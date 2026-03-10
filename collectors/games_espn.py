"""Collect game schedule and results from ESPN's public scoreboard API.

Primary source for game scores — reliably works from GitHub Actions cloud IPs
(unlike stats.nba.com and Basketball-Reference which block datacenter traffic).

Uses the ESPN scoreboard endpoint:
  https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard

Provides:
  - ESPNGameCollector class for DB upserts (used by the pipeline)
  - fetch_scores_for_grading()  for scripts/grade_picks.py
  - fetch_single_game_score()   for scripts/inject_pick.py
"""

import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

import pandas as pd

from db.connection import read_query, execute, save_dataframe, load_team_map
from config import DB_PATH
from utils.constants import ESPN_ABBR_MAP

logger = logging.getLogger(__name__)


def _normalize_abbr(espn_abbr: str) -> str:
    """Convert ESPN team abbreviation to standard 3-letter NBA abbreviation."""
    return ESPN_ABBR_MAP.get(espn_abbr, espn_abbr)


def _fetch_espn_day(date: datetime) -> list[dict]:
    """Fetch all completed games for a single date from ESPN. No DB needed.

    Returns list of dicts with keys:
        game_date, home_abbr, away_abbr, home_score, away_score
    """
    date_str = date.strftime("%Y%m%d")
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
        f"/scoreboard?dates={date_str}"
    )
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; NBASIM/1.0)",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, Exception) as e:
        logger.warning(f"ESPN fetch failed for {date_str}: {e}")
        return []

    games = []
    for event in data.get("events", []):
        competition = event.get("competitions", [{}])[0]
        status = competition.get("status", {}).get("type", {})

        if not status.get("completed", False):
            continue

        competitors = competition.get("competitors", [])
        home = away = None
        for team_entry in competitors:
            if team_entry.get("homeAway") == "home":
                home = team_entry
            else:
                away = team_entry

        if not home or not away:
            continue

        game_date = date.strftime("%Y-%m-%d")
        home_abbr = _normalize_abbr(home["team"]["abbreviation"])
        away_abbr = _normalize_abbr(away["team"]["abbreviation"])

        games.append({
            "game_date": game_date,
            "home_abbr": home_abbr,
            "away_abbr": away_abbr,
            "home_score": int(home.get("score", 0)),
            "away_score": int(away.get("score", 0)),
        })

    return games


# ── Standalone convenience functions (no DB, no class needed) ────────


def fetch_scores_for_grading(days: int = 7) -> dict:
    """Fetch recent scores keyed by matchup string for pick grading.

    Returns: {"AWAY @ HOME": {home_abbr, away_abbr, home_score, away_score}, ...}
    Used by: scripts/grade_picks.py
    """
    today = datetime.now(timezone.utc)
    scores = {}

    for day_offset in range(days):
        date = today - timedelta(days=day_offset)
        for game in _fetch_espn_day(date):
            key = f"{game['away_abbr']} @ {game['home_abbr']}"
            scores[key] = {
                "home_abbr": game["home_abbr"],
                "away_abbr": game["away_abbr"],
                "home_score": game["home_score"],
                "away_score": game["away_score"],
            }

    logger.info(f"ESPN: found {len(scores)} completed games (last {days} days)")
    return scores


def fetch_single_game_score(matchup: str, date_str: str) -> dict | None:
    """Fetch the final score for one specific game.

    Args:
        matchup: "AWAY @ HOME" format, e.g. "BOS @ CLE"
        date_str: "YYYY-MM-DD"

    Returns: {home_score, away_score, status: "final"} or None
    Used by: scripts/inject_pick.py
    """
    date = datetime.strptime(date_str, "%Y-%m-%d")
    away_team, home_team = matchup.split(" @ ")

    for game in _fetch_espn_day(date):
        if game["home_abbr"] == home_team and game["away_abbr"] == away_team:
            return {
                "home_score": game["home_score"],
                "away_score": game["away_score"],
                "status": "final",
            }

    # Game not found or not completed — check if it exists but isn't final
    date_fmt = date_str.replace("-", "")
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
        f"/scoreboard?dates={date_fmt}"
    )
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; NBASIM/1.0)",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, Exception):
        return None

    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])
        home = away = None
        for c in competitors:
            if c.get("homeAway") == "home":
                home = c
            else:
                away = c
        if not home or not away:
            continue
        h_abbr = _normalize_abbr(home["team"]["abbreviation"])
        a_abbr = _normalize_abbr(away["team"]["abbreviation"])
        if h_abbr == home_team and a_abbr == away_team:
            status_name = comp.get("status", {}).get("type", {}).get("name", "unknown")
            return {"status": status_name}

    return None


# ── Class for pipeline DB operations ────────────────────────────────


class ESPNGameCollector:
    """Fetch game results from ESPN and upsert into the games table."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def fetch_date(self, date: datetime) -> list[dict]:
        """Fetch all completed games for a single date from ESPN."""
        return _fetch_espn_day(date)

    def fetch_range(self, start_date: datetime, end_date: datetime) -> list[dict]:
        """Fetch completed games for a date range (inclusive)."""
        all_games = []
        current = start_date
        while current <= end_date:
            games = self.fetch_date(current)
            if games:
                logger.info(f"  {current.strftime('%Y-%m-%d')}: {len(games)} games")
            all_games.extend(games)
            current += timedelta(days=1)

        logger.info(f"ESPN: fetched {len(all_games)} completed games total")
        return all_games

    def fetch_recent(self, days: int = 7) -> list[dict]:
        """Fetch completed games for the last N days."""
        today = datetime.now(timezone.utc)
        start = today - timedelta(days=days - 1)
        return self.fetch_range(start, today)

    def update_games_table(self, season_id: str, days: int = 21) -> int:
        """Upsert recent games into the DB. Returns count of new/updated games.

        Args:
            season_id: e.g. '2025-26'
            days: How many days back to look (default 21 = 3 weeks)
        """
        team_map = load_team_map(self.db_path)
        scraped = self.fetch_recent(days)

        if not scraped:
            logger.warning("ESPN returned zero completed games")
            return 0

        # Load existing games for this season
        existing = read_query(
            "SELECT game_id, game_date, home_team_id, away_team_id, "
            "home_score, away_score FROM games WHERE season_id = ?",
            self.db_path, [season_id],
        )
        existing_lookup = {}
        for _, row in existing.iterrows():
            key = (row["game_date"], int(row["home_team_id"]),
                   int(row["away_team_id"]))
            existing_lookup[key] = {
                "game_id": row["game_id"],
                "home_score": row["home_score"],
                "away_score": row["away_score"],
            }

        new_games = []
        updated = 0
        skipped_teams = set()

        for game in scraped:
            home_id = team_map.get(game["home_abbr"])
            away_id = team_map.get(game["away_abbr"])

            if not home_id or not away_id:
                missing = []
                if not home_id:
                    missing.append(game["home_abbr"])
                if not away_id:
                    missing.append(game["away_abbr"])
                skipped_teams.update(missing)
                continue

            key = (game["game_date"], home_id, away_id)

            if key in existing_lookup:
                rec = existing_lookup[key]
                # Update scores if they were NULL
                if pd.isna(rec["home_score"]) or pd.isna(rec["away_score"]):
                    execute(
                        "UPDATE games SET home_score = ?, away_score = ? "
                        "WHERE game_id = ?",
                        self.db_path,
                        [game["home_score"], game["away_score"],
                         rec["game_id"]],
                    )
                    updated += 1
            else:
                # New game — generate synthetic ID
                game_id = (
                    f"espn_{game['game_date'].replace('-', '')}"
                    f"_{game['away_abbr']}_{game['home_abbr']}"
                )
                new_games.append({
                    "game_id": game_id,
                    "season_id": season_id,
                    "game_date": game["game_date"],
                    "home_team_id": home_id,
                    "away_team_id": away_id,
                    "home_score": game["home_score"],
                    "away_score": game["away_score"],
                })

        if skipped_teams:
            logger.warning(
                f"Skipped games with unknown teams: {skipped_teams}"
            )

        # Insert new games
        if new_games:
            df = pd.DataFrame(new_games)
            save_dataframe(df, "games", self.db_path, if_exists="append")

        total = len(new_games) + updated
        logger.info(
            f"ESPN games update: {len(new_games)} inserted, "
            f"{updated} scores updated, "
            f"{len(scraped) - len(new_games) - updated} already current"
        )
        return total

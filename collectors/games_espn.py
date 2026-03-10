"""Collect game schedule and results from ESPN's public scoreboard API.

Primary source for game scores — reliably works from GitHub Actions cloud IPs
(unlike stats.nba.com and Basketball-Reference which block datacenter traffic).

Uses the same endpoint that grade_picks.py has been successfully using:
  https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard

Upserts into the games table without deleting existing rows.
"""

import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

import pandas as pd

from db.connection import read_query, execute, save_dataframe
from config import DB_PATH

logger = logging.getLogger(__name__)

# ESPN uses slightly different abbreviations than the standard NBA ones
ESPN_ABBR_MAP = {
    "GS": "GSW", "SA": "SAS", "NO": "NOP", "NY": "NYK",
    "UTAH": "UTA", "WSH": "WAS",
}


def _normalize_abbr(espn_abbr: str) -> str:
    return ESPN_ABBR_MAP.get(espn_abbr, espn_abbr)


class ESPNGameCollector:
    """Fetch game results from ESPN's public scoreboard API."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def _load_team_maps(self) -> dict:
        """Build abbreviation -> team_id mapping from the teams table."""
        teams = read_query(
            "SELECT team_id, abbreviation FROM teams", self.db_path
        )
        return {row["abbreviation"]: int(row["team_id"])
                for _, row in teams.iterrows()}

    def fetch_date(self, date: datetime) -> list[dict]:
        """Fetch all completed games for a single date from ESPN."""
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
        team_map = self._load_team_maps()
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

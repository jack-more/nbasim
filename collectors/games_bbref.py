"""Collect game schedule and results from Basketball-Reference.com.

Fallback/primary source when stats.nba.com blocks cloud IPs (GitHub Actions).
Scrapes the schedule pages and upserts into the games table without deleting
existing rows (preserves NBA API game_ids for BoxScoreCollector compatibility).
"""

import logging
import time
from datetime import datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup

from db.connection import read_query, execute, save_dataframe
from config import DB_PATH

logger = logging.getLogger(__name__)

# Basketball-Reference uses slightly different abbreviations
BBREF_TO_NBA = {
    "BRK": "BKN",
    "CHO": "CHA",
    "PHO": "PHX",
}

SCHEDULE_MONTHS = [
    "october", "november", "december", "january",
    "february", "march", "april",
]

REQUEST_DELAY = 3.0  # seconds between page requests


class BRefGameCollector:
    """Scrape game results from Basketball-Reference schedule pages."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        })

    def _load_team_maps(self):
        """Build abbreviation -> team_id mapping from the teams table."""
        teams = read_query(
            "SELECT team_id, abbreviation FROM teams", self.db_path
        )
        return {row["abbreviation"]: int(row["team_id"])
                for _, row in teams.iterrows()}

    def _normalize_abbr(self, bbref_abbr: str) -> str:
        """Convert Basketball-Reference abbreviation to NBA standard."""
        return BBREF_TO_NBA.get(bbref_abbr, bbref_abbr)

    def _scrape_month(self, season_end_year: int, month: str) -> list[dict]:
        """Scrape one month's schedule page. Returns list of game dicts."""
        url = (
            f"https://www.basketball-reference.com/leagues/"
            f"NBA_{season_end_year}_games-{month}.html"
        )
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 404:
                logger.debug(f"No schedule page for {month} (404)")
                return []
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch {month} schedule: {e}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", id="schedule")
        if not table:
            logger.debug(f"No schedule table found for {month}")
            return []

        tbody = table.find("tbody")
        if not tbody:
            return []

        games = []
        for row in tbody.find_all("tr"):
            # Skip header rows that appear mid-table
            if row.find("th", {"data-stat": "date_game", "class": "thead"}):
                continue

            cells = {
                tag.get("data-stat"): tag
                for tag in row.find_all(["td", "th"])
            }

            # Skip future games (no scores yet)
            visitor_pts_cell = cells.get("visitor_pts")
            if not visitor_pts_cell or not visitor_pts_cell.text.strip():
                continue

            home_pts_cell = cells.get("home_pts")
            if not home_pts_cell or not home_pts_cell.text.strip():
                continue

            # Extract team abbreviations from links
            visitor_cell = cells.get("visitor_team_name")
            home_cell = cells.get("home_team_name")
            if not visitor_cell or not home_cell:
                continue

            visitor_link = visitor_cell.find("a")
            home_link = home_cell.find("a")
            if not visitor_link or not home_link:
                continue

            # /teams/SAS/2026.html -> SAS
            visitor_abbr = visitor_link["href"].split("/")[2]
            home_abbr = home_link["href"].split("/")[2]

            # Parse date
            date_cell = cells.get("date_game")
            if not date_cell:
                continue
            date_text = date_cell.text.strip()
            try:
                game_date = datetime.strptime(date_text, "%a, %b %d, %Y")
                game_date_str = game_date.strftime("%Y-%m-%d")
            except ValueError:
                logger.warning(f"Could not parse date: {date_text}")
                continue

            games.append({
                "game_date": game_date_str,
                "away_abbr": self._normalize_abbr(visitor_abbr),
                "home_abbr": self._normalize_abbr(home_abbr),
                "away_score": int(visitor_pts_cell.text.strip()),
                "home_score": int(home_pts_cell.text.strip()),
            })

        logger.info(f"  {month}: {len(games)} completed games")
        return games

    def scrape_all_games(self, season_id: str) -> list[dict]:
        """Scrape all completed games for a season from Basketball-Reference."""
        # season_id format: "2025-26" -> end year 2026
        end_year = int("20" + season_id.split("-")[1])

        logger.info(
            f"=== Scraping Basketball-Reference for {season_id} season ==="
        )

        all_games = []
        for month in SCHEDULE_MONTHS:
            games = self._scrape_month(end_year, month)
            all_games.extend(games)
            if games:
                time.sleep(REQUEST_DELAY)

        logger.info(f"Total completed games scraped: {len(all_games)}")
        return all_games

    def update_games_table(self, season_id: str) -> int:
        """Upsert scraped games into the DB. Returns count of new/updated games."""
        team_map = self._load_team_maps()
        scraped = self.scrape_all_games(season_id)

        if not scraped:
            raise RuntimeError("Basketball-Reference returned zero games")

        # Load existing games
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
                    f"br_{game['game_date'].replace('-', '')}"
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
            f"Games update: {len(new_games)} inserted, "
            f"{updated} scores updated, "
            f"{len(scraped) - len(new_games) - updated} already current"
        )
        return total

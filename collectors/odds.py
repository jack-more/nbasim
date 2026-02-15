"""Collect betting lines from The Odds API."""

import logging
from datetime import datetime

import requests
import pandas as pd

from db.connection import save_dataframe

logger = logging.getLogger(__name__)


class OddsCollector:
    """
    Collects betting lines from The Odds API.
    Free tier: 500 requests/month, no credit card required.
    Sign up at https://the-odds-api.com
    """

    def __init__(self, api_key: str, db_path: str):
        self.api_key = api_key
        self.db_path = db_path
        self.base_url = "https://api.the-odds-api.com/v4"

    def collect_current_odds(self):
        """Collect current NBA odds (spreads + totals). 1 API credit."""
        if not self.api_key:
            logger.warning("No ODDS_API_KEY set. Skipping odds collection.")
            return

        url = f"{self.base_url}/sports/basketball_nba/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "us",
            "markets": "spreads,totals",
            "oddsFormat": "american",
        }

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch odds: {e}")
            return

        now = datetime.utcnow().isoformat()
        rows = []

        for game in data:
            # Try to match to our game_id by date + teams
            # For now, use the odds API's own game ID as a reference
            game_ref = game.get("id", "")
            home_team = game.get("home_team", "")
            away_team = game.get("away_team", "")
            commence = game.get("commence_time", "")

            for bookmaker in game.get("bookmakers", []):
                bk_name = bookmaker.get("key", "")
                for market in bookmaker.get("markets", []):
                    market_type = market.get("key", "")
                    for outcome in market.get("outcomes", []):
                        rows.append({
                            "game_id": game_ref,
                            "bookmaker": bk_name,
                            "market_type": market_type,
                            "outcome_name": outcome.get("name", ""),
                            "price": outcome.get("price"),
                            "point": outcome.get("point"),
                            "retrieved_at": now,
                        })

        if rows:
            df = pd.DataFrame(rows)
            save_dataframe(df, "betting_lines", self.db_path)
            logger.info(f"Saved {len(rows)} betting line rows")
        else:
            logger.info("No current odds available")

        # Log remaining API credits
        remaining = resp.headers.get("x-requests-remaining", "?")
        logger.info(f"Odds API requests remaining: {remaining}")

    def get_consensus_line(self, game_id: str) -> dict:
        """Average spread and total across bookmakers for a game."""
        from db.connection import read_query
        df = read_query(
            """SELECT market_type, AVG(point) as avg_point
               FROM betting_lines
               WHERE game_id = ? AND point IS NOT NULL
               GROUP BY market_type""",
            self.db_path, [game_id]
        )
        result = {"spread": None, "total": None}
        for _, row in df.iterrows():
            if row["market_type"] == "spreads":
                result["spread"] = row["avg_point"]
            elif row["market_type"] == "totals":
                result["total"] = row["avg_point"]
        return result

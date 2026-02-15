"""Collect game schedule and results."""

import logging
import pandas as pd
from nba_api.stats.endpoints import LeagueGameFinder

from collectors.base import BaseCollector
from db.connection import execute

logger = logging.getLogger(__name__)


class GameCollector(BaseCollector):

    def collect_for_season(self, season: str):
        """Collect all games for a season. ~1 API call."""
        logger.info(f"=== Collecting games for {season} ===")

        dfs = self._call_endpoint(
            LeagueGameFinder,
            season_nullable=season,
            league_id_nullable="00",
            season_type_nullable="Regular Season",
        )
        raw = dfs[0]

        if raw.empty:
            logger.warning(f"No games found for {season}")
            return

        # Each game appears twice (once per team). Group by GAME_ID.
        games = {}
        for _, row in raw.iterrows():
            gid = row["GAME_ID"]
            if gid not in games:
                games[gid] = {
                    "game_id": gid,
                    "season_id": season,
                    "game_date": row["GAME_DATE"],
                }

            matchup = str(row.get("MATCHUP", ""))
            team_id = int(row["TEAM_ID"])
            pts = row.get("PTS")

            if " vs. " in matchup:
                # Home team
                games[gid]["home_team_id"] = team_id
                games[gid]["home_score"] = int(pts) if pd.notna(pts) else None
            elif " @ " in matchup:
                # Away team
                games[gid]["away_team_id"] = team_id
                games[gid]["away_score"] = int(pts) if pd.notna(pts) else None

        # Filter to complete games (have both teams)
        complete = [
            g for g in games.values()
            if "home_team_id" in g and "away_team_id" in g
        ]

        df = pd.DataFrame(complete)
        execute("DELETE FROM games WHERE season_id = ?", self.db_path, [season])
        self._save(df, "games")
        logger.info(f"Saved {len(df)} games for {season}")

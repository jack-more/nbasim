"""Collect team and player play type distributions."""

import logging
import pandas as pd
from nba_api.stats.endpoints import SynergyPlayTypes

from collectors.base import BaseCollector
from db.connection import execute
from utils.constants import PLAY_TYPES, TYPE_GROUPINGS

logger = logging.getLogger(__name__)


class PlayTypeCollector(BaseCollector):

    def collect_team_playtypes(self, season: str):
        """Collect play type data for all teams. ~22 API calls."""
        logger.info(f"  Collecting team play types for {season}")
        all_rows = []

        for play_type in PLAY_TYPES:
            for grouping in TYPE_GROUPINGS:
                try:
                    dfs = self._call_endpoint(
                        SynergyPlayTypes,
                        league_id="00",
                        per_mode_simple="PerGame",
                        player_or_team_abbreviation="T",
                        season_type_all_star="Regular Season",
                        season=season,
                        play_type_nullable=play_type,
                        type_grouping_nullable=grouping,
                    )
                    raw = dfs[0]

                    if raw.empty:
                        continue

                    for _, row in raw.iterrows():
                        all_rows.append({
                            "team_id": int(row.get("TEAM_ID", 0)),
                            "season_id": season,
                            "play_type": play_type,
                            "type_grouping": grouping,
                            "poss_pct": row.get("POSS_PCT", 0),
                            "ppp": row.get("PPP", 0),
                            "fg_pct": row.get("FG_PCT", 0),
                            "efg_pct": row.get("EFG_PCT", 0),
                            "tov_pct": row.get("TOV_PCT", 0),
                            "score_pct": row.get("SCORE_PCT", 0),
                            "foul_pct": row.get("PERCENTILE", 0),
                            "possessions": row.get("POSS", 0),
                        })
                except Exception as e:
                    logger.warning(
                        f"    Failed: {play_type}/{grouping}: {e}"
                    )

        if all_rows:
            df = pd.DataFrame(all_rows)
            execute(
                "DELETE FROM team_playtypes WHERE season_id = ?",
                self.db_path, [season]
            )
            self._save(df, "team_playtypes")
            logger.info(f"  Saved {len(df)} team play type rows for {season}")

    def collect_player_playtypes(self, season: str):
        """Collect play type data for all players. ~22 API calls."""
        logger.info(f"  Collecting player play types for {season}")
        all_rows = []

        for play_type in PLAY_TYPES:
            for grouping in TYPE_GROUPINGS:
                try:
                    dfs = self._call_endpoint(
                        SynergyPlayTypes,
                        league_id="00",
                        per_mode_simple="PerGame",
                        player_or_team_abbreviation="P",
                        season_type_all_star="Regular Season",
                        season=season,
                        play_type_nullable=play_type,
                        type_grouping_nullable=grouping,
                    )
                    raw = dfs[0]

                    if raw.empty:
                        continue

                    for _, row in raw.iterrows():
                        all_rows.append({
                            "player_id": int(row.get("PLAYER_ID", 0)),
                            "team_id": int(row.get("TEAM_ID", 0)),
                            "season_id": season,
                            "play_type": play_type,
                            "type_grouping": grouping,
                            "poss_pct": row.get("POSS_PCT", 0),
                            "ppp": row.get("PPP", 0),
                            "fg_pct": row.get("FG_PCT", 0),
                            "efg_pct": row.get("EFG_PCT", 0),
                            "tov_pct": row.get("TOV_PCT", 0),
                            "score_pct": row.get("SCORE_PCT", 0),
                            "possessions": row.get("POSS", 0),
                        })
                except Exception as e:
                    logger.warning(
                        f"    Failed: {play_type}/{grouping}: {e}"
                    )

        if all_rows:
            df = pd.DataFrame(all_rows)
            execute(
                "DELETE FROM player_playtypes WHERE season_id = ?",
                self.db_path, [season]
            )
            self._save(df, "player_playtypes")
            logger.info(f"  Saved {len(df)} player play type rows for {season}")

    def collect_for_season(self, season: str):
        """Collect all play type data for a season. ~44 API calls."""
        logger.info(f"=== Collecting play types for {season} ===")
        self.collect_team_playtypes(season)
        self.collect_player_playtypes(season)

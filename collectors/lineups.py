"""Collect 2/3/4/5-man lineup combination stats."""

import json
import logging
import pandas as pd
from nba_api.stats.endpoints import LeagueDashLineups

from collectors.base import BaseCollector
from db.connection import execute, read_query

logger = logging.getLogger(__name__)


class LineupCollector(BaseCollector):

    def collect_lineups(self, season: str, group_quantity: int):
        """Collect lineup stats for a specific group size. 1 API call."""
        logger.info(f"  Collecting {group_quantity}-man lineups for {season}")

        dfs = self._call_endpoint(
            LeagueDashLineups,
            season=season,
            group_quantity=str(group_quantity),
            per_mode_detailed="PerGame",
            measure_type_detailed_defense="Base",
            season_type_all_star="Regular Season",
            timeout=120,
        )
        raw = dfs[0]

        if raw.empty:
            logger.warning(f"No {group_quantity}-man lineups found for {season}")
            return

        # Get team pace data for possession estimation
        pace_map = {}
        try:
            pace_df = read_query(
                "SELECT team_id, pace FROM team_season_stats WHERE season_id = ?",
                self.db_path, [season]
            )
            pace_map = dict(zip(pace_df["team_id"].astype(int), pace_df["pace"]))
        except Exception:
            pass

        lineup_rows = []
        player_rows = []

        for _, row in raw.iterrows():
            group_id = str(row.get("GROUP_ID", ""))
            team_id = int(row.get("TEAM_ID", 0))

            # Parse player IDs from GROUP_ID (dash-separated)
            player_ids = sorted([
                int(pid) for pid in group_id.replace(" ", "").split("-")
                if pid.strip()
            ])
            player_ids_json = json.dumps(player_ids)

            # Estimate possessions from minutes and pace
            minutes = row.get("MIN", 0) or 0
            team_pace = pace_map.get(team_id, 100.0)  # default 100 if unknown
            possessions = (minutes / 48.0) * team_pace if minutes > 0 else 0

            # Compute fg3a_rate
            fga = row.get("FGA", 0) or 1
            fg3a_rate = (row.get("FG3A", 0) or 0) / fga if fga > 0 else 0

            lineup_rows.append({
                "lineup_id": group_id,
                "team_id": team_id,
                "season_id": season,
                "group_quantity": group_quantity,
                "player_ids": player_ids_json,
                "gp": row.get("GP", 0),
                "minutes": minutes,
                "possessions": possessions,
                "off_rating": None,  # Base mode doesn't include ratings
                "def_rating": None,
                "net_rating": None,
                "fg_pct": row.get("FG_PCT", 0),
                "fg3_pct": row.get("FG3_PCT", 0),
                "ft_pct": row.get("FT_PCT", 0),
                "fg3a_rate": fg3a_rate,
                "fgm": row.get("FGM", 0),
                "fga": row.get("FGA", 0),
                "fg3m": row.get("FG3M", 0),
                "fg3a": row.get("FG3A", 0),
                "ftm": row.get("FTM", 0),
                "fta": row.get("FTA", 0),
                "plus_minus": row.get("PLUS_MINUS", 0),
            })

            # Junction table entries
            for pid in player_ids:
                player_rows.append({
                    "lineup_id": group_id,
                    "season_id": season,
                    "player_id": pid,
                })

        # Try to get advanced stats too (for net rating)
        try:
            adv_dfs = self._call_endpoint(
                LeagueDashLineups,
                season=season,
                group_quantity=str(group_quantity),
                per_mode_detailed="PerGame",
                measure_type_detailed_defense="Advanced",
                season_type_all_star="Regular Season",
                timeout=120,
            )
            adv = adv_dfs[0]
            if not adv.empty:
                adv_map = {}
                for _, a in adv.iterrows():
                    gid = str(a.get("GROUP_ID", ""))
                    adv_map[gid] = {
                        "off_rating": a.get("OFF_RATING"),
                        "def_rating": a.get("DEF_RATING"),
                        "net_rating": a.get("NET_RATING"),
                    }
                for lr in lineup_rows:
                    if lr["lineup_id"] in adv_map:
                        lr.update(adv_map[lr["lineup_id"]])
        except Exception as e:
            logger.warning(f"Could not get advanced lineup stats: {e}")

        # Save (deduplicate by lineup_id + season_id)
        if lineup_rows:
            df = pd.DataFrame(lineup_rows)
            df = df.drop_duplicates(subset=["lineup_id", "season_id"], keep="first")
            execute(
                "DELETE FROM lineup_stats WHERE season_id = ? AND group_quantity = ?",
                self.db_path, [season, group_quantity]
            )
            self._save(df, "lineup_stats")

        if player_rows:
            pdf = pd.DataFrame(player_rows)
            pdf = pdf.drop_duplicates(subset=["lineup_id", "season_id", "player_id"], keep="first")
            execute(
                "DELETE FROM lineup_players WHERE season_id = ? AND lineup_id IN "
                "(SELECT lineup_id FROM lineup_stats WHERE season_id = ? AND group_quantity = ?)",
                self.db_path, [season, season, group_quantity]
            )
            self._save(pdf, "lineup_players")

        logger.info(
            f"  Saved {len(lineup_rows)} {group_quantity}-man lineups for {season}"
        )

    def collect_for_season(self, season: str):
        """Collect 2, 3, 4, and 5-man lineups. ~8 API calls per season."""
        logger.info(f"=== Collecting lineups for {season} ===")
        for n in [5, 4, 3, 2]:
            self.collect_lineups(season, n)

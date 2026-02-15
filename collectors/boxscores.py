"""Collect per-game box scores with checkpoint/resume support."""

import logging
import pandas as pd
from nba_api.stats.endpoints import BoxScoreTraditionalV3, BoxScoreAdvancedV3

from collectors.base import BaseCollector
from db.connection import read_query, execute

logger = logging.getLogger(__name__)


class BoxScoreCollector(BaseCollector):

    def _get_collected_game_ids(self) -> set:
        """Get game_ids already in player_game_stats."""
        try:
            df = read_query(
                "SELECT DISTINCT game_id FROM player_game_stats",
                self.db_path
            )
            return set(df["game_id"].tolist())
        except Exception:
            return set()

    def collect_game_boxscore(self, game_id: str):
        """Collect box score for a single game. ~2 API calls."""
        # Traditional stats
        trad_dfs = self._call_endpoint(
            BoxScoreTraditionalV3,
            game_id=game_id,
        )
        # V3 returns multiple DataFrames; player stats is typically index 0
        trad = trad_dfs[0] if trad_dfs else pd.DataFrame()

        if trad.empty:
            logger.warning(f"  No traditional box score for {game_id}")
            return

        # Advanced stats
        try:
            adv_dfs = self._call_endpoint(
                BoxScoreAdvancedV3,
                game_id=game_id,
            )
            adv = adv_dfs[0] if adv_dfs else pd.DataFrame()
        except Exception as e:
            logger.warning(f"  No advanced box score for {game_id}: {e}")
            adv = pd.DataFrame()

        # Build advanced lookup
        adv_map = {}
        if not adv.empty:
            pid_col = "personId" if "personId" in adv.columns else "PLAYER_ID"
            for _, a in adv.iterrows():
                adv_map[int(a[pid_col])] = a

        # Parse traditional stats
        rows = []
        pid_col = "personId" if "personId" in trad.columns else "PLAYER_ID"
        tid_col = "teamId" if "teamId" in trad.columns else "TEAM_ID"

        for _, t in trad.iterrows():
            player_id = int(t[pid_col])
            team_id = int(t[tid_col])

            # Parse minutes
            minutes = 0.0
            min_val = t.get("minutes", t.get("MIN", ""))
            if pd.notna(min_val) and min_val:
                min_str = str(min_val)
                if ":" in min_str:
                    parts = min_str.split(":")
                    try:
                        minutes = int(parts[0]) + int(parts[1]) / 60.0
                    except ValueError:
                        pass
                elif "PT" in min_str:
                    # ISO 8601 duration format: PT32M15.00S
                    try:
                        min_str = min_str.replace("PT", "").replace("S", "")
                        if "M" in min_str:
                            m, s = min_str.split("M")
                            minutes = float(m) + float(s) / 60.0
                        else:
                            minutes = float(min_str) / 60.0
                    except ValueError:
                        pass
                else:
                    try:
                        minutes = float(min_str)
                    except ValueError:
                        pass

            row = {
                "game_id": game_id,
                "player_id": player_id,
                "team_id": team_id,
                "minutes": minutes,
                "started": 1 if str(t.get("status", t.get("START_POSITION", ""))) else 0,
                "pts": _safe_int(t, "points", "PTS"),
                "reb": _safe_int(t, "reboundsTotal", "REB"),
                "ast": _safe_int(t, "assists", "AST"),
                "stl": _safe_int(t, "steals", "STL"),
                "blk": _safe_int(t, "blocks", "BLK"),
                "tov": _safe_int(t, "turnovers", "TOV"),
                "fgm": _safe_int(t, "fieldGoalsMade", "FGM"),
                "fga": _safe_int(t, "fieldGoalsAttempted", "FGA"),
                "fg3m": _safe_int(t, "threePointersMade", "FG3M"),
                "fg3a": _safe_int(t, "threePointersAttempted", "FG3A"),
                "ftm": _safe_int(t, "freeThrowsMade", "FTM"),
                "fta": _safe_int(t, "freeThrowsAttempted", "FTA"),
                "oreb": _safe_int(t, "reboundsOffensive", "OREB"),
                "dreb": _safe_int(t, "reboundsDefensive", "DREB"),
                "pf": _safe_int(t, "foulsPersonal", "PF"),
                "plus_minus": _safe_float(t, "plusMinusPoints", "PLUS_MINUS"),
            }

            # Add advanced stats
            if player_id in adv_map:
                a = adv_map[player_id]
                row.update({
                    "off_rating": _safe_float(a, "offensiveRating", "OFF_RATING"),
                    "def_rating": _safe_float(a, "defensiveRating", "DEF_RATING"),
                    "net_rating": _safe_float(a, "netRating", "NET_RATING"),
                    "ast_pct": _safe_float(a, "assistPercentage", "AST_PCT"),
                    "reb_pct": _safe_float(a, "reboundPercentage", "REB_PCT"),
                    "usg_pct": _safe_float(a, "usagePercentage", "USG_PCT"),
                    "ts_pct": _safe_float(a, "trueShootingPercentage", "TS_PCT"),
                    "efg_pct": _safe_float(a, "effectiveFieldGoalPercentage", "EFG_PCT"),
                    "pace": _safe_float(a, "pace", "PACE"),
                    "pie": _safe_float(a, "pie", "PIE"),
                })
            else:
                row.update({
                    "off_rating": None, "def_rating": None, "net_rating": None,
                    "ast_pct": None, "reb_pct": None, "usg_pct": None,
                    "ts_pct": None, "efg_pct": None, "pace": None, "pie": None,
                })

            rows.append(row)

        if rows:
            df = pd.DataFrame(rows)
            self._save(df, "player_game_stats")

    def collect_for_season(self, season: str):
        """Collect box scores for all games in a season with checkpointing."""
        logger.info(f"=== Collecting box scores for {season} ===")

        # Get all game IDs for the season
        games_df = read_query(
            "SELECT game_id FROM games WHERE season_id = ? ORDER BY game_date",
            self.db_path, [season]
        )
        all_game_ids = games_df["game_id"].tolist()

        # Get already-collected game IDs (checkpoint)
        collected = self._get_collected_game_ids()
        remaining = [gid for gid in all_game_ids if gid not in collected]

        logger.info(
            f"  {len(all_game_ids)} total games, "
            f"{len(collected)} already collected, "
            f"{len(remaining)} remaining"
        )

        for i, game_id in enumerate(remaining):
            try:
                self.collect_game_boxscore(game_id)
                if (i + 1) % 50 == 0:
                    logger.info(
                        f"  Progress: {i + 1}/{len(remaining)} box scores collected"
                    )
            except Exception as e:
                logger.error(f"  Failed box score for {game_id}: {e}")

        logger.info(f"Box score collection complete for {season}")


def _safe_int(row, *keys):
    """Get an integer value, trying multiple column names."""
    for key in keys:
        val = row.get(key)
        if pd.notna(val):
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
    return 0


def _safe_float(row, *keys):
    """Get a float value, trying multiple column names."""
    for key in keys:
        val = row.get(key)
        if pd.notna(val):
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
    return None

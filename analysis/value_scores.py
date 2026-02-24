"""Composite player value scores blending individual performance with lineup synergy."""

import json
import logging
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime

from db.connection import read_query, execute, save_dataframe
from config import (
    SYNERGY_WEIGHTS, BASE_VALUE_WEIGHT, ARCHETYPE_FIT_WEIGHT,
    PRIOR_STRENGTH, MIN_MINUTES_SOLO,
)
from utils.stats_math import (
    bayesian_shrinkage, normalize_to_scale, possession_weighted_average,
)

logger = logging.getLogger(__name__)


def _compute_ds(row) -> float:
    """Compute Dynamic Score for a player row (same formula as generate_frontend.py)."""
    pts = float(row.get("pts_pg", 0) or 0)
    ast = float(row.get("ast_pg", 0) or 0)
    reb = float(row.get("reb_pg", 0) or 0)
    stl = float(row.get("stl_pg", 0) or 0)
    blk = float(row.get("blk_pg", 0) or 0)
    ts = float(row.get("ts_pct", 0) or 0)
    usg = float(row.get("usg_pct", 0) or 0)
    nrtg = float(row.get("net_rating", 0) or 0)
    mpg = float(row.get("minutes_per_game", 0) or 0)
    drtg = float(row.get("def_rating", 111.7) or 111.7)

    # Offense
    scoring_c = pts * 1.2
    playmaking_c = ast * 1.8
    efficiency_c = ts * 40
    usage_c = usg * 15
    off_raw = scoring_c + playmaking_c + efficiency_c + usage_c
    off_score = min(99, max(0, off_raw / 0.85))

    # Defense
    stocks_c = stl * 8.0 + blk * 6.0
    drtg_c = max(0, (115 - drtg) * 2.5)
    def_raw = stocks_c + drtg_c
    def_score = min(99, max(0, def_raw / 0.5))

    # Shared
    rebounding_c = reb * 0.8
    impact_c = nrtg * 0.8
    minutes_c = mpg * 0.3
    shared_raw = rebounding_c + impact_c + minutes_c

    blended = 0.75 * off_score + 0.25 * def_score + shared_raw
    return min(99, max(33, int(blended / 1.1)))


class ValueScoreCalculator:

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_league_mean_nrtg(self, season: str) -> float:
        df = read_query(
            "SELECT AVG(net_rating) as m FROM team_season_stats WHERE season_id = ?",
            self.db_path, [season]
        )
        return float(df.iloc[0]["m"]) if not df.empty and df.iloc[0]["m"] is not None else 0.0

    def _get_players(self, season: str) -> pd.DataFrame:
        """Get all players with sufficient minutes."""
        return read_query("""
            SELECT ps.player_id, ps.team_id, ps.pts_pg, ps.ast_pg, ps.reb_pg,
                   ps.stl_pg, ps.blk_pg, ps.ts_pct, ps.net_rating, ps.usg_pct,
                   ps.minutes_per_game, ps.def_rating, ps.minutes_total
            FROM player_season_stats ps
            WHERE ps.season_id = ? AND ps.minutes_per_game > 5
        """, self.db_path, [season])

    def _compute_base_values(self, players: pd.DataFrame) -> dict:
        """Compute base DS for each player."""
        result = {}
        for _, row in players.iterrows():
            result[int(row["player_id"])] = _compute_ds(row)
        return result

    def _compute_solo_impact(self, players: pd.DataFrame, season: str) -> dict:
        """WOWY solo impact: team margin WITH player vs WITHOUT."""
        result = {}

        for _, row in players.iterrows():
            pid = int(row["player_id"])
            tid = int(row["team_id"])
            minutes_total = float(row.get("minutes_total", 0) or 0)

            # Games where player played >= 15 min
            with_df = read_query("""
                SELECT pgs.plus_minus
                FROM player_game_stats pgs
                JOIN games g ON pgs.game_id = g.game_id
                WHERE pgs.player_id = ? AND g.season_id = ? AND pgs.minutes >= 15
            """, self.db_path, [pid, season])

            # Team games where player did NOT play (or < 15 min)
            without_df = read_query("""
                SELECT pgs2.plus_minus
                FROM player_game_stats pgs2
                JOIN games g ON pgs2.game_id = g.game_id
                WHERE pgs2.team_id = ? AND g.season_id = ? AND pgs2.minutes >= 15
                    AND pgs2.game_id NOT IN (
                        SELECT game_id FROM player_game_stats
                        WHERE player_id = ? AND minutes >= 15
                    )
                    AND pgs2.player_id != ?
            """, self.db_path, [tid, season, pid, pid])

            if with_df.empty:
                result[pid] = 0.0
                continue

            avg_with = float(with_df["plus_minus"].mean())

            if without_df.empty:
                # Can't compute on/off — treat as neutral
                raw_diff = 0.0
            else:
                avg_without = float(without_df["plus_minus"].mean())
                raw_diff = avg_with - avg_without

            # Bayesian shrinkage
            shrunk = bayesian_shrinkage(
                raw_diff, minutes_total,
                0.0, PRIOR_STRENGTH["solo"]  # 500
            )
            result[pid] = shrunk

        return result

    def _compute_n_man_synergy(self, season: str, n: int) -> dict:
        """Compute per-player synergy from n-man lineup data."""
        prior = PRIOR_STRENGTH[n]
        league_mean = self._get_league_mean_nrtg(season)

        lineups = read_query("""
            SELECT ls.player_ids, ls.net_rating, ls.possessions
            FROM lineup_stats ls
            WHERE ls.season_id = ? AND ls.group_quantity = ?
                  AND ls.net_rating IS NOT NULL AND ls.possessions > 0
        """, self.db_path, [season, n])

        if lineups.empty:
            return {}

        player_lineups = defaultdict(list)  # pid -> [(shrunk_nrtg, possessions)]
        for _, row in lineups.iterrows():
            pids = json.loads(row["player_ids"])
            poss = float(row["possessions"])
            shrunk = bayesian_shrinkage(
                float(row["net_rating"]), poss, league_mean, prior
            )
            for pid in pids:
                player_lineups[int(pid)].append((shrunk, poss))

        result = {}
        for pid, entries in player_lineups.items():
            nrtgs = [e[0] for e in entries]
            poss = [e[1] for e in entries]
            result[pid] = possession_weighted_average(nrtgs, poss)

        return result

    def _compute_archetype_fit(self, season: str) -> dict:
        """Per-player archetype fit: weighted average synergy_score with all partners."""
        pairs = read_query("""
            SELECT player_a_id, player_b_id, synergy_score, possessions
            FROM pair_synergy WHERE season_id = ?
        """, self.db_path, [season])

        if pairs.empty:
            return {}

        player_data = defaultdict(list)  # pid -> [(syn_score, poss)]
        for _, row in pairs.iterrows():
            poss = float(row["possessions"])
            syn = float(row["synergy_score"])
            player_data[int(row["player_a_id"])].append((syn, poss))
            player_data[int(row["player_b_id"])].append((syn, poss))

        result = {}
        for pid, entries in player_data.items():
            scores = [e[0] for e in entries]
            weights = [e[1] for e in entries]
            result[pid] = possession_weighted_average(scores, weights)

        return result

    def compute_all(self, season: str):
        """Compute composite value scores for all qualifying players."""
        logger.info(f"Computing value scores for {season}...")

        players = self._get_players(season)
        if players.empty:
            logger.warning("No qualifying players found.")
            return

        logger.info(f"  {len(players)} players qualifying")

        # Component calculations
        base_values = self._compute_base_values(players)
        logger.info(f"  Base values computed: {len(base_values)} players")

        solo_impact = self._compute_solo_impact(players, season)
        logger.info(f"  Solo impact computed: {len(solo_impact)} players")

        two_man = self._compute_n_man_synergy(season, 2)
        three_man = self._compute_n_man_synergy(season, 3)
        four_man = self._compute_n_man_synergy(season, 4)
        five_man = self._compute_n_man_synergy(season, 5)
        logger.info(f"  N-man synergy: 2man={len(two_man)} 3man={len(three_man)} "
                     f"4man={len(four_man)} 5man={len(five_man)}")

        arch_fit = self._compute_archetype_fit(season)
        logger.info(f"  Archetype fit computed: {len(arch_fit)} players")

        # Build per-player rows
        all_pids = set(base_values.keys())
        raw_rows = []
        for pid in all_pids:
            raw_rows.append({
                "player_id": pid,
                "team_id": int(players.loc[players["player_id"] == pid, "team_id"].iloc[0])
                    if pid in players["player_id"].values else 0,
                "season_id": season,
                "base_value": base_values.get(pid, 50.0),
                "solo_impact": solo_impact.get(pid, 0.0),
                "two_man_synergy": two_man.get(pid, 0.0),
                "three_man_synergy": three_man.get(pid, 0.0),
                "four_man_synergy": four_man.get(pid, 0.0),
                "five_man_synergy": five_man.get(pid, 0.0),
                "archetype_fit_score": arch_fit.get(pid, 50.0),
                "minutes_weight": float(
                    players.loc[players["player_id"] == pid, "minutes_per_game"].iloc[0]
                ) if pid in players["player_id"].values else 0.0,
            })

        df = pd.DataFrame(raw_rows)

        # Normalize each component to 0-100
        for col in ["base_value", "solo_impact", "two_man_synergy",
                     "three_man_synergy", "four_man_synergy", "five_man_synergy",
                     "archetype_fit_score"]:
            vals = df[col].values
            if len(vals) > 1 and vals.max() != vals.min():
                df[col] = np.round(normalize_to_scale(vals, 0, 100), 2)
            else:
                df[col] = 50.0

        # Composite blend
        W = SYNERGY_WEIGHTS
        df["composite_value"] = np.round(
            BASE_VALUE_WEIGHT * df["base_value"] +
            W["solo"] * df["solo_impact"] +
            W["two_man"] * df["two_man_synergy"] +
            W["three_man"] * df["three_man_synergy"] +
            W["four_man"] * df["four_man_synergy"] +
            W["five_man"] * df["five_man_synergy"] +
            ARCHETYPE_FIT_WEIGHT * df["archetype_fit_score"],
            2
        )

        df["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        # Save
        execute("DELETE FROM player_value_scores WHERE season_id = ?", self.db_path, [season])
        save_dataframe(df, "player_value_scores", self.db_path)

        # Stats
        top = df.nlargest(10, "composite_value")
        logger.info(f"  Saved {len(df)} value scores")
        logger.info(f"  Top 10 composite values:")
        for _, r in top.iterrows():
            logger.info(f"    PID {int(r['player_id'])}: composite={r['composite_value']:.1f} "
                        f"base={r['base_value']:.1f} solo={r['solo_impact']:.1f} "
                        f"2man={r['two_man_synergy']:.1f}")

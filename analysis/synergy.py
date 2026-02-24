"""Pair synergy calculation from 2-man lineup data."""

import json
import logging
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime

from db.connection import read_query, execute, save_dataframe
from config import PRIOR_STRENGTH
from utils.stats_math import bayesian_shrinkage, normalize_to_scale

logger = logging.getLogger(__name__)


class PairSynergyCalculator:

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_league_mean_nrtg(self, season: str) -> float:
        """Get league-average net rating (should be ~0.0)."""
        df = read_query(
            "SELECT AVG(net_rating) as mean_nrtg FROM team_season_stats WHERE season_id = ?",
            self.db_path, [season]
        )
        if df.empty or df.iloc[0]["mean_nrtg"] is None:
            return 0.0
        return float(df.iloc[0]["mean_nrtg"])

    def _get_two_man_lineups(self, season: str) -> pd.DataFrame:
        """Get all 2-man lineup combos with net rating data."""
        return read_query("""
            SELECT ls.lineup_id, ls.team_id, ls.player_ids, ls.net_rating,
                   ls.minutes, ls.possessions, ls.gp, ls.off_rating, ls.def_rating,
                   ls.plus_minus
            FROM lineup_stats ls
            WHERE ls.season_id = ? AND ls.group_quantity = 2
                  AND ls.net_rating IS NOT NULL AND ls.possessions > 0
        """, self.db_path, [season])

    def _get_player_archetypes(self, season: str) -> dict:
        """Get archetype labels for all players."""
        df = read_query(
            "SELECT player_id, archetype_label FROM player_archetypes WHERE season_id = ?",
            self.db_path, [season]
        )
        return dict(zip(df["player_id"].astype(int), df["archetype_label"]))

    def compute_pair_synergies(self, season: str):
        """Compute pair synergy scores from 2-man lineup data and populate pair_synergy table."""
        logger.info(f"Computing pair synergies for {season}...")

        lineups = self._get_two_man_lineups(season)
        if lineups.empty:
            logger.warning("No 2-man lineup data found. Skipping synergy computation.")
            return

        league_mean = self._get_league_mean_nrtg(season)
        prior = PRIOR_STRENGTH[2]  # 30 possessions
        archetypes = self._get_player_archetypes(season)

        logger.info(f"  Found {len(lineups)} 2-man combos | League mean NRtg: {league_mean:.2f} | Prior: {prior}")

        rows = []
        for _, lu in lineups.iterrows():
            pids = json.loads(lu["player_ids"])
            if len(pids) != 2:
                continue

            # Canonical ordering: smaller ID first (matches PK constraint)
            pid_a, pid_b = sorted(int(p) for p in pids)

            raw_nrtg = float(lu["net_rating"])
            poss = float(lu["possessions"])

            # Bayesian shrinkage
            shrunk_nrtg = bayesian_shrinkage(raw_nrtg, poss, league_mean, prior)

            rows.append({
                "player_a_id": pid_a,
                "player_b_id": pid_b,
                "team_id": int(lu["team_id"]),
                "season_id": season,
                "minutes_together": float(lu["minutes"]) if lu["minutes"] else 0.0,
                "possessions": poss,
                "net_rating": round(shrunk_nrtg, 3),
                "synergy_score": 0.0,  # placeholder, normalized below
                "archetype_a": archetypes.get(pid_a, "Unknown"),
                "archetype_b": archetypes.get(pid_b, "Unknown"),
            })

        if not rows:
            logger.warning("No valid pairs extracted.")
            return

        df = pd.DataFrame(rows)

        # Normalize shrunk net_rating to synergy_score (0-100) for pairs with >= 10 possessions
        valid_mask = df["possessions"] >= 10
        if valid_mask.sum() > 0:
            valid_nrtgs = df.loc[valid_mask, "net_rating"].values
            scores = normalize_to_scale(valid_nrtgs, low=0, high=100)
            df.loc[valid_mask, "synergy_score"] = np.round(scores, 1)

            # For pairs with < 10 possessions, assign neutral score (50)
            df.loc[~valid_mask, "synergy_score"] = 50.0
        else:
            df["synergy_score"] = 50.0

        # Deduplicate: keep the row with highest possessions for each (a, b) pair
        df = df.sort_values("possessions", ascending=False).drop_duplicates(
            subset=["player_a_id", "player_b_id", "season_id"], keep="first"
        )

        # Save
        execute("DELETE FROM pair_synergy WHERE season_id = ?", self.db_path, [season])
        save_dataframe(df, "pair_synergy", self.db_path)

        # Stats
        top = df.nlargest(5, "synergy_score")
        logger.info(f"  Saved {len(df)} pair synergies")
        logger.info(f"  Top 5 synergy scores:")
        for _, r in top.iterrows():
            logger.info(f"    {r['archetype_a']} + {r['archetype_b']}: "
                        f"syn={r['synergy_score']:.1f} nrtg={r['net_rating']:+.1f} "
                        f"poss={r['possessions']:.0f}")

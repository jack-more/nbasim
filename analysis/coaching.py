"""Coaching scheme classification using percentile-rank labeling on play type distributions."""

import json
import logging
import numpy as np
import pandas as pd

from db.connection import read_query, execute, save_dataframe
from utils.constants import PLAY_TYPES

logger = logging.getLogger(__name__)


class CoachingAnalyzer:

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_offensive_data(self, season: str) -> pd.DataFrame:
        """Build a per-team DataFrame with offensive play type freq + ppp."""
        team_stats = read_query(
            "SELECT team_id, pace, off_rating, fg3a_rate, ft_rate, ast_pct, tov_pct "
            "FROM team_season_stats WHERE season_id = ?",
            self.db_path, [season]
        )

        playtypes = read_query(
            """SELECT team_id, play_type, poss_pct, ppp
               FROM team_playtypes
               WHERE season_id = ? AND type_grouping = 'Offensive'""",
            self.db_path, [season]
        )

        if team_stats.empty or playtypes.empty:
            return pd.DataFrame()

        freq_pivot = playtypes.pivot_table(
            index="team_id", columns="play_type",
            values="poss_pct", fill_value=0
        ).reset_index()
        freq_pivot.columns = [
            f"off_{c}_freq" if c != "team_id" else c for c in freq_pivot.columns
        ]

        ppp_pivot = playtypes.pivot_table(
            index="team_id", columns="play_type",
            values="ppp", fill_value=0
        ).reset_index()
        ppp_pivot.columns = [
            f"off_{c}_ppp" if c != "team_id" else c for c in ppp_pivot.columns
        ]

        merged = team_stats.merge(freq_pivot, on="team_id", how="inner")
        merged = merged.merge(ppp_pivot, on="team_id", how="left")
        return merged

    def _get_defensive_data(self, season: str) -> pd.DataFrame:
        """Build a per-team DataFrame with defensive play type freq + ppp."""
        team_stats = read_query(
            "SELECT team_id, def_rating FROM team_season_stats WHERE season_id = ?",
            self.db_path, [season]
        )

        playtypes = read_query(
            """SELECT team_id, play_type, poss_pct, ppp
               FROM team_playtypes
               WHERE season_id = ? AND type_grouping = 'Defensive'""",
            self.db_path, [season]
        )

        if team_stats.empty or playtypes.empty:
            return pd.DataFrame()

        freq_pivot = playtypes.pivot_table(
            index="team_id", columns="play_type",
            values="poss_pct", fill_value=0
        ).reset_index()
        freq_pivot.columns = [
            f"def_{c}_freq" if c != "team_id" else c for c in freq_pivot.columns
        ]

        ppp_pivot = playtypes.pivot_table(
            index="team_id", columns="play_type",
            values="ppp", fill_value=0
        ).reset_index()
        ppp_pivot.columns = [
            f"def_{c}_ppp" if c != "team_id" else c for c in ppp_pivot.columns
        ]

        merged = team_stats.merge(freq_pivot, on="team_id", how="inner")
        merged = merged.merge(ppp_pivot, on="team_id", how="left")
        return merged

    def _label_offensive_scheme(self, row: pd.Series, ranks: pd.DataFrame) -> str:
        """Label a team's offensive scheme based on percentile ranks within the league.

        Uses relative ranking (where does this team sit among the 30 teams?)
        instead of raw values, so we get meaningful differentiation.
        """
        tid = row["team_id"]
        team_ranks = ranks.loc[tid] if tid in ranks.index else pd.Series()

        # Get raw freq values for primary identification
        pnr_freq = row.get("off_PRBallHandler_freq", 0) or 0
        iso_freq = row.get("off_Isolation_freq", 0) or 0
        trans_freq = row.get("off_Transition_freq", 0) or 0
        spotup_freq = row.get("off_Spotup_freq", 0) or 0
        cut_freq = row.get("off_Cut_freq", 0) or 0
        handoff_freq = row.get("off_Handoff_freq", 0) or 0
        offscreen_freq = row.get("off_OffScreen_freq", 0) or 0
        postup_freq = row.get("off_Postup_freq", 0) or 0
        pnr_roll_freq = row.get("off_PRRollMan_freq", 0) or 0

        motion_total = cut_freq + offscreen_freq + handoff_freq
        pace = row.get("pace", 100) or 100

        # Use percentile ranks (0-1, higher = more of that thing)
        pnr_rank = team_ranks.get("off_PRBallHandler_freq", 0.5)
        iso_rank = team_ranks.get("off_Isolation_freq", 0.5)
        trans_rank = team_ranks.get("off_Transition_freq", 0.5)
        spotup_rank = team_ranks.get("off_Spotup_freq", 0.5)
        motion_rank = (
            team_ranks.get("off_Cut_freq", 0.5) +
            team_ranks.get("off_OffScreen_freq", 0.5) +
            team_ranks.get("off_Handoff_freq", 0.5)
        ) / 3
        postup_rank = team_ranks.get("off_Postup_freq", 0.5)
        pnr_roll_rank = team_ranks.get("off_PRRollMan_freq", 0.5)
        pace_rank = team_ranks.get("pace", 0.5)

        # Score each scheme type using RELATIVE rankings
        schemes = {}

        # PnR-Heavy: top-10 in PnR ball-handler frequency
        schemes["PnR-Heavy"] = pnr_rank * 3 + pnr_roll_rank * 1.5

        # ISO-Heavy: top-10 in isolation frequency
        schemes["ISO-Heavy"] = iso_rank * 4

        # Motion: high cuts + off-screens + handoffs
        schemes["Motion"] = motion_rank * 3.5

        # Transition: high pace + high transition %
        schemes["Run-and-Gun"] = trans_rank * 2.5 + pace_rank * 1.5

        # Spot-Up Heavy: relies on catch-and-shoot more than creation
        schemes["Spot-Up Heavy"] = spotup_rank * 3 + (1 - pnr_rank) * 1.0

        # Post-Oriented
        schemes["Post-Oriented"] = postup_rank * 4

        # Pick the highest
        primary = max(schemes, key=schemes.get)

        # Add a secondary modifier
        # Remove the primary from consideration
        del schemes[primary]
        secondary = max(schemes, key=schemes.get)

        # Add pace modifier
        if pace > 101:
            pace_mod = "Fast"
        elif pace < 97:
            pace_mod = "Slow"
        else:
            pace_mod = "Mid"

        return f"{primary} ({pace_mod})"

    def _label_defensive_scheme(self, row: pd.Series, ranks: pd.DataFrame) -> str:
        """Label a team's defensive scheme based on percentile ranks."""
        tid = row["team_id"]
        team_ranks = ranks.loc[tid] if tid in ranks.index else pd.Series()

        def_rating = row.get("def_rating", 115) or 115

        # How good are they at limiting specific play types (low PPP = good)?
        # For PPP, we INVERT the rank (low PPP = good defense = high rank)
        iso_ppp_rank = 1.0 - team_ranks.get("def_Isolation_ppp", 0.5)
        pnr_ppp_rank = 1.0 - team_ranks.get("def_PRBallHandler_ppp", 0.5)
        trans_ppp_rank = 1.0 - team_ranks.get("def_Transition_ppp", 0.5)
        spotup_ppp_rank = 1.0 - team_ranks.get("def_Spotup_ppp", 0.5)
        postup_ppp_rank = 1.0 - team_ranks.get("def_Postup_ppp", 0.5)

        # What do opponents run against them? (freq)
        opp_iso_rank = team_ranks.get("def_Isolation_freq", 0.5)
        opp_pnr_rank = team_ranks.get("def_PRBallHandler_freq", 0.5)
        opp_trans_rank = team_ranks.get("def_Transition_freq", 0.5)

        drtg_rank = 1.0 - team_ranks.get("def_rating", 0.5)  # invert: low DRtg = good

        schemes = {}

        # Switch-Everything: good at ISO defense, opponents don't run ISO much
        schemes["Switch-Everything"] = iso_ppp_rank * 2.5 + (1 - opp_iso_rank) * 1.5

        # Drop Coverage: let opponents PnR but limit damage
        schemes["Drop-Coverage"] = pnr_ppp_rank * 2.5 + opp_pnr_rank * 1.0

        # Rim Protection: force outside shots, protect paint
        schemes["Rim-Protect"] = postup_ppp_rank * 2 + spotup_ppp_rank * 1.5

        # Transition Defense: limit fast break points
        schemes["Trans-Defense"] = trans_ppp_rank * 3 + (1 - opp_trans_rank) * 1.5

        # Blitz/Aggressive: force turnovers
        schemes["Blitz"] = drtg_rank * 3.5

        primary = max(schemes, key=schemes.get)

        # Quality modifier
        if def_rating < 110:
            qual = "Elite"
        elif def_rating < 113:
            qual = "Good"
        elif def_rating < 116:
            qual = "Avg"
        else:
            qual = "Poor"

        return f"{primary} ({qual})"

    def classify_schemes(self, season: str):
        """Run full coaching scheme classification for a season."""
        logger.info(f"Classifying coaching schemes for {season}")

        off_df = self._get_offensive_data(season)
        def_df = self._get_defensive_data(season)

        if off_df.empty:
            logger.warning("No data for offensive scheme classification")
            return

        # Compute percentile ranks (0-1) for each feature across all teams
        off_numeric = off_df.select_dtypes(include=[np.number]).drop(columns=["team_id"], errors="ignore")
        off_ranks = off_numeric.rank(pct=True)
        off_ranks.index = off_df["team_id"].values

        def_ranks = pd.DataFrame()
        if not def_df.empty:
            def_numeric = def_df.select_dtypes(include=[np.number]).drop(columns=["team_id"], errors="ignore")
            def_ranks = def_numeric.rank(pct=True)
            def_ranks.index = def_df["team_id"].values

        # Get top 3 play styles per team
        playstyles = read_query(
            """SELECT team_id, play_type, poss_pct
               FROM team_playtypes
               WHERE season_id = ? AND type_grouping = 'Offensive'
               ORDER BY team_id, poss_pct DESC""",
            self.db_path, [season]
        )

        top_plays = {}
        for tid, group in playstyles.groupby("team_id"):
            top3 = group.nlargest(3, "poss_pct")["play_type"].tolist()
            top_plays[int(tid)] = top3

        # Build coaching profiles
        rows = []
        for _, row in off_df.iterrows():
            tid = int(row["team_id"])

            off_label = self._label_offensive_scheme(row, off_ranks)

            # Defensive label
            if not def_df.empty and tid in def_df["team_id"].values:
                def_row = def_df[def_df["team_id"] == tid].iloc[0]
                def_label = self._label_defensive_scheme(def_row, def_ranks)
            else:
                def_label = "Unknown"

            pace = row.get("pace", 100) or 100
            if pace > 101:
                pace_cat = "Fast"
            elif pace < 97:
                pace_cat = "Slow"
            else:
                pace_cat = "Average"

            plays = top_plays.get(tid, ["", "", ""])

            rows.append({
                "team_id": tid,
                "season_id": season,
                "off_scheme_label": off_label,
                "off_scheme_cluster": 0,
                "pace_category": pace_cat,
                "pace_value": pace,
                "primary_playstyle": plays[0] if len(plays) > 0 else "",
                "secondary_playstyle": plays[1] if len(plays) > 1 else "",
                "tertiary_playstyle": plays[2] if len(plays) > 2 else "",
                "fg3a_rate": row.get("fg3a_rate", 0) or 0,
                "def_scheme_label": def_label,
                "def_scheme_cluster": 0,
                "off_feature_vector": "[]",
                "def_feature_vector": "[]",
            })

        df = pd.DataFrame(rows)
        execute(
            "DELETE FROM coaching_profiles WHERE season_id = ?",
            self.db_path, [season]
        )
        save_dataframe(df, "coaching_profiles", self.db_path)
        logger.info(f"Saved {len(df)} coaching profiles for {season}")

        # Print summary
        print(f"\n{'='*60}")
        print(f"COACHING SCHEME SUMMARY - {season}")
        print(f"{'='*60}")

        teams = read_query("SELECT team_id, abbreviation FROM teams", self.db_path)
        team_names = dict(zip(teams["team_id"].astype(int), teams["abbreviation"]))

        for _, row in df.iterrows():
            abbr = team_names.get(int(row["team_id"]), "???")
            print(
                f"  {abbr:>3}: OFF={row['off_scheme_label']:<25} "
                f"DEF={row['def_scheme_label']:<25} "
                f"Top: {row['primary_playstyle']}, {row['secondary_playstyle']}"
            )
        print()

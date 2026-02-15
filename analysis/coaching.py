"""Coaching scheme classification using K-Means clustering on play type distributions."""

import json
import logging
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

from db.connection import read_query, execute, save_dataframe
from utils.constants import PLAY_TYPES

logger = logging.getLogger(__name__)


class CoachingAnalyzer:

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _build_offensive_features(self, season: str) -> tuple[pd.DataFrame, list[str]]:
        """Build offensive feature matrix for all teams."""
        # Get team season stats
        team_stats = read_query(
            "SELECT * FROM team_season_stats WHERE season_id = ?",
            self.db_path, [season]
        )

        # Get offensive play type distributions
        playtypes = read_query(
            """SELECT team_id, play_type, poss_pct, ppp
               FROM team_playtypes
               WHERE season_id = ? AND type_grouping = 'Offensive'""",
            self.db_path, [season]
        )

        if team_stats.empty or playtypes.empty:
            return pd.DataFrame(), []

        # Pivot play types: each play type becomes a column
        pt_pivot = playtypes.pivot_table(
            index="team_id", columns="play_type",
            values="poss_pct", fill_value=0
        ).reset_index()

        # Merge with team stats
        merged = team_stats.merge(pt_pivot, on="team_id", how="inner")

        # Select features
        pt_cols = [c for c in pt_pivot.columns if c != "team_id"]
        stat_cols = ["pace", "fg3a_rate", "ft_rate", "ast_pct", "tov_pct"]
        feature_cols = [c for c in stat_cols + pt_cols if c in merged.columns]

        return merged[["team_id"] + feature_cols], feature_cols

    def _build_defensive_features(self, season: str) -> tuple[pd.DataFrame, list[str]]:
        """Build defensive feature matrix for all teams."""
        team_stats = read_query(
            "SELECT * FROM team_season_stats WHERE season_id = ?",
            self.db_path, [season]
        )

        playtypes = read_query(
            """SELECT team_id, play_type, poss_pct, ppp
               FROM team_playtypes
               WHERE season_id = ? AND type_grouping = 'Defensive'""",
            self.db_path, [season]
        )

        if team_stats.empty or playtypes.empty:
            return pd.DataFrame(), []

        pt_pivot = playtypes.pivot_table(
            index="team_id", columns="play_type",
            values="poss_pct", fill_value=0
        ).reset_index()

        # Also get defensive PPP per play type
        ppp_pivot = playtypes.pivot_table(
            index="team_id", columns="play_type",
            values="ppp", fill_value=0
        ).reset_index()
        ppp_pivot.columns = [
            f"{c}_ppp" if c != "team_id" else c for c in ppp_pivot.columns
        ]

        merged = team_stats.merge(pt_pivot, on="team_id", how="inner")
        merged = merged.merge(ppp_pivot, on="team_id", how="left")

        pt_cols = [c for c in pt_pivot.columns if c != "team_id"]
        ppp_cols = [c for c in ppp_pivot.columns if c != "team_id"]
        stat_cols = ["def_rating"]
        feature_cols = [c for c in stat_cols + pt_cols + ppp_cols if c in merged.columns]

        return merged[["team_id"] + feature_cols], feature_cols

    def _find_best_k(self, X: np.ndarray, k_range: tuple = (3, 6)) -> int:
        """Find best K using silhouette score."""
        if len(X) < k_range[0]:
            return min(len(X), 2)

        best_k = k_range[0]
        best_score = -1

        for k in range(k_range[0], min(k_range[1], len(X))):
            km = KMeans(n_clusters=k, n_init=20, random_state=42)
            labels = km.fit_predict(X)
            if len(set(labels)) < 2:
                continue
            score = silhouette_score(X, labels)
            if score > best_score:
                best_score = score
                best_k = k
                logger.info(f"    K={k}: silhouette={score:.3f} (new best)")
            else:
                logger.info(f"    K={k}: silhouette={score:.3f}")

        return best_k

    def _label_offensive_cluster(self, centroid: np.ndarray, feature_names: list) -> str:
        """Assign human-readable label based on centroid characteristics."""
        feat_map = {name: val for name, val in zip(feature_names, centroid)}

        # Score each label candidate
        scores = {}

        # PnR-Dominant: high PRBallHandler
        scores["PnR-Dominant"] = feat_map.get("PRBallHandler", 0) * 2

        # Pace-and-Space: high pace + high fg3a_rate + high Transition
        scores["Pace-and-Space"] = (
            feat_map.get("pace", 0) * 0.5 +
            feat_map.get("fg3a_rate", 0) * 2 +
            feat_map.get("Transition", 0) * 1.5
        )

        # ISO-Heavy: high Isolation
        scores["ISO-Heavy"] = feat_map.get("Isolation", 0) * 2.5

        # Motion-Heavy: high Cut + OffScreen + Handoff
        scores["Motion-Heavy"] = (
            feat_map.get("Cut", 0) * 2 +
            feat_map.get("OffScreen", 0) * 2 +
            feat_map.get("Handoff", 0) * 1.5
        )

        # Post-Oriented: high Postup
        scores["Post-Oriented"] = feat_map.get("Postup", 0) * 2.5

        # Balanced
        scores["Balanced"] = 0.1  # fallback

        return max(scores, key=scores.get)

    def _label_defensive_cluster(self, centroid: np.ndarray, feature_names: list) -> str:
        """Assign defensive scheme label."""
        feat_map = {name: val for name, val in zip(feature_names, centroid)}

        scores = {}
        # Switch-Heavy: low opponent ISO PPP (good at defending ISO)
        scores["Switch-Heavy"] = -feat_map.get("Isolation_ppp", 0)

        # Drop-Coverage: high opponent PRBallHandler poss_pct but low PPP
        scores["Drop-Coverage"] = (
            feat_map.get("PRBallHandler", 0) -
            feat_map.get("PRBallHandler_ppp", 0)
        )

        # Aggressive: low def_rating (better defense)
        scores["Aggressive"] = -feat_map.get("def_rating", 0)

        # Standard
        scores["Standard"] = 0.1

        return max(scores, key=scores.get)

    def classify_schemes(self, season: str):
        """Run full coaching scheme classification for a season."""
        logger.info(f"Classifying coaching schemes for {season}")

        # Offensive
        off_df, off_features = self._build_offensive_features(season)
        # Defensive
        def_df, def_features = self._build_defensive_features(season)

        if off_df.empty:
            logger.warning("No data for offensive scheme classification")
            return

        team_ids = off_df["team_id"].values
        X_off = off_df[off_features].fillna(0).values
        scaler_off = StandardScaler()
        X_off_scaled = scaler_off.fit_transform(X_off)

        # Find best K for offensive
        logger.info("  Finding best K for offensive schemes:")
        k_off = self._find_best_k(X_off_scaled, (3, 7))
        km_off = KMeans(n_clusters=k_off, n_init=20, random_state=42)
        off_labels = km_off.fit_predict(X_off_scaled)

        # Label offensive clusters
        off_cluster_labels = {}
        used_labels = set()
        for i, centroid in enumerate(scaler_off.inverse_transform(km_off.cluster_centers_)):
            label = self._label_offensive_cluster(centroid, off_features)
            # Avoid duplicates
            if label in used_labels:
                label = f"{label}-{i}"
            used_labels.add(label)
            off_cluster_labels[i] = label
            logger.info(f"    Offensive cluster {i}: {label}")

        # Defensive
        def_labels = np.zeros(len(team_ids), dtype=int)
        def_cluster_labels = {0: "Standard"}

        if not def_df.empty:
            # Align defensive teams with offensive teams
            def_team_ids = def_df["team_id"].values
            X_def = def_df[def_features].fillna(0).values
            scaler_def = StandardScaler()
            X_def_scaled = scaler_def.fit_transform(X_def)

            logger.info("  Finding best K for defensive schemes:")
            k_def = self._find_best_k(X_def_scaled, (3, 6))
            km_def = KMeans(n_clusters=k_def, n_init=20, random_state=42)
            def_labels_raw = km_def.fit_predict(X_def_scaled)

            # Map defensive labels
            used_labels = set()
            for i, centroid in enumerate(scaler_def.inverse_transform(km_def.cluster_centers_)):
                label = self._label_defensive_cluster(centroid, def_features)
                if label in used_labels:
                    label = f"{label}-{i}"
                used_labels.add(label)
                def_cluster_labels[i] = label
                logger.info(f"    Defensive cluster {i}: {label}")

            # Create mapping from def team_id to labels
            def_map = dict(zip(def_team_ids, def_labels_raw))
            def_labels = np.array([def_map.get(tid, 0) for tid in team_ids])

        # Get pace and play type rankings for each team
        team_stats = read_query(
            "SELECT team_id, pace FROM team_season_stats WHERE season_id = ?",
            self.db_path, [season]
        )
        pace_map = dict(zip(team_stats["team_id"].astype(int), team_stats["pace"]))

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
        for idx, tid in enumerate(team_ids):
            tid = int(tid)
            pace = pace_map.get(tid, 0)

            # Pace category
            if pace > 101:
                pace_cat = "Fast"
            elif pace < 97:
                pace_cat = "Slow"
            else:
                pace_cat = "Average"

            plays = top_plays.get(tid, ["", "", ""])
            fg3a = off_df.iloc[idx].get("fg3a_rate", 0) if "fg3a_rate" in off_df.columns else 0

            rows.append({
                "team_id": tid,
                "season_id": season,
                "off_scheme_label": off_cluster_labels.get(off_labels[idx], "Unknown"),
                "off_scheme_cluster": int(off_labels[idx]),
                "pace_category": pace_cat,
                "pace_value": pace,
                "primary_playstyle": plays[0] if len(plays) > 0 else "",
                "secondary_playstyle": plays[1] if len(plays) > 1 else "",
                "tertiary_playstyle": plays[2] if len(plays) > 2 else "",
                "fg3a_rate": fg3a,
                "def_scheme_label": def_cluster_labels.get(int(def_labels[idx]), "Standard"),
                "def_scheme_cluster": int(def_labels[idx]),
                "off_feature_vector": json.dumps(X_off_scaled[idx].tolist()),
                "def_feature_vector": json.dumps(
                    X_def_scaled[
                        list(def_team_ids).index(tid)
                    ].tolist() if tid in def_team_ids else []
                ) if not def_df.empty else "[]",
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
                f"  {abbr:>3}: OFF={row['off_scheme_label']:<20} "
                f"DEF={row['def_scheme_label']:<15} "
                f"Pace={row['pace_category']:<8} "
                f"Top: {row['primary_playstyle']}, {row['secondary_playstyle']}"
            )
        print()

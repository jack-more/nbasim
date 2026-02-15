"""Player archetype clustering using K-Means per position group."""

import json
import logging
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from scipy.optimize import linear_sum_assignment

from db.connection import read_query, execute, save_dataframe
from utils.constants import (
    POSITION_GROUPS, ARCHETYPE_LABELS,
    POSITION_FEATURE_WEIGHTS, CLUSTERING_FEATURES,
)
from config import MIN_MINUTES_FOR_CLUSTERING, K_RANGE

logger = logging.getLogger(__name__)


# Archetype profile templates for label assignment
# Each template maps feature names to expected z-score direction
ARCHETYPE_PROFILES = {
    "PG": {
        "Floor General": {"ast_per36": 2, "ast_pct": 2, "usg_pct": -1, "tov_per36": 1},
        "Scoring Guard": {"pts_per36": 2, "usg_pct": 2, "ts_pct": 1, "fg3a_per36": 1},
        "Combo Guard": {"pts_per36": 1, "ast_per36": 1, "usg_pct": 0.5},
        "Defensive Specialist": {"stl_per36": 2, "usg_pct": -2, "pts_per36": -1, "def_rating": -1},
    },
    "SG": {
        "Sharpshooter": {"fg3a_per36": 2, "fg3_pct": 2, "pts_per36": 1},
        "Two-Way Wing": {"stl_per36": 1.5, "blk_per36": 1, "def_rating": -1, "pts_per36": 0.5},
        "Slasher": {"fta_per36": 2, "fg3a_per36": -1, "pts_per36": 1.5},
        "Playmaking Guard": {"ast_per36": 2, "ast_pct": 2, "usg_pct": 1},
    },
    "SF": {
        "3-and-D Wing": {"fg3a_per36": 1.5, "stl_per36": 1.5, "def_rating": -1, "usg_pct": -1},
        "Point Forward": {"ast_per36": 2, "ast_pct": 2, "usg_pct": 1, "reb_per36": 1},
        "Stretch Forward": {"fg3a_per36": 2, "fg3_pct": 1.5, "reb_per36": 0.5},
        "Athletic Wing": {"pts_per36": 1.5, "reb_per36": 1, "blk_per36": 1, "fta_per36": 1},
    },
    "PF": {
        "Stretch Big": {"fg3a_per36": 2, "fg3_pct": 1.5, "reb_per36": 0.5},
        "Traditional PF": {"reb_per36": 2, "blk_per36": 1, "fg3a_per36": -1.5, "fg_pct": 1},
        "Small-Ball 4": {"ast_per36": 1, "stl_per36": 1, "fg3a_per36": 1, "reb_per36": -0.5},
        "Two-Way Forward": {"def_rating": -1.5, "stl_per36": 1, "blk_per36": 1, "pts_per36": 0.5},
    },
    "C": {
        "Rim Protector": {"blk_per36": 2, "reb_per36": 1.5, "def_rating": -2, "fg3a_per36": -1},
        "Stretch 5": {"fg3a_per36": 2, "fg3_pct": 1.5, "blk_per36": -0.5},
        "Traditional Center": {"reb_per36": 2, "fg_pct": 1.5, "fg3a_per36": -1.5, "pts_per36": 0.5},
        "Versatile Big": {"ast_per36": 1.5, "pts_per36": 1, "reb_per36": 0.5, "fg3a_per36": 0.5},
    },
}


class ArchetypeAnalyzer:

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_players_for_position(self, season: str, position_group: str) -> pd.DataFrame:
        """Get players matching a position group with enough minutes."""
        valid_positions = POSITION_GROUPS[position_group]
        placeholders = ",".join(["?"] * len(valid_positions))

        df = read_query(
            f"""SELECT ps.*
                FROM player_season_stats ps
                JOIN roster_assignments ra
                  ON ps.player_id = ra.player_id AND ps.season_id = ra.season_id
                WHERE ps.season_id = ?
                  AND ra.listed_position IN ({placeholders})
                  AND ps.minutes_total >= ?""",
            self.db_path,
            [season] + valid_positions + [MIN_MINUTES_FOR_CLUSTERING]
        )
        return df.drop_duplicates(subset=["player_id"])

    def _score_centroid_against_profile(
        self, centroid: np.ndarray, profile: dict, feature_names: list
    ) -> float:
        """Score how well a centroid matches an archetype profile template."""
        score = 0.0
        for feat, weight in profile.items():
            if feat in feature_names:
                idx = feature_names.index(feat)
                score += centroid[idx] * weight
        return score

    def _assign_labels(
        self, centroids: np.ndarray, feature_names: list, position_group: str
    ) -> list[str]:
        """Use Hungarian algorithm to optimally assign labels to clusters."""
        profiles = ARCHETYPE_PROFILES.get(position_group, {})
        available_labels = list(profiles.keys())
        n_clusters = len(centroids)

        if n_clusters == 0:
            return []

        # If more clusters than labels, extend with numbered labels
        while len(available_labels) < n_clusters:
            available_labels.append(f"Type-{len(available_labels)}")

        # Build cost matrix (negative score = cost to minimize)
        n_labels = len(available_labels)
        cost_matrix = np.zeros((n_clusters, n_labels))

        for i, centroid in enumerate(centroids):
            for j, label in enumerate(available_labels):
                if label in profiles:
                    cost_matrix[i, j] = -self._score_centroid_against_profile(
                        centroid, profiles[label], feature_names
                    )
                else:
                    cost_matrix[i, j] = 0  # neutral for extra labels

        # Hungarian algorithm
        row_ind, col_ind = linear_sum_assignment(cost_matrix)

        labels = [""] * n_clusters
        for r, c in zip(row_ind, col_ind):
            labels[r] = available_labels[c]

        return labels

    def cluster_position(self, season: str, position_group: str) -> pd.DataFrame:
        """Cluster players in a position group. Returns DataFrame with assignments."""
        logger.info(f"  Clustering {position_group} players for {season}")

        df = self._get_players_for_position(season, position_group)
        if len(df) < 4:
            logger.warning(f"    Too few {position_group} players ({len(df)}), skipping")
            return pd.DataFrame()

        # Extract features
        available_features = [f for f in CLUSTERING_FEATURES if f in df.columns]
        X_raw = df[available_features].fillna(0).values

        # Apply position-specific weights
        weights = POSITION_FEATURE_WEIGHTS.get(position_group, {})
        weight_array = np.array([
            weights.get(f, 1.0) for f in available_features
        ])
        X_weighted = X_raw * weight_array

        # StandardScaler
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X_weighted)

        # PCA to 8 components (if enough features)
        n_components = min(8, X_scaled.shape[1], X_scaled.shape[0] - 1)
        if n_components < 2:
            n_components = 2
        pca = PCA(n_components=n_components)
        X_pca = pca.fit_transform(X_scaled)
        variance_explained = pca.explained_variance_ratio_.sum()
        logger.info(f"    PCA: {n_components} components, {variance_explained:.1%} variance")

        # Find best K
        k_min, k_max = K_RANGE
        k_max = min(k_max + 1, len(df))
        best_k = k_min
        best_score = -1

        for k in range(k_min, k_max):
            if k >= len(df):
                break
            km = KMeans(n_clusters=k, n_init=20, random_state=42)
            labels = km.fit_predict(X_pca)
            if len(set(labels)) < 2:
                continue
            score = silhouette_score(X_pca, labels)
            logger.info(f"    K={k}: silhouette={score:.3f}")
            if score > best_score:
                best_score = score
                best_k = k

        logger.info(f"    Best K={best_k} (silhouette={best_score:.3f})")

        # Final clustering with best K
        km_final = KMeans(n_clusters=best_k, n_init=20, random_state=42)
        cluster_labels = km_final.fit_predict(X_pca)

        # Assign archetype labels using centroids in scaled space
        # Transform PCA centroids back to scaled feature space for labeling
        centroids_pca = km_final.cluster_centers_
        centroids_scaled = pca.inverse_transform(centroids_pca)
        # Undo weighting to get back to standard-scaled original features
        centroids_unweighted = centroids_scaled / weight_array

        archetype_names = self._assign_labels(
            centroids_unweighted, available_features, position_group
        )

        # Compute confidence (inverse distance to cluster center)
        distances = np.linalg.norm(X_pca - centroids_pca[cluster_labels], axis=1)
        max_dist = distances.max() if distances.max() > 0 else 1
        confidence = 1.0 - (distances / max_dist)

        # Build result
        results = []
        player_names = read_query(
            "SELECT player_id, full_name FROM players", self.db_path
        )
        name_map = dict(zip(player_names["player_id"].astype(int), player_names["full_name"]))

        for i, (_, row) in enumerate(df.iterrows()):
            pid = int(row["player_id"])
            cluster_id = int(cluster_labels[i])
            archetype = archetype_names[cluster_id] if cluster_id < len(archetype_names) else f"Type-{cluster_id}"

            results.append({
                "player_id": pid,
                "season_id": season,
                "position_group": position_group,
                "archetype_id": cluster_id,
                "archetype_label": archetype,
                "confidence": float(confidence[i]),
                "feature_vector": json.dumps(X_scaled[i].tolist()),
            })

        result_df = pd.DataFrame(results)

        # Log sample assignments
        for arch in archetype_names:
            arch_players = result_df[result_df["archetype_label"] == arch]
            top_players = arch_players.nlargest(3, "confidence")
            names = [name_map.get(int(pid), "?") for pid in top_players["player_id"]]
            logger.info(f"    {arch}: {', '.join(names)}")

        return result_df

    def classify_all(self, season: str):
        """Run clustering for all 5 position groups."""
        logger.info(f"Classifying player archetypes for {season}")

        # Clear existing
        execute(
            "DELETE FROM player_archetypes WHERE season_id = ?",
            self.db_path, [season]
        )

        all_results = []
        for pos in ["PG", "SG", "SF", "PF", "C"]:
            result = self.cluster_position(season, pos)
            if not result.empty:
                all_results.append(result)

        if all_results:
            combined = pd.concat(all_results, ignore_index=True)

            # Handle players who appear in multiple position groups:
            # keep the one with highest confidence
            combined = combined.sort_values("confidence", ascending=False)
            combined = combined.drop_duplicates(subset=["player_id", "season_id"], keep="first")

            save_dataframe(combined, "player_archetypes", self.db_path)
            logger.info(f"Saved {len(combined)} player archetype assignments for {season}")

            # Print summary
            print(f"\n{'='*60}")
            print(f"PLAYER ARCHETYPE SUMMARY - {season}")
            print(f"{'='*60}")

            players = read_query("SELECT player_id, full_name FROM players", self.db_path)
            name_map = dict(zip(players["player_id"].astype(int), players["full_name"]))

            for pos in ["PG", "SG", "SF", "PF", "C"]:
                pos_data = combined[combined["position_group"] == pos]
                if pos_data.empty:
                    continue
                print(f"\n  {pos}:")
                for arch in pos_data["archetype_label"].unique():
                    arch_players = pos_data[pos_data["archetype_label"] == arch]
                    # Sort by confidence, show top 5
                    top = arch_players.nlargest(5, "confidence")
                    names = [name_map.get(int(pid), "?") for pid in top["player_id"]]
                    print(f"    {arch} ({len(arch_players)} players): {', '.join(names)}")
            print()

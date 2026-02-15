"""Statistical utility functions: Bayesian shrinkage, normalization, weighted averages."""

import numpy as np


def bayesian_shrinkage(raw_value: float, sample_size: float,
                       prior_mean: float, prior_strength: float) -> float:
    """
    Empirical Bayes shrinkage.
    Pulls raw_value toward prior_mean based on sample_size vs prior_strength.
    """
    if sample_size + prior_strength == 0:
        return prior_mean
    return (raw_value * sample_size + prior_mean * prior_strength) / (sample_size + prior_strength)


def possession_weighted_average(values: list[float], possessions: list[float]) -> float:
    """Weighted average using possessions as weights."""
    values = np.array(values, dtype=float)
    weights = np.array(possessions, dtype=float)
    total_weight = weights.sum()
    if total_weight == 0:
        return 0.0
    return float(np.average(values, weights=weights))


def normalize_to_scale(values: np.ndarray, low: float = 0, high: float = 100) -> np.ndarray:
    """Min-max normalization to [low, high]."""
    values = np.asarray(values, dtype=float)
    v_min = values.min()
    v_max = values.max()
    if v_max == v_min:
        return np.full_like(values, (low + high) / 2)
    return low + (values - v_min) / (v_max - v_min) * (high - low)


def z_score_standardize(values: np.ndarray) -> np.ndarray:
    """Z-score standardization (mean=0, std=1)."""
    values = np.asarray(values, dtype=float)
    std = values.std()
    if std == 0:
        return np.zeros_like(values)
    return (values - values.mean()) / std

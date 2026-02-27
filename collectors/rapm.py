"""RAPM collector — pulls real Regularized Adjusted Plus-Minus from nbarapm.com.

Endpoint: https://www.nbarapm.com/load/current_comp
No API key required. Returns ~520 players with:
  - rapm_timedecay (time-weighted RAPM, most important)
  - orapm_timedecay (offensive RAPM)
  - drapm_timedecay (defensive RAPM)
  - rapm_lebron, rapm_darko (alternative models)
  - 2yr/3yr/4yr/5yr RAPM variants

Usage:
  from collectors.rapm import RAPMCollector
  collector = RAPMCollector(DB_PATH)
  collector.collect()
"""

import json
import logging

import pandas as pd
import requests

from db.connection import get_connection, save_dataframe

logger = logging.getLogger(__name__)

RAPM_URL = "https://www.nbarapm.com/load/current_comp"


class RAPMCollector:
    """Collects RAPM data from nbarapm.com."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def collect(self):
        """Fetch current RAPM data and store in DB."""
        logger.info("Fetching RAPM data from nbarapm.com ...")

        try:
            resp = requests.get(RAPM_URL, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch RAPM data: {e}")
            return 0

        data = resp.json()
        logger.info(f"  Got {len(data)} players from nbarapm.com")

        rows = []
        for p in data:
            nba_id = p.get("nba_id")
            if not nba_id:
                continue

            # Skip players with no RAPM data
            rapm = p.get("rapm_timedecay")
            if rapm is None or rapm == "":
                continue

            try:
                rapm_val = float(rapm)
            except (ValueError, TypeError):
                continue

            rows.append({
                "player_id": int(nba_id),
                "player_name": p.get("player_name", ""),
                "team": p.get("team", ""),
                "position": p.get("Pos2", ""),
                # Primary: time-decay RAPM (most recent = most weight)
                "rapm_total": rapm_val,
                "rapm_offense": _safe_float(p.get("orapm_timedecay")),
                "rapm_defense": _safe_float(p.get("drapm_timedecay")),
                "rapm_rank": _safe_float(p.get("rapm_rank_timedecay")),
                # Alternative models
                "lebron_total": _safe_float(p.get("rapm_lebron")),
                "lebron_offense": _safe_float(p.get("orapm_lebron")),
                "lebron_defense": _safe_float(p.get("drapm_lebron")),
                "darko_dpm": _safe_float(p.get("rapm_darko")),
                # Multi-year RAPM
                "rapm_2yr": _safe_float(p.get("two_year_rapm")),
                "rapm_3yr": _safe_float(p.get("three_year_rapm")),
                "rapm_4yr": _safe_float(p.get("four_year_rapm")),
                "rapm_5yr": _safe_float(p.get("five_year_rapm")),
            })

        if not rows:
            logger.warning("No valid RAPM records found")
            return 0

        df = pd.DataFrame(rows)

        # Write to DB (replace existing data — RAPM is current season only)
        save_dataframe(df, "player_rapm", self.db_path, if_exists="replace")

        n = len(df)
        top = df.nlargest(5, "rapm_total")
        logger.info(f"  Stored {n} RAPM records")
        logger.info(f"  RAPM range: {df['rapm_total'].min():+.1f} to {df['rapm_total'].max():+.1f}")
        logger.info(f"  Top 5:")
        for _, r in top.iterrows():
            logger.info(
                f"    {r['player_name']:25s} {r['team']:4s} "
                f"RAPM:{r['rapm_total']:+5.1f}  "
                f"O:{r['rapm_offense']:+5.1f}  "
                f"D:{r['rapm_defense']:+5.1f}"
            )

        return n


def _safe_float(val):
    """Convert to float, return None if empty/invalid."""
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

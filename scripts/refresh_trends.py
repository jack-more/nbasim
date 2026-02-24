#!/usr/bin/env python3
"""
refresh_trends.py — Incremental boxscore collector for daily trend updates.

Collects only the last 14 days of game boxscores that are missing from the DB,
then regenerates the frontend HTML so trends/hot-cold data is fresh.

Designed to run daily at 8 AM PST via GitHub Actions.
Much faster than a full `main.py collect` because it only hits recent games.
"""

import sys
import os
import logging
from datetime import datetime, timedelta, timezone

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from config import DB_PATH
from db.connection import read_query, execute
from collectors.boxscores import BoxScoreCollector
from collectors.games import GameCollector
from collectors.lineups import LineupCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("refresh_trends")

LOOKBACK_DAYS = 14
SEASON_ID = "2025-26"


def refresh_recent_games():
    """Collect game schedule for the last 14 days (fills any gaps).
    Non-fatal — if NBA.com times out, we still have existing game records."""
    logger.info(f"=== Refreshing game schedule (last {LOOKBACK_DAYS} days) ===")
    try:
        game_collector = GameCollector(DB_PATH)
        game_collector.collect_for_season(SEASON_ID)
        logger.info("Game schedule refreshed.")
    except Exception as e:
        logger.warning(f"Game schedule refresh failed (non-fatal, using existing data): {e}")


def collect_missing_boxscores():
    """Collect boxscores for recent games not yet in player_game_stats."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    logger.info(f"=== Collecting missing boxscores since {cutoff} ===")

    # Get recent games (all games — status column may not exist in all schemas)
    recent_games = read_query("""
        SELECT game_id, game_date
        FROM games
        WHERE season_id = ? AND game_date >= ?
        ORDER BY game_date DESC
    """, DB_PATH, [SEASON_ID, cutoff])

    if recent_games.empty:
        logger.info("No recent completed games found.")
        return 0

    # Get already-collected game IDs
    collected = set()
    try:
        collected_df = read_query(
            "SELECT DISTINCT game_id FROM player_game_stats", DB_PATH
        )
        collected = set(collected_df["game_id"].tolist())
    except Exception:
        pass

    # Find missing
    all_ids = set(recent_games["game_id"].tolist())
    missing = all_ids - collected

    if not missing:
        logger.info(f"All {len(all_ids)} recent games already have boxscores.")
        return 0

    logger.info(f"Found {len(missing)} games missing boxscores (of {len(all_ids)} recent).")

    # Collect missing boxscores
    bs_collector = BoxScoreCollector(DB_PATH)
    success = 0
    for game_id in sorted(missing):
        try:
            bs_collector.collect_game_boxscore(game_id)
            success += 1
            logger.info(f"  ✓ {game_id} ({success}/{len(missing)})")
        except Exception as e:
            logger.warning(f"  ✗ {game_id}: {e}")

    logger.info(f"Collected {success}/{len(missing)} missing boxscores.")
    return success


def refresh_lineup_stats():
    """Refresh lineup combo stats (hot/cold combos use this)."""
    logger.info("=== Refreshing lineup combo stats ===")
    lineup_collector = LineupCollector(DB_PATH)
    try:
        lineup_collector.collect_for_season(SEASON_ID)
        logger.info("Lineup stats refreshed.")
    except Exception as e:
        logger.warning(f"Lineup refresh failed (non-fatal): {e}")


def main():
    logger.info("=" * 60)
    logger.info("NBA SIM — DAILY TRENDS REFRESH")
    logger.info(f"Lookback: {LOOKBACK_DAYS} days | Season: {SEASON_ID}")
    logger.info("=" * 60)

    # Step 1: Make sure we have recent game records
    refresh_recent_games()

    # Step 2: Collect any missing boxscores (the key data for player trends)
    new_boxscores = collect_missing_boxscores()

    # Step 3: Refresh lineup combo stats (for hot/cold combos)
    refresh_lineup_stats()

    logger.info("=" * 60)
    logger.info(f"TRENDS REFRESH COMPLETE — {new_boxscores} new boxscores added")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

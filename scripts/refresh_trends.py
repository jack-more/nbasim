#!/usr/bin/env python3
"""
refresh_trends.py — Incremental boxscore collector + synergy refresh for daily trend updates.

Collects only the last 10 days of game boxscores that are missing from the DB,
refreshes lineup stats and synergy/value scores, then regenerates the frontend
HTML so WOWY trends, pair synergies, and projection model data are fresh.

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
from collectors.players import PlayerCollector
from collectors.boxscores import BoxScoreCollector
from collectors.games import GameCollector
from collectors.lineups import LineupCollector
from analysis.synergy import PairSynergyCalculator
from analysis.value_scores import ValueScoreCalculator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("refresh_trends")

LOOKBACK_DAYS = 10
SEASON_ID = "2025-26"


def refresh_recent_games():
    """Collect game schedule using Basketball-Reference (primary) or NBA API (fallback)."""
    logger.info(f"=== Refreshing game schedule ===")

    # Try Basketball-Reference first (doesn't get blocked from cloud IPs)
    try:
        from collectors.games_bbref import BRefGameCollector
        bbref = BRefGameCollector(DB_PATH)
        new_count = bbref.update_games_table(SEASON_ID)
        logger.info(f"Basketball-Reference: {new_count} games added/updated")
        return
    except Exception as e:
        logger.warning(f"Basketball-Reference failed: {e}")

    # Fallback to NBA API
    try:
        game_collector = GameCollector(DB_PATH)
        game_collector.collect_for_season(SEASON_ID)
        logger.info("Game schedule refreshed via NBA API.")
    except Exception as e:
        logger.warning(f"Both data sources failed. NBA API error: {e}")


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


def refresh_synergy_data():
    """Recompute pair synergies and value scores from latest lineup data."""
    logger.info("=== Refreshing synergy + value scores ===")
    try:
        synergy_calc = PairSynergyCalculator(DB_PATH)
        synergy_calc.compute_pair_synergies(SEASON_ID)
        logger.info("Pair synergies refreshed.")
    except Exception as e:
        logger.warning(f"Synergy refresh failed (non-fatal): {e}")

    try:
        value_calc = ValueScoreCalculator(DB_PATH)
        value_calc.compute_all(SEASON_ID)
        logger.info("Value scores refreshed.")
    except Exception as e:
        logger.warning(f"Value scores refresh failed (non-fatal): {e}")


def refresh_rosters_and_stats():
    """Refresh team rosters and player/team season stats daily.

    This ensures new signings, trades, and updated stat lines are reflected
    in the lineup displays and projection model.  ~40 lightweight API calls.

    Uses a hard 3-minute timeout — if stats.nba.com is down, bail fast
    and use cached data from the DB. Yesterday's rosters are fine.
    """
    import signal

    class _Timeout(Exception):
        pass

    def _handler(signum, frame):
        raise _Timeout("Roster refresh exceeded 3-minute limit — using cached data")

    logger.info("=== Refreshing rosters + player/team season stats ===")
    player_collector = PlayerCollector(DB_PATH)

    # Hard 3-minute wall clock limit
    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(180)
    try:
        player_collector.collect_teams()
        player_collector.collect_rosters(SEASON_ID)
        player_collector.collect_player_season_stats(SEASON_ID)
        player_collector.collect_team_season_stats(SEASON_ID)
        logger.info("Rosters + season stats refreshed.")
    except _Timeout as e:
        logger.warning(f"Roster refresh timed out (non-fatal, using cached): {e}")
    except Exception as e:
        logger.warning(f"Roster/stats refresh failed (non-fatal): {e}")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def main():
    logger.info("=" * 60)
    logger.info("NBA SIM — DAILY TRENDS REFRESH")
    logger.info(f"Lookback: {LOOKBACK_DAYS} days | Season: {SEASON_ID}")
    logger.info("=" * 60)

    # Step 1: Refresh rosters + player/team season stats (lineups, trades, stat lines)
    refresh_rosters_and_stats()

    # Step 2: Make sure we have recent game records
    refresh_recent_games()

    # Step 3: Collect any missing boxscores (the key data for player trends)
    new_boxscores = collect_missing_boxscores()

    # Step 4: Refresh lineup combo stats (for hot/cold combos)
    refresh_lineup_stats()

    # Step 5: Recompute synergy + value scores (for WOWY trends + projection model)
    refresh_synergy_data()

    logger.info("=" * 60)
    logger.info(f"TRENDS REFRESH COMPLETE — {new_boxscores} new boxscores added")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

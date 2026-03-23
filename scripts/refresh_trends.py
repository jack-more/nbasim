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

from config import DB_PATH, CURRENT_SEASON
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
SEASON_ID = CURRENT_SEASON


def refresh_recent_games():
    """Collect recent game scores — ESPN primary, BBRef fallback.

    ESPN's public scoreboard API works reliably from GitHub Actions IPs
    (unlike stats.nba.com and Basketball-Reference which block datacenter traffic).
    We fetch 21 days of history to ensure no gaps.
    """
    logger.info("=== Refreshing game scores ===")

    # ── PRIMARY: ESPN (works from cloud IPs) ──
    try:
        from collectors.games_espn import ESPNGameCollector
        espn = ESPNGameCollector(DB_PATH)
        new_count = espn.update_games_table(SEASON_ID, days=21)
        logger.info(f"ESPN: {new_count} games added/updated")
        if new_count >= 0:
            # Verify we actually have recent data (fail if DB is stale)
            _verify_game_freshness()
            return
    except Exception as e:
        logger.warning(f"ESPN game collection failed: {e}")

    # ── FALLBACK: Basketball-Reference ──
    try:
        from collectors.games_bbref import BRefGameCollector
        bbref = BRefGameCollector(DB_PATH)
        new_count = bbref.update_games_table(SEASON_ID)
        logger.info(f"Basketball-Reference fallback: {new_count} games added/updated")
        _verify_game_freshness()
        return
    except Exception as e:
        logger.warning(f"Basketball-Reference also failed: {e}")

    # ── LAST RESORT: NBA API ──
    try:
        game_collector = GameCollector(DB_PATH)
        game_collector.collect_for_season(SEASON_ID)
        logger.info("Game schedule refreshed via NBA API (last resort).")
        _verify_game_freshness()
    except Exception as e:
        logger.error(
            f"ALL THREE game data sources failed! ESPN, BBRef, NBA API. "
            f"The model is flying blind on recent form. Last error: {e}"
        )
        # Raise so the pipeline step actually fails (no more silent degradation)
        raise RuntimeError(
            "Game score collection failed from all sources. "
            "Recent NRtg and momentum data is STALE."
        ) from e


def _verify_game_freshness():
    """Verify the DB has game scores within the last 4 days.

    If the most recent scored game is more than 4 days old (outside of
    All-Star break), something is wrong and we should flag it.
    """
    from datetime import datetime, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=4)).strftime("%Y-%m-%d")
    recent = read_query(
        "SELECT COUNT(*) as cnt FROM games "
        "WHERE season_id = ? AND game_date >= ? AND home_score IS NOT NULL",
        DB_PATH, [SEASON_ID, cutoff],
    )
    count = int(recent.iloc[0]["cnt"]) if not recent.empty else 0
    if count == 0:
        logger.warning(
            f"⚠️  No game scores found after {cutoff}! "
            f"Trailing NRtg and momentum data may be stale."
        )
    else:
        logger.info(f"Game freshness check: {count} scored games in last 4 days ✓")


def collect_missing_boxscores():
    """Collect boxscores for recent games not yet in player_game_stats.

    Uses stats.nba.com — hard 5-minute timeout on the entire loop so it
    can't hang forever when datacenter IPs are blocked.
    """
    import signal

    class _BoxscoreTimeout(BaseException):
        pass

    def _handler(signum, frame):
        raise _BoxscoreTimeout("Boxscore collection exceeded 5-minute limit")

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

    # Hard 5-minute wall clock limit on entire boxscore loop
    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(300)
    success = 0
    try:
        bs_collector = BoxScoreCollector(DB_PATH)
        for game_id in sorted(missing):
            try:
                bs_collector.collect_game_boxscore(game_id)
                success += 1
                logger.info(f"  ✓ {game_id} ({success}/{len(missing)})")
            except _BoxscoreTimeout:
                raise  # Let the timeout propagate
            except Exception as e:
                logger.warning(f"  ✗ {game_id}: {e}")
    except _BoxscoreTimeout:
        logger.warning(f"Boxscore collection timed out after 5 min — got {success}/{len(missing)}")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

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

    Returns True if data was actually refreshed, False if timed out or failed.
    """
    import signal

    class _Timeout(BaseException):
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
        return True
    except _Timeout as e:
        logger.warning(f"Roster refresh timed out (DATA IS STALE): {e}")
        return False
    except Exception as e:
        logger.warning(f"Roster/stats refresh failed (DATA IS STALE): {e}")
        return False
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def _verify_boxscore_freshness():
    """Check if player_game_stats has data within the last 14 days.

    If boxscore data is more than 14 days old, the MOJI and SYN signals
    (60% of the model) are running on stale player stats. Emit a loud
    warning so this is visible in CI logs and cannot be silently ignored.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
    try:
        result = read_query(
            """SELECT MAX(g.game_date) as latest
               FROM player_game_stats pgs
               JOIN games g ON pgs.game_id = g.game_id""",
            DB_PATH,
        )
        latest = result.iloc[0]["latest"] if not result.empty else None
        if latest is None or latest < cutoff:
            logger.error(
                "╔══════════════════════════════════════════════════════╗\n"
                "║  ⚠️  BOXSCORE DATA IS STALE!                        ║\n"
                f"║  Latest boxscore: {latest or 'NONE'}                       ║\n"
                f"║  Required: after {cutoff}                        ║\n"
                "║  MOJI + SYN signals (60%% of model) are UNRELIABLE  ║\n"
                "╚══════════════════════════════════════════════════════╝"
            )
        else:
            logger.info(f"Boxscore freshness check: latest = {latest} ✓")
    except Exception as e:
        logger.warning(f"Could not verify boxscore freshness: {e}")


def _nba_api_data_is_stale(max_age_days=3):
    """Check if stats.nba.com data needs refreshing.

    Returns True if player_season_stats hasn't been updated in max_age_days.
    Since stats.nba.com blocks datacenter IPs, we only attempt the refresh
    when data is actually stale — not every single run.
    """
    try:
        db_path = DB_PATH
        db_mtime = os.path.getmtime(db_path)
        # Check if any player_season_stats were updated recently by looking at
        # the DB file's modification time vs when we last successfully wrote stats
        marker = os.path.join(os.path.dirname(db_path), ".nba_api_last_refresh")
        if os.path.exists(marker):
            age_hours = (datetime.now(timezone.utc).timestamp() - os.path.getmtime(marker)) / 3600
            if age_hours < max_age_days * 24:
                logger.info(f"stats.nba.com data is {age_hours:.0f}h old (< {max_age_days}d) — skipping refresh")
                return False
        return True
    except Exception:
        return True  # If we can't tell, try to refresh


def _mark_nba_api_refreshed():
    """Touch marker file to record successful stats.nba.com refresh."""
    marker = os.path.join(os.path.dirname(DB_PATH), ".nba_api_last_refresh")
    with open(marker, "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())


def main():
    logger.info("=" * 60)
    logger.info("NBA SIM — DAILY TRENDS REFRESH")
    logger.info(f"Lookback: {LOOKBACK_DAYS} days | Season: {SEASON_ID}")
    logger.info("=" * 60)

    # Step 1: Refresh game scores from ESPN (reliable from cloud IPs)
    # This MUST succeed — everything else is optional.
    refresh_recent_games()

    # Step 2: stats.nba.com-dependent steps — only run when data is stale.
    # stats.nba.com blocks datacenter IPs, so these timeout regularly.
    # Entire block is wrapped in try/except so failures NEVER kill the script
    # (ESPN scores from step 1 must always get committed).
    new_boxscores = 0
    if _nba_api_data_is_stale(max_age_days=3):
        logger.info("=== stats.nba.com data is stale — attempting refresh ===")
        roster_ok = False
        try:
            roster_ok = refresh_rosters_and_stats()
            if roster_ok:
                # ONLY mark refreshed if data was actually collected
                _mark_nba_api_refreshed()
                logger.info("Marked stats.nba.com data as refreshed.")
            else:
                logger.warning(
                    "stats.nba.com refresh FAILED — NOT marking as fresh. "
                    "Will retry on next run."
                )
        except Exception as e:
            logger.warning(f"Roster refresh failed (non-fatal): {e}")

        try:
            new_boxscores = collect_missing_boxscores()
        except Exception as e:
            logger.warning(f"Boxscore collection failed (non-fatal): {e}")

        try:
            refresh_lineup_stats()
        except Exception as e:
            logger.warning(f"Lineup stats refresh failed (non-fatal): {e}")
    else:
        new_boxscores = 0

    # ── Staleness verification ──
    # Check if player_game_stats has data within the last 14 days.
    # If not, emit a loud warning so it's visible in CI logs.
    _verify_boxscore_freshness()

    # Step 3: Recompute synergy + value scores (local computation, always runs)
    refresh_synergy_data()

    logger.info("=" * 60)
    logger.info(f"TRENDS REFRESH COMPLETE — {new_boxscores} new boxscores added")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

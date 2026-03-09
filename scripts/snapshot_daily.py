#!/usr/bin/env python3
"""
snapshot_daily.py — Daily MOJO snapshot + player potential model.

Captures every player's MOJO score and components daily, building a trajectory
database that reveals trends, hot/cold streaks, and role changes over time.

Also computes the "potential MOJO" — what a player WOULD score if given more
usage and minutes. The gap between current and potential MOJO identifies
"miscast" players like Donovan Clingan: high per-minute efficiency trapped
in a limited role by teammates who use possessions less effectively.

Designed to run once daily after generate_frontend.py in the pipeline.
"""

import sys
import os
import logging
import sqlite3
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from config import DB_PATH
from db.connection import read_query, get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("snapshot_daily")

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
SEASON_ID = "2025-26"


def _safe(val, typ=float):
    """Convert pandas/numpy value to native Python type for SQLite binding."""
    if val is None:
        return None
    try:
        import numpy as np
        if isinstance(val, (np.integer,)):
            return int(val)
        if isinstance(val, (np.floating,)):
            return float(val)
        if isinstance(val, (np.bool_,)):
            return bool(val)
    except ImportError:
        pass
    return typ(val)

# ── Usage decay model (mirrors generate_frontend.py) ──
USAGE_DECAY = 0.995        # TS% multiplier per 1% USG increase
USAGE_DECAY_DEF = 0.985    # Defensive archetypes decay faster
MIN_GAMES = 10             # Minimum games to compute potential
MIN_MINUTES = 10.0         # Minimum MPG to be considered


def snapshot_mojo_scores():
    """Capture today's MOJO + all components for every active player.

    Reads from player_value_scores + player_season_stats to build the snapshot.
    Also computes 5-game and 10-game per-minute trends from player_game_stats.
    """
    logger.info(f"=== MOJO Snapshot for {TODAY} ===")

    # Check if we already have today's snapshot
    existing = read_query(
        "SELECT COUNT(*) as cnt FROM mojo_snapshots WHERE snapshot_date = ?",
        DB_PATH, [TODAY]
    )
    if existing.iloc[0]["cnt"] > 0:
        logger.info(f"Snapshot for {TODAY} already exists — skipping")
        return

    # Get all active players with value scores
    players = read_query("""
        SELECT
            vs.player_id, vs.team_id, vs.base_value, vs.solo_impact,
            vs.two_man_synergy, vs.three_man_synergy, vs.four_man_synergy,
            vs.five_man_synergy, vs.composite_value, vs.archetype_fit_score,
            ps.minutes_per_game, ps.usg_pct, ps.ts_pct, ps.net_rating, ps.gp
        FROM player_value_scores vs
        JOIN player_season_stats ps ON vs.player_id = ps.player_id AND ps.season_id = ?
        WHERE vs.season_id = ?
    """, DB_PATH, [SEASON_ID, SEASON_ID])

    if players.empty:
        logger.warning("No player data found for snapshot")
        return

    # Build MOJO scores using the same formula as generate_frontend.py
    # We import compute_mojo_score and compute_mojo_range from generate_frontend
    try:
        sys.path.insert(0, PROJECT_ROOT)
        from generate_frontend import (
            compute_mojo_score, compute_mojo_range,
            _ORAPM_PERCENTILES, _DRAPM_PERCENTILES, _VALUE_SCORES,
        )
        has_frontend = True
    except Exception as e:
        logger.warning(f"Could not import generate_frontend: {e}")
        has_frontend = False

    # Compute per-player trends from recent games
    trends = _compute_player_trends()

    rows = []
    for _, p in players.iterrows():
        pid = int(p["player_id"])
        tid = int(p["team_id"]) if p["team_id"] else None

        # Compute MOJO via generate_frontend functions if available
        mojo = None
        mojo_floor = None
        mojo_ceiling = None
        raw_mojo = None
        ctx_mojo = None
        orapm_p = None
        drapm_p = None

        if has_frontend:
            try:
                # Build a row dict mimicking what compute_mojo_score expects
                row = {
                    "pts_pg": float(p.get("pts_pg", 0) or 0),
                    "ast_pg": float(p.get("ast_pg", 0) or 0),
                    "reb_pg": float(p.get("reb_pg", 0) or 0),
                    "stl_pg": float(p.get("stl_pg", 0) or 0),
                    "blk_pg": float(p.get("blk_pg", 0) or 0),
                    "ts_pct": float(p.get("ts_pct", 0) or 0) / 100.0 if float(p.get("ts_pct", 0) or 0) > 1 else float(p.get("ts_pct", 0) or 0),
                    "usg_pct": float(p.get("usg_pct", 0) or 0) / 100.0 if float(p.get("usg_pct", 0) or 0) > 1 else float(p.get("usg_pct", 0) or 0),
                    "off_rating": float(p.get("off_rating", 110) or 110),
                    "def_rating": float(p.get("def_rating", 110) or 110),
                    "net_rating": float(p.get("net_rating", 0) or 0),
                    "minutes_per_game": float(p.get("minutes_per_game", 0) or 0),
                    "player_id": pid,
                }
                mojo = int(compute_mojo_score(row))
                _range = compute_mojo_range(mojo, pid)
                mojo_floor = int(_range[0])
                mojo_ceiling = int(_range[1])

                orapm_p = _ORAPM_PERCENTILES.get(pid)
                drapm_p = _DRAPM_PERCENTILES.get(pid)
                if orapm_p is not None:
                    orapm_p = int(orapm_p)
                if drapm_p is not None:
                    drapm_p = int(drapm_p)
            except Exception as e:
                logger.debug(f"MOJO calc failed for {pid}: {e}")

        # Fallback: estimate MOJO from composite_value
        if mojo is None:
            composite = p.get("composite_value", 50) or 50
            mojo = int(33 + (composite / 100) * 66)
            mojo = max(33, min(99, mojo))

        trend_5g = trends.get(pid, {}).get("trend_5g")
        trend_10g = trends.get(pid, {}).get("trend_10g")

        rows.append((
            pid, TODAY, tid, mojo, mojo_floor, mojo_ceiling,
            raw_mojo, ctx_mojo,
            None, None,  # off_score, def_score (computed inline in frontend)
            orapm_p, drapm_p,
            _safe(p.get("composite_value")), _safe(p.get("base_value")),
            _safe(p.get("solo_impact")), _safe(p.get("two_man_synergy")),
            _safe(p.get("three_man_synergy")), _safe(p.get("four_man_synergy")),
            _safe(p.get("five_man_synergy")), _safe(p.get("archetype_fit_score")),
            _safe(p.get("minutes_per_game")), _safe(p.get("usg_pct")),
            _safe(p.get("ts_pct")), _safe(p.get("net_rating")),
            _safe(p.get("gp"), int),
            trend_5g, trend_10g,
        ))

    # Insert all snapshots (FK off — some value_scores players may not be in players table)
    with get_connection(DB_PATH, foreign_keys=False) as conn:
        conn.executemany("""
            INSERT OR REPLACE INTO mojo_snapshots (
                player_id, snapshot_date, team_id, mojo_score, mojo_floor, mojo_ceiling,
                raw_mojo, contextual_mojo,
                off_score, def_score,
                orapm_pctl, drapm_pctl,
                composite_value, base_value,
                solo_impact, two_man_synergy,
                three_man_synergy, four_man_synergy,
                five_man_synergy, archetype_fit,
                minutes_per_game, usg_pct,
                ts_pct, net_rating,
                games_played,
                trend_5g, trend_10g
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)

    logger.info(f"Saved {len(rows)} MOJO snapshots for {TODAY}")
    return len(rows)


def _compute_player_trends():
    """Compute 5-game and 10-game performance trends per player.

    Uses per-minute production (pts+ast+reb / minutes) to normalize
    across different minute loads. A rising trend means the player
    is producing MORE per minute recently vs their season average.
    """
    recent_games = read_query("""
        SELECT
            pgs.player_id,
            g.game_date,
            pgs.minutes,
            pgs.pts, pgs.ast, pgs.reb,
            pgs.usg_pct, pgs.ts_pct, pgs.net_rating
        FROM player_game_stats pgs
        JOIN games g ON pgs.game_id = g.game_id
        WHERE g.season_id = ?
        AND pgs.minutes >= 5
        ORDER BY pgs.player_id, g.game_date DESC
    """, DB_PATH, [SEASON_ID])

    if recent_games.empty:
        return {}

    trends = {}
    for pid, group in recent_games.groupby("player_id"):
        if len(group) < 5:
            continue

        # Per-minute production index
        group = group.head(20)  # Last 20 games max
        group["pm_index"] = (group["pts"] + group["ast"] + group["reb"]) / group["minutes"].clip(lower=1)

        season_avg = group["pm_index"].mean()
        if season_avg == 0:
            continue

        last_5_avg = group.head(5)["pm_index"].mean()
        last_10_avg = group.head(10)["pm_index"].mean()

        # Trend as % above/below season average
        trends[int(pid)] = {
            "trend_5g": round((last_5_avg / season_avg - 1) * 100, 1),
            "trend_10g": round((last_10_avg / season_avg - 1) * 100, 1),
        }

    return trends


def compute_player_potential():
    """Compute potential MOJO for every player — the Clingan detector.

    For each player, asks: "If this player got more minutes and higher usage,
    what would their efficiency and MOJO look like?"

    Uses per-minute and per-possession rates from actual game data, then
    models efficiency decay at higher usage via the USAGE_DECAY constant.

    Identifies:
    - High per-min efficiency + low minutes = minutes headroom
    - High TS% + low USG = usage headroom
    - Teammate with lower efficiency + higher USG = usage waste
    - Large gap between current MOJO and potential = breakout candidate
    """
    logger.info("=== Computing player potential model ===")

    # Get per-minute rates from game logs (more granular than season averages)
    players = read_query("""
        SELECT
            ps.player_id, ps.team_id, ps.gp,
            ps.minutes_per_game, ps.usg_pct, ps.ts_pct,
            ps.pts_per36, ps.reb_per36, ps.ast_per36,
            ps.stl_per36, ps.blk_per36, ps.tov_per36,
            ps.off_rating, ps.def_rating, ps.net_rating,
            ps.efg_pct, ps.fg3_pct
        FROM player_season_stats ps
        WHERE ps.season_id = ? AND ps.gp >= ? AND ps.minutes_per_game >= ?
    """, DB_PATH, [SEASON_ID, MIN_GAMES, MIN_MINUTES])

    if players.empty:
        logger.warning("No eligible players for potential model")
        return

    # Get team usage distribution for teammate waste analysis
    team_usage = read_query("""
        SELECT
            ps.team_id, ps.player_id, ps.usg_pct, ps.ts_pct,
            ps.minutes_per_game, ps.gp
        FROM player_season_stats ps
        WHERE ps.season_id = ? AND ps.gp >= 10 AND ps.minutes_per_game >= 10
    """, DB_PATH, [SEASON_ID])

    # Build team usage maps
    team_players = {}
    for _, row in team_usage.iterrows():
        tid = int(row["team_id"])
        if tid not in team_players:
            team_players[tid] = []
        team_players[tid].append({
            "pid": int(row["player_id"]),
            "usg": float(row["usg_pct"] or 0),
            "ts": float(row["ts_pct"] or 0),
            "mpg": float(row["minutes_per_game"] or 0),
        })

    # Get archetype info for decay rate selection
    archetypes = read_query("""
        SELECT player_id, archetype_label
        FROM player_archetypes
        WHERE season_id = ?
    """, DB_PATH, [SEASON_ID])
    arch_map = dict(zip(archetypes["player_id"].astype(int), archetypes["archetype_label"]))

    DEFENSIVE_ARCHS = {"Rim-Protector", "Switchable-Defender", "Point-of-Attack-Defender",
                       "Wing-Stopper", "Paint-Anchor"}

    rows = []
    for _, p in players.iterrows():
        pid = int(p["player_id"])
        tid = int(p["team_id"]) if p["team_id"] else None
        current_usg = float(p["usg_pct"] or 0)
        current_ts = float(p["ts_pct"] or 0)
        current_mpg = float(p["minutes_per_game"] or 0)

        if current_usg == 0 or current_ts == 0 or current_mpg == 0:
            continue

        # Per-minute efficiency score (weighted production per 36)
        per36_prod = (
            (p.get("pts_per36", 0) or 0) * 1.0 +
            (p.get("reb_per36", 0) or 0) * 0.7 +
            (p.get("ast_per36", 0) or 0) * 1.2 +
            (p.get("stl_per36", 0) or 0) * 2.0 +
            (p.get("blk_per36", 0) or 0) * 1.5 -
            (p.get("tov_per36", 0) or 0) * 1.0
        )

        # ── Minutes headroom ──
        # How many more minutes could this player realistically get?
        max_minutes = 36.0  # realistic max for non-iron-man players
        minutes_headroom = max(0, max_minutes - current_mpg)

        # ── Usage headroom ──
        # How much higher could usage go before efficiency decay makes it negative EV?
        # NOTE: USG and TS stored as decimals (0.30 = 30%, 0.56 = 56%)
        arch = arch_map.get(pid, "")
        decay = USAGE_DECAY_DEF if arch in DEFENSIVE_ARCHS else USAGE_DECAY

        # Find the usage rate where TS% would drop to league average (~0.56)
        league_avg_ts = 0.560
        max_usg = current_usg
        projected_ts = current_ts
        while projected_ts > league_avg_ts and max_usg < 0.35:
            max_usg += 0.005  # 0.5% increments
            usg_increase = (max_usg - current_usg) * 100  # convert to percentage points for decay
            projected_ts = current_ts * (decay ** usg_increase)

        usage_headroom = max(0, (max_usg - current_usg) * 100)  # as percentage points

        # ── Project at higher role ──
        projected_usg = min(current_usg + (usage_headroom * 0.5) / 100, 0.30)  # conservative
        projected_mpg = min(current_mpg + minutes_headroom * 0.4, 34)  # conservative
        usg_increase_pct = (projected_usg - current_usg) * 100
        projected_ts_final = current_ts * (decay ** usg_increase_pct)

        # Per-possession efficiency (production adjusted for projected minutes)
        mins_multiplier = projected_mpg / max(current_mpg, 1)
        per_poss_eff = per36_prod * (projected_ts_final / max(current_ts, 1))

        # ── Teammate usage waste ──
        # Are there teammates with HIGHER usage but LOWER TS%?
        # Values in decimal form (0.30 = 30% USG, 0.56 = 56% TS)
        waste = 0.0
        if tid and tid in team_players:
            for tm in team_players[tid]:
                if tm["pid"] == pid:
                    continue
                # Teammate uses more possessions less efficiently
                # 0.02 = 2 percentage points of TS% difference threshold
                if tm["usg"] > current_usg and tm["ts"] < current_ts - 0.02:
                    usage_diff = (tm["usg"] - current_usg) * 100  # as percentage points
                    eff_diff = (current_ts - tm["ts"]) * 100  # as percentage points
                    waste += (usage_diff * eff_diff * tm["mpg"]) / 100.0

        # ── Compute potential MOJO (simplified projection) ──
        # Scale per-36 production by projected minutes/usage bump
        projected_per36 = per36_prod * (projected_ts_final / max(current_ts, 0.01))
        # Map to MOJO scale (rough: per36_prod of 30 ≈ MOJO 80, 20 ≈ 60, 10 ≈ 45)
        potential_raw = 33 + (projected_per36 / 40) * 66
        potential_mojo = max(33, min(99, int(potential_raw)))

        # Get current MOJO from today's snapshot
        current_snap = read_query(
            "SELECT mojo_score FROM mojo_snapshots WHERE player_id = ? AND snapshot_date = ?",
            DB_PATH, [pid, TODAY]
        )
        current_mojo = int(current_snap.iloc[0]["mojo_score"]) if not current_snap.empty else None

        if current_mojo is None:
            continue

        mojo_gap = potential_mojo - current_mojo

        # ── Breakout signal ──
        # Combines: mojo_gap, minutes_headroom, usage_headroom, teammate_waste
        breakout = (
            mojo_gap * 0.4 +
            minutes_headroom * 0.2 +
            usage_headroom * 0.15 +
            waste * 0.25
        )

        # Role mismatch flag: high efficiency + low minutes + gap > 10
        role_mismatch = 1 if (current_ts > 58 and current_mpg < 25 and mojo_gap > 10) else 0

        rows.append((
            pid, TODAY, tid,
            current_mojo, potential_mojo, mojo_gap,
            round(current_usg, 3), round(projected_usg, 3),
            round(current_mpg, 1), round(projected_mpg, 1),
            round(per36_prod, 2),
            round(per_poss_eff, 2),
            round(current_ts, 3),
            round(projected_ts_final, 3),
            round(usage_headroom, 1),
            round(minutes_headroom, 1),
            round(waste, 2),
            role_mismatch,
            round(breakout, 2),
            None,  # notes
        ))

    with get_connection(DB_PATH, foreign_keys=False) as conn:
        conn.executemany("""
            INSERT OR REPLACE INTO player_potential (
                player_id, snapshot_date, team_id,
                current_mojo, potential_mojo, mojo_gap,
                current_usg, projected_usg,
                current_mpg, projected_mpg,
                per_min_efficiency, per_poss_efficiency,
                ts_at_current_usg, projected_ts,
                usage_headroom, minutes_headroom,
                teammate_usg_waste, role_mismatch_flag,
                breakout_signal, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)

    # Log top breakout candidates
    role_mismatches = [r for r in rows if r[17] == 1]  # role_mismatch_flag
    top_gaps = sorted(rows, key=lambda r: r[5], reverse=True)[:10]  # mojo_gap

    logger.info(f"Computed potential for {len(rows)} players")
    logger.info(f"  Role mismatches found: {len(role_mismatches)}")
    logger.info(f"  Top 10 MOJO gaps:")
    for r in top_gaps:
        name = _get_player_name(r[0])
        logger.info(f"    {name}: current={r[3]}, potential={r[4]}, gap=+{r[5]}, "
                     f"USG {r[6]*100:.1f}%→{r[7]*100:.1f}%, MPG {r[8]}→{r[9]}, "
                     f"TS {r[12]*100:.1f}%→{r[13]*100:.1f}%, waste={r[16]}")

    return len(rows)


def _get_player_name(player_id):
    """Look up player name from DB."""
    result = read_query(
        "SELECT full_name FROM players WHERE player_id = ?",
        DB_PATH, [player_id]
    )
    if not result.empty:
        return result.iloc[0]["full_name"]
    return f"PID:{player_id}"


def main():
    logger.info("=" * 60)
    logger.info("NBA SIM — DAILY INTELLIGENCE SNAPSHOT")
    logger.info(f"Date: {TODAY} | Season: {SEASON_ID}")
    logger.info("=" * 60)

    # Step 1: Snapshot all MOJO scores
    n_snapshots = snapshot_mojo_scores()

    # Step 2: Compute potential model (depends on snapshots)
    if n_snapshots:
        n_potential = compute_player_potential()
    else:
        logger.info("Skipping potential model — no snapshots taken")

    logger.info("=" * 60)
    logger.info("INTELLIGENCE SNAPSHOT COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

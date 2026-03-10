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

# ── Potential model constants ──
MIN_GAMES = 10             # Minimum games to compute potential
MIN_MINUTES = 10.0         # Minimum MPG to be considered
MIN_GAMES_FOR_CURVE = 20   # Need enough games to fit a reliable USG-efficiency curve


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


def _compute_usg_efficiency_curves():
    """Build empirical USG vs TS% curves per player from game logs.

    For each player, splits their games into low/high USG halves and
    measures the ACTUAL efficiency relationship. This captures:
    - Load-bearers (Giannis, Trae): TS stays flat or RISES with more usage
    - Role players (Clingan): TS drops when usage increases
    - Volume scorers (SGA): moderate decay at extreme usage

    Returns dict: player_id → {
        "low_usg": avg USG in low-usage games,
        "low_ts": avg TS% in low-usage games,
        "high_usg": avg USG in high-usage games,
        "high_ts": avg TS% in high-usage games,
        "ts_per_usg": TS% change per 1% USG increase (negative = decay, positive = load-bearer),
        "is_load_bearer": True if player gets MORE efficient at higher usage,
        "n_games": number of qualifying games,
    }
    """
    logger.info("  Computing empirical USG-efficiency curves from game logs...")

    game_data = read_query("""
        SELECT pgs.player_id, pgs.usg_pct, pgs.ts_pct, pgs.minutes, pgs.pts
        FROM player_game_stats pgs
        JOIN games g ON pgs.game_id = g.game_id
        WHERE g.season_id = ? AND pgs.minutes >= 15
    """, DB_PATH, [SEASON_ID])

    if game_data.empty:
        return {}

    curves = {}
    for pid, group in game_data.groupby("player_id"):
        pid = int(pid)
        if len(group) < MIN_GAMES_FOR_CURVE:
            continue

        median_usg = group["usg_pct"].median()
        low = group[group["usg_pct"] <= median_usg]
        high = group[group["usg_pct"] > median_usg]

        if len(low) < 5 or len(high) < 5:
            continue

        low_usg = float(low["usg_pct"].mean())
        low_ts = float(low["ts_pct"].mean())
        high_usg = float(high["usg_pct"].mean())
        high_ts = float(high["ts_pct"].mean())

        usg_diff = (high_usg - low_usg) * 100  # in percentage points
        ts_diff = (high_ts - low_ts) * 100  # in percentage points

        if usg_diff < 1:  # need meaningful USG spread
            continue

        ts_per_usg = ts_diff / usg_diff  # TS% change per 1% USG increase

        curves[pid] = {
            "low_usg": low_usg,
            "low_ts": low_ts,
            "high_usg": high_usg,
            "high_ts": high_ts,
            "ts_per_usg": ts_per_usg,
            "is_load_bearer": ts_per_usg > -0.5,  # flat or positive = can handle load
            "n_games": len(group),
        }

    load_bearers = sum(1 for c in curves.values() if c["is_load_bearer"])
    logger.info(f"  Built curves for {len(curves)} players — {load_bearers} are load-bearers")
    return curves


def _compute_play_type_context():
    """Scheme-aware analysis: play type advantages, scheme alignment, teammate quality.

    For each player, evaluates:
    1. play_type_advantage: weighted PPP across their best play types vs league avg
       (identifies WHAT they're good at, not just raw USG vs TS)
    2. scheme_alignment: does the team's play type distribution support their strengths?
       (Clingan is elite in PnR Roll Man/Cuts, but Portland barely runs those)
    3. dependent_quality: for play types that need teammates (PnR Roll Man needs
       good ball handlers), how well do teammates create?

    Returns: dict[player_id] → {
        "advantage": float (>1.0 = above avg, <1.0 = below avg),
        "scheme_fit": float (0-1, 1.0 = perfect alignment),
        "dependent_boost": float (>0 = teammates help, <0 = teammates hurt),
        "best_plays": list of (play_type, ppp) top 3,
        "wasted_plays": list of (play_type, ppp) — elite plays team doesn't run,
        "detail": str description
    }
    """
    logger.info("  Computing scheme-aware play type context...")

    # Load player play types
    player_pts = read_query("""
        SELECT player_id, play_type, poss_pct, ppp, possessions
        FROM player_playtypes
        WHERE season_id = ? AND type_grouping = 'Offensive' AND possessions > 0
    """, DB_PATH, [SEASON_ID])

    if player_pts.empty:
        logger.warning("  No play type data available — skipping scheme context")
        return {}

    # Load team play types for scheme alignment
    team_pts = read_query("""
        SELECT team_id, play_type, poss_pct, ppp, possessions
        FROM team_playtypes
        WHERE season_id = ? AND type_grouping = 'Offensive' AND possessions > 0
    """, DB_PATH, [SEASON_ID])

    # Player-team mapping
    player_teams = read_query("""
        SELECT player_id, team_id FROM player_season_stats
        WHERE season_id = ? AND gp >= 10
    """, DB_PATH, [SEASON_ID])
    pid_to_tid = dict(zip(player_teams["player_id"].astype(int), player_teams["team_id"].astype(int)))

    # League avg PPP per play type (possession-weighted)
    league_avg = {}
    for pt, group in player_pts.groupby("play_type"):
        total_poss = group["possessions"].sum()
        if total_poss > 0:
            league_avg[pt] = float((group["ppp"] * group["possessions"]).sum() / total_poss)

    # Team play type distributions: team_id → {play_type → poss_pct}
    team_schemes = {}
    for tid, group in team_pts.groupby("team_id"):
        tid = int(tid)
        total_poss = group["possessions"].sum()
        team_schemes[tid] = {}
        for _, row in group.iterrows():
            team_schemes[tid][row["play_type"]] = {
                "poss_share": float(row["possessions"]) / total_poss if total_poss > 0 else 0,
                "ppp": float(row["ppp"]),
            }

    # Team PnR Ball Handler quality (for PnR Roll Man dependents)
    team_pnr_quality = {}
    for tid, scheme in team_schemes.items():
        pnr_bh = scheme.get("PRBallHandler", {})
        team_pnr_quality[tid] = pnr_bh.get("ppp", 0.88)  # league avg ~0.879

    # Dependent play types: play type → what teammate quality it depends on
    PLAY_DEPENDENCIES = {
        "PRRollMan": "PRBallHandler",  # roll man needs good ball handlers
        "Spotup": "PRBallHandler",     # spot-up often created off PnR penetration
        "Cut": "PRBallHandler",        # cuts created by ball movement
    }

    # Per-player context
    context = {}
    for pid, group in player_pts.groupby("player_id"):
        pid = int(pid)
        tid = pid_to_tid.get(pid)
        if tid is None:
            continue

        total_poss = group["possessions"].sum()
        if total_poss == 0:
            continue

        # 1. Play type advantage: weighted PPP vs league average
        weighted_advantage = 0
        for _, row in group.iterrows():
            pt = row["play_type"]
            avg = league_avg.get(pt, 0.95)
            if avg > 0:
                weighted_advantage += (float(row["ppp"]) / avg) * (float(row["possessions"]) / total_poss)

        # 2. Best play types (by PPP relative to league avg)
        plays_rated = []
        for _, row in group.iterrows():
            pt = row["play_type"]
            avg = league_avg.get(pt, 0.95)
            plays_rated.append((pt, float(row["ppp"]), float(row["ppp"]) / avg if avg > 0 else 1.0, float(row["possessions"])))
        plays_rated.sort(key=lambda x: x[2], reverse=True)
        best_plays = [(p[0], p[1]) for p in plays_rated[:3]]

        # 3. Scheme alignment: do the team's high-volume play types match player strengths?
        scheme = team_schemes.get(tid, {})
        if not scheme:
            scheme_fit = 0.5  # neutral
        else:
            # For each play type, multiply (player PPP advantage) × (team possession share)
            # High score = team gives lots of possessions to play types this player is good at
            fit_score = 0
            total_scheme_share = 0
            for pt_info in plays_rated:
                pt_name = pt_info[0]
                pt_advantage = pt_info[2]  # PPP / league_avg
                team_share = scheme.get(pt_name, {}).get("poss_share", 0)
                fit_score += pt_advantage * team_share
                total_scheme_share += team_share
            scheme_fit = fit_score / total_scheme_share if total_scheme_share > 0 else 0.5

        # 4. Identify wasted talent: play types where player is elite but team barely uses them
        wasted_plays = []
        for pt_info in plays_rated:
            pt_name, pt_ppp, pt_ratio, pt_poss = pt_info
            if pt_ratio > 1.15:  # 15% above league avg = elite
                team_share = scheme.get(pt_name, {}).get("poss_share", 0)
                if team_share < 0.08:  # team runs this less than 8% of possessions
                    wasted_plays.append((pt_name, pt_ppp))

        # 5. Dependent play quality: does the team support this player's key play types?
        dependent_boost = 0
        for _, row in group.iterrows():
            pt = row["play_type"]
            dep_type = PLAY_DEPENDENCIES.get(pt)
            if dep_type and tid in team_schemes:
                team_dep_ppp = team_schemes[tid].get(dep_type, {}).get("ppp", 0.88)
                dep_avg = league_avg.get(dep_type, 0.88)
                # If team's PnR BH is above avg → boost for roll man
                # If below avg → penalty
                quality_diff = (team_dep_ppp - dep_avg) / dep_avg if dep_avg > 0 else 0
                play_weight = float(row["possessions"]) / total_poss
                dependent_boost += quality_diff * play_weight * 10  # scale to meaningful range

        # Build detail string
        best_str = ", ".join(f"{p[0]}({p[1]:.3f})" for p in best_plays)
        detail_parts = [f"Best: {best_str}", f"SchFit={scheme_fit:.2f}"]
        if wasted_plays:
            waste_str = ", ".join(f"{p[0]}({p[1]:.3f})" for p in wasted_plays)
            detail_parts.append(f"Wasted: {waste_str}")
        if abs(dependent_boost) > 0.5:
            detail_parts.append(f"DepQ={dependent_boost:+.1f}")

        context[pid] = {
            "advantage": weighted_advantage,
            "scheme_fit": scheme_fit,
            "dependent_boost": dependent_boost,
            "best_plays": best_plays,
            "wasted_plays": wasted_plays,
            "detail": " | ".join(detail_parts),
        }

    logger.info(f"  Play type context computed for {len(context)} players")
    scheme_mismatches = sum(1 for c in context.values() if c["scheme_fit"] < 0.90)
    wasted_talent = sum(1 for c in context.values() if len(c["wasted_plays"]) > 0)
    logger.info(f"  Scheme mismatches (<0.90 fit): {scheme_mismatches}")
    logger.info(f"  Players with wasted elite play types: {wasted_talent}")

    return context


def compute_player_potential():
    """Compute potential MOJO for every player — the Clingan detector + inverse Clingan.

    Uses EMPIRICAL per-player USG-efficiency curves from actual game data instead of
    a uniform decay constant. This correctly handles:

    - Clingan-type (role player): efficient at low usage, decays at higher usage
    - Inverse Clingan (Giannis/Trae): NEEDS high usage to be efficient, gets WORSE
      with fewer touches. These players have a higher floor when given more load.
    - Volume stars (SGA): moderate decay at extreme usage but still productive

    Also identifies teammate usage waste — players who hog possessions less efficiently
    than a teammate who could use them better.

    NEW: Scheme-aware analysis layers in play type advantages, coaching scheme
    alignment, and dependent play type quality (e.g., PnR Roll Man needs good
    ball handlers) to produce a richer potential assessment.
    """
    logger.info("=== Computing player potential model ===")

    # Build empirical USG-efficiency curves from game logs
    usg_curves = _compute_usg_efficiency_curves()

    # Build scheme-aware play type context
    play_context = _compute_play_type_context()

    # Get season stats
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
    # Includes def_rating for 70/30 TS%/defense blended waste metric
    team_usage = read_query("""
        SELECT
            ps.team_id, ps.player_id, ps.usg_pct, ps.ts_pct,
            ps.minutes_per_game, ps.gp, ps.def_rating
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
            "drtg": float(row["def_rating"] or 112),  # default ~league avg
        })

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
        max_minutes = 36.0
        minutes_headroom = max(0, max_minutes - current_mpg)

        # ── Usage headroom (using EMPIRICAL curve, not fake decay constant) ──
        curve = usg_curves.get(pid)
        league_avg_ts = 0.560

        if curve:
            ts_per_usg = curve["ts_per_usg"]  # TS% change per 1% USG increase (can be positive!)

            if ts_per_usg >= 0:
                # LOAD-BEARER: efficiency stays flat or improves with usage
                # They can handle up to 35% USG without TS dropping below league avg
                max_usg = 0.35
                projected_ts_at_max = current_ts + ts_per_usg * (max_usg - current_usg) * 100
                # But cap: even load-bearers probably won't improve forever
                projected_ts_at_max = min(projected_ts_at_max, current_ts + 0.05)
            else:
                # ROLE PLAYER / VOLUME SCORER: find where TS would drop to league avg
                if current_ts > league_avg_ts:
                    usg_room_pct = (current_ts - league_avg_ts) * 100 / abs(ts_per_usg)
                    max_usg = min(0.35, current_usg + usg_room_pct / 100)
                else:
                    max_usg = current_usg  # already at or below league avg
                projected_ts_at_max = current_ts + ts_per_usg * (max_usg - current_usg) * 100

            usage_headroom = max(0, (max_usg - current_usg) * 100)
        else:
            # No curve data — use conservative default decay
            usage_headroom = 0
            projected_ts_at_max = current_ts

        # ── Project at higher role ──
        projected_usg = min(current_usg + (usage_headroom * 0.5) / 100, 0.32)
        projected_mpg = min(current_mpg + minutes_headroom * 0.4, 34)

        if curve:
            ts_change = curve["ts_per_usg"] * (projected_usg - current_usg) * 100
            projected_ts_final = min(current_ts + ts_change / 100, current_ts + 0.05)
            projected_ts_final = max(projected_ts_final, league_avg_ts - 0.02)
        else:
            projected_ts_final = current_ts

        # Per-possession efficiency at projected role
        per_poss_eff = per36_prod * (projected_ts_final / max(current_ts, 0.01))

        # ── Teammate usage waste (70% TS + 30% defense blended) ──
        # A player burning possessions at bad TS% but anchoring the defense
        # isn't as wasteful — their defensive contribution partially offsets
        # the offensive inefficiency.
        current_drtg = float(p.get("def_rating", 112) or 112)
        waste = 0.0
        if tid and tid in team_players:
            for tm in team_players[tid]:
                if tm["pid"] == pid:
                    continue
                if tm["usg"] > current_usg and tm["ts"] < current_ts - 0.02:
                    usage_diff = (tm["usg"] - current_usg) * 100

                    # 70% offensive gap (TS%) + 30% defensive gap (DRtg, normalized)
                    # Lower DRtg = better defense. If teammate has lower DRtg,
                    # their defensive value reduces the waste.
                    off_gap = (current_ts - tm["ts"]) * 100  # positive = player better offensively
                    def_gap = (tm["drtg"] - current_drtg) / 100.0 * 100  # normalized to TS% scale
                    # If teammate has LOWER DRtg (better D), def_gap is negative → reduces waste
                    # If teammate has HIGHER DRtg (worse D), def_gap is positive → adds waste
                    blended_gap = 0.70 * off_gap + 0.30 * def_gap

                    if blended_gap > 0:
                        waste += (usage_diff * blended_gap * tm["mpg"]) / 100.0

        # ── Compute potential MOJO ──
        projected_per36 = per36_prod * (projected_ts_final / max(current_ts, 0.01))
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

        # ── Scheme-aware context ──
        ctx = play_context.get(pid, {})
        scheme_fit = ctx.get("scheme_fit", 0.5)
        play_advantage = ctx.get("advantage", 1.0)
        dependent_boost = ctx.get("dependent_boost", 0)
        wasted_plays = ctx.get("wasted_plays", [])

        # Adjust potential_mojo by scheme context:
        # - Elite play types that team doesn't use → potential is HIGHER (talent wasted)
        # - Poor scheme fit → player could be better elsewhere, cap potential gain
        if wasted_plays:
            # Each wasted elite play type adds potential MOJO (team isn't leveraging talent)
            potential_mojo = min(99, potential_mojo + len(wasted_plays) * 2)
            mojo_gap = potential_mojo - current_mojo

        # Dependent play quality adjusts potential (e.g., bad PnR BH hurts Roll Man ceiling)
        if dependent_boost < -1.0:
            # Teammates are HURTING this player's production in key play types
            potential_mojo = min(99, potential_mojo + abs(int(dependent_boost)))
            mojo_gap = potential_mojo - current_mojo

        # ── Breakout signal (scheme-aware) ──
        is_load_bearer = curve["is_load_bearer"] if curve else False
        breakout = (
            mojo_gap * 0.30 +
            minutes_headroom * 0.10 +
            usage_headroom * 0.10 +
            waste * 0.15 +
            (5.0 if is_load_bearer and current_mpg < 30 else 0) +
            # Scheme-aware factors:
            (play_advantage - 1.0) * 20 +  # play type advantage above league avg
            max(0, (1.0 - scheme_fit) * 15) +  # scheme mismatch bonus (talent being wasted)
            len(wasted_plays) * 3.0 +  # each wasted elite play type
            abs(min(0, dependent_boost)) * 2.0  # bad teammate dependency
        )

        # Role mismatch: high efficiency + low minutes/usage + gap > 10
        # OR: scheme mismatch + elite play types going unused
        role_mismatch = 1 if (
            (current_ts > 0.58 and current_mpg < 25 and mojo_gap > 10) or
            (scheme_fit < 0.85 and len(wasted_plays) >= 2 and mojo_gap > 5)
        ) else 0

        # Build notes with curve info + scheme context
        notes_parts = []
        if curve:
            if curve["is_load_bearer"]:
                notes_parts.append(f"LOAD-BEARER: TS {curve['ts_per_usg']:+.2f}%/USG% ({curve['n_games']}g)")
            else:
                notes_parts.append(f"DECAY: TS {curve['ts_per_usg']:+.2f}%/USG% ({curve['n_games']}g)")
        if ctx.get("detail"):
            notes_parts.append(ctx["detail"])
        notes = " | ".join(notes_parts) if notes_parts else None

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
            notes,
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

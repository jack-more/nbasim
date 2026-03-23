#!/usr/bin/env python3
"""Generate the NBA SIM frontend HTML — mobile-first redesign with all features."""

import logging
import sqlite3
import sys
import os
import json
import math
import re
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from db.connection import read_query
from config import DB_PATH, CURRENT_SEASON

# Odds API removed — was returning 401 (expired key) and all lines come from
# RotoWire scrape anyway. Keeping stub functions so callers don't break.

# ─── Precomputed Value Scores Cache ──────────────────────────────
# Loaded once at module load — maps player_id → contextual scores
_VALUE_SCORES = {}


def _load_value_scores():
    """Load player_value_scores into memory for contextual MOJO blending."""
    global _VALUE_SCORES
    df = read_query(f"""
        SELECT player_id, base_value, solo_impact, two_man_synergy,
               three_man_synergy, four_man_synergy, five_man_synergy,
               composite_value, archetype_fit_score, minutes_weight
        FROM player_value_scores WHERE season_id = '{CURRENT_SEASON}'
    """, DB_PATH)
    if df.empty:
        return
    for _, row in df.iterrows():
        _VALUE_SCORES[int(row["player_id"])] = {
            "base": float(row["base_value"] or 50),
            "solo": float(row["solo_impact"] or 50),
            "two": float(row["two_man_synergy"] or 50),
            "three": float(row["three_man_synergy"] or 50),
            "four": float(row["four_man_synergy"] or 50),
            "five": float(row["five_man_synergy"] or 50),
            "fit": float(row["archetype_fit_score"] or 50),
            "composite": float(row["composite_value"] or 50),
            "minutes": float(row["minutes_weight"] or 20),
        }


_load_value_scores()

# ─── RAPM Data Cache ──────────────────────────────────────────────
# Raw RAPM values from nbarapm.com (517 players, updated daily).
# Defensive RAPM is used in the MOJO formula (38% weight via percentile rank).
# Total RAPM displayed on cards for context.
_RAPM_DATA = {}


def _load_rapm_data():
    """Load raw RAPM data from DB."""
    global _RAPM_DATA
    try:
        df = read_query("""
            SELECT player_id, player_name, team, rapm_total,
                   rapm_offense, rapm_defense, rapm_rank
            FROM player_rapm WHERE rapm_total IS NOT NULL
        """, DB_PATH)
    except (sqlite3.OperationalError, pd.errors.DatabaseError):
        return  # Table may not exist yet

    if df.empty:
        return
    for _, row in df.iterrows():
        _RAPM_DATA[int(row["player_id"])] = {
            "rapm": float(row["rapm_total"]),
            "rapm_off": float(row["rapm_offense"] or 0),
            "rapm_def": float(row["rapm_defense"] or 0),
            "rapm_rank": float(row["rapm_rank"] or 999),
        }


_load_rapm_data()

# ─── DRAPM Percentile Lookup ─────────────────────────────────────
# Maps player_id → defense score (33-99) based on league-wide
# defensive RAPM percentile rank. Used in MOJO formula at 38% weight.
_DRAPM_PERCENTILES = {}


def _build_drapm_percentiles():
    """Rank all players by defensive RAPM, map to 33-99 scale."""
    global _DRAPM_PERCENTILES
    drapm_vals = [(pid, info["rapm_def"]) for pid, info in _RAPM_DATA.items()
                  if info.get("rapm_def") is not None]
    if not drapm_vals:
        return
    # Sort by DRAPM ascending (worst → best)
    sorted_vals = sorted(drapm_vals, key=lambda x: x[1])
    n = len(sorted_vals)
    for rank, (pid, _) in enumerate(sorted_vals):
        pct = rank / (n - 1) if n > 1 else 0.5
        _DRAPM_PERCENTILES[pid] = int(33 + pct * 66)


_build_drapm_percentiles()

# ─── ORAPM Percentile Lookup ─────────────────────────────────────
# Maps player_id → offense score (33-99) based on league-wide
# offensive RAPM percentile rank. Used in MOJO formula at 75% of
# the offensive component (counting stats fill the remaining 25%).
_ORAPM_PERCENTILES = {}


def _build_orapm_percentiles():
    """Rank all players by offensive RAPM, map to 33-99 scale."""
    global _ORAPM_PERCENTILES
    orapm_vals = [(pid, info["rapm_off"]) for pid, info in _RAPM_DATA.items()
                  if info.get("rapm_off") is not None]
    if not orapm_vals:
        return
    # Sort by ORAPM ascending (worst → best)
    sorted_vals = sorted(orapm_vals, key=lambda x: x[1])
    n = len(sorted_vals)
    for rank, (pid, _) in enumerate(sorted_vals):
        pct = rank / (n - 1) if n > 1 else 0.5
        _ORAPM_PERCENTILES[pid] = int(33 + pct * 66)


_build_orapm_percentiles()

# ─── Play Type Intelligence Cache ────────────────────────────────
# Loaded at module load — enables scheme-aware usage redistribution.
# Maps player_id → {play_type: {ppp, poss_pct, possessions, poss_share}}
_PLAYER_PLAY_PROFILE = {}
# League average PPP per offensive play type
_LEAGUE_AVG_PPP = {}
# Waste + potential intel from player_potential table
_waste_data = {}
_waste_data_loaded = False


def _sanitize_html_attr(val):
    """Escape a string for safe embedding inside an HTML attribute value (double-quoted).

    Handles the five critical characters that can break out of attributes or
    inject HTML/JS: & (must be first), <, >, ", '
    Also strips newlines/tabs that could break attribute formatting, and
    removes backticks which can be dangerous in older JS contexts.
    """
    s = str(val)
    s = s.replace("&", "&amp;")      # Must be first — prevents double-encoding
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    s = s.replace("'", "&#x27;")
    s = s.replace("`", "&#96;")
    s = s.replace("\n", " ")
    s = s.replace("\r", " ")
    s = s.replace("\t", " ")
    return s


def _load_waste_data():
    """Load teammate waste / MOJO gap / intel from player_potential."""
    global _waste_data, _waste_data_loaded
    if _waste_data_loaded:
        return
    _waste_data_loaded = True
    try:
        waste_df = read_query("""
            SELECT player_id, teammate_usg_waste, mojo_gap, breakout_signal,
                   role_mismatch_flag, notes
            FROM player_potential
            WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM player_potential)
        """, DB_PATH)
        for _, wr in waste_df.iterrows():
            raw_notes = str(wr["notes"] or "")
            _waste_data[int(wr["player_id"])] = {
                "waste": round(float(wr["teammate_usg_waste"] or 0), 1),
                "gap": int(wr["mojo_gap"] or 0),
                "breakout": round(float(wr["breakout_signal"] or 0), 1),
                "mismatch": int(wr["role_mismatch_flag"] or 0),
                "notes": _sanitize_html_attr(raw_notes),   # Safe for HTML attributes (f-strings)
                "notes_raw": raw_notes,                      # Raw for JSON serialization (JS handles escaping)
            }
    except (sqlite3.OperationalError, pd.errors.DatabaseError, KeyError):
        pass  # Table may not exist yet


def _load_play_profiles():
    """Load offensive play type profiles for play-type-aware usage redistribution.

    When a player goes OUT, their freed possessions aren't generic "usage" —
    they're specific play types (PnR Ball Handler, ISO, Spotup, etc.).
    Each remaining player absorbs those possessions with DIFFERENT efficiency
    depending on whether those play types match their strengths.
    """
    global _PLAYER_PLAY_PROFILE, _LEAGUE_AVG_PPP

    try:
        df = read_query(f"""
            SELECT player_id, play_type, poss_pct, ppp, possessions
            FROM player_playtypes
            WHERE season_id = '{CURRENT_SEASON}' AND type_grouping = 'Offensive'
                  AND possessions > 0
        """, DB_PATH)
    except (sqlite3.OperationalError, pd.errors.DatabaseError):
        return  # Table may not exist yet

    if df.empty:
        return

    # League averages per play type (weighted by possessions)
    for pt, group in df.groupby("play_type"):
        total_poss = group["possessions"].sum()
        if total_poss > 0:
            _LEAGUE_AVG_PPP[pt] = float(
                (group["ppp"] * group["possessions"]).sum() / total_poss
            )
        else:
            _LEAGUE_AVG_PPP[pt] = 0.95

    # Per-player offensive play profiles
    for pid, group in df.groupby("player_id"):
        pid = int(pid)
        profile = {}
        total_poss = group["possessions"].sum()
        for _, row in group.iterrows():
            pt = row["play_type"]
            profile[pt] = {
                "ppp": float(row["ppp"]),
                "poss_pct": float(row["poss_pct"]),
                "possessions": float(row["possessions"]),
                "poss_share": float(row["possessions"]) / total_poss if total_poss > 0 else 0,
            }
        _PLAYER_PLAY_PROFILE[pid] = profile


_load_play_profiles()

# ─── USG-Efficiency Curves Cache ─────────────────────────────────
# Maps player_id → {ts_per_usg (float), is_load_bearer (bool)}
# Built from empirical game-by-game USG vs TS% data in player_potential.
# Load-bearers maintain or IMPROVE efficiency at higher usage (Giannis, Trae).
# Decay players lose efficiency rapidly (bench specialists, some role bigs).
_USG_CURVES = {}


def _load_usg_curves():
    """Load empirical USG-efficiency curves from latest potential snapshot.

    Replaces the uniform 0.995 decay in compute_adjusted_mojo() with
    per-player slopes derived from actual game data.
    """
    global _USG_CURVES
    import re

    try:
        df = read_query("""
            SELECT player_id, notes
            FROM player_potential
            WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM player_potential)
                  AND notes IS NOT NULL
        """, DB_PATH)
    except (sqlite3.OperationalError, pd.errors.DatabaseError):
        return  # Table may not exist yet

    if df.empty:
        return

    for _, row in df.iterrows():
        pid = int(row["player_id"])
        notes = str(row["notes"] or "")

        is_load_bearer = "LOAD-BEARER" in notes

        # Extract ts_per_usg from notes like "LOAD-BEARER: TS +0.24%/USG% (39g)"
        match = re.search(r'TS ([+-]?\d+\.?\d*)%/USG%', notes)
        if match:
            ts_per_usg = float(match.group(1))
        else:
            ts_per_usg = -0.5  # default moderate decay

        _USG_CURVES[pid] = {
            "ts_per_usg": ts_per_usg,
            "is_load_bearer": is_load_bearer,
        }


_load_usg_curves()


def _compute_play_type_absorption(absorber_pid, out_pids):
    """Score how well a player can absorb freed play types from OUT players.

    When Player X goes OUT, their possessions aren't generic — they're
    specific play types (PnR Ball Handler, Isolation, Spotup, etc.).
    This function measures how well the absorbing player handles those
    SPECIFIC play types relative to the league average.

    Returns a quality ratio:
    - > 1.0: above-average absorber for these play types (e.g., elite PnR guard
             absorbing PnR possessions from another guard)
    - 1.0: average compatibility
    - < 1.0: poor match (e.g., a center absorbing guard isolation plays)
    """
    if not _PLAYER_PLAY_PROFILE or not _LEAGUE_AVG_PPP:
        return 1.0  # No play type data — neutral

    # Build profile of freed play types from OUT players
    freed = {}
    for out_pid in out_pids:
        out_profile = _PLAYER_PLAY_PROFILE.get(int(out_pid), {})
        for pt, data in out_profile.items():
            freed[pt] = freed.get(pt, 0) + data["possessions"]

    if not freed:
        return 1.0  # No play type data for OUT players

    # Score how well the absorber handles each freed play type
    absorber_profile = _PLAYER_PLAY_PROFILE.get(int(absorber_pid), {})
    if not absorber_profile:
        return 0.95  # No profile → slightly below average assumption

    weighted_quality = 0
    total_freed = 0
    for pt, freed_poss in freed.items():
        league_avg = _LEAGUE_AVG_PPP.get(pt, 0.95)
        if pt in absorber_profile:
            player_ppp = absorber_profile[pt]["ppp"]
            quality = player_ppp / league_avg if league_avg > 0 else 1.0
        else:
            # Player doesn't play this type at all → below average absorption
            quality = 0.80

        weighted_quality += quality * freed_poss
        total_freed += freed_poss

    return weighted_quality / total_freed if total_freed > 0 else 1.0


# ─── Injury-Adjusted Value Scores Cache ──────────────────────────
# Populated per-generation for tonight's playing teams only.
# Maps player_id → adjusted composite (0-100) reflecting who's actually OUT.
_INJURY_ADJUSTED_VS = {}

# ─── Top WOWY Partners Cache ────────────────────────────────────
# Maps player_id → [(partner_name, syn_score, poss), ...] top 3 by syn
_PLAYER_TOP_PAIRS = {}
_PID_NAMES = {}  # player_id → full_name lookup


def _build_injury_adjusted_cache(matchups):
    """Recompute synergy-based composite values excluding OUT players.

    For each team playing tonight, removes pair/lineup data involving
    OUT players and recomposes the composite. Result stored in
    _INJURY_ADJUSTED_VS so matchup-card MOJO reflects tonight's rotation.
    """
    global _INJURY_ADJUSTED_VS, _PLAYER_TOP_PAIRS, _PID_NAMES
    _INJURY_ADJUSTED_VS = {}
    _PLAYER_TOP_PAIRS = {}
    _PID_NAMES = {}

    from config import (
        SYNERGY_WEIGHTS, BASE_VALUE_WEIGHT, ARCHETYPE_FIT_WEIGHT,
    )
    from collections import defaultdict

    # ── Collect team info from matchups ──
    team_out_map = {}  # team_id → set(out_player_ids)
    team_ids = set()

    for m in matchups:
        rw = m.get("rw_lineups", {})
        for abbr in [m.get("home_abbr", ""), m.get("away_abbr", "")]:
            if not abbr:
                continue

            roster = _get_full_roster(abbr)
            if roster.empty:
                continue

            tid_df = read_query(
                "SELECT team_id FROM teams WHERE abbreviation = ?",
                DB_PATH, [abbr]
            )
            tid = int(tid_df.iloc[0]["team_id"]) if not tid_df.empty else 0
            if tid == 0:
                continue

            team_ids.add(tid)

            # Resolve OUT player names → IDs
            out_ids = set()
            team_rw = rw.get(abbr, {})
            for name in team_rw.get("out", []):
                pid = _match_player_name(name, roster)
                if pid is not None:
                    out_ids.add(int(pid))
            for name, pos, status in team_rw.get("starters", []):
                if status == "OUT":
                    pid = _match_player_name(name, roster)
                    if pid is not None:
                        out_ids.add(int(pid))

            if out_ids:
                # Merge with existing (in case same team appears in multiple matchups — shouldn't happen)
                existing = team_out_map.get(tid, set())
                team_out_map[tid] = existing | out_ids

    if not team_out_map:
        return  # No injuries on tonight's slate

    # ── Batch SQL: load pair_synergy for playing teams ──
    tid_list = list(team_ids)
    placeholders = ",".join("?" * len(tid_list))

    pairs_df = read_query(f"""
        SELECT player_a_id, player_b_id, synergy_score, possessions, team_id
        FROM pair_synergy
        WHERE season_id = '{CURRENT_SEASON}' AND team_id IN ({placeholders})
    """, DB_PATH, tid_list)

    # ── Batch SQL: load lineup_stats for playing teams ──
    lineups_df = read_query(f"""
        SELECT player_ids, possessions, group_quantity, team_id
        FROM lineup_stats
        WHERE season_id = '{CURRENT_SEASON}' AND group_quantity IN (2,3,4,5)
              AND team_id IN ({placeholders})
              AND possessions > 0
    """, DB_PATH, tid_list)

    # ── Index pair data by (player, team) ──
    # team_player_pairs[(tid, pid)] = [(partner_id, syn_score, poss), ...]
    team_player_pairs = defaultdict(list)
    if not pairs_df.empty:
        for _, row in pairs_df.iterrows():
            a = int(row["player_a_id"])
            b = int(row["player_b_id"])
            t = int(row["team_id"])
            syn = float(row["synergy_score"] or 50)
            poss = float(row["possessions"] or 0)
            team_player_pairs[(t, a)].append((b, syn, poss))
            team_player_pairs[(t, b)].append((a, syn, poss))

    # ── Index lineup data by (player, team, n) ──
    # team_player_lineups[(tid, pid, n)] = [(set_of_pids, poss), ...]
    team_player_lineups = defaultdict(list)
    if not lineups_df.empty:
        for _, row in lineups_df.iterrows():
            try:
                pids = [int(p) for p in json.loads(row["player_ids"])]
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            t = int(row["team_id"])
            n = int(row["group_quantity"])
            poss = float(row["possessions"] or 0)
            pid_set = set(pids)
            for pid in pids:
                team_player_lineups[(t, pid, n)].append((pid_set, poss))

    from utils.stats_math import possession_weighted_average
    W = SYNERGY_WEIGHTS

    # ── For each team with OUT players, recompute teammate composites ──
    for tid, out_ids in team_out_map.items():
        # Find all players on this team via pair index keys
        team_pids = set()
        for (t, pid) in team_player_pairs.keys():
            if t == tid:
                team_pids.add(pid)
        # Also include players from lineup index
        for (t, pid, n) in team_player_lineups.keys():
            if t == tid:
                team_pids.add(pid)

        for pid in team_pids:
            if pid in out_ids:
                continue  # Skip OUT players
            vs = _VALUE_SCORES.get(pid)
            if not vs:
                continue  # No value scores for this player

            # ── Adjust two_man + archetype_fit from pair data ──
            pairs = team_player_pairs.get((tid, pid), [])
            if pairs:
                alive_pairs = [(syn, poss) for (partner, syn, poss) in pairs
                               if partner not in out_ids]
                total_poss = sum(poss for (_, _, poss) in pairs)
                alive_poss = sum(poss for (_, poss) in alive_pairs)

                if alive_poss > 0 and total_poss > 0:
                    alive_scores = [syn for (syn, _) in alive_pairs]
                    alive_weights = [poss for (_, poss) in alive_pairs]
                    alive_avg = possession_weighted_average(alive_scores, alive_weights)
                    confidence = alive_poss / total_poss
                    adj_two = confidence * alive_avg + (1 - confidence) * 50.0
                    adj_fit = adj_two
                else:
                    adj_two = 50.0
                    adj_fit = 50.0
            else:
                adj_two = vs["two"]
                adj_fit = vs["fit"]

            # ── Adjust n-man synergy from lineup data ──
            adj_n = {}
            for n, key in [(3, "three"), (4, "four"), (5, "five")]:
                n_lineups = team_player_lineups.get((tid, pid, n), [])
                if not n_lineups:
                    adj_n[key] = vs[key]
                    continue
                total_n_poss = sum(poss for (_, poss) in n_lineups)
                dead_poss = sum(poss for (pid_set, poss) in n_lineups
                                if pid_set & out_ids)
                if total_n_poss > 0:
                    dead_frac = dead_poss / total_n_poss
                    adj_n[key] = vs[key] * (1 - dead_frac) + 50.0 * dead_frac
                else:
                    adj_n[key] = vs[key]

            # ── Recompose adjusted composite ──
            adj_composite = (
                BASE_VALUE_WEIGHT * vs["base"] +
                W["solo"] * vs["solo"] +
                W["two_man"] * adj_two +
                W["three_man"] * adj_n["three"] +
                W["four_man"] * adj_n["four"] +
                W["five_man"] * adj_n["five"] +
                ARCHETYPE_FIT_WEIGHT * adj_fit
            )

            # Clamp: no more than ±15 from season composite
            adj_composite = max(vs["composite"] - 15, min(vs["composite"] + 15, adj_composite))

            _INJURY_ADJUSTED_VS[pid] = adj_composite

    # ── Build player name lookup + top WOWY partners ──
    all_pids = set()
    for (t, pid) in team_player_pairs.keys():
        all_pids.add(pid)
        for partner_id, syn, poss in team_player_pairs[(t, pid)]:
            all_pids.add(partner_id)

    if all_pids:
        pid_list = list(all_pids)
        ph = ",".join("?" * len(pid_list))
        names_df = read_query(
            f"SELECT player_id, full_name FROM players WHERE player_id IN ({ph})",
            DB_PATH, pid_list
        )
        if not names_df.empty:
            for _, row in names_df.iterrows():
                _PID_NAMES[int(row["player_id"])] = row["full_name"]

    # For each player, find top 3 WOWY partners by synergy score (min 10 poss)
    seen = set()
    for (t, pid), partners in team_player_pairs.items():
        if pid in seen:
            continue
        seen.add(pid)
        qualified = [(p, syn, poss) for p, syn, poss in partners if poss >= 10]
        qualified.sort(key=lambda x: x[1], reverse=True)
        top3 = []
        for partner_id, syn, poss in qualified[:3]:
            pname = _PID_NAMES.get(partner_id, f"#{partner_id}")
            parts = pname.split()
            short = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else pname
            top3.append(f"{short} ({syn:+.1f} SYN, {int(poss)} poss)")
        if top3:
            _PLAYER_TOP_PAIRS[pid] = top3


# ─── NBA Team Colors ───────────────────────────────────────────────
TEAM_COLORS = {
    "ATL": "#E03A3E", "BOS": "#007A33", "BKN": "#000000", "CHA": "#1D1160",
    "CHI": "#CE1141", "CLE": "#860038", "DAL": "#00538C", "DEN": "#0E2240",
    "DET": "#C8102E", "GSW": "#1D428A", "HOU": "#CE1141", "IND": "#002D62",
    "LAC": "#C8102E", "LAL": "#552583", "MEM": "#5D76A9", "MIA": "#98002E",
    "MIL": "#00471B", "MIN": "#0C2340", "NOP": "#0C2340", "NYK": "#F58426",
    "OKC": "#007AC1", "ORL": "#0077C0", "PHI": "#006BB6", "PHX": "#1D1160",
    "POR": "#E03A3E", "SAC": "#5A2D81", "SAS": "#C4CED4", "TOR": "#CE1141",
    "UTA": "#002B5C", "WAS": "#002B5C",
}

TEAM_SECONDARY = {
    "ATL": "#FDB927", "BOS": "#BA9653", "BKN": "#FFFFFF", "CHA": "#00788C",
    "CHI": "#000000", "CLE": "#FDBB30", "DAL": "#002B5E", "DEN": "#FEC524",
    "DET": "#1D42BA", "GSW": "#FFC72C", "HOU": "#000000", "IND": "#FDBB30",
    "LAC": "#1D428A", "LAL": "#FDB927", "MEM": "#12173F", "MIA": "#F9A01B",
    "MIL": "#EEE1C6", "MIN": "#236192", "NOP": "#C8102E", "NYK": "#0072CE",
    "OKC": "#EF6100", "ORL": "#C4CED4", "PHI": "#ED174C", "PHX": "#E56020",
    "POR": "#000000", "SAC": "#63727A", "SAS": "#000000", "TOR": "#000000",
    "UTA": "#00471B", "WAS": "#E31837",
}

# ─── NBA Team IDs (for CDN logo URLs) ─────────────────────────────
TEAM_IDS = {
    "ATL": 1610612737, "BOS": 1610612738, "BKN": 1610612751, "CHA": 1610612766,
    "CHI": 1610612741, "CLE": 1610612739, "DAL": 1610612742, "DEN": 1610612743,
    "DET": 1610612765, "GSW": 1610612744, "HOU": 1610612745, "IND": 1610612754,
    "LAC": 1610612746, "LAL": 1610612747, "MEM": 1610612763, "MIA": 1610612748,
    "MIL": 1610612749, "MIN": 1610612750, "NOP": 1610612740, "NYK": 1610612752,
    "OKC": 1610612760, "ORL": 1610612753, "PHI": 1610612755, "PHX": 1610612756,
    "POR": 1610612757, "SAC": 1610612758, "SAS": 1610612759, "TOR": 1610612761,
    "UTA": 1610612762, "WAS": 1610612764,
}

TEAM_FULL_NAMES = {
    "ATL": "Hawks", "BOS": "Celtics", "BKN": "Nets", "CHA": "Hornets",
    "CHI": "Bulls", "CLE": "Cavaliers", "DAL": "Mavericks", "DEN": "Nuggets",
    "DET": "Pistons", "GSW": "Warriors", "HOU": "Rockets", "IND": "Pacers",
    "LAC": "Clippers", "LAL": "Lakers", "MEM": "Grizzlies", "MIA": "Heat",
    "MIL": "Bucks", "MIN": "Timberwolves", "NOP": "Pelicans", "NYK": "Knicks",
    "OKC": "Thunder", "ORL": "Magic", "PHI": "76ers", "PHX": "Suns",
    "POR": "Trail Blazers", "SAC": "Kings", "SAS": "Spurs", "TOR": "Raptors",
    "UTA": "Jazz", "WAS": "Wizards",
}


def get_team_logo_url(abbreviation):
    """Get NBA CDN logo URL for a team."""
    tid = TEAM_IDS.get(abbreviation, 0)
    return f"https://cdn.nba.com/logos/nba/{tid}/global/L/logo.svg"


ARCHETYPE_ICONS = {
    "Scoring Guard": "⚡", "Defensive Specialist": "🛡️", "Floor General": "🧠",
    "Combo Guard": "🔄", "Playmaking Guard": "🎯", "Two-Way Wing": "🦾",
    "Slasher": "⚔️", "Sharpshooter": "🎯", "3-and-D Wing": "🔒",
    "Point Forward": "🧠", "Stretch Forward": "📐", "Athletic Wing": "💨",
    "Stretch Big": "📐", "Traditional PF": "🏋️", "Small-Ball 4": "⚡",
    "Two-Way Forward": "🦾", "Rim Protector": "🏰", "Stretch 5": "📐",
    "Traditional Center": "🏋️", "Versatile Big": "🔮",
}

ARCHETYPE_DESCRIPTIONS = {
    "Scoring Guard": "High-usage backcourt scorer. Attacks off the dribble and in pick-and-roll. Elite shot creation.",
    "Defensive Specialist": "Defensive-first guard. Low usage but elite on-ball pressure and deflections.",
    "Floor General": "Pass-first point guard. Orchestrates the offense with high assist rates and low turnovers.",
    "Combo Guard": "Versatile guard who can both score and distribute. Balanced statistical profile.",
    "Playmaking Guard": "Shot-creating guard with strong passing vision. Combines scoring with facilitation.",
    "Two-Way Wing": "Elite two-way player at the wing. Impacts both ends with scoring and perimeter defense.",
    "Slasher": "Rim-attacking wing. Gets to the basket with speed and athleticism. High FTA rate.",
    "Sharpshooter": "Elite 3-point specialist. Spaces the floor and punishes closeouts. High 3PA rate.",
    "3-and-D Wing": "Defensive wing who spaces the floor. Combines perimeter lockdown with corner threes.",
    "Point Forward": "Forward with guard-like passing. Initiates offense from the post or perimeter.",
    "Stretch Forward": "Floor-spacing forward. Pulls opposing bigs to the perimeter with consistent shooting.",
    "Athletic Wing": "Versatile, athletic wing. Contributes across the board with energy and athleticism.",
    "Stretch Big": "Shooting big man. Provides floor spacing from the 4/5 with reliable outside shooting.",
    "Traditional PF": "Physical power forward. Operates in the post and mid-range. Strong rebounder.",
    "Small-Ball 4": "Undersized but versatile 4. Plays with speed and skill rather than size.",
    "Two-Way Forward": "Two-way forward contributing on both ends. Solid defender with offensive versatility.",
    "Rim Protector": "Elite shot-blocker. Anchors the defense with rim protection and rebounding.",
    "Stretch 5": "Modern center who can shoot from distance. Provides spacing from the 5 position.",
    "Traditional Center": "Classic big man. Rebounds, protects the rim, and finishes inside.",
    "Versatile Big": "Multi-skilled center. Can pass, shoot, and defend at an above-average level.",
}

# Odds API team map removed — Odds API has been removed from the pipeline.


def fetch_nba_schedule():
    """Fetch today's NBA schedule from NBA.com for game times and statuses.

    Returns:
        dict: {(home_abbr, away_abbr): {"utc": datetime, "status": int, "status_text": str}}
              status: 1=scheduled, 2=in-progress, 3=final
    """
    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning("NBA Schedule: failed to fetch: %s", e)
        return {}

    schedule = {}
    for game in data.get("scoreboard", {}).get("games", []):
        home = game.get("homeTeam", {}).get("teamTricode", "")
        away = game.get("awayTeam", {}).get("teamTricode", "")
        time_utc = game.get("gameTimeUTC", "")
        status = game.get("gameStatus", 0)
        status_text = game.get("gameStatusText", "")

        if home and away and time_utc:
            try:
                dt = datetime.fromisoformat(time_utc.replace("Z", "+00:00"))
                schedule[(home, away)] = {
                    "utc": dt,
                    "status": status,
                    "status_text": status_text.strip(),
                }
            except (KeyError, ValueError, TypeError, IndexError):
                pass

    logger.info("NBA Schedule: found %d games for today", len(schedule))
    return schedule


def fetch_odds_api_lines():
    """Stub — Odds API removed. Lines come from RotoWire scrape."""
    return {}, [], None, [], {}


def fetch_odds_api_player_props(event_ids):
    """Stub — Odds API removed."""
    return {}


def compute_mojo_score(row, injury_adjusted_composite=None):
    """Compute a context-aware MOJO (33-99).

    Base layer: 75% offense / 25% defense + shared components from box score stats.
    Context layer: blended with composite_value from player_value_scores (WOWY,
    pair synergy, n-man lineups, archetype fit) to reflect team-based contribution.

    When injury_adjusted_composite is provided (from _INJURY_ADJUSTED_VS), it
    replaces the season-long composite — reflecting tonight's actual rotation
    with OUT players removed from synergy calculations.

    Final: 55% raw box score + 45% contextual value = MOJO that rewards players
    who elevate their team, not just fill the stat sheet.

    Returns (score, breakdown_dict) for tooltip display.
    """
    pts = row.get("pts_pg", 0) or 0
    ast = row.get("ast_pg", 0) or 0
    reb = row.get("reb_pg", 0) or 0
    stl = row.get("stl_pg", 0) or 0
    blk = row.get("blk_pg", 0) or 0
    ts = row.get("ts_pct", 0) or 0
    net = row.get("net_rating", 0) or 0
    usg = row.get("usg_pct", 0) or 0
    mpg = row.get("minutes_per_game", 0) or 0
    drtg = row.get("def_rating", 0) or 0
    if drtg == 0:
        drtg = 112  # league average fallback

    # ── Offensive sub-score (0-99 scale) ──
    scoring_c = pts * 1.2
    playmaking_c = ast * 1.8
    efficiency_c = ts * 40
    usage_c = usg * 15
    off_raw = scoring_c + playmaking_c + efficiency_c + usage_c
    off_score = min(99, max(0, off_raw / 0.85))

    # ── Defensive sub-score (0-99 scale) ──
    # Old box-score defense — used as fallback for players without RAPM data
    stocks_c = stl * 8.0 + blk * 6.0
    drtg_c = max(0, (115 - drtg) * 2.5)  # 107 DRtg → 20pts, 112 → 7.5, 115+ → 0
    def_raw = stocks_c + drtg_c
    def_score = min(99, max(0, def_raw / 0.5))

    # ── Shared components ──
    rebounding_c = reb * 0.8
    impact_c = net * 0.8
    minutes_c = mpg * 0.3
    shared_raw = rebounding_c + impact_c + minutes_c

    # ── Raw MOJO from RAPM-anchored blend (33-99 scale) ──
    pid = int(row.get("player_id", 0) or 0)
    orapm_pctl = _ORAPM_PERCENTILES.get(pid)
    drapm_pctl = _DRAPM_PERCENTILES.get(pid)

    # Offense: 75% ORAPM percentile + 25% counting stats
    if orapm_pctl is not None:
        offense_blended = 0.75 * orapm_pctl + 0.25 * off_score
    else:
        offense_blended = off_score  # fallback: pure counting stats

    # Defense: 100% DRAPM percentile
    if drapm_pctl is not None:
        blended = 0.62 * offense_blended + 0.38 * drapm_pctl + shared_raw
    else:
        # Fallback: old box-score defense for players without RAPM
        blended = 0.62 * offense_blended + 0.38 * def_score + shared_raw

    raw_mojo = min(99, max(33, int(blended / 1.1)))

    # ── Context Adjustment: blend with value_scores composite ──
    vs = _VALUE_SCORES.get(pid)

    if vs:
        # Use injury-adjusted composite if provided, otherwise season-long
        composite = injury_adjusted_composite if injury_adjusted_composite is not None else vs["composite"]
        # Scale composite_value (0-100) to 33-99 range
        contextual_mojo = int(33 + (composite / 100) * 66)
        contextual_mojo = min(99, max(33, contextual_mojo))
        # 55% raw box score + 45% contextual (team-based contribution)
        score = int(0.55 * raw_mojo + 0.45 * contextual_mojo)
        score = min(99, max(33, score))
    else:
        contextual_mojo = raw_mojo
        score = raw_mojo

    # Breakdown for tooltip — preserve existing keys for compatibility
    total_raw = off_raw + def_raw + shared_raw
    breakdown = {
        "pts": round(pts, 3), "ast": round(ast, 3), "reb": round(reb, 3),
        "stl": round(stl, 3), "blk": round(blk, 3),
        "ts_pct": round(ts * 100, 3) if ts < 1 else round(ts, 3),
        "net_rating": round(net, 3),
        "usg_pct": round(usg * 100, 3) if usg < 1 else round(usg, 3),
        "mpg": round(mpg, 3),
        "def_rating": round(drtg, 3),
        "off_score": round(off_score, 3),
        "def_score": round(def_score, 3),
        "scoring_c": round(scoring_c / max(1, off_raw) * 100, 0) if off_raw else 0,
        "playmaking_c": round(playmaking_c / max(1, off_raw) * 100, 0) if off_raw else 0,
        "defense_c": round(def_score, 0),
        "efficiency_c": round(efficiency_c / max(1, off_raw) * 100, 0) if off_raw else 0,
        "impact_c": round(impact_c / max(1, shared_raw) * 100, 0) if shared_raw else 0,
        # Context factors for bottom sheet
        "raw_mojo": raw_mojo,
        "contextual_mojo": contextual_mojo,
        "solo_impact": round(vs["solo"], 3) if vs else 50.0,
        "synergy_score": round(vs["two"], 3) if vs else 50.0,
        "fit_score": round(vs["fit"], 3) if vs else 50.0,
        "injury_adjusted": injury_adjusted_composite is not None,
        # Raw RAPM from nbarapm.com (no formula integration — display only)
        "rapm": _RAPM_DATA.get(pid, {}).get("rapm"),
        "rapm_off": _RAPM_DATA.get(pid, {}).get("rapm_off"),
        "rapm_def": _RAPM_DATA.get(pid, {}).get("rapm_def"),
        "rapm_rank": _RAPM_DATA.get(pid, {}).get("rapm_rank"),
    }
    return score, breakdown


def compute_mojo_range(score, player_id=None):
    """Generate a data-driven MOJO range.

    Floor = raw box score MOJO (what they'd be without team context).
    Ceiling = best-case composite from solo impact + best synergy + archetype fit.
    Falls back to math formula when no value_scores data exists.
    """
    vs = _VALUE_SCORES.get(player_id) if player_id else None

    if vs:
        # Floor = raw box score MOJO (base_value scaled to 33-99)
        raw_mojo = int(33 + (vs["base"] / 100) * 66)
        # Ceiling = best-case: solo + best synergy component + fit
        best_synergy = max(vs["two"], vs["three"], vs["four"], vs["five"])
        ceiling_composite = 0.25 * vs["base"] + 0.30 * vs["solo"] + 0.30 * best_synergy + 0.15 * vs["fit"]
        ceiling_ds = int(33 + (ceiling_composite / 100) * 66)

        low = max(33, min(raw_mojo, score - 3))
        high = min(99, max(ceiling_ds, score + 2))
    else:
        # Fallback to math formula (shifted to 33-99 scale)
        low = max(33, score - int(abs(score - 72) * 0.2) - 4)
        high = min(99, score + int(abs(score - 72) * 0.15) + 3)

    return low, high


# ────────────────────────────────────────────────────────────────────
# MOJI SPREAD MODEL — Steps 1-8
# ────────────────────────────────────────────────────────────────────

# Model constants
_MOJI_CONSTANTS = {
    "MOJO_SCALE":     1.0,    # 1pt MOJO gap → 1.0 points on spread scale
    "MOJI_WEIGHT":   0.40,   # MOJI share in final blend (down from 0.45 — too sticky)
    "NRTG_SEASON_WEIGHT": 0.10,  # season-long NRtg (stabilizer)
    "NRTG_RECENT_WEIGHT": 0.30,  # trailing 10-game NRtg (up from 0.25 — momentum matters)
    "SYN_WEIGHT":   0.20,   # lineup synergy share in final blend (SYN v2, unproven — modifier only)
    "SYN_SCALE":    0.15,   # (home_syn - away_syn) × SCALE = spread points
    "HCA":          1.8,    # base home court advantage (most arenas — modern NBA)
    "B2B_HOME":     2.0,    # home back-to-back penalty (less severe — still at home)
    "B2B_ROAD":     2.5,    # road back-to-back penalty (travel + fatigue)
    "USAGE_DECAY":      0.995,  # MOJO multiplier per 1% extra usage (efficiency tax)
    "USAGE_DECAY_DEF":  0.985,  # steeper decay for defensive archetypes absorbing offense
    "STOCKS_PENALTY":   0.8,    # MOJI points lost per lost stock (STL+BLK scaled by minutes)
    "NRTG_MOJO_ATTRITION": 0.3, # NRtg points lost per 1-point MOJI drop from injuries
    # SYN v2: lineup-simulation synergy
    "SYN_MOJI_BONUS":    0.15,   # NRtg bonus per MOJI point above team avg in a lineup
    "SYN_PAIR_TO_NRTG": 0.4,    # pair composite (0-100) → NRtg scale for synthetic lineups
    "SYN_NRTG_RANGE":   15.0,   # NRtg range for 0-100 mapping [-15, +15]
    "SYN_5MAN_PRIOR":   100,    # Bayesian prior possessions for 5-man NRtg shrinkage
    "SYN_MIN_POSS":     10,     # minimum possessions for a 5-man lineup to count
}

# Per-team home court advantage — Denver altitude + Boston historic dominance
# Everyone else uses base 1.8 from _MOJI_CONSTANTS["HCA"]
TEAM_HCA = {
    "DEN": 3.8,  # Ball Arena, 5,280 ft elevation — altitude is a real advantage
    "BOS": 3.5,  # TD Garden — historically dominant home court
}

# Pre-computed B2B schedule for 2025-26 NBA season
# Generated from NBA.com full schedule on 2026-02-25
# 447 team-game B2B instances across all 30 teams
# Lookup: (game_date "YYYY-MM-DD", team_tricode) in _B2B_SCHEDULE
_B2B_SCHEDULE = {
    ("2025-10-04", "NOP"), ("2025-10-06", "OKC"), ("2025-10-13", "MIA"),
    ("2025-10-13", "WAS"), ("2025-10-15", "LAL"), ("2025-10-17", "MIN"),
    ("2025-10-24", "GSW"), ("2025-10-25", "ATL"), ("2025-10-25", "MEM"),
    ("2025-10-25", "ORL"), ("2025-10-25", "PHX"), ("2025-10-26", "CHA"),
    ("2025-10-26", "IND"), ("2025-10-27", "BKN"), ("2025-10-27", "BOS"),
    ("2025-10-27", "CLE"), ("2025-10-27", "DAL"), ("2025-10-27", "DET"),
    ("2025-10-27", "LAL"), ("2025-10-27", "MIN"), ("2025-10-27", "POR"),
    ("2025-10-27", "SAS"), ("2025-10-27", "TOR"), ("2025-10-28", "GSW"),
    ("2025-10-28", "OKC"), ("2025-10-28", "PHI"), ("2025-10-29", "SAC"),
    ("2025-10-30", "ORL"), ("2025-11-01", "BOS"), ("2025-11-01", "IND"),
    ("2025-11-02", "CHA"), ("2025-11-03", "BKN"), ("2025-11-03", "LAL"),
    ("2025-11-03", "MEM"), ("2025-11-03", "MIA"), ("2025-11-03", "NYK"),
    ("2025-11-03", "UTA"), ("2025-11-04", "LAC"), ("2025-11-04", "MIL"),
    ("2025-11-05", "GSW"), ("2025-11-05", "NOP"), ("2025-11-05", "OKC"),
    ("2025-11-05", "PHI"), ("2025-11-08", "ATL"), ("2025-11-08", "CHI"),
    ("2025-11-08", "CLE"), ("2025-11-08", "DAL"), ("2025-11-08", "DEN"),
    ("2025-11-08", "MIA"), ("2025-11-08", "SAS"), ("2025-11-08", "TOR"),
    ("2025-11-08", "WAS"), ("2025-11-09", "IND"), ("2025-11-09", "PHI"),
    ("2025-11-10", "DET"), ("2025-11-10", "MIL"), ("2025-11-10", "MIN"),
    ("2025-11-10", "ORL"), ("2025-11-11", "UTA"), ("2025-11-12", "BOS"),
    ("2025-11-12", "DEN"), ("2025-11-12", "GSW"), ("2025-11-12", "MEM"),
    ("2025-11-12", "NYK"), ("2025-11-12", "OKC"), ("2025-11-12", "SAC"),
    ("2025-11-13", "ATL"), ("2025-11-13", "CLE"), ("2025-11-13", "PHX"),
    ("2025-11-15", "CHA"), ("2025-11-15", "LAL"), ("2025-11-15", "MIL"),
    ("2025-11-15", "MIN"), ("2025-11-17", "CHI"), ("2025-11-17", "DAL"),
    ("2025-11-17", "LAC"), ("2025-11-17", "NOP"), ("2025-11-18", "DET"),
    ("2025-11-19", "GSW"), ("2025-11-19", "POR"), ("2025-11-20", "PHI"),
    ("2025-11-20", "SAC"), ("2025-11-22", "CHI"), ("2025-11-22", "DAL"),
    ("2025-11-22", "DEN"), ("2025-11-22", "NOP"), ("2025-11-22", "WAS"),
    ("2025-11-23", "ATL"), ("2025-11-23", "CHA"), ("2025-11-23", "LAC"),
    ("2025-11-23", "ORL"), ("2025-11-24", "BKN"), ("2025-11-24", "CLE"),
    ("2025-11-24", "MIA"), ("2025-11-24", "PHX"), ("2025-11-24", "POR"),
    ("2025-11-24", "TOR"), ("2025-11-24", "UTA"), ("2025-11-29", "BKN"),
    ("2025-11-29", "CHA"), ("2025-11-29", "CHI"), ("2025-11-29", "DAL"),
    ("2025-11-29", "DEN"), ("2025-11-29", "DET"), ("2025-11-29", "IND"),
    ("2025-11-29", "LAC"), ("2025-11-29", "MIL"), ("2025-11-29", "PHX"),
    ("2025-11-30", "BOS"), ("2025-11-30", "MIN"), ("2025-11-30", "NOP"),
    ("2025-11-30", "TOR"), ("2025-12-01", "ATL"), ("2025-12-01", "CLE"),
    ("2025-12-01", "HOU"), ("2025-12-01", "LAL"), ("2025-12-01", "UTA"),
    ("2025-12-02", "WAS"), ("2025-12-03", "NYK"), ("2025-12-03", "POR"),
    ("2025-12-03", "SAS"), ("2025-12-04", "BKN"), ("2025-12-05", "BOS"),
    ("2025-12-05", "LAL"), ("2025-12-05", "PHI"), ("2025-12-05", "TOR"),
    ("2025-12-05", "UTA"), ("2025-12-06", "ATL"), ("2025-12-06", "CLE"),
    ("2025-12-06", "DAL"), ("2025-12-06", "DET"), ("2025-12-06", "HOU"),
    ("2025-12-06", "LAC"), ("2025-12-06", "MIA"), ("2025-12-06", "MIL"),
    ("2025-12-07", "GSW"), ("2025-12-19", "ATL"), ("2025-12-19", "MIA"),
    ("2025-12-19", "NYK"), ("2025-12-19", "OKC"), ("2025-12-19", "SAS"),
    ("2025-12-20", "BOS"), ("2025-12-20", "PHI"), ("2025-12-21", "HOU"),
    ("2025-12-21", "SAC"), ("2025-12-21", "TOR"), ("2025-12-21", "WAS"),
    ("2025-12-23", "CHA"), ("2025-12-23", "CLE"), ("2025-12-23", "DAL"),
    ("2025-12-23", "DEN"), ("2025-12-23", "DET"), ("2025-12-23", "IND"),
    ("2025-12-23", "MEM"), ("2025-12-23", "NOP"), ("2025-12-23", "OKC"),
    ("2025-12-23", "ORL"), ("2025-12-23", "POR"), ("2025-12-23", "UTA"),
    ("2025-12-27", "ATL"), ("2025-12-27", "CHI"), ("2025-12-27", "IND"),
    ("2025-12-27", "MIA"), ("2025-12-27", "MIL"), ("2025-12-27", "NOP"),
    ("2025-12-27", "ORL"), ("2025-12-27", "PHX"), ("2025-12-27", "UTA"),
    ("2025-12-28", "SAC"), ("2025-12-29", "GSW"), ("2025-12-29", "OKC"),
    ("2025-12-29", "POR"), ("2025-12-29", "TOR"), ("2025-12-29", "WAS"),
    ("2026-01-02", "BKN"), ("2026-01-02", "SAC"), ("2026-01-03", "ATL"),
    ("2026-01-03", "CHA"), ("2026-01-03", "CHI"), ("2026-01-03", "GSW"),
    ("2026-01-03", "NYK"), ("2026-01-03", "POR"), ("2026-01-03", "SAS"),
    ("2026-01-04", "MIA"), ("2026-01-04", "MIN"), ("2026-01-05", "DEN"),
    ("2026-01-05", "DET"), ("2026-01-05", "OKC"), ("2026-01-05", "PHX"),
    ("2026-01-07", "LAL"), ("2026-01-07", "MEM"), ("2026-01-07", "NOP"),
    ("2026-01-07", "ORL"), ("2026-01-07", "SAS"), ("2026-01-07", "WAS"),
    ("2026-01-08", "CHA"), ("2026-01-08", "UTA"), ("2026-01-10", "BOS"),
    ("2026-01-10", "LAC"), ("2026-01-11", "MIA"), ("2026-01-11", "MIN"),
    ("2026-01-11", "SAS"), ("2026-01-12", "BKN"), ("2026-01-12", "PHI"),
    ("2026-01-12", "SAC"), ("2026-01-12", "TOR"), ("2026-01-13", "LAL"),
    ("2026-01-14", "CHI"), ("2026-01-14", "DEN"), ("2026-01-14", "NOP"),
    ("2026-01-15", "DAL"), ("2026-01-15", "NYK"), ("2026-01-15", "UTA"),
    ("2026-01-16", "HOU"), ("2026-01-17", "IND"), ("2026-01-17", "MIN"),
    ("2026-01-17", "WAS"), ("2026-01-18", "CHA"), ("2026-01-18", "DEN"),
    ("2026-01-18", "LAL"), ("2026-01-18", "POR"), ("2026-01-19", "BKN"),
    ("2026-01-20", "GSW"), ("2026-01-20", "LAC"), ("2026-01-20", "MIA"),
    ("2026-01-20", "PHI"), ("2026-01-20", "PHX"), ("2026-01-20", "SAS"),
    ("2026-01-20", "UTA"), ("2026-01-21", "SAC"), ("2026-01-21", "TOR"),
    ("2026-01-22", "CHA"), ("2026-01-23", "DEN"), ("2026-01-23", "HOU"),
    ("2026-01-23", "POR"), ("2026-01-24", "BOS"), ("2026-01-24", "CLE"),
    ("2026-01-25", "MIA"), ("2026-01-26", "GSW"), ("2026-01-26", "MIN"),
    ("2026-01-27", "PHI"), ("2026-01-27", "POR"), ("2026-01-28", "NYK"),
    ("2026-01-28", "UTA"), ("2026-01-29", "ATL"), ("2026-01-29", "CHA"),
    ("2026-01-29", "CHI"), ("2026-01-29", "DAL"), ("2026-01-29", "HOU"),
    ("2026-01-29", "MIA"), ("2026-01-29", "MIN"), ("2026-01-30", "BKN"),
    ("2026-01-30", "DEN"), ("2026-01-30", "DET"), ("2026-01-30", "PHX"),
    ("2026-01-30", "SAC"), ("2026-01-30", "WAS"), ("2026-01-31", "MEM"),
    ("2026-01-31", "NOP"), ("2026-02-01", "CHI"), ("2026-02-01", "MIA"),
    ("2026-02-01", "SAS"), ("2026-02-02", "LAC"), ("2026-02-03", "IND"),
    ("2026-02-03", "PHI"), ("2026-02-04", "BOS"), ("2026-02-04", "DEN"),
    ("2026-02-04", "MIL"), ("2026-02-04", "NYK"), ("2026-02-04", "OKC"),
    ("2026-02-05", "HOU"), ("2026-02-05", "SAS"), ("2026-02-05", "TOR"),
    ("2026-02-06", "DET"), ("2026-02-07", "MEM"), ("2026-02-07", "POR"),
    ("2026-02-07", "SAC"), ("2026-02-08", "WAS"), ("2026-02-09", "MIA"),
    ("2026-02-09", "MIN"), ("2026-02-10", "LAL"), ("2026-02-11", "HOU"),
    ("2026-02-11", "IND"), ("2026-02-11", "LAC"), ("2026-02-11", "NYK"),
    ("2026-02-11", "PHX"), ("2026-02-11", "SAS"), ("2026-02-12", "MIL"),
    ("2026-02-12", "OKC"), ("2026-02-12", "POR"), ("2026-02-12", "UTA"),
    ("2026-02-20", "ATL"), ("2026-02-20", "BKN"), ("2026-02-20", "CHA"),
    ("2026-02-20", "CLE"), ("2026-02-20", "DEN"), ("2026-02-20", "IND"),
    ("2026-02-20", "LAC"), ("2026-02-20", "WAS"), ("2026-02-21", "MEM"),
    ("2026-02-21", "MIA"), ("2026-02-21", "NOP"), ("2026-02-22", "CHI"),
    ("2026-02-22", "NYK"), ("2026-02-22", "ORL"), ("2026-02-22", "PHI"),
    ("2026-02-22", "PHX"), ("2026-02-25", "BOS"), ("2026-02-25", "CLE"),
    ("2026-02-25", "GSW"), ("2026-02-25", "MIL"), ("2026-02-25", "OKC"),
    ("2026-02-25", "TOR"), ("2026-02-26", "HOU"), ("2026-02-26", "SAC"),
    ("2026-02-26", "SAS"), ("2026-02-27", "BKN"), ("2026-02-27", "DAL"),
    ("2026-03-01", "LAL"), ("2026-03-01", "NOP"), ("2026-03-01", "POR"),
    ("2026-03-02", "BOS"), ("2026-03-02", "DEN"), ("2026-03-02", "LAC"),
    ("2026-03-02", "MIL"), ("2026-03-03", "WAS"), ("2026-03-04", "CHA"),
    ("2026-03-04", "MEM"), ("2026-03-04", "NYK"), ("2026-03-04", "OKC"),
    ("2026-03-04", "PHI"), ("2026-03-05", "UTA"), ("2026-03-06", "DAL"),
    ("2026-03-06", "DEN"), ("2026-03-06", "HOU"), ("2026-03-06", "LAL"),
    ("2026-03-06", "MIA"), ("2026-03-06", "NOP"), ("2026-03-06", "PHX"),
    ("2026-03-06", "SAS"), ("2026-03-07", "LAC"), ("2026-03-08", "DET"),
    ("2026-03-08", "MIL"), ("2026-03-08", "ORL"), ("2026-03-09", "CLE"),
    ("2026-03-09", "NYK"), ("2026-03-10", "BKN"), ("2026-03-10", "GSW"),
    ("2026-03-10", "MEM"), ("2026-03-10", "PHI"), ("2026-03-11", "CHA"),
    ("2026-03-11", "HOU"), ("2026-03-11", "MIN"), ("2026-03-11", "SAC"),
    ("2026-03-11", "TOR"), ("2026-03-12", "DEN"), ("2026-03-12", "ORL"),
    ("2026-03-13", "CHI"), ("2026-03-13", "DAL"), ("2026-03-13", "DET"),
    ("2026-03-13", "IND"), ("2026-03-13", "MEM"), ("2026-03-13", "PHX"),
    ("2026-03-14", "LAC"), ("2026-03-15", "MIL"), ("2026-03-15", "PHI"),
    ("2026-03-15", "SAC"), ("2026-03-16", "DAL"), ("2026-03-16", "GSW"),
    ("2026-03-16", "POR"), ("2026-03-17", "ORL"), ("2026-03-17", "PHX"),
    ("2026-03-17", "SAS"), ("2026-03-17", "WAS"), ("2026-03-18", "DEN"),
    ("2026-03-18", "IND"), ("2026-03-18", "MIN"), ("2026-03-18", "OKC"),
    ("2026-03-19", "CHI"), ("2026-03-19", "LAC"), ("2026-03-19", "LAL"),
    ("2026-03-19", "NOP"), ("2026-03-19", "UTA"), ("2026-03-20", "DET"),
    ("2026-03-21", "ATL"), ("2026-03-21", "GSW"), ("2026-03-21", "HOU"),
    ("2026-03-21", "MEM"), ("2026-03-22", "PHX"), ("2026-03-22", "WAS"),
    ("2026-03-23", "BKN"), ("2026-03-23", "POR"), ("2026-03-23", "TOR"),
    ("2026-03-24", "ORL"), ("2026-03-25", "CLE"), ("2026-03-25", "DEN"),
    ("2026-03-26", "DET"), ("2026-03-27", "NOP"), ("2026-03-28", "ATL"),
    ("2026-03-28", "CHI"), ("2026-03-28", "MEM"), ("2026-03-28", "UTA"),
    ("2026-03-29", "CHA"), ("2026-03-29", "MIL"), ("2026-03-29", "SAC"),
    ("2026-03-30", "BOS"), ("2026-03-30", "MIA"), ("2026-03-30", "OKC"),
    ("2026-03-30", "WAS"), ("2026-03-31", "CLE"), ("2026-03-31", "DAL"),
    ("2026-03-31", "DET"), ("2026-03-31", "LAL"), ("2026-03-31", "PHX"),
    ("2026-04-01", "HOU"), ("2026-04-01", "MIL"), ("2026-04-01", "NYK"),
    ("2026-04-01", "ORL"), ("2026-04-01", "TOR"), ("2026-04-02", "GSW"),
    ("2026-04-02", "SAS"), ("2026-04-03", "CHA"), ("2026-04-03", "MIN"),
    ("2026-04-03", "NOP"), ("2026-04-04", "PHI"), ("2026-04-05", "WAS"),
    ("2026-04-06", "CLE"), ("2026-04-06", "MEM"), ("2026-04-06", "ORL"),
    ("2026-04-08", "DAL"), ("2026-04-08", "LAC"), ("2026-04-08", "MIL"),
    ("2026-04-08", "MIN"), ("2026-04-08", "OKC"), ("2026-04-08", "PHX"),
    ("2026-04-10", "BKN"), ("2026-04-10", "BOS"), ("2026-04-10", "CHI"),
    ("2026-04-10", "GSW"), ("2026-04-10", "HOU"), ("2026-04-10", "IND"),
    ("2026-04-10", "LAL"), ("2026-04-10", "MIA"), ("2026-04-10", "NYK"),
    ("2026-04-10", "PHI"), ("2026-04-10", "TOR"), ("2026-04-10", "WAS"),
}

# Archetype groups for usage redistribution
_SCORING_ARCHETYPES = {
    "Scoring Guard", "Sharpshooter", "Slasher", "Combo Guard",
    "Small-Ball 4", "Stretch Forward", "Athletic Wing",
}
_PLAYMAKING_ARCHETYPES = {
    "Floor General", "Playmaking Guard", "Point Forward", "Combo Guard",
}
_BIG_ARCHETYPES = {
    "Rim Protector", "Stretch 5", "Traditional Center", "Versatile Big",
    "Stretch Big", "Traditional PF",
}
_DEFENSIVE_ARCHETYPES = {
    "Defensive Specialist", "Two-Way Wing", "3-and-D Wing", "Two-Way Forward",
    "Rim Protector",  # dual membership with _BIG_ARCHETYPES
}
_GUARD_POSITIONS = {"PG", "SG"}
_WING_POSITIONS = {"SF", "SG"}
_BIG_POSITIONS = {"PF", "C"}


def scrape_rotowire():
    """Scrape starting lineups + sportsbook lines from RotoWire.

    Returns:
        lineups: {team_abbr: {"starters": [(name, pos, status)...], "out": [name...], "questionable": [name...]}}
        lines: {(home_abbr, away_abbr): {"spread": float, "total": float, "fav": str}}
        matchup_pairs: [(home_abbr, away_abbr), ...]
        slate_date: str like "FEB 20"
    """
    url = "https://www.rotowire.com/basketball/nba-lineups.php"
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        })
        resp.raise_for_status()
        html = resp.text
    except (requests.RequestException, ValueError) as e:
        logger.warning("RotoWire: failed to fetch: %s", e)
        return {}, {}, [], None, {}

    soup = BeautifulSoup(html, "html.parser")

    # ── Extract team abbreviations (come in pairs: away, home) ──
    team_els = soup.select(".lineup__abbr")
    team_abbrs = [el.get_text(strip=True) for el in team_els]
    if len(team_abbrs) < 2:
        logger.warning("RotoWire: no teams found")
        return {}, {}, [], None, {}

    # Build matchup pairs (every 2 teams = 1 game: away, home)
    matchup_pairs = []
    for i in range(0, len(team_abbrs) - 1, 2):
        away = team_abbrs[i]
        home = team_abbrs[i + 1]
        matchup_pairs.append((home, away))

    logger.info("RotoWire: found %d games, %d teams", len(matchup_pairs), len(team_abbrs))

    # ── Extract game times from parent containers ──
    # Structure: .lineup.is-nba > .lineup__time (text: "7:00 PM ET" or "Final")
    #                            > .lineup__box > ...
    game_times = {}
    game_containers = soup.select(".lineup.is-nba")
    for container in game_containers:
        # Skip ad/tools containers
        container_classes = " ".join(container.get("class", []))
        if "is-tools" in container_classes:
            continue

        time_el = container.select_one(".lineup__time")
        if not time_el:
            continue
        time_text = time_el.get_text(strip=True)

        # Find the home/away teams in this container's box
        box = container.select_one(".lineup__box")
        if not box:
            continue
        abbr_els = box.select(".lineup__abbr")
        if len(abbr_els) < 2:
            continue

        c_home, c_away = None, None
        for abbr_el in abbr_els:
            abbr_text = abbr_el.get_text(strip=True)
            parent_link = abbr_el.parent
            parent_classes = " ".join(parent_link.get("class", []) if parent_link else [])
            if "is-visit" in parent_classes:
                c_away = abbr_text
            elif "is-home" in parent_classes:
                c_home = abbr_text

        if c_home and c_away:
            game_times[(c_home, c_away)] = time_text

    if game_times:
        logger.info("RotoWire: extracted %d game times", len(game_times))

    # ── Extract lineups per team ──
    # Each .lineup__box = one game, containing:
    #   - 2x .lineup__abbr (visit, home) inside .lineup__teams
    #   - 1x .lineup__main with 2x .lineup__list (is-visit, is-home)
    lineups = {}
    game_boxes = soup.select(".lineup__box")

    for box in game_boxes:
        # Get the two team abbreviations in this box
        abbr_els = box.select(".lineup__abbr")
        if len(abbr_els) < 2:
            continue

        # Away team abbr is in the .is-visit parent, home in .is-home
        box_abbrs = {}
        for abbr_el in abbr_els:
            abbr_text = abbr_el.get_text(strip=True)
            parent_link = abbr_el.parent
            parent_classes = " ".join(parent_link.get("class", []) if parent_link else [])
            if "is-visit" in parent_classes:
                box_abbrs["visit"] = abbr_text
            elif "is-home" in parent_classes:
                box_abbrs["home"] = abbr_text

        # Get the two lineup lists (is-visit, is-home)
        lineup_lists = box.select(".lineup__list")
        for lst in lineup_lists:
            lst_classes = " ".join(lst.get("class", []))
            if "is-visit" in lst_classes:
                team_abbr = box_abbrs.get("visit")
            elif "is-home" in lst_classes:
                team_abbr = box_abbrs.get("home")
            else:
                continue

            if not team_abbr:
                continue

            starters = []
            out_players = []
            questionable_players = []

            for player_el in lst.select(".lineup__player"):
                link = player_el.select_one("a")
                if not link:
                    continue
                name = link.get_text(strip=True)

                pos_el = player_el.select_one(".lineup__pos")
                pos = pos_el.get_text(strip=True) if pos_el else ""

                classes = " ".join(player_el.get("class", []))
                if "is-pct-play-0" in classes:
                    out_players.append(name)
                elif "is-pct-play-25" in classes or "is-pct-play-50" in classes:
                    questionable_players.append(name)

                # Starters = first 5 with standard positions
                if pos in ("PG", "SG", "SF", "PF", "C") and len(starters) < 5:
                    if "is-pct-play-0" not in classes:
                        starters.append((name, pos, "IN"))
                    else:
                        starters.append((name, pos, "OUT"))

            lineups[team_abbr] = {
                "starters": starters,
                "out": out_players,
                "questionable": questionable_players,
            }

    # ── Extract composite odds (spreads + totals) ──
    lines = {}
    odds_spans = soup.select(".composite")
    odds_texts = [el.get_text(strip=True) for el in odds_spans]

    # Every 3 odds = 1 game: [moneyline, spread, total]
    game_idx = 0
    for i in range(0, len(odds_texts) - 2, 3):
        if game_idx >= len(matchup_pairs):
            break

        home_abbr, away_abbr = matchup_pairs[game_idx]
        ml_text = odds_texts[i]
        spread_text = odds_texts[i + 1]
        total_text = odds_texts[i + 2]

        try:
            # Parse spread: "CLE -5.0" or "-0.5" (no team = home fav)
            spread_match = re.match(r'([A-Z]{2,3})?\s*([+-]?\d+\.?\d*)', spread_text)
            if spread_match:
                fav_team = spread_match.group(1)
                spread_val = float(spread_match.group(2))

                # Convert to home-team convention (negative = home favored)
                if fav_team and fav_team == away_abbr:
                    # Away team is favored: home spread is positive (underdog)
                    home_spread = abs(spread_val)
                elif fav_team and fav_team == home_abbr:
                    # Home team is favored: home spread is negative
                    home_spread = -abs(spread_val)
                else:
                    # No team prefix or pick'em — treat spread value as home perspective
                    home_spread = spread_val

                # Round to nearest 0.5
                home_spread = round(home_spread * 2) / 2
            else:
                home_spread = 0

            # Parse total: "229.5 Pts"
            total_match = re.match(r'(\d+\.?\d*)', total_text)
            total_val = float(total_match.group(1)) if total_match else 0

            lines[(home_abbr, away_abbr)] = {
                "spread": home_spread,
                "total": total_val,
            }
        except (ValueError, KeyError, IndexError) as e:
            logger.warning("RotoWire: failed to parse odds for game %d: %s", game_idx, e)

        game_idx += 1

    # Determine slate date
    today = datetime.now()
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    slate_date = f"{months[today.month - 1]} {today.day}"

    logger.info("RotoWire: parsed %d team lineups, %d game lines", len(lineups), len(lines))
    for pair, line_data in lines.items():
        home, away = pair
        sp = line_data["spread"]
        if sp <= 0:
            logger.debug("  %s@%s: %s %+.1f, O/U %s", away, home, home, sp, line_data['total'])
        else:
            logger.debug("  %s@%s: %s %+.1f, O/U %s", away, home, away, -sp, line_data['total'])

    return lineups, lines, matchup_pairs, slate_date, game_times


# Basketball Monster abbreviation mapping (BM → our system)
BM_ABBR_MAP = {"PHO": "PHX"}

# Basketball Reference abbreviation mapping (BREF → our system)
BREF_ABBR_MAP = {"BRK": "BKN", "CHO": "CHA", "PHO": "PHX"}


def scrape_basketball_monster():
    """Fallback lineup scraper using Basketball Monster for overnight gaps.

    Used when RotoWire hasn't updated to tomorrow's slate yet.
    Returns same format as scrape_rotowire():
        (lineups, lines, matchup_pairs, slate_date, game_times)
    """
    import re

    url = "https://basketballmonster.com/nbalineups.aspx"
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        resp.raise_for_status()
    except (requests.RequestException, ValueError) as e:
        logger.warning("BM: failed to fetch: %s", e)
        return {}, {}, [], "", {}

    soup = BeautifulSoup(resp.text, "html.parser")

    # Parse date from heading: "NBA Lineups for Sunday 2/22 (11 games)"
    heading = soup.find("h1")
    slate_date = ""
    if heading:
        h_text = heading.get_text(strip=True)
        date_match = re.search(r"(\d{1,2})/(\d{1,2})", h_text)
        if date_match:
            months = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
            month_idx = int(date_match.group(1)) - 1
            day = int(date_match.group(2))
            slate_date = f"{months[month_idx]} {day}"
        logger.debug("BM: heading: %s", h_text)

    lineups = {}
    lines = {}
    matchup_pairs = []
    game_times = {}

    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 7:
            continue

        # Row 0: Header — "CLE @ OKC 1:00 PM ET in 9.7h CLE by 3.5 o/u 226.5"
        header_th = rows[0].find("th")
        if not header_th:
            continue
        header_text = header_th.get_text(" ", strip=True)

        # Parse matchup: AWAY @ HOME
        matchup_match = re.match(r"(\w{2,3})\s*@\s*(\w{2,3})", header_text)
        if not matchup_match:
            continue
        away_raw = matchup_match.group(1)
        home_raw = matchup_match.group(2)
        away = BM_ABBR_MAP.get(away_raw, away_raw)
        home = BM_ABBR_MAP.get(home_raw, home_raw)

        # Parse time: "1:00 PM ET"
        time_match = re.search(r"(\d{1,2}:\d{2}\s*[AP]M\s*ET)", header_text)
        game_time = time_match.group(1) if time_match else ""

        # Parse spread: "CLE by 3.5" or could be home team
        spread_val = 0.0
        spread_match = re.search(r"(\w{2,3})\s+by\s+([\d.]+)", header_text)
        if spread_match:
            fav_raw = spread_match.group(1)
            fav = BM_ABBR_MAP.get(fav_raw, fav_raw)
            points = float(spread_match.group(2))
            # Spread convention: negative = home favored
            if fav == home:
                spread_val = -points
            else:
                spread_val = points

        # Parse total: "o/u 226.5"
        total_val = 0.0
        total_match = re.search(r"o/u\s+([\d.]+)", header_text)
        if total_match:
            total_val = float(total_match.group(1))

        # Row 1: Team headers (skip)
        # Rows 2-6: PG, SG, SF, PF, C — position | away player | home player
        positions = ["PG", "SG", "SF", "PF", "C"]
        away_starters = []
        home_starters = []
        away_out = []
        home_out = []
        away_questionable = []
        home_questionable = []

        for i, pos in enumerate(positions):
            row_idx = i + 2
            if row_idx >= len(rows):
                break
            cells = rows[row_idx].find_all("td")
            if len(cells) < 3:
                continue

            for col_idx, (starters_list, out_list, q_list) in [
                (1, (away_starters, away_out, away_questionable)),
                (2, (home_starters, home_out, home_questionable)),
            ]:
                cell = cells[col_idx]
                cell_text = cell.get_text(strip=True)

                # Check injury status
                status = "IN"
                name = cell_text
                if cell_text.endswith("Off Inj"):
                    name = cell_text[:-7].strip()
                    status = "OUT"
                    out_list.append(name)
                elif cell_text.endswith(" Q"):
                    name = cell_text[:-2].strip()
                    status = "GTD"
                    q_list.append(name)

                # Get player name from link if available
                link = cell.find("a")
                if link:
                    name = link.get_text(strip=True)

                starters_list.append((name, pos, status))

        # Build lineups dict (same format as RotoWire)
        lineups[away] = {
            "starters": away_starters,
            "out": away_out,
            "questionable": away_questionable,
        }
        lineups[home] = {
            "starters": home_starters,
            "out": home_out,
            "questionable": home_questionable,
        }

        pair = (home, away)
        matchup_pairs.append(pair)
        game_times[pair] = game_time

        if spread_val != 0 or total_val != 0:
            lines[pair] = {"spread": spread_val, "total": total_val}

    logger.info("BM: found %d games, %d teams (%s)", len(matchup_pairs), len(lineups), slate_date)
    for home, away in matchup_pairs:
        sp = lines.get((home, away), {}).get("spread", 0)
        total = lines.get((home, away), {}).get("total", 0)
        logger.debug("  %s@%s: %s %+.1f, O/U %s", away, home, home, sp, total)

    return lineups, lines, matchup_pairs, slate_date, game_times


def scrape_bref_injuries():
    """Scrape Basketball Reference injury report for league-wide OUT players.

    Returns dict: {team_abbr: [player_name, ...]} for players marked
    'Out' or 'Out For Season'. Excludes 'Day To Day' players.
    Non-blocking — returns empty dict on failure.
    """
    url = "https://www.basketball-reference.com/friv/injuries.fcgi"
    try:
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        table = soup.find("table", id="injuries")
        if not table:
            logger.warning("Injuries: BREF: no injury table found")
            return {}

        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

        out_by_team = {}
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 4:
                continue

            # Player name
            player_name = cells[0].get_text(strip=True)

            # Team abbreviation from href: /teams/ATL/2026.html → ATL
            team_link = cells[1].find("a")
            if not team_link or not team_link.get("href"):
                continue
            parts = team_link["href"].split("/")
            team_abbr = parts[2] if len(parts) >= 3 else None
            if not team_abbr:
                continue
            team_abbr = BREF_ABBR_MAP.get(team_abbr, team_abbr)

            # Description — filter for OUT only
            desc = cells[3].get_text(strip=True)
            if not desc.startswith("Out"):
                continue  # Skip "Day To Day"

            out_by_team.setdefault(team_abbr, []).append(player_name)

        total = sum(len(v) for v in out_by_team.values())
        logger.info("Injuries: Basketball Reference: %d OUT players across %d teams", total, len(out_by_team))
        return out_by_team

    except (requests.RequestException, AttributeError, ValueError) as e:
        logger.warning("Injuries: Basketball Reference scrape failed: %s", e)
        return {}


def filter_started_games(matchup_pairs, game_times, rw_lines):
    """Step 0: Remove games that have already started or finished.

    Uses NBA.com scoreboard API (primary) and RotoWire time text (fallback).
    Games with status text like 'Final', 'Q3 5:42', 'Halftime' are always filtered.

    Returns:
        (filtered_pairs, filtered_lines, removed_count)
    """
    from zoneinfo import ZoneInfo

    now_utc = datetime.now(timezone.utc)
    et_tz = ZoneInfo("America/New_York")
    now_et = now_utc.astimezone(et_tz)

    # Fetch NBA.com schedule for precise UTC times and game status
    nba_schedule = fetch_nba_schedule()

    filtered_pairs = []
    removed = []

    for pair in matchup_pairs:
        home, away = pair
        should_keep = True

        # ── Check 1: NBA.com status (most reliable) ──
        nba_game = nba_schedule.get(pair)
        if nba_game:
            if nba_game["status"] in (2, 3):
                # In-progress or final
                should_keep = False
                removed.append(f"{away}@{home} ({nba_game['status_text']})")
            elif nba_game["status"] == 1 and nba_game["utc"] <= now_utc:
                # Scheduled but commence time already passed
                should_keep = False
                removed.append(f"{away}@{home} (past tip: {nba_game['status_text']})")

        # ── Check 2: RotoWire time text (fallback if NBA.com missed it) ──
        if should_keep and pair in game_times:
            time_text = game_times[pair]

            # Non-time strings indicate started/finished games
            started_keywords = ["FINAL", "HALF", " OT", "Q1 ", "Q2 ", "Q3 ", "Q4 ",
                                "END OF", "1ST", "2ND", "3RD", "4TH"]
            if any(kw in time_text.upper() for kw in started_keywords):
                should_keep = False
                removed.append(f"{away}@{home} (RW: {time_text})")
            else:
                # Parse "7:00 PM ET" format
                try:
                    m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)\s*ET', time_text, re.IGNORECASE)
                    if m:
                        hour = int(m.group(1))
                        minute = int(m.group(2))
                        ampm = m.group(3).upper()
                        if ampm == "PM" and hour != 12:
                            hour += 12
                        elif ampm == "AM" and hour == 12:
                            hour = 0

                        # Build ET datetime for today
                        game_et = now_et.replace(hour=hour, minute=minute, second=0, microsecond=0)

                        if game_et <= now_et:
                            should_keep = False
                            removed.append(f"{away}@{home} (tip {time_text} already passed)")
                except (ValueError, KeyError) as e:
                    logger.warning("Step 0: could not parse time for %s@%s: %s (%s)", away, home, time_text, e)

        if should_keep:
            filtered_pairs.append(pair)

    if removed:
        logger.info("Step 0: filtered %d started/completed games:", len(removed))
        for r in removed:
            logger.info("  - %s", r)
    else:
        logger.info("Step 0: all games are upcoming — no filtering needed")

    # Prune lines dict for removed games
    removed_set = set(matchup_pairs) - set(filtered_pairs)
    filtered_lines = {k: v for k, v in rw_lines.items() if k not in removed_set}

    return filtered_pairs, filtered_lines, len(removed)


def is_back_to_back(team_tricode, game_date=None):
    """Check if a team is on a back-to-back using pre-computed schedule.

    Args:
        team_tricode: e.g. "BOS", "DEN"
        game_date: "YYYY-MM-DD" string, defaults to today

    Returns True if the team played yesterday (back-to-back).
    """
    if game_date is None:
        game_date = datetime.now().strftime("%Y-%m-%d")
    return (game_date, team_tricode) in _B2B_SCHEDULE


def _get_full_roster(team_abbr):
    """Get full rotation roster (mpg > 5) with archetypes."""
    return read_query(f"""
        SELECT p.player_id, p.full_name, ps.pts_pg, ps.ast_pg, ps.reb_pg,
               ps.stl_pg, ps.blk_pg, ps.ts_pct, ps.usg_pct, ps.net_rating,
               ps.minutes_per_game, ps.off_rating, ps.def_rating,
               ra.listed_position,
               pa.archetype_label, pa.position_group, pa.confidence as arch_confidence
        FROM player_season_stats ps
        JOIN players p ON ps.player_id = p.player_id
        JOIN roster_assignments ra ON ps.player_id = ra.player_id AND ps.season_id = ra.season_id
        JOIN teams t ON ps.team_id = t.team_id
        LEFT JOIN player_archetypes pa ON ps.player_id = pa.player_id AND ps.season_id = pa.season_id
        WHERE ps.season_id = '{CURRENT_SEASON}' AND t.abbreviation = ?
              AND ps.minutes_per_game > 5
        ORDER BY ps.minutes_per_game DESC
    """, DB_PATH, [team_abbr])


_NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}


def _normalize_name(name):
    """Strip suffixes (Jr., III, etc.) and lowercase for matching.

    Returns list of name parts with suffixes removed.
    Example: "Jimmy Butler III" → ["jimmy", "butler"]
    """
    parts = name.lower().strip().split()
    while parts and parts[-1] in _NAME_SUFFIXES:
        parts.pop()
    return parts


def _match_player_name(scraped_name, db_players):
    """Fuzzy match a scraped name (e.g. 'D. Mitchell') to a full DB name.

    Returns player_id or None.
    """
    scraped_lower = scraped_name.lower().strip()
    scraped_norm = _normalize_name(scraped_name)

    # Try exact match first (with and without suffix)
    for _, row in db_players.iterrows():
        db_lower = row["full_name"].lower()
        if db_lower == scraped_lower:
            return row["player_id"]
        # Normalized match: "Jimmy Butler" == "Jimmy Butler III"
        db_norm = _normalize_name(row["full_name"])
        if db_norm == scraped_norm and scraped_norm:
            return row["player_id"]

    # Try "First Last" vs "F. Last" matching
    for _, row in db_players.iterrows():
        db_norm = _normalize_name(row["full_name"])
        if len(db_norm) >= 2:
            # "D. Mitchell" matches "Donovan Mitchell"
            abbrev = f"{db_norm[0][0]}. {' '.join(db_norm[1:])}"
            if abbrev == scraped_lower or abbrev == " ".join(scraped_norm):
                return row["player_id"]
            # Last name + first initial fallback (suffix-safe)
            scraped_last = scraped_norm[-1] if scraped_norm else ""
            db_last = db_norm[-1] if db_norm else ""
            if db_last == scraped_last and scraped_last:
                scraped_init = scraped_norm[0][0] if scraped_norm else ""
                db_init = db_norm[0][0] if db_norm else ""
                if scraped_init == db_init and scraped_init:
                    return row["player_id"]

    return None


def project_minutes(roster_df, out_player_ids):
    """Redistribute minutes from OUT players to remaining rotation.

    Returns {player_id: projected_minutes} for available players.
    """
    available = roster_df[~roster_df["player_id"].isin(out_player_ids)].copy()
    out_players = roster_df[roster_df["player_id"].isin(out_player_ids)]

    if available.empty:
        return {}

    missing_minutes = out_players["minutes_per_game"].sum() if not out_players.empty else 0

    # Distribute proportionally by existing minutes
    total_available_minutes = available["minutes_per_game"].sum()
    if total_available_minutes == 0:
        return {}

    projected = {}
    for _, row in available.iterrows():
        pid = row["player_id"]
        base_mpg = row["minutes_per_game"] or 0
        share = base_mpg / total_available_minutes
        extra = missing_minutes * share
        proj_mpg = min(40.0, base_mpg + extra)  # cap at 40 MPG
        projected[pid] = proj_mpg

    return projected


def compute_adjusted_mojo(roster_df, out_player_ids, projected_minutes):
    """Compute MOJI: MOJOs adjusted for who's actually playing.

    Uses archetypes to route usage from missing players to remaining ones.
    Applies stocks loss penalty when high-STL/BLK players are OUT.
    Returns (team_moji, player_mojo_dict, breakdown_notes).
    """
    K = _MOJI_CONSTANTS
    available = roster_df[~roster_df["player_id"].isin(out_player_ids)]
    out_players = roster_df[roster_df["player_id"].isin(out_player_ids)]

    if available.empty:
        return 50.0, {}, []

    # Calculate total usage + stocks being lost from OUT players
    # Also track waste-clearing and shooter-gravity for scheme-aware adjustments
    missing_usage = 0
    missing_stocks = 0.0
    missing_archetypes = []
    missing_positions = []
    waste_clearing_bonus = 0.0  # positive = inefficient player OUT, remaining players benefit
    missing_shooter_gravity = 0.0  # positive = shooters OUT, spacing collapses

    for _, out_row in out_players.iterrows():
        usg = out_row.get("usg_pct", 0) or 0
        ts = out_row.get("ts_pct", 0) or 0
        missing_usage += usg
        # Stocks loss: STL + BLK weighted by minutes share
        stl = out_row.get("stl_pg", 0) or 0
        blk = out_row.get("blk_pg", 0) or 0
        mpg = out_row.get("minutes_per_game", 0) or 0
        missing_stocks += (stl + blk) * (mpg / 36.0)
        arch = str(out_row.get("archetype_label", "") or "")
        pos = str(out_row.get("position_group", "") or out_row.get("listed_position", ""))
        if arch and arch != "nan":
            missing_archetypes.append(arch)
        if pos:
            missing_positions.append(pos)

        # ── Waste clearing: was this OUT player an efficiency sink? ──
        # If a high-USG, low-TS player is OUT, remaining efficient players benefit.
        # League avg TS ~0.560 — players well below avg burning possessions = waste
        if usg > 0.15 and ts < 0.540:
            # Inefficiency magnitude: how far below avg × how much usage they burned
            inefficiency = max(0, 0.560 - ts) * 100  # TS% points below league avg
            waste_bonus = inefficiency * usg * (mpg / 30.0)  # scaled by role size
            waste_clearing_bonus += waste_bonus

        # ── Shooter gravity: losing a shooter collapses floor spacing ──
        # Affects rim-runners, cutters, slashers who depend on spacing
        out_profile = _PLAYER_PLAY_PROFILE.get(out_row["player_id"], {})
        out_spotup = out_profile.get("Spotup", {})
        out_3pt_ppp = out_spotup.get("ppp", 0)
        # Elite spot-up shooter (>1.1 PPP) or Sharpshooter archetype
        is_shooter = (
            out_3pt_ppp > 1.10 or
            arch in {"Sharpshooter", "3-and-D Wing"} or
            (out_row.get("fg3_pct", 0) or 0) > 0.38
        )
        if is_shooter:
            missing_shooter_gravity += mpg / 36.0  # weighted by minutes

    # Determine archetype category of missing players
    missing_is_scoring = any(a in _SCORING_ARCHETYPES for a in missing_archetypes)
    missing_is_playmaking = any(a in _PLAYMAKING_ARCHETYPES for a in missing_archetypes)
    missing_is_big = any(a in _BIG_ARCHETYPES for a in missing_archetypes)
    missing_is_defensive = any(a in _DEFENSIVE_ARCHETYPES for a in missing_archetypes)
    missing_is_guard = any(p in _GUARD_POSITIONS for p in missing_positions)
    missing_is_wing = any(p in _WING_POSITIONS for p in missing_positions)
    missing_is_bigpos = any(p in _BIG_POSITIONS for p in missing_positions)

    # Compute adjusted MOJO for each available player
    player_mojo = {}
    notes = []
    total_weighted_mojo = 0
    total_minutes = 0

    for _, row in available.iterrows():
        pid = row["player_id"]
        proj_min = projected_minutes.get(pid, row.get("minutes_per_game", 0) or 0)
        if proj_min <= 0:
            continue

        base_usg = row.get("usg_pct", 0) or 0
        arch = str(row.get("archetype_label", "") or "")
        pos = str(row.get("position_group", "") or row.get("listed_position", ""))

        # Calculate usage boost from missing players
        usage_boost = 0
        if missing_usage > 0 and len(available) > 0:
            # Same archetype gets 60% of redistributed usage
            same_arch = arch in missing_archetypes
            same_pos_category = (
                (pos in _GUARD_POSITIONS and missing_is_guard) or
                (pos in _WING_POSITIONS and missing_is_wing) or
                (pos in _BIG_POSITIONS and missing_is_bigpos)
            )
            same_scoring = (arch in _SCORING_ARCHETYPES and missing_is_scoring)
            same_playmaking = (arch in _PLAYMAKING_ARCHETYPES and missing_is_playmaking)
            same_big = (arch in _BIG_ARCHETYPES and missing_is_big)
            same_defensive = (arch in _DEFENSIVE_ARCHETYPES and missing_is_defensive)

            if same_arch:
                usage_boost = missing_usage * 0.60 / max(1, sum(
                    1 for _, r in available.iterrows()
                    if str(r.get("archetype_label", "")) in missing_archetypes
                ))
            elif same_pos_category or same_scoring or same_playmaking or same_big or same_defensive:
                usage_boost = missing_usage * 0.25 / max(1, sum(
                    1 for _, r in available.iterrows()
                    if str(r.get("position_group", "") or r.get("listed_position", "")) in missing_positions
                    or (str(r.get("archetype_label", "")) in _SCORING_ARCHETYPES and missing_is_scoring)
                    or (str(r.get("archetype_label", "")) in _PLAYMAKING_ARCHETYPES and missing_is_playmaking)
                    or (str(r.get("archetype_label", "")) in _BIG_ARCHETYPES and missing_is_big)
                    or (str(r.get("archetype_label", "")) in _DEFENSIVE_ARCHETYPES and missing_is_defensive)
                ))
            else:
                # Everyone else gets remaining share
                remaining_share = missing_usage * 0.15
                usage_boost = remaining_share / max(1, len(available))

        adjusted_usg = base_usg + usage_boost

        # Build a modified row for MOJO calculation
        modified_row = dict(row)
        modified_row["minutes_per_game"] = proj_min

        # Defensive archetypes only absorb 50% of offensive usage boost
        if arch in _DEFENSIVE_ARCHETYPES and usage_boost > 0:
            modified_row["usg_pct"] = base_usg + (usage_boost * 0.5)
        else:
            modified_row["usg_pct"] = adjusted_usg

        ds, _ = compute_mojo_score(modified_row)

        # ── Efficiency penalty: scheme-aware + per-player curves ──
        # Replaces uniform 0.995 decay with empirical USG-efficiency data
        # and play-type compatibility scoring.
        if usage_boost > 0:
            usage_increase_pct = (usage_boost / base_usg * 100) if base_usg > 0 else 0

            # Step 1: Per-player decay rate from empirical USG-TS curves
            # (replaces uniform 0.995 for all players)
            curve = _USG_CURVES.get(pid)
            if curve:
                ts_slope = curve["ts_per_usg"]  # TS% change per 1% USG increase
                if ts_slope >= 0:
                    # LOAD-BEARER: efficiency flat or rises with usage
                    # (Giannis +0.05%, Trae +14.5%, Alex Sarr +0.24%)
                    decay_rate = 1.0  # no penalty
                elif ts_slope >= -0.5:
                    # MODERATE: mild decay — can handle some extra load
                    decay_rate = 0.998
                elif ts_slope >= -1.5:
                    # STANDARD: typical role expansion decay
                    decay_rate = 0.995
                else:
                    # HEAVY DECAY: efficiency collapses under load
                    # (e.g., -2.92%/USG or worse)
                    decay_rate = 0.990
            else:
                # No curve data — fall back to archetype-based defaults
                if arch in _DEFENSIVE_ARCHETYPES:
                    decay_rate = K["USAGE_DECAY_DEF"]   # 0.985
                else:
                    decay_rate = K["USAGE_DECAY"]        # 0.995

            # Step 2: Play-type compatibility modifier
            # Measures how well this player absorbs the SPECIFIC play types
            # freed by OUT players (PnR, ISO, Spotup, etc.)
            play_quality = _compute_play_type_absorption(pid, out_player_ids)
            if play_quality > 1.05:
                # Player is ABOVE average at absorbing these play types
                # (e.g., elite PnR guard absorbing PnR possessions)
                # Soften the decay — they handle these plays well
                decay_rate = min(1.0, decay_rate + (play_quality - 1.0) * 0.02)
            elif play_quality < 0.90:
                # Player is BELOW average at these play types
                # (e.g., center absorbing guard isolation plays)
                # Harsher penalty — play type mismatch
                decay_rate = max(0.980, decay_rate - (1.0 - play_quality) * 0.02)

            efficiency_penalty = decay_rate ** usage_increase_pct
            ds = int(ds * efficiency_penalty)
            ds = max(33, ds)

        # ── Step 3: Waste clearing boost ──
        # When a high-USG low-efficiency player is OUT, remaining efficient
        # players benefit: the freed possessions were being WASTED, and now
        # they flow to players who convert better. This is the inverse of
        # the normal "missing player = team gets worse" assumption.
        if waste_clearing_bonus > 0:
            player_ts = row.get("ts_pct", 0) or 0
            if player_ts > 0.560:
                # Only efficient players benefit from waste clearing
                # Scale: ~0.5 MOJO per waste unit for an efficient absorber
                ts_above_avg = (player_ts - 0.560) * 100
                boost = min(3, waste_clearing_bonus * ts_above_avg * 0.01)
                ds = min(99, int(ds + boost))

        # ── Step 4: Shooter gravity penalty ──
        # When shooters are OUT, floor spacing collapses. Rim-runners, cutters,
        # and slashers who depend on spacing lose efficiency even if they don't
        # absorb the shooter's possessions directly.
        if missing_shooter_gravity > 0:
            spacing_dependent = arch in {
                "Traditional Center", "Rim Protector", "Versatile Big",
                "Slasher", "Athletic Wing",
            }
            # Also check play type profile: heavy Cut/PnR Roll Man = spacing dependent
            player_profile = _PLAYER_PLAY_PROFILE.get(pid, {})
            cut_share = player_profile.get("Cut", {}).get("poss_share", 0)
            roll_share = player_profile.get("PRRollMan", {}).get("poss_share", 0)
            if spacing_dependent or (cut_share + roll_share) > 0.30:
                # 1.0 MOJO penalty per missing shooter (weighted by their minutes)
                gravity_penalty = missing_shooter_gravity * 1.0
                ds = max(33, int(ds - gravity_penalty))

        player_mojo[pid] = ds
        total_weighted_mojo += ds * proj_min
        total_minutes += proj_min

    raw_team_moji = total_weighted_mojo / total_minutes if total_minutes > 0 else 50.0

    # Stocks loss penalty: team loses MOJI for missing STL+BLK production
    stocks_penalty = missing_stocks * K["STOCKS_PENALTY"]
    team_moji = max(33.0, raw_team_moji - stocks_penalty)

    return team_moji, player_mojo, notes


def compute_lineup_rating(team_abbr, available_player_ids, team_net_rating):
    """Compute lineup quality from combo data for available players.

    Returns lineup_quality (float, net-rating scale).
    """
    # Get all reliable lineups for this team
    lineups_5 = read_query(f"""
        SELECT player_ids, net_rating, minutes, gp
        FROM lineup_stats
        WHERE season_id = '{CURRENT_SEASON}' AND group_quantity = 5
              AND gp > 5 AND minutes > 8
              AND team_id = (SELECT team_id FROM teams WHERE abbreviation = ?)
    """, DB_PATH, [team_abbr])

    lineups_small = read_query(f"""
        SELECT player_ids, net_rating, minutes, gp, group_quantity
        FROM lineup_stats
        WHERE season_id = '{CURRENT_SEASON}' AND group_quantity IN (2, 3)
              AND gp > 5 AND minutes > 15
              AND team_id = (SELECT team_id FROM teams WHERE abbreviation = ?)
        ORDER BY net_rating DESC
        LIMIT 5
    """, DB_PATH, [team_abbr])

    available_set = set(available_player_ids)

    # Filter 5-man lineups to only those where ALL players are available
    valid_5man = []
    for _, row in lineups_5.iterrows():
        try:
            pids = json.loads(row["player_ids"]) if isinstance(row["player_ids"], str) else []
            if all(int(p) in available_set for p in pids):
                valid_5man.append(row)
        except (json.JSONDecodeError, ValueError):
            continue

    # 5-man quality (minutes-weighted, dampened by sample size)
    if valid_5man:
        n = len(valid_5man)
        dampener = min(1.0, n / 4.0)
        wt_sum = sum(r["net_rating"] * r["minutes"] for r in valid_5man)
        min_sum = sum(r["minutes"] for r in valid_5man)
        raw_5q = wt_sum / min_sum if min_sum > 0 else team_net_rating
        fiveman_quality = dampener * raw_5q + (1 - dampener) * team_net_rating
    else:
        fiveman_quality = team_net_rating

    # 2/3-man quality (top combos with available players)
    valid_small = []
    for _, row in lineups_small.iterrows():
        try:
            pids = json.loads(row["player_ids"]) if isinstance(row["player_ids"], str) else []
            if all(int(p) in available_set for p in pids):
                valid_small.append(row)
        except (json.JSONDecodeError, ValueError):
            continue

    if valid_small:
        small_quality = sum(r["net_rating"] for r in valid_small[:3]) / min(3, len(valid_small))
    else:
        small_quality = team_net_rating

    return 0.65 * fiveman_quality + 0.35 * small_quality


def _classify_pair_category(arch_a, arch_b):
    """Classify a pair of archetypes into guard_guard, guard_big, wing_wing, wing_big, or big_big."""
    guard_archs = {"Scoring Guard", "Defensive Specialist", "Floor General",
                   "Combo Guard", "Playmaking Guard"}
    big_archs = {"Rim Protector", "Stretch 5", "Traditional Center", "Versatile Big",
                 "Stretch Big", "Traditional PF"}
    # Everything else is wing

    def _cat(arch):
        if arch in guard_archs:
            return "guard"
        elif arch in big_archs:
            return "big"
        else:
            return "wing"

    cat_a = _cat(arch_a or "")
    cat_b = _cat(arch_b or "")
    cats = sorted([cat_a, cat_b])
    return f"{cats[0]}_{cats[1]}"


def _parse_scheme(opp_def_scheme):
    """Parse 'Switch-Everything (Elite)' → ('Switch-Everything', 'Elite')."""
    scheme_type = "Drop-Coverage"
    scheme_quality = "Avg"
    if opp_def_scheme:
        parts = opp_def_scheme.split(" (")
        scheme_type = parts[0]
        if len(parts) > 1:
            scheme_quality = parts[1].rstrip(")")
    return scheme_type, scheme_quality


def _build_pair_lookup(pairs_df):
    """Build {(min_pid, max_pid): {syn, poss, arch_a, arch_b}} from pair_synergy DataFrame."""
    lookup = {}
    if pairs_df is None or pairs_df.empty:
        return lookup
    for _, row in pairs_df.iterrows():
        a = int(row["player_a_id"])
        b = int(row["player_b_id"])
        key = (min(a, b), max(a, b))
        lookup[key] = {
            "syn": float(row["synergy_score"] or 50),
            "poss": float(row["possessions"] or 1),
            "arch_a": row.get("archetype_a") or "",
            "arch_b": row.get("archetype_b") or "",
        }
    return lookup


def _get_alive_lineups(lineup_df, avail_set, group_size):
    """Filter N-man lineups to those where all N players are available tonight."""
    alive = []
    if lineup_df is None or lineup_df.empty:
        return alive
    for _, row in lineup_df.iterrows():
        try:
            pids = [int(p) for p in json.loads(row["player_ids"])]
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        if len(pids) == group_size and all(p in avail_set for p in pids):
            alive.append({
                "player_ids": pids,
                "raw_nrtg": float(row["net_rating"]),
                "possessions": float(row["possessions"]),
                "historical_minutes": float(row["minutes"] or 0),
                "group_size": group_size,
            })
    alive.sort(key=lambda x: x["historical_minutes"], reverse=True)
    return alive


def _estimate_5man_from_core(core_lineup, avail_ids, pair_lookup, projected_minutes,
                              player_mojo_dict, usg_min_rank):
    """Build 5-man lineups by plugging missing players into a core (4/3/2-man combo).

    For each missing slot, score ALL available candidates by their WOWY pair
    synergy with the current core. Return up to 3 lineup variants (one per
    top candidate combination) so the system averages across multiple possible
    rotations — preventing selection bias from only keeping the best fit.

    Players are ranked by usage+minutes ordering for candidate priority.
    Returns list of completed 5-man lineup dicts (up to 3).
    """
    core_pids = set(core_lineup["player_ids"])
    n_missing = 5 - len(core_pids)
    if n_missing <= 0:
        return []

    # Candidates: available players not in the core, sorted by usage+minutes rank
    candidates = [p for p in usg_min_rank if p not in core_pids]
    if len(candidates) < n_missing:
        return []

    def _score_candidate(cand, current_pids_list):
        """Score a candidate's WOWY fit with the current lineup members."""
        fit_scores = []
        for existing in current_pids_list:
            key = (min(cand, existing), max(cand, existing))
            pair_data = pair_lookup.get(key)
            if pair_data:
                fit_scores.append(pair_data["syn"])
            else:
                fit_scores.append(45.0)  # unknown pair = slight negative risk
        avg_fit = sum(fit_scores) / len(fit_scores) if fit_scores else 45.0
        mpg_bonus = projected_minutes.get(cand, 0) * 0.1
        return avg_fit + mpg_bonus

    def _compute_plug_adj(plug_pid, full_pids):
        """Compute NRtg adjustment for a plugged-in player using WOWY + role amplification."""
        # WOWY signal: average pair synergy with every core player
        plug_fits = []
        for cp in core_lineup["player_ids"]:
            key = (min(plug_pid, cp), max(plug_pid, cp))
            pair_data = pair_lookup.get(key)
            plug_fits.append(pair_data["syn"] if pair_data else 45.0)
        wowy_with_core = sum(plug_fits) / len(plug_fits) if plug_fits else 45.0

        # Elevated role: if projected minutes >> season average,
        # this player shares more court time with the core → WOWY data is more predictive
        proj_mpg = projected_minutes.get(plug_pid, 0)
        vs = _VALUE_SCORES.get(plug_pid)
        season_mpg = vs.get("minutes", 20) if vs else 20
        minutes_bump = max(0, (proj_mpg - season_mpg) / max(season_mpg, 1))

        # Amplify WOWY adjustment: up to 1.5× when player is in a much bigger role
        wowy_amplifier = 1.0 + min(0.5, minutes_bump * 0.5)
        wowy_adj = ((wowy_with_core - 50.0) * 0.4) / 5.0 * wowy_amplifier

        # Small MOJO kicker (raw player quality vs lineup avg)
        ds = player_mojo_dict.get(plug_pid, 50)
        team_avg = sum(player_mojo_dict.get(p, 50) for p in full_pids) / 5
        ds_adj = (ds - team_avg) * 0.03 / 5.0

        return wowy_adj + ds_adj

    if n_missing == 1:
        # 4-man core → plug 1: return up to 3 lineup variants
        scored = [(c, _score_candidate(c, list(core_pids))) for c in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        top_picks = scored[:3]

        results = []
        for pick_pid, _ in top_picks:
            full_pids = list(core_pids) + [pick_pid]
            adj = _compute_plug_adj(pick_pid, full_pids)
            results.append({
                "player_ids": full_pids,
                "raw_nrtg": core_lineup["raw_nrtg"] + adj,
                "possessions": core_lineup["possessions"],
                "historical_minutes": core_lineup["historical_minutes"],
                "group_size": 5,
                "base_group": core_lineup["group_size"],
            })
        return results

    else:
        # 3-man or 2-man core → plug multiple slots
        # Generate up to 3 lineup variants by varying the first plug choice
        # then greedily filling the rest
        first_slot_scored = [(c, _score_candidate(c, list(core_pids))) for c in candidates]
        first_slot_scored.sort(key=lambda x: x[1], reverse=True)
        first_picks = first_slot_scored[:3]

        results = []
        for first_pid, _ in first_picks:
            current_pids = list(core_pids) + [first_pid]
            remaining_cands = [c for c in candidates if c != first_pid]

            # Greedily fill remaining slots
            for _ in range(n_missing - 1):
                best_pid = None
                best_fit = -999
                for cand in remaining_cands:
                    if cand in current_pids:
                        continue
                    total_fit = _score_candidate(cand, current_pids)
                    if total_fit > best_fit:
                        best_fit = total_fit
                        best_pid = cand
                if best_pid is None:
                    break
                current_pids.append(best_pid)

            if len(current_pids) != 5:
                continue

            # Compute adjustments for ALL plugged players
            plugged_pids = [p for p in current_pids if p not in core_pids]
            adj = sum(_compute_plug_adj(pp, current_pids) for pp in plugged_pids)

            results.append({
                "player_ids": current_pids,
                "raw_nrtg": core_lineup["raw_nrtg"] + adj,
                "possessions": core_lineup["possessions"],
                "historical_minutes": core_lineup["historical_minutes"],
                "group_size": 5,
                "base_group": core_lineup["group_size"],
            })

        return results


def _assign_lineup_minutes(all_lineups, projected_minutes):
    """Estimate minutes per lineup using bottleneck heuristic, normalize to 48.

    Lineups built from higher group sizes (direct 5-man) get more weight than
    those built from 2-man cores with 3 plugged players.
    """
    # Confidence factor by base group size: 5-man data is most reliable
    group_confidence = {5: 1.0, 4: 0.8, 3: 0.5, 2: 0.3}

    raw_estimates = []
    for lu in all_lineups:
        bottleneck = min((projected_minutes.get(p, 0) for p in lu["player_ids"]), default=0)
        history_bonus = min(lu["historical_minutes"] / 20.0, 1.0)
        base_group = lu.get("base_group", lu.get("group_size", 5))
        confidence = group_confidence.get(base_group, 0.5)
        estimate = bottleneck * (0.3 + 0.7 * history_bonus) * confidence
        raw_estimates.append(max(estimate, 0.5))

    total_raw = sum(raw_estimates)
    if total_raw > 0:
        for i, lu in enumerate(all_lineups):
            lu["est_minutes"] = (raw_estimates[i] / total_raw) * 48.0


def _compute_pair_composite(player_ids, pair_lookup):
    """Possession-weighted average pair synergy for all C(N,2) pairs in a lineup.

    Known pairs (with WOWY data) are weighted by their possessions.
    Unknown pairs (no shared court time data) are treated as slightly negative
    risk (syn=45) with very low weight (0.1) so they barely affect the average
    but don't inflate it either.
    """
    from itertools import combinations
    total_syn = 0.0
    total_w = 0.0
    for a, b in combinations(player_ids, 2):
        key = (min(a, b), max(a, b))
        pair_data = pair_lookup.get(key)
        if pair_data:
            total_syn += pair_data["syn"] * pair_data["poss"]
            total_w += pair_data["poss"]
        else:
            # Unknown pair: no shared court time data → slight negative risk
            # Low weight so these don't dominate OR get a free pass
            total_syn += 45.0 * 0.1
            total_w += 0.1
    return total_syn / total_w if total_w > 0 else 50.0


def _compute_lineup_scheme_mult(player_ids, pair_lookup, scheme_type, quality_factors):
    """Average scheme interaction multiplier across all 10 pairs in a 5-man lineup."""
    from itertools import combinations
    from config import SCHEME_INTERACTION
    mults = []
    for a, b in combinations(player_ids, 2):
        key = (min(a, b), max(a, b))
        pair_data = pair_lookup.get(key)
        arch_a = pair_data["arch_a"] if pair_data else ""
        arch_b = pair_data["arch_b"] if pair_data else ""

        pair_cat = _classify_pair_category(arch_a, arch_b)
        base_mult = SCHEME_INTERACTION.get((pair_cat, scheme_type), 1.0)

        if base_mult > 1.0:
            mult = 1.0 + (base_mult - 1.0) * quality_factors["advantage_scale"]
        elif base_mult < 1.0:
            mult = 1.0 - (1.0 - base_mult) * quality_factors["disadvantage_scale"]
        else:
            mult = 1.0
        mults.append(mult)

    return sum(mults) / len(mults) if mults else 1.0


def _compute_team_avg_moji(projected_minutes, player_mojo_dict):
    """Minutes-weighted average MOJI for the rotation."""
    total_mojo_min = 0.0
    total_min = 0.0
    for pid, mpg in projected_minutes.items():
        ds = player_mojo_dict.get(pid, 50)
        total_mojo_min += ds * mpg
        total_min += mpg
    return total_mojo_min / total_min if total_min > 0 else 50.0


def compute_team_synergy_vs_opponent(avail_ids, team_id, opp_def_scheme,
                                     projected_minutes=None, player_mojo_dict=None,
                                     season=CURRENT_SEASON):
    """SYN v2: Lineup-simulation synergy model.

    Cascading lineup build: 5-man → 4-man → 3-man → 2-man.
    Start with best available data, plug missing players by WOWY pair
    synergy with core players (player ID-based, not archetype-based).
    Archetypes are only used for scheme interaction multipliers.
    Players sorted by usage rate + minutes (highest first).
    Depth penalty applied for teams with missing rotation players.
    """
    from config import SCHEME_QUALITY_FACTORS

    K = _MOJI_CONSTANTS

    if not avail_ids or len(avail_ids) < 2:
        return 50.0

    if projected_minutes is None:
        projected_minutes = {}
    if player_mojo_dict is None:
        player_mojo_dict = {}

    avail_set = set(int(x) for x in avail_ids)

    # Parse opponent scheme
    scheme_type, scheme_quality = _parse_scheme(opp_def_scheme)
    quality_factors = SCHEME_QUALITY_FACTORS.get(
        scheme_quality, {"advantage_scale": 1.0, "disadvantage_scale": 1.0}
    )

    # ── Sort available players by usage + minutes (descending) ──
    # This is the priority order for plugging in missing players
    usg_min_rank = sorted(
        list(avail_set),
        key=lambda p: (projected_minutes.get(p, 0) + player_mojo_dict.get(p, 50) * 0.1),
        reverse=True
    )

    # ── Load lineup data (all group sizes) ──
    lineup_df = read_query("""
        SELECT player_ids, net_rating, minutes, possessions, group_quantity
        FROM lineup_stats
        WHERE season_id = ? AND team_id = ?
              AND net_rating IS NOT NULL AND possessions > ?
    """, DB_PATH, [season, team_id, K["SYN_MIN_POSS"]])

    pairs_df = read_query("""
        SELECT player_a_id, player_b_id, synergy_score, possessions,
               archetype_a, archetype_b
        FROM pair_synergy
        WHERE season_id = ? AND team_id = ?
    """, DB_PATH, [season, team_id])

    pair_lookup = _build_pair_lookup(pairs_df)

    # ── Phase A: Cascade 5 → 4 → 3 → 2 to build 5-man lineups ──
    all_lineups = []
    seen_sets = set()

    # Level 1: Direct 5-man combos where all 5 are available
    if lineup_df is not None and not lineup_df.empty:
        five_df = lineup_df[lineup_df["group_quantity"] == 5]
        alive_5 = _get_alive_lineups(five_df, avail_set, 5)
        for lu in alive_5:
            fs = frozenset(lu["player_ids"])
            if fs not in seen_sets:
                seen_sets.add(fs)
                all_lineups.append(lu)

    # Level 2: 4-man combos → plug in 1 missing player by archetype fit
    if lineup_df is not None and not lineup_df.empty:
        four_df = lineup_df[lineup_df["group_quantity"] == 4]
        alive_4 = _get_alive_lineups(four_df, avail_set, 4)
        for core in alive_4[:20]:  # cap to avoid excessive iteration
            built = _estimate_5man_from_core(
                core, list(avail_set), pair_lookup,
                projected_minutes, player_mojo_dict, usg_min_rank
            )
            for lu in built:
                fs = frozenset(lu["player_ids"])
                if fs not in seen_sets:
                    seen_sets.add(fs)
                    all_lineups.append(lu)

    # Level 3: 3-man combos → plug in 2 missing players
    if len(all_lineups) < 3 and lineup_df is not None and not lineup_df.empty:
        three_df = lineup_df[lineup_df["group_quantity"] == 3]
        alive_3 = _get_alive_lineups(three_df, avail_set, 3)
        for core in alive_3[:15]:
            built = _estimate_5man_from_core(
                core, list(avail_set), pair_lookup,
                projected_minutes, player_mojo_dict, usg_min_rank
            )
            for lu in built:
                fs = frozenset(lu["player_ids"])
                if fs not in seen_sets:
                    seen_sets.add(fs)
                    all_lineups.append(lu)

    # Level 4: 2-man combos → plug in 3 missing players (last resort)
    if len(all_lineups) < 3 and lineup_df is not None and not lineup_df.empty:
        two_df = lineup_df[lineup_df["group_quantity"] == 2]
        alive_2 = _get_alive_lineups(two_df, avail_set, 2)
        for core in alive_2[:10]:
            built = _estimate_5man_from_core(
                core, list(avail_set), pair_lookup,
                projected_minutes, player_mojo_dict, usg_min_rank
            )
            for lu in built:
                fs = frozenset(lu["player_ids"])
                if fs not in seen_sets:
                    seen_sets.add(fs)
                    all_lineups.append(lu)

    if not all_lineups:
        # Ultimate fallback: pair composite of all available players
        pair_composite = _compute_pair_composite(usg_min_rank[:5], pair_lookup)
        return max(0.0, min(100.0, pair_composite))

    # ── Phase B: Assign minutes & score each lineup ──
    _assign_lineup_minutes(all_lineups, projected_minutes)
    team_avg_moji = _compute_team_avg_moji(projected_minutes, player_mojo_dict)

    for lu in all_lineups:
        # Base quality: pair-level WOWY chemistry (NOT lineup NRtg — that's redundant with NRtg component)
        # Average the pair synergy scores for all C(5,2)=10 pairs in the lineup
        # This captures how well these specific players work TOGETHER, not just team quality
        lu["base_quality"] = _compute_pair_composite(lu["player_ids"], pair_lookup)

        # MOJI bonus: star lineups boosted, bench lineups penalized
        lineup_moji_vals = [player_mojo_dict.get(p, 50) for p in lu["player_ids"]]
        lineup_avg_moji = sum(lineup_moji_vals) / len(lineup_moji_vals)
        lu["moji_bonus"] = (lineup_avg_moji - team_avg_moji) * K["SYN_MOJI_BONUS"]

        # Scheme multiplier across all 10 pairs
        lu["scheme_mult"] = _compute_lineup_scheme_mult(
            lu["player_ids"], pair_lookup, scheme_type, quality_factors
        )

        # base_quality is 0-100 pair WOWY chemistry
        # moji_bonus is NRtg scale (±2ish) — convert to 0-100 scale: multiply by ~3.3
        moji_adj_100 = lu["moji_bonus"] * (50.0 / K["SYN_NRTG_RANGE"])
        lu["final_quality"] = (lu["base_quality"] + moji_adj_100) * lu["scheme_mult"]

    # ── Phase C: Minutes-weighted aggregate → 0-100 ──
    total_min = sum(lu["est_minutes"] for lu in all_lineups)
    if total_min == 0:
        return 50.0

    weighted_quality = sum(lu["final_quality"] * lu["est_minutes"] for lu in all_lineups)
    syn_score = weighted_quality / total_min

    # ── Depth penalty: missing players reduce lineup flexibility ──
    # A full rotation is ~10 players. Each missing player regresses SYN
    # 5% toward neutral (50.0). This penalizes injured teams for losing
    # depth and lineup options, preventing SYN inflation from survivor bias.
    n_available = len(avail_set)
    n_full_rotation = 10
    n_missing = max(0, n_full_rotation - n_available)
    depth_penalty = n_missing * 0.05  # 5% regression per missing player
    syn_score = syn_score * (1.0 - depth_penalty) + 50.0 * depth_penalty

    return max(0.0, min(100.0, syn_score))


def _compute_full_strength_moji(roster_df):
    """Minutes-weighted avg MOJO for the full roster (no injuries)."""
    total = 0.0
    total_min = 0.0
    for _, row in roster_df.iterrows():
        ds, _ = compute_mojo_score(row)
        mpg = row.get("minutes_per_game", 0) or 0
        total += ds * mpg
        total_min += mpg
    return total / total_min if total_min > 0 else 50.0


def get_trailing_nrtg(team_id, n_games=10):
    """Recency-weighted, blowout-capped trailing net rating proxy.

    Improvements over naive average margin:
    1. **Blowout cap** (±20): A +49 win counts as +20. This prevents single
       garbage-time-inflated games from dominating the signal.
    2. **Exponential recency decay**: Most recent game has ~2× the weight of
       game 10. Teams that are *currently* hot/cold get properly represented
       instead of mixing in stale form from 3+ weeks ago.
    3. Still uses point margin (not per-100 NRtg) but the cap + decay make
       it a much better momentum signal.
    """
    import math
    BLOWOUT_CAP = 20.0   # Max margin that counts (±20)
    DECAY_RATE = 0.85     # Each older game gets 0.85× the weight of the next newer one

    df = read_query(f"""
        SELECT
            CASE WHEN home_team_id = ? THEN home_score - away_score
                 ELSE away_score - home_score END as margin
        FROM games
        WHERE (home_team_id = ? OR away_team_id = ?)
          AND season_id = '{CURRENT_SEASON}'
          AND home_score IS NOT NULL
        ORDER BY game_date DESC
        LIMIT ?
    """, DB_PATH, [team_id, team_id, team_id, n_games])
    if df.empty:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0
    for i, margin in enumerate(df["margin"]):
        # Cap blowouts
        capped = max(-BLOWOUT_CAP, min(BLOWOUT_CAP, float(margin)))
        # Exponential decay: game 0 (most recent) = weight 1.0, game 1 = 0.85, game 2 = 0.72, etc.
        weight = DECAY_RATE ** i
        weighted_sum += capped * weight
        total_weight += weight

    return weighted_sum / total_weight if total_weight > 0 else 0.0


def compute_moji_spread(home_data, away_data, rw_lineups, team_map):
    """Full MOJI spread model.

    Steps:
    1. Get starting lineups from RotoWire scrape
    2. Project minutes for available players
    3. Compute lineup quality rating
    4. Compute adjusted MOJOs (MOJI) with archetype-aware usage redistribution
    5. Compare home net rating + HCA vs away net rating (with B2B penalties)
    6. Compute lineup synergy adjusted by opponent coaching scheme
    7. Blend 40% MOJI + 10% Season NRtg + 30% Trailing 10-Game NRtg + 20% SYN

    Returns (spread, total, breakdown).
    """
    K = _MOJI_CONSTANTS
    home_abbr = home_data["abbreviation"]
    away_abbr = away_data["abbreviation"]
    home_tid = int(home_data["team_id"])
    away_tid = int(away_data["team_id"])

    h_net = (home_data.get("net_rating", 0) or 0)
    a_net = (away_data.get("net_rating", 0) or 0)

    # ── Get rosters ──
    home_roster = _get_full_roster(home_abbr)
    away_roster = _get_full_roster(away_abbr)

    # ── Match RotoWire OUT players to DB player IDs ──
    home_out_ids = set()
    away_out_ids = set()

    home_lineup = rw_lineups.get(home_abbr, {})
    away_lineup = rw_lineups.get(away_abbr, {})

    for name in home_lineup.get("out", []):
        pid = _match_player_name(name, home_roster)
        if pid is not None:
            home_out_ids.add(pid)

    for name in away_lineup.get("out", []):
        pid = _match_player_name(name, away_roster)
        if pid is not None:
            away_out_ids.add(pid)

    # Also mark starters who are OUT
    for name, pos, status in home_lineup.get("starters", []):
        if status == "OUT":
            pid = _match_player_name(name, home_roster)
            if pid is not None:
                home_out_ids.add(pid)

    for name, pos, status in away_lineup.get("starters", []):
        if status == "OUT":
            pid = _match_player_name(name, away_roster)
            if pid is not None:
                away_out_ids.add(pid)

    # ── Project minutes ──
    home_proj_min = project_minutes(home_roster, home_out_ids)
    away_proj_min = project_minutes(away_roster, away_out_ids)

    # ── Compute MOJI ──
    home_moji, home_player_mojo, _ = compute_adjusted_mojo(home_roster, home_out_ids, home_proj_min)
    away_moji, away_player_mojo, _ = compute_adjusted_mojo(away_roster, away_out_ids, away_proj_min)

    # ── Full-strength MOJI for NRtg attrition ──
    home_full_moji = _compute_full_strength_moji(home_roster)
    away_full_moji = _compute_full_strength_moji(away_roster)

    # ── Compute lineup quality (informational) ──
    home_avail_ids = [int(r["player_id"]) for _, r in home_roster.iterrows()
                      if r["player_id"] not in home_out_ids]
    away_avail_ids = [int(r["player_id"]) for _, r in away_roster.iterrows()
                      if r["player_id"] not in away_out_ids]

    home_lineup_q = compute_lineup_rating(home_abbr, home_avail_ids, h_net)
    away_lineup_q = compute_lineup_rating(away_abbr, away_avail_ids, a_net)

    # ── Adjusted net rating: home + HCA vs away, with injury attrition + B2B ──
    home_b2b = is_back_to_back(home_abbr)
    away_b2b = is_back_to_back(away_abbr)

    # NRtg injury attrition: MOJO drop from injuries → NRtg penalty
    home_mojo_drop = max(0, home_full_moji - home_moji)
    away_mojo_drop = max(0, away_full_moji - away_moji)
    home_nrtg_attrition = home_mojo_drop * K["NRTG_MOJO_ATTRITION"]
    away_nrtg_attrition = away_mojo_drop * K["NRTG_MOJO_ATTRITION"]

    team_hca = TEAM_HCA.get(home_abbr, K["HCA"])
    home_adj_nrtg = h_net + team_hca - home_nrtg_attrition
    away_adj_nrtg = a_net - away_nrtg_attrition

    if home_b2b:
        home_adj_nrtg -= K["B2B_HOME"]
        logger.debug("B2B: %s is on a home back-to-back (-%s)", home_abbr, K['B2B_HOME'])
    if away_b2b:
        away_adj_nrtg -= K["B2B_ROAD"]
        logger.debug("B2B: %s is on a road back-to-back (-%s)", away_abbr, K['B2B_ROAD'])

    season_nrtg_diff = home_adj_nrtg - away_adj_nrtg

    # ── Trailing 10-game NRtg (captures momentum / hot teams) ──
    home_recent_nrtg = get_trailing_nrtg(home_tid, n_games=10)
    away_recent_nrtg = get_trailing_nrtg(away_tid, n_games=10)
    home_adj_recent = home_recent_nrtg + team_hca - home_nrtg_attrition
    away_adj_recent = away_recent_nrtg - away_nrtg_attrition
    if home_b2b:
        home_adj_recent -= K["B2B_HOME"]
    if away_b2b:
        away_adj_recent -= K["B2B_ROAD"]
    recent_nrtg_diff = home_adj_recent - away_adj_recent

    logger.debug("NRtg: %s season=%+.1f recent10=%+.1f | %s season=%+.1f recent10=%+.1f",
                 home_abbr, h_net, home_recent_nrtg, away_abbr, a_net, away_recent_nrtg)

    # ── Tank warning: flag teams in obvious freefall ──
    # If a team has lost 8+ of last 10 (or 6+ of last 7), apply -1.5 NRtg
    # nudge. Catches IND-type tanks where season MOJI still looks OK but
    # the team is clearly broken right now.
    TANK_PENALTY = 1.5   # NRtg points nudge for tanking teams
    home_collapse_penalty = 0.0
    away_collapse_penalty = 0.0

    for tag, tid, abbr in [("home", home_tid, home_abbr), ("away", away_tid, away_abbr)]:
        loss_check = read_query(f"""
            SELECT
                CASE WHEN home_team_id = ?
                     THEN CASE WHEN home_score > away_score THEN 1 ELSE 0 END
                     ELSE CASE WHEN away_score > home_score THEN 1 ELSE 0 END
                END as won
            FROM games
            WHERE (home_team_id = ? OR away_team_id = ?)
              AND season_id = '{CURRENT_SEASON}'
              AND home_score IS NOT NULL
            ORDER BY game_date DESC
            LIMIT 10
        """, DB_PATH, [tid, tid, tid])

        if loss_check.empty or len(loss_check) < 7:
            continue

        last_7_wins = int(loss_check.head(7)["won"].sum())
        last_10_wins = int(loss_check["won"].sum()) if len(loss_check) >= 10 else None

        # Tank trigger: 2 or fewer wins in last 10, OR 1 or fewer in last 7
        is_tanking = (last_10_wins is not None and last_10_wins <= 2) or last_7_wins <= 1
        if is_tanking:
            if tag == "home":
                home_collapse_penalty = TANK_PENALTY
            else:
                away_collapse_penalty = TANK_PENALTY
            last_n = 10 if last_10_wins is not None else 7
            last_w = last_10_wins if last_10_wins is not None else last_7_wins
            logger.info("TANK WARNING: %s is %d-%d in last %d — applying -%.1f NRtg penalty",
                        abbr, last_w, last_n - last_w, last_n, TANK_PENALTY)

    # Apply tank penalties to recent NRtg diff (shifts spread toward opponent)
    if home_collapse_penalty > 0:
        recent_nrtg_diff -= home_collapse_penalty
    if away_collapse_penalty > 0:
        recent_nrtg_diff += away_collapse_penalty

    # ── Compute lineup synergy vs opponent scheme ──
    # Get opponent defensive schemes from coaching_profiles
    away_scheme_df = read_query(f"""
        SELECT def_scheme_label FROM coaching_profiles
        WHERE team_id = ? AND season_id = '{CURRENT_SEASON}'
    """, DB_PATH, [away_tid])
    home_scheme_df = read_query(f"""
        SELECT def_scheme_label FROM coaching_profiles
        WHERE team_id = ? AND season_id = '{CURRENT_SEASON}'
    """, DB_PATH, [home_tid])

    away_def_scheme = away_scheme_df.iloc[0]["def_scheme_label"] if not away_scheme_df.empty else None
    home_def_scheme = home_scheme_df.iloc[0]["def_scheme_label"] if not home_scheme_df.empty else None

    home_syn = compute_team_synergy_vs_opponent(
        home_avail_ids, home_tid, away_def_scheme, home_proj_min, home_player_mojo
    )
    away_syn = compute_team_synergy_vs_opponent(
        away_avail_ids, away_tid, home_def_scheme, away_proj_min, away_player_mojo
    )

    syn_diff = home_syn - away_syn
    synergy_as_points = syn_diff * K["SYN_SCALE"]

    # ── Final blend: 40% MOJI + 10% season NRtg + 30% recent NRtg + 20% SYN ──
    moji_diff = home_moji - away_moji
    moji_as_points = moji_diff * K["MOJO_SCALE"]

    raw_power = (K["MOJI_WEIGHT"] * moji_as_points +
                 K["NRTG_SEASON_WEIGHT"] * season_nrtg_diff +
                 K["NRTG_RECENT_WEIGHT"] * recent_nrtg_diff +
                 K["SYN_WEIGHT"] * synergy_as_points)

    proj_spread = -raw_power
    proj_spread = round(proj_spread * 2) / 2  # round to nearest 0.5

    # ── Total (keep existing logic) ──
    h_ortg = (home_data.get("off_rating", 111.7) or 111.7)
    h_drtg = (home_data.get("def_rating", 111.7) or 111.7)
    a_ortg = (away_data.get("off_rating", 111.7) or 111.7)
    a_drtg = (away_data.get("def_rating", 111.7) or 111.7)
    h_pace = (home_data.get("pace", 100) or 100)
    a_pace = (away_data.get("pace", 100) or 100)
    league_pace = 99.87
    matchup_pace = (h_pace * a_pace) / league_pace
    home_pts = ((h_ortg + a_drtg) / 2) * (matchup_pace / 100)
    away_pts = ((a_ortg + h_drtg) / 2) * (matchup_pace / 100)
    proj_total = round((home_pts + away_pts) * 2) / 2

    # ── Breakdown for display ──
    breakdown = {
        "home_moji": round(home_moji, 1),
        "away_moji": round(away_moji, 1),
        "moji_diff": round(moji_diff, 1),
        "moji_pts": round(moji_as_points, 1),
        "home_nrtg": round(home_adj_nrtg, 1),
        "away_nrtg": round(away_adj_nrtg, 1),
        "home_nrtg_attrition": round(home_nrtg_attrition, 1),
        "away_nrtg_attrition": round(away_nrtg_attrition, 1),
        "nrtg_diff": round(season_nrtg_diff, 1),
        "recent_nrtg_diff": round(recent_nrtg_diff, 1),
        "home_recent_nrtg": round(home_recent_nrtg, 1),
        "away_recent_nrtg": round(away_recent_nrtg, 1),
        "home_syn": round(home_syn, 1),
        "away_syn": round(away_syn, 1),
        "syn_diff": round(syn_diff, 1),
        "syn_pts": round(synergy_as_points, 1),
        "home_b2b": home_b2b,
        "away_b2b": away_b2b,
        "home_out": len(home_out_ids),
        "away_out": len(away_out_ids),
        "home_lineup_q": round(home_lineup_q, 1),
        "away_lineup_q": round(away_lineup_q, 1),
        "home_collapse": round(home_collapse_penalty, 1),
        "away_collapse": round(away_collapse_penalty, 1),
        "raw_power": round(raw_power, 1),
    }

    b2b_tag = (' B2B:'+home_abbr if home_b2b else '') + (' B2B:'+away_abbr if away_b2b else '')
    logger.info("MOJI: %s@%s: MOJI %.1fv%.1f | NRtg %+.1fv%+.1f | SYN %.1fv%.1f | "
                "power=%+.1f → spread=%+.1f | OUT: %dh/%da%s",
                away_abbr, home_abbr, home_moji, away_moji,
                home_adj_nrtg, away_adj_nrtg, home_syn, away_syn,
                raw_power, proj_spread, len(home_out_ids), len(away_out_ids), b2b_tag)

    return proj_spread, proj_total, breakdown


def get_player_trend(player_id, team_abbreviation):
    """Get recent game trend data for a player. Returns trend info dict."""
    games = read_query("""
        SELECT pgs.pts, pgs.ast, pgs.reb, pgs.stl, pgs.blk, pgs.ts_pct,
               pgs.minutes, g.game_date
        FROM player_game_stats pgs
        JOIN games g ON pgs.game_id = g.game_id
        WHERE pgs.player_id = ?
        ORDER BY g.game_date DESC
        LIMIT 10
    """, DB_PATH, [player_id])

    if games.empty or len(games) < 3:
        return None

    # Last 5 vs previous 5
    recent = games.head(min(5, len(games)))
    older = games.tail(max(0, len(games) - 5)) if len(games) > 5 else None

    avg_pts_recent = recent["pts"].mean()
    avg_ast_recent = recent["ast"].mean()
    avg_reb_recent = recent["reb"].mean()
    avg_stl_recent = recent["stl"].mean()
    avg_blk_recent = recent["blk"].mean()

    trend = {
        "games_count": len(recent),
        "avg_pts": round(avg_pts_recent, 1),
        "avg_ast": round(avg_ast_recent, 1),
        "avg_reb": round(avg_reb_recent, 1),
        "last_game_date": str(games.iloc[0]["game_date"]),
    }

    if older is not None and not older.empty:
        pts_diff = avg_pts_recent - older["pts"].mean()
        ast_diff = avg_ast_recent - older["ast"].mean()
        reb_diff = avg_reb_recent - older["reb"].mean()

        # Determine trend direction
        pra_diff = pts_diff + ast_diff + reb_diff
        if pra_diff > 5:
            trend["direction"] = "hot"
            trend["label"] = "🔥 HEATING UP"
            trend["streak_games"] = len(recent)
        elif pra_diff > 2:
            trend["direction"] = "up"
            trend["label"] = "📈 TRENDING UP"
            trend["streak_games"] = len(recent)
        elif pra_diff < -5:
            trend["direction"] = "cold"
            trend["label"] = "❄️ COOLING DOWN"
            trend["streak_games"] = len(recent)
        elif pra_diff < -2:
            trend["direction"] = "down"
            trend["label"] = "📉 TRENDING DOWN"
            trend["streak_games"] = len(recent)
        else:
            trend["direction"] = "steady"
            trend["label"] = "➡️ STEADY"
            trend["streak_games"] = len(recent)

        trend["pra_diff"] = round(pra_diff, 1)
        trend["pts_diff"] = round(pts_diff, 1)
    else:
        trend["direction"] = "steady"
        trend["label"] = "➡️ STEADY"
        trend["streak_games"] = len(recent)
        trend["pra_diff"] = 0
        trend["pts_diff"] = 0

    return trend


def get_wowy_trending_players(out_player_ids=None):
    """Get top 4 risers and top 4 fallers by NRtg WOWY delta (last 10 days vs prior 10 days).
    Uses most recent data date as anchor (not today) in case boxscores are delayed.
    10-day trailing window updated daily at 8 AM PST.
    out_player_ids: set of player IDs currently OUT (injured) — excluded from fallers."""
    if out_player_ids is None:
        out_player_ids = set()
    # Find the most recent game date with player stats
    latest_df = read_query("""
        SELECT MAX(g.game_date) as latest
        FROM player_game_stats pgs
        JOIN games g ON pgs.game_id = g.game_id
    """, DB_PATH)
    if latest_df.empty or latest_df.iloc[0]["latest"] is None:
        return [], []
    latest_date = latest_df.iloc[0]["latest"]
    latest_dt = datetime.strptime(latest_date, "%Y-%m-%d")
    today = latest_date
    ten_ago = (latest_dt - timedelta(days=10)).strftime("%Y-%m-%d")
    twenty_ago = (latest_dt - timedelta(days=20)).strftime("%Y-%m-%d")

    # Recent 10 days: avg plus_minus and net_rating
    recent = read_query(f"""
        SELECT pgs.player_id,
               p.full_name,
               t.abbreviation AS team,
               pa.archetype_label,
               COUNT(*) as gp,
               AVG(pgs.plus_minus) as avg_pm,
               AVG(pgs.net_rating) as avg_nrtg,
               AVG(pgs.pts) as avg_pts,
               AVG(pgs.ast) as avg_ast,
               AVG(pgs.reb) as avg_reb
        FROM player_game_stats pgs
        JOIN games g ON pgs.game_id = g.game_id
        JOIN players p ON pgs.player_id = p.player_id
        JOIN roster_assignments ra ON pgs.player_id = ra.player_id AND ra.season_id = '{CURRENT_SEASON}'
        JOIN teams t ON ra.team_id = t.team_id
        LEFT JOIN player_archetypes pa ON pgs.player_id = pa.player_id AND pa.season_id = '{CURRENT_SEASON}'
        WHERE g.game_date >= ? AND g.game_date <= ?
          AND pgs.minutes >= 15
        GROUP BY pgs.player_id
        HAVING COUNT(*) >= 2
    """, DB_PATH, [ten_ago, today])

    # Prior 10 days: avg net_rating
    prior = read_query("""
        SELECT pgs.player_id,
               AVG(pgs.net_rating) as avg_nrtg
        FROM player_game_stats pgs
        JOIN games g ON pgs.game_id = g.game_id
        WHERE g.game_date >= ? AND g.game_date < ?
          AND pgs.minutes >= 15
        GROUP BY pgs.player_id
        HAVING COUNT(*) >= 2
    """, DB_PATH, [twenty_ago, ten_ago])

    if recent.empty or prior.empty:
        return [], []

    prior_map = {int(row["player_id"]): float(row["avg_nrtg"] or 0)
                 for _, row in prior.iterrows()}

    trending = []
    for _, row in recent.iterrows():
        pid = int(row["player_id"])
        if pid not in prior_map:
            continue
        recent_nrtg = float(row["avg_nrtg"] or 0)
        prior_nrtg = prior_map[pid]
        delta = recent_nrtg - prior_nrtg
        trending.append({
            "player_id": pid,
            "name": row["full_name"],
            "team": row["team"],
            "archetype": row.get("archetype_label") or "Unclassified",
            "recent_nrtg": round(recent_nrtg, 1),
            "prior_nrtg": round(prior_nrtg, 1),
            "delta": round(delta, 1),
            "gp": int(row["gp"]),
            "avg_pts": round(float(row["avg_pts"] or 0), 1),
            "avg_ast": round(float(row["avg_ast"] or 0), 1),
            "avg_reb": round(float(row["avg_reb"] or 0), 1),
            "avg_pm": round(float(row["avg_pm"] or 0), 1),
        })

    # Top 4 risers (biggest positive NRtg delta), top 4 fallers (biggest negative)
    # Filter OUT (injured) players from fallers — we only want legit cold players
    trending.sort(key=lambda x: x["delta"], reverse=True)
    risers = trending[:4]
    fallers_pool = [p for p in trending if p["player_id"] not in out_player_ids]
    fallers = sorted(fallers_pool, key=lambda x: x["delta"])[:4]

    return risers, fallers


def get_trending_combos():
    """Get top 4 surging and top 4 fading pair combos (10-day trailing WOWY).
    Compares joint plus_minus in 10-day window vs season baseline from pair_synergy."""
    latest_df = read_query("""
        SELECT MAX(g.game_date) as latest
        FROM player_game_stats pgs
        JOIN games g ON pgs.game_id = g.game_id
    """, DB_PATH)
    if latest_df.empty or latest_df.iloc[0]["latest"] is None:
        return [], []
    latest_date = latest_df.iloc[0]["latest"]
    latest_dt = datetime.strptime(latest_date, "%Y-%m-%d")
    ten_ago = (latest_dt - timedelta(days=10)).strftime("%Y-%m-%d")

    # Get season baselines from pair_synergy
    baselines = read_query(f"""
        SELECT player_a_id, player_b_id, net_rating, synergy_score, ps2.team_id,
               t.abbreviation as team
        FROM pair_synergy ps2
        JOIN teams t ON ps2.team_id = t.team_id
        WHERE ps2.season_id = '{CURRENT_SEASON}'
    """, DB_PATH)

    if baselines.empty:
        return [], []

    baseline_map = {}
    for _, row in baselines.iterrows():
        key = (int(row["player_a_id"]), int(row["player_b_id"]))
        baseline_map[key] = {
            "nrtg": float(row["net_rating"] or 0),
            "syn": float(row["synergy_score"] or 50),
            "team": row["team"],
            "team_id": int(row["team_id"]),
        }

    # Find pairs who shared games in the 10-day window
    # Get all player-game combos in window
    window_games = read_query("""
        SELECT pgs.player_id, pgs.game_id, pgs.plus_minus, pgs.team_id
        FROM player_game_stats pgs
        JOIN games g ON pgs.game_id = g.game_id
        WHERE g.game_date >= ? AND g.game_date <= ?
          AND pgs.minutes >= 15
    """, DB_PATH, [ten_ago, latest_date])

    if window_games.empty:
        return [], []

    # Group by game + team to find co-occurring pairs
    from collections import defaultdict
    game_team_players = defaultdict(list)
    player_pm = {}  # (pid, game_id) -> plus_minus
    for _, row in window_games.iterrows():
        key = (row["game_id"], int(row["team_id"]))
        pid = int(row["player_id"])
        game_team_players[key].append(pid)
        player_pm[(pid, row["game_id"])] = float(row["plus_minus"] or 0)

    # Compute pair window stats
    pair_window = defaultdict(list)  # (a, b) -> [avg_pm values]
    for (game_id, team_id), pids in game_team_players.items():
        pids_sorted = sorted(pids)
        for i in range(len(pids_sorted)):
            for j in range(i + 1, len(pids_sorted)):
                a, b = pids_sorted[i], pids_sorted[j]
                avg_pm = (player_pm[(a, game_id)] + player_pm[(b, game_id)]) / 2
                pair_window[(a, b)].append(avg_pm)

    # Compare window performance vs baseline
    trending_pairs = []
    # Get player names
    all_pids = set()
    for (a, b) in pair_window.keys():
        all_pids.add(a)
        all_pids.add(b)

    if not all_pids:
        return [], []

    placeholders = ",".join(["?"] * len(all_pids))
    names_df = read_query(
        f"SELECT player_id, full_name FROM players WHERE player_id IN ({placeholders})",
        DB_PATH, list(all_pids)
    )
    name_map = {int(r["player_id"]): r["full_name"] for _, r in names_df.iterrows()}

    for (a, b), pm_list in pair_window.items():
        if len(pm_list) < 2:
            continue
        key = (a, b)
        if key not in baseline_map:
            continue

        window_avg = sum(pm_list) / len(pm_list)
        baseline = baseline_map[key]
        delta = window_avg - baseline["nrtg"]

        trending_pairs.append({
            "player_a": name_map.get(a, f"PID {a}"),
            "player_b": name_map.get(b, f"PID {b}"),
            "player_a_id": a,
            "player_b_id": b,
            "team": baseline["team"],
            "window_nrtg": round(window_avg, 1),
            "season_nrtg": round(baseline["nrtg"], 1),
            "synergy_score": round(baseline["syn"], 0),
            "delta": round(delta, 1),
            "gp": len(pm_list),
        })

    # Top 4 surging, top 4 fading
    trending_pairs.sort(key=lambda x: x["delta"], reverse=True)
    surging = trending_pairs[:4]
    fading = sorted(trending_pairs, key=lambda x: x["delta"])[:4]

    return surging, fading


def get_team_mojo_rankings():
    """Rank all 30 teams by minutes-weighted average MOJO across rotation."""
    all_teams = read_query(f"""
        SELECT t.abbreviation FROM teams t
        JOIN team_season_stats ts ON t.team_id = ts.team_id
        WHERE ts.season_id = '{CURRENT_SEASON}'
    """, DB_PATH)

    team_mojo = []
    for _, row in all_teams.iterrows():
        abbr = row["abbreviation"]
        roster = get_team_roster(abbr, 10)  # top 10 by minutes
        total_weighted = 0
        total_minutes = 0
        for _, p in roster.iterrows():
            ds, _ = compute_mojo_score(p)
            mpg = p.get("minutes_per_game", 0) or 0
            total_weighted += ds * mpg
            total_minutes += mpg
        avg_mojo = total_weighted / total_minutes if total_minutes > 0 else 40
        team_mojo.append((abbr, round(avg_mojo, 1)))

    team_mojo.sort(key=lambda x: x[1], reverse=True)
    return {abbr: rank + 1 for rank, (abbr, _) in enumerate(team_mojo)}


def get_matchups():
    """Generate matchups from the Odds API slate (or fallback to hardcoded)."""
    teams = read_query(f"""
        SELECT t.team_id, t.abbreviation, t.full_name,
               ts.pace, ts.off_rating, ts.def_rating, ts.net_rating, ts.fg3a_rate,
               cp.off_scheme_label, cp.def_scheme_label, cp.pace_category,
               cp.primary_playstyle, cp.secondary_playstyle
        FROM team_season_stats ts
        JOIN teams t ON ts.team_id = t.team_id
        LEFT JOIN coaching_profiles cp ON ts.team_id = cp.team_id AND ts.season_id = cp.season_id
        WHERE ts.season_id = '{CURRENT_SEASON}'
        ORDER BY ts.net_rating DESC
    """, DB_PATH)

    # ── Get real W-L records from games table ──
    records = read_query(f"""
        SELECT t.abbreviation,
               COUNT(CASE WHEN (g.home_team_id = t.team_id AND g.home_score > g.away_score)
                           OR (g.away_team_id = t.team_id AND g.away_score > g.home_score) THEN 1 END) as wins,
               COUNT(CASE WHEN (g.home_team_id = t.team_id AND g.home_score < g.away_score)
                           OR (g.away_team_id = t.team_id AND g.away_score < g.home_score) THEN 1 END) as losses
        FROM teams t
        LEFT JOIN games g ON (g.home_team_id = t.team_id OR g.away_team_id = t.team_id)
            AND g.season_id = '{CURRENT_SEASON}'
        GROUP BY t.abbreviation
    """, DB_PATH)
    record_map = {row["abbreviation"]: (int(row["wins"]), int(row["losses"])) for _, row in records.iterrows()}

    # ── Get team MOJO rankings (1-30) ──
    mojo_rank_map = get_team_mojo_rankings()

    matchups = []
    team_map = {row["abbreviation"]: row for _, row in teams.iterrows()}

    # ── Scrape RotoWire for lineups + real sportsbook lines ──
    rw_lineups, rw_lines, rw_pairs, rw_slate_date, rw_game_times = scrape_rotowire()

    # Also try Odds API as fallback
    api_lines, api_pairs, api_slate_date, event_ids, api_bookmaker_lines = fetch_odds_api_lines()

    # Merge lines: prefer RotoWire, fall back to Odds API
    real_lines = {}
    for key, val in rw_lines.items():
        real_lines[key] = val
    for key, val in api_lines.items():
        if key not in real_lines:
            real_lines[key] = val

    # Per-bookmaker odds from Odds API (for sportsbook buttons on cards)
    bookmaker_lines = api_bookmaker_lines

    # ── Fetch prediction market win probabilities (Kalshi) ──
    prediction_market_data = {}
    try:
        from collectors.prediction_markets import fetch_all_prediction_markets
        prediction_market_data = fetch_all_prediction_markets("nba")
        logger.info("Prediction Markets: %d games with market probabilities", len(prediction_market_data))
    except (requests.RequestException, KeyError, ValueError) as e:
        logger.warning("Prediction Markets: failed to fetch: %s", e)

    has_any_real = len(real_lines) > 0

    # Use RotoWire matchup pairs first, then API, then hardcoded
    using_bm_fallback = False
    if rw_pairs:
        matchup_pairs = rw_pairs
        slate_date = rw_slate_date
        logger.info("Matchups: using %d games from RotoWire (%s)", len(matchup_pairs), slate_date)
    elif api_pairs:
        matchup_pairs = api_pairs
        slate_date = api_slate_date
        logger.info("Matchups: using %d games from Odds API (%s)", len(matchup_pairs), slate_date)
    else:
        matchup_pairs = [
            ("WAS", "IND"),
            ("MEM", "UTA"),
            ("CHA", "CLE"),
            ("ATL", "MIA"),
            ("MIN", "DAL"),
            ("NOP", "MIL"),
            ("OKC", "BKN"),
            ("LAL", "LAC"),
            ("POR", "DEN"),
        ]
        slate_date = "FEB 20"
        logger.info("Matchups: using hardcoded fallback slate (%d games)", len(matchup_pairs))

    # ── STEP 0: Filter out games that have already started ──
    game_times_for_filter = rw_game_times if matchup_pairs == rw_pairs else {}
    matchup_pairs, real_lines, removed_count = filter_started_games(
        matchup_pairs, game_times_for_filter, real_lines
    )
    if removed_count > 0:
        # Also prune bookmaker_lines for removed games
        kept = set(matchup_pairs)
        bookmaker_lines = {k: v for k, v in bookmaker_lines.items() if k in kept}
        logger.info("Matchups: %d games remaining after Step 0 filtering", len(matchup_pairs))

    # ── ROLLOVER: If ALL games filtered, try Basketball Monster for tomorrow ──
    if len(matchup_pairs) == 0 and removed_count > 0:
        logger.info("Rollover: all games completed — checking Basketball Monster for tomorrow's slate")
        try:
            bm_lineups, bm_lines, bm_pairs, bm_date, bm_times = scrape_basketball_monster()
            if bm_pairs:
                # Check if BM has different games (tomorrow's slate)
                rw_set = set(rw_pairs) if rw_pairs else set()
                bm_set = set(bm_pairs)
                overlap = len(rw_set & bm_set)
                if overlap < len(bm_set) * 0.5:
                    # BM has mostly different games → it's tomorrow's slate
                    logger.info("Rollover: Basketball Monster has tomorrow's slate: %s (%d games)", bm_date, len(bm_pairs))
                    matchup_pairs = bm_pairs
                    slate_date = bm_date
                    rw_lineups = bm_lineups  # Use BM lineups for MOJI model
                    real_lines = bm_lines
                    bookmaker_lines = {}  # BM doesn't provide per-book odds
                    rw_game_times = bm_times
                    using_bm_fallback = True
                else:
                    logger.info("Rollover: BM shows same games as today — no tomorrow slate yet")
        except (requests.RequestException, KeyError, ValueError) as e:
            logger.warning("Rollover: Basketball Monster fallback failed: %s", e)

    # ── Supplement: merge Basketball Reference injury data ──
    bref_out = scrape_bref_injuries()
    if bref_out:
        added = 0
        for team_abbr, out_names in bref_out.items():
            if team_abbr not in rw_lineups:
                rw_lineups[team_abbr] = {"starters": [], "out": [], "questionable": []}
            existing_out = set(rw_lineups[team_abbr].get("out", []))
            for name in out_names:
                if name not in existing_out:
                    rw_lineups[team_abbr]["out"].append(name)
                    added += 1
        logger.info("Injuries: merged %d new BREF OUT players into lineups", added)

    for home_abbr, away_abbr in matchup_pairs:
        if home_abbr in team_map and away_abbr in team_map:
            h = team_map[home_abbr]
            a = team_map[away_abbr]

            # ── MOJI Spread Model ──
            proj_spread, proj_total, spread_breakdown = compute_moji_spread(
                h, a, rw_lineups, team_map
            )

            net_diff = (h["net_rating"] or 0) - (a["net_rating"] or 0)
            raw_edge = -(proj_spread)  # positive = home favored (from MOJI model)

            # Check for real sportsbook lines
            real = real_lines.get((home_abbr, away_abbr), {})

            spread = real.get("spread", proj_spread)
            total = real.get("total", proj_total)
            spread_is_projected = "spread" not in real
            total_is_projected = "total" not in real

            # ── True edge: SIM projected spread vs sportsbook spread ──
            # spread_edge > 0 → SIM has home MORE favored than book → home covers
            # spread_edge < 0 → SIM has home LESS favored than book → away covers
            # Example: SIM = MIN -11.0, Book = MIN -13.0
            #   proj_spread=-11, spread=-13 → edge = -11-(-13) = +2 → away (DAL) has value
            if not spread_is_projected:
                spread_edge = proj_spread - spread
            else:
                spread_edge = 0  # no edge when comparing SIM to itself

            # Confidence based on true edge magnitude (not raw power gap)
            if not spread_is_projected:
                confidence = min(96, max(35, 50 + abs(spread_edge) * 5.0))
            else:
                confidence = min(96, max(35, 50 + abs(raw_edge) * 2.5))

            # ── O/U pick: compare projected total vs sportsbook total ──
            ou_diff = proj_total - total  # positive = model says higher than book
            if ou_diff > 0:
                ou_direction = "OVER"
                ou_pick_text = f"O {total:.1f}"
            else:
                ou_direction = "UNDER"
                ou_pick_text = f"U {total:.1f}"
            # O/U confidence: 1-10 scale based on magnitude of difference
            ou_edge = abs(ou_diff)
            ou_conf_raw = min(10, max(1, round(ou_edge / 2.5 + 3)))  # 0 diff = 3, 17.5 diff = 10
            if total_is_projected:
                ou_conf_raw = 5  # neutral when no real line

            # ── Pick side selection: based on TRUE EDGE vs book, not raw power ──
            if not spread_is_projected:
                # spread_edge = proj_spread - spread
                # spread_edge > 0: SIM projects SMALLER home margin than book
                #   → book giving away team too many points → AWAY side has value
                # spread_edge < 0: SIM projects BIGGER home margin than book
                #   → book not giving home team enough credit → HOME side has value
                #
                # Example: SIM = MIN -11, Book = MIN -13, edge = +2
                #   → DAL +13 has value (SIM says they lose by 11, getting 13)
                # Example: SIM = OKC -24, Book = OKC -16, edge = -8
                #   → OKC -16 has value (SIM says blowout is bigger than book thinks)
                # Helper: build pick text for a team
                # spread is home-perspective (negative = home fav, positive = home dog)
                # For home pick: their number is `spread` (e.g., -5.0 or +9.0)
                # For away pick: their number is `-spread` (e.g., away gets +5.0 when home is -5.0)
                # ML: only when book has team as underdog (+number) but model says they WIN
                def _pick_text(team, team_spread, model_projects_win):
                    # Always use the book spread — never convert to ML.
                    # ML odds are unreliable and the spread is the actionable line.
                    return f"{team} {team_spread:+.1f}"

                # Model projects home to win if proj_spread < 0
                home_wins_model = proj_spread < 0
                # Model projects away to win if proj_spread > 0
                away_wins_model = proj_spread > 0

                if spread_edge < -3:
                    lean_team = home_abbr
                    conf_label = f"TAKE {home_abbr}"
                    conf_class = "high"
                    pick_type = "spread"
                    pick_text = _pick_text(home_abbr, spread, home_wins_model)
                elif spread_edge < -1:
                    lean_team = home_abbr
                    conf_label = f"LEAN {home_abbr}"
                    conf_class = "medium"
                    pick_type = "spread"
                    pick_text = _pick_text(home_abbr, spread, home_wins_model)
                elif spread_edge <= 1:
                    lean_team = ""
                    conf_label = "TOSS-UP"
                    conf_class = "neutral"
                    pick_type = "spread"
                    if spread_edge <= 0:
                        pick_text = f"{home_abbr} {spread:+.1f}"
                    else:
                        pick_text = f"{away_abbr} {-spread:+.1f}"
                elif spread_edge <= 3:
                    lean_team = away_abbr
                    conf_label = f"LEAN {away_abbr}"
                    conf_class = "medium"
                    pick_type = "spread"
                    pick_text = _pick_text(away_abbr, -spread, away_wins_model)
                else:
                    lean_team = away_abbr
                    conf_label = f"TAKE {away_abbr}"
                    conf_class = "high"
                    pick_type = "spread"
                    pick_text = _pick_text(away_abbr, -spread, away_wins_model)
            else:
                # Projected lines: fall back to raw_edge (power gap)
                if raw_edge > 8:
                    lean_team = home_abbr
                    conf_label = f"TAKE {home_abbr}"
                    conf_class = "high"
                    pick_type = "spread"
                    pick_text = f"{home_abbr} {spread:+.1f}"
                elif raw_edge > 3:
                    lean_team = home_abbr
                    conf_label = f"LEAN {home_abbr}"
                    conf_class = "medium"
                    pick_type = "spread"
                    pick_text = f"{home_abbr} {spread:+.1f}"
                elif raw_edge > -3:
                    lean_team = ""
                    conf_label = "TOSS-UP"
                    conf_class = "neutral"
                    pick_type = "spread"
                    if raw_edge >= 0:
                        pick_text = f"{home_abbr} {spread:+.1f}"
                    else:
                        pick_text = f"{away_abbr} {-spread:+.1f}"
                elif raw_edge > -8:
                    lean_team = away_abbr
                    conf_label = f"LEAN {away_abbr}"
                    conf_class = "medium"
                    pick_type = "spread"
                    pick_text = f"{away_abbr} {-spread:+.1f}"
                else:
                    lean_team = away_abbr
                    conf_label = f"TAKE {away_abbr}"
                    conf_class = "high"
                    pick_type = "spread"
                    pick_text = f"{away_abbr} {-spread:+.1f}"

            # Real W-L records from games table
            h_wins, h_losses = record_map.get(home_abbr, (0, 0))
            a_wins, a_losses = record_map.get(away_abbr, (0, 0))

            # MOJO rankings (1-30)
            h_mojo_rank = mojo_rank_map.get(home_abbr, 30)
            a_mojo_rank = mojo_rank_map.get(away_abbr, 30)

            matchups.append({
                "home": h, "away": a,
                "home_abbr": home_abbr, "away_abbr": away_abbr,
                "confidence": round(confidence, 1),
                "conf_label": conf_label,
                "conf_class": conf_class,
                "lean_team": lean_team,
                "net_diff": round(net_diff, 1),
                "raw_edge": round(raw_edge, 1),
                "spread_edge": round(spread_edge, 1),
                "proj_spread": proj_spread,
                "spread": spread,
                "total": total,
                "proj_total": proj_total,
                "spread_is_projected": spread_is_projected,
                "total_is_projected": total_is_projected,
                "pick_type": pick_type,
                "pick_text": pick_text,
                "ou_direction": ou_direction,
                "ou_pick_text": ou_pick_text,
                "ou_conf": ou_conf_raw,
                "ou_edge": round(ou_diff, 1),
                "h_wins": h_wins, "h_losses": h_losses,
                "a_wins": a_wins, "a_losses": a_losses,
                "h_mojo_rank": h_mojo_rank, "a_mojo_rank": a_mojo_rank,
                "spread_breakdown": spread_breakdown,
                "rw_lineups": rw_lineups,
                "bookmaker_odds": bookmaker_lines.get((home_abbr, away_abbr), []),
                "prediction_markets": prediction_market_data.get((home_abbr, away_abbr), {}),
            })

    # ── Save daily picks snapshot for automated logging ──
    daily_snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "slate_date": slate_date,
        "games": [],
    }
    for m in matchups:
        daily_snapshot["games"].append({
            "matchup": f"{m['away_abbr']} @ {m['home_abbr']}",
            "home": m["home_abbr"],
            "away": m["away_abbr"],
            "book_spread": m["spread"] if not m["spread_is_projected"] else None,
            "book_total": m["total"] if not m["total_is_projected"] else None,
            "sim_spread": m["proj_spread"],
            "sim_total": m["proj_total"],
            "confidence": m["confidence"],
            "spread_edge": m["spread_edge"],
            "raw_edge": m["raw_edge"],
            "pick_text": m["pick_text"],
            "pick_type": m["pick_type"],
            "conf_label": m["conf_label"],
            "ou_pick_text": m["ou_pick_text"],
            "ou_conf": m["ou_conf"],
            "ou_edge": m["ou_edge"],
            "home_ml": real_lines.get((m["home_abbr"], m["away_abbr"]), {}).get("home_ml"),
            "away_ml": real_lines.get((m["home_abbr"], m["away_abbr"]), {}).get("away_ml"),
        })
    os.makedirs("data", exist_ok=True)
    with open("data/daily_picks.json", "w") as _dpf:
        json.dump(daily_snapshot, _dpf, indent=2)
    logger.info("Picks: saved daily snapshot: %d games → data/daily_picks.json", len(daily_snapshot["games"]))

    return matchups, team_map, slate_date, event_ids


def get_team_roster(abbreviation, limit=8):
    """Get top players for a team sorted by minutes."""
    players = read_query(f"""
        SELECT p.player_id, p.full_name, ps.pts_pg, ps.ast_pg, ps.reb_pg,
               ps.stl_pg, ps.blk_pg, ps.ts_pct, ps.usg_pct, ps.net_rating,
               ps.minutes_per_game, ps.def_rating, ra.listed_position,
               pa.archetype_label, pa.confidence as arch_confidence
        FROM player_season_stats ps
        JOIN players p ON ps.player_id = p.player_id
        JOIN roster_assignments ra ON ps.player_id = ra.player_id AND ps.season_id = ra.season_id
        JOIN teams t ON ps.team_id = t.team_id
        LEFT JOIN player_archetypes pa ON ps.player_id = pa.player_id AND ps.season_id = pa.season_id
        WHERE ps.season_id = '{CURRENT_SEASON}' AND t.abbreviation = ?
              AND ps.minutes_per_game > 5
        ORDER BY ps.minutes_per_game DESC
        LIMIT ?
    """, DB_PATH, [abbreviation, limit])
    return players


def get_top_combos():
    """Get top lineup combos with trend badges and game counts."""
    combos = []
    for n in [5, 3, 2]:
        label = {5: "5-Man Unit", 3: "3-Man Core", 2: "2-Man Duo"}[n]
        top = read_query(f"""
            SELECT ls.player_ids, t.abbreviation, ls.minutes, ls.net_rating,
                   ls.plus_minus, ls.gp, ls.fg_pct, ls.fg3_pct
            FROM lineup_stats ls
            JOIN teams t ON ls.team_id = t.team_id
            WHERE ls.season_id = '{CURRENT_SEASON}' AND ls.group_quantity = {n}
                  AND ls.net_rating IS NOT NULL AND ls.minutes > 8 AND ls.gp > 5
            ORDER BY ls.net_rating DESC
            LIMIT 4
        """, DB_PATH)

        for _, row in top.iterrows():
            pids = json.loads(row["player_ids"])
            placeholders = ",".join(["?"] * len(pids))
            players = read_query(
                f"""SELECT p.full_name, p.player_id, pa.archetype_label,
                           ps.pts_pg, ps.ast_pg, ps.reb_pg, ps.stl_pg, ps.blk_pg,
                           ps.ts_pct, ps.usg_pct, ps.net_rating, ps.minutes_per_game,
                           ps.def_rating
                    FROM players p
                    LEFT JOIN player_archetypes pa ON p.player_id = pa.player_id AND pa.season_id = '{CURRENT_SEASON}'
                    LEFT JOIN player_season_stats ps ON p.player_id = ps.player_id AND ps.season_id = '{CURRENT_SEASON}'
                    WHERE p.player_id IN ({placeholders})""",
                DB_PATH, pids
            )

            player_details = []
            for _, pl in players.iterrows():
                ds, _ = compute_mojo_score(pl)
                player_details.append({
                    "name": pl["full_name"],
                    "player_id": pl["player_id"],
                    "archetype": pl.get("archetype_label", "") or "Unclassified",
                    "mojo": ds,
                })

            net = row["net_rating"]
            mins = row["minutes"]
            gp = row["gp"]

            if net > 15 and gp > 10:
                badge = "🔥 HEATING UP"
                badge_class = "badge-hot"
            elif mins > 15 and gp > 15:
                badge = "📈 MORE MINUTES"
                badge_class = "badge-minutes"
            elif net > 10:
                badge = "⚡ ELITE FLOOR"
                badge_class = "badge-elite"
            else:
                badge = ""
                badge_class = ""

            combos.append({
                "type": label, "team": row["abbreviation"],
                "players": player_details,
                "net_rating": round(net, 1), "minutes": round(mins, 1),
                "gp": gp, "plus_minus": round(row["plus_minus"], 1),
                "badge": badge, "badge_class": badge_class,
                "trend_games": gp,
            })
    return combos


def get_fade_combos():
    """Get worst-performing combos to fade, with severity badges and game counts."""
    all_fades = []
    for n in [2, 3, 5]:
        label = {5: "5-Man Fade", 3: "3-Man Fade", 2: "2-Man Fade"}[n]
        fades = read_query(f"""
            SELECT ls.player_ids, t.abbreviation, ls.minutes, ls.net_rating, ls.gp
            FROM lineup_stats ls
            JOIN teams t ON ls.team_id = t.team_id
            WHERE ls.season_id = '{CURRENT_SEASON}' AND ls.group_quantity = {n}
                  AND ls.net_rating IS NOT NULL AND ls.minutes > 8 AND ls.gp > 5
            ORDER BY ls.net_rating ASC
            LIMIT 3
        """, DB_PATH)

        for _, row in fades.iterrows():
            pids = json.loads(row["player_ids"])
            placeholders = ",".join(["?"] * len(pids))
            players = read_query(
                f"""SELECT p.full_name, p.player_id, pa.archetype_label,
                           ps.pts_pg, ps.ast_pg, ps.reb_pg, ps.stl_pg, ps.blk_pg,
                           ps.ts_pct, ps.usg_pct, ps.net_rating, ps.minutes_per_game,
                           ps.def_rating
                    FROM players p
                    LEFT JOIN player_archetypes pa ON p.player_id = pa.player_id AND pa.season_id = '{CURRENT_SEASON}'
                    LEFT JOIN player_season_stats ps ON p.player_id = ps.player_id AND ps.season_id = '{CURRENT_SEASON}'
                    WHERE p.player_id IN ({placeholders})""",
                DB_PATH, pids
            )

            player_details = []
            for _, pl in players.iterrows():
                ds, _ = compute_mojo_score(pl)
                player_details.append({
                    "name": pl["full_name"],
                    "player_id": pl["player_id"],
                    "archetype": pl.get("archetype_label", "") or "Unclassified",
                    "mojo": ds,
                })

            net = row["net_rating"]
            gp = row["gp"]

            if net < -15:
                badge = "💀 DISASTERCLASS"
                badge_class = "badge-disaster"
            elif net < -10:
                badge = "🍳 COOKED"
                badge_class = "badge-cooked"
            else:
                badge = "⚠️ FADE"
                badge_class = "badge-fade"

            all_fades.append({
                "type": label, "team": row["abbreviation"],
                "players": player_details,
                "net_rating": round(net, 1), "gp": gp,
                "minutes": round(row["minutes"], 1),
                "badge": badge, "badge_class": badge_class,
                "trend_games": gp,
            })
    return all_fades


def get_lab_data():
    """Build LAB_DATA JSON for the WOWY Explorer tab — rosters, pair synergies, combo data.
    All data baked at build time for client-side interactivity."""
    from collections import defaultdict

    # Rosters grouped by team abbreviation
    rosters_df = read_query(f"""
        SELECT p.player_id, p.full_name, t.abbreviation as team,
               ps.pts_pg, ps.ast_pg, ps.reb_pg, ps.stl_pg, ps.blk_pg,
               ps.ts_pct, ps.usg_pct, ps.net_rating, ps.minutes_per_game, ps.def_rating,
               ra.listed_position,
               pa.archetype_label
        FROM player_season_stats ps
        JOIN players p ON ps.player_id = p.player_id
        JOIN roster_assignments ra ON ps.player_id = ra.player_id AND ps.season_id = ra.season_id
        JOIN teams t ON ra.team_id = t.team_id
        LEFT JOIN player_archetypes pa ON ps.player_id = pa.player_id AND pa.season_id = '{CURRENT_SEASON}'
        WHERE ps.season_id = '{CURRENT_SEASON}' AND ps.minutes_per_game > 5
        ORDER BY t.abbreviation, ps.minutes_per_game DESC
    """, DB_PATH)

    # Load teammate waste data from player_potential for card display
    _load_waste_data()

    rosters = {}
    for _, row in rosters_df.iterrows():
        team = row["team"]
        pid = int(row["player_id"])
        ds, breakdown = compute_mojo_score(row)
        low, high = compute_mojo_range(ds, pid)
        vs = _VALUE_SCORES.get(pid, {})
        arch = row.get("archetype_label") or "Unclassified"
        icon = ARCHETYPE_ICONS.get(arch, "◆")
        tid = TEAM_IDS.get(team, 0)
        if team not in rosters:
            rosters[team] = []
        # Map listed_position to Guard / Wing / Big
        # DB values: G, F, C, G-F, F-C, C-F, F-G, or empty
        raw_pos = str(row.get("listed_position") or "").strip()
        if raw_pos in ("C", "C-F", "F-C"):
            pos = "BIG"
        elif raw_pos in ("G",):
            pos = "GUARD"
        elif raw_pos in ("G-F", "F-G"):
            pos = "WING"
        elif raw_pos == "F":
            pos = "WING"
        else:
            pos = "WING"
        rosters[team].append({
            "id": pid,
            "name": row["full_name"],
            "pos": pos,
            "mojo": ds,
            "floor": low,
            "ceil": high,
            "archetype": arch,
            "arch_icon": icon,
            "team_id": tid,
            "pts": round(float(row.get("pts_pg") or 0), 3),
            "ast": round(float(row.get("ast_pg") or 0), 3),
            "reb": round(float(row.get("reb_pg") or 0), 3),
            "stl": round(float(row.get("stl_pg") or 0), 3),
            "blk": round(float(row.get("blk_pg") or 0), 3),
            "mpg": round(float(row.get("minutes_per_game") or 0), 3),
            "usg": round(float(row.get("usg_pct") or 0.20) * 100, 3) if float(row.get("usg_pct") or 0.20) < 1 else round(float(row.get("usg_pct") or 20), 3),
            "ts": round(float(row.get("ts_pct") or 0.54) * 100, 3) if float(row.get("ts_pct") or 0.54) < 1 else round(float(row.get("ts_pct") or 54), 3),
            "solo": round(float(vs.get("solo", 50)), 3),
            "rapm": _RAPM_DATA.get(pid, {}).get("rapm"),
            "rapm_off": _RAPM_DATA.get(pid, {}).get("rapm_off"),
            "rapm_def": _RAPM_DATA.get(pid, {}).get("rapm_def"),
            "waste": _waste_data.get(pid, {}).get("waste", 0),
            "mojo_gap": _waste_data.get(pid, {}).get("gap", 0),
            "breakout": _waste_data.get(pid, {}).get("breakout", 0),
            "role_mismatch": _waste_data.get(pid, {}).get("mismatch", 0),
            "intel_notes": _waste_data.get(pid, {}).get("notes_raw", ""),  # Raw — JS _escAttr/_escHtml handles escaping
        })

    # Build PID → name lookup for all roster players
    pid_names = {}
    for team_players in rosters.values():
        for p in team_players:
            pid_names[p["id"]] = p["name"]

    # Pair synergy data — add team_id for team grouping
    pairs_df = read_query(f"""
        SELECT player_a_id, player_b_id, synergy_score, net_rating,
               minutes_together, possessions, team_id
        FROM pair_synergy
        WHERE season_id = '{CURRENT_SEASON}'
    """, DB_PATH)

    pairs = {}
    # Team-grouped pairs for WOWY explorer: team_abbr → [{players, nrtg, min, poss, syn}]
    team_pairs = defaultdict(list)
    # Reverse team_id → abbr
    tid_to_abbr = {v: k for k, v in TEAM_IDS.items()}

    for _, row in pairs_df.iterrows():
        a = int(row["player_a_id"])
        b = int(row["player_b_id"])
        key = f"{a}-{b}"
        syn_val = round(float(row["synergy_score"] or 50), 3)
        nrtg_val = round(float(row["net_rating"] or 0), 3)
        min_val = round(float(row["minutes_together"] or 0), 3)
        poss_val = round(float(row["possessions"] or 0), 0)
        pairs[key] = {
            "syn": syn_val, "nrtg": nrtg_val,
            "min": min_val, "poss": poss_val,
        }
        tid = int(row.get("team_id", 0) or 0)
        abbr = tid_to_abbr.get(tid, "")
        if abbr and min_val > 0:
            name_a = pid_names.get(a, f"#{a}")
            name_b = pid_names.get(b, f"#{b}")
            team_pairs[abbr].append({
                "pids": [a, b],
                "names": [name_a, name_b],
                "nrtg": nrtg_val, "min": min_val,
                "poss": int(poss_val), "syn": syn_val,
            })

    # ── Enrich rosters with best pair data ──
    # Build pid → best partner (by NRtg, min 30 poss)
    pid_best_pair = {}  # pid → {"name": str, "nrtg": float}
    for _, row in pairs_df.iterrows():
        a = int(row["player_a_id"])
        b = int(row["player_b_id"])
        nrtg = float(row["net_rating"] or 0)
        poss = float(row["possessions"] or 0)
        if poss < 30:
            continue
        for pid, partner_id in [(a, b), (b, a)]:
            pname = pid_names.get(partner_id, f"#{partner_id}")
            parts = pname.split()
            short = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else pname
            if pid not in pid_best_pair or nrtg > pid_best_pair[pid]["nrtg"]:
                pid_best_pair[pid] = {"name": short, "nrtg": round(nrtg, 1)}

    # Inject best pair into roster entries
    for team_players in rosters.values():
        for p in team_players:
            bp = pid_best_pair.get(p["id"])
            if bp:
                p["bp_name"] = bp["name"]
                p["bp_nrtg"] = bp["nrtg"]
            else:
                p["bp_name"] = ""
                p["bp_nrtg"] = 0

    # N-man combo data — 2, 3, 4, 5
    combos = {"2": {}, "3": {}, "4": {}, "5": {}}
    team_combos = {"2": defaultdict(list), "3": defaultdict(list),
                   "4": defaultdict(list), "5": defaultdict(list)}

    for n in [2, 3, 4, 5]:
        df = read_query(f"""
            SELECT player_ids, net_rating, off_rating, def_rating, minutes, gp, team_id
            FROM lineup_stats
            WHERE season_id = '{CURRENT_SEASON}' AND group_quantity = {n}
                  AND net_rating IS NOT NULL AND minutes > 5
        """, DB_PATH)
        for _, row in df.iterrows():
            try:
                pids = sorted(json.loads(row["player_ids"]))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            key = "-".join(str(p) for p in pids)
            nrtg_val = round(float(row["net_rating"]), 1)
            min_val = round(float(row["minutes"]), 1)
            gp_val = int(row["gp"] or 0)
            combos[str(n)][key] = {
                "nrtg": nrtg_val, "min": min_val, "gp": gp_val,
                "ortg": round(float(row.get("off_rating") or 0), 1),
                "drtg": round(float(row.get("def_rating") or 0), 1),
            }
            tid = int(row.get("team_id", 0) or 0)
            abbr = tid_to_abbr.get(tid, "")
            if abbr:
                names = [pid_names.get(p, f"#{p}") for p in pids]
                team_combos[str(n)][abbr].append({
                    "pids": pids, "names": names,
                    "nrtg": nrtg_val, "min": min_val, "gp": gp_val,
                })

    # ── Team-level stats for SIM engine (pace, ORTG, DRTG, NRtg) ──
    team_stats_df = read_query(f"""
        SELECT t.abbreviation, ts.pace, ts.off_rating, ts.def_rating, ts.net_rating,
               cp.def_scheme_label, cp.off_scheme_label
        FROM team_season_stats ts
        JOIN teams t ON ts.team_id = t.team_id
        LEFT JOIN coaching_profiles cp ON ts.team_id = cp.team_id AND ts.season_id = cp.season_id
        WHERE ts.season_id = '{CURRENT_SEASON}'
    """, DB_PATH)
    team_stats = {}
    for _, row in team_stats_df.iterrows():
        abbr = row["abbreviation"]
        team_stats[abbr] = {
            "pace": round(float(row.get("pace") or 100), 1),
            "ortg": round(float(row.get("off_rating") or 111.7), 1),
            "drtg": round(float(row.get("def_rating") or 111.7), 1),
            "nrtg": round(float(row.get("net_rating") or 0), 1),
            "def_scheme": row.get("def_scheme_label") or "Standard",
            "off_scheme": row.get("off_scheme_label") or "Balanced",
        }

    return {
        "rosters": rosters,
        "pairs": pairs,
        "combos_2": combos["2"],
        "combos_3": combos["3"],
        "combos_4": combos["4"],
        "combos_5": combos["5"],
        "team_pairs": dict(team_pairs),
        "team_combos": {k: dict(v) for k, v in team_combos.items()},
        "team_stats": team_stats,
    }


def build_lab_html(lab_data):
    """Build the WOWY Explorer HTML + inline JS — DataBallr-inspired lineup data browser."""
    # Prepare WOWY data: team_pairs + team_combos (2/3/4/5-man)
    wowy_data = {
        "rosters": lab_data["rosters"],
        "pairs": lab_data.get("team_pairs", {}),
        "combos": lab_data.get("team_combos", {}),
    }
    wowy_json = json.dumps(wowy_data, separators=(",", ":"))

    # Build team options
    team_options = ""
    for abbr in sorted(lab_data["rosters"].keys()):
        name = TEAM_FULL_NAMES.get(abbr, abbr)
        team_options += f'<option value="{abbr}">{abbr} — {name}</option>\n'

    return f"""
    <div class="wowy-container">
        <div class="wowy-controls">
            <div class="wowy-team-chooser">
                <label class="wowy-label">TEAM</label>
                <select id="wowyTeamSelect" class="wowy-select" onchange="wowyTeamChange()">
                    <option value="">Select a team...</option>
                    {team_options}
                </select>
            </div>
        </div>

        <!-- MOJO PLAYER CARDS GRID -->
        <div id="mojoCardsSection" style="display:none">
            <div class="mojo-sort-bar">
                <button class="mojo-sort-btn active" data-sort="mojo" onclick="mojoSortCards('mojo')">MOJO</button>
                <button class="mojo-sort-btn" data-sort="solo" onclick="mojoSortCards('solo')">SOLO IMPACT</button>
                <button class="mojo-sort-btn" data-sort="mpg" onclick="mojoSortCards('mpg')">MINUTES</button>
            </div>
            <div class="mojo-card-grid" id="mojoCardGrid"></div>
        </div>

        <!-- LINEUP COMBOS SECTION -->
        <div id="lineupCombosSection" style="display:none">
            <div class="lineup-combos-header">LINEUP COMBOS</div>
            <div class="wowy-tabs" id="wowyTabs">
                <button class="wowy-tab active" data-n="2" onclick="wowySetTab(2)">2-MAN</button>
                <button class="wowy-tab" data-n="3" onclick="wowySetTab(3)">3-MAN</button>
                <button class="wowy-tab" data-n="4" onclick="wowySetTab(4)">4-MAN</button>
                <button class="wowy-tab" data-n="5" onclick="wowySetTab(5)">5-MAN</button>
            </div>
            <div class="wowy-filters" id="wowyFilters">
                <div class="wowy-filter-label">FILTER BY PLAYER</div>
                <div class="wowy-chips" id="wowyChips"></div>
            </div>
            <div class="wowy-table-wrap" id="wowyTableWrap">
                <table class="wowy-table" id="wowyTable">
                    <thead>
                        <tr>
                            <th class="wowy-th-players" onclick="wowySort('players')">PLAYERS</th>
                            <th class="wowy-th-nrtg wowy-sortable" onclick="wowySort('nrtg')">NRtg</th>
                            <th class="wowy-th-min wowy-sortable active-sort" onclick="wowySort('min')">MIN ▼</th>
                            <th class="wowy-th-poss wowy-sortable" onclick="wowySort('poss')">POSS</th>
                            <th class="wowy-th-gp wowy-sortable" onclick="wowySort('gp')">GP</th>
                        </tr>
                    </thead>
                    <tbody id="wowyBody"></tbody>
                </table>
            </div>
        </div>

        <div class="wowy-empty" id="wowyEmpty">
            <div class="wowy-empty-icon">📊</div>
            <div class="wowy-empty-text">Select a team to explore MOJO ratings and lineup combinations</div>
        </div>
    </div>

    <script>
    function _escAttr(s) {{ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#x27;').replace(/`/g,'&#96;'); }}
    function _escHtml(s) {{ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#x27;'); }}
    const WOWY_DATA = {wowy_json};
    let wowyCurrentTeam = '';
    let wowyCurrentN = 2;
    let wowyCurrentSort = 'min';
    let wowySortDir = -1; // -1 = desc
    let wowyActiveFilters = new Set();

    let mojoCurrentSort = 'mojo';

    function wowyTeamChange() {{
        wowyCurrentTeam = document.getElementById('wowyTeamSelect').value;
        wowyActiveFilters.clear();

        if (!wowyCurrentTeam) {{
            document.getElementById('mojoCardsSection').style.display = 'none';
            document.getElementById('lineupCombosSection').style.display = 'none';
            document.getElementById('wowyEmpty').style.display = 'block';
            return;
        }}

        document.getElementById('mojoCardsSection').style.display = 'block';
        document.getElementById('lineupCombosSection').style.display = 'block';
        document.getElementById('wowyEmpty').style.display = 'none';

        // Build player filter chips
        const roster = WOWY_DATA.rosters[wowyCurrentTeam] || [];
        const chipsDiv = document.getElementById('wowyChips');
        chipsDiv.innerHTML = '';
        roster.forEach(p => {{
            const chip = document.createElement('button');
            chip.className = 'wowy-chip';
            chip.textContent = p.name.split(' ').pop();
            chip.dataset.pid = p.id;
            chip.onclick = () => wowyToggleFilter(p.id, chip);
            chipsDiv.appendChild(chip);
        }});

        renderMojoCards();
        wowyRender();
    }}

    function renderMojoCards() {{
        const team = wowyCurrentTeam;
        if (!team) return;
        let roster = [...(WOWY_DATA.rosters[team] || [])];
        const tc = TEAM_COLORS[team] || '#333';

        // Sort roster
        if (mojoCurrentSort === 'mojo') roster.sort((a, b) => b.mojo - a.mojo);
        else if (mojoCurrentSort === 'solo') roster.sort((a, b) => b.solo - a.solo);
        else if (mojoCurrentSort === 'mpg') roster.sort((a, b) => b.mpg - a.mpg);

        const grid = document.getElementById('mojoCardGrid');
        let html = '';
        roster.forEach((p, i) => {{
            const ds = p.mojo || 0;
            const headshot = 'https://cdn.nba.com/headshots/nba/latest/260x190/' + p.id + '.png';
            const teamLogo = 'https://cdn.nba.com/logos/nba/' + (p.team_id || 0) + '/global/L/logo.svg';
            const stk = ((p.stl || 0) + (p.blk || 0)).toFixed(1);

            // Tier classes
            let tier = 'role';
            if (ds >= 90) tier = 'icon';
            else if (ds >= 75) tier = 'elite';
            else if (ds >= 60) tier = 'solid';

            // Solo impact bar
            const solo = p.solo || 50;
            const soloOffset = Math.min(Math.max((solo - 20) / 80 * 100, 2), 98);
            const soloColor = solo >= 60 ? '#00FF55' : solo >= 45 ? '#FFB300' : '#FF3333';
            const soloLabel = solo >= 50 ? '+' + (solo - 50).toFixed(0) : (solo - 50).toFixed(0);

            // Best pair
            const bpName = p.bp_name || '';
            const bpNrtg = p.bp_nrtg || 0;
            const bpSign = bpNrtg >= 0 ? '+' : '';
            const bpColor = bpNrtg >= 0 ? '#00FF55' : '#FF3333';

            html += `
            <div class="mojo-card mojo-${{tier}}" style="--tc:${{tc}}" onclick="openPlayerSheet(this)"
                 data-name="${{p.name}}" data-arch="${{p.archetype}}" data-mojo="${{ds}}"
                 data-range="${{p.floor || ds}}-${{p.ceil || ds}}"
                 data-pts="${{p.pts || 0}}" data-ast="${{p.ast || 0}}" data-reb="${{p.reb || 0}}"
                 data-stl="${{p.stl || 0}}" data-blk="${{p.blk || 0}}" data-ts="0"
                 data-net="0" data-usg="0" data-mpg="${{p.mpg || 0}}"
                 data-team="${{team}}" data-pid="${{p.id}}"
                 data-waste="${{p.waste || 0}}" data-mojo-gap="${{p.mojo_gap || 0}}"
                 data-breakout="${{p.breakout || 0}}" data-role-mismatch="${{p.role_mismatch || 0}}"
                 data-intel="${{_escAttr(p.intel_notes)}}"
                 data-ts="${{p.ts || 0}}" data-usg="${{p.usg || 0}}">
                <div class="mc-frame">
                    <div class="mc-score-area">
                        <div class="mc-mojo-num">${{ds}}</div>
                        <div class="mc-mojo-label">MOJO</div>
                        <div class="mc-mojo-range">${{p.floor || ds}}-${{p.ceil || ds}}</div>
                    </div>
                    <div class="mc-team-badge">${{team}}</div>
                    <div class="mc-portrait">
                        <img src="${{teamLogo}}" class="mc-team-watermark" onerror="this.style.display='none'">
                        <img src="${{headshot}}" class="mc-headshot" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22/>'">
                    </div>
                    <div class="mc-player-name">${{p.name}}</div>
                    <div class="mc-archetype">${{p.arch_icon || ''}} ${{p.archetype}}</div>
                    <div class="mc-stat-row">
                        <div class="mc-stat"><span class="mc-stat-num">${{(p.pts || 0).toFixed(1)}}</span><span class="mc-stat-lbl">PTS</span></div>
                        <div class="mc-stat"><span class="mc-stat-num">${{(p.ast || 0).toFixed(1)}}</span><span class="mc-stat-lbl">AST</span></div>
                        <div class="mc-stat"><span class="mc-stat-num">${{(p.reb || 0).toFixed(1)}}</span><span class="mc-stat-lbl">REB</span></div>
                        <div class="mc-stat"><span class="mc-stat-num">${{stk}}</span><span class="mc-stat-lbl">STK</span></div>
                    </div>
                    <div class="mc-solo-row">
                        <span class="mc-solo-label">SOLO</span>
                        <div class="mc-solo-bar"><div class="mc-solo-fill" style="width:${{soloOffset}}%;background:${{soloColor}}"></div></div>
                        <span class="mc-solo-val" style="color:${{soloColor}}">${{soloLabel}}</span>
                    </div>
                    ${{p.rapm != null ? '<div class="mc-rapm-row"><span class="mc-rapm-label">RAPM</span><span class="mc-rapm-val" style="color:' + (p.rapm >= 0 ? '#2e7d32' : '#c62828') + '">' + (p.rapm >= 0 ? '+' : '') + p.rapm.toFixed(1) + '</span></div>' : ''}}
                    ${{bpName ? '<div class="mc-pair-row"><span class="mc-pair-label">w/ ' + bpName + '</span><span class="mc-pair-nrtg" style="color:' + bpColor + '">' + bpSign + bpNrtg.toFixed(1) + '</span></div>' : ''}}
                    ${{p.waste > 5 ? '<div class="mc-waste-row"><span class="mc-waste-label">TM WASTE</span><span class="mc-waste-val" style="color:' + (p.waste >= 40 ? '#FF3333' : p.waste >= 20 ? '#FFB300' : '#8e8e8e') + '">' + p.waste.toFixed(1) + '</span></div>' : ''}}
                    ${{p.mojo_gap > 10 ? '<div class="mc-gap-row"><span class="mc-gap-label">UPSIDE</span><span class="mc-gap-val" style="color:#00c6ff">+' + parseInt(p.mojo_gap || 0) + '</span></div>' : ''}}
                </div>
            </div>`;
        }});
        grid.innerHTML = html;
    }}

    function mojoSortCards(sortBy) {{
        mojoCurrentSort = sortBy;
        document.querySelectorAll('.mojo-sort-btn').forEach(b => b.classList.remove('active'));
        document.querySelector('.mojo-sort-btn[data-sort="' + sortBy + '"]').classList.add('active');
        renderMojoCards();
    }}

    const TEAM_COLORS = {json.dumps({k: TEAM_COLORS.get(k, '#333') for k in lab_data["rosters"].keys()}, separators=(",", ":"))};


    function wowySetTab(n) {{
        wowyCurrentN = n;
        document.querySelectorAll('.wowy-tab').forEach(b => b.classList.remove('active'));
        document.querySelector('.wowy-tab[data-n="' + n + '"]').classList.add('active');

        // Update table header — pairs show SYN column instead of GP
        const headers = document.querySelectorAll('#wowyTable thead th');
        if (n === 2) {{
            headers[3].textContent = 'POSS';
            headers[3].onclick = () => wowySort('poss');
            headers[4].textContent = 'SYN';
            headers[4].onclick = () => wowySort('syn');
        }} else {{
            headers[3].textContent = 'POSS';
            headers[3].onclick = () => wowySort('poss');
            headers[4].textContent = 'GP';
            headers[4].onclick = () => wowySort('gp');
        }}

        wowyRender();
    }}

    function wowyToggleFilter(pid, chip) {{
        if (wowyActiveFilters.has(pid)) {{
            wowyActiveFilters.delete(pid);
            chip.classList.remove('active');
        }} else {{
            wowyActiveFilters.add(pid);
            chip.classList.add('active');
        }}
        wowyRender();
    }}

    function wowySort(col) {{
        if (wowyCurrentSort === col) {{
            wowySortDir *= -1;
        }} else {{
            wowyCurrentSort = col;
            wowySortDir = -1;
        }}

        // Update sort indicators
        document.querySelectorAll('#wowyTable thead th').forEach(th => {{
            th.classList.remove('active-sort');
            const text = th.textContent.replace(/ [▲▼]$/, '');
            th.textContent = text;
        }});

        wowyRender();
    }}

    function wowyRender() {{
        const team = wowyCurrentTeam;
        const n = wowyCurrentN;
        let rows = [];

        if (n === 2) {{
            // Use pair data
            const pairs = WOWY_DATA.pairs[team] || [];
            rows = pairs.map(p => ({{
                names: p.names,
                pids: p.pids,
                nrtg: p.nrtg,
                min: p.min,
                poss: p.poss,
                gp: 0,
                syn: p.syn,
            }}));
        }} else {{
            // Use combo data
            const combos = (WOWY_DATA.combos[String(n)] || {{}})[team] || [];
            rows = combos.map(c => ({{
                names: c.names,
                pids: c.pids,
                nrtg: c.nrtg,
                min: c.min,
                poss: 0,
                gp: c.gp,
                syn: 0,
            }}));
        }}

        // Filter by active player chips (AND logic)
        if (wowyActiveFilters.size > 0) {{
            rows = rows.filter(r => {{
                for (const pid of wowyActiveFilters) {{
                    if (!r.pids.includes(pid)) return false;
                }}
                return true;
            }});
        }}

        // Sort
        const col = wowyCurrentSort;
        rows.sort((a, b) => {{
            const av = a[col] || 0;
            const bv = b[col] || 0;
            return (av - bv) * wowySortDir;
        }});

        // Update sort arrow in header
        const headers = document.querySelectorAll('#wowyTable thead th');
        const colMap = {{'players': 0, 'nrtg': 1, 'min': 2, 'poss': 3, 'gp': 4, 'syn': 4}};
        const idx = colMap[col];
        if (idx !== undefined && headers[idx]) {{
            headers[idx].classList.add('active-sort');
            const text = headers[idx].textContent.replace(/ [▲▼]$/, '');
            headers[idx].textContent = text + (wowySortDir === -1 ? ' ▼' : ' ▲');
        }}

        // Render rows
        const tbody = document.getElementById('wowyBody');
        if (rows.length === 0) {{
            tbody.innerHTML = '<tr><td colspan="5" class="wowy-nodata">No lineup data available</td></tr>';
            return;
        }}

        let html = '';
        rows.forEach(r => {{
            const nrtgColor = r.nrtg >= 0 ? '#00FF55' : '#FF3333';
            const nrtgSign = r.nrtg >= 0 ? '+' : '';
            const shortNames = r.names.map(nm => {{
                const parts = nm.split(' ');
                return parts.length > 1 ? parts[0][0] + '. ' + parts.slice(1).join(' ') : nm;
            }}).join(' / ');

            const lastCol = n === 2
                ? '<td class="wowy-td-syn">' + r.syn.toFixed(1) + '</td>'
                : '<td class="wowy-td-gp">' + r.gp + '</td>';

            html += '<tr class="wowy-row">' +
                '<td class="wowy-td-players">' + shortNames + '</td>' +
                '<td class="wowy-td-nrtg" style="color:' + nrtgColor + '">' + nrtgSign + r.nrtg.toFixed(1) + '</td>' +
                '<td class="wowy-td-min">' + r.min.toFixed(1) + '</td>' +
                '<td class="wowy-td-poss">' + (n === 2 ? r.poss : '—') + '</td>' +
                lastCol +
                '</tr>';
        }});
        tbody.innerHTML = html;
    }}
    </script>
    """


def get_ceiling_floor_players():
    """Get players most elevated or suppressed by team context.

    Ceiling: composite_value >> base_value (team makes them better)
    Floor: composite_value << base_value (team drags them down)
    """
    if not _VALUE_SCORES:
        return [], []

    players_df = read_query(f"""
        SELECT p.player_id, p.full_name, t.abbreviation as team,
               pa.archetype_label, ps.minutes_per_game
        FROM player_season_stats ps
        JOIN players p ON ps.player_id = p.player_id
        JOIN roster_assignments ra ON ps.player_id = ra.player_id AND ps.season_id = ra.season_id
        JOIN teams t ON ra.team_id = t.team_id
        LEFT JOIN player_archetypes pa ON ps.player_id = pa.player_id AND pa.season_id = '{CURRENT_SEASON}'
        WHERE ps.season_id = '{CURRENT_SEASON}' AND ps.minutes_per_game > 12
    """, DB_PATH)

    movers = []
    for _, row in players_df.iterrows():
        pid = int(row["player_id"])
        vs = _VALUE_SCORES.get(pid)
        if not vs:
            continue

        # Scale both to 33-99
        raw_mojo = int(33 + (vs["base"] / 100) * 66)
        contextual_mojo = int(33 + (vs["composite"] / 100) * 66)
        delta = contextual_mojo - raw_mojo

        movers.append({
            "player_id": pid,
            "name": row["full_name"],
            "team": row["team"],
            "archetype": row.get("archetype_label") or "Unclassified",
            "raw_mojo": raw_mojo,
            "contextual_mojo": contextual_mojo,
            "delta": delta,
            "solo": round(vs["solo"], 1),
            "synergy": round(vs["two"], 1),
            "fit": round(vs["fit"], 1),
        })

    movers.sort(key=lambda x: x["delta"], reverse=True)
    ceiling = movers[:4]
    floor = sorted(movers, key=lambda x: x["delta"])[:4]

    return ceiling, floor


def get_lock_picks(matchups):
    """Generate top highest-confidence picks on actual spreads/totals."""
    picks = []
    for m in sorted(matchups, key=lambda x: abs(x["confidence"] - 50), reverse=True):
        if m["confidence"] > 65:
            picks.append({
                "label": m["pick_text"],
                "score": m["confidence"],
                "reason": f"{m['home_abbr']} vs {m['away_abbr']}",
                "spread": m["spread"],
                "total": m["total"],
                "matchup": f"{m['away_abbr']} @ {m['home_abbr']}",
            })
        elif m["confidence"] < 35:
            picks.append({
                "label": m["pick_text"],
                "score": 100 - m["confidence"],
                "reason": f"{m['home_abbr']} vs {m['away_abbr']}",
                "spread": m["spread"],
                "total": m["total"],
                "matchup": f"{m['away_abbr']} @ {m['home_abbr']}",
            })
        if len(picks) >= 5:
            break
    return picks[:5]


def get_last5_prop_stats(player_id, prop_type):
    """Get last 5 game values for a specific prop stat.

    prop_type: 'PTS', 'AST', 'REB', 'PRA', 'STL+BLK'
    Returns list of values (most recent first), e.g. [32, 25, 31, 28, 35]
    """
    games = read_query("""
        SELECT pgs.pts, pgs.ast, pgs.reb, pgs.stl, pgs.blk, g.game_date
        FROM player_game_stats pgs
        JOIN games g ON pgs.game_id = g.game_id
        WHERE pgs.player_id = ?
        ORDER BY g.game_date DESC
        LIMIT 5
    """, DB_PATH, [player_id])

    if games.empty:
        return []

    values = []
    for _, g in games.iterrows():
        if prop_type == "PTS":
            values.append(int(g["pts"]))
        elif prop_type == "AST":
            values.append(int(g["ast"]))
        elif prop_type == "REB":
            values.append(int(g["reb"]))
        elif prop_type == "PRA":
            values.append(int(g["pts"] + g["reb"] + g["ast"]))
        elif prop_type == "STL+BLK":
            values.append(int(g["stl"] + g["blk"]))
        else:
            values.append(0)
    return values


def round_to_half(val):
    """Round a value to the nearest 0.5 like real sportsbook lines."""
    return round(val * 2) / 2

def get_player_spotlights(matchups, team_map, real_player_props=None):
    """Generate top player stat spotlights ranked by MOJO + matchup advantage.

    Pure research view — no OVER/UNDER picks, no confidence pills.
    Shows stat lines, sportsbook lines (for context), and matchup data.

    real_player_props: dict from fetch_odds_api_player_props() keyed by player name
        with sub-dict of prop_type -> line value.
    """
    if real_player_props is None:
        real_player_props = {}
    all_spotlights = []

    for m in matchups:
        ha = m["home_abbr"]
        aa = m["away_abbr"]

        for abbr in [ha, aa]:
            opponent = aa if abbr == ha else ha
            opp_data = team_map.get(opponent, {})
            own_data = team_map.get(abbr, {})
            opp_drtg = (opp_data.get("def_rating", 112) or 112)
            opp_pace = (opp_data.get("pace", 100) or 100)
            own_pace = (own_data.get("pace", 100) or 100)

            def_signal = (opp_drtg - 112) * 2.0
            pace_signal = ((opp_pace + own_pace) / 2 - 100) * 0.5
            matchup_signal = def_signal + pace_signal

            roster = get_team_roster(abbr, 8)

            for _, p in roster.iterrows():
                _pid = int(p.get("player_id", 0) or 0)
                _adj = _INJURY_ADJUSTED_VS.get(_pid)
                ds, breakdown = compute_mojo_score(p, injury_adjusted_composite=_adj)
                if ds < 40:
                    continue

                pts = p.get("pts_pg", 0) or 0
                ast = p.get("ast_pg", 0) or 0
                reb = p.get("reb_pg", 0) or 0
                stl = p.get("stl_pg", 0) or 0
                blk = p.get("blk_pg", 0) or 0
                mpg = p.get("minutes_per_game", 0) or 0
                ts = p.get("ts_pct", 0) or 0
                name = p.get("full_name", "?")
                player_id = p.get("player_id", 0)
                arch_raw = p.get("archetype_label", "")
                arch = arch_raw if (arch_raw and str(arch_raw) != "nan") else "Unclassified"

                parts = name.split()
                short = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else name

                # Get trend for context
                trend = get_player_trend(player_id, abbr)
                trend_note = ""
                if trend and trend.get("direction") in ["hot", "up"]:
                    trend_note = f" // {trend['label']} ({trend['streak_games']}G)"
                elif trend and trend.get("direction") in ["cold", "down"]:
                    trend_note = f" // {trend['label']} ({trend['streak_games']}G)"

                # Check if we have real sportsbook lines for context
                player_real = real_player_props.get(name, {})

                # Determine primary stat category for this player
                real_pts_line = player_real.get("POINTS")
                real_ast_line = player_real.get("ASSISTS")
                real_reb_line = player_real.get("REBOUNDS")
                real_pra_line = player_real.get("PRA")

                # Pick the best stat to feature (highest production relative to threshold)
                primary_stat = "PTS"
                primary_line = real_pts_line if real_pts_line is not None else round_to_half(pts) if pts >= 15 else None
                primary_avg = pts
                is_real = real_pts_line is not None

                # Build stat line
                stat_line = f"{pts:.1f}p | {ast:.1f}a | {reb:.1f}r"

                # Build note with matchup context
                note = f"Avg {pts:.1f} pts // {ts*100:.0f}% TS vs {opp_drtg:.0f} DRTG{trend_note}"

                # Matchup advantage score: MOJO + matchup signal (for ranking)
                matchup_advantage = ds * 0.6 + max(0, matchup_signal) * 4.0

                # Edge vs line (informational, not a pick)
                edge = 0
                if primary_line is not None:
                    edge = primary_avg - float(primary_line)

                low, high = compute_mojo_range(ds, player_id)

                # Get last 5 games for PTS (primary stat)
                last5 = get_last5_prop_stats(player_id, "PTS") if pts >= 15 else []

                # Sportsbook lines for display (context only)
                lines_display = {}
                if real_pts_line is not None:
                    lines_display["PTS"] = real_pts_line
                if real_ast_line is not None:
                    lines_display["AST"] = real_ast_line
                if real_reb_line is not None:
                    lines_display["REB"] = real_reb_line
                if real_pra_line is not None:
                    lines_display["PRA"] = real_pra_line

                # Matchup advantage label
                if matchup_signal > 4:
                    matchup_label = "ELITE"
                elif matchup_signal > 1:
                    matchup_label = "GOOD"
                elif matchup_signal > -1:
                    matchup_label = "NEUTRAL"
                elif matchup_signal > -4:
                    matchup_label = "TOUGH"
                else:
                    matchup_label = "HARD"

                all_spotlights.append({
                    "player": short,
                    "full_name": name,
                    "player_id": player_id,
                    "team": abbr,
                    "opponent": opponent,
                    "mojo": ds,
                    "ds_range": f"{low}-{high}",
                    "archetype": arch,
                    "stat_line": stat_line,
                    "pts": pts, "ast": ast, "reb": reb,
                    "primary_line": f"{primary_line:.1f}" if primary_line else None,
                    "primary_avg": primary_avg,
                    "edge": edge,
                    "line_is_projected": not is_real,
                    "lines_display": lines_display,
                    "note": note,
                    "matchup_advantage": matchup_advantage,
                    "matchup_label": matchup_label,
                    "matchup_signal": matchup_signal,
                    "opp_drtg": opp_drtg,
                    "last5": last5,
                })

    all_spotlights.sort(key=lambda x: x["matchup_advantage"], reverse=True)
    return all_spotlights[:20]


def get_top_50_ds():
    """Get top 50 players league-wide ranked by MOJO."""
    players = read_query(f"""
        SELECT p.player_id, p.full_name, t.abbreviation,
               ps.pts_pg, ps.ast_pg, ps.reb_pg,
               ps.stl_pg, ps.blk_pg, ps.ts_pct, ps.usg_pct, ps.net_rating,
               ps.minutes_per_game, ps.def_rating,
               pa.archetype_label
        FROM player_season_stats ps
        JOIN players p ON ps.player_id = p.player_id
        JOIN teams t ON ps.team_id = t.team_id
        LEFT JOIN player_archetypes pa ON ps.player_id = pa.player_id AND ps.season_id = pa.season_id
        WHERE ps.season_id = '{CURRENT_SEASON}' AND ps.minutes_per_game > 15
        ORDER BY ps.minutes_per_game DESC
        LIMIT 300
    """, DB_PATH)

    # Compute MOJO for each player, then sort by MOJO and take top 50
    all_scored = []
    for _, p in players.iterrows():
        ds, breakdown = compute_mojo_score(p)
        all_scored.append((p, ds, breakdown))
    all_scored.sort(key=lambda x: x[1], reverse=True)
    all_scored = all_scored[:50]

    ranked = []
    for p, ds, breakdown in all_scored:
        pid = int(p.get("player_id", 0) or 0)
        low, high = compute_mojo_range(ds, pid)
        ranked.append({
            "rank": len(ranked) + 1,
            "name": p["full_name"],
            "player_id": p["player_id"],
            "team": p["abbreviation"],
            "mojo": ds,
            "low": low, "high": high,
            "pts": round(p.get("pts_pg", 0) or 0, 3),
            "ast": round(p.get("ast_pg", 0) or 0, 3),
            "reb": round(p.get("reb_pg", 0) or 0, 3),
            "stl": round(p.get("stl_pg", 0) or 0, 3),
            "blk": round(p.get("blk_pg", 0) or 0, 3),
            "ts": round((p.get("ts_pct", 0) or 0) * 100, 3) if (p.get("ts_pct", 0) or 0) < 1 else round(p.get("ts_pct", 0) or 0, 3),
            "net": round(p.get("net_rating", 0) or 0, 3),
            "mpg": round(p.get("minutes_per_game", 0) or 0, 3),
            "archetype": p.get("archetype_label", "") or "Unclassified",
            "breakdown": breakdown,
        })
    return ranked


def get_projected_player_lines(team_abbr, opponent_abbr, team_map):
    """Generate projected stat lines for each player in a matchup.
    Uses season averages adjusted by opponent defensive quality."""
    roster = get_team_roster(team_abbr, 8)
    opp_data = team_map.get(opponent_abbr, {})
    opp_drtg = (opp_data.get("def_rating", 112) or 112)
    opp_pace = (opp_data.get("pace", 100) or 100)
    own_data = team_map.get(team_abbr, {})
    own_pace = (own_data.get("pace", 100) or 100)

    # Matchup pace factor — faster games = more stats
    league_pace = 99.87
    pace_factor = ((opp_pace + own_pace) / 2) / league_pace

    # Defense factor — bad defense = boost, elite defense = suppress
    # 112 is league avg DRTG
    def_factor = opp_drtg / 112.0

    projections = []
    for _, p in roster.iterrows():
        pts = (p.get("pts_pg", 0) or 0)
        ast = (p.get("ast_pg", 0) or 0)
        reb = (p.get("reb_pg", 0) or 0)
        stl = (p.get("stl_pg", 0) or 0)
        blk = (p.get("blk_pg", 0) or 0)
        mpg = (p.get("minutes_per_game", 0) or 0)
        ts = (p.get("ts_pct", 0) or 0)
        name = p.get("full_name", "?")
        player_id = p.get("player_id", 0)

        if mpg < 10:
            continue

        # Adjust scoring stats by defense/pace matchup
        proj_pts = round(pts * def_factor * pace_factor, 1)
        proj_ast = round(ast * pace_factor, 1)
        proj_reb = round(reb * pace_factor * 0.98, 1)  # Reb less matchup-dependent
        proj_pra = round(proj_pts + proj_ast + proj_reb, 1)

        parts = name.split()
        short = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else name

        projections.append({
            "player": short,
            "full_name": name,
            "player_id": player_id,
            "team": team_abbr,
            "opponent": opponent_abbr,
            "proj_pts": proj_pts,
            "proj_ast": proj_ast,
            "proj_reb": proj_reb,
            "proj_pra": proj_pra,
            "season_pts": round(pts, 1),
            "season_ast": round(ast, 1),
            "season_reb": round(reb, 1),
            "mpg": round(mpg, 1),
            "ts": round(ts * 100, 1) if ts < 1 else round(ts, 1),
        })

    return projections


# ────────────────────────────────────────────────────────────────────
# HTML GENERATION
# ────────────────────────────────────────────────────────────────────

def generate_html():
    """Generate the complete NBA SIM HTML — mobile-first with all features."""
    matchups, team_map, slate_date, event_ids = get_matchups()
    slate_date = slate_date or "TODAY"

    # Build injury-adjusted MOJO cache for tonight's matchup cards
    _build_injury_adjusted_cache(matchups)
    combos = get_top_combos()
    fades = get_fade_combos()
    surging_pairs, fading_pairs = get_trending_combos()
    ceiling_players, floor_players = get_ceiling_floor_players()
    locks = get_lock_picks(matchups)

    # Player props — Odds API removed, always empty
    real_player_props = {}

    props = get_player_spotlights(matchups, team_map, real_player_props)
    top50 = get_top_50_ds()

    # Check if any games have real sportsbook lines
    all_projected = all(m.get("spread_is_projected", True) for m in matchups)
    has_some_real = not all_projected

    # ── Load waste intel BEFORE building matchup cards so render_player_row can use it ──
    _load_waste_data()

    # ── Build matchup cards HTML (with projected player lines) ──
    matchup_cards = ""
    if matchups:
        for idx, m in enumerate(matchups):
            matchup_cards += render_matchup_card(m, idx, team_map)
    else:
        matchup_cards = """
        <div style="text-align:center; padding:60px 20px; color:#888;">
            <div style="font-size:2.5rem; margin-bottom:16px;">&#127936;</div>
            <div style="font-size:1.2rem; font-weight:700; color:#ccc; margin-bottom:8px;">No Upcoming Games</div>
            <div style="font-size:0.9rem; line-height:1.5;">
                All games for today have started or finished.<br>
                Check back tomorrow for fresh predictions.
            </div>
        </div>
        """

    # ── Build player stats HTML ──
    props_cards = ""
    for i, prop in enumerate(props):
        props_cards += render_stat_card(prop, i + 1)

    # ── Build combos HTML (hot + fade side by side) ──
    hot_cards = ""
    for c in combos:
        hot_cards += render_combo_card(c, is_fade=False)

    fade_cards = ""
    for f in fades:
        fade_cards += render_combo_card(f, is_fade=True)

    # ── Build trending pairs HTML (WOWY duo trends) ──
    surging_pair_cards = ""
    for p in surging_pairs:
        if p["delta"] > 8:
            badge = "🔥 SURGING"
            badge_class = "badge-hot"
        elif p["delta"] > 4:
            badge = "📈 RISING"
            badge_class = "badge-minutes"
        else:
            badge = "⚡ WARMING"
            badge_class = "badge-elite"
        surging_pair_cards += f"""
        <div class="trend-card trend-up">
            <div class="trend-info" style="flex:1">
                <span class="trend-name">{p['player_a']} + {p['player_b']}</span>
                <span class="trend-meta">{p['team']} // SYN {p['synergy_score']:.0f} // {p['gp']}G window</span>
                <span class="trend-stats">Window: {p['window_nrtg']:+.1f} NRtg | Season: {p['season_nrtg']:+.1f}</span>
            </div>
            <div class="trend-delta trend-pos">+{p['delta']:.1f} NRtg</div>
        </div>"""

    fading_pair_cards = ""
    for p in fading_pairs:
        if p["delta"] < -8:
            badge = "💀 CRATERING"
            badge_class = "badge-disaster"
        elif p["delta"] < -4:
            badge = "🍳 COOKED"
            badge_class = "badge-cooked"
        else:
            badge = "⚠️ COOLING"
            badge_class = "badge-fade"
        fading_pair_cards += f"""
        <div class="trend-card trend-down">
            <div class="trend-info" style="flex:1">
                <span class="trend-name">{p['player_a']} + {p['player_b']}</span>
                <span class="trend-meta">{p['team']} // SYN {p['synergy_score']:.0f} // {p['gp']}G window</span>
                <span class="trend-stats">Window: {p['window_nrtg']:+.1f} NRtg | Season: {p['season_nrtg']:+.1f}</span>
            </div>
            <div class="trend-delta trend-neg">{p['delta']:.1f} NRtg</div>
        </div>"""

    # ── Build Ceiling/Floor Player Cards ──
    ceiling_cards = ""
    for p in ceiling_players:
        headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{p['player_id']}.png"
        icon = ARCHETYPE_ICONS.get(p["archetype"], "◆")
        ceiling_cards += f"""
        <div class="trend-card trend-up">
            <img src="{headshot}" class="trend-face" onerror="this.style.display='none'">
            <div class="trend-info">
                <span class="trend-name">{p['name']}</span>
                <span class="trend-meta">{p['team']} // {icon} {p['archetype']}</span>
                <span class="trend-stats">Raw: {p['raw_mojo']} → Context: {p['contextual_mojo']}</span>
            </div>
            <div class="trend-delta trend-pos">+{p['delta']} MOJO</div>
        </div>"""

    floor_cards = ""
    for p in floor_players:
        headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{p['player_id']}.png"
        icon = ARCHETYPE_ICONS.get(p["archetype"], "◆")
        floor_cards += f"""
        <div class="trend-card trend-down">
            <img src="{headshot}" class="trend-face" onerror="this.style.display='none'">
            <div class="trend-info">
                <span class="trend-name">{p['name']}</span>
                <span class="trend-meta">{p['team']} // {icon} {p['archetype']}</span>
                <span class="trend-stats">Raw: {p['raw_mojo']} → Context: {p['contextual_mojo']}</span>
            </div>
            <div class="trend-delta trend-neg">{p['delta']} MOJO</div>
        </div>"""

    # ── Lock picks removed (user request) ──
    lock_cards = ""

    # ── Build Top 50 MOJO Rankings ──
    top50_rows = ""
    for p in top50:
        ds = p["mojo"]
        if ds >= 83:
            ds_cls = "mojo-elite"
        elif ds >= 67:
            ds_cls = "mojo-good"
        elif ds >= 52:
            ds_cls = "mojo-avg"
        else:
            ds_cls = "mojo-low"
        icon = ARCHETYPE_ICONS.get(p["archetype"], "◆")
        headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{p['player_id']}.png"
        net_color = "#00CC44" if p["net"] >= 0 else "#FF3333"
        net_sign = "+" if p["net"] >= 0 else ""
        team_logo = get_team_logo_url(p["team"])

        bd = p["breakdown"]
        _rwd = _waste_data.get(int(p['player_id']), {})
        top50_rows += f"""
        <div class="rank-row" onclick="openPlayerSheet(this)"
             data-name="{p['name']}" data-arch="{p['archetype']}" data-mojo="{ds}" data-range="{p['low']}-{p['high']}"
             data-pts="{p['pts']}" data-ast="{p['ast']}" data-reb="{p['reb']}"
             data-stl="{p['stl']}" data-blk="{p['blk']}" data-ts="{p['ts']}"
             data-net="{p['net']}" data-usg="{bd.get('usg_pct', 0)}" data-mpg="{p['mpg']}"
             data-team="{p['team']}" data-pid="{p['player_id']}"
             data-scoring-pct="{bd.get('scoring_c', 0)}" data-playmaking-pct="{bd.get('playmaking_c', 0)}"
             data-defense-pct="{bd.get('defense_c', 0)}" data-efficiency-pct="{bd.get('efficiency_c', 0)}"
             data-impact-pct="{bd.get('impact_c', 0)}"
             data-raw-mojo="{bd.get('raw_mojo', ds)}" data-solo-impact="{bd.get('solo_impact', 50)}"
             data-syn-score="{bd.get('synergy_score', 50)}" data-fit-score="{bd.get('fit_score', 50)}"
             data-waste="{_rwd.get('waste', 0)}" data-mojo-gap="{_rwd.get('gap', 0)}"
             data-breakout="{_rwd.get('breakout', 0)}" data-role-mismatch="{_rwd.get('mismatch', 0)}"
             data-intel="{_rwd.get('notes', '')}">
            <span class="rank-num">#{p['rank']}</span>
            <img src="{headshot}" class="rank-face" onerror="this.style.display='none'">
            <img src="{team_logo}" class="rank-team-logo" onerror="this.style.display='none'">
            <div class="rank-info">
                <span class="rank-name">{p['name']}</span>
                <span class="rank-meta">{p['team']} // {icon} {p['archetype']}</span>
            </div>
            <div class="rank-stats">
                <span>{p['pts']}p {p['ast']}a {p['reb']}r</span>
                <span style="color:{net_color}">{net_sign}{p['net']}</span>
            </div>
            <div class="rank-mojo {ds_cls}">
                <span class="rank-mojo-num">{ds}</span>
                <span class="rank-mojo-range">{p['low']}-{p['high']}</span>
            </div>
        </div>"""

    # ── Build projected player lines for Props tab ──
    proj_lines_html = ""
    for m in matchups:
        ha = m["home_abbr"]
        aa = m["away_abbr"]
        h_logo = get_team_logo_url(ha)
        a_logo = get_team_logo_url(aa)

        away_projs = get_projected_player_lines(aa, ha, team_map)
        home_projs = get_projected_player_lines(ha, aa, team_map)

        proj_lines_html += f"""
        <div class="proj-matchup">
            <div class="proj-matchup-header">
                <img src="{a_logo}" class="proj-logo" onerror="this.style.display='none'">
                <span>{aa} @ {ha}</span>
                <img src="{h_logo}" class="proj-logo" onerror="this.style.display='none'">
            </div>
            <div class="proj-grid">
                <div class="proj-half">"""

        for p in away_projs:
            proj_lines_html += f"""
                    <div class="proj-row">
                        <span class="proj-name">{p['player']}</span>
                        <span class="proj-line">{p['proj_pts']}p</span>
                        <span class="proj-line">{p['proj_ast']}a</span>
                        <span class="proj-line">{p['proj_reb']}r</span>
                        <span class="proj-pra">{p['proj_pra']}</span>
                    </div>"""

        proj_lines_html += """
                </div>
                <div class="proj-half">"""

        for p in home_projs:
            proj_lines_html += f"""
                    <div class="proj-row">
                        <span class="proj-name">{p['player']}</span>
                        <span class="proj-line">{p['proj_pts']}p</span>
                        <span class="proj-line">{p['proj_ast']}a</span>
                        <span class="proj-line">{p['proj_reb']}r</span>
                        <span class="proj-pra">{p['proj_pra']}</span>
                    </div>"""

        proj_lines_html += """
                </div>
            </div>
        </div>"""

    # ── Build global OUT player ID set (for filtering injured from trends) ──
    global_out_pids = set()
    if matchups:
        rw_lu = matchups[0].get("rw_lineups", {})
        for team_abbr, lineup_info in rw_lu.items():
            roster = _get_full_roster(team_abbr)
            for name in lineup_info.get("out", []):
                pid = _match_player_name(name, roster)
                if pid is not None:
                    global_out_pids.add(int(pid))
            for name, pos, status in lineup_info.get("starters", []):
                if status == "OUT":
                    pid = _match_player_name(name, roster)
                    if pid is not None:
                        global_out_pids.add(int(pid))
    logger.info("Trends: %d OUT players excluded from fallers", len(global_out_pids))

    # ── Build WOWY Trending Players HTML ──
    risers, fallers = get_wowy_trending_players(out_player_ids=global_out_pids)
    trending_html = ""
    if risers or fallers:
        riser_cards = ""
        for p in risers:
            icon = ARCHETYPE_ICONS.get(p["archetype"], "◆")
            headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{p['player_id']}.png"
            team_logo = get_team_logo_url(p["team"])
            riser_cards += f"""
            <div class="trend-card trend-up">
                <img src="{team_logo}" class="trend-team-logo" onerror="this.style.display='none'">
                <img src="{headshot}" class="trend-face" onerror="this.style.display='none'">
                <div class="trend-info">
                    <span class="trend-name">{p['name']}</span>
                    <span class="trend-meta">{p['team']} // {icon} {p['archetype']}</span>
                    <span class="trend-stats">{p['avg_pts']}p {p['avg_ast']}a {p['avg_reb']}r ({p['gp']}G)</span>
                </div>
                <div class="trend-delta trend-pos">+{p['delta']:.1f} NRtg</div>
            </div>"""

        faller_cards = ""
        for p in fallers:
            icon = ARCHETYPE_ICONS.get(p["archetype"], "◆")
            headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{p['player_id']}.png"
            team_logo = get_team_logo_url(p["team"])
            faller_cards += f"""
            <div class="trend-card trend-down">
                <img src="{team_logo}" class="trend-team-logo" onerror="this.style.display='none'">
                <img src="{headshot}" class="trend-face" onerror="this.style.display='none'">
                <div class="trend-info">
                    <span class="trend-name">{p['name']}</span>
                    <span class="trend-meta">{p['team']} // {icon} {p['archetype']}</span>
                    <span class="trend-stats">{p['avg_pts']}p {p['avg_ast']}a {p['avg_reb']}r ({p['gp']}G)</span>
                </div>
                <div class="trend-delta trend-neg">{p['delta']:.1f} NRtg</div>
            </div>"""

        trending_html = f"""
            <div class="section-header">
                <h2>WOWY TRENDS</h2>
                <span class="section-sub">10-day trailing NRtg movers — WOWY impact (updated daily 8 AM)</span>
            </div>
            <div class="trends-grid">
                <div class="trends-column">
                    <div class="trends-col-header hot">📈 RISERS</div>
                    {riser_cards}
                </div>
                <div class="trends-column">
                    <div class="trends-col-header fade">📉 FALLERS</div>
                    {faller_cards}
                </div>
            </div>
        """

    # ── Build Lineup Lab HTML ──
    lab_data = get_lab_data()
    lab_html = build_lab_html(lab_data)

    # ── Build SIM tab data ──
    sim_data_json = json.dumps({
        "rosters": lab_data["rosters"],
        "pairs": lab_data.get("pairs", {}),
        "combos_2": lab_data.get("combos_2", {}),
        "combos_3": lab_data.get("combos_3", {}),
        "combos_4": lab_data.get("combos_4", {}),
        "combos_5": lab_data.get("combos_5", {}),
        "team_stats": lab_data.get("team_stats", {}),
        "team_hca": TEAM_HCA,
        "team_colors": TEAM_COLORS,
        "team_secondary": TEAM_SECONDARY,
        "team_ids": TEAM_IDS,
        "team_names": TEAM_FULL_NAMES,
        "moji_constants": _MOJI_CONSTANTS,
    }, separators=(",", ":"))

    # Build team option HTML for sim selectors
    sim_team_options = ""
    for abbr in sorted(lab_data["rosters"].keys()):
        name = TEAM_FULL_NAMES.get(abbr, abbr)
        sim_team_options += f'<option value="{abbr}">{abbr} — {name}</option>\n'

    # ── Build INFO page content ──
    info_content = render_info_page()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>NBA SIM // {slate_date}</title>
    <link rel="icon" type="image/svg+xml" href="/favicon.svg">
    <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
    <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
    <meta property="og:image" content="https://morellosims.com/og-image.png">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://morellosims.com/morello-auth.css">
    <style>
{generate_css()}
    </style>
</head>
<body>
    <!-- STICKY HEADER WRAPPER -->
    <div class="sticky-header">
        <!-- TOP HEADER -->
        <header class="top-bar">
            <div class="top-bar-inner">
                <div class="logo">
                    <img src="/favicon.svg" alt="Morello Sims" style="width:24px;height:24px;">
                    <span class="logo-text">NBA SIM</span>
                    <span class="logo-date">{slate_date}</span>
                    <span class="logo-credit">by Jack Morello</span>
                </div>
                <div class="top-picks">
                    {lock_cards}
                </div>
            </div>
        </header>

        <!-- FILTER BAR -->
        <div class="filter-bar">
            <div class="filter-bar-inner">
                <button class="filter-btn active" data-tab="slate">Game Lines</button>
                <button class="filter-btn" data-tab="sim">SIM (desktop)</button>
                <button class="filter-btn" data-tab="props">Player Stats</button>
                <button class="filter-btn" data-tab="trends">Trends</button>
                <button class="filter-btn" data-tab="info">Info</button>
            </div>
        </div>
    </div>

    <!-- MAIN CONTENT AREA -->
    <main class="content">

        <!-- SLATE TAB -->
        <div class="tab-content active" id="tab-slate">
            <div class="section-header">
                <h2>{slate_date} SLATE</h2>
                <span class="section-sub">{len(matchups)} games</span>
            </div>
            <div class="proj-disclaimer" style="margin-bottom:12px">
                <strong>MOJO</strong> (33–99) rates each player using 25% box-score stats + 75% lineup impact (WOWY on/off, 2-to-5-man synergy, and archetype fit). <strong>MOJI</strong> (0–99) converts team lineups into a quality score by weighting player MOJOs by projected minutes with fatigue and DNP adjustments.
            </div>
            <div class="sort-bar">
                <button class="sort-btn active" data-sort="default">All Games</button>
                <button class="sort-btn" data-sort="value">Best Value</button>
            </div>
            <div class="matchup-list" id="matchupList">
                {matchup_cards}
            </div>
        </div>

        <!-- PROPS TAB -->
        <div class="tab-content" id="tab-props">
            <div class="section-header">
                <h2>PLAYER STATS</h2>
                <span class="section-sub">Top 20 matchup spotlights ranked by MOJO + matchup advantage</span>
            </div>
            <div class="props-list">
                {props_cards}
            </div>

            <div class="section-header" style="margin-top:32px">
                <h2>PLAYER STAT LINES <span class="proj-tag">(PROJ. LINE)</span></h2>
                <span class="section-sub">Season averages adjusted for opponent defense + pace</span>
            </div>
            <div class="proj-disclaimer">
                All lines marked <strong>(PROJ. LINE)</strong> are SIM-projected from season stats adjusted for matchup.
                Real player props will replace projections when available via sportsbook API.
            </div>
            <div class="proj-lines-list">
                {proj_lines_html}
            </div>

            <!-- Top 50 MOJO Rankings — collapsible -->
            <div class="rankings-section" style="margin-top:32px">
                <div class="rankings-header" onclick="toggleRankings()">
                    <div>
                        <h2 class="rankings-title">TOP 50 MOJO</h2>
                        <span class="section-sub">League-wide player rankings by MOJO</span>
                    </div>
                    <span class="rankings-toggle" id="rankingsToggle">▼</span>
                </div>
                <div class="rankings-body" id="rankingsBody" style="display:none">
                    <div class="rankings-col-headers">
                        <span class="rch-rank">#</span>
                        <span class="rch-player">PLAYER</span>
                        <span class="rch-stats">STATS</span>
                        <span class="rch-mojo">MOJO</span>
                    </div>
                    {top50_rows}
                </div>
            </div>
        </div>

        <!-- TRENDS TAB -->
        <div class="tab-content" id="tab-trends">
            {trending_html}

            <div class="section-header" style="margin-top:24px">
                <h2>MOJO RANGE MOVERS</h2>
                <span class="section-sub">Players most elevated or suppressed by team context</span>
            </div>
            <div class="trends-grid">
                <div class="trends-column">
                    <div class="trends-col-header hot">🚀 CEILING PLAYERS</div>
                    {ceiling_cards}
                </div>
                <div class="trends-column">
                    <div class="trends-col-header fade">🪫 FLOOR PLAYERS</div>
                    {floor_cards}
                </div>
            </div>

            <div class="section-header" style="margin-top:24px">
                <h2>DUO TRENDS</h2>
                <span class="section-sub">Pair WOWY — 10-day window vs season baseline</span>
            </div>
            <div class="trends-grid">
                <div class="trends-column">
                    <div class="trends-col-header hot">🔥 SURGING DUOS</div>
                    {surging_pair_cards}
                </div>
                <div class="trends-column">
                    <div class="trends-col-header fade">💀 FADING DUOS</div>
                    {fading_pair_cards}
                </div>
            </div>

            <div class="section-header" style="margin-top:24px">
                <h2>LINEUP TRENDS</h2>
                <span class="section-sub">Hot combos + fades with full player details</span>
            </div>
            <div class="trends-grid">
                <div class="trends-column">
                    <div class="trends-col-header hot">🔥 HOT COMBOS</div>
                    {hot_cards}
                </div>
                <div class="trends-column">
                    <div class="trends-col-header fade">💀 FADE COMBOS</div>
                    {fade_cards}
                </div>
            </div>
        </div>

        <!-- WOWY TAB -->
        <!-- WOWY tab removed — functionality merged into SIM WOWY Inspector -->

        <!-- SIM TAB -->
        <div class="tab-content" id="tab-sim">
            <div class="sim-container">
                <!-- TEAM SELECTORS (logo grid) -->
                <div class="sim-team-bar">
                    <div class="sim-team-picker home">
                        <label class="sim-label" style="color:var(--green)">HOME</label>
                        <div class="sim-team-btn" id="simHomeBtnDisplay" onclick="simOpenTeamGrid('home')">
                            <img id="simHomeBtnLogo" class="sim-team-btn-logo" src="" style="display:none" alt="">
                            <span id="simHomeBtnText">Select team...</span>
                        </div>
                        <select id="simHomeTeam" class="sim-select" onchange="simTeamChange('home')" style="display:none">
                            <option value="">Select team...</option>
                            {sim_team_options}
                        </select>
                    </div>
                    <div class="sim-vs-badge">VS</div>
                    <div class="sim-team-picker away">
                        <label class="sim-label" style="color:#CE1141">AWAY</label>
                        <div class="sim-team-btn" id="simAwayBtnDisplay" onclick="simOpenTeamGrid('away')">
                            <img id="simAwayBtnLogo" class="sim-team-btn-logo" src="" style="display:none" alt="">
                            <span id="simAwayBtnText">Select team...</span>
                        </div>
                        <select id="simAwayTeam" class="sim-select" onchange="simTeamChange('away')" style="display:none">
                            <option value="">Select team...</option>
                            {sim_team_options}
                        </select>
                    </div>
                </div>
                <!-- TEAM LOGO GRID (overlay) -->
                <div class="sim-team-grid-overlay" id="simTeamGridOverlay" style="display:none" onclick="if(event.target===this)simCloseTeamGrid()">
                    <div class="sim-team-grid-panel">
                        <div class="sim-team-grid-title" id="simTeamGridTitle">SELECT HOME TEAM</div>
                        <div class="sim-team-grid" id="simTeamGrid"></div>
                    </div>
                </div>

                <!-- THREE-COLUMN LAYOUT (always visible) -->
                <div class="sim-three-col" id="simThreeCol">
                    <!-- LEFT: HOME PANEL -->
                    <div class="sim-panel home" id="simPanelHome">
                        <div class="sim-panel-header" id="simHomeHeader">
                            <img id="simHomeLogo" class="sim-panel-logo" src="" alt="">
                            <span id="simHomeLabel">HOME</span>
                            <span class="sim-moji-badge home" id="simHomeMojiBadge">MOJI —<span class="sim-moji-info">i</span><div class="sim-moji-tooltip"><strong>MOJI</strong> — Minutes-weighted Offensive Lineup Index<br><br>Lineup quality rating (0–99):<br>• Player MOJO scores weighted by minutes<br>• Usage redistribution from DNP players<br>• Fatigue penalty for overplayed minutes<br>• Archetype decay for extra usage load</div></span>
                        </div>
                        <!-- HALF-COURT with position slots -->
                        <div class="sim-court" id="simHomeCourt">
                            <div class="sim-onboard-banner" id="simOnboardHome" style="display:none">
                                <div class="sim-onboard-row"><strong>Click</strong> any synergy line to see pair chemistry below</div>
                                <div class="sim-onboard-row"><strong>Drag</strong> any card to swap lineup positions</div>
                                <button class="sim-onboard-dismiss" onclick="simDismissOnboard()">GOT IT</button>
                            </div>
                            <svg class="sim-court-lines" viewBox="0 0 400 320" preserveAspectRatio="none">
                                <rect x="0" y="0" width="400" height="320" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="2"/>
                                <path d="M 60 320 L 60 130 Q 60 70 120 70 L 280 70 Q 340 70 340 130 L 340 320" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="2"/>
                                <circle cx="200" cy="320" r="60" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="2"/>
                                <path d="M 30 320 Q 30 100 200 20 Q 370 100 370 320" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="1.5" stroke-dasharray="6,4"/>
                                <line x1="0" y1="320" x2="400" y2="320" stroke="rgba(255,255,255,0.1)" stroke-width="2"/>
                            </svg>
                            <svg class="sim-link-overlay" id="simHomeLinkOverlay"></svg>
                            <div class="sim-link-tooltip" id="simHomeLinkTooltip"></div>
                            <div class="sim-pos-slot" data-pos="GUARD" data-slot="1" data-side="home" style="top:5%;left:10%"
                                 ondrop="simDrop(event,'home','court')" ondragover="simAllowDrop(event)">
                                <span class="sim-pos-label">G</span>
                            </div>
                            <div class="sim-pos-slot" data-pos="GUARD" data-slot="2" data-side="home" style="top:5%;right:10%"
                                 ondrop="simDrop(event,'home','court')" ondragover="simAllowDrop(event)">
                                <span class="sim-pos-label">G</span>
                            </div>
                            <div class="sim-pos-slot" data-pos="WING" data-slot="1" data-side="home" style="top:35%;left:5%"
                                 ondrop="simDrop(event,'home','court')" ondragover="simAllowDrop(event)">
                                <span class="sim-pos-label">W</span>
                            </div>
                            <div class="sim-pos-slot" data-pos="WING" data-slot="2" data-side="home" style="top:35%;right:5%"
                                 ondrop="simDrop(event,'home','court')" ondragover="simAllowDrop(event)">
                                <span class="sim-pos-label">W</span>
                            </div>
                            <div class="sim-pos-slot" data-pos="BIG" data-slot="1" data-side="home" style="top:65%;left:50%;transform:translateX(-50%)"
                                 ondrop="simDrop(event,'home','court')" ondragover="simAllowDrop(event)">
                                <span class="sim-pos-label">B</span>
                            </div>
                        </div>
                        <!-- BENCH -->
                        <div class="sim-bench-strip" id="simHomeBenchStrip">
                            <div class="sim-bench-header">BENCH <span id="simHomeBenchCount">0</span></div>
                            <div class="sim-bench-zone" id="simHomeBenchZone"
                                 ondrop="simDrop(event,'home','bench')" ondragover="simAllowDrop(event)">
                                <span class="sim-bench-hint">Drag players here</span>
                            </div>
                        </div>
                        <!-- LOCKER ROOM (collapsible) -->
                        <div class="sim-locker-wrap" id="simHomeLockerWrap">
                            <div class="sim-locker-header" onclick="simToggleLocker('home')">
                                <span>LOCKER ROOM</span>
                                <span class="sim-locker-count" id="simHomeLockerCount">0</span>
                                <span class="sim-locker-arrow" id="simHomeLockerArrow">&#9660;</span>
                            </div>
                            <div class="sim-locker-zone" id="simHomeLockerZone" style="display:none"
                                 ondrop="simDrop(event,'home','locker')" ondragover="simAllowDrop(event)">
                            </div>
                        </div>
                    </div>

                    <!-- RIGHT: AWAY PANEL -->
                    <div class="sim-panel away" id="simPanelAway">
                        <div class="sim-panel-header" id="simAwayHeader">
                            <img id="simAwayLogo" class="sim-panel-logo" src="" alt="">
                            <span id="simAwayLabel">AWAY</span>
                            <span class="sim-moji-badge away" id="simAwayMojiBadge">MOJI —<span class="sim-moji-info">i</span><div class="sim-moji-tooltip"><strong>MOJI</strong> — Minutes-weighted Offensive Lineup Index<br><br>Lineup quality rating (0–99):<br>• Player MOJO scores weighted by minutes<br>• Usage redistribution from DNP players<br>• Fatigue penalty for overplayed minutes<br>• Archetype decay for extra usage load</div></span>
                        </div>
                        <!-- HALF-COURT with position slots -->
                        <div class="sim-court" id="simAwayCourt">
                            <div class="sim-onboard-banner" id="simOnboardAway" style="display:none">
                                <div class="sim-onboard-row"><strong>Click</strong> any synergy line to see pair chemistry below</div>
                                <div class="sim-onboard-row"><strong>Drag</strong> any card to swap lineup positions</div>
                                <button class="sim-onboard-dismiss" onclick="simDismissOnboard()">GOT IT</button>
                            </div>
                            <svg class="sim-court-lines" viewBox="0 0 400 320" preserveAspectRatio="none">
                                <rect x="0" y="0" width="400" height="320" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="2"/>
                                <path d="M 60 320 L 60 130 Q 60 70 120 70 L 280 70 Q 340 70 340 130 L 340 320" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="2"/>
                                <circle cx="200" cy="320" r="60" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="2"/>
                                <path d="M 30 320 Q 30 100 200 20 Q 370 100 370 320" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="1.5" stroke-dasharray="6,4"/>
                                <line x1="0" y1="320" x2="400" y2="320" stroke="rgba(255,255,255,0.1)" stroke-width="2"/>
                            </svg>
                            <svg class="sim-link-overlay" id="simAwayLinkOverlay"></svg>
                            <div class="sim-link-tooltip" id="simAwayLinkTooltip"></div>
                            <div class="sim-pos-slot" data-pos="GUARD" data-slot="1" data-side="away" style="top:5%;left:10%"
                                 ondrop="simDrop(event,'away','court')" ondragover="simAllowDrop(event)">
                                <span class="sim-pos-label">G</span>
                            </div>
                            <div class="sim-pos-slot" data-pos="GUARD" data-slot="2" data-side="away" style="top:5%;right:10%"
                                 ondrop="simDrop(event,'away','court')" ondragover="simAllowDrop(event)">
                                <span class="sim-pos-label">G</span>
                            </div>
                            <div class="sim-pos-slot" data-pos="WING" data-slot="1" data-side="away" style="top:35%;left:5%"
                                 ondrop="simDrop(event,'away','court')" ondragover="simAllowDrop(event)">
                                <span class="sim-pos-label">W</span>
                            </div>
                            <div class="sim-pos-slot" data-pos="WING" data-slot="2" data-side="away" style="top:35%;right:5%"
                                 ondrop="simDrop(event,'away','court')" ondragover="simAllowDrop(event)">
                                <span class="sim-pos-label">W</span>
                            </div>
                            <div class="sim-pos-slot" data-pos="BIG" data-slot="1" data-side="away" style="top:65%;left:50%;transform:translateX(-50%)"
                                 ondrop="simDrop(event,'away','court')" ondragover="simAllowDrop(event)">
                                <span class="sim-pos-label">B</span>
                            </div>
                        </div>
                        <!-- BENCH -->
                        <div class="sim-bench-strip" id="simAwayBenchStrip">
                            <div class="sim-bench-header">BENCH <span id="simAwayBenchCount">0</span></div>
                            <div class="sim-bench-zone" id="simAwayBenchZone"
                                 ondrop="simDrop(event,'away','bench')" ondragover="simAllowDrop(event)">
                                <span class="sim-bench-hint">Drag players here</span>
                            </div>
                        </div>
                        <!-- LOCKER ROOM (collapsible) -->
                        <div class="sim-locker-wrap" id="simAwayLockerWrap">
                            <div class="sim-locker-header" onclick="simToggleLocker('away')">
                                <span>LOCKER ROOM</span>
                                <span class="sim-locker-count" id="simAwayLockerCount">0</span>
                                <span class="sim-locker-arrow" id="simAwayLockerArrow">&#9660;</span>
                            </div>
                            <div class="sim-locker-zone" id="simAwayLockerZone" style="display:none"
                                 ondrop="simDrop(event,'away','locker')" ondragover="simAllowDrop(event)">
                            </div>
                        </div>
                    </div>

                    <!-- CENTER HUB: CONTROLS (full-width below courts) -->
                    <div class="sim-center-col" id="simCenterCol">
                        <div class="sim-center-top">
                            <!-- WOWY INSPECTOR (top of center console) -->
                            <div class="sim-wowy-inspector" id="simComboInspector">
                                <div class="sim-wowy-title">WOWY INSPECTOR</div>
                                <div id="simComboContent">
                                    <div class="sim-combo-empty">Click a synergy line or player card to inspect</div>
                                </div>
                            </div>
                            <!-- BLOCK 1: Schemes + Venue -->
                            <div class="sim-center-block">
                                <div class="sim-center-section">
                                    <div class="sim-center-label">VENUE</div>
                                    <div class="sim-venue-row">
                                        <select id="simVenue" class="sim-select-sm">
                                            <option value="home">Home Court</option>
                                            <option value="neutral">Neutral</option>
                                        </select>
                                        <span class="sim-hca-badge" id="simHcaBadge"></span>
                                    </div>
                                </div>
                                <div class="sim-center-section">
                                    <div class="sim-center-label">HOME SCHEME</div>
                                    <div class="sim-scheme-pills" id="simHomeSchemes"></div>
                                </div>
                                <div class="sim-center-section">
                                    <div class="sim-center-label">AWAY SCHEME</div>
                                    <div class="sim-scheme-pills" id="simAwaySchemes"></div>
                                </div>
                                <div class="sim-center-section">
                                    <div class="sim-b2b-row">
                                        <label class="sim-b2b-label">
                                            <input type="checkbox" id="simHomeB2B"> HOME B2B
                                        </label>
                                        <label class="sim-b2b-label">
                                            <input type="checkbox" id="simAwayB2B"> AWAY B2B
                                        </label>
                                    </div>
                                </div>
                                <!-- LINK MODE TOGGLE -->
                                <div class="sim-center-section">
                                    <div class="sim-link-toggle active" id="simLinkToggle" onclick="simToggleLinkMode()">
                                        <span class="sim-link-toggle-dot"></span>
                                        <div><div>LINK MODE</div><div class="sim-link-toggle-sub">Click lines to inspect pairs</div></div>
                                    </div>
                                </div>
                            </div>
                            <!-- BLOCK 2: Rotation Editor -->
                            <div class="sim-center-block">
                                <div class="sim-center-section" id="simRotationSection" style="display:none">
                                    <div class="sim-center-label">ROTATION</div>
                                    <div class="sim-rotation-tabs">
                                        <div class="sim-rotation-tab active" id="simRotTabHome" onclick="simSwitchRotTab('home')"><img id="simRotLogoHome" class="sim-rot-logo" src="" style="display:none"> HOME</div>
                                        <div class="sim-rotation-tab" id="simRotTabAway" onclick="simSwitchRotTab('away')"><img id="simRotLogoAway" class="sim-rot-logo" src="" style="display:none"> AWAY</div>
                                    </div>
                                    <div class="sim-rotation-wrap" id="simRotationContent"></div>
                                </div>
                            </div>
                            <!-- BLOCK 3: Run Button -->
                            <div class="sim-center-block">
                                <button class="sim-run-btn" id="simRunBtn" onclick="simRunGame()" disabled>
                                    &#9654; RUN SIMULATION
                                </button>
                                <div class="sim-action-info" id="simActionInfo">Select 5 per team</div>
                                <!-- INLINE RESULTS -->
                                <div class="sim-center-results" id="simCenterResults" style="display:none">
                                    <div class="sim-score-display" id="simScoreDisplay"></div>
                                    <div class="sim-winprob-bar" id="simWinProbBar"></div>
                                    <div class="sim-resim-btns">
                                        <button class="sim-resim-btn" onclick="simResim()">EDIT LINEUP</button>
                                        <button class="sim-resim-btn accent" onclick="simRunGame()">RE-SIM</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <!-- COMBO INSPECTOR moved to top of sim-center-top -->
                    </div>
                </div>

                <!-- FULL-WIDTH BOX SCORES (below three-col) -->
                <div class="sim-boxscore-full" id="simBoxScores" style="display:none"></div>
                <div id="simShotChart" style="display:none"></div>

                <!-- (empty state removed — courts always visible) -->
            </div>

            <script>
            const SIM_DATA = {sim_data_json};
            </script>
        </div>

        <!-- INFO TAB -->
        <div class="tab-content" id="tab-info">
            {info_content}
        </div>

    </main>

    <!-- BOTTOM NAV (MOBILE) -->
    <nav class="bottom-nav">
        <button class="nav-btn active" data-tab="slate">
            <span class="nav-icon">📊</span>
            <span>LINES</span>
        </button>
        <button class="nav-btn" data-tab="sim">
            <span class="nav-icon">🏀</span>
            <span>SIM</span>
        </button>
        <button class="nav-btn" data-tab="props">
            <span class="nav-icon">🎯</span>
            <span>PROPS</span>
        </button>
        <button class="nav-btn" data-tab="trends">
            <span class="nav-icon">📈</span>
            <span>TRENDS</span>
        </button>
        <button class="nav-btn" data-tab="info">
            <span class="nav-icon">ℹ️</span>
            <span>INFO</span>
        </button>
    </nav>

    <!-- PLAYER BOTTOM SHEET -->
    <div class="sheet-overlay" id="sheetOverlay"></div>
    <div class="bottom-sheet" id="bottomSheet">
        <div class="sheet-handle"></div>
        <div class="sheet-content" id="sheetContent"></div>
    </div>

    <script>
{generate_js()}
    </script>

    <!-- Firebase SDK + Morello Auth -->
    <script src="https://www.gstatic.com/firebasejs/10.8.0/firebase-app-compat.js"></script>
    <script src="https://www.gstatic.com/firebasejs/10.8.0/firebase-auth-compat.js"></script>
    <script src="https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore-compat.js"></script>
    <script src="https://morellosims.com/morello-auth.js" data-ma-theme="nba"></script>
</body>
</html>"""


def render_matchup_card(m, idx, team_map):
    """Render a single matchup card with spread/total and expandable lineup."""
    ha = m["home_abbr"]
    aa = m["away_abbr"]
    h = m["home"]
    a = m["away"]
    hc = TEAM_COLORS.get(ha, "#333")
    ac = TEAM_COLORS.get(aa, "#333")
    h_logo = get_team_logo_url(ha)
    a_logo = get_team_logo_url(aa)
    h_name = TEAM_FULL_NAMES.get(ha, ha)
    a_name = TEAM_FULL_NAMES.get(aa, aa)

    spread = m["spread"]
    total = m["total"]
    raw_edge = m["raw_edge"]
    spread_edge = m.get("spread_edge", 0)
    pick_text = m["pick_text"]
    spread_proj = m.get("spread_is_projected", True)
    total_proj = m.get("total_is_projected", True)

    # Spread display
    if spread <= 0:
        spread_display = f"{ha} {spread:+.1f}"
    else:
        spread_display = f"{aa} {-spread:+.1f}"

    spread_tag = ' <span class="proj-tag">(PROJ. SPREAD)</span>' if spread_proj else ""
    total_tag = ' <span class="proj-tag">(PROJ O/U)</span>' if total_proj else ""

    # Implied scores from spread + total
    implied_home = (total - spread) / 2
    implied_away = (total + spread) / 2
    implied_html = f'<div class="mc-implied">{aa} {implied_away:.0f} — {ha} {implied_home:.0f}</div>'

    # SIM projection line — show what the SIM thinks vs the book
    # Display using FAVORITE convention (same as the book line display)
    proj_spread_val = m.get("proj_spread", 0)
    if not spread_proj:
        # Show SIM projection when we have a real sportsbook line to compare
        if proj_spread_val <= 0:
            sim_fav_team = ha
            sim_fav_spread = proj_spread_val  # already negative
        else:
            sim_fav_team = aa
            sim_fav_spread = -proj_spread_val  # flip to negative (fav convention)

        # Edge = how much the SIM disagrees with the book (always positive magnitude)
        # spread_edge = proj_spread - spread (home perspective)
        edge_abs = abs(spread_edge)

        # Determine which team the SIM favors MORE than the book
        if spread_edge < 0:
            edge_team = ha  # SIM likes home more than book
        elif spread_edge > 0:
            edge_team = aa  # SIM likes away more than book
        else:
            edge_team = ""

        sim_proj_html = f'<div class="mc-sim-proj ma-premium">{sim_fav_team} {sim_fav_spread:+.1f} (SIM) · EDGE {edge_abs:.1f} {edge_team}</div>'
    else:
        sim_proj_html = ""

    # Tug of war bar — use full rotation for MOJI tug-of-war (injury-adjusted)
    home_mojo_sum = 0
    away_mojo_sum = 0
    home_roster = get_team_roster(ha, 15)
    away_roster = get_team_roster(aa, 15)
    for _, r in home_roster.head(5).iterrows():
        _pid = int(r.get("player_id", 0) or 0)
        _adj = _INJURY_ADJUSTED_VS.get(_pid)
        ds, _ = compute_mojo_score(r, injury_adjusted_composite=_adj)
        home_mojo_sum += ds
    for _, r in away_roster.head(5).iterrows():
        _pid = int(r.get("player_id", 0) or 0)
        _adj = _INJURY_ADJUSTED_VS.get(_pid)
        ds, _ = compute_mojo_score(r, injury_adjusted_composite=_adj)
        away_mojo_sum += ds

    total_ds = home_mojo_sum + away_mojo_sum
    home_pct = (home_mojo_sum / total_ds * 100) if total_ds > 0 else 50

    # Coaching schemes
    h_off = h.get("off_scheme_label", "") or ""
    h_def = h.get("def_scheme_label", "") or ""
    a_off = a.get("off_scheme_label", "") or ""
    a_def = a.get("def_scheme_label", "") or ""

    # Edge color — based on TRUE edge vs book (not raw power gap)
    spread_edge = m.get("spread_edge", 0)
    if abs(spread_edge) > 3:
        edge_color = "#00FF55"
    elif abs(spread_edge) > 1:
        edge_color = "#FFD600"
    else:
        edge_color = "#888"

    # Build player rows for expanded view with RotoWire status
    rw_lineups = m.get("rw_lineups", {})
    home_rw = rw_lineups.get(ha, {})
    away_rw = rw_lineups.get(aa, {})

    def _rw_status_for_player(player_name, rw_data):
        """Check if a player is OUT or GTD based on RotoWire/BREF data.

        Uses _normalize_name() to strip suffixes (Jr., III, etc.)
        so 'Jimmy Butler' matches 'Jimmy Butler III'.
        """
        if not rw_data:
            return "IN"
        out_names = rw_data.get("out", [])
        gtd_names = rw_data.get("questionable", [])
        p_norm = _normalize_name(player_name)
        p_last = p_norm[-1] if p_norm else ""
        p_init = p_norm[0][0] if p_norm else ""
        for out_n in out_names:
            o_norm = _normalize_name(out_n)
            o_last = o_norm[-1] if o_norm else ""
            o_init = o_norm[0][0] if o_norm else ""
            if o_last == p_last and o_init == p_init and p_last:
                return "OUT"
            if " ".join(o_norm) == " ".join(p_norm) and p_norm:
                return "OUT"
        for gtd_n in gtd_names:
            g_norm = _normalize_name(gtd_n)
            g_last = g_norm[-1] if g_norm else ""
            g_init = g_norm[0][0] if g_norm else ""
            if g_last == p_last and g_init == p_init and p_last:
                return "GTD"
            if " ".join(g_norm) == " ".join(p_norm) and p_norm:
                return "GTD"
        return "IN"

    def _is_rw_starter(player_name, rw_data):
        """Check if player is listed as a RotoWire starter."""
        if not rw_data:
            return False
        p_norm = _normalize_name(player_name)
        p_last = p_norm[-1] if p_norm else ""
        p_init = p_norm[0][0] if p_norm else ""
        for sname, spos, sstatus in rw_data.get("starters", []):
            s_norm = _normalize_name(sname)
            s_last = s_norm[-1] if s_norm else ""
            s_init = s_norm[0][0] if s_norm else ""
            if s_last == p_last and s_init == p_init and p_last:
                return True
            if " ".join(s_norm) == " ".join(p_norm) and p_norm:
                return True
        return False

    def _build_sorted_player_html(roster, team_abbr, rw_data):
        """Build player rows sorted: active starters → active bench → OUT."""
        players_with_info = []
        for _, player in roster.iterrows():
            status = _rw_status_for_player(player["full_name"], rw_data)
            is_starter = _is_rw_starter(player["full_name"], rw_data)
            # Sort key: 0 = active starter, 1 = active bench, 2 = GTD, 3 = OUT
            if status == "OUT":
                sort_key = 3
            elif status == "GTD":
                sort_key = 2 if not is_starter else 0
            elif is_starter:
                sort_key = 0
            else:
                sort_key = 1
            players_with_info.append((sort_key, player, status, is_starter))

        # Sort by key, then by minutes within each group
        players_with_info.sort(key=lambda x: (x[0], -(x[1].get("minutes_per_game", 0) or 0)))

        html = ""
        for sort_key, player, status, is_starter in players_with_info:
            html += render_player_row(player, team_abbr, team_map, is_starter=is_starter, rw_status=status)
        return html

    home_players_html = _build_sorted_player_html(home_roster, ha, home_rw)
    away_players_html = _build_sorted_player_html(away_roster, aa, away_rw)

    conf_pct = m["confidence"]
    # Confidence: 1-10 scale from distance to 50 (toss-up)
    conf_grade_100 = min(100, int(abs(conf_pct - 50) * 2.5 + 20))
    conf_10 = max(1, min(10, round(conf_grade_100 / 10)))
    if conf_10 >= 8:
        conf_color = "#00FF55"
    elif conf_10 >= 6:
        conf_color = "#7FFF00"
    elif conf_10 >= 4:
        conf_color = "#FFD600"
    elif conf_10 >= 2:
        conf_color = "#FF8C00"
    else:
        conf_color = "#FF3333"

    # O/U pick data
    ou_dir = m.get("ou_direction", "OVER")
    ou_text = m.get("ou_pick_text", f"O {total:.1f}")
    ou_conf = m.get("ou_conf", 5)
    ou_edge = m.get("ou_edge", 0)
    ou_sign = "+" if ou_edge > 0 else ""
    if ou_conf >= 7:
        ou_color = "#00FF55"
    elif ou_conf >= 5:
        ou_color = "#FFD600"
    else:
        ou_color = "#FF8C00"

    # ── MOJI Breakdown ──
    bd = m.get("spread_breakdown", {})
    home_moji = bd.get("home_moji", 0)
    away_moji = bd.get("away_moji", 0)
    moji_diff = bd.get("moji_diff", 0)
    moji_pts = bd.get("moji_pts", 0)
    home_nrtg = bd.get("home_nrtg", 0)
    away_nrtg = bd.get("away_nrtg", 0)
    nrtg_diff = bd.get("nrtg_diff", 0)
    recent_nrtg_diff = bd.get("recent_nrtg_diff", 0)
    home_recent_nrtg = bd.get("home_recent_nrtg", 0)
    away_recent_nrtg = bd.get("away_recent_nrtg", 0)
    home_syn = bd.get("home_syn", 50)
    away_syn = bd.get("away_syn", 50)
    syn_diff = bd.get("syn_diff", 0)
    syn_pts = bd.get("syn_pts", 0)
    home_b2b = bd.get("home_b2b", False)
    away_b2b = bd.get("away_b2b", False)
    home_out_n = bd.get("home_out", 0)
    away_out_n = bd.get("away_out", 0)
    home_lq = bd.get("home_lineup_q", 0)
    away_lq = bd.get("away_lineup_q", 0)
    raw_power_val = bd.get("raw_power", 0)

    # B2B badge HTML — ▼ arrow = fatigue penalty (weaker), not a spread line
    b2b_badges = ""
    if home_b2b:
        b2b_badges += f'<span class="b2b-badge" style="color:#FF6B6B">{ha} B2B \u25BC2</span>'
    if away_b2b:
        b2b_badges += f'<span class="b2b-badge" style="color:#FF6B6B">{aa} B2B \u25BC2.5</span>'

    # OUT player count badges
    out_badges = ""
    if home_out_n > 0:
        out_badges += f'<span class="out-badge">{ha}: {home_out_n} OUT</span>'
    if away_out_n > 0:
        out_badges += f'<span class="out-badge">{aa}: {away_out_n} OUT</span>'

    # MOJI bar visualization
    moji_total = home_moji + away_moji
    moji_home_pct = (home_moji / moji_total * 100) if moji_total > 0 else 50

    # Which team MOJI favors
    if moji_diff > 0:
        moji_fav = ha
        moji_fav_val = f"+{abs(moji_diff):.1f}"
    elif moji_diff < 0:
        moji_fav = aa
        moji_fav_val = f"+{abs(moji_diff):.1f}"
    else:
        moji_fav = "EVEN"
        moji_fav_val = ""

    # Which team season NRtg favors
    if nrtg_diff > 0:
        nrtg_fav = ha
        nrtg_fav_val = f"+{abs(nrtg_diff):.1f}"
    elif nrtg_diff < 0:
        nrtg_fav = aa
        nrtg_fav_val = f"+{abs(nrtg_diff):.1f}"
    else:
        nrtg_fav = "EVEN"
        nrtg_fav_val = ""

    # Which team L10 NRtg favors
    if recent_nrtg_diff > 0:
        l10_fav = ha
        l10_fav_val = f"+{abs(recent_nrtg_diff):.1f}"
    elif recent_nrtg_diff < 0:
        l10_fav = aa
        l10_fav_val = f"+{abs(recent_nrtg_diff):.1f}"
    else:
        l10_fav = "EVEN"
        l10_fav_val = ""

    # Model weighting computations (must match _MOJI_CONSTANTS: 40/10/30/20)
    moji_weighted = 0.40 * moji_pts
    nrtg_weighted = 0.10 * nrtg_diff + 0.30 * recent_nrtg_diff
    syn_weighted = 0.20 * syn_pts
    proj_spread_val = m.get("proj_spread", 0)

    # Which team SYN favors
    if syn_diff > 0:
        syn_fav = ha
        syn_fav_val = f"+{abs(syn_diff):.1f}"
    elif syn_diff < 0:
        syn_fav = aa
        syn_fav_val = f"+{abs(syn_diff):.1f}"
    else:
        syn_fav = "EVEN"
        syn_fav_val = ""

    breakdown_html = f"""
        <div class="moji-breakdown">
            <div class="moji-row">
                <span class="moji-label">MOJI</span>
                <span class="moji-val">{aa} {away_moji:.1f}</span>
                <div class="moji-bar-mini">
                    <div class="moji-bar-away" style="width:{100-moji_home_pct:.0f}%; background:{ac};"></div>
                    <div class="moji-bar-home" style="width:{moji_home_pct:.0f}%; background:{hc};"></div>
                </div>
                <span class="moji-val">{ha} {home_moji:.1f}</span>
                <span class="moji-edge-sm">{moji_fav} {moji_fav_val}</span>
            </div>
            <div class="moji-row">
                <span class="moji-label">NRtg</span>
                <span class="moji-val">{aa} {away_nrtg:+.1f}</span>
                <div class="moji-mid-spacer"></div>
                <span class="moji-val">{ha} {home_nrtg:+.1f}</span>
                <span class="moji-edge-sm">{nrtg_fav} {nrtg_fav_val}</span>
            </div>
            <div class="moji-row">
                <span class="moji-label">L10</span>
                <span class="moji-val">{aa} {away_recent_nrtg:+.1f}</span>
                <div class="moji-mid-spacer"></div>
                <span class="moji-val">{ha} {home_recent_nrtg:+.1f}</span>
                <span class="moji-edge-sm">{l10_fav} {l10_fav_val}</span>
            </div>
            <div class="moji-row">
                <span class="moji-label">SYN</span>
                <span class="moji-val">{aa} {away_syn:.1f}</span>
                <div class="moji-mid-spacer"></div>
                <span class="moji-val">{ha} {home_syn:.1f}</span>
                <span class="moji-edge-sm">{syn_fav} {syn_fav_val}</span>
            </div>
            <div class="moji-row moji-model-row ma-premium">
                <span class="moji-label">MODEL</span>
                <span class="moji-model-formula">40% MOJI ({moji_weighted:+.1f}) + 10% NRtg ({0.10 * nrtg_diff:+.1f}) + 30% L10 ({0.30 * recent_nrtg_diff:+.1f}) + 20% SYN ({syn_weighted:+.1f}) = <strong>PROJ {ha if proj_spread_val <= 0 else aa} {(-abs(proj_spread_val)):+.1f}</strong></span>
            </div>
            <div class="moji-row moji-tags">
                <span class="hca-badge">HCA \u25B2{TEAM_HCA.get(ha, 1.8):.1f} {ha}</span>
                {b2b_badges}
                {out_badges}
            </div>
        </div>"""

    # Sportsbook odds buttons row
    book_odds = m.get("bookmaker_odds", [])

    # Affiliate link templates
    AFFILIATE_LINKS = {
        "draftkings": "https://sportsbook.draftkings.com",
        "fanduel": "https://sportsbook.fanduel.com",
        "betmgm": "https://sports.betmgm.com",
        "bovada": "https://www.bovada.lv",
        "pointsbetus": "https://www.pointsbet.com",
        "bethog": "https://bethog.com/r/alphamale",
    }

    BOOK_DISPLAY = {
        "draftkings": "DK",
        "fanduel": "FD",
        "betmgm": "MGM",
        "bovada": "BOV",
        "pointsbetus": "PBU",
        "bethog": "BetHOG",
    }

    BOOK_COLORS = {
        "draftkings": "#53d337",
        "fanduel": "#1493ff",
        "betmgm": "#c4a44a",
        "bovada": "#cc0000",
        "pointsbetus": "#ed1c24",
        "bethog": "#ff6b00",
    }

    sportsbook_btns = ""
    if book_odds:
        # Determine pick side for edge display
        pick_side = ha if proj_spread_val <= 0 else aa

        btns_html = ""
        for bk in book_odds:
            bk_key = bk["key"]
            bk_name = BOOK_DISPLAY.get(bk_key, bk_key.upper()[:3])
            bk_color = BOOK_COLORS.get(bk_key, "#888")
            bk_spread = bk["spread"]  # home perspective
            bk_link = AFFILIATE_LINKS.get(bk_key, "#")

            # Display spread from favorite perspective (same convention as main display)
            if bk_spread <= 0:
                disp_team = ha
                disp_spread = bk_spread
            else:
                disp_team = aa
                disp_spread = -bk_spread

            # Calculate edge: difference between model and this book's line
            edge_val = abs(proj_spread_val - bk_spread)
            edge_class = "sb-edge-hot" if edge_val >= 2.5 else "sb-edge-mild" if edge_val >= 1 else "sb-edge-none"

            btns_html += f'''<a href="{bk_link}" target="_blank" rel="noopener" class="sb-btn" style="border-color:{bk_color}40">
                <span class="sb-name" style="color:{bk_color}">{bk_name}</span>
                <span class="sb-line">{disp_team} {disp_spread:+.1f}</span>
                <span class="{edge_class}">{edge_val:+.1f}</span>
            </a>'''

        sportsbook_btns = f'''
        <!-- Sportsbook Odds -->
        <div class="mc-sportsbooks">
            <span class="sb-header">BOOKS</span>
            {btns_html}
        </div>'''

    # BetHOG button — always rendered regardless of Odds API status
    bethog_btn = f'''
        <div class="mc-sportsbooks mc-bethog-row">
            <a href="{AFFILIATE_LINKS['bethog']}" target="_blank" rel="noopener" class="sb-btn sb-btn-featured" style="border-color:{BOOK_COLORS['bethog']}60">
                <img src="https://www.bethog.com/logo-mini.svg" class="sb-logo" alt="BetHOG" style="height:16px;filter:brightness(0);">
                <span class="sb-name" style="color:{BOOK_COLORS['bethog']}">BetHOG</span>
                <span class="sb-line">BET NOW</span>
            </a>
        </div>'''

    # ── Prediction Markets row (Kalshi win probabilities) ──
    pm_data = m.get("prediction_markets", {})
    prediction_btns = ""

    kalshi_data = pm_data.get("kalshi") if pm_data else None

    if kalshi_data:
        k_home = kalshi_data["home_prob"]
        k_away = kalshi_data["away_prob"]
        # Show the favorite's probability
        if k_home >= k_away:
            k_team = ha
            k_prob = k_home
        else:
            k_team = aa
            k_prob = k_away
        k_link = "https://kalshi.com/sign-up/?referral=88acd325-1cbe-44b0-9358-f0cf92cf9fc7"
        pm_btn_html = f'''<a href="{k_link}" target="_blank" rel="noopener" class="sb-btn pm-btn" style="border-color:#00C48040">
            <img src="https://kalshi.com/logo192.png" class="sb-logo" alt="Kalshi" style="height:16px;border-radius:3px;">
            <span class="sb-name" style="color:#00C480">KALSHI</span>
            <span class="sb-line">{k_team} {k_prob*100:.0f}%</span>
        </a>'''

        prediction_btns = f'''
        <!-- Prediction Markets -->
        <div class="mc-sportsbooks mc-prediction-markets">
            <span class="sb-header">MARKETS</span>
            {pm_btn_html}
        </div>'''

    return f"""
    <div class="matchup-card" data-conf="{conf_10}" data-edge="{abs(spread_edge):.1f}" data-total="{total}" data-idx="{idx}">
        <div class="mc-header">
            <div class="mc-team mc-away">
                <img src="{a_logo}" class="mc-logo" alt="{aa}" onerror="this.style.display='none'">
                <div class="mc-team-info">
                    <span class="mc-abbr">{aa}</span>
                    <span class="mc-mojo-rank">MOJO #{m['a_mojo_rank']}</span>
                    <span class="mc-record">{m['a_wins']}-{m['a_losses']}</span>
                </div>
            </div>
            <div class="mc-center">
                <div class="mc-spread ma-premium" style="color:{edge_color}">{spread_display}{spread_tag}</div>
                <div class="mc-total">O/U {total:.1f}{total_tag}</div>
                <div class="mc-pick ma-premium"><span class="pick-label">SPREAD</span> {pick_text} <span class="mc-conf-num" style="color:{conf_color}">{conf_10}</span></div>
                {implied_html}
                {sim_proj_html}
            </div>
            <div class="mc-team mc-home">
                <div class="mc-team-info right">
                    <span class="mc-abbr">{ha}</span>
                    <span class="mc-mojo-rank">MOJO #{m['h_mojo_rank']}</span>
                    <span class="mc-record">{m['h_wins']}-{m['h_losses']}</span>
                </div>
                <img src="{h_logo}" class="mc-logo" alt="{ha}" onerror="this.style.display='none'">
            </div>
        </div>

        <!-- Tug of war bar -->
        <div class="tow-bar">
            <div class="tow-fill tow-away" style="width:{100-home_pct:.1f}%; background:{ac};"></div>
            <div class="tow-fill tow-home" style="width:{home_pct:.1f}%; background:{hc};"></div>
            <div class="tow-mid"></div>
        </div>
        <div class="tow-labels">
            <span>{aa} MOJO {away_mojo_sum}</span>
            <span>{ha} MOJO {home_mojo_sum}</span>
        </div>

        <!-- Schemes row -->
        <div class="mc-schemes">
            <div class="scheme-tag" style="background:{ac}; color:{TEAM_SECONDARY.get(aa, '#fff')}">{a_off}</div>
            <div class="scheme-tag" style="background:{ac}; color:{TEAM_SECONDARY.get(aa, '#fff')}">{a_def}</div>
            <div class="scheme-divider">vs</div>
            <div class="scheme-tag" style="background:{hc}; color:{TEAM_SECONDARY.get(ha, '#fff')}">{h_off}</div>
            <div class="scheme-tag" style="background:{hc}; color:{TEAM_SECONDARY.get(ha, '#fff')}">{h_def}</div>
        </div>

        <!-- MOJI Breakdown -->
        {breakdown_html}

        {sportsbook_btns}
        {prediction_btns}
        {bethog_btn}

        <!-- Expand button -->
        <button class="expand-btn" onclick="toggleExpand(this)">
            <span>▼ VIEW LINEUPS</span>
        </button>

        <!-- Expanded lineup section -->
        <div class="mc-expanded" style="display:none">
            <div class="lineup-half">
                <div class="lineup-team-header" style="border-color:{ac}">{aa} {a_name}</div>
                {away_players_html}
            </div>
            <div class="lineup-half">
                <div class="lineup-team-header" style="border-color:{hc}">{ha} {h_name}</div>
                {home_players_html}
            </div>
        </div>
    </div>"""


def render_player_row(player, team_abbr, team_map, is_starter=True, rw_status="IN"):
    """Render a player row inside a matchup card with MOJO, archetype, context."""
    pid = int(player.get("player_id", 0) or 0)
    adj = _INJURY_ADJUSTED_VS.get(pid)
    ds, breakdown = compute_mojo_score(player, injury_adjusted_composite=adj)

    # Compute injury delta for badge display
    inj_delta = 0
    if adj is not None:
        season_mojo, _ = compute_mojo_score(player)  # un-adjusted
        inj_delta = ds - season_mojo

    low, high = compute_mojo_range(ds, pid)
    arch = player.get("archetype_label", "") or "Unclassified"
    icon = ARCHETYPE_ICONS.get(arch, "◆")
    name = player["full_name"]
    parts = name.split()
    short = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else name
    pos = player.get("listed_position", "")
    mpg = player.get("minutes_per_game", 0) or 0
    player_id = player.get("player_id", 0)
    pts = player.get("pts_pg", 0) or 0
    ast = player.get("ast_pg", 0) or 0
    reb = player.get("reb_pg", 0) or 0

    headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{player_id}.png"

    if ds >= 83:
        ds_class = "mojo-elite"
    elif ds >= 67:
        ds_class = "mojo-good"
    elif ds >= 52:
        ds_class = "mojo-avg"
    else:
        ds_class = "mojo-low"

    starter_class = "starter" if is_starter else "bench"
    bd = breakdown

    # RotoWire status classes
    status_class = ""
    status_badge = ""
    if rw_status == "OUT":
        status_class = "player-out"
        status_badge = '<span class="rw-status-badge rw-out">OUT</span>'
    elif rw_status == "GTD":
        status_class = "player-gtd"
        status_badge = '<span class="rw-status-badge rw-gtd">GTD</span>'

    # Top WOWY partners for enhanced player card
    top_pairs = _PLAYER_TOP_PAIRS.get(pid, [])
    top_pairs_json = json.dumps(top_pairs).replace('"', '&quot;')

    # Scouting intel from player_potential
    _wd = _waste_data.get(pid, {})
    w_waste = _wd.get("waste", 0)
    w_gap = _wd.get("gap", 0)
    w_breakout = _wd.get("breakout", 0)
    w_mismatch = _wd.get("mismatch", 0)
    w_intel = _wd.get("notes", "")  # Pre-sanitized by _sanitize_html_attr at load

    return f"""
    <div class="player-row {starter_class} {status_class}" onclick="openPlayerSheet(this)"
         data-name="{name}" data-arch="{arch}" data-mojo="{ds}" data-range="{low}-{high}"
         data-pts="{bd['pts']}" data-ast="{bd['ast']}" data-reb="{bd['reb']}"
         data-stl="{bd['stl']}" data-blk="{bd['blk']}" data-ts="{bd['ts_pct']}"
         data-net="{bd['net_rating']}" data-usg="{bd['usg_pct']}" data-mpg="{bd['mpg']}"
         data-team="{team_abbr}" data-pid="{player_id}"
         data-scoring-pct="{bd['scoring_c']}" data-playmaking-pct="{bd['playmaking_c']}"
         data-defense-pct="{bd['defense_c']}" data-efficiency-pct="{bd['efficiency_c']}"
         data-impact-pct="{bd['impact_c']}"
         data-raw-mojo="{bd.get('raw_mojo', ds)}" data-solo-impact="{bd.get('solo_impact', 50)}"
         data-syn-score="{bd.get('synergy_score', 50)}" data-fit-score="{bd.get('fit_score', 50)}"
         data-inj-delta="{inj_delta}"
         data-waste="{w_waste}" data-mojo-gap="{w_gap}"
         data-breakout="{w_breakout}" data-role-mismatch="{w_mismatch}"
         data-intel="{w_intel}"
         data-top-pairs="{top_pairs_json}">
        <img src="{headshot}" class="pr-face" onerror="this.style.display='none'">
        <div class="pr-info">
            <span class="pr-name">{short} {status_badge}</span>
            <span class="pr-meta">{pos} {icon} {arch}</span>
        </div>
        <div class="pr-stats">
            <span>{pts:.0f}p {ast:.0f}a {reb:.0f}r</span>
            <span>{mpg:.0f} mpg</span>
        </div>
        <div class="pr-mojo {ds_class}">
            <span class="pr-mojo-num">{ds}</span>{'<span class="pr-inj-delta ' + ('inj-up' if inj_delta > 0 else 'inj-down') + '">' + ('+' if inj_delta > 0 else '') + str(inj_delta) + '</span>' if inj_delta != 0 else ''}
            <span class="pr-mojo-range">{low}-{high}</span>
        </div>
    </div>"""


def render_stat_card(prop, rank):
    """Render a player stat spotlight card — no picks, pure research."""
    team_logo = get_team_logo_url(prop["team"])
    headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{prop['player_id']}.png"
    tc = TEAM_COLORS.get(prop["team"], "#333")

    # MOJO badge color
    ds = prop["mojo"]
    if ds >= 83:
        ds_color = "var(--green)"
        ds_bg = "rgba(0,255,85,0.12)"
    elif ds >= 67:
        ds_color = "var(--amber)"
        ds_bg = "rgba(255,214,0,0.1)"
    else:
        ds_color = "rgba(255,255,255,0.5)"
        ds_bg = "rgba(255,255,255,0.06)"

    # Matchup advantage badge
    ml = prop.get("matchup_label", "NEUTRAL")
    if ml == "ELITE":
        mu_color = "#00FF55"; mu_bg = "rgba(0,255,85,0.12)"
    elif ml == "GOOD":
        mu_color = "#7FFF00"; mu_bg = "rgba(127,255,0,0.1)"
    elif ml == "NEUTRAL":
        mu_color = "rgba(255,255,255,0.5)"; mu_bg = "rgba(255,255,255,0.06)"
    elif ml == "TOUGH":
        mu_color = "#FF8C00"; mu_bg = "rgba(255,140,0,0.1)"
    else:
        mu_color = "#FF5555"; mu_bg = "rgba(255,85,85,0.1)"

    # Sportsbook lines for context (not a pick)
    lines_html = ""
    lines_display = prop.get("lines_display", {})
    if lines_display:
        line_parts = []
        for stat, val in lines_display.items():
            line_parts.append(f'<span class="stat-line-ref">{stat} {val:.1f}</span>')
        lines_html = f'<div class="stat-lines-row">{"".join(line_parts)}</div>'
    elif prop.get("primary_line"):
        proj_tag = ' <span class="proj-tag">PROJ</span>' if prop.get("line_is_projected") else ""
        lines_html = f'<div class="stat-lines-row"><span class="stat-line-ref">PTS {prop["primary_line"]}{proj_tag}</span></div>'

    # Edge vs line (informational) — only show when we have a line to compare
    edge = prop.get("edge", 0)
    has_line = prop.get("primary_line") is not None
    if has_line and abs(edge) > 0.01:
        edge_sign = "+" if edge > 0 else ""
        edge_str = f"Δ {edge_sign}{edge:.1f}"
        edge_color = "rgba(0,255,85,0.6)" if edge > 0 else "rgba(255,80,80,0.5)" if edge < -1 else "rgba(255,255,255,0.3)"
    else:
        edge_str = f"DRTG {prop.get('opp_drtg', 112):.0f}"
        edge_color = "rgba(255,255,255,0.3)"

    # Last 5 games — show raw values (no hit/miss coloring)
    last5 = prop.get("last5", [])
    last5_html = ""
    if last5:
        dots = []
        for val in last5:
            dots.append(f'<span class="l5-val l5-neutral">{val}</span>')
        avg5 = sum(last5) / len(last5) if last5 else 0
        last5_html = f"""
        <div class="prop-last5">
            {"".join(dots)}
            <span class="l5-hit-rate">L5 avg: {avg5:.0f}</span>
        </div>"""

    return f"""
    <div class="stat-spotlight-card" style="border-left: 3px solid {tc};">
        <div class="prop-rank-num">{rank}</div>
        <div class="prop-row">
            <img src="{headshot}" class="prop-face" onerror="this.style.display='none'">
            <div class="prop-info">
                <div class="prop-name-row">
                    <span class="prop-name">{prop['player']}</span>
                    <span class="prop-team-opp">{prop['team']} vs {prop['opponent']}</span>
                </div>
                <div class="prop-meta">{ARCHETYPE_ICONS.get(prop['archetype'], '◆')} {prop['archetype']} · <span style="color:{ds_color}">MOJO {ds}</span></div>
            </div>
            <div class="stat-summary-box">
                <span class="stat-summary-line">{prop.get('stat_line', '')}</span>
                <span class="stat-matchup-badge" style="color:{mu_color};background:{mu_bg}">{ml}</span>
            </div>
        </div>
        <div class="prop-bottom">
            <div class="prop-edge" style="color:{edge_color}">{edge_str}</div>
            {lines_html}
            <div class="prop-note">{prop['note']}</div>
            {last5_html}
        </div>
    </div>"""


def render_combo_card(combo, is_fade=False):
    """Render a lineup combo card with full player details."""
    net = combo["net_rating"]
    badge = combo.get("badge", "")
    badge_class = combo.get("badge_class", "")
    gp = combo.get("gp", 0)
    mins = combo.get("minutes", 0)
    card_class = "combo-card fade" if is_fade else "combo-card hot"

    players_html = ""
    for pl in combo["players"]:
        ds = pl["mojo"]
        arch = pl["archetype"]
        icon = ARCHETYPE_ICONS.get(arch, "◆")
        pid = pl["player_id"]
        headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{pid}.png"
        low, high = compute_mojo_range(ds, int(pid))

        if ds >= 83:
            ds_cls = "mojo-elite"
        elif ds >= 67:
            ds_cls = "mojo-good"
        elif ds >= 52:
            ds_cls = "mojo-avg"
        else:
            ds_cls = "mojo-low"

        _cwd = _waste_data.get(int(pid), {})
        players_html += f"""
        <div class="combo-player" onclick="openPlayerSheet(this)"
             data-name="{pl['name']}" data-arch="{arch}" data-mojo="{ds}" data-range="{low}-{high}"
             data-pid="{pid}" data-team="{combo['team']}"
             data-waste="{_cwd.get('waste', 0)}" data-mojo-gap="{_cwd.get('gap', 0)}"
             data-role-mismatch="{_cwd.get('mismatch', 0)}"
             data-intel="{_cwd.get('notes', '')}">
            <img src="{headshot}" class="combo-face" onerror="this.style.display='none'">
            <span class="combo-pname">{pl['name']}</span>
            <span class="combo-parch">{icon} {arch}</span>
            <span class="combo-pds {ds_cls}">{ds}</span>
        </div>"""

    return f"""
    <div class="{card_class}">
        <div class="combo-top">
            <span class="combo-type">{combo['type']}</span>
            <img src="{get_team_logo_url(combo['team'])}" class="combo-logo" onerror="this.style.display='none'">
            <span class="combo-team">{combo['team']}</span>
        </div>
        {"<div class='combo-badge " + badge_class + "'>" + badge + "</div>" if badge else ""}
        <div class="combo-players-list">
            {players_html}
        </div>
        <div class="combo-stats">
            <div class="combo-stat-item">
                <span>NET RTG</span>
                <span class="{'positive' if net > 0 else 'negative'}">{net:+.1f}</span>
            </div>
            <div class="combo-stat-item">
                <span>GP</span>
                <span>{gp}</span>
            </div>
            <div class="combo-stat-item">
                <span>MIN/G</span>
                <span>{mins:.1f}</span>
            </div>
        </div>
        <div class="combo-trend-note">{gp} games tracked</div>
    </div>"""


def render_info_page():
    """Render the full INFO page with methodology, archetypes, MOJO guide, coaching."""
    # Build archetype cards
    arch_cards = ""
    for arch, desc in sorted(ARCHETYPE_DESCRIPTIONS.items()):
        icon = ARCHETYPE_ICONS.get(arch, "◆")
        arch_cards += f"""
        <div class="info-arch-card">
            <div class="info-arch-icon">{icon}</div>
            <div class="info-arch-name">{arch}</div>
            <div class="info-arch-desc">{desc}</div>
        </div>"""

    return f"""
    <div class="info-page">
        <div class="info-section">
            <h2 class="info-title">HOW NBA SIM WORKS</h2>
            <p class="info-text">
                NBA SIM is a data-driven prediction system that analyzes coaching schemes, player archetypes,
                and lineup synergy to predict game spreads and over/unders. All data sourced from 2025-26 NBA
                season statistics via the official NBA API.
            </p>
        </div>

        <div class="info-section">
            <h2 class="info-title">MOJO (Morello's Optimized Joint Output) — 33 TO 99</h2>
            <p class="info-text">
                Every player gets a MOJO score from 33-99 using a <strong>75% offense / 25% defense</strong>
                split plus shared impact components, blended with team synergy context.
            </p>
            <div class="info-formula">
                <div class="formula-row" style="color:rgba(0,0,0,0.7)"><span><strong>OFFENSE (75%)</strong></span><span></span></div>
                <div class="formula-row"><span>Points</span><span>× 1.2</span></div>
                <div class="formula-row"><span>Assists</span><span>× 1.8</span></div>
                <div class="formula-row"><span>True Shooting %</span><span>× 40</span></div>
                <div class="formula-row"><span>Usage %</span><span>× 15</span></div>
                <div class="formula-row" style="color:rgba(0,0,0,0.7); margin-top:4px"><span><strong>DEFENSE (25%)</strong></span><span></span></div>
                <div class="formula-row"><span>Stocks (STL × 8.0 + BLK × 6.0)</span><span></span></div>
                <div class="formula-row"><span>Def Rating bonus</span><span>(115 − DRtg) × 2.5</span></div>
                <div class="formula-row" style="color:rgba(0,0,0,0.7); margin-top:4px"><span><strong>SHARED</strong></span><span></span></div>
                <div class="formula-row"><span>Rebounds</span><span>× 0.8</span></div>
                <div class="formula-row"><span>Net Rating</span><span>× 0.8</span></div>
                <div class="formula-row"><span>Minutes/Game</span><span>× 0.3</span></div>
            </div>
            <p class="info-text">
                <strong>Defensive Rating (DRtg)</strong> matters: a player with 107 DRtg earns ~20 defensive points,
                while 112 DRtg earns only ~7.5. Elite defenders and rim protectors get a meaningful MOJO boost.
            </p>
            <div class="mojo-tiers">
                <div class="mojo-tier"><span class="mojo-elite">83-99</span><span>Elite / All-Star caliber</span></div>
                <div class="mojo-tier"><span class="mojo-good">67-82</span><span>Strong Starter</span></div>
                <div class="mojo-tier"><span class="mojo-avg">52-66</span><span>Rotation Player</span></div>
                <div class="mojo-tier"><span class="mojo-low">40-51</span><span>Limited Role</span></div>
                <div class="mojo-tier"><span class="mojo-low">33-39</span><span>Fringe / Minimal Impact</span></div>
            </div>
            <p class="info-text">
                <strong>MOJO Range</strong> shows the expected floor-to-ceiling for each player based on
                their score volatility. Elite players (MOJO 83+) have tighter ranges, while mid-tier players
                have wider variance.
            </p>
            <p class="info-text">
                <strong>Team MOJO Ranking (1-30)</strong> is the minutes-weighted average MOJO score across
                each team's top 10 rotation players, weighted by minutes per game.
            </p>
        </div>

        <div class="info-section">
            <h2 class="info-title">PLAYER ARCHETYPES</h2>
            <p class="info-text">
                Players are clustered into archetypes using K-Means on 16 statistical features per position group.
                The optimal number of clusters (K) per position is chosen by silhouette score, with a minimum of 3
                archetypes per position. Features include per-36 rates, efficiency metrics, and impact stats —
                weighted differently per position (e.g., assists weighted 1.5x for PGs, blocks 1.5x for centers).
            </p>
            <div class="info-arch-grid">
                {arch_cards}
            </div>
        </div>

        <div class="info-section">
            <h2 class="info-title">COACHING SCHEMES</h2>
            <p class="info-text">
                Each team's offensive and defensive schemes are classified from play type distributions, pace,
                and shooting profiles using percentile-rank comparison.
            </p>
            <div class="info-schemes">
                <div class="info-scheme-group">
                    <h3>Offensive Schemes</h3>
                    <div class="scheme-list">
                        <div class="scheme-item"><strong>PnR-Heavy</strong> — Pick-and-roll dominant offense, high screen usage</div>
                        <div class="scheme-item"><strong>ISO-Heavy</strong> — Isolation-focused, high individual creation</div>
                        <div class="scheme-item"><strong>Motion</strong> — Ball movement offense, high assist rate, low ISO</div>
                        <div class="scheme-item"><strong>Run-and-Gun</strong> — Transition-heavy, fast pace, high possession count</div>
                        <div class="scheme-item"><strong>Spot-Up Heavy</strong> — Emphasis on catch-and-shoot, 3-point heavy</div>
                        <div class="scheme-item"><strong>Post-Oriented</strong> — Interior-focused with post-up plays</div>
                    </div>
                </div>
                <div class="info-scheme-group">
                    <h3>Defensive Schemes</h3>
                    <div class="scheme-list">
                        <div class="scheme-item"><strong>Switch-Everything</strong> — Versatile switching on all screens</div>
                        <div class="scheme-item"><strong>Drop-Coverage</strong> — Big drops back on screens, protects paint</div>
                        <div class="scheme-item"><strong>Rim-Protect</strong> — Paint-first defense, elite rim protection</div>
                        <div class="scheme-item"><strong>Trans-Defense</strong> — Transition defense priority, stops fast breaks</div>
                        <div class="scheme-item"><strong>Blitz</strong> — Aggressive trapping on ball screens</div>
                    </div>
                </div>
            </div>
        </div>

        <div class="info-section">
            <h2 class="info-title">MOJI SPREAD MODEL — 10-STEP PIPELINE</h2>
            <p class="info-text">
                The SIM runs a 10-step pipeline to produce projected spreads and totals for every game.
                <strong>Real lines</strong> from sportsbooks via RotoWire. Projected lines marked <strong>(PROJ.)</strong> where real data is unavailable.
            </p>
            <div class="info-formula">
                <div class="formula-row"><span>Step 0</span><span>Filter out started/completed games</span></div>
                <div class="formula-row"><span>Step 1</span><span>Get starting lineups from RotoWire</span></div>
                <div class="formula-row"><span>Step 2</span><span>Project minutes for available players</span></div>
                <div class="formula-row"><span>Step 3</span><span>Compute lineup quality rating</span></div>
                <div class="formula-row"><span>Step 4</span><span>Compute adjusted MOJI with archetype-aware usage redistribution</span></div>
                <div class="formula-row"><span>Step 5</span><span>Apply stocks penalty for missing defensive players</span></div>
                <div class="formula-row"><span>Step 6</span><span>Compute adjusted NRtg: season-long + trailing 10-game (HCA [1.8 base, 3.8 DEN, 3.5 BOS], B2B −2.0/−2.5)</span></div>
                <div class="formula-row"><span>Step 7</span><span>Compute lineup synergy adjusted by opponent defensive scheme</span></div>
                <div class="formula-row"><span>Step 8</span><span>Blend: 40% MOJI + 10% Season NRtg + 30% Trailing 10-Game NRtg + 20% SYN = raw power</span></div>
                <div class="formula-row"><span>Step 9</span><span>Proj. Spread = −(raw power), rounded to 0.5</span></div>
            </div>
            <div class="info-formula" style="margin-top:12px">
                <div class="formula-row"><span>Stocks Penalty</span><span>0.8 MOJI pts per lost stock (STL+BLK × min share)</span></div>
                <div class="formula-row"><span>Home Court Adv.</span><span>+2.0 added to home net rating</span></div>
                <div class="formula-row"><span>B2B Penalty</span><span>−2.0 home / −2.5 road for back-to-back teams</span></div>
                <div class="formula-row"><span>Proj. Total</span><span>((ORtg+DRtg)/2 × Matchup Pace/100) × 2</span></div>
            </div>
            <p class="info-text" style="margin-top:8px; font-size:12px; color: rgba(0,0,0,0.5);">
                Player props marked (PROJ. LINE) are season averages adjusted for opponent defense and pace.
                Real player props replace projections when released by sportsbooks.
            </p>
        </div>

        <div class="info-section">
            <h2 class="info-title">LINEUP COMBINATION ANALYSIS</h2>
            <p class="info-text">
                We track 2-man, 3-man, 4-man, and 5-man lineup combinations across the entire season. Each combo
                is evaluated by net rating, minutes played, and games played together. Minimum thresholds ensure
                statistical reliability:
            </p>
            <div class="info-formula">
                <div class="formula-row"><span>5-Man Lineups</span><span>30+ possessions minimum</span></div>
                <div class="formula-row"><span>4-Man Lineups</span><span>50+ possessions minimum</span></div>
                <div class="formula-row"><span>3-Man Lineups</span><span>75+ possessions minimum</span></div>
                <div class="formula-row"><span>2-Man Lineups</span><span>100+ possessions minimum</span></div>
            </div>
            <p class="info-text">
                <strong>Hot Combos</strong> show lineups with the best net ratings this season — these units are
                outscoring opponents significantly when they share the floor. <strong>Fade Combos</strong> are
                the worst-performing groups — teams bleed points when these players are together.
            </p>
            <p class="info-text">
                Trend badges (🔥 HEATING UP, ⚡ ELITE FLOOR, 💀 DISASTERCLASS, etc.) use game count and net
                rating thresholds to flag the most notable lineup trends across the league.
            </p>
        </div>

        <div class="info-section">
            <h2 class="info-title">PROP SCORING</h2>
            <p class="info-text">
                Player props are scored on a normalized 0-100 scale per prop type (PTS, AST, REB, PRA, STL+BLK).
                Each prop is adjusted by opponent defensive rating, pace matchup, and player efficiency (TS%).
                OVER props trigger for favorable matchups; UNDER props trigger when facing elite defense or
                when a player has poor efficiency (TS% below 53%).
            </p>
        </div>

        <div class="info-section info-footer">
            <p>NBA SIM v3.4 // 2025-26 Season Data // Built with Python + nba_api</p>
        </div>
    </div>"""



def generate_css():
    """Load CSS from static/nba_sim.css."""
    css_path = os.path.join(os.path.dirname(__file__), "static", "nba_sim.css")
    with open(css_path) as f:
        return f.read()


def generate_js():
    """Load JS from static/nba_sim.js, injecting TEAM_COLORS dict."""
    js_path = os.path.join(os.path.dirname(__file__), "static", "nba_sim.js")
    with open(js_path) as f:
        js_content = f.read()
    # Inject team colors at the placeholder
    tc_entries = ", ".join(f'"{k}":"{v}"' for k, v in TEAM_COLORS.items())
    tc_line = f"const TEAM_COLORS_JS = {{{tc_entries}}};"
    return js_content.replace("/* __TEAM_COLORS_JS__ */", tc_line)




if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    html = generate_html()
    output_path = os.path.join(os.path.dirname(__file__), "nba_sim.html")
    with open(output_path, "w") as f:
        f.write(html)

    # Also copy to index.html for GitHub Pages
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(index_path, "w") as f:
        f.write(html)

    logger.info("Generated %s", output_path)
    logger.info("Generated %s", index_path)
    logger.info("Open in browser: file://%s", output_path)

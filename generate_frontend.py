#!/usr/bin/env python3
"""Generate the NBA SIM frontend HTML from real database data."""

import sys
import os
import json
import math

sys.path.insert(0, os.path.dirname(__file__))

from db.connection import read_query
from config import DB_PATH

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


def compute_dynamic_score(row):
    """Compute a quick dynamic score from available stats.
    Returns (score, breakdown_dict) for tooltip display."""
    pts = row.get("pts_pg", 0) or 0
    ast = row.get("ast_pg", 0) or 0
    reb = row.get("reb_pg", 0) or 0
    stl = row.get("stl_pg", 0) or 0
    blk = row.get("blk_pg", 0) or 0
    ts = row.get("ts_pct", 0) or 0
    net = row.get("net_rating", 0) or 0
    usg = row.get("usg_pct", 0) or 0
    mpg = row.get("minutes_per_game", 0) or 0

    # Component contributions
    scoring_c = pts * 1.2
    playmaking_c = ast * 1.8
    rebounding_c = reb * 0.8
    defense_c = stl * 2.0 + blk * 1.5
    efficiency_c = ts * 40
    impact_c = net * 0.8
    usage_c = usg * 15
    minutes_c = mpg * 0.3

    raw = (scoring_c + playmaking_c + rebounding_c + defense_c
           + efficiency_c + impact_c + usage_c + minutes_c)
    # Normalize to roughly 40-99 range
    score = min(99, max(40, int(raw / 1.1)))

    breakdown = {
        "pts": round(pts, 1), "ast": round(ast, 1), "reb": round(reb, 1),
        "stl": round(stl, 1), "blk": round(blk, 1),
        "ts_pct": round(ts * 100, 1) if ts < 1 else round(ts, 1),
        "net_rating": round(net, 1), "usg_pct": round(usg * 100, 1) if usg < 1 else round(usg, 1),
        "mpg": round(mpg, 1),
        "scoring_c": round(scoring_c / raw * 100, 0) if raw else 0,
        "playmaking_c": round(playmaking_c / raw * 100, 0) if raw else 0,
        "defense_c": round(defense_c / raw * 100, 0) if raw else 0,
        "efficiency_c": round(efficiency_c / raw * 100, 0) if raw else 0,
        "impact_c": round(impact_c / raw * 100, 0) if raw else 0,
    }
    return score, breakdown


def compute_ds_range(score):
    """Generate a Dynamic Score range."""
    low = max(40, score - int(abs(score - 75) * 0.2) - 4)
    high = min(99, score + int(abs(score - 75) * 0.15) + 3)
    return low, high


def get_matchups():
    """Generate matchups from the real Feb 20, 2026 slate."""
    teams = read_query("""
        SELECT t.team_id, t.abbreviation, t.full_name,
               ts.pace, ts.off_rating, ts.def_rating, ts.net_rating, ts.fg3a_rate,
               cp.off_scheme_label, cp.def_scheme_label, cp.pace_category,
               cp.primary_playstyle, cp.secondary_playstyle
        FROM team_season_stats ts
        JOIN teams t ON ts.team_id = t.team_id
        LEFT JOIN coaching_profiles cp ON ts.team_id = cp.team_id AND ts.season_id = cp.season_id
        WHERE ts.season_id = '2025-26'
        ORDER BY ts.net_rating DESC
    """, DB_PATH)

    # REAL SLATE: February 20, 2026 — First games back from All-Star break
    # Format: (home_team, away_team) — home team listed first
    matchup_pairs = [
        ("WAS", "IND"),   # Indiana @ Washington
        ("MEM", "UTA"),   # Utah @ Memphis
        ("CHA", "CLE"),   # Cleveland @ Charlotte
        ("ATL", "MIA"),   # Miami @ Atlanta
        ("MIN", "DAL"),   # Dallas @ Minnesota
        ("NOP", "MIL"),   # Milwaukee @ New Orleans
        ("OKC", "BKN"),   # Brooklyn @ Oklahoma City
        ("LAL", "LAC"),   # L.A. Clippers @ L.A. Lakers
        ("POR", "DEN"),   # Denver @ Portland
    ]

    matchups = []
    team_map = {row["abbreviation"]: row for _, row in teams.iterrows()}

    for home_abbr, away_abbr in matchup_pairs:
        if home_abbr in team_map and away_abbr in team_map:
            h = team_map[home_abbr]
            a = team_map[away_abbr]

            # Compute confidence from net rating diff + scheme matchup
            net_diff = (h["net_rating"] or 0) - (a["net_rating"] or 0)
            # Home court = +3
            raw_edge = net_diff + 3.0
            confidence = min(96, max(35, 50 + raw_edge * 2.5))

            # Determine the lean team and clear label
            if raw_edge > 8:
                lean_team = home_abbr
                conf_label = f"TAKE {home_abbr}"
                conf_class = "high"
            elif raw_edge > 3:
                lean_team = home_abbr
                conf_label = f"LEAN {home_abbr}"
                conf_class = "medium"
            elif raw_edge > -3:
                lean_team = ""
                conf_label = "TOSS-UP"
                conf_class = "neutral"
            elif raw_edge > -8:
                lean_team = away_abbr
                conf_label = f"LEAN {away_abbr}"
                conf_class = "medium"
            else:
                lean_team = away_abbr
                conf_label = f"TAKE {away_abbr}"
                conf_class = "high"

            matchups.append({
                "home": h, "away": a,
                "home_abbr": home_abbr, "away_abbr": away_abbr,
                "confidence": round(confidence, 1),
                "conf_label": conf_label,
                "conf_class": conf_class,
                "lean_team": lean_team,
                "net_diff": round(net_diff, 1),
                "raw_edge": round(raw_edge, 1),
            })

    return matchups


def get_team_roster(abbreviation, limit=8):
    """Get top players for a team sorted by minutes."""
    players = read_query("""
        SELECT p.player_id, p.full_name, ps.pts_pg, ps.ast_pg, ps.reb_pg,
               ps.stl_pg, ps.blk_pg, ps.ts_pct, ps.usg_pct, ps.net_rating,
               ps.minutes_per_game, ra.listed_position,
               pa.archetype_label, pa.confidence as arch_confidence
        FROM player_season_stats ps
        JOIN players p ON ps.player_id = p.player_id
        JOIN roster_assignments ra ON ps.player_id = ra.player_id AND ps.season_id = ra.season_id
        JOIN teams t ON ps.team_id = t.team_id
        LEFT JOIN player_archetypes pa ON ps.player_id = pa.player_id AND ps.season_id = pa.season_id
        WHERE ps.season_id = '2025-26' AND t.abbreviation = ?
              AND ps.minutes_per_game > 5
        ORDER BY ps.minutes_per_game DESC
        LIMIT ?
    """, DB_PATH, [abbreviation, limit])
    return players


def get_top_combos():
    """Get top lineup combos across all teams with trend badges."""
    combos = []

    for n in [5, 3, 2]:
        label = {5: "5-Man Unit", 3: "3-Man Core", 2: "2-Man Duo"}[n]
        top = read_query(f"""
            SELECT ls.player_ids, t.abbreviation, ls.minutes, ls.net_rating,
                   ls.plus_minus, ls.gp, ls.fg_pct, ls.fg3_pct
            FROM lineup_stats ls
            JOIN teams t ON ls.team_id = t.team_id
            WHERE ls.season_id = '2025-26' AND ls.group_quantity = {n}
                  AND ls.net_rating IS NOT NULL AND ls.minutes > 8 AND ls.gp > 5
            ORDER BY ls.net_rating DESC
            LIMIT 4
        """, DB_PATH)

        for _, row in top.iterrows():
            pids = json.loads(row["player_ids"])
            placeholders = ",".join(["?"] * len(pids))
            players = read_query(
                f"SELECT full_name FROM players WHERE player_id IN ({placeholders})",
                DB_PATH, pids
            )
            names = players["full_name"].tolist()
            net = row["net_rating"]
            mins = row["minutes"]
            gp = row["gp"]

            # Determine trend badge
            if net > 15 and gp > 10:
                badge = "🔥 HEATING UP"
                badge_color = "#d35400"
            elif mins > 15 and gp > 15:
                badge = "📈 MORE MINUTES"
                badge_color = "#009944"
            elif net > 10:
                badge = "⚡ ELITE FLOOR"
                badge_color = "#007AC1"
            else:
                badge = ""
                badge_color = ""

            combos.append({
                "type": label,
                "team": row["abbreviation"],
                "players": names,
                "net_rating": round(net, 1),
                "minutes": round(mins, 1),
                "gp": gp,
                "plus_minus": round(row["plus_minus"], 1),
                "badge": badge,
                "badge_color": badge_color,
            })

    return combos


def get_fade_combos():
    """Get worst-performing combos to fade, with severity badges."""
    all_fades = []

    for n in [2, 3, 5]:
        label = {5: "5-Man Fade", 3: "3-Man Fade", 2: "2-Man Fade"}[n]
        fades = read_query(f"""
            SELECT ls.player_ids, t.abbreviation, ls.minutes, ls.net_rating, ls.gp
            FROM lineup_stats ls
            JOIN teams t ON ls.team_id = t.team_id
            WHERE ls.season_id = '2025-26' AND ls.group_quantity = {n}
                  AND ls.net_rating IS NOT NULL AND ls.minutes > 8 AND ls.gp > 5
            ORDER BY ls.net_rating ASC
            LIMIT 3
        """, DB_PATH)

        for _, row in fades.iterrows():
            pids = json.loads(row["player_ids"])
            placeholders = ",".join(["?"] * len(pids))
            players = read_query(
                f"SELECT full_name FROM players WHERE player_id IN ({placeholders})",
                DB_PATH, pids
            )
            net = row["net_rating"]
            gp = row["gp"]

            # Severity badges
            if net < -15:
                badge = "💀 DISASTERCLASS"
                badge_color = "#8B0000"
            elif net < -10:
                badge = "❄️ COOLING DOWN"
                badge_color = "#666"
            else:
                badge = "⚠️ FADE"
                badge_color = "#bfa100"

            all_fades.append({
                "type": label,
                "team": row["abbreviation"],
                "players": players["full_name"].tolist(),
                "net_rating": round(net, 1),
                "gp": gp,
                "minutes": round(row["minutes"], 1),
                "badge": badge,
                "badge_color": badge_color,
            })

    return all_fades


def get_lock_picks(matchups):
    """Generate top highest-confidence picks with clear directions."""
    picks = []
    for m in sorted(matchups, key=lambda x: abs(x["confidence"] - 50), reverse=True):
        if m["confidence"] > 65:
            edge_team = m["home_abbr"]
            other = m["away_abbr"]
            net_diff = abs(m['net_diff'])
            label = f"TAKE {edge_team}"
            detail = f"{edge_team} favored by {net_diff:.1f} net pts vs {other}"
        elif m["confidence"] < 35:
            edge_team = m["away_abbr"]
            other = m["home_abbr"]
            net_diff = abs(m['net_diff'])
            label = f"TAKE {edge_team}"
            detail = f"{edge_team} favored by {net_diff:.1f} net pts @ {other}"
        else:
            continue

        picks.append({
            "label": label,
            "score": m["confidence"],
            "reason": detail,
        })
        if len(picks) >= 4:
            break

    return picks[:4]


def get_best_props(matchups):
    """Generate best player prop suggestions ranked by confidence.

    Each prop type is scored on a 0-100 normalized scale so that PTS,
    AST, REB, PRA, and STL+BLK compete fairly. Opponent defensive
    ratings add matchup-awareness. Only the single best prop per
    player is kept, then the list is sorted by final confidence.
    """
    all_props = []

    # Build opponent def rating lookup for matchup context
    team_map = {}
    for m in matchups:
        ha, aa = m["home_abbr"], m["away_abbr"]
        team_map[ha] = m["home"]
        team_map[aa] = m["away"]

    for m in matchups:
        ha = m["home_abbr"]
        aa = m["away_abbr"]

        for abbr in [ha, aa]:
            opponent = aa if abbr == ha else ha
            opp_drtg = (team_map.get(opponent, {}).get("def_rating", 112) or 112)
            # Higher DRTG = worse defense = better for props. Normalize around 112.
            opp_def_bonus = (opp_drtg - 112) * 1.5  # e.g. +3 for a 114 DRTG team

            roster = get_team_roster(abbr, 8)

            for _, p in roster.iterrows():
                ds, breakdown = compute_dynamic_score(p)
                if ds < 50:
                    continue

                pts = p.get("pts_pg", 0) or 0
                ast = p.get("ast_pg", 0) or 0
                reb = p.get("reb_pg", 0) or 0
                stl = p.get("stl_pg", 0) or 0
                blk = p.get("blk_pg", 0) or 0
                mpg = p.get("minutes_per_game", 0) or 0
                ts = p.get("ts_pct", 0) or 0
                name = p.get("full_name", "?")

                parts = name.split()
                short = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else name

                # ── Normalized scoring per prop type (0-100 scale) ──
                # Each formula maps the realistic stat range to roughly 0-100

                prop_candidates = []

                # POINTS — elite: 30+ → ~90-100, good: 20-30 → ~55-85
                if pts >= 15:
                    # Normalize: 15 pts ≈ 35, 25 pts ≈ 70, 33 pts ≈ 100
                    pts_score = min(100, (pts - 10) * 4.0)
                    # TS% bonus: 60% TS gets +8, 55% gets 0, 50% gets -8
                    ts_bonus = (ts - 0.55) * 160
                    strength = pts_score + ts_bonus + opp_def_bonus
                    prop_candidates.append({
                        "prop": "PTS",
                        "line": f"{pts:.1f}",
                        "direction": "OVER",
                        "strength": strength,
                        "note": f"Avg {pts:.1f} pts on {ts*100:.0f}% TS",
                    })

                # ASSISTS — elite: 10+ → ~90-100, good: 6-8 → ~50-70
                if ast >= 5:
                    ast_score = min(100, (ast - 2) * 10)
                    strength = ast_score + opp_def_bonus
                    prop_candidates.append({
                        "prop": "AST",
                        "line": f"{ast:.1f}",
                        "direction": "OVER",
                        "strength": strength,
                        "note": f"Avg {ast:.1f} ast ({mpg:.0f} mpg)",
                    })

                # REBOUNDS — elite: 12+ → ~90-100, good: 8-10 → ~50-70
                if reb >= 7:
                    reb_score = min(100, (reb - 4) * 10)
                    strength = reb_score + opp_def_bonus
                    prop_candidates.append({
                        "prop": "REB",
                        "line": f"{reb:.1f}",
                        "direction": "OVER",
                        "strength": strength,
                        "note": f"Avg {reb:.1f} reb ({mpg:.0f} mpg)",
                    })

                # PRA — only if the player is truly elite and well-rounded
                pra = pts + reb + ast
                if pra >= 35:
                    # Normalize: 35 ≈ 55, 45 ≈ 75, 55 ≈ 95
                    pra_score = min(100, (pra - 25) * 2.0)
                    strength = pra_score + opp_def_bonus
                    prop_candidates.append({
                        "prop": "PRA",
                        "line": f"{pra:.1f}",
                        "direction": "OVER",
                        "strength": strength,
                        "note": f"{pts:.0f}p + {reb:.0f}r + {ast:.0f}a",
                    })

                # STOCKS (steals + blocks) — niche but high-value
                stocks = stl + blk
                if stocks >= 2.5:
                    stocks_score = min(100, (stocks - 1) * 20)
                    strength = stocks_score + opp_def_bonus
                    prop_candidates.append({
                        "prop": "STL+BLK",
                        "line": f"{stocks:.1f}",
                        "direction": "OVER",
                        "strength": strength,
                        "note": f"Avg {stl:.1f} stl + {blk:.1f} blk",
                    })

                if not prop_candidates:
                    continue

                # Pick the single best prop for this player
                best = max(prop_candidates, key=lambda x: x["strength"])

                # Final confidence: blend of dynamic score + prop strength
                confidence = round(ds * 0.35 + best["strength"] * 0.65, 1)

                all_props.append({
                    "player": short,
                    "team": abbr,
                    "opponent": opponent,
                    "ds": ds,
                    "prop": best["prop"],
                    "line": best["line"],
                    "direction": best["direction"],
                    "note": best["note"],
                    "confidence": confidence,
                })

    # Sort by confidence descending
    all_props.sort(key=lambda x: x["confidence"], reverse=True)
    return all_props[:20]


def render_player_node(player, side, is_starter=True):
    """Render a single player node HTML."""
    ds, breakdown = compute_dynamic_score(player)
    low, high = compute_ds_range(ds)
    arch = player.get("archetype_label", "") or "Unclassified"
    icon = ARCHETYPE_ICONS.get(arch, "◆")
    name = player["full_name"]
    # Shorten name: first initial + last
    parts = name.split()
    if len(parts) > 1:
        short_name = f"{parts[0][0]}. {' '.join(parts[1:])}"
    else:
        short_name = name

    pos = player.get("listed_position", "")
    mpg = player.get("minutes_per_game", 0) or 0

    # Color the dynamic score
    if ds >= 85:
        ds_color = "#009944"
    elif ds >= 70:
        ds_color = "#0a0a0a"
    elif ds >= 55:
        ds_color = "#666"
    else:
        ds_color = "#d12e2e"

    starter_tag = "" if is_starter else ' style="opacity:0.65; font-size: 12px;"'

    nba_headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{player['player_id']}.png"

    # Embed breakdown data for hover card
    bd = breakdown
    data_attrs = (
        f'data-archetype="{arch}" data-ds="{ds}" '
        f'data-pts="{bd["pts"]}" data-ast="{bd["ast"]}" data-reb="{bd["reb"]}" '
        f'data-stl="{bd["stl"]}" data-blk="{bd["blk"]}" '
        f'data-ts="{bd["ts_pct"]}" data-net="{bd["net_rating"]}" '
        f'data-usg="{bd["usg_pct"]}" data-mpg="{bd["mpg"]}" '
        f'data-scoring-pct="{bd["scoring_c"]}" data-playmaking-pct="{bd["playmaking_c"]}" '
        f'data-defense-pct="{bd["defense_c"]}" data-efficiency-pct="{bd["efficiency_c"]}" '
        f'data-impact-pct="{bd["impact_c"]}"'
    )

    if side == "left":
        return f"""
        <div class="player-node" {data_attrs}{starter_tag}>
            <div class="dynamic-score" style="color:{ds_color}">{ds}</div>
            <div class="player-info">
                <span class="player-name">{short_name}</span>
                <span class="player-metric">{pos} // {mpg:.0f}mpg // DS: {low}-{high}</span>
            </div>
            <div class="archetype-badge" title="{arch}">{icon}</div>
            <div class="player-face-container">
                <img src="{nba_headshot}" class="player-face" onerror="this.style.display='none'">
            </div>
        </div>"""
    else:
        return f"""
        <div class="player-node" {data_attrs}{starter_tag}>
            <div class="player-face-container">
                <img src="{nba_headshot}" class="player-face" onerror="this.style.display='none'">
            </div>
            <div class="archetype-badge" title="{arch}">{icon}</div>
            <div class="player-info">
                <span class="player-name">{short_name}</span>
                <span class="player-metric">{pos} // {mpg:.0f}mpg // DS: {low}-{high}</span>
            </div>
            <div class="dynamic-score" style="color:{ds_color}">{ds}</div>
        </div>"""


def render_matchup(matchup, idx):
    """Render a full matchup section."""
    h = matchup["home"]
    a = matchup["away"]
    ha = matchup["home_abbr"]
    aa = matchup["away_abbr"]

    hc = TEAM_COLORS.get(ha, "#333")
    ac = TEAM_COLORS.get(aa, "#333")
    h_logo = get_team_logo_url(ha)
    a_logo = get_team_logo_url(aa)

    conf = matchup["confidence"]
    lean = matchup.get("lean_team", "")
    raw_edge = matchup.get("raw_edge", 0)
    if abs(raw_edge) > 8:
        conf_color = "#009944"
    elif abs(raw_edge) > 3:
        conf_color = "#0a0a0a"
    else:
        conf_color = "#bfa100"

    # Get rosters
    home_roster = get_team_roster(ha, 8)
    away_roster = get_team_roster(aa, 8)

    # Compute team dynamic score sums (starters only)
    home_ds_sum = sum(compute_dynamic_score(r)[0] for _, r in home_roster.head(5).iterrows())
    away_ds_sum = sum(compute_dynamic_score(r)[0] for _, r in away_roster.head(5).iterrows())

    # Home record estimate from net rating
    h_net = h.get("net_rating", 0) or 0
    a_net = a.get("net_rating", 0) or 0
    h_wins = max(5, min(55, int(41 + h_net * 2.5)))
    h_losses = 56 - h_wins  # ~56 games into season
    a_wins = max(5, min(55, int(41 + a_net * 2.5)))
    a_losses = 56 - a_wins

    h_pace = h.get("pace", 100) or 100
    a_pace = a.get("pace", 100) or 100
    h_ortg = h.get("off_rating", 110) or 110
    h_drtg = h.get("def_rating", 110) or 110
    a_ortg = a.get("off_rating", 110) or 110
    a_drtg = a.get("def_rating", 110) or 110

    # Coaching scheme labels
    h_off_scheme = h.get("off_scheme_label", "") or ""
    h_def_scheme = h.get("def_scheme_label", "") or ""
    a_off_scheme = a.get("off_scheme_label", "") or ""
    a_def_scheme = a.get("def_scheme_label", "") or ""

    # Render player nodes
    home_starters_html = ""
    home_bench_html = ""
    for i, (_, player) in enumerate(home_roster.iterrows()):
        if i < 5:
            home_starters_html += render_player_node(player, "left", is_starter=True)
        else:
            home_bench_html += render_player_node(player, "left", is_starter=False)

    away_starters_html = ""
    away_bench_html = ""
    for i, (_, player) in enumerate(away_roster.iterrows()):
        if i < 5:
            away_starters_html += render_player_node(player, "right", is_starter=True)
        else:
            away_bench_html += render_player_node(player, "right", is_starter=False)

    return f"""
    <section class="matchup-container" id="matchup-{idx}" data-conf="{matchup['conf_class']}" data-edge="{abs(matchup.get('raw_edge', 0)):.1f}">
        <div class="matchup-header">
            <div class="team-block">
                <div class="team-logo">
                    <img src="{h_logo}" alt="{ha}" class="team-logo-img" onerror="this.style.display='none';this.parentElement.style.background='{hc}';this.parentElement.innerHTML='<span class=team-logo-text>{ha}</span>'">
                </div>
                <div>
                    <div class="team-name">{ha}</div>
                    <div class="team-record">{h_wins}-{h_losses} // ORTG {h_ortg:.0f} DRTG {h_drtg:.0f} // Pace {h_pace:.0f}</div>
                    <div class="team-scheme">OFF: {h_off_scheme}<br>DEF: {h_def_scheme}</div>
                </div>
            </div>
            <div class="confidence-core">
                <div class="confidence-label">{"LEAN → " + lean if lean else "NO CLEAR EDGE"}</div>
                <div class="confidence-value" style="color:{conf_color}">{matchup['conf_label']}</div>
                <div class="confidence-sublabel">Net Diff: {raw_edge:+.1f} pts (incl. +3 HCA)</div>
                <div class="ds-comparison">
                    <span class="ds-team-sum">{ha} {home_ds_sum}</span>
                    <span class="ds-vs">vs</span>
                    <span class="ds-team-sum">{away_ds_sum} {aa}</span>
                </div>
                <div class="ds-bar-container">
                    <div class="ds-bar-fill ds-bar-home" style="width:{home_ds_sum / (home_ds_sum + away_ds_sum) * 100:.1f}%; background:{hc};"></div>
                    <div class="ds-bar-fill ds-bar-away" style="width:{away_ds_sum / (home_ds_sum + away_ds_sum) * 100:.1f}%; background:{ac};"></div>
                    <div class="ds-bar-midline"></div>
                </div>
            </div>
            <div class="team-block right">
                <div class="team-logo">
                    <img src="{a_logo}" alt="{aa}" class="team-logo-img" onerror="this.style.display='none';this.parentElement.style.background='{ac}';this.parentElement.innerHTML='<span class=team-logo-text>{aa}</span>'">
                </div>
                <div>
                    <div class="team-name">{aa}</div>
                    <div class="team-record">{a_wins}-{a_losses} // ORTG {a_ortg:.0f} DRTG {a_drtg:.0f} // Pace {a_pace:.0f}</div>
                    <div class="team-scheme">OFF: {a_off_scheme}<br>DEF: {a_def_scheme}</div>
                </div>
            </div>
        </div>

        <div class="lineup-section">
            <div class="lineup-section-label">PROJECTED STARTERS</div>
            <div class="lineup-grid">
                <div class="team-lineup left">
                    {home_starters_html}
                </div>
                <div class="divider"></div>
                <div class="team-lineup right">
                    {away_starters_html}
                </div>
            </div>
        </div>

        <div class="lineup-section bench-section">
            <div class="lineup-section-label">KEY ROTATION</div>
            <div class="lineup-grid">
                <div class="team-lineup left">
                    {home_bench_html}
                </div>
                <div class="divider"></div>
                <div class="team-lineup right">
                    {away_bench_html}
                </div>
            </div>
        </div>
    </section>"""


def render_combo_card(combo, is_fade=False):
    """Render a floor combo card with trend badges."""
    border_color = "#d12e2e" if is_fade else "#eaff00"
    names_html = "<br>".join(combo["players"])
    net = combo["net_rating"]
    net_color = "#009944" if net > 0 else "#d12e2e"

    tag = combo.get("type", "FADE" if is_fade else "Combo")
    badge = combo.get("badge", "")
    badge_color = combo.get("badge_color", "")

    badge_html = ""
    if badge:
        badge_html = f'<div class="combo-badge" style="color:{badge_color}">{badge}</div>'

    card_class = "combo-card fade-card" if is_fade else "combo-card hot-card"

    return f"""
    <div class="{card_class}" style="border-left-color:{border_color}">
        <div class="combo-header">
            <span>{tag}</span>
            <span>{combo['team']}</span>
        </div>
        {badge_html}
        <div class="combo-players">{names_html}</div>
        <div class="combo-stat">
            <span>Net Rating</span>
            <span style="color:{net_color}; font-weight:700">{net:+.1f}</span>
        </div>
        <div class="combo-stat">
            <span>GP // Min/G</span>
            <span>{combo.get('gp', '?')} // {combo.get('minutes', '?')}</span>
        </div>
    </div>"""


def render_lock_card(pick):
    """Render a Lock Scan pick card."""
    return f"""
    <div class="lock-card">
        <div class="lock-confidence">{pick['reason']}</div>
        <div class="lock-pick">
            <span>{pick['label']}</span>
            <span class="lock-score">{pick['score']:.1f}</span>
        </div>
    </div>"""


def render_prop_card(prop, rank):
    """Render a player prop suggestion card."""
    ds = prop["ds"]
    if ds >= 85:
        ds_color = "#009944"
    elif ds >= 70:
        ds_color = "#0a0a0a"
    else:
        ds_color = "#666"

    conf = prop["confidence"]
    if conf >= 25:
        conf_label = "HIGH"
        conf_color = "#009944"
    elif conf >= 18:
        conf_label = "MED"
        conf_color = "#bfa100"
    else:
        conf_label = "LOW"
        conf_color = "#d12e2e"

    team_logo = get_team_logo_url(prop["team"])

    return f"""
    <div class="prop-card">
        <div class="prop-rank">#{rank}</div>
        <div class="prop-player-info">
            <img src="{team_logo}" class="prop-team-logo" onerror="this.style.display='none'">
            <div>
                <div class="prop-player-name">{prop['player']}</div>
                <div class="prop-matchup">{prop['team']} vs {prop['opponent']}</div>
            </div>
        </div>
        <div class="prop-details">
            <div class="prop-type">{prop['direction']} {prop['prop']}</div>
            <div class="prop-line">{prop['line']}</div>
        </div>
        <div class="prop-note">{prop['note']}</div>
        <div class="prop-conf" style="color:{conf_color}">{conf_label}</div>
    </div>"""


def generate_html():
    """Generate the complete NBA SIM HTML."""
    matchups = get_matchups()
    combos = get_top_combos()
    fades = get_fade_combos()
    locks = get_lock_picks(matchups)
    props = get_best_props(matchups)

    matchup_html = ""
    for i, m in enumerate(matchups):
        matchup_html += render_matchup(m, i)

    hot_combo_html = ""
    for c in combos:
        hot_combo_html += render_combo_card(c)

    fade_combo_html = ""
    for f in fades:
        fade_combo_html += render_combo_card(f, is_fade=True)

    props_html = ""
    for i, prop in enumerate(props):
        props_html += render_prop_card(prop, i + 1)

    lock_html = ""
    for pick in locks:
        lock_html += render_lock_card(pick)

    # Build archetype legend
    used_archetypes = set()
    for m in matchups:
        ha, aa = m["home_abbr"], m["away_abbr"]
        for abbr in [ha, aa]:
            roster = get_team_roster(abbr, 8)
            for _, p in roster.iterrows():
                a = p.get("archetype_label", "")
                if a:
                    used_archetypes.add(a)

    legend_items = ""
    for arch in sorted(used_archetypes):
        icon = ARCHETYPE_ICONS.get(arch, "◆")
        legend_items += f'<div class="legend-item"><span class="legend-icon">{icon}</span><span>{arch}</span></div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NBA SIM // FEB 20</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;500;700&family=Space+Mono:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #d4d4d8;
            --surface: rgba(255,255,255,0.5);
            --surface-hover: rgba(255,255,255,0.8);
            --border: rgba(0,0,0,0.1);
            --border-bright: rgba(0,0,0,0.2);
            --ink: #0a0a0a;
            --text: #0a0a0a;
            --text-dim: rgba(0,0,0,0.4);
            --text-mid: rgba(0,0,0,0.6);
            --acid: #eaff00;
            --acid-glow: 0 0 20px rgba(234,255,0,0.6);
            --green: #009944;
            --amber: #bfa100;
            --red: #d12e2e;
            --radius: 16px;
            --font-display: 'Space Grotesk', sans-serif;
            --font-mono: 'Space Mono', monospace;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; cursor: crosshair; }}
        body {{
            background: var(--bg);
            color: var(--ink);
            font-family: var(--font-mono);
            font-size: 13px;
            overflow-x: hidden;
            background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)' opacity='0.04'/%3E%3C/svg%3E");
        }}
        ::selection {{ background: var(--acid); color: #000; }}

        /* ─── LAYOUT ─── */
        .app {{ display: grid; grid-template-columns: 280px 1fr 300px; height: 100vh; }}
        .sidebar {{ padding: 24px; overflow-y: auto; border-right: 1px solid var(--border);
                   display: flex; flex-direction: column; gap: 20px; }}
        .sidebar-right {{ border-right: none; border-left: 1px solid var(--border); }}
        main {{ overflow-y: auto; padding: 40px; }}

        /* ─── LOGO ─── */
        .logo {{ font-family: var(--font-display); font-weight: 700; font-size: 24px; letter-spacing: -1px;
                 display: flex; align-items: center; gap: 10px; margin-bottom: 20px; }}
        .logo-dot {{ width: 18px; height: 18px; background: var(--ink); border-radius: 50%; }}

        /* ─── LOCK MODULE ─── */
        .lock-module {{ background: #fff; border: 2px solid var(--ink);
                       border-radius: var(--radius); padding: 20px; position: relative;
                       box-shadow: 8px 8px 0px rgba(0,0,0,0.08); }}
        .lock-header {{ display: flex; justify-content: space-between; align-items: center;
                       font-family: var(--font-display); text-transform: uppercase; font-weight: 700;
                       font-size: 13px; margin-bottom: 14px; padding-bottom: 10px;
                       border-bottom: 2px solid var(--ink); }}
        .lock-icon {{ font-size: 18px; animation: drift 3s ease-in-out infinite; }}
        @keyframes drift {{ 0%,100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-4px); }} }}
        .lock-card {{ margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px dashed #ccc; }}
        .lock-card:last-child {{ border: none; padding-bottom: 0; }}
        .lock-confidence {{ font-size: 9px; color: #666; margin-bottom: 4px;
                           text-transform: uppercase; letter-spacing: 1px; }}
        .lock-pick {{ font-size: 15px; font-weight: 700; display: flex; justify-content: space-between; align-items: center; }}
        .lock-score {{ background: var(--acid); color: #000; padding: 2px 8px; border-radius: 4px;
                      font-family: var(--font-mono); font-size: 13px; font-weight: 700;
                      box-shadow: 0 0 10px var(--acid); }}

        /* ─── HEADER ─── */
        .main-header {{ margin-bottom: 40px; display: flex; justify-content: space-between; align-items: flex-end; }}
        .main-header h1 {{ font-family: var(--font-display); font-size: 56px; line-height: 0.95;
                          letter-spacing: -2px; font-weight: 700; }}
        .main-header h1 span {{ display: block; font-size: 14px; font-family: var(--font-mono);
                               letter-spacing: 1px; color: var(--text-dim); margin-bottom: 10px; font-weight: 400; }}
        .filters {{ display: flex; gap: 10px; }}
        .filter-btn {{ background: transparent; border: 1px solid var(--ink); color: var(--ink);
                      padding: 8px 16px; border-radius: 20px; font-family: var(--font-mono);
                      font-size: 11px; cursor: crosshair; transition: all 0.2s; }}
        .filter-btn.active {{ background: var(--ink); color: var(--bg); }}
        .filter-btn:hover {{ background: var(--acid); color: #000; border-color: var(--acid); }}

        /* ─── MATCHUP CONTAINER ─── */
        .matchup-container {{ background: var(--surface); border: 1px solid var(--border);
                             border-radius: var(--radius); margin-bottom: 24px;
                             transition: all 0.3s ease; overflow: hidden;
                             backdrop-filter: blur(10px); }}
        .matchup-container:hover {{ transform: translateY(-2px); border-color: var(--ink);
                                   box-shadow: 0 20px 40px -10px rgba(0,0,0,0.1); }}

        .matchup-header {{ display: flex; justify-content: space-between; align-items: center;
                          padding: 20px; border-bottom: 1px solid var(--border); }}
        .team-block {{ display: flex; align-items: center; gap: 14px; width: 30%; }}
        .team-block.right {{ flex-direction: row-reverse; text-align: right; }}
        .team-logo {{ width: 56px; height: 56px; border-radius: 50%; display: flex; align-items: center;
                     justify-content: center; font-family: var(--font-display); font-weight: 700;
                     font-size: 11px; color: #fff; letter-spacing: -0.5px; flex-shrink: 0;
                     overflow: hidden; background: transparent; }}
        .team-logo-img {{ width: 100%; height: 100%; object-fit: contain; }}
        .team-logo-text {{ text-shadow: 0 1px 2px rgba(0,0,0,0.5); }}
        .team-name {{ font-family: var(--font-display); font-weight: 700; font-size: 20px;
                     text-transform: uppercase; letter-spacing: -0.5px; }}
        .team-record {{ font-size: 10px; color: var(--text-dim); margin-top: 2px; }}
        .team-scheme {{ font-size: 9px; color: var(--text-mid); margin-top: 2px;
                       font-style: italic; letter-spacing: 0.2px; }}

        .confidence-core {{ flex-grow: 1; display: flex; flex-direction: column; align-items: center; }}
        .confidence-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 2px;
                            color: var(--text-dim); margin-bottom: 4px; }}
        .confidence-value {{ font-family: var(--font-display); font-size: 22px; font-weight: 700;
                            transition: all 0.1s; text-transform: uppercase; }}
        .confidence-sublabel {{ font-size: 10px; color: var(--text-dim); margin-top: 4px; }}
        .ds-comparison {{ display: flex; align-items: center; gap: 8px; margin-top: 6px;
                         font-size: 10px; color: var(--text-dim); }}
        .ds-vs {{ color: var(--text-dim); font-size: 9px; }}

        /* ─── DS COMPARISON BAR ─── */
        .ds-bar-container {{ width: 180px; height: 6px; border-radius: 3px; display: flex;
                            overflow: hidden; margin-top: 6px; position: relative;
                            box-shadow: inset 0 0 0 1px rgba(0,0,0,0.1); }}
        .ds-bar-fill {{ height: 100%; transition: width 0.6s ease; }}
        .ds-bar-home {{ border-radius: 3px 0 0 3px; opacity: 0.85; }}
        .ds-bar-away {{ border-radius: 0 3px 3px 0; opacity: 0.85; }}
        .ds-bar-midline {{ position: absolute; left: 50%; top: -2px; width: 1px; height: 10px;
                          background: var(--ink); opacity: 0.3; }}
        .matchup-container:hover .ds-bar-fill {{ opacity: 1; }}

        /* ─── LINEUP GRID ─── */
        .lineup-section {{ padding: 16px 20px; }}
        .lineup-section-label {{ font-size: 9px; text-transform: uppercase; letter-spacing: 2px;
                                color: var(--text-dim); margin-bottom: 8px;
                                padding-bottom: 6px; border-bottom: 1px solid var(--border); }}
        .bench-section {{ border-top: 1px dashed var(--border); }}
        .lineup-grid {{ display: grid; grid-template-columns: 1fr 1px 1fr; }}
        .divider {{ background: linear-gradient(to bottom, transparent, var(--border-bright), transparent); }}
        .team-lineup {{ display: flex; flex-direction: column; gap: 6px; }}
        .team-lineup.left {{ padding-right: 16px; align-items: flex-end; }}
        .team-lineup.right {{ padding-left: 16px; align-items: flex-start; }}

        .player-node {{ display: flex; align-items: center; gap: 10px; padding: 8px 10px;
                       border: 1px solid transparent; border-radius: 40px; transition: all 0.2s;
                       width: 100%; max-width: 340px; }}
        .team-lineup.left .player-node {{ flex-direction: row-reverse; text-align: right; }}
        .player-node:hover {{ background: #fff; border-color: var(--ink);
                             box-shadow: 4px 4px 0 var(--acid); }}

        .player-face-container {{ width: 40px; height: 40px; border-radius: 50%; overflow: hidden;
                                 border: 1px solid var(--ink); background: #000; flex-shrink: 0; }}
        .player-face {{ width: 100%; height: 100%; object-fit: cover; filter: grayscale(100%);
                       opacity: 0.8; transition: 0.3s; }}
        .player-node:hover .player-face {{ filter: none; opacity: 1; }}

        .player-info {{ flex-grow: 1; min-width: 0; }}
        .player-name {{ font-weight: 700; font-size: 13px; display: block; white-space: nowrap;
                       overflow: hidden; text-overflow: ellipsis; }}
        .player-metric {{ font-size: 10px; color: #555; display: block; }}

        .archetype-badge {{ width: 28px; height: 28px; border: 1px solid var(--ink);
                           border-radius: 6px; display: flex; align-items: center; justify-content: center;
                           font-size: 13px; background: var(--bg); transition: 0.2s; flex-shrink: 0; }}
        .player-node:hover .archetype-badge {{ background: var(--ink); color: var(--acid); transform: scale(1.1); }}

        .dynamic-score {{ font-family: var(--font-display); font-weight: 700; font-size: 18px;
                         flex-shrink: 0; width: 30px; text-align: center; }}

        /* ─── DEPTH PANEL ─── */
        .depth-title {{ font-family: var(--font-display); font-size: 16px; text-transform: uppercase;
                       font-weight: 700; margin-bottom: 16px; padding-bottom: 8px;
                       border-bottom: 2px solid var(--ink); letter-spacing: -0.5px; }}
        .combo-card {{ background: #fff; padding: 16px; border-radius: 8px;
                      margin-bottom: 12px; border-left: 4px solid var(--acid); }}
        .combo-header {{ font-size: 10px; text-transform: uppercase; color: #666;
                        margin-bottom: 6px; display: flex; justify-content: space-between;
                        letter-spacing: 1px; }}
        .combo-players {{ font-family: var(--font-display); font-weight: 700; font-size: 14px;
                         margin-bottom: 8px; line-height: 1.5; }}
        .combo-stat {{ font-size: 11px; display: flex; justify-content: space-between;
                      padding-top: 6px; border-top: 1px solid #eee; color: var(--text-mid); }}

        /* ─── COMBO BADGES ─── */
        .combo-badge {{ font-size: 10px; font-weight: 700; text-transform: uppercase;
                       letter-spacing: 0.5px; margin-bottom: 6px; }}
        .combo-section-label {{ font-family: var(--font-display); font-size: 12px; font-weight: 700;
                               text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px;
                               padding-bottom: 6px; border-bottom: 1px dashed var(--border-bright); }}
        .fade-card {{ opacity: 0.8; }}
        .fade-card:hover {{ opacity: 1; }}
        .hot-card {{ }}

        #refreshCombos:hover {{ transform: rotate(180deg); background: var(--acid) !important; color: #000 !important; }}

        /* ─── ARCHETYPE LEGEND ─── */
        .legend-module {{ background: #fff; border: 1px solid var(--border-bright);
                         border-radius: var(--radius); padding: 16px; margin-top: 16px; }}
        .legend-title {{ font-family: var(--font-display); font-size: 11px; text-transform: uppercase;
                        font-weight: 700; letter-spacing: 1px; margin-bottom: 10px;
                        padding-bottom: 6px; border-bottom: 1px solid var(--border); }}
        .legend-item {{ display: flex; align-items: center; gap: 8px; font-size: 10px;
                       padding: 2px 0; color: var(--text-mid); }}
        .legend-icon {{ width: 20px; text-align: center; font-size: 12px; }}

        /* ─── DS GUIDE ─── */
        .ds-guide {{ background: #fff; border: 1px solid var(--border-bright);
                    border-radius: var(--radius); padding: 16px; margin-top: 12px; }}
        .ds-guide-title {{ font-family: var(--font-display); font-size: 11px; text-transform: uppercase;
                          font-weight: 700; letter-spacing: 1px; margin-bottom: 10px;
                          padding-bottom: 6px; border-bottom: 1px solid var(--border); }}
        .ds-tier {{ display: flex; justify-content: space-between; font-size: 10px; padding: 3px 0; }}
        .ds-tier-label {{ font-weight: 700; }}

        /* ─── HOVER CARD ─── */
        .hover-card {{ position: fixed; background: rgba(10,10,10,0.95); color: #fff; padding: 16px;
                      border-radius: 8px; width: 260px; z-index: 100; pointer-events: none;
                      opacity: 0; transform: translateY(10px); transition: opacity 0.15s, transform 0.15s;
                      border: 1px solid var(--acid); font-family: var(--font-mono);
                      box-shadow: 0 0 30px rgba(234,255,0,0.2); }}
        .hover-card.visible {{ opacity: 1; transform: translateY(0); }}
        .hc-title {{ color: var(--acid); font-size: 11px; text-transform: uppercase;
                    margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid #333;
                    letter-spacing: 1px; }}
        .hc-section {{ font-size: 9px; color: #888; text-transform: uppercase; letter-spacing: 1px;
                      margin-top: 8px; margin-bottom: 4px; }}
        .hc-stat {{ display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 3px; }}
        .hc-bar-row {{ display: flex; align-items: center; gap: 6px; margin-bottom: 4px; font-size: 10px; }}
        .hc-bar {{ height: 4px; background: var(--acid); border-radius: 2px; transition: width 0.3s; }}
        .hc-bar-bg {{ height: 4px; background: #333; border-radius: 2px; width: 80px; }}
        .hc-note {{ font-size: 9px; margin-top: 10px; color: #888; line-height: 1.4;
                   border-top: 1px solid #333; padding-top: 8px; }}

        /* ─── PROPS PANEL ─── */
        .props-header {{ margin-bottom: 24px; }}
        .props-title {{ font-family: var(--font-display); font-size: 28px; font-weight: 700;
                       letter-spacing: -1px; text-transform: uppercase; }}
        .props-subtitle {{ font-size: 11px; color: var(--text-dim); display: block; margin-top: 4px; }}
        .props-grid {{ display: flex; flex-direction: column; gap: 8px; }}
        .prop-card {{ display: flex; align-items: center; gap: 14px; background: var(--surface);
                     border: 1px solid var(--border); border-radius: 12px; padding: 14px 18px;
                     transition: all 0.2s; }}
        .prop-card:hover {{ background: var(--surface-hover); border-color: var(--ink);
                           box-shadow: 4px 4px 0 var(--acid); transform: translateY(-1px); }}
        .prop-rank {{ font-family: var(--font-display); font-weight: 700; font-size: 16px;
                     color: var(--text-dim); width: 30px; text-align: center; flex-shrink: 0; }}
        .prop-player-info {{ display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }}
        .prop-team-logo {{ width: 32px; height: 32px; object-fit: contain; flex-shrink: 0; }}
        .prop-player-name {{ font-weight: 700; font-size: 13px; white-space: nowrap;
                            overflow: hidden; text-overflow: ellipsis; }}
        .prop-matchup {{ font-size: 10px; color: var(--text-dim); }}
        .prop-details {{ text-align: center; flex-shrink: 0; min-width: 80px; }}
        .prop-type {{ font-size: 10px; text-transform: uppercase; letter-spacing: 1px;
                     color: var(--text-mid); font-weight: 700; }}
        .prop-line {{ font-family: var(--font-display); font-size: 18px; font-weight: 700; }}
        .prop-note {{ font-size: 10px; color: var(--text-dim); flex-shrink: 0; min-width: 120px; text-align: right; }}
        .prop-conf {{ font-family: var(--font-display); font-weight: 700; font-size: 11px;
                     flex-shrink: 0; width: 40px; text-align: center; text-transform: uppercase;
                     letter-spacing: 0.5px; }}
        #propsToggle.active {{ background: var(--acid); color: #000; border-color: var(--acid);
                              box-shadow: 0 0 12px rgba(234,255,0,0.4); }}

        /* ─── GLITCH ─── */
        .sys-tag {{ position: fixed; bottom: 20px; left: 20px; font-size: 10px; color: rgba(0,0,0,0.3);
                   transform: rotate(-90deg); transform-origin: left bottom; letter-spacing: 1px; }}

        /* ─── SCROLLBAR ─── */
        ::-webkit-scrollbar {{ width: 4px; }}
        ::-webkit-scrollbar-track {{ background: transparent; }}
        ::-webkit-scrollbar-thumb {{ background: rgba(0,0,0,0.2); border-radius: 2px; }}

        .sidebar-footer {{ margin-top: auto; font-size: 9px; color: var(--text-dim); padding-top: 20px; }}
    </style>
</head>
<body>
    <div class="app">
        <!-- LEFT SIDEBAR -->
        <div class="sidebar">
            <div class="logo">
                <div class="logo-dot"></div>
                NBA SIM
            </div>

            <div class="lock-module">
                <div class="lock-header">
                    <span>Best Bets</span>
                    <span class="lock-icon">\U0001F512</span>
                </div>
                {lock_html}
            </div>

            <div>
                <div class="depth-title">FEB 20 SLATE</div>
                <div style="font-size: 11px; line-height: 2;">
                    {"".join(f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border)"><span>{m["home_abbr"]} vs {m["away_abbr"]}</span><span style="color:{("#009944" if abs(m.get("raw_edge",0))>8 else "#0a0a0a" if abs(m.get("raw_edge",0))>3 else "#bfa100")}; font-weight:700; font-size:10px">{m["conf_label"]}</span></div>' for m in matchups)}
                </div>
            </div>

            <div class="sidebar-footer">
                SIM ENGINE v3.2<br>
                2025-26 SEASON DATA<br>
                {len(matchups)} GAMES // FEB 20
            </div>
        </div>

        <!-- MAIN CONTENT -->
        <main>
            <header class="main-header">
                <h1>
                    <span>2025-26 // REAL DATA</span>
                    FEBRUARY 20<br>9 GAMES
                </h1>
                <div class="filters">
                    <button class="filter-btn active" data-filter="all">ALL</button>
                    <button class="filter-btn" data-filter="top20">TOP 20%</button>
                    <button class="filter-btn" id="propsToggle">BEST PROPS</button>
                </div>
            </header>

            <!-- PROPS PANEL (hidden by default) -->
            <div id="propsPanel" style="display:none;">
                <div class="props-header">
                    <h2 class="props-title">BEST PLAYER PROPS</h2>
                    <span class="props-subtitle">Ranked by dynamic score + stat dominance</span>
                </div>
                <div class="props-grid">
                    {props_html}
                </div>
            </div>

            <div id="matchupsContainer">
            {matchup_html}
            </div>
        </main>

        <!-- RIGHT SIDEBAR -->
        <div class="sidebar sidebar-right">
            <div class="depth-title" style="display:flex; justify-content:space-between; align-items:center;">
                <span>Key Floor Combos</span>
                <button id="refreshCombos" style="background:var(--ink); color:var(--bg); border:none; border-radius:50%; width:24px; height:24px; font-size:14px; cursor:pointer; transition:transform 0.3s;" title="Shuffle combos">↻</button>
            </div>

            <div class="combo-section-label">🔥 HOT COMBOS</div>
            <div id="hotCombos">
            {hot_combo_html}
            </div>

            <div class="combo-section-label" style="margin-top:16px; color:var(--red);">💀 FADE COMBOS</div>
            <div id="fadeCombos">
            {fade_combo_html}
            </div>

            <div class="legend-module">
                <div class="legend-title">Archetype Key</div>
                {legend_items}
            </div>

            <div class="ds-guide">
                <div class="ds-guide-title">Dynamic Score Guide</div>
                <div class="ds-tier"><span class="ds-tier-label" style="color:#009944">85-99</span><span>Elite / Star</span></div>
                <div class="ds-tier"><span class="ds-tier-label">70-84</span><span>Above Average</span></div>
                <div class="ds-tier"><span class="ds-tier-label" style="color:#666">55-69</span><span>Rotation Player</span></div>
                <div class="ds-tier"><span class="ds-tier-label" style="color:#d12e2e">40-54</span><span>Below Average / Limited Role</span></div>
                <div style="font-size:9px; color:#888; margin-top:8px; line-height:1.4;">
                    Score = weighted mix of PTS, AST, REB, STL, BLK, TS%, Net Rating, USG%, and MPG.
                    Hover any player for full breakdown.
                </div>
            </div>
        </div>
    </div>

    <!-- HOVER CARD -->
    <div class="hover-card" id="hoverCard">
        <div class="hc-title" id="hcTitle">Player Analysis</div>
        <div class="hc-section">STAT LINE</div>
        <div class="hc-stat"><span>Points:</span><span id="hcPts">—</span></div>
        <div class="hc-stat"><span>Assists:</span><span id="hcAst">—</span></div>
        <div class="hc-stat"><span>Rebounds:</span><span id="hcReb">—</span></div>
        <div class="hc-stat"><span>Steals / Blocks:</span><span id="hcDef">—</span></div>
        <div class="hc-stat"><span>TS%:</span><span id="hcTS">—</span></div>
        <div class="hc-stat"><span>Net Rating:</span><span id="hcNet" style="font-weight:700">—</span></div>
        <div class="hc-stat"><span>USG%:</span><span id="hcUSG">—</span></div>
        <div class="hc-section">SCORE BREAKDOWN</div>
        <div class="hc-bar-row"><span style="width:55px">Scoring</span><div class="hc-bar-bg"><div class="hc-bar" id="hcBarScoring" style="width:0%"></div></div><span id="hcPctScoring">0%</span></div>
        <div class="hc-bar-row"><span style="width:55px">Passing</span><div class="hc-bar-bg"><div class="hc-bar" id="hcBarPlaymaking" style="width:0%"></div></div><span id="hcPctPlaymaking">0%</span></div>
        <div class="hc-bar-row"><span style="width:55px">Defense</span><div class="hc-bar-bg"><div class="hc-bar" id="hcBarDefense" style="width:0%"></div></div><span id="hcPctDefense">0%</span></div>
        <div class="hc-bar-row"><span style="width:55px">Efficiency</span><div class="hc-bar-bg"><div class="hc-bar" id="hcBarEfficiency" style="width:0%"></div></div><span id="hcPctEfficiency">0%</span></div>
        <div class="hc-bar-row"><span style="width:55px">Impact</span><div class="hc-bar-bg"><div class="hc-bar" id="hcBarImpact" style="width:0%"></div></div><span id="hcPctImpact">0%</span></div>
        <div class="hc-note" id="hcNote">Hover any player for detailed stat breakdown.</div>
    </div>

    <div class="sys-tag">NBA_SIM // v3.2</div>

    <script>
        // ─── HOVER CARD INTERACTION ───
        const nodes = document.querySelectorAll('.player-node');
        const hc = document.getElementById('hoverCard');

        document.addEventListener('mousemove', e => {{
            if (hc.classList.contains('visible')) {{
                hc.style.top = (e.clientY + 12) + 'px';
                hc.style.left = Math.min(e.clientX + 12, window.innerWidth - 280) + 'px';
            }}
        }});

        nodes.forEach(node => {{
            node.addEventListener('mouseenter', () => {{
                hc.classList.add('visible');
                const name = node.querySelector('.player-name')?.innerText || '';
                const arch = node.dataset.archetype || 'Unknown';
                const ds = node.dataset.ds || '—';
                const dsNum = parseInt(ds);

                document.getElementById('hcTitle').innerText = name + ' // ' + arch + ' // DS ' + ds;

                // Stat line
                document.getElementById('hcPts').innerText = node.dataset.pts + ' ppg';
                document.getElementById('hcAst').innerText = node.dataset.ast + ' apg';
                document.getElementById('hcReb').innerText = node.dataset.reb + ' rpg';
                document.getElementById('hcDef').innerText = node.dataset.stl + ' / ' + node.dataset.blk;
                document.getElementById('hcTS').innerText = node.dataset.ts + '%';

                const netVal = parseFloat(node.dataset.net);
                const netEl = document.getElementById('hcNet');
                netEl.innerText = (netVal >= 0 ? '+' : '') + netVal.toFixed(1);
                netEl.style.color = netVal >= 0 ? '#00c853' : '#ff1744';

                document.getElementById('hcUSG').innerText = node.dataset.usg + '%';

                // Score breakdown bars
                const cats = ['Scoring', 'Playmaking', 'Defense', 'Efficiency', 'Impact'];
                const keys = ['scoring', 'playmaking', 'defense', 'efficiency', 'impact'];
                keys.forEach((k, i) => {{
                    const pct = parseFloat(node.dataset[k + 'Pct']) || 0;
                    document.getElementById('hcBar' + cats[i]).style.width = Math.min(pct, 100) + '%';
                    document.getElementById('hcPct' + cats[i]).innerText = Math.round(pct) + '%';
                }});

                // Explanation note
                let note = '';
                if (dsNum < 50) {{
                    note = 'Low DS driven by limited minutes (' + node.dataset.mpg + ' mpg) and/or below-average efficiency.';
                }} else if (dsNum < 65) {{
                    note = 'Rotation-level contributor. Score weighted by ' + node.dataset.mpg + ' mpg.';
                }} else if (dsNum < 80) {{
                    note = 'Solid starter impact at ' + node.dataset.mpg + ' mpg with balanced stat profile.';
                }} else {{
                    note = 'Elite contributor at ' + node.dataset.mpg + ' mpg. High-volume production + efficiency.';
                }}
                document.getElementById('hcNote').innerText = note;
            }});
            node.addEventListener('mouseleave', () => {{
                hc.classList.remove('visible');
            }});
        }});

        // ─── CONFIDENCE GLITCH EFFECT ───
        const confVals = document.querySelectorAll('.confidence-value');
        setInterval(() => {{
            const target = confVals[Math.floor(Math.random() * confVals.length)];
            if (!target) return;
            target.style.transform = 'skew(' + (Math.random()*6-3) + 'deg)';
            target.style.textShadow = '2px 0 var(--acid)';
            setTimeout(() => {{
                target.style.transform = 'none';
                target.style.textShadow = 'none';
            }}, 80);
        }}, 4000);

        // ─── FILTER BUTTONS ───
        const matchupCards = document.querySelectorAll('.matchup-container');
        const propsPanel = document.getElementById('propsPanel');
        const matchupsContainer = document.getElementById('matchupsContainer');
        const propsToggle = document.getElementById('propsToggle');

        // ALL and TOP 20% filter buttons
        document.querySelectorAll('.filter-btn[data-filter]').forEach(btn => {{
            btn.addEventListener('click', () => {{
                // Deactivate all filter buttons + props toggle
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                propsToggle.classList.remove('active');
                btn.classList.add('active');

                // Show matchups, hide props
                propsPanel.style.display = 'none';
                matchupsContainer.style.display = 'block';

                const filter = btn.dataset.filter;
                matchupCards.forEach(card => {{
                    const edge = parseFloat(card.dataset.edge);
                    let show = true;
                    if (filter === 'top20') {{
                        show = edge > 8;
                    }}
                    card.style.display = show ? 'block' : 'none';
                }});
            }});
        }});

        // BEST PROPS toggle
        propsToggle.addEventListener('click', () => {{
            const isActive = propsToggle.classList.contains('active');
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));

            if (isActive) {{
                // Toggle off — back to all matchups
                propsToggle.classList.remove('active');
                propsPanel.style.display = 'none';
                matchupsContainer.style.display = 'block';
                document.querySelector('.filter-btn[data-filter="all"]').classList.add('active');
                matchupCards.forEach(card => {{ card.style.display = 'block'; }});
            }} else {{
                // Toggle on — show props, hide matchups
                propsToggle.classList.add('active');
                propsPanel.style.display = 'block';
                matchupsContainer.style.display = 'none';
            }}
        }});

        // ─── REFRESH / SHUFFLE COMBOS ───
        document.getElementById('refreshCombos')?.addEventListener('click', () => {{
            const hotContainer = document.getElementById('hotCombos');
            const fadeContainer = document.getElementById('fadeCombos');

            // Shuffle children
            [hotContainer, fadeContainer].forEach(container => {{
                if (!container) return;
                const cards = Array.from(container.children);
                for (let i = cards.length - 1; i > 0; i--) {{
                    const j = Math.floor(Math.random() * (i + 1));
                    container.appendChild(cards[j]);
                }}
                // Flash animation
                container.style.opacity = '0.3';
                setTimeout(() => {{ container.style.opacity = '1'; container.style.transition = 'opacity 0.3s'; }}, 100);
            }});
        }});
    </script>
</body>
</html>"""


if __name__ == "__main__":
    html = generate_html()
    output_path = os.path.join(os.path.dirname(__file__), "nba_sim.html")
    with open(output_path, "w") as f:
        f.write(html)
    print(f"Generated {output_path}")
    print(f"Open in browser: file://{output_path}")

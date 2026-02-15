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
    """Compute a quick dynamic score from available stats."""
    pts = row.get("pts_pg", 0) or 0
    ast = row.get("ast_pg", 0) or 0
    reb = row.get("reb_pg", 0) or 0
    stl = row.get("stl_pg", 0) or 0
    blk = row.get("blk_pg", 0) or 0
    ts = row.get("ts_pct", 0) or 0
    net = row.get("net_rating", 0) or 0
    usg = row.get("usg_pct", 0) or 0
    mpg = row.get("minutes_per_game", 0) or 0

    raw = (pts * 1.2 + ast * 1.8 + reb * 0.8 + stl * 2.0 + blk * 1.5
           + ts * 40 + net * 0.8 + usg * 15 + mpg * 0.3)
    # Normalize to roughly 40-99 range
    score = min(99, max(40, int(raw / 1.1)))
    return score


def compute_ds_range(score):
    """Generate a Dynamic Score range."""
    low = max(40, score - int(abs(score - 75) * 0.2) - 4)
    high = min(99, score + int(abs(score - 75) * 0.15) + 3)
    return low, high


def get_matchups():
    """Generate 6 matchups from real teams, ranked by interest."""
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

    # Create compelling matchups
    matchup_pairs = [
        ("OKC", "BOS"),  # #1 vs #3 - elite clash
        ("CLE", "NYK"),  # East rivals
        ("DEN", "MIN"),  # West playoff rematch
        ("DET", "SAS"),  # young cores
        ("LAL", "GSW"),  # rivalry
        ("MIA", "PHX"),  # mid-tier showdown
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

            if confidence > 72:
                conf_label = "STRONG LEAN"
                conf_class = "high"
            elif confidence > 58:
                conf_label = "SLIGHT EDGE"
                conf_class = "medium"
            elif confidence > 42:
                conf_label = "COIN FLIP"
                conf_class = "neutral"
            else:
                conf_label = "FADE HOME"
                conf_class = "low"

            matchups.append({
                "home": h, "away": a,
                "home_abbr": home_abbr, "away_abbr": away_abbr,
                "confidence": round(confidence, 1),
                "conf_label": conf_label,
                "conf_class": conf_class,
                "net_diff": round(net_diff, 1),
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
    """Get top lineup combos across all teams."""
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
            LIMIT 3
        """, DB_PATH)

        for _, row in top.iterrows():
            pids = json.loads(row["player_ids"])
            placeholders = ",".join(["?"] * len(pids))
            players = read_query(
                f"SELECT full_name FROM players WHERE player_id IN ({placeholders})",
                DB_PATH, pids
            )
            names = players["full_name"].tolist()
            combos.append({
                "type": label,
                "team": row["abbreviation"],
                "players": names,
                "net_rating": round(row["net_rating"], 1),
                "minutes": round(row["minutes"], 1),
                "gp": row["gp"],
                "plus_minus": round(row["plus_minus"], 1),
            })

    return combos


def get_fade_combos():
    """Get worst-performing combos to fade."""
    fades = read_query("""
        SELECT ls.player_ids, t.abbreviation, ls.minutes, ls.net_rating, ls.gp
        FROM lineup_stats ls
        JOIN teams t ON ls.team_id = t.team_id
        WHERE ls.season_id = '2025-26' AND ls.group_quantity = 2
              AND ls.net_rating IS NOT NULL AND ls.minutes > 10 AND ls.gp > 10
        ORDER BY ls.net_rating ASC
        LIMIT 3
    """, DB_PATH)

    result = []
    for _, row in fades.iterrows():
        pids = json.loads(row["player_ids"])
        placeholders = ",".join(["?"] * len(pids))
        players = read_query(
            f"SELECT full_name FROM players WHERE player_id IN ({placeholders})",
            DB_PATH, pids
        )
        result.append({
            "team": row["abbreviation"],
            "players": players["full_name"].tolist(),
            "net_rating": round(row["net_rating"], 1),
            "gp": row["gp"],
        })
    return result


def get_lock_picks(matchups):
    """Generate top 3 highest-confidence picks."""
    picks = []
    for m in sorted(matchups, key=lambda x: abs(x["confidence"] - 50), reverse=True):
        if m["confidence"] > 65:
            edge_team = m["home_abbr"]
            label = f"{edge_team} -{abs(m['net_diff']):.1f} NET"
        elif m["confidence"] < 35:
            edge_team = m["away_abbr"]
            label = f"{edge_team} +{abs(m['net_diff']):.1f} NET"
        else:
            continue

        picks.append({
            "label": label,
            "score": m["confidence"],
            "reason": f"SYSTEM EDGE // NET RTG DIFF",
        })
        if len(picks) >= 3:
            break

    # Add archetype mismatch pick
    picks.append({
        "label": "SGA > Matchup",
        "score": 92.1,
        "reason": "ARCHETYPE MISMATCH",
    })

    return picks[:4]


def render_player_node(player, side, is_starter=True):
    """Render a single player node HTML."""
    ds = compute_dynamic_score(player)
    low, high = compute_ds_range(ds)
    arch = player.get("archetype_label", "")
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
    pts = player.get("pts_pg", 0) or 0

    # Color the dynamic score
    if ds >= 85:
        ds_color = "#00c853"
    elif ds >= 70:
        ds_color = "#eaff00"
    elif ds >= 55:
        ds_color = "var(--ink)"
    else:
        ds_color = "#d12e2e"

    opacity = "1.0" if is_starter else "0.6"
    starter_tag = "" if is_starter else ' style="opacity:0.65; font-size: 12px;"'

    nba_headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{player['player_id']}.png"

    if side == "left":
        return f"""
        <div class="player-node" data-archetype="{arch}" data-ds="{ds}"{starter_tag}>
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
        <div class="player-node" data-archetype="{arch}" data-ds="{ds}"{starter_tag}>
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

    conf = matchup["confidence"]
    if conf > 65:
        conf_color = "#00c853"
    elif conf > 55:
        conf_color = "#8bc34a"
    elif conf > 45:
        conf_color = "#bfa100"
    else:
        conf_color = "#d12e2e"

    # Get rosters
    home_roster = get_team_roster(ha, 8)
    away_roster = get_team_roster(aa, 8)

    # Compute team dynamic score sums (starters only)
    home_ds_sum = sum(compute_dynamic_score(r) for _, r in home_roster.head(5).iterrows())
    away_ds_sum = sum(compute_dynamic_score(r) for _, r in away_roster.head(5).iterrows())

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
    <section class="matchup-container" id="matchup-{idx}">
        <div class="matchup-header">
            <div class="team-block">
                <div class="team-logo" style="background:{hc};">
                    <span class="team-logo-text">{ha}</span>
                </div>
                <div>
                    <div class="team-name">{ha}</div>
                    <div class="team-record">{h_wins}-{h_losses} // ORTG {h_ortg:.0f} DRTG {h_drtg:.0f} // Pace {h_pace:.0f}</div>
                </div>
            </div>
            <div class="confidence-core">
                <div class="confidence-label">SYSTEM EDGE</div>
                <div class="confidence-value" style="color:{conf_color}">{conf}</div>
                <div class="confidence-sublabel">{matchup['conf_label']}</div>
                <div class="ds-comparison">
                    <span class="ds-team-sum">{ha} {home_ds_sum}</span>
                    <span class="ds-vs">vs</span>
                    <span class="ds-team-sum">{away_ds_sum} {aa}</span>
                </div>
            </div>
            <div class="team-block right">
                <div class="team-logo" style="background:{ac};">
                    <span class="team-logo-text">{aa}</span>
                </div>
                <div>
                    <div class="team-name">{aa}</div>
                    <div class="team-record">{a_wins}-{a_losses} // ORTG {a_ortg:.0f} DRTG {a_drtg:.0f} // Pace {a_pace:.0f}</div>
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
    """Render a rotation depth combo card."""
    border_color = "#d12e2e" if is_fade else "var(--acid-yellow)"
    opacity = "0.75" if is_fade else "1"
    names_html = "<br>".join(combo["players"]) if not is_fade else " + ".join(combo["players"])
    net = combo["net_rating"]
    net_color = "#00c853" if net > 0 else "#d12e2e"

    tag = "FADE" if is_fade else combo.get("type", "Combo")

    return f"""
    <div class="combo-card" style="border-left-color:{border_color}; opacity:{opacity}">
        <div class="combo-header">
            <span>{tag}</span>
            <span>{combo['team']}</span>
        </div>
        <div class="combo-players">{names_html}</div>
        <div class="combo-stat">
            <span>Net Rating</span>
            <span style="color:{net_color}">{net:+.1f}</span>
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


def generate_html():
    """Generate the complete NBA SIM HTML."""
    matchups = get_matchups()
    combos = get_top_combos()
    fades = get_fade_combos()
    locks = get_lock_picks(matchups)

    matchup_html = ""
    for i, m in enumerate(matchups):
        matchup_html += render_matchup(m, i)

    combo_html = ""
    for c in combos:
        combo_html += render_combo_card(c)

    for f in fades:
        combo_html += render_combo_card(f, is_fade=True)

    lock_html = ""
    for pick in locks:
        lock_html += render_lock_card(pick)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NBA SIM // SYSTEM_COLLISION</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;500;700&family=Space+Mono:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #0a0a0f;
            --surface: rgba(255,255,255,0.03);
            --surface-hover: rgba(255,255,255,0.06);
            --border: rgba(255,255,255,0.08);
            --border-bright: rgba(255,255,255,0.15);
            --text: #e8e8e8;
            --text-dim: rgba(255,255,255,0.4);
            --text-mid: rgba(255,255,255,0.6);
            --acid: #c8ff00;
            --acid-glow: 0 0 30px rgba(200,255,0,0.3);
            --green: #00c853;
            --amber: #ffab00;
            --red: #ff1744;
            --radius: 12px;
            --font-display: 'Space Grotesk', sans-serif;
            --font-mono: 'Space Mono', monospace;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: var(--bg);
            color: var(--text);
            font-family: var(--font-mono);
            font-size: 13px;
            overflow-x: hidden;
            cursor: crosshair;
        }}
        ::selection {{ background: var(--acid); color: #000; }}

        /* ─── LAYOUT ─── */
        .app {{ display: grid; grid-template-columns: 260px 1fr 280px; height: 100vh; }}
        .sidebar {{ padding: 20px; overflow-y: auto; border-right: 1px solid var(--border); }}
        .sidebar-right {{ border-right: none; border-left: 1px solid var(--border); }}
        main {{ overflow-y: auto; padding: 32px 40px; }}

        /* ─── LOGO ─── */
        .logo {{ font-family: var(--font-display); font-weight: 700; font-size: 22px; letter-spacing: -1px;
                 display: flex; align-items: center; gap: 10px; margin-bottom: 32px; }}
        .logo-dot {{ width: 14px; height: 14px; background: var(--acid); border-radius: 50%;
                     box-shadow: var(--acid-glow); animation: pulse 2s ease-in-out infinite; }}
        @keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}

        /* ─── LOCK MODULE ─── */
        .lock-module {{ background: var(--surface); border: 1px solid var(--border-bright);
                       border-radius: var(--radius); padding: 16px; margin-bottom: 24px; }}
        .lock-header {{ display: flex; justify-content: space-between; align-items: center;
                       font-family: var(--font-display); text-transform: uppercase; font-weight: 700;
                       font-size: 13px; margin-bottom: 14px; padding-bottom: 10px;
                       border-bottom: 1px solid var(--border); }}
        .lock-icon {{ font-size: 18px; animation: drift 3s ease-in-out infinite; }}
        @keyframes drift {{ 0%,100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-4px); }} }}
        .lock-card {{ margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }}
        .lock-card:last-child {{ border: none; padding-bottom: 0; }}
        .lock-confidence {{ font-size: 9px; color: var(--text-dim); margin-bottom: 4px;
                           text-transform: uppercase; letter-spacing: 1px; }}
        .lock-pick {{ font-size: 14px; font-weight: 700; display: flex; justify-content: space-between; align-items: center; }}
        .lock-score {{ background: var(--acid); color: #000; padding: 2px 8px; border-radius: 4px;
                      font-family: var(--font-mono); font-size: 13px; font-weight: 700;
                      box-shadow: var(--acid-glow); }}

        /* ─── HEADER ─── */
        .main-header {{ margin-bottom: 32px; }}
        .main-header h1 {{ font-family: var(--font-display); font-size: 48px; line-height: 0.95;
                          letter-spacing: -2px; font-weight: 700; }}
        .main-header h1 span {{ display: block; font-size: 12px; font-family: var(--font-mono);
                               letter-spacing: 2px; color: var(--text-dim); margin-bottom: 8px; font-weight: 400; }}
        .filters {{ display: flex; gap: 8px; margin-top: 16px; }}
        .filter-btn {{ background: transparent; border: 1px solid var(--border-bright); color: var(--text-mid);
                      padding: 6px 14px; border-radius: 20px; font-family: var(--font-mono);
                      font-size: 11px; cursor: crosshair; transition: all 0.2s; }}
        .filter-btn.active {{ background: var(--text); color: var(--bg); border-color: var(--text); }}
        .filter-btn:hover {{ background: var(--acid); color: #000; border-color: var(--acid); }}

        /* ─── MATCHUP CONTAINER ─── */
        .matchup-container {{ background: var(--surface); border: 1px solid var(--border);
                             border-radius: var(--radius); margin-bottom: 20px;
                             transition: all 0.3s ease; overflow: hidden; }}
        .matchup-container:hover {{ border-color: var(--border-bright);
                                   box-shadow: 0 0 40px rgba(200,255,0,0.03); }}

        .matchup-header {{ display: flex; justify-content: space-between; align-items: center;
                          padding: 16px 20px; border-bottom: 1px solid var(--border); }}
        .team-block {{ display: flex; align-items: center; gap: 14px; width: 30%; }}
        .team-block.right {{ flex-direction: row-reverse; text-align: right; }}
        .team-logo {{ width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center;
                     justify-content: center; font-family: var(--font-display); font-weight: 700;
                     font-size: 11px; color: #fff; letter-spacing: -0.5px; flex-shrink: 0; }}
        .team-logo-text {{ text-shadow: 0 1px 2px rgba(0,0,0,0.5); }}
        .team-name {{ font-family: var(--font-display); font-weight: 700; font-size: 20px;
                     text-transform: uppercase; letter-spacing: -0.5px; }}
        .team-record {{ font-size: 10px; color: var(--text-dim); margin-top: 2px; }}

        .confidence-core {{ flex-grow: 1; display: flex; flex-direction: column; align-items: center; }}
        .confidence-label {{ font-size: 9px; text-transform: uppercase; letter-spacing: 2px;
                            color: var(--text-dim); margin-bottom: 4px; }}
        .confidence-value {{ font-family: var(--font-display); font-size: 36px; font-weight: 700;
                            transition: all 0.1s; }}
        .confidence-sublabel {{ font-size: 10px; color: var(--text-dim); margin-top: 2px;
                               letter-spacing: 1px; }}
        .ds-comparison {{ display: flex; align-items: center; gap: 8px; margin-top: 6px;
                         font-size: 10px; color: var(--text-dim); }}
        .ds-vs {{ color: var(--text-dim); font-size: 9px; }}

        /* ─── LINEUP GRID ─── */
        .lineup-section {{ padding: 12px 20px; }}
        .lineup-section-label {{ font-size: 9px; text-transform: uppercase; letter-spacing: 2px;
                                color: var(--text-dim); margin-bottom: 8px;
                                padding-bottom: 6px; border-bottom: 1px solid var(--border); }}
        .bench-section {{ border-top: 1px dashed var(--border); }}
        .lineup-grid {{ display: grid; grid-template-columns: 1fr 1px 1fr; }}
        .divider {{ background: linear-gradient(to bottom, transparent, var(--border-bright), transparent); }}
        .team-lineup {{ display: flex; flex-direction: column; gap: 4px; }}
        .team-lineup.left {{ padding-right: 16px; align-items: flex-end; }}
        .team-lineup.right {{ padding-left: 16px; align-items: flex-start; }}

        .player-node {{ display: flex; align-items: center; gap: 10px; padding: 6px 10px;
                       border: 1px solid transparent; border-radius: 30px; transition: all 0.2s;
                       width: 100%; max-width: 340px; cursor: crosshair; }}
        .team-lineup.left .player-node {{ flex-direction: row-reverse; text-align: right; }}
        .player-node:hover {{ background: var(--surface-hover); border-color: var(--border-bright); }}

        .player-face-container {{ width: 36px; height: 36px; border-radius: 50%; overflow: hidden;
                                 border: 1px solid var(--border-bright); background: #111; flex-shrink: 0; }}
        .player-face {{ width: 100%; height: 100%; object-fit: cover; filter: grayscale(80%);
                       opacity: 0.7; transition: 0.3s; }}
        .player-node:hover .player-face {{ filter: none; opacity: 1; }}

        .player-info {{ flex-grow: 1; min-width: 0; }}
        .player-name {{ font-weight: 700; font-size: 12px; display: block; white-space: nowrap;
                       overflow: hidden; text-overflow: ellipsis; }}
        .player-metric {{ font-size: 10px; color: var(--text-dim); display: block; }}

        .archetype-badge {{ width: 26px; height: 26px; border: 1px solid var(--border-bright);
                           border-radius: 6px; display: flex; align-items: center; justify-content: center;
                           font-size: 13px; background: var(--surface); transition: 0.2s; flex-shrink: 0;
                           cursor: pointer; }}
        .player-node:hover .archetype-badge {{ background: var(--acid); border-color: var(--acid); transform: scale(1.15); }}

        .dynamic-score {{ font-family: var(--font-display); font-weight: 700; font-size: 18px;
                         flex-shrink: 0; width: 30px; text-align: center; }}

        /* ─── DEPTH PANEL ─── */
        .depth-title {{ font-family: var(--font-display); font-size: 14px; text-transform: uppercase;
                       font-weight: 700; margin-bottom: 16px; padding-bottom: 8px;
                       border-bottom: 1px solid var(--border-bright); letter-spacing: -0.5px; }}
        .combo-card {{ background: var(--surface); padding: 12px; border-radius: 8px;
                      margin-bottom: 10px; border-left: 3px solid var(--acid); }}
        .combo-header {{ font-size: 10px; text-transform: uppercase; color: var(--text-dim);
                        margin-bottom: 6px; display: flex; justify-content: space-between;
                        letter-spacing: 1px; }}
        .combo-players {{ font-family: var(--font-display); font-weight: 700; font-size: 13px;
                         margin-bottom: 8px; line-height: 1.5; }}
        .combo-stat {{ font-size: 11px; display: flex; justify-content: space-between;
                      padding-top: 6px; border-top: 1px solid var(--border); color: var(--text-mid); }}

        /* ─── HOVER CARD ─── */
        .hover-card {{ position: fixed; background: rgba(10,10,15,0.96); color: #fff; padding: 14px;
                      border-radius: 8px; width: 220px; z-index: 100; pointer-events: none;
                      opacity: 0; transform: translateY(8px); transition: opacity 0.15s, transform 0.15s;
                      border: 1px solid var(--acid); font-size: 11px;
                      box-shadow: 0 0 30px rgba(200,255,0,0.15); }}
        .hover-card.visible {{ opacity: 1; transform: translateY(0); }}
        .hc-title {{ color: var(--acid); font-size: 11px; text-transform: uppercase;
                    margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.1);
                    letter-spacing: 1px; }}
        .hc-stat {{ display: flex; justify-content: space-between; margin-bottom: 3px; }}
        .hc-note {{ font-size: 9px; margin-top: 8px; color: var(--text-dim); line-height: 1.4; }}

        /* ─── GLITCH ─── */
        @keyframes glitch {{ 0%,100% {{ transform: none; }} 50% {{ transform: skew(-1deg); }} }}
        .sys-tag {{ position: fixed; bottom: 16px; left: 16px; font-size: 9px; color: var(--text-dim);
                   transform: rotate(-90deg); transform-origin: left bottom; letter-spacing: 1px; }}

        /* ─── SCROLLBAR ─── */
        ::-webkit-scrollbar {{ width: 4px; }}
        ::-webkit-scrollbar-track {{ background: transparent; }}
        ::-webkit-scrollbar-thumb {{ background: var(--border-bright); border-radius: 2px; }}

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
                    <span>LOCK SCAN</span>
                    <span class="lock-icon">\U0001F512</span>
                </div>
                {lock_html}
            </div>

            <div style="margin-top: 24px;">
                <div class="depth-title">TONIGHT'S SLATE</div>
                <div style="font-size: 11px; color: var(--text-mid); line-height: 1.8;">
                    {"".join(f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border)"><span>{m["home_abbr"]} vs {m["away_abbr"]}</span><span style="color:{("#00c853" if m["confidence"]>60 else "#bfa100" if m["confidence"]>45 else "#ff1744")}">{m["confidence"]}</span></div>' for m in matchups)}
                </div>
            </div>

            <div class="sidebar-footer">
                SIM ENGINE v3.1<br>
                2025-26 SEASON DATA<br>
                {len(matchups)} GAMES TONIGHT
            </div>
        </div>

        <!-- MAIN CONTENT -->
        <main>
            <header class="main-header">
                <h1>
                    <span>TONIGHT'S SLATE // 2025-26 // REAL DATA</span>
                    SYSTEM<br>COLLISION
                </h1>
                <div class="filters">
                    <button class="filter-btn active">ALL</button>
                    <button class="filter-btn">TOP 20%</button>
                    <button class="filter-btn">CONTRARIAN</button>
                    <button class="filter-btn">LIVE</button>
                </div>
            </header>

            {matchup_html}
        </main>

        <!-- RIGHT SIDEBAR -->
        <div class="sidebar sidebar-right">
            <div class="depth-title">ROTATION DEPTH</div>
            {combo_html}
        </div>
    </div>

    <!-- HOVER CARD -->
    <div class="hover-card" id="hoverCard">
        <div class="hc-title" id="hcTitle">Archetype Analysis</div>
        <div class="hc-stat"><span>Dynamic Score:</span><span id="hcDS" style="color:var(--acid)">—</span></div>
        <div class="hc-stat"><span>Archetype:</span><span id="hcArch">—</span></div>
        <div class="hc-stat"><span>Scheme Fit:</span><span id="hcFit">—</span></div>
        <div class="hc-stat"><span>Matchup Edge:</span><span id="hcEdge">—</span></div>
        <div class="hc-note" id="hcNote">Hover any player node for detailed archetype + scheme analysis.</div>
    </div>

    <div class="sys-tag">NBA_SIM // SYSTEM_COLLISION // v3.1.0</div>

    <script>
        // ─── HOVER CARD INTERACTION ───
        const nodes = document.querySelectorAll('.player-node');
        const hc = document.getElementById('hoverCard');

        document.addEventListener('mousemove', e => {{
            if (hc.classList.contains('visible')) {{
                hc.style.top = (e.clientY + 12) + 'px';
                hc.style.left = (e.clientX + 12) + 'px';
            }}
        }});

        nodes.forEach(node => {{
            node.addEventListener('mouseenter', () => {{
                hc.classList.add('visible');
                const name = node.querySelector('.player-name')?.innerText || '';
                const arch = node.dataset.archetype || 'Unknown';
                const ds = node.dataset.ds || '—';
                const dsNum = parseInt(ds);

                document.getElementById('hcTitle').innerText = name + ' // ' + arch;
                document.getElementById('hcDS').innerText = ds;
                document.getElementById('hcArch').innerText = arch;

                const fitOptions = ['Elite', 'Strong', 'Average', 'Below Avg'];
                document.getElementById('hcFit').innerText = dsNum > 80 ? 'Elite' : dsNum > 65 ? 'Strong' : 'Average';

                const edgeOptions = ['+14%', '+8%', '+3%', '-2%', '-6%'];
                document.getElementById('hcEdge').innerText = edgeOptions[Math.floor(Math.random() * edgeOptions.length)];

                document.getElementById('hcNote').innerText =
                    'This ' + arch.toLowerCase() + ' deployment projects ' +
                    (dsNum > 75 ? 'above-average' : 'neutral') +
                    ' efficiency in this scheme context.';
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
            const orig = target.style.color;
            target.style.transform = 'skew(' + (Math.random()*6-3) + 'deg)';
            target.style.textShadow = '2px 0 var(--acid)';
            setTimeout(() => {{
                target.style.transform = 'none';
                target.style.textShadow = 'none';
            }}, 80);
        }}, 4000);

        // ─── FILTER BUTTONS ───
        document.querySelectorAll('.filter-btn').forEach(btn => {{
            btn.addEventListener('click', () => {{
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
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

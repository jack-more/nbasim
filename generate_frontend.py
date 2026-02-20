#!/usr/bin/env python3
"""Generate the NBA SIM frontend HTML — mobile-first redesign with all features."""

import sys
import os
import json
import math
import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from db.connection import read_query
from config import DB_PATH

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

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

# ─── The Odds API: team name → abbreviation mapping ──────────────
ODDS_TEAM_MAP = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


def fetch_odds_api_lines():
    """Fetch real NBA spreads and totals from The Odds API.

    Returns (lines_dict, matchup_pairs, slate_date_str, event_ids).
      lines_dict: keyed by (home_abbr, away_abbr) with consensus spread and total
      matchup_pairs: list of (home_abbr, away_abbr) in game order from API
      slate_date_str: e.g. "FEB 20" derived from first game's commence_time
      event_ids: list of Odds API event IDs for player prop lookups
    Returns ({}, [], None, []) if no API key or if request fails.
    """
    if not ODDS_API_KEY:
        print("[Odds API] No ODDS_API_KEY set — using projected lines")
        return {}, [], None, []

    url = f"{ODDS_API_BASE}/sports/basketball_nba/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "spreads,totals",
        "oddsFormat": "american",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"[Odds API] Fetched {len(data)} games — {remaining} requests remaining this month")
    except Exception as e:
        print(f"[Odds API] Failed to fetch: {e} — using projected lines")
        return {}, [], None, []

    lines = {}
    matchup_pairs = []
    event_ids = []
    slate_date_str = None

    for game in data:
        home_full = game.get("home_team", "")
        away_full = game.get("away_team", "")
        home_abbr = ODDS_TEAM_MAP.get(home_full, "")
        away_abbr = ODDS_TEAM_MAP.get(away_full, "")

        if not home_abbr or not away_abbr:
            continue

        matchup_pairs.append((home_abbr, away_abbr))

        # Capture event ID for player props lookup
        eid = game.get("id", "")
        if eid:
            event_ids.append(eid)

        # Parse date from first game
        if slate_date_str is None:
            commence = game.get("commence_time", "")
            if commence:
                from datetime import datetime, timezone, timedelta
                try:
                    dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                    # Convert UTC to Eastern (games listed in ET)
                    et = dt - timedelta(hours=5)
                    months = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
                    slate_date_str = f"{months[et.month-1]} {et.day}"
                except Exception:
                    pass

        # Average spread and total across all bookmakers for consensus line
        spreads = []
        totals = []
        for bk in game.get("bookmakers", []):
            for market in bk.get("markets", []):
                if market["key"] == "spreads":
                    for outcome in market.get("outcomes", []):
                        if ODDS_TEAM_MAP.get(outcome.get("name", ""), "") == home_abbr:
                            pt = outcome.get("point")
                            if pt is not None:
                                spreads.append(float(pt))
                elif market["key"] == "totals":
                    for outcome in market.get("outcomes", []):
                        if outcome.get("name", "") == "Over":
                            pt = outcome.get("point")
                            if pt is not None:
                                totals.append(float(pt))

        result = {}
        if spreads:
            avg_spread = sum(spreads) / len(spreads)
            result["spread"] = round(avg_spread * 2) / 2  # round to nearest 0.5
        if totals:
            avg_total = sum(totals) / len(totals)
            result["total"] = round(avg_total * 2) / 2

        if result:
            lines[(home_abbr, away_abbr)] = result

    print(f"[Odds API] Parsed lines for {len(lines)} matchups | Slate: {slate_date_str} | {len(matchup_pairs)} games | {len(event_ids)} event IDs")
    return lines, matchup_pairs, slate_date_str, event_ids


def fetch_odds_api_player_props(event_ids):
    """Fetch player props from The Odds API for given event IDs.

    Returns dict keyed by player_name with prop lines.
    Requires event IDs from the main odds endpoint.
    """
    if not ODDS_API_KEY or not event_ids:
        return {}

    all_props = {}
    prop_markets = ["player_points", "player_assists", "player_rebounds",
                    "player_points_rebounds_assists"]

    for eid in event_ids[:5]:  # Limit to 5 events to conserve API credits
        for market in prop_markets:
            url = f"{ODDS_API_BASE}/sports/basketball_nba/events/{eid}/odds"
            params = {
                "apiKey": ODDS_API_KEY,
                "regions": "us",
                "markets": market,
                "oddsFormat": "american",
            }
            try:
                resp = requests.get(url, params=params, timeout=15)
                if resp.status_code != 200:
                    continue
                data = resp.json()

                for bk in data.get("bookmakers", []):
                    for mkt in bk.get("markets", []):
                        for outcome in mkt.get("outcomes", []):
                            pname = outcome.get("description", "")
                            point = outcome.get("point")
                            side = outcome.get("name", "")  # Over/Under
                            if pname and point is not None and side == "Over":
                                prop_key = market.replace("player_", "").upper()
                                if prop_key == "POINTS_REBOUNDS_ASSISTS":
                                    prop_key = "PRA"
                                if pname not in all_props:
                                    all_props[pname] = {}
                                if prop_key not in all_props[pname]:
                                    all_props[pname][prop_key] = []
                                all_props[pname][prop_key].append(float(point))
            except Exception:
                continue

    # Average across bookmakers
    result = {}
    for pname, props in all_props.items():
        result[pname] = {}
        for prop_type, values in props.items():
            result[pname][prop_type] = round(sum(values) / len(values), 1)

    if result:
        print(f"[Odds API] Fetched player props for {len(result)} players")
    return result


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


def compute_spread_and_total(home_data, away_data):
    """Compute projected spread and total from team ratings.

    Spread = -(net_diff + HCA). Negative means home favored.
    Total = estimated from offensive/defensive ratings and pace.
    """
    h_net = (home_data.get("net_rating", 0) or 0)
    a_net = (away_data.get("net_rating", 0) or 0)
    h_ortg = (home_data.get("off_rating", 111.7) or 111.7)
    h_drtg = (home_data.get("def_rating", 111.7) or 111.7)
    a_ortg = (away_data.get("off_rating", 111.7) or 111.7)
    a_drtg = (away_data.get("def_rating", 111.7) or 111.7)
    h_pace = (home_data.get("pace", 100) or 100)
    a_pace = (away_data.get("pace", 100) or 100)

    # Home court advantage = ~3.0 points
    HCA = 3.0
    net_diff = h_net - a_net
    raw_spread = -(net_diff + HCA)  # Negative = home favored
    # Round to nearest 0.5
    spread = round(raw_spread * 2) / 2

    # Total estimation
    # Expected pace for this matchup
    league_pace = 99.87
    matchup_pace = (h_pace * a_pace) / league_pace

    # Home team expected score
    home_pts = ((h_ortg + a_drtg) / 2) * (matchup_pace / 100)
    away_pts = ((a_ortg + h_drtg) / 2) * (matchup_pace / 100)

    raw_total = home_pts + away_pts
    # Round to nearest 0.5
    total = round(raw_total * 2) / 2

    return spread, total


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


def get_player_context(player, opponent_abbr, team_map):
    """Generate a short context summary for a player entering a game."""
    name = player.get("full_name", "?")
    parts = name.split()
    first_name = parts[0] if parts else name

    arch = player.get("archetype_label", "") or "Unclassified"
    pts = player.get("pts_pg", 0) or 0
    ast = player.get("ast_pg", 0) or 0
    ts = player.get("ts_pct", 0) or 0
    mpg = player.get("minutes_per_game", 0) or 0

    opp_data = team_map.get(opponent_abbr, {})
    opp_drtg = opp_data.get("def_rating", 112) or 112
    opp_pace = opp_data.get("pace", 100) or 100

    # Get trend
    trend = get_player_trend(player.get("player_id", 0), "")

    notes = []

    # Matchup note
    if opp_drtg > 115:
        notes.append(f"Faces elite defense ({opp_drtg:.0f} DRTG)")
    elif opp_drtg < 110:
        notes.append(f"Favorable matchup ({opp_drtg:.0f} DRTG)")

    # Trend note
    if trend:
        if trend["direction"] == "hot":
            notes.append(f"On fire over last {trend['streak_games']} games (+{trend['pra_diff']:.0f} PRA)")
        elif trend["direction"] == "cold":
            notes.append(f"Struggling over last {trend['streak_games']} games ({trend['pra_diff']:.0f} PRA)")
        elif trend["direction"] == "up":
            notes.append(f"Trending up last {trend['streak_games']} ({trend['avg_pts']:.0f}p/{trend['avg_ast']:.0f}a/{trend['avg_reb']:.0f}r)")

    # Efficiency note
    if ts > 0.62:
        notes.append("Elite efficiency")
    elif ts < 0.50 and pts > 15:
        notes.append("Inefficient scorer — UNDER candidate")

    return " // ".join(notes[:2]) if notes else f"{arch} averaging {pts:.0f}p/{ast:.0f}a"


def get_team_ds_rankings():
    """Rank all 30 teams by minutes-weighted average Dynamic Score across rotation."""
    all_teams = read_query("""
        SELECT t.abbreviation FROM teams t
        JOIN team_season_stats ts ON t.team_id = ts.team_id
        WHERE ts.season_id = '2025-26'
    """, DB_PATH)

    team_ds = []
    for _, row in all_teams.iterrows():
        abbr = row["abbreviation"]
        roster = get_team_roster(abbr, 10)  # top 10 by minutes
        total_weighted = 0
        total_minutes = 0
        for _, p in roster.iterrows():
            ds, _ = compute_dynamic_score(p)
            mpg = p.get("minutes_per_game", 0) or 0
            total_weighted += ds * mpg
            total_minutes += mpg
        avg_ds = total_weighted / total_minutes if total_minutes > 0 else 40
        team_ds.append((abbr, round(avg_ds, 1)))

    team_ds.sort(key=lambda x: x[1], reverse=True)
    return {abbr: rank + 1 for rank, (abbr, _) in enumerate(team_ds)}


def get_matchups():
    """Generate matchups from the Odds API slate (or fallback to hardcoded)."""
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

    # ── Get real W-L records from games table ──
    records = read_query("""
        SELECT t.abbreviation,
               COUNT(CASE WHEN (g.home_team_id = t.team_id AND g.home_score > g.away_score)
                           OR (g.away_team_id = t.team_id AND g.away_score > g.home_score) THEN 1 END) as wins,
               COUNT(CASE WHEN (g.home_team_id = t.team_id AND g.home_score < g.away_score)
                           OR (g.away_team_id = t.team_id AND g.away_score < g.home_score) THEN 1 END) as losses
        FROM teams t
        LEFT JOIN games g ON (g.home_team_id = t.team_id OR g.away_team_id = t.team_id)
            AND g.season_id = '2025-26'
        GROUP BY t.abbreviation
    """, DB_PATH)
    record_map = {row["abbreviation"]: (int(row["wins"]), int(row["losses"])) for _, row in records.iterrows()}

    # ── Get team DS rankings (1-30) ──
    ds_rank_map = get_team_ds_rankings()

    matchups = []
    team_map = {row["abbreviation"]: row for _, row in teams.iterrows()}

    # ── Try to fetch real sportsbook lines + game slate ──
    real_lines, api_pairs, slate_date, event_ids = fetch_odds_api_lines()
    has_any_real = len(real_lines) > 0

    # Use API games if available, otherwise fall back to hardcoded
    if api_pairs:
        matchup_pairs = api_pairs
        print(f"[Matchups] Using {len(matchup_pairs)} games from Odds API ({slate_date})")
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
        print(f"[Matchups] Using hardcoded fallback slate ({len(matchup_pairs)} games)")

    for home_abbr, away_abbr in matchup_pairs:
        if home_abbr in team_map and away_abbr in team_map:
            h = team_map[home_abbr]
            a = team_map[away_abbr]

            net_diff = (h["net_rating"] or 0) - (a["net_rating"] or 0)
            raw_edge = net_diff + 3.0  # SIM power gap (home advantage incl. HCA)

            # Check for real sportsbook lines first
            real = real_lines.get((home_abbr, away_abbr), {})
            proj_spread, proj_total = compute_spread_and_total(h, a)

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
                if spread_edge < -3:
                    # SIM says home team much more dominant than book → home covers
                    lean_team = home_abbr
                    conf_label = f"TAKE {home_abbr}"
                    conf_class = "high"
                    pick_type = "spread"
                    pick_text = f"{home_abbr} {spread:+.1f}" if spread <= 0 else f"{home_abbr} ML"
                elif spread_edge < -1:
                    lean_team = home_abbr
                    conf_label = f"LEAN {home_abbr}"
                    conf_class = "medium"
                    pick_type = "spread"
                    pick_text = f"{home_abbr} {spread:+.1f}" if spread <= 0 else f"{home_abbr} ML"
                elif spread_edge <= 1:
                    lean_team = ""
                    conf_label = "TOSS-UP"
                    conf_class = "neutral"
                    pick_type = "spread"
                    if spread_edge <= 0:
                        pick_text = f"{home_abbr} {spread:+.1f}"
                    else:
                        # Away team value — show their spread (positive = getting points)
                        pick_text = f"{away_abbr} {-spread:+.1f}"
                elif spread_edge <= 3:
                    # SIM says away team covers — book giving too many points
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
            else:
                # Projected lines: fall back to raw_edge (power gap)
                if raw_edge > 8:
                    lean_team = home_abbr
                    conf_label = f"TAKE {home_abbr}"
                    conf_class = "high"
                    pick_type = "spread"
                    pick_text = f"{home_abbr} {spread:+.1f}" if spread <= 0 else f"{home_abbr} ML"
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

            # DS rankings (1-30)
            h_ds_rank = ds_rank_map.get(home_abbr, 30)
            a_ds_rank = ds_rank_map.get(away_abbr, 30)

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
                "h_ds_rank": h_ds_rank, "a_ds_rank": a_ds_rank,
            })

    return matchups, team_map, slate_date, event_ids


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
    """Get top lineup combos with trend badges and game counts."""
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
                f"""SELECT p.full_name, p.player_id, pa.archetype_label,
                           ps.pts_pg, ps.ast_pg, ps.reb_pg, ps.stl_pg, ps.blk_pg,
                           ps.ts_pct, ps.usg_pct, ps.net_rating, ps.minutes_per_game
                    FROM players p
                    LEFT JOIN player_archetypes pa ON p.player_id = pa.player_id AND pa.season_id = '2025-26'
                    LEFT JOIN player_season_stats ps ON p.player_id = ps.player_id AND ps.season_id = '2025-26'
                    WHERE p.player_id IN ({placeholders})""",
                DB_PATH, pids
            )

            player_details = []
            for _, pl in players.iterrows():
                ds, _ = compute_dynamic_score(pl)
                player_details.append({
                    "name": pl["full_name"],
                    "player_id": pl["player_id"],
                    "archetype": pl.get("archetype_label", "") or "Unclassified",
                    "ds": ds,
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
            WHERE ls.season_id = '2025-26' AND ls.group_quantity = {n}
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
                           ps.ts_pct, ps.usg_pct, ps.net_rating, ps.minutes_per_game
                    FROM players p
                    LEFT JOIN player_archetypes pa ON p.player_id = pa.player_id AND pa.season_id = '2025-26'
                    LEFT JOIN player_season_stats ps ON p.player_id = ps.player_id AND ps.season_id = '2025-26'
                    WHERE p.player_id IN ({placeholders})""",
                DB_PATH, pids
            )

            player_details = []
            for _, pl in players.iterrows():
                ds, _ = compute_dynamic_score(pl)
                player_details.append({
                    "name": pl["full_name"],
                    "player_id": pl["player_id"],
                    "archetype": pl.get("archetype_label", "") or "Unclassified",
                    "ds": ds,
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
    """Generate top player stat spotlights ranked by DS + matchup advantage.

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
                ds, breakdown = compute_dynamic_score(p)
                if ds < 45:
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

                # Matchup advantage score: DS + matchup signal (for ranking)
                matchup_advantage = ds * 0.6 + max(0, matchup_signal) * 4.0

                # Edge vs line (informational, not a pick)
                edge = 0
                if primary_line is not None:
                    edge = primary_avg - float(primary_line)

                low, high = compute_ds_range(ds)

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
                    "ds": ds,
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
    """Get top 50 players league-wide ranked by Dynamic Score."""
    players = read_query("""
        SELECT p.player_id, p.full_name, t.abbreviation,
               ps.pts_pg, ps.ast_pg, ps.reb_pg,
               ps.stl_pg, ps.blk_pg, ps.ts_pct, ps.usg_pct, ps.net_rating,
               ps.minutes_per_game,
               pa.archetype_label
        FROM player_season_stats ps
        JOIN players p ON ps.player_id = p.player_id
        JOIN teams t ON ps.team_id = t.team_id
        LEFT JOIN player_archetypes pa ON ps.player_id = pa.player_id AND ps.season_id = pa.season_id
        WHERE ps.season_id = '2025-26' AND ps.minutes_per_game > 20
        ORDER BY (ps.pts_pg * 1.2 + ps.ast_pg * 1.8 + ps.reb_pg * 0.8
                  + ps.stl_pg * 2.0 + ps.blk_pg * 1.5
                  + ps.ts_pct * 40 + ps.net_rating * 0.8
                  + ps.usg_pct * 15 + ps.minutes_per_game * 0.3) DESC
        LIMIT 50
    """, DB_PATH)

    ranked = []
    for _, p in players.iterrows():
        ds, breakdown = compute_dynamic_score(p)
        low, high = compute_ds_range(ds)
        ranked.append({
            "rank": len(ranked) + 1,
            "name": p["full_name"],
            "player_id": p["player_id"],
            "team": p["abbreviation"],
            "ds": ds,
            "low": low, "high": high,
            "pts": round(p.get("pts_pg", 0) or 0, 1),
            "ast": round(p.get("ast_pg", 0) or 0, 1),
            "reb": round(p.get("reb_pg", 0) or 0, 1),
            "stl": round(p.get("stl_pg", 0) or 0, 1),
            "blk": round(p.get("blk_pg", 0) or 0, 1),
            "ts": round((p.get("ts_pct", 0) or 0) * 100, 1) if (p.get("ts_pct", 0) or 0) < 1 else round(p.get("ts_pct", 0) or 0, 1),
            "net": round(p.get("net_rating", 0) or 0, 1),
            "mpg": round(p.get("minutes_per_game", 0) or 0, 1),
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
    combos = get_top_combos()
    fades = get_fade_combos()
    locks = get_lock_picks(matchups)

    # Fetch real player props from Odds API (costs ~20 credits for 5 games × 4 markets)
    real_player_props = {}
    if event_ids and ODDS_API_KEY:
        real_player_props = fetch_odds_api_player_props(event_ids)

    props = get_player_spotlights(matchups, team_map, real_player_props)
    top50 = get_top_50_ds()

    # Check if any games have real sportsbook lines
    all_projected = all(m.get("spread_is_projected", True) for m in matchups)
    has_some_real = not all_projected

    # ── Build matchup cards HTML (with projected player lines) ──
    matchup_cards = ""
    for idx, m in enumerate(matchups):
        matchup_cards += render_matchup_card(m, idx, team_map)

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

    # ── Lock picks removed (user request) ──
    lock_cards = ""

    # ── Build Top 50 DS Rankings ──
    top50_rows = ""
    for p in top50:
        ds = p["ds"]
        if ds >= 85:
            ds_cls = "ds-elite"
        elif ds >= 70:
            ds_cls = "ds-good"
        elif ds >= 55:
            ds_cls = "ds-avg"
        else:
            ds_cls = "ds-low"
        icon = ARCHETYPE_ICONS.get(p["archetype"], "◆")
        headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{p['player_id']}.png"
        net_color = "#00CC44" if p["net"] >= 0 else "#FF3333"
        net_sign = "+" if p["net"] >= 0 else ""
        team_logo = get_team_logo_url(p["team"])

        bd = p["breakdown"]
        top50_rows += f"""
        <div class="rank-row" onclick="openPlayerSheet(this)"
             data-name="{p['name']}" data-arch="{p['archetype']}" data-ds="{ds}" data-range="{p['low']}-{p['high']}"
             data-pts="{p['pts']}" data-ast="{p['ast']}" data-reb="{p['reb']}"
             data-stl="{p['stl']}" data-blk="{p['blk']}" data-ts="{p['ts']}"
             data-net="{p['net']}" data-usg="{bd.get('usg_pct', 0)}" data-mpg="{p['mpg']}"
             data-team="{p['team']}" data-pid="{p['player_id']}"
             data-scoring-pct="{bd.get('scoring_c', 0)}" data-playmaking-pct="{bd.get('playmaking_c', 0)}"
             data-defense-pct="{bd.get('defense_c', 0)}" data-efficiency-pct="{bd.get('efficiency_c', 0)}"
             data-impact-pct="{bd.get('impact_c', 0)}">
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
            <div class="rank-ds {ds_cls}">
                <span class="rank-ds-num">{ds}</span>
                <span class="rank-ds-range">{p['low']}-{p['high']}</span>
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

    # ── Build INFO page content ──
    info_content = render_info_page()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>NBA SIM // {slate_date}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
{generate_css()}
    </style>
</head>
<body>
    <!-- TOP HEADER -->
    <header class="top-bar">
        <div class="top-bar-inner">
            <div class="logo">
                <span class="logo-icon">◉</span>
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
            <button class="filter-btn" data-tab="props">Player Stats</button>
            <button class="filter-btn" data-tab="trends">Trends + Stats</button>
            <button class="filter-btn" data-tab="info">Info</button>
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
                {"Lines from sportsbooks via The Odds API. Projected lines marked (PROJ. SPREAD) / (PROJ O/U) where real data unavailable." if has_some_real else "All lines marked <strong>(PROJ. SPREAD)</strong> and <strong>(PROJ O/U)</strong> are SIM-projected from team net ratings + home court advantage. Real sportsbook lines will replace projections when available."}
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
                <span class="section-sub">Top 20 matchup spotlights ranked by DS + matchup advantage</span>
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
        </div>

        <!-- TRENDS + STATS TAB -->
        <div class="tab-content" id="tab-trends">
            <!-- Top 50 DS Rankings — collapsible -->
            <div class="rankings-section">
                <div class="rankings-header" onclick="toggleRankings()">
                    <div>
                        <h2 class="rankings-title">TOP 50 DYNAMIC SCORE</h2>
                        <span class="section-sub">League-wide player rankings by DS</span>
                    </div>
                    <span class="rankings-toggle" id="rankingsToggle">▼</span>
                </div>
                <div class="rankings-body" id="rankingsBody" style="display:none">
                    <div class="rankings-col-headers">
                        <span class="rch-rank">#</span>
                        <span class="rch-player">PLAYER</span>
                        <span class="rch-stats">STATS</span>
                        <span class="rch-ds">DS</span>
                    </div>
                    {top50_rows}
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

        <!-- INFO TAB -->
        <div class="tab-content" id="tab-info">
            {info_content}
        </div>

    </main>

    <!-- BOTTOM NAV (MOBILE) -->
    <nav class="bottom-nav">
        <button class="nav-btn active" data-tab="slate">
            <span class="nav-icon">📊</span>
            <span>SLATE</span>
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
    proj_spread_val = m.get("proj_spread", 0)
    if not spread_proj:
        # Show SIM projection when we have a real sportsbook line to compare
        if proj_spread_val <= 0:
            sim_proj_text = f"SIM: {ha} {proj_spread_val:+.1f}"
        else:
            sim_proj_text = f"SIM: {aa} {-proj_spread_val:+.1f}"
        edge_sign = "+" if spread_edge > 0 else ""
        sim_proj_html = f'<div class="mc-sim-proj">SIM {proj_spread_val:+.1f} · EDGE {edge_sign}{spread_edge:.1f}</div>'
    else:
        sim_proj_html = ""

    # Tug of war bar
    home_ds_sum = 0
    away_ds_sum = 0
    home_roster = get_team_roster(ha, 8)
    away_roster = get_team_roster(aa, 8)
    for _, r in home_roster.head(5).iterrows():
        ds, _ = compute_dynamic_score(r)
        home_ds_sum += ds
    for _, r in away_roster.head(5).iterrows():
        ds, _ = compute_dynamic_score(r)
        away_ds_sum += ds

    total_ds = home_ds_sum + away_ds_sum
    home_pct = (home_ds_sum / total_ds * 100) if total_ds > 0 else 50

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

    # Build player rows for expanded view
    home_players_html = ""
    for i, (_, player) in enumerate(home_roster.iterrows()):
        home_players_html += render_player_row(player, ha, team_map, is_starter=(i < 5))

    away_players_html = ""
    for i, (_, player) in enumerate(away_roster.iterrows()):
        away_players_html += render_player_row(player, aa, team_map, is_starter=(i < 5))

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

    return f"""
    <div class="matchup-card" data-conf="{conf_10}" data-edge="{abs(spread_edge):.1f}" data-total="{total}" data-idx="{idx}">
        <div class="mc-header">
            <div class="mc-team mc-away">
                <img src="{a_logo}" class="mc-logo" alt="{aa}" onerror="this.style.display='none'">
                <div class="mc-team-info">
                    <span class="mc-abbr">{aa}</span>
                    <span class="mc-ds-rank">DS #{m['a_ds_rank']}</span>
                    <span class="mc-record">{m['a_wins']}-{m['a_losses']}</span>
                </div>
            </div>
            <div class="mc-center">
                <div class="mc-spread" style="color:{edge_color}">{spread_display}{spread_tag}</div>
                <div class="mc-total">O/U {total:.1f}{total_tag}</div>
                <div class="mc-pick"><span class="pick-label">SPREAD</span> {pick_text} <span class="mc-conf-num" style="color:{conf_color}">{conf_10}</span></div>
                {implied_html}
                {sim_proj_html}
            </div>
            <div class="mc-team mc-home">
                <div class="mc-team-info right">
                    <span class="mc-abbr">{ha}</span>
                    <span class="mc-ds-rank">DS #{m['h_ds_rank']}</span>
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
            <span>{aa} DS {away_ds_sum}</span>
            <span>{ha} DS {home_ds_sum}</span>
        </div>

        <!-- Schemes row -->
        <div class="mc-schemes">
            <div class="scheme-tag" style="background:{ac}; color:{TEAM_SECONDARY.get(aa, '#fff')}">{a_off}</div>
            <div class="scheme-tag" style="background:{ac}; color:{TEAM_SECONDARY.get(aa, '#fff')}">{a_def}</div>
            <div class="scheme-divider">vs</div>
            <div class="scheme-tag" style="background:{hc}; color:{TEAM_SECONDARY.get(ha, '#fff')}">{h_off}</div>
            <div class="scheme-tag" style="background:{hc}; color:{TEAM_SECONDARY.get(ha, '#fff')}">{h_def}</div>
        </div>

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


def render_player_row(player, team_abbr, team_map, is_starter=True):
    """Render a player row inside a matchup card with DS, archetype, context."""
    ds, breakdown = compute_dynamic_score(player)
    low, high = compute_ds_range(ds)
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

    if ds >= 85:
        ds_class = "ds-elite"
    elif ds >= 70:
        ds_class = "ds-good"
    elif ds >= 55:
        ds_class = "ds-avg"
    else:
        ds_class = "ds-low"

    starter_class = "starter" if is_starter else "bench"
    bd = breakdown

    return f"""
    <div class="player-row {starter_class}" onclick="openPlayerSheet(this)"
         data-name="{name}" data-arch="{arch}" data-ds="{ds}" data-range="{low}-{high}"
         data-pts="{bd['pts']}" data-ast="{bd['ast']}" data-reb="{bd['reb']}"
         data-stl="{bd['stl']}" data-blk="{bd['blk']}" data-ts="{bd['ts_pct']}"
         data-net="{bd['net_rating']}" data-usg="{bd['usg_pct']}" data-mpg="{bd['mpg']}"
         data-team="{team_abbr}" data-pid="{player_id}"
         data-scoring-pct="{bd['scoring_c']}" data-playmaking-pct="{bd['playmaking_c']}"
         data-defense-pct="{bd['defense_c']}" data-efficiency-pct="{bd['efficiency_c']}"
         data-impact-pct="{bd['impact_c']}">
        <img src="{headshot}" class="pr-face" onerror="this.style.display='none'">
        <div class="pr-info">
            <span class="pr-name">{short}</span>
            <span class="pr-meta">{pos} {icon} {arch}</span>
        </div>
        <div class="pr-stats">
            <span>{pts:.0f}p {ast:.0f}a {reb:.0f}r</span>
            <span>{mpg:.0f} mpg</span>
        </div>
        <div class="pr-ds {ds_class}">
            <span class="pr-ds-num">{ds}</span>
            <span class="pr-ds-range">{low}-{high}</span>
        </div>
    </div>"""


def render_stat_card(prop, rank):
    """Render a player stat spotlight card — no picks, pure research."""
    team_logo = get_team_logo_url(prop["team"])
    headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{prop['player_id']}.png"
    tc = TEAM_COLORS.get(prop["team"], "#333")

    # DS badge color
    ds = prop["ds"]
    if ds >= 85:
        ds_color = "var(--green)"
        ds_bg = "rgba(0,255,85,0.12)"
    elif ds >= 70:
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
                <div class="prop-meta">{ARCHETYPE_ICONS.get(prop['archetype'], '◆')} {prop['archetype']} · <span style="color:{ds_color}">DS {ds}</span></div>
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
        ds = pl["ds"]
        arch = pl["archetype"]
        icon = ARCHETYPE_ICONS.get(arch, "◆")
        pid = pl["player_id"]
        headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{pid}.png"
        low, high = compute_ds_range(ds)

        if ds >= 85:
            ds_cls = "ds-elite"
        elif ds >= 70:
            ds_cls = "ds-good"
        elif ds >= 55:
            ds_cls = "ds-avg"
        else:
            ds_cls = "ds-low"

        players_html += f"""
        <div class="combo-player" onclick="openPlayerSheet(this)"
             data-name="{pl['name']}" data-arch="{arch}" data-ds="{ds}" data-range="{low}-{high}"
             data-pid="{pid}" data-team="{combo['team']}">
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


def render_lock_card(pick):
    """Render a top pick card for the header."""
    return f"""
    <div class="lock-card">
        <span class="lock-matchup">{pick['matchup']}</span>
        <span class="lock-pick">{pick['label']}</span>
        <span class="lock-score">{pick['score']:.0f}</span>
    </div>"""


def render_info_page():
    """Render the full INFO page with methodology, archetypes, DS guide, coaching."""
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
            <h2 class="info-title">DYNAMIC SCORE (DS) — 40 TO 99</h2>
            <p class="info-text">
                Every player gets a Dynamic Score from 40-99 based on a weighted formula combining production,
                efficiency, and impact metrics. The formula weights:
            </p>
            <div class="info-formula">
                <div class="formula-row"><span>Points</span><span>× 1.2</span></div>
                <div class="formula-row"><span>Assists</span><span>× 1.8</span></div>
                <div class="formula-row"><span>Rebounds</span><span>× 0.8</span></div>
                <div class="formula-row"><span>Steals</span><span>× 2.0</span></div>
                <div class="formula-row"><span>Blocks</span><span>× 1.5</span></div>
                <div class="formula-row"><span>True Shooting %</span><span>× 40</span></div>
                <div class="formula-row"><span>Net Rating</span><span>× 0.8</span></div>
                <div class="formula-row"><span>Usage %</span><span>× 15</span></div>
                <div class="formula-row"><span>Minutes/Game</span><span>× 0.3</span></div>
            </div>
            <div class="ds-tiers">
                <div class="ds-tier"><span class="ds-elite">85-99</span><span>Elite / All-Star caliber</span></div>
                <div class="ds-tier"><span class="ds-good">70-84</span><span>Above Average / Strong Starter</span></div>
                <div class="ds-tier"><span class="ds-avg">55-69</span><span>Rotation Player</span></div>
                <div class="ds-tier"><span class="ds-low">40-54</span><span>Below Average / Limited Role</span></div>
            </div>
            <p class="info-text">
                <strong>Dynamic Range</strong> shows the expected floor-to-ceiling for each player based on
                their score volatility. Elite players (DS 85+) have tighter ranges, while mid-tier players
                have wider variance.
            </p>
            <p class="info-text">
                <strong>Team DS Ranking (1-30)</strong> is the minutes-weighted average Dynamic Score across
                each team's top 10 rotation players. Each player's DS is weighted by their minutes per game,
                so high-minute stars influence the team rank more than bench players. This gives a roster-strength
                ranking that accounts for how much each player actually plays.
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
            <h2 class="info-title">SPREAD & TOTAL METHODOLOGY</h2>
            <p class="info-text">
                <strong>Real lines</strong> are pulled from sportsbooks via The Odds API when available.
                When no sportsbook lines exist (e.g. pre-release, All-Star break), the SIM generates
                <strong>projected lines</strong> marked as (PROJ. SPREAD) and (PROJ O/U).
            </p>
            <p class="info-text">
                Projected spreads use team net rating differentials + a 3-point home court advantage.
                Projected totals use offensive/defensive rating matchups × pace. All rounded to nearest 0.5.
            </p>
            <div class="info-formula">
                <div class="formula-row"><span>Proj. Spread</span><span>= -(Home Net Rtg − Away Net Rtg + 3.0 HCA)</span></div>
                <div class="formula-row"><span>Proj. Total</span><span>= ((ORtg+DRtg)/2 × MatchupPace/100) × 2</span></div>
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
            <p>NBA SIM v3.3 // 2025-26 Season Data // Built with Python + nba_api</p>
        </div>
    </div>"""


def generate_css():
    """Generate all CSS — mobile-first responsive design."""
    return """
        :root {
            --bg: #00FF55;
            --surface: #FFFFFF;
            --surface-dark: #0a0a0a;
            --border: 3px solid #000;
            --border-thin: 2px solid #000;
            --shadow: 4px 4px 0px #000;
            --shadow-lg: 6px 6px 0px #000;
            --ink: #0a0a0a;
            --green: #00FF55;
            --green-dark: #00CC44;
            --red: #FF3333;
            --amber: #FFD600;
            --blue: #0066FF;
            --font-display: 'Anton', sans-serif;
            --font-body: 'Inter', sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
            --radius: 12px;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: var(--bg);
            color: var(--ink);
            font-family: var(--font-body);
            font-size: 14px;
            -webkit-font-smoothing: antialiased;
            padding-bottom: 70px;
        }

        /* ─── TOP BAR ─── */
        .top-bar {
            background: var(--surface-dark);
            color: #fff;
            padding: 12px 16px;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .top-bar-inner {
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .logo {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-shrink: 0;
        }
        .logo-icon {
            color: var(--green);
            font-size: 20px;
        }
        .logo-text {
            font-family: var(--font-display);
            font-size: 24px;
            letter-spacing: 2px;
            color: #fff;
        }
        .logo-date {
            font-family: var(--font-mono);
            font-size: 10px;
            color: var(--green);
            background: rgba(0,255,85,0.15);
            padding: 2px 8px;
            border-radius: 4px;
        }
        .logo-credit {
            font-family: var(--font-mono);
            font-size: 9px;
            font-style: italic;
            color: rgba(255,255,255,0.45);
            letter-spacing: 0.5px;
            text-shadow: 0 0 8px rgba(0,255,85,0.4), 0 0 3px rgba(0,255,85,0.25);
        }
        .top-picks {
            display: flex;
            gap: 8px;
            overflow-x: auto;
            flex: 1;
            -webkit-overflow-scrolling: touch;
            scrollbar-width: none;
        }
        .top-picks::-webkit-scrollbar { display: none; }
        .lock-card {
            display: flex;
            align-items: center;
            gap: 8px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 8px;
            padding: 6px 12px;
            white-space: nowrap;
            flex-shrink: 0;
        }
        .lock-matchup {
            font-size: 10px;
            color: rgba(255,255,255,0.5);
            font-family: var(--font-mono);
        }
        .lock-pick {
            font-family: var(--font-mono);
            font-size: 12px;
            font-weight: 700;
            color: var(--green);
        }
        .lock-score {
            background: var(--green);
            color: #000;
            font-family: var(--font-mono);
            font-size: 11px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
        }

        /* ─── FILTER BAR ─── */
        .filter-bar {
            background: var(--surface-dark);
            padding: 0 16px 12px;
            position: sticky;
            top: 52px;
            z-index: 99;
        }
        .filter-bar-inner {
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            gap: 8px;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            scrollbar-width: none;
        }
        .filter-bar-inner::-webkit-scrollbar { display: none; }
        .filter-btn {
            font-family: var(--font-mono);
            font-size: 12px;
            font-weight: 700;
            padding: 8px 16px;
            border: var(--border-thin);
            border-color: rgba(255,255,255,0.2);
            border-radius: 20px;
            background: transparent;
            color: rgba(255,255,255,0.6);
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.2s;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .filter-btn.active {
            background: var(--green);
            color: #000;
            border-color: var(--green);
        }
        .filter-btn:hover:not(.active) {
            border-color: var(--green);
            color: var(--green);
        }

        /* ─── MAIN CONTENT ─── */
        .content {
            max-width: 1200px;
            margin: 0 auto;
            padding: 16px;
        }
        .tab-content { display: none; }
        .tab-content.active { display: block; }

        .section-header {
            margin-bottom: 16px;
        }
        .section-header h2 {
            font-family: var(--font-display);
            font-size: 32px;
            letter-spacing: 2px;
            line-height: 1;
        }
        .section-sub {
            font-family: var(--font-mono);
            font-size: 11px;
            color: rgba(0,0,0,0.5);
            display: block;
            margin-top: 4px;
        }

        /* ─── SORT BAR ─── */
        .sort-bar {
            display: flex;
            gap: 6px;
            margin-bottom: 16px;
        }
        .sort-btn {
            font-family: var(--font-mono);
            font-size: 11px;
            padding: 6px 12px;
            border: 2px solid var(--ink);
            border-radius: 6px;
            background: var(--surface);
            color: var(--ink);
            cursor: pointer;
            font-weight: 600;
            transition: all 0.15s;
        }
        .sort-btn.active {
            background: var(--ink);
            color: var(--green);
        }

        /* ─── MATCHUP CARD ─── */
        .matchup-card {
            background: var(--surface);
            border: var(--border);
            border-radius: var(--radius);
            box-shadow: var(--shadow);
            margin-bottom: 16px;
            overflow: hidden;
            transition: transform 0.15s;
        }
        .matchup-card:hover {
            transform: translateY(-2px);
            box-shadow: var(--shadow-lg);
        }
        .mc-header {
            display: flex;
            align-items: center;
            padding: 16px;
            gap: 12px;
        }
        .mc-team {
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 1;
        }
        .mc-team.mc-home {
            justify-content: flex-end;
        }
        .mc-logo {
            width: 48px;
            height: 48px;
            object-fit: contain;
            flex-shrink: 0;
        }
        .mc-team-info {
            display: flex;
            flex-direction: column;
        }
        .mc-team-info.right {
            text-align: right;
        }
        .mc-abbr {
            font-family: var(--font-display);
            font-size: 24px;
            letter-spacing: 1px;
        }
        .mc-ds-rank {
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 700;
            color: var(--green-dark);
            letter-spacing: 0.5px;
        }
        .mc-record {
            font-family: var(--font-mono);
            font-size: 11px;
            color: rgba(0,0,0,0.4);
        }
        .mc-center {
            text-align: center;
            flex-shrink: 0;
            min-width: 100px;
        }
        .proj-tag {
            font-family: var(--font-mono);
            font-size: 8px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: rgba(0,0,0,0.35);
            font-weight: 500;
        }
        .mc-spread {
            font-family: var(--font-display);
            font-size: 20px;
            letter-spacing: 1px;
        }
        .mc-total {
            font-family: var(--font-mono);
            font-size: 12px;
            color: rgba(0,0,0,0.5);
        }
        .mc-pick {
            font-family: var(--font-mono);
            font-size: 11px;
            font-weight: 700;
            color: #000;
            background: var(--green);
            padding: 2px 8px;
            border-radius: 4px;
            margin-top: 4px;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .mc-ou-pick {
            background: rgba(255,214,0,0.9);
        }
        .pick-label {
            font-size: 8px;
            letter-spacing: 1px;
            opacity: 0.6;
            margin-right: 2px;
        }
        .pick-label-ou {
            opacity: 0.7;
        }
        .mc-conf-num {
            font-size: 10px;
            font-weight: 800;
            background: rgba(0,0,0,0.25);
            padding: 1px 5px;
            border-radius: 3px;
            letter-spacing: 0.5px;
        }
        .mc-implied {
            font-family: var(--font-mono);
            font-size: 10px;
            color: rgba(255,255,255,0.35);
            letter-spacing: 0.5px;
            margin-top: 4px;
        }
        .mc-sim-proj {
            font-family: var(--font-mono);
            font-size: 9px;
            color: rgba(255,255,255,0.25);
            letter-spacing: 0.5px;
            margin-top: 2px;
        }

        /* Tug of war bar */
        .tow-bar {
            height: 16px;
            display: flex;
            margin: 0 16px;
            border-radius: 8px;
            overflow: hidden;
            border: 2px solid #000;
            position: relative;
            box-shadow: 2px 2px 0 rgba(0,0,0,0.15);
        }
        .tow-fill {
            height: 100%;
            transition: width 0.5s ease;
        }
        .tow-fill.tow-away {
            border-right: 2px solid #000;
        }
        .tow-fill.tow-home {
            border-left: none;
        }
        .tow-mid {
            position: absolute;
            left: 50%;
            top: -3px;
            width: 3px;
            height: 22px;
            background: #000;
            border-radius: 1px;
            z-index: 1;
        }
        .tow-labels {
            display: flex;
            justify-content: space-between;
            padding: 6px 16px 0;
            font-family: var(--font-mono);
            font-size: 11px;
            font-weight: 600;
            color: rgba(0,0,0,0.55);
        }

        /* Schemes */
        .mc-schemes {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 8px 16px;
            flex-wrap: wrap;
            justify-content: center;
        }
        .scheme-tag {
            font-family: var(--font-mono);
            font-size: 9px;
            font-weight: 600;
            padding: 3px 10px;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border: 1px solid rgba(0,0,0,0.15);
            text-shadow: 0 0 3px rgba(255,255,255,0.5), 0 0 1px rgba(255,255,255,0.3);
        }
        .scheme-divider {
            font-size: 10px;
            color: rgba(0,0,0,0.3);
        }

        /* Expand button */
        .expand-btn {
            width: 100%;
            padding: 10px;
            border: none;
            border-top: 2px dashed rgba(0,0,0,0.1);
            background: rgba(0,0,0,0.02);
            font-family: var(--font-mono);
            font-size: 11px;
            font-weight: 700;
            color: rgba(0,0,0,0.4);
            cursor: pointer;
            transition: all 0.15s;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .expand-btn:hover {
            background: rgba(0,255,85,0.1);
            color: #000;
        }
        /* No rotation — arrow text is swapped in JS already */

        /* Expanded lineup */
        .mc-expanded {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0;
            border-top: var(--border-thin);
        }
        .lineup-half {
            padding: 12px;
        }
        .lineup-half:first-child {
            border-right: 1px solid rgba(0,0,0,0.1);
        }
        .lineup-team-header {
            font-family: var(--font-display);
            font-size: 14px;
            letter-spacing: 1px;
            text-transform: uppercase;
            margin-bottom: 8px;
            padding-bottom: 6px;
            border-bottom: 3px solid #000;
        }

        /* Player row */
        .player-row {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 6px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.15s;
        }
        .player-row:hover {
            background: rgba(0,255,85,0.12);
        }
        .player-row.bench {
            opacity: 0.6;
        }
        .player-row.bench:hover {
            opacity: 1;
        }
        .pr-face {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            object-fit: cover;
            border: 2px solid #000;
            background: #eee;
            flex-shrink: 0;
        }
        .pr-info {
            flex: 1;
            min-width: 0;
        }
        .pr-name {
            font-weight: 700;
            font-size: 13px;
            display: block;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .pr-meta {
            font-size: 10px;
            color: rgba(0,0,0,0.45);
            display: block;
        }
        .pr-stats {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            font-family: var(--font-mono);
            font-size: 10px;
            color: rgba(0,0,0,0.5);
            flex-shrink: 0;
        }
        .pr-ds {
            display: flex;
            flex-direction: column;
            align-items: center;
            flex-shrink: 0;
            width: 40px;
        }
        .pr-ds-num {
            font-family: var(--font-display);
            font-size: 20px;
        }
        .pr-ds-range {
            font-family: var(--font-mono);
            font-size: 9px;
            color: rgba(0,0,0,0.4);
        }
        .ds-elite .pr-ds-num { color: #00CC44; }
        .ds-good .pr-ds-num { color: #0a0a0a; }
        .ds-avg .pr-ds-num { color: #888; }
        .ds-low .pr-ds-num { color: #FF3333; }

        /* ─── PROPS ─── */
        .props-list { display: flex; flex-direction: column; gap: 10px; }
        /* ─── PROP CARDS — Compact Row Layout ─── */
        .prop-card {
            background: var(--surface-dark);
            color: #fff;
            border-radius: var(--radius);
            padding: 10px 12px;
            position: relative;
            overflow: hidden;
        }
        .prop-rank-num {
            position: absolute;
            top: 0;
            left: 0;
            font-family: var(--font-mono);
            font-size: 9px;
            font-weight: 700;
            color: rgba(255,255,255,0.25);
            background: rgba(255,255,255,0.06);
            padding: 2px 6px;
            border-radius: 0 0 6px 0;
        }
        .prop-row {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .prop-face {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            object-fit: cover;
            border: 2px solid rgba(255,255,255,0.15);
            background: #222;
            flex-shrink: 0;
        }
        .prop-info {
            flex: 1;
            min-width: 0;
        }
        .prop-name-row {
            display: flex;
            align-items: baseline;
            gap: 6px;
        }
        .prop-name {
            font-weight: 700;
            font-size: 14px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .prop-team-opp {
            font-family: var(--font-mono);
            font-size: 10px;
            color: rgba(255,255,255,0.35);
            white-space: nowrap;
        }
        .prop-meta {
            font-size: 10px;
            color: rgba(255,255,255,0.3);
            margin-top: 1px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        /* Stat summary box (replaces prop-pick-compact) */
        .stat-summary-box {
            text-align: center;
            flex-shrink: 0;
            padding: 6px 10px;
            border-radius: 8px;
            min-width: 90px;
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
        }
        .stat-summary-line {
            font-family: var(--font-mono);
            font-size: 12px;
            font-weight: 700;
            display: block;
            color: rgba(255,255,255,0.8);
            line-height: 1.2;
            letter-spacing: 0.3px;
        }
        .stat-matchup-badge {
            font-family: var(--font-mono);
            font-size: 8px;
            font-weight: 700;
            display: inline-block;
            padding: 1px 6px;
            border-radius: 3px;
            margin-top: 3px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        /* Sportsbook lines reference row */
        .stat-lines-row {
            display: flex;
            gap: 6px;
            align-items: center;
            flex-shrink: 0;
        }
        .stat-line-ref {
            font-family: var(--font-mono);
            font-size: 9px;
            color: rgba(255,255,255,0.35);
            background: rgba(255,255,255,0.04);
            padding: 1px 5px;
            border-radius: 2px;
            white-space: nowrap;
        }
        .stat-line-ref .proj-tag {
            color: rgba(255,255,255,0.2);
            font-size: 7px;
            margin-left: 2px;
        }
        /* Stat spotlight card (replaces prop-card) */
        .stat-spotlight-card {
            display: flex;
            flex-direction: column;
            gap: 0;
            padding: 10px 10px 10px 12px;
            margin-bottom: 6px;
            border-radius: 6px;
            background: rgba(255,255,255,0.025);
            position: relative;
        }
        .stat-spotlight-card:hover { background: rgba(255,255,255,0.05); }
        /* Neutral last 5 game dots (no hit/miss) */
        .l5-neutral {
            background: rgba(255,255,255,0.08);
            color: rgba(255,255,255,0.6);
        }
        .prop-bottom {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 6px;
            padding-top: 6px;
            border-top: 1px solid rgba(255,255,255,0.06);
        }
        .prop-edge {
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.5px;
            white-space: nowrap;
            min-width: 36px;
        }
        .prop-note {
            font-family: var(--font-mono);
            font-size: 10px;
            color: rgba(255,255,255,0.3);
            flex: 1;
            min-width: 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        /* Last 5 games — compact inline */
        .prop-last5 {
            display: flex;
            align-items: center;
            gap: 3px;
            flex-shrink: 0;
        }
        .l5-val {
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 700;
            padding: 1px 4px;
            border-radius: 3px;
            min-width: 22px;
            text-align: center;
        }
        .l5-hit {
            background: rgba(0,255,85,0.15);
            color: #00FF55;
        }
        .l5-miss {
            background: rgba(255,51,51,0.1);
            color: #FF5555;
        }
        .l5-hit-rate {
            font-family: var(--font-mono);
            font-size: 9px;
            color: rgba(255,255,255,0.35);
            margin-left: 1px;
        }

        /* ─── TRENDS ─── */
        .trends-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }
        .trends-col-header {
            font-family: var(--font-display);
            font-size: 20px;
            letter-spacing: 1px;
            text-transform: uppercase;
            margin-bottom: 12px;
            padding: 10px;
            border-radius: 8px;
            text-align: center;
        }
        .trends-col-header.hot {
            background: var(--surface-dark);
            color: var(--green);
        }
        .trends-col-header.fade {
            background: var(--surface-dark);
            color: var(--red);
        }
        .combo-card {
            background: var(--surface);
            border: var(--border);
            border-radius: var(--radius);
            box-shadow: var(--shadow);
            margin-bottom: 12px;
            overflow: hidden;
        }
        .combo-card.fade {
            border-color: var(--red);
        }
        .combo-top {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 10px 12px;
            border-bottom: 2px solid rgba(0,0,0,0.06);
        }
        .combo-type {
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: rgba(0,0,0,0.4);
        }
        .combo-logo {
            width: 24px;
            height: 24px;
            object-fit: contain;
        }
        .combo-team {
            font-family: var(--font-display);
            font-size: 16px;
            letter-spacing: 1px;
        }
        .combo-badge {
            font-family: var(--font-mono);
            font-size: 11px;
            font-weight: 700;
            padding: 4px 12px;
            text-align: center;
        }
        .badge-hot { background: rgba(0,255,85,0.15); color: #009944; }
        .badge-elite { background: rgba(0,102,255,0.1); color: #0066FF; }
        .badge-minutes { background: rgba(0,153,68,0.1); color: #009944; }
        .badge-disaster { background: rgba(255,51,51,0.12); color: #CC0000; }
        .badge-cooked { background: rgba(255,51,51,0.08); color: #AA0000; }
        .badge-fade { background: rgba(255,214,0,0.12); color: #AA8800; }

        .combo-players-list {
            padding: 4px 8px;
        }
        .combo-player {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 4px;
            border-radius: 6px;
            cursor: pointer;
            transition: background 0.15s;
        }
        .combo-player:hover {
            background: rgba(0,255,85,0.1);
        }
        .combo-face {
            width: 28px;
            height: 28px;
            border-radius: 50%;
            object-fit: cover;
            border: 1px solid #000;
            background: #eee;
            flex-shrink: 0;
        }
        .combo-pname {
            font-weight: 600;
            font-size: 12px;
            flex: 1;
            min-width: 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .combo-parch {
            font-size: 10px;
            color: rgba(0,0,0,0.4);
            flex-shrink: 0;
        }
        .combo-pds {
            font-family: var(--font-display);
            font-size: 16px;
            flex-shrink: 0;
            width: 30px;
            text-align: center;
        }
        .combo-pds.ds-elite { color: #00CC44; }
        .combo-pds.ds-good { color: #0a0a0a; }
        .combo-pds.ds-avg { color: #888; }
        .combo-pds.ds-low { color: #FF3333; }

        .combo-stats {
            display: flex;
            border-top: 2px solid rgba(0,0,0,0.06);
        }
        .combo-stat-item {
            flex: 1;
            padding: 8px;
            text-align: center;
            font-family: var(--font-mono);
            font-size: 11px;
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .combo-stat-item span:first-child {
            font-size: 9px;
            color: rgba(0,0,0,0.4);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .combo-stat-item .positive { color: #009944; font-weight: 700; }
        .combo-stat-item .negative { color: #FF3333; font-weight: 700; }
        .combo-trend-note {
            font-family: var(--font-mono);
            font-size: 10px;
            color: rgba(0,0,0,0.3);
            text-align: center;
            padding: 4px 8px 8px;
        }

        /* ─── BOTTOM SHEET ─── */
        .sheet-overlay {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.5);
            z-index: 200;
            display: none;
            opacity: 0;
            transition: opacity 0.3s;
        }
        .sheet-overlay.show { display: block; opacity: 1; }
        .bottom-sheet {
            position: fixed;
            bottom: 0; left: 0; right: 0;
            background: var(--surface-dark);
            color: #fff;
            border-radius: 20px 20px 0 0;
            z-index: 201;
            transform: translateY(100%);
            transition: transform 0.3s ease;
            max-height: 80vh;
            overflow-y: auto;
        }
        .bottom-sheet.show { transform: translateY(0); }
        .sheet-handle {
            width: 40px;
            height: 4px;
            background: rgba(255,255,255,0.2);
            border-radius: 2px;
            margin: 12px auto;
        }
        .sheet-content { padding: 0 20px 30px; }

        .sheet-header { display: flex; align-items: center; gap: 14px; margin-bottom: 20px; }
        .sheet-face {
            width: 60px; height: 60px; border-radius: 50%;
            border: 3px solid var(--green); object-fit: cover; background: #222;
        }
        .sheet-name { font-family: var(--font-display); font-size: 24px; }
        .sheet-meta { font-family: var(--font-mono); font-size: 11px; color: rgba(255,255,255,0.4); }
        .sheet-ds {
            font-family: var(--font-display);
            font-size: 40px;
            color: var(--green);
            margin-left: auto;
        }
        .sheet-ds-range {
            font-family: var(--font-mono);
            font-size: 11px;
            color: rgba(255,255,255,0.4);
        }

        .sheet-section {
            font-family: var(--font-mono);
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 2px;
            color: rgba(255,255,255,0.3);
            margin: 16px 0 8px;
            padding-bottom: 4px;
            border-bottom: 1px solid rgba(255,255,255,0.08);
        }
        .sheet-stat {
            display: flex;
            justify-content: space-between;
            padding: 6px 0;
            font-size: 13px;
        }
        .sheet-stat-val { font-weight: 700; }
        .sheet-bar-row {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
            font-size: 12px;
        }
        .sheet-bar-label { width: 70px; font-size: 11px; color: rgba(255,255,255,0.5); }
        .sheet-bar-bg {
            flex: 1; height: 6px; background: rgba(255,255,255,0.08);
            border-radius: 3px; overflow: hidden;
        }
        .sheet-bar-fill {
            height: 100%; background: var(--green); border-radius: 3px;
            transition: width 0.4s ease;
        }
        .sheet-bar-pct { font-family: var(--font-mono); font-size: 11px; width: 35px; text-align: right; }

        /* ─── BOTTOM NAV ─── */
        .bottom-nav {
            position: fixed;
            bottom: 0; left: 0; right: 0;
            background: var(--surface-dark);
            display: flex;
            z-index: 150;
            border-top: 2px solid rgba(255,255,255,0.1);
            padding: 4px 0;
            padding-bottom: env(safe-area-inset-bottom, 8px);
        }
        .nav-btn {
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 2px;
            padding: 8px 4px;
            background: none;
            border: none;
            color: rgba(255,255,255,0.35);
            font-family: var(--font-mono);
            font-size: 10px;
            font-weight: 700;
            cursor: pointer;
            transition: color 0.15s;
            letter-spacing: 0.5px;
        }
        .nav-btn.active {
            color: var(--green);
        }
        .nav-icon { font-size: 18px; }

        /* ─── INFO PAGE ─── */
        .info-page { max-width: 800px; }
        .info-section {
            background: var(--surface);
            border: var(--border);
            border-radius: var(--radius);
            box-shadow: var(--shadow);
            padding: 20px;
            margin-bottom: 16px;
        }
        .info-title {
            font-family: var(--font-display);
            font-size: 22px;
            letter-spacing: 1px;
            margin-bottom: 12px;
        }
        .info-text {
            font-size: 13px;
            line-height: 1.7;
            color: rgba(0,0,0,0.7);
            margin-bottom: 12px;
        }
        .info-formula {
            background: var(--surface-dark);
            color: #fff;
            border-radius: 8px;
            padding: 12px 16px;
            margin: 12px 0;
        }
        .formula-row {
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            font-family: var(--font-mono);
            font-size: 12px;
        }
        .ds-tiers { margin: 12px 0; }
        .ds-tiers .ds-tier {
            display: flex;
            gap: 12px;
            padding: 6px 0;
            font-size: 13px;
            align-items: center;
        }
        .ds-tiers .ds-elite { color: #00CC44; font-family: var(--font-display); font-size: 16px; width: 60px; }
        .ds-tiers .ds-good { color: #0a0a0a; font-family: var(--font-display); font-size: 16px; width: 60px; }
        .ds-tiers .ds-avg { color: #888; font-family: var(--font-display); font-size: 16px; width: 60px; }
        .ds-tiers .ds-low { color: #FF3333; font-family: var(--font-display); font-size: 16px; width: 60px; }

        .info-arch-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 10px;
            margin-top: 12px;
        }
        .info-arch-card {
            background: rgba(0,0,0,0.03);
            border: 1px solid rgba(0,0,0,0.08);
            border-radius: 8px;
            padding: 12px;
        }
        .info-arch-icon { font-size: 20px; margin-bottom: 4px; }
        .info-arch-name {
            font-family: var(--font-display);
            font-size: 14px;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }
        .info-arch-desc {
            font-size: 11px;
            color: rgba(0,0,0,0.55);
            line-height: 1.5;
        }

        .info-schemes {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-top: 12px;
        }
        .info-scheme-group h3 {
            font-family: var(--font-display);
            font-size: 14px;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        .scheme-list { display: flex; flex-direction: column; gap: 6px; }
        .scheme-item {
            font-size: 12px;
            line-height: 1.5;
            color: rgba(0,0,0,0.6);
        }

        .info-footer {
            text-align: center;
            background: var(--surface-dark);
            color: rgba(255,255,255,0.4);
        }
        .info-footer p {
            font-family: var(--font-mono);
            font-size: 11px;
            color: rgba(255,255,255,0.4);
        }

        /* ─── TOP 50 RANKINGS ─── */
        .rankings-section {
            background: var(--surface);
            border: var(--border);
            border-radius: var(--radius);
            box-shadow: var(--shadow);
            overflow: hidden;
        }
        .rankings-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            cursor: pointer;
            transition: background 0.15s;
        }
        .rankings-header:hover { background: rgba(0,255,85,0.06); }
        .rankings-title {
            font-family: var(--font-display);
            font-size: 22px;
            letter-spacing: 1px;
        }
        .rankings-toggle {
            font-size: 18px;
            transition: transform 0.3s;
        }
        .rankings-toggle.open { transform: rotate(180deg); }
        .rankings-body {
            border-top: var(--border-thin);
        }
        .rankings-col-headers {
            display: flex;
            align-items: center;
            padding: 8px 16px;
            font-family: var(--font-mono);
            font-size: 9px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: rgba(0,0,0,0.35);
            border-bottom: 1px solid rgba(0,0,0,0.06);
            gap: 8px;
        }
        .rch-rank { width: 30px; }
        .rch-player { flex: 1; }
        .rch-stats { width: 120px; text-align: right; }
        .rch-ds { width: 50px; text-align: center; }
        .rank-row {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            cursor: pointer;
            transition: background 0.15s;
            border-bottom: 1px solid rgba(0,0,0,0.04);
        }
        .rank-row:hover { background: rgba(0,255,85,0.08); }
        .rank-row:nth-child(even) { background: rgba(0,0,0,0.015); }
        .rank-row:nth-child(even):hover { background: rgba(0,255,85,0.08); }
        .rank-num {
            font-family: var(--font-mono);
            font-size: 12px;
            font-weight: 700;
            color: rgba(0,0,0,0.3);
            width: 30px;
            text-align: center;
            flex-shrink: 0;
        }
        .rank-face {
            width: 32px; height: 32px; border-radius: 50%;
            object-fit: cover; border: 2px solid #000;
            background: #eee; flex-shrink: 0;
        }
        .rank-team-logo {
            width: 20px; height: 20px; object-fit: contain; flex-shrink: 0;
        }
        .rank-info { flex: 1; min-width: 0; }
        .rank-name {
            font-weight: 700; font-size: 13px; display: block;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .rank-meta {
            font-size: 10px; color: rgba(0,0,0,0.4); display: block;
        }
        .rank-stats {
            font-family: var(--font-mono); font-size: 11px;
            display: flex; flex-direction: column; align-items: flex-end;
            gap: 1px; flex-shrink: 0; color: rgba(0,0,0,0.5);
        }
        .rank-ds {
            display: flex; flex-direction: column; align-items: center;
            flex-shrink: 0; width: 44px;
        }
        .rank-ds-num {
            font-family: var(--font-display); font-size: 22px;
        }
        .rank-ds-range {
            font-family: var(--font-mono); font-size: 9px; color: rgba(0,0,0,0.35);
        }
        .rank-ds.ds-elite .rank-ds-num { color: #00CC44; }
        .rank-ds.ds-good .rank-ds-num { color: #0a0a0a; }
        .rank-ds.ds-avg .rank-ds-num { color: #888; }
        .rank-ds.ds-low .rank-ds-num { color: #FF3333; }

        /* ─── PROJECTED PLAYER LINES ─── */
        .proj-disclaimer {
            font-family: var(--font-mono);
            font-size: 11px;
            color: rgba(0,0,0,0.45);
            background: rgba(0,0,0,0.04);
            border: 1px dashed rgba(0,0,0,0.15);
            border-radius: 8px;
            padding: 10px 14px;
            margin-bottom: 16px;
            line-height: 1.5;
        }
        .proj-matchup {
            background: var(--surface);
            border: var(--border);
            border-radius: var(--radius);
            box-shadow: var(--shadow);
            margin-bottom: 12px;
            overflow: hidden;
        }
        .proj-matchup-header {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            padding: 10px 16px;
            background: var(--surface-dark);
            color: #fff;
            font-family: var(--font-display);
            font-size: 16px;
            letter-spacing: 1px;
        }
        .proj-logo { width: 24px; height: 24px; object-fit: contain; }
        .proj-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
        }
        .proj-half {
            padding: 8px;
        }
        .proj-half:first-child { border-right: 1px solid rgba(0,0,0,0.08); }
        .proj-row {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 5px 6px;
            font-size: 12px;
            border-bottom: 1px solid rgba(0,0,0,0.04);
        }
        .proj-name {
            flex: 1; font-weight: 600; min-width: 0;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .proj-line {
            font-family: var(--font-mono); font-size: 11px;
            color: rgba(0,0,0,0.55); width: 32px; text-align: right;
        }
        .proj-pra {
            font-family: var(--font-mono); font-size: 11px;
            font-weight: 700; color: var(--ink);
            width: 36px; text-align: right;
            background: rgba(0,255,85,0.1); padding: 2px 4px; border-radius: 3px;
        }

        /* ─── RESPONSIVE ─── */
        @media (max-width: 768px) {
            .top-bar { padding: 8px 12px; }
            .top-picks { display: none; }
            .filter-bar { top: 44px; padding: 0 12px 8px; }
            .content { padding: 12px; }
            .section-header h2 { font-size: 24px; }
            .mc-header { padding: 12px; gap: 8px; }
            .mc-logo { width: 36px; height: 36px; }
            .mc-abbr { font-size: 18px; }
            .mc-spread { font-size: 16px; }
            .mc-expanded { grid-template-columns: 1fr; }
            .lineup-half:first-child { border-right: none; border-bottom: 1px solid rgba(0,0,0,0.1); }
            .trends-grid { grid-template-columns: 1fr; }
            .info-schemes { grid-template-columns: 1fr; }
            .info-arch-grid { grid-template-columns: 1fr; }
            .pr-stats { display: none; }
            .rank-stats { display: none; }
            .rank-team-logo { display: none; }
            .proj-grid { grid-template-columns: 1fr; }
            .proj-half:first-child { border-right: none; border-bottom: 1px solid rgba(0,0,0,0.08); }
        }

        @media (min-width: 769px) {
            .bottom-nav { display: none; }
            body { padding-bottom: 0; }
        }
"""


def generate_js():
    """Generate all JavaScript for tab switching, sorting, expand, bottom sheet."""
    return """
        // ─── RANKINGS TOGGLE ───
        function toggleRankings() {
            const body = document.getElementById('rankingsBody');
            const toggle = document.getElementById('rankingsToggle');
            const isOpen = body.style.display !== 'none';
            body.style.display = isOpen ? 'none' : 'block';
            toggle.classList.toggle('open', !isOpen);
            toggle.textContent = isOpen ? '▼' : '▲';
        }

        // ─── TAB SWITCHING ───
        const filterBtns = document.querySelectorAll('.filter-btn[data-tab]');
        const navBtns = document.querySelectorAll('.nav-btn[data-tab]');
        const tabs = document.querySelectorAll('.tab-content');

        function switchTab(tabId) {
            tabs.forEach(t => t.classList.remove('active'));
            filterBtns.forEach(b => b.classList.remove('active'));
            navBtns.forEach(b => b.classList.remove('active'));

            const target = document.getElementById('tab-' + tabId);
            if (target) target.classList.add('active');

            filterBtns.forEach(b => {
                if (b.dataset.tab === tabId) b.classList.add('active');
            });
            navBtns.forEach(b => {
                if (b.dataset.tab === tabId) b.classList.add('active');
            });

            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        filterBtns.forEach(btn => {
            btn.addEventListener('click', () => switchTab(btn.dataset.tab));
        });
        navBtns.forEach(btn => {
            btn.addEventListener('click', () => switchTab(btn.dataset.tab));
        });

        // ─── SORT BUTTONS ───
        const sortBtns = document.querySelectorAll('.sort-btn');
        const matchupList = document.getElementById('matchupList');

        sortBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                sortBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                const cards = Array.from(matchupList.children);
                const sort = btn.dataset.sort;

                if (sort === 'value') {
                    cards.sort((a, b) => parseFloat(b.dataset.conf) - parseFloat(a.dataset.conf));
                } else {
                    cards.sort((a, b) => parseInt(a.dataset.idx) - parseInt(b.dataset.idx));
                }
                cards.forEach(card => matchupList.appendChild(card));
            });
        });

        // ─── EXPAND / COLLAPSE LINEUPS ───
        function toggleExpand(btn) {
            const card = btn.closest('.matchup-card');
            const expanded = card.querySelector('.mc-expanded');
            const isOpen = expanded.style.display !== 'none';
            expanded.style.display = isOpen ? 'none' : 'grid';
            btn.classList.toggle('open', !isOpen);
            btn.querySelector('span').textContent = isOpen ? '▼ VIEW LINEUPS' : '▲ HIDE LINEUPS';
        }

        // ─── PLAYER BOTTOM SHEET ───
        const overlay = document.getElementById('sheetOverlay');
        const sheet = document.getElementById('bottomSheet');
        const sheetContent = document.getElementById('sheetContent');

        function openPlayerSheet(el) {
            const d = el.dataset;
            const pid = d.pid || '';
            const headshot = pid ? 'https://cdn.nba.com/headshots/nba/latest/260x190/' + pid + '.png' : '';
            const netVal = parseFloat(d.net || 0);
            const netColor = netVal >= 0 ? '#00FF55' : '#FF3333';
            const netSign = netVal >= 0 ? '+' : '';

            sheetContent.innerHTML = `
                <div class="sheet-header">
                    ${headshot ? '<img src="' + headshot + '" class="sheet-face" onerror="this.style.display=\\'none\\'">' : ''}
                    <div>
                        <div class="sheet-name">${d.name || '—'}</div>
                        <div class="sheet-meta">${d.arch || '—'} // ${d.team || '—'}</div>
                    </div>
                    <div style="margin-left:auto; text-align:center">
                        <div class="sheet-ds">${d.ds || '—'}</div>
                        <div class="sheet-ds-range">${d.range || ''}</div>
                    </div>
                </div>

                <div class="sheet-section">STAT LINE</div>
                <div class="sheet-stat"><span>Points</span><span class="sheet-stat-val">${d.pts || '—'} ppg</span></div>
                <div class="sheet-stat"><span>Assists</span><span class="sheet-stat-val">${d.ast || '—'} apg</span></div>
                <div class="sheet-stat"><span>Rebounds</span><span class="sheet-stat-val">${d.reb || '—'} rpg</span></div>
                <div class="sheet-stat"><span>Steals / Blocks</span><span class="sheet-stat-val">${d.stl || '—'} / ${d.blk || '—'}</span></div>
                <div class="sheet-stat"><span>True Shooting</span><span class="sheet-stat-val">${d.ts || '—'}%</span></div>
                <div class="sheet-stat"><span>Net Rating</span><span class="sheet-stat-val" style="color:${netColor}">${netSign}${netVal.toFixed(1)}</span></div>
                <div class="sheet-stat"><span>Usage Rate</span><span class="sheet-stat-val">${d.usg || '—'}%</span></div>
                <div class="sheet-stat"><span>Minutes</span><span class="sheet-stat-val">${d.mpg || '—'} mpg</span></div>

                <div class="sheet-section">SCORE BREAKDOWN</div>
                <div class="sheet-bar-row">
                    <span class="sheet-bar-label">Scoring</span>
                    <div class="sheet-bar-bg"><div class="sheet-bar-fill" style="width:${Math.min(d.scoringPct || 0, 100)}%"></div></div>
                    <span class="sheet-bar-pct">${Math.round(d.scoringPct || 0)}%</span>
                </div>
                <div class="sheet-bar-row">
                    <span class="sheet-bar-label">Playmaking</span>
                    <div class="sheet-bar-bg"><div class="sheet-bar-fill" style="width:${Math.min(d.playmakingPct || 0, 100)}%"></div></div>
                    <span class="sheet-bar-pct">${Math.round(d.playmakingPct || 0)}%</span>
                </div>
                <div class="sheet-bar-row">
                    <span class="sheet-bar-label">Defense</span>
                    <div class="sheet-bar-bg"><div class="sheet-bar-fill" style="width:${Math.min(d.defensePct || 0, 100)}%"></div></div>
                    <span class="sheet-bar-pct">${Math.round(d.defensePct || 0)}%</span>
                </div>
                <div class="sheet-bar-row">
                    <span class="sheet-bar-label">Efficiency</span>
                    <div class="sheet-bar-bg"><div class="sheet-bar-fill" style="width:${Math.min(d.efficiencyPct || 0, 100)}%"></div></div>
                    <span class="sheet-bar-pct">${Math.round(d.efficiencyPct || 0)}%</span>
                </div>
                <div class="sheet-bar-row">
                    <span class="sheet-bar-label">Impact</span>
                    <div class="sheet-bar-bg"><div class="sheet-bar-fill" style="width:${Math.min(d.impactPct || 0, 100)}%"></div></div>
                    <span class="sheet-bar-pct">${Math.round(d.impactPct || 0)}%</span>
                </div>
            `;

            overlay.classList.add('show');
            sheet.classList.add('show');
        }

        overlay.addEventListener('click', closeSheet);
        function closeSheet() {
            overlay.classList.remove('show');
            sheet.classList.remove('show');
        }

        // Close on swipe down
        let sheetStartY = 0;
        sheet.addEventListener('touchstart', e => {
            sheetStartY = e.touches[0].clientY;
        });
        sheet.addEventListener('touchmove', e => {
            const diff = e.touches[0].clientY - sheetStartY;
            if (diff > 80) closeSheet();
        });
"""


if __name__ == "__main__":
    html = generate_html()
    output_path = os.path.join(os.path.dirname(__file__), "nba_sim.html")
    with open(output_path, "w") as f:
        f.write(html)

    # Also copy to index.html for GitHub Pages
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(index_path, "w") as f:
        f.write(html)

    print(f"Generated {output_path}")
    print(f"Generated {index_path}")
    print(f"Open in browser: file://{output_path}")

#!/usr/bin/env python3
"""Generate the NBA SIM frontend HTML — mobile-first redesign with all features."""

import sys
import os
import json
import math
import re
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup
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
    except Exception as e:
        print(f"[NBA Schedule] Failed to fetch: {e}")
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
            except Exception:
                pass

    print(f"[NBA Schedule] Found {len(schedule)} games for today")
    return schedule


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
    """Compute a dynamic score with 75% offense / 25% defense split.

    Offensive sub-score: scoring, playmaking, efficiency, usage
    Defensive sub-score: stocks (STL+BLK amplified) + defensive rating
    Shared: rebounds, net rating impact, minutes

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
    stocks_c = stl * 8.0 + blk * 6.0
    drtg_c = max(0, (115 - drtg) * 2.5)  # 107 DRtg → 20pts, 112 → 7.5, 115+ → 0
    def_raw = stocks_c + drtg_c
    def_score = min(99, max(0, def_raw / 0.5))

    # ── Shared components ──
    rebounding_c = reb * 0.8
    impact_c = net * 0.8
    minutes_c = mpg * 0.3
    shared_raw = rebounding_c + impact_c + minutes_c

    # ── Blend: 75% offense + 25% defense + shared ──
    blended = 0.75 * off_score + 0.25 * def_score + shared_raw
    score = min(99, max(40, int(blended / 1.1)))

    # Breakdown for tooltip — preserve existing keys for compatibility
    total_raw = off_raw + def_raw + shared_raw
    breakdown = {
        "pts": round(pts, 1), "ast": round(ast, 1), "reb": round(reb, 1),
        "stl": round(stl, 1), "blk": round(blk, 1),
        "ts_pct": round(ts * 100, 1) if ts < 1 else round(ts, 1),
        "net_rating": round(net, 1),
        "usg_pct": round(usg * 100, 1) if usg < 1 else round(usg, 1),
        "mpg": round(mpg, 1),
        "def_rating": round(drtg, 1),
        "off_score": round(off_score, 1),
        "def_score": round(def_score, 1),
        "scoring_c": round(scoring_c / max(1, off_raw) * 100, 0) if off_raw else 0,
        "playmaking_c": round(playmaking_c / max(1, off_raw) * 100, 0) if off_raw else 0,
        "defense_c": round(def_score, 0),
        "efficiency_c": round(efficiency_c / max(1, off_raw) * 100, 0) if off_raw else 0,
        "impact_c": round(impact_c / max(1, shared_raw) * 100, 0) if shared_raw else 0,
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


# ────────────────────────────────────────────────────────────────────
# DSI SPREAD MODEL — Steps 1-8
# ────────────────────────────────────────────────────────────────────

# Model constants
_DSI_CONSTANTS = {
    "DS_SCALE":     1.0,    # 1pt DS gap → 1.0 points on spread scale
    "DSI_WEIGHT":   0.50,   # DSI share in final blend
    "NRTG_WEIGHT":  0.50,   # adjusted net rating share in final blend
    "HCA":          3.0,    # home court advantage added to home net rating
    "B2B_PENALTY":  3.0,    # back-to-back penalty subtracted from net rating
    "USAGE_DECAY":      0.995,  # DS multiplier per 1% extra usage (efficiency tax)
    "USAGE_DECAY_DEF":  0.985,  # steeper decay for defensive archetypes absorbing offense
    "STOCKS_PENALTY":   0.8,    # DSI points lost per lost stock (STL+BLK scaled by minutes)
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
    except Exception as e:
        print(f"[RotoWire] Failed to fetch: {e}")
        return {}, {}, [], None, {}

    soup = BeautifulSoup(html, "html.parser")

    # ── Extract team abbreviations (come in pairs: away, home) ──
    team_els = soup.select(".lineup__abbr")
    team_abbrs = [el.get_text(strip=True) for el in team_els]
    if len(team_abbrs) < 2:
        print("[RotoWire] No teams found")
        return {}, {}, [], None, {}

    # Build matchup pairs (every 2 teams = 1 game: away, home)
    matchup_pairs = []
    for i in range(0, len(team_abbrs) - 1, 2):
        away = team_abbrs[i]
        home = team_abbrs[i + 1]
        matchup_pairs.append((home, away))

    print(f"[RotoWire] Found {len(matchup_pairs)} games, {len(team_abbrs)} teams")

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
        print(f"[RotoWire] Extracted {len(game_times)} game times")

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
        except Exception as e:
            print(f"[RotoWire] Failed to parse odds for game {game_idx}: {e}")

        game_idx += 1

    # Determine slate date
    today = datetime.now()
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    slate_date = f"{months[today.month - 1]} {today.day}"

    print(f"[RotoWire] Parsed {len(lineups)} team lineups, {len(lines)} game lines")
    for pair, line_data in lines.items():
        home, away = pair
        sp = line_data["spread"]
        if sp <= 0:
            print(f"  {away}@{home}: {home} {sp:+.1f}, O/U {line_data['total']}")
        else:
            print(f"  {away}@{home}: {away} {-sp:+.1f}, O/U {line_data['total']}")

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
    except Exception as e:
        print(f"[BM] Failed to fetch: {e}")
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
        print(f"[BM] Heading: {h_text}")

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

    print(f"[BM] Found {len(matchup_pairs)} games, {len(lineups)} teams ({slate_date})")
    for home, away in matchup_pairs:
        sp = lines.get((home, away), {}).get("spread", 0)
        total = lines.get((home, away), {}).get("total", 0)
        print(f"  {away}@{home}: {home} {sp:+.1f}, O/U {total}")

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
            print("[Injuries] BREF: no injury table found")
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
        print(f"[Injuries] Basketball Reference: {total} OUT players across {len(out_by_team)} teams")
        return out_by_team

    except Exception as e:
        print(f"[Injuries] Basketball Reference scrape failed: {e}")
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
                except Exception as e:
                    print(f"[Step 0] Could not parse time for {away}@{home}: {time_text} ({e})")

        if should_keep:
            filtered_pairs.append(pair)

    if removed:
        print(f"[Step 0] Filtered {len(removed)} started/completed games:")
        for r in removed:
            print(f"  - {r}")
    else:
        print("[Step 0] All games are upcoming — no filtering needed")

    # Prune lines dict for removed games
    removed_set = set(matchup_pairs) - set(filtered_pairs)
    filtered_lines = {k: v for k, v in rw_lines.items() if k not in removed_set}

    return filtered_pairs, filtered_lines, len(removed)


def detect_back_to_back(team_id):
    """Check if a team played yesterday (back-to-back).

    Returns True if the team's most recent game was yesterday.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    result = read_query("""
        SELECT game_date FROM games
        WHERE season_id = '2025-26'
          AND (home_team_id = ? OR away_team_id = ?)
        ORDER BY game_date DESC
        LIMIT 1
    """, DB_PATH, [team_id, team_id])

    if result.empty:
        return False

    last_game = result.iloc[0]["game_date"]
    is_b2b = str(last_game) == yesterday
    return is_b2b


def _get_full_roster(team_abbr):
    """Get full rotation roster (mpg > 5) with archetypes."""
    return read_query("""
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
        WHERE ps.season_id = '2025-26' AND t.abbreviation = ?
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


def compute_adjusted_ds(roster_df, out_player_ids, projected_minutes):
    """Compute DSI: Dynamic Scores adjusted for who's actually playing.

    Uses archetypes to route usage from missing players to remaining ones.
    Applies stocks loss penalty when high-STL/BLK players are OUT.
    Returns (team_dsi, player_ds_dict, breakdown_notes).
    """
    K = _DSI_CONSTANTS
    available = roster_df[~roster_df["player_id"].isin(out_player_ids)]
    out_players = roster_df[roster_df["player_id"].isin(out_player_ids)]

    if available.empty:
        return 50.0, {}, []

    # Calculate total usage + stocks being lost from OUT players
    missing_usage = 0
    missing_stocks = 0.0
    missing_archetypes = []
    missing_positions = []
    for _, out_row in out_players.iterrows():
        usg = out_row.get("usg_pct", 0) or 0
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

    # Determine archetype category of missing players
    missing_is_scoring = any(a in _SCORING_ARCHETYPES for a in missing_archetypes)
    missing_is_playmaking = any(a in _PLAYMAKING_ARCHETYPES for a in missing_archetypes)
    missing_is_big = any(a in _BIG_ARCHETYPES for a in missing_archetypes)
    missing_is_defensive = any(a in _DEFENSIVE_ARCHETYPES for a in missing_archetypes)
    missing_is_guard = any(p in _GUARD_POSITIONS for p in missing_positions)
    missing_is_wing = any(p in _WING_POSITIONS for p in missing_positions)
    missing_is_bigpos = any(p in _BIG_POSITIONS for p in missing_positions)

    # Compute adjusted DS for each available player
    player_ds = {}
    notes = []
    total_weighted_ds = 0
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

        # Build a modified row for DS calculation
        modified_row = dict(row)
        modified_row["minutes_per_game"] = proj_min

        # Defensive archetypes only absorb 50% of offensive usage boost
        if arch in _DEFENSIVE_ARCHETYPES and usage_boost > 0:
            modified_row["usg_pct"] = base_usg + (usage_boost * 0.5)
        else:
            modified_row["usg_pct"] = adjusted_usg

        ds, _ = compute_dynamic_score(modified_row)

        # Efficiency penalty: more usage = DS decay
        if usage_boost > 0:
            usage_increase_pct = (usage_boost / base_usg * 100) if base_usg > 0 else 0
            # Defensive archetypes suffer MORE from offensive usage absorption
            if arch in _DEFENSIVE_ARCHETYPES:
                decay_rate = K["USAGE_DECAY_DEF"]   # 0.985 — harsh
            else:
                decay_rate = K["USAGE_DECAY"]        # 0.995 — standard
            efficiency_penalty = decay_rate ** usage_increase_pct
            ds = int(ds * efficiency_penalty)
            ds = max(40, ds)

        player_ds[pid] = ds
        total_weighted_ds += ds * proj_min
        total_minutes += proj_min

    raw_team_dsi = total_weighted_ds / total_minutes if total_minutes > 0 else 50.0

    # Stocks loss penalty: team loses DSI for missing STL+BLK production
    stocks_penalty = missing_stocks * K["STOCKS_PENALTY"]
    team_dsi = max(40.0, raw_team_dsi - stocks_penalty)

    return team_dsi, player_ds, notes


def compute_lineup_rating(team_abbr, available_player_ids, team_net_rating):
    """Compute lineup quality from combo data for available players.

    Returns lineup_quality (float, net-rating scale).
    """
    # Get all reliable lineups for this team
    lineups_5 = read_query("""
        SELECT player_ids, net_rating, minutes, gp
        FROM lineup_stats
        WHERE season_id = '2025-26' AND group_quantity = 5
              AND gp > 5 AND minutes > 8
              AND team_id = (SELECT team_id FROM teams WHERE abbreviation = ?)
    """, DB_PATH, [team_abbr])

    lineups_small = read_query("""
        SELECT player_ids, net_rating, minutes, gp, group_quantity
        FROM lineup_stats
        WHERE season_id = '2025-26' AND group_quantity IN (2, 3)
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


def compute_dsi_spread(home_data, away_data, rw_lineups, team_map):
    """Full DSI spread model.

    Steps:
    1. Get starting lineups from RotoWire scrape
    2. Project minutes for available players
    3. Compute lineup quality rating
    4. Compute adjusted Dynamic Scores (DSI) with archetype-aware usage redistribution
    5. Compare home net rating + 3 vs away net rating (with B2B penalties)
    6. Blend 50% DSI + 50% adjusted NRtg

    Returns (spread, total, breakdown).
    """
    K = _DSI_CONSTANTS
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

    # ── Compute DSI ──
    home_dsi, home_player_ds, _ = compute_adjusted_ds(home_roster, home_out_ids, home_proj_min)
    away_dsi, away_player_ds, _ = compute_adjusted_ds(away_roster, away_out_ids, away_proj_min)

    # ── Compute lineup quality (informational) ──
    home_avail_ids = [int(r["player_id"]) for _, r in home_roster.iterrows()
                      if r["player_id"] not in home_out_ids]
    away_avail_ids = [int(r["player_id"]) for _, r in away_roster.iterrows()
                      if r["player_id"] not in away_out_ids]

    home_lineup_q = compute_lineup_rating(home_abbr, home_avail_ids, h_net)
    away_lineup_q = compute_lineup_rating(away_abbr, away_avail_ids, a_net)

    # ── Adjusted net rating: home + 3 vs away, with B2B penalty ──
    home_b2b = detect_back_to_back(home_tid)
    away_b2b = detect_back_to_back(away_tid)

    home_adj_nrtg = h_net + K["HCA"]
    away_adj_nrtg = a_net

    if home_b2b:
        home_adj_nrtg -= K["B2B_PENALTY"]
        print(f"  [B2B] {home_abbr} is on a back-to-back (-{K['B2B_PENALTY']})")
    if away_b2b:
        away_adj_nrtg -= K["B2B_PENALTY"]
        print(f"  [B2B] {away_abbr} is on a back-to-back (-{K['B2B_PENALTY']})")

    nrtg_diff = home_adj_nrtg - away_adj_nrtg

    # ── Final blend: 50% DSI + 50% adjusted NRtg ──
    dsi_diff = home_dsi - away_dsi
    dsi_as_points = dsi_diff * K["DS_SCALE"]

    raw_power = K["DSI_WEIGHT"] * dsi_as_points + K["NRTG_WEIGHT"] * nrtg_diff

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
        "home_dsi": round(home_dsi, 1),
        "away_dsi": round(away_dsi, 1),
        "dsi_diff": round(dsi_diff, 1),
        "dsi_pts": round(dsi_as_points, 1),
        "home_nrtg": round(home_adj_nrtg, 1),
        "away_nrtg": round(away_adj_nrtg, 1),
        "nrtg_diff": round(nrtg_diff, 1),
        "home_b2b": home_b2b,
        "away_b2b": away_b2b,
        "home_out": len(home_out_ids),
        "away_out": len(away_out_ids),
        "home_lineup_q": round(home_lineup_q, 1),
        "away_lineup_q": round(away_lineup_q, 1),
        "raw_power": round(raw_power, 1),
    }

    print(f"  [DSI] {away_abbr}@{home_abbr}: DSI {home_dsi:.1f}v{away_dsi:.1f} | "
          f"NRtg {home_adj_nrtg:+.1f}v{away_adj_nrtg:+.1f} | "
          f"power={raw_power:+.1f} → spread={proj_spread:+.1f} | "
          f"OUT: {len(home_out_ids)}h/{len(away_out_ids)}a"
          f"{' B2B:'+home_abbr if home_b2b else ''}{' B2B:'+away_abbr if away_b2b else ''}")

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


def get_top_trending_players():
    """Get top 4 risers and top 4 fallers by PRA delta (last 14 days vs prior 14 days).
    Uses most recent data date as anchor (not today) in case boxscores are delayed.
    14-day trailing window updated daily at 8 AM PST."""
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
    seven_ago = (latest_dt - timedelta(days=14)).strftime("%Y-%m-%d")
    fourteen_ago = (latest_dt - timedelta(days=28)).strftime("%Y-%m-%d")

    # Recent 7 days averages
    recent = read_query("""
        SELECT pgs.player_id,
               p.full_name,
               t.abbreviation AS team,
               pa.archetype_label,
               COUNT(*) as gp,
               AVG(pgs.pts) as avg_pts,
               AVG(pgs.ast) as avg_ast,
               AVG(pgs.reb) as avg_reb,
               AVG(pgs.pts + pgs.ast + pgs.reb) as avg_pra
        FROM player_game_stats pgs
        JOIN games g ON pgs.game_id = g.game_id
        JOIN players p ON pgs.player_id = p.player_id
        JOIN roster_assignments ra ON pgs.player_id = ra.player_id AND ra.season_id = '2025-26'
        JOIN teams t ON ra.team_id = t.team_id
        LEFT JOIN player_archetypes pa ON pgs.player_id = pa.player_id AND pa.season_id = '2025-26'
        WHERE g.game_date >= ? AND g.game_date <= ?
          AND pgs.minutes >= 15
        GROUP BY pgs.player_id
        HAVING COUNT(*) >= 2
    """, DB_PATH, [seven_ago, today])

    # Prior 7 days averages
    prior = read_query("""
        SELECT pgs.player_id,
               AVG(pgs.pts + pgs.ast + pgs.reb) as avg_pra
        FROM player_game_stats pgs
        JOIN games g ON pgs.game_id = g.game_id
        WHERE g.game_date >= ? AND g.game_date < ?
          AND pgs.minutes >= 15
        GROUP BY pgs.player_id
        HAVING COUNT(*) >= 2
    """, DB_PATH, [fourteen_ago, seven_ago])

    if recent.empty or prior.empty:
        return [], []

    prior_map = {int(row["player_id"]): row["avg_pra"] for _, row in prior.iterrows()}

    trending = []
    for _, row in recent.iterrows():
        pid = int(row["player_id"])
        if pid not in prior_map:
            continue
        recent_pra = row["avg_pra"]
        prior_pra = prior_map[pid]
        delta = recent_pra - prior_pra
        trending.append({
            "player_id": pid,
            "name": row["full_name"],
            "team": row["team"],
            "archetype": row.get("archetype_label") or "Unclassified",
            "recent_pra": round(recent_pra, 1),
            "prior_pra": round(prior_pra, 1),
            "delta": round(delta, 1),
            "gp": int(row["gp"]),
            "avg_pts": round(row["avg_pts"], 1),
            "avg_ast": round(row["avg_ast"], 1),
            "avg_reb": round(row["avg_reb"], 1),
        })

    # Top 4 risers (biggest positive delta), top 4 fallers (biggest negative delta)
    trending.sort(key=lambda x: x["delta"], reverse=True)
    risers = trending[:4]
    fallers = sorted(trending, key=lambda x: x["delta"])[:4]

    return risers, fallers


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

    # ── Scrape RotoWire for lineups + real sportsbook lines ──
    rw_lineups, rw_lines, rw_pairs, rw_slate_date, rw_game_times = scrape_rotowire()

    # Also try Odds API as fallback
    api_lines, api_pairs, api_slate_date, event_ids = fetch_odds_api_lines()

    # Merge lines: prefer RotoWire, fall back to Odds API
    real_lines = {}
    for key, val in rw_lines.items():
        real_lines[key] = val
    for key, val in api_lines.items():
        if key not in real_lines:
            real_lines[key] = val

    has_any_real = len(real_lines) > 0

    # Use RotoWire matchup pairs first, then API, then hardcoded
    using_bm_fallback = False
    if rw_pairs:
        matchup_pairs = rw_pairs
        slate_date = rw_slate_date
        print(f"[Matchups] Using {len(matchup_pairs)} games from RotoWire ({slate_date})")
    elif api_pairs:
        matchup_pairs = api_pairs
        slate_date = api_slate_date
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

    # ── STEP 0: Filter out games that have already started ──
    game_times_for_filter = rw_game_times if matchup_pairs == rw_pairs else {}
    matchup_pairs, real_lines, removed_count = filter_started_games(
        matchup_pairs, game_times_for_filter, real_lines
    )
    if removed_count > 0:
        print(f"[Matchups] {len(matchup_pairs)} games remaining after Step 0 filtering")

    # ── ROLLOVER: If ALL games filtered, try Basketball Monster for tomorrow ──
    if len(matchup_pairs) == 0 and removed_count > 0:
        print("[Rollover] All games completed — checking Basketball Monster for tomorrow's slate...")
        try:
            bm_lineups, bm_lines, bm_pairs, bm_date, bm_times = scrape_basketball_monster()
            if bm_pairs:
                # Check if BM has different games (tomorrow's slate)
                rw_set = set(rw_pairs) if rw_pairs else set()
                bm_set = set(bm_pairs)
                overlap = len(rw_set & bm_set)
                if overlap < len(bm_set) * 0.5:
                    # BM has mostly different games → it's tomorrow's slate
                    print(f"[Rollover] Basketball Monster has tomorrow's slate: {bm_date} ({len(bm_pairs)} games)")
                    matchup_pairs = bm_pairs
                    slate_date = bm_date
                    rw_lineups = bm_lineups  # Use BM lineups for DSI model
                    real_lines = bm_lines
                    rw_game_times = bm_times
                    using_bm_fallback = True
                else:
                    print(f"[Rollover] BM shows same games as today — no tomorrow slate yet")
        except Exception as e:
            print(f"[Rollover] Basketball Monster fallback failed: {e}")

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
        print(f"[Injuries] Merged {added} new BREF OUT players into lineups")

    for home_abbr, away_abbr in matchup_pairs:
        if home_abbr in team_map and away_abbr in team_map:
            h = team_map[home_abbr]
            a = team_map[away_abbr]

            # ── DSI Spread Model ──
            proj_spread, proj_total, spread_breakdown = compute_dsi_spread(
                h, a, rw_lineups, team_map
            )

            net_diff = (h["net_rating"] or 0) - (a["net_rating"] or 0)
            raw_edge = -(proj_spread)  # positive = home favored (from DSI model)

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
                "spread_breakdown": spread_breakdown,
                "rw_lineups": rw_lineups,
            })

    return matchups, team_map, slate_date, event_ids


def get_team_roster(abbreviation, limit=8):
    """Get top players for a team sorted by minutes."""
    players = read_query("""
        SELECT p.player_id, p.full_name, ps.pts_pg, ps.ast_pg, ps.reb_pg,
               ps.stl_pg, ps.blk_pg, ps.ts_pct, ps.usg_pct, ps.net_rating,
               ps.minutes_per_game, ps.def_rating, ra.listed_position,
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
                           ps.ts_pct, ps.usg_pct, ps.net_rating, ps.minutes_per_game,
                           ps.def_rating
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
                           ps.ts_pct, ps.usg_pct, ps.net_rating, ps.minutes_per_game,
                           ps.def_rating
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
               ps.minutes_per_game, ps.def_rating,
               pa.archetype_label
        FROM player_season_stats ps
        JOIN players p ON ps.player_id = p.player_id
        JOIN teams t ON ps.team_id = t.team_id
        LEFT JOIN player_archetypes pa ON ps.player_id = pa.player_id AND ps.season_id = pa.season_id
        WHERE ps.season_id = '2025-26' AND ps.minutes_per_game > 20
        ORDER BY ps.minutes_per_game DESC
        LIMIT 100
    """, DB_PATH)

    # Compute DS for each player, then sort by DS and take top 50
    all_scored = []
    for _, p in players.iterrows():
        ds, breakdown = compute_dynamic_score(p)
        all_scored.append((p, ds, breakdown))
    all_scored.sort(key=lambda x: x[1], reverse=True)
    all_scored = all_scored[:50]

    ranked = []
    for p, ds, breakdown in all_scored:
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

    # ── Build Top 8 Trending Players HTML ──
    risers, fallers = get_top_trending_players()
    trending_html = ""
    if risers or fallers:
        riser_cards = ""
        for p in risers:
            icon = ARCHETYPE_ICONS.get(p["archetype"], "◆")
            headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{p['player_id']}.png"
            riser_cards += f"""
            <div class="trend-card trend-up">
                <img src="{headshot}" class="trend-face" onerror="this.style.display='none'">
                <div class="trend-info">
                    <span class="trend-name">{p['name']}</span>
                    <span class="trend-meta">{p['team']} // {icon} {p['archetype']}</span>
                    <span class="trend-stats">{p['avg_pts']}p {p['avg_ast']}a {p['avg_reb']}r ({p['gp']}G)</span>
                </div>
                <div class="trend-delta trend-pos">+{p['delta']:.1f} PRA</div>
            </div>"""

        faller_cards = ""
        for p in fallers:
            icon = ARCHETYPE_ICONS.get(p["archetype"], "◆")
            headshot = f"https://cdn.nba.com/headshots/nba/latest/260x190/{p['player_id']}.png"
            faller_cards += f"""
            <div class="trend-card trend-down">
                <img src="{headshot}" class="trend-face" onerror="this.style.display='none'">
                <div class="trend-info">
                    <span class="trend-name">{p['name']}</span>
                    <span class="trend-meta">{p['team']} // {icon} {p['archetype']}</span>
                    <span class="trend-stats">{p['avg_pts']}p {p['avg_ast']}a {p['avg_reb']}r ({p['gp']}G)</span>
                </div>
                <div class="trend-delta trend-neg">{p['delta']:.1f} PRA</div>
            </div>"""

        trending_html = f"""
            <div class="section-header">
                <h2>TOP 8 TRENDING PLAYERS</h2>
                <span class="section-sub">Biggest PRA movers — 14-day trailing window (updated daily 8 AM)</span>
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
            <button class="filter-btn" data-tab="trends">Trends</button>
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

            <!-- Top 50 DS Rankings — collapsible (moved from Trends) -->
            <div class="rankings-section" style="margin-top:32px">
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
        </div>

        <!-- TRENDS TAB -->
        <div class="tab-content" id="tab-trends">
            {trending_html}

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

        sim_proj_html = f'<div class="mc-sim-proj">{sim_fav_team} {sim_fav_spread:+.1f} (SIM) · EDGE {edge_abs:.1f} {edge_team}</div>'
    else:
        sim_proj_html = ""

    # Tug of war bar — use full rotation for DSI tug-of-war
    home_ds_sum = 0
    away_ds_sum = 0
    home_roster = get_team_roster(ha, 15)
    away_roster = get_team_roster(aa, 15)
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

    # ── DSI Breakdown ──
    bd = m.get("spread_breakdown", {})
    home_dsi = bd.get("home_dsi", 0)
    away_dsi = bd.get("away_dsi", 0)
    dsi_diff = bd.get("dsi_diff", 0)
    dsi_pts = bd.get("dsi_pts", 0)
    home_nrtg = bd.get("home_nrtg", 0)
    away_nrtg = bd.get("away_nrtg", 0)
    nrtg_diff = bd.get("nrtg_diff", 0)
    home_b2b = bd.get("home_b2b", False)
    away_b2b = bd.get("away_b2b", False)
    home_out_n = bd.get("home_out", 0)
    away_out_n = bd.get("away_out", 0)
    home_lq = bd.get("home_lineup_q", 0)
    away_lq = bd.get("away_lineup_q", 0)
    raw_power_val = bd.get("raw_power", 0)

    # B2B badge HTML
    b2b_badges = ""
    if home_b2b:
        b2b_badges += f'<span class="b2b-badge" style="color:#FF6B6B">B2B {ha} (-3)</span>'
    if away_b2b:
        b2b_badges += f'<span class="b2b-badge" style="color:#FF6B6B">B2B {aa} (-3)</span>'

    # OUT player count badges
    out_badges = ""
    if home_out_n > 0:
        out_badges += f'<span class="out-badge">{ha}: {home_out_n} OUT</span>'
    if away_out_n > 0:
        out_badges += f'<span class="out-badge">{aa}: {away_out_n} OUT</span>'

    # DSI bar visualization
    dsi_total = home_dsi + away_dsi
    dsi_home_pct = (home_dsi / dsi_total * 100) if dsi_total > 0 else 50

    # Which team DSI favors
    if dsi_diff > 0:
        dsi_fav = ha
        dsi_fav_val = f"+{abs(dsi_diff):.1f}"
    elif dsi_diff < 0:
        dsi_fav = aa
        dsi_fav_val = f"+{abs(dsi_diff):.1f}"
    else:
        dsi_fav = "EVEN"
        dsi_fav_val = ""

    # Which team NRtg favors
    if nrtg_diff > 0:
        nrtg_fav = ha
        nrtg_fav_val = f"+{abs(nrtg_diff):.1f}"
    elif nrtg_diff < 0:
        nrtg_fav = aa
        nrtg_fav_val = f"+{abs(nrtg_diff):.1f}"
    else:
        nrtg_fav = "EVEN"
        nrtg_fav_val = ""

    # Model weighting computations
    dsi_weighted = 0.50 * dsi_pts
    nrtg_weighted = 0.50 * nrtg_diff
    proj_spread_val = m.get("proj_spread", 0)

    breakdown_html = f"""
        <div class="dsi-breakdown">
            <div class="dsi-row">
                <span class="dsi-label">DSI</span>
                <span class="dsi-val">{aa} {away_dsi:.1f}</span>
                <div class="dsi-bar-mini">
                    <div class="dsi-bar-away" style="width:{100-dsi_home_pct:.0f}%; background:{ac};"></div>
                    <div class="dsi-bar-home" style="width:{dsi_home_pct:.0f}%; background:{hc};"></div>
                </div>
                <span class="dsi-val">{ha} {home_dsi:.1f}</span>
                <span class="dsi-edge-sm">{dsi_fav} {dsi_fav_val}</span>
            </div>
            <div class="dsi-row">
                <span class="dsi-label">NRtg</span>
                <span class="dsi-val">{aa} {away_nrtg:+.1f}</span>
                <div class="dsi-mid-spacer"></div>
                <span class="dsi-val">{ha} {home_nrtg:+.1f}</span>
                <span class="dsi-edge-sm">{nrtg_fav} {nrtg_fav_val}</span>
            </div>
            <div class="dsi-row dsi-model-row">
                <span class="dsi-label">MODEL</span>
                <span class="dsi-model-formula">50% DSI ({dsi_weighted:+.1f}) + 50% NRtg ({nrtg_weighted:+.1f}) = <strong>PROJ {proj_spread_val:+.1f}</strong></span>
            </div>
            <div class="dsi-row dsi-tags">
                <span class="hca-badge">HCA +3 {ha}</span>
                {b2b_badges}
                {out_badges}
            </div>
        </div>"""

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

        <!-- DSI Breakdown -->
        {breakdown_html}

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

    # RotoWire status classes
    status_class = ""
    status_badge = ""
    if rw_status == "OUT":
        status_class = "player-out"
        status_badge = '<span class="rw-status-badge rw-out">OUT</span>'
    elif rw_status == "GTD":
        status_class = "player-gtd"
        status_badge = '<span class="rw-status-badge rw-gtd">GTD</span>'

    return f"""
    <div class="player-row {starter_class} {status_class}" onclick="openPlayerSheet(this)"
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
            <span class="pr-name">{short} {status_badge}</span>
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
                Every player gets a Dynamic Score from 40-99 using a <strong>75% offense / 25% defense</strong>
                split plus shared impact components.
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
                while 112 DRtg earns only ~7.5. Elite defenders and rim protectors get a meaningful DS boost.
            </p>
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
            <h2 class="info-title">DSI SPREAD MODEL — 9-STEP PIPELINE</h2>
            <p class="info-text">
                The SIM runs a 9-step pipeline to produce projected spreads and totals for every game.
                <strong>Real lines</strong> from sportsbooks replace projections when available via The Odds API.
            </p>
            <div class="info-formula">
                <div class="formula-row"><span>Step 0</span><span>Filter out started/completed games</span></div>
                <div class="formula-row"><span>Step 1</span><span>Get starting lineups from RotoWire</span></div>
                <div class="formula-row"><span>Step 2</span><span>Project minutes for available players</span></div>
                <div class="formula-row"><span>Step 3</span><span>Compute lineup quality rating</span></div>
                <div class="formula-row"><span>Step 4</span><span>Compute adjusted DSI with archetype-aware usage redistribution</span></div>
                <div class="formula-row"><span>Step 5</span><span>Apply stocks penalty for missing defensive players</span></div>
                <div class="formula-row"><span>Step 6</span><span>Compute adjusted NRtg (Home NRtg + 3.0 HCA, with B2B −3.0)</span></div>
                <div class="formula-row"><span>Step 7</span><span>Blend: 50% DSI + 50% Adjusted NRtg = raw power</span></div>
                <div class="formula-row"><span>Step 8</span><span>Proj. Spread = −(raw power), rounded to 0.5</span></div>
            </div>
            <div class="info-formula" style="margin-top:12px">
                <div class="formula-row"><span>Stocks Penalty</span><span>0.8 DSI pts per lost stock (STL+BLK × min share)</span></div>
                <div class="formula-row"><span>Home Court Adv.</span><span>+3.0 added to home net rating</span></div>
                <div class="formula-row"><span>B2B Penalty</span><span>−3.0 subtracted for back-to-back teams</span></div>
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

        /* DSI Breakdown */
        .dsi-breakdown {
            margin: 4px 12px 6px;
            padding: 8px 10px;
            background: rgba(0,0,0,0.03);
            border-radius: 8px;
            border: 1px solid rgba(0,0,0,0.06);
        }
        .dsi-row {
            display: flex;
            align-items: center;
            gap: 6px;
            margin-bottom: 5px;
            font-family: var(--font-mono);
            font-size: 10px;
        }
        .dsi-row:last-child { margin-bottom: 0; }
        .dsi-label {
            font-weight: 700;
            color: rgba(0,0,0,0.45);
            min-width: 30px;
            text-transform: uppercase;
            font-size: 9px;
            letter-spacing: 0.5px;
        }
        .dsi-val {
            font-weight: 600;
            color: rgba(0,0,0,0.7);
            min-width: 55px;
            text-align: center;
            font-size: 10px;
        }
        .dsi-bar-mini {
            flex: 1;
            height: 8px;
            display: flex;
            border-radius: 4px;
            overflow: hidden;
            border: 1px solid rgba(0,0,0,0.15);
        }
        .dsi-bar-away, .dsi-bar-home {
            height: 100%;
            transition: width 0.5s ease;
        }
        .dsi-mid-spacer {
            flex: 1;
        }
        .dsi-edge-sm {
            font-weight: 700;
            color: rgba(0,0,0,0.55);
            font-size: 9px;
            min-width: 50px;
            text-align: right;
        }
        .dsi-model-row {
            margin-top: 4px;
            padding-top: 5px;
            border-top: 1px dashed rgba(0,0,0,0.10);
        }
        .dsi-model-formula {
            font-family: var(--font-mono);
            font-size: 9px;
            font-weight: 600;
            color: rgba(0,0,0,0.55);
            flex: 1;
            text-align: center;
        }
        .dsi-model-formula strong {
            color: rgba(0,0,0,0.85);
            font-size: 10px;
        }
        .dsi-tags {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }
        .hca-badge {
            font-family: var(--font-mono);
            font-size: 9px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 3px;
            background: rgba(0,180,80,0.12);
            color: #0a7d3a;
            letter-spacing: 0.3px;
        }
        .b2b-badge {
            font-family: var(--font-mono);
            font-size: 9px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 3px;
            background: rgba(255,60,60,0.10);
        }
        .out-badge {
            font-family: var(--font-mono);
            font-size: 9px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 3px;
            background: rgba(255,150,0,0.12);
            color: #b36500;
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
        .player-row.player-out {
            opacity: 0.35;
            text-decoration: line-through;
            text-decoration-color: rgba(255,60,60,0.6);
            text-decoration-thickness: 2px;
        }
        .player-row.player-out .pr-face {
            filter: grayscale(100%);
        }
        .player-row.player-gtd {
            opacity: 0.7;
        }
        .rw-status-badge {
            font-family: var(--font-mono);
            font-size: 8px;
            font-weight: 800;
            padding: 1px 5px;
            border-radius: 3px;
            letter-spacing: 0.5px;
            vertical-align: middle;
            margin-left: 4px;
        }
        .rw-out {
            background: rgba(255,60,60,0.15);
            color: #d32f2f;
        }
        .rw-gtd {
            background: rgba(255,180,0,0.15);
            color: #e68a00;
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
            color: rgba(0,0,0,0.35);
            background: rgba(0,0,0,0.06);
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
            border: 2px solid rgba(0,0,0,0.15);
            background: #eee;
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
            color: #000;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .prop-team-opp {
            font-family: var(--font-mono);
            font-size: 10px;
            color: rgba(0,0,0,0.45);
            white-space: nowrap;
        }
        .prop-meta {
            font-size: 10px;
            color: rgba(0,0,0,0.5);
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
            background: rgba(0,0,0,0.04);
            border: 1px solid rgba(0,0,0,0.12);
        }
        .stat-summary-line {
            font-family: var(--font-mono);
            font-size: 12px;
            font-weight: 700;
            display: block;
            color: #000;
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
            color: rgba(0,0,0,0.5);
            background: rgba(0,0,0,0.06);
            padding: 1px 5px;
            border-radius: 2px;
            white-space: nowrap;
        }
        .stat-line-ref .proj-tag {
            color: rgba(0,0,0,0.3);
            font-size: 7px;
            margin-left: 2px;
        }
        /* Stat spotlight card (replaces prop-card) */
        .stat-spotlight-card {
            display: flex;
            flex-direction: column;
            gap: 0;
            padding: 10px 10px 10px 12px;
            margin-bottom: 12px;
            border-radius: var(--radius);
            background: var(--surface);
            border: var(--border);
            box-shadow: var(--shadow);
            color: var(--ink);
            position: relative;
        }
        .stat-spotlight-card:hover { transform: translateY(-1px); }
        /* Neutral last 5 game dots (no hit/miss) */
        .l5-neutral {
            background: rgba(0,0,0,0.08);
            color: rgba(0,0,0,0.6);
        }
        .prop-bottom {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 6px;
            padding-top: 6px;
            border-top: 1px solid rgba(0,0,0,0.08);
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
            color: rgba(0,0,0,0.5);
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
            color: #00994D;
        }
        .l5-miss {
            background: rgba(255,51,51,0.1);
            color: #CC0000;
        }
        .l5-hit-rate {
            font-family: var(--font-mono);
            font-size: 9px;
            color: rgba(0,0,0,0.45);
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

        /* Trending player cards */
        .trend-card {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 12px;
            background: var(--surface);
            border-radius: var(--radius);
            margin-bottom: 8px;
            border: 1px solid rgba(0,0,0,0.06);
        }
        .trend-face {
            width: 40px;
            height: 30px;
            object-fit: cover;
            border-radius: 6px;
        }
        .trend-info {
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 1px;
        }
        .trend-name {
            font-weight: 700;
            font-size: 12px;
            color: #111;
        }
        .trend-meta {
            font-size: 9px;
            color: rgba(0,0,0,0.4);
            font-family: var(--font-mono);
        }
        .trend-stats {
            font-size: 9.5px;
            color: rgba(0,0,0,0.5);
            font-family: var(--font-mono);
        }
        .trend-delta {
            font-family: var(--font-mono);
            font-weight: 800;
            font-size: 12px;
            min-width: 70px;
            text-align: right;
        }
        .trend-pos { color: #00AA33; }
        .trend-neg { color: #DD2222; }

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

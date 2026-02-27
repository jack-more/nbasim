#!/usr/bin/env python3
"""
grade_picks.py — CSV-based pick tracker with auto-grading.

Reads picks from data/picks.csv, fetches scores from The Odds API,
grades ungraded picks W/L/P, updates the CSV in-place.

Usage:
  python scripts/grade_picks.py                          # Grade pending picks
  python scripts/grade_picks.py --add "2026-02-26,OKC @ LAL,LAL +3.5,spread,50"
  python scripts/grade_picks.py --summary                # Just print record
"""

import csv
import os
import re
import sys
from datetime import datetime, timezone

import requests

# ── Paths ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
PICKS_CSV = os.path.join(PROJECT_ROOT, "data", "picks.csv")
RESULTS_JSON = os.path.join(PROJECT_ROOT, "data", "settlement_results.json")

# ── API config ──
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
if not ODDS_API_KEY:
    sys.path.insert(0, PROJECT_ROOT)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
        ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
    except ImportError:
        pass

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

STARTING_BANKROLL = 1150.0
CSV_FIELDS = ["date", "matchup", "side", "type", "risk", "result", "profit"]


# ── CSV I/O ──────────────────────────────────────────────────────────

def read_picks():
    """Read all picks from CSV. Returns list of dicts."""
    if not os.path.exists(PICKS_CSV):
        print(f"No picks file at {PICKS_CSV}")
        return []
    with open(PICKS_CSV, newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            row["risk"] = row.get("risk", "0").strip()
            row["result"] = row.get("result", "").strip()
            row["profit"] = row.get("profit", "").strip()
            rows.append(row)
        return rows


def write_picks(picks):
    """Write picks back to CSV."""
    os.makedirs(os.path.dirname(PICKS_CSV), exist_ok=True)
    with open(PICKS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(picks)


def add_pick(raw_str):
    """Append a pick from CLI string: 'date,matchup,side,type,risk'"""
    parts = [p.strip() for p in raw_str.split(",")]
    if len(parts) < 5:
        print("Format: date,matchup,side,type,risk")
        print('Example: "2026-02-26,OKC @ LAL,LAL +3.5,spread,50"')
        sys.exit(1)

    new_pick = {
        "date": parts[0],
        "matchup": parts[1],
        "side": parts[2],
        "type": parts[3],
        "risk": parts[4],
        "result": "",
        "profit": "",
    }

    picks = read_picks()
    picks.append(new_pick)
    write_picks(picks)
    print(f"Added: {new_pick['date']} | {new_pick['matchup']} | {new_pick['side']} | risk {new_pick['risk']}")


# ── Score Fetching ───────────────────────────────────────────────────

def fetch_scores(days_from=5):
    """Fetch completed NBA game scores from The Odds API."""
    if not ODDS_API_KEY:
        print("No ODDS_API_KEY set — cannot auto-grade. Set result column manually.")
        return {}

    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/scores"
    resp = requests.get(url, params={
        "apiKey": ODDS_API_KEY,
        "daysFrom": days_from,
    })

    if resp.status_code != 200:
        print(f"Scores API error: {resp.status_code}")
        return {}

    remaining = resp.headers.get("x-requests-remaining", "?")
    print(f"[Scores API] {remaining} requests remaining")

    scores = {}
    for event in resp.json():
        if not event.get("completed", False):
            continue

        home_full = event.get("home_team", "")
        away_full = event.get("away_team", "")
        home_abbr = ODDS_TEAM_MAP.get(home_full, "")
        away_abbr = ODDS_TEAM_MAP.get(away_full, "")

        if not home_abbr or not away_abbr:
            continue

        event_scores = event.get("scores", [])
        home_score = away_score = None
        for s in event_scores:
            team_name = s.get("name", "")
            score_val = int(s.get("score", 0))
            if team_name == home_full:
                home_score = score_val
            elif team_name == away_full:
                away_score = score_val

        if home_score is not None and away_score is not None:
            key = f"{away_abbr} @ {home_abbr}"
            scores[key] = {
                "home_abbr": home_abbr,
                "away_abbr": away_abbr,
                "home_score": home_score,
                "away_score": away_score,
            }

    print(f"  Found {len(scores)} completed games")
    return scores


# ── Grading Logic ────────────────────────────────────────────────────

def parse_side(side_str):
    """Parse 'CLE -16.0' or 'BOS +4.5' into (team, line_value, direction).

    Returns (team_abbr, line_float, 'home_spread'|'away_spread') or None.
    """
    m = re.match(r"([A-Z]{3})\s+([+-]?[\d.]+)", side_str.strip())
    if not m:
        return None
    team = m.group(1)
    line = float(m.group(2))
    return team, line


def compute_profit(result, risk_amount, odds=-110):
    """Compute profit based on result and standard -110 odds."""
    if result == "W":
        return round(risk_amount * (100 / abs(odds)), 2)
    elif result == "L":
        return round(-risk_amount, 2)
    else:
        return 0.0


def grade_spread(matchup, side_str, scores):
    """Grade a spread pick. Returns (result, profit_amount) or None."""
    game = scores.get(matchup)
    if game is None:
        return None

    parsed = parse_side(side_str)
    if parsed is None:
        return None

    team, line = parsed
    home_score = game["home_score"]
    away_score = game["away_score"]
    home_abbr = game["home_abbr"]
    away_abbr = game["away_abbr"]
    actual_margin = home_score - away_score

    if team == home_abbr:
        # Picked home team with this spread
        # Home -16.0: home needs to win by more than 16
        # Home +4.5: home can lose by up to 4
        cover_margin = actual_margin - line  # positive means cover
    elif team == away_abbr:
        # Picked away team with this spread
        # Away +4.5 means line is +4.5, away covers if they lose by less than 4.5
        cover_margin = -actual_margin - line  # flip perspective
    else:
        return None

    if cover_margin > 0:
        return "W"
    elif cover_margin == 0:
        return "P"
    else:
        return "L"


# ── Main ─────────────────────────────────────────────────────────────

def grade_all():
    """Grade all pending picks from CSV using Odds API scores."""
    picks = read_picks()
    if not picks:
        print("No picks in CSV")
        return

    # Count pending
    pending = [p for p in picks if not p["result"]]
    if not pending:
        print("All picks already graded")
        print_summary(picks)
        return

    print(f"\n{len(pending)} pending picks to grade\n")

    # Fetch scores
    scores = fetch_scores()

    # Grade each pending pick
    graded = 0
    for pick in picks:
        if pick["result"]:
            continue  # Already graded

        matchup = pick["matchup"]
        side = pick["side"]
        pick_type = pick.get("type", "spread")
        risk = float(pick.get("risk", 0) or 0)

        if pick_type == "spread":
            result = grade_spread(matchup, side, scores)
        else:
            result = None  # TODO: total/prop grading

        if result is None:
            print(f"  PENDING: {pick['date']} | {matchup} | {side}")
            continue

        profit = compute_profit(result, risk)
        pick["result"] = result
        pick["profit"] = str(profit)
        graded += 1

        marker = {"W": "+", "L": "-", "P": "="}[result]
        print(f"  {marker} {result}: {matchup} | {side} | {profit:+.2f} $PP")

    # Write updated CSV
    write_picks(picks)
    print(f"\nGraded {graded} picks")

    print_summary(picks)


def print_summary(picks):
    """Print running record and bankroll."""
    record = {"W": 0, "L": 0, "P": 0}
    total_profit = 0.0
    pending = 0

    for p in picks:
        r = p.get("result", "").strip()
        if r in ("W", "L", "P"):
            record[r] += 1
            total_profit += float(p.get("profit", 0) or 0)
        else:
            pending += 1

    bankroll = STARTING_BANKROLL + total_profit

    print(f"\n{'='*50}")
    print(f"  RECORD:   {record['W']}-{record['L']}-{record['P']}")
    print(f"  P/L:      {total_profit:+.2f} $PP")
    print(f"  BANKROLL: {STARTING_BANKROLL:.0f} -> {bankroll:.0f} $PP")
    if pending:
        print(f"  PENDING:  {pending} picks")
    print(f"{'='*50}")

    # Also write settlement JSON for blog integration
    import json
    results_list = []
    for p in picks:
        r = p.get("result", "").strip()
        if r:
            results_list.append({
                "date": p["date"],
                "matchup": p["matchup"],
                "side": p["side"],
                "type": p.get("type", "spread"),
                "risk": float(p.get("risk", 0) or 0),
                "result": r,
                "profit": float(p.get("profit", 0) or 0),
            })

    settlement = {
        "graded_at": datetime.now(timezone.utc).isoformat(),
        "picks": results_list,
        "pending_count": pending,
        "record": record,
        "total_profit": round(total_profit, 2),
        "starting_bankroll": STARTING_BANKROLL,
        "new_bankroll": round(bankroll, 2),
        "status": "SETTLED" if pending == 0 else "PARTIAL",
    }

    os.makedirs(os.path.dirname(RESULTS_JSON), exist_ok=True)
    with open(RESULTS_JSON, "w") as f:
        json.dump(settlement, f, indent=2)


def main():
    print("=== NBA SIM Pick Tracker ===\n")

    if len(sys.argv) > 1:
        if sys.argv[1] == "--add" and len(sys.argv) > 2:
            add_pick(sys.argv[2])
            return
        elif sys.argv[1] == "--summary":
            picks = read_picks()
            if picks:
                print_summary(picks)
            return
        else:
            print(f"Unknown flag: {sys.argv[1]}")
            print("Usage:")
            print('  python scripts/grade_picks.py                  # Grade pending')
            print('  python scripts/grade_picks.py --add "..."      # Add a pick')
            print('  python scripts/grade_picks.py --summary        # Print record')
            sys.exit(1)

    grade_all()


if __name__ == "__main__":
    main()

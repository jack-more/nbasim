#!/usr/bin/env python3
"""
grade_picks.py — CSV-based pick tracker with auto-grading.

Reads picks from data/picks.csv, fetches scores from ESPN's public API
(works from GitHub Actions IPs), grades ungraded picks W/L/P, updates
the CSV in-place.

Usage:
  python scripts/grade_picks.py                          # Grade pending picks
  python scripts/grade_picks.py --add "2026-02-26,OKC @ LAL,LAL +3.5,spread,50"
  python scripts/grade_picks.py --summary                # Just print record
"""

import csv
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

# ── Paths ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
PICKS_CSV = os.path.join(PROJECT_ROOT, "data", "picks.csv")
RESULTS_JSON = os.path.join(PROJECT_ROOT, "data", "settlement_results.json")

STARTING_BANKROLL = 1150.0
CSV_FIELDS = ["date", "matchup", "side", "type", "risk", "result", "profit", "odds", "home_score", "away_score"]


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
            row["odds"] = row.get("odds", "").strip()
            row["home_score"] = row.get("home_score", "").strip()
            row["away_score"] = row.get("away_score", "").strip()
            rows.append(row)
        return rows


def write_picks(picks):
    """Write picks back to CSV."""
    os.makedirs(os.path.dirname(PICKS_CSV), exist_ok=True)
    with open(PICKS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
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


# ── ESPN abbreviation → standard NBA abbreviation mapping ────────────
ESPN_ABBR_MAP = {
    "GS": "GSW", "SA": "SAS", "NO": "NOP", "NY": "NYK",
    "UTAH": "UTA", "WSH": "WAS",
}


def _normalize_abbr(espn_abbr):
    """Convert ESPN team abbreviation to standard 3-letter NBA abbreviation."""
    return ESPN_ABBR_MAP.get(espn_abbr, espn_abbr)


# ── Score Fetching ───────────────────────────────────────────────────

def fetch_scores(days_from=7):
    """Fetch completed NBA game scores from ESPN's public API.

    Uses the ESPN scoreboard endpoint which works reliably from
    GitHub Actions cloud IPs (unlike BBRef/stats.nba.com).
    """
    scores = {}
    today = datetime.now(timezone.utc)

    for day_offset in range(days_from):
        date = today - timedelta(days=day_offset)
        date_str = date.strftime("%Y%m%d")

        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date_str}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, Exception) as e:
            print(f"[ESPN] Failed to fetch {date_str}: {e}")
            continue

        for event in data.get("events", []):
            competition = event.get("competitions", [{}])[0]
            status = competition.get("status", {}).get("type", {})

            # Only process completed games
            if not status.get("completed", False):
                continue

            competitors = competition.get("competitors", [])
            home = away = None
            for team_entry in competitors:
                if team_entry.get("homeAway") == "home":
                    home = team_entry
                else:
                    away = team_entry

            if not home or not away:
                continue

            home_abbr = _normalize_abbr(home["team"]["abbreviation"])
            away_abbr = _normalize_abbr(away["team"]["abbreviation"])
            home_score = int(home.get("score", 0))
            away_score = int(away.get("score", 0))

            key = f"{away_abbr} @ {home_abbr}"
            scores[key] = {
                "home_abbr": home_abbr,
                "away_abbr": away_abbr,
                "home_score": home_score,
                "away_score": away_score,
            }

    print(f"[ESPN] Found {len(scores)} completed games (last {days_from} days)")
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
    """Compute profit based on result and American odds.

    American odds:
      -110: risk $110 to win $100 → profit = risk * (100/110)
      +150: risk $100 to win $150 → profit = risk * (150/100)
    """
    if result == "W":
        if odds > 0:
            # Underdog: +150 means risk $100 to win $150
            return round(risk_amount * (odds / 100), 2)
        else:
            # Favorite: -110 means risk $110 to win $100
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
        # Picked home team: margin from home perspective + line
        # HOU -8.5: actual_margin=10 → 10+(-8.5)=1.5 → covers (won by more than 8.5)
        # HOU -8.5: actual_margin=5  → 5+(-8.5)=-3.5 → doesn't cover
        cover_margin = actual_margin + line
    elif team == away_abbr:
        # Picked away team: flip margin to away perspective + line
        # GSW +15: actual_margin=7 (home won by 7) → -7+15=8 → covers (lost by less than 15)
        # GSW +15: actual_margin=20 → -20+15=-5 → doesn't cover
        cover_margin = -actual_margin + line
    else:
        return None

    if cover_margin > 0:
        return "W"
    elif cover_margin == 0:
        return "P"
    else:
        return "L"


def grade_ml(matchup, side_str, scores):
    """Grade a moneyline pick. Side is like 'GSW ML' or 'BOS ML'."""
    game = scores.get(matchup)
    if game is None:
        return None

    # Parse "GSW ML" → team = "GSW"
    m = re.match(r"([A-Z]{3})\s+ML", side_str.strip())
    if not m:
        return None

    team = m.group(1)
    home_score = game["home_score"]
    away_score = game["away_score"]
    home_abbr = game["home_abbr"]
    away_abbr = game["away_abbr"]

    if team == home_abbr:
        if home_score > away_score:
            return "W"
        elif home_score == away_score:
            return "P"
        else:
            return "L"
    elif team == away_abbr:
        if away_score > home_score:
            return "W"
        elif away_score == home_score:
            return "P"
        else:
            return "L"
    else:
        return None


# ── Main ─────────────────────────────────────────────────────────────

def grade_all():
    """Grade all pending picks from CSV using local DB scores."""
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

    # Auto-compute lookback: go back far enough to cover oldest pending pick
    oldest_date = min(p["date"] for p in pending)
    days_needed = (datetime.now(timezone.utc) - datetime.strptime(oldest_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)).days + 2
    days_needed = max(days_needed, 3)  # Minimum 3 days
    print(f"Oldest pending: {oldest_date} → fetching {days_needed} days of scores")

    # Fetch scores
    scores = fetch_scores(days_from=days_needed)

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
        elif pick_type == "ml":
            result = grade_ml(matchup, side, scores)
        else:
            result = None  # TODO: total/prop grading

        if result is None:
            print(f"  PENDING: {pick['date']} | {matchup} | {side}")
            continue

        # Use actual ML odds for moneyline picks, standard -110 for spreads
        pick_odds = -110
        if pick_type == "ml" and pick.get("odds"):
            try:
                pick_odds = int(pick["odds"])
            except (ValueError, TypeError):
                pass
        profit = compute_profit(result, risk, odds=pick_odds)
        pick["result"] = result
        pick["profit"] = str(profit)
        # Store game scores for settlement blog patching
        game = scores.get(matchup)
        if game:
            pick["home_score"] = str(game["home_score"])
            pick["away_score"] = str(game["away_score"])
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
            entry = {
                "date": p["date"],
                "matchup": p["matchup"],
                "side": p["side"],
                "type": p.get("type", "spread"),
                "risk": float(p.get("risk", 0) or 0),
                "result": r,
                "profit": float(p.get("profit", 0) or 0),
            }
            # Include game scores if available
            if p.get("home_score"):
                entry["home_score"] = int(p["home_score"])
            if p.get("away_score"):
                entry["away_score"] = int(p["away_score"])
            results_list.append(entry)

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

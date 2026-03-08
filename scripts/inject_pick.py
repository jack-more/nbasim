#!/usr/bin/env python3
"""
inject_pick.py — Manually inject a pick into the tracker.

For picks outside the 8+ auto-capture threshold. Supports both
pre-game (pending) and post-game (auto-grades via ESPN) injection.

Usage:
  # Pre-game (pending, will be graded later):
  python scripts/inject_pick.py "BOS @ CLE" "BOS -0.5" --risk 50

  # Moneyline pick:
  python scripts/inject_pick.py "BOS @ CLE" "BOS ML" --risk 50 --odds +130

  # Custom date:
  python scripts/inject_pick.py "BOS @ CLE" "BOS -0.5" --date 2026-03-08

  # Force add even if game exists:
  python scripts/inject_pick.py "BOS @ CLE" "BOS -0.5" --force

  # Via workflow dispatch:
  Called automatically when the workflow receives inject_pick input
"""

import argparse
import csv
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PICKS_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "picks.csv")

# ESPN team abbreviation normalization (ESPN → standard)
ESPN_ABBREV = {"GS": "GSW", "SA": "SAS", "NO": "NOP", "NY": "NYK", "UTAH": "UTA", "WSH": "WAS"}


def parse_pick(side_text):
    """Parse side text like 'BOS -0.5' or 'BOS ML' into components."""
    parts = side_text.strip().split()
    if len(parts) < 2:
        raise ValueError(f"Invalid pick format: '{side_text}'. Use 'TEAM +/-SPREAD' or 'TEAM ML'")

    team = parts[0].upper()
    line_part = parts[1]

    if line_part.upper() == "ML":
        return team, "ml", 0.0
    else:
        try:
            spread = float(line_part)
        except ValueError:
            raise ValueError(f"Invalid spread: '{line_part}'. Use a number like +3.5 or -2.0")
        return team, "spread", spread


def check_existing(date_str, matchup, pick_type):
    """Check if this pick already exists in CSV."""
    if not os.path.exists(PICKS_CSV):
        return False
    with open(PICKS_CSV) as f:
        for row in csv.DictReader(f):
            if row["date"] == date_str and row["matchup"] == matchup and row.get("type", "spread") == pick_type:
                return True
    return False


def fetch_espn_score(matchup, date_str):
    """Try to get final score from ESPN for this matchup."""
    espn_date = date_str.replace("-", "")
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={espn_date}"

    try:
        data = json.loads(urllib.request.urlopen(url, timeout=10).read())
    except Exception as e:
        print(f"  [ESPN] Could not fetch scores: {e}")
        return None

    away_team, home_team = matchup.split(" @ ")

    for ev in data.get("events", []):
        comp = ev["competitions"][0]
        status = comp["status"]["type"]["name"]

        home = [c for c in comp["competitors"] if c["homeAway"] == "home"][0]
        away = [c for c in comp["competitors"] if c["homeAway"] == "away"][0]

        h_abbr = ESPN_ABBREV.get(home["team"]["abbreviation"], home["team"]["abbreviation"])
        a_abbr = ESPN_ABBREV.get(away["team"]["abbreviation"], away["team"]["abbreviation"])

        if (a_abbr == away_team and h_abbr == home_team) or (h_abbr == home_team and a_abbr == away_team):
            if status == "STATUS_FINAL":
                return {
                    "home_score": int(home["score"]),
                    "away_score": int(away["score"]),
                    "status": "final",
                }
            else:
                return {"status": status}

    return None


def grade_pick(side_text, pick_type, matchup, home_score, away_score, ml_odds=None):
    """Grade a pick given final scores. Returns (result, profit)."""
    parts = side_text.strip().split()
    team = parts[0].upper()
    away_team, home_team = matchup.split(" @ ")
    actual_margin = home_score - away_score

    if pick_type == "ml":
        # ML: did the picked team win?
        if team == home_team:
            won = home_score > away_score
        else:
            won = away_score > home_score

        if home_score == away_score:
            return "P", 0.0

        if won:
            if ml_odds and ml_odds != 0:
                if ml_odds > 0:
                    payout_ratio = ml_odds / 100.0
                else:
                    payout_ratio = 100.0 / abs(ml_odds)
            else:
                payout_ratio = 100.0 / 110.0  # default -110
            return "W", round(50 * payout_ratio, 2)  # risk is set separately
        else:
            return "L", 0.0  # loss amount set from risk

    else:
        # Spread
        spread = float(parts[1])
        if team == home_team:
            cover_margin = actual_margin + spread
        else:
            cover_margin = -actual_margin + spread

        if cover_margin > 0:
            return "W", 0.0  # profit calculated from risk
        elif cover_margin < 0:
            return "L", 0.0
        else:
            return "P", 0.0


def inject(matchup, side_text, risk=50, date_str=None, ml_odds=None, force=False):
    """Inject a pick into picks.csv, auto-grading if game is final."""
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    team, pick_type, line_val = parse_pick(side_text)

    # Normalize side text
    if pick_type == "ml":
        side = f"{team} ML"
    else:
        side = f"{team} {line_val:+.1f}" if line_val != 0 else f"{team} +0.0"
        # Clean up: remove +0.0 formatting quirk for negative numbers
        side = side.replace("+-", "-")

    print(f"[inject] Pick: {matchup} → {side} ({pick_type}) | Risk: {risk} $PP | Date: {date_str}")

    # Dedup check
    if not force and check_existing(date_str, matchup, pick_type):
        print(f"[inject] SKIP — pick already exists for {matchup} ({pick_type}) on {date_str}")
        print(f"[inject] Use --force to override")
        return False

    # Try to auto-grade from ESPN
    result = ""
    profit = ""
    home_score = ""
    away_score = ""
    odds_val = ""

    if ml_odds:
        odds_val = f"+{ml_odds}" if ml_odds > 0 else str(ml_odds)

    score_data = fetch_espn_score(matchup, date_str)
    if score_data and score_data.get("status") == "final":
        h_score = score_data["home_score"]
        a_score = score_data["away_score"]
        home_score = str(h_score)
        away_score = str(a_score)

        res, _ = grade_pick(side, pick_type, matchup, h_score, a_score, ml_odds)
        result = res

        if result == "W":
            if pick_type == "ml" and ml_odds:
                if ml_odds > 0:
                    profit = str(round(risk * ml_odds / 100.0, 2))
                else:
                    profit = str(round(risk * 100.0 / abs(ml_odds), 2))
            else:
                profit = str(round(risk * 100.0 / 110.0, 2))  # standard -110
        elif result == "L":
            profit = str(-risk)
        else:
            profit = "0"

        print(f"  [ESPN] FINAL: {matchup} → {away_score}-{home_score}")
        print(f"  [grade] {side} → {result} ({'+' if float(profit) >= 0 else ''}{profit} $PP)")
    elif score_data:
        print(f"  [ESPN] Game status: {score_data.get('status', 'unknown')} — will grade later")
    else:
        print(f"  [ESPN] No score found — will grade later via pipeline")

    # Append to CSV
    csv_exists = os.path.exists(PICKS_CSV)
    with open(PICKS_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        if not csv_exists:
            writer.writerow(["date", "matchup", "side", "type", "risk", "result", "profit", "odds", "home_score", "away_score"])
        writer.writerow([date_str, matchup, side, pick_type, risk, result, profit, odds_val, home_score, away_score])

    print(f"[inject] Added to {PICKS_CSV}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Manually inject a pick into the tracker",
        epilog='Example: python scripts/inject_pick.py "BOS @ CLE" "BOS -0.5" --risk 50',
    )
    parser.add_argument("matchup", help='Game matchup, e.g. "BOS @ CLE"')
    parser.add_argument("side", help='Pick side, e.g. "BOS -0.5" or "BOS ML"')
    parser.add_argument("--risk", type=int, default=50, help="Risk amount in $PP (default: 50)")
    parser.add_argument("--date", type=str, default=None, help="Date YYYY-MM-DD (default: today)")
    parser.add_argument("--odds", type=int, default=None, help="ML odds (e.g. +130 or -150)")
    parser.add_argument("--force", action="store_true", help="Add even if pick already exists")
    args = parser.parse_args()

    success = inject(
        matchup=args.matchup,
        side_text=args.side,
        risk=args.risk,
        date_str=args.date,
        ml_odds=args.odds,
        force=args.force,
    )

    if success:
        # Show updated record
        with open(PICKS_CSV) as f:
            picks = list(csv.DictReader(f))
        wins = sum(1 for p in picks if p["result"] == "W")
        losses = sum(1 for p in picks if p["result"] == "L")
        pending = sum(1 for p in picks if not p["result"])
        total_profit = sum(float(p.get("profit", 0) or 0) for p in picks)
        bankroll = 1150 + total_profit
        print(f"\n  RECORD: {wins}-{losses} | PENDING: {pending} | BANKROLL: {bankroll:,.0f} $PP")


if __name__ == "__main__":
    main()

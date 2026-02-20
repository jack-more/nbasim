#!/usr/bin/env python3
"""
grade_picks.py — Fetch scores, grade picks W/L/P, compute profit.

Reads picks from the picks table (or inserts hardcoded picks if empty),
fetches completed game scores from The Odds API,
grades each pick, and writes settlement_results.json.

Usage:
  python scripts/grade_picks.py
"""

import json
import os
import sys
import sqlite3
from datetime import datetime, timezone

import requests

# ── Ensure project root is on path ──
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DB_PATH

# ── API config ──
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
if not ODDS_API_KEY:
    from dotenv import load_dotenv
    load_dotenv()
    ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

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

# ── Starting bankroll ──
STARTING_BANKROLL = 1000.0

# ── Hardcoded picks (insert once, then read from DB) ──
CURRENT_PICKS = [
    # FEB 19 — THURSDAY
    # Spreads
    {"slate_date": "2026-02-19", "pick_type": "spread", "matchup": "BKN @ CLE",
     "side": "CLE -16.0", "line_value": 16.0, "direction": "home_spread",
     "confidence": 10, "risk_amount": 50},
    {"slate_date": "2026-02-19", "pick_type": "spread", "matchup": "PHX @ SAS",
     "side": "SAS -8.0", "line_value": 8.0, "direction": "home_spread",
     "confidence": 7, "risk_amount": 30},
    # O/U
    {"slate_date": "2026-02-19", "pick_type": "total", "matchup": "BKN @ CLE",
     "side": "OVER 229.5", "line_value": 229.5, "direction": "over",
     "confidence": 10, "risk_amount": 30},
    {"slate_date": "2026-02-19", "pick_type": "total", "matchup": "PHX @ SAS",
     "side": "OVER 230.0", "line_value": 230.0, "direction": "over",
     "confidence": 5, "risk_amount": 30},
    # Props
    {"slate_date": "2026-02-19", "pick_type": "prop", "matchup": "DEN @ LAC",
     "side": "OVER 28.5 PTS", "player_name": "N. Jokic", "stat_type": "PTS",
     "line_value": 28.5, "direction": "over", "confidence": 10, "risk_amount": 30},
    {"slate_date": "2026-02-19", "pick_type": "prop", "matchup": "BKN @ CLE",
     "side": "OVER 27.2 PTS", "player_name": "D. Mitchell", "stat_type": "PTS",
     "line_value": 27.2, "direction": "over", "confidence": 9, "risk_amount": 30},
    {"slate_date": "2026-02-19", "pick_type": "prop", "matchup": "BKN @ CLE",
     "side": "OVER 20.2 PTS", "player_name": "J. Harden", "stat_type": "PTS",
     "line_value": 20.2, "direction": "over", "confidence": 8, "risk_amount": 30},
    {"slate_date": "2026-02-19", "pick_type": "prop", "matchup": "PHX @ SAS",
     "side": "OVER 11.0 REB", "player_name": "V. Wembanyama", "stat_type": "REB",
     "line_value": 11.0, "direction": "over", "confidence": 9, "risk_amount": 10},
    # FEB 20 — FRIDAY
    # Spreads
    {"slate_date": "2026-02-20", "pick_type": "spread", "matchup": "DAL @ MIN",
     "side": "MIN -12.0", "line_value": 12.0, "direction": "home_spread",
     "confidence": 9, "risk_amount": 50},
    {"slate_date": "2026-02-20", "pick_type": "spread", "matchup": "UTA @ MEM",
     "side": "MEM -4.5", "line_value": 4.5, "direction": "home_spread",
     "confidence": 7, "risk_amount": 30},
    # O/U
    {"slate_date": "2026-02-20", "pick_type": "total", "matchup": "DAL @ MIN",
     "side": "UNDER 235.5", "line_value": 235.5, "direction": "under",
     "confidence": 5, "risk_amount": 30},
    {"slate_date": "2026-02-20", "pick_type": "total", "matchup": "UTA @ MEM",
     "side": "OVER 241.5", "line_value": 241.5, "direction": "over",
     "confidence": 5, "risk_amount": 30},
]


def ensure_picks_in_db():
    """Insert hardcoded picks into DB if not already there."""
    from db.schema import create_all_tables
    create_all_tables(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    inserted = 0
    for p in CURRENT_PICKS:
        try:
            cur.execute("""
                INSERT OR IGNORE INTO picks
                (slate_date, pick_type, matchup, side, player_name, stat_type,
                 line_value, direction, confidence, risk_amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p["slate_date"], p["pick_type"], p["matchup"], p["side"],
                p.get("player_name"), p.get("stat_type"),
                p["line_value"], p["direction"], p["confidence"], p["risk_amount"],
            ))
            if cur.rowcount > 0:
                inserted += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    print(f"Inserted {inserted} new picks into DB")


def get_pending_picks():
    """Get all picks that haven't been graded yet."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    picks = conn.execute("SELECT * FROM picks WHERE result IS NULL").fetchall()
    conn.close()
    return [dict(p) for p in picks]


def fetch_scores():
    """Fetch completed NBA game scores from The Odds API."""
    if not ODDS_API_KEY:
        print("No ODDS_API_KEY — skipping score fetch")
        return {}

    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/scores"
    resp = requests.get(url, params={
        "apiKey": ODDS_API_KEY,
        "daysFrom": 3,
    })

    if resp.status_code != 200:
        print(f"Scores API error: {resp.status_code}")
        return {}

    remaining = resp.headers.get("x-requests-remaining", "?")
    print(f"[Scores API] Fetched — {remaining} API requests remaining")

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
            print(f"  {key}: {away_abbr} {away_score} - {home_abbr} {home_score}")

    return scores


# ── Hardcoded scores + player stats for immediate grading ──
# Fallback when games just completed and Odds API hasn't updated yet.
# The automated system will fetch these from the Odds API / nba_api.
KNOWN_SCORES = {
    "PHX @ SAS": {"home_abbr": "SAS", "away_abbr": "PHX", "home_score": 91, "away_score": 65},
}

KNOWN_PLAYER_STATS = {
    "2026-02-19": {
        "BKN @ CLE": {
            "Mitchell": {"PTS": 17, "REB": 5, "AST": 5},
            "Harden": {"PTS": 16, "REB": 3, "AST": 9},
        },
        "PHX @ SAS": {
            "Wembanyama": {"PTS": 24, "REB": 10, "AST": 3},
        },
    },
}


def get_player_stat(pick, scores):
    """Look up actual player stat for a prop pick.

    First checks KNOWN_PLAYER_STATS (hardcoded from research).
    In the future, this will query nba_api or the DB.
    """
    slate = pick["slate_date"]
    matchup = pick["matchup"]
    player = pick["player_name"]
    stat = pick["stat_type"]

    # Extract last name from "N. Jokic" -> "Jokic"
    last_name = player.split(". ", 1)[-1] if ". " in player else player

    # Check hardcoded stats
    if slate in KNOWN_PLAYER_STATS:
        game_stats = KNOWN_PLAYER_STATS[slate].get(matchup, {})
        if last_name in game_stats:
            return game_stats[last_name].get(stat)

    return None


def compute_profit(result, risk_amount, odds=-110):
    """Compute profit based on result and standard -110 odds."""
    if result == "W":
        return round(risk_amount * (100 / abs(odds)), 2)
    elif result == "L":
        return round(-risk_amount, 2)
    else:  # Push
        return 0.0


def grade_pick(pick, scores):
    """Grade a single pick. Returns (result, profit, actual_value, home_score, away_score) or None if game not completed."""
    matchup = pick["matchup"]

    # Check if game score is available
    game = scores.get(matchup)
    if game is None:
        return None  # Game not completed yet

    home_score = game["home_score"]
    away_score = game["away_score"]

    if pick["pick_type"] == "spread":
        # Spread grading
        # "home_spread" means we bet on the home team covering
        actual_margin = home_score - away_score
        line = pick["line_value"]

        if actual_margin > line:
            result = "W"
        elif actual_margin == line:
            result = "P"
        else:
            result = "L"

        profit = compute_profit(result, pick["risk_amount"])
        return result, profit, actual_margin, home_score, away_score

    elif pick["pick_type"] == "total":
        # O/U grading
        actual_total = home_score + away_score
        line = pick["line_value"]

        if pick["direction"] == "over":
            if actual_total > line:
                result = "W"
            elif actual_total == line:
                result = "P"
            else:
                result = "L"
        else:  # under
            if actual_total < line:
                result = "W"
            elif actual_total == line:
                result = "P"
            else:
                result = "L"

        profit = compute_profit(result, pick["risk_amount"])
        return result, profit, actual_total, home_score, away_score

    elif pick["pick_type"] == "prop":
        # Prop grading
        actual_stat = get_player_stat(pick, scores)
        if actual_stat is None:
            return None  # Can't grade without stats

        line = pick["line_value"]

        if pick["direction"] == "over":
            if actual_stat > line:
                result = "W"
            elif actual_stat == line:
                result = "P"
            else:
                result = "L"
        else:  # under
            if actual_stat < line:
                result = "W"
            elif actual_stat == line:
                result = "P"
            else:
                result = "L"

        profit = compute_profit(result, pick["risk_amount"])
        return result, profit, actual_stat, home_score, away_score

    return None


def update_pick_in_db(pick_id, result, profit, actual_value, home_score, away_score):
    """Write grading result back to the DB."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        UPDATE picks
        SET result = ?, profit = ?, actual_value = ?,
            home_score = ?, away_score = ?,
            graded_at = ?
        WHERE pick_id = ?
    """, (result, profit, actual_value, home_score, away_score,
          datetime.now(timezone.utc).isoformat(), pick_id))
    conn.commit()
    conn.close()


def get_all_picks():
    """Get all picks from DB (graded and pending)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    picks = conn.execute("SELECT * FROM picks ORDER BY slate_date, pick_id").fetchall()
    conn.close()
    return [dict(p) for p in picks]


def main():
    print("=== NBA SIM Pick Grading ===\n")

    # Step 1: Ensure picks are in DB
    ensure_picks_in_db()

    # Step 2: Get pending picks
    pending = get_pending_picks()
    print(f"\nPending picks: {len(pending)}")

    if not pending:
        print("No pending picks to grade")
        return

    # Step 3: Fetch scores (API + hardcoded fallback)
    print("\nFetching completed game scores...")
    scores = fetch_scores()
    # Merge in hardcoded scores for games the API hasn't updated yet
    for key, val in KNOWN_SCORES.items():
        if key not in scores:
            scores[key] = val
            print(f"  (hardcoded) {key}: {val['away_abbr']} {val['away_score']} - {val['home_abbr']} {val['home_score']}")
    print(f"Found {len(scores)} completed games\n")

    # Step 4: Grade each pending pick
    graded = 0
    for pick in pending:
        result = grade_pick(pick, scores)
        if result is None:
            print(f"  PENDING: {pick['matchup']} — {pick['side']} (game not completed)")
            continue

        res, profit, actual, h_score, a_score = result
        update_pick_in_db(pick["pick_id"], res, profit, actual, h_score, a_score)
        graded += 1

        emoji = {"W": "+", "L": "-", "P": "="}[res]
        print(f"  {emoji} {res}: {pick['matchup']} — {pick['side']} | "
              f"Actual: {actual} | Profit: {profit:+.2f} $PP")

    print(f"\nGraded {graded} of {len(pending)} pending picks")

    # Step 5: Build settlement results
    all_picks = get_all_picks()
    record = {"W": 0, "L": 0, "P": 0}
    total_profit = 0.0
    results_list = []

    for p in all_picks:
        if p["result"]:
            record[p["result"]] += 1
            total_profit += p["profit"] or 0
            away, home = p["matchup"].split(" @ ")
            results_list.append({
                "matchup": p["matchup"],
                "side": p["side"],
                "pick_type": p["pick_type"],
                "player_name": p.get("player_name"),
                "result": p["result"],
                "profit": p["profit"],
                "actual_value": p["actual_value"],
                "home_score": p["home_score"],
                "away_score": p["away_score"],
                "risk_amount": p["risk_amount"],
            })

    new_bankroll = round(STARTING_BANKROLL + total_profit, 2)
    pending_count = sum(1 for p in all_picks if p["result"] is None)

    settlement = {
        "graded_at": datetime.now(timezone.utc).isoformat(),
        "picks": results_list,
        "pending_count": pending_count,
        "record": record,
        "total_profit": round(total_profit, 2),
        "starting_bankroll": STARTING_BANKROLL,
        "new_bankroll": new_bankroll,
        "status": "SETTLED" if pending_count == 0 else "PARTIAL",
    }

    # Write results
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)
    out_path = os.path.join(data_dir, "settlement_results.json")

    with open(out_path, "w") as f:
        json.dump(settlement, f, indent=2)

    print(f"\n{'='*50}")
    print(f"Record: {record['W']}-{record['L']}-{record['P']}")
    print(f"P/L: {total_profit:+.2f} $PP")
    print(f"Bankroll: {STARTING_BANKROLL:.0f} → {new_bankroll:.0f} $PP")
    print(f"Status: {settlement['status']} ({pending_count} pending)")
    print(f"\nResults written to: {out_path}")


if __name__ == "__main__":
    main()

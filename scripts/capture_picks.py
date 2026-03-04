#!/usr/bin/env python3
"""
capture_picks.py — Automated pick capture from daily_picks.json.

Reads the SIM's pre-game predictions, filters by confidence threshold,
and logs actionable picks to:
  1. data/picks.csv (backward compat with grade_picks.py / settle_blog.py)
  2. picks DB table (full metadata)
  3. data/pick_log.json (append-only audit trail)

Usage:
  python scripts/capture_picks.py [--threshold 65] [--dry-run]
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import DB_PATH
from db.connection import execute, read_query


PICKS_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "picks.csv")
DAILY_JSON = os.path.join(os.path.dirname(__file__), "..", "data", "daily_picks.json")
PICK_LOG = os.path.join(os.path.dirname(__file__), "..", "data", "pick_log.json")


def conf_to_1_10(confidence):
    """Convert 35-96 confidence to 1-10 display scale."""
    return round((abs(confidence - 50) / 46) * 10)


def risk_amount(conf_1_10):
    """Determine risk amount from 1-10 confidence scale."""
    if conf_1_10 >= 8:
        return 50
    elif conf_1_10 >= 5:
        return 30
    return 20


def existing_picks(slate_date):
    """Return set of (matchup, side) already in picks.csv for this date."""
    existing = set()
    if not os.path.exists(PICKS_CSV):
        return existing
    with open(PICKS_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["date"] == slate_date:
                existing.add((row["matchup"], row["side"]))
    return existing


def capture(threshold=65, dry_run=False):
    """Read daily_picks.json, filter, and log picks."""
    if not os.path.exists(DAILY_JSON):
        print("[capture] No daily_picks.json found. Run generate_frontend.py first.")
        return []

    with open(DAILY_JSON) as f:
        snapshot = json.load(f)

    raw_slate_date = snapshot["slate_date"]
    generated_at = snapshot["generated_at"]
    now = datetime.now(timezone.utc).isoformat()

    # Normalize date to YYYY-MM-DD format (daily_picks.json uses "MAR 4" format)
    if raw_slate_date and not raw_slate_date[0].isdigit():
        try:
            dt = datetime.strptime(raw_slate_date, "%b %d")
            slate_date = dt.replace(year=datetime.now().year).strftime("%Y-%m-%d")
        except ValueError:
            try:
                dt = datetime.strptime(raw_slate_date, "%B %d")
                slate_date = dt.replace(year=datetime.now().year).strftime("%Y-%m-%d")
            except ValueError:
                slate_date = raw_slate_date  # fallback
    else:
        slate_date = raw_slate_date

    print(f"[capture] Slate: {slate_date} | Generated: {generated_at}")
    print(f"[capture] Threshold: >{threshold} or <{100 - threshold}")

    already = existing_picks(slate_date)
    picks = []

    for g in snapshot["games"]:
        conf = g["confidence"]
        edge = g["spread_edge"]

        # Skip games without real sportsbook lines
        if g["book_spread"] is None:
            continue

        # Filter: only actionable picks (strong edge)
        # Skip if confidence is in the neutral zone (35-65 = no meaningful edge)
        if (100 - threshold) <= conf <= threshold:
            continue

        pick_text = g["pick_text"]
        pick_type = g["pick_type"]
        matchup = g["matchup"]

        # Determine side direction
        if conf > 50:
            # Home favored by model more than book
            direction = "HOME"
        else:
            direction = "AWAY"

        c10 = conf_to_1_10(conf)
        risk = risk_amount(c10)

        # Extract line value from pick_text (e.g., "LAL +3.5" → 3.5, "MIN ML" → 0)
        ml_odds = None
        if "ML" in pick_text:
            line_val = 0.0
            pick_type = "ml"
            # Store actual moneyline odds for correct payout calculation
            team = pick_text.replace(" ML", "").strip()
            home = g["matchup"].split(" @ ")[1]
            if team == home:
                ml_odds = g.get("home_ml")
            else:
                ml_odds = g.get("away_ml")
        else:
            parts = pick_text.split()
            line_val = float(parts[-1]) if len(parts) >= 2 else 0.0

        # Dedup check
        if (matchup, pick_text) in already:
            print(f"  SKIP (exists): {matchup} → {pick_text}")
            continue

        pick = {
            "slate_date": slate_date,
            "matchup": matchup,
            "side": pick_text,
            "pick_type": pick_type,
            "direction": direction,
            "line_value": line_val,
            "confidence": conf,
            "conf_1_10": c10,
            "risk": risk,
            "sim_spread": g["sim_spread"],
            "book_spread": g["book_spread"],
            "spread_edge": edge,
            "sim_total": g["sim_total"],
            "book_total": g["book_total"],
            "raw_edge": g["raw_edge"],
            "captured_at": now,
            "conf_label": g["conf_label"],
            "ml_odds": ml_odds,
        }
        picks.append(pick)
        tag = "W" if c10 >= 8 else "M"  # max or mid unit
        print(f"  PICK [{tag}]: {matchup} → {pick_text} | conf={conf:.0f} ({c10}/10) | edge={edge:+.1f} | {risk} $PP")

    if not picks:
        print("[capture] No actionable picks found.")
        return []

    if dry_run:
        print(f"\n[capture] DRY RUN — {len(picks)} picks would be logged.")
        return picks

    # ── Write to CSV ──
    csv_exists = os.path.exists(PICKS_CSV)
    with open(PICKS_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        if not csv_exists:
            writer.writerow(["date", "matchup", "side", "type", "risk", "result", "profit", "odds"])
        for p in picks:
            odds_val = p.get("ml_odds") or ""
            writer.writerow([p["slate_date"], p["matchup"], p["side"], p["pick_type"], p["risk"], "", "", odds_val])

    print(f"[capture] Appended {len(picks)} picks to {PICKS_CSV}")

    # ── Write to DB ──
    for p in picks:
        try:
            execute("""
                INSERT OR IGNORE INTO picks
                    (slate_date, pick_type, matchup, side, line_value, direction,
                     confidence, risk_amount, sim_spread, book_spread, spread_edge,
                     sim_total, book_total, raw_edge, captured_at, conf_1_10)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, DB_PATH, [
                p["slate_date"], p["pick_type"], p["matchup"], p["side"],
                p["line_value"], p["direction"], p["confidence"], p["risk"],
                p["sim_spread"], p["book_spread"], p["spread_edge"],
                p["sim_total"], p["book_total"], p["raw_edge"],
                p["captured_at"], p["conf_1_10"],
            ])
        except Exception as e:
            print(f"  DB insert failed for {p['matchup']}: {e}")

    print(f"[capture] Inserted {len(picks)} picks to DB")

    # ── Append to audit log ──
    log_entries = []
    if os.path.exists(PICK_LOG):
        with open(PICK_LOG) as f:
            log_entries = json.load(f)

    for p in picks:
        log_entries.append({
            **p,
            "generated_at": generated_at,
        })

    with open(PICK_LOG, "w") as f:
        json.dump(log_entries, f, indent=2)

    print(f"[capture] Audit log updated: {len(log_entries)} total entries")

    return picks


def main():
    parser = argparse.ArgumentParser(description="Capture SIM picks from daily snapshot")
    parser.add_argument("--threshold", type=int, default=65,
                        help="Confidence threshold (default 65 = picks >65 or <35)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview picks without saving")
    args = parser.parse_args()

    # Ensure DB schema has new columns (ALTER TABLE is idempotent via try/except)
    new_cols = [
        ("sim_spread", "REAL"),
        ("book_spread", "REAL"),
        ("spread_edge", "REAL"),
        ("sim_total", "REAL"),
        ("book_total", "REAL"),
        ("raw_edge", "REAL"),
        ("captured_at", "TEXT"),
        ("conf_1_10", "INTEGER"),
    ]
    for col_name, col_type in new_cols:
        try:
            execute(f"ALTER TABLE picks ADD COLUMN {col_name} {col_type}", DB_PATH)
        except Exception:
            pass  # Column already exists

    picks = capture(threshold=args.threshold, dry_run=args.dry_run)
    print(f"\n[capture] Done. {len(picks)} picks captured for today's slate.")


if __name__ == "__main__":
    main()

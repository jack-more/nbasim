#!/usr/bin/env python3
"""
generate_blog_entry.py — Generate blog HTML snippet from captured picks.

Reads today's picks from data/picks.csv (or pick_log.json) and generates
blog-ready HTML matching the MORELLOSIMS pick card format.

Output: data/blog_snippet.html

Usage:
  python scripts/generate_blog_entry.py [--date 2026-03-01]
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PICKS_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "picks.csv")
PICK_LOG = os.path.join(os.path.dirname(__file__), "..", "data", "pick_log.json")
DAILY_JSON = os.path.join(os.path.dirname(__file__), "..", "data", "daily_picks.json")
OUTPUT = os.path.join(os.path.dirname(__file__), "..", "data", "blog_snippet.html")

DAYS_OF_WEEK = {0: "MONDAY", 1: "TUESDAY", 2: "WEDNESDAY", 3: "THURSDAY",
                4: "FRIDAY", 5: "SATURDAY", 6: "SUNDAY"}


def load_picks_for_date(target_date):
    """Load picks from pick_log.json for a specific date."""
    picks = []

    # Try pick_log.json first (has full metadata)
    if os.path.exists(PICK_LOG):
        with open(PICK_LOG) as f:
            log = json.load(f)
        for entry in log:
            if entry.get("slate_date") == target_date:
                picks.append(entry)

    # Fallback to CSV if no log entries
    if not picks and os.path.exists(PICKS_CSV):
        with open(PICKS_CSV) as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["date"] == target_date:
                    picks.append({
                        "slate_date": row["date"],
                        "matchup": row["matchup"],
                        "side": row["side"],
                        "pick_type": row["type"],
                        "risk": int(float(row["risk"])) if row["risk"] else 30,
                        "conf_1_10": 7,
                        "confidence": 65,
                        "spread_edge": 0,
                        "sim_spread": None,
                        "book_spread": None,
                        "sim_total": None,
                        "book_total": None,
                    })

    return picks


def load_game_data(target_date):
    """Load full game data from daily_picks.json if date matches."""
    if not os.path.exists(DAILY_JSON):
        return {}
    with open(DAILY_JSON) as f:
        snap = json.load(f)
    if snap.get("slate_date") != target_date:
        return {}
    return {g["matchup"]: g for g in snap.get("games", [])}


def implied_scores(matchup, game_data):
    """Get implied home/away scores from game data."""
    gd = game_data.get(matchup, {})
    st = gd.get("sim_total")
    ss = gd.get("sim_spread")
    if st and ss:
        home_imp = round((st - ss) / 2)
        away_imp = round((st + ss) / 2)
        away, home = matchup.split(" @ ")
        return f"IMPLIED: {away} {away_imp} — {home} {home_imp}"
    return None


def generate_pick_card(pick, game_data):
    """Generate a single pick card HTML."""
    matchup = pick["matchup"]
    side = pick["side"]
    risk = pick.get("risk", 30)
    c10 = pick.get("conf_1_10", 7)
    pick_type = pick.get("pick_type", "spread")
    edge = pick.get("spread_edge", 0)

    # Confidence badge
    type_label = "ML" if pick_type == "ml" else "SPREAD"
    conf_bg = "rgba(42,157,95,0.12)" if c10 >= 8 else "rgba(42,157,95,0.08)" if c10 >= 6 else "rgba(42,157,95,0.05)"

    implied = implied_scores(matchup, game_data)
    implied_line = ""
    if implied:
        implied_line = f'<p class="mono" style="font-size:8px; color:rgba(255,255,255,0.35); margin:0 0 4px; letter-spacing:0.5px;">{implied}</p>'

    rationale = f"SIM edge: {edge:+.1f} pts vs book. " if edge else ""
    if pick.get("sim_spread") is not None and pick.get("book_spread") is not None:
        rationale += f"SIM spread: {pick['sim_spread']:+.1f}, Book: {pick['book_spread']:+.1f}. "

    return f"""
                    <div style="margin:8px 0 6px; padding:10px 12px; background:{conf_bg}; border-left:3px solid #2a9d5f; border-radius:0 4px 4px 0;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                            <p class="mono" style="font-size:10px; color:#2a9d5f; font-weight:700; letter-spacing:1px; margin:0;">{matchup} — {side}</p>
                            <div style="display:flex; gap:6px; align-items:center;">
                                <span class="mono" style="font-size:9px; background:#f4a261; color:#000; padding:2px 6px; border-radius:2px; font-weight:700;">{risk} $PP</span>
                                <span class="mono" style="font-size:9px; background:#2a9d5f; color:#000; padding:2px 6px; border-radius:2px; font-weight:700;">{type_label} {c10}</span>
                            </div>
                        </div>
                        {implied_line}
                        <p class="mono" style="font-size:8px; color:#FFD600; margin:0 0 4px; font-weight:700; letter-spacing:0.5px;">PENDING</p>
                        <p class="blog-body-text" style="font-size:10px; color:#999; margin:0;">{rationale}</p>
                    </div>"""


def generate_table_row(pick, idx):
    """Generate a table row for the picks tracker."""
    bg_opacity = 0.06 - (idx % 3) * 0.02
    conf_color = "#00FF55" if pick.get("conf_1_10", 7) >= 8 else "#7FFF00" if pick.get("conf_1_10", 7) >= 6 else "#FFD600"
    return f"""                                <tr style="border-bottom:1px solid #1a1a1a; background:rgba(42,157,95,{bg_opacity:.2f});">
                                    <td style="padding:6px 10px; color:#e0e0e0;">{pick['matchup']}</td>
                                    <td style="padding:6px 10px; color:#2a9d5f;">{pick['side']}</td>
                                    <td style="padding:6px 10px; text-align:center; color:rgba(255,255,255,0.35); font-size:9px;">—</td>
                                    <td style="padding:6px 10px; text-align:center; color:{conf_color}; font-weight:700;">{pick.get('conf_1_10', 7)}</td>
                                    <td style="padding:6px 10px; text-align:right; color:#f4a261; font-weight:700;">{pick.get('risk', 30)}</td>
                                    <td style="padding:6px 10px; text-align:center; color:#FFD600; font-weight:700;">&mdash;</td>
                                </tr>"""


def generate_blog_snippet(target_date, picks, game_data):
    """Generate full blog snippet for a date."""
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    day_name = DAYS_OF_WEEK[dt.weekday()]
    month_day = dt.strftime("%b").upper() + " " + str(dt.day)

    total_risk = sum(p.get("risk", 30) for p in picks)
    spread_count = sum(1 for p in picks if p.get("pick_type") != "ml")
    ml_count = sum(1 for p in picks if p.get("pick_type") == "ml")

    type_text = f"{spread_count} SPREAD{'S' if spread_count != 1 else ''}"
    if ml_count:
        type_text += f" + {ml_count} ML"

    # Slate header
    html = f"""
                    <!-- {'═' * 46} -->
                    <!-- {month_day} SLATE ({day_name}){' ' * (37 - len(month_day) - len(day_name))} -->
                    <!-- {'═' * 46} -->
                    <div style="margin:24px 0 6px; padding:8px 12px; background:rgba(0,255,85,0.06); border:1px solid rgba(0,255,85,0.15); border-radius:4px;">
                        <p class="mono" style="font-size:11px; color:#00FF55; letter-spacing:2px; font-weight:700; margin:0;">{month_day} SLATE &nbsp;·&nbsp; {day_name}</p>
                        <p class="mono" style="font-size:8px; color:rgba(255,255,255,0.3); letter-spacing:1px; margin:2px 0 0;">{type_text} &nbsp;·&nbsp; {total_risk} $PP RISKED</p>
                    </div>

                    <p class="mono" style="font-size:10px; color:#2a9d5f; letter-spacing:2px; margin:12px 0 8px; font-weight:700;">▎ GAME LINES — {type_text}</p>
"""

    # Pick cards
    for p in picks:
        html += generate_pick_card(p, game_data)

    # Table rows
    table_html = f"""                                <!-- {month_day} — {day_name} -->
                                <tr><td colspan="6" style="padding:12px 10px 4px; color:#00FF55; font-size:9px; letter-spacing:2px; font-weight:700; border-bottom:1px solid rgba(0,255,85,0.15);">{month_day} — {day_name}</td></tr>
"""
    for i, p in enumerate(picks):
        table_html += generate_table_row(p, i) + "\n"

    return html, table_html


def main():
    parser = argparse.ArgumentParser(description="Generate blog HTML from captured picks")
    parser.add_argument("--date", type=str, default=None,
                        help="Target date (YYYY-MM-DD). Default: today or daily_picks.json date")
    args = parser.parse_args()

    # Determine date
    if args.date:
        target_date = args.date
    elif os.path.exists(DAILY_JSON):
        with open(DAILY_JSON) as f:
            raw_date = json.load(f).get("slate_date", "")
            # slate_date can be "MAR 3" format — convert to YYYY-MM-DD
            if raw_date and not raw_date[0].isdigit():
                try:
                    dt_parsed = datetime.strptime(raw_date, "%b %d")
                    target_date = dt_parsed.replace(year=datetime.now().year).strftime("%Y-%m-%d")
                except ValueError:
                    try:
                        dt_parsed = datetime.strptime(raw_date, "%B %d")
                        target_date = dt_parsed.replace(year=datetime.now().year).strftime("%Y-%m-%d")
                    except ValueError:
                        target_date = datetime.now().strftime("%Y-%m-%d")
            elif raw_date:
                target_date = raw_date
            else:
                target_date = datetime.now().strftime("%Y-%m-%d")
    else:
        target_date = datetime.now().strftime("%Y-%m-%d")

    picks = load_picks_for_date(target_date)
    if not picks:
        print(f"[blog] No picks found for {target_date}")
        return

    game_data = load_game_data(target_date)

    cards_html, table_html = generate_blog_snippet(target_date, picks, game_data)

    output = {
        "date": target_date,
        "pick_count": len(picks),
        "total_risk": sum(p.get("risk", 30) for p in picks),
        "cards_html": cards_html,
        "table_html": table_html,
    }

    with open(OUTPUT, "w") as f:
        f.write(f"<!-- Blog snippet for {target_date} -->\n")
        f.write(f"<!-- {len(picks)} picks, {output['total_risk']} $PP risked -->\n\n")
        f.write("<!-- ═══ PICK CARDS (insert before picks table) ═══ -->\n")
        f.write(cards_html)
        f.write("\n\n<!-- ═══ TABLE ROWS (insert before </tbody>) ═══ -->\n")
        f.write(table_html)

    print(f"[blog] Generated snippet: {len(picks)} picks for {target_date} → {OUTPUT}")


if __name__ == "__main__":
    main()

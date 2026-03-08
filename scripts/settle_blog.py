#!/usr/bin/env python3
"""
settle_blog.py — Patch MORELLOSIMS blog with graded pick results.

Reads settlement_results.json and patches the blog HTML:
  - Fill Result column (— → W/L/P)
  - Update bankroll display
  - Update record + status
  - Add FINAL score lines to pick cards

Usage:
  python scripts/settle_blog.py <settlement_results.json> <morellosims_index.html>
"""

import csv
import json
import os
import re
import sys


# Nickname → last name mappings for table matching
PLAYER_NICKNAMES = {
    "Wembanyama": "Wemby",
}

RESULT_STYLES = {
    "W": 'style="padding:6px 10px; text-align:center; color:#00FF55; font-weight:700;"',
    "L": 'style="padding:6px 10px; text-align:center; color:#FF4444; font-weight:700;"',
    "P": 'style="padding:6px 10px; text-align:center; color:#FFD600; font-weight:700;"',
}


def patch_results_table(html, picks):
    """Replace &mdash; with W/L/P in the picks tracker table rows."""
    changes = 0

    for p in picks:
        matchup = p["matchup"]
        side = p["side"]
        result = p["result"]

        if not result:
            continue

        style = RESULT_STYLES[result]

        # Escape regex special chars in side text
        side_escaped = re.escape(side)
        matchup_parts = matchup.split(" @ ")
        if len(matchup_parts) != 2:
            continue
        away, home = matchup_parts

        # For spread/total picks: match row with matchup + side in <td> elements
        # Pattern: find <tr> containing the matchup text and the side text,
        # then replace the last <td> that contains &mdash;
        pick_type = p.get("pick_type", p.get("type", "spread"))
        if pick_type in ("spread", "ml"):
            # Spread/ML rows: "BKN @ CLE" in first td, "CLE -16.0" or "GSW ML" in second td
            pattern = re.compile(
                rf'(<tr[^>]*>.*?>{re.escape(away)} @ {re.escape(home)}</td>'
                rf'.*?>{side_escaped}</td>'
                rf'.*?)<td[^>]*>\s*&mdash;\s*</td>',
                re.DOTALL,
            )
        elif pick_type == "total":
            # O/U rows: "BKN @ CLE" in first td, "OVER 229.5" or "UNDER 235.5" in second td
            pattern = re.compile(
                rf'(<tr[^>]*>.*?>{re.escape(away)} @ {re.escape(home)}</td>'
                rf'.*?>{side_escaped}</td>'
                rf'.*?)<td[^>]*>\s*&mdash;\s*</td>',
                re.DOTALL,
            )
        elif pick_type == "prop":
            # Prop rows: "Jokic PTS" or "Mitchell PTS" in first td, "OVER 28.5" in second td
            # Extract player last name and stat for matching
            player = p.get("player_name", "")
            last_name = player.split(". ", 1)[-1] if ". " in player else player
            # Use nickname if available (e.g., Wembanyama → Wemby)
            table_name = PLAYER_NICKNAMES.get(last_name, last_name)
            # Side is like "OVER 28.5 PTS" — in the table it's just "OVER 28.5"
            side_short = re.sub(r' (PTS|REB|AST|PRA|STL\+BLK)$', '', side)
            pattern = re.compile(
                rf'(<tr[^>]*>.*?>{re.escape(table_name)}[^<]*</td>'
                rf'.*?>{re.escape(side_short)}</td>'
                rf'.*?)<td[^>]*>\s*&mdash;\s*</td>',
                re.DOTALL,
            )
        else:
            continue

        replacement = rf'\1<td {style}>{result}</td>'
        new_html = pattern.sub(replacement, html, count=1)
        if new_html != html:
            changes += 1
            html = new_html
            print(f"  Updated result: {matchup} — {side} → {result}")

    return html, changes


def patch_bankroll(html, new_bankroll, starting=1000):
    """Update bankroll display in the blog."""
    changes = 0

    # Color based on profit/loss
    if new_bankroll > starting:
        color = "#00FF55"
    elif new_bankroll < starting:
        color = "#FF4444"
    else:
        color = "#f4a261"

    # Patch main bankroll box: "1,449 $PP"
    old_bankroll_pattern = re.compile(
        r'(BANKROLL</div>\s*<div[^>]*>)\s*[\d,]+ \$PP'
    )
    new_html = old_bankroll_pattern.sub(
        rf'\g<1>{new_bankroll:,.0f} $PP', html
    )
    if new_html != html:
        changes += 1
        html = new_html

    # Patch summary bankroll number (bottom section)
    old_summary = re.compile(
        r'(BANKROLL</div>\s*<div[^>]*font-size:16px[^>]*>)\s*[\d,]+'
    )
    new_html = old_summary.sub(rf'\g<1>{new_bankroll:,.0f}', html)
    if new_html != html:
        changes += 1
        html = new_html

    return html, changes


def patch_hero_stats(html, record, bankroll, total_picks, total_risked):
    """Update the hero stat bar (record, ROI, bankroll, picks)."""
    changes = 0

    wins = record.get("W", 0)
    losses = record.get("L", 0)
    record_str = f"{wins}-{losses}"

    # Compute ROI on settled risked
    profit = bankroll - 1000
    roi_pct = round(profit / total_risked * 100) if total_risked > 0 else 0
    roi_sign = "+" if roi_pct >= 0 else ""

    # Patch hero record: <span class="stat-value">XX-XX</span>\n..RECORD
    old_record = re.compile(
        r'(<span class="stat-value">)[\d]+-[\d]+(<\/span>\s*<span class="stat-label">RECORD)'
    )
    new_html = old_record.sub(rf'\g<1>{record_str}\2', html)
    if new_html != html:
        changes += 1
        html = new_html

    # Patch hero ROI
    old_roi = re.compile(
        r'(<span class="stat-value">)[+-]?\d+%(<\/span>\s*<span class="stat-label">ROI)'
    )
    new_html = old_roi.sub(rf'\g<1>{roi_sign}{roi_pct}%\2', html)
    if new_html != html:
        changes += 1
        html = new_html

    # Patch hero bankroll
    old_bankroll = re.compile(
        r'(<span class="stat-value">)[\d,]+(<\/span>\s*<span class="stat-label">BANKROLL)'
    )
    new_html = old_bankroll.sub(rf'\g<1>{bankroll:,.0f}\2', html)
    if new_html != html:
        changes += 1
        html = new_html

    # Patch hero picks count
    old_picks = re.compile(
        r'(<span class="stat-value">)\d+(<\/span>\s*<span class="stat-label">PICKS)'
    )
    new_html = old_picks.sub(rf'\g<1>{total_picks}\2', html)
    if new_html != html:
        changes += 1
        html = new_html

    # Patch total risked in bankroll box and tfoot
    old_risked = re.compile(r'(TOTAL RISKED</div>\s*<div[^>]*>)\s*[\d,]+ \$PP')
    new_html = old_risked.sub(rf'\g<1>{total_risked:,.0f} $PP', html)
    if new_html != html:
        changes += 1
        html = new_html

    # Patch tfoot risked
    old_tfoot = re.compile(r'(TOTAL RISKED</td>\s*<td[^>]*>)\s*[\d,]+ \$PP')
    new_html = old_tfoot.sub(rf'\g<1>{total_risked:,.0f} $PP', html)
    if new_html != html:
        changes += 1
        html = new_html

    # Patch summary section risked
    old_summary_risked = re.compile(
        r'(RISKED</div>\s*<div[^>]*font-size:16px[^>]*>)\s*[\d,]+'
    )
    new_html = old_summary_risked.sub(rf'\g<1>{total_risked:,.0f}', html)
    if new_html != html:
        changes += 1
        html = new_html

    # Patch summary section picks
    old_summary_picks = re.compile(
        r'(PICKS</div>\s*<div[^>]*font-size:16px[^>]*>)\s*\d+'
    )
    new_html = old_summary_picks.sub(rf'\g<1>{total_picks}', html)
    if new_html != html:
        changes += 1
        html = new_html

    # Patch blog preview text
    old_preview = re.compile(r'\d+ picks across \d+ slates')
    new_html = old_preview.sub(f'{total_picks} picks across {wins + losses} slates', html)
    if new_html != html:
        changes += 1
        html = new_html

    # Patch blog title: "NBA SIM: XX-XX RECORD (+XX% ROI)"
    old_title = re.compile(r'(NBA SIM: )\d+-\d+ RECORD \([+-]?\d+% ROI\)')
    new_html = old_title.sub(rf'\g<1>{record_str} RECORD ({roi_sign}{roi_pct}% ROI)', html)
    if new_html != html:
        changes += 1
        html = new_html

    # Patch summary section record: "XX-XX-0"
    old_summary_record = re.compile(
        r'(RECORD</div>\s*<div[^>]*font-size:16px[^>]*>)\s*\d+-\d+-\d+'
    )
    new_html = old_summary_record.sub(rf'\g<1>{record_str}-0', html)
    if new_html != html:
        changes += 1
        html = new_html

    return html, changes


def patch_pick_cards(html, picks):
    """Replace PENDING with FINAL score line on pick cards that have been graded."""
    changes = 0

    for p in picks:
        pick_type = p.get("pick_type", p.get("type", "spread"))
        if not p["result"] or pick_type == "prop":
            continue  # Only add final score to game line cards

        matchup = p["matchup"]
        away, home = matchup.split(" @ ")
        h_score = p.get("home_score")
        a_score = p.get("away_score")
        result = p["result"]
        profit = p["profit"]

        if pick_type not in ("spread", "ml"):
            continue

        has_scores = h_score is not None and a_score is not None

        # Skip if FINAL already exists for this matchup
        if has_scores and re.search(rf'FINAL: {re.escape(away)} \d+ — {re.escape(home)} \d+', html):
            continue

        result_emoji = "+" if result == "W" else "-" if result == "L" else "="
        result_color = "#00FF55" if result == "W" else "#FF4444" if result == "L" else "#FFD600"

        if has_scores:
            final_text = (
                f'FINAL: {away} {a_score} — {home} {h_score} | '
                f'{p["side"]} {result} ({result_emoji}{abs(profit):.0f} $PP)'
            )
        else:
            final_text = (
                f'{p["side"]} {result} ({result_emoji}{abs(profit):.0f} $PP)'
            )

        # Strategy 1: Replace PENDING text inside a pick card with matching matchup
        # Match: data-matchup="XXX @ YYY" ... >PENDING</p>
        pending_pattern = re.compile(
            rf'(data-matchup="{re.escape(matchup)}".*?)'
            rf'<p class="mono"[^>]*color:#FFD600[^>]*>\s*PENDING\s*</p>',
            re.DOTALL,
        )
        final_replacement = (
            rf'\1<p class="mono" style="font-size:8px; color:{result_color}; '
            f'margin:0 0 4px; font-weight:700; letter-spacing:0.5px;">'
            f'{final_text}</p>'
        )
        new_html = pending_pattern.sub(final_replacement, html, count=1)
        if new_html != html:
            changes += 1
            html = new_html
            print(f"  Updated card: {matchup} — PENDING → {final_text}")

            # Also update data-status from pending to settled
            status_pattern = re.compile(
                rf'data-status="pending"(\s+data-matchup="{re.escape(matchup)}")'
            )
            html = status_pattern.sub(r'data-status="settled"\1', html, count=1)
            continue

        # Strategy 2 (fallback): Find IMPLIED line and add FINAL after it
        implied_pattern = re.compile(
            rf'(IMPLIED: {re.escape(away)} \d+ .{{1,5}} {re.escape(home)} \d+)'
        )
        final_line = (
            f'\\1</p>'
            f'<p class="mono" style="font-size:8px; color:{result_color}; '
            f'margin:0 0 4px; font-weight:700; letter-spacing:0.5px;">'
            f'{final_text}'
        )
        new_html = implied_pattern.sub(final_line, html, count=1)
        if new_html != html:
            changes += 1
            html = new_html
            print(f"  Added FINAL (implied): {matchup} — {away} {a_score}, {home} {h_score}")

    return html, changes


def patch_day_summaries(html, picks):
    """Update day summary records from PENDING to actual W-L record."""
    changes = 0

    # Group settled picks by date
    from collections import defaultdict
    daily = defaultdict(lambda: {"W": 0, "L": 0, "P": 0, "profit": 0.0})
    for p in picks:
        if not p.get("result"):
            continue
        date = p["date"]
        daily[date][p["result"]] += 1
        daily[date]["profit"] += float(p.get("profit", 0))

    # Date label map: "2026-03-06" → "MAR 6"
    month_names = {
        "01": "JAN", "02": "FEB", "03": "MAR", "04": "APR",
        "05": "MAY", "06": "JUN", "07": "JUL", "08": "AUG",
        "09": "SEP", "10": "OCT", "11": "NOV", "12": "DEC",
    }

    for date_str, rec in daily.items():
        parts = date_str.split("-")
        month = month_names.get(parts[1], parts[1])
        day = str(int(parts[2]))  # Remove leading zero
        label = f"{month} {day}"

        wins = rec["W"]
        losses = rec["L"]
        total_profit = rec["profit"]

        # Determine color: green if winning, red if losing
        if wins > losses:
            color = "#00FF55"
        elif losses > wins:
            color = "#FF4444"
        else:
            color = "#FFD600"

        profit_sign = "+" if total_profit >= 0 else ""
        record_text = f'{wins}-{losses} · {profit_sign}{total_profit:.0f} $PP'

        # Find the day summary with this label and PENDING
        day_pattern = re.compile(
            rf'(<span class="slate-day-label">{re.escape(label)} · [A-Z]+</span>'
            rf'.*?</div>\s*)'
            rf'<span class="slate-day-record"[^>]*>PENDING</span>',
            re.DOTALL,
        )
        replacement = (
            rf'\1<span class="slate-day-record" style="color:{color};">'
            f'{record_text}</span>'
        )
        new_html = day_pattern.sub(replacement, html, count=1)
        if new_html != html:
            changes += 1
            html = new_html
            print(f"  Updated day: {label} → {record_text}")

    return html, changes


def compute_stats_from_csv(csv_path):
    """Compute record, bankroll, totals from picks.csv."""
    wins = 0
    losses = 0
    pushes = 0
    total_profit = 0.0
    total_risked = 0
    total_picks = 0

    if not os.path.exists(csv_path):
        return None

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_picks += 1
            risk = int(float(row.get("risk", 0) or 0))
            total_risked += risk

            result = row.get("result", "").strip()
            profit = float(row.get("profit", 0) or 0)

            if result == "W":
                wins += 1
                total_profit += profit
            elif result == "L":
                losses += 1
                total_profit += profit  # profit is negative for L
            elif result == "P":
                pushes += 1

    bankroll = 1000 + total_profit
    return {
        "record": {"W": wins, "L": losses, "P": pushes},
        "bankroll": round(bankroll),
        "total_profit": total_profit,
        "total_picks": total_picks,
        "total_risked": total_risked,
    }


def main():
    if len(sys.argv) != 3:
        print("Usage: python settle_blog.py <settlement_results.json> <blog_html>")
        sys.exit(1)

    results_path = sys.argv[1]
    blog_path = sys.argv[2]

    with open(results_path) as f:
        settlement = json.load(f)

    with open(blog_path) as f:
        html = f.read()

    picks = settlement["picks"]

    total_changes = 0

    # Patch results table
    print("Patching results table...")
    html, c = patch_results_table(html, picks)
    total_changes += c

    # Patch pick cards with FINAL scores
    print("Patching pick cards with final scores...")
    html, c = patch_pick_cards(html, picks)
    total_changes += c

    # Patch day summary records (PENDING → W-L · profit)
    print("Patching day summaries...")
    html, c = patch_day_summaries(html, picks)
    total_changes += c

    # Compute stats from CSV (source of truth) for hero stats + bankroll
    csv_path = os.path.join(os.path.dirname(results_path), "picks.csv")
    stats = compute_stats_from_csv(csv_path)

    if stats:
        record = stats["record"]
        bankroll = stats["bankroll"]
        total_picks = stats["total_picks"]
        total_risked = stats["total_risked"]

        print(f"\nCSV stats: {record['W']}-{record['L']} | "
              f"P/L: {stats['total_profit']:+.2f} | "
              f"Bankroll: {bankroll} | Picks: {total_picks} | Risked: {total_risked}")

        # Patch bankroll box
        print("Patching bankroll...")
        html, c = patch_bankroll(html, bankroll)
        total_changes += c

        # Patch hero stats (record, ROI, bankroll, picks)
        print("Patching hero stats...")
        html, c = patch_hero_stats(html, record, bankroll, total_picks, total_risked)
        total_changes += c
    else:
        print("WARNING: Could not find picks.csv — skipping hero stat update")

    print(f"\nTotal changes: {total_changes}")

    with open(blog_path, "w") as f:
        f.write(html)

    print(f"Blog updated: {blog_path}")


if __name__ == "__main__":
    main()

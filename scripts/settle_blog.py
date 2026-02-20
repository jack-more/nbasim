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

import json
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
        if p["pick_type"] == "spread":
            # Spread rows: "BKN @ CLE" in first td, "CLE -16.0" in second td
            pattern = re.compile(
                rf'(<tr[^>]*>.*?>{re.escape(away)} @ {re.escape(home)}</td>'
                rf'.*?>{side_escaped}</td>'
                rf'.*?)<td[^>]*>\s*&mdash;\s*</td>',
                re.DOTALL,
            )
        elif p["pick_type"] == "total":
            # O/U rows: "BKN @ CLE" in first td, "OVER 229.5" or "UNDER 235.5" in second td
            pattern = re.compile(
                rf'(<tr[^>]*>.*?>{re.escape(away)} @ {re.escape(home)}</td>'
                rf'.*?>{side_escaped}</td>'
                rf'.*?)<td[^>]*>\s*&mdash;\s*</td>',
                re.DOTALL,
            )
        elif p["pick_type"] == "prop":
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

    # Patch main bankroll display: "1,000 $PP" → "943 $PP"
    old_bankroll_pattern = re.compile(
        r'(BANKROLL</div>\s*<div[^>]*>)\s*[\d,]+ \$PP'
    )
    new_html = old_bankroll_pattern.sub(
        rf'\g<1>{new_bankroll:,.0f} $PP', html
    )
    if new_html != html:
        changes += 1
        html = new_html

    # Update bankroll color
    old_color = re.compile(r'(BANKROLL</div>\s*<div[^>]*style="[^"]*color:)#f4a261')
    html = old_color.sub(rf'\g<1>{color}', html)

    # Patch summary bankroll number
    old_summary = re.compile(
        r'(BANKROLL</div>\s*<div[^>]*font-size:16px[^>]*>)\s*[\d,]+'
    )
    new_html = old_summary.sub(rf'\g<1>{new_bankroll:,.0f}', html)
    if new_html != html:
        changes += 1
        html = new_html

    return html, changes


def patch_record_and_status(html, record, status):
    """Update record and status displays."""
    changes = 0
    record_str = f"{record['W']}-{record['L']}-{record['P']}"

    # Patch record: "—" → "2-5-0"
    old_record = re.compile(
        r'(RECORD</div>\s*<div[^>]*>)\s*&mdash;'
    )
    new_html = old_record.sub(rf'\g<1>{record_str}', html)
    if new_html != html:
        changes += 1
        html = new_html

    # Patch status: "PENDING" → "PARTIAL" or "SETTLED"
    old_status = re.compile(
        r'(STATUS</div>\s*<div[^>]*>)\s*PENDING'
    )
    status_color = "#00FF55" if status == "SETTLED" else "#f4a261"
    new_html = old_status.sub(rf'\g<1>{status}', html)
    if new_html != html:
        changes += 1
        html = new_html

    return html, changes


def patch_pick_cards(html, picks):
    """Add FINAL score line to pick cards that have been graded."""
    changes = 0

    for p in picks:
        if not p["result"] or p["pick_type"] == "prop":
            continue  # Only add final score to game line cards

        matchup = p["matchup"]
        away, home = matchup.split(" @ ")
        h_score = p["home_score"]
        a_score = p["away_score"]
        result = p["result"]
        profit = p["profit"]

        if p["pick_type"] == "spread":
            # Skip if FINAL already exists for this matchup
            if re.search(rf'FINAL: {re.escape(away)} \d+ — {re.escape(home)} \d+', html):
                continue

            result_emoji = "+" if result == "W" else "-" if result == "L" else "="
            result_color = "#00FF55" if result == "W" else "#FF4444" if result == "L" else "#FFD600"

            # Find the IMPLIED line for this matchup and add FINAL after it
            implied_pattern = re.compile(
                rf'(IMPLIED: {re.escape(away)} \d+ .{{1,5}} {re.escape(home)} \d+)'
            )
            final_line = (
                f'\\1</p>'
                f'<p class="mono" style="font-size:8px; color:{result_color}; '
                f'margin:0 0 4px; font-weight:700; letter-spacing:0.5px;">'
                f'FINAL: {away} {a_score} — {home} {h_score} | '
                f'{p["side"]} {result} ({result_emoji}{abs(profit):.0f} $PP)'
            )

            new_html = implied_pattern.sub(final_line, html, count=1)
            if new_html != html:
                changes += 1
                html = new_html
                print(f"  Added FINAL: {matchup} — {away} {a_score}, {home} {h_score}")

    return html, changes


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
    record = settlement["record"]
    new_bankroll = settlement["new_bankroll"]
    status = settlement["status"]

    print(f"Settlement: {record['W']}-{record['L']}-{record['P']} | "
          f"P/L: {settlement['total_profit']:+.2f} | "
          f"Bankroll: {new_bankroll:.0f} | Status: {status}")
    print()

    total_changes = 0

    # Patch results table
    print("Patching results table...")
    html, c = patch_results_table(html, picks)
    total_changes += c

    # Patch bankroll
    print("Patching bankroll...")
    html, c = patch_bankroll(html, new_bankroll)
    total_changes += c

    # Patch record + status
    print("Patching record + status...")
    html, c = patch_record_and_status(html, record, status)
    total_changes += c

    # Patch pick cards with FINAL scores
    print("Patching pick cards with final scores...")
    html, c = patch_pick_cards(html, picks)
    total_changes += c

    print(f"\nTotal changes: {total_changes}")

    with open(blog_path, "w") as f:
        f.write(html)

    print(f"Blog updated: {blog_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
update_blog.py — Sync fresh line data into MORELLOSIMS blog picks.

Only updates EXISTING picks in the blog with fresh values:
  - Game line spreads (e.g., CLE -16.0 → CLE -16.5)
  - O/U totals
  - Implied scores
  - Prop line values + edges

Does NOT add/remove picks or change rationale text.
One game at a time — finds each pick in the blog and patches its numbers.

Usage:
  python scripts/update_blog.py <nbasim_index.html> <morellosims_index.html>
"""

import re
import sys
from bs4 import BeautifulSoup


def extract_sim_data(sim_path):
    """Extract all matchup + prop data from the NBA SIM dashboard."""

    with open(sim_path, "r") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    # ── Game lines ──
    games = {}
    for card in soup.select(".matchup-card"):
        away_el = card.select_one(".mc-team.mc-away .mc-abbr")
        home_el = card.select_one(".mc-team.mc-home .mc-abbr")
        spread_el = card.select_one(".mc-spread")
        total_el = card.select_one(".mc-total")
        implied_el = card.select_one(".mc-implied")
        conf_el = card.select_one(".mc-conf")

        if not all([away_el, home_el, spread_el]):
            continue

        away = away_el.get_text(strip=True)
        home = home_el.get_text(strip=True)
        spread = spread_el.get_text(strip=True)
        total = total_el.get_text(strip=True).replace("O/U ", "") if total_el else ""
        implied = implied_el.get_text(strip=True) if implied_el else ""

        # Parse confidence number from "100 A" → 100
        conf_text = conf_el.get_text(strip=True) if conf_el else ""
        conf_match = re.match(r"(\d+)", conf_text)
        conf_num = int(conf_match.group(1)) if conf_match else 0

        # Parse team from spread (e.g., "CLE -16.0" → "CLE", "-16.0")
        spread_match = re.match(r"([A-Z]{3}) ([+-]?[\d.]+)", spread)
        if spread_match:
            spread_team = spread_match.group(1)
            spread_val = spread_match.group(2)
        else:
            spread_team = ""
            spread_val = ""

        key = f"{away} @ {home}"
        games[key] = {
            "away": away,
            "home": home,
            "spread": spread,  # e.g., "CLE -16.0"
            "spread_team": spread_team,
            "spread_val": spread_val,
            "total": total,  # e.g., "229.5"
            "implied": implied,  # e.g., "BKN 107 — CLE 123"
            "conf": conf_num,
        }

    # ── Props ──
    props = {}
    for card in soup.select(".prop-card"):
        name_el = card.select_one(".prop-name")
        type_el = card.select_one(".prop-type-label")
        dir_el = card.select_one(".prop-dir-line")
        edge_el = card.select_one(".prop-edge")
        note_el = card.select_one(".prop-note")

        if not all([name_el, type_el, dir_el, edge_el]):
            continue

        name = name_el.get_text(strip=True)

        # Parse line value
        dir_text = dir_el.get_text(strip=True)
        line_match = re.search(r"([\d.]+)", dir_text)
        line_val = line_match.group(1) if line_match else ""

        edge_text = edge_el.get_text(strip=True)
        prop_type = type_el.get_text(strip=True)  # "OVER PTS"

        # Parse avg from note (e.g., "Avg 28.7 pts")
        avg_val = ""
        if note_el:
            avg_match = re.search(r"Avg ([\d.]+)", note_el.get_text())
            if avg_match:
                avg_val = avg_match.group(1)

        # Key by last name for matching
        props[name] = {
            "name": name,
            "type": prop_type,
            "line": line_val,
            "edge": edge_text,
            "avg": avg_val,
        }

    return games, props


def patch_blog(blog_path, games, props):
    """Patch specific values in the blog HTML, one pick at a time."""

    with open(blog_path, "r") as f:
        html = f.read()

    changes = 0

    # ── Patch game line spreads ──
    # Finds "AWAY @ HOME — TEAM -XX.X" and updates the spread
    # SKIP matchups that have already been settled (have a FINAL line)
    for key, g in games.items():
        away, home = g["away"], g["home"]

        # Check if this matchup has already been settled
        final_check = re.search(
            rf"FINAL: {re.escape(away)} \d+ — {re.escape(home)} \d+",
            html,
        )
        if final_check:
            print(f"  Skipping {key} — already settled (FINAL exists)")
            continue

        # Update spread in pick card headers
        # Pattern: "BKN @ CLE — CLE -16.0"
        old_pattern = re.compile(
            rf"({re.escape(away)} @ {re.escape(home)} — {re.escape(g['spread_team'])}) [+-]?[\d.]+"
        )
        new_val = f"\\1 {g['spread_val']}"
        new_html = old_pattern.sub(new_val, html)
        if new_html != html:
            print(f"  Updated spread: {key} → {g['spread']}")
            changes += 1
            html = new_html

        # Update spread in table rows
        # Pattern: "CLE -16.0" in <td> elements
        old_table = re.compile(
            rf"(>){re.escape(g['spread_team'])} [+-]?[\d.]+(</td>)"
        )
        new_table = f"\\g<1>{g['spread']}\\2"
        new_html = old_table.sub(new_table, html)
        if new_html != html:
            changes += 1
            html = new_html

        # Update IMPLIED line
        if g["implied"]:
            old_implied = re.compile(
                rf"IMPLIED: {re.escape(away)} \d+ — {re.escape(home)} \d+"
            )
            new_implied = f"IMPLIED: {g['implied']}"
            new_html = old_implied.sub(new_implied, html)
            if new_html != html:
                print(f"  Updated implied: {key} → {g['implied']}")
                changes += 1
                html = new_html

            # Update implied in table (e.g., "107-123")
            imp_match = re.match(
                r"([A-Z]{3}) (\d+) — ([A-Z]{3}) (\d+)", g["implied"]
            )
            if imp_match:
                a_score = imp_match.group(2)
                h_score = imp_match.group(4)
                # Find the table row for this matchup
                old_tbl_impl = re.compile(
                    rf"({re.escape(away)} @ {re.escape(home)}.*?)\d+-\d+(.*?</tr>)",
                    re.DOTALL,
                )
                # Simpler: just replace the score pattern near the matchup
                # We'll target "XXX-XXX" in a td near the matchup teams

        # Update O/U total
        if g["total"]:
            old_ou = re.compile(
                rf"(IMPLIED: {re.escape(g['implied'])}.*?O/U )[\d.]+"
            )
            new_ou = f"\\g<1>{g['total']}"
            new_html = old_ou.sub(new_ou, html)
            if new_html != html:
                print(f"  Updated O/U: {key} → {g['total']}")
                changes += 1
                html = new_html

    # ── Patch prop lines + edges ──
    # SKIP props that have already been settled (result in table)
    for pname, p in props.items():
        # Match the player in the blog by name pattern
        # Blog uses: "D. MITCHELL" or "N. JOKIĆ" or "J. HARDEN"
        # SIM uses: "D. Mitchell" or "N. Jokić" or "J. Harden"
        blog_name = pname.upper()

        # Check if this prop already has a W/L/P result in the table
        last_name = pname.split(". ", 1)[-1] if ". " in pname else pname
        # Also check common nicknames
        name_variants = [last_name, last_name.upper()]
        if last_name == "Wembanyama":
            name_variants.append("Wemby")
        settled = False
        for variant in name_variants:
            if re.search(
                rf">{re.escape(variant)}[^<]*</td>.*?>[WLP]</td>",
                html,
                re.DOTALL,
            ):
                print(f"  Skipping {pname} — already settled")
                settled = True
                break
        if settled:
            continue

        # Update line value: "OVER XX.X PTS" → new line
        if p["line"]:
            old_line = re.compile(
                rf"({re.escape(blog_name)}.*?OVER )([\d.]+)( (?:PTS|AST|REB))",
                re.DOTALL,
            )
            new_html = old_line.sub(rf"\g<1>{p['line']}\3", html)
            if new_html != html:
                print(f"  Updated prop line: {pname} → {p['line']}")
                changes += 1
                html = new_html

        # Update EDGE value
        if p["edge"] and p["avg"] and p["line"]:
            old_edge = re.compile(
                rf"(EDGE: )[+-]?[\d.]+(.*?Avg [\d.]+ vs Line )[\d.]+"
            )
            # Only replace near this player — use a more targeted pattern
            # Match edge + avg context near this player's section
            block_pattern = re.compile(
                rf"({re.escape(blog_name)}.*?EDGE: )[+-]?[\d.]+(.*?Avg )[\d.]+"
                rf"( vs Line )[\d.]+",
                re.DOTALL,
            )
            repl = rf"\g<1>{p['edge']}\g<2>{p['avg']}\g<3>{p['line']}"
            new_html = block_pattern.sub(repl, html)
            if new_html != html:
                print(f"  Updated edge: {pname} → {p['edge']}")
                changes += 1
                html = new_html

    print(f"\nTotal changes: {changes}")

    with open(blog_path, "w") as f:
        f.write(html)

    return changes


def main():
    if len(sys.argv) != 3:
        print("Usage: python update_blog.py <nbasim_html> <blog_html>")
        sys.exit(1)

    sim_path = sys.argv[1]
    blog_path = sys.argv[2]

    print(f"Reading NBA SIM data from: {sim_path}")
    games, props = extract_sim_data(sim_path)
    print(f"Found {len(games)} games, {len(props)} props")

    print(f"\nPatching blog: {blog_path}")
    changes = patch_blog(blog_path, games, props)

    if changes == 0:
        print("No changes needed — blog is up to date")
    else:
        print(f"Done — {changes} values updated")


if __name__ == "__main__":
    main()

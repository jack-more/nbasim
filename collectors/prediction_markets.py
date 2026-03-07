"""Fetch win probabilities from Polymarket and Kalshi prediction markets.

No authentication required — both APIs are fully public for read operations.
Returns dicts keyed by (home_abbr, away_abbr) with win probability data.
"""

import json
import logging
import re
from datetime import datetime, timezone, timedelta

import requests

logger = logging.getLogger(__name__)

# ── Polymarket team name → NBA abbreviation ──
POLY_TEAM_MAP = {
    "hawks": "ATL", "celtics": "BOS", "nets": "BKN", "hornets": "CHA",
    "bulls": "CHI", "cavaliers": "CLE", "mavericks": "DAL", "nuggets": "DEN",
    "pistons": "DET", "warriors": "GSW", "rockets": "HOU", "pacers": "IND",
    "clippers": "LAC", "lakers": "LAL", "grizzlies": "MEM", "heat": "MIA",
    "bucks": "MIL", "timberwolves": "MIN", "pelicans": "NOP", "knicks": "NYK",
    "thunder": "OKC", "magic": "ORL", "76ers": "PHI", "suns": "PHX",
    "trail blazers": "POR", "kings": "SAC", "spurs": "SAS", "raptors": "TOR",
    "jazz": "UTA", "wizards": "WAS",
}

# Polymarket slug abbreviations (lowercase) → NBA abbreviation
POLY_SLUG_MAP = {
    "atl": "ATL", "bos": "BOS", "bkn": "BKN", "cha": "CHA",
    "chi": "CHI", "cle": "CLE", "dal": "DAL", "den": "DEN",
    "det": "DET", "gsw": "GSW", "hou": "HOU", "ind": "IND",
    "lac": "LAC", "lal": "LAL", "mem": "MEM", "mia": "MIA",
    "mil": "MIL", "min": "MIN", "nop": "NOP", "nyk": "NYK",
    "okc": "OKC", "orl": "ORL", "phi": "PHI", "phx": "PHX",
    "por": "POR", "sac": "SAC", "sas": "SAS", "tor": "TOR",
    "uta": "UTA", "was": "WAS",
}

# Kalshi ticker abbreviations → NBA abbreviation
KALSHI_TEAM_MAP = {
    "ATL": "ATL", "BOS": "BOS", "BKN": "BKN", "CHA": "CHA",
    "CHI": "CHI", "CLE": "CLE", "DAL": "DAL", "DEN": "DEN",
    "DET": "DET", "GSW": "GSW", "HOU": "HOU", "IND": "IND",
    "LAC": "LAC", "LAL": "LAL", "MEM": "MEM", "MIA": "MIA",
    "MIL": "MIL", "MIN": "MIN", "NOP": "NOP", "NYK": "NYK",
    "OKC": "OKC", "ORL": "ORL", "PHI": "PHI", "PHX": "PHX",
    "POR": "POR", "SAC": "SAC", "SAS": "SAS", "TOR": "TOR",
    "UTA": "UTA", "WAS": "WAS",
}

# Kalshi city names in event titles → abbreviation
KALSHI_CITY_MAP = {
    "Atlanta": "ATL", "Boston": "BOS", "Brooklyn": "BKN", "Charlotte": "CHA",
    "Chicago": "CHI", "Cleveland": "CLE", "Dallas": "DAL", "Denver": "DEN",
    "Detroit": "DET", "Golden State": "GSW", "Houston": "HOU", "Indiana": "IND",
    "Los Angeles C": "LAC", "Los Angeles L": "LAL", "LA Clippers": "LAC",
    "LA Lakers": "LAL", "Memphis": "MEM", "Miami": "MIA", "Milwaukee": "MIL",
    "Minnesota": "MIN", "New Orleans": "NOP", "New York": "NYK",
    "Oklahoma City": "OKC", "Orlando": "ORL", "Philadelphia": "PHI",
    "Phoenix": "PHX", "Portland": "POR", "Sacramento": "SAC",
    "San Antonio": "SAS", "Toronto": "TOR", "Utah": "UTA", "Washington": "WAS",
}


def fetch_polymarket_nba(target_date=None):
    """Fetch NBA game win probabilities from Polymarket Gamma API.

    Args:
        target_date: date string "YYYY-MM-DD" to filter games. Defaults to today (ET).

    Returns:
        dict keyed by (home_abbr, away_abbr) -> {
            "away_prob": float (0-1),
            "home_prob": float (0-1),
            "volume": float,
            "slug": str,  # for building Polymarket URL
        }
    """
    if target_date is None:
        # Use Eastern Time for "today" since NBA schedule is in ET
        et = datetime.now(timezone.utc) - timedelta(hours=5)
        target_date = et.strftime("%Y-%m-%d")

    try:
        resp = requests.get(
            "https://gamma-api.polymarket.com/events",
            params={
                "tag_slug": "nba",
                "active": "true",
                "closed": "false",
                "limit": 100,
            },
            timeout=15,
        )
        resp.raise_for_status()
        events = resp.json()
    except Exception as e:
        logger.warning(f"Polymarket API failed: {e}")
        return {}

    results = {}

    for ev in events:
        slug = ev.get("slug", "")

        # Match slug format: nba-{away}-{home}-{date}
        # e.g. nba-orl-min-2026-03-07
        m = re.match(r"^nba-([a-z]+)-([a-z]+)-(\d{4}-\d{2}-\d{2})$", slug)
        if not m:
            continue

        away_slug, home_slug, game_date = m.groups()

        if game_date != target_date:
            continue

        away_abbr = POLY_SLUG_MAP.get(away_slug)
        home_abbr = POLY_SLUG_MAP.get(home_slug)
        if not away_abbr or not home_abbr:
            continue

        # Find the moneyline market (the one with no suffix — just the game slug)
        for mkt in ev.get("markets", []):
            mkt_slug = mkt.get("slug", "")
            # The moneyline market slug matches the event slug exactly
            if mkt_slug == slug:
                raw_prices = mkt.get("outcomePrices")
                raw_outcomes = mkt.get("outcomes", [])

                # These fields can be JSON strings — parse if needed
                if isinstance(raw_prices, str):
                    try:
                        raw_prices = json.loads(raw_prices)
                    except (json.JSONDecodeError, TypeError):
                        continue
                if isinstance(raw_outcomes, str):
                    try:
                        raw_outcomes = json.loads(raw_outcomes)
                    except (json.JSONDecodeError, TypeError):
                        continue

                prices = raw_prices
                outcomes = raw_outcomes
                if not prices or len(prices) < 2 or len(outcomes) < 2:
                    continue

                try:
                    p1 = float(prices[0])
                    p2 = float(prices[1])
                except (ValueError, TypeError):
                    continue

                # Map outcomes to teams
                # Outcomes are team names like ["Magic", "Timberwolves"]
                o1_lower = outcomes[0].lower()
                o2_lower = outcomes[1].lower()

                o1_abbr = POLY_TEAM_MAP.get(o1_lower)
                o2_abbr = POLY_TEAM_MAP.get(o2_lower)

                if o1_abbr == away_abbr and o2_abbr == home_abbr:
                    away_prob, home_prob = p1, p2
                elif o1_abbr == home_abbr and o2_abbr == away_abbr:
                    home_prob, away_prob = p1, p2
                else:
                    # Fallback: slug order is away-home, outcomes typically match
                    away_prob, home_prob = p1, p2

                results[(home_abbr, away_abbr)] = {
                    "away_prob": round(away_prob, 3),
                    "home_prob": round(home_prob, 3),
                    "volume": mkt.get("volume") or 0,
                    "slug": slug,
                }
                break

    logger.info(f"[Polymarket] {len(results)} NBA game probabilities for {target_date}")
    return results


def fetch_kalshi_nba(target_date=None):
    """Fetch NBA game win probabilities from Kalshi API.

    Args:
        target_date: date string "YYYY-MM-DD" to filter games. Defaults to today (ET).

    Returns:
        dict keyed by (home_abbr, away_abbr) -> {
            "away_prob": float (0-1),
            "home_prob": float (0-1),
            "event_ticker": str,
        }
    """
    if target_date is None:
        et = datetime.now(timezone.utc) - timedelta(hours=5)
        target_date = et.strftime("%Y-%m-%d")

    try:
        resp = requests.get(
            "https://api.elections.kalshi.com/trade-api/v2/events",
            params={
                "series_ticker": "KXNBAGAME",
                "status": "open",
                "with_nested_markets": "true",
                "limit": 50,
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        events = data.get("events", [])
    except Exception as e:
        logger.warning(f"Kalshi API failed: {e}")
        return {}

    results = {}

    for ev in events:
        event_ticker = ev.get("event_ticker", "")
        sub_title = ev.get("sub_title", "")  # e.g. "NYK at LAC (Mar 9)"

        # Parse date from sub_title: "NYK at LAC (Mar 9)"
        date_match = re.search(r"\((\w+)\s+(\d+)\)", sub_title)
        if not date_match:
            continue

        month_str, day_str = date_match.groups()
        month_map = {
            "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
            "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
        }
        month_num = month_map.get(month_str)
        if not month_num:
            continue

        # Determine year from target_date
        target_year = int(target_date[:4])
        kalshi_date = f"{target_year}-{month_num:02d}-{int(day_str):02d}"

        if kalshi_date != target_date:
            continue

        # Parse team abbreviations from sub_title: "NYK at LAC (Mar 9)"
        team_match = re.match(r"(\w+)\s+at\s+(.+?)\s+\(", sub_title)
        if not team_match:
            continue

        away_raw, home_raw = team_match.groups()
        away_abbr = KALSHI_TEAM_MAP.get(away_raw.strip())
        home_abbr = KALSHI_TEAM_MAP.get(home_raw.strip())

        # Fallback: try city name mapping from event title
        if not away_abbr or not home_abbr:
            title = ev.get("title", "")  # "New York at Los Angeles C"
            title_match = re.match(r"(.+?)\s+at\s+(.+?)$", title)
            if title_match:
                away_city, home_city = title_match.groups()
                if not away_abbr:
                    away_abbr = KALSHI_CITY_MAP.get(away_city.strip())
                if not home_abbr:
                    home_abbr = KALSHI_CITY_MAP.get(home_city.strip())

        if not away_abbr or not home_abbr:
            logger.debug(f"Kalshi: could not map teams for {sub_title}")
            continue

        # Parse win probabilities from markets
        markets = ev.get("markets", [])
        team_probs = {}

        for mkt in markets:
            ticker = mkt.get("ticker", "")
            yes_bid = mkt.get("yes_bid")
            yes_ask = mkt.get("yes_ask")

            if yes_bid is not None and yes_ask is not None:
                # Midpoint of bid/ask for best estimate
                midpoint = (yes_bid + yes_ask) / 2.0 / 100.0  # Convert cents to probability
            elif yes_bid is not None:
                midpoint = yes_bid / 100.0
            elif yes_ask is not None:
                midpoint = yes_ask / 100.0
            else:
                continue

            # Ticker ends with team abbr: KXNBAGAME-26MAR09NYKLAC-LAC
            ticker_team = ticker.split("-")[-1] if "-" in ticker else ""
            team_abbr = KALSHI_TEAM_MAP.get(ticker_team)
            if team_abbr:
                team_probs[team_abbr] = midpoint

        if away_abbr in team_probs and home_abbr in team_probs:
            results[(home_abbr, away_abbr)] = {
                "away_prob": round(team_probs[away_abbr], 3),
                "home_prob": round(team_probs[home_abbr], 3),
                "event_ticker": event_ticker,
            }
        elif away_abbr in team_probs:
            results[(home_abbr, away_abbr)] = {
                "away_prob": round(team_probs[away_abbr], 3),
                "home_prob": round(1 - team_probs[away_abbr], 3),
                "event_ticker": event_ticker,
            }
        elif home_abbr in team_probs:
            results[(home_abbr, away_abbr)] = {
                "away_prob": round(1 - team_probs[home_abbr], 3),
                "home_prob": round(team_probs[home_abbr], 3),
                "event_ticker": event_ticker,
            }

    logger.info(f"[Kalshi] {len(results)} NBA game probabilities for {target_date}")
    return results


def fetch_all_prediction_markets(sport="nba", target_date=None):
    """Fetch win probabilities from all prediction market sources.

    Returns:
        dict keyed by (home_abbr, away_abbr) -> {
            "polymarket": {"away_prob", "home_prob", "volume", "slug"} or None,
            "kalshi": {"away_prob", "home_prob", "event_ticker"} or None,
        }
    """
    poly = {}
    kalshi = {}

    if sport == "nba":
        poly = fetch_polymarket_nba(target_date)
        kalshi = fetch_kalshi_nba(target_date)
    # MLB support can be added when season starts

    # Merge into unified structure
    all_keys = set(poly.keys()) | set(kalshi.keys())
    result = {}
    for key in all_keys:
        result[key] = {
            "polymarket": poly.get(key),
            "kalshi": kalshi.get(key),
        }

    logger.info(
        f"[Prediction Markets] {len(result)} games: "
        f"Polymarket={len(poly)}, Kalshi={len(kalshi)}"
    )
    return result

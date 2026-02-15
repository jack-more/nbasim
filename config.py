import os
from dotenv import load_dotenv

load_dotenv()

# Seasons to collect (most recent first)
SEASONS = ["2025-26", "2024-25"]
SEASON_TYPES = ["Regular Season"]
LEAGUE_ID = "00"

# Rate limiting for nba_api
API_DELAY_SECONDS = 2.0
API_MAX_RETRIES = 3
API_TIMEOUT = 60

# Database
DB_PATH = os.path.join(os.path.dirname(__file__), "db", "nba_sim.db")

# The Odds API
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Minimum possession thresholds for lineup data
MIN_POSS_5MAN = 30
MIN_POSS_4MAN = 50
MIN_POSS_3MAN = 75
MIN_POSS_2MAN = 100
MIN_MINUTES_SOLO = 200

# Archetype clustering
MIN_MINUTES_FOR_CLUSTERING = 300
K_RANGE = (2, 5)  # test K=2,3,4,5 per position, pick best by silhouette

# Value score synergy weights (sum of synergy portion = 0.70)
SYNERGY_WEIGHTS = {
    "solo": 0.21,
    "two_man": 0.196,
    "three_man": 0.14,
    "four_man": 0.091,
    "five_man": 0.063,
}
BASE_VALUE_WEIGHT = 0.25
ARCHETYPE_FIT_WEIGHT = 0.05

# Bayesian shrinkage prior strengths (possessions)
PRIOR_STRENGTH = {
    5: 100,
    4: 75,
    3: 50,
    2: 30,
    "solo": 500,  # minutes for solo impact
}

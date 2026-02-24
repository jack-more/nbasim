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
K_RANGE = (3, 6)  # test K=3,4,5,6 per position — force minimum 3 for meaningful archetypes

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

# ── Synergy × Opponent Scheme Interaction ──────────────────────────
# Maps (pair_archetype_category, opponent_def_scheme_type) → multiplier.
# > 1.0 = pair benefits against this scheme, < 1.0 = pair is penalized.
# Quality factor from opponent defense rating further adjusts:
#   Elite (<110 DRtg): advantages dampened ×0.90, disadvantages amplified ×1.15
#   Good  (<113 DRtg): no adjustment
#   Poor  (≥116 DRtg): advantages amplified ×1.10, disadvantages dampened ×0.90

SCHEME_INTERACTION = {
    # guard-guard pairs: excel vs drop coverage (PnR freedom), struggle vs switch
    ("guard_guard", "Switch-Everything"): 0.88,
    ("guard_guard", "Drop-Coverage"):     1.12,
    ("guard_guard", "Rim-Protect"):       1.00,
    ("guard_guard", "Trans-Defense"):     0.95,
    ("guard_guard", "Blitz"):             0.92,

    # guard-big pairs: PnR duos, punish drop coverage hard
    ("guard_big", "Switch-Everything"):   0.95,
    ("guard_big", "Drop-Coverage"):       1.15,
    ("guard_big", "Rim-Protect"):         0.90,
    ("guard_big", "Trans-Defense"):       1.00,
    ("guard_big", "Blitz"):               0.85,

    # wing-wing pairs: versatile, thrive vs switch schemes
    ("wing_wing", "Switch-Everything"):   1.10,
    ("wing_wing", "Drop-Coverage"):       1.00,
    ("wing_wing", "Rim-Protect"):         1.05,
    ("wing_wing", "Trans-Defense"):       1.05,
    ("wing_wing", "Blitz"):               1.00,

    # wing-big pairs: balanced, slight edge vs rim protect (spacing)
    ("wing_big", "Switch-Everything"):    1.00,
    ("wing_big", "Drop-Coverage"):        1.05,
    ("wing_big", "Rim-Protect"):          0.92,
    ("wing_big", "Trans-Defense"):        1.00,
    ("wing_big", "Blitz"):                0.95,

    # big-big pairs: interior-heavy, punished by switch & blitz
    ("big_big", "Switch-Everything"):     0.85,
    ("big_big", "Drop-Coverage"):         1.05,
    ("big_big", "Rim-Protect"):           1.08,
    ("big_big", "Trans-Defense"):         0.90,
    ("big_big", "Blitz"):                 0.88,
}

# Quality modifiers for opponent defense rating
SCHEME_QUALITY_FACTORS = {
    "Elite": {"advantage_scale": 0.90, "disadvantage_scale": 1.15},  # <110 DRtg
    "Good":  {"advantage_scale": 1.00, "disadvantage_scale": 1.00},  # <113 DRtg
    "Avg":   {"advantage_scale": 1.00, "disadvantage_scale": 1.00},  # <116 DRtg
    "Poor":  {"advantage_scale": 1.10, "disadvantage_scale": 0.90},  # ≥116 DRtg
}

# Projection model constants
SYNERGY_WEIGHT = 0.10       # portion of projection blend for synergy
SYNERGY_SCALE = 0.15        # conversion: (home_syn - away_syn) × SCALE = spread points
DSI_WEIGHT = 0.45           # reduced from 0.50
NRTG_WEIGHT = 0.45          # reduced from 0.50

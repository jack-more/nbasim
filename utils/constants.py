"""NBA team IDs, position mappings, and other constants."""

# Position group mappings - which listed positions belong to each group
POSITION_GROUPS = {
    "PG": ["PG", "G"],
    "SG": ["SG", "G", "G-F"],
    "SF": ["SF", "F", "G-F", "F-G"],
    "PF": ["PF", "F", "F-C"],
    "C": ["C", "C-F", "F-C"],
}

# Candidate archetype labels per position (used for labeling clusters post-hoc)
ARCHETYPE_LABELS = {
    "PG": ["Floor General", "Scoring Guard", "Combo Guard", "Defensive Specialist"],
    "SG": ["Sharpshooter", "Two-Way Wing", "Slasher", "Playmaking Guard"],
    "SF": ["3-and-D Wing", "Point Forward", "Stretch Forward", "Athletic Wing"],
    "PF": ["Stretch Big", "Traditional PF", "Small-Ball 4", "Two-Way Forward"],
    "C": ["Rim Protector", "Stretch 5", "Traditional Center", "Versatile Big"],
}

# Position-specific feature weights for clustering (multiplied before StandardScaler)
POSITION_FEATURE_WEIGHTS = {
    "PG": {
        "pts_per36": 1.0, "ast_per36": 1.5, "reb_per36": 0.8, "stl_per36": 1.2,
        "blk_per36": 0.5, "tov_per36": 1.0, "fg3a_per36": 1.0, "fta_per36": 0.8,
        "ts_pct": 1.0, "usg_pct": 1.3, "ast_pct": 1.5, "reb_pct": 0.5,
        "fg_pct": 0.8, "fg3_pct": 1.0, "off_rating": 1.0, "def_rating": 1.0,
    },
    "SG": {
        "pts_per36": 1.0, "ast_per36": 1.0, "reb_per36": 0.8, "stl_per36": 1.0,
        "blk_per36": 0.7, "tov_per36": 1.0, "fg3a_per36": 1.3, "fta_per36": 0.8,
        "ts_pct": 1.0, "usg_pct": 1.2, "ast_pct": 1.0, "reb_pct": 0.6,
        "fg_pct": 0.8, "fg3_pct": 1.3, "off_rating": 1.0, "def_rating": 1.0,
    },
    "SF": {
        "pts_per36": 1.0, "ast_per36": 1.2, "reb_per36": 1.0, "stl_per36": 1.2,
        "blk_per36": 0.9, "tov_per36": 1.0, "fg3a_per36": 1.2, "fta_per36": 1.0,
        "ts_pct": 1.0, "usg_pct": 1.0, "ast_pct": 1.2, "reb_pct": 0.8,
        "fg_pct": 0.9, "fg3_pct": 1.2, "off_rating": 1.0, "def_rating": 1.0,
    },
    "PF": {
        "pts_per36": 1.0, "ast_per36": 0.8, "reb_per36": 1.3, "stl_per36": 1.0,
        "blk_per36": 1.2, "tov_per36": 1.0, "fg3a_per36": 1.3, "fta_per36": 1.0,
        "ts_pct": 1.0, "usg_pct": 0.9, "ast_pct": 0.7, "reb_pct": 1.2,
        "fg_pct": 1.0, "fg3_pct": 1.2, "off_rating": 1.0, "def_rating": 1.0,
    },
    "C": {
        "pts_per36": 1.0, "ast_per36": 0.8, "reb_per36": 1.5, "stl_per36": 0.8,
        "blk_per36": 1.5, "tov_per36": 1.0, "fg3a_per36": 1.3, "fta_per36": 1.0,
        "ts_pct": 1.0, "usg_pct": 0.9, "ast_pct": 0.7, "reb_pct": 1.5,
        "fg_pct": 1.1, "fg3_pct": 1.0, "off_rating": 1.0, "def_rating": 1.0,
    },
}

# All clustering features (order matters - must match DB columns)
CLUSTERING_FEATURES = [
    "pts_per36", "ast_per36", "reb_per36", "stl_per36", "blk_per36",
    "tov_per36", "fg3a_per36", "fta_per36", "ts_pct", "usg_pct",
    "ast_pct", "reb_pct", "fg_pct", "fg3_pct", "off_rating", "def_rating",
]

# Play types tracked by NBA SynergyPlayTypes
PLAY_TYPES = [
    "Isolation", "Transition", "PRBallHandler", "PRRollMan",
    "Postup", "Spotup", "Handoff", "Cut", "OffScreen", "OffRebound", "Misc",
]

TYPE_GROUPINGS = ["Offensive", "Defensive"]

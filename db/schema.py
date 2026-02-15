"""SQLite schema definitions. Creates all 17 tables."""

import logging
from db.connection import get_connection

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
-- ============================================================
-- REFERENCE DATA
-- ============================================================

CREATE TABLE IF NOT EXISTS teams (
    team_id         INTEGER PRIMARY KEY,
    abbreviation    TEXT NOT NULL,
    full_name       TEXT NOT NULL,
    conference      TEXT,
    division        TEXT
);

CREATE TABLE IF NOT EXISTS players (
    player_id       INTEGER PRIMARY KEY,
    full_name       TEXT NOT NULL,
    position        TEXT,
    height_inches   INTEGER,
    weight_lbs      INTEGER,
    birth_date      TEXT,
    experience      INTEGER,
    is_active       INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS roster_assignments (
    player_id       INTEGER NOT NULL,
    team_id         INTEGER NOT NULL,
    season_id       TEXT NOT NULL,
    jersey_number   TEXT,
    listed_position TEXT,
    PRIMARY KEY (player_id, team_id, season_id),
    FOREIGN KEY (player_id) REFERENCES players(player_id),
    FOREIGN KEY (team_id) REFERENCES teams(team_id)
);

-- ============================================================
-- GAME DATA
-- ============================================================

CREATE TABLE IF NOT EXISTS games (
    game_id         TEXT PRIMARY KEY,
    season_id       TEXT NOT NULL,
    game_date       TEXT NOT NULL,
    home_team_id    INTEGER NOT NULL,
    away_team_id    INTEGER NOT NULL,
    home_score      INTEGER,
    away_score      INTEGER,
    FOREIGN KEY (home_team_id) REFERENCES teams(team_id),
    FOREIGN KEY (away_team_id) REFERENCES teams(team_id)
);

CREATE INDEX IF NOT EXISTS idx_games_date ON games(game_date);
CREATE INDEX IF NOT EXISTS idx_games_season ON games(season_id);

CREATE TABLE IF NOT EXISTS player_game_stats (
    game_id         TEXT NOT NULL,
    player_id       INTEGER NOT NULL,
    team_id         INTEGER NOT NULL,
    minutes         REAL,
    started         INTEGER,
    pts             INTEGER,
    reb             INTEGER,
    ast             INTEGER,
    stl             INTEGER,
    blk             INTEGER,
    tov             INTEGER,
    fgm             INTEGER,
    fga             INTEGER,
    fg3m            INTEGER,
    fg3a            INTEGER,
    ftm             INTEGER,
    fta             INTEGER,
    oreb            INTEGER,
    dreb            INTEGER,
    pf              INTEGER,
    plus_minus      REAL,
    off_rating      REAL,
    def_rating      REAL,
    net_rating      REAL,
    ast_pct         REAL,
    reb_pct         REAL,
    usg_pct         REAL,
    ts_pct          REAL,
    efg_pct         REAL,
    pace            REAL,
    pie             REAL,
    PRIMARY KEY (game_id, player_id),
    FOREIGN KEY (game_id) REFERENCES games(game_id),
    FOREIGN KEY (player_id) REFERENCES players(player_id)
);

CREATE INDEX IF NOT EXISTS idx_pgs_player ON player_game_stats(player_id);
CREATE INDEX IF NOT EXISTS idx_pgs_team ON player_game_stats(team_id);

-- ============================================================
-- LINEUP COMBINATION DATA
-- ============================================================

CREATE TABLE IF NOT EXISTS lineup_stats (
    lineup_id       TEXT NOT NULL,
    team_id         INTEGER NOT NULL,
    season_id       TEXT NOT NULL,
    group_quantity  INTEGER NOT NULL,
    player_ids      TEXT NOT NULL,
    gp              INTEGER,
    minutes         REAL,
    possessions     REAL,
    off_rating      REAL,
    def_rating      REAL,
    net_rating      REAL,
    fg_pct          REAL,
    fg3_pct         REAL,
    ft_pct          REAL,
    fg3a_rate       REAL,
    fgm             INTEGER,
    fga             INTEGER,
    fg3m            INTEGER,
    fg3a            INTEGER,
    ftm             INTEGER,
    fta             INTEGER,
    plus_minus      REAL,
    PRIMARY KEY (lineup_id, season_id),
    FOREIGN KEY (team_id) REFERENCES teams(team_id)
);

CREATE INDEX IF NOT EXISTS idx_lineup_team ON lineup_stats(team_id, season_id);
CREATE INDEX IF NOT EXISTS idx_lineup_quantity ON lineup_stats(group_quantity);

CREATE TABLE IF NOT EXISTS lineup_players (
    lineup_id       TEXT NOT NULL,
    season_id       TEXT NOT NULL,
    player_id       INTEGER NOT NULL,
    PRIMARY KEY (lineup_id, season_id, player_id),
    FOREIGN KEY (player_id) REFERENCES players(player_id)
);

CREATE INDEX IF NOT EXISTS idx_lp_player ON lineup_players(player_id);

-- ============================================================
-- PLAY TYPE / COACHING DATA
-- ============================================================

CREATE TABLE IF NOT EXISTS team_playtypes (
    team_id         INTEGER NOT NULL,
    season_id       TEXT NOT NULL,
    play_type       TEXT NOT NULL,
    type_grouping   TEXT NOT NULL,
    poss_pct        REAL,
    ppp             REAL,
    fg_pct          REAL,
    efg_pct         REAL,
    tov_pct         REAL,
    score_pct       REAL,
    foul_pct        REAL,
    possessions     REAL,
    PRIMARY KEY (team_id, season_id, play_type, type_grouping),
    FOREIGN KEY (team_id) REFERENCES teams(team_id)
);

CREATE TABLE IF NOT EXISTS player_playtypes (
    player_id       INTEGER NOT NULL,
    team_id         INTEGER NOT NULL,
    season_id       TEXT NOT NULL,
    play_type       TEXT NOT NULL,
    type_grouping   TEXT NOT NULL,
    poss_pct        REAL,
    ppp             REAL,
    fg_pct          REAL,
    efg_pct         REAL,
    tov_pct         REAL,
    score_pct       REAL,
    possessions     REAL,
    PRIMARY KEY (player_id, season_id, play_type, type_grouping),
    FOREIGN KEY (player_id) REFERENCES players(player_id)
);

-- ============================================================
-- SEASON-AGGREGATED STATS
-- ============================================================

CREATE TABLE IF NOT EXISTS player_season_stats (
    player_id       INTEGER NOT NULL,
    team_id         INTEGER NOT NULL,
    season_id       TEXT NOT NULL,
    gp              INTEGER,
    minutes_total   REAL,
    minutes_per_game REAL,
    pts_pg          REAL,
    reb_pg          REAL,
    ast_pg          REAL,
    stl_pg          REAL,
    blk_pg          REAL,
    tov_pg          REAL,
    fg_pct          REAL,
    fg3_pct         REAL,
    ft_pct          REAL,
    fg3a_pg         REAL,
    fta_pg          REAL,
    usg_pct         REAL,
    ast_pct         REAL,
    reb_pct         REAL,
    ts_pct          REAL,
    efg_pct         REAL,
    off_rating      REAL,
    def_rating      REAL,
    net_rating      REAL,
    pie             REAL,
    pace            REAL,
    pts_per36       REAL,
    reb_per36       REAL,
    ast_per36       REAL,
    stl_per36       REAL,
    blk_per36       REAL,
    tov_per36       REAL,
    fg3a_per36      REAL,
    fta_per36       REAL,
    PRIMARY KEY (player_id, season_id),
    FOREIGN KEY (player_id) REFERENCES players(player_id)
);

CREATE TABLE IF NOT EXISTS team_season_stats (
    team_id         INTEGER NOT NULL,
    season_id       TEXT NOT NULL,
    gp              INTEGER,
    pace            REAL,
    off_rating      REAL,
    def_rating      REAL,
    net_rating      REAL,
    fg_pct          REAL,
    fg3_pct         REAL,
    fg3a_rate       REAL,
    ft_rate         REAL,
    oreb_pct        REAL,
    dreb_pct        REAL,
    ast_pct         REAL,
    tov_pct         REAL,
    ast_tov_ratio   REAL,
    PRIMARY KEY (team_id, season_id),
    FOREIGN KEY (team_id) REFERENCES teams(team_id)
);

-- ============================================================
-- DERIVED: COACHING PROFILES
-- ============================================================

CREATE TABLE IF NOT EXISTS coaching_profiles (
    team_id             INTEGER NOT NULL,
    season_id           TEXT NOT NULL,
    off_scheme_label    TEXT,
    off_scheme_cluster  INTEGER,
    pace_category       TEXT,
    pace_value          REAL,
    primary_playstyle   TEXT,
    secondary_playstyle TEXT,
    tertiary_playstyle  TEXT,
    fg3a_rate           REAL,
    def_scheme_label    TEXT,
    def_scheme_cluster  INTEGER,
    off_feature_vector  TEXT,
    def_feature_vector  TEXT,
    PRIMARY KEY (team_id, season_id),
    FOREIGN KEY (team_id) REFERENCES teams(team_id)
);

-- ============================================================
-- DERIVED: PLAYER ARCHETYPES
-- ============================================================

CREATE TABLE IF NOT EXISTS player_archetypes (
    player_id       INTEGER NOT NULL,
    season_id       TEXT NOT NULL,
    position_group  TEXT NOT NULL,
    archetype_id    INTEGER NOT NULL,
    archetype_label TEXT,
    confidence      REAL,
    feature_vector  TEXT,
    PRIMARY KEY (player_id, season_id),
    FOREIGN KEY (player_id) REFERENCES players(player_id)
);

-- ============================================================
-- DERIVED: VALUE SCORES
-- ============================================================

CREATE TABLE IF NOT EXISTS player_value_scores (
    player_id           INTEGER NOT NULL,
    team_id             INTEGER NOT NULL,
    season_id           TEXT NOT NULL,
    base_value          REAL,
    solo_impact         REAL,
    two_man_synergy     REAL,
    three_man_synergy   REAL,
    four_man_synergy    REAL,
    five_man_synergy    REAL,
    composite_value     REAL,
    archetype_fit_score REAL,
    minutes_weight      REAL,
    updated_at          TEXT,
    PRIMARY KEY (player_id, season_id),
    FOREIGN KEY (player_id) REFERENCES players(player_id)
);

CREATE TABLE IF NOT EXISTS pair_synergy (
    player_a_id     INTEGER NOT NULL,
    player_b_id     INTEGER NOT NULL,
    team_id         INTEGER NOT NULL,
    season_id       TEXT NOT NULL,
    minutes_together REAL,
    possessions     REAL,
    net_rating      REAL,
    synergy_score   REAL,
    archetype_a     TEXT,
    archetype_b     TEXT,
    PRIMARY KEY (player_a_id, player_b_id, season_id),
    FOREIGN KEY (player_a_id) REFERENCES players(player_id),
    FOREIGN KEY (player_b_id) REFERENCES players(player_id)
);

-- ============================================================
-- BETTING LINES
-- ============================================================

CREATE TABLE IF NOT EXISTS betting_lines (
    game_id         TEXT NOT NULL,
    bookmaker       TEXT NOT NULL,
    market_type     TEXT NOT NULL,
    outcome_name    TEXT NOT NULL,
    price           REAL,
    point           REAL,
    retrieved_at    TEXT NOT NULL,
    PRIMARY KEY (game_id, bookmaker, market_type, outcome_name, retrieved_at),
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);

CREATE INDEX IF NOT EXISTS idx_betting_game ON betting_lines(game_id);

-- ============================================================
-- MODEL PREDICTIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS predictions (
    game_id             TEXT NOT NULL,
    model_version       TEXT NOT NULL,
    predicted_spread    REAL,
    predicted_total     REAL,
    spread_confidence   REAL,
    total_confidence    REAL,
    market_spread       REAL,
    market_total        REAL,
    spread_edge         REAL,
    total_edge          REAL,
    actual_spread       REAL,
    actual_total        REAL,
    spread_correct      INTEGER,
    total_correct       INTEGER,
    created_at          TEXT,
    PRIMARY KEY (game_id, model_version),
    FOREIGN KEY (game_id) REFERENCES games(game_id)
);
"""


def create_all_tables(db_path: str):
    """Create all tables in the database."""
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
    logger.info(f"All tables created in {db_path}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from config import DB_PATH
    logging.basicConfig(level=logging.INFO)
    create_all_tables(DB_PATH)
    print(f"Database initialized at {DB_PATH}")

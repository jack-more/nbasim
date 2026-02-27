"""CLI entry point for the NBA Betting Model pipeline."""

import sys
import os
import logging
import argparse

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(__file__))

from config import DB_PATH, SEASONS, ODDS_API_KEY
from db.schema import create_all_tables
from collectors.players import PlayerCollector
from collectors.games import GameCollector
from collectors.lineups import LineupCollector
from collectors.playtypes import PlayTypeCollector
from collectors.boxscores import BoxScoreCollector
from collectors.odds import OddsCollector
from collectors.rapm import RAPMCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_collect(seasons: list[str], skip_boxscores: bool = False):
    """Run all data collection for specified seasons."""
    create_all_tables(DB_PATH)

    player_collector = PlayerCollector(DB_PATH)
    game_collector = GameCollector(DB_PATH)
    lineup_collector = LineupCollector(DB_PATH)
    playtype_collector = PlayTypeCollector(DB_PATH)
    boxscore_collector = BoxScoreCollector(DB_PATH)

    for season in seasons:
        logger.info(f"\n{'='*60}")
        logger.info(f"COLLECTING DATA FOR {season}")
        logger.info(f"{'='*60}")

        # Step 1: Teams, rosters, season stats
        player_collector.collect_for_season(season)

        # Step 2: Games
        game_collector.collect_for_season(season)

        # Step 3: Lineups (needs team_season_stats for pace)
        lineup_collector.collect_for_season(season)

        # Step 4: Play types
        playtype_collector.collect_for_season(season)

        # Step 5: Box scores (longest step)
        if not skip_boxscores:
            boxscore_collector.collect_for_season(season)
        else:
            logger.info(f"Skipping box scores for {season} (--skip-boxscores)")

    # Step 6: Odds (if API key available)
    if ODDS_API_KEY:
        odds_collector = OddsCollector(ODDS_API_KEY, DB_PATH)
        odds_collector.collect_current_odds()
    else:
        logger.info("No ODDS_API_KEY set. Skipping odds collection.")
        logger.info("Sign up free at https://the-odds-api.com to get a key.")

    # Step 7: RAPM data from nbarapm.com (no API key needed)
    rapm_collector = RAPMCollector(DB_PATH)
    rapm_collector.collect()


def run_analyze(seasons: list[str]):
    """Run analysis (coaching schemes + archetypes) for specified seasons."""
    from analysis.coaching import CoachingAnalyzer
    from analysis.archetypes import ArchetypeAnalyzer

    coaching = CoachingAnalyzer(DB_PATH)
    archetypes = ArchetypeAnalyzer(DB_PATH)

    for season in seasons:
        logger.info(f"\n{'='*60}")
        logger.info(f"ANALYZING {season}")
        logger.info(f"{'='*60}")

        coaching.classify_schemes(season)
        archetypes.classify_all(season)


def run_scores(seasons: list[str]):
    """Compute value scores for specified seasons."""
    from analysis.value_scores import ValueScoreCalculator
    from analysis.synergy import PairSynergyCalculator

    for season in seasons:
        logger.info(f"\n{'='*60}")
        logger.info(f"COMPUTING VALUE SCORES FOR {season}")
        logger.info(f"{'='*60}")

        synergy_calc = PairSynergyCalculator(DB_PATH)
        synergy_calc.compute_pair_synergies(season)

        value_calc = ValueScoreCalculator(DB_PATH)
        value_calc.compute_all(season)


def run_predict(seasons: list[str]):
    """Train model and generate predictions."""
    from models.features import FeatureEngineer
    from models.predictor import GamePredictor
    from models.evaluation import ModelEvaluator

    engineer = FeatureEngineer(DB_PATH)
    predictor = GamePredictor()
    evaluator = ModelEvaluator(DB_PATH)

    # Use first season as training, second for validation
    if len(seasons) >= 2:
        train_season = seasons[1]  # older season
        test_season = seasons[0]   # newer season
    else:
        train_season = seasons[0]
        test_season = seasons[0]

    X_train, y_spread, y_total = engineer.build_training_matrix(train_season)
    predictor.train(X_train, y_spread, y_total)

    # Backtest on test season
    evaluator.backtest(test_season, predictor, engineer)


def show_status():
    """Show current database status."""
    from db.connection import table_row_count
    tables = [
        "teams", "players", "roster_assignments", "games",
        "player_game_stats", "lineup_stats", "lineup_players",
        "team_playtypes", "player_playtypes",
        "player_season_stats", "team_season_stats",
        "coaching_profiles", "player_archetypes",
        "player_value_scores", "pair_synergy",
        "betting_lines", "player_rapm", "predictions",
    ]
    print("\n=== Database Status ===")
    for table in tables:
        try:
            count = table_row_count(table, DB_PATH)
            print(f"  {table:.<35} {count:>8} rows")
        except Exception:
            print(f"  {table:.<35} {'N/A':>8}")
    print()


def main():
    parser = argparse.ArgumentParser(description="NBA Betting Model Pipeline")
    parser.add_argument(
        "command",
        choices=["collect", "analyze", "scores", "predict", "status", "all"],
        help="Pipeline phase to run",
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        default=SEASONS,
        help="Seasons to process (default: %(default)s)",
    )
    parser.add_argument(
        "--skip-boxscores",
        action="store_true",
        help="Skip box score collection (fast mode)",
    )

    args = parser.parse_args()

    if args.command == "status":
        show_status()
    elif args.command == "collect":
        run_collect(args.seasons, skip_boxscores=args.skip_boxscores)
    elif args.command == "analyze":
        run_analyze(args.seasons)
    elif args.command == "scores":
        run_scores(args.seasons)
    elif args.command == "predict":
        run_predict(args.seasons)
    elif args.command == "all":
        run_collect(args.seasons, skip_boxscores=args.skip_boxscores)
        run_analyze(args.seasons)
        run_scores(args.seasons)
        run_predict(args.seasons)


if __name__ == "__main__":
    main()

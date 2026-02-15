"""Collect teams, rosters, and player/team season stats."""

import logging
import pandas as pd
from nba_api.stats.static import teams as nba_teams
from nba_api.stats.endpoints import (
    CommonTeamRoster,
    LeagueDashPlayerStats,
    LeagueDashTeamStats,
)

from collectors.base import BaseCollector
from db.connection import read_query

logger = logging.getLogger(__name__)


class PlayerCollector(BaseCollector):

    def collect_teams(self):
        """Populate teams table from static data (no API call)."""
        all_teams = nba_teams.get_teams()
        df = pd.DataFrame(all_teams)
        df = df.rename(columns={
            "id": "team_id",
            "abbreviation": "abbreviation",
            "full_name": "full_name",
        })
        # Add conference/division info
        east_teams = {
            "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DET", "IND",
            "MIA", "MIL", "NYK", "ORL", "PHI", "TOR", "WAS"
        }
        df["conference"] = df["abbreviation"].apply(
            lambda x: "East" if x in east_teams else "West"
        )
        df["division"] = ""  # Can be filled later if needed
        df = df[["team_id", "abbreviation", "full_name", "conference", "division"]]
        self._save(df, "teams", if_exists="replace")
        logger.info(f"Saved {len(df)} teams")
        return df

    def collect_rosters(self, season: str):
        """Collect rosters for all teams. ~30 API calls."""
        teams_df = read_query("SELECT team_id FROM teams", self.db_path)
        all_players = []
        all_assignments = []

        for _, row in teams_df.iterrows():
            team_id = int(row["team_id"])
            try:
                dfs = self._call_endpoint(
                    CommonTeamRoster,
                    team_id=team_id,
                    season=season,
                )
                roster = dfs[0]
                if roster.empty:
                    continue

                for _, p in roster.iterrows():
                    player_id = int(p["PLAYER_ID"])

                    # Parse height to inches
                    height_inches = None
                    if pd.notna(p.get("HEIGHT")) and p["HEIGHT"]:
                        parts = str(p["HEIGHT"]).split("-")
                        if len(parts) == 2:
                            try:
                                height_inches = int(parts[0]) * 12 + int(parts[1])
                            except ValueError:
                                pass

                    weight = None
                    if pd.notna(p.get("WEIGHT")) and p["WEIGHT"]:
                        try:
                            weight = int(p["WEIGHT"])
                        except ValueError:
                            pass

                    exp = None
                    if pd.notna(p.get("EXP")) and p["EXP"] != "R":
                        try:
                            exp = int(p["EXP"])
                        except ValueError:
                            pass
                    elif p.get("EXP") == "R":
                        exp = 0

                    all_players.append({
                        "player_id": player_id,
                        "full_name": p.get("PLAYER", ""),
                        "position": p.get("POSITION", ""),
                        "height_inches": height_inches,
                        "weight_lbs": weight,
                        "birth_date": p.get("BIRTH_DATE", ""),
                        "experience": exp,
                        "is_active": 1,
                    })

                    all_assignments.append({
                        "player_id": player_id,
                        "team_id": team_id,
                        "season_id": season,
                        "jersey_number": str(p.get("NUM", "")),
                        "listed_position": p.get("POSITION", ""),
                    })

                logger.info(f"  Roster for team {team_id}: {len(roster)} players")
            except Exception as e:
                logger.error(f"  Failed to get roster for team {team_id}: {e}")

        if all_players:
            players_df = pd.DataFrame(all_players).drop_duplicates(subset=["player_id"])
            self._save(players_df, "players", if_exists="replace")
            logger.info(f"Saved {len(players_df)} players")

        if all_assignments:
            assignments_df = pd.DataFrame(all_assignments)
            # Clear existing for this season first
            from db.connection import execute
            execute(
                "DELETE FROM roster_assignments WHERE season_id = ?",
                self.db_path, [season]
            )
            self._save(assignments_df, "roster_assignments")
            logger.info(f"Saved {len(assignments_df)} roster assignments for {season}")

    def collect_player_season_stats(self, season: str):
        """Collect per-game and advanced player stats for a season. ~4 API calls."""
        # Base stats (PerGame)
        dfs = self._call_endpoint(
            LeagueDashPlayerStats,
            season=season,
            per_mode_detailed="PerGame",
            season_type_all_star="Regular Season",
        )
        base = dfs[0]

        # Per36 stats
        dfs36 = self._call_endpoint(
            LeagueDashPlayerStats,
            season=season,
            per_mode_detailed="Per36",
            season_type_all_star="Regular Season",
        )
        per36 = dfs36[0]

        # Advanced stats
        dfs_adv = self._call_endpoint(
            LeagueDashPlayerStats,
            season=season,
            per_mode_detailed="PerGame",
            measure_type_detailed_defense="Advanced",
            season_type_all_star="Regular Season",
        )
        adv = dfs_adv[0]

        if base.empty:
            logger.warning(f"No player stats found for {season}")
            return

        # Build combined DataFrame
        rows = []
        for _, b in base.iterrows():
            pid = int(b["PLAYER_ID"])
            tid = int(b["TEAM_ID"])

            # Find matching per36 and advanced rows
            p36_row = per36[per36["PLAYER_ID"] == pid]
            adv_row = adv[adv["PLAYER_ID"] == pid]

            mpg = b.get("MIN", 0) or 0
            gp = b.get("GP", 0) or 0

            row = {
                "player_id": pid,
                "team_id": tid,
                "season_id": season,
                "gp": gp,
                "minutes_total": mpg * gp if mpg and gp else 0,
                "minutes_per_game": mpg,
                "pts_pg": b.get("PTS", 0),
                "reb_pg": b.get("REB", 0),
                "ast_pg": b.get("AST", 0),
                "stl_pg": b.get("STL", 0),
                "blk_pg": b.get("BLK", 0),
                "tov_pg": b.get("TOV", 0),
                "fg_pct": b.get("FG_PCT", 0),
                "fg3_pct": b.get("FG3_PCT", 0),
                "ft_pct": b.get("FT_PCT", 0),
                "fg3a_pg": b.get("FG3A", 0),
                "fta_pg": b.get("FTA", 0),
            }

            # Advanced
            if not adv_row.empty:
                a = adv_row.iloc[0]
                row.update({
                    "usg_pct": a.get("USG_PCT", 0),
                    "ast_pct": a.get("AST_PCT", 0),
                    "reb_pct": a.get("REB_PCT", 0),
                    "ts_pct": a.get("TS_PCT", 0),
                    "efg_pct": a.get("EFG_PCT", 0),
                    "off_rating": a.get("OFF_RATING", 0),
                    "def_rating": a.get("DEF_RATING", 0),
                    "net_rating": a.get("NET_RATING", 0),
                    "pie": a.get("PIE", 0),
                    "pace": a.get("PACE", 0),
                })
            else:
                row.update({
                    "usg_pct": 0, "ast_pct": 0, "reb_pct": 0,
                    "ts_pct": 0, "efg_pct": 0, "off_rating": 0,
                    "def_rating": 0, "net_rating": 0, "pie": 0, "pace": 0,
                })

            # Per36
            if not p36_row.empty:
                p = p36_row.iloc[0]
                row.update({
                    "pts_per36": p.get("PTS", 0),
                    "reb_per36": p.get("REB", 0),
                    "ast_per36": p.get("AST", 0),
                    "stl_per36": p.get("STL", 0),
                    "blk_per36": p.get("BLK", 0),
                    "tov_per36": p.get("TOV", 0),
                    "fg3a_per36": p.get("FG3A", 0),
                    "fta_per36": p.get("FTA", 0),
                })
            else:
                row.update({
                    "pts_per36": 0, "reb_per36": 0, "ast_per36": 0,
                    "stl_per36": 0, "blk_per36": 0, "tov_per36": 0,
                    "fg3a_per36": 0, "fta_per36": 0,
                })

            rows.append(row)

        df = pd.DataFrame(rows)
        from db.connection import execute
        execute("DELETE FROM player_season_stats WHERE season_id = ?", self.db_path, [season])
        self._save(df, "player_season_stats")
        logger.info(f"Saved {len(df)} player season stats for {season}")

    def collect_team_season_stats(self, season: str):
        """Collect team-level season stats. ~2 API calls."""
        # Base team stats
        dfs = self._call_endpoint(
            LeagueDashTeamStats,
            season=season,
            per_mode_detailed="PerGame",
            season_type_all_star="Regular Season",
        )
        base = dfs[0]

        # Advanced team stats
        dfs_adv = self._call_endpoint(
            LeagueDashTeamStats,
            season=season,
            per_mode_detailed="PerGame",
            measure_type_detailed_defense="Advanced",
            season_type_all_star="Regular Season",
        )
        adv = dfs_adv[0]

        if base.empty:
            logger.warning(f"No team stats found for {season}")
            return

        rows = []
        for _, b in base.iterrows():
            tid = int(b["TEAM_ID"])
            adv_row = adv[adv["TEAM_ID"] == tid]

            row = {
                "team_id": tid,
                "season_id": season,
                "gp": b.get("GP", 0),
                "fg_pct": b.get("FG_PCT", 0),
                "fg3_pct": b.get("FG3_PCT", 0),
            }

            # Compute fg3a_rate and ft_rate
            fga = b.get("FGA", 0) or 1
            row["fg3a_rate"] = (b.get("FG3A", 0) or 0) / fga if fga > 0 else 0
            row["ft_rate"] = (b.get("FTA", 0) or 0) / fga if fga > 0 else 0

            if not adv_row.empty:
                a = adv_row.iloc[0]
                row.update({
                    "pace": a.get("PACE", 0),
                    "off_rating": a.get("OFF_RATING", 0),
                    "def_rating": a.get("DEF_RATING", 0),
                    "net_rating": a.get("NET_RATING", 0),
                    "oreb_pct": a.get("OREB_PCT", 0),
                    "dreb_pct": a.get("DREB_PCT", 0),
                    "ast_pct": a.get("AST_PCT", 0),
                    "tov_pct": a.get("TM_TOV_PCT", 0),
                    "ast_tov_ratio": a.get("AST_TO", 0),
                })
            else:
                row.update({
                    "pace": 0, "off_rating": 0, "def_rating": 0, "net_rating": 0,
                    "oreb_pct": 0, "dreb_pct": 0, "ast_pct": 0, "tov_pct": 0,
                    "ast_tov_ratio": 0,
                })

            rows.append(row)

        df = pd.DataFrame(rows)
        from db.connection import execute
        execute("DELETE FROM team_season_stats WHERE season_id = ?", self.db_path, [season])
        self._save(df, "team_season_stats")
        logger.info(f"Saved {len(df)} team season stats for {season}")

    def collect_for_season(self, season: str):
        """Run all player/team collection for a season."""
        logger.info(f"=== Collecting player/team data for {season} ===")
        self.collect_teams()
        self.collect_rosters(season)
        self.collect_player_season_stats(season)
        self.collect_team_season_stats(season)

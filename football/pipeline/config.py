"""Model knobs, ported 1:1 from the Config tab of the Google-Sheets football model (FootballModel.gs).

Every number here was measured on the sheet's 2022-2025 backtests (the reasons are in the docstrings of the
original and summarised on the site's Methodology tab). Change a knob, then run `python -m football.pipeline.backtest`
to see whether the error actually moved. The scoring weights are NOT here: they only change how stats are valued, so
they live in the browser (Config tab) and the pipeline ships the stat lines, not the points.
"""
import datetime as dt
from zoneinfo import ZoneInfo

SEASON = 2026                      # NFL season (the year it kicks off)
SEASON_TYPE = "REG"
PROJECT_WEEK = "auto"              # "auto" = first week that still has an unplayed game

# --- data volume ---------------------------------------------------------------
ROLLING_WINDOW = 3                 # games in the Trends window and the volume blend
MIN_ATTEMPTS = 25                  # Efficiency rows: season-cumulative minimums
MIN_CARRIES = 10
MIN_TARGETS = 8

# --- model ---------------------------------------------------------------------
DEF_ADJ_CAP = 0.15                 # a matchup moves a projection at most 15%
CATCH_CAP_FRACTION = 0.5           # catch rate varies less between defences than yards do
RECENT_WEIGHT = 0.20               # recency weight for carries and targets
RECENT_WEIGHT_ATT = 0.80           # ... and for pass attempts (tracks the current starter)
PRIOR_CARRIES = 40
PRIOR_TARGETS = 25
PRIOR_ATTEMPTS = 40
PRIOR_FUMBLES = 150
PRIOR_SACKS = 250
PRIOR_TWOPT = 200
SACK_DEF_STRENGTH = 0.25
K_DEF_RUSH = 60
K_DEF_CATCH = 80
K_DEF_YPR = 80
K_DEF_PASS = 80
K_DEF_POS = 40
K_DEF_POS_WR = 40
K_DEF_POS_TE = 100000              # effectively off: vs-TE splits carried no information (split-half r = -0.03)
K_DEF_POS_RB = 40
K_TEAM_VOL = 3
TEAM_SCALE_CAP = 0.20
DEF_STRENGTH_RUSH = 0.34           # share of each measured matchup actually applied (regressed on 2024-25 results)
DEF_STRENGTH_YPR = 0.15
DEF_STRENGTH_CATCH = 0.39
DEF_STRENGTH_PASS = 0.47
DEF_STRENGTH_COMP = 0.66
TEAM_TD_WEIGHT = 0.75
K_TEAM_TD = 150
EXPL_RUSH_WEIGHT = 0.0             # off: a steadier rating did not make a better projection
EXPL_RUSH_SCALE = 0.64
CAL_PASS_SLOPE = 0.68              # QB projections come out too spread out; pull toward the slate mean
CAL_COMP_SLOPE = 0.68
LAMBDA_RUSH_TD = 0.60              # share of the yardage matchup that carries into touchdown rate
LAMBDA_REC_TD = 0.77
LAMBDA_PASS_TD = 0.78
CONCENTRATE_ATTEMPTS = 1
CONCENTRATE_CARRIES = 0
CONCENTRATE_TARGETS = 0
PLAY_WINDOW = 6
PLAY_PRIOR = 0.25
MEAN_FACTOR = 1.17                 # Proj Pts is a MEDIAN; x this gives the mean (scoring is right-skewed)

# league fallbacks used before a sample exists
LG_PASS_TD = 0.045
LG_INT = 0.025
LG_YPA = 7.0

# --- weather (wind only: temperature and rain were tested and dropped) ------------
WEATHER_ON = True
WX_WIND_THRESHOLD = 13
WX_WIND_SLOPE = 0.022
WX_WIND_FLOOR = 0.70
WX_REC_DAMP = 0.5
WX_RUSH_SLOPE = 0.0

# --- scorecard / backtest ----------------------------------------------------------
SCORECARD_MIN_PTS = 4
BACKTEST_FROM_WEEK = 5
BACKTEST_MIN_PTS = 4
EDGE_MIN = 0.04

# --- default scoring (full PPR). The site lets you switch preset; the pipeline only needs it for backtests. ---
DEFAULT_SCORING = {"passYd": 0.04, "passTd": 4, "intr": -1, "rushYd": 0.1, "rushTd": 6,
                   "recYd": 0.1, "recTd": 6, "rec": 1, "fum": -1, "two": 2}

# stadium_id -> (lat, lon). Keyed on the id, not the name, because stadiums get renamed while the id holds.
STADIUMS = {
    "ATL97": (33.7555, -84.4009), "BAL00": (39.2780, -76.6227), "BOS00": (42.0909, -71.2643), "BUF00": (42.7738, -78.7870),
    "CAR00": (35.2258, -80.8528), "CHI98": (41.8623, -87.6167), "CIN00": (39.0955, -84.5161), "CLE00": (41.5061, -81.6995),
    "DAL00": (32.7473, -97.0945), "DEN00": (39.7439, -105.0201), "DET00": (42.3400, -83.0456), "GNB00": (44.5013, -88.0622),
    "HOU00": (29.6847, -95.4107), "IND00": (39.7601, -86.1639), "JAX00": (30.3239, -81.6373), "KAN00": (39.0490, -94.4839),
    "LAX01": (33.9535, -118.3392), "MIA00": (25.9580, -80.2389), "MIN01": (44.9736, -93.2578), "NAS00": (36.1665, -86.7713),
    "NOR00": (29.9511, -90.0812), "NYC01": (40.8135, -74.0745), "PHI00": (39.9008, -75.1675), "PHO00": (33.5276, -112.2626),
    "PIT00": (40.4468, -80.0158), "SEA00": (47.5952, -122.3316), "SFO01": (37.4033, -121.9694), "TAM00": (27.9759, -82.5033),
    "VEG00": (36.0909, -115.1833), "WAS00": (38.9077, -76.8645),
    # neutral sites
    "LON00": (51.5560, -0.2796), "LON02": (51.6043, -0.0665), "BRL00": (52.5147, 13.2395), "FRA00": (50.0686, 8.6455),
    "MUN01": (48.2188, 11.6247), "MAD01": (40.4531, -3.6883), "PAR00": (48.9245, 2.3601), "MEX00": (19.3029, -99.1505),
    "RIO00": (-22.9121, -43.2302), "MEL00": (-37.8200, 144.9834),
}
# nflverse sometimes reuses a home stadium_id for an international game. The stadium NAME is then the truth.
STADIUM_BY_NAME = {
    "Tottenham Hotspur Stadium": "LON02", "Wembley Stadium": "LON00", "Deutsche Bank Park": "FRA00",
    "Allianz Arena": "MUN01", "Olympiastadion": "BRL00", "Santiago Bernabeu Stadium": "MAD01",
    "Estadio Santiago Bernabeu": "MAD01", "Stade de France": "PAR00", "Estadio Azteca": "MEX00",
    "Estadio Banorte": "MEX00", "Maracana": "RIO00", "Arena Corinthians": "RIO00",
    "Melbourne Cricket Ground": "MEL00",
}
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"

# Columns kept from the 150-column nflverse weekly file.
NFL_COLS = [
    "player_id", "player_display_name", "position", "position_group", "season", "week", "season_type", "team", "opponent_team",
    "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered", "sack_yards_lost",
    "passing_air_yards", "passing_yards_after_catch", "passing_first_downs", "passing_epa", "passing_cpoe",
    "carries", "rushing_yards", "rushing_tds", "rushing_first_downs", "rushing_10", "rushing_epa",
    "receptions", "targets", "receiving_yards", "receiving_tds", "receiving_air_yards", "receiving_yards_after_catch",
    "receiving_first_downs", "receiving_epa", "racr", "target_share", "air_yards_share", "wopr",
    "rushing_fumbles_lost", "receiving_fumbles_lost", "sack_fumbles_lost",
    "rushing_2pt_conversions", "receiving_2pt_conversions", "passing_2pt_conversions",
    "fantasy_points", "fantasy_points_ppr",
]

ET = ZoneInfo("America/New_York")


def kickoff(day, time):
    """nflverse gives the date and the Eastern clock time separately; return an aware datetime or None."""
    try:
        h, m = str(time)[:5].split(":")
        y, mo, d = str(day).split("-")
        return dt.datetime(int(y), int(mo), int(d), int(h), int(m), tzinfo=ET)
    except Exception:
        return None

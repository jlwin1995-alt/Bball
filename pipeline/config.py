"""Model knobs. Every one is documented on the site's Methodology page.

Change a knob and re-run `python -m pipeline.build`. The scoring weights live in
the browser (Config tab on the site) because they only change how stats are
valued, not how they are projected.
"""

SEASON = 2027                      # season ENDING year: 2026-27 -> 2027
CUR_START = "2026-10-21"           # first regular-season game date of SEASON
PRIOR_START = "2025-10-21"         # prior season window used as early-season prior
PRIOR_END = "2026-04-13"

STATS = ["pts", "reb", "ast", "fg3m", "stl", "blk", "tov"]

ROLLING_WINDOW = 5                 # games in the recent-form window
PRIOR_SEASON_WEIGHT = 0.5          # last season's games count this much; fades as games pile up
MIN_GAMES = 3                      # weighted games needed before a player is projected

# --- minutes -------------------------------------------------------------
RECENT_WEIGHT_MIN = 0.5            # share of projected minutes taken from the rolling window
TEAM_MINUTES = 240.0               # a game's worth of player minutes
RESCALE_CLIP = (0.80, 1.25)        # how far the team rescale may move anyone's minutes
MAX_MIN = 42.0
PLAY_WINDOW = 20                   # team games used to measure how often a player actually plays
ACTIVE_DAYS = 21                   # a player must have played in this window to take minutes
TIER_CUTS = (30.0, 22.0)             # projected-minutes cutoffs: T1 stars/starters >= 30, T2 rotation >= 22, T3 the rest
QUESTIONABLE_MIN_MULT = 0.90       # Questionable/Day-To-Day minutes haircut; Out/Doubtful are dropped

# --- rates ---------------------------------------------------------------
# Prior strength in MINUTES: how long before a player's own rate outweighs the position average.
RATE_PRIOR_MIN = {"pts": 300, "reb": 350, "ast": 350, "fg3m": 500, "stl": 900, "blk": 900, "tov": 500}
RECENT_EXTRA = 0.5                 # extra weight on the rolling window when estimating rates

# --- matchups ------------------------------------------------------------
DEF_PRIOR_GAMES = 12               # defence regressed toward league by games / (games + this)
DEF_ADJ_CAP = 0.15                 # raw multiplier capped to 1 +/- this
# Share of the measured adjustment that is allowed through (damping). Starting values; the
# backtest (`python -m pipeline.backtest`) is how they should be re-tuned on real data.
DEF_STRENGTH = {"pts": 0.50, "reb": 0.35, "ast": 0.40, "fg3m": 0.40, "stl": 0.15, "blk": 0.15, "tov": 0.15}

# --- situation -----------------------------------------------------------
HOME_MULT = 1.01
AWAY_MULT = 0.995
B2B_MIN_MULT = 0.97                # second night of a back-to-back
RESTED_MIN_MULT = 1.01             # 3+ days off

# --- distribution --------------------------------------------------------
# Proj is the central (median-ish) outcome; Mean = Proj x MEAN_FACTOR. Stat lines are right-skewed.
# 1.07 = 1 / (1 - 0.068): the measured median-style bias on 2,400 real player-games (Over % ~ 50).
MEAN_FACTOR = 1.07

# Spread for Lines: sd = a + b * projection, per stat. Placeholders until backtest fits them.
SPREAD_DEFAULT = {"pts": [2.5, 0.20], "reb": [1.2, 0.30], "ast": [0.9, 0.30],
                  "fg3m": [0.6, 0.45], "stl": [0.5, 0.45], "blk": [0.4, 0.55], "tov": [0.6, 0.30],
                  "fp": [4.0, 0.15]}

# Default fantasy scoring used for Trends, the Scorecard and the backtest. (DraftKings classic)
DEFAULT_SCORING = {"pts": 1.0, "fg3m": 0.5, "reb": 1.25, "ast": 1.5, "stl": 2.0, "blk": 2.0, "tov": -0.5}

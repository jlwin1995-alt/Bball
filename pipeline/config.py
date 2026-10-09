"""Model knobs. Every one is documented on the site's Methodology page.

Change a knob and re-run `python -m pipeline.build`. The scoring weights live in
the browser (Config tab on the site) because they only change how stats are
valued, not how they are projected.
"""

SEASON = 2027                      # season ENDING year: 2026-27 -> 2027
CUR_START = "2026-10-21"           # APPROXIMATE first regular-season date (a guess; The Odds API lists 2026-10-20). Only anchors the fetch window; preseason/regular is read from ESPN's season type
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
RESCALE_STRENGTH = 1.0             # share of the team-240 rescale applied (1 = fully; <1 when absences redistribute fewer minutes than the rescale gives)
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
# Share of the (already shrunk and capped) adjustment that is allowed through. MEASURED by `python -m pipeline.measure` on the
# 2025-26 season: the share that arrives is ~1.0 (pts 1.33, blk 1.37, ast 1.2 with intervals that include 1; fg3m 0.75), so 1.0 across
# the board. Guessed values of 0.15-0.5 used before were costing accuracy. Re-measure when a second season of data exists.
DEF_STRENGTH = {"pts": 1.0, "reb": 1.0, "ast": 1.0, "fg3m": 1.0, "stl": 1.0, "blk": 1.0, "tov": 1.0}

# Calibration: projected per-minute rates are over-shrunk toward the league (actual outcomes spread out ~5-20% more than the
# projections do; slope of actual on projection measured at 1.05-1.20 in both halves of the season). Rates are stretched about
# the league rate by this factor. Out-of-sample MAE improves 0.3-1.2% per stat. 1.0 = off.
CAL_RATE_SLOPE = {"pts": 1.2, "reb": 1.1, "ast": 1.2, "fg3m": 1.2, "stl": 1.0, "blk": 1.2, "tov": 1.2}

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

# Preseason fallback if the learner (pipeline.preseason_minutes) has no data: a ROUGH GUESS, not measured here, so the site never
# projects stars for regular-season minutes in a preseason game. The site banner says when these are in use.
PRESEASON_MULT_FALLBACK = {"T1": 0.60, "T2": 0.80, "T3": 1.00}

# --- live lines (The Odds API) ------------------------------------------------
# Needs the ODDS_API_KEY environment variable (a GitHub Actions secret in CI). Never put the key in this file.
ODDS_SPORTS = ["basketball_nba", "basketball_nba_preseason"]   # tried in order; a key your plan/the API does not know is skipped
# Specific bookmakers rather than regions: as I recall The Odds API bills every 10 bookmakers as one "region", so up to
# 10 books here costs (markets x 1) credits per game. Verify against their docs/usage before relying on that.
ODDS_BOOKS = ["draftkings", "fanduel", "betmgm", "williamhill_us", "betrivers", "espnbet", "fanatics",
              "prizepicks", "underdog", "pick6"]
DFS_BOOKS = ["prizepicks", "underdog", "pick6", "dabble_us_dfs"]     # nominal-price books: shown beside, never in the consensus
ODDS_MARKETS = {                                                    # Odds API market key -> our stat key
    "player_points": "pts", "player_rebounds": "reb", "player_assists": "ast", "player_threes": "fg3m",
    "player_points_rebounds_assists": "pra",
    # add more here (each costs credits per game): "player_steals": "stl", "player_blocks": "blk", "player_turnovers": "tov",
    # "player_points_rebounds": "pr", "player_points_assists": "pa", "player_rebounds_assists": "ra"
}
ODDS_HORIZON_HOURS = 18            # only games starting within this window are pulled (props for tomorrow's games are rarely up yet)
ODDS_MIN_INTERVAL_MIN = 90         # a scheduled pull is skipped if the previous check was this recent, so backup runs cost no credits
ODDS_MIN_CREDITS = 60              # stop pulling when the API reports fewer credits than this remaining
COMBOS = {"pra": ["pts", "reb", "ast"], "pr": ["pts", "reb"], "pa": ["pts", "ast"], "ra": ["reb", "ast"]}
SPREAD_DEFAULT.update({"pra": [3.5, 0.17], "pr": [3.0, 0.20], "pa": [2.8, 0.20], "ra": [1.5, 0.25]})

ODDS_KEEP_STARTED_HOURS = 5        # keep a game's last PREGAME lines on the site this long after tipoff (books pull props at tip)

# --- Results tab ---------------------------------------------------------------------------------------------------
RESULTS_MIN_PROJ_MIN = 15.0        # players projected for fewer minutes are shown but not counted in the headline error numbers
RESULTS_EDGE_PP = 4.0              # model-vs-line gap (percentage points) that counts as a "pick" when grading line results
PP_BREAKEVEN = 0.577               # PrizePicks per-leg break-even used to grade PrizePicks picks (2 legs at 3x); edit if you play differently

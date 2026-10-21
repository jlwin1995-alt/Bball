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
PRIOR2_SEASON_WEIGHT = 0.25       # games from two seasons back (only player rates and minutes use them); backs up players who missed most of last season
PRIOR_SEASON_WEIGHT = 0.5          # last season's games count this much; fades as games pile up
MIN_GAMES = 3                      # weighted games needed before a player is projected
# Players with no NBA regular-season history (rookies, veterans who missed last season) are projected from their PRESEASON box scores
# until real games exist: rates shrink hard toward the position average (RATE_PRIOR_MIN already does that); the preseason minute
# adjustment is NOT applied to them (their minutes already are preseason minutes). Measured on 494 players (2025 preseason -> first 5
# regular-season games): early regular minutes = ~1.1 x preseason minutes (corr 0.59), heavy shrinkage toward a default HURT (minutes MAE
# 6.8 unshrunk vs 7.5 with k=2), so the prior is light.
PRE_ONLY_MIN_PRIOR = 17.0          # minutes a no-history player is lightly pulled toward (the group's average preseason minutes)
PRE_ONLY_MIN_K = 0.5               # preseason games' worth of that prior
# Regular-season minutes WHEN PLAYING = A + B x preseason minutes (not applied on preseason slates). Fitted on the no-history players of the 2025 preseason (59 who
# played early in 2025-26): minutes MAE 9.3 -> 7.4 and bias +6.4 -> 0 against the old flat 1.1x, which was fitted on every preseason player, veterans included.
PRE_ONLY_MIN_A = 1.71
PRE_ONLY_MIN_B = 0.683
# Share of team games a no-history player appears in = clip(A + B x preseason minutes, LO, HI) (105 players: 17.6 preseason minutes -> 39% of games)
PRE_ONLY_PPLAY_A = -0.12
PRE_ONLY_PPLAY_B = 0.0295
PRE_ONLY_PPLAY_LO = 0.03
PRE_ONLY_PPLAY_HI = 0.70
PRE_ONLY_RESCALE = 0.25            # share of the team-240 cut applied to no-history players: established players keep their minutes, rookies share what is left (tested on 2025-26: 0 -> bias +2.0 min, 0.25 -> +0.4, 0.5 -> -1.3, 1.0 -> -4.9)
PRE_ONLY_PPLAY = 0.85              # preseason slates only: share of team games assumed to be played

# --- minutes -------------------------------------------------------------
RECENT_WEIGHT_MIN = 0.5            # share of projected minutes taken from the rolling window
TEAM_MINUTES = 240.0               # a game's worth of player minutes
RESCALE_CLIP = (0.80, 1.25)        # how far the team rescale may move anyone's minutes
MAX_MIN = 42.0
RESCALE_STRENGTH = 0.25            # share of the team-240 rescale applied. MEASURED (pipeline.absence_test, 2025-26): full rescale over-credits teammates; 0.25 cuts minutes MAE 6% and fantasy-point MAE ~2% with absences known (~1% unknown), in both halves of the season
PLAY_WINDOW = 20                   # team games used to measure how often a player actually plays
ACTIVE_DAYS = 21                   # a player must have played in this window to take minutes
TIER_CUTS = (30.0, 22.0)             # projected-minutes cutoffs: T1 stars/starters >= 30, T2 rotation >= 22, T3 the rest
QUESTIONABLE_MIN_MULT = 0.90       # Questionable/Day-To-Day minutes haircut; Out/Doubtful are dropped

# --- rates ---------------------------------------------------------------
# Prior strength in MINUTES: how long before a player's own rate outweighs the position average.
# Halved from 300/350/350/500/900/900/500. pipeline.tune found it on 2024-25; it also helped on 2025-26 (late season and the first 15 and 30 game days)
RATE_PRIOR_MIN = {"pts": 150, "reb": 175, "ast": 175, "fg3m": 250, "stl": 450, "blk": 450, "tov": 250}
RECENT_EXTRA = 2.0                 # (was 0.5; same evidence as RATE_PRIOR_MIN) extra weight on the rolling window when estimating rates

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

# --- game environment ------------------------------------------------------
# Expected margin comes from each team's shrunk average point differential (a stand-in for the spread; swap in the book's
# spread when it is stored). Starters (T1) lose minutes in expected blowouts, as a hinge: nothing below BLOWOUT_HINGE points.
# Pace = both teams' average possessions per game vs the league, applied to per-minute rates. 0 = off.
ENV_PRIOR_GAMES = 8                # games before a team's own pace / margin outweighs the league's
HOME_MARGIN = 1.5                  # points of home advantage in the expected margin
BLOWOUT_HINGE = 9.0
BLOWOUT_SLOPE = 0.0                # T1 minutes lost per point of |expected margin| beyond the hinge
PACE_STRENGTH = 1.0                # share of the pace factor applied to rates. Measured lambda ~1 (pts 1.36 [0.71, 2.06]); effect is small, +0.1pt of edge
# BLOWOUT_SLOPE stays 0: starters do lose ~0.3 min per point past 9, and it replicated in both halves on T1 minutes, but fantasy-point MAE did not move and half-by-half minutes MAE disagreed on blowout games. Tested, not modelled.

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

# Default fantasy scoring used for Trends, the Scorecard and the backtest. (PrizePicks fantasy scoring: pts 1, reb 1.2, ast 1.5, stl 3, blk 3, tov -1, no 3PM bonus; was DraftKings classic before the 2026-27 opener)
DEFAULT_SCORING = {"pts": 1.0, "fg3m": 0.0, "reb": 1.2, "ast": 1.5, "stl": 3.0, "blk": 3.0, "tov": -1.0}

# Preseason fallback if the learner (pipeline.preseason_minutes) has no data: a ROUGH GUESS, not measured here, so the site never
# projects stars for regular-season minutes in a preseason game. The site banner says when these are in use.
PRESEASON_MULT_FALLBACK = {"T1": 0.60, "T2": 0.80, "T3": 1.00}
# Preseason minutes are modelled as a + b x (regular-season minutes), fitted by pipeline.preseason_minutes.relearn on last preseason plus
# this one so far; this year's games count PRESEASON_CUR_WEIGHT times (preseason rest differs year to year). Out-of-sample on the 2026
# preseason: minutes MAE 6.7 (tier ratios) -> 4.5 (line, last year only) -> 3.8 (line, adapting to this year).
PRESEASON_CUR_WEIGHT = 4.0

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
    "player_points_rebounds_assists": "pra", "player_points_rebounds": "pr", "player_points_assists": "pa", "player_rebounds_assists": "ra",
    # each market costs 1 credit per game per pull (10 books = 1 bookmaker group). Optional extras, ~+1 credit per game each:
    # "player_steals": "stl", "player_blocks": "blk", "player_turnovers": "tov"
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

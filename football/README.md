# Gridiron Model

NFL player projections for fantasy and stat lines — the football sibling of the Hoops Model, published at `/football/` next to it.
A static site (`football/site/`) fed by a small Python pipeline (`football/pipeline/`).

The model itself is a line-for-line port of the Google-Sheets "Football Player Model" (`FootballModel.gs`), including every measured constant
(opponent-adjustment strengths, touchdown lambdas, QB calibration slopes, wind hinge, participation weighting).

## What's on the site

| Tab | What it does |
|---|---|
| Projections | This week's stat line for every player: carries, targets, attempts × the player's own regressed rate × the opponent multiplier. Shaded **OVR** boxes (carries / targets / receptions / attempts) recalculate instantly and are saved on your device. |
| Game Board | Pick a game; both teams ranked by projected points, with kickoff, weather, and nflverse's spread/total/implied totals for context. |
| Leaders | Top projected players in nine categories. |
| Matchups | This week's offences ranked by how soft their opponent has been, plus every defence's rushing / catch / yards-per-catch / pass rating and position splits. |
| Efficiency / Usage / Trends | Season-to-date efficiency (QB / rushing / receiving views), share of team opportunity (target share, WOPR, carry share), rolling form vs season with HOT/COLD. |
| Weather | Kickoff wind per game and the multiplier it applies (wind only: temperature and rain were tested and dropped). |
| Lines | Every posted player prop (pass / rush / receiving yards, receptions, completions, sacks): sportsbook consensus with the vig removed, PrizePicks / Underdog lines beside it, and the model's edge against each. Type your own line and two prices and it recalculates (works with no API key). |
| Results | Projected → actual for every player and market of each graded week, with the last pregame lines beside them and hit rates for the model's side. |
| Scorecard | Each week's projections are logged **before** kickoff and never rewritten, then scored against season-average and last-3 baselines. |
| Backtest | Walk-forward replay of past seasons with the same code the site runs. |
| College (`/football/college/`) | The same engine on FBS: Projections (volume overrides), Game Board, Leaders, Matchups, Scorecard, Backtest (with a measured college spread), Config, Methodology. |
| Config | Scoring preset (Full/Half/Standard PPR, 6-pt pass TD, FanDuel, custom), median vs mean. |

## Run it

All commands run from the `football/` directory.

```bash
cd football
pip install -r pipeline/requirements.txt
python -m pipeline.fetch                                  # nflverse -> data/raw/  (weekly stats, schedule, snap counts, injuries)
python -m pipeline.fetch --season 2025                    # a past season, for the backtest (kept in data/raw/history/, not committed)
python -m pipeline.backtest --season 2025 --write         # -> site/data/backtest_2025.json
python -m pipeline.build                                  # -> site/data/*.json (also logs the week, once, before kickoff)
python -m http.server -d site 8000
node site/test/parity.mjs                                 # the browser arithmetic must match the pipeline's own numbers
```

`python -m pipeline.build --no-log` builds without touching the accuracy log (use this when experimenting).

### Live lines, consensus and PrizePicks

Lines come from [The Odds API](https://the-odds-api.com) (`pipeline/fetch_odds.py`; markets, books and the fitted spreads are in `config.py`).

1. Get a key at the-odds-api.com. A game costs (6 markets × 1 bookmaker group) = 6 credits, so a 13-game Sunday is about 80 credits per full pull;
   the schedule (Tue, Thu, Fri, Sat ×2, Sun ×4, Mon ×2, each with a skipped backup) uses roughly 5,000 credits a month, sized for a 20,000-credit plan shared with the basketball workflow. Games start being pulled 72 hours ahead (`ODDS_HORIZON_HOURS`); the run stops if fewer than `ODDS_MIN_CREDITS` (500) remain.
2. GitHub: Settings → Secrets and variables → Actions → **New repository secret** `ODDS_API_KEY` (the same one the basketball workflow uses). Never commit the key.
3. Actions → **Football refresh odds** → Run workflow (tick *probe* first to see what the API has for the next game without spending much).
   Scheduled runs skip themselves if the previous check was under 90 minutes ago, so the backup runs cost nothing unless the first one failed.
   Locally: `ODDS_API_KEY=... python -m pipeline.fetch_odds && python -m pipeline.build --no-log`.

`python -m pipeline.selftest` checks the response parser, name matching (two Josh Allens) and the consensus maths offline.
`node site/test/lines.mjs` checks the probability maths the Lines tab uses.

### Results

Each pull keeps the **last pregame** consensus and PrizePicks line per game, player and market in `data/log/lines_log.csv` (overwritten while a game
hasn't kicked off, never touched after). `pipeline/results.py` joins that to the frozen projections and the box scores and writes `site/data/results/`.
A pick is a gap of at least 4 points between the model and the book (`RESULTS_EDGE_PP`); PrizePicks picks must clear a 57.7% per-leg break-even (`PP_BREAKEVEN`).

### College football

`pipeline/cfb_data.py` pulls [CollegeFootballData](https://collegefootballdata.com) (`cfb_model.py` is the port of the sheet's `cfbCore_`, `cfb_build.py` builds
`site/data/cfb/` plus the college log, scorecard and walk-forward backtest). It needs a free key:

1. Get a key at collegefootballdata.com/key (free tier = 1,000 calls/month).
2. GitHub: Settings → Secrets and variables → Actions → **New repository secret** `CFBD_API_KEY`.
3. Run **Football refresh data and deploy**. Without the key the college steps skip and the college page says so.

A refresh with nothing new costs one API call (the schedule); each newly finished week costs two (positions once, plus the week). A stored week is only
fetched again if more of its games have finished since. Locally: `CFBD_API_KEY=... python -m pipeline.cfb_data && python -m pipeline.cfb_build`.
What differs from the NFL model is what CFBD reports: no targets (receptions are projected directly), no injury report, no weather, no sacks, no
2-point conversions, no betting lines, and a college QB's rushing line has his sacks subtracted so quarterbacks get their own rushing baseline.

## How the pieces fit

- `pipeline/model.py` — `nfl_core` (league baselines, regressed defence ratings, volumes, rates, participation weighting, QB calibration) and
  `derive` (volume × rate × matchup → stat line). The backtest and the site call the same functions.
- `site/model.js` — the same arithmetic in the browser, so overriding a volume or switching scoring recalculates without a rebuild.
  `site/test/parity.mjs` checks it against the pipeline output.
- `pipeline/scorecard.py` — append-only log with a settings stamp (hash of every knob in `config.py`), so changing a knob starts a fresh record.
  A row logged after its team's kickoff is marked late and never scored. **Logging is skipped while earlier games' box scores are still
  missing** from nflverse (it publishes the schedule result before the player stats), because a frozen log built on incomplete history would
  be wrong forever.
- `pipeline/weather.py` — recorded wind for played games, Open-Meteo forecast at the kickoff hour for the rest. Any failure degrades to
  multipliers of 1.000. Force a reading with `data/wind_overrides.json`, e.g. `{"BUF @ MIA": 22}`.

## Automatic refresh

`.github/workflows/football-refresh.yml` (data) and `football-odds.yml` (lines) run on a schedule. The data refresh runs daily (with backups, plus Tuesday-afternoon, Sunday-morning and Wednesday-evening runs): fetch →
build → commit data → deploy. No secrets are needed. GitHub only runs scheduled workflows from the **default branch**, so merge to `main`
first, then run the workflow once from the Actions tab. All deploys (basketball, football, site-only) publish both sites through
`scripts/stage_pages.sh`, so one can never erase the other.

## Status — read this

- **Validated here:** the Python port was run against real nflverse data (2024 and 2025 backtests behave as the sheet documents: Over % ≈ 50 on
  points, Bias ≈ -10 to -15% on the median projection, beating the season-average baseline on every market; the 2025 file has the sheet's
  18,540 player-games), the browser arithmetic matches the pipeline to rounding, and the log → score cycle was exercised on 2025 weeks.
- **Not validated live:** the Open-Meteo forecast call (the dev sandbox blocks the host; it fails soft and the site says which games have no
  reading). Run the workflow once and check the Weather tab.
- **Lines / odds not validated live:** the Odds API host is blocked from the dev sandbox, so the fetcher was written from the documented response
  shape and tested only on a stub (`pipeline.selftest`). Run the *probe* workflow once and eyeball the output before trusting the Lines tab.
- **College not validated against live CFBD:** the host is blocked here and there is no key, so the parser was tested on a stub shaped like the documented
  payload and the model on synthetic weeks. Check the first real
  run's CFB_Fields-equivalent output: `data/raw/cfb_weekly.csv` should have carries/receptions/attempts filled in for every team.
- **Not ported:** the sheet's phone "Edges" view (the Lines tab covers it).
  The sheet has no live in-game view either, so there is no Live tab.
- The model only uses the current season's games (as the sheet does), so Week 1-3 projections are thin by design: priors do the work.
- Season constants (`SEASON` in `config.py`) need updating each year.

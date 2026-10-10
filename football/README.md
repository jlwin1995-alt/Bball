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
| Scorecard | Each week's projections are logged **before** kickoff and never rewritten, then scored against season-average and last-3 baselines. |
| Backtest | Walk-forward replay of past seasons with the same code the site runs. |
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

`.github/workflows/football-refresh.yml` runs daily (with backups, plus Tuesday-afternoon, Sunday-morning and Wednesday-evening runs): fetch →
build → commit data → deploy. No secrets are needed. GitHub only runs scheduled workflows from the **default branch**, so merge to `main`
first, then run the workflow once from the Actions tab. All deploys (basketball, football, site-only) publish both sites through
`scripts/stage_pages.sh`, so one can never erase the other.

## Status — read this

- **Validated here:** the Python port was run against real nflverse data (2024 and 2025 backtests behave as the sheet documents: Over % ≈ 50 on
  points, Bias ≈ -10 to -15% on the median projection, beating the season-average baseline on every market; the 2025 file has the sheet's
  18,540 player-games), the browser arithmetic matches the pipeline to rounding, and the log → score cycle was exercised on 2025 weeks.
- **Not validated live:** the Open-Meteo forecast call (the dev sandbox blocks the host; it fails soft and the site says which games have no
  reading). Run the workflow once and check the Weather tab.
- **Not ported yet:** college football (CollegeFootballData), the Lines tab (sportsbook / PrizePicks props via The Odds API), a Live tab, and a
  per-player Results tab. The sheet's Lines logic is the next piece.
- The model only uses the current season's games (as the sheet does), so Week 1-3 projections are thin by design: priors do the work.
- Season constants (`SEASON` in `config.py`) need updating each year.

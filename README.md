# Hoops Model

NBA player projections for fantasy and stat lines — the basketball sibling of the football model.
A static site (`site/`) fed by a small Python pipeline (`pipeline/`).

## What's on the site

| Tab | What it does |
|---|---|
| Projections | Next slate's stat line for every player: minutes × adjusted per-minute rate. Shaded **Min OVR** recalculates instantly and is saved on your device. |
| Game Board | Pick a game; both teams ranked by projected fantasy points. |
| Matchups | What each defence allows vs league, per stat. |
| Efficiency / Usage / Trends | Per-36 and shooting rates; share of team opportunity; rolling form vs season, floor/ceiling, HOT/COLD. |
| Lines | Projection vs a posted line → P(over) with the vig removed from the book price. |
| Scorecard | Projections are logged **before** tip-off and never rewritten, then scored against season-average and last-N baselines. |
| Config | Scoring preset (DraftKings / FanDuel / custom), median vs mean, edge threshold. |

## Run it

```bash
pip install -r pipeline/requirements.txt
python -m pipeline.fetch_espn --backfill   # real data -> data/raw/   (needs network access to ESPN)
python -m pipeline.backtest --write-spread # optional: tune/inspect, fit Lines spreads
python -m pipeline.build                   # -> site/data/*.json  (also logs the next slate)
python -m http.server -d site 8000
```

No network? Develop on a synthetic league (clearly bannered on the site):

```bash
python -m pipeline.sample_data && python -m pipeline.build --raw data/sample
```

### Dry-run on a preseason slate

```bash
python -m pipeline.fetch_espn                              # refreshes injuries, schedule and current rosters
python -m pipeline.preseason_test project --date 2026-10-08   # BEFORE tip-off
python -m pipeline.preseason_test score   --date 2026-10-08   # after the games are final
```
Stars play far fewer minutes in preseason, so learn by how much from last year's preseason box scores (one-off, a few minutes),
then `project` applies it by tier (T1 = 30+ mpg, T2 = 22-30, T3 = the rest) instead of the usual 240-minute rescale:
```bash
python -m pipeline.preseason_minutes                        # writes data/raw/preseason_minutes.json
python -m pipeline.preseason_test project --date 2026-10-08 --game-no 1   # or --mult T1=0.55,T2=0.8,T3=1.05
```
Preseason minutes look nothing like the regular season, so `score` grades the per-minute rates and matchup
adjustments at the minutes each player actually played, and reports minutes separately. It never touches the real accuracy log.

### Data sources

| Source | Command | Notes |
|---|---|---|
| ESPN public JSON (default) | `python -m pipeline.fetch_espn` | Box scores, schedule and injuries; works from CI. One request per game. |
| `nba_api` (official stats.nba.com) | `python -m pipeline.fetch_nba_api` | Whole season in one call; best stats quality. Often blocked from cloud IPs, so run it locally and commit `data/raw`. Injuries still come from ESPN, matched by name. |

Pick one per `games.csv`: the two use different player ids, and `fetch_nba_api` refuses to run over an ESPN file. In CI, set the repository variable `DATA_SOURCE` to `nba_api` to switch.

`.github/workflows/refresh.yml` does the fetch → build → deploy daily. Enable GitHub Pages (source: GitHub Actions).

## Status — read this

- **The fetcher has not been run against live ESPN.** The dev sandbox blocks the host, so
  `pipeline/fetch_espn.py` was written from the API's known shape and fails loudly if a stat key is
  missing. Run `python -m pipeline.fetch_espn --selftest` first and eyeball the box score it prints.
- **Model knobs are untuned starting values** (`pipeline/config.py`): damping shares, `MEAN_FACTOR`,
  shrinkage strengths. On the synthetic league the model ties the season-average baseline, which is
  all that league can show. Run the backtest on real data before trusting any edge, and use the
  Scorecard to keep it honest.
- Not modelled: opposing-offence strength inside the defence rating, pace as a separate term,
  double-double bonuses, blowout risk, redistributing minutes in the browser when you override a teammate.
- Season constants (`SEASON`, `CUR_START`, …) in `config.py` need updating each year.

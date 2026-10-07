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

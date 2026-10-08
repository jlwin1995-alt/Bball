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

To show preseason-adjusted projections on the site itself (it switches back to normal on its own once the next slate is on or after `CUR_START`):
```bash
python -m pipeline.preseason_minutes && python -m pipeline.fetch_espn --preseason && python -m pipeline.build
```
The site then carries a PRESEASON banner, and nothing is logged to the Scorecard.

### Live lines, consensus and PrizePicks

The **Lines** tab shows every posted player prop with the sportsbook consensus (median line, vig removed, fair odds), the PrizePicks and
Underdog lines beside it, and the model's edge against each. Data comes from [The Odds API](https://the-odds-api.com): its `us_dfs` region
carries `prizepicks`, `underdog` and `pick6`. DFS prices are nominal, so PrizePicks edge is measured against your own break-even (Config; a
k-pick entry paying M× needs M^(-1/k) per leg).

1. Get a key at the-odds-api.com (the free tier is 500 credits/month; a full slate of 5 markets costs roughly 5 credits per game per pull
   with one bookmaker group, so plan on a paid tier for daily use - check their pricing page).
2. GitHub: Settings → Secrets and variables → Actions → **New repository secret** `ODDS_API_KEY`. Never commit the key.
3. Actions → **Refresh odds** → Run workflow. It then runs three times a day (noon, 5pm, 7:35pm ET). Locally:
   `ODDS_API_KEY=... python -m pipeline.fetch_odds && python -m pipeline.lines`.

Markets and books are in `pipeline/config.py` (`ODDS_MARKETS`, `ODDS_BOOKS`). Edges above 15 points get a warning marker: they usually mean the
model has the player's minutes or role wrong (injury news), not a bargain. Players with 0 projected minutes show OUT instead of a pick.

### Live games

The **Live** tab polls ESPN's scoreboard from your browser every 30 s (no credits, no workflow needed): scores, clock, and for games in
progress every player's box line (any player with history, via `players.json`, not just today's slate) as *now → projected final* (model per-minute rate × minutes still expected) with the posted line in
brackets. Blowouts and foul trouble aren't modelled. On the Lines tab, a game that has tipped off keeps its last pregame lines for
`ODDS_KEEP_STARTED_HOURS` and is marked LIVE with no pick: books pull props at tip and the model's pregame probability no longer applies.

### Data sources

| Source | Command | Notes |
|---|---|---|
| ESPN public JSON (default) | `python -m pipeline.fetch_espn` | Box scores, schedule and injuries; works from CI. One request per game. |
| `nba_api` (official stats.nba.com) | `python -m pipeline.fetch_nba_api` | Whole season in one call; best stats quality. Often blocked from cloud IPs, so run it locally and commit `data/raw`. Injuries still come from ESPN, matched by name. |

Pick one per `games.csv`: the two use different player ids, and `fetch_nba_api` refuses to run over an ESPN file. In CI, set the repository variable `DATA_SOURCE` to `nba_api` to switch.

### Automatic daily refresh

`.github/workflows/refresh.yml` runs every day at 09:17 UTC (about 5am Eastern): fetch → learn preseason minutes (once) → fit spreads →
build (logging the next regular-season slate) → commit the data → deploy the site. GitHub only runs scheduled workflows from the
**default branch**, so merge this branch to `main` first, then in the repo go to Settings → Pages → Source: **GitHub Actions**, and
run it once from the Actions tab (Run workflow) to check it. No secrets needed. Preseason games are included automatically until `CUR_START`.

Prefer your own machine? `scripts/morning.sh` does the same refresh locally; add it to `crontab -e` (the Mac must be awake).

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

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

**Leans.** A *lean* is the model disagreeing with the consensus line, in units of that market's spread (z = (projection - line) / sd). At 0.25 sd or more
it is shown as a LEAN, at 0.5 or more as STRONG, on the Game Board (strongest lean per player, row marked), the Projections tab and the Lines tab
(*strong leans only* filter). On week 5's 380 lines the model's side won 43% under 0.1 sd, 50% at 0.1-0.25, 55% at 0.25-0.5 and 54% over 0.5: small samples,
so the tiers are a way to sort, not a promise. Thresholds are `LEAN` in `site/app.js`.

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
2-point conversions, no player props (the college Game Board does show the game spread, total and implied scores from The Odds API's `americanfootball_ncaaf`, one cheap call of about 2 credits per pull), and a college QB's rushing line has his sacks subtracted so quarterbacks get their own rushing baseline.

**Tested and not adopted (college QB mobility).** College starters range from pocket passers to near-running-backs (QBs take 25% of team carries
against 15% in the NFL). On the walk-forward backtest (2026 weeks 3-6, 453 QB starts) none of these moved the model: mobility tiers for the QB rushing baseline
(pocket < 3 carries a game, mid 3-8, mobile 8+), a lighter QB prior, leaving QB carries out of the team-volume rescale, and rating defences on non-QB carries.
Points error changed by under 0.1% in every case; tiers helped pocket QBs (rushing MAE 11.3 to 11.0) and hurt mobile ones (27.4 to 27.8), and only the
fixed-carries variant changed bias (-9% to +3%) without reducing error. The options remain in `config.py` (`CFB_QB_TIERS`, `CFB_QB_PRIOR_CAR`,
`CFB_QB_FIXED_CARRIES`, `CFB_DEF_EXCL_QB`), all off.

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

**College: FCS / tier-gap games.** They are left out of the college scorecard and backtest (`CFB_SCORE_EXCL_*`). Also dropping them from the history the model learns from (`CFB_TRAIN_EXCL`) was tested on the same 2,416-player scored set and was worse on every market (points MAE +4.5%, receiving yards +12.9%, receptions +13.6%), because it throws away real snaps and shrinks each player's sample. Left off.

**College player props and leans.** `fetch_odds` also pulls college props (pass, rush and reception yards and receptions) for games on the college schedule starting within `CFB_PROPS_HORIZON_HOURS` (30), not re-pulling a game within 3 hours: about 4 credits a game, roughly 180 per pull on a 45-game Saturday. Rows go to `data/raw/cfb_odds.csv`; `cfb_build` turns them into `site/data/cfb/lines.json` with the college sigma per market from the backtest (NFL fit until a market has 300 college rows). The college page gets a Lines tab and a Lean column using the NFL tiers (0.25 / 0.5 sigma). Books post college props for only the top few players per team and late, and the college record under this model is still small, so the tiers are ungraded for college.

**Depth chart / starters.** The NFL Projections and Game Board carry a Depth column from nflverse's ESPN depth charts (`depth_charts_<season>.csv`, newest daily snapshot only, kept in `data/raw/depth.csv`): ★ marks a starter (rank 1 at QB, RB, TE; ranks 1-3 at WR), with the rank (RB2, WR4...). It sits beside the injury Status. A depth chart is a team's plan, not a confirmation: inactives come out 90 minutes before kickoff. College has no depth-chart feed, so its Depth column is INFERRED from usage in the team's last three games (ranking by attempts for QB, carries for RB, receptions for WR/TE), with the player's share of that volume.

A projected starter (depth rank above) who the injury report lists Out, IR or Doubtful gets a red pill on the Depth column and a warning above his team's Game Board table. The model does not redistribute his volume to teammates (tested: small effect), so the warning is the prompt to check the next man up.

**College lean record.** Each odds run also keeps the last PRE-GAME consensus line per player and market in `data/log/cfb_lines_log.csv` (never touched after kickoff, tagged with the week). `cfb_build` grades the model's side (its frozen `cfb_log` projection against that line; pushes left out; FCS / tier-gap games left out) by lean tier and shows it under the college Scorecard as the Lean record. College props are posted late, so lines for a game may only be logged a few hours before kickoff.

College lean tiers (week 7, 509 lines graded): STRONG (0.5 sigma or more) won 47 of 63 (75%), LEAN (0.25-0.5) 77 of 156 (49%), under 0.25 144 of 290 (50%). The college page now flags STRONG only; the Scorecard's Lean record still grades all three tiers so this can be re-checked. NFL tiers are unchanged.

**Running backs listed Out (adopted).** A back the injury report lists Out is removed from the team's carry pool and the team's carries are shared by the men who remain (`OUT_RB`, `OUT_CAP`); before, he kept a full share and teammates inherited nothing. Backtest 2024-26 on RBs whose team had an Out back with 8+ recent carries (147 player-games): teammates' carries MAE 5.13 to 4.24, rushing-yards MAE 23.7 to 20.7 (a 12% cut), rushing bias -43% to -24%; teammates are still under-projected (7.0 carries against 9.3 actual). Wide receivers and the other positions are NOT redistributed (an earlier test showed little gain), and Doubtful stays a flag only. The model stamp changed with these settings, so the NFL scorecard starts a new record. The Game Board warning above each team lists starters on the report and says which rule applies.

**Wide receivers listed Out (adopted) and thin samples.** A receiver the injury report lists Out is removed from the target pool the same way as a back (`OUT_WR`, `OUT_TGT_CAP` = 0.5). Backtest 2024-26 on receivers whose team had an Out WR averaging 4+ targets (991 player-games): WR targets MAE 2.52 to 2.41 (-5%), and with 2+ WRs out (75 games) 2.10 to 1.96 (-7%), receiving yards 20.4 to 19.7; teammates are still projected low (4.3 targets against 5.2 actual). TEs and RBs are not removed. Separately, a player with fewer than 3 games of history is tagged `thin` (his projection is mostly the league prior) and gets no lean pill or row marker on either page; his sigma is still shown. The depth chart would be the better signal for promoted rookies and practice-squad players, but only the latest snapshot is kept, so that cannot be backtested yet.

**Keeping thin and shifted samples out of the leans.** No lean pill or row marker is shown for (1) a player with fewer than 3 games of history (`thin`) or (2) a teammate at the position of a starter the injury report lists Out, RB or WR (`role shift`): his volume is the model's re-spread, and re-spread receivers are still projected low on average (4.3 targets vs 5.2 actual), which would skew leans toward the UNDER. Check on week 7 college lines (509 graded): lines come overwhelmingly from established players (451 of 509 had 5-6 games, 25 had 3 or fewer) and STRONG leans did not hit less often for low-history players (79% on 34 lines with under 30 prior touches/catches/attempts), so thin samples are not what drives the college STRONG record. The sigma is still shown for every line.

**Fantasy-points prop (collecting, not shown).** PrizePicks and Underdog post `player_fantasy_points` (sportsbooks do not). Each NFL odds pull now also requests it (one more credit per game) and keeps PrizePicks' LAST PRE-GAME line per player in `data/log/fp_lines_log.csv` (overwritten until kickoff, never after). Nothing appears on the site yet: a lean needs PrizePicks' scoring (to be fitted from the posted lines against our projected components, since the site already recomputes points under any scoring preset) and a sigma for points from the backtest.

**PrizePicks scoring (official chart).** Passing yard 0.04, passing TD 4, interception -1, rushing yard 0.1, rushing TD 6, receiving yard 0.1, receiving TD 6, reception 1, fumble lost -1, no two-point term. That is our Full PPR with the 2-point term removed, so it is now a `PrizePicks` scoring preset on the Config tab (the 14 lines logged for Sunday night sat 1.3 points from our full-PPR projections and 2.5 from half-PPR, consistent with this). The fantasy-points lean will use this preset, so no scoring fit is needed; the remaining step is a sigma for points from the backtest.

**Partial games (built).** A skill player (QB/RB/FB/WR/TE) whose offensive snap share in a game is under 50% of the average of his previous up-to-3 games (at least 2 prior games, average at least 35%) is tagged `partial game` (`analysis.partial_games`). The NFL Scorecard leaves partials out of the accuracy numbers, counts them, and lists them; the sportsbook lean record keeps them. It cannot tell an injury from a benching in a blowout. Week 6 flagged 8 skill players (McConkey, Doubs, Bateman, Brian Thomas Jr., ...); leaving them out barely moves points MAE because their errors were close to the average. The snap counts post about a day after a game, so the newest game is unflagged until then. MarShawn Lloyd was NOT flagged: he played 30 snaps (40%), his usual share. Snap counts have no halves, so `left in 1st half (est.)` comes from slim play-by-play (`data/raw/pbp_slim.csv`): a flagged player whose last involvement in a play was in Q1 or Q2. It is an estimate (a player can miss time without a touch). PrizePicks voids MORE picks, not LESS, for a first-half exit without a return; applying that to PrizePicks grading is not built yet.

**Void status (estimate).** PrizePicks voids a MORE pick (not LESS) when a player leaves in the 1st half and does not return. The Scorecard's partial-game table has a `Void (est.)` column: **no** = he touched the ball in the 2nd half, or took more snaps than his team ran in the whole 1st half (so some must be 2nd-half snaps); **likely void** = his last play was in the 1st half and his snaps fit inside it; **check** = no touches either way. It is an estimate because snap counts have no halves and nflverse's play-level participation file (who was on the field) is not published for 2026; a blowout benching looks the same as an injury. Week 6: Hockenson, KC Concepcion, Montgomery, Bateman, Brian Thomas Jr., Doubs, McConkey and Henderson read as likely void; Sadiq, Cody White and Isaiah Williams as not. Grading PrizePicks picks against this is not built yet.

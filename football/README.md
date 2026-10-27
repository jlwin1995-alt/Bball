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

**PrizePicks grading and voids (built).** In the Results tab, a PrizePicks MORE (over) pick on a player whose void status is `likely` (above) is shown as `void (est.)` and left out of the PrizePicks side/pick percentages; a LESS pick on the same player is still graded. The week table has a `PP voids (est.)` count. Weeks 5 and 6 so far: 3 and 4 MORE picks voided (Bateman and Brian Thomas Jr. receiving yards, Doubs receiving yards, Brian Thomas Jr. receptions, ...). Overrule any call with `data/log/void_overrides.csv` (columns `player_id,week,void`; `1` = void, `0` = stands), from PrizePicks' own notice; an override beats the estimate and shows as `void` without `(est.)`. Sportsbook consensus grading is unchanged: those bets stand once the player has played.

A MORE pick that had already cleared its line when the player left is not voided (an estimated void only applies when the stat is at or under the line); only an override you confirm from PrizePicks' notice (`void` = 1) voids it regardless.

**Fantasy-points lean (built; NFL live, college collecting).** The Lines tab has a Fantasy points (PrizePicks) section: the player's median points under the PrizePicks scoring become a mean-adjusted projection (`FP_MEAN`: mean = 1.988 + 0.916 x median, fitted on the 2024-26 backtests, 6,364 player-games; a flat x1.113 over-adjusts the top fifth), compared with the PrizePicks line in units of sigma (`FP_SIGMA`: 4.386 + 0.2455 x mean). MORE = over, LESS = under; only STRONG (0.5 sigma or more) is flagged, never for thin-sample or role-shift players, and a lean is ungraded until it has a record. The Results week table has an `FP lines (strong / all)` column, grading the frozen projections against the logged lines with the void rule (week 6, before the mean adjustment: the unadjusted sides were 10 LESS of 11; after it, 6 LESS and 6 MORE, 6 of 12 won, no STRONG picks). College: the same collection runs in the college props pull (`data/log/cfb_fp_lines_log.csv`, one more credit per game) and the section appears when PrizePicks posts college fantasy lines, using the college backtest's own fit (`pts_fit` in `backtest_<season>.json`: mean = 2.939 + 0.832 x median, sigma = 3.896 + 0.358 x mean). Whether PrizePicks posts college fantasy points is unconfirmed until Friday's props. College grading is not built yet.

**College spread and total model (in progress).** `pipeline/cfb_lines_data.py` fetches CFBD game lines (current season each refresh, 1 call; the two earlier seasons' games and lines once, 4 calls) into `data/raw/cfb_game_lines.csv` and `data/raw/cfb_hist/`. `pipeline/cfb_spread.py` fits ridge team ratings from scores (margin = r_home - r_away + home field, shrunk toward last season's rating) and a per-team total tendency, walk-forward by week, and reports MAE against the market's closing line, BETA (how much of model minus market is worth adding to the market) and the against-the-spread record by edge size. `python -m pipeline.cfb_spread [--tune]`. No leans are shown until the backtest says the model adds something.

**College spread/total backtest (first result: no leans).** Walk-forward, FBS vs FBS only, against CFBD closing lines; ridge ratings with last season as the prior, margins capped at 60, an FCS team starting at -22. Tuned on 2025 (lam 2, rho 1.0, cap 60), 2026 is the holdout. Margin MAE: 2025 model 12.41 vs market 11.79; 2026 model 13.29 vs market 11.02. BETA (how much of model minus market is worth adding to the market): margin +0.18 (2025), -0.06 (2026), pooled 0.06 +/- 0.07; total +0.17 and +0.12, pooled 0.15 +/- 0.12. The total model is much closer to its market (12.6 vs 12.4 MAE) than the margin model is to its own. Against the spread, edges of 3+ points hit 52.4% pooled (341 of 651), the break-even at -110. Nothing here separates the model from zero, so no spread or total leans are shown. Next: anchor on the market (market-implied ratings plus recent-form residuals) and test features that predict the market's error, totals first.

**Market-anchored college totals (result: no stable edge).** `pipeline/cfb_totals.py` predicts the market's error (actual total minus closing total) from features known before kickoff, walk-forward, ridge-shrunk toward zero: each team's earlier over/under record versus the market, how extreme the total is, mismatch size, the scores-only model's gap, week, FCS and neutral flags. Over/under rate overall is 50.9% (2,233 non-push games), so there is no simple bias. In-sample, two features look significant (a team's earlier error and the market total's level, both with t of about -2.5, in the direction of mean reversion), but walk-forward they do not hold: 2025 BETA +0.5 to +1.3, 2026 BETA -0.6 to -2.2, and the adjusted MAE is no better than the market's (12.1 vs 12.1 in 2025, 12.2 vs 12.2-12.3 in 2026). The sign flips between seasons, so it reads as noise. No totals leans are shown. Untested ideas: weather (needs venue coordinates and historical forecasts), opening-to-closing line movement (the lines fetch keeps only the closing line), and the player model's team volume.

**College line movement (result: inconclusive, probably stale opens).** `pipeline/cfb_move.py` compares the scores-only model with the OPENING line (first line CFBD recorded) and asks whether the line moves toward the model and whether betting the model's side at the open wins (FBS vs FBS). 2025: the close is only slightly sharper than the open (margin MAE 11.79 vs 11.89, total 12.37 vs 12.42), the average move is 1.3 (margin) and 1.6 (total) points, and the line moves toward the model (slope of close-open on model-open: margin 0.07 +/- 0.01, total 0.18 +/- 0.02), with 55.4% against the open spread and 53.3% on totals when the model differs by 2+ points (CLV +0.3 and +0.7 points). 2026 shows none of it (slopes 0.03 and 0.00, 49.7% and 51.7%). The likely reason for 2025 is timing, not edge: an opening line can be posted before the previous week's games finish, so a model that has seen those games disagrees with it and the market then catches up. A bettor pulling lines midweek would see the line AFTER that move. The honest test needs a timestamped midweek snapshot (The Odds API's historical endpoint) rather than the open; not built.

### NFL spread / total model (scores-only ridge ratings) — no edge

`pipeline/nfl_spread.py` runs the college ridge team ratings on NFL scores (regular season, 2015–2026, `data/raw/nfl_hist/nfl_games.csv` from nflverse schedules, closing `spread_line`/`total_line`), walk-forward from week 3 with last season's ratings as the prior (lam 6, rho 0.7, margin cap 28). `python -m pipeline.nfl_spread [--tune]`.

Result, 2016–2025 (about 225–240 games per season): the model's margin MAE is 9.1–11.3 against the market's 8.7–10.8, so the market is better in every season by roughly 0.3–0.7 points. BETA (the share of model-minus-market worth adding to the market) is -0.44 to +0.28 with no consistent sign, and the ATS hit rate by edge size is noise (the "edge >= 6" bucket has only 8–33 games a season). The total model is also worse than the closing total (MAE about 0.1–0.7 worse in 9 of 10 seasons). Same conclusion as college: scores alone do not beat the closing line, so there are no spread/total leans. Any NFL edge would have to come from information the market is slower on (injuries, QB changes, the player model), not from team ratings.

### NFL player model vs the closing lines — no edge

`pipeline/nfl_player.py` sums the site's own player projections (`nfl_core` + `derive`, walk-forward from week 5, no weather, Out players removed) to the team (yards, touchdowns, turnovers, sacks, home flag), fits a small ridge to points on EARLIER seasons only, and compares the implied game total and margin with the nflverse closing lines. It needs `data/raw/history/{weekly,schedule,injuries}_<season>.csv` (`python -m pipeline.fetch --season N`; gitignored, so it runs locally, about 15 seconds). `python -m pipeline.nfl_player`.

Result, 2023–2025, weeks 5+, 208 games a season. BETA (slope of actual-minus-market on model-minus-market; 0 means the model adds nothing):

| season | total BETA (±se) | total hit, edge ≥1 | margin BETA (±se) | margin hit |
|---|---|---|---|---|
| 2023 | -0.06 (0.30) | 53.5% (n 157) | -0.03 (0.20) | 48.5% |
| 2024 | +0.05 (0.29) | 48.1% (n 154) | -0.45 (0.19) | 45.5% |
| 2025 | +0.03 (0.24) | 48.2% (n 168) | -0.25 (0.19) | 49.7% |

The market is more accurate every season (total MAE 10.1–10.6 for the model vs 9.8–10.4; margin 10.3–10.7 vs 9.3–10.0). Total BETA is zero within noise; margin BETA is negative, i.e. where the player model disagrees with the spread, the spread is the better guess. No spread/total leans from the player model. It is still a fair test of the player projections' team-level sums, but weather, injuries beyond Out, and QB changes are the places left that the market could be slower on.

### Timestamped line snapshots

`pipeline/line_snapshots.py` + `.github/workflows/football-line-snapshots.yml` append the consensus spread and total of every upcoming NFL and college game to `data/log/line_snapshots.csv` (ts, sport, event, commence, home, away, home_spread, total, n_spread, n_total) on Wednesday ~noon ET, Thursday, Friday, Saturday and Sunday ~9am ET (about 4 credits a run, ~20 a week; games that have kicked off are skipped, so a game's last snapshot is its close). This replaces the stale "open" lines of the movement test: once a few weeks have accumulated, compare Wednesday against the final snapshot and test whether the move follows the scores-only / player model.

### Backup quarterbacks no longer absorb the offence (Out-QB and QB participation)

MNF WAS@SF showed Washington's running backs with only 16 of the team's 28.5 projected carries and three quarterbacks sharing 85 attempts: a QB listed Out (Mariota) was still projected, and the backups (Kaliakmanis, one start; Mariota) kept their full per-game history because the +-20% team-scale cap cannot shrink them. That leaked about 5 carries a game from the backs to backup QBs. Two changes in `model.nfl_core` (knobs `OUT_QB`, `QB_PART`, `QB_BACKUP_W`; both are in the scorecard stamp, so the NFL accuracy record restarts under the new stamp):
- a QB listed Out is removed from the pool (as RBs and WRs already were);
- a backup QB's attempts and carries are weighted by how often he played relative to the team's main passer, and with a healthy depth-chart QB1 (`QB1_IDS`, from `depth.csv`) a backup keeps at most `QB_BACKUP_W` = 10% of his own history.

Backtest (2024 / 2025, weeks 5+, QBs with real volume): passing yards MAE 10.66 -> 10.25 / 10.52 -> 9.60, completions 0.87 -> 0.82 / 0.88 -> 0.81, projected points 5.59 -> 5.59 / 5.52 -> 5.49 (the backtest has no historical depth chart, so it tests only the participation weighting). WAS@SF now: Washington RB carries 19.8 (was 16.4), Daniels 30.4 attempts, Kaliakmanis 4.0, Mariota gone. Next-man-up RB volume still follows each back's own history (White 8.6, Ekeler 4.1, Allen 4.7 carries), so a lone replacement does not take the whole lead role unless the history says so.

### Next-man-up RB share: tested, not adopted

Test: when a back is listed Out, give a fraction NMU of his vacated carries to the team's leading remaining back (highest carry load) before the team rescale, instead of spreading them by every back's own history. Walk-forward 2023-2025, weeks 5+, 302 teammate-back projections on teams with an Out back:

| NMU | carries MAE | rushing yards MAE |
|---|---|---|
| 0 (current: spread by history) | 4.14 | 21.73 |
| 0.25 | 4.10 | 22.22 |
| 0.5 | 4.22 | 22.95 |
| 1.0 (lead back takes all) | 4.56 | 24.77 |

Concentrating on the lead back is worse the more of it there is (backfields split a vacated role more than the "next man takes it" story suggests), and the 0.25 carries gain is within noise while yards get worse. The current pro-rata spread stays; the code was not kept. A depth-chart version (the backtest has no historical depth) is the one untested variant.

### Void check on MNF (week 6): confirmed voids respect cleared stats

McLaurin (left in Q1, 1 target) and Evans (out after the first half) were hurt; the snaps were not posted yet, so the estimate stayed off and both are in `data/log/void_overrides.csv`. PrizePicks voided McLaurin's picks and Evans's receptions (3, under a 4.5 line) but not his yards (94, over 64.5), which is the cleared-stat rule. Results used to void everything for a confirmed override; a confirmed void now also stays graded for a stat that had already cleared its line. Both players were LESS picks in our record, which a void never touches (MORE only), so no result changed. Juszczyk (FB) had Q1/Q2 plays only because the scheme made him a blocker, not an injury; the snap-based estimate sees a full game and flags nothing.

### Kickers: a backtest, no market added

`pipeline/kicker.py` (kicking points = 3 x field goals + extra points; the kicking columns `fg_made`, `fg_att`, `fg_missed`, `fg_long`, `pat_made`, `pat_att` are now kept in the weekly file). Walk-forward 2023-2025, weeks 4+, 1,341 kicker games, 66 kickers, against the team's implied points from the closing spread and total:

| predictor | MAE | RMSE |
|---|---|---|
| league mean (7.2 pts, sd 3.7) | 3.016 | 3.752 |
| team implied points only (pts = 3.42 + 0.172 x implied) | **2.965** | **3.678** |
| implied points + the kicker's own history (shrunk 6 games) | 2.985 | 3.696 |
| kicker's season average | 3.076 | 3.803 |
| kicker's last three | 3.400 | 4.279 |

The scoring environment explains almost all there is: implied points beat the league mean by only 1.7% of MAE, and adding a kicker's own history makes it slightly WORSE in every season. A single game's kicking points are mostly noise (sd 3.7 against an explainable spread of well under 1), and books price kicker props off the same totals. No kicker market was added to the odds pull and no leans are built; the projection is not worth surfacing. Revisit only if a book posts kicker lines well off their team's implied points (the logged lines would show that).

### College void overrides (lean record)

`data/log/cfb_void_overrides.csv` (player_id,week) lists college players who left in the first half and did not return. `cfb_build.lean_record` drops a MORE (over) pick on such a player when his stat had not cleared the line (the PrizePicks reboot rule, as on the NFL page; LESS picks are never voided). First case: Emory Williams (ECU, pulled after the first quarter with an injury, week 8) - the Over on passing yards (174.5 line, 61 actual) is void, so the STRONG record reads 56 of 76 rather than 56 of 77. College has no snap data, so this is manual only; the Lean record note on the college Scorecard shows the void count.

### Watch item: college STRONG leans where the projection is under half the line

Through week 8 (Oct 24), STRONG college leans by projection / consensus line: under 0.50 went 4 of 8 (50%); 0.50-0.65 went 27 of 40 (68%); 0.65-0.80 went 23 of 36 (64%); 1.25 and up went 10 of 11. The extreme-gap picks are mostly quarterbacks the books treat as starters and the model does not (Hasselbeck App State, Tommy Carr Michigan, Sagapolutele Cal; pass yards projected 38-140 against lines of 145-233), plus a benching (Lonergan, 0 yards). Likely role or lineup uncertainty, not a real edge. Sample is small, so nothing is changed yet.

Revisit after about two more slates (target: 20+ picks in the under-0.5 bucket). If it still runs near 50% while the rest stays near 65%+, drop the STRONG flag (not the projection) when the projection is under half the line, as thin and role-shift players already lose theirs. The check is the bucket table above: `lean_record` rows with |z| >= 0.5 grouped by projection / line.

### Goal-line / red-zone touchdown shares and points allowed by position (NFL)

`pipeline/situation.py` reads the play-by-play (`pbp_slim.csv` now also keeps down, distance, yards to the goal line, defence and the touchdown flags; the history files `data/raw/history/pbp_slim_<season>.csv` come from `fetch.pbp`).
- **Touchdown shares (in the model).** A player's touchdown expectation was `carries x his shrunk TD rate x matchup`, which says nothing about WHERE his carries come from. Now half of it (`SIT_TD_W` = 0.5) is `carries x (goal-line share x 0.389 + other share x 0.014)` for rushing and `targets x (red-zone share x 0.237 + other x 0.016)` for receiving, with each player's share (carries inside the 5, targets inside the 20) shrunk toward the league (`SIT_K_CAR` = 40, `SIT_K_TGT` = 30; league rates are 2022-25 constants in config). Walk-forward backtest 2023-25 (3,001 rusher-games with 3+ projected carries, 6,486 receiver-games with 2+ projected targets): Bernoulli log-loss for "scores a TD" 0.5433 -> 0.5370 (rush) and 0.4968 -> 0.4889 (receiving) at a 50/50 blend (0.5359 / 0.4842 once the level is also rescaled), MSE down 1%. Through the whole model, projected points MAE improves 5.42 -> 5.40, 5.59 -> 5.58, 5.49 -> 5.47 (2023/24/25): small, same direction in all three seasons. `python -m pipeline.situation` reruns the TD test. The browser model (`site/model.js`) applies the same blend (`sit_r`, `sit_c` per player, `meta.sit_w`); `site/test/parity.mjs` matches Python again. College is untouched.
- **A level problem this exposed.** Both the old and the new touchdown estimates are LOW: projected rushing TDs total 869 against 970 actual (-10%) and receiving TDs 1,285 against 1,545 (-17%) for players with real volume, which is most of the model's -8% to -13% points bias. Not changed here (it would shift every projection and prop); it is the next candidate.
- **Third-down shares** (`td3_car`, `td3_tgt`) are computed in `situation.shares` but not used or tested yet.
- **Points allowed by position.** `situation.allowed` sums PPR points, yards and touchdowns allowed per game to QB / RB / WR / TE for every defence (rank, % above league) and the Matchups tab shows it under "Fantasy points allowed by position". It is a reference table, not a model input: the model keeps the regressed and capped multipliers because points allowed barely repeat from one half-season to the next. Not available free: routes run, outside vs slot alignment (the participation file stopped being published after 2022).

### NFL touchdown calibration: tested, not applied to the points

The touchdown projections run low (rushing about 10%, receiving about 17% for players with real volume). Test: scale the expected touchdowns by a factor fitted on the OTHER two seasons and apply it to the held-out season (2023-25, weeks 5+, 11,113 player-games, current model with the goal-line / red-zone blend).

- **The shortfall is stable across seasons.** Actual / projected TDs: rushing 1.07 / 1.09 / 1.19, receiving 1.15 / 1.32 / 1.17, passing 0.95 / 1.06 / 0.93 (passing needs no change).
- **It is concentrated by position.** Rushing: QBs 1.34-1.45 (their rushing TDs are badly under-projected), RBs 1.03-1.09. Receiving: TEs 1.31-1.41, WRs 1.15-1.29, RBs 0.84-0.99 (RB receiving TDs are slightly OVER-projected). A flat scale hides that.
- **What it buys.** Bernoulli log-loss for "scores a TD" improves in every held-out season (rush 0.5127 -> 0.5118 flat, 0.5104 by position in 2023; rec 0.4666 -> 0.4639; 2024 and 2025 similar), small gains. Points BIAS improves (-10.5% -> -7.8%, -14.2% -> -12.5%, -9.7% -> -7.1%) because the touchdown mean is corrected.
- **What it does not buy.** Projected-points MAE gets slightly WORSE (4.627 -> 4.638, 4.865 -> 4.868, 4.786 -> 4.799). The points projection is a median (that is what MAE rewards, and the fantasy-points lean already adds its own fitted mean adjustment), and touchdowns are skewed counts: raising their mean moves the points projection away from the median.

Decision: the points projection is NOT recalibrated. The factors are the numbers to use when touchdown probabilities matter (an anytime-TD market, which the odds pull does not collect): QB rush x1.4, RB rush x1.05, WR rec x1.2, TE rec x1.35, RB rec x0.9, pass x1.0. Revisit if we add that market.

### Anytime touchdown prices (collection only)

The NFL odds pull now also requests `player_anytime_td` (one more market per game: about +1 credit a game on the ~7 already spent) and `fetch_odds.parse_td` keeps one row per (player, sportsbook) with the American price for Yes (and No where posted) in `data/log/td_lines_log.csv` (ts, event, commence, game, home, away, player, book, yes, no). Like the fantasy-points log it holds the LAST PRE-GAME price per (event, player, book), overwritten until kickoff. The DFS apps are skipped. Nothing is shown on the site and no leans are made yet: after a few weeks the plan is to compare the book-implied probability (vig removed) with the model's expected touchdowns, calibrated by position (QB rush x1.4, RB rush x1.05, WR rec x1.2, TE rec x1.35, RB rec x0.9) and the goal-line / red-zone shares, against who actually scored.

The points-allowed-by-position numbers also appear on the Game Board: above each team's table, a line shows the OPPOSING defence's PPR points allowed per game to QB, RB, WR and TE with its rank (1 = allows the most) and % versus the league (hover for the full wording). Reference only, as on Matchups.

### A changed starting QB no longer gets inflated attempts

Week 7 showed Tanner McKee (PHI; Hurts out, McKee the depth-chart QB1) with 54 attempts and 308 yards. He had one start (45 attempts) in the last six weeks, so the participation weighting treated him as a part-timer, shrank the team's weighted attempts, and the team-scale step pushed him to its +20% ceiling (45 x 1.2). Fix in `nfl_core`: when the depth chart's QB1 has played less recently than a backup (a changed starter), his participation weight is set to 1, so the team's attempts are scaled to the team's base, not stacked on him. McKee now 36 attempts, 227 yards, 14.5 points (was 54 / 308 / 19.9). The rule fires only in that situation: of the other starters, none changed (a first version that set every QB1 to full participation moved five healthy starters by 4-7 attempts and was rejected, as the backtest-tuned weighting is right for them). Live only (the backtest has no historical depth chart); no new setting, so the stamp is unchanged.

### Usage trend view (Usage tab > View > Weekly trend)

`analysis.usage_trend` -> `site/data/usage_trend.json`. For every RB / WR / TE (FB included) with 3+ games: weekly series of target share, carry share, share of the team's carries + targets, and snap %; the last `window` (3) games against the games BEFORE them (ratio of sums; the whole season when fewer than 2 games precede the window); and the team's own volume (targets a game for receivers, carries for backs) over the same split, so a team-wide change shows separately from a role change. The Role pill is RISING / FALLING when the main share (target share for WR/TE, share of carries + targets for RB) moves 5 points or more, and the top of the page lists the biggest risers and fallers with their snap change. Season-to-date shares stay on View > Season share.

### Weighting recent usage more for players whose role moved: tested, not adopted

Idea from the usage trend view: when a player's share of the team's carries or targets over the last 3 games has moved well away from his earlier games, trust the recent games more than the standing 20% recent weight (`RECENT_WEIGHT`). Walk-forward 2023-25, weeks 5+, RB/WR/TE (9,700 player-games; volume MAE = |projected - actual carries| + |projected - actual targets|):

| recent weight | where | players flagged | volume MAE (flagged) | volume MAE (all) |
|---|---|---|---|---|
| 0.20 | everyone (current) | - | 3.901 | 3.036 |
| 0.70 | share moved 10+ points | 2,900 | 3.857 | 3.022 |
| 0.90 | share moved 10+ points | 2,900 | 3.876 | 3.028 |
| 0.70 | share moved 15+ points | fewer | 3.867 | 3.025 |
| 0.50 | share moved 5+ points | 4,993 (half of all rows: 5 points is routine noise) | 3.559 vs 3.583 | 3.037 vs 3.050 |
| 0.35 / 0.50 | everyone, no flag | - | about the same as the flagged runs | 3.037 / 3.033 |

Raw volume improves by about 0.5% at best, and a plain higher weight for everyone does as well as the flag, so the share-move trigger adds nothing. Through the whole model it is slightly worse: with the 0.7 weight on 10+ point movers, rushing yards MAE 8.84 -> 8.86, 8.91 -> 8.98, 9.01 -> 9.10, receiving yards 18.00 -> 18.12, 17.75 -> 17.88, 17.11 -> 17.12 and projected points 5.398 -> 5.419, 5.581 -> 5.603, 5.474 -> 5.494 (2023/24/25); a global 0.35 or 0.50 is also flat to slightly worse. A recent share move is mostly noise that reverts, which is why the team-scale and season-long weighting win. The usage trend view stays as a reading aid, not a model input; the code was not kept.

### Passing fix: team pass attempts were running about 5 (15%) too high

Week 7's quarterback Over leans went about 5 of 15 (Mayfield 64 yards on a 215.5 line, Murray 150, Jones 108). Checking projected team pass attempts against what teams actually threw (2023-25, weeks 5+, 1,248 team-games) found the cause: the model's sum of attempts was +5.2 over actual (MAE 9.8), while simply using the team's own average of past attempts was unbiased (bias ~0, MAE 6.2). `CONCENTRATE_ATTEMPTS = 1` weighted the team's attempts by how often each passer has played and then scaled the UNWEIGHTED volumes to the team base, so every starter who missed a game (weight < 1) was scaled up by about 1/weight, up to the +20% cap. That inflated attempts for nearly every team; passing yards looked calibrated only because yards per attempt were being underestimated by about the same amount (the shrinkage toward the league mean and the wind/matchup factors), which is why this survived earlier backtests.

Fix: `CONCENTRATE_ATTEMPTS = 0` (the scale uses raw volumes; the relative weights for backups from `QB_PART` stay), plus a re-centring of the two rates that had been hiding the bias: `PASS_YPA_ADJ = 1.06` (yards per attempt) and `COMP_ADJ = 1.03` (completion rate), chosen from a 4-point grid on the same three seasons (two numbers, so mild in-sample fitting). Result, 2023 / 2024 / 2025:
- team attempts: bias +5.2 -> +0.8 before the re-centring, MAE 9.8 -> 7.0 (the team's own average is 6.2: the player-level share logic still adds noise);
- passing yards MAE 10.69 -> 10.25, 10.18 -> 9.93, 9.55 -> 9.18; completions MAE 0.876 -> 0.840, 0.816 -> 0.815, 0.807 -> 0.781;
- share of actuals above the passing-yards projection 50.6% / 53.3% / 52.1% (it was 48.8-51.1%), completions 51.9 / 56.5 / 49.4; passing yards bias +1.0 / -3.6 / +1.0%;
- projected points MAE 5.398 -> 5.385, 5.581 -> 5.578, 5.474 -> 5.466.
Week 7 2026 on its own: passing yards bias +10.1% -> about +1%, MAE 11.67 -> 11.17 before the re-centring. The new settings change the model stamp, so the NFL accuracy record restarts again (week 7 is scored under the old model).

### QB matchup strength and rolling defensive windows: tested, no change

Prompted by week 7, where QBs against the five most generous defences beat their projections by 3.5 points and those against the five stingiest fell short by 4.4 (n = 5 each). Backtest 2023-25 (weeks 5+), averages over the three seasons:

- **Is the passing matchup under-applied?** Raising the share of the measured passing matchup that is applied (`DEF_STRENGTH_PASS`, now 0.47) to 0.7 or 1.0 does not help: passing-yards MAE 9.784 -> 9.790 -> 9.816. Setting it to 0 gives 9.811, so the whole matchup is worth about 0.03 of a point per QB; completions (`DEF_STRENGTH_COMP` 0.66 vs 0.9 or 1.0) 0.812 -> 0.811; a smaller prior (`K_DEF_PASS` 40) 9.795. Projected points MAE is 5.476-5.478 in every case.
- **Does a defence's QB-points-allowed carry extra information?** Across 989 QB games (20+ projected attempts), the residual (actual minus projected points) rises 2.0 +- 1.5 points per +100% of "QB points allowed vs league" through the prior week, i.e. about +0.6 points for a defence 30% above average, not statistically distinguishable from zero, and unstable by season (slopes +0.7, -0.5, +5.6 in 2023, 2024, 2025). The most generous third of defences is +0.77 vs +0.66 for the middle third and -0.03 for the stingiest.
- **Rolling defensive data.** The defensive tables (yards per carry, catch rate, yards per reception, yards per target, completion rate, sacks, and the position splits) are season-to-date, regressed by sample size and capped; they are not rolling, and prior seasons are not used. Tested a rolling version two ways (games older than N weeks dropped, N = 4 or 6; or each older week's weight multiplied by 0.9, 0.8 or 0.7): no gain anywhere (passing yards MAE 9.784 season-to-date vs 9.807-9.838, completions 0.812 vs 0.816-0.820, rushing and receiving yards flat within 0.01, points 5.476 vs 5.479-5.486). With so few plays per defence per week the regression already does the smoothing; a window only throws data away.

Conclusion: week 7's gap was a five-player sample. The passing matchup stays at its fitted strength and the defensive tables stay season-to-date. The knobs were not kept.

### Returning-star rule (no lean on a starter whose history understates his role)

Week 7 MNF: Saquon Barkley (PHI RB1, Questionable, 4 of 6 games played, 2 and 4 carries in the two partial games) projected 33 rushing yards on a 61.5 line, a STRONG Under. His line prices the role he has when healthy; the model's history is dragged down by the games he missed or left. The model already withholds the lean for thin-sample (under 3 games) and role-shift players; it now also does so for a **returning star** (`ret` on the projection row, `RET_MISSED` = 2, `RET_WEEKS` = 3): a depth-chart starter (QB1, RB1, TE1, or a WR in ranks 1-3) with at least 3 games who has missed 2 or more of his team's games this season, or left a game early in the last 3 weeks (the partial-game detector). Currently 18 of 322 players carry it (Caleb Williams, Nacua, Penix, Bowers, Aaron Jones, Mayfield, Hall, Nico Collins, Chase, Goedert, Barkley and others). The Depth column shows a "returning" pill and the lean pill and strong tier are suppressed exactly as for thin and role-shift players; the projection itself is unchanged. No backtest (the depth chart is not available historically); the lean record shows whether those players' leans were the weaker ones once a few weeks have passed.

### PFF API evaluation (key in `PFF_API_KEY`, repo private; PFF's terms govern the data and it is never staged into the public site)

Access: `https://api.pff.com`, Bearer `ak_live_...` key, 100 reads a minute (exports metered separately), contract at `/openapi.json` (71 paths). Leaderboards by league (`nfl`, `ncaa`), season, week or game; game-level only (no play-by-play, no injuries). Probes: `pipeline/pff_probe.py` (docs), `pipeline/pff_api.py` (contract, one call or a batch, prints only column names and counts); pulls: `pipeline/pff_hist.py` (workflow `football-pff-hist.yml`) into `data/raw/pff_hist/`: NFL weekly receiving 2022-26, college receiving / passing / rushing / offense snaps 2024-26, per-game NFL team grades 2022-25.

What is there that nflverse and CFBD do not have: routes run, route rate and slot / wide / inline snaps (NFL and college), snaps by play type for every offensive player including linemen, alignment pivots, pass-blocking and pressure allowed by line position, QB pressure / blitz / time-to-throw splits, pass rush, run defence and coverage reports, team grades, depth-chart roster with grades. Tests so far (all walk-forward or leave-one-out, none adopted into the model):
- **Routes to targets (NFL, 2023-25, 9,230 WR/TE/RB player-weeks):** team pass plays x route rate x targets per route has target MAE 1.821 against the model's 1.802; a 50/50 blend 1.780 (-1.2%, same direction in every season, bias about 0 instead of -0.55). `pff_routes.py`. (PFF's `pass_plays` is the player's own pass snaps; the team's are the largest in the team-week.)
- **College role shares (weeks 6-8, 2,819 logged projections):** PFF last-3-game QB snap share, route rate and carry share add nothing out of sample to the current yardage projections (receiving yards MAE 24.78 vs 25.13, rushing 30.17 vs 31.19, passing 69.18 vs 70.74, one week held out at a time). The college QBs the books priced as starters that the model had as backups (Hasselbeck 20% of App State's passing snaps, Carr 17%, Clayton 22%) really were backups by usage: the line carries news (a starter out) that neither the model nor PFF has.
- **Team grades vs the closing line (NFL 2022-25, weeks 5+, 831 games):** a model of margin from the grade differences (overall, offence, defence, pass block, pass rush) and of the total from the grade sums, fitted on the other seasons, does not beat the market: BETA -0.28 to +0.33 (se about 0.2) on margins and -0.00 to +0.20 on totals, MAE 9.3-10.6 against the market's 8.9-10.0, hit rate at a 1-point edge 49-52%. `pff_grades.py`.
Conclusion so far: the data is rich and new but our existing usage-based projections already capture most of it; the one measurable gain is the roughly 1% target-volume improvement from blending routes. Tested since: OL / pressure inputs for QBs (below). Untested: grades as priors for thin-sample players, the depth-chart roster, and how soon after a game the weekly rows post (`lock_status`, `updatedAt`).

- **QB line and pressure (NFL 2023-25, weeks 5+, 1,045 QB games with 20+ projected attempts):** the model's miss (actual minus projection) against two pre-game PFF numbers, the QB's own line's pressures allowed per pass play and the opposing pass rush's pressures per dropback (season to date, regressed toward the league), fitted on the other seasons. Average miss as projected -> with the PFF inputs: passing yards 59.01 -> 58.87 (-0.2%), completions 4.770 -> 4.781 (+0.2%), sacks 1.337 -> 1.340 (+0.3%): nothing. Pooled coefficients are statistically visible but small: a line pressuring 3.4 points more per pass play (one sd) costs about 6.5 passing yards (t -2.8) and 0.5 completions (t -2.6), and either side adds about 0.08 sacks (t +1.6 own line, +2.1 opposing rush), a tenth of the typical miss. `pff_qbline.py`. Not adopted.

- **Does the routes gain compound through the model?** No. Carrying the 50/50 routes blend of projected targets through the whole model (re-deriving receptions, receiving yards and points for the same 8,371 WR/TE/RB player-weeks, 2023-25): targets MAE 1.874 -> 1.850 (-1.3%), receptions 1.459 -> 1.452 (-0.5%), receiving yards 19.170 -> 19.327 (+0.8%, worse), points 4.894 -> 4.908 (+0.3%, worse), the same direction in each season. The blend raises projected volume (target bias -13.5% -> -6.0%), but the yardage and catch rates downstream were calibrated against the lower volume and are medians, so the extra volume pushes yards away from the median. The small volume gain is largely absorbed or reversed. `pff_routes.run_full`. Using it would need yards per target recalibrated and the gain would still be about a percent.

## PFF roles on the site (display only)

The Usage "Weekly trend" view has PFF columns (alignment: Slot / Wide / Inline / Backfield with the split in the tooltip, route % per team pass play over the last 3 games, a weekly route-rate sparkline, targets per route, yards per route), and the Game Board has a "Role (PFF)" column. Built by `pipeline/pff_roles.py` from `data/raw/pff_hist/pff_receiving_<season>.csv`; the refresh workflow re-pulls the last two weeks plus the next (3 API calls, skipped without `PFF_API_KEY`). 270 of 276 projected skill players match PFF rows. Not a model input: the routes tests found no gain. Only derived numbers go into `site/data`; the raw PFF rows stay in this private repo. Check PFF's terms on redistribution before the site is public.

### PFF defence stats as model inputs: tested, no gain

`pipeline/pff_def.py`; PFF defence reports pulled for 2023-26 (`defsummary`, `defcoverage`, `defrun`; `defmatchup` returned nothing). Pre-game, season-to-date, regressed team features: yards and targets allowed per coverage snap, snap-weighted coverage grade, run-stop failure rate, run-defence grade, pressures per pass play. The model's miss (actual minus projection) for every skill player-game in weeks 5+ of 2023-25 is regressed on the features for the stat concerned, fitted on the other seasons (ridge). MAE as projected -> with the PFF defence features:
- receiving yards 24.79 -> 25.26 (+1.9%, worse), receptions 1.760 -> 1.771; WR 27.49 -> 28.00, TE 22.25 -> 22.61, RB 16.17 -> 16.10 (-0.4%, n = 587);
- rushing yards 27.01 -> 27.11 (+0.4%), carries 4.58 -> 4.54 (-0.8%); passing yards 59.01 -> 59.28, completions 4.77 -> 4.80.
Pooled slopes are mostly under t = 2 and flip sign by position (TE and RB receptions +0.2 per sd of yards-per-coverage-snap allowed, t +2.1; WR slightly negative); rushing-yards slope +2.3 yards per sd of run-stop failure (t +1.9), but out of sample it does not help. Same conclusion as the earlier opponent tests: season-to-date defensive rates are too noisy to move a player projection beyond what the model's opponent multipliers already do. Not adopted.

### Three more model tests (walk-forward, weeks 5+): game script / pace, tight end out, PFF priors for thin-sample players. None adopted.

**Game script and pace** (`pipeline/game_script.py`, 1,248 team-games 2023-25). Team volume misses (actual minus the sum of the players' projections) against the spread (+ = favoured), the game total and each team's own and the opponent's pace (attempts + carries a game to date), fitted on the other seasons. The signal is real at team level: MAE of team pass attempts 6.85 -> 6.65 (-2.8%), carries 6.45 -> 6.23 (-3.5%), targets 6.16 -> 6.08 (-1.3%). Per 1 sd: spread +1.4 carries (t +5.9, favourites run more), +0.8 attempts; total +1.5 attempts (t +6.1); own pace -1.1 to -1.6 (t -4 to -7: the model leans too hard on a team's own history, a pace-heavy team regresses). Carried through the whole model (scaling each team's att / car / tgt, re-deriving every player) the gain nearly vanishes: rushing yards MAE 8.352 -> 8.310 (-0.5%), receptions 1.291 -> 1.291, receiving yards 16.946 -> 16.935, passing yards 66.58 -> 66.41 (-0.2%), completions -0.4%, points 5.191 -> 5.184 (-0.1%). The team-level gain is mostly absorbed by player-level noise and the median calibration. Not adopted; the spread and total are not in the model's volumes today, so this is the first thing to revisit if the team-volume scale is reworked.

**Tight end listed OUT** (`pipeline/out_te.py`, knob `OUT_TE`, off). Remove an OUT TE from the pool as is done for RB / WR / QB: the other TEs on those teams improve a little (228 player-games, targets MAE 1.819 -> 1.786, points 3.948 -> 3.898, -1.3%), their wide receivers and backs do not (1,109 player-games: points 5.030 -> 5.048, +0.4%); overall points 4.846 -> 4.852. Kept off.

**PFF priors for thin-sample players** (`pipeline/pff_prior.py`, 2024-25). WR / TE / RB with fewer than 3 games this season (253 player-weeks, 156 with a PFF row last year; 1,695 and 1,266 at fewer than 6 games): last season's route rate, targets per route, yards per route and pass-route grade (regressed by routes toward the position). Last season's route rate carries a clear pooled signal on the misses (+0.3 targets, +3.5 receiving yards per sd, t +4.3 to +4.8 at fewer than 6 games), but out of sample (fitted on the other season) MAE does not improve: targets 1.736 -> 1.735, receptions 1.336 -> 1.339, receiving yards 17.47 -> 17.67; at fewer than 3 games all three get slightly worse. Targets per route, yards per route and grade add nothing (t under 1.3). Not adopted.

### Player-vs-player coverage (PFF receiver-versus-defender pairs): tested, no gain

`pipeline/pff_cov.py`; `/v1/facet/receiving/coverage` pulled for 2023-26 (`covvs_<s>.csv`: one row per receiver / covering defender pair that had a target, with targets, yards, touchdowns; `covdef_<s>.csv`: each defender's game coverage grade). The pairs have no coverage snaps (only thrown-at plays), and PFF's own matchup page (GREAT / projected snaps per defender, "vs similar coverage") is not in the API, so who covers whom before a game has to be estimated. Two pre-game, season-to-date features: the target-weighted coverage grade of the opposing defenders who were thrown at by receivers of his position (regressed with 40 targets), and, for the team's leading WR / TE, the best coverage grade among the opponent's defenders with 10+ targets faced (the shadow-corner effect). Walk-forward, 4,372 WR / TE / RB player-games (3+ projected targets, weeks 5+, 2023-25), fitted on the other seasons: receptions MAE 1.764 -> 1.778 (+0.8%), receiving yards 24.84 -> 25.36 (+2.1%); WR 27.50 -> 28.10, TE 22.39 -> 22.88, RB 16.02 -> 16.00. The shadow feature has the right sign for lead receivers (-3.2 receiving yards per sd, t -2.3, 1,098 games) but does not survive out of sample (30.44 -> 30.96). Not adopted. Same answer as the team-level defence test: the coverage side is too noisy week to week, and what is predictable (a good corner, a weak slot) is already in the lines and in the model's opponent factors.

## Projected matchup strength on the boards (visual only)

The Projections table and the Game Board have a "Matchup (PFF)" column for WR / TE / RB: a pill (GREAT 27-32, GOOD 21-26, EVEN 12-20, TOUGH 7-11, HARD 1-6) with the opposing coverage's rank among the 32 teams (32 = weakest coverage). `pipeline/pff_matchups.py`: the target-weighted coverage grade of the defenders thrown at by receivers of that position group (PFF receiver-versus-defender pairs and defender coverage grades, season to date, regressed with 40 targets; each defender's grade regressed with 100 coverage snaps). It reproduces PFF's own page for Flowers against Buffalo (weakest coverage, 32nd of 32; Alford, Igbinosun and Benford the most targeted). The tests (above) found no predictive gain from coverage features, so this is a display aid, not a model input; the tooltip says so. The likely covering defenders (name, position, coverage rank, share of the group's targets) are built but not published: `PFF_SHOW_DEFENDERS` is False until PFF's terms on redistributing player-level data are confirmed; only the team-level rating and rank are in `site/data`.

### College boards: PFF alignment, routes and coverage matchups (visual only)

The college Projections table and Game Board have "Alignment (PFF)" (Slot / Wide / Inline / Backfield with the split in the tooltip, plus routes per team pass play over the last 3 games) and "Matchup (PFF)" (the opposing coverage's strength against his position group, GREAT to HARD, rank among the teams in the model's slate) columns, built exactly as on the NFL page (`pipeline/pff_roles.py`, `pipeline/pff_matchups.py`, league `ncaa`). PFF's college team names are truncated strings ("E WASHGTON", "MICH STATE"); `pipeline/pff_teams.py` maps them to CollegeFootballData names (all 112 teams in the current slate map; 886 of 988 projected WR / TE / RB match a PFF receiving row). PFF college week ids equal CFBD weeks. The refresh workflow re-pulls the last two weeks plus the next of the college receiving, defender coverage and pairs files (9 calls). Defender names stay unpublished (`PFF_SHOW_DEFENDERS` False). Shared display helpers (`muCell`, `roleCell`) moved to `site/common.js`.

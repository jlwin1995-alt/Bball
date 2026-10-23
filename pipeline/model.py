"""Projection engine. Pure functions over DataFrames so build.py and backtest.py share one path.

games columns: pid,name,team,pos,date,opp,home,season,min,pts,reb,ast,fg3m,stl,blk,tov,fgm,fga,ftm,fta
slate columns: date,team,opp,home         (one row per team playing on the projected date)
"""
import numpy as np
import pandas as pd
from . import config as C
from .fetch_nba_api import norm

POS_MAP = {"PG": "G", "SG": "G", "G": "G", "GF": "F", "SF": "F", "PF": "F", "F": "F", "FC": "C", "C": "C"}


def norm_pos(p):
    return POS_MAP.get(str(p).upper(), "F")


def _prep(games):
    g = games[games["min"] > 0].copy()
    g["date"] = pd.to_datetime(g["date"])
    g["pos"] = g["pos"].map(norm_pos)
    age = C.SEASON - g["season"]
    g["w"] = np.select([age <= 0, age == 1, age == 2], [1.0, C.PRIOR_SEASON_WEIGHT, C.PRIOR2_SEASON_WEIGHT], 0.0)   # two seasons back only backs up players' own rates
    g = g[g["w"] > 0]
    g["recent"] = age <= 1
    return g.sort_values("date")


def defence_table(g):
    """Per-team opponent multipliers by stat: what each defence allowed vs league, regressed and damped."""
    g = g[g["recent"]]                                              # rosters turn over: defences and pace use this and last season only
    tg = g.groupby(["opp", "date", "w"])[C.STATS].sum().reset_index()
    out = {}
    lg = {s: np.average(tg[s], weights=tg["w"]) for s in C.STATS}
    for team, d in tg.groupby("opp"):
        n = d["w"].sum()
        shrink = n / (n + C.DEF_PRIOR_GAMES)
        row = {"games": round(float(n), 1)}
        for s in C.STATS:
            raw = np.average(d[s], weights=d["w"]) / lg[s]
            m = 1 + np.clip((raw - 1) * shrink, -C.DEF_ADJ_CAP, C.DEF_ADJ_CAP)
            row[s + "_raw"] = float(m)                                   # undamped, for display
            row[s] = float(1 + (m - 1) * C.DEF_STRENGTH[s])               # what the projection uses
        out[team] = row
    return out


def team_env(g):
    """Per-team shrunk pace (possessions per game, both sides) and average point margin, plus the league pace. Box scores only."""
    g = g[g["recent"]].assign(poss=g["fga"] + 0.44 * g["fta"] + g["tov"])
    tg = g.groupby(["team", "opp", "date", "w"], as_index=False)[["poss", "pts"]].sum()
    o = tg.rename(columns={"team": "opp", "opp": "team", "pts": "pts_o", "poss": "poss_o"})[["team", "opp", "date", "pts_o", "poss_o"]]
    tg = tg.merge(o, on=["team", "opp", "date"])
    tg["pace"] = (tg["poss"] + tg["poss_o"]) / 2
    tg["margin"] = tg["pts"] - tg["pts_o"]
    lg = float(np.average(tg["pace"], weights=tg["w"])) if len(tg) else 100.0
    out = {}
    for team, d in tg.groupby("team"):
        n = d["w"].sum()
        sh = n / (n + C.ENV_PRIOR_GAMES)
        out[team] = {"pace": lg + (np.average(d["pace"], weights=d["w"]) - lg) * sh, "margin": float(np.average(d["margin"], weights=d["w"]) * sh)}
    return out, lg


def play_rates(g):
    """Share of each player's recent team games he actually played in (last PLAY_WINDOW team games, since he joined the team)."""
    out = {}
    for team, d in g.groupby("team"):
        dates = np.sort(d["date"].unique())[-C.PLAY_WINDOW:]
        for pid, pd_ in d[d["date"].isin(dates)].groupby("pid"):
            first = pd_["date"].min()
            denom = max(int((dates >= first).sum()), 1)
            out[(team, pid)] = min(len(pd_) / denom, 1.0)
    return out


def player_rates(g, asof, fallback=None, reg_mode=False):
    """Shrunk per-minute rates, projected minutes, and bookkeeping per player.
    fallback: preseason box scores (same columns as games). Players without MIN_GAMES of regular-season history are built from
    them instead of being dropped (rookies, players back from a missed season); flagged pre_only when ALL their games are preseason."""
    pp = play_rates(g)
    lg_rate = {}
    for pos, d in g.groupby("pos"):
        lg_rate[pos] = {s: (d[s] * d["w"]).sum() / (d["min"] * d["w"]).sum() for s in C.STATS}
    gall = g.assign(pre=False)
    if fallback is not None and len(fallback):
        have = g.groupby("pid")["w"].sum()
        fb = fallback[~fallback["pid"].astype(str).isin(have[have >= C.MIN_GAMES].index)].copy()
        fb["pid"] = fb["pid"].astype(str)
        fb["date"] = pd.to_datetime(fb["date"])
        fb = fb[fb["min"] > 0]                                        # the caller already cut it off at the slate day
        fb["pos"] = fb["pos"].map(norm_pos)
        fb["w"] = 1.0
        fb["pre"] = True
        for pos in fb["pos"].unique():
            lg_rate.setdefault(pos, next(iter(lg_rate.values())) if lg_rate else {s: 0.0 for s in C.STATS})
        gall = pd.concat([gall, fb], ignore_index=True)
    rows = []
    for pid, d in gall.groupby("pid"):
        d = d.sort_values("date")
        last = d.iloc[-1]
        gw = d["w"].sum()
        pre_only = bool(d["pre"].all())
        if gw < (1 if pre_only else C.MIN_GAMES):
            continue
        rec = d.tail(C.ROLLING_WINDOW)
        mw = (d["min"] * d["w"]).sum()
        mr = rec["min"].sum()
        pos = last["pos"]
        if pre_only:                                                  # his preseason minutes are a noisy guide: pull toward a rookie-ish default
            min_s = (mw + C.PRE_ONLY_MIN_K * C.PRE_ONLY_MIN_PRIOR) / (gw + C.PRE_ONLY_MIN_K)
            min_r = (mr + C.PRE_ONLY_MIN_K * C.PRE_ONLY_MIN_PRIOR) / (len(rec) + C.PRE_ONLY_MIN_K)
            pplay = float(np.clip(C.PRE_ONLY_PPLAY_A + C.PRE_ONLY_PPLAY_B * (mw / gw), C.PRE_ONLY_PPLAY_LO, C.PRE_ONLY_PPLAY_HI)) if reg_mode else C.PRE_ONLY_PPLAY
        else:
            min_s, min_r, pplay = mw / gw, rec["min"].mean(), pp.get((last["team"], pid), 0.0)
        r = {"pid": pid, "name": last["name"], "team": last["team"], "pos": pos, "pre_only": pre_only,
             "g": round(float(gw), 1), "last_game": last["date"],
             "min_s": min_s, "min_r": min_r, "pplay": pplay}
        for s in C.STATS:
            k = C.RATE_PRIOR_MIN[s]
            num = (d[s] * d["w"]).sum() + C.RECENT_EXTRA * rec[s].sum() + k * lg_rate[pos][s]
            den = mw + C.RECENT_EXTRA * mr + k
            r["pm_" + s] = num / den
        rows.append(r)
    R = pd.DataFrame(rows)
    if len(R):                                                        # un-shrink: stretch rates about the league rate (see CAL_RATE_SLOPE)
        w = R["min_s"].where(R["min_s"] >= 15, 0.0)
        for s in C.STATS:
            b = C.CAL_RATE_SLOPE.get(s, 1.0)
            if b != 1.0 and w.sum() > 0:
                mu = (R["pm_" + s] * w).sum() / w.sum()
                R["pm_" + s] = (mu + b * (R["pm_" + s] - mu)).clip(lower=0.0)
    return R


def project(games, slate, injuries=None, asof=None, rosters=None, minute_mult=None, fallback=None):
    games = games.astype({"pid": str})
    g = _prep(games)
    asof = pd.Timestamp(asof) if asof else g["date"].max() + pd.Timedelta(days=1)
    g = g[g["date"] < asof]
    if fallback is not None and len(fallback):                      # preseason rows only count if they are BEFORE the day being projected
        fallback = fallback[pd.to_datetime(fallback["date"]) < pd.to_datetime(slate["date"]).min()]
    P = player_rates(g, asof, fallback, reg_mode=not minute_mult)
    D = defence_table(g)
    if rosters is not None and len(rosters) >= 350:           # a full league's worth; a partial fetch must not drop people
        cur = dict(zip(rosters["pid"].astype(str), rosters["team"]))
        P = P[P["pid"].isin(cur)].copy()                       # on no roster = not playing
        P["team"] = P["pid"].map(cur)                          # traded over the summer -> his new team
    slate = slate.copy()
    slate["date"] = pd.to_datetime(slate["date"])
    day = slate["date"].min()
    slate = slate[slate["date"] == day]
    last_played = g.groupby("team")["date"].max()

    P = P.merge(slate[["team", "opp", "home"]], on="team", how="inner")
    status = {}
    if injuries is not None and len(injuries):
        inj = injuries.dropna(subset=["status"]).copy()
        inj["pid"] = inj["pid"].astype(str).where(inj["pid"].notna(), "")
        has = ~inj["pid"].isin(["None", "nan", ""])
        status = dict(zip(inj[has].drop_duplicates("pid", keep="last")["pid"], inj[has].drop_duplicates("pid", keep="last")["status"]))
        by_name = {(norm(n), t): s for n, t, s in zip(inj[~has]["name"], inj[~has]["team"], inj[~has]["status"])}   # older files / feeds without an id
    P["status"] = P["pid"].map(status).fillna("")
    if injuries is not None and len(injuries):
        P["status"] = np.where(P["status"] == "", [by_name.get((norm(n), t), "") for n, t in zip(P["name"], P["team"])], P["status"])
    team_last = P["team"].map(last_played)
    P["active"] = (team_last - P["last_game"]).dt.days <= C.ACTIVE_DAYS   # relative to the team, so the offseason does not drop everyone
    have_injuries = injuries is not None and len(injuries) > 0
    # With a live injury report the report decides: a player who has not played for weeks but is not listed is healthy (Irving, Kessler,
    # Young were all excluded by the 21-day rule). The rule only stands in when there is no report (backtests, a failed fetch).
    P["out"] = P["status"].isin(["Out", "Doubtful"]) | (~P["active"] & (not have_injuries))

    P["rest"] = P["team"].map(lambda t: (day - last_played[t]).days if t in last_played else np.nan)
    P.loc[P["rest"] > 14, "rest"] = np.nan                            # offseason gap is not a rest signal
    rest_mult = np.where(P["rest"] <= 1, C.B2B_MIN_MULT, np.where(P["rest"] >= 3, C.RESTED_MIN_MULT, 1.0))
    qm = np.where(P["status"].isin(["Questionable", "Day-To-Day"]), C.QUESTIONABLE_MIN_MULT, 1.0)
    P["min_raw"] = (C.RECENT_WEIGHT_MIN * P["min_r"] + (1 - C.RECENT_WEIGHT_MIN) * P["min_s"]) * rest_mult * qm
    P.loc[P["out"], "min_raw"] = 0.0
    if not minute_mult:                                              # regular-season slate: no-history players play ~1.1x their preseason minutes
        po = P["pre_only"] & ~P["out"]
        P.loc[po, "min_raw"] = np.clip(C.PRE_ONLY_MIN_A + C.PRE_ONLY_MIN_B * P.loc[po, "min_raw"], 0, C.MAX_MIN)
        role = P["name"].map(C.ROOKIE_ROLE_MIN)
        ncur = P["pid"].map(g[g["season"] == C.SEASON].groupby("pid").size()).fillna(0)       # regular-season games so far this season
        P["role_set"] = role.notna() & (ncur < 3) & ~P["out"]          # hand-set roles apply until the player has 3 games of his own
        P.loc[P["role_set"], "min_raw"] = role[P["role_set"]]
        P.loc[P["role_set"], "pplay"] = C.ROOKIE_ROLE_PPLAY
        bench = P["name"].isin(C.ROOKIE_BENCH) & (ncur < 3) & ~P["out"] & ~P["role_set"]
        P.loc[bench, "min_raw"] = C.ROOKIE_BENCH_MIN
        P.loc[bench, "pplay"] = C.ROOKIE_BENCH_PPLAY
        P["role_set"] = P["role_set"] | bench                    # fixed minutes: not part of the leftover sharing

    # Minutes above are conditional on playing; a team's 240 is shared by whoever dresses, so the
    # rescale sums EXPECTED minutes (weighted by how often each man plays) and is applied to the conditional ones.
    P["min_exp"] = P["min_raw"] * P["pplay"]
    tot = P.groupby("team")["min_exp"].transform("sum")
    fac = np.clip(C.TEAM_MINUTES / tot.replace(0, np.nan), *C.RESCALE_CLIP).fillna(1.0)
    fac = 1 + C.RESCALE_STRENGTH * (fac - 1)                     # how much of the rescale to believe (measured: pipeline.usage_test)
    if not minute_mult and C.PRE_ONLY_RESCALE:                    # established players first: no-history players share only the minutes left over
        po = P["pre_only"] & ~P["role_set"]
        est = P["min_exp"].where(~po, 0.0).groupby(P["team"]).transform("sum")
        rk = P["min_exp"].where(po, 0.0).groupby(P["team"]).transform("sum")
        fr = np.clip((C.TEAM_MINUTES - est) / rk.replace(0, np.nan), 0.3, 1.0).fillna(1.0)
        fac = np.where(po, 1 + C.PRE_ONLY_RESCALE * (fr - 1), fac)
    P["min"] = np.minimum(P["min_raw"] * fac, C.MAX_MIN)
    if not minute_mult and C.EARLY_TIGHTEN_GAMES:                  # opening weeks: rotations are shorter than last season's
        tgames = g[g["season"] == C.SEASON].groupby("team")["date"].nunique()
        w = np.clip(1 - P["team"].map(tgames).fillna(0) / C.EARLY_TIGHTEN_GAMES, 0, 1)
        rk = P.groupby("team")["min"].rank(ascending=False, method="first")
        cut = np.select([rk <= 5, rk <= 8], [C.EARLY_TIGHTEN_CUTS[0], C.EARLY_TIGHTEN_CUTS[1]], C.EARLY_TIGHTEN_CUTS[2])
        P["min"] = P["min"] * (1 - w * cut)
    P["min_noadj"] = P["min"]
    # Preseason mode: stars/starters play a fraction of their normal minutes. A multiplier by tier replaces the
    # 240 rescale (which would just undo it): the missing minutes go to rookies/two-way players we do not project.
    P["tier"] = np.where(P["min_raw"] >= C.TIER_CUTS[0], "T1", np.where(P["min_raw"] >= C.TIER_CUTS[1], "T2", "T3"))
    if minute_mult and "lin" in minute_mult:                       # preseason: minutes = a + b x usual minutes (fitted, see PRESEASON_CUR_WEIGHT)
        a, b = minute_mult["lin"]
        mapped = np.where(P["min_raw"] > 0, np.clip(a + b * P["min_raw"], 0, C.MAX_MIN), 0.0)
        P["min"] = np.where(P["pre_only"], np.minimum(P["min_raw"], C.MAX_MIN), mapped)      # no-history players already carry preseason minutes
    elif minute_mult:
        P["min"] = np.where(P["pre_only"], np.minimum(P["min_raw"], C.MAX_MIN), P["min_raw"] * P["tier"].map(minute_mult).fillna(1.0))
    env, lg_pace = team_env(g)
    P["pace_f"] = P.apply(lambda r: (env.get(r["team"], {}).get("pace", lg_pace) + env.get(r["opp"], {}).get("pace", lg_pace)) / 2 / lg_pace, axis=1)
    P["exp_margin"] = P.apply(lambda r: env.get(r["team"], {}).get("margin", 0.0) - env.get(r["opp"], {}).get("margin", 0.0)
                              + (C.HOME_MARGIN if r["home"] == 1 else -C.HOME_MARGIN), axis=1)
    if not minute_mult and C.BLOWOUT_SLOPE:                       # starters sit in expected blowouts (not in preseason mode: tier multipliers rule there)
        P.loc[P["tier"] == "T1", "min"] -= C.BLOWOUT_SLOPE * np.clip(P["exp_margin"].abs() - C.BLOWOUT_HINGE, 0, None)
    P["site_mult"] = np.where(P["home"] == 1, C.HOME_MULT, C.AWAY_MULT)

    for s in C.STATS:
        adj = P["opp"].map(lambda t: D.get(t, {}).get(s, 1.0))
        P["adj_" + s] = adj
        P["rate_" + s] = P["pm_" + s] * adj * P["site_mult"] * (1 + C.PACE_STRENGTH * (P["pace_f"] - 1))           # per-minute, fully adjusted
        P[s] = P["min"] * P["rate_" + s]
    P["date"] = day
    P["team_min_factor"] = fac
    return P.sort_values(["team", "min"], ascending=[True, False]).reset_index(drop=True), D


def all_players(games, rosters=None, minute_mult=None, fallback=None):
    """Every player we have history for: expected minutes IF he plays and per-minute rates, with no slate or opponent attached.
    The Live tab uses it to project players in games that are not in the daily slate (today's later games, yesterday's, preseason)."""
    g = _prep(games.astype({"pid": str}))
    P = player_rates(g, None, fallback, reg_mode=not minute_mult)
    if rosters is not None and len(rosters) >= 350:
        cur = dict(zip(rosters["pid"].astype(str), rosters["team"]))
        P = P[P["pid"].isin(cur)].copy()
        P["team"] = P["pid"].map(cur)
    raw = C.RECENT_WEIGHT_MIN * P["min_r"] + (1 - C.RECENT_WEIGHT_MIN) * P["min_s"]
    tier = np.where(raw >= C.TIER_CUTS[0], "T1", np.where(raw >= C.TIER_CUTS[1], "T2", "T3"))
    if minute_mult and "lin" in minute_mult:
        a, b = minute_mult["lin"]
        adj = np.clip(a + b * raw, 0, C.MAX_MIN)
    else:
        adj = np.minimum(raw * (pd.Series(tier, index=P.index).map(minute_mult).fillna(1.0) if minute_mult else 1.0), C.MAX_MIN)
        if not minute_mult:                                          # regular season: no-history players, same mapping as project()
            adj = np.where(P["pre_only"], np.clip(C.PRE_ONLY_MIN_A + C.PRE_ONLY_MIN_B * raw, 0, C.MAX_MIN), adj)
            role = P["name"].map(C.ROOKIE_ROLE_MIN)
            adj = np.where(P["pre_only"] & role.notna(), role.fillna(0), adj)
            adj = np.where(P["pre_only"] & P["name"].isin(C.ROOKIE_BENCH) & role.isna(), C.ROOKIE_BENCH_MIN, adj)
    P["min_exp"] = np.where(P["pre_only"], np.minimum(raw, C.MAX_MIN), adj) if minute_mult else adj
    return P.reset_index(drop=True)


def fantasy(df, scoring=None):
    sc = scoring or C.DEFAULT_SCORING
    return sum(df[s] * w for s, w in sc.items())

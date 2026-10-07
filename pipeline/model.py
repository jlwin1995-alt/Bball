"""Projection engine. Pure functions over DataFrames so build.py and backtest.py share one path.

games columns: pid,name,team,pos,date,opp,home,season,min,pts,reb,ast,fg3m,stl,blk,tov,fgm,fga,ftm,fta
slate columns: date,team,opp,home         (one row per team playing on the projected date)
"""
import numpy as np
import pandas as pd
from . import config as C

POS_MAP = {"PG": "G", "SG": "G", "G": "G", "GF": "F", "SF": "F", "PF": "F", "F": "F", "FC": "C", "C": "C"}


def norm_pos(p):
    return POS_MAP.get(str(p).upper(), "F")


def _prep(games):
    g = games[games["min"] > 0].copy()
    g["date"] = pd.to_datetime(g["date"])
    g["pos"] = g["pos"].map(norm_pos)
    g["w"] = np.where(g["season"] == C.SEASON, 1.0, C.PRIOR_SEASON_WEIGHT)
    return g.sort_values("date")


def defence_table(g):
    """Per-team opponent multipliers by stat: what each defence allowed vs league, regressed and damped."""
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


def player_rates(g, asof):
    """Shrunk per-minute rates, projected minutes, and bookkeeping per player."""
    pp = play_rates(g)
    lg_rate = {}
    for pos, d in g.groupby("pos"):
        lg_rate[pos] = {s: (d[s] * d["w"]).sum() / (d["min"] * d["w"]).sum() for s in C.STATS}
    rows = []
    for pid, d in g.groupby("pid"):
        d = d.sort_values("date")
        last = d.iloc[-1]
        gw = d["w"].sum()
        if gw < C.MIN_GAMES:
            continue
        rec = d.tail(C.ROLLING_WINDOW)
        mw = (d["min"] * d["w"]).sum()
        mr = rec["min"].sum()
        pos = last["pos"]
        r = {"pid": pid, "name": last["name"], "team": last["team"], "pos": pos,
             "g": round(float(gw), 1), "last_game": last["date"],
             "min_s": mw / gw, "min_r": rec["min"].mean(), "pplay": pp.get((last["team"], pid), 0.0)}
        for s in C.STATS:
            k = C.RATE_PRIOR_MIN[s]
            num = (d[s] * d["w"]).sum() + C.RECENT_EXTRA * rec[s].sum() + k * lg_rate[pos][s]
            den = mw + C.RECENT_EXTRA * mr + k
            r["pm_" + s] = num / den
        rows.append(r)
    return pd.DataFrame(rows)


def project(games, slate, injuries=None, asof=None):
    games = games.astype({"pid": str})
    g = _prep(games)
    asof = pd.Timestamp(asof) if asof else g["date"].max() + pd.Timedelta(days=1)
    g = g[g["date"] < asof]
    P = player_rates(g, asof)
    D = defence_table(g)
    slate = slate.copy()
    slate["date"] = pd.to_datetime(slate["date"])
    day = slate["date"].min()
    slate = slate[slate["date"] == day]
    last_played = g.groupby("team")["date"].max()

    P = P.merge(slate[["team", "opp", "home"]], on="team", how="inner")
    status = {}
    if injuries is not None and len(injuries):
        inj = injuries.dropna(subset=["pid", "status"]).astype({"pid": str})
        inj = inj[~inj["pid"].isin(["None", "nan", ""])].drop_duplicates("pid", keep="last")
        status = dict(zip(inj["pid"], inj["status"]))
    P["status"] = P["pid"].map(status).fillna("")
    team_last = P["team"].map(last_played)
    P["active"] = (team_last - P["last_game"]).dt.days <= C.ACTIVE_DAYS   # relative to the team, so the offseason does not drop everyone
    P["out"] = P["status"].isin(["Out", "Doubtful"]) | ~P["active"]

    P["rest"] = P["team"].map(lambda t: (day - last_played[t]).days if t in last_played else np.nan)
    P.loc[P["rest"] > 14, "rest"] = np.nan                            # offseason gap is not a rest signal
    rest_mult = np.where(P["rest"] <= 1, C.B2B_MIN_MULT, np.where(P["rest"] >= 3, C.RESTED_MIN_MULT, 1.0))
    qm = np.where(P["status"].isin(["Questionable", "Day-To-Day"]), C.QUESTIONABLE_MIN_MULT, 1.0)
    P["min_raw"] = (C.RECENT_WEIGHT_MIN * P["min_r"] + (1 - C.RECENT_WEIGHT_MIN) * P["min_s"]) * rest_mult * qm
    P.loc[P["out"], "min_raw"] = 0.0

    # Minutes above are conditional on playing; a team's 240 is shared by whoever dresses, so the
    # rescale sums EXPECTED minutes (weighted by how often each man plays) and is applied to the conditional ones.
    P["min_exp"] = P["min_raw"] * P["pplay"]
    tot = P.groupby("team")["min_exp"].transform("sum")
    fac = np.clip(C.TEAM_MINUTES / tot.replace(0, np.nan), *C.RESCALE_CLIP).fillna(1.0)
    P["min"] = np.minimum(P["min_raw"] * fac, C.MAX_MIN)
    P["site_mult"] = np.where(P["home"] == 1, C.HOME_MULT, C.AWAY_MULT)

    for s in C.STATS:
        adj = P["opp"].map(lambda t: D.get(t, {}).get(s, 1.0))
        P["adj_" + s] = adj
        P["rate_" + s] = P["pm_" + s] * adj * P["site_mult"]           # per-minute, fully adjusted
        P[s] = P["min"] * P["rate_" + s]
    P["date"] = day
    P["team_min_factor"] = fac
    return P.sort_values(["team", "min"], ascending=[True, False]).reset_index(drop=True), D


def fantasy(df, scoring=None):
    sc = scoring or C.DEFAULT_SCORING
    return sum(df[s] * w for s, w in sc.items())

"""How each teammate has played with and without a rotation man who is OUT tonight  ->  site/data/absence.json   (display only)

    python -m pipeline.absence

For every team on the slate, the rotation players who are out (averaged 20+ minutes over their last 10 games, played within the last 120 days) are the
"stars". For each healthy teammate the box scores since the star joined the team are split into games the star played and games he missed:
minutes, points, rebounds, assists and fantasy points (DEFAULT_SCORING) in each. Needs 5+ games with and 3+ without. Samples are small and the
"without" games often have other absences too, so the site shows the number of games and greys under 5. A 2025-26 walk-forward test found these splits
add only a little beyond the model (slope +0.17 +/- 0.04 FP per predicted FP), so this is NOT in the projections.
"""
import json, os
import pandas as pd
from . import config as C

MIN_ON, MIN_OFF = 5, 3
STAR_MIN, STAR_RECENT_DAYS = 20.0, 120
SHOW_MIN = 8.0                    # teammates projected for fewer minutes are skipped
MAX_STARS = 3


def _fp(d):
    return sum(d[s] * w for s, w in C.DEFAULT_SCORING.items())


def build(games, P, today=None):
    g = games[games["min"] > 0].copy(); g["pid"] = g["pid"].astype(str); g["date"] = pd.to_datetime(g["date"])
    g["fp"] = _fp(g)
    today = pd.Timestamp(today) if today is not None else pd.Timestamp(P["date"].iloc[0]) if len(P) else g["date"].max() + pd.Timedelta(days=1)
    g = g[g["date"] < today]
    P = P.copy(); P["pid"] = P["pid"].astype(str)
    stars, players = {}, {}
    last10 = g.sort_values("date").groupby("pid").tail(10)
    lm = last10.groupby("pid").agg(m=("min", "mean"), last=("date", "max"), name=("name", "last"))
    for team, tp in P.groupby("team"):
        T = g[g["team"] == team]
        out = tp[tp["out"]]
        st = []
        for _, s in out.iterrows():
            x = lm.loc[s.pid] if s.pid in lm.index else None
            if x is None or x.m < STAR_MIN or (today - x["last"]).days > STAR_RECENT_DAYS: continue
            sd = T[T.pid == s.pid]
            if sd.empty: continue                                  # no games with this team yet
            st.append((s.pid, s["name"], x.m, set(sd["date"]), sd["date"].min()))
        if not st: continue
        st.sort(key=lambda t: -t[2])
        stars[team] = [{"pid": p, "name": n, "min": round(float(m), 1)} for p, n, m, _, _ in st]
        for _, p in tp[~tp["out"] & (tp["min_raw"] >= SHOW_MIN)].iterrows() if "min_raw" in tp else tp[~tp["out"]].iterrows():
            rows = []
            for sp, sn, sm, sdates, first in st[:MAX_STARS]:
                if sp == p.pid: continue
                pg = T[(T.pid == p.pid) & (T["date"] >= first)]
                on, off = pg[pg["date"].isin(sdates)], pg[~pg["date"].isin(sdates)]
                if len(on) < MIN_ON or len(off) < MIN_OFF: continue
                rows.append([sn, len(on), len(off)] + [round(float(v), 1) for c in ("min", "pts", "reb", "ast", "fp") for v in (on[c].mean(), off[c].mean())])
            if rows: players[p.pid] = rows
    return {"stars": stars, "players": players}


def main(P, games, out="site/data"):
    res = build(games, P)
    json.dump(res, open(os.path.join(out, "absence.json"), "w"), separators=(",", ":"))
    return res

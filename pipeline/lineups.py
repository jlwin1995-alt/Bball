"""Projected starting lineups from who has been starting  ->  site/data/lineups.json  (display only: nothing here feeds the projections)

There is no public pregame lineup feed for the NBA, so, like the college side of the football site, the lineup is INFERRED from usage: for each team, the players with the most starts in its last N games (N = 10),
ties broken by minutes. The site then walks that list, skipping anyone the injury report lists Out tonight (the next man up takes the spot) and flags anyone Day-To-Day.
Starts come from the box scores' starter flags in data/raw/stints.csv.gz (one starter flag per player per game, five per team).

`acc` backtests the rule on every team-game with 8+ prior games: the starters it would have named (last 10 games' starts, skipping anyone who did not play that night, the stand-in for an Out list known
beforehand) against the actual five: average starters right and how often it names the exact five or gets four or five.
"""
import os, json
import numpy as np
import pandas as pd

N_GAMES = 10
KEEP = 10                   # candidates kept per team (the site needs five plus replacements for anyone Out)


def load(raw="data/raw"):
    s = pd.read_csv(f"{raw}/stints.csv.gz", dtype={"pid": str, "event": str})
    s = s[s["pid"].notna() & (s["pid"] != "")]
    st = s.groupby(["event", "team", "pid"], as_index=False).agg(starter=("starter", "max"), date=("date", "first"), secs=("end", "sum"))
    st["starter"] = st["starter"].astype(int)
    return st


def build(raw="data/raw"):
    st = load(raw)
    g = pd.read_csv(f"{raw}/games.csv", dtype={"pid": str, "event": str})
    last = g.sort_values("date").drop_duplicates("pid", keep="last").set_index("pid")                # latest team, name and position per player
    mins = g.set_index(["event", "pid"])["min"]
    teams = {}
    for team, d in st.groupby("team"):
        evs = list(d.sort_values("date").event.unique())[-N_GAMES:]
        prev = d[d.event.isin(evs)]
        rows = []
        for pid, x in prev.groupby("pid"):
            if pid not in last.index or last.loc[pid, "team"] != team: continue                      # traded or waived: not on this roster now
            m = [float(mins.get((e, pid), np.nan)) for e in x.event]
            rows.append({"pid": pid, "name": last.loc[pid, "name"], "pos": last.loc[pid, "pos"], "s": int(x.starter.sum()), "gp": int(len(x)),
                         "mpg": round(float(np.nanmean(m)), 1) if len(m) and not np.all(np.isnan(m)) else 0.0})
        rows.sort(key=lambda r: (-r["s"], -r["mpg"]))
        teams[team] = {"games": len(evs), "players": rows[:KEEP]}
    return {"asof": str(st["date"].max()), "n_games": N_GAMES, "teams": teams, "acc": backtest(st)}


def backtest(st):
    """average starters right (of 5), exact-five rate and four-or-five rate, with and without knowing who sat out"""
    res_all, res_known = [], []
    for team, d in st.groupby("team"):
        evs = list(d.sort_values("date").event.unique())
        for i, e in enumerate(evs):
            if i < 8: continue
            prev = d[d.event.isin(evs[max(0, i - N_GAMES):i])]
            act = set(d[(d.event == e) & (d.starter == 1)].pid)
            if len(act) != 5: continue
            played = set(d[d.event == e].pid)
            rate = prev.groupby("pid").starter.sum().sort_values(ascending=False)
            res_all.append(len(set(rate.head(5).index) & act))
            res_known.append(len(set(rate[rate.index.isin(played)].head(5).index) & act))
    a, k = np.array(res_all), np.array(res_known)
    f = lambda r: {"avg_right": round(float(r.mean()), 2), "exact": round(float((r == 5).mean()), 3), "four_plus": round(float((r >= 4).mean()), 3)}
    return {"team_games": int(len(a)), "blind": f(a), "absences_known": f(k)}


def main(raw="data/raw", out="site/data"):
    res = build(raw)
    os.makedirs(out, exist_ok=True)
    with open(f"{out}/lineups.json", "w") as f: json.dump(res, f, separators=(",", ":"))
    print(f"lineups: {len(res['teams'])} teams through {res['asof']}; backtest {res['acc']}")


if __name__ == "__main__":
    main()

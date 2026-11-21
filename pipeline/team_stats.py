"""Team stats for and allowed (per game) -> site/data/team_stats.json  (display only: for the Matchups tab; nothing here feeds the projections)

Rolled up from the player box scores of the latest season: a team's stats are the sum of its players in each game, and what it ALLOWED is the other team's sum in the same game. Windows are the
whole season and the last 10 / 5 games. 3-point attempts are not in the box scores, so they come from the shot log (every shot has a three-point flag; made threes there match the box-score
fg3m to within 0.003 a team-game). Offensive / defensive rebounds and fouls are not in the feed. Possessions are estimated as FGA + 0.44*FTA + TOV (offensive rebounds are missing, so the level runs a few
percent high; rankings are unaffected), as on the Team Tiers tab. Ranks are within the window: 1 = best for that side (most for / fewest allowed; turnovers are the other way round).
"""
import os
import numpy as np
import pandas as pd

SUMS = ["pts", "fgm", "fga", "fg3m", "ftm", "fta", "reb", "ast", "stl", "blk", "tov"]
KEYS = SUMS[:3] + ["fg3a"] + SUMS[3:] + ["poss"]
WINDOWS = {"season": None, "l10": 10, "l5": 5}
LOWER_IS_BETTER_FOR = {"tov"}                     # for the team's own stats; for allowed stats the reverse (we want fewer allowed, except turnovers forced)


def team_games(g, shots=None):
    t = g.groupby(["event", "team", "opp", "date"], as_index=False)[SUMS].sum()
    if shots is not None and len(shots):
        s = shots[shots["event"].astype(str).isin(set(g["event"].astype(str)))].copy()
        a = s.groupby(["event", "team"]).agg(fg3a=("three", "sum")).reset_index()
        a["event"] = a["event"].astype(str); t["event"] = t["event"].astype(str)
        t = t.merge(a, on=["event", "team"], how="left")
    if "fg3a" not in t: t["fg3a"] = np.nan
    t["poss"] = t["fga"] + 0.44 * t["fta"] + t["tov"]
    o = t[["event", "team"] + KEYS].rename(columns={"team": "opp", **{k: k + "_o" for k in KEYS}})
    t = t.merge(o, on=["event", "opp"])
    t["win"] = (t["pts"] > t["pts_o"]).astype(int)
    n = t.groupby("team")["date"].transform("count")
    return t[n >= 0.5 * n.max()].sort_values(["date", "event"])               # drops exhibition clubs


def _side(d, sfx):
    m = {k: float(d[k + sfx].mean()) for k in KEYS}                          # per game
    pos = float(d["poss" + sfx].sum())
    out = {k: round(v, 1) for k, v in m.items()}
    out["fg_pct"] = round(100 * d["fgm" + sfx].sum() / max(d["fga" + sfx].sum(), 1), 1)
    out["ft_pct"] = round(100 * d["ftm" + sfx].sum() / max(d["fta" + sfx].sum(), 1), 1)
    a3 = d["fg3a" + sfx]
    out["fg3_pct"] = round(100 * d["fg3m" + sfx].sum() / a3.sum(), 1) if a3.notna().all() and a3.sum() > 0 else None
    if a3.isna().any(): out["fg3a"] = None
    out["ortg"] = round(100 * float(d["pts" + sfx].sum()) / pos, 1) if pos else None             # points per 100 possessions (for: offence; allowed: defence)
    return out


def build(g, shots=None):
    """g: box scores of ONE season. Returns {season, asof, windows, stats, teams: [{team, g, w, l, season|l10|l5: {for, allowed, rk_for, rk_al}}], league}."""
    if g is None or not len(g): return {"teams": []}
    t = team_games(g, shots)
    teams = []
    for team, d in t.groupby("team"):
        row = {"team": team, "g": int(len(d)), "w": int(d["win"].sum()), "l": int(len(d) - d["win"].sum())}
        for w, n in WINDOWS.items():
            x = d if n is None else d.tail(n)
            row[w] = {"g": int(len(x)), "for": _side(x, ""), "allowed": _side(x, "_o")}
        row["pace"] = round(float(((d["poss"] + d["poss_o"]) / 2).mean()), 1)
        teams.append(row)
    stats = KEYS + ["fg_pct", "fg3_pct", "ft_pct", "ortg"]
    for w in WINDOWS:
        for s in stats:
            for side, rk in (("for", "rk_for"), ("allowed", "rk_al")):
                v = pd.Series({r["team"]: r[w][side].get(s) for r in teams}, dtype=float)
                if v.isna().all(): continue
                better_high = (s not in LOWER_IS_BETTER_FOR) if side == "for" else (s in LOWER_IS_BETTER_FOR)
                if s == "ortg" and side == "allowed": better_high = False
                rank = v.rank(ascending=not better_high, method="min")
                for r in teams:
                    if pd.notna(rank.get(r["team"])): r[w].setdefault(rk, {})[s] = int(rank[r["team"]])
    lg = {w: {side: _side(t if WINDOWS[w] is None else t.groupby("team").tail(WINDOWS[w]), "" if side == "for" else "_o") for side in ("for", "allowed")} for w in WINDOWS}
    try: un = units(g)
    except Exception as e:
        print(f"team_stats units skipped: {e}"); un = {}
    for r in teams: r["units"] = un.get(r["team"], {})
    return {"season": int(g["season"].iloc[0]) if "season" in g else None, "asof": str(t["date"].max()), "windows": list(WINDOWS), "stats": stats,
            "teams": sorted(teams, key=lambda r: r["team"]), "league": lg}


def units(g, windows=("season", "l10")):
    """Unit strength: what each team's guards / forwards / centers produce per 48 minutes (PrizePicks fantasy points, plus points, rebounds, assists), ranked across the league in thirds.
    Production only: it says how good the unit's players are, not who is available tonight (the page lists the unit's rotation players who are out)."""
    from .model import norm_pos
    SCw = {"pts": 1.0, "reb": 1.2, "ast": 1.5, "stl": 3.0, "blk": 3.0, "tov": -1.0}
    x = g[g["min"] > 0].copy()
    x["pos"] = x["pos"].map(norm_pos)
    x["fp"] = sum(w * x[c] for c, w in SCw.items())
    ev = x.groupby(["team", "event"], as_index=False)["date"].first().sort_values("date")
    n = ev.groupby("team")["date"].transform("count")
    ok = set(ev[n >= 0.5 * n.max()]["team"])
    out = {t: {} for t in ok}
    for w in windows:
        last = None if w == "season" else int(w[1:])
        keep = ev if last is None else ev.groupby("team").tail(last)
        d = x.merge(keep[["team", "event"]], on=["team", "event"])
        d = d[d["team"].isin(ok)]
        agg = d.groupby(["team", "pos"])[["min", "fp", "pts", "reb", "ast"]].sum()
        games = keep.groupby("team").size()
        lgp = agg.groupby("pos")[["min", "fp"]].sum()
        K = 250.0                                                           # minutes of league-average production added before ranking, so a unit seen for few minutes is not ranked on noise
        for (team, pos), r in agg.iterrows():
            if r["min"] <= 0: continue
            out[team].setdefault(w, {})[pos] = {"mpg": round(float(r["min"] / games[team]), 1), "fp48": round(float(r["fp"] / r["min"] * 48), 1), "fp48_s": round(float((r["fp"] + K * lgp.loc[pos, "fp"] / lgp.loc[pos, "min"]) / (r["min"] + K) * 48), 2), "pts48": round(float(r["pts"] / r["min"] * 48), 1),
                                                  "reb48": round(float(r["reb"] / r["min"] * 48), 1), "ast48": round(float(r["ast"] / r["min"] * 48), 1)}
        for pos in ("G", "F", "C"):
            v = pd.Series({t: out[t][w][pos]["fp48_s"] for t in ok if w in out[t] and pos in out[t][w]})
            rk = v.rank(ascending=False, method="min")
            for t in v.index:
                out[t][w][pos]["rank"] = int(rk[t]); out[t][w][pos]["of"] = int(len(v))
                out[t][w][pos]["tier"] = "Top third" if rk[t] <= len(v) / 3 else "Bottom third" if rk[t] > 2 * len(v) / 3 else "Middle third"
    return out


def main(raw="data/raw", out="site/data"):
    import json
    g = pd.read_csv(f"{raw}/games.csv", dtype={"event": str})
    gl = g[g["season"] == g["season"].max()]
    sp = f"{raw}/shots.csv.gz"
    sh = pd.read_csv(sp, dtype={"event": str}, usecols=["event", "team", "three"]) if os.path.exists(sp) else None
    res = build(gl, sh)
    os.makedirs(out, exist_ok=True)
    with open(f"{out}/team_stats.json", "w") as f: json.dump(res, f, separators=(",", ":"))
    print(f"team_stats: {len(res['teams'])} teams, through {res.get('asof')}")


if __name__ == "__main__":
    main()

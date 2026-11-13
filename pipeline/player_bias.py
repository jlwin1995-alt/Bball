"""Players who consistently beat or miss the projection and the line  ->  data/log/player_bias.csv, data/log/player_bias_hist.csv  (research: nothing here feeds the model)

    python -m pipeline.player_bias            # rebuild the table and append today's flags to the history (run by the refresh workflow, soft-fail)
    python -m pipeline.player_bias --report   # forward test: did flagged players keep deviating AFTER the day they were flagged?

player_bias.csv: one row per (player, stat), rebuilt from scratch every run from data/log/accuracy_log.csv (the last pre-tip projection of each player-day), data/raw/games.csv (actuals)
and data/log/lines_log.csv (PrizePicks closing line, else the sportsbook consensus). Only games the player played (minutes > 0) with a projected 15+ minutes count.
  resid = actual - projection.  n, mean_resid (raw), vs_league = mean_resid minus the league-wide mean miss for that stat over the same games (the model over-projects everyone a little; a flag should
  mean he is off compared with OTHER players), se, z = vs_league/se, first / second half (his own games in date order, both vs_league), last5.  Same for the line: n_line, over_rate, mean_vs_line.
  flag_proj: 'over' / 'under' when n >= MIN_N, |z| >= Z_FLAG and both halves have the same sign.  flag_line: over_rate >= 0.70 or <= 0.30 on n_line >= MIN_N.
player_bias_hist.csv: the flags as they stood on each day (one block per day, appended once), which is what --report tests; the table itself only shows the present.
A flag is a description of the past. Whether it predicts the future is what the report measures (a first look on Nov 12: the half-vs-half correlation of a player's mean miss was 0.4 on points).
"""
import os, sys
import pandas as pd, numpy as np

LOG, RAW = "data/log", "data/raw"
OUT, HIST = f"{LOG}/player_bias.csv", f"{LOG}/player_bias_hist.csv"
MIN_PROJ_MIN, MIN_N, Z_FLAG = 15.0, 8, 2.0
STATS = ["min", "pts", "reb", "ast", "fg3m", "pra", "pr", "pa", "ra", "fp"]
SC = {"pts": 1.0, "reb": 1.2, "ast": 1.5, "stl": 3.0, "blk": 3.0, "tov": -1.0}      # PrizePicks fantasy scoring (config.DEFAULT_SCORING)
COLS = ["pid", "name", "team", "stat", "n", "mean_proj", "mean_actual", "mean_resid", "vs_league", "resid_pct", "se", "z", "first_half", "second_half", "last5", "flag_proj",
        "n_line", "over_rate", "mean_vs_line", "flag_line", "last_date"]
HCOLS = ["asof", "pid", "name", "stat", "flag", "n", "vs_league", "z"]


def combo(df, p):
    """the stat (or its projection when p is the '_p' suffix) for a combo name, from the pts/reb/ast/... columns"""
    g = lambda c: df[c + p]
    return {"pra": g("pts") + g("reb") + g("ast"), "pr": g("pts") + g("reb"), "pa": g("pts") + g("ast"), "ra": g("reb") + g("ast"),
            "fp": sum(w * g(c) for c, w in SC.items())}


def load():
    a = pd.read_csv(f"{LOG}/accuracy_log.csv", dtype={"pid": str}).sort_values("logged_at").drop_duplicates(["date", "pid"], keep="last")
    g = pd.read_csv(f"{RAW}/games.csv", dtype={"pid": str})
    m = a.merge(g[["pid", "date", "min", "pts", "reb", "ast", "fg3m", "stl", "blk", "tov"]], on=["pid", "date"], suffixes=("_p", ""))
    m = m[(m["min"] > 0) & (m["min_p"] >= MIN_PROJ_MIN)].copy()
    for k, v in combo(m, "_p").items(): m[k + "_p"] = v
    for k, v in combo(m, "").items(): m[k] = v
    return m


def lines():
    p = f"{LOG}/lines_log.csv"
    if not os.path.exists(p): return pd.DataFrame(columns=["date", "pid", "stat", "line"])
    l = pd.read_csv(p, dtype={"pid": str}).sort_values("ts").drop_duplicates(["date", "pid", "stat"], keep="last")
    l["line"] = l.pp_line.fillna(l.cons_line)
    return l.dropna(subset=["line"])[["date", "pid", "stat", "line"]]


def build(m=None, L=None, upto=None):
    """the table as it stood using only games dated before `upto` (default: everything)."""
    m = load() if m is None else m
    L = lines() if L is None else L
    if upto is not None: m = m[m.date < upto]
    rows = []
    for s in STATS:
        d = m.assign(act=m[s], proj=m[s + "_p"]).dropna(subset=["act", "proj"]).sort_values("date")
        d["resid"] = d.act - d.proj
        lg = d.resid.mean(); d["resid"] = d.resid - lg                    # centred on the league: a player's own bias, not the model's
        d = d.merge(L[L.stat == s][["date", "pid", "line"]], on=["date", "pid"], how="left")
        for pid, x in d.groupby("pid"):
            n = len(x)
            if n < 3: continue
            r = x.resid.values; h = n // 2
            se = r.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
            mr = r.mean(); z = mr / se if se and se > 0 else np.nan
            a1, a2 = r[:h].mean(), r[h:].mean()
            fl = ""
            if n >= MIN_N and abs(z) >= Z_FLAG and a1 * a2 > 0: fl = "over" if mr > 0 else "under"
            y = x.dropna(subset=["line"]); y = y[y.act != y.line]
            nl = len(y); orr = float((y.act > y.line).mean()) if nl else np.nan
            fll = "" if nl < MIN_N else ("over" if orr >= 0.70 else "under" if orr <= 0.30 else "")
            rows.append(dict(pid=pid, name=x.name.iloc[-1], team=x.team.iloc[-1], stat=s, n=n, mean_proj=x.proj.mean(), mean_actual=x.act.mean(), mean_resid=mr + lg, vs_league=mr,
                             resid_pct=(mr + lg) / x.proj.mean() if x.proj.mean() else np.nan, se=se, z=z, first_half=a1, second_half=a2, last5=r[-5:].mean(), flag_proj=fl,
                             n_line=nl, over_rate=orr, mean_vs_line=float((y.act - y.line).mean()) if nl else np.nan, flag_line=fll, last_date=x.date.iloc[-1]))
    return pd.DataFrame(rows, columns=COLS).round(3)


def snapshot(t, asof):
    f = t[t.flag_proj != ""]
    return pd.DataFrame({"asof": asof, "pid": f.pid, "name": f.name, "stat": f.stat, "flag": f.flag_proj, "n": f.n, "vs_league": f.vs_league, "z": f.z}, columns=HCOLS)


def main():
    m = load(); t = build(m, lines())
    os.makedirs(LOG, exist_ok=True)
    t.to_csv(OUT, index=False)
    asof = str(pd.Timestamp.now("UTC").date())
    h = pd.read_csv(HIST, dtype={"pid": str}) if os.path.exists(HIST) else pd.DataFrame(columns=HCOLS)
    if asof not in set(h["asof"].astype(str)):
        s = snapshot(t, asof)
        if len(s): h = pd.concat([h, s], ignore_index=True); h.to_csv(HIST, index=False)
    f = t[t.flag_proj != ""]
    print(f"player_bias: {len(t)} player-stat rows, {t.pid.nunique()} players; flagged vs projection {len(f)} ({(f.flag_proj == 'over').sum()} over, {(f.flag_proj == 'under').sum()} under); "
          f"flagged vs line {(t.flag_line != '').sum()}")


def report():
    """forward test: for every flag in the history, the miss in the games played AFTER the flag date (the history holds what was known then)."""
    if not os.path.exists(HIST): print("no history yet"); return
    h = pd.read_csv(HIST, dtype={"pid": str}); m = load()
    out = []
    for r in h.itertuples():
        x = m[(m.pid == r.pid) & (m.date >= r.asof)]
        if not len(x): continue
        fw = m[(m.date >= r.asof)]; res = x[r.stat] - x[r.stat + "_p"] - (fw[r.stat] - fw[r.stat + "_p"]).mean()     # minus the league's miss over the same dates
        out.append((r.stat, r.flag, len(x), res.mean() * (1 if r.flag == "over" else -1)))   # positive = kept deviating in the flagged direction
    if not out: print("no flagged player has played since his flag date yet"); return
    d = pd.DataFrame(out, columns=["stat", "flag", "n", "fwd"])
    print(f"{len(d)} flags with games since; mean forward miss in the flagged direction {d.fwd.mean():+.2f} (0 = no persistence), kept direction in {(d.fwd > 0).mean():.0%}")
    print(d.groupby("stat").agg(flags=("fwd", "size"), mean_fwd=("fwd", "mean"), kept=("fwd", lambda s: (s > 0).mean())).round(2).to_string())


if __name__ == "__main__":
    report() if "--report" in sys.argv else main()

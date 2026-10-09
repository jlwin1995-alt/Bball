"""games.csv + schedule.csv + injuries.csv  ->  site/data/*.json

Run:  python -m pipeline.build [--raw data/raw] [--out site/data]
"""
import argparse, json, os
import numpy as np
import pandas as pd
from . import config as C
from .model import project, fantasy, _prep, all_players
from . import scorecard, lines as lines_mod, results as results_mod
from .preseason_test import resolve_mult


def r(x, n=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def dump(obj, out, name):
    with open(os.path.join(out, name), "w") as f:
        json.dump(obj, f, separators=(",", ":"), default=str)


def season_view(g):
    """Current season if it has a meaningful sample, else everything (early-season fallback)."""
    cur = g[g["season"] == C.SEASON]
    return cur if len(cur) >= 200 else g


def main(raw="data/raw", out="site/data"):
    os.makedirs(out, exist_ok=True)
    games = pd.read_csv(f"{raw}/games.csv", dtype={"pid": str})
    sched = pd.read_csv(f"{raw}/schedule.csv")
    inj = pd.read_csv(f"{raw}/injuries.csv", dtype={"pid": str}) if os.path.exists(f"{raw}/injuries.csv") else None
    meta_in = pd.read_csv(f"{raw}/meta.csv").iloc[0].to_dict() if os.path.exists(f"{raw}/meta.csv") else {}
    sample = str(meta_in.get("sample", "False")) == "True"

    if sched.empty:
        raise SystemExit("schedule.csv has no upcoming regular-season games; leaving site/data as it was. "
                         "Re-run the fetch closer to the season.")
    # Preseason slate (before the regular season starts): stars play far fewer minutes, so apply the learned tier multipliers.
    first = sched[sched["date"] == sched["date"].min()]
    # Preseason = every game on the slate day is tagged preseason by ESPN (no hard-coded season-start date to get wrong).
    # Older schedule files without the tag fall back to the CUR_START date.
    pre = bool((first["stype"] == 1).all()) if "stype" in first.columns and first["stype"].notna().all() else pd.Timestamp(sched["date"].min()) < pd.Timestamp(C.CUR_START)
    mult, mult_how = (resolve_mult(None, None, raw) if pre else (None, None))
    if pre and not mult:
        mult, mult_how = C.PRESEASON_MULT_FALLBACK, "fallback"
    ros = pd.read_csv(f"{raw}/rosters.csv", dtype={"pid": str}) if os.path.exists(f"{raw}/rosters.csv") else None
    P, D = project(games, sched, inj, rosters=ros, minute_mult=mult)
    g = _prep(games)

    # --- Projections / Game Board ------------------------------------------------
    cols = ["pid", "name", "pos", "team", "opp", "home", "rest", "status", "g", "min", "min_s", "min_r"]
    proj = []
    for _, p in P.iterrows():
        row = {c: (r(p[c]) if isinstance(p[c], (float, np.floating)) else p[c]) for c in cols}
        row["home"] = int(p["home"])
        row["out"] = bool(p["out"])
        row["fp"] = r(fantasy(p))
        row["exp_margin"] = r(p["exp_margin"], 1)
        row["pace_f"] = r(p["pace_f"], 3)
        for s in C.STATS:
            row["rate_" + s] = r(p["rate_" + s], 5)
            row["adj_" + s] = r(p["adj_" + s], 4)
            row["pm_" + s] = r(p["pm_" + s], 5)
        proj.append(row)
    dump(proj, out, "projections.json")
    AP = all_players(games, ros, mult)                              # for the Live tab: anyone in any game, not just today's slate
    dump({q.pid: {"m": round(float(q.min_exp), 1), "r": [round(float(getattr(q, "pm_" + st)), 5) for st in C.STATS]} for q in AP.itertuples()},
         out, "players.json")

    # --- Matchups ------------------------------------------------------------------
    play = {(t) for t in P["team"]}
    dump([{"team": t, "playing": t in {*P["opp"]}, **{k: r(v, 4) for k, v in d.items()}} for t, d in D.items()], out, "matchups.json")

    # --- Efficiency + Usage (season view) ----------------------------------------
    sv = season_view(g)
    agg = sv.groupby("pid").agg(name=("name", "last"), team=("team", "last"), pos=("pos", "last"), g=("min", "size"),
                                 **{s: (s, "sum") for s in ["min", "pts", "reb", "ast", "fg3m", "stl", "blk", "tov", "fgm", "fga", "ftm", "fta"]})
    # Team totals only over games the player appeared in, so missed games are not held against his share.
    tcols = ["min", "fga", "fta", "tov", "ast", "reb"]
    tg = sv.groupby(["team", "date"])[tcols].sum().add_prefix("t_").reset_index()
    tt = sv.merge(tg, on=["team", "date"]).groupby("pid")[["t_" + c for c in tcols]].sum()
    eff, use = [], []
    for pid, a in agg.iterrows():
        if a["min"] < 100:
            continue
        per36 = lambda s: a[s] / a["min"] * 36
        ts = a["pts"] / (2 * (a["fga"] + 0.44 * a["fta"])) if a["fga"] + a["fta"] else None
        eff.append({"pid": pid, "name": a["name"], "team": a["team"], "pos": a["pos"], "g": int(a["g"]), "mpg": r(a["min"] / a["g"], 1),
                    "pts36": r(per36("pts"), 1), "reb36": r(per36("reb"), 1), "ast36": r(per36("ast"), 1),
                    "stl36": r(per36("stl"), 2), "blk36": r(per36("blk"), 2), "tov36": r(per36("tov"), 2),
                    "fg": r(a["fgm"] / a["fga"], 3) if a["fga"] else None, "fg3": None,
                    "ft": r(a["ftm"] / a["fta"], 3) if a["fta"] else None, "ts": r(ts, 3),
                    "ast_tov": r(a["ast"] / a["tov"], 2) if a["tov"] else None})
        t = tt.loc[pid]
        mins_t = t["t_min"] / 5
        uses = a["fga"] + 0.44 * a["fta"] + a["tov"]
        tuses = t["t_fga"] + 0.44 * t["t_fta"] + t["t_tov"]
        use.append({"pid": pid, "name": a["name"], "team": a["team"], "pos": a["pos"], "g": int(a["g"]),
                    "min_sh": r(a["min"] / mins_t * 100, 1), "mpg": r(a["min"] / a["g"], 1), "fga_sh": r(a["fga"] / t["t_fga"] * 100, 1),
                    "fta_sh": r(a["fta"] / t["t_fta"] * 100, 1), "ast_sh": r(a["ast"] / t["t_ast"] * 100, 1),
                    "reb_sh": r(a["reb"] / t["t_reb"] * 100, 1), "tov_sh": r(a["tov"] / t["t_tov"] * 100, 1),
                    "usg": r(uses / tuses * 100, 1)})
    dump(eff, out, "efficiency.json")
    dump(use, out, "usage.json")

    # --- Trends --------------------------------------------------------------------
    sv = sv.copy()
    sv["fp"] = fantasy(sv)
    trends = []
    for pid, d in sv.groupby("pid"):
        if len(d) < max(C.ROLLING_WINDOW + 1, 6):
            continue
        d = d.sort_values("date")
        rec = d.tail(C.ROLLING_WINDOW)
        base = d.iloc[:-C.ROLLING_WINDOW]
        fp_s, fp_r = d["fp"].mean(), rec["fp"].mean()
        m_s, m_r = d["min"].mean(), rec["min"].mean()
        dfp, dmin = fp_r / fp_s - 1 if fp_s else 0, m_r / m_s - 1 if m_s else 0
        form = "HOT" if dfp > .10 and dmin > .05 else "COLD" if dfp < -.10 and dmin < -.05 else "-"
        trends.append({"pid": pid, "name": d["name"].iloc[-1], "team": d["team"].iloc[-1], "pos": d["pos"].iloc[-1], "g": len(d),
                       "fp_s": r(fp_s, 1), "fp_r": r(fp_r, 1), "d_fp": r(dfp * 100, 1), "min_s": r(m_s, 1), "min_r": r(m_r, 1),
                       "d_min": r(dmin * 100, 1), "sd": r(d["fp"].std(), 1), "cv": r(d["fp"].std() / fp_s, 2) if fp_s else None,
                       "floor": r(d["fp"].quantile(.10), 1), "ceil": r(d["fp"].quantile(.90), 1), "form": form,
                       "last": [r(x, 1) for x in d["fp"].tail(10)]})
    dump(trends, out, "trends.json")

    # --- Coverage / meta -----------------------------------------------------------
    cov = {"asof": str(g["date"].max().date()), "slate_date": str(P["date"].iloc[0].date()) if len(P) else None,
           "player_games": int(len(g)), "players": int(g["pid"].nunique()), "projected": int(len(P)),
           "out": int(P["out"].sum()), "teams_playing": int(P["team"].nunique()),
           "cur_season_games": int((g["season"] == C.SEASON).sum()), "game_days": int(g["date"].nunique())}
    dump(cov, out, "coverage.json")
    dump({"sample": sample, "season": C.SEASON, "rolling_window": C.ROLLING_WINDOW, "mean_factor": C.MEAN_FACTOR,
          "preseason": bool(pre), "minute_mult": mult, "mult_source": mult_how, "stats": C.STATS, "default_scoring": C.DEFAULT_SCORING, "spread": C.SPREAD_DEFAULT,
          "generated": pd.Timestamp.now("UTC").isoformat(timespec="seconds")}, out, "meta.json")
    if os.path.exists(f"{raw}/spread.json"):
        dump(json.load(open(f"{raw}/spread.json")), out, "spread.json")
    if not sample:
        lines_mod.main(raw, out)                                    # live lines + consensus, if odds.csv exists
    logged = 0 if sample else scorecard.log_slate(P, games, preseason=pre)   # sample data never touches the real log; preseason -> rehearsal log
    dump(scorecard.score(games), out, "scorecard.json")
    if not sample:
        results_mod.main(raw, out, games)                           # projected vs actual per player, per game day
        rg = f"{raw}/rehearsal_games.csv"                           # preseason dress rehearsal of the same pipeline
        results_mod.main(raw, out, pd.read_csv(rg, dtype={"pid": str}) if os.path.exists(rg) else pd.DataFrame(columns=["date", "pid"]),
                         log=scorecard.REHEARSAL_LOG, subdir="results_rehearsal", rehearsal=True)
    print(f"logged {logged} rows; projected {len(P)} players for {cov['slate_date']}  (out: {cov['out']})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="site/data")
    a = ap.parse_args()
    main(a.raw, a.out)

"""Projected vs actual, per player and per game day  ->  site/data/results/index.json + results/<date>.json

    python -m pipeline.results [--raw data/raw] [--out site/data]

Inputs
  data/log/accuracy_log.csv   pregame projections, frozen before tip-off (scorecard.py)
  data/log/lines_log.csv      the last PRE-game consensus / PrizePicks line per game day, player and stat (lines.py)
  data/raw/games.csv          final box scores

A day appears once its games are in games.csv. Line grading: the model "takes" OVER if its projection is above the line, UNDER if
below; a result equal to the line is a push and is excluded. A *pick* is a line where the model's probability differs from the book's by
at least RESULTS_EDGE_PP points (consensus) / from the PrizePicks break-even (PrizePicks), using the same spread model as the Lines tab.
"""
import argparse, json, math, os
import numpy as np
import pandas as pd
from . import config as C
from . import scorecard, lines as lines_mod

LINE_STATS = ["pts", "reb", "ast", "fg3m", "pra", "pr", "pa", "ra"]
SHOWN = C.STATS + list(C.COMBOS)


def cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def sides(line, m, sd):
    """P(over), P(under); a whole-number line treats a push as neither side (same as the site)."""
    if float(line).is_integer():
        return 1 - cdf((line + 0.5 - m) / sd), cdf((line - 0.5 - m) / sd)
    o = 1 - cdf((line - m) / sd)
    return o, 1 - o


def grade(actual, line, side):
    """True/False for a won/lost call, None for a push."""
    if actual == line:
        return None
    return (actual > line) if side == "O" else (actual < line)


def add_combos(df, cols):
    for c, parts in C.COMBOS.items():
        for suf in cols:
            df[f"{c}_{suf}"] = sum(df[f"{s}_{suf}"] for s in parts)
    return df


def build(L, G, LG, spread):
    """L: accuracy log, G: box scores, LG: lines log (may be empty), spread: {stat: [a, b]}. Returns (index_rows, {date: [rows]})."""
    A = G.groupby(["date", "pid"], as_index=False).agg(**{"min": ("min", "sum"), **{s: (s, "sum") for s in C.STATS}}).rename(columns={"min": "min_a"})
    M = L.merge(A, on=["date", "pid"], how="inner", suffixes=("_p", "_a"))
    M = add_combos(M, ["p", "a"])
    M["fp_a"] = sum(M[f"{s}_a"] * w for s, w in C.DEFAULT_SCORING.items())
    M = M.rename(columns={"fp": "fp_p"})
    lk = {}
    if len(LG):
        for r in LG.sort_values("ts").itertuples():
            lk[(str(r.date), str(r.pid), r.stat)] = r
    days, detail = [], {}
    for date, d in M.groupby("date"):
        rows, tally = [], {k: [0, 0] for k in ("cons", "picks", "pp", "pp_picks")}
        for r in d.itertuples():
            s_out = {}
            for st in SHOWN:
                p, a = float(getattr(r, st + "_p")), float(getattr(r, st + "_a"))
                cl = pl = None
                pc = pk = ""
                if st in LINE_STATS:
                    ln = lk.get((str(date), str(r.pid), st))
                    if ln is not None:
                        a_, b_ = spread.get(st, [1.0, 0.3])
                        sd = max(a_ + b_ * p, 0.1)
                        if pd.notna(ln.cons_line):
                            cl = float(ln.cons_line)
                            po, pu = sides(cl, p, sd)
                            side = "O" if p > cl else "U"
                            g = grade(a, cl, side)
                            if g is not None:
                                tally["cons"][0] += 1; tally["cons"][1] += int(g)
                            if pd.notna(ln.cons_p_over) and abs(po - float(ln.cons_p_over)) * 100 >= C.RESULTS_EDGE_PP:
                                pc = "O" if po > float(ln.cons_p_over) else "U"
                                gg = grade(a, cl, pc)
                                if gg is not None:
                                    tally["picks"][0] += 1; tally["picks"][1] += int(gg)
                        if pd.notna(ln.pp_line):
                            pl = float(ln.pp_line)
                            po, pu = sides(pl, p, sd)
                            side = "O" if po >= pu else "U"
                            g = grade(a, pl, side)
                            if g is not None:
                                tally["pp"][0] += 1; tally["pp"][1] += int(g)
                            if max(po, pu) - C.PP_BREAKEVEN >= C.RESULTS_EDGE_PP / 100:
                                gg = grade(a, pl, side)
                                pk = side
                                if gg is not None:
                                    tally["pp_picks"][0] += 1; tally["pp_picks"][1] += int(gg)
                s_out[st] = [round(p, 1), round(a, 1), cl, pl, pc, pk]
            rows.append({"pid": r.pid, "n": r.name, "t": r.team, "mp": round(float(r.min_p), 1), "ma": round(float(r.min_a), 1),
                         "fp": [round(float(r.fp_p), 1), round(float(r.fp_a), 1)], "s": s_out})
        big = d[d["min_p"] >= C.RESULTS_MIN_PROJ_MIN]
        days.append({"date": str(date), "rows": len(d), "n": int(len(big)),
                     "min_mae": round(float((big["min_p"] - big["min_a"]).abs().mean()), 2) if len(big) else None,
                     "fp_mae": round(float((big["fp_p"] - big["fp_a"]).abs().mean()), 2) if len(big) else None,
                     "fp_bias": round(float((big["fp_p"].sum() - big["fp_a"].sum()) / big["fp_a"].sum() * 100), 1) if len(big) and big["fp_a"].sum() else None,
                     **tally})
        detail[str(date)] = rows
    return sorted(days, key=lambda x: x["date"], reverse=True), detail


def main(raw="data/raw", out="site/data", games=None, log=None, subdir="results", rehearsal=False):
    log = log or scorecard.LOG
    os.makedirs(f"{out}/{subdir}", exist_ok=True)
    meta = {"edge_pp": C.RESULTS_EDGE_PP, "pp_breakeven": C.PP_BREAKEVEN, "min_proj": C.RESULTS_MIN_PROJ_MIN, "stamp": scorecard.stamp(), "rehearsal": rehearsal}
    if not os.path.exists(log):
        json.dump({"days": [], **meta}, open(f"{out}/{subdir}/index.json", "w"))
        print(f"{subdir}: no {os.path.basename(log)} yet")
        return
    L = pd.read_csv(log, dtype={"pid": str}).rename(columns={"min": "min_p"})
    G = (games if games is not None else pd.read_csv(f"{raw}/games.csv", dtype={"pid": str}))
    G = G.astype({"pid": str}); G["date"] = G["date"].astype(str)
    L["date"] = L["date"].astype(str)
    if not len(G):
        json.dump({"days": [], **meta}, open(f"{out}/{subdir}/index.json", "w"))
        print(f"{subdir}: no finished games to score yet")
        return
    LG = pd.read_csv(lines_mod.LOG, dtype={"pid": str}) if (not rehearsal and os.path.exists(lines_mod.LOG)) else pd.DataFrame()
    sp = json.load(open(f"{raw}/spread.json")) if os.path.exists(f"{raw}/spread.json") else {}
    spread = {**C.SPREAD_DEFAULT, **sp}
    days, detail = build(L, G, LG, spread)
    for date, rows in detail.items():
        json.dump(rows, open(f"{out}/{subdir}/{date}.json", "w"), separators=(",", ":"))
    json.dump({"days": days, **meta}, open(f"{out}/{subdir}/index.json", "w"), separators=(",", ":"))
    print(f"{subdir}: {len(days)} scored game days, {sum(d['rows'] for d in days)} player rows")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="site/data")
    a = ap.parse_args()
    main(a.raw, a.out)

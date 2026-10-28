"""Graded consensus lines against the toughest and softest defences (this season's logged lines).

    python -m pipeline.def_lines         # needs data/log/lines_log.csv, data/log/accuracy_log.csv, data/raw/weekly.csv

For every logged consensus line with a result: whether the OVER hit (actual > line, pushes dropped), by the opposing defence's tier on that stat going into the week (toughest 8 / middle / softest 8
by allowed per game to the position group), and the model's side (its frozen projection against the line) hit rate within each tier. These are the actual hit rates at the posted price.
"""
import csv
from collections import defaultdict
from .def_hitrates import MARKETS, allowed_rank
from .model import load_weekly

COL = {m: v[2] for m, v in MARKETS.items()}


def run(raw="data/raw", season="2026"):
    rows = load_weekly(f"{raw}/weekly.csv")
    by_week = defaultdict(list)
    for r in rows:
        by_week[int(r["week"])].append(r)
    acc = {}
    for x in csv.DictReader(open("data/log/accuracy_log.csv")):
        if x["season"] == season:
            acc[(x["player_id"], x["kickoff"][:10])] = x
    out = []
    for x in csv.DictReader(open("data/log/lines_log.csv")):
        if not x["cons_line"] or x["stat"] not in MARKETS:
            continue
        a = acc.get((x["player_id"], x["commence"][:10]))
        if not a:
            continue
        wk = int(a["week"])
        res = next((r for r in by_week.get(wk, []) if r["player_id"] == x["player_id"]), None)
        if res is None or not by_week.get(wk):
            continue
        hist = [r for w, rs in by_week.items() if w < wk for r in rs]
        pos, _, col, _ = MARKETS[x["stat"]]
        if a["pos"] not in pos:
            continue
        rk, n = allowed_rank(hist, wk, pos, col)
        r_ = rk.get(a["opp"])
        if r_ is None:
            continue
        tier = "tough" if r_ <= 8 else "soft" if r_ > n - 8 else "mid"
        line, actual, proj = float(x["cons_line"]), res[col], float(a["p_" + x["stat"]] or 0)
        if actual == line:
            continue
        out.append(dict(stat=x["stat"], tier=tier, over=actual > line, model_over=proj > line, week=wk, name=x["name"]))
    return out


if __name__ == "__main__":
    r = run()
    print(f"{len(r)} graded consensus lines (pushes dropped)")
    print(f"{'':16}{'n':>5}{'over hit':>10}{'model side hit':>16}")
    for lab, f in (("all", lambda x: True), ("tough D (top 8)", lambda x: x["tier"] == "tough"), ("middle", lambda x: x["tier"] == "mid"), ("soft D (bottom 8)", lambda x: x["tier"] == "soft")):
        s = [x for x in r if f(x)]
        print(f"{lab:16}{len(s):5}{sum(x['over'] for x in s) / len(s) * 100:9.1f}%{sum(x['over'] == x['model_over'] for x in s) / len(s) * 100:15.1f}%")
    for m in MARKETS:
        for tier in ("tough", "mid", "soft"):
            s = [x for x in r if x["stat"] == m and x["tier"] == tier]
            if s:
                print(f"{m:7} {tier:6} n={len(s):4} over {sum(x['over'] for x in s) / len(s) * 100:5.1f}%  model side {sum(x['over'] == x['model_over'] for x in s) / len(s) * 100:5.1f}%")

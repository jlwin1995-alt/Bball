"""Backtest: is RB receiving (receptions, receiving yards) over-projected, and does a correction help?

Walk-forward projections (pipeline.ranges.walk_*) for backs only, NFL 2023-26 and college 2025-26. Candidate corrections, each fitted on the other seasons and scored on the held-out one (leave-one-season-out):
  k      one multiplier on the projection (the median of actual/projection, found by minimising absolute error)
  k(p)   a multiplier that depends on projection size (3 bins)
Scored on MAE and median error. Then a check on this season's graded posted lines: does shading the projection pick the right side more often?
"""
import csv, json, statistics as S, sys
from collections import defaultdict
from . import config as C, ranges

STATS = ("rec", "recY")


def load(cache="/tmp/rb_pairs.json"):
    try:
        return json.load(open(cache))
    except OSError:
        W = dict(C.DEFAULT_SCORING)
        d = {"nfl": [t for t in ranges.walk_nfl(W) if t[0] in STATS and t[1] == "RB"], "cfb": [t for t in ranges.walk_cfb(W) if t[0] in STATS and t[1] == "RB"]}
        json.dump(d, open(cache, "w"))
        return d


def best_k(v):
    """multiplier minimising sum |a - k p|: the weighted median of a/p with weights p"""
    r = sorted((a / p, p) for p, a in v if p > 0)
    half, c = sum(p for _, p in r) / 2, 0.0
    for q, p in r:
        c += p
        if c >= half:
            return q


def edges(v, n=3):
    ps = sorted(p for p, _ in v)
    return [ps[i * len(ps) // n] for i in range(1, n)]


def fit(v):
    e = edges(v)
    bins = [[x for x in v if (x[0] < e[0])], [x for x in v if e[0] <= x[0] < e[1]], [x for x in v if x[0] >= e[1]]]
    return dict(k=best_k(v), e=e, kb=[best_k(b) for b in bins])


def apply(m, p, how):
    if how == "k":
        return p * m["k"]
    return p * m["kb"][0 if p < m["e"][0] else 1 if p < m["e"][1] else 2]


def main():
    d = load()
    for lg in ("nfl", "cfb"):
        for st in STATS:
            rows = [(p, a, s) for (t, pos, p, a, s) in d[lg] if t == st and p >= (1 if st == "rec" else 10)]
            seasons = sorted({s for _, _, s in rows})
            res = {h: [] for h in ("raw", "k", "k(p)")}
            for s in seasons:
                tr, te = [(p, a) for p, a, x in rows if x != s], [(p, a) for p, a, x in rows if x == s]
                m = fit(tr)
                for p, a in te:
                    res["raw"].append(a - p); res["k"].append(a - apply(m, p, "k")); res["k(p)"].append(a - apply(m, p, "kb"))
            m = fit([(p, a) for p, a, _ in rows])
            print(f"\n{lg.upper()} RB {st}: n={len(rows)} seasons {seasons}  fitted k={m['k']:.3f}  by size {[round(x, 3) for x in m['kb']]} (edges {[round(x, 1) for x in m['e']]})")
            for h, e in res.items():
                print(f"  {h:5} leave-one-season-out MAE {S.mean(abs(x) for x in e):6.2f}  median err {S.median(e):6.2f}  over-rate {100 * sum(x > 0 for x in e) / len(e):4.1f}%")
            for s in seasons:
                v = [(p, a) for p, a, x in rows if x == s]
                print(f"  season {s}: n={len(v)} actual/proj (median) {S.median(a / p for p, a in v):.3f}  mean act {S.mean(a for p, a in v):.2f} vs proj {S.mean(p for p, a in v):.2f}")
    # graded 2026 posted lines (RB, last consensus line): which side does the projection pick, and does the shaded one pick better?
    k = {lg: {st: best_k([(p, a) for (t, pos, p, a, s) in d[lg] if t == st and p >= (1 if st == "rec" else 10)]) for st in STATS} for lg in ("nfl", "cfb")}
    from .model import load_weekly
    from .cfb_model import load_rows
    nfl = {(int(r["week"]), r["player_id"]): r for r in load_weekly("data/raw/weekly.csv")}
    cfb = {(int(r["week"]), r["playerId"]): r for r in load_rows("data/raw/cfb_weekly.csv")}
    for lg, log, lines, wk, col in (("nfl", "data/log/accuracy_log.csv", "data/log/lines_log.csv", nfl, {"rec": "receptions", "recY": "receiving_yards"}),
                                    ("cfb", "data/log/cfb_log.csv", "data/log/cfb_lines_log.csv", cfb, {"rec": "receptions", "recY": "receiving_yards"})):
        proj = {(x["player_id"], int(x["week"])): x for x in csv.DictReader(open(log)) if x["season"] == "2026" and x["pos"] == "RB"}
        last = {}
        for x in csv.DictReader(open(lines)):
            if x["cons_line"] and x["stat"] in STATS:
                for (pid, w), lg_ in proj.items():
                    if pid == x["player_id"] and lg_["kickoff"][:10] == x["commence"][:10]:
                        last[(pid, x["stat"], w)] = (float(x["cons_line"]), lg_)
        for st in STATS:
            n = raw = sh = 0
            diff = rawU = 0
            for (pid, s2, w), (line, lg_) in last.items():
                if s2 != st:
                    continue
                a = wk.get((w, pid))
                if not a:
                    continue
                v = float(a[col[st]])
                p = float(lg_["p_" + st] or 0)
                if not p or v == line:
                    continue
                n += 1
                went_over = v > line
                raw += (p > line) == went_over
                sh += (p * k[lg][st] > line) == went_over
                diff += (p > line) != (p * k[lg][st] > line)
                rawU += p < line
            if n:
                print(f"\n{lg.upper()} 2026 RB {st} lines: n={n}  side hit raw {100 * raw / n:.1f}%  shaded x{k[lg][st]:.2f} {100 * sh / n:.1f}%  (side flips {diff}; raw picks Under on {rawU})")


if __name__ == "__main__":
    main()

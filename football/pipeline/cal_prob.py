"""Calibrated P(over) for posted lines (the football version of the NBA project's "Cal P(win)").

The model's P(over) / P(under) at a posted line has been overconfident: across this season's graded consensus lines the model's side was given ~60% on average and hit ~52%. Fit, separately for the
side the model leans to (a projection above the line = an Over pick, below = an Under pick) and per league:  Cal P = 0.5 + beta x (P - 0.5), beta by least squares through (0.5, 0.5) on every graded line.
beta is clipped to [0, 1]; its standard error and n are published so the page can show how settled it is. Written to site/data/calprob.json (NFL) and site/data/cfb/calprob.json (college) by the builds,
so it refits on every refresh. Display only: the projections, the lean sigma tiers and the Pick thresholds are unchanged.
"""
import csv, json, math
from collections import defaultdict
from . import prob

COL = {"rushY": "rushing_yards", "recY": "receiving_yards", "rec": "receptions", "passY": "passing_yards", "comp": "completions"}
MIN_N = 40


def f(v):
    return float(v or 0)


def graded_nfl(markets, season="2026", raw="data/raw", log="data/log", exclude=(("ATL", 8), ("TB", 8))):
    """-> [(model P(over), 1 if the line went over else 0, week)] for every last pre-game consensus line with a result."""
    from .model import load_weekly
    wk = defaultdict(dict)
    for r in load_weekly(f"{raw}/weekly.csv"):
        wk[int(r["week"])][r["player_id"]] = r
    bypl = defaultdict(list)
    for x in csv.DictReader(open(f"{log}/accuracy_log.csv")):
        if x["season"] == season:
            bypl[x["player_id"]].append((int(x["week"]), x))
    last = {}
    for x in csv.DictReader(open(f"{log}/lines_log.csv")):
        if not x["cons_line"] or x["stat"] not in COL:
            continue
        for w, lg in bypl.get(x["player_id"], []):
            if lg["kickoff"][:10] == x["commence"][:10]:
                last[(x["player_id"], x["stat"], w)] = (x, lg)
    out = []
    for (pid, st, w), (x, lg) in last.items():
        a = wk[w].get(pid)
        if not a or (x["team"], w) in exclude:           # the rain game (ATL @ TB, week 8) is a weather outlier
            continue
        pr, line, v = f(lg["p_" + st]), float(x["cons_line"]), a[COL[st]]
        if not pr or v == line or st not in markets:
            continue
        out.append((prob.sides(line, pr, markets[st])[0], 1 if v > line else 0, w))
    return out


def graded_cfb(specs, season="2026", raw="data/raw", log="data/log"):
    from .cfb_model import load_rows
    wk = defaultdict(dict)
    for r in load_rows(f"{raw}/cfb_weekly.csv"):
        wk[int(r["week"])][r["playerId"]] = r
    frozen = {(x["player_id"], int(x["week"])): x for x in csv.DictReader(open(f"{log}/cfb_log.csv")) if x["season"] == season}
    last = {}
    for x in csv.DictReader(open(f"{log}/cfb_lines_log.csv")):
        if x["cons_line"] and x["stat"] in COL:
            last[(x["player_id"], x["stat"], int(x["week"]))] = x
    out = []
    for (pid, st, w), x in last.items():
        a, lg = wk[w].get(pid), frozen.get((pid, w))
        if not a or not lg or st not in specs:
            continue
        pr, line, v = f(lg["p_" + st]), float(x["cons_line"]), a[COL[st]]
        if not pr or v == line:
            continue
        out.append((prob.sides(line, pr, specs[st])[0], 1 if v > line else 0, w))
    return out


def fit(d):
    """d: [(P(over), outcome, week)] -> dict(over=dict(beta, se, n), under=..., pooled=..., weeks=[...])."""
    res = {}
    for name, keep in (("over", lambda p: p > 0.5), ("under", lambda p: p <= 0.5)):
        xs = [p - 0.5 for p, y, w in d if keep(p)]
        ys = [y - 0.5 for p, y, w in d if keep(p)]
        n = len(xs)
        if n < MIN_N or not sum(x * x for x in xs):
            res[name] = dict(beta=None, se=None, n=n)
            continue
        sxx = sum(x * x for x in xs)
        b = sum(x * y for x, y in zip(xs, ys)) / sxx
        se = math.sqrt(sum((y - b * x) ** 2 for x, y in zip(xs, ys)) / (n - 1) / sxx)
        res[name] = dict(beta=round(min(1.0, max(0.0, b)), 3), se=round(se, 3), n=n)
    best = [(max(p, 1 - p), y if p > 0.5 else 1 - y) for p, y, w in d]
    res["model_conf"] = round(sum(b[0] for b in best) / len(best) * 100, 1) if best else None
    res["actual_hit"] = round(sum(b[1] for b in best) / len(best) * 100, 1) if best else None
    res["n"] = len(d)
    res["weeks"] = sorted({w for p, y, w in d})
    return res


def write(path, d):
    json.dump(fit(d), open(path, "w"), separators=(",", ":"))
    return fit(d)

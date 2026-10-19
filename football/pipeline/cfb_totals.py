"""Market-anchored college totals: predict the market's ERROR instead of the total.

    python -m pipeline.cfb_totals [--lam 30]

y = actual total - closing total. The model only has to find what the closing line missed, so it starts from the market and shrinks hard toward zero.
Features, all known before kickoff and built walk-forward (a week sees only earlier games):
  team_resid   shrunk average of (actual - market) over each team's earlier games, home + away (do some teams' games keep landing over or under?)
  level        market total minus the league's average market total so far (do extreme totals regress?)
  mismatch     |home spread| (blowout games, and the starters that sit)
  ridge_gap    the scores-only ridge model's total minus the market's (pipeline/cfb_spread.py)
  week         week of the season / 15
  fcs          one team outside FBS
  neutral      neutral site
Ridge regression, standardised features. Evaluation: MAE of the market vs market + delta, BETA (slope of the error on delta) and the over/under record by the
size of delta.
"""
import argparse, json, math
from . import config as C
from . import cfb_spread as S

FEATS = ["team_resid", "level", "mismatch", "ridge_gap", "week", "fcs", "neutral"]


def solve(a, b):
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(m[r][i]))
        m[i], m[piv] = m[piv], m[i]
        d = m[i][i] or 1e-12
        for j in range(i, n + 1):
            m[i][j] /= d
        for r in range(n):
            if r != i:
                f = m[r][i]
                for j in range(i, n + 1):
                    m[r][j] -= f * m[i][j]
    return [m[i][n] for i in range(n)]


def ridge(rows, ys, lam):
    """Standardised ridge with an intercept. Returns (coef, mean, sd, intercept)."""
    k = len(rows[0])
    mean = [sum(r[j] for r in rows) / len(rows) for j in range(k)]
    sd = [math.sqrt(sum((r[j] - mean[j]) ** 2 for r in rows) / len(rows)) or 1.0 for j in range(k)]
    z = [[(r[j] - mean[j]) / sd[j] for j in range(k)] for r in rows]
    ym = sum(ys) / len(ys)
    a = [[sum(r[i] * r[j] for r in z) + (lam if i == j else 0.0) for j in range(k)] for i in range(k)]
    b = [sum(r[i] * (y - ym) for r, y in zip(z, ys)) for i in range(k)]
    return solve(a, b), mean, sd, ym


def build(games, lines, fbs, ridge_gap, seasons):
    """One feature row per finished game with a closing total, in time order. `ridge_gap` maps (season, id) -> model total - market total."""
    rows = []
    for s in sorted(seasons):
        for g in games.get(s, []):
            sp, tt = lines.get((s, g["id"]), (None, None))
            if not g["done"] or tt is None or sp is None:
                continue
            rows.append(dict(season=s, week=g["week"], id=g["id"], home=g["home"], away=g["away"], total=tt, spread=sp, actual=g["hp"] + g["ap"],
                             neutral=int(g["neutral"]), fcs=int(not (g["home"] in fbs and g["away"] in fbs)), gap=ridge_gap.get((s, g["id"]))))
    return rows


def features(r, hist, shrink=8.0):
    """hist: the rows strictly before this game. -> feature vector in FEATS order."""
    res, n = {}, {}
    for h in hist:
        e = h["actual"] - h["total"]
        w = 1.0 if h["season"] == r["season"] else 0.5          # last season counts half
        for t in (h["home"], h["away"]):
            res[t] = res.get(t, 0.0) + w * e
            n[t] = n.get(t, 0.0) + w
    tr = sum(res.get(t, 0.0) / (n.get(t, 0.0) + shrink) for t in (r["home"], r["away"]))
    lg = sum(h["total"] for h in hist) / len(hist) if hist else r["total"]
    return [tr, r["total"] - lg, abs(r["spread"]), r["gap"] if r["gap"] is not None else 0.0, r["week"] / 15.0, r["fcs"], r["neutral"]]


def walk_forward(rows, season, lam, first_week=4):
    out = []
    for wk in sorted({r["week"] for r in rows if r["season"] == season}):
        if wk < first_week:
            continue
        train = [r for r in rows if (r["season"], r["week"]) < (season, wk)]
        test = [r for r in rows if r["season"] == season and r["week"] == wk]
        if len(train) < 300 or not test:
            continue
        # features for training rows use only THEIR earlier games; keep the pass O(n) per week by caching a running history
        xs, ys = [], []
        for i, r in enumerate(train):
            if i < 100:
                continue
            xs.append(features(r, train[:i]))
            ys.append(r["actual"] - r["total"])
        coef, mean, sd, ym = ridge(xs, ys, lam)
        for r in test:
            x = features(r, train)
            d = ym + sum(c * (x[j] - mean[j]) / sd[j] for j, c in enumerate(coef))
            out.append(dict(r, delta=d, coef=coef))
    return out


def evaluate(preds):
    n = len(preds)
    if not n:
        return dict(n=0)
    y = [p["actual"] - p["total"] for p in preds]
    d = [p["delta"] for p in preds]
    mkt = sum(abs(v) for v in y) / n
    adj = sum(abs(a - b) for a, b in zip(y, d)) / n
    sxx = sum(v * v for v in d)
    beta = sum(a * b for a, b in zip(d, y)) / sxx
    res = [a - beta * b for a, b in zip(y, d)]
    se = math.sqrt(sum(v * v for v in res) / (n - 2)) / math.sqrt(sxx)
    ou = {}
    for p, e in zip(preds, y):
        if e == 0:
            continue
        k = "|delta| >= 3" if abs(p["delta"]) >= 3 else "|delta| 2-3" if abs(p["delta"]) >= 2 else "|delta| 1-2" if abs(p["delta"]) >= 1 else "|delta| < 1"
        b = ou.setdefault(k, [0, 0])
        b[0] += 1
        b[1] += (e > 0) == (p["delta"] > 0)
    return dict(n=n, mkt_mae=round(mkt, 3), adj_mae=round(adj, 3), beta=round(beta, 3), beta_se=round(se, 3), delta_sd=round(math.sqrt(sxx / n), 2),
                ou={k: dict(n=v[0], hit=v[1], pct=round(v[1] / v[0] * 100, 1)) for k, v in sorted(ou.items())})


def main(raw="data/raw", lam=30.0):
    games, lines, fbs = S.load_games(raw)
    # the scores-only model's total gap, walk-forward, for every season it can predict
    gap = {}
    for s in sorted(games):
        if s - 1 in games or s == C.SEASON:
            for p in S.walk_forward(games, s, C.CFB_SPREAD_LAM, C.CFB_SPREAD_RHO, fbs=fbs):
                tt = lines.get((s, p["id"]), (None, None))[1]
                if tt is not None:
                    gap[(s, p["id"])] = p["model_total"] - tt
    rows = build(games, lines, fbs, gap, sorted(games))
    print(len(rows), "games with a closing total")
    for s in (C.SEASON - 1, C.SEASON):
        ev = evaluate(walk_forward(rows, s, lam))
        print(s, json.dumps(ev))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--lam", type=float, default=30.0)
    a = ap.parse_args()
    main(a.raw, a.lam)

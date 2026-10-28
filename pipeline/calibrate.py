"""How much of the model's P(win) at the PrizePicks line to believe  ->  site/data/calib.json

    python -m pipeline.calibrate [--results site/data/results] [--out site/data]

For every graded PrizePicks line (voided players left out, pushes skipped) the model's probability for its better side is computed exactly as
the Lines tab does (normal around the projection, the fitted spread), and compared with whether that side won. The calibrated probability is
    0.5 + beta * (P - 0.5),  beta = sum(x*y) / sum(x*x)  with x = P - 0.5, y = win - 0.5, clipped to [0, 1]
fitted separately for the Over and the Under side and for both together. beta = 1 would mean the model is right; 0 means the line is a coin flip
whatever the model says. First fit (Oct 20-27, 4,195 lines): about 0.1-0.2. It is refit on every refresh, so it follows the record.
"""
import argparse, glob, json, os
import numpy as np
from . import config as C
from . import results as R

MIN_N = 150


def fit(results_dir="site/data/results", raw="data/raw"):
    sp = {**C.SPREAD_DEFAULT, **(json.load(open(f"{raw}/spread.json")) if os.path.exists(f"{raw}/spread.json") else {})}
    X = {"all": [], "OVER": [], "UNDER": []}
    days = sorted(glob.glob(os.path.join(results_dir, "20??-??-??.json")))
    for f in days:
        for p in json.load(open(f)):
            if p.get("v"):
                continue
            for k, v in p["s"].items():
                pr, ac, cl, pl = v[0], v[1], v[2], v[3]
                if pl is None:
                    continue
                a, b = sp.get(k, [1.0, 0.3]); sd = max(a + b * pr, 0.1)
                po, pu = R.sides(pl, pr, sd); side = "OVER" if po >= pu else "UNDER"; pw = max(po, pu)
                g = R.grade(ac, pl, side)
                if g is None:
                    continue
                X["all"].append((pw - 0.5, int(g) - 0.5)); X[side].append((pw - 0.5, int(g) - 0.5))
    out = {"days": len(days), "asof": os.path.basename(days[-1])[:10] if days else None}
    for k, rows in X.items():
        n = len(rows)
        if n >= MIN_N:
            x = np.array([r[0] for r in rows]); y = np.array([r[1] for r in rows])
            beta = float(np.clip((x * y).sum() / (x * x).sum(), 0, 1))
            se = float(np.sqrt(((y - beta * x) ** 2).sum() / max(n - 1, 1) / (x * x).sum()))
            out[k] = {"beta": round(beta, 3), "se": round(se, 3), "n": n, "hit": round(float(y.mean() + 0.5), 3), "avgP": round(float(x.mean() + 0.5), 3)}
        else:
            out[k] = {"beta": None, "n": n}
    return out


def main(results_dir="site/data/results", out="site/data", raw="data/raw"):
    c = fit(results_dir, raw)
    os.makedirs(out, exist_ok=True)
    json.dump(c, open(os.path.join(out, "calib.json"), "w"), separators=(",", ":"))
    return c


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="site/data/results")
    ap.add_argument("--out", default="site/data")
    a = ap.parse_args()
    print(json.dumps(main(a.results, a.out), indent=1))

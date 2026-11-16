"""The cut behind the Under 65%+ gate: hit rate of the model's Unders at 65%+ by how many rotation players were out for the team.

    python -m pipeline.highlights_gate_test

Uses the graded days in site/data/results and the same leg logic as pipeline/highlights.py (records), with the rotation-out count of highlights.rotation_out. First run (Nov 16, 1,138 legs):
0 out 64.2% (525, 90% range 60.7-67.6, halves 61.5 / 71.9), 1 out 51.9% (264), 2+ out 49.9% (349); the Unders below 65% show the same fall (53.1% with 0-1 out, 47.4% with 2+).
"""
import glob, json, os
import numpy as np
from . import highlights as H, results as R


def wilson(h, n, z=1.645):
    if not n: return (float("nan"), float("nan"))
    p = h / n; c = (p + z * z / (2 * n)) / (1 + z * z / n); w = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n); return float(round(c - w, 3)), float(round(c + w, 3))


def main(out="site/data", raw="data/raw"):
    sp = H._spread(raw)
    days = sorted(glob.glob(os.path.join(out, "results", "20??-??-??.json"))); names = [os.path.basename(f)[:10] for f in days]
    mid = names[len(names) // 2]; ro = H.rotation_out(raw, names)
    legs = []
    for f, day in zip(days, names):
        for p in json.load(open(f)):
            if p.get("v"): continue
            for k, v in p["s"].items():
                if k not in H.STATS or v[3] is None: continue
                a, b = sp.get(k, [1.0, 0.3]); sd = max(a + b * v[0], 0.1)
                po, pu = R.sides(v[3], v[0], sd); side = "O" if po >= pu else "U"; g = R.grade(v[1], v[3], side)
                if g is not None: legs.append((day < mid, side, max(po, pu), min(ro.get(day, {}).get(p["t"], 0), 2), int(g)))
    for label, sel in (("Unders at 65%+", lambda l: l[1] == "U" and l[2] >= 0.65), ("Unders below 65%", lambda l: l[1] == "U" and l[2] < 0.65), ("Overs at 70%+", lambda l: l[1] == "O" and l[2] >= 0.70)):
        rows = [l for l in legs if sel(l)]
        print(f"{label}: {len(rows)} legs, hit {np.mean([l[4] for l in rows]):.3f}")
        for o in (0, 1, 2):
            x = [l for l in rows if l[3] == o]; n = len(x); h = sum(l[4] for l in x); A_ = [l for l in x if l[0]]; B_ = [l for l in x if not l[0]]
            print(f"  {'2+' if o == 2 else o} out: n {n:4d} hit {h / n if n else float('nan'):.3f} (90% {wilson(h, n)})  halves {np.mean([l[4] for l in A_]) if A_ else float('nan'):.3f}/{len(A_)} {np.mean([l[4] for l in B_]) if B_ else float('nan'):.3f}/{len(B_)}")


if __name__ == "__main__":
    main()

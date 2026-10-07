"""Tune the model's knobs on real data without fooling yourself.

    python -m pipeline.tune [--raw data/raw] [--last 120] [--every 2]

Walk-forward backtests the last --last game days. The OLDER half is the tuning set, the NEWER half is a
holdout the search never sees. Each knob is tried at a few values, one at a time, scored as the mean over
stats of (model MAE / season-average MAE) -- below 1.00 beats the baseline, and every stat counts equally.

A change is only recommended if it helps on the tuning half AND does not hurt the holdout. It prints
suggestions; it edits nothing. Copy what you accept into pipeline/config.py.
"""
import argparse, contextlib
import numpy as np
import pandas as pd
from . import config as C
from .backtest import run


@contextlib.contextmanager
def patched(name, value):
    old = getattr(C, name)
    setattr(C, name, value)
    try:
        yield
    finally:
        setattr(C, name, old)


def score(R):
    if not len(R):
        return np.nan
    return float(np.mean([(R[s + "_p"] - R[s + "_a"]).abs().mean() / (R[s + "_season"] - R[s + "_a"]).abs().mean() for s in C.STATS]))


def scaled(d, k):
    return {s: v * k for s, v in d.items()}


KNOBS = [
    ("RECENT_WEIGHT_MIN", [0.3, 0.5, 0.7, 0.85], lambda v: v),
    ("PRIOR_SEASON_WEIGHT", [0.25, 0.5, 0.8], lambda v: v),
    ("RECENT_EXTRA", [0.0, 0.5, 1.0, 2.0], lambda v: v),
    ("DEF_STRENGTH", [0.0, 0.5, 1.0, 1.5, 2.0], lambda v: scaled(C.DEF_STRENGTH, v)),   # scale on current damping
    ("RATE_PRIOR_MIN", [0.5, 1.0, 2.0], lambda v: scaled(C.RATE_PRIOR_MIN, v)),
    ("ROLLING_WINDOW", [3, 5, 8, 10], lambda v: v),
]


def main(raw, last, every):
    games = pd.read_csv(f"{raw}/games.csv", dtype={"pid": str})
    base = run(games, every, last)
    cut = base["date"].sort_values().iloc[len(base) // 2]
    print(f"{len(base)} player-games; tune on dates < {pd.Timestamp(cut).date()}, holdout on the rest")
    b_t, b_h = score(base[base["date"] < cut]), score(base[base["date"] >= cut])
    print(f"current settings: tune {b_t:.4f}   holdout {b_h:.4f}   (below 1.0 beats the season-average baseline)\n")
    suggest = []
    for name, vals, mk in KNOBS:
        cur = getattr(C, name)
        orig = cur.copy() if isinstance(cur, dict) else cur
        rows = []
        for v in vals:
            val = mk(v) if not isinstance(orig, dict) else {s: x * v for s, x in orig.items()}
            with patched(name, val):
                R = run(games, every, last)
            rows.append((v, score(R[R["date"] < cut]), score(R[R["date"] >= cut])))
        print(f"{name}  (current: {'x1.0 of ' if isinstance(orig, dict) else ''}{orig if not isinstance(orig, dict) else 'dict'})")
        for v, t, h in rows:
            flag = ""
            if t < b_t - 0.003 and h <= b_h + 0.001:
                flag = "  <- better on tune, not worse on holdout"
            print(f"   {v:>6}   tune {t:.4f}   holdout {h:.4f}{flag}")
        best = min(rows, key=lambda r: r[1])
        if best[1] < b_t - 0.003 and best[2] <= b_h + 0.001:
            suggest.append((name, best[0], best[1] - b_t, best[2] - b_h))
    print("\nSuggested changes (apply by hand in pipeline/config.py; for dict knobs multiply every value by the factor):")
    if not suggest:
        print("  none — current settings hold up; further tuning would mostly be fitting noise.")
    for n, v, dt, dh in suggest:
        print(f"  {n}: {'x' if n in ('DEF_STRENGTH', 'RATE_PRIOR_MIN') else '='}{v}   (tune {dt:+.4f}, holdout {dh:+.4f})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--last", type=int, default=120)
    ap.add_argument("--every", type=int, default=2)
    a = ap.parse_args()
    main(a.raw, a.last, a.every)

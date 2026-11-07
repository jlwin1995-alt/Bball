"""Test: pull each stat's projection toward the middle (regression to the mean) so the high and low ends land closer to actual results.

Bands show low projections beating the projection and high ones falling short (college 2026: WR receiving yards projected 10-25 average 34 actual, projected 70+ average 78 vs 85). Fit, per league / stat / position,
actual = a + b x projection by least absolute error (the projection is a median, so the median line, not the mean), on walk-forward pairs (pipeline.ranges.walk_*).
Scored leave-one-season-out: MAE, and the median error in low / middle / high projection bands, raw against shrunk. Adopt only if MAE does not get worse and the band errors move toward zero in both leagues.
"""
import json, os, statistics as S, sys
from . import config as C, ranges

CACHE = os.environ.get("PAIRS_CACHE", "/tmp/stat_pairs.json")
STATS = {"pts": 3.0, "rushY": 10, "recY": 10, "passY": 100, "rec": 1.0}
GROUPS = {"pts": ("QB", "RB", "WR", "TE"), "rushY": ("RB", "QB"), "recY": ("WR", "TE", "RB"), "passY": ("QB",), "rec": ("WR", "TE", "RB")}


def load():
    try:
        return json.load(open(CACHE))
    except OSError:
        W = dict(C.DEFAULT_SCORING)
        d = {"nfl": ranges.walk_nfl(W), "cfb": ranges.walk_cfb(W)}
        json.dump(d, open(CACHE, "w"))
        return d


def lad(xs, ys, iters=60):
    """y = a + b x by least absolute deviations (IRLS)."""
    n = len(xs)
    a, b = S.mean(ys), 0.0
    mx, my = S.mean(xs), S.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx:
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        a = my - b * mx
    for _ in range(iters):
        w = [1.0 / max(abs(y - a - b * x), 0.5) for x, y in zip(xs, ys)]
        sw = sum(w)
        mxw = sum(wi * x for wi, x in zip(w, xs)) / sw
        myw = sum(wi * y for wi, y in zip(w, ys)) / sw
        sxxw = sum(wi * (x - mxw) ** 2 for wi, x in zip(w, xs))
        if not sxxw:
            break
        b = sum(wi * (x - mxw) * (y - myw) for wi, x, y in zip(w, xs, ys)) / sxxw
        a = myw - b * mxw
    return a, b


def terciles(v):
    s = sorted(v)
    return s[len(s) // 3], s[2 * len(s) // 3]


def main():
    d = load()
    print(f"{'league stat pos':18}{'n':>6} {'fit a,b':>16} | {'MAE raw':>8}{'MAE shr':>8} | median error low/mid/high band: raw -> shrunk")
    adopt = {}
    for lg in ("nfl", "cfb"):
        for st, mn in STATS.items():
            for pos in GROUPS[st]:
                rows = [(p, a, s) for (t, ps, p, a, s) in d[lg] if t == st and ps == pos and p >= mn]
                if len(rows) < 300:
                    continue
                seasons = sorted({s for _, _, s in rows})
                lo_t, hi_t = terciles([p for p, _, _ in rows])
                raw, shr, band = [], [], {"raw": [[], [], []], "shr": [[], [], []]}
                for s in seasons:
                    tr = [(p, a) for p, a, x in rows if x != s]
                    te = [(p, a) for p, a, x in rows if x == s]
                    a0, b0 = lad([p for p, _ in tr], [a for _, a in tr])
                    for p, a in te:
                        q = max(0.0, a0 + b0 * p)
                        i = 0 if p < lo_t else 1 if p < hi_t else 2
                        raw.append(abs(a - p)); shr.append(abs(a - q))
                        band["raw"][i].append(a - p); band["shr"][i].append(a - q)
                a0, b0 = lad([p for p, _, _ in rows], [a for _, a, _ in rows])
                m = lambda k: "/".join(f"{S.median(x):+.1f}" for x in band[k])
                print(f"{lg+' '+st+' '+pos:18}{len(rows):6} {a0:8.2f},{b0:6.3f} | {S.mean(raw):8.2f}{S.mean(shr):8.2f} | {m('raw')} -> {m('shr')}")
                adopt[f"{lg}.{st}.{pos}"] = dict(n=len(rows), a=round(a0, 3), b=round(b0, 4), mae_raw=round(S.mean(raw), 3), mae_shr=round(S.mean(shr), 3))
    json.dump(adopt, open(os.environ.get("OUT", "/tmp/stat_shrink_fits.json"), "w"), indent=1)


if __name__ == "__main__":
    main()

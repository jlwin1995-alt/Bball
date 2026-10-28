"""Defence tiers and actual hit rates for the Lines tab (display only; see README "Hit rates against the toughest and softest defences").

tiers_now(rows)            -> {market: {team: dict(rank, of, tier)}}: how each defence ranks on that market going into the next games (1 = toughest = fewest allowed per game to the position group)
line_table(raw)            -> graded consensus lines of this season by tier (and market): n, over hit %, model side hit % (def_lines)
hist_table(path)           -> the 2023-25 walk-forward table (over-projection rate, actual / projected) saved in site/data/hitrates_hist.json by `python -m pipeline.hitrates --hist`
"""
import json, os, statistics, sys
from .def_hitrates import MARKETS, allowed_rank, collect


def tiers_now(rows):
    out = {}
    for m, (pos, _, col, _) in MARKETS.items():
        rk, n = allowed_rank(rows, 99, pos, col)
        out[m] = {t: dict(rank=r, of=n, tier="tough" if r <= 8 else "soft" if r > n - 8 else "mid") for t, r in rk.items()}
    return out


def line_table(raw="data/raw"):
    from .def_lines import run
    try:
        r = run(raw)
    except (OSError, KeyError, ValueError):
        return []
    rows = []
    for stat in [None] + list(MARKETS):
        for tier in ("tough", "mid", "soft"):
            s = [x for x in r if (stat is None or x["stat"] == stat) and x["tier"] == tier]
            if s:
                rows.append(dict(stat=stat or "all", tier=tier, n=len(s), over=round(sum(x["over"] for x in s) / len(s) * 100, 1),
                                 model=round(sum(x["over"] == x["model_over"] for x in s) / len(s) * 100, 1)))
    return rows


def hist_table(path="site/data/hitrates_hist.json"):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return []


if __name__ == "__main__":
    if "--hist" in sys.argv:
        res = collect()
        out = []
        for m in MARKETS:
            for tier in ("tough", "mid", "soft"):
                r = [x for x in res if x[0] == m and x[1] == tier]
                if r:
                    out.append(dict(stat=m, tier=tier, n=len(r), over=round(sum(1 for x in r if x[3] > x[2]) / len([x for x in r if x[3] != x[2]]) * 100, 1),
                                    ratio=round(sum(x[3] for x in r) / sum(x[2] for x in r), 2), miss=round(statistics.median(x[3] - x[2] for x in r), 1)))
        json.dump(out, open("site/data/hitrates_hist.json", "w"), separators=(",", ":"))
        print(f"wrote {len(out)} rows")

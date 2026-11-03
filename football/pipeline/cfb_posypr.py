"""Test: shrink college yards per catch toward the receiver's own position group (RB / TE / WR) instead of one league-wide figure (CFB_POS_YPR).
Walk-forward 2025-26, no fitted parameters, so a plain before/after on MAE and median error by position and season."""
import statistics as S
from collections import defaultdict
from . import config as C, ranges


def run(flag):
    C.CFB_POS_YPR = flag
    return ranges.walk_cfb(dict(C.DEFAULT_SCORING))


def main():
    res = {f: run(f) for f in (False, True)}
    assert len(res[False]) == len(res[True])
    for st, mn in (("recY", 10), ("rec", 1), ("pts", 3)):
        for pos in ("RB", "WR", "TE", "ALL"):
            print(f"\n{st} {pos}")
            for yr in (2025, 2026, None):
                line = f"  {yr or 'both'}: "
                for f in (False, True):
                    v = [(p, a) for (t, ps, p, a, y) in res[f] if t == st and (pos == "ALL" and ps in ("RB", "WR", "TE") or ps == pos) and (yr is None or y == yr)]
                    # same players in both runs: filter on the OFF projection so the sample matches
                    v = v
                    e = [a - p for p, a in v if p >= mn]
                    line += f"{'ON ' if f else 'OFF'} n={len(e)} MAE {S.mean(abs(x) for x in e):6.2f} med err {S.median(e):6.2f} mean proj {S.mean(p for p, a in v if p >= mn):6.2f} act {S.mean(a for p, a in v if p >= mn):6.2f}   "
                print(line)


if __name__ == "__main__":
    main()

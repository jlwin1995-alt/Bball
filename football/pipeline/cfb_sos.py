"""Test: schedule-adjusted college defence ratings (config CFB_SOS = {"pass", "rec"}): what a defence allowed against what each opposing offence normally gets, not against the league average.
Walk-forward 2025-26 (pipeline.ranges.walk_cfb), same projections otherwise. Scores passing / receiving yards MAE and the top-QB tough / soft split that motivated it."""
import statistics as S, sys
from . import config as C, ranges

W = dict(C.DEFAULT_SCORING)


def run(kinds):
    C.CFB_SOS = kinds
    return ranges.walk_cfb(W)


def main():
    base = run(())
    res = {"pass": run(("pass",)), "rec": run(("rec",)), "both": run(("pass", "rec"))}
    MIN = {"passY": 100, "recY": 10, "pts": 3, "rec": 1}
    print(f"{'stat pos':10}{'n':>6}  {'base':>8}" + "".join(f"{k:>9}" for k in res))
    for st, pos in (("passY", "QB"), ("recY", "WR"), ("recY", "TE"), ("recY", "RB"), ("rec", "WR"), ("pts", "QB"), ("pts", "WR"), ("pts", "TE"), ("pts", "RB")):
        idx = [i for i, t in enumerate(base) if t[0] == st and t[1] == pos and t[2] >= MIN[st]]
        b = S.mean(abs(base[i][3] - base[i][2]) for i in idx)
        cells = []
        for k, r in res.items():
            m = S.mean(abs(r[i][3] - r[i][2]) for i in idx)
            cells.append(f"{m:8.2f}({100 * (m / b - 1):+.1f}%)")
        print(f"{st+' '+pos:10}{len(idx):6}  {b:8.2f}  " + " ".join(cells))
    # the top-QB split by defence tier: projection factor is not in walk_cfb output, so compare actual / projection by the projection change instead
    idx = [i for i, t in enumerate(base) if t[0] == "passY" and t[1] == "QB" and t[2] >= 100]
    top = sorted(base[i][2] for i in idx)[2 * len(idx) // 3]
    for k, r in res.items():
        # defence effect = projection under SOS / projection at base; tough = SOS lowers the projection
        ch = [(r[i][2] / base[i][2], base[i][3] / r[i][2], base[i][2]) for i in idx if base[i][2] >= top and base[i][2] > 0]
        lo, hi = sorted(c[0] for c in ch)[len(ch) // 3], sorted(c[0] for c in ch)[2 * len(ch) // 3]
        tough = [c[1] for c in ch if c[0] < lo]; soft = [c[1] for c in ch if c[0] >= hi]
        print(f"top-third QBs, {k}: where SOS lowers the projection (n {len(tough)}) actual/proj median {S.median(tough):.2f}; where it raises it (n {len(soft)}) {S.median(soft):.2f}")
    # also base: split by base-projection change is not available; skip


if __name__ == "__main__":
    main()

"""Test: weaken the college pass-defence factor (CFB_K_DEF_PASS prior weight, DEF_ADJ_CAP) because top-third QBs beat projection against tough pass defences (1.10) and fall short against soft ones (0.93).
Walk-forward 2025-26 via pipeline.tier_grid.cfb (carries the model's own pass factor a_pass). Scores QB passing yards MAE, QB fantasy points MAE, and the top-third QB split by defence tier."""
import statistics as S
from . import config as C, tier_grid, ranges


def run(k, cap):
    C.CFB_K_DEF_PASS = k
    C.DEF_ADJ_CAP = cap
    rows = tier_grid.cfb(C.DEFAULT_SCORING)
    py = [(p, a, f) for (t, ps, p, a, s, f, o) in rows if t == "passY" and ps == "QB" and p >= 100]
    top = sorted(p for p, _, _ in py)[2 * len(py) // 3]
    fl, fh = sorted(f for _, _, f in py)[len(py) // 3], sorted(f for _, _, f in py)[2 * len(py) // 3]
    mae = S.mean(abs(a - p) for p, a, _ in py)
    tt = [a / p for p, a, f in py if p >= top and f < fl]
    ts = [a / p for p, a, f in py if p >= top and f >= fh]
    allt = [a / p for p, a, f in py if f < fl]; alls = [a / p for p, a, f in py if f >= fh]
    spread = S.pstdev([f for _, _, f in py])
    return dict(n=len(py), mae=mae, tough_top=S.median(tt) if tt else None, nt=len(tt), soft_top=S.median(ts) if ts else None, ns=len(ts), tough_all=S.median(allt), soft_all=S.median(alls), spread=spread)


def main():
    base_k, base_cap = C.CFB_K_DEF_PASS, C.DEF_ADJ_CAP
    print(f"{'setting':28}{'n':>6}{'MAE':>8}{'factor sd':>10}  top-third QBs: tough / soft (n)       all QBs: tough / soft")
    for lab, k, cap in (("as now (K %s, cap %s)" % (base_k, base_cap), base_k, base_cap), ("K 150", 150, base_cap), ("K 400", 400, base_cap), ("factor off (K 1e9)", 1e9, base_cap), ("cap 0.10", base_k, 0.10), ("cap 0.05", base_k, 0.05)):
        r = run(k, cap)
        print(f"{lab:28}{r['n']:6}{r['mae']:8.2f}{r['spread']:10.3f}  {r['tough_top']:.2f} ({r['nt']}) / {r['soft_top']:.2f} ({r['ns']})       {r['tough_all']:.2f} / {r['soft_all']:.2f}")


if __name__ == "__main__":
    main()

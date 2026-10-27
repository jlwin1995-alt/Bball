"""Tight end out test: when the injury report lists a TE OUT, does removing him from the pool (OUT_TE, as is done for RB / WR / QB) improve his teammates' projections?

    python -m pipeline.out_te        # needs data/raw/history/{weekly,schedule,injuries}_<s>.csv

Walk-forward weeks 5+, 2023-25. Teammates of an OUT tight end who played, with and without OUT_TE, MAE of targets, receptions, receiving yards and points; also the other TEs on those teams.
"""
from . import config as C
from .backtest import load_inj, INJ, actual
from .model import load_weekly, nfl_core, derive, params
from .slate import load_csv, matchups


def run(seasons, raw="data/raw"):
    P = params()
    W = C.DEFAULT_SCORING
    out = []
    for season in seasons:
        load_inj(season, raw)
        rows = load_weekly(f"{raw}/history/weekly_{season}.csv")
        sched = load_csv(f"{raw}/history/schedule_{season}.csv")
        by_week = {}
        for r in rows:
            by_week.setdefault(int(r["week"]), []).append(r)
        for wk in range(5, max(by_week) + 1):
            mu = matchups(sched, wk)
            if not mu:
                continue
            hist = [r for x in range(1, wk) for r in by_week.get(x, [])]
            ids = {r["gsis_id"] for r in INJ.get(season, []) if int(float(r["week"] or 0)) == wk and r["report_status"] == "Out"}
            pos = {r["player_id"]: r["position"] for r in hist}
            te_out = {r["team"] for r in hist if r["player_id"] in ids and r["position"] == "TE" and r["season_type"] == "REG" if "season_type" in r} if False else {r["team"] for r in hist if r["player_id"] in ids and r["position"] == "TE"}
            if not te_out:
                continue
            c0 = nfl_core(hist, mu, None, dict(P, OUT_IDS=ids, OUT_TE=False))
            c1 = nfl_core(hist, mu, None, dict(P, OUT_IDS=ids, OUT_TE=True))
            act = {r["player_id"]: r for r in by_week[wk]}
            p1 = {pl["id"]: pl for pl in c1["players"]}
            for pl in c0["players"]:
                a = act.get(pl["id"])
                if a is None or pl["team"] not in te_out or pl["id"] in ids or pl["id"] not in p1:
                    continue
                d0, d1 = derive(pl, W, P), derive(p1[pl["id"]], W, P)
                if d0["pts"] < 2.0 and d1["pts"] < 2.0:
                    continue
                s_ = actual(a, W)
                grp = "TE" if pl["pos"] == "TE" else "other"
                for st, k0, ak in (("targets", "tgt", a["targets"]), ("receptions", "rec", a["receptions"]), ("rec yards", "recY", a["receiving_yards"]), ("points", "pts", s_["pts"])):
                    out.append((grp, st, d0[k0] if k0 != "tgt" else pl["tgt"], d1[k0] if k0 != "tgt" else p1[pl["id"]]["tgt"], ak))
    return out


if __name__ == "__main__":
    res = run([2023, 2024, 2025])
    for grp in ("TE", "other", None):
        for st in ("targets", "receptions", "rec yards", "points"):
            r = [x for x in res if x[1] == st and (grp is None or x[0] == grp)]
            if not r:
                continue
            m0, m1 = (sum(abs(x[i] - x[4]) for x in r) / len(r) for i in (2, 3))
            print(f"{grp or 'all':5} {st:10} n={len(r):4}  MAE {m0:.3f} -> {m1:.3f} ({(m1 - m0) / m0 * 100:+.1f}%)  bias {sum(x[2] - x[4] for x in r) / sum(x[4] for x in r) * 100:+.1f}% -> {sum(x[3] - x[4] for x in r) / sum(x[4] for x in r) * 100:+.1f}%")

"""College QB rushing test: are mobile quarterbacks' rushing projections shrunk too far?

    python -m pipeline.cfb_qbrush       # needs data/raw/cfb_hist/cfb_{weekly,games}_2025.csv and data/raw/cfb_{weekly,games}.csv

Walk-forward weeks 5+, 2025-26, college QBs projecting 15+ attempts who played 8+ (1,399 player-games), grouped by the rushing yards a game in their earlier games (pocket < 20, mid 20-40,
runner 40+ with at least 3 earlier games). Variants of the existing knobs: CFB_QB_PRIOR_CAR (carries of prior for the QB's yards per carry and rushing TD rate; None = 30), CFB_QB_FIXED_CARRIES,
CFB_QB_TIERS, RECENT_WEIGHT. Reported per group: MAE of projected rushing yards and of points, bias of rushing yards against the actual median and mean.
"""
import statistics
from . import config as C
from .cfb_build import schedule, excluded_games
from .cfb_data import read_csv
from .cfb_model import cfb_core, derive, load_rows, actual_pts
from .model import params

VARIANTS = [("today", {}), ("prior 10", dict(CFB_QB_PRIOR_CAR=10)), ("prior 0.1", dict(CFB_QB_PRIOR_CAR=0.1)), ("fixed carries", dict(CFB_QB_FIXED_CARRIES=True)),
            ("tiers", dict(CFB_QB_TIERS=True)), ("fixed + prior 10", dict(CFB_QB_FIXED_CARRIES=True, CFB_QB_PRIOR_CAR=10)), ("tiers + fixed", dict(CFB_QB_TIERS=True, CFB_QB_FIXED_CARRIES=True)),
            ("recent .5", dict(RECENT_WEIGHT=0.5))]
GROUPS = (("pocket", lambda m: m < 20), ("mid", lambda m: 20 <= m < 40), ("runner", lambda m: m >= 40))


def run(sources, variants=VARIANTS, from_week=5):
    W = C.DEFAULT_SCORING
    out = []
    for wpath, gpath in sources:
        rows, games = load_rows(wpath), read_csv(gpath)
        sched, skip = schedule(games), excluded_games(games)
        for wk in sorted({int(x["week"]) for x in rows}):
            if wk < from_week or wk not in sched:
                continue
            hist = [x for x in rows if x["week"] < wk and (x["team"], int(x["week"])) not in skip]
            now = {x["playerId"]: x for x in rows if x["week"] == wk}
            mu = {}
            for g in sched[wk]["games"]:
                neu = g["neutral"]
                mu[g["awayTeam"]] = dict(opp=g["homeTeam"], site="N" if neu else "@")
                mu[g["homeTeam"]] = dict(opp=g["awayTeam"], site="N" if neu else "vs")
            by = {}
            for x in hist:
                by.setdefault(x["playerId"], []).append(x)
            for name, over in variants:
                core = cfb_core(hist, mu, sched[wk]["conf"], dict(params(), **over))
                for pl in core["players"]:
                    a = now.get(pl["id"])
                    h = by.get(pl["id"], [])
                    if a is None or pl["pos"] != "QB" or pl["att"] < 15 or a["attempts"] < 8 or (pl["team"], wk) in skip or len(h) < 3:
                        continue
                    d = derive(pl, W)
                    m = statistics.mean(x["rushing_yards"] for x in h)
                    g = next(n for n, f in GROUPS if f(m))
                    for grp in (g, "all"):
                        out.append((name, grp, d["rushY"], a["rushing_yards"], d["pts"], actual_pts(a, W), pl["car"], a["carries"]))
    return out


if __name__ == "__main__":
    res = run([("data/raw/cfb_hist/cfb_weekly_2025.csv", "data/raw/cfb_hist/cfb_games_2025.csv"), ("data/raw/cfb_weekly.csv", "data/raw/cfb_games.csv")])
    names = [v[0] for v in VARIANTS]
    for grp in ("pocket", "mid", "runner", "all"):
        base = [x for x in res if x[0] == "today" and x[1] == grp]
        print(f"--- {grp} (n={len(base)}; actual rush median {statistics.median(x[3] for x in base):.0f}, mean {statistics.mean(x[3] for x in base):.1f}, carries {statistics.mean(x[7] for x in base):.1f}) ---")
        print(f"{'variant':20}{'rush MAE':>9}{'rush bias':>10}{'vs median':>10}{'carries':>8}{'pts MAE':>8}{'pts bias':>9}")
        for nm in names:
            s = [x for x in res if x[0] == nm and x[1] == grp]
            med = statistics.median(x[3] for x in s)
            print(f"{nm:20}{statistics.mean(abs(x[2] - x[3]) for x in s):9.2f}{(sum(x[2] for x in s) / sum(x[3] for x in s) - 1) * 100:+9.1f}%{statistics.mean(x[2] for x in s) / med * 100 - 100:+9.1f}%"
                  f"{statistics.mean(x[6] for x in s):8.1f}{statistics.mean(abs(x[4] - x[5]) for x in s):8.2f}{(sum(x[4] for x in s) / sum(x[5] for x in s) - 1) * 100:+8.1f}%", flush=True)

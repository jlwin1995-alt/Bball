"""College recent-usage weighting test: does the 20% weight on a player's last 3 games (RECENT_WEIGHT) under-project players whose role moved?

    python -m pipeline.cfb_recent        # needs data/raw/cfb_hist/cfb_{weekly,games}_2025.csv and data/raw/cfb_{weekly,games}.csv (2026)

Walk-forward, weeks 5+ of 2025 and 2026, each week projected from the weeks before it by cfb_core; RECENT_WEIGHT in 0.2 (current), 0.35, 0.5, 0.7. A "mover" is a RB / WR / TE whose share of the team's
carries + receptions over his last 3 games is 10+ points above (riser) or below (faller) his earlier games (at least 3 earlier games). MAE of projected carries / receptions / yards / points,
all players and movers.
"""
import statistics
from . import config as C
from .cfb_build import schedule, excluded_games
from .cfb_data import read_csv
from .cfb_model import cfb_core, derive, load_rows, actual_pts
from .model import params

WEIGHTS = (0.2, 0.35, 0.5, 0.7)


def shares(hist):
    team = {}
    for x in hist:
        t = team.setdefault((x["team"], int(x["week"])), 0.0)
        team[(x["team"], int(x["week"]))] = t + x["carries"] + x["receptions"]
    by = {}
    for x in hist:
        by.setdefault(x["playerId"], []).append(x)
    mv = {}
    for pid, w in by.items():
        w = sorted(w, key=lambda x: x["week"])
        if len(w) < 6 or w[-1]["position"] not in ("RB", "WR", "TE"):
            continue
        sh = lambda seg: (lambda d: None if not d else sum(x["carries"] + x["receptions"] for x in seg) / d * 100)(sum(team[(x["team"], int(x["week"]))] for x in seg))
        a, b = sh(w[-3:]), sh(w[:-3])
        if a is not None and b is not None:
            mv[pid] = a - b
    return mv


def run(sources, weights=WEIGHTS, from_week=5):
    W = C.DEFAULT_SCORING
    out = []                                                    # (weight, group, stat, projection, actual)
    for wpath, gpath in sources:
        rows, games = load_rows(wpath), read_csv(gpath)
        sched = schedule(games)
        skip = excluded_games(games)
        for wk in sorted({int(x["week"]) for x in rows}):
            if wk < from_week or wk not in sched:
                continue
            hist = [x for x in rows if x["week"] < wk and (x["team"], int(x["week"])) not in skip]
            now = {x["playerId"]: x for x in rows if x["week"] == wk}
            if len(hist) < 200 or not now:
                continue
            mu = {}
            for g in sched[wk]["games"]:
                neu = g["neutral"]
                mu[g["awayTeam"]] = dict(opp=g["homeTeam"], site="N" if neu else "@")
                mu[g["homeTeam"]] = dict(opp=g["awayTeam"], site="N" if neu else "vs")
            mv = shares(hist)
            for rw in weights:
                core = cfb_core(hist, mu, sched[wk]["conf"], dict(params(), RECENT_WEIGHT=rw))
                for pl in core["players"]:
                    a = now.get(pl["id"])
                    if a is None or (pl["team"], wk) in skip or pl["pos"] not in ("RB", "WR", "TE"):
                        continue
                    d = derive(pl, W)
                    if d["pts"] < 2.0:
                        continue
                    m = mv.get(pl["id"])
                    grp = "all" if m is None or abs(m) < 10 else "riser" if m > 0 else "faller"
                    for g_ in {"all", grp}:
                        for st, proj, act in (("carries", pl["car"], a["carries"]), ("receptions", pl["rec"], a["receptions"]), ("rush yds", d["rushY"], a["rushing_yards"]),
                                              ("rec yds", d["recY"], a["receiving_yards"]), ("points", d["pts"], actual_pts(a, W))):
                            out.append((rw, g_, st, proj, act))
    return out


if __name__ == "__main__":
    res = run([("data/raw/cfb_hist/cfb_weekly_2025.csv", "data/raw/cfb_hist/cfb_games_2025.csv"), ("data/raw/cfb_weekly.csv", "data/raw/cfb_games.csv")])
    for grp in ("all", "riser", "faller"):
        for st in ("carries", "receptions", "rush yds", "rec yds", "points"):
            line = []
            for rw in WEIGHTS:
                r = [x for x in res if x[0] == rw and x[1] == grp and x[2] == st]
                line.append(f"{sum(abs(x[3] - x[4]) for x in r) / len(r):.3f}")
            n = len([x for x in res if x[0] == 0.2 and x[1] == grp and x[2] == st])
            b = [x for x in res if x[0] == 0.2 and x[1] == grp and x[2] == st]
            bias = sum(x[3] - x[4] for x in b) / max(1.0, sum(x[4] for x in b)) * 100
            print(f"{grp:7} {st:10} n={n:5} MAE by recent weight {WEIGHTS}: {' '.join(line)}  (bias at 0.2: {bias:+.1f}%)", flush=True)

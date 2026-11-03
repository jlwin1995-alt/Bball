"""Typical range of a projection: how far actual results land from the projection, by league, stat and position.

Walk-forward projections (each week projected from the weeks before it only; NFL 2023-26, college 2025-26, week 5 on) are compared with what happened.
For every (stat, position) the 10th and 90th percentile of (actual - projection) are taken in six projection-size bins
(equal counts). The bin points are kept as [mean projection, 10th, 90th] and the page interpolates between them (held flat beyond the first and last bin, no extrapolation), so the band widens as the projection grows:
low = proj + error_10th, high = proj + error_90th (never below 0).
Points are Full PPR (the site default); the page rescales them for other scoring presets. Written to data/ranges.json (committed, refit by hand with
`python -m pipeline.ranges` a few times a season) and copied to site/data[/cfb]/ranges.json by the builds. Display only; no projection changes.
"""
import json
from collections import defaultdict
from . import config as C

LO, HI = 0.10, 0.90
MIN_PROJ = {"pts": 3.0, "rushY": 10, "recY": 10, "passY": 100, "rec": 1.0}
GROUPS = {"pts": ("QB", "RB", "WR", "TE"), "rushY": ("RB", "QB"), "recY": ("WR", "TE", "RB"), "passY": ("QB",), "rec": ("WR", "TE", "RB")}
MIN_N = 120


def q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))]


def walk_nfl(W):
    from .model import load_weekly, nfl_core, derive, params
    from .slate import load_csv, matchups
    from .backtest import load_inj, INJ, actual
    P, out = params(), []
    src = [(s, f"data/raw/history/weekly_{s}.csv", f"data/raw/history/schedule_{s}.csv") for s in (2023, 2024, 2025)] + [(2026, "data/raw/weekly.csv", "data/raw/schedule.csv")]
    for season, wp, sp in src:
        load_inj(season, "data/raw")
        rows, sched, by = load_weekly(wp), load_csv(sp), {}
        for r in rows:
            by.setdefault(int(r["week"]), []).append(r)
        for wk in range(5, max(by) + 1):
            mu = matchups(sched, wk)
            if not mu or wk not in by:
                continue
            hist = [r for x in range(1, wk) for r in by.get(x, [])]
            outs = {r["gsis_id"] for r in INJ.get(season, []) if int(float(r["week"] or 0)) == wk and r["report_status"] == "Out"}
            core = nfl_core(hist, mu, None, dict(P, OUT_IDS=outs))
            act = {r["player_id"]: r for r in by[wk]}
            for pl in core["players"]:
                a = act.get(pl["id"])
                if a is None:
                    continue
                d, z = derive(pl, W, P), actual(a, W)
                for st in GROUPS:
                    out.append((st, pl["pos"], d[st], z[st], season))
    return out


def walk_cfb(W):
    from .cfb_build import schedule, excluded_games
    from .cfb_data import read_csv
    from .cfb_model import cfb_core, derive, load_rows
    from .model import params
    out = []
    for yr, (wp, gp) in zip((2025, 2026), (("data/raw/cfb_hist/cfb_weekly_2025.csv", "data/raw/cfb_hist/cfb_games_2025.csv"), ("data/raw/cfb_weekly.csv", "data/raw/cfb_games.csv"))):
        rows, games = load_rows(wp), read_csv(gp)
        sched, skip = schedule(games), excluded_games(games)
        for wk in sorted({int(x["week"]) for x in rows}):
            if wk < 5 or wk not in sched:
                continue
            hist = [x for x in rows if x["week"] < wk and (x["team"], int(x["week"])) not in skip]
            now = {x["playerId"]: x for x in rows if x["week"] == wk}
            mu = {}
            for g in sched[wk]["games"]:
                s = "N" if g["neutral"] else None
                mu[g["awayTeam"]] = dict(opp=g["homeTeam"], site=s or "@")
                mu[g["homeTeam"]] = dict(opp=g["awayTeam"], site=s or "vs")
            core = cfb_core(hist, mu, sched[wk]["conf"], params())
            for pl in core["players"]:
                a = now.get(pl["id"])
                if a is None or (pl["team"], wk) in skip:
                    continue
                d = derive(pl, W)
                act = dict(pts=sum([a["rushing_yards"] * W["rushYd"], a["receiving_yards"] * W["recYd"], a["passing_yards"] * W["passYd"], a["receptions"] * W["rec"],
                                    a["rushing_tds"] * W["rushTd"], a["receiving_tds"] * W["recTd"], a["passing_tds"] * W["passTd"], a["interceptions"] * W["intr"], a["fumbles_lost"] * W["fum"]]),
                           rushY=a["rushing_yards"], recY=a["receiving_yards"], passY=a["passing_yards"], rec=a["receptions"])
                for st in GROUPS:
                    out.append((st, pl["pos"], d[st], act[st], yr))
    return out


def fit(pairs):
    g = defaultdict(list)
    for st, pos, p, a, *_ in pairs:
        if st in MIN_PROJ and p >= MIN_PROJ[st] and pos in GROUPS[st]:
            g[(st, pos)].append((p, a - p))
    out = {}
    for (st, pos), v in g.items():
        if len(v) < MIN_N:
            continue
        v.sort()
        k = 6
        bins = [v[i * len(v) // k:(i + 1) * len(v) // k] for i in range(k)]
        es = [e for _, e in v]
        out.setdefault(st, {})[pos] = dict(n=len(v), min=MIN_PROJ[st], mae=round(sum(abs(e) for e in es) / len(es), 2),
                                           bins=[[round(sum(p for p, _ in b) / len(b), 2), round(q([e for _, e in b], LO), 2), round(q([e for _, e in b], HI), 2)] for b in bins])
    return out


def main():
    W = dict(C.DEFAULT_SCORING)
    res = {}
    for lg, fn in (("nfl", walk_nfl), ("cfb", walk_cfb)):
        res[lg] = fit(fn(W))
        print(lg, {st: {p: v["n"] for p, v in d.items()} for st, d in res[lg].items()})
    json.dump(dict(scoring="Full PPR", level=f"{int(LO * 100)}th to {int(HI * 100)}th percentile", **res), open("data/ranges.json", "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()

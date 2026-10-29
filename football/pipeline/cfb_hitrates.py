"""College version of the defence-tier hit rates (see pipeline/hitrates.py, README "Hit rates against the toughest and softest defences").

    python -m pipeline.cfb_hitrates [--hist]       # --hist writes site/data/cfb/hitrates_hist.json (walk-forward 2025-26, minutes)

Defences are FBS teams ranked on a market by what they allowed per game to that position group over the earlier weeks of the season (min 3 games; opponents' box-score rows against them),
toughest 25% / middle 50% / softest 25% (the NFL's 8 / 16 / 8 of 32). hist: share of games the actual went over the model's projection; lines: this season's graded consensus lines.
"""
import csv, json, statistics, sys
from collections import defaultdict
from . import config as C
from .cfb_data import read_csv
from .cfb_model import cfb_core, derive, load_rows
from .model import params
from .teamstats import fbs_teams

MARKETS = {"rushY": (("RB",), "rushing_yards", "ry"), "recY": (("WR", "TE", "RB"), "receiving_yards", "recy"), "rec": (("WR", "TE", "RB"), "receptions", "rec"),
           "passY": (("QB",), "passing_yards", "py"), "comp": (("QB",), "completions", "comp")}
FLOOR = {"rushY": 10.0, "recY": 10.0, "rec": 1.0, "passY": 50.0, "comp": 5.0}


def tier_of(rank, n):
    return "tough" if rank <= n * 0.25 else "soft" if rank > n * 0.75 else "mid"


def allowed_rank(hist, positions, col, fbs, min_g=3):
    """{team: (rank, n)} (1 = toughest) among FBS defences, from the weekly rows `hist`."""
    tot, games = defaultdict(float), defaultdict(set)
    for r in hist:
        o = r["opponent"]
        if o in fbs:
            games[o].add(int(r["week"]))
            if r["position"] in positions:
                tot[o] += r[col]
    per = {t: tot[t] / len(games[t]) for t in games if len(games[t]) >= min_g}
    order = sorted(per, key=lambda t: per[t])
    return {t: (i + 1, len(order)) for i, t in enumerate(order)}


def tiers_now(rows, games):
    fbs = fbs_teams(games)
    out = {}
    for m, (pos, col, _) in MARKETS.items():
        rk = allowed_rank(rows, pos, col, fbs)
        out[m] = {t: dict(rank=r, of=n, tier=tier_of(r, n)) for t, (r, n) in rk.items()}
    return out


def collect(sources, from_week=5):
    from .cfb_build import schedule, excluded_games
    W = C.DEFAULT_SCORING
    out = []
    for wpath, gpath in sources:
        rows, games = load_rows(wpath), read_csv(gpath)
        fbs = fbs_teams(games)
        sched, skip = schedule(games), excluded_games(games)
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
            ranks = {m: allowed_rank(hist, v[0], v[1], fbs) for m, v in MARKETS.items()}
            core = cfb_core(hist, mu, sched[wk]["conf"], params())
            for pl in core["players"]:
                a = now.get(pl["id"])
                if a is None or (pl["team"], wk) in skip:
                    continue
                d = derive(pl, W)
                for m, (pos, col, key) in MARKETS.items():
                    if pl["pos"] not in pos or d[{"rushY": "rushY", "recY": "recY", "rec": "rec", "passY": "passY", "comp": "comp"}[m]] < FLOOR[m]:
                        continue
                    rk = ranks[m].get(pl["opp"])
                    if rk is None:
                        continue
                    out.append((m, tier_of(*rk), d[m], a[col]))
    return out


def hist_rows(res):
    out = []
    for m in MARKETS:
        for tier in ("tough", "mid", "soft"):
            r = [x for x in res if x[0] == m and x[1] == tier]
            if r:
                ne = [x for x in r if x[3] != x[2]]
                out.append(dict(stat=m, tier=tier, n=len(r), over=round(sum(1 for x in ne if x[3] > x[2]) / len(ne) * 100, 1),
                                ratio=round(sum(x[3] for x in r) / sum(x[2] for x in r), 2), miss=round(statistics.median(x[3] - x[2] for x in r), 1)))
    return out


def line_table(rows, games, log="data/log/cfb_log.csv", lines="data/log/cfb_lines_log.csv", season="2026"):
    """This season's graded college consensus lines by defence tier (and market): n, over hit %, the model's side hit % (frozen projection from the college log)."""
    fbs = fbs_teams(games)
    try:
        frozen = {(x["player_id"], x["week"]): x for x in csv.DictReader(open(log)) if x["season"] == season}
        lrows = list(csv.DictReader(open(lines)))
    except OSError:
        return []
    by = defaultdict(dict)
    for r in rows:
        by[int(r["week"])][r["playerId"]] = r
    cache, out = {}, []
    for x in lrows:
        if not x["cons_line"] or x["stat"] not in MARKETS:
            continue
        wk = int(x["week"])
        a, lg = by[wk].get(x["player_id"]), frozen.get((x["player_id"], x["week"]))
        if not a or not lg:
            continue
        pos, col, _ = MARKETS[x["stat"]]
        if a["position"] not in pos:
            continue
        if (wk, x["stat"]) not in cache:
            cache[(wk, x["stat"])] = allowed_rank([r for w, d in by.items() if w < wk for r in d.values()], pos, col, fbs)
        rk = cache[(wk, x["stat"])].get(lg["opp"])
        line, act = float(x["cons_line"]), a[col]
        if not rk or act == line:
            continue
        out.append(dict(stat=x["stat"], tier=tier_of(*rk), over=act > line, model_over=float(lg["p_" + x["stat"]] or 0) > line))
    rows_ = []
    for stat in [None] + list(MARKETS):
        for tier in ("tough", "mid", "soft"):
            s = [o for o in out if (stat is None or o["stat"] == stat) and o["tier"] == tier]
            if s:
                rows_.append(dict(stat=stat or "all", tier=tier, n=len(s), over=round(sum(o["over"] for o in s) / len(s) * 100, 1),
                                  model=round(sum(o["over"] == o["model_over"] for o in s) / len(s) * 100, 1)))
    return rows_


def hist_table(path="site/data/cfb/hitrates_hist.json"):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return []


NOTE = "In college the pattern is weaker and less consistent than in the NFL: the Over rate on posted lines is higher against the softest quarter of defences (about 55% vs 48%), but over the projection it is mixed by market, and the college line record covers only a few weeks."

SOURCES = [("data/raw/cfb_hist/cfb_weekly_2025.csv", "data/raw/cfb_hist/cfb_games_2025.csv"), ("data/raw/cfb_weekly.csv", "data/raw/cfb_games.csv")]

if __name__ == "__main__":
    res = collect(SOURCES)
    h = hist_rows(res)
    print(f"{len(res)} player-game-markets")
    print(f"{'market':7}{'tier':6}{'n':>6}{'over proj':>10}{'actual/proj':>12}{'median miss':>12}")
    for x in h:
        print(f"{x['stat']:7}{x['tier']:6}{x['n']:6}{x['over']:9.1f}%{x['ratio']:12.2f}{x['miss']:+12.1f}")
    if "--hist" in sys.argv:
        json.dump(h, open("site/data/cfb/hitrates_hist.json", "w"), separators=(",", ":"))
        print("wrote site/data/cfb/hitrates_hist.json")

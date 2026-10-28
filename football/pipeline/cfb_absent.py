"""College absent-player test: with no injury feed, treat a player who has no box-score row in his team's last N games as probably out, so the men who have been playing take his share.

    python -m pipeline.cfb_absent       # needs data/raw/cfb_hist/cfb_{weekly,games}_2025.csv and data/raw/cfb_{weekly,games}.csv (2026)

Walk-forward weeks 5+ of 2025 and 2026 (cfb_core, `CFB_ABSENT_GAMES` N, `CFB_ABSENT_W` the weight his share keeps in the team's carry / reception denominator: 1 = today, 0 = none). Compared on all
RB / WR / TE and on the teammates of a "meaningful absentee" (3+ carries + receptions a game when he played, missing the last N team games). RECENT_WEIGHT variants ride along.
"""
from . import config as C
from .cfb_build import schedule, excluded_games
from .cfb_data import read_csv
from .cfb_model import cfb_core, derive, load_rows, actual_pts
from .model import params

VARIANTS = [("today", {}), ("absent2 w0", dict(CFB_ABSENT_GAMES=2, CFB_ABSENT_W=0.0)), ("absent2 w.5", dict(CFB_ABSENT_GAMES=2, CFB_ABSENT_W=0.5)),
            ("absent3 w0", dict(CFB_ABSENT_GAMES=3, CFB_ABSENT_W=0.0)), ("recent .5", dict(RECENT_WEIGHT=0.5)), ("absent2 w0 + recent .5", dict(CFB_ABSENT_GAMES=2, CFB_ABSENT_W=0.0, RECENT_WEIGHT=0.5))]


def absentee_teams(hist, n=2):
    tw, pl = {}, {}
    for x in hist:
        tw.setdefault(x["team"], set()).add(int(x["week"]))
        pl.setdefault((x["team"], x["playerId"]), []).append(x)
    out = set()
    for t, ws in tw.items():
        last = sorted(ws)[-n:]
        if len(ws) <= n:
            continue
        for (tt, pid), w in pl.items():
            if tt != t or len(w) < 2 or any(int(x["week"]) in last for x in w):
                continue
            if w[0]["position"] in ("RB", "WR", "TE") and sum(x["carries"] + x["receptions"] for x in w) / len(w) >= 3:
                out.add(t)
    return out


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
            if len(hist) < 200 or not now:
                continue
            mu = {}
            for g in sched[wk]["games"]:
                neu = g["neutral"]
                mu[g["awayTeam"]] = dict(opp=g["homeTeam"], site="N" if neu else "@")
                mu[g["homeTeam"]] = dict(opp=g["awayTeam"], site="N" if neu else "vs")
            ab = absentee_teams(hist)
            for name, over in variants:
                core = cfb_core(hist, mu, sched[wk]["conf"], dict(params(), **over))
                for pl in core["players"]:
                    a = now.get(pl["id"])
                    if a is None or (pl["team"], wk) in skip or pl["pos"] not in ("RB", "WR", "TE"):
                        continue
                    d = derive(pl, W)
                    if d["pts"] < 2.0:
                        continue
                    for g_ in ("all", "mates") if pl["team"] in ab else ("all",):
                        for st, proj, act in (("carries", pl["car"], a["carries"]), ("receptions", pl["rec"], a["receptions"]), ("rush yds", d["rushY"], a["rushing_yards"]),
                                              ("rec yds", d["recY"], a["receiving_yards"]), ("points", d["pts"], actual_pts(a, W))):
                            out.append((name, g_, st, proj, act))
    return out


if __name__ == "__main__":
    res = run([("data/raw/cfb_hist/cfb_weekly_2025.csv", "data/raw/cfb_hist/cfb_games_2025.csv"), ("data/raw/cfb_weekly.csv", "data/raw/cfb_games.csv")])
    names = [v[0] for v in VARIANTS]
    for grp in ("all", "mates"):
        print(f"--- {grp} ---   variants: {' | '.join(names)}")
        for st in ("carries", "receptions", "rush yds", "rec yds", "points"):
            line = []
            for nm in names:
                r = [x for x in res if x[0] == nm and x[1] == grp and x[2] == st]
                line.append(f"{sum(abs(x[3] - x[4]) for x in r) / len(r):.3f}")
            b = [x for x in res if x[0] == "today" and x[1] == grp and x[2] == st]
            print(f"{st:10} n={len(b):5}  {' '.join(line)}  (bias today {sum(x[3] - x[4] for x in b) / max(1.0, sum(x[4] for x in b)) * 100:+.1f}%)", flush=True)

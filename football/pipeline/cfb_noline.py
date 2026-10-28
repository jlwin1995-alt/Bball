"""Line-removal and no-line signals for college availability.

    python -m pipeline.cfb_noline        # needs data/log/cfb_lines_log.csv (weeks 7+), data/raw/cfb_{weekly,games}.csv

College has no injury feed. Props are posted for a team's top few players, so two signals are tested on the weeks the line log covers (7 and 8, graded against the box scores):
  no line:  a player the model projects for real volume (carries + receptions + attempts / 2 >= `opp`) whose team has 2+ priced players that week but who has none himself;
  removed:  a player who had a line the week before, whose team is priced again this week, and who has none now.
For each: the share who actually played (a box-score row), and actual / projected opportunities for those who did, against the players who have a line.
"""
import csv
from collections import defaultdict
from . import config as C
from .cfb_build import schedule, excluded_games
from .cfb_data import read_csv
from .cfb_model import cfb_core, derive, load_rows
from .model import params


def lines_by_week(path="data/log/cfb_lines_log.csv"):
    by = defaultdict(set)
    team_n = defaultdict(set)
    for r in csv.DictReader(open(path, newline="")):
        if r["cons_line"] == "" and r["pp_line"] == "" and r["ud_line"] == "":
            continue
        w = int(r["week"])
        by[w].add(r["player_id"])
        team_n[(w, r["team"])].add(r["player_id"])
    return by, team_n


def run(opp_min=6.0, weeks=(7, 8)):
    rows, games = load_rows("data/raw/cfb_weekly.csv"), read_csv("data/raw/cfb_games.csv")
    sched, skip = schedule(games), excluded_games(games)
    by, team_n = lines_by_week()
    out = []
    for wk in weeks:
        hist = [x for x in rows if x["week"] < wk and (x["team"], int(x["week"])) not in skip]
        now = {x["playerId"]: x for x in rows if x["week"] == wk}
        mu = {}
        for g in sched[wk]["games"]:
            neu = g["neutral"]
            mu[g["awayTeam"]] = dict(opp=g["homeTeam"], site="N" if neu else "@")
            mu[g["homeTeam"]] = dict(opp=g["awayTeam"], site="N" if neu else "vs")
        core = cfb_core(hist, mu, sched[wk]["conf"], params())
        for pl in core["players"]:
            if (pl["team"], wk) in skip or pl["pos"] not in ("RB", "WR", "TE", "QB"):
                continue
            opp = pl["car"] + pl["rec"] + pl["att"] / 2
            if opp < opp_min or len(team_n.get((wk, pl["team"]), ())) < 2:
                continue
            has = pl["id"] in by[wk]
            had_prev = pl["id"] in by.get(wk - 1, set()) and len(team_n.get((wk - 1, pl["team"]), ())) >= 2
            a = now.get(pl["id"])
            used = None if a is None else a["carries"] + a["receptions"] + a["attempts"] / 2
            out.append(dict(wk=wk, has=has, removed=had_prev and not has, played=a is not None, proj=opp, used=used, name=pl["name"], team=pl["team"]))
    return out


def summarize(res, label, f):
    r = [x for x in res if f(x)]
    if not r:
        print(f"{label:34} n=0")
        return
    pl = [x for x in r if x["played"]]
    ratio = sum(x["used"] for x in pl) / max(1e-9, sum(x["proj"] for x in pl)) if pl else float("nan")
    print(f"{label:34} n={len(r):4}  played {len(pl) / len(r) * 100:5.1f}%  actual/projected opps {ratio:.2f}  (mean projected {sum(x['proj'] for x in r) / len(r):.1f})")


if __name__ == "__main__":
    res = run()
    print(f"{len(res)} projected player-games on priced teams (weeks 7-8)")
    summarize(res, "has a line", lambda x: x["has"])
    summarize(res, "no line", lambda x: not x["has"])
    summarize(res, "no line, projected 10+ opps", lambda x: not x["has"] and x["proj"] >= 10)
    summarize(res, "has a line, projected 10+ opps", lambda x: x["has"] and x["proj"] >= 10)
    summarize(res, "line removed (had one last week)", lambda x: x["removed"])
    summarize(res, "had one last week, still has", lambda x: x["has"] and any(True for _ in [0]) and not x["removed"] and x["wk"] == 8)


def teammates(opp_min=10.0, weeks=(7, 8)):
    """Treat no-line players (projected opp_min+ opportunities, team priced) as out: do their teammates' projections improve?"""
    W = C.DEFAULT_SCORING
    rows, games = load_rows("data/raw/cfb_weekly.csv"), read_csv("data/raw/cfb_games.csv")
    sched, skip = schedule(games), excluded_games(games)
    by, team_n = lines_by_week()
    res = []
    for wk in weeks:
        hist = [x for x in rows if x["week"] < wk and (x["team"], int(x["week"])) not in skip]
        now = {x["playerId"]: x for x in rows if x["week"] == wk}
        mu = {}
        for g in sched[wk]["games"]:
            neu = g["neutral"]
            mu[g["awayTeam"]] = dict(opp=g["homeTeam"], site="N" if neu else "@")
            mu[g["homeTeam"]] = dict(opp=g["awayTeam"], site="N" if neu else "vs")
        base = cfb_core(hist, mu, sched[wk]["conf"], params())
        nol = {pl["id"] for pl in base["players"] if pl["car"] + pl["rec"] + pl["att"] / 2 >= opp_min and len(team_n.get((wk, pl["team"]), ())) >= 2 and pl["id"] not in by[wk]}
        teams = {pl["team"] for pl in base["players"] if pl["id"] in nol}
        alt = cfb_core(hist, mu, sched[wk]["conf"], dict(params(), CFB_OUT_IDS=nol, CFB_ABSENT_W=0.0))
        alt_by = {pl["id"]: pl for pl in alt["players"]}
        for pl in base["players"]:
            a = now.get(pl["id"])
            if a is None or pl["id"] in nol or pl["team"] not in teams or pl["pos"] not in ("RB", "WR", "TE") or pl["id"] not in alt_by:
                continue
            q = alt_by[pl["id"]]
            for st, k, ak in (("carries", "car", "carries"), ("receptions", "rec", "receptions")):
                res.append((st, pl[k], q[k], a[ak]))
    return res


if __name__ == "__main__":
    r = teammates()
    for st in ("carries", "receptions"):
        x = [t for t in r if t[0] == st]
        m0, m1 = (sum(abs(t[i] - t[3]) for t in x) / len(x) for i in (1, 2))
        print(f"teammates of a no-line player, {st:10} n={len(x):4}  MAE {m0:.3f} -> {m1:.3f} ({(m1 - m0) / m0 * 100:+.1f}%)  bias {sum(t[1] - t[3] for t in x) / sum(t[3] for t in x) * 100:+.1f}% -> {sum(t[2] - t[3] for t in x) / sum(t[3] for t in x) * 100:+.1f}%")

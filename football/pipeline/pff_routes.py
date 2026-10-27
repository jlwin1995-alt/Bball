"""Routes test: does PFF route participation predict targets better than the model's own target projection?

    python -m pipeline.pff_routes [--seasons 2023 2024 2025]     # needs data/raw/pff_hist/pff_receiving_<s>.csv and data/raw/history/{weekly,schedule,injuries}_<s>.csv

For each player-week (weeks 5+, walk-forward) the PFF projection is  team pass plays x route rate x targets per route:
  team pass plays: his team's average PFF pass plays in earlier games (regressed toward the league average, K_TEAM games);
  route rate: routes / the team's pass plays over the last W games blended with his season (weight RR_RECENT on the recent games), over games he played;
  targets per route: season-to-date targets / routes, shrunk toward the position's rate with K_ROUTES routes.
Compared with the model's projected targets (nfl_core / derive) on the same player-weeks, and with a 50/50 blend. Metric: mean absolute error of targets.
"""
import argparse, csv, os, statistics
from . import config as C
from .analysis import name_key
from .model import load_weekly, nfl_core, derive, params
from .slate import load_csv, matchups
from .backtest import load_inj, INJ

TEAM_FIX = {"ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "SL": "LA", "LAR": "LA", "SD": "LAC", "OAK": "LV", "JAC": "JAX"}


def load_pff(season, raw="data/raw"):
    out = {}
    with open(f"{raw}/pff_hist/pff_receiving_{season}.csv", newline="") as f:
        for r in csv.DictReader(f):
            t = TEAM_FIX.get(r["team"], r["team"])
            out[(name_key(r["player"]), t, int(r["week"]))] = dict(routes=float(r["routes"] or 0), pass_plays=float(r["pass_plays"] or 0),
                                                                       targets=float(r["targets"] or 0), pos=r["position"], slot=float(r["slot_rate"] or 0))
    # a row's pass_plays is the plays HE was on the field for; the team's pass plays are the largest of its players' in that week
    team = {}
    for (n, t, w), v in out.items():
        team[(t, w)] = max(team.get((t, w), 0.0), v["pass_plays"])
    for (n, t, w), v in out.items():
        v["team_pp"] = team[(t, w)]
    return out


def project(pff, key, week, kt=3.0, rr_recent=0.5, win=3, k_routes=40.0, pos_tpr=None, lg_pp=None):
    """PFF-based target projection for one (name, team) before `week`, or None when he has no route history."""
    games = sorted((w, v) for (n, t, w), v in pff.items() if (n, t) == key and w < week and v["team_pp"] > 0)
    games = [(w, v) for w, v in games if v["routes"] > 0]
    if not games:
        return None
    routes_s, pp_s, tg_s = (sum(v[k] for _, v in games) for k in ("routes", "team_pp", "targets"))
    rec = games[-win:]
    rr_season = routes_s / pp_s                       # routes over the TEAM's pass plays in the games he played
    rr_recent_v = sum(v["routes"] for _, v in rec) / max(1.0, sum(v["team_pp"] for _, v in rec))
    rr = rr_recent * rr_recent_v + (1 - rr_recent) * rr_season
    pos = games[-1][1]["pos"]
    tpr = (tg_s + k_routes * pos_tpr.get(pos, 0.12)) / (routes_s + k_routes)
    return rr, tpr


def run(seasons, raw="data/raw", **kw):
    P = params()
    W = C.DEFAULT_SCORING
    res = []
    for season in seasons:
        pff = load_pff(season, raw)
        load_inj(season, raw)
        rows = load_weekly(f"{raw}/history/weekly_{season}.csv")
        sched = load_csv(f"{raw}/history/schedule_{season}.csv")
        by_week = {}
        for r in rows:
            by_week.setdefault(int(r["week"]), []).append(r)
        # team pass plays per game and position target-per-route rates, built week by week
        for wk in range(5, max(by_week) + 1):
            mu = matchups(sched, wk)
            if not mu:
                continue
            hist = [r for x in range(1, wk) for r in by_week.get(x, [])]
            outs = {r["gsis_id"] for r in INJ.get(season, []) if int(float(r["week"] or 0)) == wk and r["report_status"] == "Out"}
            core = nfl_core(hist, mu, None, dict(P, OUT_IDS=outs))
            tm = {}
            for (n, t, w), v in pff.items():
                if w < wk:
                    tm.setdefault(t, {})[w] = max(tm.get(t, {}).get(w, 0.0), v["pass_plays"])
            lg_pp = statistics.mean(v for d in tm.values() for v in d.values()) if tm else 35.0
            pos_t, pos_r = {}, {}
            for (n, t, w), v in pff.items():
                if w < wk:
                    pos_t[v["pos"]] = pos_t.get(v["pos"], 0.0) + v["targets"]; pos_r[v["pos"]] = pos_r.get(v["pos"], 0.0) + v["routes"]
            pos_tpr = {p: pos_t[p] / pos_r[p] for p in pos_t if pos_r[p]}
            act = {(name_key(r["player_display_name"]), r["team"]): r for r in by_week[wk]}
            for pl in core["players"]:
                if pl["pos"] not in ("WR", "TE", "RB"):
                    continue
                key = (name_key(pl["name"]), pl["team"])
                a = act.get(key)
                if a is None:
                    continue
                pj = project(pff, key, wk, pos_tpr=pos_tpr, **kw)
                if pj is None:
                    continue
                games = tm.get(pl["team"], {})
                n = len(games)
                team_pp = (sum(games.values()) + 3.0 * lg_pp) / (n + 3.0) if n else lg_pp
                d = derive(pl, W, P)
                res.append((season, wk, pl["pos"], d["tgt"], team_pp * pj[0] * pj[1], a["targets"]))
    return res


def report(res):
    def mae(f, rows):
        return sum(abs(f(r) - r[5]) for r in rows) / len(rows)
    sel = [r for r in res if r[3] >= 1.0 or r[4] >= 1.0]
    print(f"{len(sel)} player-weeks (model or PFF projects 1+ targets), {len({r[0] for r in sel})} seasons")
    for lab, rows in (("all", sel), ("WR", [r for r in sel if r[2] == "WR"]), ("TE", [r for r in sel if r[2] == "TE"]), ("RB", [r for r in sel if r[2] == "RB"])):
        if rows:
            print(f"{lab:4} n={len(rows):5d}  model {mae(lambda r: r[3], rows):.3f}  PFF routes {mae(lambda r: r[4], rows):.3f}  blend 50/50 {mae(lambda r: .5 * r[3] + .5 * r[4], rows):.3f}"
                  f"  | bias model {sum(r[3] - r[5] for r in rows) / len(rows):+.2f} PFF {sum(r[4] - r[5] for r in rows) / len(rows):+.2f}")
    for s in sorted({r[0] for r in sel}):
        rows = [r for r in sel if r[0] == s]
        print(f"  {s}: model {mae(lambda r: r[3], rows):.3f}  PFF {mae(lambda r: r[4], rows):.3f}  blend {mae(lambda r: .5 * r[3] + .5 * r[4], rows):.3f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, nargs="+", default=[2023, 2024, 2025])
    ap.add_argument("--raw", default="data/raw")
    a = ap.parse_args()
    report(run(a.seasons, a.raw))


def run_full(seasons, raw="data/raw", w=0.5, **kw):
    """The routes blend carried through the whole model: replace each WR/TE/RB's projected targets with (1-w) x the model's + w x the routes projection, re-derive receptions / receiving yards /
    points, and compare with the unblended model on the same player-weeks. -> list of (stat, model projection, blended projection, actual)."""
    from .backtest import actual
    P = params()
    W = C.DEFAULT_SCORING
    out = []
    for season in seasons:
        pff = load_pff(season, raw)
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
            outs = {r["gsis_id"] for r in INJ.get(season, []) if int(float(r["week"] or 0)) == wk and r["report_status"] == "Out"}
            core = nfl_core(hist, mu, None, dict(P, OUT_IDS=outs))
            tm = {}
            for (n, t, w_), v in pff.items():
                if w_ < wk:
                    tm.setdefault(t, {})[w_] = max(tm.get(t, {}).get(w_, 0.0), v["pass_plays"])
            lg_pp = statistics.mean(v for d_ in tm.values() for v in d_.values()) if tm else 35.0
            pos_t, pos_r = {}, {}
            for (n, t, w_), v in pff.items():
                if w_ < wk:
                    pos_t[v["pos"]] = pos_t.get(v["pos"], 0.0) + v["targets"]; pos_r[v["pos"]] = pos_r.get(v["pos"], 0.0) + v["routes"]
            pos_tpr = {p: pos_t[p] / pos_r[p] for p in pos_t if pos_r[p]}
            act = {(name_key(r["player_display_name"]), r["team"]): r for r in by_week[wk]}
            for pl in core["players"]:
                if pl["pos"] not in ("WR", "TE", "RB"):
                    continue
                key = (name_key(pl["name"]), pl["team"])
                a = act.get(key)
                pj = project(pff, key, wk, pos_tpr=pos_tpr, **kw) if a is not None else None
                if a is None or pj is None:
                    continue
                games = tm.get(pl["team"], {})
                n = len(games)
                team_pp = (sum(games.values()) + 3.0 * lg_pp) / (n + 3.0) if n else lg_pp
                d0 = derive(pl, W, P)
                new_tgt = (1 - w) * pl["tgt"] + w * team_pp * pj[0] * pj[1]
                d1 = derive(dict(pl, tgt=new_tgt), W, P)
                if d0["pts"] < 3.0 and d1["pts"] < 3.0:
                    continue
                act_s = actual(a, W)
                for st, k0, ak in (("targets", "tgt", a["targets"]), ("receptions", "rec", a["receptions"]), ("rec yards", "recY", a["receiving_yards"]), ("points", "pts", act_s["pts"])):
                    out.append((st, d0[k0], d1[k0], ak))
    return out


def report_full(res):
    for st in ("targets", "receptions", "rec yards", "points"):
        r = [x for x in res if x[0] == st]
        m0 = sum(abs(x[1] - x[3]) for x in r) / len(r)
        m1 = sum(abs(x[2] - x[3]) for x in r) / len(r)
        b0 = sum(x[1] - x[3] for x in r) / sum(x[3] for x in r) * 100
        b1 = sum(x[2] - x[3] for x in r) / sum(x[3] for x in r) * 100
        print(f"{st:11} n={len(r):5d}  MAE model {m0:.3f} -> with routes blend {m1:.3f} ({(m1 - m0) / m0 * 100:+.1f}%)   bias {b0:+.1f}% -> {b1:+.1f}%")

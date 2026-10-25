"""Situational shares from play-by-play (third down, goal line, red zone) and points allowed by position.

    python -m pipeline.situation            # backtest: do goal-line / red-zone shares improve the touchdown projections?

shares(plays) -> player_id -> dict(car, gl_car, tgt, rz_tgt, gl_tgt, td3_car, td3_tgt, ...) from rows of pbp_slim (down, yardline_100, rusher/receiver).
allowed(weekly_rows, ...) -> defence -> position group -> points / yards / touchdowns allowed per game, with the league mean and rank.
"""
import csv, math, os
from . import config as C
from .model import load_weekly, nfl_core, derive, params
from .slate import load_csv, matchups
from .backtest import load_inj, INJ


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def shares(plays, upto_week=None, season=None):
    """Per-player counts of carries / targets by situation from pbp_slim rows (dicts). Only rows before `upto_week` when given."""
    out = {}
    if plays and "yardline_100" not in plays[0]:
        return out                                              # an older pbp_slim.csv without the situation columns: the next fetch writes them
    for x in plays:
        if upto_week is not None and int(num(x["week"])) >= upto_week:
            continue
        yl, dn = num(x["yardline_100"]), int(num(x["down"]))
        for col, kind in (("rusher_player_id", "car"), ("receiver_player_id", "tgt")):
            pid = x[col]
            if not pid:
                continue
            d = out.setdefault(pid, dict(car=0, gl_car=0, rz_car=0, td3_car=0, tgt=0, gl_tgt=0, rz_tgt=0, td3_tgt=0, rush_td=0, rec_td=0, gl_td=0))
            d[kind] += 1
            if yl <= 5:
                d["gl_" + kind] += 1
            if yl <= 20:
                d["rz_" + kind] += 1
            if dn == 3:
                d["td3_" + kind] += 1
            if kind == "car" and num(x["rush_touchdown"]):
                d["rush_td"] += 1
            if kind == "tgt" and num(x["pass_touchdown"]):
                d["rec_td"] += 1
    return out


def allowed(rows):
    """rows: weekly stat rows (load_weekly). -> {defence: {group: dict(g, pts, yds, td)}} per game, plus league means and ranks."""
    acc, games = {}, {}
    for r in rows:
        g = r.get("position_group")
        if g not in ("QB", "RB", "WR", "TE"):
            continue
        d, wk = r["opponent_team"], r["week"]
        games.setdefault(d, set()).add(wk)
        a = acc.setdefault(d, {}).setdefault(g, dict(pts=0.0, yds=0.0, td=0.0))
        a["pts"] += r.get("fantasy_points_ppr", 0.0)
        a["yds"] += r.get("rushing_yards", 0.0) + r.get("receiving_yards", 0.0) + r.get("passing_yards", 0.0)
        a["td"] += r.get("rushing_tds", 0.0) + r.get("receiving_tds", 0.0) + r.get("passing_tds", 0.0)
    out = {}
    for d, gs in acc.items():
        n = max(1, len(games[d]))
        out[d] = {g: dict(g=n, pts=a["pts"] / n, yds=a["yds"] / n, td=a["td"] / n) for g, a in gs.items()}
    lg = {}
    for g in ("QB", "RB", "WR", "TE"):
        vals = [out[d][g] for d in out if g in out[d]]
        lg[g] = {k: sum(v[k] for v in vals) / len(vals) for k in ("pts", "yds", "td")} if vals else {}
        for k in ("pts",):
            order = sorted((d for d in out if g in out[d]), key=lambda d: -out[d][g][k])        # rank 1 = allows the most
            for i, d in enumerate(order, 1):
                out[d][g]["rank"] = i
                out[d][g]["vs"] = out[d][g]["pts"] / lg[g]["pts"] - 1 if lg[g] else 0.0
    return out, lg


def load_plays(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _ll(lam, y):
    """Bernoulli log-loss of 'at least one touchdown' under a Poisson mean."""
    p = min(0.995, max(0.005, 1 - math.exp(-max(lam, 1e-6))))
    return -(math.log(p) if y >= 1 else math.log(1 - p))


def backtest(seasons=(2023, 2024, 2025), raw="data/raw", kc=40.0, kt=30.0, w=0.5):
    plays = {s: load_plays(f"{raw}/history/pbp_slim_{s}.csv") for s in range(min(seasons) - 1, max(seasons) + 1)}
    P = params()
    W = C.DEFAULT_SCORING
    res = {"rush": [], "rec": []}
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
            outs = {r["gsis_id"] for r in INJ.get(season, []) if int(num(r["week"])) == wk and r["report_status"] == "Out"}
            core = nfl_core(hist, mu, None, dict(P, OUT_IDS=outs))
            earlier = [x for s in plays if s < season for x in plays[s]] + [x for x in plays[season] if int(num(x["week"])) < wk]
            lgs = shares(earlier)
            tot = {k: sum(d[k] for d in lgs.values()) for k in ("car", "gl_car", "tgt", "rz_tgt", "rush_td", "rec_td", "gl_td")}
            gl_td = sum(1 for x in earlier if x["rusher_player_id"] and num(x["yardline_100"]) <= 5 and num(x["rush_touchdown"]))
            rz_td = sum(1 for x in earlier if x["receiver_player_id"] and num(x["yardline_100"]) <= 20 and num(x["pass_touchdown"]))
            r_gl = gl_td / max(1, tot["gl_car"]); r_op = (tot["rush_td"] - gl_td) / max(1, tot["car"] - tot["gl_car"])
            r_rz = rz_td / max(1, tot["rz_tgt"]); r_ro = (tot["rec_td"] - rz_td) / max(1, tot["tgt"] - tot["rz_tgt"])
            f_gl, f_rz = tot["gl_car"] / max(1, tot["car"]), tot["rz_tgt"] / max(1, tot["tgt"])
            mine = shares([x for x in plays[season] if int(num(x["week"])) < wk])
            act = {r["player_id"]: r for r in by_week[wk]}
            for pl in core["players"]:
                a = act.get(pl["id"])
                if a is None:
                    continue
                d = derive(pl, W, P)
                s = mine.get(pl["id"], {})
                if d["car"] >= 3:
                    gf = (s.get("gl_car", 0) + kc * f_gl) / (s.get("car", 0) + kc)
                    alt = d["car"] * (gf * r_gl + (1 - gf) * r_op)
                    res["rush"].append((d["rushTD"], alt, a["rushing_tds"]))
                if d["tgt"] >= 2:
                    rf = (s.get("rz_tgt", 0) + kt * f_rz) / (s.get("tgt", 0) + kt)
                    alt = d["tgt"] * (rf * r_rz + (1 - rf) * r_ro)
                    res["rec"].append((d["recTD"], alt, a["receiving_tds"]))
    for k, rows in res.items():
        n = len(rows)
        print(k, "n", n, "actual TD", sum(r[2] for r in rows), "| model", round(sum(r[0] for r in rows), 1), "| situational", round(sum(r[1] for r in rows), 1))
        for name, f in (("model", lambda r: r[0]), ("situational", lambda r: r[1]), ("blend", lambda r: (1 - w) * r[0] + w * r[1])):
            mse = sum((f(r) - r[2]) ** 2 for r in rows) / n
            ll = sum(_ll(f(r), r[2]) for r in rows) / n
            print(f"  {name:12} MSE {mse:.4f}  log-loss {ll:.4f}")
    return res


if __name__ == "__main__":
    backtest()


def fracs(plays, upto_week, P=None):
    """pid -> (goal-line share of carries, red-zone share of targets), each shrunk toward the league's (SIT_K_CAR / SIT_K_TGT) from plays before `upto_week`."""
    P = P or params()
    out = {}
    for pid, d in shares(plays, upto_week).items():
        out[pid] = ((d["gl_car"] + P["SIT_K_CAR"] * P["SIT_F_GL"]) / (d["car"] + P["SIT_K_CAR"]),
                    (d["rz_tgt"] + P["SIT_K_TGT"] * P["SIT_F_RZ"]) / (d["tgt"] + P["SIT_K_TGT"]))
    return out

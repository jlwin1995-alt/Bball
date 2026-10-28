"""College usage trend: how each rusher's and receiver's role has moved, the last `win` games against the games before them.

Shares come from the CollegeFootballData box scores (no targets or snaps there, so receptions stand in for targets): a player's share of his team's carries, of its receptions and of its
carries + receptions ("opportunity"), as weekly series and as last-`win` against the earlier games (ratio of sums; the whole season when fewer than 2 games precede the window). PFF adds
snap % (offensive snaps over the team's plays that game) and route % (routes over the team's pass plays) where the player matches a PFF row. flag RISING / FALLING when the primary share moves
`move` points or more: reception share for WR / TE, opportunity share for RB. The team's own volume over the same split rides along, so a team-wide change is not read as a role change.
Display only.
"""
import csv, os
from .analysis import name_key
from . import pff_teams


def fl(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def r1(v, n=1):
    return None if v is None else round(v, n)


def pff_weekly(path, key_cols, den):
    """-> {(name_key, pff team, week): value}: numerator column over the largest `den` column in the team-week."""
    if not os.path.exists(path):
        return {}
    rows = list(csv.DictReader(open(path, newline="")))
    team = {}
    for r in rows:
        k = (r["team"], int(r["week"]))
        team[k] = max(team.get(k, 0.0), fl(r[den]))
    return {(name_key(r["player"]), r["team"], int(r["week"])): fl(r[key_cols]) / team[(r["team"], int(r["week"]))] * 100
            for r in rows if team[(r["team"], int(r["week"]))] > 0 and fl(r[key_cols]) > 0}


def usage_trend(rows, conf, raw="data/raw", season=None, win=3, min_g=3, move=5.0):
    """rows: CFBD weekly rows (cfb_model.load_rows). conf: team -> conference. -> list of dicts, largest movers first."""
    team_wk = {}
    for x in rows:
        a = team_wk.setdefault((x["team"], int(x["week"])), dict(car=0.0, rec=0.0))
        a["car"] += x["carries"]; a["rec"] += x["receptions"]
    players = {}
    for x in rows:
        if x["position"] not in ("RB", "WR", "TE", "FB"):
            continue
        players.setdefault(x["playerId"], dict(name=x["player"], pos="RB" if x["position"] == "FB" else x["position"], team=x["team"], weeks=[]))["weeks"].append(x)
    snap_w, route_w, tm = {}, {}, {}
    pre = f"{raw}/pff_hist/ncaa_"
    if season:
        names = {x["team"] for x in rows}
        # PFF strings -> CFBD names for the two files
        off = pre + f"offense_{season}.csv"
        recf = pre + f"receiving_{season}.csv"
        pffteams = {r["team"] for r in csv.DictReader(open(off, newline=""))} if os.path.exists(off) else set()
        tm = pff_teams.cfbd_map(pffteams, names)
        snap_w = pff_weekly(off, "snap_counts_total", "snap_counts_total")
        route_w = pff_weekly(recf, "routes", "pass_plays")
    inv = {v: k for k, v in tm.items()}                       # CFBD name -> PFF string
    out = []
    pct = lambda n, d: None if not d else n / d * 100
    for pid, p in players.items():
        w = sorted(p["weeks"], key=lambda x: x["week"])
        for x in w:
            t = team_wk[(x["team"], int(x["week"]))]
            x["tm_car"], x["tm_rec"] = t["car"], t["rec"]
        if len(w) < min_g or sum(x["carries"] + x["receptions"] for x in w) < 15:
            continue
        sh = lambda seg, k, tk: pct(sum(x[k] for x in seg), sum(x[tk] for x in seg))
        opp = lambda seg: pct(sum(x["carries"] + x["receptions"] for x in seg), sum(x["tm_car"] + x["tm_rec"] for x in seg))
        pf = inv.get(p["team"])
        nk = name_key(p["name"])
        ser = lambda src, seg: [src.get((nk, pf, int(x["week"]))) for x in seg]
        avg = lambda vals: (lambda v: sum(v) / len(v) if v else None)([a for a in vals if a is not None])
        recent, prior = w[-win:], w[:-win]
        ref = prior if len(prior) >= 2 else w
        wk = lambda f: [r1(f([x])) for x in w]
        row = dict(id=pid, name=p["name"], pos=p["pos"], team=p["team"], conf=conf.get(p["team"], ""), g=len(w), vs_season=ref is w, weeks=[int(x["week"]) for x in w],
                   rec_w=wk(lambda s: sh(s, "receptions", "tm_rec")), car_w=wk(lambda s: sh(s, "carries", "tm_car")), opp_w=wk(opp),
                   snap_w=[r1(v) for v in ser(snap_w, w)], route_w=[r1(v) for v in ser(route_w, w)])
        for key, f in (("rec", lambda s: sh(s, "receptions", "tm_rec")), ("car", lambda s: sh(s, "carries", "tm_car")), ("opp", opp),
                       ("snap", lambda s: avg(ser(snap_w, s))), ("route", lambda s: avg(ser(route_w, s)))):
            a, b = f(recent), f(ref)
            row[key + "_r"], row[key + "_b"] = r1(a), r1(b)
            row[key + "_d"] = r1(None if a is None or b is None else a - b)
        tk = "tm_car" if p["pos"] == "RB" else "tm_rec"
        tr = {int(x["week"]): x[tk] for x in recent}
        tb = {int(x["week"]): x[tk] for x in ref}
        row["tm_d"] = r1((sum(tr.values()) / len(tr)) / (sum(tb.values()) / len(tb)) * 100 - 100, 0) if tr and tb and sum(tb.values()) else None
        d = row["opp_d"] if p["pos"] == "RB" else row["rec_d"]
        row["flag"] = "RISING" if d is not None and d >= move else "FALLING" if d is not None and d <= -move else ""
        row["move"] = d
        out.append(row)
    out.sort(key=lambda x: -abs(x["move"] or 0))
    return out

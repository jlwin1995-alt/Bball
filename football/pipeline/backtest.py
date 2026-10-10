"""Walk-forward backtest: for each week W, project using ONLY the weeks before it, then score against what happened.

    python -m pipeline.backtest --season 2025            # needs data/raw/history/weekly_2025.csv  (python -m pipeline.fetch --season 2025)
    python -m pipeline.backtest --season 2025 --write    # also writes site/data/backtest.json

Runs the same nfl_core / derive the site uses. Two naive baselines run alongside - the player's season average and his last three
games - because the number that matters is not "how big is the error" but "is this beating not bothering".
"""
import argparse, json, math, os
from . import config as C
from .model import load_weekly, nfl_core, derive, params, num
from .slate import load_csv, matchups, recorded_wx

# `over` is the projection size below which a player is not counted toward that row's Over % (otherwise every WR's zero completions
# would make the column measure roster composition instead of calibration).
STATS = [("rushY", "Rushing yards", "rushing_yards", 10), ("recY", "Receiving yards", "receiving_yards", 10),
         ("passY", "Passing yards", "passing_yards", 50), ("rec", "Receptions", "receptions", 1),
         ("comp", "Completions", "completions", 5), ("sacks", "Sacks taken", "sacks_suffered", 1), ("pts", "Projected points", None, 0)]


def actual(r, W):
    g = lambda c: r.get(c, 0.0)
    a = dict(rushY=g("rushing_yards"), recY=g("receiving_yards"), passY=g("passing_yards"), rec=g("receptions"),
             comp=g("completions"), sacks=g("sacks_suffered"))
    a["pts"] = (g("rushing_yards") * W["rushYd"] + g("receiving_yards") * W["recYd"] + g("passing_yards") * W["passYd"]
                + g("receptions") * W["rec"] + g("rushing_tds") * W["rushTd"] + g("receiving_tds") * W["recTd"]
                + g("passing_tds") * W["passTd"] + g("passing_interceptions") * W["intr"]
                + (g("rushing_fumbles_lost") + g("receiving_fumbles_lost") + g("sack_fumbles_lost")) * W["fum"]
                + (g("rushing_2pt_conversions") + g("receiving_2pt_conversions") + g("passing_2pt_conversions")) * W["two"])
    return a


def run(season, raw="data/raw", W=None, P=None, from_week=None, min_pts=None, quiet=False):
    W = W or C.DEFAULT_SCORING
    P = P or params()
    from_week = max(2, from_week or C.BACKTEST_FROM_WEEK)
    min_pts = C.BACKTEST_MIN_PTS if min_pts is None else min_pts
    cur = season == C.SEASON
    wpath = f"{raw}/weekly.csv" if cur else f"{raw}/history/weekly_{season}.csv"
    spath = f"{raw}/schedule.csv" if cur else f"{raw}/history/schedule_{season}.csv"
    rows = load_weekly(wpath)
    sched = load_csv(spath)
    by_week = {}
    for r in rows:
        by_week.setdefault(int(r["week"]), []).append(r)
    max_week = max(by_week) if by_week else 0

    models = ("model", "season", "last3")
    acc = {m: {k: dict(ae=0.0, se=0.0, n=0, pred=0.0, act=0.0, over=0, overN=0) for k, *_ in STATS} for m in models}
    pos_acc = {g: dict(n=0, over=0, pred=0.0, act=0.0) for g in ("QB", "RB", "WR", "TE")}
    per_week, last_week = [], from_week - 1

    for wk in range(from_week, max_week + 1):
        if wk not in by_week:
            continue
        mu = matchups(sched, wk)
        if not mu:
            continue
        hist = [r for w in range(1, wk) for r in by_week.get(w, [])]
        if not hist:
            continue
        # weather for a played week is not a forecast: nflverse backfills the wind that blew, so the backtest's weather gain is a ceiling
        core = nfl_core(hist, mu, recorded_wx(sched, wk, P), P)
        seen = {}
        for r in hist:
            seen.setdefault(r["player_id"], []).append(actual(r, W))
        act = {r["player_id"]: actual(r, W) for r in by_week[wk]}
        wk_acc = {m: dict(ae=0.0, n=0) for m in models}
        for pl in core["players"]:
            a = act.get(pl["id"])
            if a is None:
                continue                                   # did not play - not a miss to score
            d = derive(pl, W, P)
            if d["pts"] < min_pts:
                continue
            h = seen.get(pl["id"])
            if not h:
                continue
            avg, last3 = {}, {}
            for k, *_ in STATS:
                avg[k] = sum(x[k] for x in h) / len(h)
                t = h[-3:]
                last3[k] = sum(x[k] for x in t) / len(t)
            pg = pos_acc.get(pl["pos"])
            if pg:
                pg["n"] += 1; pg["pred"] += d["pts"]; pg["act"] += a["pts"]
                if a["pts"] > d["pts"]:
                    pg["over"] += 1
            for k, _, _, over in STATS:
                preds = {"model": d[k], "season": avg[k], "last3": last3[k]}
                for m in models:
                    e = preds[m] - a[k]
                    c = acc[m][k]
                    c["ae"] += abs(e); c["se"] += e * e; c["n"] += 1; c["pred"] += preds[m]; c["act"] += a[k]
                    if preds[m] >= over:
                        c["overN"] += 1
                        if a[k] > preds[m]:
                            c["over"] += 1
                    if k == "pts":
                        wk_acc[m]["ae"] += abs(e); wk_acc[m]["n"] += 1
        if wk_acc["model"]["n"]:
            n = wk_acc["model"]["n"]
            per_week.append(dict(week=wk, n=n, model=round(wk_acc["model"]["ae"] / n, 3), season=round(wk_acc["season"]["ae"] / n, 3),
                                 last3=round(wk_acc["last3"]["ae"] / n, 3)))
            last_week = wk

    table = []
    for k, label, _, over in STATS:
        m, a, b = acc["model"][k], acc["season"][k], acc["last3"][k]
        mm = m["ae"] / m["n"] if m["n"] else 0
        aa = a["ae"] / a["n"] if a["n"] else 0
        bb = b["ae"] / b["n"] if b["n"] else 0
        table.append(dict(k=k, label=label, n=m["n"], mae=round(mm, 3), base=round(aa, 3), last3=round(bb, 3),
                          rmse=round(math.sqrt(m["se"] / m["n"]), 3) if m["n"] else 0,
                          vs=round((mm - aa) / aa * 100, 2) if aa else None, vs3=round((mm - bb) / bb * 100, 2) if bb else None,
                          bias=round((m["pred"] / m["act"] - 1) * 100, 1) if m["act"] else None,
                          over=round(m["over"] / m["overN"] * 100, 1) if m["overN"] >= 100 else None))
    pos = []
    for g, c in pos_acc.items():
        if c["n"] < 100:
            continue
        ov = c["over"] / c["n"] * 100
        band = math.sqrt(0.25 / c["n"]) * 100 * 1.96
        pos.append(dict(pos=g, n=c["n"], over=round(ov, 1), band=round(band, 1),
                        verdict=("projecting LOW" if ov > 50 else "projecting HIGH") if abs(ov - 50) > band else "calibrated",
                        bias=round((c["pred"] / c["act"] - 1) * 100, 1) if c["act"] else None))
    out = dict(season=season, weeks=[from_week, last_week], min_pts=min_pts, table=table, pos=pos, per_week=per_week)
    if not quiet:
        print(f"{season} weeks {from_week}-{last_week}")
        print(f"{'stat':20}{'n':>7}{'model':>9}{'season':>9}{'last3':>9}{'vs seas%':>10}{'vs l3%':>9}{'bias%':>8}{'over%':>8}")
        for t in table:
            print(f"{t['label']:20}{t['n']:>7}{t['mae']:>9.3f}{t['base']:>9.3f}{t['last3']:>9.3f}{t['vs'] or 0:>10.2f}{t['vs3'] or 0:>9.2f}{t['bias'] or 0:>8.1f}{t['over'] if t['over'] is not None else '':>8}")
        for p in pos:
            print(p)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=C.SEASON - 1)
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--from-week", type=int)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out", default="site/data")
    a = ap.parse_args()
    res = run(a.season, a.raw, from_week=a.from_week)
    if a.write:
        os.makedirs(a.out, exist_ok=True)
        json.dump(res, open(f"{a.out}/backtest_{a.season}.json", "w"), separators=(",", ":"))

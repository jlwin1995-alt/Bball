"""PFF roles for the site: alignment and route participation per receiver from PFF's weekly receiving summaries (data/raw/pff_hist/pff_receiving_<season>.csv).

roles(rows, week, win=3) -> (name_key, team) -> dict:  label ("Slot", "Wide", "Inline", "Backfield" or a mix), rr (routes per team pass play over the last `win` games),
sl / wd / il / bk (share of his pass-route snaps by alignment, %), tprr (targets per route), yprr, grade (PFF pass-route grade), g (games), weekly (route rate by week).
refresh_current(season) re-pulls the last two weeks from the API and merges them into the season file (3 calls).
This is display only: the tests in the README found no gain from routes or alignment as model inputs.
"""
import csv, os
from .analysis import name_key

FIX = {"ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}


def load(path):
    try:
        with open(path, newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def label(sl, wd, il, bk):
    """The alignment he is mostly used in: one word when one share is 60%+, two when two shares are 30%+."""
    parts = sorted([("Slot", sl), ("Wide", wd), ("Inline", il), ("Backfield", bk)], key=lambda x: -x[1])
    if parts[0][1] >= 60 or parts[1][1] < 30:
        return parts[0][0]
    return f"{parts[0][0]}/{parts[1][0]}"


def roles(rows, week, win=3, fx=None):
    fx = fx or (lambda t: FIX.get(t, t))
    team_pp = {}
    for r in rows:
        k = (fx(r["team"]), int(r["week"]))
        team_pp[k] = max(team_pp.get(k, 0.0), num(r["pass_plays"]))
    by = {}
    for r in rows:
        w = int(r["week"])
        if w >= week or num(r["routes"]) <= 0:
            continue
        by.setdefault((name_key(r["player"]), fx(r["team"])), []).append((w, r))
    out = {}
    for key, gs in by.items():
        gs.sort(key=lambda x: x[0])
        rec = gs[-win:]
        routes = sum(num(r["routes"]) for _, r in rec)
        snaps = {k: sum(num(r[c]) for _, r in rec) for k, c in (("sl", "slot_snaps"), ("wd", "wide_snaps"), ("il", "inline_snaps"))}
        tot = max(1.0, sum(snaps.values()))
        # a back's routes run from the backfield: PFF counts only slot / wide / inline snaps, the rest of his routes are backfield
        bk_routes = max(0.0, routes - tot) if gs[-1][1]["position"] in ("HB", "FB", "RB") else 0.0
        den = tot + bk_routes
        sl, wd, il, bk = (snaps["sl"] / den * 100, snaps["wd"] / den * 100, snaps["il"] / den * 100, bk_routes / den * 100)
        pp = sum(team_pp.get((key[1], w), 0.0) for w, _ in rec)
        tg_all = sum(num(r["targets"]) for _, r in gs)
        rt_all = sum(num(r["routes"]) for _, r in gs)
        out[key] = dict(label=label(sl, wd, il, bk), rr=round(routes / pp * 100, 1) if pp else None, sl=round(sl), wd=round(wd), il=round(il), bk=round(bk),
                        tprr=round(tg_all / rt_all, 3) if rt_all else None, yprr=round(sum(num(r["yards"]) for _, r in gs) / rt_all, 2) if rt_all else None,
                        grade=round(num(rec[-1][1]["grades_pass_route"]), 1), g=len(gs),
                        weekly=[round(num(r["routes"]) / team_pp[(fx(r["team"]), w)] * 100, 1) if team_pp.get((fx(r["team"]), w)) else None for w, r in gs])
    return out


def refresh_current(season, raw="data/raw", league="nfl"):
    """Re-pull the most recent weeks (the API is cheap: one call per week) and merge them into pff_receiving_<season>.csv. Skips quietly without PFF_API_KEY."""
    from . import pff_hist
    key = os.environ.get("PFF_API_KEY", "").strip()
    if not key:
        print("PFF_API_KEY not set; PFF roles not refreshed")
        return
    path = f"{raw}/pff_hist/pff_receiving_{season}.csv" if league == "nfl" else f"{raw}/pff_hist/{league}_receiving_{season}.csv"
    old = load(path)
    last = max([int(r["week"]) for r in old] or [0])
    new = []
    for wk in range(max(0 if league != "nfl" else 1, last - 1), min(last + 2, 23)):    # the last two weeks on file (late stat corrections) and the next one
        r = pff_hist.get("/v1/facet/receiving/summary", dict(league=league, season=season, week=wk), key)
        if r.status_code != 200:
            print(f"PFF week {wk}: HTTP {r.status_code}")
            continue
        for x in r.json().get("receiving_summary", []):
            new.append({k: (season if k == "season" else wk if k == "week" else x.get(k)) for k in pff_hist.KEEP})
    if not new:
        return
    got = {int(r["week"]) for r in new}
    rows = [r for r in old if int(r["week"]) not in got] + new
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=pff_hist.KEEP)
        w.writeheader()
        w.writerows(rows)
    print(f"PFF roles refreshed: weeks {sorted(got)}, {len(new)} rows")

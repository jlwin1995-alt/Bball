"""Live track record. Projections are appended to data/log/accuracy_log.csv BEFORE the games and never rewritten; once box scores
arrive each logged row is scored against two naive baselines (the player's season average and his last three games, as of that week).

The order matters more than anything else here: a projection reconstructed after the fact silently inherits injury news and depth-chart
changes that were not knowable on Friday. So the log is written at build time and a week that already has rows is never touched.

Each row carries a settings stamp (hash of every knob in config.py). Change a knob and the stamp changes, so the scorecard can tell
one model's record from another's; only the newest stamp counts toward the headline numbers.
A row logged after its team's kickoff is marked late and never scored (a projection made after kickoff is not a prediction).
"""
import csv, datetime as dt, hashlib, json, math, os
from . import config as C
from .model import derive, params, load_weekly
from .backtest import STATS, actual

LOG = "data/log/accuracy_log.csv"
KEYS = [k for k, *_ in STATS]
COLS = (["season", "week", "player_id", "name", "pos", "team", "opp", "kickoff", "logged_at", "late", "stamp", "status",
         "car", "tgt", "att", "rtd", "rectd", "ptd", "int", "fum", "two"]
        + [f"p_{k}" for k in KEYS] + [f"bs_{k}" for k in KEYS] + [f"bl_{k}" for k in KEYS])
# model knobs only: the scoring weights are applied in the browser, and the season/schedule do not change what the model is
STAMP_SKIP = {"SEASON", "NFLVERSE", "OPEN_METEO", "STADIUMS", "STADIUM_BY_NAME", "NFL_COLS", "ET", "PROJECT_WEEK", "DEFAULT_SCORING",
              "BACKTEST_FROM_WEEK", "BACKTEST_MIN_PTS", "SCORECARD_MIN_PTS", "EDGE_MIN", "MIN_ATTEMPTS", "MIN_CARRIES", "MIN_TARGETS", "SEASON_TYPE"}


def stamp(P=None):
    P = P or params()
    knobs = {k: v for k, v in P.items() if k not in STAMP_SKIP}
    return hashlib.sha1(json.dumps(knobs, sort_keys=True, default=str).encode()).hexdigest()[:8]


def read_log(path=LOG):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def log_week(season, week, core, hist_rows, status, kick, P, W=None, path=LOG, now=None):
    """Append this week's projections once. If the week is already there it does nothing at all."""
    if not week:
        return 0
    old = read_log(path)
    if any(r["season"] == str(season) and r["week"] == str(week) for r in old):
        return 0
    W = W or C.DEFAULT_SCORING
    now = now or dt.datetime.now(dt.timezone.utc)
    by_p = {}
    for r in hist_rows:
        by_p.setdefault(r["player_id"], []).append(actual(r, W))
    st = stamp(P)
    new = []
    for pl in core["players"]:
        d = derive(pl, W, P)
        if d["pts"] < C.SCORECARD_MIN_PTS:
            continue
        h = by_p.get(pl["id"], [])
        k0 = kick.get(pl["team"])
        row = dict(season=season, week=week, player_id=pl["id"], name=pl["name"], pos=pl["pos"], team=pl["team"], opp=pl["opp"],
                   kickoff=k0.astimezone(dt.timezone.utc).isoformat(timespec="seconds") if k0 else "",
                   logged_at=now.isoformat(timespec="seconds"), late=int(bool(k0 and now >= k0)), stamp=st,
                   status=status.get(pl["id"], ""), car=round(d["car"], 2), tgt=round(d["tgt"], 2), att=round(d["att"], 2),
                   rtd=round(d["rushTD"], 3), rectd=round(d["recTD"], 3), ptd=round(d["passTD"], 3), int=round(d["int"], 3),
                   fum=round(d["fum"], 3), two=round(d["two"], 4))
        for k in KEYS:
            row[f"p_{k}"] = round(d[k], 3)
            row[f"bs_{k}"] = round(sum(x[k] for x in h) / len(h), 3) if h else ""
            t = h[-3:]
            row[f"bl_{k}"] = round(sum(x[k] for x in t) / len(t), 3) if t else ""
        new.append(row)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    exists = os.path.exists(path) and old
    with open(path, "a" if exists else "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if not exists:
            w.writeheader()
        w.writerows(new)
    return len(new)


def read_tag(n, over, band):
    # a miss can be spotted from ~100 rows, but the word "calibrated" needs 400 before it means more than "no miss seen"
    if n < 100:
        return "too few to read"
    if abs(over - 50) > band:
        return "projecting LOW" if over > 50 else "projecting HIGH"
    return "no miss detected" if n < 400 else "calibrated"


def score(season_rows, live, path=LOG, P=None, W=None):
    """season_rows: this season's weekly rows. live: {(team, week): bool} from analysis.aggregate. -> scorecard dict."""
    W = W or C.DEFAULT_SCORING
    cur = stamp(P)
    log = read_log(path)
    act = {(r["player_id"], int(r["week"])): actual(r, W) for r in season_rows}
    scored, waiting, late, dnp, other = [], 0, 0, 0, 0
    for r in log:
        if r["stamp"] != cur:
            other += 1
            continue
        if str(r["late"]) == "1":
            late += 1
            continue
        wk = int(r["week"])
        if not live.get((r["team"], float(wk))) and not live.get((r["team"], wk)):
            waiting += 1
            continue
        a = act.get((r["player_id"], wk))
        if a is None:
            dnp += 1
            continue
        scored.append((r, a))

    def f(r, k):
        v = r.get(k, "")
        return float(v) if v not in ("", None) else None

    markets, by_pos, by_week = [], {}, {}
    for k, label, _, over in STATS:
        n = ae = bs = bl = pred = actv = ov = ovn = 0
        for r, a in scored:
            p, s, l = f(r, f"p_{k}"), f(r, f"bs_{k}"), f(r, f"bl_{k}")
            if p is None or s is None or l is None:
                continue
            n += 1; ae += abs(p - a[k]); bs += abs(s - a[k]); bl += abs(l - a[k]); pred += p; actv += a[k]
            if p >= over:
                ovn += 1
                ov += a[k] > p
        if not n:
            continue
        o = ov / ovn * 100 if ovn else None
        band = math.sqrt(0.25 / ovn) * 100 * 1.96 if ovn else None
        markets.append(dict(k=k, label=label, n=n, mae=round(ae / n, 3), base=round(bs / n, 3), last3=round(bl / n, 3),
                            vs=round((ae - bs) / bs * 100, 2) if bs else None, vs3=round((ae - bl) / bl * 100, 2) if bl else None,
                            bias=round((pred / actv - 1) * 100, 1) if actv else None, overN=ovn,
                            over=round(o, 1) if o is not None else None, band=round(band, 1) if band else None,
                            read=read_tag(ovn, o, band) if ovn else "too few to read"))
    for r, a in scored:
        p = f(r, "p_pts")
        g = by_pos.setdefault(r["pos"], dict(n=0, ae=0.0, ov=0, pred=0.0, act=0.0))
        g["n"] += 1; g["ae"] += abs(p - a["pts"]); g["ov"] += a["pts"] > p; g["pred"] += p; g["act"] += a["pts"]
        wk = by_week.setdefault(int(r["week"]), dict(n=0, m=0.0, s=0.0, l=0.0))
        wk["n"] += 1; wk["m"] += abs(p - a["pts"]); wk["s"] += abs((f(r, "bs_pts") or 0) - a["pts"]); wk["l"] += abs((f(r, "bl_pts") or 0) - a["pts"])
    pos = []
    for g, c in sorted(by_pos.items()):
        o = c["ov"] / c["n"] * 100
        band = math.sqrt(0.25 / c["n"]) * 100 * 1.96
        pos.append(dict(pos=g, n=c["n"], mae=round(c["ae"] / c["n"], 3), over=round(o, 1), band=round(band, 1),
                        bias=round((c["pred"] / c["act"] - 1) * 100, 1) if c["act"] else None, read=read_tag(c["n"], o, band)))
    weeks = [dict(week=w, n=c["n"], model=round(c["m"] / c["n"], 3), season=round(c["s"] / c["n"], 3), last3=round(c["l"] / c["n"], 3))
             for w, c in sorted(by_week.items())]
    return dict(stamp=cur, scored=len(scored), waiting=waiting, late=late, dnp=dnp, other_models=other,
                logged=len(log), markets=markets, pos=pos, weeks=weeks)

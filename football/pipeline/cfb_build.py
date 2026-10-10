"""College: data/raw/cfb_*.csv -> site/data/cfb/*.json, plus the pre-kickoff log, scorecard and walk-forward backtest.

    python -m pipeline.cfb_build [--raw data/raw] [--out site/data/cfb] [--no-log]
    python -m pipeline.cfb_build --backtest [--season 2025]      # -> backtest_<season>.json (needs that season's cfb_weekly)
"""
import argparse, csv, datetime as dt, hashlib, json, math, os, sys
from . import config as C
from .cfb_model import cfb_core, derive, load_rows, actual_pts, STATS as RAWSTATS
from .cfb_data import read_csv
from .model import params, rnd, nsum
from .scorecard import read_tag

LOG = "data/log/cfb_log.csv"
# market key -> (label, actual field, floor): `floor` is the projection size below which a player is not counted in that row
MKT = [("rushY", "Rushing yards", "rushing_yards", 10), ("recY", "Receiving yards", "receiving_yards", 10), ("rec", "Receptions", "receptions", 1),
       ("passY", "Passing yards", "passing_yards", 50), ("comp", "Completions", "completions", 5), ("pts", "Projected points", None, 4)]
KEYS = [m[0] for m in MKT]
COLS = (["season", "week", "player_id", "name", "pos", "team", "opp", "kickoff", "logged_at", "late", "stamp"]
        + [f"p_{k}" for k in KEYS] + [f"bs_{k}" for k in KEYS] + [f"bl_{k}" for k in KEYS])


def r(x, n=3):
    return None if x is None or x == "" or x != x else rnd(float(x), n)


def stamp(P):
    knobs = {k: (P[k] if k in P else getattr(C, k)) for k in C.CFB_MODEL_KEYS}
    return hashlib.sha1(json.dumps(knobs, sort_keys=True, default=str).encode()).hexdigest()[:8]


def to_utc(s):
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def schedule(games):
    """week -> {matchup, conf, games}. Matchups skip games already played: projecting a team whose game finished forecasts a known result."""
    by = {}
    for g in games:
        try:
            w = int(float(g["week"]))
        except ValueError:
            continue
        s = by.setdefault(w, dict(matchup={}, conf={}, games=[]))
        done = str(g["completed"]).lower() == "true"
        neu = str(g["neutralSite"]).lower() == "true"
        hm, aw = g["homeTeam"], g["awayTeam"]
        s["conf"][hm], s["conf"][aw] = g["homeConference"], g["awayConference"]
        s["games"].append(dict(g, done=done, neutral=neu))
        if done:
            continue
        s["matchup"][aw] = dict(opp=hm, site="N" if neu else "@", start=g["startDate"])
        s["matchup"][hm] = dict(opp=aw, site="N" if neu else "vs", start=g["startDate"])
    return by


def label(team, opp, site):
    if site == "N":                          # a neutral game has no home team: order the names so both sides build the same label
        a, h = (team, opp) if team < opp else (opp, team)
        return f"{a} vs {h}"
    a, h = (opp, team) if site == "vs" else (team, opp)
    return f"{a} @ {h}"


def plain(x):
    return None if x is None else x


def log_week(season, week, core, hist, kick, P, W, path=LOG, now=None):
    old = read_csv(path)
    if any(x["season"] == str(season) and x["week"] == str(week) for x in old):
        return 0
    now = now or dt.datetime.now(dt.timezone.utc)
    by = {}
    for x in hist:
        by.setdefault(x["playerId"], []).append(actuals(x, W))
    st, new = stamp(P), []
    for pl in core["players"]:
        d = derive(pl, W)
        if d["pts"] < C.SCORECARD_MIN_PTS:
            continue
        h = by.get(pl["id"], [])
        k0 = to_utc(kick.get(pl["team"], ""))
        row = dict(season=season, week=week, player_id=pl["id"], name=pl["name"], pos=pl["pos"], team=pl["team"], opp=pl["opp"],
                   kickoff=k0.isoformat(timespec="seconds") if k0 else "", logged_at=now.isoformat(timespec="seconds"),
                   late=int(bool(k0 and now >= k0)), stamp=st)
        for k in KEYS:
            row[f"p_{k}"] = rnd(d[k], 3)
            row[f"bs_{k}"] = rnd(nsum(a[k] for a in h) / len(h), 3) if h else ""
            row[f"bl_{k}"] = rnd(nsum(a[k] for a in h[-3:]) / len(h[-3:]), 3) if h else ""
        new.append(row)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a" if old else "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if not old:
            w.writeheader()
        w.writerows(new)
    return len(new)


def actuals(x, W):
    a = {k: x[act] for k, _, act, _ in MKT if act}
    a["pts"] = actual_pts(x, W)
    return a


def score(rows, played, P, W, path=LOG):
    """played: {(team, week)} whose game has been fetched. -> scorecard dict (current stamp only; late rows never scored)."""
    cur, log = stamp(P), read_csv(path)
    act = {(x["playerId"], int(x["week"])): x for x in rows}
    scored, waiting, late, dnp, other = [], 0, 0, 0, 0
    for x in log:
        if x["stamp"] != cur:
            other += 1
        elif str(x["late"]) == "1":
            late += 1
        elif (x["team"], int(x["week"])) not in played:
            waiting += 1
        elif (x["player_id"], int(x["week"])) not in act:
            dnp += 1
        else:
            scored.append((x, actuals(act[(x["player_id"], int(x["week"]))], W)))
    f = lambda x, k: float(x[k]) if x.get(k) not in ("", None) else None
    markets, by_pos = [], {}
    for k, label_, _, floor in MKT:
        n = ae = bs = bl = pred = actv = ov = ovn = 0
        for x, a in scored:
            p, s, l = f(x, f"p_{k}"), f(x, f"bs_{k}"), f(x, f"bl_{k}")
            if None in (p, s, l):
                continue
            n += 1; ae += abs(p - a[k]); bs += abs(s - a[k]); bl += abs(l - a[k]); pred += p; actv += a[k]
            if p >= floor:
                ovn += 1; ov += a[k] > p
        if n:
            o = ov / ovn * 100 if ovn else None
            band = math.sqrt(0.25 / ovn) * 100 * 1.96 if ovn else None
            markets.append(dict(k=k, label=label_, n=n, mae=rnd(ae / n, 3), base=rnd(bs / n, 3), last3=rnd(bl / n, 3),
                                vs=rnd((ae - bs) / bs * 100, 2) if bs else None, vs3=rnd((ae - bl) / bl * 100, 2) if bl else None,
                                bias=rnd((pred / actv - 1) * 100, 1) if actv else None, over=rnd(o, 1) if o is not None else None,
                                band=rnd(band, 1) if band else None, read=read_tag(ovn, o, band) if ovn else "too few to read"))
    weeks = {}
    for x, a in scored:
        p = f(x, "p_pts")
        g = by_pos.setdefault(x["pos"] or "?", dict(n=0, ae=0.0, ov=0, pred=0.0, act=0.0))
        g["n"] += 1; g["ae"] += abs(p - a["pts"]); g["ov"] += a["pts"] > p; g["pred"] += p; g["act"] += a["pts"]
        w = weeks.setdefault(int(x["week"]), dict(n=0, m=0.0, s=0.0, l=0.0))
        w["n"] += 1; w["m"] += abs(p - a["pts"]); w["s"] += abs((f(x, "bs_pts") or 0) - a["pts"]); w["l"] += abs((f(x, "bl_pts") or 0) - a["pts"])
    pos = []
    for g, c in sorted(by_pos.items()):
        o = c["ov"] / c["n"] * 100
        band = math.sqrt(0.25 / c["n"]) * 100 * 1.96
        pos.append(dict(pos=g, n=c["n"], mae=rnd(c["ae"] / c["n"], 3), over=rnd(o, 1), band=rnd(band, 1),
                        bias=rnd((c["pred"] / c["act"] - 1) * 100, 1) if c["act"] else None, read=read_tag(c["n"], o, band)))
    return dict(stamp=cur, scored=len(scored), waiting=waiting, late=late, dnp=dnp, other_models=other, logged=len(log), markets=markets, pos=pos,
                weeks=[dict(week=w, n=c["n"], model=rnd(c["m"] / c["n"], 3), season=rnd(c["s"] / c["n"], 3), last3=rnd(c["l"] / c["n"], 3)) for w, c in sorted(weeks.items())])


def backtest(rows, games, W, P, from_week=None):
    """Walk-forward: each week is projected from the weeks BEFORE it by the same cfb_core the site runs, then scored."""
    sched = schedule(games)
    from_week = max(2, from_week or C.CFB_BACKTEST_FROM_WEEK)
    wks = sorted({int(x["week"]) for x in rows})
    acc = {k: dict(ae=0.0, se=0.0, n=0, sAe=0.0, lAe=0.0, over=0, pred=0.0, act=0.0) for k in KEYS}
    resid, used, nscored = [], [], 0
    for wk in wks:
        if wk < from_week or wk not in sched:
            continue
        hist = [x for x in rows if x["week"] < wk]
        now = [x for x in rows if x["week"] == wk]
        if len(hist) < 200 or not now:
            continue
        # the schedule says every game of that week is complete now, but the matchups it hands back skip completed games: rebuild them
        mu, conf = {}, sched[wk]["conf"]
        for g in sched[wk]["games"]:
            neu = g["neutral"]
            mu[g["awayTeam"]] = dict(opp=g["homeTeam"], site="N" if neu else "@")
            mu[g["homeTeam"]] = dict(opp=g["awayTeam"], site="N" if neu else "vs")
        core = cfb_core(hist, mu, conf, P)
        actual = {x["playerId"]: x for x in now}
        hist_by = {}
        for x in hist:
            hist_by.setdefault(x["playerId"], []).append(x)
        for pl in core["players"]:
            a = actual.get(pl["id"])
            h = hist_by.get(pl["id"], [])
            if a is None or not h:
                continue                                  # did not play: availability, not accuracy
            d = derive(pl, W)
            pts_h = [actual_pts(x, W) for x in h]
            for k, label_, act, floor in MKT:
                pj = d[k]
                if not pj >= floor:
                    continue
                ac = a[act] if act else actual_pts(a, W)
                c = acc[k]
                c["ae"] += abs(pj - ac); c["se"] += (pj - ac) ** 2; c["n"] += 1; c["over"] += ac > pj; c["pred"] += pj; c["act"] += ac
                series = pts_h if k == "pts" else [x[act] for x in h]
                c["sAe"] += abs(nsum(series) / len(series) - ac)
                c["lAe"] += abs(nsum(series[-3:]) / len(series[-3:]) - ac)
                if k == "pts":
                    nscored += 1
                resid.append((k, pj, ac - pj))
        used.append(wk)
    table = []
    for k, label_, _, _ in MKT:
        c = acc[k]
        mm, sa, l3 = (c["ae"] / c["n"], c["sAe"] / c["n"], c["lAe"] / c["n"]) if c["n"] else (0, 0, 0)
        table.append(dict(k=k, label=label_, n=c["n"], mae=rnd(mm, 3), base=rnd(sa, 3), last3=rnd(l3, 3), rmse=rnd(math.sqrt(c["se"] / c["n"]), 3) if c["n"] else 0,
                          vs=rnd((mm - sa) / sa * 100, 2) if sa else None, vs3=rnd((mm - l3) / l3 * 100, 2) if l3 else None,
                          bias=rnd((c["pred"] / c["act"] - 1) * 100, 1) if c["act"] else None, over=rnd(c["over"] / c["n"] * 100, 1) if c["n"] >= 100 else None))
    # residual spread per market: what the college sigma should be, measured rather than borrowed from the NFL
    spread = []
    for k, label_, _, _ in MKT:
        if k == "pts":
            continue
        mine = sorted((x for x in resid if x[0] == k), key=lambda x: x[1])
        if len(mine) < 60:
            spread.append(dict(label=label_, n=len(mine), a=None, b=None))
            continue
        half = len(mine) // 2

        def fit(arr):
            m = sum(x[2] for x in arr) / len(arr)
            return math.sqrt(sum((x[2] - m) ** 2 for x in arr) / max(1, len(arr) - 1)), sum(x[1] for x in arr) / len(arr)
        (sd_lo, p_lo), (sd_hi, p_hi) = fit(mine[:half]), fit(mine[half:])
        b = (sd_hi - sd_lo) / max(0.001, p_hi - p_lo)
        spread.append(dict(label=label_, n=len(mine), a=rnd(sd_lo - b * p_lo, 3), b=rnd(b, 4)))
    return dict(weeks=used, scored=nscored, thin=len(used) < 3, table=table, spread=spread)


def main(raw="data/raw", out="site/data/cfb", log=True, do_backtest=False, season=None):
    os.makedirs(out, exist_ok=True)
    P, W = params(), C.DEFAULT_SCORING
    season = season or C.SEASON
    cur = season == C.SEASON
    d = raw if cur else os.path.join(raw, "history")
    sfx = "" if cur else f"_{season}"
    if not os.path.exists(f"{d}/cfb_weekly{sfx}.csv"):
        print("no college data yet (set CFBD_API_KEY and run `python -m pipeline.cfb_data`); skipping")
        return 0
    rows = load_rows(f"{d}/cfb_weekly{sfx}.csv")
    games = read_csv(f"{d}/cfb_games{sfx}.csv")
    if do_backtest:
        bt = backtest(rows, games, W, P)
        json.dump(dict(season=season, **bt), open(f"{out}/backtest_{season}.json", "w"), separators=(",", ":"))
        print(f"college backtest {season}: weeks {bt['weeks']}, {bt['scored']} player-games")
        for t in bt["table"]:
            print(f"  {t['label']:20}{t['n']:>7}{t['mae']:>9}{t['base']:>9}{t['last3']:>9}{t['vs']!s:>8}")
        return len(bt["weeks"])
    sched = schedule(games)
    targets = [w for w, s in sched.items() if s["matchup"]]
    if not targets or not rows:
        print("no upcoming FBS games or no player rows; leaving college data as it was")
        return 0
    week = min(targets)
    s = sched[week]
    core = cfb_core(rows, s["matchup"], s["conf"], P)
    meta_in = json.load(open(f"{d}/cfb_meta.json")) if os.path.exists(f"{d}/cfb_meta.json") else {}
    gaps = [w for w in meta_in.get("done", {}) if int(w) < week and meta_in.get("fetched", {}).get(w) != meta_in["done"][w]]
    kick = {t: m["start"] for t, m in s["matchup"].items()}
    proj = []
    for pl in core["players"]:
        x = derive(pl, W)
        proj.append(dict(id=pl["id"], name=pl["name"], pos=pl["pos"], team=pl["team"], conf=pl["conf"], opp=pl["opp"], site=pl["siteTag"], game=label(pl["team"], pl["opp"], pl["siteTag"]),
                         ko=pl["start"] or None, g=pl["g"], car=pl["car"], rec=pl["rec"], att=pl["att"], ypc=r(pl["ypc"], 4), ypr=r(pl["ypr"], 4), ypa=r(pl["ypa"], 4),
                         cmp=r(pl["compRate"], 4), rtd_r=r(pl["rushTdRate"], 5), rectd_r=r(pl["recTdRate"], 5), ptd_r=r(pl["ptdRate"], 5), int_r=r(pl["intRate"], 5),
                         fum_r=r(pl["fumRate"], 6), a_rush=r(pl["a_rush"], 4), a_rec=r(pl["a_rec"], 4), a_pass=r(pl["a_pass"], 4), a_comp=r(pl["a_comp"], 4),
                         a_rtd=r(pl["a_rtd"], 4), a_rectd=r(pl["a_rectd"], 4), a_ptd=r(pl["a_ptd"], 4), tcar=r(pl["tcar"], 1), trec=r(pl["trec"], 1),
                         ry=r(x["rushY"], 2), recy=r(x["recY"], 2), py=r(x["passY"], 2), comp=r(x["comp"], 3), rtd=r(x["rushTD"], 4), rectd=r(x["recTD"], 4),
                         ptd=r(x["passTD"], 4), int=r(x["int"], 4), fum=r(x["fum"], 4), pts=r(x["pts"], 2)))
    proj.sort(key=lambda x: -(x["car"] + x["rec"] + x["att"] * 0.5))
    games_out = []
    for g in s["games"]:
        games_out.append(dict(game=label(g["homeTeam"], g["awayTeam"], "N" if g["neutral"] else "vs"), away=g["awayTeam"], home=g["homeTeam"], neutral=g["neutral"],
                              ko=g["startDate"], done=g["done"], conf=[g["awayConference"], g["homeConference"]]))
    games_out.sort(key=lambda x: x["ko"] or "")
    faces = {}
    for t, m in s["matchup"].items():
        faces.setdefault(m["opp"], []).append(t)
    dr = []
    for t in sorted(core["de"]):
        a = core["de"][t]
        dr.append(dict(team=t, conf=s["conf"].get(t, ""), car=a["car"], ypc=r(a["ry"] / a["car"], 2) if a["car"] else None, rush=r(core["def_rush"].get(t, 1.0)),
                       rec=a["rec"], ypr_a=r(a["recy"] / a["rec"], 2) if a["rec"] else None, recadj=r(core["def_rec"].get(t, 1.0)), pass_=r(core["def_pass"].get(t, 1.0)),
                       comp=r(core["def_comp"].get(t, 1.0)), faces=", ".join(sorted(faces.get(t, [])))))
    json.dump(proj, open(f"{out}/projections.json", "w"), separators=(",", ":"))
    json.dump(games_out, open(f"{out}/games.json", "w"), separators=(",", ":"))
    json.dump(dict(week=week, rows=dr, lg=dict(ypc=r(core["LG_YPC"], 3), ypr=r(core["LG_YPR"], 3), ypa=r(core["LG_YPA"], 3),
                                                 qb=dict(ypc=r(core["rush_base"]["QB"]["ypc"], 2), other=r(core["rush_base"]["OTHER"]["ypc"], 2)))),
              open(f"{out}/matchups.json", "w"), separators=(",", ":"))
    hist = rows
    if gaps:
        print(f"::warning::college history incomplete (weeks {sorted(gaps)} not fully fetched); showing projections but NOT logging them")
    logged = log_week(season, week, core, hist, kick, P, W) if (log and not gaps) else 0
    played = {(x["team"], int(x["week"])) for x in rows}
    sc = score(rows, played, P, W)
    json.dump(sc, open(f"{out}/scorecard.json", "w"), separators=(",", ":"))
    bts = sorted(f[len("backtest_"):-5] for f in os.listdir(out) if f.startswith("backtest_") and f.endswith(".json"))
    json.dump(dict(season=season, week=week, generated=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), stamp=stamp(P), default_scoring=W,
                   players=len(proj), games=len(games_out), history_rows=len(rows), history_gaps=sorted(gaps)[:6], backtests=bts,
                   asof_week=int(max(x["week"] for x in rows))), open(f"{out}/meta.json", "w"), separators=(",", ":"))
    print(f"college week {week}: projected {len(proj)} players in {len(games_out)} games; logged {logged}; scorecard has {sc['scored']} scored")
    return len(proj)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="site/data/cfb")
    ap.add_argument("--no-log", action="store_true")
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--season", type=int)
    a = ap.parse_args()
    main(a.raw, a.out, not a.no_log, a.backtest, a.season)

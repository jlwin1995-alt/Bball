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
from . import cfb_lines, teamstats

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


def excluded_games(games):
    """(team, week) -> reason, for games kept out of the scorecard and backtest: an FCS opponent, or a non-conference Power 4 vs lower-tier game."""
    out = {}
    for g in games:
        try:
            w = int(float(g["week"]))
        except ValueError:
            continue
        hm, aw, hc, ac = g["homeTeam"], g["awayTeam"], g["homeConference"], g["awayConference"]
        why = None
        if C.CFB_SCORE_EXCL_FCS and not (hc in teamstats.FBS_CONFERENCES and ac in teamstats.FBS_CONFERENCES):
            why = "fcs"
        elif C.CFB_SCORE_EXCL_TIER_GAP and hc != ac:
            pw = lambda t, c: c in C.CFB_POWER_CONFS or t in C.CFB_POWER_INDEPENDENTS
            if pw(hm, hc) != pw(aw, ac):
                why = "tier"
        if why:
            out[(hm, w)] = out[(aw, w)] = why
    return out


def roles(rows, proj):
    """Inferred depth role per projected player. CFBD has no depth chart, so this is who has actually been used: over the team's last three
    games, rank each position group by passing attempts (QB), carries (RB), receptions (WR, TE; yards break ties). A starter is rank 1 at QB, RB and TE
    and ranks 1-3 at WR. Returns id -> dict(slot, rank, st, share) where share is the player's fraction of the group's last-three-game volume."""
    wk = {}
    for x in rows:
        wk.setdefault(x["team"], set()).add(int(x["week"]))
    last = {t: sorted(w)[-3:] for t, w in wk.items()}
    use = {}
    for x in rows:
        if int(x["week"]) in last.get(x["team"], ()):
            u = use.setdefault((x["team"], x["playerId"]), [0.0, 0.0, 0.0, 0.0])
            u[0] += x["attempts"]; u[1] += x["carries"]; u[2] += x["receptions"]; u[3] += x["receiving_yards"]
    key = {"QB": lambda u: (u[0], 0), "RB": lambda u: (u[1], 0), "WR": lambda u: (u[2], u[3]), "TE": lambda u: (u[2], u[3])}
    grp = {}
    for p in proj:
        if p["pos"] in key:
            grp.setdefault((p["team"], p["pos"]), []).append(p)
    out = {}
    for (team, pos), ps in grp.items():
        # rank against EVERY player of that position on the team, not only the projected ones
        ids = {x["playerId"] for x in rows if x["team"] == team and x["position"] == pos and int(x["week"]) in last.get(team, ())} | {p["id"] for p in ps}
        scored = sorted(((i, key[pos](use.get((team, i), [0.0] * 4))) for i in ids), key=lambda t: t[1], reverse=True)
        tot = sum(v[0] for _, v in scored) or 0.0
        for rank, (i, v) in enumerate(scored, 1):
            out[i] = dict(slot=f"{pos}{rank}", rank=rank, st=int(rank <= (3 if pos == "WR" else 1) and v[0] > 0), share=r(v[0] / tot, 3) if tot else None)
    return out


def line_specs(out, season):
    """Odds-market specs for college: the NFL fit as the fallback, the college backtest's sigma (a + b x projection) once a market has 300 rows."""
    specs = {}
    for k in C.CFB_ODDS_MARKETS:
        stat, label_, a, b, law = C.ODDS_MARKETS[k]
        specs[stat] = dict(label=label_, a=a, b=b, law=law, src="nfl")
    bp = f"{out}/backtest_{season}.json"
    if os.path.exists(bp):
        for sp in json.load(open(bp)).get("spread", []):
            st = C.CFB_SPREAD_STAT.get(sp["label"])
            if st in specs and sp.get("a") is not None and sp.get("b") is not None and sp["n"] >= 300:
                specs[st].update(a=sp["a"], b=sp["b"], src="college", n=sp["n"])
    return specs


def props_lines(raw, out, season, week=None):
    """cfb_odds.csv + this week's projections -> out/lines.json (consensus, DFS lines). The last PRE-GAME consensus per player and market is also
    kept in data/log/cfb_lines_log.csv (never touched after kickoff) so the leans can be graded once the games are final."""
    from . import lines as L
    L.main(raw, out, odds_file="cfb_odds.csv", meta_file="cfb_odds_meta.json", snapshot=week is not None, extra=dict(specs=line_specs(out, season)),
           log_name="cfb_lines_log.csv", week=week)
    # PrizePicks fantasy-points lines (college): the lean's mean-adjustment and sigma come from the college backtest (none until it has enough rows)
    from . import fp as FP
    cfg = None
    bp = f"{out}/backtest_{season}.json"
    if os.path.exists(bp):
        cfg = json.load(open(bp)).get("pts_fit")
    proj = json.load(open(f"{out}/projections.json")) if os.path.exists(f"{out}/projections.json") else []
    FP.build("data/log/cfb_fp_lines_log.csv", proj, f"{out}/fp_lines.json", cfg)


LEAN_FIELD = {"rushY": "rushing_yards", "recY": "receiving_yards", "rec": "receptions", "passY": "passing_yards"}


VOIDS = "data/log/cfb_void_overrides.csv"


def load_voids(path=VOIDS):
    """data/log/cfb_void_overrides.csv (player_id,week): a player who left in the first half and did not return. PrizePicks voids his MORE picks."""
    try:
        return {(x["player_id"], str(x["week"])) for x in read_csv(path)}
    except FileNotFoundError:
        return set()


def lean_record(rows, played, skip, specs, P, lines_log="data/log/cfb_lines_log.csv", log=LOG, voids=None):
    """Grade the leans: for every logged pre-game consensus line, the model's side is its FROZEN projection (cfb_log, current model, logged before
    kickoff) against the line, and the lean is (projection - line) / sigma. Hit = the model's side won; a result equal to the line is a push and is
    left out. FCS / tier-gap games are left out as in the rest of the college record."""
    cur = stamp(P)
    proj = {(x["player_id"], str(x["week"])): x for x in read_csv(log) if x["stamp"] == cur and str(x["late"]) != "1"}
    act = {(x["playerId"], int(x["week"])): x for x in rows}
    tiers = {t: dict(n=0, hit=0) for t in ("strong", "lean", "none")}
    by_mkt = {}
    graded = waiting = voided = 0
    voids = load_voids() if voids is None else voids
    for x in read_csv(lines_log):
        pr = proj.get((x["player_id"], str(x.get("week", ""))))
        st = x["stat"]
        if not pr or st not in LEAN_FIELD or x.get("cons_line") in ("", None) or pr.get(f"p_{st}") in ("", None):
            continue
        wk = int(x["week"])
        if (x["team"], wk) in skip:
            continue
        a = act.get((x["player_id"], wk))
        if (x["team"], wk) not in played:
            waiting += 1
            continue
        if a is None:
            continue                                            # did not play
        line, m, res = float(x["cons_line"]), float(pr[f"p_{st}"]), a[LEAN_FIELD[st]]
        if res == line or m <= 0:
            continue
        if (x["player_id"], str(x["week"])) in voids and m > line and res < line:
            voided += 1                                         # a MORE pick on a first-half exit that had not cleared its line is void, not a miss
            continue
        sp = specs[st]
        z = (m - line) / max(sp["a"] + sp["b"] * m, max(0.12 * m, 0.5))
        t = "strong" if abs(z) >= 0.5 else "lean" if abs(z) >= 0.25 else "none"
        hit = (res > line) == (m > line)
        graded += 1
        for d in (tiers[t], by_mkt.setdefault((sp["label"], t), dict(n=0, hit=0))):
            d["n"] += 1; d["hit"] += hit
    return dict(graded=graded, waiting=waiting, voided=voided, tiers=[dict(tier=t, **d) for t, d in tiers.items()],
                markets=[dict(label=k[0], tier=k[1], **v) for k, v in sorted(by_mkt.items())])


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
    st = stamp(P)
    # a week is written once PER MODEL: after a settings change the new model logs the week again (only games that have not kicked off count;
    # the rest are flagged late), and the earlier model's rows stay in the log, untouched and excluded from the current record
    if any(x["season"] == str(season) and x["week"] == str(week) and x["stamp"] == st for x in old):
        return 0
    now = now or dt.datetime.now(dt.timezone.utc)
    by = {}
    for x in hist:
        by.setdefault(x["playerId"], []).append(actuals(x, W))
    new = []
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


def score(rows, played, P, W, path=LOG, skip=None):
    """played: {(team, week)} whose game has been fetched. -> scorecard dict (current stamp only; late rows never scored)."""
    cur, log = stamp(P), read_csv(path)
    act = {(x["playerId"], int(x["week"])): x for x in rows}
    skip = skip or {}
    scored, waiting, late, dnp, other, excl = [], 0, 0, 0, 0, 0
    for x in log:
        if x["stamp"] != cur:
            other += 1
        elif (x["team"], int(x["week"])) in skip:
            excl += 1
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
    return dict(stamp=cur, scored=len(scored), waiting=waiting, late=late, dnp=dnp, excluded=excl, other_models=other, logged=len(log), markets=markets, pos=pos,
                weeks=[dict(week=w, n=c["n"], model=rnd(c["m"] / c["n"], 3), season=rnd(c["s"] / c["n"], 3), last3=rnd(c["l"] / c["n"], 3)) for w, c in sorted(weeks.items())])


def backtest(rows, games, W, P, from_week=None):
    """Walk-forward: each week is projected from the weeks BEFORE it by the same cfb_core the site runs, then scored."""
    sched = schedule(games)
    from_week = max(2, from_week or C.CFB_BACKTEST_FROM_WEEK)
    wks = sorted({int(x["week"]) for x in rows})
    acc = {k: dict(ae=0.0, se=0.0, n=0, sAe=0.0, lAe=0.0, over=0, pred=0.0, act=0.0) for k in KEYS}
    skip = excluded_games(games)
    resid, used, nscored, nskip = [], [], 0, 0
    for wk in wks:
        if wk < from_week or wk not in sched:
            continue
        hist = [x for x in rows if x["week"] < wk]
        if C.CFB_TRAIN_EXCL:
            hist = [x for x in hist if (x["team"], int(x["week"])) not in skip]
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
            if (pl["team"], wk) in skip:
                nskip += 1
                continue                                  # FCS / tier-gap game: left out of the record
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
    pa = acc["pts"]
    from . import fp as FP
    pts_fit = FP.fit([(pj, pj + r) for k, pj, r in resid if k == "pts" and pj >= 4])
    return dict(pts_fit=pts_fit, weeks=used, scored=nscored, excluded=nskip, thin=len(used) < 3, table=table, spread=spread, mean_factor=rnd(pa["act"] / pa["pred"], 3) if pa["pred"] else None)


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
    rl = roles(rows, proj)
    for x in proj:
        x["depth"] = rl.get(x["id"])
    games_out = []
    for g in s["games"]:
        games_out.append(dict(game=label(g["homeTeam"], g["awayTeam"], "N" if g["neutral"] else "vs"), away=g["awayTeam"], home=g["homeTeam"], neutral=g["neutral"],
                              ko=g["startDate"], done=g["done"], conf=[g["awayConference"], g["homeConference"]]))
    games_out.sort(key=lambda x: x["ko"] or "")
    cl = cfb_lines.load(raw)
    lines_ts = None
    if cl:
        miss = cfb_lines.attach(games_out, cl["games"])
        lines_ts = cl["ts"]
        got = sum(1 for g in games_out if g.get("spread") is not None or g.get("total") is not None)
        print(f"college lines: {got} of {len(games_out)} games matched" + (f"; unmatched Odds API games: {', '.join(miss[:8])}" if miss else ""))
    faces = {}
    for t, m in s["matchup"].items():
        faces.setdefault(m["opp"], []).append(t)
    dr = []
    for t in sorted(core["de"]):
        a = core["de"][t]
        dr.append(dict(team=t, conf=s["conf"].get(t, ""), car=a["car"], ypc=r(a["ry"] / a["car"], 2) if a["car"] else None, rush=r(core["def_rush"].get(t, 1.0)),
                       rec=a["rec"], ypr_a=r(a["recy"] / a["rec"], 2) if a["rec"] else None, recadj=r(core["def_rec"].get(t, 1.0)), pass_=r(core["def_pass"].get(t, 1.0)),
                       comp=r(core["def_comp"].get(t, 1.0)), faces=", ".join(sorted(faces.get(t, [])))))
    json.dump(teamstats.build(teamstats.cfb_team_games(rows, games), keep=teamstats.fbs_teams(games)), open(f"{out}/teams.json", "w"), separators=(",", ":"))
    json.dump(proj, open(f"{out}/projections.json", "w"), separators=(",", ":"))
    json.dump(games_out, open(f"{out}/games.json", "w"), separators=(",", ":"))
    props_lines(raw, out, season, week)
    json.dump(dict(week=week, rows=dr, lg=dict(ypc=r(core["LG_YPC"], 3), ypr=r(core["LG_YPR"], 3), ypa=r(core["LG_YPA"], 3),
                                                 qb=dict(ypc=r(core["rush_base"]["QB"]["ypc"], 2), other=r(core["rush_base"]["OTHER"]["ypc"], 2)))),
              open(f"{out}/matchups.json", "w"), separators=(",", ":"))
    hist = rows
    if gaps:
        print(f"::warning::college history incomplete (weeks {sorted(gaps)} not fully fetched); showing projections but NOT logging them")
    logged = log_week(season, week, core, hist, kick, P, W) if (log and not gaps) else 0
    played = {(x["team"], int(x["week"])) for x in rows}
    skip = excluded_games(games)
    sc = score(rows, played, P, W, skip=skip)
    sc["leans"] = lean_record(rows, played, skip, line_specs(out, season), P)
    json.dump(sc, open(f"{out}/scorecard.json", "w"), separators=(",", ":"))
    bts = sorted(f[len("backtest_"):-5] for f in os.listdir(out) if f.startswith("backtest_") and f.endswith(".json"))
    json.dump(dict(season=season, week=week, generated=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), stamp=stamp(P), default_scoring=W,
                   players=len(proj), games=len(games_out), lines_ts=lines_ts, mean_factor=C.CFB_MEAN_FACTOR, props_horizon=C.CFB_PROPS_HORIZON_HOURS, history_rows=len(rows), history_gaps=sorted(gaps)[:6], backtests=bts,
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

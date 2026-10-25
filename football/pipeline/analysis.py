"""Efficiency / Usage / Trends / Coverage tables from the weekly box scores (ports of buildEfficiency_ / buildUsage_ / buildTrends_)."""
import csv, math, re
from . import config as C
from .model import num, rnd, nsum

SUM = ["completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered", "sack_yards_lost",
       "passing_air_yards", "passing_yards_after_catch", "passing_first_downs", "passing_epa", "carries", "rushing_yards", "rushing_tds",
       "rushing_first_downs", "rushing_epa", "receptions", "targets", "receiving_yards", "receiving_tds", "receiving_air_yards",
       "receiving_yards_after_catch", "receiving_first_downs", "receiving_epa", "fantasy_points", "fantasy_points_ppr"]


def name_key(s):
    s = re.sub(r"[.'`’]", "", str(s).lower())
    s = re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", s)
    return re.sub(r"\s+", " ", s).strip()


def load_snaps(path):
    m = {}
    try:
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                if r.get("offense_pct", "") != "":
                    m[f"{name_key(r['player'])}|{r['team']}|{r['week']}"] = num(r["offense_pct"])
    except FileNotFoundError:
        pass
    return m


def partial_games(snaps_path, rows, frac=0.5, min_avg=0.35, min_prev=2, pbp_path=None):
    """(player_id, week) -> dict(avg, pct, snaps) for skill players who played well under his usual share of the offence: this game's offensive snap share
    is under `frac` of the average of his previous (up to 3) games, those averaging at least `min_avg` over at least `min_prev` games. It cannot tell an
    injury from a benching in a blowout, so it is a 'partial game', not an 'injury'. Snap counts post about a day after the game."""
    by = {}
    try:
        with open(snaps_path, newline="") as f:
            for r in csv.DictReader(f):
                if r.get("offense_pct", "") != "" and r.get("position") in ("QB", "RB", "FB", "WR", "TE"):
                    by.setdefault((name_key(r["player"]), r["team"]), {})[int(num(r["week"]))] = (num(r["offense_pct"]), int(num(r["offense_snaps"])))
    except FileNotFoundError:
        return {}
    ids = {(name_key(r["player_display_name"]), r["team"], int(num(r["week"]))): r["player_id"] for r in rows}
    last_q, team_h1 = {}, {}
    if pbp_path:
        try:
            with open(pbp_path, newline="") as f:
                for r in csv.DictReader(f):
                    if int(num(r["qtr"])) <= 2:
                        tk = (r["posteam"], int(num(r["week"])))
                        team_h1[tk] = team_h1.get(tk, 0) + 1
                    for col in ("passer_player_id", "rusher_player_id", "receiver_player_id"):
                        if r[col]:
                            k = (r[col], int(num(r["week"])))
                            last_q[k] = max(last_q.get(k, 0), int(num(r["qtr"])))
        except FileNotFoundError:
            pass
    out = {}
    for (nk, team), d in by.items():
        for wk, (pct, n) in d.items():
            prev = [d[w][0] for w in sorted(d) if w < wk][-3:]
            if len(prev) < min_prev:
                continue
            avg = sum(prev) / len(prev)
            pid = ids.get((nk, team, wk))
            if pid and avg >= min_avg and pct < frac * avg:
                q = last_q.get((pid, wk), 0)
                h1 = team_h1.get((team, wk), 0)
                # Is the play void under PrizePicks' reboot rule (a first-half exit with no return; MORE picks only)? The snap counts have no halves and the
                # 2026 participation file is not published, so this is an ESTIMATE:
                #   not void: he touched the ball in the 2nd half, or he took more snaps than his team ran in the whole 1st half (so some must be 2nd-half snaps)
                #   likely void: his last play was in the 1st half and his snaps fit inside it
                #   check: no involvement either way (a player can take snaps without a touch)
                if q >= 3 or (h1 and n > h1):
                    void = "no"
                elif 0 < q <= 2:
                    void = "likely"
                else:
                    void = "check"
                out[(pid, wk)] = dict(avg=round(avg, 2), pct=round(pct, 2), snaps=n, last_q=q, team_h1=h1, void=void)
    return out


def div(n, d):
    return n / d if d else None


def r_(v, p):
    return None if v is None else rnd(v, p)


def aggregate(rows, snaps):
    """-> (players, team_week).  Team-weeks with no recorded offence (game not processed yet) are dropped so they cannot drag rates to zero."""
    team_week = {}
    for r in rows:
        k = (r["team"], r["week"])
        t = team_week.setdefault(k, dict(carries=0.0, targets=0.0, attempts=0.0, air=0.0))
        t["carries"] += r["carries"]; t["targets"] += r["targets"]; t["attempts"] += r["attempts"]; t["air"] += r["receiving_air_yards"]
    live = {k: (t["carries"] + t["targets"] + t["attempts"]) > 0 for k, t in team_week.items()}
    P = {}
    for r in rows:
        team, week = r["team"], r["week"]
        if not live[(team, week)]:
            continue
        pid = r["player_id"]
        if pid not in P:
            P[pid] = dict(id=pid, name=r["player_display_name"], pos=r["position"], grp=r["position_group"], team=team, g=0, snapSum=0.0,
                          snapGames=0, cpoeW=0.0, teamCar=0.0, teamTgt=0.0, teamAir=0.0, weeks=[])
            for c in SUM:
                P[pid][c] = 0.0
        p = P[pid]
        p["team"] = team
        p["g"] += 1
        for c in SUM:
            p[c] += r.get(c, 0.0)
        p["cpoeW"] += r.get("passing_cpoe", 0.0) * r["attempts"]
        tw = team_week[(team, week)]
        p["teamCar"] += tw["carries"]; p["teamTgt"] += tw["targets"]; p["teamAir"] += tw["air"]
        sp = snaps.get(f"{name_key(p['name'])}|{team}|{int(week)}")
        if sp is not None:
            p["snapSum"] += sp; p["snapGames"] += 1
        p["weeks"].append(dict(week=week, ppr=r["fantasy_points_ppr"], yds=r["passing_yards"] + r["rushing_yards"] + r["receiving_yards"],
                               opp=r["attempts"] + r["carries"] + r["targets"], epa=r["passing_epa"] + r["rushing_epa"] + r["receiving_epa"],
                               tgt=r["targets"], car=r["carries"], snap=sp, tm_tgt=tw["targets"], tm_car=tw["carries"]))
    for p in P.values():
        p["weeks"].sort(key=lambda x: x["week"])
    return P, team_week, live


def efficiency(P):
    out = []
    for p in P.values():
        is_qb, is_rush, is_rec = p["attempts"] >= C.MIN_ATTEMPTS, p["carries"] >= C.MIN_CARRIES, p["targets"] >= C.MIN_TARGETS
        if not (is_qb or is_rush or is_rec):
            continue
        db = p["attempts"] + p["sacks_suffered"]
        anya = (p["passing_yards"] + 20 * p["passing_tds"] - 45 * p["passing_interceptions"] - p["sack_yards_lost"]) / db if db else None
        pct = lambda n, d, dp=1: r_(None if not d else n / d * 100, dp)
        row = dict(id=p["id"], name=p["name"], pos=p["pos"], team=p["team"], g=p["g"],
                   snap=r_(p["snapSum"] / p["snapGames"] * 100, 1) if p["snapGames"] else None, ppr_g=r_(div(p["fantasy_points_ppr"], p["g"]), 1))
        if is_qb:
            row.update(att=p["attempts"], ypa=r_(div(p["passing_yards"], p["attempts"]), 2), anya=r_(anya, 2),
                       comp=pct(p["completions"], p["attempts"]), cpoe=r_(div(p["cpoeW"], p["attempts"]), 2),
                       epa_db=r_(div(p["passing_epa"], db), 3), adot=r_(div(p["passing_air_yards"], p["attempts"]), 1),
                       ptd=pct(p["passing_tds"], p["attempts"]), int=pct(p["passing_interceptions"], p["attempts"]), sack=pct(p["sacks_suffered"], db))
        if is_rush:
            row.update(car=p["carries"], ypc=r_(div(p["rushing_yards"], p["carries"]), 2), r1d=pct(p["rushing_first_downs"], p["carries"]),
                       epa_car=r_(div(p["rushing_epa"], p["carries"]), 3), rtd=pct(p["rushing_tds"], p["carries"]))
        if is_rec:
            row.update(tgt=p["targets"], rec=p["receptions"], ypt=r_(div(p["receiving_yards"], p["targets"]), 2),
                       ypr=r_(div(p["receiving_yards"], p["receptions"]), 2), catch=pct(p["receptions"], p["targets"]),
                       radot=r_(div(p["receiving_air_yards"], p["targets"]), 1), yac=r_(div(p["receiving_yards_after_catch"], p["receptions"]), 2),
                       epa_tgt=r_(div(p["receiving_epa"], p["targets"]), 3), racr=r_(div(p["receiving_yards"], p["receiving_air_yards"]), 2),
                       r1dt=pct(p["receiving_first_downs"], p["targets"]))
        out.append(row)
    out.sort(key=lambda x: -(x["ppr_g"] or 0))
    return out


def usage(P):
    out = []
    for p in P.values():
        touches, opp = p["carries"] + p["receptions"], p["carries"] + p["targets"]
        if opp < 5 and p["attempts"] < 10:
            continue
        # air yards go negative when every target is behind the line of scrimmage; floor both sides at zero for the share maths
        air_pos, team_air_pos = max(0.0, p["receiving_air_yards"]), max(0.0, p["teamAir"])
        tgt_share, air_share = div(p["targets"], p["teamTgt"]), div(air_pos, team_air_pos)
        wopr = (1.5 * tgt_share if tgt_share is not None else 0) + (0.7 * air_share if air_share is not None else 0)
        team_opp = p["teamCar"] + p["teamTgt"]
        sh = lambda n, d: r_(None if not d else n / d * 100, 1)
        out.append(dict(id=p["id"], name=p["name"], pos=p["pos"], team=p["team"], g=p["g"],
                        snap=r_(p["snapSum"] / p["snapGames"] * 100, 1) if p["snapGames"] else None,
                        tgt=p["targets"], tgt_g=r_(div(p["targets"], p["g"]), 1), tgt_sh=sh(p["targets"], p["teamTgt"]),
                        air=p["receiving_air_yards"], air_sh=sh(air_pos, team_air_pos), wopr=r_(wopr, 3),
                        car=p["carries"], car_g=r_(div(p["carries"], p["g"]), 1), car_sh=sh(p["carries"], p["teamCar"]),
                        touches=touches, touch_g=r_(div(touches, p["g"]), 1), opp=opp, opp_g=r_(div(opp, p["g"]), 1),
                        opp_sh=sh(opp, team_opp), team_opp=team_opp))
    out.sort(key=lambda x: -(x["opp_sh"] or 0))
    return out


def usage_trend(P, win=None, min_g=3, move=5.0):
    """Week-by-week and rolling usage for rushers and receivers: target share, carry share, share of the team's opportunity (carries + targets) and snap %,
    each as a weekly series, the last-`win` games against the games BEFORE them (ratio of sums; against the whole season when fewer than 2 games precede the window),
    and the team's own volume (targets or carries a game) over the same split, so a team-wide change is not read as a role change.
    flag RISING / FALLING when the primary share moves `move` points or more: target share for WR/TE, opportunity share for RB/FB."""
    win = win or C.ROLLING_WINDOW
    out = []
    pct = lambda n, d: None if not d else n / d * 100
    for p in P.values():
        if p["grp"] not in ("RB", "WR", "TE") and p["pos"] != "FB":
            continue
        w = p["weeks"]
        if len(w) < min_g or (nsum(x["car"] + x["tgt"] for x in w) < 15):
            continue
        sh = lambda seg, num_k, tm_k: pct(nsum(x[num_k] for x in seg), nsum(x[tm_k] for x in seg))
        opp_sh = lambda seg: pct(nsum(x["car"] + x["tgt"] for x in seg), nsum(x["tm_car"] + x["tm_tgt"] for x in seg))
        snap = lambda seg: (lambda v: sum(v) / len(v) * 100 if v else None)([x["snap"] for x in seg if x["snap"] is not None])
        recent, prior = w[-win:], w[:-win]
        ref = prior if len(prior) >= 2 else w                    # too few earlier games to be a baseline: compare with the whole season
        wk_series = lambda f: [r_(f([x]), 1) for x in w]
        row = dict(id=p["id"], name=p["name"], pos=p["pos"], team=p["team"], g=len(w), ref=len(ref) if ref is not w else len(w), vs_season=ref is w,
                   weeks=[int(x["week"]) for x in w],
                   tgt_w=wk_series(lambda s: sh(s, "tgt", "tm_tgt")), car_w=wk_series(lambda s: sh(s, "car", "tm_car")), opp_w=wk_series(opp_sh),
                   snap_w=[r_(x["snap"] * 100, 1) if x["snap"] is not None else None for x in w])
        for key, f in (("tgt", lambda s: sh(s, "tgt", "tm_tgt")), ("car", lambda s: sh(s, "car", "tm_car")), ("opp", opp_sh), ("snap", snap)):
            a, b = f(recent), f(ref)
            row[key + "_r"], row[key + "_b"] = r_(a, 1), r_(b, 1)
            row[key + "_d"] = r_(None if a is None or b is None else a - b, 1)
        # the team's own volume over the same split (targets for receivers, carries for backs)
        tk = "tm_car" if p["grp"] == "RB" else "tm_tgt"
        team_by_week = {}
        for x in w:
            team_by_week[x["week"]] = x[tk]
        tr = [v for k, v in team_by_week.items() if k in {x["week"] for x in recent}]
        tb = [v for k, v in team_by_week.items() if k in {x["week"] for x in ref}]
        row["tm_d"] = r_((sum(tr) / len(tr)) / (sum(tb) / len(tb)) * 100 - 100, 0) if tr and tb and sum(tb) else None
        key = "opp_d" if p["grp"] == "RB" else "tgt_d"
        d = row[key]
        row["flag"] = "RISING" if d is not None and d >= move else "FALLING" if d is not None and d <= -move else ""
        row["move"] = d
        out.append(row)
    out.sort(key=lambda x: -abs(x["move"] or 0))
    return out


def trends(P, win=None):
    win = win or C.ROLLING_WINDOW
    out = []
    mean = lambda arr, f: nsum(f(x) for x in arr) / len(arr) if arr else 0.0
    for p in P.values():
        if p["g"] < 2:
            continue
        w = p["weeks"]
        recent = w[-win:]
        ppr_s, ppr_r = mean(w, lambda x: x["ppr"]), mean(recent, lambda x: x["ppr"])
        yds_s, yds_r = mean(w, lambda x: x["yds"]), mean(recent, lambda x: x["yds"])
        opp_s, opp_r = mean(w, lambda x: x["opp"]), mean(recent, lambda x: x["opp"])
        epa_s, epa_r = mean(w, lambda x: x["epa"]), mean(recent, lambda x: x["epa"])
        if ppr_s < 1 and opp_s < 2:
            continue
        sd = math.sqrt(nsum((x["ppr"] - ppr_s) ** 2 for x in w) / len(w))
        pprs = [x["ppr"] for x in w]
        delta = ppr_r - ppr_s
        delta_pct = delta / ppr_s * 100 if ppr_s else None
        # Form needs scoring AND opportunity moving the same way, and enough games that the window is a subset of the season
        form = "n/a"
        if len(w) > win:
            form = "STEADY"
            opp_d = (opp_r - opp_s) / opp_s if opp_s else 0
            if delta_pct is not None and delta_pct > 15 and opp_d > -0.1:
                form = "HOT"
            elif delta_pct is not None and delta_pct < -15 and opp_d < 0.1:
                form = "COLD"
        out.append(dict(id=p["id"], name=p["name"], pos=p["pos"], team=p["team"], g=p["g"],
                        ppr_g=r_(ppr_s, 1), ppr_r=r_(ppr_r, 1), d=r_(delta, 1), dpct=r_(delta_pct, 1),
                        yds_g=r_(yds_s, 1), yds_r=r_(yds_r, 1), dyds=r_(yds_r - yds_s, 1),
                        opp_g=r_(opp_s, 1), opp_r=r_(opp_r, 1), dopp=r_(opp_r - opp_s, 1),
                        epa_g=r_(epa_s, 2), epa_r=r_(epa_r, 2), sd=r_(sd, 2), cv=r_(sd / ppr_s, 2) if ppr_s else None,
                        floor=r_(min(pprs), 1), ceil=r_(max(pprs), 1), form=form, last=[r_(x, 1) for x in pprs[-8:]]))
    out.sort(key=lambda x: -(x["ppr_r"] or 0))
    return out


def coverage(team_week, live):
    teams = {k[0] for k in team_week}
    n = len(teams)
    by_week = {}
    for k in team_week:
        b = by_week.setdefault(int(k[1]), dict(present=0, recorded=0))
        b["present"] += 1
        if live[k]:
            b["recorded"] += 1
    rows = []
    for wk in sorted(by_week):
        b = by_week[wk]
        pct = b["recorded"] / n if n else 0
        missing = n - b["recorded"]
        status = "complete" if pct >= 0.95 else (f"in progress - {missing} teams not in yet" if pct >= 0.5 else f"early - only {b['recorded']} of {n} teams in")
        rows.append(dict(week=wk, teams=b["recorded"], league=n, pct=int(rnd(pct * 100, 0)), games=int(rnd(b["recorded"] / 2, 0)), pending=missing, status=status))
    return rows

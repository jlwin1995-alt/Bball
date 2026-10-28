"""College projection for one week. A line-for-line port of cfbCore_ from the sheet.

Honest differences from the NFL model (all inherited from what CollegeFootballData reports):
  * no targets: receptions are projected directly, receiving touchdowns are per reception, and "Rec %" is a share of receptions;
  * no 2-point conversions, no sack projection, no injury report, no weather;
  * defence strengths are applied in full (no measured damping yet: college has a 6x larger sample, so that is a job for the backtest);
  * a college QB's rushing line has his sacks subtracted from it (the NCAA charges a sack as a rushing attempt), so quarterbacks regress
    toward what quarterbacks do, not toward ball carriers.
"""
from . import config as C
from .model import regress, clamp_to, td_adj, rnd, nsum


def js_order(d):
    """Keys in JavaScript object order: integer-like ids ascending numerically, everything else in insertion order. The sheet's float sums
    visit players this way, and a 1e-15 difference can flip a one-decimal rounding."""
    ks = list(d)
    ints = sorted((k for k in ks if k.isdigit() and (k == "0" or not k.startswith("0"))), key=int)
    return ints + [k for k in ks if not (k.isdigit() and (k == "0" or not k.startswith("0")))]


def is_qb(p):
    return str(p["pos"] or "").upper().startswith("QB") or p["attempts"] >= C.CFB_QB_MIN_ATT or p["passing_yards"] >= 40


def load_rows(path):
    import csv
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            for k in ("week", "carries", "rushing_yards", "rushing_tds", "receptions", "receiving_yards", "receiving_tds", "completions", "attempts",
                      "passing_yards", "passing_tds", "interceptions", "fumbles_lost"):
                r[k] = float(r[k] or 0)
            out.append(r)
    return out


STATS = ["carries", "rushing_yards", "rushing_tds", "receptions", "receiving_yards", "receiving_tds", "completions", "attempts", "passing_yards",
         "passing_tds", "interceptions", "fumbles_lost"]


def cfb_core(rows, matchup, conf, P):
    """rows: weekly rows to learn from. matchup: team -> {opp, site ('vs' | '@' | 'N'), start}. conf: team -> conference."""
    cap = P["DEF_ADJ_CAP"] or 0.15
    lg = dict(car=0.0, ry=0.0, rec=0.0, recy=0.0, att=0.0, py=0.0, rtd=0.0, rectd=0.0, fum=0.0, comp=0.0)
    de, team_tot, team_weeks = {}, {}, {}
    qb_ids, lg_nq = set(), [0.0, 0.0]
    if P.get("CFB_DEF_EXCL_QB", C.CFB_DEF_EXCL_QB):
        att_by = {}
        for r in rows:
            a = att_by.setdefault(r["playerId"], [0.0, 0.0, ""])
            a[0] += r["attempts"]; a[1] += r["passing_yards"]; a[2] = r["position"]
        qb_ids = {i for i, a in att_by.items() if is_qb(dict(pos=a[2], attempts=a[0], passing_yards=a[1]))}
    for r in rows:
        t, w = r["team"], r["week"]
        lg["car"] += r["carries"]; lg["ry"] += r["rushing_yards"]; lg["rec"] += r["receptions"]; lg["recy"] += r["receiving_yards"]
        lg["att"] += r["attempts"]; lg["py"] += r["passing_yards"]; lg["rtd"] += r["rushing_tds"]; lg["rectd"] += r["receiving_tds"]
        lg["fum"] += r["fumbles_lost"]; lg["comp"] += r["completions"]
        d = r["opponent"]
        if d:
            a = de.setdefault(d, dict(car=0.0, ry=0.0, rec=0.0, recy=0.0, att=0.0, py=0.0, comp=0.0))
            if r["playerId"] not in qb_ids:      # CFB_DEF_EXCL_QB: rate the defence on running backs only (a QB's line carries his sacks as negative yards)
                a["car"] += r["carries"]; a["ry"] += r["rushing_yards"]; lg_nq[0] += r["carries"]; lg_nq[1] += r["rushing_yards"]
            a["rec"] += r["receptions"]; a["recy"] += r["receiving_yards"]
            a["att"] += r["attempts"]; a["py"] += r["passing_yards"]; a["comp"] += r["completions"]
        tt = team_tot.setdefault(t, dict(car=0.0, rec=0.0, att=0.0))
        team_weeks.setdefault(t, set()).add(w)
        tt["car"] += r["carries"]; tt["rec"] += r["receptions"]; tt["att"] += r["attempts"]

    LG_YPC = lg["ry"] / lg["car"] if lg["car"] else 4.5
    LG_YPR = lg["recy"] / lg["rec"] if lg["rec"] else 11.5
    LG_YPA = lg["py"] / lg["att"] if lg["att"] else 7.5
    LG_RUSH_TD = lg["rtd"] / lg["car"] if lg["car"] else 0.03
    LG_REC_TD = lg["rectd"] / lg["rec"] if lg["rec"] else 0.08
    LG_FUM = lg["fum"] / (lg["car"] + lg["rec"] + lg["att"]) if (lg["car"] + lg["rec"] + lg["att"]) else 0.006
    LG_COMP = lg["comp"] / lg["att"] if lg["att"] else 0.62

    def_rush, def_rec, def_pass, def_comp = {}, {}, {}, {}
    DEF_LG_YPC = (lg_nq[1] / lg_nq[0]) if (qb_ids and lg_nq[0]) else LG_YPC       # the league figure a defence is compared with must be on the same footing
    for d, a in de.items():
        if a["car"]:
            def_rush[d] = clamp_to(regress((a["ry"] / a["car"]) / DEF_LG_YPC, a["car"], C.CFB_K_DEF_RUSH), cap)
        if a["rec"]:
            def_rec[d] = clamp_to(regress((a["recy"] / a["rec"]) / LG_YPR, a["rec"], C.CFB_K_DEF_REC), cap)
        if a["att"]:
            def_pass[d] = clamp_to(regress((a["py"] / a["att"]) / LG_YPA, a["att"], C.CFB_K_DEF_PASS), cap)
            def_comp[d] = clamp_to(regress((a["comp"] / a["att"]) / LG_COMP, a["att"], C.CFB_K_DEF_PASS), cap * P["CATCH_CAP_FRACTION"])

    lg_team = dict(car=0.0, rec=0.0, att=0.0)
    tot_games = 0
    for t in team_tot:
        tot_games += len(team_weeks[t])
        for k in lg_team:
            lg_team[k] += team_tot[t][k]
    for k in lg_team:
        lg_team[k] = lg_team[k] / tot_games if tot_games else 0.0
    team_base = {}
    for t in team_tot:
        n = len(team_weeks[t]) or 1
        w = n / (n + C.CFB_K_TEAM_VOL)
        team_base[t] = {k: (team_tot[t][k] / n) * w + lg_team[k] * (1 - w) for k in ("car", "rec", "att")}

    win = max(1, int(P["ROLLING_WINDOW"] or 3))
    PL = {}
    for r in rows:
        pid = r["playerId"]
        if pid not in PL:
            PL[pid] = dict(name=r["player"], pos=r["position"] or "", team=r["team"], conf=r["conference"] or "", g=0, weeks=[], **{c: 0.0 for c in STATS})
        p = PL[pid]
        p["team"] = r["team"]
        p["g"] += 1
        for c in STATS:
            p[c] += r[c]
        p["weeks"].append(dict(week=r["week"], car=r["carries"], rec=r["receptions"], att=r["attempts"]))

    # rushing baselines per group, from this season's own data, so they track whatever the sack environment is doing
    grp = {"QB": dict(car=0.0, ry=0.0, td=0.0), "OTHER": dict(car=0.0, ry=0.0, td=0.0)}
    for p in (PL[k] for k in js_order(PL)):
        g = grp["QB" if is_qb(p) else "OTHER"]
        g["car"] += p["carries"]; g["ry"] += p["rushing_yards"]; g["td"] += p["rushing_tds"]
    rush_base = {k: dict(ypc=a["ry"] / a["car"] if a["car"] >= 200 else LG_YPC, td=a["td"] / a["car"] if a["car"] >= 200 else LG_RUSH_TD) for k, a in grp.items()}

    # CFB_QB_TIERS: quarterbacks regress toward their own kind. A pocket passer's rushing line is mostly sacks; a dual-threat's is designed runs, so one
    # blended baseline pulls the first up and the second down. Tier = carries per game so far (pocket < 3, mid 3-8, mobile 8+), each with its own
    # baseline when the tier has enough carries to say anything.
    def qb_tier(p):
        c = p["carries"] / max(p["g"], 1)
        return "pocket" if c < 3 else ("mid" if c < 8 else "mobile")
    use_tiers = P.get("CFB_QB_TIERS", C.CFB_QB_TIERS)
    if use_tiers:
        tg = {t: dict(car=0.0, ry=0.0, td=0.0) for t in ("pocket", "mid", "mobile")}
        for p in PL.values():
            if is_qb(p):
                g = tg[qb_tier(p)]
                g["car"] += p["carries"]; g["ry"] += p["rushing_yards"]; g["td"] += p["rushing_tds"]
        for t, a in tg.items():
            rush_base["QB_" + t] = dict(ypc=a["ry"] / a["car"] if a["car"] >= 150 else rush_base["QB"]["ypc"], td=a["td"] / a["car"] if a["car"] >= 150 else rush_base["QB"]["td"])
    qb_prior = P.get("CFB_QB_PRIOR_CAR") or C.CFB_PRIOR_CAR

    def blend(p, k):
        w = sorted(p["weeks"], key=lambda x: x["week"])
        season = nsum(x[k] for x in w) / len(w)
        if len(w) < win:
            return season
        rec = w[-win:]
        rw = P["RECENT_WEIGHT_ATT"] if k == "att" else P["RECENT_WEIGHT"]
        return rw * (nsum(x[k] for x in rec) / len(rec)) + (1 - rw) * season

    want_conf = str(C.CFB_CONFERENCE or "").strip().upper()
    ids = []
    for i in js_order(PL):
        p = PL[i]
        if p["team"] not in matchup:
            continue
        if want_conf and str(p["conf"] or conf.get(p["team"]) or "").upper() != want_conf:
            continue
        if p["carries"] + p["receptions"] + p["attempts"] >= (C.CFB_MIN_OPPS or 12):
            ids.append(i)
    # Everyone on a team's roster share the team's volume, not only the players selected for projection: scaling the selected few up to the whole
    # team's baseline hands them the receptions that real depth-chart players below the minimum really take (CFB_SCALE_ALL; see the Backtest notes).
    pool = [i for i in js_order(PL) if PL[i]["team"] in matchup] if P.get("CFB_SCALE_ALL", C.CFB_SCALE_ALL) else ids
    raw = {i: dict(car=blend(PL[i], "car"), rec=blend(PL[i], "rec"), att=blend(PL[i], "att")) for i in pool}
    qb_fixed = P.get("CFB_QB_FIXED_CARRIES", C.CFB_QB_FIXED_CARRIES)

    # CFB_CONCENTRATE_ATT (the NFL model's participation weighting): a team's attempts are shared among everyone who might throw them, which divides
    # them too far, because a backup who threw in one game of six still counts as a full passer. Each player's contribution to the DENOMINATOR is weighted
    # by how often he has actually thrown in the team's last PLAY_WINDOW games; his own projection stays the conditional one (what he does in a game he plays).
    p_play = {}
    if P.get("CFB_CONCENTRATE_ATT", C.CFB_CONCENTRATE_ATT):
        win_p, prior_p = max(1, int(P["PLAY_WINDOW"])), P.get("CFB_PLAY_PRIOR", C.CFB_PLAY_PRIOR)
        seen_w = {}
        for r in rows:
            if r["team"] and r["week"]:
                seen_w.setdefault(r["team"], set()).add(r["week"])
        recent_w = {t: sorted(ws)[-win_p:] for t, ws in seen_w.items()}
        for i in pool:
            want = recent_w.get(PL[i]["team"], [])
            if not want:
                continue
            seen = {x["week"]: x for x in PL[i]["weeks"]}
            hits = sum(1 for w in want if w in seen and seen[w]["att"] >= 5)
            p_play[i] = (hits + prior_p * 0.5) / (len(want) + prior_p)
    # CFB_ABSENT_GAMES / CFB_ABSENT_W: college has no injury feed, so a player who played earlier but has no box-score row in his team's last N games is treated as probably out: his share of
    # the team's carries and receptions counts for ABSENT_W (0 = not at all) in the denominator, so the men who have been playing take the volume. His own projection is unchanged.
    absent_w = {}
    n_abs = int(P.get("CFB_ABSENT_GAMES", 0) or 0)
    if n_abs:
        tw = {}
        for r in rows:
            if r["team"] and r["week"]:
                tw.setdefault(r["team"], set()).add(r["week"])
        last_n = {t: sorted(ws)[-n_abs:] for t, ws in tw.items() if len(ws) > n_abs}
        for i in pool:
            want = last_n.get(PL[i]["team"])
            if want and len(PL[i]["weeks"]) >= 2 and not any(x["week"] in want for x in PL[i]["weeks"]):
                absent_w[i] = float(P.get("CFB_ABSENT_W", 0.0))
    scale = {}
    for t in team_base:
        scale[t] = dict(car=1.0, rec=1.0, att=1.0)
        for k in ("car", "rec", "att"):
            # CFB_QB_FIXED_CARRIES: a quarterback's carries are his own style (and his sacks), not a share of a fixed pie, so the rescale divides the
            # pie among the other ball carriers: team carries minus what the QBs are expected to take
            if k == "car" and qb_fixed:
                qb_tot = nsum(raw[i]["car"] for i in pool if PL[i]["team"] == t and is_qb(PL[i]))
                tot = nsum(raw[i]["car"] * absent_w.get(i, 1.0) for i in pool if PL[i]["team"] == t and not is_qb(PL[i]))
                if tot > 0:
                    scale[t]["car"] = max(1 - C.CFB_TEAM_SCALE_CAP, min(1 + C.CFB_TEAM_SCALE_CAP, max(team_base[t]["car"] - qb_tot, 0.0) / tot))
                continue
            tot = nsum(raw[i][k] * (p_play.get(i, 1.0) if k == "att" else absent_w.get(i, 1.0)) for i in pool if PL[i]["team"] == t)
            if tot > 0:
                scale[t][k] = max(1 - C.CFB_TEAM_SCALE_CAP, min(1 + C.CFB_TEAM_SCALE_CAP, team_base[t][k] / tot))
    # team projected volume after the rescale, so a share adds to 100% across the team (receiving share is a share of RECEPTIONS)
    team_car, team_rec = {}, {}
    for i in ids:
        t = PL[i]["team"]
        team_car[t] = team_car.get(t, 0.0) + raw[i]["car"] * (1.0 if (qb_fixed and is_qb(PL[i])) else scale[t]["car"])
        team_rec[t] = team_rec.get(t, 0.0) + raw[i]["rec"] * scale[t]["rec"]

    out = []
    for i in ids:
        p = PL[i]
        m = matchup[p["team"]]
        car, rec, att = (raw[i][k] * scale[p["team"]][k] for k in ("car", "rec", "att"))
        if qb_fixed and is_qb(p):
            car = raw[i]["car"]
        if car < 0.5 and rec < 0.5 and att < 1:
            continue
        dr, dc, dp, dcomp = def_rush.get(m["opp"], 1.0), def_rec.get(m["opp"], 1.0), def_pass.get(m["opp"], 1.0), def_comp.get(m["opp"], 1.0)
        site = 1.02 if m["site"] == "vs" else (1.0 if m["site"] == "N" else 0.98)
        rb = rush_base[("QB_" + qb_tier(p) if use_tiers else "QB") if is_qb(p) else "OTHER"]
        pc = qb_prior if is_qb(p) else C.CFB_PRIOR_CAR
        out.append(dict(
            id=i, name=p["name"], pos=p["pos"], team=p["team"], conf=p["conf"] or conf.get(p["team"]) or "", opp=m["opp"], siteTag=m["site"], start=m.get("start") or "",
            g=p["g"], car=rnd(car, 1), rec=rnd(rec, 1), att=rnd(att, 1),
            ypc=(p["rushing_yards"] + pc * rb["ypc"]) / (p["carries"] + pc),
            ypr=(p["receiving_yards"] + C.CFB_PRIOR_REC * LG_YPR) / (p["receptions"] + C.CFB_PRIOR_REC),
            ypa=(p["passing_yards"] + C.CFB_PRIOR_ATT * LG_YPA) / (p["attempts"] + C.CFB_PRIOR_ATT),
            compRate=(p["completions"] + C.CFB_PRIOR_ATT * LG_COMP) / (p["attempts"] + C.CFB_PRIOR_ATT),
            rushTdRate=(p["rushing_tds"] + pc * rb["td"]) / (p["carries"] + pc),
            recTdRate=(p["receiving_tds"] + C.CFB_PRIOR_REC * LG_REC_TD) / (p["receptions"] + C.CFB_PRIOR_REC),
            ptdRate=(p["passing_tds"] + C.CFB_PRIOR_ATT * P["LG_PASS_TD"]) / (p["attempts"] + C.CFB_PRIOR_ATT),
            intRate=(p["interceptions"] + C.CFB_PRIOR_ATT * P["LG_INT"]) / (p["attempts"] + C.CFB_PRIOR_ATT),
            # CFBD reports fumbles lost without saying how they happened, so one rate covers carries, catches and dropbacks alike
            fumRate=(p["fumbles_lost"] + P["PRIOR_FUMBLES"] * LG_FUM) / (p["carries"] + p["receptions"] + p["attempts"] + P["PRIOR_FUMBLES"]),
            a_rush=dr * site, a_rec=dc * site, a_pass=dp * site, a_comp=dcomp,
            a_rtd=td_adj(dr, P["LAMBDA_RUSH_TD"]) * site, a_rectd=td_adj(dc, P["LAMBDA_REC_TD"]) * site, a_ptd=td_adj(dp, P["LAMBDA_PASS_TD"]) * site,
            tcar=team_car.get(p["team"], 0.0), trec=team_rec.get(p["team"], 0.0)))
    return dict(players=out, def_rush=def_rush, def_rec=def_rec, def_pass=def_pass, def_comp=def_comp, de=de, LG_YPC=LG_YPC, LG_YPR=LG_YPR, LG_YPA=LG_YPA,
                rush_base=rush_base)


def derive(pl, W):
    """Stat line from a core record. Volumes are already rounded to one decimal, as displayed."""
    car, rec, att = pl["car"], pl["rec"], pl["att"]
    rush_y = car * pl["ypc"] * pl["a_rush"]
    rec_y = rec * pl["ypr"] * pl["a_rec"]
    pass_y = att * pl["ypa"] * pl["a_pass"]
    rush_td = car * pl["rushTdRate"] * pl["a_rtd"]
    rec_td = rec * pl["recTdRate"] * pl["a_rectd"]
    pass_td = att * pl["ptdRate"] * pl["a_ptd"]
    ints = att * pl["intRate"]
    fum = (car + rec + att) * pl["fumRate"]
    comp = att * pl["compRate"] * pl["a_comp"]
    pts = (rush_y * W["rushYd"] + rec_y * W["recYd"] + pass_y * W["passYd"] + rec * W["rec"] + rush_td * W["rushTd"] + rec_td * W["recTd"]
           + pass_td * W["passTd"] + ints * W["intr"] + fum * W["fum"])
    return dict(car=car, rec=rec, att=att, rushY=rush_y, recY=rec_y, passY=pass_y, comp=comp, rushTD=rush_td, recTD=rec_td, passTD=pass_td,
                td=rush_td + rec_td, int=ints, fum=fum, pts=pts)


def actual_pts(r, W):
    return (r["rushing_yards"] * W["rushYd"] + r["receiving_yards"] * W["recYd"] + r["passing_yards"] * W["passYd"] + r["receptions"] * W["rec"]
            + r["rushing_tds"] * W["rushTd"] + r["receiving_tds"] * W["recTd"] + r["passing_tds"] * W["passTd"] + r["interceptions"] * W["intr"]
            + r["fumbles_lost"] * W["fum"])

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
    for r in rows:
        t, w = r["team"], r["week"]
        lg["car"] += r["carries"]; lg["ry"] += r["rushing_yards"]; lg["rec"] += r["receptions"]; lg["recy"] += r["receiving_yards"]
        lg["att"] += r["attempts"]; lg["py"] += r["passing_yards"]; lg["rtd"] += r["rushing_tds"]; lg["rectd"] += r["receiving_tds"]
        lg["fum"] += r["fumbles_lost"]; lg["comp"] += r["completions"]
        d = r["opponent"]
        if d:
            a = de.setdefault(d, dict(car=0.0, ry=0.0, rec=0.0, recy=0.0, att=0.0, py=0.0, comp=0.0))
            a["car"] += r["carries"]; a["ry"] += r["rushing_yards"]; a["rec"] += r["receptions"]; a["recy"] += r["receiving_yards"]
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
    for d, a in de.items():
        if a["car"]:
            def_rush[d] = clamp_to(regress((a["ry"] / a["car"]) / LG_YPC, a["car"], C.CFB_K_DEF_RUSH), cap)
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
    for p in PL.values():
        g = grp["QB" if is_qb(p) else "OTHER"]
        g["car"] += p["carries"]; g["ry"] += p["rushing_yards"]; g["td"] += p["rushing_tds"]
    rush_base = {k: dict(ypc=a["ry"] / a["car"] if a["car"] >= 200 else LG_YPC, td=a["td"] / a["car"] if a["car"] >= 200 else LG_RUSH_TD) for k, a in grp.items()}

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
    for i, p in PL.items():
        if p["team"] not in matchup:
            continue
        if want_conf and str(p["conf"] or conf.get(p["team"]) or "").upper() != want_conf:
            continue
        if p["carries"] + p["receptions"] + p["attempts"] >= (C.CFB_MIN_OPPS or 12):
            ids.append(i)
    raw = {i: dict(car=blend(PL[i], "car"), rec=blend(PL[i], "rec"), att=blend(PL[i], "att")) for i in ids}
    scale = {}
    for t in team_base:
        scale[t] = dict(car=1.0, rec=1.0, att=1.0)
        for k in ("car", "rec", "att"):
            tot = nsum(raw[i][k] for i in ids if PL[i]["team"] == t)
            if tot > 0:
                scale[t][k] = max(1 - C.CFB_TEAM_SCALE_CAP, min(1 + C.CFB_TEAM_SCALE_CAP, team_base[t][k] / tot))
    # team projected volume after the rescale, so a share adds to 100% across the team (receiving share is a share of RECEPTIONS)
    team_car, team_rec = {}, {}
    for i in ids:
        t = PL[i]["team"]
        team_car[t] = team_car.get(t, 0.0) + raw[i]["car"] * scale[t]["car"]
        team_rec[t] = team_rec.get(t, 0.0) + raw[i]["rec"] * scale[t]["rec"]

    out = []
    for i in ids:
        p = PL[i]
        m = matchup[p["team"]]
        car, rec, att = (raw[i][k] * scale[p["team"]][k] for k in ("car", "rec", "att"))
        if car < 0.5 and rec < 0.5 and att < 1:
            continue
        dr, dc, dp, dcomp = def_rush.get(m["opp"], 1.0), def_rec.get(m["opp"], 1.0), def_pass.get(m["opp"], 1.0), def_comp.get(m["opp"], 1.0)
        site = 1.02 if m["site"] == "vs" else (1.0 if m["site"] == "N" else 0.98)
        rb = rush_base["QB" if is_qb(p) else "OTHER"]
        out.append(dict(
            id=i, name=p["name"], pos=p["pos"], team=p["team"], conf=p["conf"] or conf.get(p["team"]) or "", opp=m["opp"], siteTag=m["site"], start=m.get("start") or "",
            g=p["g"], car=rnd(car, 1), rec=rnd(rec, 1), att=rnd(att, 1),
            ypc=(p["rushing_yards"] + C.CFB_PRIOR_CAR * rb["ypc"]) / (p["carries"] + C.CFB_PRIOR_CAR),
            ypr=(p["receiving_yards"] + C.CFB_PRIOR_REC * LG_YPR) / (p["receptions"] + C.CFB_PRIOR_REC),
            ypa=(p["passing_yards"] + C.CFB_PRIOR_ATT * LG_YPA) / (p["attempts"] + C.CFB_PRIOR_ATT),
            compRate=(p["completions"] + C.CFB_PRIOR_ATT * LG_COMP) / (p["attempts"] + C.CFB_PRIOR_ATT),
            rushTdRate=(p["rushing_tds"] + C.CFB_PRIOR_CAR * rb["td"]) / (p["carries"] + C.CFB_PRIOR_CAR),
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

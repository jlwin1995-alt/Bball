"""The projection model for one NFL week. A line-for-line port of nflCore_ / nflDerive_ from the sheet.

nfl_core(rows, matchup, wx) is a pure function of the weekly rows (already filtered to weeks BEFORE the one being projected)
and the slate. The backtest calls the same function, so what it measures is what the site shows.
"""
import csv, math
from . import config as C

REC_POS = ("WR", "TE", "RB")


def num(v):
    if v is None or v == "" or v == "NA":
        return 0.0
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if x != x else x


def rnd(v, p=1):
    """JS Math.round(v * 10^p) / 10^p: halves round up, not to even."""
    if v == "" or v is None:
        return ""
    f = 10.0 ** p
    return math.floor(v * f + 0.5) / f


def load_weekly(path):
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            for k, v in r.items():
                if k in ("player_id", "player_display_name", "position", "position_group", "team", "opponent_team", "season_type"):
                    continue
                r[k] = num(v)
            out.append(r)
    return out


def regress(raw, nobs, k, toward=1.0):
    return toward + (raw - toward) * (nobs / (nobs + k))


def clamp_to(x, c):
    return max(1 - c, min(1 + c, x))


def def_strength(x, s):
    return 1 + (x - 1) * s


def td_adj(yard_adj, lam):
    return 1 + (yard_adj - 1) * lam


def td_base(pl, key):
    raw = pl.get(key + "Raw")
    return pl[key] if raw is None else raw


def cal_shrink(x, pivot, slope, weight):
    if not pivot or not (slope < 1) or not (weight > 0):
        return x
    w = min(1.0, weight)
    return x + w * ((pivot + (x - pivot) * slope) - x)


def pos_k(grp, P):
    return {"WR": P["K_DEF_POS_WR"], "TE": P["K_DEF_POS_TE"], "RB": P["K_DEF_POS_RB"]}.get(grp, P["K_DEF_POS"])


def params(**over):
    """Every model knob as a dict (config.py defaults, optionally overridden)."""
    P = {k: getattr(C, k) for k in dir(C) if k.isupper()}
    P.update(over)
    return P


def wx_factors(wind, indoor, P):
    """Wind -> multipliers. The hinge lives here and nowhere else. Unknown weather must never quietly become 'fine'."""
    none = {"yds": 1.0, "rec": 1.0, "rush": 1.0, "wind": ""}
    if not P["WEATHER_ON"] or indoor:
        return none
    if wind is None or wind == "" or wind == "NA":
        return none
    try:
        w = float(wind)
    except (TypeError, ValueError):
        return none
    if w != w or w < 0:
        return none
    excess = max(0.0, w - P["WX_WIND_THRESHOLD"])
    yds = max(P["WX_WIND_FLOOR"], 1 - P["WX_WIND_SLOPE"] * excess)
    return {"yds": yds, "rec": 1 + (yds - 1) * P["WX_REC_DAMP"], "rush": min(1.15, 1 + P["WX_RUSH_SLOPE"] * excess), "wind": w}


def wx_indoor(roof):
    """A retractable roof with no state recorded is treated as INDOOR: better a missed adjustment than a false one."""
    return str(roof or "").lower() in ("dome", "closed", "")


SUMS = ["carries", "rushing_yards", "rushing_tds", "targets", "receptions", "receiving_yards", "receiving_tds", "completions",
        "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered", "rushing_fumbles_lost",
        "receiving_fumbles_lost", "sack_fumbles_lost", "rushing_2pt_conversions", "receiving_2pt_conversions",
        "passing_2pt_conversions"]


def nfl_core(rows, matchup, wx=None, P=None):
    """matchup: team -> {opp, site ('@' | 'vs'), rest}.  wx: team -> wind multipliers.  Returns the players plus the defence tables."""
    P = P or params()
    wx = wx or {}
    cap = P["DEF_ADJ_CAP"] or 0.15
    catch_cap = cap * P["CATCH_CAP_FRACTION"]
    win = max(1, int(P["ROLLING_WINDOW"] or 3))

    # --- league baselines, overall and per position group --------------------------------------------------------------
    lg = dict(car=0.0, ry=0.0, r10=0.0, tgt=0.0, recy=0.0, rec=0.0, rtd=0.0, rectd=0.0, att=0.0, comp=0.0, sack=0.0,
              fumRR=0.0, fumSack=0.0, two=0.0)
    lg_pos = {p: dict(tgt=0.0, rec=0.0, recy=0.0) for p in REC_POS}
    de, de_pos, team_tot, team_weeks = {}, {}, {}, {}

    for r in rows:
        d, t, pg = r["opponent_team"], r["team"], r["position_group"]
        car, ry, r10, tgt, recy, rec = r["carries"], r["rushing_yards"], r.get("rushing_10", 0.0), r["targets"], r["receiving_yards"], r["receptions"]
        att, comp, sack = r["attempts"], r["completions"], r["sacks_suffered"]
        lg["car"] += car; lg["ry"] += ry; lg["r10"] += r10; lg["tgt"] += tgt; lg["recy"] += recy; lg["rec"] += rec
        lg["rtd"] += r["rushing_tds"]; lg["rectd"] += r["receiving_tds"]; lg["att"] += att; lg["comp"] += comp; lg["sack"] += sack
        lg["fumRR"] += r["rushing_fumbles_lost"] + r["receiving_fumbles_lost"]; lg["fumSack"] += r["sack_fumbles_lost"]
        lg["two"] += r["rushing_2pt_conversions"] + r["receiving_2pt_conversions"] + r["passing_2pt_conversions"]
        if pg in lg_pos:
            lg_pos[pg]["tgt"] += tgt; lg_pos[pg]["rec"] += rec; lg_pos[pg]["recy"] += recy
        if d not in de:
            de[d] = dict(car=0.0, ry=0.0, r10=0.0, tgt=0.0, recy=0.0, rec=0.0, comp=0.0, att=0.0, sack=0.0)
            de_pos[d] = {p: dict(tgt=0.0, rec=0.0, recy=0.0) for p in REC_POS}
        a = de[d]
        a["car"] += car; a["ry"] += ry; a["r10"] += r10; a["tgt"] += tgt; a["rec"] += rec; a["recy"] += recy
        a["comp"] += comp; a["att"] += att; a["sack"] += sack
        if pg in de_pos[d]:
            ap = de_pos[d][pg]; ap["tgt"] += tgt; ap["rec"] += rec; ap["recy"] += recy
        if t not in team_tot:
            team_tot[t] = dict(car=0.0, tgt=0.0, att=0.0, rtd=0.0, rectd=0.0)
            team_weeks[t] = set()
        tt = team_tot[t]
        tt["car"] += car; tt["tgt"] += tgt; tt["att"] += att; tt["rtd"] += r["rushing_tds"]; tt["rectd"] += r["receiving_tds"]
        team_weeks[t].add(r["week"])

    LG_YPC = lg["ry"] / lg["car"] if lg["car"] else 4.3
    LG_YPT = lg["recy"] / lg["tgt"] if lg["tgt"] else 7.5
    LG_CATCH = lg["rec"] / lg["tgt"] if lg["tgt"] else 0.65
    LG_YPR = lg["recy"] / lg["rec"] if lg["rec"] else 11.0
    LG_EXPL10 = lg["r10"] / lg["car"] if lg["car"] else 0.112
    LG_RUSH_TD = lg["rtd"] / lg["car"] if lg["car"] else 0.025
    LG_REC_TD = lg["rectd"] / lg["tgt"] if lg["tgt"] else 0.045
    LG_FUM_TOUCH = lg["fumRR"] / (lg["car"] + lg["rec"]) if (lg["car"] + lg["rec"]) else 0.007
    LG_FUM_ATT = lg["fumSack"] / lg["att"] if lg["att"] else 0.007
    opp_all = lg["car"] + lg["tgt"] + lg["att"]
    LG_2PT = lg["two"] / opp_all if opp_all else 0.0005
    # completion rate is NOT the receivers' catch rate: attempts include throwaways and spikes that never charge a target
    LG_COMP = lg["comp"] / lg["att"] if lg["att"] else 0.65
    # sacks are a rate per DROPBACK (attempt or sack), not per attempt
    LG_SACK = lg["sack"] / (lg["att"] + lg["sack"]) if (lg["att"] + lg["sack"]) else 0.068

    pos_base = {}
    for p in REC_POS:
        a = lg_pos[p]
        pos_base[p] = dict(catch=a["rec"] / a["tgt"] if a["tgt"] else LG_CATCH, ypr=a["recy"] / a["rec"] if a["rec"] else LG_YPR)

    def base_for(pg):
        return pos_base.get(pg) or dict(catch=LG_CATCH, ypr=LG_YPR)

    # --- defensive adjustments -------------------------------------------------------------------------------------------
    def_rush, def_catch, def_ypr, def_pass, def_comp, def_sack = {}, {}, {}, {}, {}, {}
    def_pos_catch, def_pos_ypr = {}, {}
    for d, a in de.items():
        if a["car"]:
            # rushing defence from TWO measurements: yards per carry and how often it allows a 10-yard run (weight 0 by default)
            dY = (a["ry"] / a["car"]) / LG_YPC - 1
            dE = ((a["r10"] / a["car"]) / LG_EXPL10 - 1) * P["EXPL_RUSH_SCALE"] if LG_EXPL10 else 0
            mixed = 1 + P["EXPL_RUSH_WEIGHT"] * dE + (1 - P["EXPL_RUSH_WEIGHT"]) * dY
            def_rush[d] = clamp_to(regress(mixed, a["car"], P["K_DEF_RUSH"]), cap)
        if a["tgt"]:
            def_catch[d] = clamp_to(regress((a["rec"] / a["tgt"]) / LG_CATCH, a["tgt"], P["K_DEF_CATCH"]), catch_cap)
            def_pass[d] = clamp_to(regress((a["recy"] / a["tgt"]) / LG_YPT, a["tgt"], P["K_DEF_PASS"]), cap)
        if a["rec"]:
            def_ypr[d] = clamp_to(regress((a["recy"] / a["rec"]) / LG_YPR, a["rec"], P["K_DEF_YPR"]), cap)
        if a["att"]:
            def_comp[d] = clamp_to(regress((a["comp"] / a["att"]) / LG_COMP, a["att"], P["K_DEF_CATCH"]), catch_cap)
            db = a["att"] + a["sack"]
            if db:
                def_sack[d] = clamp_to(regress((a["sack"] / db) / LG_SACK, db, P["K_DEF_PASS"]), cap)
        # position splits regress toward this defence's own overall number
        def_pos_catch[d], def_pos_ypr[d] = {}, {}
        base_c = def_catch.get(d, 1.0)
        base_y = def_ypr.get(d, 1.0)
        for p in REC_POS:
            k_pos = pos_k(p, P)
            ap, lp = de_pos[d][p], lg_pos[p]
            def_pos_catch[d][p] = (clamp_to(regress((ap["rec"] / ap["tgt"]) / (lp["rec"] / lp["tgt"]), ap["tgt"], k_pos, base_c), catch_cap)
                                   if (ap["tgt"] and lp["tgt"] and lp["rec"]) else base_c)
            def_pos_ypr[d][p] = (clamp_to(regress((ap["recy"] / ap["rec"]) / (lp["recy"] / lp["rec"]), ap["rec"], k_pos, base_y), cap)
                                 if (ap["rec"] and lp["rec"] and lp["recy"]) else base_y)

    # --- team volume baselines, regressed toward the league rate ---------------------------------------------------------------------
    lg_team = dict(car=0.0, tgt=0.0, att=0.0)
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
        w = n / (n + P["K_TEAM_VOL"])
        team_base[t] = {k: (team_tot[t][k] / n) * w + lg_team[k] * (1 - w) for k in ("car", "tgt", "att")}

    # --- aggregate players ---------------------------------------------------------------------------------------------------------
    PL = {}
    for r in rows:
        pid = r["player_id"]
        if pid not in PL:
            PL[pid] = dict(name=r["player_display_name"], pos=r["position"], grp=r["position_group"], team=r["team"], g=0, weeks=[])
            for c in SUMS:
                PL[pid][c] = 0.0
        p = PL[pid]
        p["team"] = r["team"]
        p["grp"] = r["position_group"] or p["grp"]
        p["g"] += 1
        for c in SUMS:
            p[c] += r.get(c, 0.0)
        p["weeks"].append(dict(week=r["week"], car=r["carries"], tgt=r["targets"], att=r["attempts"]))

    def blend(p, key):
        w = sorted(p["weeks"], key=lambda x: x["week"])
        season = sum(x[key] for x in w) / len(w)
        if len(w) < win:
            return season
        recent = w[-win:]
        rw = P["RECENT_WEIGHT_ATT"] if key == "att" else P["RECENT_WEIGHT"]
        return rw * (sum(x[key] for x in recent) / len(recent)) + (1 - rw) * season

    ids = [i for i in PL if PL[i]["team"] in matchup]
    raw = {i: dict(car=blend(PL[i], "car"), tgt=blend(PL[i], "tgt"), att=blend(PL[i], "att")) for i in ids}

    # --- participation weighting (attempts only): a backup who threw in one of the last six games stops absorbing a fifth of the offence
    play_win = max(1, int(P["PLAY_WINDOW"]))
    play_prior = P["PLAY_PRIOR"]
    use_w = dict(car=bool(P["CONCENTRATE_CARRIES"]), tgt=bool(P["CONCENTRATE_TARGETS"]), att=bool(P["CONCENTRATE_ATTEMPTS"]))
    play_floor = dict(car=1, tgt=1, att=5)
    seen_weeks = {}
    for r in rows:
        if r["team"] and r["week"]:
            seen_weeks.setdefault(r["team"], set()).add(r["week"])
    recent_team_weeks = {t: sorted(ws)[-play_win:] for t, ws in seen_weeks.items()}
    p_play = {}
    for i in ids:
        p = PL[i]
        want = recent_team_weeks.get(p["team"], [])
        p_play[i] = dict(car=1.0, tgt=1.0, att=1.0)
        if not want:
            continue
        seen = {x["week"]: x for x in p["weeks"]}
        for k in ("car", "tgt", "att"):
            hits = sum(1 for w in want if w in seen and seen[w][k] >= play_floor[k])
            p_play[i][k] = (hits + play_prior * 0.5) / (len(want) + play_prior)

    scale = {}
    for t in team_base:
        scale[t] = dict(car=1.0, tgt=1.0, att=1.0)
        for k in ("car", "tgt", "att"):
            tot = sum(raw[i][k] * (p_play[i][k] if use_w[k] else 1) for i in ids if PL[i]["team"] == t)
            if tot > 0:
                scale[t][k] = max(1 - P["TEAM_SCALE_CAP"], min(1 + P["TEAM_SCALE_CAP"], team_base[t][k] / tot))

    def td_target(p, kind):
        """The rate a touchdown rate is shrunk toward: a blend of his own offence (EXCLUDING him) and the league."""
        lg_rate = LG_RUSH_TD if kind == "rush" else LG_REC_TD
        if P["TEAM_TD_WEIGHT"] <= 0:
            return lg_rate
        t = team_tot.get(p["team"])
        if not t:
            return lg_rate
        n = (t["rtd"] - p["rushing_tds"]) if kind == "rush" else (t["rectd"] - p["receiving_tds"])
        dn = (t["car"] - p["carries"]) if kind == "rush" else (t["tgt"] - p["targets"])
        if dn <= 0:
            return lg_rate
        team_rate = (n + P["K_TEAM_TD"] * lg_rate) / (dn + P["K_TEAM_TD"])
        return P["TEAM_TD_WEIGHT"] * team_rate + (1 - P["TEAM_TD_WEIGHT"]) * lg_rate

    # which players make it onto the slate, decided BEFORE the team totals are summed (so shares add up to 100)
    keep = []
    for i in ids:
        p = PL[i]
        car, tgt, att = (raw[i][k] * scale[p["team"]][k] for k in ("car", "tgt", "att"))
        if car < 1 and tgt < 1 and att < 1:
            continue
        keep.append((i, car, tgt, att))
    team_proj = {}
    for i, car, tgt, att in keep:
        t = PL[i]["team"]
        tp = team_proj.setdefault(t, dict(car=0.0, tgt=0.0, att=0.0))
        tp["car"] += rnd(car, 1); tp["tgt"] += rnd(tgt, 1); tp["att"] += rnd(att, 1)

    out = []
    for i, car, tgt, att in keep:
        p = PL[i]
        m = matchup[p["team"]]
        pb = base_for(p["grp"])
        opp = m["opp"]
        dr = def_rush.get(opp, 1.0)
        dp = def_pass.get(opp, 1.0)
        dcomp = def_comp.get(opp, 1.0)
        dsack = def_sack.get(opp, 1.0)
        dc = def_pos_catch.get(opp, {}).get(p["grp"], def_catch.get(opp, 1.0))
        dy = def_pos_ypr.get(opp, {}).get(p["grp"], def_ypr.get(opp, 1.0))

        site = 1.02 if m["site"] == "vs" else 0.98
        rest = m.get("rest") or 0
        if rest >= 10:
            site *= 1.01
        elif 0 < rest <= 5:
            site *= 0.99

        # strength governs YARDAGE only; touchdown lambdas were measured against the undamped number, so keep the originals
        drRaw, dyRaw, dcRaw, dpRaw = dr, dy, dc, dp
        dr = def_strength(dr, P["DEF_STRENGTH_RUSH"])
        dy = def_strength(dy, P["DEF_STRENGTH_YPR"])
        dc = def_strength(dc, P["DEF_STRENGTH_CATCH"])
        dp = def_strength(dp, P["DEF_STRENGTH_PASS"])
        dcomp = def_strength(dcomp, P["DEF_STRENGTH_COMP"])
        dsack = def_strength(dsack, P["SACK_DEF_STRENGTH"])

        w = wx.get(p["team"]) or {"yds": 1.0, "rec": 1.0, "rush": 1.0, "wind": ""}
        dr *= w["rush"]; dc *= w["rec"]
        dy *= (w["yds"] / w["rec"]) if w["rec"] else w["yds"]
        dp *= w["yds"]; dcomp *= w["rec"]

        tp = team_proj.get(p["team"]) or {}
        out.append(dict(
            id=i, name=p["name"], pos=p["pos"], grp=p["grp"], team=p["team"], opp=opp, siteTag=m["site"], rest=m.get("rest") or 0, g=p["g"],
            car=car, tgt=tgt, att=att, site=site, drRaw=drRaw, dyRaw=dyRaw, dcRaw=dcRaw, dpRaw=dpRaw, wind=w["wind"], wxYds=w["yds"],
            teamCar=tp.get("car", 0.0), teamTgt=tp.get("tgt", 0.0), dr=dr, dc=dc, dy=dy, dp=dp, dcomp=dcomp,
            ypc=(p["rushing_yards"] + P["PRIOR_CARRIES"] * LG_YPC) / (p["carries"] + P["PRIOR_CARRIES"]),
            cr=(p["receptions"] + P["PRIOR_TARGETS"] * pb["catch"]) / (p["targets"] + P["PRIOR_TARGETS"]),
            ypr=(p["receiving_yards"] + P["PRIOR_TARGETS"] * pb["catch"] * pb["ypr"]) / (p["receptions"] + P["PRIOR_TARGETS"] * pb["catch"]),
            ypa=(p["passing_yards"] + P["PRIOR_ATTEMPTS"] * C.LG_YPA) / (p["attempts"] + P["PRIOR_ATTEMPTS"]),
            compRate=(p["completions"] + P["PRIOR_ATTEMPTS"] * LG_COMP) / (p["attempts"] + P["PRIOR_ATTEMPTS"]),
            # touchdown rates shrink toward the player's OFFENCE (regressing results on own history + team-without-him: +0.32 vs +0.34)
            rushTdRate=(p["rushing_tds"] + P["PRIOR_CARRIES"] * td_target(p, "rush")) / (p["carries"] + P["PRIOR_CARRIES"]),
            recTdRate=(p["receiving_tds"] + P["PRIOR_TARGETS"] * td_target(p, "rec")) / (p["targets"] + P["PRIOR_TARGETS"]),
            ptdRate=(p["passing_tds"] + P["PRIOR_ATTEMPTS"] * C.LG_PASS_TD) / (p["attempts"] + P["PRIOR_ATTEMPTS"]),
            intRate=(p["passing_interceptions"] + P["PRIOR_ATTEMPTS"] * C.LG_INT) / (p["attempts"] + P["PRIOR_ATTEMPTS"]),
            # being sacked is a quarterback's own trait more than his line's; needs heavy shrinkage (a sack is rare)
            sackRate=(p["sacks_suffered"] + P["PRIOR_SACKS"] * LG_SACK) / (p["attempts"] + p["sacks_suffered"] + P["PRIOR_SACKS"]),
            dsack=dsack,
            fumTouch=(p["rushing_fumbles_lost"] + p["receiving_fumbles_lost"] + P["PRIOR_FUMBLES"] * LG_FUM_TOUCH) / (p["carries"] + p["receptions"] + P["PRIOR_FUMBLES"]),
            fumAtt=(p["sack_fumbles_lost"] + P["PRIOR_FUMBLES"] * LG_FUM_ATT) / (p["attempts"] + P["PRIOR_FUMBLES"]),
            twoRate=(p["rushing_2pt_conversions"] + p["receiving_2pt_conversions"] + p["passing_2pt_conversions"] + P["PRIOR_TWOPT"] * LG_2PT)
                    / (p["carries"] + p["targets"] + p["attempts"] + P["PRIOR_TWOPT"]),
        ))

    # Quarterback projections come out too SPREAD OUT (regressing actual on projected gives 0.68 for passing yards and completions):
    # pull the two affected markets back toward the slate's own mean.
    pass_pivot = comp_pivot = 0.0
    n = 0
    for pl in out:
        if pl["att"] < 15:
            continue
        n += 1
        pass_pivot += pl["att"] * pl["ypa"] * pl["dp"] * pl["site"]
        comp_pivot += pl["att"] * pl["compRate"] * pl["dcomp"]
    if n:
        pass_pivot /= n; comp_pivot /= n
        for pl in out:
            pl["passPivot"], pl["compPivot"] = pass_pivot, comp_pivot

    def scale_map(mp, s):
        return {k: def_strength(v, s) for k, v in mp.items()}

    def scale_nested(mp, s):
        return {k: {g: def_strength(v, s) for g, v in d.items()} for k, d in mp.items()}

    return dict(players=out, de=de, de_pos=de_pos, posBase=pos_base, LG_YPC=LG_YPC, LG_CATCH=LG_CATCH, LG_YPR=LG_YPR,
                defRush=scale_map(def_rush, P["DEF_STRENGTH_RUSH"]), defCatch=scale_map(def_catch, P["DEF_STRENGTH_CATCH"]),
                defYpr=scale_map(def_ypr, P["DEF_STRENGTH_YPR"]), defPass=scale_map(def_pass, P["DEF_STRENGTH_PASS"]),
                defComp=scale_map(def_comp, P["DEF_STRENGTH_COMP"]),
                defPosCatch=scale_nested(def_pos_catch, P["DEF_STRENGTH_CATCH"]), defPosYpr=scale_nested(def_pos_ypr, P["DEF_STRENGTH_YPR"]))


def derive(pl, W, P=None):
    """Turn a core player record into the stat line (nflDerive_). Volumes are rounded to one decimal FIRST, as displayed."""
    P = P or params()
    vcar, vtgt, vatt = rnd(pl["car"], 1), rnd(pl["tgt"], 1), rnd(pl["att"], 1)
    rush_y = vcar * pl["ypc"] * (pl["dr"] * pl["site"])
    rec = vtgt * pl["cr"] * pl["dc"]
    rec_y = rec * pl["ypr"] * (pl["dy"] * pl["site"])
    qb_w = vatt / 15                       # full correction at 15+ projected attempts, none at 0
    pass_y = cal_shrink(vatt * pl["ypa"] * (pl["dp"] * pl["site"]), pl.get("passPivot"), P["CAL_PASS_SLOPE"], qb_w)
    comp = cal_shrink(vatt * pl["compRate"] * pl["dcomp"], pl.get("compPivot"), P["CAL_COMP_SLOPE"], qb_w)
    rush_td = vcar * pl["rushTdRate"] * td_adj(td_base(pl, "dr"), P["LAMBDA_RUSH_TD"]) * pl["site"]
    rec_td = vtgt * pl["recTdRate"] * td_adj(td_base(pl, "dc") * td_base(pl, "dy"), P["LAMBDA_REC_TD"]) * pl["site"]
    pass_td = vatt * pl["ptdRate"] * td_adj(td_base(pl, "dp"), P["LAMBDA_PASS_TD"]) * pl["site"]
    ints = vatt * pl["intRate"]
    # the sack rate is per dropback (an attempt OR a sack): solve sacks = rate x (att + sacks) for sacks
    sr = min(0.5, max(0.0, pl["sackRate"] * pl["dsack"]))
    sacks = vatt * sr / (1 - sr) if vatt > 0 else 0.0
    fum = (vcar + rec) * pl["fumTouch"] + vatt * pl["fumAtt"]
    two = (vcar + vtgt + vatt) * pl["twoRate"]
    out = dict(car=vcar, tgt=vtgt, att=vatt, rushY=rush_y, rec=rec, recY=rec_y, passY=pass_y, comp=comp, sacks=sacks,
               rushTD=rush_td, recTD=rec_td, td=rush_td + rec_td, passTD=pass_td, int=ints, fum=fum, two=two)
    out["pts"] = points(out, W)
    return out


def points(d, W):
    return (d["rushY"] * W["rushYd"] + d["recY"] * W["recYd"] + d["passY"] * W["passYd"] + d["rec"] * W["rec"]
            + d["rushTD"] * W["rushTd"] + d["recTD"] * W["recTd"] + d["passTD"] * W["passTd"]
            + d["int"] * W["intr"] + d["fum"] * W["fum"] + d["two"] * W["two"])


def opp_pos_factor(pl, P=None):
    """The multiplier that applies to this player's main market, defence only (site and weather are separate columns)."""
    P = P or params()
    if pl["att"] > 0 or pl["pos"] == "QB":
        return def_strength(pl["dpRaw"], P["DEF_STRENGTH_PASS"])
    if pl["grp"] == "RB" or pl["pos"] in ("RB", "FB"):
        return def_strength(pl["drRaw"], P["DEF_STRENGTH_RUSH"])
    return def_strength(pl["dcRaw"], P["DEF_STRENGTH_CATCH"]) * def_strength(pl["dyRaw"], P["DEF_STRENGTH_YPR"])


def pos_group(pl):
    if pl["att"] > 0 or pl["pos"] == "QB":
        return "QB"
    if pl["grp"] == "RB" or pl["pos"] in ("RB", "FB"):
        return "RB"
    return "REC"

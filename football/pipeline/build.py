"""data/raw -> site/data/*.json   (and logs the slate before kickoff)

    python -m pipeline.build [--raw data/raw] [--out site/data] [--no-log] [--no-weather] [--week N]
"""
import argparse, datetime as dt, json, os, sys
from . import config as C, analysis, scorecard, weather
from .model import (load_weekly, nfl_core, derive, params, rnd, td_adj, td_base, opp_pos_factor, pos_group, REC_POS, num)
from .slate import load_csv, target_week, matchups, kickoffs, statuses, week_games, game_label, history_gaps


def dump(obj, out, name):
    with open(os.path.join(out, name), "w") as f:
        json.dump(obj, f, separators=(",", ":"), default=str)


def r(x, n=3):
    return None if x is None or x == "" or x != x else round(float(x), n)


def utc(d):
    return d.astimezone(dt.timezone.utc).isoformat(timespec="seconds") if d else None


def game_rows(sched, week, wx_rows):
    wxm = {w["game"]: w for w in wx_rows}
    out = []
    for g in week_games(sched, week):
        label = game_label(g["away_team"], g["home_team"])
        k = C.kickoff(g["gameday"], g["gametime"])
        spread, total = num(g.get("spread_line")) if g.get("spread_line") not in ("", "NA") else None, num(g.get("total_line")) if g.get("total_line") not in ("", "NA") else None
        w = wxm.get(label, {})
        out.append(dict(game=label, away=g["away_team"], home=g["home_team"], ko=utc(k), stadium=g.get("stadium", ""), neutral=g.get("location") == "Neutral",
                        roof=w.get("roof") or g.get("roof", ""), wind=w.get("wind"), temp=w.get("temp"), src=w.get("src"),
                        spread=spread, total=total,
                        # nflverse spread_line is from the home team's side: positive = home favoured
                        away_imp=r(total / 2 - spread / 2, 1) if spread is not None and total is not None else None,
                        home_imp=r(total / 2 + spread / 2, 1) if spread is not None and total is not None else None,
                        played=g["result"] not in ("", "NA")))
    out.sort(key=lambda x: x["ko"] or "")
    return out


def matchup_table(core, mu, week, P):
    rows = []
    facing = {}
    for t, m in mu.items():
        facing.setdefault(m["opp"], []).append(t)
    for d in sorted(core["de"]):
        a = core["de"][d]
        dr, dc, dy, dp = (core[k].get(d, 1.0) for k in ("defRush", "defCatch", "defYpr", "defPass"))
        # the three TD Adj columns come from the yardage columns, not from touchdowns allowed (a defence's own TD rate allowed barely
        # predicts its future one: split-half r +0.19 rushing, negative for receiving and passing)
        rows.append(dict(
            team=d, car=a["car"], ypc=r(a["ry"] / a["car"], 2) if a["car"] else None, r10=r(a["r10"] / a["car"] * 100, 1) if a["car"] else None,
            rush=r(dr), tgt=a["tgt"], catch_pct=r(a["rec"] / a["tgt"], 3) if a["tgt"] else None, catch=r(dc),
            ypr_a=r(a["recy"] / a["rec"], 2) if a["rec"] else None, ypr=r(dy), pass_=r(dp), comp=r(core["defComp"].get(d, 1.0)),
            rtd=r(td_adj(dr, P["LAMBDA_RUSH_TD"])), rectd=r(td_adj(dc * dy, P["LAMBDA_REC_TD"])), ptd=r(td_adj(dp, P["LAMBDA_PASS_TD"])),
            **{f"catch_{p.lower()}": r(core["defPosCatch"].get(d, {}).get(p, 1.0)) for p in REC_POS},
            **{f"ypr_{p.lower()}": r(core["defPosYpr"].get(d, {}).get(p, 1.0)) for p in REC_POS},
            faces=", ".join(sorted(facing.get(d, [])))))
    return rows


def main(raw="data/raw", out="site/data", log=True, fetch_wx=True, force_week=None):
    os.makedirs(out, exist_ok=True)
    P = params()
    W = C.DEFAULT_SCORING
    rows = load_weekly(f"{raw}/weekly.csv")
    sched = load_csv(f"{raw}/schedule.csv")
    inj = load_csv(f"{raw}/injuries.csv") if os.path.exists(f"{raw}/injuries.csv") else []
    snaps = analysis.load_snaps(f"{raw}/snaps.csv")
    week = target_week(sched, force_week or C.PROJECT_WEEK)
    if not week:
        print("No unplayed games found - nothing to project (off-season?). Leaving site/data as it was.")
        return 0
    mu = matchups(sched, week)
    if not rows:
        raise SystemExit("weekly.csv is empty; run `python -m pipeline.fetch` first")

    # history is every week BEFORE the one being projected, and nothing else: on a Monday afternoon Sunday's games are already in the
    # file but the target week is still the current one, so passing everything would put a player's own result in his history
    hist = [x for x in rows if x["week"] < week]
    held = len(rows) - len(hist)
    if held:
        print(f"held back {held} rows from week {week} or later so the projection cannot see its own answers")

    by_team_wx, wx_rows = weather.week_weather(sched, week, P, weather.load_overrides(), fetch=fetch_wx)
    core = nfl_core(hist, mu, by_team_wx, P)
    status = statuses(inj, week)
    kick = kickoffs(sched, week)

    # rank each opponent within the position group it is being judged on, so "+4.7%" carries the context that makes it readable
    pos_fac, pos_rank = {}, {}
    for pl in core["players"]:
        pos_fac.setdefault(pos_group(pl), {}).setdefault(pl["opp"], opp_pos_factor(pl, P))
    for g, d in pos_fac.items():
        order = sorted(d, key=lambda t: -d[t])
        pos_rank[g] = {t: (i + 1, len(order)) for i, t in enumerate(order)}

    proj = []
    for pl in core["players"]:
        d = derive(pl, W, P)
        away = pl["opp"] if pl["siteTag"] == "vs" else pl["team"]
        home = pl["team"] if pl["siteTag"] == "vs" else pl["opp"]
        g = pos_group(pl)
        rk = pos_rank.get(g, {}).get(pl["opp"])
        k0 = kick.get(pl["team"])
        proj.append(dict(
            id=pl["id"], name=pl["name"], pos=pl["pos"], grp=pl["grp"], team=pl["team"], opp=pl["opp"], home=int(pl["siteTag"] == "vs"),
            game=game_label(away, home), ko=utc(k0), status=status.get(pl["id"], ""), g=pl["g"], rest=pl["rest"],
            wind=r(pl["wind"], 1) if pl["wind"] != "" else None,
            # volumes (rounded to one decimal, as displayed) and the rates the browser multiplies them by when you override a volume
            car=d["car"], tgt=d["tgt"], att=d["att"], ypc=r(pl["ypc"], 4), cr=r(pl["cr"], 4), ypr=r(pl["ypr"], 4), ypa=r(pl["ypa"], 4), cmp=r(pl["compRate"], 4),
            a_rush=r(pl["dr"] * pl["site"], 4), a_catch=r(pl["dc"], 4), a_ypr=r(pl["dy"] * pl["site"], 4), a_pass=r(pl["dp"] * pl["site"], 4),
            a_comp=r(pl["dcomp"], 4), a_sack=r(pl["dsack"], 4),
            rtd_r=r(pl["rushTdRate"], 5), rectd_r=r(pl["recTdRate"], 5), ptd_r=r(pl["ptdRate"], 5), int_r=r(pl["intRate"], 5),
            sack_r=r(pl["sackRate"], 5), fum_t=r(pl["fumTouch"], 6), fum_a=r(pl["fumAtt"], 6), two_r=r(pl["twoRate"], 6),
            a_rtd=r(td_adj(td_base(pl, "dr"), P["LAMBDA_RUSH_TD"]) * pl["site"], 4),
            a_rectd=r(td_adj(td_base(pl, "dc") * td_base(pl, "dy"), P["LAMBDA_REC_TD"]) * pl["site"], 4),
            a_ptd=r(td_adj(td_base(pl, "dp"), P["LAMBDA_PASS_TD"]) * pl["site"], 4),
            tcar=r(pl["teamCar"], 1), ttgt=r(pl["teamTgt"], 1), pp=r(pl.get("passPivot"), 4), cp=r(pl.get("compPivot"), 4),
            # the projection under the default scoring components (the browser recomputes points from these under any scoring preset)
            ry=r(d["rushY"], 2), rec=r(d["rec"], 3), recy=r(d["recY"], 2), py=r(d["passY"], 2), comp=r(d["comp"], 3), sacks=r(d["sacks"], 3),
            rtd=r(d["rushTD"], 4), rectd=r(d["recTD"], 4), ptd=r(d["passTD"], 4), int=r(d["int"], 4), fum=r(d["fum"], 4), two=r(d["two"], 5),
            ovp=r((opp_pos_factor(pl, P) - 1) * 100, 1), ork=f"{rk[0]}/{rk[1]}" if rk else None, pts=r(d["pts"], 2)))
    proj.sort(key=lambda x: -(x["car"] + x["tgt"] + x["att"] * 0.5))
    dump(proj, out, "projections.json")

    games = game_rows(sched, week, wx_rows)
    dump(games, out, "games.json")
    dump(wx_rows, out, "weather.json")
    dump(dict(week=week, rows=matchup_table(core, mu, week, P), lg=dict(ypc=r(core["LG_YPC"], 3), catch=r(core["LG_CATCH"], 4), ypr=r(core["LG_YPR"], 3),
                                                                        pos={p: dict(catch=r(v["catch"], 3), ypr=r(v["ypr"], 2)) for p, v in core["posBase"].items()})),
         out, "matchups.json")

    # --- Efficiency / Usage / Trends / Coverage: every row in the file, with unprocessed team-weeks dropped -------------------------
    Pl, team_week, live = analysis.aggregate(rows, snaps)
    dump(analysis.efficiency(Pl), out, "efficiency.json")
    dump(analysis.usage(Pl), out, "usage.json")
    dump(analysis.trends(Pl), out, "trends.json")
    dump(analysis.coverage(team_week, live), out, "coverage.json")

    # --- Accuracy log (written ONCE per week, before the games) and its scorecard --------------------------------------------------------
    gaps = history_gaps(rows, sched, week)
    if gaps:
        print(f"::warning::history is incomplete ({len(gaps)} earlier games have no box scores yet, e.g. {gaps[0]}); showing projections but NOT logging them")
    logged = scorecard.log_week(C.SEASON, week, core, hist, status, kick, P) if (log and not gaps) else 0
    sc = scorecard.score(rows, live, P=P)
    dump(sc, out, "scorecard.json")

    now = dt.datetime.now(dt.timezone.utc)
    dump(dict(season=C.SEASON, week=week, generated=now.isoformat(timespec="seconds"), stamp=scorecard.stamp(P),
              mean_factor=C.MEAN_FACTOR, window=C.ROLLING_WINDOW, cal_pass=P["CAL_PASS_SLOPE"], cal_comp=P["CAL_COMP_SLOPE"], default_scoring=C.DEFAULT_SCORING,
              players=len(proj), games=len(games), history_rows=len(hist), history_gaps=gaps[:6], asof_week=int(max(x["week"] for x in rows)),
              weather=dict(on=P["WEATHER_ON"], threshold=P["WX_WIND_THRESHOLD"]),
              first_kick=min((g["ko"] for g in games if g["ko"]), default=None),
              backtests=sorted(f[len("backtest_"):-5] for f in os.listdir(out) if f.startswith("backtest_") and f.endswith(".json"))),
         out, "meta.json")
    print(f"week {week}: projected {len(proj)} players in {len(games)} games; logged {logged} rows; scorecard has {sc['scored']} scored")
    return len(proj)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="site/data")
    ap.add_argument("--no-log", action="store_true")
    ap.add_argument("--no-weather", action="store_true")
    ap.add_argument("--week", type=int)
    a = ap.parse_args()
    sys.exit(0 if main(a.raw, a.out, not a.no_log, not a.no_weather, a.week) is not None else 1)

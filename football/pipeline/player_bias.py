"""Players who consistently beat or miss the projection and the line  ->  data/log/player_bias.csv (NFL), data/log/cfb_player_bias.csv (college) and their *_hist.csv
(research: nothing here feeds the model; the football twin of the basketball log)

    python -m pipeline.player_bias                  # rebuild both tables and append this week's flags to the history (run by the refresh workflow, soft-fail)
    python -m pipeline.player_bias --report         # forward test on the recorded history: did flagged players keep deviating in the weeks AFTER the flag?
    python -m pipeline.player_bias --backtest       # the same test on the season so far, replaying each week: flags from games up to week w, results in weeks after w

One row per (player, stat), rebuilt from scratch every run from the frozen pre-kick projections (data/log/accuracy_log.csv, cfb_log.csv; the log is written once per week so late news is not in it), the box scores
(data/raw/weekly.csv, cfb_weekly.csv) and the closing consensus line (lines_log.csv, cfb_lines_log.csv). Stats: pts (Full PPR), rushY, recY, rec, passY, plus carries / targets / attempts for the NFL.
Only games with a projection above the stat's floor count; a game where the player left early (his actual carries + targets + attempts under a quarter of the projected, with 8+ projected) is counted as an exit
and left out of the miss, so an injury is not read as a trait.
  resid = actual - projection, centred on the league mean miss for that stat (a flag should mean he is off compared with OTHER players, not that the model runs low for everyone).
  n, mean_resid (raw), vs_league, se, z = vs_league / se, first / second half (his own games in order, both vs_league), last3, exits.  Against the line: n_line, over_rate, mean_vs_line.
  flag_proj: 'over' / 'under' when n >= MIN_N, |z| >= Z_FLAG and both halves have the same sign.  flag_line: over_rate >= 0.75 or <= 0.25 on n_line >= MIN_N.
A flag describes the past. Whether it predicts the future is what --report / --backtest measure; football has only 4-9 games a player a season, so the thresholds are looser than basketball's.
"""
import csv, math, os, statistics as S, sys
from collections import defaultdict

LOG, RAW = "data/log", "data/raw"
MIN_N, Z_FLAG, LINE_HI, LINE_LO = 4, 1.5, 0.75, 0.25
FLOOR = {"pts": 4.0, "rushY": 10.0, "recY": 10.0, "rec": 1.0, "passY": 100.0, "car": 4.0, "tgt": 2.0, "att": 10.0}
COLS = ["pid", "name", "team", "pos", "stat", "n", "exits", "mean_proj", "mean_actual", "mean_resid", "vs_league", "resid_pct", "se", "z", "first_half", "second_half", "last3", "flag_proj",
        "n_line", "over_rate", "mean_vs_line", "flag_line", "last_week"]
HCOLS = ["asof", "pid", "name", "stat", "flag", "n", "vs_league", "z"]
f = lambda v: float(v or 0)


def fs(a, college):
    il = (a["interceptions"] + a["fumbles_lost"]) if college else (a["passing_interceptions"] + a["rushing_fumbles_lost"] + a["receiving_fumbles_lost"] + a["sack_fumbles_lost"])
    return (a["rushing_yards"] * .1 + a["receiving_yards"] * .1 + a["passing_yards"] * .04 + a["receptions"] + 6 * (a["rushing_tds"] + a["receiving_tds"])
            + 4 * a["passing_tds"] - il)


def games(league):
    """-> list of dict(pid, name, team, pos, week, stat -> (projection, actual), exit)"""
    college = league == "cfb"
    if college:
        from .cfb_model import load_rows
        act = {(r["playerId"], int(r["week"])): r for r in load_rows(f"{RAW}/cfb_weekly.csv")}
        logp, season = f"{LOG}/cfb_log.csv", "2026"
        key = "player_id"
    else:
        from .model import load_weekly
        act = {(r["player_id"], int(r["week"])): r for r in load_weekly(f"{RAW}/weekly.csv")}
        logp, season = f"{LOG}/accuracy_log.csv", "2026"
        key = "player_id"
    fro = {}
    for x in csv.DictReader(open(logp, newline="")):
        if x["season"] != season or x.get("late") == "1":
            continue
        k = (x[key], int(x["week"]))
        if k not in fro or x["logged_at"] > fro[k]["logged_at"]:
            fro[k] = x
    out = []
    for (pid, wk), x in fro.items():
        a = act.get((pid, wk))
        if not a:
            continue                                                      # did not play (no box-score row)
        if college:
            pr = {"pts": f(x["p_pts"]), "rushY": f(x["p_rushY"]), "recY": f(x["p_recY"]), "rec": f(x["p_rec"]), "passY": f(x["p_passY"])}
            ac = {"pts": fs(a, True), "rushY": f(a["rushing_yards"]), "recY": f(a["receiving_yards"]), "rec": f(a["receptions"]), "passY": f(a["passing_yards"])}
        else:
            pr = {"pts": f(x["p_pts"]), "rushY": f(x["p_rushY"]), "recY": f(x["p_recY"]), "rec": f(x["p_rec"]), "passY": f(x["p_passY"]), "car": f(x["car"]), "tgt": f(x["tgt"]), "att": f(x["att"])}
            ac = {"pts": fs(a, False), "rushY": f(a["rushing_yards"]), "recY": f(a["receiving_yards"]), "rec": f(a["receptions"]), "passY": f(a["passing_yards"]),
                  "car": f(a["carries"]), "tgt": f(a["targets"]), "att": f(a["attempts"])}
            popp, aopp = pr["car"] + pr["tgt"] + pr["att"], ac["car"] + ac["tgt"] + ac["att"]
        if college:                       # the college log has no projected volumes: opportunities from the projected yards (4.3 a carry, 7.0 an attempt) and receptions
            popp = f(x.get("p_rushY")) / 4.3 + f(x.get("p_rec")) + f(x.get("p_passY")) / 7.0
            aopp = f(a["carries"]) + f(a["receptions"]) + f(a["attempts"])
        exit_ = popp >= 8 and aopp < 0.25 * popp
        out.append(dict(pid=pid, name=x["name"], team=x["team"], pos=x["pos"], week=wk, kickoff=x["kickoff"][:10], vals={s: (pr[s], ac[s]) for s in pr}, exit=exit_))
    return out


def lines(league):
    p = f"{LOG}/{'cfb_lines_log' if league == 'cfb' else 'lines_log'}.csv"
    out = {}
    if os.path.exists(p):
        for x in csv.DictReader(open(p, newline="")):
            v = x["cons_line"] or x["pp_line"]
            if v:
                out[(x["player_id"], x["stat"], x["commence"][:10])] = float(v)
    return out


def build(gs, L, upto=None):
    """the table using only games up to week `upto` (default: everything)"""
    if upto is not None:
        gs = [g for g in gs if g["week"] <= upto]
    rows, lgmean = [], {}
    for s, fl in FLOOR.items():
        pts = [(g, g["vals"][s]) for g in gs if s in g["vals"] and g["vals"][s][0] >= fl and not g["exit"]]
        if not pts:
            continue
        lgmean[s] = S.mean(a - p for _, (p, a) in pts)
        by = defaultdict(list)
        for g, (p, a) in pts:
            by[g["pid"]].append((g, p, a))
        exits = defaultdict(int)
        for g in gs:
            if s in g["vals"] and g["vals"][s][0] >= fl and g["exit"]:
                exits[g["pid"]] += 1
        for pid, xs in by.items():
            xs.sort(key=lambda z: z[0]["week"])
            n = len(xs)
            if n < 3:
                continue
            res = [a - p - lgmean[s] for _, p, a in xs]
            mr = S.mean(res); se = (S.stdev(res) / math.sqrt(n)) if n > 1 else float("nan"); z = mr / se if se and se > 0 else float("nan")
            h = n // 2; a1, a2 = S.mean(res[:h]), S.mean(res[h:])
            fl_ = ""
            if n >= MIN_N and z == z and abs(z) >= Z_FLAG and a1 * a2 > 0:
                fl_ = "over" if mr > 0 else "under"
            ys = [(a, L[(pid, s, g["kickoff"])]) for g, p, a in xs if (pid, s, g["kickoff"]) in L and a != L[(pid, s, g["kickoff"])]]
            nl = len(ys); orr = sum(a > l for a, l in ys) / nl if nl else float("nan")
            fll = "" if nl < MIN_N else ("over" if orr >= LINE_HI else "under" if orr <= LINE_LO else "")
            g0 = xs[-1][0]
            mp = S.mean(p for _, p, _ in xs); ma = S.mean(a for _, _, a in xs)
            rows.append(dict(pid=pid, name=g0["name"], team=g0["team"], pos=g0["pos"], stat=s, n=n, exits=exits.get(pid, 0), mean_proj=mp, mean_actual=ma, mean_resid=mr + lgmean[s], vs_league=mr,
                             resid_pct=(mr + lgmean[s]) / mp if mp else float("nan"), se=se, z=z, first_half=a1, second_half=a2, last3=S.mean(res[-3:]), flag_proj=fl_, n_line=nl, over_rate=orr,
                             mean_vs_line=S.mean(a - l for a, l in ys) if nl else float("nan"), flag_line=fll, last_week=xs[-1][0]["week"]))
    return rows, lgmean


def write(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS); w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})


def forward(gs, rows, lgmean_all, asof):
    """for each flag in `rows` (built from games up to `asof`): the miss in games AFTER asof, minus the league's miss over the same games, signed so + = kept deviating"""
    res = []
    for r in rows:
        if not r["flag_proj"]:
            continue
        after = [g for g in gs if g["week"] > asof and r["stat"] in g["vals"] and g["vals"][r["stat"]][0] >= FLOOR[r["stat"]] and not g["exit"]]
        mine = [g["vals"][r["stat"]][1] - g["vals"][r["stat"]][0] for g in after if g["pid"] == r["pid"]]
        if not mine or not after:
            continue
        lg = S.mean(g["vals"][r["stat"]][1] - g["vals"][r["stat"]][0] for g in after)
        res.append((r["stat"], r["flag_proj"], len(mine), (S.mean(mine) - lg) * (1 if r["flag_proj"] == "over" else -1)))
    return res


def summarise(res, lab):
    if not res:
        print(f"{lab}: no flagged player has played since his flag yet"); return
    print(f"{lab}: {len(res)} flag-stat pairs with later games; mean forward miss in the flagged direction {S.mean(r[3] for r in res):+.2f} (0 = no persistence), kept the direction in {100 * sum(r[3] > 0 for r in res) / len(res):.0f}%")
    by = defaultdict(list)
    for r in res:
        by[r[0]].append(r[3])
    for s, v in sorted(by.items()):
        print(f"   {s:6} flags {len(v):4}  mean forward {S.mean(v):+7.2f}  kept {100 * sum(x > 0 for x in v) / len(v):3.0f}%")


def main():
    os.makedirs(LOG, exist_ok=True)
    for lg, out, hist in (("nfl", f"{LOG}/player_bias.csv", f"{LOG}/player_bias_hist.csv"), ("cfb", f"{LOG}/cfb_player_bias.csv", f"{LOG}/cfb_player_bias_hist.csv")):
        gs = games(lg); L = lines(lg)
        rows, _ = build(gs, L)
        rows.sort(key=lambda r: (r["flag_proj"] == "", r["n"] < MIN_N, -abs(r["z"]) if r["z"] == r["z"] else 0))     # flagged first, then the most extreme
        write(out, rows)
        wk = max((g["week"] for g in gs), default=0)
        h = list(csv.DictReader(open(hist))) if os.path.exists(hist) else []
        if str(wk) not in {x["asof"] for x in h}:
            with open(hist, "a", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=HCOLS)
                if not h:
                    w.writeheader()
                for r in rows:
                    if r["flag_proj"]:
                        w.writerow(dict(asof=wk, pid=r["pid"], name=r["name"], stat=r["stat"], flag=r["flag_proj"], n=r["n"], vs_league=round(r["vs_league"], 3), z=round(r["z"], 3)))
        fl = [r for r in rows if r["flag_proj"]]
        print(f"player_bias {lg}: {len(rows)} player-stat rows, {len({r['pid'] for r in rows})} players; flagged vs projection {len(fl)} ({sum(r['flag_proj'] == 'over' for r in fl)} over, {sum(r['flag_proj'] == 'under' for r in fl)} under); "
              f"flagged vs line {sum(1 for r in rows if r['flag_line'])}")


def report():
    for lg, hist in (("nfl", f"{LOG}/player_bias_hist.csv"), ("cfb", f"{LOG}/cfb_player_bias_hist.csv")):
        if not os.path.exists(hist):
            print(f"{lg}: no history yet"); continue
        gs = games(lg); res = []
        for r in csv.DictReader(open(hist)):
            rows = [dict(pid=r["pid"], stat=r["stat"], flag_proj=r["flag"])]
            res += forward(gs, rows, None, int(float(r["asof"])))
        summarise(res, lg.upper() + " recorded flags")


def backtest():
    for lg in ("nfl", "cfb"):
        gs = games(lg); L = lines(lg)
        weeks = sorted({g["week"] for g in gs})
        allres = []
        for w in weeks[:-1]:
            rows, _ = build(gs, L, upto=w)
            allres += forward(gs, rows, None, w)
        summarise(allres, f"{lg.upper()} backtest, every week's flags against the weeks after (weeks {weeks[0]}-{weeks[-1]})")


if __name__ == "__main__":
    report() if "--report" in sys.argv else backtest() if "--backtest" in sys.argv else main()

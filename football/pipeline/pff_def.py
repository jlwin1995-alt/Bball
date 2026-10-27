"""Defence test: do PFF defensive numbers explain what the model misses for the players who face that defence?

    python -m pipeline.pff_def        # needs data/raw/pff_hist/{defcoverage,defrun,passrush}_<s>.csv (pipeline.pff_hist --reports ...) and data/raw/history/*

Season-to-date, pre-game team features (each a ratio of sums regressed toward the league with K plays; grades are snap-weighted means):
  cov_ypc: receiving yards allowed per coverage snap       cov_tpc: targets per coverage snap       cov_grade: coverage grade
  run_stop: stop rate against the run (1 - stops / run-stop opportunities, so higher = worse defence)       run_grade: run-defence grade
  rush_pr: pressures per pass play (pass rush)
For every skill player-game (weeks 5+, 2023-25) the residual (actual - model projection) is regressed on the features for the stat it concerns, fitted on the other seasons (ridge),
and the mean absolute error with and without them is compared. Pooled OLS slopes with t-stats show whether any feature carries a signal at all.
"""
import csv, math, statistics
from . import config as C
from .model import load_weekly, nfl_core, derive, params
from .slate import load_csv, matchups
from .backtest import load_inj, INJ
from .cfb_totals import ridge, solve
from .pff_grades import FIX

FEATS = ("cov_ypc", "cov_tpc", "cov_grade", "run_stop", "run_grade", "rush_pr")
K = dict(cov_ypc=250.0, cov_tpc=250.0, cov_grade=250.0, run_stop=120.0, run_grade=250.0, rush_pr=150.0)


def fl(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def team_weeks(season, raw="data/raw"):
    """-> {feature: {(team, week): (numerator, denominator)}}"""
    out = {f: {} for f in FEATS}

    def add(f, team, wk, n, d):
        a = out[f].setdefault((FIX.get(team, team), wk), [0.0, 0.0])
        a[0] += n; a[1] += d

    with open(f"{raw}/pff_hist/defcoverage_{season}.csv", newline="") as f:
        for r in csv.DictReader(f):
            sn, wk = fl(r["snap_counts_coverage"]), int(r["week"])
            if sn <= 0:
                continue
            add("cov_ypc", r["team"], wk, fl(r["yards"]), sn)
            add("cov_tpc", r["team"], wk, fl(r["targets"]), sn)
            add("cov_grade", r["team"], wk, fl(r["grades_coverage_defense"]) * sn, sn)
    with open(f"{raw}/pff_hist/defrun_{season}.csv", newline="") as f:
        for r in csv.DictReader(f):
            opp, sn, wk = fl(r["run_stop_opp"]), fl(r["snap_counts_run"]), int(r["week"])
            if opp > 0:
                add("run_stop", r["team"], wk, opp - fl(r["stops"]), opp)
            if sn > 0:
                add("run_grade", r["team"], wk, fl(r["grades_run_defense"]) * sn, sn)
    agg = {}
    with open(f"{raw}/pff_hist/passrush_{season}.csv", newline="") as f:
        for r in csv.DictReader(f):
            k = (FIX.get(r["team"], r["team"]), int(r["week"]))
            a = agg.setdefault(k, [0.0, 0.0])
            a[0] += fl(r["total_pressures"]); a[1] = max(a[1], fl(r["snap_counts_pass_play"]))
    out["rush_pr"] = {k: v for k, v in agg.items() if v[1] > 0}
    return out


def feat_to_date(tw, f, team, week, lg):
    n = sum(v[0] for (t, w), v in tw[f].items() if t == team and w < week)
    d = sum(v[1] for (t, w), v in tw[f].items() if t == team and w < week)
    return (n + K[f] * lg) / (d + K[f]) - lg


def collect(seasons, raw="data/raw"):
    P = params()
    W = C.DEFAULT_SCORING
    rows = []
    for season in seasons:
        tw = team_weeks(season, raw)
        load_inj(season, raw)
        wrows = load_weekly(f"{raw}/history/weekly_{season}.csv")
        sched = load_csv(f"{raw}/history/schedule_{season}.csv")
        by_week = {}
        for r in wrows:
            by_week.setdefault(int(r["week"]), []).append(r)
        for wk in range(5, max(by_week) + 1):
            mu = matchups(sched, wk)
            if not mu:
                continue
            hist = [r for x in range(1, wk) for r in by_week.get(x, [])]
            outs = {r["gsis_id"] for r in INJ.get(season, []) if int(float(r["week"] or 0)) == wk and r["report_status"] == "Out"}
            core = nfl_core(hist, mu, None, dict(P, OUT_IDS=outs))
            lg = {}
            for f in FEATS:
                n = sum(v[0] for (t, w), v in tw[f].items() if w < wk)
                d = sum(v[1] for (t, w), v in tw[f].items() if w < wk)
                lg[f] = n / d if d else 0.0
            act = {r["player_id"]: r for r in by_week[wk]}
            cache = {}
            for pl in core["players"]:
                a = act.get(pl["id"])
                if a is None:
                    continue
                if pl["opp"] not in cache:
                    cache[pl["opp"]] = {f: feat_to_date(tw, f, pl["opp"], wk, lg[f]) for f in FEATS}
                x = cache[pl["opp"]]
                d = derive(pl, W, P)
                base = dict(season=season, week=wk, grp=pl["grp"], **x)
                if pl["grp"] in ("WR", "TE", "RB") and pl["tgt"] >= 3:
                    rows.append(dict(base, kind="rec", p_y=d["recY"], a_y=fl(a["receiving_yards"]), p_n=d["rec"], a_n=fl(a["receptions"])))
                if pl["grp"] == "RB" and pl["car"] >= 8:
                    rows.append(dict(base, kind="rush", p_y=d["rushY"], a_y=fl(a["rushing_yards"]), p_n=pl["car"], a_n=fl(a["carries"])))
                if pl["grp"] == "QB" and pl["att"] >= 20 and fl(a["attempts"]) >= 10:
                    rows.append(dict(base, kind="pass", p_y=d["passY"], a_y=fl(a["passing_yards"]), p_n=d["comp"], a_n=fl(a["completions"])))
    return rows


def loso(rows, feats, py, ay, label):
    base = fit = 0.0
    for s in sorted({r["season"] for r in rows}):
        tr, te = [r for r in rows if r["season"] != s], [r for r in rows if r["season"] == s]
        coef, mean, sd, ym = ridge([[r[f] for f in feats] for r in tr], [r[ay] - r[py] for r in tr], 1.0)
        for r in te:
            pred = ym + sum(c * (r[f] - m) / sdv for c, f, m, sdv in zip(coef, feats, mean, sd))
            base += abs(r[ay] - r[py]); fit += abs(r[ay] - r[py] - pred)
    n = len(rows)
    X = [[1.0] + [r[f] for f in feats] for r in rows]
    y = [r[ay] - r[py] for r in rows]
    k = len(X[0])
    xtx = [[sum(x[i] * x[j] for x in X) for j in range(k)] for i in range(k)]
    beta = solve([r[:] for r in xtx], [sum(x[i] * yy for x, yy in zip(X, y)) for i in range(k)])
    res = [yy - sum(b * x for b, x in zip(beta, xi)) for xi, yy in zip(X, y)]
    s2 = sum(e * e for e in res) / (len(y) - k)
    inv = [solve([r[:] for r in xtx], [1.0 if i == j else 0.0 for i in range(k)]) for j in range(k)]
    slopes = ", ".join(f"{f} {beta[i + 1] * statistics.pstdev(r[f] for r in rows):+.2f} (t {beta[i + 1] / math.sqrt(s2 * inv[i + 1][i + 1]):+.1f})" for i, f in enumerate(feats))
    print(f"{label:34} n={n:5}  MAE {base / n:.3f} -> {fit / n:.3f} ({(fit - base) / base * 100:+.1f}%) | per 1 sd: {slopes}", flush=True)


if __name__ == "__main__":
    rows = collect([2023, 2024, 2025])
    sets = {"rec": (("cov_ypc", "cov_tpc", "cov_grade"), "receiving"), "rush": (("run_stop", "run_grade"), "rushing"), "pass": (("cov_ypc", "cov_grade", "rush_pr"), "passing")}
    for kind, (feats, name) in sets.items():
        sub = [r for r in rows if r["kind"] == kind]
        if kind == "rec":
            for g in ("WR", "TE", "RB", None):
                s2 = [r for r in sub if g is None or r["grp"] == g]
                loso(s2, feats, "p_y", "a_y", f"{g or 'all'} receiving yards vs coverage")
                loso(s2, feats, "p_n", "a_n", f"{g or 'all'} receptions vs coverage")
        else:
            loso(sub, feats, "p_y", "a_y", f"{name} yards")
            loso(sub, feats, "p_n", "a_n", f"{name} {'carries' if kind == 'rush' else 'completions'}")

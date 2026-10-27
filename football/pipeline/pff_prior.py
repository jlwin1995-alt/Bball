"""PFF priors for thin-sample players: do last season's PFF route / target / yardage rates explain what the model misses for players with few games this season?

    python -m pipeline.pff_prior        # needs data/raw/pff_hist/pff_receiving_<s-1>.csv and <s>.csv, data/raw/history/*

Player-weeks (weeks 5+, 2024-25) of WR / TE / RB with fewer than THIN games in the model's history (new players, backups, returning from injury) who played. Features from the PREVIOUS
season's PFF rows (routes-weighted): route rate (routes / team pass plays), targets per route, yards per route, pass-route grade; all regressed with K routes toward the position.
Residual (actual - projection) of targets, receptions and receiving yards is regressed on them, fitted on the other season (ridge); MAE with and without, pooled slopes with t-stats.
Needs a previous season of PFF rows, so players with no PFF row last year (rookies) are reported separately and get a zero adjustment.
"""
import csv, math, statistics
from . import config as C
from .analysis import name_key
from .model import load_weekly, nfl_core, derive, params
from .slate import load_csv, matchups
from .backtest import load_inj, INJ
from .cfb_totals import ridge, solve
from .pff_routes import TEAM_FIX, load_pff

FEATS = ("rr", "tprr", "yprr", "grade")
THIN = 3
K_R = 150.0


def prior_table(season, raw="data/raw"):
    """-> {name_key: dict(rr, tprr, yprr, grade)} from the previous season's rows, regressed toward the position."""
    pff = load_pff(season, raw)
    agg, pos_t, pos_r, pos_y = {}, {}, {}, {}
    with open(f"{raw}/pff_hist/pff_receiving_{season}.csv", newline="") as f:
        grades = {}
        for r in csv.DictReader(f):
            g = float(r["grades_pass_route"] or 0)
            grades.setdefault((name_key(r["player"]), TEAM_FIX.get(r["team"], r["team"]), int(r["week"])), g)
    for (n, t, w), v in pff.items():
        a = agg.setdefault(n, dict(routes=0.0, pp=0.0, tg=0.0, yd=0.0, gs=0.0, pos=v["pos"]))
        a["routes"] += v["routes"]; a["pp"] += v["team_pp"] if v["routes"] > 0 else 0.0; a["tg"] += v["targets"]; a["pos"] = v["pos"]
        a["gs"] += grades.get((n, t, w), 0.0) * v["routes"]
    with open(f"{raw}/pff_hist/pff_receiving_{season}.csv", newline="") as f:
        for r in csv.DictReader(f):
            n = name_key(r["player"])
            if n in agg:
                agg[n]["yd"] += float(r["yards"] or 0)
    for a in agg.values():
        p = a["pos"]
        pos_t[p] = pos_t.get(p, 0.0) + a["tg"]; pos_r[p] = pos_r.get(p, 0.0) + a["routes"]; pos_y[p] = pos_y.get(p, 0.0) + a["yd"]
    out = {}
    for n, a in agg.items():
        if a["routes"] < 20:
            continue
        p = a["pos"]
        lg_t, lg_y = pos_t[p] / pos_r[p], pos_y[p] / pos_r[p]
        lg_rr = statistics.mean(x["routes"] / x["pp"] for x in agg.values() if x["pos"] == p and x["pp"] > 0 and x["routes"] > 20)
        lg_g = sum(x["gs"] for x in agg.values() if x["pos"] == p) / pos_r[p]
        k = K_R
        out[n] = dict(rr=(a["routes"] + k * lg_rr * 0) / (a["pp"] + 0) if False else a["routes"] / a["pp"] - lg_rr,
                      tprr=(a["tg"] + k * lg_t) / (a["routes"] + k) - lg_t, yprr=(a["yd"] + k * lg_y) / (a["routes"] + k) - lg_y,
                      grade=(a["gs"] + k * lg_g) / (a["routes"] + k) - lg_g)
    return out


def collect(seasons, raw="data/raw"):
    P = params()
    W = C.DEFAULT_SCORING
    rows = []
    for season in seasons:
        prior = prior_table(season - 1, raw)
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
            act = {r["player_id"]: r for r in by_week[wk]}
            for pl in core["players"]:
                a = act.get(pl["id"])
                if a is None or pl["grp"] not in ("WR", "TE", "RB") or pl["g"] >= THIN:
                    continue
                d = derive(pl, W, P)
                if d["pts"] < 2.0:
                    continue
                x = prior.get(name_key(pl["name"]))
                rows.append(dict(season=season, week=wk, has=x is not None, **(x or {f: 0.0 for f in FEATS}),
                                 p_tgt=pl["tgt"], a_tgt=a["targets"], p_rec=d["rec"], a_rec=a["receptions"], p_ry=d["recY"], a_ry=a["receiving_yards"]))
    return rows


def loso(rows, pk, ak, label):
    base = fit = 0.0
    for s in sorted({r["season"] for r in rows}):
        tr, te = [r for r in rows if r["season"] != s and r["has"]], [r for r in rows if r["season"] == s]
        coef, mean, sd, ym = ridge([[r[f] for f in FEATS] for r in tr], [r[ak] - r[pk] for r in tr], 1.0)
        for r in te:
            e = r[ak] - r[pk]
            pred = ym + sum(c * (r[f] - m) / sdv for c, f, m, sdv in zip(coef, FEATS, mean, sd)) if r["has"] else 0.0
            base += abs(e); fit += abs(e - pred)
    n = len(rows)
    sub = [r for r in rows if r["has"]]
    X = [[1.0] + [r[f] for f in FEATS] for r in sub]
    y = [r[ak] - r[pk] for r in sub]
    k = len(X[0])
    xtx = [[sum(x[i] * x[j] for x in X) for j in range(k)] for i in range(k)]
    beta = solve([r[:] for r in xtx], [sum(x[i] * yy for x, yy in zip(X, y)) for i in range(k)])
    s2 = sum((yy - sum(b * x for b, x in zip(beta, xi))) ** 2 for xi, yy in zip(X, y)) / (len(y) - k)
    inv = [solve([r[:] for r in xtx], [1.0 if i == j else 0.0 for i in range(k)]) for j in range(k)]
    sl = ", ".join(f"{f} {beta[i + 1] * statistics.pstdev(r[f] for r in sub):+.2f} (t {beta[i + 1] / math.sqrt(s2 * inv[i + 1][i + 1]):+.1f})" for i, f in enumerate(FEATS))
    print(f"{label:11} n={n} ({len(sub)} with a prior)  bias {statistics.mean(r[ak] - r[pk] for r in rows):+.2f}  MAE {base / n:.3f} -> {fit / n:.3f} ({(fit - base) / base * 100:+.1f}%) | per 1 sd: {sl}", flush=True)


if __name__ == "__main__":
    rows = collect([2024, 2025])
    print(f"{len(rows)} thin-sample player-weeks (g < {THIN}), {sum(r['has'] for r in rows)} with a PFF row last season")
    loso(rows, "p_tgt", "a_tgt", "targets")
    loso(rows, "p_rec", "a_rec", "receptions")
    loso(rows, "p_ry", "a_ry", "rec yards")

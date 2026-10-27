"""QB line and pressure test: do PFF pass-blocking and pass-rush numbers explain what the model misses for quarterbacks?

    python -m pipeline.pff_qbline        # needs data/raw/pff_hist/passblock_<s>.csv / passrush_<s>.csv (pipeline.pff_hist --reports passblock passrush) and data/raw/history/*

For every quarterback-game (weeks 5+, projected 20+ attempts, 2023-25): the model's projection (nfl_core / derive) against the actual passing yards, completions and sacks, and two
pre-game numbers from PFF: his offensive line's pressures allowed per pass play and the opposing pass rush's pressures per dropback, each the season-to-date total regressed toward the
league rate (K plays) and expressed against the league. Residual (actual - projection) is regressed on the two numbers, fitted on the other seasons (leave-one-season-out).
"""
import csv, math, statistics
from . import config as C
from .model import load_weekly, nfl_core, derive, params
from .slate import load_csv, matchups
from .backtest import load_inj, INJ
from .cfb_totals import ridge
from .pff_grades import FIX

K_PLAYS = 150.0


def load_team_weeks(season, raw="data/raw"):
    """-> (ol, rush): (team, week) -> (pressures allowed, pass plays) and (team, week) -> (pressures, dropbacks faced)."""
    ol, rush = {}, {}
    for kind, tgt, pcol in (("passblock", ol, "pressures_allowed"), ("passrush", rush, "total_pressures")):
        agg = {}
        with open(f"{raw}/pff_hist/{kind}_{season}.csv", newline="") as f:
            for r in csv.DictReader(f):
                k = (FIX.get(r["team"], r["team"]), int(r["week"]))
                a = agg.setdefault(k, [0.0, 0.0])
                a[0] += float(r[pcol] or 0)
                a[1] = max(a[1], float(r["snap_counts_pass_play"] or 0))
        tgt.update({k: tuple(v) for k, v in agg.items() if v[1] > 0})
    return ol, rush


def rate_to_date(tw, team, week, lg, k=K_PLAYS):
    p = sum(v[0] for (t, w), v in tw.items() if t == team and w < week)
    n = sum(v[1] for (t, w), v in tw.items() if t == team and w < week)
    return (p + k * lg) / (n + k) - lg


def collect(seasons, raw="data/raw"):
    P = params()
    W = C.DEFAULT_SCORING
    rows = []
    for season in seasons:
        ol, rush = load_team_weeks(season, raw)
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
            lg_ol = sum(v[0] for (t, w), v in ol.items() if w < wk) / max(1.0, sum(v[1] for (t, w), v in ol.items() if w < wk))
            lg_rush = sum(v[0] for (t, w), v in rush.items() if w < wk) / max(1.0, sum(v[1] for (t, w), v in rush.items() if w < wk))
            act = {r["player_id"]: r for r in by_week[wk]}
            for pl in core["players"]:
                a = act.get(pl["id"])
                if pl["grp"] != "QB" or a is None or pl["att"] < 20 or a["attempts"] < 10:
                    continue
                d = derive(pl, W, P)
                rows.append(dict(season=season, week=wk, x_ol=rate_to_date(ol, pl["team"], wk, lg_ol), x_rush=rate_to_date(rush, pl["opp"], wk, lg_rush),
                                 p_py=d["passY"], a_py=a["passing_yards"], p_comp=d["comp"], a_comp=a["completions"], p_sack=d["sacks"], a_sack=a["sacks_suffered"]))
    return rows


def loso(rows, pk, ak, label):
    base = fit = n = 0
    pooled = []
    for s in sorted({r["season"] for r in rows}):
        tr, te = [r for r in rows if r["season"] != s], [r for r in rows if r["season"] == s]
        X = [[r["x_ol"], r["x_rush"]] for r in tr]
        y = [r[ak] - r[pk] for r in tr]
        coef, mean, sd, ym = ridge(X, y, 1.0)
        for r in te:
            pred = ym + sum(c * (x - m) / sdv for c, x, m, sdv in zip(coef, [r["x_ol"], r["x_rush"]], mean, sd))
            base += abs(r[ak] - r[pk]); fit += abs(r[ak] - r[pk] - pred); n += 1
    # pooled OLS t-stats
    X = [[1.0, r["x_ol"], r["x_rush"]] for r in rows]
    y = [r[ak] - r[pk] for r in rows]
    k = 3
    xtx = [[sum(x[i] * x[j] for x in X) for j in range(k)] for i in range(k)]
    xty = [sum(x[i] * yy for x, yy in zip(X, y)) for i in range(k)]
    from .cfb_totals import solve
    beta = solve([r[:] for r in xtx], xty[:])
    res = [yy - sum(b * x for b, x in zip(beta, xi)) for xi, yy in zip(X, y)]
    s2 = sum(e * e for e in res) / (len(y) - k)
    inv = [solve([r[:] for r in xtx], [1.0 if i == j else 0.0 for i in range(k)]) for j in range(k)]
    se = [math.sqrt(s2 * inv[i][i]) for i in range(k)]
    print(f"{label:12} n={n}  MAE as projected {base / n:.3f} -> with PFF line/pressure {fit / n:.3f} ({(fit - base) / base * 100:+.1f}%) | pooled: own line {beta[1]:+.2f} (t {beta[1] / se[1]:+.1f}), opposing rush {beta[2]:+.2f} (t {beta[2] / se[2]:+.1f})")


if __name__ == "__main__":
    rows = collect([2023, 2024, 2025])
    sd_ol = statistics.pstdev(r["x_ol"] for r in rows); sd_rush = statistics.pstdev(r["x_rush"] for r in rows)
    print(f"{len(rows)} QB games; sd of own-line pressure rate {sd_ol:.4f}, of opposing rush {sd_rush:.4f} (per pass play)")
    loso(rows, "p_py", "a_py", "pass yards")
    loso(rows, "p_comp", "a_comp", "completions")
    loso(rows, "p_sack", "a_sack", "sacks")

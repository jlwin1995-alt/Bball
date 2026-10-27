"""Game-script test: do the point spread, game total and the two teams' pace explain what the model misses in TEAM volume?

    python -m pipeline.game_script        # needs data/raw/history/{weekly,schedule}_<s>.csv

For every team-game (weeks 5+, 2023-25): the model's projected team pass attempts, carries and targets (sum of its players' projections, nfl_core) against the actual, and four
pre-game numbers: the team's spread (+ = favoured), the game total, the team's own pace (pass attempts + carries a game, season to date, regressed toward the league) and the
opponent's pace. The miss (actual - projected) is regressed on them, fitted on the other seasons (ridge), MAE with and without compared; pooled OLS slopes with t-stats.
"""
import math, statistics
from . import config as C
from .model import load_weekly, nfl_core, derive, params
from .slate import load_csv, matchups
from .cfb_totals import ridge, solve

FEATS = ("spread", "total", "own_pace", "opp_pace")
K_GAMES = 4.0


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def collect(seasons, raw="data/raw"):
    P = params()
    rows = []
    for season in seasons:
        wrows = load_weekly(f"{raw}/history/weekly_{season}.csv")
        sched = load_csv(f"{raw}/history/schedule_{season}.csv")
        line = {}
        for g in sched:
            sp, tl = num(g.get("spread_line")), num(g.get("total_line"))
            if sp is not None and tl is not None:
                line[(g["home_team"], int(g["week"]))] = (sp, tl)
                line[(g["away_team"], int(g["week"]))] = (-sp, tl)
        by_week = {}
        for r in wrows:
            by_week.setdefault(int(r["week"]), []).append(r)
        for wk in range(5, max(by_week) + 1):
            mu = matchups(sched, wk)
            if not mu:
                continue
            hist = [r for x in range(1, wk) for r in by_week.get(x, [])]
            core = nfl_core(hist, mu, None, dict(P))
            vol, games = {}, {}
            for r in hist:
                vol[(r["team"], int(r["week"]))] = vol.get((r["team"], int(r["week"])), 0.0) + r["attempts"] + r["carries"]
            for (t, w), v in vol.items():
                games.setdefault(t, []).append(v)
            lg = statistics.mean(vol.values())
            pace = lambda t: (sum(games.get(t, [])) + K_GAMES * lg) / (len(games.get(t, [])) + K_GAMES) - lg
            proj, act = {}, {}
            for pl in core["players"]:
                p = proj.setdefault(pl["team"], dict(att=0.0, car=0.0, tgt=0.0, opp=pl["opp"]))
                p["att"] += pl["att"]; p["car"] += pl["car"]; p["tgt"] += pl["tgt"]
            for r in by_week[wk]:
                a = act.setdefault(r["team"], dict(att=0.0, car=0.0, tgt=0.0))
                a["att"] += r["attempts"]; a["car"] += r["carries"]; a["tgt"] += r["targets"]
            for t, p in proj.items():
                if t not in act or (t, wk) not in line:
                    continue
                sp, tl = line[(t, wk)]
                rows.append(dict(season=season, week=wk, team=t, spread=sp, total=tl, own_pace=pace(t), opp_pace=pace(p["opp"]),
                                 **{f"p_{k}": p[k] for k in ("att", "car", "tgt")}, **{f"a_{k}": act[t][k] for k in ("att", "car", "tgt")}))
    return rows


def loso(rows, k, feats=FEATS):
    base = fit = 0.0
    for s in sorted({r["season"] for r in rows}):
        tr, te = [r for r in rows if r["season"] != s], [r for r in rows if r["season"] == s]
        coef, mean, sd, ym = ridge([[r[f] for f in feats] for r in tr], [r[f"a_{k}"] - r[f"p_{k}"] for r in tr], 1.0)
        for r in te:
            e = r[f"a_{k}"] - r[f"p_{k}"]
            base += abs(e); fit += abs(e - (ym + sum(c * (r[f] - m) / sdv for c, f, m, sdv in zip(coef, feats, mean, sd))))
    n = len(rows)
    X = [[1.0] + [r[f] for f in feats] for r in rows]
    y = [r[f"a_{k}"] - r[f"p_{k}"] for r in rows]
    kk = len(X[0])
    xtx = [[sum(x[i] * x[j] for x in X) for j in range(kk)] for i in range(kk)]
    beta = solve([r[:] for r in xtx], [sum(x[i] * yy for x, yy in zip(X, y)) for i in range(kk)])
    res = [yy - sum(b * x for b, x in zip(beta, xi)) for xi, yy in zip(X, y)]
    s2 = sum(e * e for e in res) / (n - kk)
    inv = [solve([r[:] for r in xtx], [1.0 if i == j else 0.0 for i in range(kk)]) for j in range(kk)]
    sl = ", ".join(f"{f} {beta[i + 1] * statistics.pstdev(r[f] for r in rows):+.2f} (t {beta[i + 1] / math.sqrt(s2 * inv[i + 1][i + 1]):+.1f})" for i, f in enumerate(feats))
    print(f"team {k:4} n={n}  bias {statistics.mean(y):+.2f}  MAE {base / n:.3f} -> {fit / n:.3f} ({(fit - base) / base * 100:+.1f}%) | per 1 sd: {sl}", flush=True)


def run_full(rows, raw="data/raw"):
    """The adjustment carried through the whole model: scale each team's projected pass attempts, carries and targets by (projection + fitted miss) / projection (fitted on the other
    seasons), re-derive every player's stats, compare with the unadjusted model. -> list of (stat, model projection, adjusted projection, actual)."""
    from .backtest import actual, load_inj, INJ
    P = params()
    W = C.DEFAULT_SCORING
    out = []
    fit = {}
    for s in sorted({r["season"] for r in rows}):
        tr = [r for r in rows if r["season"] != s]
        for k in ("att", "car", "tgt"):
            fit[(s, k)] = ridge([[r[f] for f in FEATS] for r in tr], [r[f"a_{k}"] - r[f"p_{k}"] for r in tr], 1.0)
    by_team = {(r["season"], r["week"], r["team"]): r for r in rows}
    for season in sorted({r["season"] for r in rows}):
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
                a, tr = act.get(pl["id"]), by_team.get((season, wk, pl["team"]))
                if a is None or tr is None:
                    continue
                adj = {}
                for k in ("att", "car", "tgt"):
                    coef, mean, sd, ym = fit[(season, k)]
                    pred = ym + sum(c * (tr[f] - m) / sdv for c, f, m, sdv in zip(coef, FEATS, mean, sd))
                    adj[k] = max(0.5, min(1.5, (tr[f"p_{k}"] + pred) / tr[f"p_{k}"])) if tr[f"p_{k}"] else 1.0
                d0 = derive(pl, W, P)
                d1 = derive(dict(pl, att=pl["att"] * adj["att"], car=pl["car"] * adj["car"], tgt=pl["tgt"] * adj["tgt"]), W, P)
                if d0["pts"] < 3.0 and d1["pts"] < 3.0:
                    continue
                s_ = actual(a, W)
                for st, k0, ak in (("rush yards", "rushY", a["rushing_yards"]), ("receptions", "rec", a["receptions"]), ("rec yards", "recY", a["receiving_yards"]),
                                   ("pass yards", "passY", a["passing_yards"]), ("completions", "comp", a["completions"]), ("points", "pts", s_["pts"])):
                    if st in ("pass yards", "completions") and pl["grp"] != "QB":
                        continue
                    out.append((st, d0[k0], d1[k0], ak))
    return out


if __name__ == "__main__":
    rows = collect([2023, 2024, 2025])
    print(f"{len(rows)} team-games; sd spread {statistics.pstdev(r['spread'] for r in rows):.1f}, total {statistics.pstdev(r['total'] for r in rows):.1f}")
    for k in ("att", "car", "tgt"):
        loso(rows, k)
    print("--- carried through the whole model (player level) ---")
    res = run_full(rows)
    for st in ("rush yards", "receptions", "rec yards", "pass yards", "completions", "points"):
        r = [x for x in res if x[0] == st]
        m0, m1 = (sum(abs(x[i] - x[3]) for x in r) / len(r) for i in (1, 2))
        print(f"{st:11} n={len(r):5}  MAE {m0:.3f} -> {m1:.3f} ({(m1 - m0) / m0 * 100:+.1f}%)  bias {sum(x[1] - x[3] for x in r) / sum(x[3] for x in r) * 100:+.1f}% -> {sum(x[2] - x[3] for x in r) / sum(x[3] for x in r) * 100:+.1f}%", flush=True)

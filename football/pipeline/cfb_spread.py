"""College spread and total model: ridge team ratings from scores, evaluated walk-forward against the closing lines.

    python -m pipeline.cfb_spread [--tune]

MARGIN: a rating per team (points better than an average FBS team), margin = r_home - r_away + HFA (none at a neutral site). Fitted by iterated
ridge regression toward a PRIOR (last season's rating shrunk by RHO), so a team with few games stays near its prior. TOTAL: a "total tendency" per team
(pace + offence + defence in one number): total = league total + t_home + t_away, ridge toward 0.
Everything is walk-forward: a week is predicted from the games before it. The market's closing line is the benchmark; the interesting output is BETA,
how much of (model - market) is worth adding to the market.

Sign convention (as books print): home_spread NEGATIVE = home favoured, so the market margin (home - away) is -home_spread.
"""
import argparse, csv, json, math, os, statistics
from . import config as C


def load_games(raw="data/raw"):
    """-> dict season -> list of dict(id, week, home, away, hp, ap, neutral, done), plus lines {(season, id): (home_spread, total)}."""
    games, lines = {}, {}
    sources = [(C.SEASON, f"{raw}/cfb_games.csv", f"{raw}/cfb_game_lines.csv")]
    for y in (C.SEASON - 1, C.SEASON - 2):
        sources.append((y, f"{raw}/history/cfb_games_{y}.csv", f"{raw}/history/cfb_game_lines_{y}.csv"))
    for y, gp, lp in sources:
        if os.path.exists(gp):
            with open(gp, newline="") as f:
                for r in csv.DictReader(f):
                    try:
                        wk = int(float(r["week"]))
                    except ValueError:
                        continue
                    done = str(r["completed"]).lower() == "true" and r["homePoints"] not in ("", None) and r["awayPoints"] not in ("", None)
                    games.setdefault(y, []).append(dict(id=r["id"], week=wk, home=r["homeTeam"], away=r["awayTeam"], neutral=str(r["neutralSite"]).lower() == "true", done=done,
                                                        hp=float(r["homePoints"]) if done else None, ap=float(r["awayPoints"]) if done else None, date=r["startDate"]))
        if os.path.exists(lp):
            with open(lp, newline="") as f:
                for r in csv.DictReader(f):
                    sp = float(r["home_spread"]) if r["home_spread"] not in ("", None) else None
                    tt = float(r["total"]) if r["total"] not in ("", None) else None
                    lines[(y, r["id"])] = (sp, tt)
    return games, lines


def fit_margin(games, prior, lam, rho, iters=80):
    """Ridge team ratings + a home-field term from completed games (list of dict). Returns (ratings, hfa)."""
    teams = {}
    for g in games:
        teams.setdefault(g["home"], []).append((g, True))
        teams.setdefault(g["away"], []).append((g, False))
    pri = {t: rho * prior.get(t, 0.0) for t in teams}
    r = dict(pri)
    hfa = C.CFB_SPREAD_HFA
    for _ in range(iters):
        new = {}
        for t, gs in teams.items():
            num = lam * pri[t]
            den = lam
            for g, is_home in gs:
                m = g["hp"] - g["ap"]
                h = 0.0 if g["neutral"] else hfa
                if is_home:
                    obs = m - h + r.get(g["away"], 0.0)
                else:
                    obs = -m + h + r.get(g["home"], 0.0)
                num += obs
                den += 1.0
            new[t] = num / den
        r = new
        res = [g["hp"] - g["ap"] - (r[g["home"]] - r[g["away"]]) for g in games if not g["neutral"]]
        if res:
            hfa = 0.5 * hfa + 0.5 * (sum(res) / len(res))        # damped, so a thin early sample does not swing it
    return r, hfa


def fit_total(games, lam=C.CFB_TOTAL_LAM, iters=60):
    tot = [g["hp"] + g["ap"] for g in games]
    mu = sum(tot) / len(tot)
    teams = {}
    for g in games:
        teams.setdefault(g["home"], []).append(g)
        teams.setdefault(g["away"], []).append(g)
    a = {t: 0.0 for t in teams}
    for _ in range(iters):
        new = {}
        for t, gs in teams.items():
            num = den = 0.0
            den = lam
            for g in gs:
                opp = g["away"] if g["home"] == t else g["home"]
                num += (g["hp"] + g["ap"]) - mu - a.get(opp, 0.0)
                den += 1.0
            new[t] = num / den
        a = new
    return mu, a


def predict(g, rat, hfa, mu, ta):
    m = rat.get(g["home"], 0.0) - rat.get(g["away"], 0.0) + (0.0 if g["neutral"] else hfa)
    t = mu + ta.get(g["home"], 0.0) + ta.get(g["away"], 0.0)
    return m, t


def season_ratings(games, prior, lam, rho):
    done = [g for g in games if g["done"]]
    return fit_margin(done, prior, lam, rho)[0] if done else {}


def walk_forward(games_by_season, season, lam, rho, first_week=2):
    """Predict every game of `season` week by week from the earlier weeks (and last season as the prior). -> list of dict(game + model margin/total)."""
    prev = games_by_season.get(season - 1, [])
    prior = season_ratings(prev, {}, lam, 1.0) if prev else {}
    out = []
    cur = games_by_season.get(season, [])
    for wk in sorted({g["week"] for g in cur}):
        if wk < first_week:
            continue
        past = [g for g in cur if g["done"] and g["week"] < wk]
        if len(past) < 40:
            continue
        rat, hfa = fit_margin(past, prior, lam, rho)
        mu, ta = fit_total(past)
        for g in (x for x in cur if x["week"] == wk):
            m, t = predict(g, rat, hfa, mu, ta)
            out.append(dict(g, model_margin=m, model_total=t, season=season))
    return out


def evaluate(preds, lines):
    """MAE of margin and total against the actual result for the model and (where there is a line) the market, plus BETA and the ATS record by edge."""
    rows = []
    for p in preds:
        if not p["done"]:
            continue
        sp, tt = lines.get((p["season"], p["id"]), (None, None))
        rows.append(dict(p, mkt_margin=None if sp is None else -sp, mkt_total=tt, actual=p["hp"] - p["ap"], atotal=p["hp"] + p["ap"]))
    res = dict(n=len(rows))
    if not rows:
        return res
    res["model_margin_mae"] = round(sum(abs(r["model_margin"] - r["actual"]) for r in rows) / len(rows), 3)
    res["zero_margin_mae"] = round(sum(abs(r["actual"]) for r in rows) / len(rows), 3)
    res["model_total_mae"] = round(sum(abs(r["model_total"] - r["atotal"]) for r in rows) / len(rows), 3)
    res["avg_total_mae"] = round(sum(abs(statistics.mean(x["atotal"] for x in rows) - r["atotal"]) for r in rows) / len(rows), 3)
    ln = [r for r in rows if r["mkt_margin"] is not None]
    res["n_lines"] = len(ln)
    if len(ln) >= 30:
        res["mkt_margin_mae"] = round(sum(abs(r["mkt_margin"] - r["actual"]) for r in ln) / len(ln), 3)
        res["model_margin_mae_on_lines"] = round(sum(abs(r["model_margin"] - r["actual"]) for r in ln) / len(ln), 3)
        x = [r["model_margin"] - r["mkt_margin"] for r in ln]
        y = [r["actual"] - r["mkt_margin"] for r in ln]
        sxx = sum(v * v for v in x)
        res["beta"] = round(sum(a * b for a, b in zip(x, y)) / sxx, 3) if sxx else None
        res["edge_sd"] = round(math.sqrt(sxx / len(x)), 2)
        buckets = {}
        for r, e in zip(ln, x):
            cover = r["actual"] - r["mkt_margin"]
            if cover == 0:
                continue
            side_home = e > 0
            hit = (cover > 0) == side_home
            k = "edge >= 6" if abs(e) >= 6 else "edge 3-6" if abs(e) >= 3 else "edge < 3"
            b = buckets.setdefault(k, [0, 0])
            b[0] += 1
            b[1] += hit
        res["ats"] = {k: dict(n=v[0], hit=v[1], pct=round(v[1] / v[0] * 100, 1)) for k, v in sorted(buckets.items())}
    lt = [r for r in rows if r["mkt_total"] is not None]
    if len(lt) >= 30:
        res["mkt_total_mae"] = round(sum(abs(r["mkt_total"] - r["atotal"]) for r in lt) / len(lt), 3)
        res["model_total_mae_on_lines"] = round(sum(abs(r["model_total"] - r["atotal"]) for r in lt) / len(lt), 3)
        x = [r["model_total"] - r["mkt_total"] for r in lt]
        y = [r["atotal"] - r["mkt_total"] for r in lt]
        sxx = sum(v * v for v in x)
        res["total_beta"] = round(sum(a * b for a, b in zip(x, y)) / sxx, 3) if sxx else None
    return res


def main(raw="data/raw", tune=False):
    games, lines = load_games(raw)
    print({y: (len(g), sum(1 for x in g if x["done"])) for y, g in games.items()}, "lines:", len(lines))
    lam, rho = C.CFB_SPREAD_LAM, C.CFB_SPREAD_RHO
    if tune:
        best = None
        for l in (2, 4, 6, 8, 12):
            for rr in (0.4, 0.6, 0.8, 1.0):
                ev = evaluate(walk_forward(games, C.SEASON - 1, l, rr), lines)
                if ev["n"] and (best is None or ev["model_margin_mae"] < best[0]):
                    best = (ev["model_margin_mae"], l, rr)
                print(f"lam {l:>2} rho {rr}: margin MAE {ev.get('model_margin_mae')} (n {ev['n']})")
        print("best on", C.SEASON - 1, best)
    for s in sorted(games):
        if s - 1 in games or s == C.SEASON:
            print(s, json.dumps(evaluate(walk_forward(games, s, lam, rho), lines)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--tune", action="store_true")
    a = ap.parse_args()
    main(a.raw, a.tune)

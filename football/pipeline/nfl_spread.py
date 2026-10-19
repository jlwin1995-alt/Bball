"""NFL spread and total model: the college ridge ratings (pipeline.cfb_spread) run on NFL scores, walk-forward against the closing lines.

    python -m pipeline.nfl_spread [--tune]

Lines are nflverse's (spread_line POSITIVE = home favoured, i.e. the market margin itself). Regular season only. Same question as college: is BETA
(how much of model-minus-market is worth adding to the market) different from zero out of sample?
"""
import argparse, csv, json, os
from . import config as C
from . import cfb_spread as S

CAP = 28.0


def load(path="data/raw/nfl_hist/nfl_games.csv"):
    games, lines = {}, {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["game_type"] != "REG":
                continue
            y = int(r["season"])
            done = r["home_score"] not in ("", None) and r["away_score"] not in ("", None)
            games.setdefault(y, []).append(dict(id=r["game_id"], week=int(r["week"]), home=r["home_team"], away=r["away_team"], neutral=r["location"] == "Neutral", done=done,
                                                hp=float(r["home_score"]) if done else None, ap=float(r["away_score"]) if done else None))
            sp = float(r["spread_line"]) if r["spread_line"] else None
            lines[(y, r["game_id"])] = (None if sp is None else -sp, float(r["total_line"]) if r["total_line"] else None)   # cfb_spread's sign: negative = home favoured
    return games, lines


def walk(games, season, lam, rho, first_week=3):
    prev = games.get(season - 1, [])
    prior = S.fit_margin([g for g in prev if g["done"]], {}, lam, 1.0, cap=CAP)[0] if prev else {}
    out, cur = [], games.get(season, [])
    for wk in sorted({g["week"] for g in cur}):
        past = [g for g in cur if g["done"] and g["week"] < wk]
        if wk < first_week or len(past) < 30:
            continue
        rat, hfa = S.fit_margin(past, prior, lam, rho, cap=CAP)
        mu, ta = S.fit_total(past, lam=C.NFL_TOTAL_LAM if hasattr(C, "NFL_TOTAL_LAM") else 12.0)
        for g in (x for x in cur if x["week"] == wk):
            m, t = S.predict(g, rat, hfa, mu, ta)
            out.append(dict(g, model_margin=m, model_total=t, season=season))
    return out


def main(path="data/raw/nfl_hist/nfl_games.csv", tune=False):
    games, lines = load(path)
    lam, rho = 6.0, 0.7
    if tune:
        for l in (2, 4, 6, 10):
            for rr in (0.5, 0.7, 0.9):
                ev = [S.evaluate(walk(games, s, l, rr), lines) for s in range(2016, 2026)]
                print(f"lam {l} rho {rr}: margin MAE {sum(e['model_margin_mae'] for e in ev)/len(ev):.3f}")
    tot = {}
    for s in sorted(games):
        if s - 1 in games:
            ev = S.evaluate(walk(games, s, lam, rho), lines)
            print(s, json.dumps(ev))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="data/raw/nfl_hist/nfl_games.csv")
    ap.add_argument("--tune", action="store_true")
    a = ap.parse_args()
    main(a.path, a.tune)

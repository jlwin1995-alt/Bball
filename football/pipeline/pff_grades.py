"""Do PFF's per-game team grades add anything to the closing spread and total?

    python -m pipeline.pff_grades            # needs data/raw/pff_hist/team_games_<s>.csv and data/raw/nfl_hist/nfl_games.csv

Each team's grades are its season-to-date mean through the previous week (weeks 5+, at least 4 games). A grade model (margin or total regressed on grade differences or sums) is fitted on
the OTHER seasons (leave-one-season-out) and compared with the closing line: BETA = slope of (actual - market) on (grade model - market), and MAE against the market's.
"""
import csv, math, statistics
from .cfb_totals import ridge

FIX = {"ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
G = ["grades_offense", "grades_defense", "grades_pass", "grades_run", "grades_pass_block", "grades_run_block", "grades_pass_rush_defense", "grades_coverage_defense", "grades_run_defense", "grades_overall"]


def load_games(path="data/raw/nfl_hist/nfl_games.csv"):
    out = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["game_type"] == "REG" and r["spread_line"] and r["total_line"] and r["home_score"] != "":
                out[(int(r["season"]), int(r["week"]), r["home_team"])] = (r["away_team"], float(r["home_score"]), float(r["away_score"]), float(r["spread_line"]), float(r["total_line"]))
    return out


def load_grades(seasons, raw="data/raw"):
    gr = {}
    for s in seasons:
        with open(f"{raw}/pff_hist/team_games_{s}.csv", newline="") as f:
            for r in csv.DictReader(f):
                w = int(r["week"])
                if 1 <= w <= 18:
                    t = FIX.get(r["team"], r["team"])
                    gr.setdefault((s, t), []).append((w, {g: float(r[g]) for g in G if r.get(g) not in ("", None)}))
    return gr


def to_date(gr, s, t, week, min_games=4):
    gs = [d for w, d in gr.get((s, t), []) if w < week]
    if len(gs) < min_games:
        return None
    out = {}
    for g in G:
        v = [d[g] for d in gs if g in d]
        if len(v) >= 3:
            out[g] = sum(v) / len(v)
    return out if all(g in out for g in G) else None


def build(seasons, raw="data/raw"):
    games, gr = load_games(), load_grades(seasons, raw)
    rows = []
    for (s, w, h), (a, hs, as_, sp, tl) in sorted(games.items()):
        if s not in seasons or w < 5:
            continue
        gh, ga = to_date(gr, s, h, w), to_date(gr, s, a, w)
        if not gh or not ga:
            continue
        rows.append(dict(season=s, week=w, gh=gh, ga=ga, margin=hs - as_, total=hs + as_, mkt_m=sp, mkt_t=tl))
    return rows


FEATS_M = [lambda r: r["gh"]["grades_overall"] - r["ga"]["grades_overall"],
           lambda r: r["gh"]["grades_offense"] - r["ga"]["grades_offense"],
           lambda r: r["gh"]["grades_defense"] - r["ga"]["grades_defense"],
           lambda r: r["gh"]["grades_pass_block"] - r["ga"]["grades_pass_block"],
           lambda r: r["gh"]["grades_pass_rush_defense"] - r["ga"]["grades_pass_rush_defense"]]
FEATS_T = [lambda r: r["gh"]["grades_offense"] + r["ga"]["grades_offense"],
           lambda r: r["gh"]["grades_defense"] + r["ga"]["grades_defense"],
           lambda r: r["gh"]["grades_pass"] + r["ga"]["grades_pass"],
           lambda r: r["gh"]["grades_run_defense"] + r["ga"]["grades_run_defense"]]


def ols_fit(tr, feats, ykey, lam=5.0):
    X = [[f(r) for f in feats] for r in tr]
    y = [r[ykey] for r in tr]
    coef, mean, sd, ym = ridge(X, y, lam)
    return lambda r: ym + sum(c * (f(r) - m) / s for c, f, m, s in zip(coef, feats, mean, sd))


def evaluate(rows, feats, ykey, mkey, label):
    res = []
    for s in sorted({r["season"] for r in rows}):
        tr, te = [r for r in rows if r["season"] != s], [r for r in rows if r["season"] == s]
        f = ols_fit(tr, feats, ykey)
        x = [f(r) - r[mkey] for r in te]
        y = [r[ykey] - r[mkey] for r in te]
        sxx = sum(v * v for v in x)
        beta = sum(a * b for a, b in zip(x, y)) / sxx
        se = math.sqrt(sum((b - beta * a) ** 2 for a, b in zip(x, y)) / (len(x) - 1) / sxx)
        mae_m = sum(abs(r[ykey] - r[mkey]) for r in te) / len(te)
        mae_g = sum(abs(r[ykey] - f(r)) for r in te) / len(te)
        hit = [(a > 0) == (b > 0) for a, b in zip(x, y) if abs(a) >= 1.0 and b != 0]
        res.append((s, len(te), beta, se, mae_g, mae_m, len(hit), sum(hit) / len(hit) * 100 if hit else float("nan")))
        print(f"{label} {s}: n={len(te)} BETA {beta:+.2f} +- {se:.2f} | MAE grades {mae_g:.2f} vs market {mae_m:.2f} | edge>=1pt hit {sum(hit)}/{len(hit)} ({sum(hit)/len(hit)*100:.1f}%)")
    return res


if __name__ == "__main__":
    seasons = [2022, 2023, 2024, 2025]
    rows = build(seasons)
    print(len(rows), "games (weeks 5+, both teams with 4+ games of grades)")
    evaluate(rows, FEATS_M, "margin", "mkt_m", "margin")
    evaluate(rows, FEATS_T, "total", "mkt_t", "total")

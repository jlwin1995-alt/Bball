"""Kicker model: expected kicking points (3 x field goals + extra points) from the team's implied points and the kicker's own history.

    python -m pipeline.kicker            # backtest; needs data/raw/history/weekly_<s>.csv (python -m pipeline.fetch --season N) and data/raw/nfl_hist/nfl_games.csv

A kicker's output is mostly the scoring environment, so the question is whether HIS history adds anything to the team's implied points (from the closing spread and
total). Backtest rows are walk-forward: a week is predicted from earlier weeks of the same season plus earlier seasons. Baselines: the league mean, implied points
alone, the kicker's season average, his last three games.
"""
import csv, math, statistics
from .model import load_weekly

SEASONS = (2022, 2023, 2024, 2025)


def kpts(r):
    return 3.0 * r["fg_made"] + r["pat_made"]


def implied(path="data/raw/nfl_hist/nfl_games.csv"):
    """(season, week, team) -> implied team points from the closing spread (positive = home favoured) and total."""
    out = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["game_type"] != "REG" or not r["spread_line"] or not r["total_line"]:
                continue
            s, t, w = float(r["spread_line"]), float(r["total_line"]), (int(r["season"]), int(r["week"]))
            out[w + (r["home_team"],)] = (t + s) / 2
            out[w + (r["away_team"],)] = (t - s) / 2
    return out


def load(raw="data/raw"):
    imp = implied()
    rows = []
    for y in SEASONS:
        for r in load_weekly(f"{raw}/history/weekly_{y}.csv"):
            if r["position"] == "K" and (y, int(r["week"]), r["team"]) in imp:
                rows.append(dict(season=y, week=int(r["week"]), id=r["player_id"], name=r["player_display_name"], team=r["team"],
                                 imp=imp[(y, int(r["week"]), r["team"])], pts=kpts(r), fg=r["fg_made"], att=r["fg_att"]))
    return rows


def ols(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    return my - b * mx, b


def walk(rows, season, k=6.0):
    """Predict every kicker-game of `season` from earlier data. The kicker's effect is his mean residual against the implied-points fit, shrunk by k games."""
    out = []
    by_wk = sorted({r["week"] for r in rows if r["season"] == season})
    for wk in by_wk:
        past = [r for r in rows if (r["season"], r["week"]) < (season, wk)]
        if len(past) < 150:
            continue
        a, b = ols([r["imp"] for r in past], [r["pts"] for r in past])
        res = {}
        for r in past:
            res.setdefault(r["id"], []).append(r["pts"] - (a + b * r["imp"]))
        hist = {}
        for r in past:
            hist.setdefault(r["id"], []).append((r["season"], r["week"], r["pts"]))
        for r in (x for x in rows if x["season"] == season and x["week"] == wk):
            base = a + b * r["imp"]
            rs = res.get(r["id"], [])
            adj = sum(rs) / (len(rs) + k) if rs else 0.0                    # shrunk toward 0: a kicker with few games stays near the league line
            h = [x[2] for x in sorted(hist.get(r["id"], []))]
            league = sum(p["pts"] for p in past) / len(past)
            out.append(dict(r, mean=league, implied=base, model=base + adj, season_avg=(sum(h) / len(h)) if h else league,
                            last3=(sum(h[-3:]) / len(h[-3:])) if h else league, n_hist=len(h)))
    return out


def report(preds):
    res = {}
    for m in ("mean", "implied", "model", "season_avg", "last3"):
        e = [p[m] - p["pts"] for p in preds]
        res[m] = dict(mae=round(sum(abs(x) for x in e) / len(e), 3), rmse=round(math.sqrt(sum(x * x for x in e) / len(e)), 3), bias=round(sum(e) / len(e), 3))
    return res


def main(raw="data/raw"):
    rows = load(raw)
    print(len(rows), "kicker games", len({r["id"] for r in rows}), "kickers; mean pts", round(statistics.mean(r["pts"] for r in rows), 2),
          "sd", round(statistics.pstdev(r["pts"] for r in rows), 2))
    for s in SEASONS[1:]:
        p = [x for x in walk(rows, s) if x["week"] >= 4]
        print(s, len(p), report(p))
    p = [x for s in SEASONS[1:] for x in walk(rows, s) if x["week"] >= 4]
    print("all", len(p), report(p))
    a, b = ols([r["imp"] for r in rows], [r["pts"] for r in rows])
    print(f"kicking points = {a:.2f} + {b:.3f} x implied team points")


if __name__ == "__main__":
    main()

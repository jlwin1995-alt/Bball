"""NFL player-model test: do the player projections, summed to the team, predict games better than the closing line?

    python -m pipeline.nfl_player [--seasons 2022 2023 2024 2025]     # needs data/raw/history/weekly_<s>.csv, schedule_<s>.csv, injuries_<s>.csv (pipeline.fetch --season)

Per week W (from BACKTEST_FROM_WEEK) the same nfl_core / derive the site uses projects every player from the weeks before W (no weather: the history holds the
wind that blew, which is not a forecast; Out players removed as in the backtest). Each team's projections are summed to a few team numbers (yards, touchdowns,
turnovers, sacks). A small ridge, fitted on EARLIER seasons only, turns those into points; the game's model total / margin is compared with nflverse's closing
total_line / spread_line. BETA is the slope of (actual - market) on (model - market): zero means the model adds nothing to the market.
"""
import argparse, csv, json, math, os
from . import config as C
from .model import load_weekly, nfl_core, derive, params
from .slate import load_csv, matchups
from .cfb_totals import ridge

FEATS = ["yards", "td", "turn", "sacks"]


def team_features(season, raw="data/raw", from_week=None):
    """-> list of dict(season, week, game_id, team, home, f=[...], pts) for every team-game from from_week on."""
    P = params()
    W = C.DEFAULT_SCORING
    from_week = from_week or C.BACKTEST_FROM_WEEK
    rows = load_weekly(f"{raw}/history/weekly_{season}.csv")
    sched = load_csv(f"{raw}/history/schedule_{season}.csv")
    inj = []
    p = f"{raw}/history/injuries_{season}.csv"
    if os.path.exists(p):
        with open(p, newline="") as f:
            inj = list(csv.DictReader(f))
    by_week = {}
    for r in rows:
        by_week.setdefault(int(r["week"]), []).append(r)
    games = {(int(float(g["week"])), g["home_team"]): g for g in sched if g.get("game_type", "REG") == "REG"}
    out = []
    for wk in range(from_week, max(by_week) + 1):
        mu = matchups(sched, wk)
        hist = [r for w in range(1, wk) for r in by_week.get(w, [])]
        if not mu or not hist:
            continue
        Pw = dict(P, OUT_IDS={r["gsis_id"] for r in inj if int(float(r["week"] or 0)) == wk and r["report_status"] in P.get("OUT_STATUS", ("Out",))}) if P.get("OUT_RB") else P
        tot = {}
        for pl in nfl_core(hist, mu, None, Pw)["players"]:
            if pl["team"] not in mu:
                continue
            d = derive(pl, W, P)
            t = tot.setdefault(pl["team"], dict(yards=0.0, td=0.0, turn=0.0, sacks=0.0))
            t["yards"] += d["rushY"] + d["passY"]
            t["td"] += d["rushTD"] + d["passTD"]
            t["turn"] += d["int"] + d["fum"]
            t["sacks"] += d["sacks"]
        for (w, home), g in games.items():
            if w != wk or g["home_score"] in ("", None) or home not in tot or g["away_team"] not in tot:
                continue
            for team, is_home, pts in ((home, 1, float(g["home_score"])), (g["away_team"], 0, float(g["away_score"]))):
                out.append(dict(season=season, week=wk, game_id=g["game_id"], team=team, home=is_home, f=[tot[team][k] for k in FEATS] + [is_home], pts=pts))
    return out


def load_lines(path="data/raw/nfl_hist/nfl_games.csv"):
    ln = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["spread_line"] and r["total_line"]:
                ln[r["game_id"]] = (float(r["spread_line"]), float(r["total_line"]))
    return ln


def fit_apply(train, test, lam=20.0):
    coef, mean, sd, ym = ridge([r["f"] for r in train], [r["pts"] for r in train], lam)
    pred = lambda f: ym + sum(c * (x - m) / s for c, x, m, s in zip(coef, f, mean, sd))
    return pred


def evaluate(test, pred, lines):
    games = {}
    for r in test:
        games.setdefault(r["game_id"], {})["h" if r["home"] else "a"] = r
    xs_t, ys_t, xs_m, ys_m, mt, mm, mkt_t, mkt_m = [], [], [], [], 0.0, 0.0, 0.0, 0.0
    rows = []
    for gid, g in games.items():
        if "h" not in g or "a" not in g or gid not in lines:
            continue
        sp, tl = lines[gid]
        ph, pa = pred(g["h"]["f"]), pred(g["a"]["f"])
        at, am = g["h"]["pts"] + g["a"]["pts"], g["h"]["pts"] - g["a"]["pts"]
        rows.append((ph + pa, ph - pa, tl, sp, at, am))
    n = len(rows)
    if n < 30:
        return dict(n=n)
    res = dict(n=n)
    for name, (mi, li, ai) in (("total", (0, 2, 4)), ("margin", (1, 3, 5))):
        x = [r[mi] - r[li] for r in rows]
        y = [r[ai] - r[li] for r in rows]
        sxx = sum(v * v for v in x)
        beta = sum(a * b for a, b in zip(x, y)) / sxx
        resid = [b - beta * a for a, b in zip(x, y)]
        se = math.sqrt(sum(e * e for e in resid) / (n - 1) / sxx)
        hit = [(a > 0) == (b > 0) for a, b in zip(x, y) if b != 0 and abs(a) >= 1.0]
        res[name] = dict(model_mae=round(sum(abs(r[mi] - r[ai]) for r in rows) / n, 3), mkt_mae=round(sum(abs(r[li] - r[ai]) for r in rows) / n, 3),
                         beta=round(beta, 3), se=round(se, 3), edge_sd=round(math.sqrt(sxx / n), 2), hit_n=len(hit), hit=round(sum(hit) / len(hit) * 100, 1) if hit else None)
    return res


def main(seasons, raw="data/raw", cache="/tmp/nfl_player_cache.json"):
    data = {}
    for s in seasons:
        data[s] = team_features(s, raw)
        print(s, len(data[s]), "team-games", flush=True)
    lines = load_lines()
    for s in seasons[1:]:
        train = [r for t in seasons if t < s for r in data[t]]
        res = evaluate(data[s], fit_apply(train, data[s]), lines)
        print(s, json.dumps(res))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, nargs="+", default=[2022, 2023, 2024, 2025])
    ap.add_argument("--raw", default="data/raw")
    a = ap.parse_args()
    main(a.seasons, a.raw)

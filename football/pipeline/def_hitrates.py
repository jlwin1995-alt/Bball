"""Actual hit rates against the toughest and softest defences (the football version of the NBA project's "over his own projection vs defences like tonight's").

    python -m pipeline.def_hitrates       # needs data/raw/history/{weekly,schedule,injuries}_<s>.csv

Walk-forward, weeks 5+, 2023-25: each player-game's frozen-style projection (nfl_core / derive) against what happened, split by how the OPPOSING defence ranked, going into that week, on the stat
(allowed per game to that position group over the earlier weeks of the season, min 3 games; toughest 8 / middle 16 / softest 8 of 32). Per market and tier: games, over-projection rate
(actual > projection), actual / projected, and the median miss. This says what a line equal to the projection would have paid; the live table also grades the logged consensus lines.
"""
import statistics
from collections import defaultdict
from . import config as C
from .model import load_weekly, nfl_core, derive, params
from .slate import load_csv, matchups
from .backtest import load_inj, INJ

MARKETS = {  # market: (positions, derive key, box-score column)
    "rushY": (("RB",), "rushY", "rushing_yards", 8.0), "recY": (("WR", "TE", "RB"), "recY", "receiving_yards", 8.0), "rec": (("WR", "TE", "RB"), "rec", "receptions", 1.0),
    "passY": (("QB",), "passY", "passing_yards", 60.0), "comp": (("QB",), "comp", "completions", 6.0)}


def allowed_rank(hist, wk, positions, col, min_g=3):
    """{defence: rank} (1 = toughest = fewest allowed per game to these positions) from the weeks before wk."""
    tot, games = defaultdict(float), defaultdict(set)
    for r in hist:
        if r["position"] in positions:
            tot[r["opponent_team"]] += r[col]
        games[r["opponent_team"]].add(int(r["week"]))
    per = {t: tot[t] / len(games[t]) for t in games if len(games[t]) >= min_g}
    order = sorted(per, key=lambda t: per[t])
    return {t: i + 1 for i, t in enumerate(order)}, len(order)


def collect(seasons=(2023, 2024, 2025), raw="data/raw"):
    P, W = params(), C.DEFAULT_SCORING
    out = []                                                  # (market, tier, projection, actual, season, week, player id, team)
    for season in seasons:
        load_inj(season, raw)
        rows = load_weekly(f"{raw}/history/weekly_{season}.csv")
        sched = load_csv(f"{raw}/history/schedule_{season}.csv")
        by_week = {}
        for r in rows:
            by_week.setdefault(int(r["week"]), []).append(r)
        for wk in range(5, max(by_week) + 1):
            mu = matchups(sched, wk)
            if not mu:
                continue
            hist = [r for x in range(1, wk) for r in by_week.get(x, [])]
            outs = {r["gsis_id"] for r in INJ.get(season, []) if int(float(r["week"] or 0)) == wk and r["report_status"] == "Out"}
            core = nfl_core(hist, mu, None, dict(P, OUT_IDS=outs))
            act = {r["player_id"]: r for r in by_week[wk]}
            ranks = {m: allowed_rank(hist, wk, v[0], v[2]) for m, v in MARKETS.items()}
            for pl in core["players"]:
                a = act.get(pl["id"])
                if a is None:
                    continue
                d = derive(pl, W, P)
                for m, (pos, key, col, floor) in MARKETS.items():
                    if pl["pos"] not in pos or d[key] < floor * (0.25 if m in ("rec", "comp") else 1):
                        continue
                    rk, n = ranks[m]
                    r_ = rk.get(pl["opp"])
                    if r_ is None:
                        continue
                    tier = "tough" if r_ <= 8 else "soft" if r_ > n - 8 else "mid"
                    out.append((m, tier, d[key], a[col], season, wk, pl["id"], pl["team"]))
    return out


def table(rows):
    print(f"{'market':7} {'tier':6} {'n':>5} {'over proj':>10} {'actual/proj':>12} {'median miss':>12}")
    for m in MARKETS:
        for tier in ("tough", "mid", "soft"):
            r = [x for x in rows if x[0] == m and x[1] == tier]
            if not r:
                continue
            over = sum(1 for x in r if x[3] > x[2]) / len([x for x in r if x[3] != x[2]]) * 100
            print(f"{m:7} {tier:6} {len(r):5} {over:9.1f}% {sum(x[3] for x in r) / sum(x[2] for x in r):11.2f} {statistics.median(x[3] - x[2] for x in r):+12.1f}")


if __name__ == "__main__":
    rows = collect()
    print(f"{len(rows)} player-game-markets")
    table(rows)

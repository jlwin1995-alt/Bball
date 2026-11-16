"""Does a player's result against the SAME opponent earlier in the season predict the rematch beyond the projection?

    python -m pipeline.h2h

Walk-forward (same loop as backtest.py, 2023-26): every projected player-game keeps its residual (actual - projection). For a rematch (the
team already played this opponent earlier in the season) the first game's residual is compared with the rematch's residual: slope of
rematch residual on first-game residual, by stat, with a standard error. A positive slope would mean the model should lean toward the
earlier result against that opponent; a slope near zero means the first game was noise (or the model already priced it).
"""
import math
from . import config as C
from .model import load_weekly, nfl_core, derive, params
from .slate import load_csv, matchups, recorded_wx
from .backtest import actual, STATS, INJ, load_inj

KEYS = ["rushY", "recY", "rec", "passY", "comp"]
MINP = {"rushY": 10, "recY": 10, "rec": 1, "passY": 50, "comp": 5}


def season_resids(season, raw="data/raw"):
    W, P = C.DEFAULT_SCORING, params()
    cur = season == C.SEASON
    rows = load_weekly(f"{raw}/weekly.csv" if cur else f"{raw}/history/weekly_{season}.csv")
    sched = load_csv(f"{raw}/schedule.csv" if cur else f"{raw}/history/schedule_{season}.csv")
    by_week = {}
    for r in rows:
        by_week.setdefault(int(r["week"]), []).append(r)
    out = {}                                  # (week, pid) -> dict(opp, team, stat -> (proj, act))
    for wk in range(5, max(by_week) + 1):
        if wk not in by_week:
            continue
        mu = matchups(sched, wk)
        hist = [r for w in range(1, wk) for r in by_week.get(w, [])]
        if not mu or not hist:
            continue
        core = nfl_core(hist, mu, recorded_wx(sched, wk, P), P)
        act = {r["player_id"]: r for r in by_week[wk]}
        for pl in core["players"]:
            r = act.get(pl["id"])
            if r is None:
                continue
            d = derive(pl, W, P)
            if d["pts"] < C.BACKTEST_MIN_PTS:
                continue
            a = actual(r, W)
            out[(wk, pl["id"])] = dict(opp=r["opponent_team"], team=r["team"], s={k: (d[k], a[k]) for k in KEYS})
    return out


def main():
    pairs = {k: [] for k in KEYS}
    for season in ("2023", "2024", "2025", C.SEASON):
        try:
            res = season_resids(season)
        except FileNotFoundError:
            continue
        first = {}
        for (wk, pid), v in sorted(res.items()):
            key = (pid, v["opp"])
            if key in first:
                f = first[key]
                for k in KEYS:
                    if v["s"][k][0] >= MINP[k] and f["s"][k][0] >= MINP[k]:
                        pairs[k].append((f["s"][k][1] - f["s"][k][0], v["s"][k][1] - v["s"][k][0], f["s"][k][0], v["s"][k][0]))
            else:
                first[key] = v
    for k in KEYS:
        p = pairs[k]
        n = len(p)
        if n < 10:
            continue
        x = [a for a, b, _, _ in p]; y = [b for a, b, _, _ in p]
        mx, my = sum(x) / n, sum(y) / n
        sxx = sum((a - mx) ** 2 for a in x); sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
        slope = sxy / sxx
        res = [b - my - slope * (a - mx) for a, b in zip(x, y)]
        se = math.sqrt(sum(r * r for r in res) / (n - 2) / sxx)
        hi = [(a, b) for a, b in zip(x, y) if a > 0]
        lo = [(a, b) for a, b in zip(x, y) if a < 0]
        # big first-game beat: first game ran 1.5x+ the projection... keep it simple: top quarter of residuals
        srt = sorted(p, key=lambda t: t[0] / max(t[2], 1))
        q = n // 4
        top, bot = srt[-q:], srt[:q]
        print(f"{k:5} n={n:4}  slope {slope:+.3f} (se {se:.3f})  rematch residual mean {my:+.2f}; "
              f"after a big beat (top quarter, first game +{sum(t[0] for t in top)/q:.1f}) the rematch ran {sum(t[1] for t in top)/q:+.2f}; "
              f"after a big miss (bottom quarter, {sum(t[0] for t in bot)/q:.1f}) it ran {sum(t[1] for t in bot)/q:+.2f}")


if __name__ == "__main__":
    main()

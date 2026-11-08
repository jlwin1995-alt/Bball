"""Test: does the opponent's strength matter more (or less) for top-tier players than for the rest? Player tier x defence tier grid.

Walk-forward projections (NFL 2023-26, college 2025-26, week 5 on). For each stat's main position group the player tier is the projection tercile within the stat (low / mid / top) and the defence
tier the tercile of the matchup factor the model itself used (rushing: dr / a_rush; receiving: dc x dy / a_rec; passing: dp / a_pass; 1.0 = league average, lower = tougher). Per cell: n, median actual / projection,
share over the projection, and the actual-projection miss in the stat's units. Read: is the tough-vs-soft gap the same for a top player as for a low one?
"""
import json, os, statistics as S
from . import config as C

CACHE = os.environ.get("GRID_CACHE", "/tmp/grid_pairs.json")
MAIN = {"rushY": ("RB",), "recY": ("WR", "TE"), "passY": ("QB",)}
MIN = {"rushY": 10, "recY": 10, "passY": 100}


def nfl(W):
    from .model import load_weekly, nfl_core, derive, params
    from .slate import load_csv, matchups
    from .backtest import load_inj, INJ, actual
    P, out = params(), []
    src = [(s, f"data/raw/history/weekly_{s}.csv", f"data/raw/history/schedule_{s}.csv") for s in (2023, 2024, 2025)] + [(2026, "data/raw/weekly.csv", "data/raw/schedule.csv")]
    for season, wp, sp in src:
        load_inj(season, "data/raw")
        rows, sched, by = load_weekly(wp), load_csv(sp), {}
        for r in rows:
            by.setdefault(int(r["week"]), []).append(r)
        for wk in range(5, max(by) + 1):
            mu = matchups(sched, wk)
            if not mu or wk not in by:
                continue
            hist = [r for x in range(1, wk) for r in by.get(x, [])]
            outs = {r["gsis_id"] for r in INJ.get(season, []) if int(float(r["week"] or 0)) == wk and r["report_status"] == "Out"}
            core = nfl_core(hist, mu, None, dict(P, OUT_IDS=outs))
            act = {r["player_id"]: r for r in by[wk]}
            for pl in core["players"]:
                a = act.get(pl["id"])
                if a is None:
                    continue
                d, z = derive(pl, C.DEFAULT_SCORING, P), actual(a, C.DEFAULT_SCORING)
                fac = {"rushY": pl["dr"], "recY": pl["dc"] * pl["dy"], "passY": pl["dp"]}
                for st in MAIN:
                    out.append((st, pl["pos"], d[st], z[st], season, fac[st], pl["opp"]))
    return out


def cfb(W):
    from .cfb_build import schedule, excluded_games
    from .cfb_data import read_csv
    from .cfb_model import cfb_core, derive, load_rows
    from .model import params
    out = []
    for yr, (wp, gp) in zip((2025, 2026), (("data/raw/cfb_hist/cfb_weekly_2025.csv", "data/raw/cfb_hist/cfb_games_2025.csv"), ("data/raw/cfb_weekly.csv", "data/raw/cfb_games.csv"))):
        rows, games = load_rows(wp), read_csv(gp)
        sched, skip = schedule(games), excluded_games(games)
        for wk in sorted({int(x["week"]) for x in rows}):
            if wk < 5 or wk not in sched:
                continue
            hist = [x for x in rows if x["week"] < wk and (x["team"], int(x["week"])) not in skip]
            now = {x["playerId"]: x for x in rows if x["week"] == wk}
            mu = {}
            for g in sched[wk]["games"]:
                s = "N" if g["neutral"] else None
                mu[g["awayTeam"]] = dict(opp=g["homeTeam"], site=s or "@")
                mu[g["homeTeam"]] = dict(opp=g["awayTeam"], site=s or "vs")
            core = cfb_core(hist, mu, sched[wk]["conf"], params())
            for pl in core["players"]:
                a = now.get(pl["id"])
                if a is None or (pl["team"], wk) in skip:
                    continue
                d = derive(pl, C.DEFAULT_SCORING)
                act = dict(rushY=a["rushing_yards"], recY=a["receiving_yards"], passY=a["passing_yards"])
                fac = {"rushY": pl["a_rush"], "recY": pl["a_rec"], "passY": pl["a_pass"]}
                for st in MAIN:
                    out.append((st, pl["pos"], d[st], act[st], yr, fac[st], pl["opp"]))
    return out


def terc(v):
    s = sorted(v)
    return s[len(s) // 3], s[2 * len(s) // 3]


def main():
    try:
        d = json.load(open(CACHE))
    except OSError:
        d = {"nfl": nfl(C.DEFAULT_SCORING), "cfb": cfb(C.DEFAULT_SCORING)}
        json.dump(d, open(CACHE, "w"))
    for lg in ("nfl", "cfb"):
        for st, poss in MAIN.items():
            rows = [(p, a, f) for (t, ps, p, a, s, f, o) in d[lg] if t == st and ps in poss and p >= MIN[st]]
            pl_lo, pl_hi = terc([p for p, _, _ in rows])
            df_lo, df_hi = terc([f for _, _, f in rows])      # low factor = tough defence
            print(f"\n{lg.upper()} {st} ({'/'.join(poss)}), n={len(rows)}; player tiers split at projection {pl_lo:.0f} / {pl_hi:.0f}; defence tiers at factor {df_lo:.3f} / {df_hi:.3f}")
            print(f"{'player tier':12}{'defence':>9}{'n':>6}{'med act/proj':>14}{'over proj':>10}{'mean miss':>11}")
            for pn, plf in (("top", lambda p: p >= pl_hi), ("mid", lambda p: pl_lo <= p < pl_hi), ("low", lambda p: p < pl_lo)):
                for dn, dff in (("tough", lambda f: f < df_lo), ("mid", lambda f: df_lo <= f < df_hi), ("soft", lambda f: f >= df_hi)):
                    v = [(p, a) for p, a, f in rows if plf(p) and dff(f)]
                    if len(v) < 40:
                        continue
                    print(f"{pn:12}{dn:>9}{len(v):6}{S.median(a / p for p, a in v):14.2f}{100 * sum(a > p for p, a in v) / len(v):9.0f}%{S.mean(a - p for p, a in v):11.1f}")


if __name__ == "__main__":
    main()

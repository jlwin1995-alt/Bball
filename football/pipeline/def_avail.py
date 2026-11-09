"""Test: do missing defensive starters change the opposing offence's results?

For every defence and week (NFL 2023-26) the availability index is the sum, over its defenders on that week's injury report, of status weight (Out 1.0, Doubtful 0.8, Questionable 0.2) x the defender's
season-to-date share of his team's defensive snaps (so one full-time starter out = about 1.0), split into DL (DE / DT / NT), LB, CB and S. Opposing offence rows come from the walk-forward projections
(week 5 on). Fit  actual / projection - 1 = b_group x index_group  (least squares weighted by the projection) and score it leave-one-season-out against the unchanged projection.
Snap counts are read from SNAPS_DIR (nflverse snap_counts_<season>.csv, 2022-25; the current season from data/raw/snaps.csv)."""
import csv, json, os, re, statistics as S
from collections import defaultdict
from . import config as C

SNAPS_DIR = os.environ.get("SNAPS_DIR", "/tmp/claude-0/-home-user-Bball/6033d333-3d26-519b-b4f4-6413cdb352d7/scratchpad/snaps")
CACHE = os.environ.get("DA_CACHE", "/tmp/def_avail_rows.json")
GROUP = {"DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL", "EDGE": "DL", "LB": "LB", "ILB": "LB", "OLB": "LB", "MLB": "LB", "CB": "CB", "DB": "CB", "S": "S", "FS": "S", "SS": "S"}
W = {"Out": 1.0, "Doubtful": 0.8, "Questionable": 0.2}
GROUPS = ("DL", "LB", "CB", "S")
STATS = {"passY": ("QB",), "recY": ("WR", "TE", "RB"), "rec": ("WR", "TE", "RB"), "rushY": ("RB",)}
MIN = {"passY": 100, "recY": 10, "rec": 1, "rushY": 10}


def nk(s):
    return re.sub(r"[^a-z]", "", re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", str(s).lower()))


def snaps_for(season):
    path = f"{SNAPS_DIR}/snap_counts_{season}.csv" if season != C.SEASON else "data/raw/snaps.csv"
    return list(csv.DictReader(open(path)))


def injuries_for(season):
    path = f"data/raw/history/injuries_{season}.csv" if season != C.SEASON else "data/raw/injuries.csv"
    return list(csv.DictReader(open(path)))


def indices(season):
    """(team, week) -> {group: index}"""
    sn = [r for r in snaps_for(season) if r.get("game_type", "REG") == "REG"]
    # season-to-date average defensive snap share before each week, per (team, normalised name)
    by = defaultdict(list)
    for r in sn:
        if float(r["defense_snaps"] or 0) > 0 or r["position"] in GROUP:
            by[(r["team"], nk(r["player"]))].append((int(float(r["week"])), float(r["defense_pct"] or 0)))
    out = defaultdict(lambda: dict.fromkeys(GROUPS, 0.0))
    for r in injuries_for(season):
        st = r.get("report_status")
        if st not in W or r.get("game_type", "REG") != "REG" or GROUP.get(r["position"]) is None:
            continue
        w = int(float(r["week"] or 0)); team = r["team"]
        hist = [p for wk, p in by.get((team, nk(r["full_name"])), []) if wk < w]
        if len(hist) < 2:
            continue
        out[(team, w)][GROUP[r["position"]]] += W[st] * (sum(hist) / len(hist))
    return out


def walk():
    from .model import load_weekly, nfl_core, derive, params
    from .slate import load_csv, matchups
    from .backtest import load_inj, INJ, actual
    P, rows = params(), []
    src = [(s, f"data/raw/history/weekly_{s}.csv", f"data/raw/history/schedule_{s}.csv") for s in (2023, 2024, 2025)] + [(2026, "data/raw/weekly.csv", "data/raw/schedule.csv")]
    for season, wp, sp in src:
        load_inj(season, "data/raw")
        ix = indices(season)
        wk_rows, sched, by = load_weekly(wp), load_csv(sp), {}
        for r in wk_rows:
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
                idx = ix.get((pl["opp"], wk), dict.fromkeys(GROUPS, 0.0))
                for st in STATS:
                    rows.append((st, pl["pos"], d[st], z[st], season, wk, pl["opp"], [idx[g] for g in GROUPS]))
    return rows


def fit(rows):
    """weighted least squares of (actual/proj - 1) on the four indices, weight = projection"""
    import itertools
    k = len(rows[0][2]) if rows else len(GROUPS)
    A = [[0.0] * k for _ in range(k)]; B = [0.0] * k
    for p, a, x in rows:
        y = a / p - 1
        for i in range(k):
            B[i] += p * x[i] * y
            for j in range(k):
                A[i][j] += p * x[i] * x[j]
    for i in range(k):
        A[i][i] += 1e-6 + 2.0 * sum(p for p, _, _ in rows) / max(len(rows), 1) * 0.0
    # Gauss-Jordan
    M = [A[i][:] + [B[i]] for i in range(k)]
    for c in range(k):
        piv = max(range(c, k), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        if abs(M[c][c]) < 1e-12:
            return [0.0] * k
        M[c] = [v / M[c][c] for v in M[c]]
        for r in range(k):
            if r != c:
                f = M[r][c]; M[r] = [M[r][i] - f * M[c][i] for i in range(k + 1)]
    return [M[i][k] for i in range(k)]


def main():
    try:
        rows = json.load(open(CACHE))
    except OSError:
        rows = walk(); json.dump(rows, open(CACHE, "w"))
    allx = [x for r in rows for x in [r[7]]]
    nz = sum(1 for x in allx if any(v > 0 for v in x))
    print(f"{len(rows)} offence rows; {nz} ({100 * nz / len(rows):.0f}%) face a defence with at least one listed defender; mean index per group when listed:",
          {g: round(S.mean(x[i] for x in allx if x[i] > 0), 2) for i, g in enumerate(GROUPS)})
    print(f"\n{'stat pos':12}{'n':>6}  effect on actual/projection per one starter-equivalent out (intercept in the model)      MAE: projection | + intercept only | + intercept + defence indices   (leave-one-season-out)")
    for st, poss in STATS.items():
        sel = [(p, a, s, x) for (t, ps, p, a, s, wk, o, x) in rows if t == st and ps in poss and p >= MIN[st]]
        if len(sel) < 300:
            continue
        seasons = sorted({s for _, _, s, _ in sel})
        full = fit([(p, a, [1.0] + x) for p, a, s, x in sel])
        raw = i_only = both = 0.0
        for s in seasons:
            tr = [(p, a, x) for p, a, s2, x in sel if s2 != s]
            c0 = fit([(p, a, [1.0]) for p, a, x in tr])
            b = fit([(p, a, [1.0] + x) for p, a, x in tr])
            for p, a, s2, x in sel:
                if s2 == s:
                    raw += abs(a - p)
                    i_only += abs(a - max(0.0, p * (1 + c0[0])))
                    both += abs(a - max(0.0, p * (1 + b[0] + sum(bi * xi for bi, xi in zip(b[1:], x)))))
        n = len(sel)
        print(f"{st+' '+'/'.join(poss):12}{n:6}  intercept {100 * full[0]:+5.1f}%  DL {100 * full[1]:+5.1f}%  LB {100 * full[2]:+5.1f}%  CB {100 * full[3]:+5.1f}%  S {100 * full[4]:+5.1f}%      {raw / n:.3f} | {i_only / n:.3f} | {both / n:.3f} ({100 * (both / i_only - 1):+.2f}% vs intercept only)")


if __name__ == "__main__":
    main()

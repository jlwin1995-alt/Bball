"""Player-vs-player coverage test: do PFF receiver-versus-defender pairs say anything the model's receiving projections miss?

    python -m pipeline.pff_cov      # needs data/raw/pff_hist/{covvs,covdef,defcoverage,pff_receiving}_<s>.csv (pipeline.pff_hist --reports covmatchup ...) and data/raw/history/*

PFF's pairs only exist where a pass was thrown at the receiver (no coverage snaps), so who covers whom before the game has to be estimated. Two pre-game, season-to-date features of the
opposing defence, built from the pairs and the defenders' game coverage grades:
  cov_pos: the target-weighted mean coverage grade of the defenders who were thrown at by receivers of HIS position (WR / TE / RB), regressed toward the league with K targets;
  cov_top: for his team's leading target getter (WR / TE), the best coverage grade among the opponent's defenders (10+ targets faced): the shadow-corner effect; 0 for everyone else.
Residual (actual - projection) of receptions and receiving yards for WR / TE / RB (3+ projected targets, weeks 5+, 2023-25) regressed on them, fitted on the other seasons (ridge).
"""
import csv, math, statistics
from . import config as C
from .analysis import name_key
from .model import load_weekly, nfl_core, derive, params
from .slate import load_csv, matchups
from .backtest import load_inj, INJ
from .cfb_totals import ridge, solve
from .pff_grades import FIX

FEATS = ("cov_pos", "cov_top")
K_T = 40.0
LG_GRADE = 60.0


def fl(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def tables(season, raw="data/raw"):
    d = f"{raw}/pff_hist"
    team_of, pos_of, rid = {}, {}, {}
    with open(f"{d}/defcoverage_{season}.csv", newline="") as f:
        for r in csv.DictReader(f):
            team_of[(r["player_id"], int(r["week"]))] = FIX.get(r["team"], r["team"])
    with open(f"{d}/pff_receiving_{season}.csv", newline="") as f:
        for r in csv.DictReader(f):
            pos_of[r["player_id"]] = r["position"]
            rid[(name_key(r["player"]), FIX.get(r["team"], r["team"]))] = r["player_id"]
    grade = {}
    with open(f"{d}/covdef_{season}.csv", newline="") as f:
        for r in csv.DictReader(f):
            if r["grades_coverage_defense"] != "":
                grade[(r["player_id"], int(r["week"]))] = fl(r["grades_coverage_defense"])
    pairs = []          # (week, defender id, defender team, receiver position, targets, receiver id)
    with open(f"{d}/covvs_{season}.csv", newline="") as f:
        for r in csv.DictReader(f):
            wk = int(r["week"])
            t = team_of.get((r["coverage_player_id"], wk))
            if t:
                pairs.append((wk, r["coverage_player_id"], t, pos_of.get(r["player_id"], ""), fl(r["targets"]), r["player_id"]))
    return team_of, pos_of, rid, grade, pairs


def pos_group(p):
    return "RB" if p in ("HB", "FB", "RB") else p


def features(tb, opp, pos, wk, top):
    """-> (cov_pos, cov_top) for a receiver of `pos` facing `opp` before week `wk`."""
    team_of, pos_of, rid, grade, pairs = tb
    gsum, gn = {}, {}
    for (did, w), g in grade.items():
        if w < wk:
            gsum[did] = gsum.get(did, 0.0) + g; gn[did] = gn.get(did, 0) + 1
    dgrade = lambda did: (gsum[did] + 3 * LG_GRADE) / (gn[did] + 3) if did in gn else LG_GRADE
    num = den = 0.0
    faced = {}
    for w, did, t, p, tg, rid_ in pairs:
        if w >= wk or t != opp:
            continue
        faced[did] = faced.get(did, 0.0) + tg
        if pos_group(p) == pos:
            num += tg * dgrade(did); den += tg
    cov_pos = (num + K_T * LG_GRADE) / (den + K_T) - LG_GRADE
    best = max([dgrade(d) for d, n in faced.items() if n >= 10] or [LG_GRADE])
    return cov_pos, (best - LG_GRADE) if top else 0.0


def collect(seasons, raw="data/raw"):
    P = params()
    W = C.DEFAULT_SCORING
    rows = []
    for season in seasons:
        tb = tables(season, raw)
        rid = tb[2]
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
            lead = {}
            for pl in core["players"]:
                if pl["grp"] in ("WR", "TE") and pl["tgt"] > lead.get(pl["team"], (0, None))[0]:
                    lead[pl["team"]] = (pl["tgt"], pl["id"])
            for pl in core["players"]:
                a = act.get(pl["id"])
                if a is None or pl["grp"] not in ("WR", "TE", "RB") or pl["tgt"] < 3 or (name_key(pl["name"]), pl["team"]) not in rid:
                    continue
                d = derive(pl, W, P)
                x = features(tb, pl["opp"], pl["grp"], wk, lead.get(pl["team"], (0, None))[1] == pl["id"])
                rows.append(dict(season=season, week=wk, grp=pl["grp"], cov_pos=x[0], cov_top=x[1], top=x[1] != 0.0,
                                 p_rec=d["rec"], a_rec=fl(a["receptions"]), p_ry=d["recY"], a_ry=fl(a["receiving_yards"])))
    return rows


def loso(rows, pk, ak, label, feats=FEATS):
    base = fit = 0.0
    for s in sorted({r["season"] for r in rows}):
        tr, te = [r for r in rows if r["season"] != s], [r for r in rows if r["season"] == s]
        coef, mean, sd, ym = ridge([[r[f] for f in feats] for r in tr], [r[ak] - r[pk] for r in tr], 1.0)
        for r in te:
            e = r[ak] - r[pk]
            base += abs(e); fit += abs(e - (ym + sum(c * (r[f] - m) / sdv for c, f, m, sdv in zip(coef, feats, mean, sd))))
    n = len(rows)
    X = [[1.0] + [r[f] for f in feats] for r in rows]
    y = [r[ak] - r[pk] for r in rows]
    k = len(X[0])
    xtx = [[sum(x[i] * x[j] for x in X) for j in range(k)] for i in range(k)]
    beta = solve([r[:] for r in xtx], [sum(x[i] * yy for x, yy in zip(X, y)) for i in range(k)])
    s2 = sum((yy - sum(b * x for b, x in zip(beta, xi))) ** 2 for xi, yy in zip(X, y)) / (n - k)
    inv = [solve([r[:] for r in xtx], [1.0 if i == j else 0.0 for i in range(k)]) for j in range(k)]
    sl = ", ".join(f"{f} {beta[i + 1] * statistics.pstdev(r[f] for r in rows):+.2f} (t {beta[i + 1] / math.sqrt(s2 * inv[i + 1][i + 1]):+.1f})" for i, f in enumerate(feats))
    print(f"{label:22} n={n:5}  MAE {base / n:.3f} -> {fit / n:.3f} ({(fit - base) / base * 100:+.1f}%) | per 1 sd: {sl}", flush=True)


if __name__ == "__main__":
    rows = collect([2023, 2024, 2025])
    print(f"{len(rows)} player-games; sd cov_pos {statistics.pstdev(r['cov_pos'] for r in rows):.2f}, cov_top (leaders only) {statistics.pstdev(r['cov_top'] for r in rows if r['top']):.2f}; {sum(r['top'] for r in rows)} lead receivers")
    for g in ("WR", "TE", "RB", None):
        sub = [r for r in rows if g is None or r["grp"] == g]
        loso(sub, "p_rec", "a_rec", f"{g or 'all'} receptions")
        loso(sub, "p_ry", "a_ry", f"{g or 'all'} receiving yards")
    lead = [r for r in rows if r["top"]]
    loso(lead, "p_rec", "a_rec", "lead WR/TE receptions", ("cov_pos", "cov_top"))
    loso(lead, "p_ry", "a_ry", "lead WR/TE rec yards", ("cov_pos", "cov_top"))

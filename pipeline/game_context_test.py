"""Do the market's game total and spread carry information the model lacks?  (data/raw/game_lines.csv from pipeline.fetch_game_lines)

    python -m pipeline.game_context_test [season] [step_days]

Walk-forward over one season, known absences as in usage_test, using the games that have a line (ESPN has none for 2024-25 or before mid-Nov 2025). Prints, for the live model:
  A. starters' (projected 28+ min) minutes residual by |spread| - lopsided games cost starters minutes (about -0.9 min at 9-12 points, -2.7 at 15+, 2025-26), but a minutes rule only moved minutes MAE 5.13 -> 5.11.
  B. team level: points the model expects (sum of points x chance of playing) vs the market's implied team total (total/2 -/+ spread/2). The market is far closer to the real team score (MAE about 9-11 vs 13-16).
  C. player level: scaling each team's points to the implied total (exponent 0.9, level-neutral) gave fantasy-point MAE -0.4% (2026 Feb-Apr) and about 0 on 2026-27: team-level error is mostly WHO plays, a few points
     spread over nine players is small next to an 8-point typical miss. A first version of this test, which summed projections only over players who actually played, showed -2% and was look-ahead.
  D. line level (graded points lines in site/data/results): actual vs line slope on the game environment 0.15 (se 0.25), i.e. the books' lines already carry it; actual vs model -0.59 (se 0.26). NOT added to the model.
"""
import sys, glob, os, json
import pandas as pd, numpy as np
from pipeline import config as C
from pipeline.model import project, _prep

S = int(sys.argv[1]) if len(sys.argv) > 1 else 2027
EVERY = int(sys.argv[2]) if len(sys.argv) > 2 else 1
games = pd.read_csv("data/raw/games.csv", dtype={"pid": str}); games = games[games["season"] <= S]; C.SEASON = S
gl = pd.read_csv("data/raw/game_lines.csv").dropna(subset=["spread_home", "total"]); ok = set(gl["date"].astype(str))
g = _prep(games); days = [d for d in sorted(g[g.season == S]["date"].unique()) if str(pd.Timestamp(d).date()) in ok][::EVERY]
rows = []
for d in days:
    today = g[g.date == d]; slate = today[["team", "opp", "home"]].drop_duplicates("team").assign(date=d); hist = games[pd.to_datetime(games["date"]) < d]
    P0, _ = project(hist, slate, None, asof=d)
    ab = P0[(P0.min_s >= 15) & (P0.pplay >= 0.6) & (~P0.pid.isin(set(today.pid)))]
    inj = pd.DataFrame({"pid": ab.pid.astype(str), "name": ab["name"], "team": ab.team, "status": "Out"})
    P, _ = project(hist, slate, inj, asof=d); P = P[~P.out]
    G = gl[gl.date.astype(str) == str(pd.Timestamp(d).date())]; imp, sp = {}, {}
    for r in G.itertuples(): imp[r.home] = r.total / 2 - r.spread_home / 2; imp[r.away] = r.total / 2 + r.spread_home / 2; sp[r.home] = sp[r.away] = abs(r.spread_home)
    act = today.drop_duplicates("pid").set_index("pid")
    P["imp"] = P.team.map(imp); P["abs_sp"] = P.team.map(sp); P["played"] = P.pid.isin(act.index); P["a_min"] = P.pid.map(act["min"]); P["a_pts"] = P.pid.map(act["pts"]); P["date"] = d
    rows.append(P[["date", "team", "pid", "pplay", "min", "pts", "imp", "abs_sp", "played", "a_min", "a_pts"]])
R = pd.concat(rows, ignore_index=True).dropna(subset=["imp"])
print(f"{S}: {R.date.nunique()} days, {R.groupby(['date', 'team']).ngroups} team-games with a market line")
st = R[(R.played) & (R["min"] >= 28)].copy(); st["sb"] = pd.cut(st.abs_sp, [-1, 3, 6, 9, 12, 15, 40])
print("A. starters' minutes, actual - projected, by |spread|:"); print(st.groupby("sb", observed=True).apply(lambda d: pd.Series({"n": len(d), "min": (d.a_min - d["min"]).mean()}), include_groups=False).round(2).to_string())
R["tp"] = (R.pts * R.pplay).where(R["min"] >= 5, 0.0).groupby([R.date, R.team]).transform("sum")
T = R[R.played].groupby(["date", "team"]).agg(a=("a_pts", "sum"), tp=("tp", "first"), imp=("imp", "first"), n=("pid", "size")).reset_index(); T = T[(T.n >= 6) & (T.tp > 0)]
x, y = np.log(T.imp / T.tp), np.log(T.a / T.tp); b = np.polyfit(x, y, 1)
print(f"B. team points: model MAE {np.abs(T.a - T.tp).mean():.2f}, market implied (level-matched) {np.abs(T.a - T.imp * (T.a.sum() / T.imp.sum())).mean():.2f}; slope of log(actual/model) on log(implied/model) {b[0]:.2f}")
# D. line level, on graded days that have a market line
lr = []
for f in sorted(glob.glob("site/data/results/20*.json")):
    day = os.path.basename(f)[:-5]; G = gl[gl.date.astype(str) == day]
    if G.empty: continue
    imp = {}
    for r in G.itertuples(): imp[r.home] = r.total / 2 - r.spread_home / 2; imp[r.away] = r.total / 2 + r.spread_home / 2
    for p in json.load(open(f)):
        s = p["s"].get("pts")
        if s and s[1] is not None and s[2] is not None and p["t"] in imp and s[0] >= 6: lr.append((s[0], s[1], s[2], imp[p["t"]]))
L = pd.DataFrame(lr, columns=["proj", "act", "line", "imp"]); L["z"] = L.imp / L.imp.mean() - 1
def sl(yv): return np.polyfit(L.z, yv, 1)[0]
print(f"D. {len(L)} graded points lines: per unit of the game environment z: (actual-line)/line {sl((L.act - L.line) / L.line):.2f}, (actual-proj)/proj {sl((L.act - L.proj) / L.proj):.2f}")

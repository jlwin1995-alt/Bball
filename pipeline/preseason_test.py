"""Dry-run the model on a slate that is NOT in the regular season (e.g. preseason) and score it afterwards.

    python -m pipeline.preseason_test project --date 2026-10-08     # before tip-off
    python -m pipeline.preseason_test score   --date 2026-10-08     # after the games are final

Preseason minutes are wildly unlike the regular season (starters play 15-20), so raw totals are expected to
miss. The score therefore reports two things separately:
  * RATES   projected at the minutes each player ACTUALLY played -> tests the per-minute rates and matchup
            adjustments, which is what carries over to the regular season. Compared with a naive rate
            (his own historical stat-per-minute) at the same minutes.
  * MINUTES projected vs actual minutes -> expected to be poor; informational only.
Nothing here touches data/log/accuracy_log.csv. Players with no history (rookies) are not projected.
"""
import argparse, os
import numpy as np
import pandas as pd
from . import config as C
from .model import project, fantasy, _prep

OUT = "data/preseason"


def project_slate(games, slate, injuries=None, rosters=None, minute_mult=None):
    P, _ = project(games, slate, injuries, rosters=rosters, minute_mult=minute_mult)
    g = _prep(games)
    tot = g.groupby("pid")[["min"] + C.STATS].sum()
    for s in C.STATS:                                          # naive per-minute rate: his own history, no shrinkage/adjustment
        P["naive_" + s] = P["pid"].map(tot[s] / tot["min"])
    P["fp"] = fantasy(P)
    return P


def score_slate(P, actual):
    """P: output of project_slate. actual: box-score rows (pid, min, stats). Returns (summary_df, detail_df)."""
    A = actual[["pid", "min"] + C.STATS].rename(columns={c: c + "_a" for c in ["min"] + C.STATS})
    M = P.merge(A, on="pid", how="inner")
    M = M[M["min_a"] >= 8].copy()
    rows = []
    for s in C.STATS:
        model_c = M["min_a"] * M["rate_" + s]                  # model rate x actual minutes
        naive_c = M["min_a"] * M["naive_" + s]
        a = M[s + "_a"]
        rows.append(dict(stat=s, n=len(M), mae_model=(model_c - a).abs().mean(), mae_naive=(naive_c - a).abs().mean(),
                         bias_pct=(model_c.sum() - a.sum()) / a.sum() * 100 if a.sum() else np.nan,
                         mae_raw=(M[s] - a).abs().mean()))
    S = pd.DataFrame(rows)
    S["edge_pct"] = (1 - S["mae_model"] / S["mae_naive"]) * 100
    M["fp_a"] = sum(M[s + "_a"] * w for s, w in C.DEFAULT_SCORING.items())
    M["fp_c"] = sum(M["min_a"] * M["rate_" + s] * w for s, w in C.DEFAULT_SCORING.items())
    M["fp_n"] = sum(M["min_a"] * M["naive_" + s] * w for s, w in C.DEFAULT_SCORING.items())
    fp = dict(stat="fp", n=len(M), mae_model=(M["fp_c"] - M["fp_a"]).abs().mean(), mae_naive=(M["fp_n"] - M["fp_a"]).abs().mean(),
              bias_pct=(M["fp_c"].sum() - M["fp_a"].sum()) / M["fp_a"].sum() * 100, mae_raw=(M["fp"] - M["fp_a"]).abs().mean())
    fp["edge_pct"] = (1 - fp["mae_model"] / fp["mae_naive"]) * 100
    S = pd.concat([S, pd.DataFrame([fp])], ignore_index=True)
    M["min_err"] = M["min"] - M["min_a"]
    return S, M


def resolve_mult(manual, game_no, raw="data/raw"):
    """Minutes multiplier by tier: --mult wins, else learned from last preseason, else none (regular-season minutes)."""
    if manual:
        return {k.strip(): float(v) for k, v in (kv.split("=") for kv in manual.split(","))}, "manual"
    path = f"{raw}/preseason_minutes.json"
    if os.path.exists(path):
        import json
        f = json.load(open(path))
        key = str(game_no) if game_no and str(game_no) in f.get("T1", {}) else "all"
        return {t: f[t].get(key, f[t]["all"]) for t in ("T1", "T2", "T3") if t in f}, f"learned ({key})"
    return None, "none"


def cmd_project(date, manual=None, game_no=None):
    from . import fetch_espn as E
    games = pd.read_csv("data/raw/games.csv", dtype={"pid": str})
    inj = pd.read_csv("data/raw/injuries.csv", dtype={"pid": str}) if os.path.exists("data/raw/injuries.csv") else None
    ros = pd.read_csv("data/raw/rosters.csv", dtype={"pid": str}) if os.path.exists("data/raw/rosters.csv") else None
    if ros is None:
        print("note: data/raw/rosters.csv missing - run `python -m pipeline.fetch_espn` first, or traded players use their old team")
    d = pd.Timestamp(date).date()
    rows, kinds = [], set()
    for ev in E.scoreboard(d):
        comp = ev["competitions"][0]
        t = {c["homeAway"]: c["team"]["abbreviation"] for c in comp["competitors"]}
        kinds.add(ev.get("season", {}).get("type"))
        if comp["status"]["type"].get("completed"):
            print("warning: a game on this date is already final; projecting it now is not a fair test:", t)
        rows += [dict(date=d.isoformat(), team=t["home"], opp=t["away"], home=1), dict(date=d.isoformat(), team=t["away"], opp=t["home"], home=0)]
    if not rows:
        raise SystemExit(f"no games found on {d}")
    mult, how = resolve_mult(manual, game_no)
    print("preseason minutes multipliers:", mult or "none - using regular-season minutes", f"[{how}]")
    if not mult:
        print("  tip: `python -m pipeline.preseason_minutes` learns them, or pass --mult T1=0.55,T2=0.8,T3=1.05")
    P = project_slate(games, pd.DataFrame(rows), inj, ros, mult)
    os.makedirs(OUT, exist_ok=True)
    path = f"{OUT}/proj_{d}.csv"
    P.to_csv(path, index=False)
    print(f"{len(rows) // 2} games on {d} (season type(s) {sorted(k for k in kinds if k)}); projected {len(P)} players -> {path}")
    show = P[~P["out"]].sort_values("fp", ascending=False).head(15)
    print(show[["name", "team", "opp", "min", "pts", "reb", "ast", "fg3m", "fp", "status"]].round(1).to_string(index=False))
    print("\nWhen the games are final:  python -m pipeline.preseason_test score --date", d)


def cmd_score(date):
    from . import fetch_espn as E
    d = pd.Timestamp(date).date()
    path = f"{OUT}/proj_{d}.csv"
    if not os.path.exists(path):
        raise SystemExit(f"{path} not found - run `project --date {d}` BEFORE the games")
    P = pd.read_csv(path, dtype={"pid": str})
    rows = []
    for ev in E.scoreboard(d):
        comp = ev["competitions"][0]
        if not comp["status"]["type"].get("completed"):
            continue
        t = {c["homeAway"]: c["team"]["abbreviation"] for c in comp["competitors"]}
        rows += E.parse_box(ev["id"], d.isoformat(), C.SEASON, t["home"], t["away"])
    if not rows:
        raise SystemExit("no finished games yet on that date")
    S, M = score_slate(P, pd.DataFrame(rows))
    report(S, M, len(P))


def report(S, M, n_proj):
    pd.set_option("display.width", 160)
    print(f"\n{len(M)} players matched with 8+ actual minutes (of {n_proj} projected)\n")
    print("RATES at actual minutes (what carries over to the regular season):")
    print(S.assign(mae_model=S.mae_model.round(3), mae_naive=S.mae_naive.round(3), bias_pct=S.bias_pct.round(1), edge_pct=S.edge_pct.round(1))
          [["stat", "n", "mae_model", "mae_naive", "edge_pct", "bias_pct"]].to_string(index=False))
    mae_adj = M["min_err"].abs().mean()
    mae_raw = (M["min_noadj"] - M["min_a"]).abs().mean() if "min_noadj" in M else float("nan")
    print(f"\nMINUTES: actual avg {M['min_a'].mean():.1f}; projected {M['min'].mean():.1f} with the preseason adjustment (MAE {mae_adj:.1f}) "
          f"vs {M['min_noadj'].mean():.1f} without (MAE {mae_raw:.1f})")
    if "tier" in M:
        print(M.groupby("tier").agg(n=("pid", "size"), actual=("min_a", "mean"), proj=("min", "mean"), unadjusted=("min_noadj", "mean")).round(1).to_string())
    print(f"RAW fantasy points MAE (projected minutes, not actual): {S[S.stat == 'fp'].mae_raw.iloc[0]:.2f}")
    worst = M.assign(err=(M["fp_c"] - M["fp_a"]).abs()).sort_values("err", ascending=False).head(8)
    print("\nBiggest rate misses (fantasy points at actual minutes):")
    print(worst[["name", "team", "min_a", "fp_c", "fp_a"]].round(1).rename(columns={"min_a": "min", "fp_c": "proj", "fp_a": "actual"}).to_string(index=False))
    print("\nOne slate is a handful of games; treat the edge as 'nothing is broken', not as proof the model is good.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["project", "score"])
    ap.add_argument("--date", required=True)
    ap.add_argument("--mult", help="manual minutes multipliers by tier, e.g. T1=0.55,T2=0.8,T3=1.05 (T1 = 30+ mpg stars/starters)")
    ap.add_argument("--game-no", type=int, help="the team's 1st/2nd/3rd+ preseason game, to use the learned per-game factor")
    a = ap.parse_args()
    cmd_project(a.date, a.mult, a.game_no) if a.cmd == "project" else cmd_score(a.date)

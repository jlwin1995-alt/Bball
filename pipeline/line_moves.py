"""How far do the books move a teammate's line when a rotation player is ruled out?  ->  data/log/line_moves.csv  (research: nothing here feeds the model or the picks)

    python -m pipeline.line_moves            # log the board as it stands (run by the refresh workflow after the site data is built, soft-fail)
    python -m pipeline.line_moves --report   # lines that moved after a new absence, and whether the move was enough (needs graded games)

One row per (slate day, player, stat) for EVERY line on the board, not only the legs that qualify for a pick rule. first_* is the first time the line was seen, last_* the last time before tip-off
(a row is never touched once the game has started). Each side carries the PrizePicks / consensus / Underdog line, the model's projection and projected minutes, and the team's rotation players
out at that moment (from the injury report: players averaging 20+ minutes, the same list the pick rules use), so a leg whose team gained an absence between its first and last sighting can be
compared with legs whose team did not. Only moves INSIDE the window are measurable: lines first seen with the absence already priced in show no move. The NBA window is short (morning odds pull to
the pre-tip pull, about 10 hours), which is the reason to log every line rather than guess.

--report: for legs whose team lost a rotation player between first and last sighting, the mean line move (in the line's own units and as a share of the line), the mean move of the model's
projection, and mean (actual - first line) vs mean (actual - last line): if the move was enough, the second is about zero. Legs on teams with no change are the control.
"""
import os, sys, json
import pandas as pd, numpy as np

LOG, RAW = "data/log", "data/raw"
PATH = f"{LOG}/line_moves.csv"
COMBO = {"pra": ["pts", "reb", "ast"], "pr": ["pts", "reb"], "pa": ["pts", "ast"], "ra": ["reb", "ast"]}
SIDE = ["ts", "pp", "cons", "ud", "proj", "min", "out_n", "out"]
COLS = ["date", "pid", "name", "team", "game", "stat", "commence", "n_seen"] + [f"first_{c}" for c in SIDE] + [f"last_{c}" for c in SIDE]


def et_date(commence):
    return pd.Timestamp(commence).tz_convert("America/New_York").date().isoformat()


def board(out="site/data"):
    """every line on the board right now with the model's projection and the team's rotation players out."""
    lp, pp_, ap = f"{out}/lines.json", f"{out}/projections.json", f"{out}/absence.json"
    if not (os.path.exists(lp) and os.path.exists(pp_)): return [], None
    P = {str(p["pid"]): p for p in json.load(open(pp_))}
    stars = json.load(open(ap)).get("stars", {}) if os.path.exists(ap) else {}
    L = json.load(open(lp)); now = pd.Timestamp.now("UTC"); rows = []
    for r in L.get("rows", []):
        if pd.Timestamp(r["commence"]) <= now or r.get("started"): continue               # tipped off: frozen
        p = P.get(str(r["pid"])); k = r["stat"]; d = r.get("dfs") or {}; c = (r.get("cons") or {}).get("line")
        ud = d.get("underdog") if d.get("underdog") is not None else d.get("pick6")
        if d.get("prizepicks") is None and c is None and ud is None: continue
        proj = mn = None
        if p and p.get("min", 0) > 0:
            try: proj = round(sum(p["min"] * p["rate_" + x] for x in COMBO.get(k, [k])), 2); mn = round(float(p["min"]), 1)
            except KeyError: proj = None
        out_p = stars.get(r["team"], [])
        rows.append(dict(date=et_date(r["commence"]), pid=str(r["pid"]), name=r["name"], team=r["team"], game=r["game"], stat=k, commence=r["commence"],
                         pp=d.get("prizepicks"), cons=c, ud=ud, proj=proj, min=mn, out_n=len(out_p), out=";".join(sorted(x["name"] for x in out_p))))
    return rows, L.get("updated")


def log_moves(out="site/data", path=PATH):
    rows, ts = board(out)
    if not rows: print("line_moves: nothing on the board"); return None
    old = pd.read_csv(path, dtype={"pid": str}, keep_default_na=False, na_values=[""]) if os.path.exists(path) else pd.DataFrame(columns=COLS)
    idx = {(r.date, r.pid, r.stat): i for i, r in enumerate(old.itertuples())}
    recs = old.to_dict("records"); new = upd = 0
    for x in rows:
        cur = {f"last_{c}": (ts if c == "ts" else x[c]) for c in SIDE}
        key = (x["date"], x["pid"], x["stat"])
        if key in idx:
            recs[idx[key]].update(cur); recs[idx[key]]["n_seen"] = int(recs[idx[key]].get("n_seen") or 1) + 1; upd += 1
        else:
            recs.append(dict(date=x["date"], pid=x["pid"], name=x["name"], team=x["team"], game=x["game"], stat=x["stat"], commence=x["commence"], n_seen=1,
                             **{f"first_{c}": (ts if c == "ts" else x[c]) for c in SIDE}, **cur)); new += 1
    df = pd.DataFrame(recs, columns=COLS)
    os.makedirs(os.path.dirname(path), exist_ok=True); df.to_csv(path, index=False)
    print(f"line_moves: {new} new, {upd} updated; log {len(df)} rows")
    return df


def line_of(df, side):
    return df[f"{side}_pp"].fillna(df[f"{side}_cons"]).fillna(df[f"{side}_ud"])


def report(path=PATH):
    if not os.path.exists(path): print("no line-move log yet"); return
    d = pd.read_csv(path, dtype={"pid": str}); d = d[d.first_ts != d.last_ts].copy()
    if not len(d): print("no line has been seen twice yet"); return
    d["l1"], d["l2"] = line_of(d, "first"), line_of(d, "last")
    d = d.dropna(subset=["l1", "l2"])
    d["mv"] = d.l2 - d.l1; d["mv_pct"] = d.mv / d.l1.replace(0, np.nan); d["pmv"] = d.last_proj - d.first_proj
    d["new_out"] = [sorted(set(str(b).split(";")) - set(str(a).split(";")) - {"nan", ""}) for a, b in zip(d.first_out, d.last_out)]
    d["gained"] = d.new_out.map(len) > 0
    g = pd.read_csv(f"{RAW}/games.csv", dtype={"pid": str}) if os.path.exists(f"{RAW}/games.csv") else pd.DataFrame()
    if len(g):
        g = g.assign(pra=g.pts + g.reb + g.ast, pr=g.pts + g.reb, pa=g.pts + g.ast, ra=g.reb + g.ast)
        long = g.melt(id_vars=["pid", "date", "min"], value_vars=["pts", "reb", "ast", "fg3m", "pra", "pr", "pa", "ra"], var_name="stat", value_name="act")
        d = d.merge(long[long["min"] > 0][["pid", "date", "stat", "act"]], on=["pid", "date", "stat"], how="left")
    else: d["act"] = np.nan
    print(f"{len(d)} lines seen at least twice, {d.date.nunique()} slate days; {int(d.gained.sum())} of them on a team that gained a rotation absence between sightings")
    for name, x in (("team GAINED an absence", d[d.gained]), ("no change (control)", d[~d.gained])):
        if not len(x): print(f"  {name}: none"); continue
        s = f"  {name}: n={len(x)}  mean line move {x.mv.mean():+.2f} ({x.mv_pct.mean():+.1%})  moved up {(x.mv > 0).mean():.0%} / down {(x.mv < 0).mean():.0%}  model projection move {x.pmv.mean():+.2f}"
        y = x.dropna(subset=["act"]); y = y[(y.act != y.l1) & (y.act != y.l2)]
        if len(y): s += f"  | graded n={len(y)}: actual - first line {(y.act - y.l1).mean():+.2f}, actual - last line {(y.act - y.l2).mean():+.2f}"
        print(s)
    x = d[d.gained]
    if len(x):
        print("  by stat (gained):")
        print(x.groupby("stat").agg(n=("mv", "size"), line_move=("mv", "mean"), proj_move=("pmv", "mean")).round(2).to_string())
        print("  new absences:", ", ".join(sorted({n for l in x.new_out for n in l})))


if __name__ == "__main__":
    report() if "--report" in sys.argv else log_moves()

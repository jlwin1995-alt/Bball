"""odds.csv -> site/data/lines.json: per player and stat, the sportsbook consensus plus DFS lines.

    python -m pipeline.lines [--raw data/raw] [--out site/data]

Consensus (sportsbooks only, DFS books excluded): the median line across books (snapped to a line a book actually
posted), then the AVERAGE vig-free P(over) among the books posting that exact line, with the fair American odds that
implies. DFS books (PrizePicks, Underdog, Pick6) have nominal prices, so only their LINE is kept, shown next to the
consensus. The browser adds the model's P(over) and edge, because Min OVR overrides and scoring settings live there.
"""
import argparse, json, os
import numpy as np
import pandas as pd
from . import config as C
from .fetch_nba_api import norm

LOG = "data/log/lines_log.csv"


def imp(price):
    """American price -> implied probability (with vig)."""
    if price is None or pd.isna(price) or price == 0:
        return None
    price = float(price)
    return -price / (-price + 100) if price < 0 else 100 / (price + 100)


def fair_american(p):
    if p is None or not 0 < p < 1:
        return None
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def devig_over(over, under):
    a, b = imp(over), imp(under)
    return a / (a + b) if a and b else None


def build_lines(odds, roster):
    """odds: odds.csv frame. roster: DataFrame(pid, name, team). Returns the lines.json dict."""
    by_name = {}
    for r in roster.itertuples():
        by_name.setdefault(norm(r.name), []).append((str(r.pid), r.team, r.name))
    rows, unmatched = [], set()
    for (event, player, stat), g in odds.groupby(["event", "player", "stat"]):
        first = g.iloc[0]
        cands = [c for c in by_name.get(norm(player), []) if c[1] in (first["home"], first["away"])] or \
                (by_name.get(norm(player), []) if len(by_name.get(norm(player), [])) == 1 else [])
        if not cands:
            unmatched.add(player)
            continue
        pid, team, name = cands[0]
        books = [dict(b=r.book, line=float(r.line), over=None if pd.isna(r.over) else float(r.over),
                      under=None if pd.isna(r.under) else float(r.under)) for r in g.itertuples()]
        sb = [b for b in books if b["b"] not in C.DFS_BOOKS and b["over"] is not None and b["under"] is not None]
        cons = None
        if sb:
            lines = sorted(b["line"] for b in sb)
            med = float(np.median(lines))
            line = min(set(lines), key=lambda x: (abs(x - med), x))        # a line that was really posted
            ps = [devig_over(b["over"], b["under"]) for b in sb if b["line"] == line]
            ps = [p for p in ps if p is not None]
            if ps:
                p = float(np.mean(ps))
                cons = dict(line=line, n=len(ps), n_books=len(sb), lo=lines[0], hi=lines[-1], p_over=round(p, 4),
                            fair_over=fair_american(p), fair_under=fair_american(1 - p))
        dfs = {b["b"]: b["line"] for b in books if b["b"] in C.DFS_BOOKS}
        if cons or dfs:
            rows.append(dict(pid=pid, name=name, team=team, game=first["game"], commence=first["commence"], stat=stat,
                             cons=cons, dfs=dfs, books=[b for b in books if b["b"] not in C.DFS_BOOKS]))
    rows.sort(key=lambda r: (r["commence"], r["name"], r["stat"]))
    return dict(updated=str(odds["ts"].max()) if len(odds) else None, n=len(rows),
                games=sorted({r["game"] for r in rows}), unmatched=sorted(unmatched)[:25], rows=rows)


def et_date(commence):
    """ESPN scoreboard days (and so every date in the logs) are US Eastern."""
    return pd.Timestamp(commence).tz_convert("America/New_York").date().isoformat()


def snapshot_pregame(res, log=None, now=None):
    """Keep the LAST PRE-GAME consensus / PrizePicks line for every (game day, player, stat).

    Each pull overwrites that key while the game has not started; once it tips off the key is never touched again, so the row left
    in the log is the final pregame line. The Results tab grades projections against it.
    """
    log = log or LOG
    now = now or pd.Timestamp.now("UTC")
    rows = []
    for r in res.get("rows", []):
        if pd.Timestamp(r["commence"]) <= now:
            continue                                            # started: its line is already frozen
        c = r.get("cons") or {}
        rows.append(dict(date=et_date(r["commence"]), commence=r["commence"], pid=str(r["pid"]), name=r["name"], team=r["team"], game=r["game"],
                         stat=r["stat"], cons_line=c.get("line"), cons_p_over=c.get("p_over"), n_books=c.get("n"),
                         pp_line=r["dfs"].get("prizepicks"), ud_line=r["dfs"].get("underdog") if r["dfs"].get("underdog") is not None else r["dfs"].get("pick6"),
                         ts=res.get("updated")))
    if not rows:
        return 0
    new = pd.DataFrame(rows)
    old = pd.read_csv(log, dtype={"pid": str}) if os.path.exists(log) else pd.DataFrame(columns=new.columns)
    key = lambda d: d["date"].astype(str) + "|" + d["pid"].astype(str) + "|" + d["stat"].astype(str)
    old = old[~key(old).isin(set(key(new)))] if len(old) else old
    os.makedirs(os.path.dirname(log), exist_ok=True)
    pd.concat([old, new], ignore_index=True).to_csv(log, index=False)
    return len(new)


def main(raw, out):
    p = f"{raw}/odds.csv"
    if not os.path.exists(p):
        print("no odds.csv; skipping lines.json")
        return
    odds = pd.read_csv(p)
    if odds.empty:
        print("odds.csv is empty (no games in the window?); writing an empty lines.json")
    ros = pd.read_csv(f"{raw}/rosters.csv", dtype={"pid": str}) if os.path.exists(f"{raw}/rosters.csv") else None
    if ros is None:                                                         # fall back to last team in the box scores
        g = pd.read_csv(f"{raw}/games.csv", dtype={"pid": str}).sort_values("date")
        ros = g.drop_duplicates("pid", keep="last")[["pid", "name", "team"]]
    res = build_lines(odds, ros) if len(odds) else dict(updated=None, n=0, games=[], unmatched=[], rows=[])
    mp = f"{raw}/odds_meta.json"
    if os.path.exists(mp):
        res["meta"] = json.load(open(mp))                       # when we last looked, which games exist, credits left
    os.makedirs(out, exist_ok=True)
    json.dump(res, open(f"{out}/lines.json", "w"), separators=(",", ":"))
    snapshot_pregame(res)
    print(f"lines.json: {res['n']} player-stat lines, {len(res['games'])} games, {len(res['unmatched'])} unmatched names")
    if res["unmatched"]:
        print("  unmatched (check name spellings):", ", ".join(res["unmatched"][:10]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="site/data")
    a = ap.parse_args()
    main(a.raw, a.out)

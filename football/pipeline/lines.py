"""odds.csv + projections.json -> site/data/lines.json: per player and market, the sportsbook consensus plus DFS lines.

    python -m pipeline.lines [--raw data/raw] [--out site/data]

Consensus (sportsbooks only, DFS books excluded): the median line across books (snapped to a line a book actually posted), then the
AVERAGE vig-free P(over) among the books posting that exact line, with the fair American odds that implies. DFS books (PrizePicks,
Underdog, Pick6) have nominal prices, so only their LINE is kept, shown next to the consensus. The browser adds the model's P(over)
and edge, because volume overrides and the scoring preset live there.
"""
import argparse, csv, json, os, re, statistics
from . import config as C
from .fetch_odds import read_rows

LOG = "data/log/lines_log.csv"
STAT_OF = {v[0]: v for v in C.ODDS_MARKETS.values()}


def norm(s):
    """Names differ between feeds; strip everything that is not a letter, and generational suffixes."""
    s = re.sub(r"[^a-z ]", "", str(s or "").lower())
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def imp(price):
    """American price -> implied probability (with vig)."""
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if p == 0 or p != p:
        return None
    return -p / (-p + 100) if p < 0 else 100 / (p + 100)


def fair_american(p):
    if p is None or not 0 < p < 1:
        return None
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def devig_over(over, under):
    a, b = imp(over), imp(under)
    return a / (a + b) if a and b else None


def fnum(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def build_lines(odds, players):
    """odds: rows from odds.csv. players: the projections list (id, name, team, att, pos). Returns the lines.json dict."""
    by_name = {}
    for p in players:
        by_name.setdefault(norm(p["name"]), []).append(p)
    groups = {}
    for r in odds:
        groups.setdefault((r["event"], r["player"], r["stat"]), []).append(r)
    rows, unmatched = [], set()
    for (event, player, stat), g in groups.items():
        first = g[0]
        # the player has to actually be in this game, or a name shared across the league lands one team's price on another's row
        cands = [p for p in by_name.get(norm(player), []) if p["team"] in (first["home"], first["away"])]
        if len(cands) != 1:
            unmatched.add(player)
            continue
        p = cands[0]
        # sacks are posted both ways (taken by a passer, made by a rusher) under one market key; only a QB has attempts projected
        if stat == "sacks" and not p.get("att"):
            continue
        books = [dict(b=r["book"], line=float(r["line"]), over=fnum(r["over"]), under=fnum(r["under"])) for r in g if fnum(r["line"]) is not None]
        sb = [b for b in books if b["b"] not in C.DFS_BOOKS and b["over"] is not None and b["under"] is not None]
        cons = None
        if sb:
            lines = sorted(b["line"] for b in sb)
            med = statistics.median(lines)
            line = min(set(lines), key=lambda x: (abs(x - med), x))        # a line that was really posted
            ps = [devig_over(b["over"], b["under"]) for b in sb if b["line"] == line]
            ps = [x for x in ps if x is not None]
            if ps:
                po = sum(ps) / len(ps)
                cons = dict(line=line, n=len(ps), n_books=len(sb), lo=lines[0], hi=lines[-1], p_over=round(po, 4),
                            fair_over=fair_american(po), fair_under=fair_american(1 - po))
        dfs = {b["b"]: b["line"] for b in books if b["b"] in C.DFS_BOOKS}
        if cons or dfs:
            rows.append(dict(id=p["id"], name=p["name"], team=p["team"], pos=p["pos"], game=f"{first['away']} @ {first['home']}", commence=first["commence"],
                             stat=stat, cons=cons, dfs=dfs, books=[b for b in books if b["b"] not in C.DFS_BOOKS]))
    rows.sort(key=lambda r: (r["commence"], r["name"], r["stat"]))
    return dict(updated=max((r["ts"] for r in odds), default=None), n=len(rows), games=sorted({r["game"] for r in rows}),
                unmatched=sorted(unmatched)[:25], rows=rows)


def snapshot_pregame(res, log=None, now=None):
    """Keep the LAST PRE-GAME consensus / PrizePicks line for every (game, player, stat).

    Each pull overwrites that key while the game has not started; once it kicks off the key is never touched again, so the row left in
    the log is the final pregame line. The Results tab grades projections against it.
    """
    import datetime as dt
    log = log or LOG
    now = now or dt.datetime.now(dt.timezone.utc)
    rows = []
    for r in res.get("rows", []):
        if dt.datetime.fromisoformat(r["commence"].replace("Z", "+00:00")) <= now:
            continue                                            # started: its line is already frozen
        c = r.get("cons") or {}
        rows.append(dict(commence=r["commence"], game=r["game"], player_id=r["id"], name=r["name"], team=r["team"], stat=r["stat"],
                         cons_line=c.get("line", ""), cons_p_over=c.get("p_over", ""), n_books=c.get("n", ""),
                         pp_line=r["dfs"].get("prizepicks", ""), ud_line=r["dfs"].get("underdog", r["dfs"].get("pick6", "")), ts=res.get("updated")))
    if not rows:
        return 0
    cols = ["commence", "game", "player_id", "name", "team", "stat", "cons_line", "cons_p_over", "n_books", "pp_line", "ud_line", "ts"]
    key = lambda d: f"{d['game']}|{d['player_id']}|{d['stat']}"
    fresh = {key(x) for x in rows}
    old = []
    if os.path.exists(log):
        with open(log, newline="") as f:
            old = [x for x in csv.DictReader(f) if key(x) not in fresh]
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(old + rows)
    return len(rows)


def main(raw="data/raw", out="site/data", games=None):
    """games: this week's "AWAY @ HOME" labels. Odds rows for any other game (last week's, if no pull has cleaned them out) are ignored."""
    p = f"{raw}/odds.csv"
    if not os.path.exists(p):
        print("no odds.csv; skipping lines.json")
        return
    odds = read_rows(p)
    if games is not None:
        odds = [r for r in odds if r["game"] in games]
    players = json.load(open(f"{out}/projections.json"))
    res = build_lines(odds, players) if odds else dict(updated=None, n=0, games=[], unmatched=[], rows=[])
    mp = f"{raw}/odds_meta.json"
    if os.path.exists(mp):
        res["meta"] = json.load(open(mp))                       # when we last looked, which games exist, credits left
    os.makedirs(out, exist_ok=True)
    json.dump(res, open(f"{out}/lines.json", "w"), separators=(",", ":"))
    snapshot_pregame(res, log=os.path.join(os.path.dirname(os.path.abspath(raw)), "log", "lines_log.csv"))
    print(f"lines.json: {res['n']} player-market lines, {len(res['games'])} games, {len(res['unmatched'])} unmatched names")
    if res["unmatched"]:
        print("  unmatched (check name spellings or the player is not projected this week):", ", ".join(res["unmatched"][:10]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="site/data")
    a = ap.parse_args()
    main(a.raw, a.out)

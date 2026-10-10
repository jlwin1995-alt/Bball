"""Projected vs actual, per player, per game week -> site/data/results/index.json and results/<season>-<week>.json

Joins three things: the frozen pre-kickoff projections (data/log/accuracy_log.csv), the box scores, and the LAST PREGAME consensus and
PrizePicks line for each player and market (data/log/lines_log.csv, snapshotted at every odds pull until kickoff, never touched after).
The model "takes" the over when its projection is above a line and the under when below; a result exactly on the line is a push and is
left out. A PICK is a line where the model's probability differs from the book's by RESULTS_EDGE_PP (PrizePicks: from the break-even).
A game with no odds pull before kickoff has no line to grade against.
"""
import csv, datetime as dt, json, os
from . import config as C
from .backtest import STATS, actual
from .prob import SPEC, sides
from .scorecard import read_log

LINES_LOG = "data/log/lines_log.csv"
KEYS = [k for k, *_ in STATS]


def fnum(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def grade(a, line, side):
    """True = the side won, False = lost, None = push."""
    if a == line:
        return None
    return a > line if side == "O" else a < line


def tally(rec, res):
    if res is None:
        return
    rec[0] += 1
    rec[1] += 1 if res else 0


def main(rows, live, out="site/data", log_path=None, lines_path=LINES_LOG, W=None):
    W = W or C.DEFAULT_SCORING
    log_path = log_path or "data/log/accuracy_log.csv"
    log = [r for r in read_log(log_path) if str(r["late"]) != "1"]
    act = {(r["player_id"], int(r["week"])): r for r in rows}
    lines = {}
    if os.path.exists(lines_path):
        with open(lines_path, newline="") as f:
            for r in csv.DictReader(f):
                lines.setdefault((r["player_id"], r["stat"]), []).append(r)
    os.makedirs(f"{out}/results", exist_ok=True)
    by_week = {}
    for r in log:
        by_week.setdefault((int(r["season"]), int(r["week"])), []).append(r)
    index, edge, be = [], C.RESULTS_EDGE_PP / 100, C.PP_BREAKEVEN
    for (season, week), lr in sorted(by_week.items()):
        players, dnp = [], 0
        sm = dict(n=0, ae=dict(m=0.0, s=0.0, l=0.0), cons=[0, 0], cons_pick=[0, 0], pp=[0, 0], pp_pick=[0, 0])
        per_mkt = {}
        for r in lr:
            wk = int(r["week"])
            if not (live.get((r["team"], float(wk))) or live.get((r["team"], wk))):
                continue                                           # the team's game is not in the box scores yet
            a_row = act.get((r["player_id"], wk))
            if a_row is None:
                dnp += 1
                continue
            a = actual(a_row, W)
            k0 = dt.datetime.fromisoformat(r["kickoff"]) if r["kickoff"] else None
            pl = dict(id=r["player_id"], name=r["name"], pos=r["pos"], team=r["team"], opp=r["opp"], status=r["status"],
                      vol={"car": [fnum(r["car"]), a_row.get("carries", 0.0)], "tgt": [fnum(r["tgt"]), a_row.get("targets", 0.0)],
                           "att": [fnum(r["att"]), a_row.get("attempts", 0.0)]},
                      m={})
            for k in KEYS:
                p = fnum(r[f"p_{k}"])
                ent = dict(p=p, a=round(a[k], 2), bs=fnum(r[f"bs_{k}"]), bl=fnum(r[f"bl_{k}"]))
                if k == "pts":
                    sm["n"] += 1
                    sm["ae"]["m"] += abs(p - a[k]); sm["ae"]["s"] += abs((ent["bs"] or 0) - a[k]); sm["ae"]["l"] += abs((ent["bl"] or 0) - a[k])
                spec = SPEC.get(k)
                if spec:
                    # the last pregame line for this player and market, from the odds pull closest before THIS game's kickoff
                    cand = [x for x in lines.get((r["player_id"], k), []) if x["team"] == r["team"] and k0
                            and abs((dt.datetime.fromisoformat(x["commence"].replace("Z", "+00:00")) - k0).total_seconds()) < 6 * 3600]
                    ln = cand[-1] if cand else None
                    cl, pl_, ul = (fnum(ln["cons_line"]), fnum(ln["pp_line"]), fnum(ln["ud_line"])) if ln else (None, None, None)
                    mk = per_mkt.setdefault(k, dict(cons=[0, 0], cons_pick=[0, 0], pp=[0, 0], pp_pick=[0, 0]))
                    if cl is not None and p is not None:
                        po, _ = sides(cl, p, spec)
                        side = "O" if p > cl else "U"
                        g = grade(a[k], cl, side)
                        ent["line"], ent["side"], ent["hit"] = cl, side, g
                        tally(mk["cons"], g); tally(sm["cons"], g)
                        pc = fnum(ln["cons_p_over"])
                        if pc is not None and abs(po - pc) >= edge:
                            ps = "O" if po > pc else "U"
                            gp = grade(a[k], cl, ps)
                            ent["pick"] = ps; ent["pick_hit"] = gp
                            tally(mk["cons_pick"], gp); tally(sm["cons_pick"], gp)
                    if pl_ is not None and p is not None:
                        o, u = sides(pl_, p, spec)
                        side = "O" if o >= u else "U"
                        g = grade(a[k], pl_, side)
                        ent["pp"] = pl_; ent["pp_side"] = side; ent["pp_hit"] = g
                        tally(mk["pp"], g); tally(sm["pp"], g)
                        if max(o, u) - be >= edge:
                            tally(mk["pp_pick"], g); tally(sm["pp_pick"], g)
                            ent["pp_pick"] = True
                    if ul is not None:
                        ent["ud"] = ul
                pl["m"][k] = ent
            players.append(pl)
        if not players:
            continue
        n = sm["n"]
        row = dict(season=season, week=week, n=n, dnp=dnp,
                   mae=round(sm["ae"]["m"] / n, 3), base=round(sm["ae"]["s"] / n, 3), last3=round(sm["ae"]["l"] / n, 3),
                   cons=sm["cons"], cons_pick=sm["cons_pick"], pp=sm["pp"], pp_pick=sm["pp_pick"],
                   mkts={k: v for k, v in per_mkt.items()})
        index.append(row)
        json.dump(dict(**row, players=players), open(f"{out}/results/{season}-{week}.json", "w"), separators=(",", ":"))
    json.dump(dict(weeks=index, edge_pp=C.RESULTS_EDGE_PP, pp_breakeven=be * 100), open(f"{out}/results/index.json", "w"), separators=(",", ":"))
    return len(index)

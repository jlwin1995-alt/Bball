"""Game-by-game results per player and market  ->  site/data/hist.json and site/data/cfb/hist.json  (display only)

{player_id: {stat: [values, oldest first, last 10 games]}} from the box scores, so the Lines tabs can show "cleared N of the last M": how many of his recent games beat the posted line.
Written by the data refresh (not by the odds-only rebuild of lines.json); the page joins it to the live lines by player id and market. A game counts when the player had real volume in it
(carries, targets or receptions, attempts): a row with no touches is not a game for the market. Markets by position: QB passY / rushY (and comp, sacks in the NFL), RB rushY / recY / rec,
WR and TE recY / rec. Every player also gets `fp`: Full PPR fantasy points per game (the Game Board's Consistency column)."""
import json, os

MAXG = 10
COLS = {"rushY": "rushing_yards", "recY": "receiving_yards", "rec": "receptions", "passY": "passing_yards", "comp": "completions", "sacks": "sacks_suffered"}
BY_POS = {"QB": ("passY", "rushY", "comp", "sacks", "fp"), "RB": ("rushY", "recY", "rec", "fp"), "FB": ("rushY", "recY", "rec", "fp"), "WR": ("recY", "rec", "fp"), "TE": ("recY", "rec", "fp")}


def ppr(r, college):
    """Full PPR fantasy points of one box-score row (the Game Board's Consistency column; nflverse already carries fantasy_points_ppr)."""
    g = lambda c: float(r.get(c) or 0)
    if not college and r.get("fantasy_points_ppr") not in (None, ""):
        return g("fantasy_points_ppr")
    if college:
        return (g("passing_yards") * 0.04 + g("passing_tds") * 4 - g("interceptions") + g("rushing_yards") * 0.1 + g("rushing_tds") * 6
                + g("receptions") + g("receiving_yards") * 0.1 + g("receiving_tds") * 6 - g("fumbles_lost"))
    return None


def build(rows, college=False):
    idk = "playerId" if college else "player_id"
    by = {}
    for r in rows:
        by.setdefault(r[idk], []).append(r)
    out = {}
    for pid, gs in by.items():
        gs.sort(key=lambda r: int(float(r["week"])))
        pos = str(gs[-1].get("position") or "").upper()
        stats = BY_POS.get(pos)
        if not stats:
            continue
        d = {}
        for st in stats:
            if college and st in ("comp", "sacks"):
                continue
            vals = []
            for r in gs:
                touches = (r.get("carries", 0) or 0) + (r.get("targets", 0) or 0) + (r.get("receptions", 0) or 0) + (r.get("attempts", 0) or 0)
                if touches <= 0:
                    continue
                if st == "passY" and (r.get("attempts", 0) or 0) < 1:
                    continue
                if st in ("recY", "rec") and pos == "QB":
                    continue
                if st == "fp":
                    v = ppr(r, college)
                    if v is not None:
                        vals.append(round(v, 1))
                    continue
                v = r.get(COLS[st])
                if v is None or v == "":
                    continue
                vals.append(round(float(v), 1) if st in ("sacks",) else int(round(float(v))))
            if vals:
                d[st] = vals[-MAXG:]
        if d:
            out[pid] = d
    return out


def write(rows, path, college=False):
    h = build(rows, college)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(h, open(path, "w"), separators=(",", ":"))
    return len(h)

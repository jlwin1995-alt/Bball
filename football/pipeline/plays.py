"""Ranked NFL plays from the current board (the rules in README "Decision (2026-11-16)"), sorted by the blend probability.

    python -m pipeline.plays [--all] [--data DIR] [--asof ISO]   # --all lists the lines the rules dropped, with the reason; --data/--asof replay an old board

Rules: two or more books, raw model confidence 62%+, depth-chart starter, no shift / returning / moved / status / thin flag, projection 0.55-1.6 of the
line, Unders on receptions and receiving yards only (no Overs, no rushing Unders), no Miami pass
catchers. Sort: blend P(side) = market + BLEND_K x (model - market) on the side, BLEND_K 0.25 (README "Model against the market", 2026-11-16).
"""
import csv, json, sys
from datetime import datetime, timezone
from . import prob, config as C

BLEND_K = 0.25
KEY = {"rushY": "ry", "recY": "recy", "rec": "rec", "passY": "py", "comp": "comp"}
SPEC = {v[0]: dict(a=v[2], b=v[3], law=v[4]) for v in C.ODDS_MARKETS.values()}
STATS = {"rec", "recY"}
GUARD_CSV = "data/log/plays_team_guard.csv"   # team, from_week, to_week (blank = open), reason: teams whose pass catchers are left off the list


def team_guard(week, path=GUARD_CSV):
    """-> {team: reason} for the teams guarded in `week`."""
    out = {}
    try:
        for r in csv.DictReader(open(path)):
            if int(r["from_week"] or 0) <= week and (not r["to_week"] or week <= int(r["to_week"])):
                out[r["team"]] = r["reason"]
    except FileNotFoundError:
        pass
    return out


def swapped_teams(P):
    """Teams whose depth-chart quarterback is new to the job: moved at the deadline, a Starter override, or under 3 games of history."""
    out = set()
    for p in P.values():
        if p["pos"] == "QB" and ((p.get("depth") or {}).get("st") or p["status"] == "Starter") and (p.get("moved") or p["status"] == "Starter" or p["g"] < 3):
            out.add(p["team"])
    return out


def build(data="site/data", asof=None):
    L = json.load(open(f"{data}/lines.json"))
    P = {p["id"]: p for p in json.load(open(f"{data}/projections.json"))}
    H = json.load(open(f"{data}/hist.json"))
    now = asof or datetime.now(timezone.utc).isoformat()
    qb_new = swapped_teams(P)
    guard = team_guard(int(json.load(open(f"{data}/meta.json")).get("week") or 0))
    out = []
    for r in L["rows"]:
        p, c, s = P.get(r["id"]), r.get("cons"), r["stat"]
        if not p or not c or s not in KEY or r["commence"] <= now:
            continue
        m, line = p[KEY[s]], c["line"]
        o, u = prob.sides(line, m, SPEC[s])
        side, conf = ("Over", o) if o >= u else ("Under", u)
        mk = c["p_over"] if side == "Over" else 1 - c["p_over"]
        blend = mk + BLEND_K * (conf - mk)
        h = H.get(r["id"], {}).get(s) or []
        cl = sum(v > line for v in h) / len(h) if len(h) >= 3 else None
        why = []
        if c["n_books"] < 2: why.append("one book")
        if conf < 0.62: why.append("model under 62%")
        if side != "Under": why.append("Over")
        if s not in STATS: why.append("market not on the list")
        if not (p.get("depth") or {}).get("st"): why.append("not depth starter")
        why += [f for f in ("shift", "ret", "moved") if p.get(f)]
        if p["status"]: why.append(p["status"])
        if p["g"] < 3: why.append("thin")
        if not 0.55 <= (m / line if line else 9) <= 1.6: why.append("gap to line")
        # no "cleared the line in 40%+ of his games" guard here: on 372 graded NFL receptions / receiving-yards Unders it was backwards (README 2026-11-18)
        if p["pos"] != "QB" and p["team"] in guard: why.append("team guard: " + guard[p["team"]].split(";")[0])
        if p["pos"] != "QB" and p["team"] in qb_new: why.append("new quarterback")
        out.append(dict(name=p["name"], team=p["team"], game=r["game"], stat=s, side=side, line=line, proj=round(m, 1), conf=conf, market=mk,
                        blend=blend, cleared=cl, n=len(h), books=c["n_books"], why=why))
    return out


def main():
    arg = lambda k: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else None
    rows = build(arg("--data") or "site/data", arg("--asof"))
    ok = sorted((x for x in rows if not x["why"]), key=lambda x: -x["blend"])
    print(f"{len(ok)} plays (of {len(rows)} upcoming lines), sorted by blend P(side):")
    for i, x in enumerate(ok, 1):
        cl = "-" if x["cleared"] is None else f"{round(x['cleared'] * 100)}%/{x['n']}"
        print(f"{i:2}. {x['name']} ({x['team']}, {x['game']}) {x['stat']} {x['side']} {x['line']}  proj {x['proj']}  market {x['market'] * 100:.0f}%  model {x['conf'] * 100:.0f}%  blend {x['blend'] * 100:.1f}%  cleared {cl}  books {x['books']}")
    if "--all" in sys.argv:
        for x in sorted((x for x in rows if x["why"] and x["conf"] >= 0.62), key=lambda x: -x["blend"]):
            print(f"   dropped: {x['name']} {x['stat']} {x['side']} {x['line']}  ({', '.join(x['why'])})")


if __name__ == "__main__":
    main()

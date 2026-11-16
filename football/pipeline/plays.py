"""Ranked NFL plays from the current board (the rules in README "Decision (2026-11-16)"), sorted by the blend probability.

    python -m pipeline.plays [--all]      # --all also lists lines the rules dropped, with the reason

Rules: two or more books, raw model confidence 62%+, depth-chart starter, no shift / returning / moved / status / thin flag, projection 0.55-1.6 of the
line, Unders on receptions and receiving yards only (no Overs, no rushing Unders), player cleared the line in under 40% of his last games, no Miami pass
catchers. Sort: blend P(side) = market + BLEND_K x (model - market) on the side, BLEND_K 0.25 (README "Model against the market", 2026-11-16).
"""
import json, sys
from datetime import datetime, timezone
from . import prob, config as C

BLEND_K = 0.25
KEY = {"rushY": "ry", "recY": "recy", "rec": "rec", "passY": "py", "comp": "comp"}
SPEC = {v[0]: dict(a=v[2], b=v[3], law=v[4]) for v in C.ODDS_MARKETS.values()}
STATS = {"rec", "recY"}
NO_TEAM = {"MIA"}


def build(data="site/data"):
    L = json.load(open(f"{data}/lines.json"))
    P = {p["id"]: p for p in json.load(open(f"{data}/projections.json"))}
    H = json.load(open(f"{data}/hist.json"))
    now = datetime.now(timezone.utc).isoformat()
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
        if cl is not None and cl >= 0.4: why.append("cleared line %d%%" % round(cl * 100))
        if p["team"] in NO_TEAM: why.append("team guard")
        out.append(dict(name=p["name"], team=p["team"], game=r["game"], stat=s, side=side, line=line, proj=round(m, 1), conf=conf, market=mk,
                        blend=blend, cleared=cl, n=len(h), books=c["n_books"], why=why))
    return out


def main():
    rows = build()
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

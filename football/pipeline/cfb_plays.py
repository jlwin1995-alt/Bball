"""Ranked college plays from the current board, sorted by the blend probability (college twin of plays.py).

    python -m pipeline.cfb_plays [--all] [--data DIR] [--asof ISO]

Rules (README "College plays rules", 2026-11-16): two or more books, raw model confidence 62%+, projection 0.55-1.6 of the line, a depth-chart starter
(not an override / no-line / returning / out player, 3+ games of history), and only the categories with evidence: receptions Under, passing yards Over,
rushing yards Under. No receiving yards, no other Overs. Guards: Unders only if the player cleared the line in under 40% of his last games; no rushing
Under when his team is a 6+ point favourite (favourite backs beat their projections); no receptions Under in a 65+ total; no passing Over in a total
under 45 (low scoring caps volume). Sort: blend P(side) = market + BLEND_K x (model - market) on the model's side; BLEND_K 0.25 as in the NFL list.
The blend needs a real market price, which is why one-book lines (about 3 in 4 college lines, price fixed at 50%) are excluded.
"""
import json, sys
from datetime import datetime, timezone
from . import prob

BLEND_K = 0.25
KEY = {"rushY": "ry", "recY": "recy", "rec": "rec", "passY": "py"}
OK = {("rec", "Under"), ("passY", "Over"), ("rushY", "Under")}


def build(data="site/data/cfb", asof=None):
    L = json.load(open(f"{data}/lines.json"))
    P = {p["id"]: p for p in json.load(open(f"{data}/projections.json"))}
    H = json.load(open(f"{data}/hist.json"))
    G = {g["game"]: g for g in json.load(open(f"{data}/games.json"))}
    now = asof or datetime.now(timezone.utc).isoformat()
    out = []
    for r in L["rows"]:
        p, c, s = P.get(r["id"]), r.get("cons"), r["stat"]
        if not p or not c or s not in KEY or r["commence"] <= now:
            continue
        m, line, spec = p[KEY[s]], c["line"], L["specs"][s]
        o, u = prob.sides(line, m, spec)
        side, conf = ("Over", o) if o >= u else ("Under", u)
        mk = c["p_over"] if side == "Over" else 1 - c["p_over"]
        blend = mk + BLEND_K * (conf - mk)
        h = H.get(r["id"], {}).get(s) or []
        cl = sum(v > line for v in h) / len(h) if len(h) >= 3 else None
        g = G.get(p["game"]) or {}
        home = p["site"] == "vs"
        fav = (g["home_imp"] - g["away_imp"]) * (1 if home else -1) if g.get("home_imp") is not None else None
        tot = g.get("total")
        why = []
        if c["n_books"] < 2: why.append("one book")
        if conf < 0.62: why.append("model under 62%")
        if (s, side) not in OK: why.append("category not on the list")
        if not (p.get("depth") or {}).get("st"): why.append("not depth starter")
        why += [f for f in ("starter", "noline", "returning", "out") if p.get(f)]
        if p["g"] < 3: why.append("thin")
        if not 0.55 <= (m / line if line else 9) <= 1.6: why.append("gap to line")
        if side == "Under" and cl is not None and cl >= 0.4: why.append("cleared line %d%%" % round(cl * 100))
        if s == "rushY" and side == "Under" and fav is not None and fav >= 6: why.append("favourite by %.1f" % fav)
        if s == "rec" and side == "Under" and tot and tot >= 65: why.append("total %.1f" % tot)
        if s == "passY" and side == "Over" and tot and tot < 45: why.append("low total %.1f" % tot)
        out.append(dict(name=p["name"], team=p["team"], game=r["game"], stat=s, side=side, line=line, proj=round(m, 1), conf=conf, market=mk,
                        blend=blend, cleared=cl, n=len(h), books=c["n_books"], fav=fav, total=tot, why=why))
    return out


def main():
    arg = lambda k: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else None
    rows = build(arg("--data") or "site/data/cfb", arg("--asof"))
    ok = sorted((x for x in rows if not x["why"]), key=lambda x: -x["blend"])
    print(f"{len(ok)} plays (of {len(rows)} upcoming lines), sorted by blend P(side):")
    for i, x in enumerate(ok, 1):
        cl = "-" if x["cleared"] is None else f"{round(x['cleared'] * 100)}%/{x['n']}"
        print(f"{i:2}. {x['name']} ({x['team']}, {x['game']}) {x['stat']} {x['side']} {x['line']}  proj {x['proj']}  market {x['market'] * 100:.0f}%  model {x['conf'] * 100:.0f}%  blend {x['blend'] * 100:.1f}%  cleared {cl}  books {x['books']}")
    if "--all" in sys.argv:
        for x in sorted((x for x in rows if x["why"] and x["conf"] >= 0.62 and x["books"] >= 2), key=lambda x: -x["blend"]):
            print(f"   dropped: {x['name']} ({x['team']}) {x['stat']} {x['side']} {x['line']}  ({', '.join(x['why'])})")


if __name__ == "__main__":
    main()

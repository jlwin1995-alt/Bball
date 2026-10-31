"""Pregame highlights: the few PrizePicks leg types whose graded record has held up  ->  site/data/highlights.json

    python -m pipeline.highlights [--out site/data]

Every graded PrizePicks line (voids and pushes out) is put through the same probability the Lines tab shows (normal around the projection, fitted
spread). SEGMENTS are leg types picked from the first two weeks (Oct 20-29: 5,820 lines, overall hit 50.5%): rebound Overs, assist Unders, and
the model's own 70%+ Overs, which have been a cold spot (the record covers every leg of the segment; tonight's list shows only the backed legs where the model is 55%+ sure). Each segment's record is recomputed on every refresh, with the two halves of the
dates side by side, and a segment is ACTIVE only while its record holds:
    backed   active while n >= MIN_N and hit rate >= PP_BREAKEVEN          (shown as BACKED)
    caution  active while n >= MIN_N and hit rate <= CAUTION_BELOW         (shown as CAUTION)
`today` lists tonight's PrizePicks lines that fall in an active segment. Honest caveat, also on the site: these were found by looking at about 50
cuts of a small sample, so treat them as 'best supported so far', not as an edge.
"""
import argparse, glob, json, os
import numpy as np
from . import config as C
from . import results as R

MIN_N = 100
SHOW_PW = 0.55                    # a backed segment lists tonight only its legs where the model is at least this sure (the record covers the whole segment)
CAUTION_BELOW = 0.47
STATS = ["pts", "reb", "ast", "fg3m", "pra", "pr", "pa", "ra"]
COMBO = {"pra": ["pts", "reb", "ast"], "pr": ["pts", "reb"], "pa": ["pts", "ast"], "ra": ["reb", "ast"]}
SEGMENTS = [
    {"id": "reb_over", "kind": "backed", "label": "Rebound Overs", "test": lambda s, st, pw: s == "O" and st == "reb"},
    {"id": "ast_under", "kind": "backed", "label": "Assist Unders", "test": lambda s, st, pw: s == "U" and st == "ast"},
    {"id": "over70", "kind": "caution", "label": "Model Overs at 70%+", "test": lambda s, st, pw: s == "O" and pw >= 0.70},
]


def _spread(raw):
    return {**C.SPREAD_DEFAULT, **(json.load(open(f"{raw}/spread.json")) if os.path.exists(f"{raw}/spread.json") else {})}


def records(results_dir="site/data/results", raw="data/raw"):
    sp = _spread(raw)
    days = sorted(glob.glob(os.path.join(results_dir, "20??-??-??.json")))
    mid = os.path.basename(days[len(days) // 2])[:10] if days else ""
    rec = {s["id"]: {"n": 0, "w": 0, "nA": 0, "wA": 0, "nB": 0, "wB": 0} for s in SEGMENTS}
    for f in days:
        day = os.path.basename(f)[:10]; half = "A" if day < mid else "B"
        for p in json.load(open(f)):
            if p.get("v"):
                continue
            for k, v in p["s"].items():
                if k not in STATS or v[3] is None:
                    continue
                pr, ac, pl = v[0], v[1], v[3]
                a, b = sp.get(k, [1.0, 0.3]); sd = max(a + b * pr, 0.1)
                po, pu = R.sides(pl, pr, sd); side = "O" if po >= pu else "U"; pw = max(po, pu)
                g = R.grade(ac, pl, side)
                if g is None:
                    continue
                for s in SEGMENTS:
                    if s["test"](side, k, pw):
                        r = rec[s["id"]]; r["n"] += 1; r["w"] += int(g); r["n" + half] += 1; r["w" + half] += int(g)
    return rec, mid


def build(out="site/data", raw="data/raw"):
    rec, mid = records(os.path.join(out, "results"), raw)
    be = C.PP_BREAKEVEN
    segs = []
    for s in SEGMENTS:
        r = rec[s["id"]]; hit = r["w"] / r["n"] if r["n"] else None
        active = bool(r["n"] >= MIN_N and hit is not None and (hit >= be if s["kind"] == "backed" else hit <= CAUTION_BELOW))
        segs.append({"id": s["id"], "kind": s["kind"], "label": s["label"], "n": r["n"], "hit": None if hit is None else round(hit, 3),
                     "hitA": round(r["wA"] / r["nA"], 3) if r["nA"] else None, "hitB": round(r["wB"] / r["nB"], 3) if r["nB"] else None, "active": active})
    today = []
    lp, pp_ = f"{out}/lines.json", f"{out}/projections.json"
    if os.path.exists(lp) and os.path.exists(pp_):
        sp = _spread(raw)
        P = {p["pid"]: p for p in json.load(open(pp_))}
        act = [s for s in SEGMENTS if any(x["id"] == s["id"] and x["active"] for x in segs)]
        for r in json.load(open(lp)).get("rows", []):
            p = P.get(r["pid"]); pl = (r.get("dfs") or {}).get("prizepicks"); k = r["stat"]
            if not p or pl is None or p["min"] <= 0 or k not in STATS or r.get("started"):
                continue
            m = sum(p["min"] * p["rate_" + c] for c in COMBO.get(k, [k]))
            a, b = sp.get(k, [1.0, 0.3]); sd = max(a + b * m, 0.1)
            po, pu = R.sides(pl, m, sd); side = "O" if po >= pu else "U"; pw = max(po, pu)
            for s in act:
                if s["test"](side, k, pw) and (s["kind"] == "caution" or pw >= SHOW_PW):
                    today.append({"pid": r["pid"], "name": p["name"], "team": p["team"], "game": r["game"], "stat": k, "side": side, "line": pl, "pw": round(pw, 3),
                                  "proj": round(m, 1), "min": round(p["min"]), "status": p.get("status") or "", "seg": s["id"], "kind": s["kind"]})
    today.sort(key=lambda x: (x["kind"] != "backed", -x["pw"]))
    return {"asof": os.path.basename(sorted(glob.glob(f"{out}/results/20??-??-??.json"))[-1])[:10] if glob.glob(f"{out}/results/20??-??-??.json") else None,
            "breakeven": be, "min_n": MIN_N, "caution_below": CAUTION_BELOW, "split_at": mid, "segments": segs, "today": today}


def main(out="site/data", raw="data/raw"):
    h = build(out, raw)
    json.dump(h, open(os.path.join(out, "highlights.json"), "w"), separators=(",", ":"))
    return h


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data")
    a = ap.parse_args()
    h = main(a.out)
    for s in h["segments"]:
        print(s["id"], s["kind"], "n", s["n"], "hit", s["hit"], "halves", s["hitA"], s["hitB"], "ACTIVE" if s["active"] else "off")
    print(len(h["today"]), "legs today:", sum(1 for t in h["today"] if t["kind"] == "backed"), "backed,", sum(1 for t in h["today"] if t["kind"] == "caution"), "caution")

"""Frozen pick rules (v1): log, grade and track closing-line value  ->  data/log/picks_log.csv, picks_graded.csv, picks_summary.json  (research: nothing here feeds the model or the site)

    python -m pipeline.picks              # log today's qualifying legs (run by the refresh workflow, soft-fail)
    python -m pipeline.picks --grade      # grade finished days, rebuild picks_graded.csv and picks_summary.json
    python -m pipeline.picks --report     # print the summary
    python -m pipeline.picks --site       # write site/data/picks.json for the Picks tab (open legs, forward record, by day)
    python -m pipeline.picks --backtest   # the in-sample cut the rules were frozen from

Why: the model as a whole hits ~50% against PrizePicks (break-even 54.4%). The cuts below were found by looking at 14,717 graded legs (Oct 20 - Nov 16), so they are post-hoc; the point of this module is to
FREEZE them now and grade them forward, honestly, before anyone leans on them. Rules (RULES_VERSION v1, do not edit in place: add v2):
  R1 under_solo  Under, NO rotation player out for the team (injury report), model P(win) >= 0.65, projected minutes >= 20.         in sample: 323-335 legs, 68% (player-days 67%), halves 65% / 78%
  R2 over_one    Over, EXACTLY ONE rotation player out for the team, model P(win) >= 0.60.                                           in sample: 553-572 legs, 58% (player-days 56%), halves 58% / 58%
  R3 market_gap  tracked only: the side the PrizePicks line is off the sportsbook consensus by 1.0+ (Over when PP is 1.0+ below consensus, Under when 1.0+ above), ignoring the model.  in sample: 725 legs, 56%
A "skip if the market disagrees with the model" filter was tested and changes nothing inside R1 / R2, so it is not a rule (the market gap is still logged). A skew-aware probability was tested and not adopted.

picks_log.csv is append-only per (slate date, player, stat, rule): the first run in which a leg qualifies writes first_* (line, side, P(win), rotation players out); every later run before tip-off
updates last_* and qualifies_last (a leg can stop qualifying when injuries change); after tip-off nothing is touched. The pick that counts is the LAST qualifying state (what the 2-hours-before-tip run
shows); the first state gives the closing-line value: CLV = how far the line moved in our favour between first and last sighting, measured on the side we first saw (Under: first - last, Over: last - first), in line units. It counts EVERY leg that ever qualified, including the ones that stopped qualifying by tip-off (a gap that closes is exactly the case worth seeing) and not only the survivors; legs seen once (first_ts == last_ts) have no second sighting and are left out. Grading counts
legs and also PLAYER-DAYS (legs on one player the same day are one bet): hit rate by player-day, with 90% Wilson ranges. Voids (voids.csv) and pushes are left out.
"""
import os, sys, json, argparse, datetime as dt
import numpy as np, pandas as pd
from . import config as C
from . import results as R
from . import highlights as H

LOG, GRADED, SUMMARY = "data/log/picks_log.csv", "data/log/picks_graded.csv", "data/log/picks_summary.json"
RULES_VERSION = "v1"
RULES = {"R1": "under_solo", "R2": "over_one", "R3": "market_gap"}
R1_PW, R1_MIN, R2_PW, R3_GAP = 0.65, 20.0, 0.60, 1.0
COLS = ["date", "pid", "name", "team", "game", "stat", "rule", "version", "commence",
        "first_ts", "first_side", "first_line", "first_pw", "first_out", "first_cons",
        "last_ts", "last_side", "last_line", "last_pw", "last_out", "last_cons", "last_proj", "last_min", "last_gap", "qualifies_last"]
COMBO = H.COMBO


def et_date(commence):
    return pd.Timestamp(commence).tz_convert("America/New_York").date().isoformat()


def legs_now(out="site/data", raw="data/raw"):
    """every PrizePicks line on tonight's board with the model's side, P(win), rotation players out and the consensus gap."""
    lp, pp_ = f"{out}/lines.json", f"{out}/projections.json"
    if not (os.path.exists(lp) and os.path.exists(pp_)): return [], None
    sp = H._spread(raw); P = {p["pid"]: p for p in json.load(open(pp_))}
    ap = f"{out}/absence.json"; stars = json.load(open(ap)).get("stars", {}) if os.path.exists(ap) else {}
    L = json.load(open(lp)); now = pd.Timestamp.now("UTC"); legs = []
    for r in L.get("rows", []):
        p = P.get(r["pid"]); pl = (r.get("dfs") or {}).get("prizepicks"); k = r["stat"]
        if not p or pl is None or p["min"] <= 0 or k not in H.STATS or r.get("started"): continue
        if pd.Timestamp(r["commence"]) <= now: continue                                    # tipped off: frozen
        m = sum(p["min"] * p["rate_" + c] for c in COMBO.get(k, [k]))
        a, b = sp.get(k, [1.0, 0.3]); sd = max(a + b * m, 0.1)
        po, pu = R.sides(pl, m, sd); side = "O" if po >= pu else "U"
        cons = (r.get("cons") or {}).get("line")
        legs.append(dict(date=et_date(r["commence"]), pid=str(r["pid"]), name=p["name"], team=p["team"], game=r["game"], stat=k, commence=r["commence"], line=float(pl), proj=float(m), minutes=float(p["min"]),
                         side=side, pw=float(max(po, pu)), out=len(stars.get(p["team"], [])), cons=None if cons is None else float(cons), gap=None if cons is None else float(pl) - float(cons)))
    return legs, L.get("updated")


def qualify(rule, leg):
    """(side, qualifies) for one leg under one rule."""
    if rule == "R1": return leg["side"], bool(leg["side"] == "U" and leg["out"] == 0 and leg["pw"] >= R1_PW and leg["minutes"] >= R1_MIN)
    if rule == "R2": return leg["side"], bool(leg["side"] == "O" and leg["out"] == 1 and leg["pw"] >= R2_PW)
    g = leg["gap"]                                                                        # R3
    if g is None or abs(g) < R3_GAP: return leg["side"], False
    return ("O" if g < 0 else "U"), True


def log_picks(out="site/data", raw="data/raw", path=LOG):
    legs, ts = legs_now(out, raw)
    old = pd.read_csv(path, dtype={"pid": str}) if os.path.exists(path) else pd.DataFrame(columns=COLS)
    idx = {(r.date, r.pid, r.stat, r.rule): i for i, r in enumerate(old.itertuples())}
    rows = old.to_dict("records"); new = upd = 0
    for leg in legs:
        for rule in RULES:
            side, q = qualify(rule, leg); key = (leg["date"], leg["pid"], leg["stat"], rule)
            cur = dict(last_ts=ts, last_side=side, last_line=leg["line"], last_pw=round(leg["pw"], 4), last_out=leg["out"], last_cons=leg["cons"], last_proj=round(leg["proj"], 2),
                       last_min=round(leg["minutes"], 1), last_gap=leg["gap"], qualifies_last=q)
            if key in idx:
                rows[idx[key]].update(cur); upd += 1
            elif q:
                rows.append(dict(date=leg["date"], pid=leg["pid"], name=leg["name"], team=leg["team"], game=leg["game"], stat=leg["stat"], rule=rule, version=RULES_VERSION, commence=leg["commence"],
                                 first_ts=ts, first_side=side, first_line=leg["line"], first_pw=round(leg["pw"], 4), first_out=leg["out"], first_cons=leg["cons"], **cur)); new += 1
    df = pd.DataFrame(rows, columns=COLS)
    os.makedirs(os.path.dirname(path), exist_ok=True); df.to_csv(path, index=False)
    q = df[(df.qualifies_last == True)] if len(df) else df
    print(f"picks: {new} new, {upd} updated; {len(q)} legs currently qualify ({q.groupby('rule').size().to_dict() if len(q) else {}}); log {len(df)} rows")
    return df


def wilson(h, n, z=1.645):
    if not n: return [None, None]
    p = h / n; c = (p + z * z / (2 * n)) / (1 + z * z / n); w = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n); return [round(float(c - w), 3), round(float(c + w), 3)]


def clv_of(first_side, first_line, last_line):
    """line movement in our favour on the FIRST-sighting side: Under gains when the line falls, Over when it rises."""
    return (first_line - last_line) if first_side == "U" else (last_line - first_line)


def clv_summary(L):
    """per rule: closing-line value over every logged leg with two sightings (first_ts != last_ts), survivors and dropped legs together and apart; legs seen once are counted separately."""
    out = {}
    for rule in RULES:
        x = L[L.rule == rule]
        two = x[x.first_ts != x.last_ts].copy()
        two["clv"] = [clv_of(a, f, l) for a, f, l in zip(two.first_side, two.first_line, two.last_line)]
        r = {"n": int(len(two)), "single_sighting_excluded": int(len(x) - len(two))}
        if len(two):
            sv, dr = two[two.qualifies_last.astype(bool)], two[~two.qualifies_last.astype(bool)]
            r.update(mean=round(float(two.clv.mean()), 3), better=int((two.clv > 0).sum()), same=int((two.clv == 0).sum()), worse=int((two.clv < 0).sum()),
                     survivors_n=int(len(sv)), survivors_mean=round(float(sv.clv.mean()), 3) if len(sv) else None, dropped_n=int(len(dr)), dropped_mean=round(float(dr.clv.mean()), 3) if len(dr) else None)
        out[rule] = r
    return out


def grade(raw="data/raw", log=LOG, voids="data/log/voids.csv"):
    if not os.path.exists(log): print("no picks log yet"); return None
    L = pd.read_csv(log, dtype={"pid": str}); g = pd.read_csv(f"{raw}/games.csv", dtype={"pid": str}).drop_duplicates(["pid", "date"])
    v = pd.read_csv(voids, dtype={"pid": str}) if os.path.exists(voids) else pd.DataFrame(columns=["date", "pid"]); vk = set(zip(v.date.astype(str), v.pid.astype(str)))
    M = L.merge(g[["pid", "date", "min"] + C.STATS], on=["pid", "date"], how="left")
    comp = lambda r, k: sum(r[c] for c in COMBO.get(k, [k]))
    rows = []
    for r in M.itertuples(index=False):
        d = r._asdict()
        if pd.isna(d["min"]): continue                                                    # not played / not final yet
        act = comp(d, d["stat"]); void = (d["date"], d["pid"]) in vk or d["min"] <= 0
        res_f = R.grade(act, d["last_line"], d["last_side"]); res_1 = R.grade(act, d["first_line"], d["first_side"])
        clv = clv_of(d["first_side"], d["first_line"], d["last_line"]) if d["first_ts"] != d["last_ts"] else None
        rows.append(dict(date=d["date"], pid=d["pid"], name=d["name"], team=d["team"], stat=d["stat"], rule=d["rule"], first_side=d["first_side"], first_line=d["first_line"], last_side=d["last_side"], last_line=d["last_line"],
                         last_pw=d["last_pw"], last_out=d["last_out"], last_min=d["last_min"], qualifies_last=bool(d["qualifies_last"]), actual=act, void=bool(void), hit_final=None if (void or res_f is None) else int(res_f),
                         hit_first=None if (void or res_1 is None) else int(res_1), clv=clv))
    G = pd.DataFrame(rows); G.to_csv(GRADED, index=False)
    S = {"version": RULES_VERSION, "graded_through": str(G.date.max()) if len(G) else None, "break_even": C.PP_BREAKEVEN, "rules": {}}
    mid = sorted(G.date.unique())[len(G.date.unique()) // 2] if len(G) else None
    for rule, name in RULES.items():
        x = G[(G.rule == rule) & G.qualifies_last & G.hit_final.notna()]; f = G[(G.rule == rule) & G.hit_first.notna()]
        if not len(x): S["rules"][rule] = {"name": name, "legs": 0}; continue
        pdv = x.groupby(["date", "pid"]).hit_final.mean()
        S["rules"][rule] = {"name": name, "legs": int(len(x)), "hit": round(float(x.hit_final.mean()), 3), "hit_range90": wilson(int(x.hit_final.sum()), len(x)),
                            "player_days": int(len(pdv)), "hit_player_day": round(float(pdv.mean()), 3), "days": int(x.date.nunique()),
                            "hit_first_sighting": round(float(f.hit_first.mean()), 3) if len(f) else None, "legs_ever_qualified": int(len(f)),
                                                        "first_half": round(float(x[x.date < mid].hit_final.mean()), 3) if (x.date < mid).any() else None, "second_half": round(float(x[x.date >= mid].hit_final.mean()), 3) if (x.date >= mid).any() else None}
    S["clv"] = clv_summary(L)                                                              # all legs ever logged, not only the graded survivors
    with open(SUMMARY, "w") as fh: json.dump(S, fh, indent=1)
    print(f"picks graded through {S['graded_through']}: " + "; ".join(f"{k} {v.get('legs', 0)} legs" + (f" hit {v['hit']:.3f} (player-days {v['hit_player_day']:.3f}, CLV {S['clv'][k].get('mean')} on {S['clv'][k]['n']})" if v.get("legs") else "") for k, v in S["rules"].items()))
    return S


INSAMPLE = {"R1": {"legs": 335, "hit": 0.684, "range": [0.64, 0.724], "player_days": 124, "hit_pd": 0.670, "per_day": 12.4},
            "R2": {"legs": 572, "hit": 0.580, "range": [0.546, 0.614], "player_days": 226, "hit_pd": 0.561, "per_day": 21.2},
            "R3": {"legs": 725, "hit": 0.559, "range": [0.528, 0.589], "player_days": 636, "hit_pd": 0.552, "per_day": 26.9}}
RULE_TEXT = {"R1": "Under, no rotation player out for the team, model P(win) 65%+, projected 20+ minutes",
             "R2": "Over, exactly one rotation player out for the team, model P(win) 60%+",
             "R3": "The side a PrizePicks line 1.0+ off the sportsbook consensus points to (model ignored); tracked only"}


def site_json(out="site/data", raw="data/raw", log=LOG, graded=GRADED, summary=SUMMARY):
    """site/data/picks.json for the Picks tab: every qualifying leg of the last 14 slate days per rule (open ones with their current injury status, graded ones with the result), the forward record from picks_summary.json, and the last days by rule."""
    L = pd.read_csv(log, dtype={"pid": str}) if os.path.exists(log) else pd.DataFrame(columns=COLS)
    G = pd.read_csv(graded, dtype={"pid": str}) if os.path.exists(graded) and os.path.getsize(graded) > 5 else pd.DataFrame()
    S = json.load(open(summary)) if os.path.exists(summary) else {"rules": {}, "graded_through": None}
    st = {}
    ip = f"{raw}/injuries.csv"
    if os.path.exists(ip):
        inj = pd.read_csv(ip); inj["t"] = pd.to_datetime(inj["ts"], utc=True); inj = inj[inj.t >= pd.Timestamp.now("UTC") - pd.Timedelta(hours=48)].sort_values("t").drop_duplicates(["team", "name"], keep="last")
        st = {(r.team, r.name): r.status for r in inj.itertuples()}
    gk = {(r.date, r.pid, r.stat, r.rule): r for r in G.itertuples(index=False)} if len(G) else {}
    keep = sorted(L.date.unique())[-14:] if len(L) else []
    legs = []
    for r in L.itertuples(index=False):
        if not bool(r.qualifies_last) or r.date not in keep: continue
        side_m = "O" if (r.last_proj is not None and r.last_proj == r.last_proj and r.last_proj >= r.last_line) else "U"
        clv = None if (r.first_side != r.last_side or r.first_ts == r.last_ts) else clv_of(r.first_side, r.first_line, r.last_line)     # per-leg CLV only while the side is unchanged; flipped legs are marked instead
        g = gk.get((r.date, r.pid, r.stat, r.rule))
        res = None; actual = None
        if g is not None:
            actual = float(g.actual) if g.actual == g.actual else None
            res = "V" if bool(g.void) else ("P" if g.hit_final != g.hit_final else ("W" if int(g.hit_final) == 1 else "L"))      # win / loss / push / void; None = not graded yet
        legs.append(dict(rule=r.rule, date=r.date, pid=r.pid, name=r.name, team=r.team, game=r.game, stat=r.stat, side=r.last_side, line=float(r.last_line), first_line=float(r.first_line), pw=float(r.last_pw),
                         out=int(r.last_out), min=None if r.last_min != r.last_min else float(r.last_min), cons=None if r.last_cons != r.last_cons else float(r.last_cons), agree=bool(side_m == r.last_side),
                         clv=None if clv is None or clv != clv else float(clv), flipped=bool(r.first_side != r.last_side), first_side=r.first_side, status=st.get((r.team, r.name), ""), commence=r.commence, last_ts=r.last_ts, res=res, actual=actual))
    by_day = []
    if len(G):
        for date, d in G[G.qualifies_last & G.hit_final.notna()].groupby("date"):
            row = {"date": date}
            for rule in RULES:
                x = d[d.rule == rule]
                row[rule] = [int(len(x)), int(x.hit_final.sum()), int(x.groupby("pid").ngroups)] if len(x) else None
            by_day.append(row)
        by_day.sort(key=lambda r: r["date"], reverse=True)
    res = {"version": RULES_VERSION, "break_even": C.PP_BREAKEVEN, "graded_through": S.get("graded_through"), "asof": max([l["last_ts"] for l in legs if l["res"] is None] or [l["last_ts"] for l in legs], default=None), "days": sorted({l["date"] for l in legs}, reverse=True),
           "rules": {k: {"name": RULES[k], "text": RULE_TEXT[k], "insample": INSAMPLE[k], "record": S["rules"].get(k, {}), "clv": (S.get("clv") or clv_summary(L)).get(k, {})} for k in RULES}, "today": legs, "by_day": by_day[:14]}
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "picks.json"), "w") as f: json.dump(res, f, separators=(",", ":"))
    print(f"picks.json: {len(legs)} legs over {len({l['date'] for l in legs})} slate days ({sum(1 for l in legs if l['res'] is None)} open), {len(by_day)} graded days")
    return res


def report():
    if not os.path.exists(SUMMARY): print("no summary yet; run --grade"); return
    S = json.load(open(SUMMARY)); print(f"rules {S['version']}, graded through {S['graded_through']}, break-even {S['break_even']}")
    for k, v in S["rules"].items(): print(" ", k, json.dumps(v))


def backtest(out="site/data", raw="data/raw"):
    """in-sample table the rules were frozen from (post-hoc; see the module docstring)."""
    sp = H._spread(raw); days = sorted(__import__("glob").glob(f"{out}/results/20??-??-??.json")); names = [os.path.basename(f)[:10] for f in days]; ro = H.rotation_out(raw, names)
    Lg = pd.read_csv("data/log/lines_log.csv", dtype={"pid": str}).drop_duplicates(["date", "pid", "stat"], keep="last").set_index(["date", "pid", "stat"])
    rows = []
    for f, day in zip(days, names):
        for p in json.load(open(f)):
            if p.get("v"): continue
            for k, v in p["s"].items():
                if k not in H.STATS or v[3] is None or v[1] == v[3]: continue
                a, b = sp.get(k, [1.0, 0.3]); sd = max(a + b * v[0], 0.1); po, pu = R.sides(v[3], v[0], sd); side = "O" if po >= pu else "U"
                try: cons = Lg.loc[(day, str(p["pid"]), k)]["cons_line"]
                except KeyError: cons = np.nan
                rows.append(dict(day=day, pid=str(p["pid"]), side=side, pw=max(po, pu), out=ro.get(day, {}).get(p["t"], 0), mp=p["mp"], gap=v[3] - cons, over=int(v[1] > v[3])))
    d = pd.DataFrame(rows); d["hit"] = np.where(d.side == "O", d.over, 1 - d.over)
    sel = {"R1": d[(d.side == "U") & (d.out == 0) & (d.pw >= R1_PW) & (d.mp >= R1_MIN)], "R2": d[(d.side == "O") & (d.out == 1) & (d.pw >= R2_PW)]}
    big = d[d.gap.abs() >= R3_GAP]; r3 = big.assign(hit=np.where(big.gap < 0, big.over, 1 - big.over)); sel["R3"] = r3
    print(f"in-sample, {len(d)} graded legs over {len(names)} days (break-even {C.PP_BREAKEVEN})")
    for k, x in sel.items():
        pdv = x.groupby(["day", "pid"]).hit.mean(); print(f"  {k} {RULES[k]}: {len(x)} legs hit {x.hit.mean():.3f} {wilson(int(x.hit.sum()), len(x))} | player-days {len(pdv)} hit {pdv.mean():.3f} | ~{len(x) / len(names):.1f} legs/day")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--grade", action="store_true"); ap.add_argument("--report", action="store_true"); ap.add_argument("--backtest", action="store_true"); ap.add_argument("--site", action="store_true"); a = ap.parse_args()
    if a.backtest: backtest()
    elif a.site: site_json()
    elif a.report: report()
    elif a.grade: grade()
    else: log_picks()

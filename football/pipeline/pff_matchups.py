"""Projected matchups for the boards: how strong is the coverage a receiver is likely to face? A visual aid; the tests found no predictive gain from coverage features (README).

matchups(raw, season, week) -> {opp_team: {"WR"|"TE"|"RB": dict(rank, of, label, score, def=[...])}}
  score: the target-weighted coverage grade of the defenders who were thrown at by receivers of that position group (PFF receiver-versus-defender pairs, weeks before `week`),
         each defender's grade = his coverage-snap-weighted season grade, regressed toward 60 with 100 snaps; the team's score is regressed toward the league with K_T targets;
  rank:  1 = best coverage in the league ... 32 = worst (a soft matchup);  label: GREAT (27-32), GOOD (21-26), EVEN (12-20), TOUGH (7-11), HARD (1-6);
  def:   the defenders most targeted by that group (the likely coverage): name, position, coverage rank among 80+ snap defenders, share of the group's targets.
"""
import csv
from .pff_grades import FIX

K_T = 40.0
K_SN = 100.0
LG = 60.0
MIN_SN = 80


def fl(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def group(p):
    return "RB" if p in ("HB", "FB", "RB") else p


def label(rank):
    return "GREAT" if rank >= 27 else "GOOD" if rank >= 21 else "EVEN" if rank >= 12 else "TOUGH" if rank >= 7 else "HARD"


def matchups(raw, season, week):
    d = f"{raw}/pff_hist"
    try:
        cov = list(csv.DictReader(open(f"{d}/defcoverage_{season}.csv", newline="")))
        vs = list(csv.DictReader(open(f"{d}/covvs_{season}.csv", newline="")))
        rec = list(csv.DictReader(open(f"{d}/pff_receiving_{season}.csv", newline="")))
    except FileNotFoundError:
        return {}
    pos_of = {r["player_id"]: group(r["position"]) for r in rec}
    info, gs, sn, team_wk = {}, {}, {}, {}
    for r in cov:
        wk = int(r["week"])
        if wk >= week:
            continue
        s = fl(r["snap_counts_coverage"])
        pid = r["player_id"]
        info[pid] = (r["player"], r["position"], FIX.get(r["team"], r["team"]))
        team_wk[(pid, wk)] = FIX.get(r["team"], r["team"])
        gs[pid] = gs.get(pid, 0.0) + fl(r["grades_coverage_defense"]) * s
        sn[pid] = sn.get(pid, 0.0) + s
    grade = {p: (gs[p] + K_SN * LG) / (sn[p] + K_SN) for p in sn}
    ranked = sorted((p for p in sn if sn[p] >= MIN_SN), key=lambda p: -grade[p])
    drank = {p: i + 1 for i, p in enumerate(ranked)}
    tg = {}                                                  # (team, group) -> {defender: targets}
    for r in vs:
        wk = int(r["week"])
        t = team_wk.get((r["coverage_player_id"], wk))
        g = pos_of.get(r["player_id"])
        if wk >= week or not t or not g:
            continue
        x = tg.setdefault((t, g), {})
        x[r["coverage_player_id"]] = x.get(r["coverage_player_id"], 0.0) + fl(r["targets"])
    score = {}
    for k, x in tg.items():
        den = sum(x.values())
        score[k] = (sum(n * grade.get(p, LG) for p, n in x.items()) + K_T * LG) / (den + K_T)
    out = {}
    for g in ("WR", "TE", "RB"):
        teams = sorted((k[0] for k in score if k[1] == g), key=lambda t: -score[(t, g)])     # best coverage first
        n = len(teams)
        for i, t in enumerate(teams):
            x = tg[(t, g)]
            den = sum(x.values()) or 1.0
            top = sorted(x.items(), key=lambda kv: -kv[1])[:3]
            out.setdefault(t, {})[g] = dict(rank=i + 1, of=n, label=label(round((i + 1) * 32 / n)), score=round(score[(t, g)], 1),
                                            defs=[dict(name=info[p][0], pos=info[p][1], rk=drank.get(p), n=len(ranked), share=round(v / den * 100)) for p, v in top if p in info])
    return out


def refresh_current(season, raw="data/raw"):
    """Re-pull the last two weeks on file plus the next for the defender coverage report and the receiver-versus-defender pairs and merge them into the season files (6 API calls).
    Skips quietly without PFF_API_KEY."""
    import os
    from . import pff_hist
    key = os.environ.get("PFF_API_KEY", "").strip()
    if not key:
        print("PFF_API_KEY not set; PFF matchups not refreshed")
        return
    d = f"{raw}/pff_hist"
    for name, path, key_of, pick in (("defcoverage", "/v1/facet/defense/coverage", None, None), ("covvs", "/v1/facet/receiving/coverage", "receiving_coverage_stats", "versus")):
        fp = f"{d}/{name}_{season}.csv"
        try:
            old = list(csv.DictReader(open(fp, newline="")))
        except FileNotFoundError:
            continue
        cols = list(old[0].keys()) if old else []
        last = max([int(r["week"]) for r in old] or [0])
        new = []
        for wk in range(max(1, last - 1), min(last + 2, 23)):
            r = pff_hist.get(path, dict(league="nfl", season=season, week=wk), key)
            if r.status_code != 200:
                print(f"PFF {name} week {wk}: HTTP {r.status_code}")
                continue
            body = r.json()
            data = body.get(key_of, {}).get(pick, []) if key_of else next((v for v in body.values() if isinstance(v, list) and v and isinstance(v[0], dict)), [])
            new += [dict(x, season=season, week=wk) for x in data]
        if not new:
            continue
        got = {int(x["week"]) for x in new}
        rows = [r for r in old if int(r["week"]) not in got] + new
        with open(fp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"PFF {name} refreshed: weeks {sorted(got)}, {len(new)} rows")

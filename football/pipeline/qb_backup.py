"""Test: when a backup quarterback starts, do the top one or two receivers see a bigger share of the targets than the model projects?

NFL 2023-26, week 5 on. For every team-week the "backup game" flag is: the quarterback with the most attempts that week is not the team's season-to-date leader in attempts (the usual starter),
and the leader himself threw under half his usual attempts. The receivers are ranked by season-to-date target share before the game (WR / TE / RB). Compared in backup and normal games: the actual
share of the team's targets going to the top-1 and top-2 receivers, the share the model projected, and actual / projected targets for the top-2 and for the rest. Uses the known passer of the week (a backup
start is usually known before kickoff)."""
import json, os, statistics as S
from collections import defaultdict
from . import config as C

CACHE = os.environ.get("QB_CACHE", "/tmp/qb_backup_rows.json")


def build():
    from .model import load_weekly, nfl_core, derive, params
    from .slate import load_csv, matchups
    P, out = params(), []
    src = [(s, f"data/raw/history/weekly_{s}.csv", f"data/raw/history/schedule_{s}.csv") for s in (2023, 2024, 2025)] + [(2026, "data/raw/weekly.csv", "data/raw/schedule.csv")]
    for season, wp, sp in src:
        rows, sched, by = load_weekly(wp), load_csv(sp), defaultdict(list)
        for r in rows:
            by[int(r["week"])].append(r)
        for wk in range(5, max(by) + 1):
            mu = matchups(sched, wk)
            if not mu or wk not in by:
                continue
            prior = [r for x in range(1, wk) for r in by.get(x, [])]
            core = nfl_core(prior, mu, None, P)
            proj = {pl["id"]: derive(pl, C.DEFAULT_SCORING, P) for pl in core["players"]}
            now = {r["player_id"]: r for r in by[wk]}
            teams = defaultdict(dict)
            for pl in core["players"]:
                teams[pl["team"]][pl["id"]] = pl
            for t, pls in teams.items():
                # quarterbacks: usual starter = season-to-date attempts leader
                att_prior = defaultdict(float); tg_prior = defaultdict(float); name = {}
                for r in prior:
                    if r["team"] == t:
                        att_prior[r["player_id"]] += r["attempts"]; tg_prior[r["player_id"]] += r["targets"]; name[r["player_id"]] = r["player_display_name"]
                att_now = {r["player_id"]: r["attempts"] for r in by[wk] if r["team"] == t and r["attempts"] > 0}
                if not att_now or not att_prior:
                    continue
                usual = max(att_prior, key=att_prior.get)
                if att_prior[usual] < 60:
                    continue
                passer = max(att_now, key=att_now.get)
                usual_games = max(1, sum(1 for x in range(1, wk) if any(r["team"] == t and r["player_id"] == usual and r["attempts"] > 0 for r in by.get(x, []))))
                usual_avg = att_prior[usual] / usual_games
                backup = passer != usual and att_now.get(usual, 0) < 0.5 * usual_avg
                # receivers ranked by season-to-date targets
                recs = [(i, tg_prior.get(i, 0.0)) for i in pls if pls[i]["pos"] in ("WR", "TE", "RB") and i in now]
                recs.sort(key=lambda z: -z[1])
                tot_actual = sum(now[i]["targets"] for i, _ in recs)
                tot_proj = sum(proj[i]["tgt"] for i, _ in recs)
                if tot_actual < 15 or tot_proj <= 0:
                    continue
                top = [i for i, _ in recs[:2]]
                out.append(dict(season=season, week=wk, team=t, backup=int(backup), passer=name.get(passer, passer), usual=name.get(usual),
                                a1=now[top[0]]["targets"], a2=sum(now[i]["targets"] for i in top), p1=proj[top[0]]["tgt"], p2=sum(proj[i]["tgt"] for i in top),
                                at=tot_actual, pt=tot_proj, prior_share2=sum(tg_prior.get(i, 0) for i in top) / max(1.0, sum(tg_prior.values()))))
    return out


def main():
    try:
        rows = json.load(open(CACHE))
    except OSError:
        rows = build(); json.dump(rows, open(CACHE, "w"))
    for lab, flt in (("backup quarterback games", lambda r: r["backup"]), ("normal games", lambda r: not r["backup"])):
        v = [r for r in rows if flt(r)]
        if not v:
            continue
        print(f"\n{lab}: n={len(v)} team-games")
        print(f"  top-2 receivers' share of the team's targets: before the game (season to date) {100 * S.mean(r['prior_share2'] for r in v):.1f}%  projected {100 * S.mean(r['p2'] / r['pt'] for r in v):.1f}%  actual {100 * S.mean(r['a2'] / r['at'] for r in v):.1f}%")
        print(f"  top-1 receiver's projected share {100 * S.mean(r['p1'] / r['pt'] for r in v):.1f}%, actual {100 * S.mean(r['a1'] / r['at'] for r in v):.1f}%")
        print(f"  team targets: projected {S.mean(r['pt'] for r in v):.1f}, actual {S.mean(r['at'] for r in v):.1f}; top-2 targets: projected {S.mean(r['p2'] for r in v):.1f}, actual {S.mean(r['a2'] for r in v):.1f}; rest: projected {S.mean(r['pt'] - r['p2'] for r in v):.1f}, actual {S.mean(r['at'] - r['a2'] for r in v):.1f}")
    b = [r for r in rows if r["backup"]]
    print("\nbackup games:", [(r["season"], r["week"], r["team"], r["passer"], f"top2 {100 * r['a2'] / r['at']:.0f}% vs usual {100 * r['prior_share2']:.0f}%") for r in b][:40])
    # difference-in-differences: actual share minus the pre-game share, backup minus normal
    d_b = S.mean(r["a2"] / r["at"] - r["prior_share2"] for r in b) if b else float("nan")
    d_n = S.mean(r["a2"] / r["at"] - r["prior_share2"] for r in rows if not r["backup"])
    se = (S.pstdev([r["a2"] / r["at"] - r["prior_share2"] for r in b]) / len(b) ** 0.5) if len(b) > 1 else float("nan")
    print(f"\nactual top-2 share minus season-to-date top-2 share: backup {100 * d_b:+.1f} pts (se {100 * se:.1f}), normal {100 * d_n:+.1f} pts")


if __name__ == "__main__":
    main()

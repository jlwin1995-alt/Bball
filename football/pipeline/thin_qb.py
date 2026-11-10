"""Test: a thin-history quarterback who starts is projected on his own tiny history (6.2 attempts, 0.8 carries) while he throws about 28 and runs about 3. config THIN_QB_ON gives the depth chart's QB1 with fewer
than THIN_QB_ATT career attempts the team's usual attempts and THIN_QB_CAR carries (the manual Starter override already did the attempts part).
Walk-forward NFL 2023-26 (week 5 on): the depth-chart proxy is "a QB who threw 10+ passes that week and had fewer than THIN_QB_ATT attempts before it" (a starter is known before kickoff). Compares ON and OFF
on those quarterbacks (attempts, carries, passing and rushing yards, points) and on the receivers and backs of the same teams."""
import statistics as S
from collections import defaultdict
from . import config as C


def run(on, frac=0.97, ypa=1.0):
    from .model import load_weekly, nfl_core, derive, params
    from .slate import load_csv, matchups
    from .backtest import actual
    P = params(); P["THIN_QB_ON"] = on; P["THIN_QB_ATT_FRAC"] = frac; P["THIN_QB_YPA"] = ypa
    qbs, mates = [], []
    for season, wp, sp in [(2023, "data/raw/history/weekly_2023.csv", "data/raw/history/schedule_2023.csv"), (2024, "data/raw/history/weekly_2024.csv", "data/raw/history/schedule_2024.csv"),
                           (2025, "data/raw/history/weekly_2025.csv", "data/raw/history/schedule_2025.csv"), (2026, "data/raw/weekly.csv", "data/raw/schedule.csv")]:
        wr, sched, by = load_weekly(wp), load_csv(sp), defaultdict(list)
        for r in wr:
            by[int(r["week"])].append(r)
        for wk in range(5, max(by) + 1):
            mu = matchups(sched, wk)
            if not mu or wk not in by:
                continue
            prior = [r for x in range(1, wk) for r in by.get(x, [])]
            att_prior = defaultdict(float)
            for r in prior:
                att_prior[r["player_id"]] += r["attempts"]
            now = {r["player_id"]: r for r in by[wk]}
            thin = {i for i, r in now.items() if r["position"] == "QB" and r["attempts"] >= 10 and att_prior.get(i, 0) < P["THIN_QB_ATT"]}
            core = nfl_core(prior, mu, None, dict(P, QB1_IDS=thin))
            thin_teams = {now[i]["team"] for i in thin}
            for pl in core["players"]:
                a = now.get(pl["id"])
                if a is None:
                    continue
                d, z = derive(pl, C.DEFAULT_SCORING, P), actual(a, C.DEFAULT_SCORING)
                if pl["id"] in thin:
                    qbs.append((d["att"], a["attempts"], d["car"], a["carries"], d["passY"], z["passY"], d["rushY"], z["rushY"], d["pts"], z["pts"]))
                elif pl["team"] in thin_teams and pl["pos"] in ("WR", "TE", "RB"):
                    mates.append((d["tgt"], a["targets"], d["pts"], z["pts"], pl["pos"]))
    return qbs, mates


def line(lab, r):
    q, m = r
    return (f"  {lab:34} attempts {S.mean(x[0] for x in q):5.1f} (act {S.mean(x[1] for x in q):4.1f}) | carries {S.mean(x[2] for x in q):4.2f} (act {S.mean(x[3] for x in q):4.2f}) | pass yds MAE {S.mean(abs(x[4]-x[5]) for x in q):5.1f}, proj {S.mean(x[4] for x in q):5.1f} (act {S.mean(x[5] for x in q):5.1f})"
            f" | points MAE {S.mean(abs(x[8]-x[9]) for x in q):5.2f}, proj {S.mean(x[8] for x in q):5.1f} (act {S.mean(x[9] for x in q):4.1f}) || teammates pts MAE {S.mean(abs(x[2]-x[3]) for x in m):.3f} (n {len(m)})")


def main():
    print("thin-history QBs who started, walk-forward NFL 2023-26:")
    print(line("OFF", run(False)))
    for frac, ypa in ((0.97, 1.0), (0.90, 1.0), (0.90, 0.90), (0.85, 0.90)):
        print(line(f"ON  attempts x{frac}, ypa x{ypa}", run(True, frac, ypa)))


if __name__ == "__main__":
    main()

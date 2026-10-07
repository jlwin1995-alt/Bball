"""Synthetic league for developing and testing the site without network access.

Everything here is invented: fictional players, simulated box scores. The latent team-defence
multipliers give the matchup adjustment real signal to find, so the backtest can tell whether the
model works. Output goes to data/raw/ in the same shape fetch_espn.py writes.
"""
import numpy as np
import pandas as pd
from datetime import date, timedelta

TEAMS = ("ATL BOS BKN CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK "
         "OKC ORL PHI PHX POR SAC SAS TOR UTA WAS").split()
FIRST = "Jalen Marcus Devin Tariq Kofi Elias Nico Darius Malik Teo Rashad Cole Andre Brandon Isaiah Leon Omar Silas Ty Zane".split()
LAST = "Ashford Brook Calloway Dray Ellison Fairley Grayson Holloway Ibarra Jessup Keller Lund Mercer Nash Okafor Pruitt Quill Rowe Stroud Vance".split()
ROLE_MIN = [34, 32, 30, 27, 25, 22, 19, 16, 12, 9, 6, 4]
KEYS = ["min", "pts", "reb", "ast", "fg3m", "stl", "blk", "tov", "fgm", "fga", "ftm", "fta"]


def make_league(rng):
    names = set()
    rows = []
    defense = {}
    for t in TEAMS:
        defense[t] = {s: float(np.clip(rng.normal(1.0, 0.06), 0.85, 1.15)) for s in ["pts", "reb", "ast", "fg3m", "stl", "blk", "tov"]}
        for i in range(12):
            while True:
                nm = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
                if nm not in names:
                    names.add(nm)
                    break
            pos = rng.choice(["G", "G", "F", "F", "C"])
            skill = float(np.clip(rng.normal(1.0, 0.25) - i * 0.03, 0.5, 1.8))
            rows.append(dict(pid=f"S{len(rows):04d}", name=nm, team=t, pos=pos, role=i, skill=skill,
                             fga_pm=0.40 * skill * (1.0 if pos != "C" else 0.85), fg_pct=0.42 + 0.05 * skill,
                             tpa_share={"G": 0.5, "F": 0.35, "C": 0.08}[pos], tp_pct=0.30 + 0.04 * skill,
                             fta_pm=0.10 * skill * (1.3 if pos == "C" else 1.0), ft_pct=0.68 + 0.08 * skill,
                             reb_pm={"G": 0.10, "F": 0.16, "C": 0.26}[pos] * skill ** 0.5,
                             ast_pm={"G": 0.20, "F": 0.10, "C": 0.08}[pos] * skill,
                             stl_pm=0.030 * skill ** 0.5, blk_pm={"G": 0.008, "F": 0.02, "C": 0.05}[pos],
                             tov_pm=0.06 * skill ** 0.5))
    return pd.DataFrame(rows), defense


def sim_game(p, opp_def, rng, minutes):
    m = minutes
    fga = rng.poisson(p.fga_pm * m * opp_def["pts"])
    tpa = rng.binomial(fga, p.tpa_share)
    tpm = rng.binomial(tpa, min(p.tp_pct, 0.5))
    fgm = tpm + rng.binomial(fga - tpa, min(p.fg_pct + 0.06, 0.7))
    fta = rng.poisson(p.fta_pm * m * opp_def["pts"])
    ftm = rng.binomial(fta, min(p.ft_pct, 0.95))
    return dict(min=round(m, 1), pts=int(2 * fgm + tpm + ftm), reb=int(rng.poisson(p.reb_pm * m * opp_def["reb"])),
                ast=int(rng.poisson(p.ast_pm * m * opp_def["ast"])), fg3m=int(tpm),
                stl=int(rng.poisson(p.stl_pm * m * opp_def["stl"])), blk=int(rng.poisson(p.blk_pm * m * opp_def["blk"])),
                tov=int(rng.poisson(p.tov_pm * m * opp_def["tov"])), fgm=int(fgm), fga=int(fga), ftm=int(ftm), fta=int(fta))


def schedule(start, end, rng, per_day=7):
    out, d = [], start
    while d <= end:
        if d.weekday() != 5 or rng.random() < 0.5:
            ts = list(rng.permutation(TEAMS))[: per_day * 2]
            for i in range(0, len(ts), 2):
                out.append((d.isoformat(), ts[i], ts[i + 1]))   # (date, home, away)
        d += timedelta(days=1)
    return out


def build(out_dir="data/sample", seed=7, asof="2026-10-07"):
    rng = np.random.default_rng(seed)
    league, defense = make_league(rng)
    by_team = {t: league[league.team == t].sort_values("role") for t in TEAMS}
    prior = schedule(date(2025, 10, 21), date(2026, 4, 12), rng)
    cur_start = date(2026, 10, 21)
    games = []
    for season, sched in ((2026, prior),):
        for d, home, away in sched:
            for team, opp, is_home in ((home, away, 1), (away, home, 0)):
                for _, p in by_team[team].iterrows():
                    if rng.random() < 0.04:        # DNP / rest
                        continue
                    m = float(np.clip(rng.normal(ROLE_MIN[p.role], 3.5), 0, 42))
                    if m < 3:
                        continue
                    g = sim_game(p, defense[opp], rng, m)
                    g.update(pid=p.pid, name=p["name"], team=team, pos=p.pos, date=d, opp=opp, home=is_home, season=season)
                    games.append(g)
    games = pd.DataFrame(games)
    sched_rows = []
    for d, home, away in schedule(cur_start, cur_start + timedelta(days=6), rng):
        sched_rows += [dict(date=d, team=home, opp=away, home=1), dict(date=d, team=away, opp=home, home=0)]
    sched_df = pd.DataFrame(sched_rows)
    inj = league.sample(8, random_state=3)[["pid", "name", "team"]].copy()
    inj["status"] = ["Out", "Out", "Questionable", "Questionable", "Doubtful", "Day-To-Day", "Out", "Questionable"]
    import os
    os.makedirs(out_dir, exist_ok=True)
    games.to_csv(f"{out_dir}/games.csv", index=False)
    sched_df.to_csv(f"{out_dir}/schedule.csv", index=False)
    inj.to_csv(f"{out_dir}/injuries.csv", index=False)
    pd.DataFrame({"sample": [True], "asof": [asof]}).to_csv(f"{out_dir}/meta.csv", index=False)
    return games, sched_df, inj, defense


if __name__ == "__main__":
    g, s, i, _ = build()
    print(len(g), "player-games,", g.date.nunique(), "game days,", len(s) // 2, "scheduled games")

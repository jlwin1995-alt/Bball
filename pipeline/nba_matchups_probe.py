"""One-off check: can a GitHub runner reach NBA.com's player matchup data?   ->  data/log/nba_matchups_probe/

    python -m pipeline.nba_matchups_probe

Calls stats.nba.com leagueseasonmatchups (defender vs offensive player, per season) for Evan Mobley vs Myles Turner in both directions, plus a plain
scoreboard call, and saves status, timing and the raw JSON. Research only; nothing here feeds the model.
"""
import json, os, time, urllib.parse, urllib.request

OUT = "data/log/nba_matchups_probe"
H = {"Referer": "https://www.nba.com/", "Origin": "https://www.nba.com", "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*", "x-nba-stats-origin": "stats", "x-nba-stats-token": "true"}
MOB, TUR = 1630596, 1626167
SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26", "2026-27"]


def get(url, timeout=30):
    t = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=timeout) as r:
            return r.status, time.time() - t, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", "ERR"), time.time() - t, str(e)[:300]


def main():
    os.makedirs(OUT, exist_ok=True); lines = []
    jobs = [("scoreboard", "https://stats.nba.com/stats/scoreboardv2?DayOffset=0&LeagueID=00&gameDate=2026-10-30")]
    for s in SEASONS:
        for lab, off, de in (("mob_vs_tur", MOB, TUR), ("tur_vs_mob", TUR, MOB)):
            q = urllib.parse.urlencode({"DefPlayerID": de, "OffPlayerID": off, "Season": s, "SeasonType": "Regular Season", "LeagueID": "00", "PerMode": "Totals"})
            jobs.append((f"{lab}_{s}", "https://stats.nba.com/stats/leagueseasonmatchups?" + q))
    for name, url in jobs:
        st, dt, body = get(url)
        lines.append(f"{name:22s} status={st} {dt:5.1f}s bytes={len(body)}")
        open(f"{OUT}/{name}.json", "w").write(body[:200000])
        if st == "ERR": break                        # blocked or timing out: no point hammering the rest
        time.sleep(1)
    open(f"{OUT}/summary.txt", "w").write("\n".join(lines) + "\n"); print("\n".join(lines))


if __name__ == "__main__":
    main()

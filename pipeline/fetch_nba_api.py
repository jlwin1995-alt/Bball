"""Fetch NBA data via the `nba_api` package (official stats.nba.com) into data/raw/.

    pip install nba_api
    python -m pipeline.fetch_nba_api [--backfill]

Same output files as fetch_espn.py, so build.py / backtest.py don't care which one you used.
One PlayerGameLogs call returns every player-game for a season, so a refresh is 2-3 requests.

- Positions come from PlayerIndex (PlayerGameLogs has none); missing -> "F".
- Schedule: ScoreboardV2 for the next 7 days.
- Injuries: nba_api has no injury feed, so ESPN's is used and matched to NBA ids BY NAME.
- Do not mix sources: NBA ids and ESPN ids differ. Switching source means starting games.csv fresh.

NOTE: stats.nba.com often blocks cloud / datacenter IPs (GitHub Actions included). Run this from your
own machine or a self-hosted runner and commit data/raw. Written from nba_api's documented columns and
NOT run against the live API from the dev sandbox; `convert()` is unit-tested on a synthetic frame.
"""
import argparse, os, re, time, unicodedata
from datetime import datetime, timedelta, timezone
import pandas as pd
from . import config as C

RAW = "data/raw"
HEADERS_NOTE = "If this times out from CI, run it locally: stats.nba.com blocks many cloud IP ranges."


def season_label(end_year):                         # 2027 -> "2026-27"
    return f"{end_year - 1}-{str(end_year)[2:]}"


def norm(n):
    n = unicodedata.normalize("NFKD", str(n)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", n)).strip()


def convert(logs, positions, season):
    """nba_api PlayerGameLogs frame -> the pipeline's games.csv schema."""
    need = ["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "GAME_DATE", "MATCHUP", "MIN", "PTS", "REB", "AST",
            "FG3M", "STL", "BLK", "TOV", "FGM", "FGA", "FTM", "FTA"]
    missing = [c for c in need if c not in logs.columns]
    if missing:
        raise KeyError(f"nba_api columns changed, missing {missing}; got {list(logs.columns)}")
    g = pd.DataFrame({
        "pid": logs["PLAYER_ID"].astype(str), "name": logs["PLAYER_NAME"], "team": logs["TEAM_ABBREVIATION"],
        "pos": logs["PLAYER_ID"].astype(str).map(positions).fillna("F"),
        "date": pd.to_datetime(logs["GAME_DATE"]).dt.strftime("%Y-%m-%d"),
        "opp": logs["MATCHUP"].str.split(r"\s+(?:vs\.|@)\s+").str[1],
        "home": logs["MATCHUP"].str.contains("vs.", regex=False).astype(int),
        "season": season, "min": pd.to_numeric(logs["MIN"], errors="coerce"),
        **{k.lower(): logs[k] for k in ["PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV", "FGM", "FGA", "FTM", "FTA"]}})
    return g[g["min"] > 0].dropna(subset=["opp"])


def main(backfill=False):
    from nba_api.stats.endpoints import playergamelogs, playerindex, scoreboardv2
    from nba_api.stats.static import teams as nba_teams
    os.makedirs(RAW, exist_ok=True)
    path = f"{RAW}/games.csv"
    if os.path.exists(path) and "event" in pd.read_csv(path, nrows=1).columns:
        raise SystemExit("data/raw/games.csv came from the ESPN fetcher (different player ids). Delete it to switch sources.")

    def call(fn, **kw):
        for i in range(3):
            try:
                return fn(timeout=60, **kw)
            except Exception as e:                    # nba_api raises requests errors / JSON errors
                last = e
                time.sleep(3 * (i + 1))
        raise RuntimeError(f"{fn.__name__} failed: {last}. {HEADERS_NOTE}")

    seasons = [C.SEASON] + ([C.SEASON - 1] if backfill or not os.path.exists(path) else [])
    pos = {}
    frames = []
    for s in seasons:
        lab = season_label(s)
        idx = call(playerindex.PlayerIndex, season=lab).get_data_frames()[0]
        pos.update({str(r.PERSON_ID): r.POSITION[:2].replace("-", "") if isinstance(r.POSITION, str) else "F" for r in idx.itertuples()})
        logs = call(playergamelogs.PlayerGameLogs, season_nullable=lab, season_type_nullable="Regular Season").get_data_frames()[0]
        frames.append(convert(logs, pos, s))
        print(f"{lab}: {len(frames[-1])} player-games")
    new = pd.concat(frames, ignore_index=True)
    if len(seasons) == 1:                                  # routine refresh: keep last season on disk, replace the current one
        old = pd.read_csv(path, dtype={"pid": str})
        new = pd.concat([old[old["season"] != C.SEASON], new], ignore_index=True)
    new.to_csv(path, index=False)

    tid = {t["id"]: t["abbreviation"] for t in nba_teams.get_teams()}
    sched, today = [], datetime.now(timezone.utc).date()
    for d in range(8):
        day = today + timedelta(days=d)
        hdr = call(scoreboardv2.ScoreboardV2, game_date=day.strftime("%m/%d/%Y")).get_data_frames()[0]
        for r in hdr.itertuples():
            if int(r.GAME_STATUS_ID) == 3:                 # already final
                continue
            h, a = tid[r.HOME_TEAM_ID], tid[r.VISITOR_TEAM_ID]
            sched += [dict(date=day.isoformat(), team=h, opp=a, home=1), dict(date=day.isoformat(), team=a, opp=h, home=0)]
        time.sleep(0.7)
    pd.DataFrame(sched, columns=["date", "team", "opp", "home"]).to_csv(f"{RAW}/schedule.csv", index=False)
    print(f"schedule.csv: {len(sched) // 2} games")

    try:                                                   # injuries: ESPN feed, matched to NBA ids by name
        from . import fetch_espn
        by_name = {norm(n): p for p, n in zip(new["pid"], new["name"])}
        rows = []
        for team in fetch_espn.get(f"{fetch_espn.BASE}/injuries").get("injuries", []):
            for i in team.get("injuries", []):
                ath = i.get("athlete", {})
                pid = by_name.get(norm(ath.get("displayName", "")))
                if pid:
                    rows.append(dict(pid=pid, name=ath["displayName"], team="", status=i.get("status")))
        pd.DataFrame(rows, columns=["pid", "name", "team", "status"]).to_csv(f"{RAW}/injuries.csv", index=False)
        print(f"injuries.csv: {len(rows)} matched")
    except Exception as e:
        print("injuries skipped:", e)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    main(ap.parse_args().backfill)

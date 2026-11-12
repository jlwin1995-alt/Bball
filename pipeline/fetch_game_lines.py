"""ESPN game spread and total (DraftKings, from the free game page) -> data/raw/game_lines.csv

    python -m pipeline.fetch_game_lines [--max 3000] [--workers 6]

One row per game: event, date, home, away, spread_home (the HOME team's line: negative = home favoured), total, provider, fetched_at.
  * Finished games already in games.csv are fetched once (rows with no line are stored too, so they are not asked again).
  * Upcoming games (today and tomorrow in schedule.csv) are matched to ESPN events through the scoreboard and refreshed on every run, because the line moves until tip.
Used by pipeline.game_context_test (does the spread move starters' minutes, does the total move scoring?). Soft-fail in the workflow: it can never block the refresh.
"""
import os, sys, csv, argparse, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import requests, pandas as pd, numpy as np

API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
COLS = ["event", "date", "home", "away", "spread_home", "total", "provider", "fetched_at"]


def get(url, tries=3):
    for _ in range(tries):
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200: return r.json()
        except requests.RequestException:
            pass
    return None


def line_for(event):
    d = get(f"{API}/summary?event={event}")
    pc = ((d or {}).get("pickcenter") or [{}])[0]
    if not pc: return (np.nan, np.nan, "")
    sp = pc.get("spread"); tot = pc.get("overUnder")
    return (float(sp) if sp is not None else np.nan, float(tot) if tot is not None else np.nan, (pc.get("provider") or {}).get("name", ""))


def past_games(raw):
    g = pd.read_csv(f"{raw}/games.csv", dtype={"event": str}, usecols=["event", "date", "team", "opp", "home"]).drop_duplicates(["event", "team"])
    h = g[g.home == 1].rename(columns={"team": "home_t", "opp": "away_t"})[["event", "date", "home_t", "away_t"]]
    return h.drop_duplicates("event")


def upcoming_games(raw):
    s = pd.read_csv(f"{raw}/schedule.csv"); out = []
    for day in sorted(s["date"].unique())[:2]:
        sb = get(f"{API}/scoreboard?dates={str(day).replace('-', '')}")
        for e in (sb or {}).get("events", []):
            comp = e["competitions"][0]; side = {c["homeAway"]: c["team"]["abbreviation"] for c in comp["competitors"]}
            out.append(dict(event=str(e["id"]), date=day, home_t=side.get("home"), away_t=side.get("away")))
    return pd.DataFrame(out, columns=["event", "date", "home_t", "away_t"])


def main(raw="data/raw"):
    ap = argparse.ArgumentParser(); ap.add_argument("--max", type=int, default=3000); ap.add_argument("--workers", type=int, default=6); a = ap.parse_args()
    path = f"{raw}/game_lines.csv"; now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    old = pd.read_csv(path, dtype={"event": str}) if os.path.exists(path) else pd.DataFrame(columns=COLS)
    have = set(old.event)
    up = upcoming_games(raw)
    past = past_games(raw)
    today = str(pd.Timestamp.now(tz="America/New_York").date())
    todo = pd.concat([past[(~past.event.isin(have)) & (past.date < today)], up]).drop_duplicates("event").head(a.max)
    print(f"{len(todo)} games to fetch ({len(up)} upcoming, refreshed every run; {int((~past.event.isin(have)).sum())} finished games without a row)")
    if todo.empty: return
    with ThreadPoolExecutor(a.workers) as ex: res = list(ex.map(line_for, todo.event))
    new = pd.DataFrame([dict(event=r.event, date=r.date, home=r.home_t, away=r.away_t, spread_home=s, total=t, provider=p, fetched_at=now)
                        for r, (s, t, p) in zip(todo.itertuples(), res)], columns=COLS)
    out = pd.concat([old[~old.event.isin(set(new.event))], new], ignore_index=True).sort_values(["date", "event"])
    out.to_csv(path, index=False)
    print(f"wrote {len(out)} rows; with a line: {int(out.spread_home.notna().sum())}; new this run with a line: {int(new.spread_home.notna().sum())} of {len(new)}")


if __name__ == "__main__":
    main()

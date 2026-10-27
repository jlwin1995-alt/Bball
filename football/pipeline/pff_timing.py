"""Log when PFF finishes processing each game, so the delay after a game can be measured.

    python -m pipeline.pff_timing

For NFL and college it reads the current and previous week's games (/v1/games) and appends a row to data/log/pff_timing.csv the first time a game is seen and
whenever its lock_status / has_stats changes: observed_at, league, game_id, away, home, start, lock_status, has_stats. The delay for a game is the first row where it
reads processed with has_stats minus its kickoff (plus the game's length, about 3.3 hours in the NFL). Exits quietly after STOP_AFTER.
"""
import csv, os, sys
from datetime import datetime, timezone
import requests

BASE = "https://api.pff.com"
LOG = "data/log/pff_timing.csv"
COLS = ["observed_at", "league", "game_id", "away", "home", "start", "lock_status", "has_stats"]
STOP_AFTER = "2026-11-04"


def get(path, params, key):
    r = requests.get(BASE + path, params=params, headers={"Authorization": f"Bearer {key}", "Accept": "application/json", "User-Agent": "gridiron-model"}, timeout=60)
    r.raise_for_status()
    return r.json()


def last_state(path=LOG):
    st = {}
    if os.path.exists(path):
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                st[(r["league"], r["game_id"])] = (r["lock_status"], r["has_stats"])
    return st


def main():
    now = datetime.now(timezone.utc)
    if now.date().isoformat() >= STOP_AFTER:
        print("past STOP_AFTER; nothing to do")
        return
    key = os.environ.get("PFF_API_KEY", "").strip()
    if not key:
        sys.exit("PFF_API_KEY is not set")
    st, new = last_state(), []
    leagues = get("/v1/leagues", {}, key)["leagues"]
    for lg in leagues:
        slug = lg["slug"]
        if slug not in ("nfl", "ncaa"):
            continue
        wk, season = lg["default_week"], lg["default_season"]
        for w in (wk, wk - 1, wk + 1):
            if w < (0 if slug == "ncaa" else 1):
                continue
            try:
                games = get("/v1/games", dict(league=slug, season=season, week=w), key).get("games", [])
            except requests.RequestException as e:
                print(f"{slug} week {w}: {e}")
                continue
            for g in games:
                start = datetime.fromisoformat(g["start"].replace("Z", "+00:00"))
                if not (-36 * 3600 <= (now - start).total_seconds() <= 3 * 3600 or (st.get((slug, str(g["id"]))) or ("", ""))[0] != "processed"):
                    continue
                state = (g.get("lock_status"), str(g.get("has_stats")))
                if st.get((slug, str(g["id"]))) == state:
                    continue
                new.append(dict(observed_at=now.isoformat(timespec="seconds"), league=slug, game_id=g["id"], away=g["away_team"]["abbreviation"], home=g["home_team"]["abbreviation"],
                                start=g["start"], lock_status=g.get("lock_status"), has_stats=g.get("has_stats")))
    if new:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        fresh = not os.path.exists(LOG)
        with open(LOG, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            if fresh:
                w.writeheader()
            w.writerows(new)
    print(f"{len(new)} state changes logged at {now.isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()

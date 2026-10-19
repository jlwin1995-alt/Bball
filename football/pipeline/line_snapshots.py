"""Timestamped spread/total snapshots (NFL and college) so line movement can be measured honestly.

    ODDS_API_KEY=... python -m pipeline.line_snapshots

One /odds call per sport (spreads + totals, the sportsbooks without the DFS apps, about 2 credits each) appended to data/log/line_snapshots.csv:
ts, sport, event, commence, home, away, home_spread (NEGATIVE = home favoured), total, n_spread, n_total. Games that have already kicked off are skipped,
so the last snapshot of a game is its closing line. Compare snapshots of the same event to see how it moved between Wednesday, the morning of the game, etc.
"""
import csv, os, sys
from datetime import datetime, timezone
import requests
from . import config as C
from .fetch_odds import parse_game_lines

LOG = "data/log/line_snapshots.csv"
COLS = ["ts", "sport", "event", "commence", "home", "away", "home_spread", "total", "n_spread", "n_total"]
SPORTS = {"nfl": C.ODDS_SPORT, "cfb": C.ODDS_SPORT_CFB}


def snapshot(sport, events, now):
    ts = now.isoformat(timespec="seconds")
    return [dict(ts=ts, sport=sport, **{k: g[k] for k in COLS[2:]}) for g in parse_game_lines(events) if g["commence"] > ts.replace("+00:00", "Z")]


def append(rows, path=LOG):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if new:
            w.writeheader()
        w.writerows(rows)


def main():
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("::notice::ODDS_API_KEY not set; skipping")
        return
    now = datetime.now(timezone.utc)
    s = requests.Session()
    for sport, code in SPORTS.items():
        r = s.get(f"https://api.the-odds-api.com/v4/sports/{code}/odds", timeout=30,
                  params={"apiKey": key, "bookmakers": ",".join(b for b in C.ODDS_BOOKS if b not in C.DFS_BOOKS), "markets": "spreads,totals",
                          "oddsFormat": "american", "dateFormat": "iso"})
        if r.status_code != 200:
            print(f"::warning::{sport} snapshot: HTTP {r.status_code} {r.text[:120]}")
            continue
        rows = snapshot(sport, r.json(), now)
        append(rows)
        print(f"{sport}: {len(rows)} games; credits remaining {r.headers.get('x-requests-remaining')}")


if __name__ == "__main__":
    main()

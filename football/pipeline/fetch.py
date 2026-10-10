"""nflverse -> data/raw/*.csv

    python -m pipeline.fetch                 # current season: weekly stats, snap counts, schedule, injuries
    python -m pipeline.fetch --season 2025   # another season (kept in data/raw/history/ for the backtest)

nflverse publishes everything as release CSVs on GitHub (no key, no rate limit). Rows are kept as-is except that the 150-column
weekly file is cut down to the columns the model uses, and only regular-season rows are kept.
"""
import argparse, csv, io, os, sys, time
import requests
from . import config as C


def get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, timeout=120, headers={"User-Agent": "football-model"})
            if r.status_code == 200:
                return r.text
            last = f"HTTP {r.status_code}"
            if r.status_code == 404:
                break
        except requests.RequestException as e:
            last = str(e)
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def write(path, head, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)


def weekly(season, out):
    t = list(csv.reader(io.StringIO(get(f"{C.NFLVERSE}/stats_player/stats_player_week_{season}.csv"))))
    head, idx = t[0], {h: i for i, h in enumerate(t[0])}
    keep = [c for c in C.NFL_COLS if c in idx]
    rows = [[r[idx[c]] for c in keep] for r in t[1:] if r[idx["season_type"]] == C.SEASON_TYPE]
    write(out, keep, rows)
    return len(rows)


def schedule(season, out):
    t = list(csv.reader(io.StringIO(get(f"{C.NFLVERSE}/schedules/games.csv"))))
    si = t[0].index("season")
    rows = [r for r in t[1:] if r[si] == str(season)]
    write(out, t[0], rows)
    return len(rows)


def simple(url, out, season=None):
    t = list(csv.reader(io.StringIO(get(url))))
    write(out, t[0], t[1:])
    return len(t) - 1


def resolve_season(raw="data/raw"):
    """The newest season nflverse has published weekly stats for (this calendar year's once Week 1 has been played, otherwise last year's).
    Written to data/raw/season.txt so config.SEASON follows it: the site rolls over by itself in September and stays on last season through
    the off-season instead of failing every night on a file that does not exist yet."""
    today = C.dt.date.today()
    for s in (today.year, today.year - 1):
        try:
            with requests.get(f"{C.NFLVERSE}/stats_player/stats_player_week_{s}.csv", timeout=30, stream=True) as r:
                r.raise_for_status()
            os.makedirs(raw, exist_ok=True)
            open(os.path.join(raw, "season.txt"), "w").write(str(s))
            return s
        except requests.RequestException:
            continue
    return C.SEASON


def main(season=None, raw="data/raw"):
    current = resolve_season(raw)
    season = season or current
    cur = season == current
    d = raw if cur else os.path.join(raw, "history")
    sfx = "" if cur else f"_{season}"
    n = weekly(season, f"{d}/weekly{sfx}.csv")
    print(f"weekly {season}: {n} player-weeks")
    n = schedule(season, f"{d}/schedule{sfx}.csv")
    print(f"schedule {season}: {n} games")
    if cur:
        # Snap counts and injuries lag early in a week; never let them block a refresh.
        for name, url in (("snaps", f"{C.NFLVERSE}/snap_counts/snap_counts_{season}.csv"),
                          ("injuries", f"{C.NFLVERSE}/injuries/injuries_{season}.csv")):
            try:
                print(f"{name}: {simple(url, f'{d}/{name}.csv')} rows")
            except Exception as e:
                print(f"::warning::{name} unavailable ({e}); keeping the previous file", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--raw", default="data/raw")
    a = ap.parse_args()
    main(a.season, a.raw)

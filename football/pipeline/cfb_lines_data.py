"""CollegeFootballData game lines (and earlier seasons' scores) for the spread / total model.

    CFBD_API_KEY=... python -m pipeline.cfb_lines_data

One /lines call for the current season (data/raw/cfb_game_lines.csv, every refresh) and, ONCE, the two earlier seasons' games and lines
(data/raw/history/cfb_games_<y>.csv, cfb_game_lines_<y>.csv): 1 + 2 x 2 = 5 calls of the 1,000 a month. A finished game's line is its closing line.
home_spread is as books print it: NEGATIVE = the home team is favoured. The consensus is the median across the providers CFBD lists.
"""
import argparse, os, statistics
from . import config as C
from .cfb_data import get, norm_game, write_csv, read_csv, GAME_COLS

LINE_COLS = ["id", "season", "week", "home", "away", "home_spread", "total", "n_spread", "n_total"]


def num(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def parse_lines(items, season):
    """/lines -> one row per game with the median spread (home perspective, negative = home favoured) and total."""
    rows = []
    for g in items:
        sp, tot = [], []
        for ln in g.get("lines") or []:
            s, t = num(ln.get("spread")), num(ln.get("overUnder"))
            fm = str(ln.get("formattedSpread") or "")
            if s is not None:
                # CFBD's spread is the home team's; the formatted text ("Texas -3.5") names the favourite, so trust it when the two disagree
                home = str(g.get("homeTeam") or "")
                fav_home = fm.startswith(home) if home and fm else None
                if fav_home is not None and fm and abs(s) > 0:
                    s = -abs(s) if fav_home else abs(s)
                sp.append(s)
            if t is not None:
                tot.append(t)
        if sp or tot:
            rows.append(dict(id=g.get("id"), season=season, week=g.get("week"), home=g.get("homeTeam"), away=g.get("awayTeam"),
                             home_spread=statistics.median(sp) if sp else "", total=statistics.median(tot) if tot else "", n_spread=len(sp), n_total=len(tot)))
    return rows


def main(raw="data/raw", key=None):
    key = (key or os.environ.get("CFBD_API_KEY", "")).strip()
    if not key:
        print("CFBD_API_KEY is not set; skipping college lines")
        return 0
    calls = 0
    cur = C.SEASON
    items = get("/lines", key, year=cur, seasonType=C.CFB_SEASON_TYPE)
    calls += 1
    write_csv(f"{raw}/cfb_game_lines.csv", LINE_COLS, parse_lines(items, cur))
    for y in (cur - 1, cur - 2):
        gp, lp = f"{raw}/history/cfb_games_{y}.csv", f"{raw}/history/cfb_game_lines_{y}.csv"
        if not os.path.exists(gp):
            games = [norm_game(g) for g in get("/games", key, year=y, seasonType=C.CFB_SEASON_TYPE, classification="fbs")]
            calls += 1
            games.sort(key=lambda g: (g["week"] if g["week"] != "" else 99))
            write_csv(gp, GAME_COLS, games)
        if not os.path.exists(lp):
            write_csv(lp, LINE_COLS, parse_lines(get("/lines", key, year=y, seasonType=C.CFB_SEASON_TYPE), y))
            calls += 1
    print(f"college lines: {calls} API calls")
    return calls


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    a = ap.parse_args()
    main(a.raw)

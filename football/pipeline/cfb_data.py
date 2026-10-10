"""CollegeFootballData -> data/raw/cfb_games.csv and data/raw/cfb_weekly.csv

    CFBD_API_KEY=... python -m pipeline.cfb_data [--season 2025]

Free tier is 1,000 calls/month, so this spends as few as it can: one call for the schedule, one for player positions (only when something is
fetched), and one per played week - but a week already stored is NOT fetched again unless more of its games have finished since (tracked in
data/raw/cfb_meta.json). A refresh with nothing new costs one call.

The season-totals endpoint cannot support a projection (no rolling window, no opponent), so weekly splits are rebuilt from /games/players, which
returns box scores per game with both teams side by side. CFBD reports RECEPTIONS, not targets, so there is no catch rate to model, and it
publishes no injury report at any tier.
"""
import argparse, csv, json, os, sys, time
import requests
from . import config as C

WEEK_COLS = ["week", "playerId", "player", "position", "team", "conference", "opponent", "home", "carries", "rushing_yards", "rushing_tds",
             "receptions", "receiving_yards", "receiving_tds", "completions", "attempts", "passing_yards", "passing_tds", "interceptions", "fumbles_lost"]
GAME_COLS = ["id", "week", "startDate", "completed", "neutralSite", "homeTeam", "homeConference", "homePoints", "awayTeam", "awayConference", "awayPoints"]


def key_(s):
    """Stat names vary; normalise before matching so casing/spacing cannot break it."""
    return "".join(ch for ch in str("" if s is None else s).upper() if ch.isalnum() or ch == "/")


def cnum(v):
    if v is None or v == "":
        return 0.0
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return 0.0


def get(path, key, tries=3, **params):
    last = None
    for i in range(tries):
        try:
            r = requests.get(C.CFBD + path, params=params, headers={"Authorization": f"Bearer {key}"}, timeout=120)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:120]}"
            if r.status_code in (401, 403, 404, 429):
                break
        except requests.RequestException as e:
            last = str(e)
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"{path}: {last}")


def flatten_week(games, week, positions, seen=None):
    """One week of /games/players -> one wide row per offensive player. Shape: game -> teams[] -> categories[] -> types[] -> athletes[]."""
    seen = {} if seen is None else seen
    out = []
    for game in games:
        teams = game.get("teams") or []
        names = [t.get("team") for t in teams]
        for t in teams:
            opp = next((n for n in names if n != t.get("team")), "")
            acc = {}
            for cat in t.get("categories") or []:
                cn = key_(cat.get("name"))
                for typ in cat.get("types") or []:
                    tn = key_(typ.get("name"))
                    seen[f"{cn}.{tn}"] = seen.get(f"{cn}.{tn}", 0) + 1
                    for a in typ.get("athletes") or []:
                        pid = str(a.get("id"))
                        if pid not in acc:
                            acc[pid] = dict(week=week, playerId=pid, player=a.get("name") or "", position=positions.get(pid, ""), team=t.get("team") or "",
                                            conference=t.get("conference") or "", opponent=opp, home=t.get("homeAway") == "home",
                                            carries=0.0, rushing_yards=0.0, rushing_tds=0.0, receptions=0.0, receiving_yards=0.0, receiving_tds=0.0,
                                            completions=0.0, attempts=0.0, passing_yards=0.0, passing_tds=0.0, interceptions=0.0, fumbles_lost=0.0)
                        p, v = acc[pid], a.get("stat")
                        if cn == "RUSHING":
                            if tn in ("CAR", "ATT", "CARRIES"): p["carries"] = cnum(v)
                            elif tn in ("YDS", "YARDS"): p["rushing_yards"] = cnum(v)
                            elif tn in ("TD", "TDS"): p["rushing_tds"] = cnum(v)
                        elif cn == "RECEIVING":
                            if tn in ("REC", "RECEPTIONS"): p["receptions"] = cnum(v)
                            elif tn in ("YDS", "YARDS"): p["receiving_yards"] = cnum(v)
                            elif tn in ("TD", "TDS"): p["receiving_tds"] = cnum(v)
                        elif cn == "FUMBLES":
                            if tn == "LOST": p["fumbles_lost"] = cnum(v)
                        elif cn == "PASSING":
                            # /games/players sends a combined "27/41"; the flat season endpoint sends separate ATT and COMPLETIONS. Accept both.
                            if tn in ("C/ATT", "CATT"):
                                parts = str(v).split("/")
                                if len(parts) == 2:
                                    p["completions"], p["attempts"] = cnum(parts[0]), cnum(parts[1])
                            elif tn in ("COMPLETIONS", "COMP"): p["completions"] = cnum(v)
                            elif tn in ("ATT", "ATTEMPTS"): p["attempts"] = cnum(v)
                            elif tn in ("YDS", "YARDS"): p["passing_yards"] = cnum(v)
                            elif tn in ("TD", "TDS"): p["passing_tds"] = cnum(v)
                            elif tn in ("INT", "INTS"): p["interceptions"] = cnum(v)
            # defensive players come back in the same payload; keep only those who touched the ball on offence
            out += [p for p in acc.values() if p["carries"] or p["receptions"] or p["attempts"]]
    return out


def norm_game(g):
    pick = lambda *ks: next((g[k] for k in ks if k in g and g[k] is not None), "")
    return dict(id=pick("id"), week=pick("week"), startDate=pick("startDate", "start_date"), completed=bool(pick("completed")),
                neutralSite=bool(pick("neutralSite", "neutral_site")), homeTeam=pick("homeTeam", "home_team"),
                homeConference=pick("homeConference", "home_conference"), homePoints=pick("homePoints", "home_points"),
                awayTeam=pick("awayTeam", "away_team"), awayConference=pick("awayConference", "away_conference"),
                awayPoints=pick("awayPoints", "away_points"))


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main(season=None, raw="data/raw", key=None, max_seconds=None):
    key = (key or os.environ.get("CFBD_API_KEY", "")).strip()
    if not key:
        print("CFBD_API_KEY is not set; skipping college data (get a free key at collegefootballdata.com/key)")
        return 0
    season = season or C.SEASON
    cur = season == C.SEASON
    d = raw if cur else os.path.join(raw, "history")
    sfx = "" if cur else f"_{season}"
    games = [norm_game(g) for g in get("/games", key, year=season, seasonType=C.CFB_SEASON_TYPE, classification="fbs")]
    games.sort(key=lambda g: (g["week"] if g["week"] != "" else 99))
    write_csv(f"{d}/cfb_games{sfx}.csv", GAME_COLS, games)
    done, total = {}, {}
    for g in games:
        total[g["week"]] = total.get(g["week"], 0) + 1
        if g["completed"]:
            done[g["week"]] = done.get(g["week"], 0) + 1
    meta_path = f"{d}/cfb_meta{sfx}.json"
    meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {"fetched": {}}
    rows = read_csv(f"{d}/cfb_weekly{sfx}.csv")
    positions, calls, t0 = None, 1, time.time()
    for w in sorted(done):
        if w == "" or w > C.CFB_MAX_WEEK:
            continue
        # a stored week is only fetched again if more of its games have finished since (the newest week is often still filling in)
        if meta["fetched"].get(str(w)) == done[w]:
            continue
        if max_seconds and calls > 1 and time.time() - t0 > max_seconds:
            print(f"stopping early; the next run continues from week {w}")
            break
        if positions is None:                      # positions are cosmetic: never fail a refresh over them
            try:
                positions = {str(u["id"]): u.get("position") or "" for u in get("/player/usage", key, year=season) if u.get("id")}
            except RuntimeError as e:
                print(f"::warning::positions unavailable ({e})")
                positions = {}
            calls += 1
        wk = get("/games/players", key, year=season, week=w, seasonType=C.CFB_SEASON_TYPE, classification="fbs")
        calls += 1
        rows = [r for r in rows if int(float(r["week"])) != w]
        rows += [{k: (int(v) if k == "home" else v) for k, v in p.items()} for p in flatten_week(wk, w, positions)]
        meta["fetched"][str(w)] = done[w]
        print(f"week {w}: {done[w]}/{total[w]} games final, fetched")
    rows.sort(key=lambda r: float(r["week"]))
    write_csv(f"{d}/cfb_weekly{sfx}.csv", WEEK_COLS, rows)
    meta["totals"] = {str(k): v for k, v in total.items()}
    meta["done"] = {str(k): v for k, v in done.items()}
    json.dump(meta, open(meta_path, "w"))
    print(f"college {season}: {len(rows)} player-weeks, {len(games)} games, {calls} API calls")
    return calls


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--raw", default="data/raw")
    a = ap.parse_args()
    main(a.season, a.raw)

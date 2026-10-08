"""Fetch NBA data from ESPN's public JSON endpoints (no key) into data/raw/.

    python -m pipeline.fetch_espn [--backfill]

Writes games.csv (player box scores, incremental: finished games already stored are skipped),
schedule.csv (next 7 days) and injuries.csv. --backfill also pulls the prior season window.

NOTE: written against ESPN's documented-by-observation response shapes and NOT yet run against the live
API (the development sandbox blocks the host). The stat keys are read by name and a missing key
raises loudly instead of filling zeros. Run it once locally or from the GitHub Action and check
`python -m pipeline.fetch_espn --selftest` output before trusting the numbers.
"""
import argparse, os, sys, time
from datetime import date, datetime, timedelta, timezone
import pandas as pd
import requests
from . import config as C

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
S = requests.Session()
S.headers["User-Agent"] = "bball-projections (personal project)"
RAW = "data/raw"


def get(url, **params):
    for i in range(4):
        try:
            r = S.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(2 ** i)
    raise RuntimeError(f"GET failed: {url} {params}")


def scoreboard(day):
    return get(f"{BASE}/scoreboard", dates=day.strftime("%Y%m%d"), limit=100).get("events", [])


def split(v):
    a, b = str(v).split("-")
    return int(a), int(b)


def parse_box(event_id, ev_date, season, home_abbr, away_abbr):
    box = get(f"{BASE}/summary", event=event_id).get("boxscore", {}).get("players", [])
    rows = []
    for tm in box:
        team = tm["team"]["abbreviation"]
        opp, home = (away_abbr, 1) if team == home_abbr else (home_abbr, 0)
        for grp in tm.get("statistics", []):
            keys = grp["keys"]
            need = ["minutes", "points", "rebounds", "assists", "steals", "blocks", "turnovers",
                    "fieldGoalsMade-fieldGoalsAttempted", "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
                    "freeThrowsMade-freeThrowsAttempted"]
            missing = [k for k in need if k not in keys]
            if missing:
                raise KeyError(f"ESPN box score keys changed, missing {missing}; got {keys}")
            ix = {k: keys.index(k) for k in need}
            for a in grp.get("athletes", []):
                st = a.get("stats") or []
                if a.get("didNotPlay") or not st or not st[ix["minutes"]] or st[ix["minutes"]] in ("--", "0"):
                    continue
                fgm, fga = split(st[ix["fieldGoalsMade-fieldGoalsAttempted"]])
                tpm, _ = split(st[ix["threePointFieldGoalsMade-threePointFieldGoalsAttempted"]])
                ftm, fta = split(st[ix["freeThrowsMade-freeThrowsAttempted"]])
                ath = a["athlete"]
                rows.append(dict(pid=ath["id"], name=ath["displayName"], team=team,
                                 pos=(ath.get("position") or {}).get("abbreviation", "F"), date=ev_date, opp=opp, home=home,
                                 season=season, min=float(st[ix["minutes"]]), pts=int(st[ix["points"]]), reb=int(st[ix["rebounds"]]),
                                 ast=int(st[ix["assists"]]), fg3m=tpm, stl=int(st[ix["steals"]]), blk=int(st[ix["blocks"]]),
                                 tov=int(st[ix["turnovers"]]), fgm=fgm, fga=fga, ftm=ftm, fta=fta, event=event_id))
    return rows


def fetch_rosters():
    """Current roster per team -> data/raw/rosters.csv. The model uses it so a player who changed teams
    over the summer is projected for his NEW team, and players on no roster are not projected at all."""
    teams = get(f"{BASE}/teams", limit=40)["sports"][0]["leagues"][0]["teams"]
    rows = []
    for t in teams:
        tm = t["team"]
        for g in get(f"{BASE}/teams/{tm['id']}/roster").get("athletes", []):
            for a in (g.get("items") or [g]):                 # flat list, or grouped by position
                rows.append(dict(pid=str(a["id"]), name=a.get("fullName") or a.get("displayName"), team=tm["abbreviation"]))
        time.sleep(0.15)
    pd.DataFrame(rows, columns=["pid", "name", "team"]).to_csv(f"{RAW}/rosters.csv", index=False)
    return len(rows)


def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def main(backfill=False):
    os.makedirs(RAW, exist_ok=True)
    path = f"{RAW}/games.csv"
    old = pd.read_csv(path, dtype={"pid": str, "event": str}) if os.path.exists(path) else pd.DataFrame()
    seen = set(old["event"].dropna()) if "event" in old else set()
    today = datetime.now(timezone.utc).date()
    windows = [(date.fromisoformat(C.CUR_START), min(today, date.fromisoformat(C.CUR_START) + timedelta(days=260)), C.SEASON)]
    if backfill or old.empty:
        windows.append((date.fromisoformat(C.PRIOR_START), date.fromisoformat(C.PRIOR_END), C.SEASON - 1))
    new = []
    for a, b, season in windows:
        if a > b:
            continue
        for day in daterange(a, b):
            for ev in scoreboard(day):
                comp = ev["competitions"][0]
                if not comp["status"]["type"].get("completed") or str(ev["id"]) in seen:
                    continue
                if ev.get("season", {}).get("type", 2) != 2:
                    continue
                t = {c["homeAway"]: c["team"]["abbreviation"] for c in comp["competitors"]}
                new += parse_box(ev["id"], day.isoformat(), season, t["home"], t["away"])
                time.sleep(0.15)
    if new:
        old = pd.concat([old, pd.DataFrame(new)], ignore_index=True)
        old.to_csv(path, index=False)
    print(f"games.csv: +{len(new)} player-games, {len(old)} total")

    sched = []
    for day in daterange(today, today + timedelta(days=21)):      # 21 days so the opener shows up in the offseason
        for ev in scoreboard(day):
            comp = ev["competitions"][0]
            if comp["status"]["type"].get("completed") or ev.get("season", {}).get("type", 2) != 2:
                continue                                           # finished, or preseason/playoffs (type 1/3)
            t = {c["homeAway"]: c["team"]["abbreviation"] for c in comp["competitors"]}
            local = ev["date"][:10] if False else day.isoformat()
            sched += [dict(date=local, team=t["home"], opp=t["away"], home=1), dict(date=local, team=t["away"], opp=t["home"], home=0)]
    pd.DataFrame(sched, columns=["date", "team", "opp", "home"]).to_csv(f"{RAW}/schedule.csv", index=False)
    print(f"schedule.csv: {len(sched) // 2} regular-season games in the next 21 days")

    try:
        print(f"rosters.csv: {fetch_rosters()} players")
    except Exception as e:                                     # soft-fail: the model falls back to last-played team
        print("rosters skipped:", e)

    inj = []
    for team in get(f"{BASE}/injuries").get("injuries", []):
        for i in team.get("injuries", []):
            ath = i.get("athlete", {})
            inj.append(dict(pid=str(ath.get("id")), name=ath.get("displayName"), team=(ath.get("team") or {}).get("abbreviation", team.get("displayName")),
                            status=i.get("status")))
    pd.DataFrame(inj, columns=["pid", "name", "team", "status"]).to_csv(f"{RAW}/injuries.csv", index=False)
    print(f"injuries.csv: {len(inj)} entries")


def selftest():
    """One scoreboard + one box score, printed raw, so the parsing can be eyeballed."""
    d = datetime.now(timezone.utc).date() - timedelta(days=1)
    for _ in range(200):
        evs = [e for e in scoreboard(d) if e["competitions"][0]["status"]["type"].get("completed")]
        if evs:
            e = evs[0]
            t = {c["homeAway"]: c["team"]["abbreviation"] for c in e["competitions"][0]["competitors"]}
            rows = parse_box(e["id"], d.isoformat(), C.SEASON, t["home"], t["away"])
            print(pd.DataFrame(rows).head(12).to_string())
            return
        d -= timedelta(days=1)
    print("no finished game found in the last 200 days")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    selftest() if a.selftest else main(a.backfill)

"""Pull NFL player-prop lines and prices from The Odds API into data/raw/odds.csv.

    ODDS_API_KEY=... python -m pipeline.fetch_odds [--force] [--probe]

One row per (game, player, market, bookmaker): line, over price, under price (American). Books in config.DFS_BOOKS (PrizePicks,
Underdog, Pick6) carry nominal prices, so only their LINE is used (shown beside the consensus).

Cost control: /events is free; /events/{id}/odds costs (markets x bookmaker-groups) credits per game. Only games starting inside
ODDS_HORIZON_HOURS are pulled, and the run stops if the remaining-credits header drops below ODDS_MIN_CREDITS.
NOT yet run against the live API from the dev sandbox (host blocked); the response parsing is unit-tested on a stub (pipeline/selftest.py).
"""
import csv, json, os, sys, time
from datetime import datetime, timedelta, timezone
import requests
from . import config as C

BASE = f"https://api.the-odds-api.com/v4/sports/{C.ODDS_SPORT}"
RAW = "data/raw"
COLS = ["ts", "event", "commence", "game", "home", "away", "player", "stat", "book", "line", "over", "under"]


def parse_event(ev, odds, now_iso):
    """Flatten one /events/{id}/odds response into rows.

    Names are not unique across the league (Josh Allen is a quarterback in Buffalo and an edge rusher in Jacksonville). If one book posts two
    different lines for the same name and market in one event, one of them belongs to somebody else and there is no way from here to tell which:
    guessing would price the wrong man, so those rows are dropped.
    """
    away, home = C.TEAM_ABBR.get(ev["away_team"], ev["away_team"]), C.TEAM_ABBR.get(ev["home_team"], ev["home_team"])
    rows, dropped = [], 0
    for bk in odds.get("bookmakers", []):
        for mk in bk.get("markets", []):
            spec = C.ODDS_MARKETS.get(mk["key"])
            if not spec:
                continue
            by_player, conflict = {}, set()
            for o in mk.get("outcomes", []):
                who = o.get("description")
                if not who or o.get("point") is None or o.get("name") not in ("Over", "Under"):
                    continue
                d = by_player.setdefault(who, {"line": o["point"]})
                if o["name"] == "Over":
                    if "over" in d and d["line"] != o["point"]:
                        conflict.add(who)
                    d["over"] = o.get("price")
                else:
                    if "under" in d and d["line"] != o["point"]:
                        conflict.add(who)
                    d["under"] = o.get("price")
                d["line"] = o["point"]
            for who, d in by_player.items():
                if who in conflict:
                    dropped += 1
                    continue
                rows.append(dict(ts=now_iso, event=ev["id"], commence=ev["commence_time"], game=f"{away} @ {home}", home=home, away=away,
                                 player=who, stat=spec[0], book=bk["key"], line=d["line"], over=d.get("over"), under=d.get("under")))
    if dropped:
        print(f"  dropped {dropped} player-market rows where one book posted two different lines for the same name (shared name)")
    return rows


def read_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_rows(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)


def probe(session=None):
    """Diagnostic (costs a handful of credits): which bookmakers and markets does the API have for the next NFL game?"""
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise SystemExit("ODDS_API_KEY is not set")
    s = session or requests.Session()
    r = s.get(f"{BASE}/events", params={"apiKey": key, "dateFormat": "iso"}, timeout=30)
    print("events HTTP", r.status_code)
    if r.status_code != 200:
        print(r.text[:200]); return
    evs = r.json()
    print(f"{len(evs)} upcoming events")
    if not evs:
        return
    ev = evs[0]
    print(f"probing {ev['away_team']} @ {ev['home_team']} ({ev['commence_time']})")
    j = s.get(f"{BASE}/events/{ev['id']}/markets", params={"apiKey": key, "regions": "us,us_dfs"}, timeout=30).json()
    for bk in j.get("bookmakers", []):
        print(f"  {bk['key']:<18} {', '.join(sorted(m['key'] for m in bk.get('markets', [])))[:150]}")
    resp = s.get(f"{BASE}/events/{ev['id']}/odds", timeout=30, params={"apiKey": key, "bookmakers": ",".join(C.ODDS_BOOKS), "markets": ",".join(C.ODDS_MARKETS), "oddsFormat": "american"})
    print("odds HTTP", resp.status_code, "credits left", resp.headers.get("x-requests-remaining"))
    for bk in resp.json().get("bookmakers", []):
        print(f"  {bk['key']:<18} " + ", ".join(f"{m['key']}: {len(m.get('outcomes', []))}" for m in bk.get("markets", [])))


def main(session=None, force=False):
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise SystemExit("ODDS_API_KEY is not set (GitHub: Settings -> Secrets and variables -> Actions -> New repository secret)")
    s = session or requests.Session()
    now = datetime.now(timezone.utc)
    prev_meta = json.load(open(f"{RAW}/odds_meta.json")) if os.path.exists(f"{RAW}/odds_meta.json") else {}
    if not force and prev_meta.get("ts"):
        age = (now - datetime.fromisoformat(prev_meta["ts"])).total_seconds() / 60
        if age < C.ODDS_MIN_INTERVAL_MIN:
            print(f"last check was {age:.0f} min ago (< {C.ODDS_MIN_INTERVAL_MIN}); skipping so backup runs do not spend credits. Use --force to override.")
            return
    horizon = now + timedelta(hours=C.ODDS_HORIZON_HOURS)
    prev_rows = read_rows(f"{RAW}/odds.csv")
    rows, remaining, n_games, info = [], None, 0, []
    r = s.get(f"{BASE}/events", params={"apiKey": key, "dateFormat": "iso"}, timeout=30)
    if r.status_code in (401, 429):
        raise SystemExit(f"Odds API {r.status_code}: {r.text[:200]}")
    r.raise_for_status()
    remaining = float(r.headers.get("x-requests-remaining", "nan"))
    events = [e for e in r.json() if now < datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) <= horizon]
    print(f"{len(events)} games start in the next {C.ODDS_HORIZON_HOURS}h (the events endpoint is free); credits remaining {remaining}")
    for ev in events:
        if remaining is not None and remaining == remaining and remaining < C.ODDS_MIN_CREDITS:
            print(f"stopping: only {remaining} credits left (ODDS_MIN_CREDITS={C.ODDS_MIN_CREDITS})")
            break
        resp = s.get(f"{BASE}/events/{ev['id']}/odds", timeout=30, params={
            "apiKey": key, "bookmakers": ",".join(C.ODDS_BOOKS), "markets": ",".join(C.ODDS_MARKETS), "oddsFormat": "american", "dateFormat": "iso"})
        if resp.status_code in (401, 429):
            raise SystemExit(f"Odds API {resp.status_code}: {resp.text[:200]}")
        resp.raise_for_status()
        remaining = float(resp.headers.get("x-requests-remaining", "nan"))
        got = parse_event(ev, resp.json(), now.isoformat(timespec="seconds"))
        n_games += 1
        info.append(dict(game=f"{C.TEAM_ABBR.get(ev['away_team'], ev['away_team'])} @ {C.TEAM_ABBR.get(ev['home_team'], ev['home_team'])}",
                         commence=ev["commence_time"], props=len(got)))
        if not got:
            print(f"  {ev['away_team']} @ {ev['home_team']}: no props posted yet for the configured books/markets")
        rows += got
        time.sleep(0.2)
    # Games that have kicked off are not re-fetched (books pull props at kickoff; live prices would cost credits and mean something else),
    # so carry their last PREGAME rows forward for a few hours. The site marks them LIVE.
    cutoff = now - timedelta(hours=C.ODDS_KEEP_STARTED_HOURS)
    started = lambda c: cutoff <= datetime.fromisoformat(str(c).replace("Z", "+00:00")) <= now
    seen_events = {x["event"] for x in rows}
    rows += [x for x in prev_rows if started(x["commence"]) and x["event"] not in seen_events]
    seen_games = {g["game"] for g in info}
    info += [g for g in prev_meta.get("games", []) if started(g["commence"]) and g["game"] not in seen_games]
    write_rows(f"{RAW}/odds.csv", rows)
    json.dump(dict(ts=now.isoformat(timespec="seconds"), credits=None if remaining is None or remaining != remaining else remaining, games=info),
              open(f"{RAW}/odds_meta.json", "w"))
    print(f"odds.csv: {len(rows)} lines across {n_games} games; credits remaining: {remaining}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="pull even if the last check was recent (manual runs)")
    ap.add_argument("--probe", action="store_true", help="diagnostic: what does the API have for the next game? (spends a few credits)")
    a = ap.parse_args()
    probe() if a.probe else main(force=a.force)

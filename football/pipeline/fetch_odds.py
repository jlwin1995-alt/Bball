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
CFB_BASE = f"https://api.the-odds-api.com/v4/sports/{C.ODDS_SPORT_CFB}"
RAW = "data/raw"
COLS = ["ts", "event", "commence", "game", "home", "away", "player", "stat", "book", "line", "over", "under"]


def parse_event(ev, odds, now_iso, markets=None, teams=None):
    """Flatten one /events/{id}/odds response into rows.

    Names are not unique across the league (Josh Allen is a quarterback in Buffalo and an edge rusher in Jacksonville). If one book posts two
    different lines for the same name and market in one event, one of them belongs to somebody else and there is no way from here to tell which:
    guessing would price the wrong man, so those rows are dropped.
    """
    markets = markets or C.ODDS_MARKETS
    away, home = teams or (C.TEAM_ABBR.get(ev["away_team"], ev["away_team"]), C.TEAM_ABBR.get(ev["home_team"], ev["home_team"]))
    rows, dropped = [], 0
    for bk in odds.get("bookmakers", []):
        for mk in bk.get("markets", []):
            spec = markets.get(mk["key"])
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


def parse_game_lines(events):
    """/odds (featured markets) -> one row per game: consensus spread (home perspective, NEGATIVE = home favoured, as books print it) and total.
    The consensus is the median across books; a book that posts only one of the two still counts for the one it posts."""
    import statistics
    out = []
    for ev in events:
        sp, tot = [], []
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk["key"] == "spreads":
                    for o in mk.get("outcomes", []):
                        if o.get("name") == ev["home_team"] and o.get("point") is not None:
                            sp.append(float(o["point"]))
                elif mk["key"] == "totals":
                    for o in mk.get("outcomes", []):
                        if o.get("name") == "Over" and o.get("point") is not None:
                            tot.append(float(o["point"]))
        if sp or tot:
            out.append(dict(event=ev["id"], commence=ev["commence_time"], home=ev["home_team"], away=ev["away_team"],
                            home_spread=statistics.median(sp) if sp else None, total=statistics.median(tot) if tot else None,
                            n_spread=len(sp), n_total=len(tot)))
    return out


def fetch_cfb_lines(s, key, now):
    """College spreads and totals: ONE call covers every upcoming game (cost = markets x bookmaker groups, about 2 credits), so this is cheap
    next to per-game player props. Never lets a failure here stop the NFL pull."""
    try:
        r = s.get(f"{CFB_BASE}/odds", timeout=30, params={"apiKey": key, "bookmakers": ",".join(b for b in C.ODDS_BOOKS if b not in C.DFS_BOOKS),
                                                           "markets": "spreads,totals", "oddsFormat": "american", "dateFormat": "iso"})
        if r.status_code != 200:
            print(f"college lines: HTTP {r.status_code} {r.text[:120]}")
            return
        games = parse_game_lines(r.json())
        json.dump(dict(ts=now.isoformat(timespec="seconds"), games=games), open(f"{RAW}/cfb_lines.json", "w"))
        print(f"college lines: {len(games)} games with a spread or total; credits remaining {r.headers.get('x-requests-remaining')}")
    except Exception as e:                                      # noqa: BLE001
        print(f"::warning::college lines failed: {e}")


def fetch_cfb_props(s, key, now, force=False, raw=RAW):
    """College player props. Only FBS games that are on the site's college schedule (so FCS and unmatched games cost nothing), only games
    starting inside CFB_PROPS_HORIZON_HOURS, and a game is not pulled again within CFB_PROPS_MIN_HOURS. Never lets a failure stop the NFL pull."""
    from . import cfb_lines
    try:
        gp = "site/data/cfb/games.json"
        if not os.path.exists(gp):
            print("college props: no college schedule yet; skipping")
            return
        games = json.load(open(gp))
        names = sorted({g["home"] for g in games} | {g["away"] for g in games})
        specs = {k: C.ODDS_MARKETS[k] for k in C.CFB_ODDS_MARKETS}
        mp = f"{raw}/cfb_odds_meta.json"
        meta = json.load(open(mp)) if os.path.exists(mp) else {}
        pulled = meta.get("pulled", {})
        prev = read_rows(f"{raw}/cfb_odds.csv")
        r = s.get(f"{CFB_BASE}/events", params={"apiKey": key, "dateFormat": "iso"}, timeout=30)
        if r.status_code != 200:
            print(f"college props: events HTTP {r.status_code}")
            return
        horizon = now + timedelta(hours=C.CFB_PROPS_HORIZON_HOURS)
        rows, info, remaining, calls, skipped = [], [], None, 0, 0
        fresh = set()
        for ev in r.json():
            ko = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
            if not now < ko <= horizon:
                continue
            h, a = cfb_lines.resolve(ev["home_team"], names), cfb_lines.resolve(ev["away_team"], names)
            if not (h or a) or not any({h, a} & {g["home"], g["away"]} for g in games):
                continue
            last = pulled.get(ev["id"])
            if not force and last and (now - datetime.fromisoformat(last)).total_seconds() < C.CFB_PROPS_MIN_HOURS * 3600:
                skipped += 1
                continue
            if remaining is not None and remaining < C.ODDS_MIN_CREDITS:
                print(f"college props: stopping, only {remaining} credits left")
                break
            resp = s.get(f"{CFB_BASE}/events/{ev['id']}/odds", timeout=30, params={"apiKey": key, "bookmakers": ",".join(C.ODDS_BOOKS),
                         "markets": ",".join(C.CFB_ODDS_MARKETS), "oddsFormat": "american", "dateFormat": "iso"})
            if resp.status_code != 200:
                print(f"college props: {ev['away_team']} @ {ev['home_team']} HTTP {resp.status_code} {resp.text[:100]}")
                if resp.status_code in (401, 429):
                    break
                continue
            remaining = float(resp.headers.get("x-requests-remaining", "nan"))
            got = parse_event(ev, resp.json(), now.isoformat(timespec="seconds"), markets=specs, teams=(a or ev["away_team"], h or ev["home_team"]))
            calls += 1
            fresh.add(ev["id"])
            pulled[ev["id"]] = now.isoformat(timespec="seconds")
            rows += got
            info.append(dict(event=ev["id"], game=f"{a or ev['away_team']} @ {h or ev['home_team']}", commence=ev["commence_time"], props=len(got)))
            time.sleep(0.2)
        cutoff = now - timedelta(hours=C.ODDS_KEEP_STARTED_HOURS)
        keep = lambda c: datetime.fromisoformat(str(c).replace("Z", "+00:00")) >= cutoff
        rows += [x for x in prev if x["event"] not in fresh and keep(x["commence"])]
        have = {g["event"] for g in info}
        info += [g for g in meta.get("games", []) if g["event"] not in have and keep(g["commence"])]
        write_rows(f"{raw}/cfb_odds.csv", rows)
        pulled = {k: v for k, v in pulled.items() if k in {g["event"] for g in info}}
        json.dump(dict(ts=now.isoformat(timespec="seconds"), credits=remaining if remaining is not None and remaining == remaining else meta.get("credits"),
                       games=info, pulled=pulled), open(mp, "w"))
        print(f"college props: pulled {calls} games ({skipped} skipped as recent), {len(rows)} lines kept; credits remaining {remaining}")
    except Exception as e:                                       # noqa: BLE001
        print(f"::warning::college props failed: {e}")


def probe(session=None, base=None):
    """Diagnostic (costs a handful of credits): which bookmakers and markets does the API have for the next game? Runs for NFL, then college."""
    if base is None:
        probe(session, BASE)
        print("\n=== college ===")
        return probe(session, CFB_BASE)
    # (below uses `base`)
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise SystemExit("ODDS_API_KEY is not set")
    s = session or requests.Session()
    r = s.get(f"{base}/events", params={"apiKey": key, "dateFormat": "iso"}, timeout=30)
    print("events HTTP", r.status_code)
    if r.status_code != 200:
        print(r.text[:200]); return
    evs = r.json()
    print(f"{len(evs)} upcoming events")
    if not evs:
        return
    now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    evs = sorted((e for e in evs if e['commence_time'] > now_iso), key=lambda e: e['commence_time'])
    if not evs:
        print('no game that has not started'); return
    ev = evs[0]
    print(f"probing {ev['away_team']} @ {ev['home_team']} ({ev['commence_time']})")
    j = s.get(f"{base}/events/{ev['id']}/markets", params={"apiKey": key, "regions": "us,us_dfs"}, timeout=30).json()
    for bk in j.get("bookmakers", []):
        print(f"  {bk['key']:<18} {', '.join(sorted(m['key'] for m in bk.get('markets', [])))[:400]}")
    mk = ",".join(C.ODDS_MARKETS)
    if base == CFB_BASE:                                    # college: the NFL player-prop names, plus the college-only ones the API lists
        mk = ",".join(dict.fromkeys(list(C.ODDS_MARKETS) + ["player_pass_yds", "player_rush_yds", "player_reception_yds", "player_receptions", "player_anytime_td"]))
    resp = s.get(f"{base}/events/{ev['id']}/odds", timeout=30, params={"apiKey": key, "bookmakers": ",".join(C.ODDS_BOOKS), "markets": mk, "oddsFormat": "american"})
    if resp.status_code != 200:
        print("odds HTTP", resp.status_code, resp.text[:200])
        return
    print("odds HTTP", resp.status_code, "credits left", resp.headers.get("x-requests-remaining"))
    for bk in resp.json().get("bookmakers", []):
        print(f"  {bk['key']:<18} " + ", ".join(f"{m['key']}: {len(m.get('outcomes', []))}" for m in bk.get("markets", [])))


FP_SPEC = {C.FP_MARKET: ("fp", "Fantasy pts", 0, 0, "normal")}
FP_LOG = "data/log/fp_lines_log.csv"
FP_COLS = ["ts", "event", "commence", "game", "home", "away", "player", "book", "line", "over", "under"]


def snapshot_fp(rows, now, path=FP_LOG):
    """Keep the LAST PRE-GAME fantasy-points line per (event, player, book): overwritten while the game has not started, never touched after kickoff."""
    new = [x for x in rows if datetime.fromisoformat(x["commence"].replace("Z", "+00:00")) > now]
    if not new:
        return 0
    key = lambda x: (x["event"], x["player"], x["book"])
    fresh = {key(x) for x in new}
    old = [x for x in read_rows(path) if key(x) not in fresh]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FP_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(old + new)
    return len(new)


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
    fetch_cfb_lines(s, key, now)
    fetch_cfb_props(s, key, now, force=force)
    horizon = now + timedelta(hours=C.ODDS_HORIZON_HOURS)
    prev_rows = read_rows(f"{RAW}/odds.csv")
    rows, remaining, n_games, info = [], None, 0, []
    fp_rows = []
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
            "apiKey": key, "bookmakers": ",".join(C.ODDS_BOOKS), "markets": ",".join([*C.ODDS_MARKETS, C.FP_MARKET]), "oddsFormat": "american", "dateFormat": "iso"})
        if resp.status_code in (401, 429):
            raise SystemExit(f"Odds API {resp.status_code}: {resp.text[:200]}")
        resp.raise_for_status()
        remaining = float(resp.headers.get("x-requests-remaining", "nan"))
        got = parse_event(ev, resp.json(), now.isoformat(timespec="seconds"))
        fp_rows += [x for x in parse_event(ev, resp.json(), now.isoformat(timespec="seconds"), markets=FP_SPEC) if x["book"] == C.FP_BOOK]
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
    n_fp = snapshot_fp(fp_rows, now)
    print(f"fantasy-points lines ({C.FP_BOOK}): {len(fp_rows)} seen, {n_fp} kept in the log")
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

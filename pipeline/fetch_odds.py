"""Pull NBA player-prop lines and prices from The Odds API into data/raw/odds.csv.

    ODDS_API_KEY=... python -m pipeline.fetch_odds

One row per (game, player, market, bookmaker): line, over price, under price (American). Books in
config.DFS_BOOKS (PrizePicks, Underdog, Pick6) carry nominal prices - their docs call DFS odds "indicative only"
- and non-default PrizePicks lines (goblins/demons) live in separate *_alternate markets, which are not pulled.

Cost control: /events is free; /events/{id}/odds costs (markets x bookmaker-groups) credits per game. Only games starting
inside ODDS_HORIZON_HOURS are pulled, and the run stops if the remaining-credits header drops below ODDS_MIN_CREDITS.
NOT yet run against the live API from the dev sandbox (host blocked); the response parsing is unit-tested on a stub.
"""
import json, os, sys, time
from datetime import datetime, timedelta, timezone
import pandas as pd
import requests
from . import config as C

BASE = "https://api.the-odds-api.com/v4"
RAW = "data/raw"

# ESPN's abbreviations, because that is what rosters, projections and the Live tab use (GS not GSW, NO not NOP, ...).
TEAM_ABBR = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GS", "Houston Rockets": "HOU", "Indiana Pacers": "IND", "Los Angeles Clippers": "LAC",
    "LA Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM", "Miami Heat": "MIA", "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NO", "New York Knicks": "NY", "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC", "San Antonio Spurs": "SA", "Toronto Raptors": "TOR", "Utah Jazz": "UTAH", "Washington Wizards": "WSH",
}


def event_odds(s, sport, ev_id, key):
    """One game's props. If the API rejects the market list (400/422: a key it does not know), retry market by market and skip the
    unknown ones, so a single bad market name can never fail the whole pull. Returns (json, credits_remaining, calls)."""
    url = f"{BASE}/sports/{sport}/events/{ev_id}/odds"
    base = {"apiKey": key, "bookmakers": ",".join(C.ODDS_BOOKS), "oddsFormat": "american", "dateFormat": "iso"}
    r = s.get(url, timeout=30, params={**base, "markets": ",".join(C.ODDS_MARKETS)})
    if r.status_code in (401, 429):
        raise SystemExit(f"Odds API {r.status_code}: {r.text[:200]}")
    if r.status_code not in (400, 422):
        r.raise_for_status()
        return r.json(), float(r.headers.get("x-requests-remaining", "nan")), 1
    left, calls, by_book = float("nan"), 1, {}
    for mk in C.ODDS_MARKETS:
        rr = s.get(url, timeout=30, params={**base, "markets": mk})
        calls += 1
        if rr.status_code in (400, 422):
            print(f"  skipping market {mk}: the API does not accept it ({rr.status_code})")
            continue
        if rr.status_code in (401, 429):
            raise SystemExit(f"Odds API {rr.status_code}: {rr.text[:200]}")
        rr.raise_for_status()
        left = float(rr.headers.get("x-requests-remaining", "nan"))
        for bk in rr.json().get("bookmakers", []):
            by_book.setdefault(bk["key"], {**bk, "markets": []})["markets"] += bk.get("markets", [])
    return {"bookmakers": list(by_book.values())}, left, calls


def parse_event(ev, odds, now_iso):
    """Flatten one /events/{id}/odds response into rows."""
    away, home = TEAM_ABBR.get(ev["away_team"], ev["away_team"]), TEAM_ABBR.get(ev["home_team"], ev["home_team"])
    rows = []
    for bk in odds.get("bookmakers", []):
        for mk in bk.get("markets", []):
            stat = C.ODDS_MARKETS.get(mk["key"])
            if not stat:
                continue
            by_player = {}
            for o in mk.get("outcomes", []):
                who = o.get("description")
                if not who or o.get("point") is None or o.get("name") not in ("Over", "Under"):
                    continue
                d = by_player.setdefault(who, {"line": o["point"]})
                d["over" if o["name"] == "Over" else "under"] = o.get("price")
                d["line"] = o["point"]
            for who, d in by_player.items():
                rows.append(dict(ts=now_iso, event=ev["id"], commence=ev["commence_time"], game=f"{away} @ {home}", home=home, away=away,
                                 player=who, stat=stat, book=bk["key"], line=d["line"], over=d.get("over"), under=d.get("under")))
    return rows


def probe(session=None):
    """Diagnostic (costs a handful of credits): what does The Odds API actually have for the next game of each feed?
    Prints which bookmakers/markets exist for it, what the DFS region (PrizePicks, Underdog, Pick6) returns, and whether
    ordinary books post any player props. Run from the workflow with 'probe' ticked, or:  ODDS_API_KEY=... python -m pipeline.fetch_odds --probe
    """
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise SystemExit("ODDS_API_KEY is not set")
    s = session or requests.Session()
    PROPS = "player_points,player_rebounds,player_assists,player_threes,player_points_alternate"
    def show(label, r):
        left = r.headers.get("x-requests-remaining") if hasattr(r, "headers") else None
        print(f"  [{label}] HTTP {r.status_code}" + (f", credits left {left}" if left else ""))
        if r.status_code != 200:
            print("    ", str(r.text)[:200]); return None
        return r.json()
    for sport in C.ODDS_SPORTS:
        r = s.get(f"{BASE}/sports/{sport}/events", params={"apiKey": key, "dateFormat": "iso"}, timeout=30)
        if r.status_code != 200:
            print(f"{sport}: events HTTP {r.status_code}"); continue
        evs = r.json()
        print(f"\n{sport}: {len(evs)} upcoming events")
        if not evs:
            continue
        ev = evs[0]
        print(f"  probing {ev['away_team']} @ {ev['home_team']} (tip {ev['commence_time']}, id {ev['id']})")
        base = f"{BASE}/sports/{sport}/events/{ev['id']}"
        found = {}
        j = show("which markets each book has (US + DFS regions)", s.get(f"{base}/markets", params={"apiKey": key, "regions": "us,us_dfs"}, timeout=30))
        if j:
            for bk in j.get("bookmakers", []):
                keys = sorted(m["key"] for m in bk.get("markets", []))
                found[bk["key"]] = keys
                print(f"     {bk['key']:<18} {', '.join(keys)[:140]}")
            ft = {b: [k for k in v if any(t in k for t in ("free", "field_goal", "fta", "ftm", "fantasy"))] for b, v in found.items()}
            print("     free-throw / field-goal / fantasy-score markets by book:", {b: v for b, v in ft.items() if v} or "none")
            print("     all distinct market keys across books:", ", ".join(sorted({k for v in found.values() for k in v})))
            print("     -> prizepicks listed:", "prizepicks" in found, "| any player_* market anywhere:", any(k.startswith("player_") for v in found.values() for k in v))
        for label, params in (("DFS region, player props", {"regions": "us_dfs", "markets": PROPS}),
                              ("US books, player props", {"regions": "us", "markets": "player_points,player_rebounds,player_assists"}),
                              ("US books, game moneyline", {"regions": "us", "markets": "h2h"})):
            resp = s.get(f"{base}/odds", params={"apiKey": key, "oddsFormat": "american", "dateFormat": "iso", **params}, timeout=30)
            j = show(label, resp)
            if j is None:
                continue
            bks = j.get("bookmakers", [])
            if not bks:
                print("     (no bookmakers returned)")
            for bk in bks:
                print(f"     {bk['key']:<18} " + ", ".join(f"{m['key']}: {len(m.get('outcomes', []))} outcomes" for m in bk.get("markets", [])))
        time.sleep(0.3)


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
    horizon = now + timedelta(hours=float(os.environ.get("ODDS_HORIZON_HOURS") or C.ODDS_HORIZON_HOURS))   # manual runs can look further ahead
    try:                                                   # free call: which basketball feeds does this key see?
        sp = s.get(f"{BASE}/sports", params={"apiKey": key, "all": "true"}, timeout=30)
        if sp.status_code == 200:
            ks = [f"{x['key']}{'' if x.get('active') else ' (inactive)'}" for x in sp.json() if "basketball" in x["key"]]
            print("basketball feeds visible:", ", ".join(ks) or "none")
    except requests.RequestException as e:
        print("could not list sports:", e)
    prev_rows = pd.read_csv(f"{RAW}/odds.csv") if os.path.exists(f"{RAW}/odds.csv") else pd.DataFrame()
    rows, remaining, n_games, n_calls, info = [], None, 0, 0, []
    credits_start = None
    for sport in C.ODDS_SPORTS:
        r = s.get(f"{BASE}/sports/{sport}/events", params={"apiKey": key, "dateFormat": "iso"}, timeout=30)
        if r.status_code in (404, 422):
            print(f"{sport}: not available ({r.status_code}); skipping")
            continue
        if r.status_code in (401, 429):
            raise SystemExit(f"Odds API {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        remaining = float(r.headers.get("x-requests-remaining", "nan"))
        credits_start = remaining if credits_start is None else credits_start
        events = [e for e in r.json() if now < datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) <= horizon]
        print(f"{sport}: {len(events)} games start in the next {C.ODDS_HORIZON_HOURS}h (events endpoint is free); credits remaining {remaining}")
        for ev in events:
            if remaining is not None and remaining < C.ODDS_MIN_CREDITS:
                print(f"stopping: only {remaining} credits left (ODDS_MIN_CREDITS={C.ODDS_MIN_CREDITS})")
                break
            payload, remaining, ncalls = event_odds(s, sport, ev['id'], key)
            n_calls += ncalls
            got = parse_event(ev, payload, now.isoformat(timespec="seconds"))
            n_games += 1
            info.append(dict(feed=sport, game=f"{TEAM_ABBR.get(ev['away_team'], ev['away_team'])} @ {TEAM_ABBR.get(ev['home_team'], ev['home_team'])}",
                             commence=ev["commence_time"], props=len(got)))
            if not got:
                print(f"  {ev['away_team']} @ {ev['home_team']}: no props posted yet for the configured books/markets")
            rows += got
            time.sleep(0.2)
    # Games that have tipped off are not re-fetched (books pull props at tip; live prices would cost credits and mean something else),
    # so carry their last PREGAME rows forward for a few hours. The site marks them LIVE.
    cutoff = now - timedelta(hours=C.ODDS_KEEP_STARTED_HOURS)
    started = lambda c: cutoff <= datetime.fromisoformat(str(c).replace("Z", "+00:00")) <= now
    seen_events = {r["event"] for r in rows}
    if len(prev_rows):
        keep = prev_rows[prev_rows["commence"].map(started) & ~prev_rows["event"].isin(seen_events)]
        rows += keep.astype(object).where(keep.notna(), None).to_dict("records")
    seen_games = {g["game"] for g in info}
    info += [g for g in prev_meta.get("games", []) if started(g["commence"]) and g["game"] not in seen_games]
    os.makedirs(RAW, exist_ok=True)
    cols = ["ts", "event", "commence", "game", "home", "away", "player", "stat", "book", "line", "over", "under"]
    pd.DataFrame(rows, columns=cols).to_csv(f"{RAW}/odds.csv", index=False)
    json.dump(dict(ts=now.isoformat(timespec="seconds"), credits=None if remaining is None or remaining != remaining else remaining,
                   games=info, feeds=[f for f in C.ODDS_SPORTS]), open(f"{RAW}/odds_meta.json", "w"))
    print(f"odds.csv: {len(rows)} lines across {n_games} games; credits remaining: {remaining}")
    if n_games and credits_start == credits_start and remaining == remaining:         # credit log: verifies cost per game, projects the month
        os.makedirs("data/log", exist_ok=True)
        lg = "data/log/odds_credits.csv"
        fresh = not os.path.exists(lg)
        used = credits_start - remaining
        with open(lg, "a") as f:
            if fresh:
                f.write("ts,games,calls,credits_before,credits_after,used,per_game\n")
            f.write(f"{now.isoformat(timespec='seconds')},{n_games},{n_calls},{credits_start:.0f},{remaining:.0f},{used:.0f},{used / n_games:.1f}\n")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="pull even if the last check was recent (manual runs)")
    ap.add_argument("--probe", action="store_true", help="diagnostic: what does the API have for the next game of each feed? (spends a few credits)")
    a = ap.parse_args()
    probe() if a.probe else main(force=a.force)

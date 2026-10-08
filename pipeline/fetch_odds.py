"""Pull NBA player-prop lines and prices from The Odds API into data/raw/odds.csv.

    ODDS_API_KEY=... python -m pipeline.fetch_odds

One row per (game, player, market, bookmaker): line, over price, under price (American). Books in
config.DFS_BOOKS (PrizePicks, Underdog, Pick6) carry nominal prices - their docs call DFS odds "indicative only"
- and non-default PrizePicks lines (goblins/demons) live in separate *_alternate markets, which are not pulled.

Cost control: /events is free; /events/{id}/odds costs (markets x bookmaker-groups) credits per game. Only games starting
inside ODDS_HORIZON_HOURS are pulled, and the run stops if the remaining-credits header drops below ODDS_MIN_CREDITS.
NOT yet run against the live API from the dev sandbox (host blocked); the response parsing is unit-tested on a stub.
"""
import os, sys, time
from datetime import datetime, timedelta, timezone
import pandas as pd
import requests
from . import config as C

BASE = "https://api.the-odds-api.com/v4"
RAW = "data/raw"

TEAM_ABBR = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI",
    "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND", "Los Angeles Clippers": "LAC",
    "LA Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM", "Miami Heat": "MIA", "Milwaukee Bucks": "MIL",
    "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP", "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR",
    "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


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


def main():
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise SystemExit("ODDS_API_KEY is not set (GitHub: Settings -> Secrets and variables -> Actions -> New repository secret)")
    s = requests.Session()
    now = datetime.now(timezone.utc)
    r = s.get(f"{BASE}/sports/{C.ODDS_SPORT}/events", params={"apiKey": key, "dateFormat": "iso"}, timeout=30)
    r.raise_for_status()
    horizon = now + timedelta(hours=C.ODDS_HORIZON_HOURS)
    events = [e for e in r.json() if now < datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) <= horizon]
    print(f"{len(events)} games start in the next {C.ODDS_HORIZON_HOURS}h (events endpoint is free)")
    rows, remaining = [], None
    for ev in events:
        if remaining is not None and remaining < C.ODDS_MIN_CREDITS:
            print(f"stopping: only {remaining} credits left (ODDS_MIN_CREDITS={C.ODDS_MIN_CREDITS})")
            break
        resp = s.get(f"{BASE}/sports/{C.ODDS_SPORT}/events/{ev['id']}/odds", timeout=30, params={
            "apiKey": key, "bookmakers": ",".join(C.ODDS_BOOKS), "markets": ",".join(C.ODDS_MARKETS), "oddsFormat": "american", "dateFormat": "iso"})
        if resp.status_code == 401 or resp.status_code == 429:
            raise SystemExit(f"Odds API {resp.status_code}: {resp.text[:200]}")
        resp.raise_for_status()
        remaining = float(resp.headers.get("x-requests-remaining", "nan"))
        rows += parse_event(ev, resp.json(), now.isoformat(timespec="seconds"))
        time.sleep(0.2)
    os.makedirs(RAW, exist_ok=True)
    cols = ["ts", "event", "commence", "game", "home", "away", "player", "stat", "book", "line", "over", "under"]
    pd.DataFrame(rows, columns=cols).to_csv(f"{RAW}/odds.csv", index=False)
    used = resp.headers.get("x-requests-last") if rows else None
    print(f"odds.csv: {len(rows)} lines across {len(events)} games; credits remaining: {remaining}")


if __name__ == "__main__":
    main()

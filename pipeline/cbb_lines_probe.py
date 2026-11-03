"""One-off Phase 0 check for a college-basketball model: what player-prop coverage does The Odds API have?   ->  data/log/cbb_probe/

    ODDS_API_KEY=... python -m pipeline.cbb_lines_probe

Free calls first (/sports, /sports/basketball_ncaab/events cost no credits), then a very small paid sample: the first 4 events that start within 30 hours get the
points / rebounds / assists / threes markets from the same sportsbooks and DFS books the NBA pull uses. Saves the raw answers, never the key. Research only.
"""
import json, os, sys, time
from datetime import datetime, timedelta, timezone
import requests
from . import config as C

BASE = "https://api.the-odds-api.com/v4"
OUT = "data/log/cbb_probe"
SPORT = "basketball_ncaab"
MARKETS = ["player_points", "player_rebounds", "player_assists", "player_threes"]
N_EVENTS = 4


def main():
    key = os.environ.get("ODDS_API_KEY")
    if not key: sys.exit("no ODDS_API_KEY")
    os.makedirs(OUT, exist_ok=True); s = requests.Session(); lines = []
    r = s.get(f"{BASE}/sports", params={"apiKey": key}, timeout=30); lines.append(f"/sports {r.status_code} credits_left={r.headers.get('x-requests-remaining')}")
    sports = r.json() if r.ok else []
    json.dump([x for x in sports if "basketball" in x.get("key", "")], open(f"{OUT}/sports.json", "w"), indent=1)
    lines.append("basketball sports: " + ", ".join(f"{x['key']}(active={x.get('active')})" for x in sports if "basketball" in x.get("key", "")))
    r = s.get(f"{BASE}/sports/{SPORT}/events", params={"apiKey": key, "dateFormat": "iso"}, timeout=30); lines.append(f"/events {r.status_code}")
    ev = r.json() if r.ok else []
    json.dump(ev, open(f"{OUT}/events.json", "w"), indent=1); lines.append(f"events listed: {len(ev)}")
    now = datetime.now(timezone.utc); soon = [e for e in ev if now <= datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) <= now + timedelta(hours=30)]
    lines.append(f"events starting within 30h: {len(soon)}")
    books = C.ODDS_BOOKS + C.DFS_BOOKS
    for i, e in enumerate(soon[:N_EVENTS]):
        rr = s.get(f"{BASE}/sports/{SPORT}/events/{e['id']}/odds", timeout=40, params={"apiKey": key, "bookmakers": ",".join(books), "markets": ",".join(MARKETS), "oddsFormat": "american", "dateFormat": "iso"})
        left = rr.headers.get("x-requests-remaining"); used = rr.headers.get("x-requests-last")
        if not rr.ok:
            lines.append(f"{e['away_team']} @ {e['home_team']}: {rr.status_code} {rr.text[:150]}"); continue
        j = rr.json(); json.dump(j, open(f"{OUT}/odds_{i}.json", "w"))
        per = {}
        for b in j.get("bookmakers", []):
            for m in b.get("markets", []):
                per.setdefault(b["key"], {}).setdefault(m["key"], set()).update(o.get("description") for o in m.get("outcomes", []))
        summ = "; ".join(f"{b}: " + ", ".join(f"{m} {len(p)}p" for m, p in ms.items()) for b, ms in per.items()) or "NO PLAYER PROPS"
        lines.append(f"{e['away_team']} @ {e['home_team']} ({e['commence_time']}): credits used {used}, left {left} | {summ}")
        time.sleep(1)
    open(f"{OUT}/summary.txt", "w").write("\n".join(lines) + "\n"); print("\n".join(lines))


if __name__ == "__main__":
    main()

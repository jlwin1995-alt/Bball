"""One-off Phase 0 check for a college-basketball model: what player-prop coverage does The Odds API have?   ->  data/log/cbb_probe/

    ODDS_API_KEY=... python -m pipeline.cbb_lines_probe

Free calls first (/sports, /sports/basketball_ncaab/events cost no credits), then a very small paid sample: the first N_EVENTS events (env, default 4) that start within HOURS (env, default 30) get the
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
N_EVENTS = int(os.environ.get("N_EVENTS", "4"))
HOURS = float(os.environ.get("HOURS", "30"))


def norm(n):
    """The Odds API writes 'Montana St Bobcats', ESPN 'Montana State Bobcats'."""
    n = " " + (n or "").lower().replace(".", "").replace("&", "and") + " "
    for a, b in ((" st ", " state "), (" univ ", " university "), (" intl ", " international ")):
        n = n.replace(a, b)
    return " ".join(n.split())


def conferences():
    """ESPN's Division I conference table: team display name -> conference (Non-NCAA Division I teams are not in it)."""
    out = {}
    try:
        g = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/groups", params={"group": "50"}, timeout=30).json()
        for top in g.get("groups", []):
            if top.get("name") != "NCAA Division I": continue
            for c in top.get("children", []):
                for t in c.get("teams", []):
                    out[norm(t.get("displayName") or t.get("name") or "")] = c.get("name", "").replace(" Conference", "")
    except Exception as e:
        print("conference table failed:", e)
    return out


def main():
    key = os.environ.get("ODDS_API_KEY")
    if not key: sys.exit("no ODDS_API_KEY")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M"); OUT_RUN = f"{OUT}/{stamp}"
    os.makedirs(OUT_RUN, exist_ok=True); s = requests.Session(); lines = []
    r = s.get(f"{BASE}/sports", params={"apiKey": key}, timeout=30); lines.append(f"/sports {r.status_code} credits_left={r.headers.get('x-requests-remaining')}")
    sports = r.json() if r.ok else []
    json.dump([x for x in sports if "basketball" in x.get("key", "")], open(f"{OUT_RUN}/sports.json", "w"), indent=1)
    lines.append("basketball sports: " + ", ".join(f"{x['key']}(active={x.get('active')})" for x in sports if "basketball" in x.get("key", "")))
    r = s.get(f"{BASE}/sports/{SPORT}/events", params={"apiKey": key, "dateFormat": "iso"}, timeout=30); lines.append(f"/events {r.status_code}")
    ev = r.json() if r.ok else []
    json.dump(ev, open(f"{OUT_RUN}/events.json", "w"), indent=1); lines.append(f"events listed: {len(ev)}")
    conf = conferences(); lines.append(f"conference table: {len(conf)} teams")
    tag = lambda n: conf.get(norm(n), "unmapped (mid/low major or non-D1)")
    now = datetime.now(timezone.utc); soon = [e for e in ev if now <= datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) <= now + timedelta(hours=HOURS)]
    lines.append(f"events starting within the window: {len(soon)}")
    books = C.ODDS_BOOKS + C.DFS_BOOKS
    for i, e in enumerate(soon[:N_EVENTS]):
        rr = s.get(f"{BASE}/sports/{SPORT}/events/{e['id']}/odds", timeout=40, params={"apiKey": key, "bookmakers": ",".join(books), "markets": ",".join(MARKETS), "oddsFormat": "american", "dateFormat": "iso"})
        left = rr.headers.get("x-requests-remaining"); used = rr.headers.get("x-requests-last")
        if not rr.ok:
            lines.append(f"{e['away_team']} [{tag(e['away_team'])}] @ {e['home_team']} [{tag(e['home_team'])}]: {rr.status_code} {rr.text[:150]}"); continue
        j = rr.json(); json.dump(j, open(f"{OUT_RUN}/odds_{i}.json", "w"))
        per = {}
        for b in j.get("bookmakers", []):
            for m in b.get("markets", []):
                per.setdefault(b["key"], {}).setdefault(m["key"], set()).update(o.get("description") for o in m.get("outcomes", []))
        summ = "; ".join(f"{b}: " + ", ".join(f"{m} {len(p)}p" for m, p in ms.items()) for b, ms in per.items()) or "NO PLAYER PROPS"
        lines.append(f"{e['away_team']} [{tag(e['away_team'])}] @ {e['home_team']} [{tag(e['home_team'])}] ({e['commence_time']}): credits used {used}, left {left} | {summ}")
        time.sleep(1)
    lines.append("window events by conference tag (away | home): " + "; ".join(sorted({f"{tag(e['away_team'])} @ {tag(e['home_team'])}" for e in soon})))
    open(f"{OUT_RUN}/summary.txt", "w").write("\n".join(lines) + "\n"); print("\n".join(lines))


if __name__ == "__main__":
    main()

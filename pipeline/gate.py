"""Decides whether a scheduled odds pull + data refresh should run now. Standard library only (runs before any install).

    python pipeline/gate.py decide [--state data/log/gate_odds.json] [--now 2026-10-22T21:00:00Z]   prints fire=1|0 and key=<what> (GITHUB_OUTPUT format)
    python pipeline/gate.py record KEY [--state ...]                                                 marks KEY as done (committed with the data)

Two daily runs, both decided here so the schedule follows the real slate and Eastern time (GitHub's cron is UTC only):
  morning  7:00-7:59 am Eastern, once per Eastern date;
  pretip   from 2 hours before the day's first tip until that tip, once per first-tip time. The first tip comes from ESPN's scoreboard.
The workflow ticks every 30 minutes; a tick that finds nothing to do ends in seconds and costs no Odds API credits.
"""
import argparse, json, os, sys, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
LEAD = timedelta(hours=2)
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={}"


def load(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return {}


def first_tip(day):
    """Earliest tip (UTC) among the NBA games ESPN lists for this Eastern date, or None."""
    req = urllib.request.Request(SCOREBOARD.format(day.strftime("%Y%m%d")), headers={"User-Agent": "bball-projections (personal project)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        events = json.load(r).get("events", [])
    tips = [datetime.fromisoformat(e["date"].replace("Z", "+00:00")) for e in events if e.get("date")]
    return min(tips) if tips else None


def decide(state, now):
    local = now.astimezone(ET)
    if local.hour == 7 and state.get("morning") != local.date().isoformat():
        return True, "morning:" + local.date().isoformat()
    try:
        tip = first_tip(local.date())
    except Exception as e:                                           # ESPN down: do nothing now, the next tick tries again
        print("scoreboard unavailable:", e, file=sys.stderr)
        return False, ""
    if tip and tip - LEAD <= now < tip and state.get("pretip") != tip.strftime("%Y-%m-%dT%H:%MZ"):
        return True, "pretip:" + tip.strftime("%Y-%m-%dT%H:%MZ")
    return False, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["decide", "record"])
    ap.add_argument("key", nargs="?", default="")
    ap.add_argument("--state", default="data/log/gate_odds.json")
    ap.add_argument("--now")
    a = ap.parse_args()
    state = load(a.state)
    if a.cmd == "record":
        kind, _, val = a.key.partition(":")
        if kind in ("morning", "pretip") and val:
            state[kind] = val
            os.makedirs(os.path.dirname(a.state), exist_ok=True)
            json.dump(state, open(a.state, "w"), indent=1)
            print("recorded", a.key)
        return
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    fire, key = decide(state, now)
    print(f"fire={int(fire)}")
    print(f"key={key}")
    print(f"gate: now {now:%Y-%m-%d %H:%MZ} -> {'RUN ' + key if fire else 'nothing to do'}", file=sys.stderr)


if __name__ == "__main__":
    main()

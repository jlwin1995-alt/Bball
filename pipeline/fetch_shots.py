"""Shot locations from ESPN play-by-play, one row per field-goal attempt, into data/raw/shots.csv.gz.

    python -m pipeline.fetch_shots [--limit N]

ESPN's summary endpoint (the same call that gives box scores) lists every play. A shooting play carries
coordinate {x, y} in feet (the rim is at about x=25, y=0; free throws have a sentinel and are skipped), the
shooter (participants[0]), whether it was made (scoringPlay), points attempted (2/3) and a shot type. There is NO
defender information: shot quality here means location + type, not contested vs open.

Incremental: events already in the file are skipped; the event list comes from games.csv, so run fetch_espn first.
"""
import argparse, os, time
import pandas as pd
from . import fetch_espn as E

PATH = f"{E.RAW}/shots.csv.gz"
COLS = ["event", "date", "pid", "team", "opp", "x", "y", "three", "made", "assisted", "blocked", "kind", "period"]


def parse_shots(event_id, ev_date, summary):
    comp = (summary.get("header", {}).get("competitions") or [{}])[0]
    ab = {str((c.get("team") or {}).get("id")): (c.get("team") or {}).get("abbreviation") for c in comp.get("competitors", [])}
    if len(ab) != 2 or None in ab.values():
        return []
    rows = []
    for p in summary.get("plays", []):
        co = p.get("coordinate")
        if not p.get("shootingPlay") or not co or p.get("pointsAttempted") not in (2, 3):
            continue
        x, y = co.get("x"), co.get("y")
        if x is None or y is None or x < -1000 or y < -1000:                # free throws / unlocated plays use a huge negative sentinel
            continue
        parts = p.get("participants") or []
        team = str((p.get("team") or {}).get("id"))
        if not parts or team not in ab:
            continue
        opp = [v for k, v in ab.items() if k != team][0]
        text = p.get("text", "")
        rows.append(dict(event=str(event_id), date=ev_date, pid=str(parts[0]["athlete"]["id"]), team=ab[team], opp=opp, x=x, y=y,
                         three=int(p["pointsAttempted"] == 3), made=int(bool(p.get("scoringPlay"))),
                         assisted=int("assists" in text), blocked=int(" blocks " in text),
                         kind=(p.get("type") or {}).get("text", ""), period=(p.get("period") or {}).get("number")))
    return rows


def main(raw=E.RAW, limit=None):
    games = pd.read_csv(f"{raw}/games.csv", dtype={"event": str})
    ev = games.drop_duplicates("event")[["event", "date"]].dropna()
    old = pd.read_csv(PATH, dtype={"pid": str, "event": str}) if os.path.exists(PATH) else pd.DataFrame(columns=COLS)
    todo = ev[~ev["event"].isin(set(old["event"]))]
    if limit:
        todo = todo.head(limit)
    new, bad = [], 0
    for i, r in enumerate(todo.itertuples(), 1):
        try:
            new += parse_shots(r.event, r.date, E.get(f"{E.BASE}/summary", event=r.event))
        except Exception as e:                                               # one bad game must not lose the rest
            bad += 1
            print("skip", r.event, e)
        if i % 100 == 0:
            print(f"{i}/{len(todo)} games, {len(new)} shots", flush=True)
        time.sleep(0.12)
    out = pd.concat([old, pd.DataFrame(new, columns=COLS)], ignore_index=True)
    out.to_csv(PATH, index=False, compression="gzip")
    print(f"shots: +{len(new)} from {len(todo) - bad} games ({bad} failed), {len(out)} total, {out['event'].nunique()} games")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=E.RAW)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    main(a.raw, a.limit)

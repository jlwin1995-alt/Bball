"""Shot locations from ESPN play-by-play, one row per field-goal attempt, into data/raw/shots.csv.gz.

    python -m pipeline.fetch_shots [--limit N]

ESPN's summary endpoint (the same call that gives box scores) lists every play. A shooting play carries
coordinate {x, y} in feet (the rim is at about x=25, y=0; free throws have a sentinel and are skipped), the
shooter (participants[0]), whether it was made (scoringPlay), points attempted (2/3) and a shot type. There is NO
defender information: shot quality here means location + type, not contested vs open.

Incremental: events already in the file are skipped; the event list comes from games.csv, so run fetch_espn first.

The same summary call also yields who started and every substitution, saved as stints in data/raw/stints.csv.gz (one row per continuous
spell on the floor; a row with an empty pid only marks a game that could not be parsed: event, date, team, pid, start and end in elapsed game seconds, starter = began the game). Rebuilt minutes match the box
score to within a minute for every player in 22 of 24 sampled games. Not used by the model yet; it is the base for a starter-rate feature
and, later, a rotation / game simulator.
"""
import argparse, os, re, time
import pandas as pd
from . import fetch_espn as E

PATH = f"{E.RAW}/shots.csv.gz"
STINTS = f"{E.RAW}/stints.csv.gz"
STINT_COLS = ["event", "date", "team", "pid", "start", "end", "starter"]
BACKFILL_PER_RUN = 350          # older games missing stints are filled this many per run so one refresh never takes long; new games are always done
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


def _clock(c):
    c = str(c)
    if ":" not in c:
        return float(c)
    m, sec = c.split(":")
    return int(m) * 60 + float(sec)


def _elapsed(period, clock):
    """Seconds since tip: four 12-minute quarters, then 5-minute overtimes; the clock counts down."""
    period = int(period)
    done = 720 * min(period - 1, 4) + 300 * max(period - 5, 0)
    return done + (720 if period <= 4 else 300) - _clock(clock)


def parse_stints(event_id, ev_date, summary):
    """Continuous spells on the floor per player, from the box score's starter flags and the substitution plays.
    Returns (rows, max_minutes_error) where the error compares the rebuilt minutes with the box score (a quality check), or ([], None)."""
    comp = (summary.get("header", {}).get("competitions") or [{}])[0]
    ab = {str((c.get("team") or {}).get("id")): (c.get("team") or {}).get("abbreviation") for c in comp.get("competitors", [])}
    box, starters, names = {}, {}, {}
    for t in summary.get("boxscore", {}).get("players", []):
        tid = str(t["team"]["id"])
        for st in t.get("statistics", []):
            ix = {k: i for i, k in enumerate(st.get("keys", []))}
            for a in st.get("athletes", []):
                pid = str(a["athlete"]["id"])
                names[(a["athlete"].get("displayName") or "").lower()] = pid
                if a.get("didNotPlay") or not a.get("stats") or "minutes" not in ix:
                    continue
                try:
                    box[pid] = float(a["stats"][ix["minutes"]])
                except ValueError:
                    continue
                if a.get("starter"):
                    starters.setdefault(tid, set()).add(pid)
    if len(ab) != 2 or any(len(starters.get(t, ())) != 5 for t in ab):
        return [], None
    plays = summary.get("plays", [])
    if not plays:
        return [], None
    end = max(_elapsed(p["period"]["number"], p["clock"]["displayValue"]) for p in plays)
    on = {t: set(starters[t]) for t in ab}
    since = {pid: 0.0 for t in on for pid in on[t]}
    first = set(since)
    rows = []

    def close(tid, pid, t):
        if pid in on[tid]:
            on[tid].discard(pid)
            rows.append(dict(event=str(event_id), date=ev_date, team=ab[tid], pid=pid, start=round(since.pop(pid), 1), end=round(t, 1), starter=int(pid in first)))
            return True
        return False

    for p in plays:
        if (p.get("type") or {}).get("text") != "Substitution":
            continue
        tid = str((p.get("team") or {}).get("id"))
        if tid not in on:
            continue
        ids = [str((x.get("athlete") or {}).get("id") or "") for x in p.get("participants", [])]
        if len(ids) < 2 or not all(ids[:2]):                      # id missing in some older feeds: fall back to the names in the text
            m = re.match(r"(.+?) enters the game for (.+)", p.get("text", ""))
            ids = [names.get(m.group(1).strip().lower(), ""), names.get(m.group(2).strip().lower(), "")] if m else ["", ""]
        pin, pout = ids[0], ids[1]
        if not pin or not pout:
            continue
        t = _elapsed(p["period"]["number"], p["clock"]["displayValue"])
        close(tid, pout, t)
        on[tid].add(pin)
        since[pin] = t
    for tid in on:
        for pid in list(on[tid]):
            close(tid, pid, end)
    if not rows:
        return [], None
    played = {}
    for r in rows:
        played[r["pid"]] = played.get(r["pid"], 0.0) + (r["end"] - r["start"]) / 60
    err = max(abs(played.get(pid, 0.0) - m) for pid, m in box.items())
    return rows, round(err, 1)


def main(raw=E.RAW, limit=None):
    games = pd.read_csv(f"{raw}/games.csv", dtype={"event": str})
    ev = games.drop_duplicates("event")[["event", "date"]].dropna()
    ev = ev[ev["date"] >= E.C.PRIOR_START]                               # games.csv also holds the season before last (player rates only)
    old = pd.read_csv(PATH, dtype={"pid": str, "event": str}) if os.path.exists(PATH) else pd.DataFrame(columns=COLS)
    have_shots = set(old["event"])
    old_st = pd.read_csv(STINTS, dtype={"pid": str, "event": str}) if os.path.exists(STINTS) else pd.DataFrame(columns=STINT_COLS)
    have_st = set(old_st["event"])
    need_shots = ev[~ev["event"].isin(have_shots)]
    need_st = ev[~ev["event"].isin(have_st)].sort_values("date", ascending=False)        # newest first
    recent = need_st[need_st["date"] >= (pd.Timestamp.now() - pd.Timedelta(days=3)).strftime("%Y-%m-%d")]
    older = need_st[~need_st["event"].isin(set(recent["event"]))].head(BACKFILL_PER_RUN)
    todo = pd.concat([need_shots, recent, older]).drop_duplicates("event")
    if limit:
        todo = todo.head(limit)
    new, new_st, bad, bad_st = [], [], 0, 0
    for i, r in enumerate(todo.itertuples(), 1):
        try:
            summ = E.get(f"{E.BASE}/summary", event=r.event)
            if r.event not in have_shots:
                new += parse_shots(r.event, r.date, summ)
        except Exception as e:                                               # one bad game must not lose the rest
            bad += 1
            print("skip", r.event, e)
            continue
        if r.event not in have_st:
            try:
                rows, err = parse_stints(r.event, r.date, summ)
                if not rows:                                           # unparseable (no starters flagged, no plays): leave a marker so it is not refetched every run
                    rows = [dict(event=str(r.event), date=r.date, team="", pid="", start=0, end=0, starter=0)]
                new_st += rows
                if err is not None and err > 1.5:
                    bad_st += 1
                    print(f"stints: {r.event} rebuilt minutes are {err} off the box score")
            except Exception as e:
                print("stints skip", r.event, e)
        if i % 100 == 0:
            print(f"{i}/{len(todo)} games, {len(new)} shots, {len(new_st)} stints", flush=True)
        time.sleep(0.12)
    out = pd.concat([old, pd.DataFrame(new, columns=COLS)], ignore_index=True)
    out.to_csv(PATH, index=False, compression="gzip")
    st = pd.concat([old_st, pd.DataFrame(new_st, columns=STINT_COLS)], ignore_index=True)
    st.to_csv(STINTS, index=False, compression="gzip")
    print(f"shots: +{len(new)} from {len(todo) - bad} games ({bad} failed), {len(out)} total, {out['event'].nunique()} games")
    print(f"stints: +{len(new_st)} rows, {st['event'].nunique()} games total, {bad_st} new games with minutes more than 1.5 off the box score, {len(ev) - st['event'].nunique()} games still to fill")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=E.RAW)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    main(a.raw, a.limit)

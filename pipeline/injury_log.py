"""Injury snapshots with the availability tag from the note -> data/log/injury_log.csv  (research: how often does a "probable" / "questionable" player actually play?)

    python -m pipeline.injury_log            # snapshot the next slate (run by the refresh workflow, soft-fail)
    python -m pipeline.injury_log --report   # P(played) by tag for slate days that are already in games.csv

ESPN collapses probable / questionable to "Day-To-Day"; the note text says which ("Jokic is probable for Monday's game", "Allen is questionable ..."). Each refresh logs, for the teams on the next
slate day, every Out / Doubtful / Day-To-Day player with the tag parsed from the note. A row is appended only when something changed since the last logged row for that (slate day, player), so the
LAST row per (slate day, player) is his state at the final pre-tip refresh. Notes are about a specific game: a stale note (older than the slate day by 2+ days) is tagged 'stale'.
"""
import os, re, sys, datetime as dt
import pandas as pd, numpy as np

RAW, LOG = "data/raw", "data/log"
COLS = ["snap_ts", "slate_date", "team", "pid", "name", "status", "tag", "note_ts", "note"]
TAGS = [("out", r"ruled out|is out|will not play|won't play|will miss|sitting out|not play|has been ruled|is listed as out|out for"), ("doubtful", r"doubtful"),
        ("questionable", r"questionable|game-time decision|gametime decision"), ("probable", r"probable|expected to play|will play|available")]


def parse_tag(note, status, note_ts, slate_date):
    n = str(note or "").lower()
    try:
        age = (pd.Timestamp(slate_date) - pd.Timestamp(note_ts).tz_convert(None).normalize()).days
    except Exception:
        age = 0
    # the more specific availability words win over a generic 'out for'; order: doubtful, questionable, probable, then out
    for tag, pat in (TAGS[1], TAGS[2], TAGS[3], TAGS[0]):
        if re.search(pat, n): return "stale" if age > 2 and tag != "out" else tag
    return "stale" if age > 2 else ("out" if status in ("Out", "Doubtful") else "other")


def snapshot():
    inj = pd.read_csv(f"{RAW}/injuries.csv", dtype={"pid": str}); sched = pd.read_csv(f"{RAW}/schedule.csv")
    day = sorted(sched.date.unique())[0]; teams = set(sched[sched.date == day].team)
    x = inj[inj.team.isin(teams) & inj.status.isin(["Out", "Doubtful", "Day-To-Day"])].copy()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    x["tag"] = [parse_tag(n, s, t, day) for n, s, t in zip(x.note, x.status, x.ts)]
    new = pd.DataFrame({"snap_ts": now, "slate_date": day, "team": x.team, "pid": x.pid, "name": x.name, "status": x.status, "tag": x.tag, "note_ts": x.ts, "note": x.note.astype(str).str.slice(0, 160)}, columns=COLS)
    path = f"{LOG}/injury_log.csv"; os.makedirs(LOG, exist_ok=True)
    old = pd.read_csv(path, dtype={"pid": str}) if os.path.exists(path) else pd.DataFrame(columns=COLS)
    last = old.sort_values("snap_ts").groupby(["slate_date", "pid"]).tail(1).set_index(["slate_date", "pid"]) if len(old) else pd.DataFrame()
    keep = []
    for r in new.itertuples(index=False):
        k = (r.slate_date, r.pid)
        if len(last) and k in last.index and (last.loc[k, "status"], last.loc[k, "tag"], last.loc[k, "note_ts"]) == (r.status, r.tag, r.note_ts): continue
        keep.append(r)
    if keep: pd.concat([old, pd.DataFrame(keep, columns=COLS)], ignore_index=True).to_csv(path, index=False)
    print(f"injury snapshot for {day}: {len(new)} listed, {len(keep)} new or changed; tags {new.tag.value_counts().to_dict()}")


def report():
    log = pd.read_csv(f"{LOG}/injury_log.csv", dtype={"pid": str})
    fin = log.sort_values("snap_ts").groupby(["slate_date", "pid"]).tail(1)
    g = pd.read_csv(f"{RAW}/games.csv", dtype={"pid": str}, usecols=["pid", "date", "min"]); g = g[g["min"] > 0]
    played = set(zip(g.date, g.pid)); days = set(g.date)
    fin = fin[fin.slate_date.isin(days)].copy(); fin["played"] = [(d, p) in played for d, p in zip(fin.slate_date, fin.pid)]
    out = fin.groupby("tag").played.agg(["size", "sum"]).rename(columns={"size": "n", "sum": "played"}); out["p_played"] = (out.played / out.n).round(2)
    print(out.to_string()); print("by ESPN status:"); print(fin.groupby("status").played.agg(["size", "mean"]).round(2).to_string())


if __name__ == "__main__":
    report() if "--report" in sys.argv else snapshot()

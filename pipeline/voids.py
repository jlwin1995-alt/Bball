"""Plays that void: a player who misses the whole second half, or leaves hurt and does not come back.

  data/log/voids.csv   date, pid, name, team, reason, note      (written here; edit by hand to add or remove a row)

Two automatic signals, both read after the game, and the rule underneath them: a play is void only if the player did NOT touch the court after
halftime. Leaving hurt in the 2nd half does not void it (he played in that half), whatever the injury note says.
  stints   data/raw/stints.csv.gz has no spell on the floor after halftime (1440 s) for a man who has box-score minutes
  note     ESPN's injury feed carries a news note ("won't return ...") stamped during that player's game day (injuries.csv note/ts); it only
           counts when the stints show no 2nd-half time (or the game's stints are not parsed yet), and then supplies the reason text
Rows already in voids.csv are kept, so a note that ESPN later overwrites is not lost. results.py leaves voided players out of the
hit-rate tallies and marks them in the Results tab; error numbers still include them.

    python -m pipeline.voids [--raw data/raw] [--log data/log/voids.csv]
"""
import argparse, os, re
import pandas as pd
from . import config as C

LOG = "data/log/voids.csv"
COLS = ["date", "pid", "name", "team", "reason", "note"]
HALF = 1440.0                                    # seconds of game time at halftime
LEFT = re.compile(r"won'?t return|will not return|did not return|didn'?t return|not return|ruled out for the (rest|remainder)|left .{0,40}game|exited", re.I)


def from_stints(G, S):
    """G box scores, S stints. Only games with stints parsed are judged."""
    if S is None or not len(S):
        return pd.DataFrame(columns=COLS)
    G = G[(G["min"] > 0) & G["event"].isin(set(S["event"]))]
    late = S[S["end"] > HALF]
    h2 = set(zip(late["event"], late["pid"]))
    miss = G[[(e, p) not in h2 for e, p in zip(G["event"], G["pid"])]]
    return pd.DataFrame({"date": miss["date"].astype(str), "pid": miss["pid"], "name": miss["name"], "team": miss["team"],
                         "reason": "no 2nd half", "note": ""})


def played_h2(G, S):
    """{(date, pid): True/False} for box-score players in games whose stints are parsed: did he touch the court after halftime? Others are absent (unknown)."""
    if S is None or not len(S):
        return {}
    G = G[(G["min"] > 0) & G["event"].isin(set(S["event"]))]
    late = S[S["end"] > HALF]
    h2 = set(zip(late["event"], late["pid"]))
    return {(str(d), p): (e, p) in h2 for d, p, e in zip(G["date"], G["pid"], G["event"])}


def from_notes(G, inj, played=None):
    """An injury note stamped between 16:00Z on the game's (US Eastern) date and 16:00Z the next day, saying he did not return.
    Leaving hurt only voids the play if he missed the whole second half: a man who played in the 2nd half (even briefly) is NOT void-eligible,
    so with stints parsed a note counts only when he has no second-half time; with no stints for the game the note is the best evidence there is."""
    played = played or {}
    if inj is None or "note" not in inj or "ts" not in inj:
        return pd.DataFrame(columns=COLS)
    inj = inj[inj["note"].fillna("").map(lambda s: bool(LEFT.search(s))) & inj["pid"].notna()].copy()
    if not len(inj):
        return pd.DataFrame(columns=COLS)
    inj["ts"] = pd.to_datetime(inj["ts"], utc=True, errors="coerce")
    rows = []
    for r in G[G["min"] > 0].itertuples():
        for i in inj[inj["pid"] == r.pid].itertuples():
            start = pd.Timestamp(str(r.date), tz="UTC") + pd.Timedelta(hours=16)
            if pd.notna(i.ts) and start <= i.ts <= start + pd.Timedelta(hours=24) and played.get((str(r.date), r.pid)) is not True:
                rows.append(dict(date=str(r.date), pid=r.pid, name=r.name, team=r.team, reason="injured, no return", note=str(i.note)[:200]))
    return pd.DataFrame(rows, columns=COLS)


def update(raw="data/raw", log=LOG, games=None):
    G = (games if games is not None else pd.read_csv(f"{raw}/games.csv", dtype={"pid": str, "event": str}))
    G = G.astype({"pid": str}); G["date"] = G["date"].astype(str)
    if "event" in G:
        G["event"] = G["event"].astype(str)
    G = G[G["date"] >= C.CUR_START]                                      # this season only
    S = pd.read_csv(f"{raw}/stints.csv.gz", dtype={"pid": str, "event": str}) if os.path.exists(f"{raw}/stints.csv.gz") else None
    inj = pd.read_csv(f"{raw}/injuries.csv", dtype={"pid": str}) if os.path.exists(f"{raw}/injuries.csv") else None
    old = pd.read_csv(log, dtype={"pid": str, "date": str}) if os.path.exists(log) else pd.DataFrame(columns=COLS)
    played = played_h2(G, S)
    new = pd.concat([from_stints(G, S), from_notes(G, inj, played)], ignore_index=True)
    allv = pd.concat([old, new], ignore_index=True)
    allv["note"] = allv["note"].fillna("")
    auto = allv["reason"].isin(["no 2nd half", "injured, no return"])           # hand-added rows (any other reason) are never touched
    has_h2 = pd.Series([played.get((str(d), p)) is True for d, p in zip(allv["date"], allv["pid"])], index=allv.index)
    allv = allv[~(auto & has_h2)]   # played after halftime: not void-eligible
    # one row per player-day: keep the one that has a note (the more informative reason), else the first seen
    allv = allv.sort_values("note", key=lambda s: s == "", kind="stable").drop_duplicates(["date", "pid"]).sort_values(["date", "team", "name"])
    os.makedirs(os.path.dirname(log), exist_ok=True)
    allv[COLS].to_csv(log, index=False)
    return allv


def load(log=LOG):
    if not os.path.exists(log):
        return {}
    v = pd.read_csv(log, dtype={"pid": str, "date": str}).fillna("")
    return {(r.date, r.pid): (r.reason + (": " + r.note if r.note else "")) for r in v.itertuples()}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--log", default=LOG)
    a = ap.parse_args()
    v = update(a.raw, a.log)
    print(f"voids.csv: {len(v)} rows ({(v['reason'] == 'injured, no return').sum()} with an injury note)")

"""Import the Google-Sheets model's own accuracy log (data/legacy/sheet_accuracy_log.csv, an export of its Accuracy_Log tab) into this project's log.

The sheet ran the same model before this site existed, logging each week's projections before kickoff (rows it logged after kickoff are marked LATE
and are never scored). Those NFL weeks are appended to data/log/accuracy_log.csv under the stamp "sheet", so they show up on the Results tab with
their box-score outcomes (taken from nflverse, like everything else) and on the Scorecard under "Earlier record (Google Sheet)". A week that is
already in the log is never touched, and the import is idempotent. Only points carry a baseline in the sheet's log (season average and last 3), so
the earlier record is scored on points; per-market projections are still shown on Results.
"""
import csv, datetime as dt, os
from .scorecard import COLS, LOG, read_log

SRC = "data/legacy/sheet_accuracy_log.csv"
STAMP = "sheet"


def day(s):
    try:
        m, d, y = str(s).split("/")
        return dt.date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return ""


def import_sheet_log(src=SRC, path=LOG):
    if not os.path.exists(src):
        return 0
    have = {(x["season"], x["week"], x["stamp"]) for x in read_log(path)}
    new = []
    with open(src, newline="") as f:
        for r in csv.DictReader(f):
            if r["League"] != "NFL" or r["Scored"] not in ("yes", "DNP", "LATE"):
                continue                              # a week still waiting on its games is the live log's job, not history
            if (r["Season"], r["Week"], STAMP) in have or any(k[:2] == (r["Season"], r["Week"]) for k in have):
                continue
            row = {c: "" for c in COLS}
            row.update(season=r["Season"], week=r["Week"], player_id=r["player_id"], name=r["Player"], pos=r["Pos"], team=r["Team"], opp=r["Opp"],
                       kickoff=day(r["Kickoff"]), logged_at=day(r["Logged"]), late=int(r["Scored"] == "LATE"), stamp=STAMP,
                       car=r["Proj Car"], att=r["Proj Att"], p_rushY=r["Proj Rush Yds"], p_rec=r["Proj Rec"], p_recY=r["Proj Rec Yds"],
                       p_passY=r["Proj Pass Yds"], p_comp=r["Proj Comp"], p_sacks=r["Proj Sacks"], p_pts=r["Proj Pts"],
                       bs_pts=r["Base Season"], bl_pts=r["Base Last3"])
            new.append(row)
    if not new:
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a" if exists else "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if not exists:
            w.writeheader()
        w.writerows(new)
    return len(new)

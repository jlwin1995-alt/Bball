"""Log DARKO's own projections next to ours for each day's logged slate  ->  data/log/darko_proj.csv   (display/research only; feeds nothing)

    python -m pipeline.darko_log

DARKO (darko.app) serves a public, keyless MCP endpoint. For the latest date in accuracy_log.csv that is not yet in darko_proj.csv (the log only
writes in the window from 2 hours before the first tip), every logged player projected 12+ minutes is looked up by name (ids cached in
data/log/darko_ids.json) and DARKO's projected minutes, pace and per-100 rates are stored beside ours, so the two can be scored against the box
scores later. DARKO's numbers are season-level expectations, not adjusted for that night's injuries. Any failure is soft: the refresh goes on.
"""
import json, os, time, urllib.request
import pandas as pd

URL = "https://www.darko.app/mcp"
LOG = "data/log/darko_proj.csv"
IDS = "data/log/darko_ids.json"
KEYS = ["x_minutes", "x_pace", "x_pts_100", "x_ast_100", "x_orb_100", "x_drb_100", "x_stl_100", "x_blk_100", "x_tov_100", "x_fg3a_100"]
MIN_MIN = 12.0


def call(tool, args):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}).encode()
    req = urllib.request.Request(URL, body, {"content-type": "application/json", "accept": "application/json, text/event-stream", "user-agent": "bball-darko-log"})
    for t in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                line = [l for l in r.read().decode().splitlines() if l.startswith("data: ")][0][6:]
            return json.loads(json.loads(line)["result"]["content"][0]["text"])
        except Exception:
            time.sleep(1 + t)
    return None


def main():
    A = pd.read_csv("data/log/accuracy_log.csv", dtype={"pid": str})
    day = A["date"].max()
    done = pd.read_csv(LOG, dtype={"pid": str}) if os.path.exists(LOG) else pd.DataFrame()
    if len(done) and (done["date"] == day).any():
        print("darko: already logged", day); return
    A = A[(A["date"] == day) & (A["min"] >= MIN_MIN)].drop_duplicates("pid")
    ids = json.load(open(IDS)) if os.path.exists(IDS) else {}
    need = [(r.pid, r.name) for r in A.itertuples() if r.pid not in ids]
    for i in range(0, len(need), 6):
        ch = need[i:i + 6]
        res = call("search_players", {"queries": [n for _, n in ch]})
        if not res: continue
        for (pid, n), m in zip(ch, res["matches"]):
            c = m["candidates"]; ex = [x for x in c if x["player_name"].lower() == n.lower()]; c = ex or c
            ids[pid] = c[0]["nba_id"] if len(c) == 1 else None          # ambiguous names stay unmapped (None)
    os.makedirs("data/log", exist_ok=True); json.dump(ids, open(IDS, "w"))
    rows = []; keep = [(r, ids.get(r.pid)) for r in A.itertuples()]; keep = [(r, i) for r, i in keep if i]
    for i in range(0, len(keep), 6):
        ch = keep[i:i + 6]
        res = call("get_players", {"ids": [i for _, i in ch], "groups": ["projections"]})
        if not res: continue
        by = {p["nba_id"]: p["values"]["projections"] for p in res["players"] if p.get("values", {}).get("projections")}
        for r, nid in ch:
            v = by.get(nid)
            if v: rows.append({"date": day, "pid": r.pid, "name": r.name, "team": r.team, "nba_id": nid, "our_min": r.min, "our_pts": r.pts, "our_reb": r.reb,
                               "our_ast": r.ast, "our_fp": r.fp, **{k: v.get(k) for k in KEYS}})
    if rows:
        pd.concat([done, pd.DataFrame(rows)], ignore_index=True).to_csv(LOG, index=False)
    print(f"darko: logged {len(rows)} of {len(A)} players for {day}")


if __name__ == "__main__":
    main()

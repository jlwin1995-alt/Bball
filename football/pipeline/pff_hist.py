"""Pull PFF weekly receiving summaries into data/raw/pff_hist/ (needs PFF_API_KEY; run in GitHub Actions).

    python -m pipeline.pff_hist --seasons 2022 2023 2024 2025 2026 [--weeks 1 18]

One call per (season, week) to /v1/facet/receiving/summary (about 250 rows each), kept to the columns the model can use, one CSV per season:
data/raw/pff_hist/pff_receiving_<season>.csv. Throttled under the 100 reads a minute limit and retried on 429. The repository is private; PFF's terms govern the data
and it is never staged into the public site.
"""
import argparse, csv, os, sys, time
import requests

BASE = "https://api.pff.com"
KEEP = ["season", "week", "player_id", "player", "team", "position", "player_game_count", "routes", "pass_plays", "route_rate", "targets", "receptions", "yards",
        "touchdowns", "slot_snaps", "wide_snaps", "inline_snaps", "slot_rate", "wide_rate", "inline_rate", "pass_block_rate", "yprr", "grades_offense",
        "grades_pass_route", "avg_depth_of_target", "caught_percent", "drops", "contested_targets"]


def get(path, params, key, tries=4):
    h = {"Authorization": f"Bearer {key}", "Accept": "application/json", "User-Agent": "gridiron-model"}
    for i in range(tries):
        r = requests.get(BASE + path, params=params, headers=h, timeout=120)
        if r.status_code == 429:
            wait = float(r.headers.get("Retry-After", 5)) + 1
            print(f"  429, waiting {wait:.0f}s")
            time.sleep(wait)
            continue
        if r.status_code in (502, 503, 504):
            time.sleep(3 * (i + 1))
            continue
        return r
    return r


# report name -> (path, response key, columns kept, positions kept (None = all)); the file is data/raw/pff_hist/<prefix><report>_<season>.csv (NFL receiving keeps its old name)
SKILL = {"QB", "HB", "WR", "TE", "FB", "RB"}
REPORTS = {
    "receiving": ("/v1/facet/receiving/summary", "receiving_summary", KEEP[2:], None),
    "passing": ("/v1/facet/passing/summary", "passing_summary", ["player_id", "player", "team", "team_name", "position", "player_game_count", "attempts", "dropbacks", "passing_snaps",
                                                                  "completions", "yards", "touchdowns", "interceptions", "sacks", "scrambles", "ypa", "grades_pass", "grades_offense",
                                                                  "avg_time_to_throw", "avg_depth_of_target", "twp_rate", "btt_rate", "pressure_to_sack_rate"], None),
    "rushing": ("/v1/facet/rushing/summary", "rushing_summary", ["player_id", "player", "team", "team_name", "position", "player_game_count", "attempts", "run_plays", "yards", "ypa",
                                                                  "touchdowns", "targets", "receptions", "routes", "total_touches", "yards_after_contact", "elusive_rating", "grades_run",
                                                                  "grades_offense", "scrambles"], None),
    "passblock": ("/v1/facet/offense/pass_blocking", None, ["player_id", "player", "team", "position", "player_game_count", "snap_counts_pass_play", "snap_counts_pass_block", "pressures_allowed",
                                                            "sacks_allowed", "hits_allowed", "hurries_allowed", "grades_pass_block", "pbe", "pass_block_percent"], None),
    "passrush": ("/v1/facet/defense/pass_rush", None, ["player_id", "player", "team", "position", "player_game_count", "snap_counts_pass_play", "snap_counts_pass_rush", "total_pressures", "sacks",
                                                       "hits", "hurries", "pass_rush_win_rate", "pass_rush_percent", "grades_pass_rush_defense"], None),
    # defence reports keep every column the API returns (cols None); they are aggregated to team-weeks by pff_def.py
    "defsummary": ("/v1/facet/defense/summary", None, None, None),
    "defcoverage": ("/v1/facet/defense/coverage", None, None, None),
    "defrun": ("/v1/facet/defense/run", None, None, None),
    "defmatchup": ("/v1/facet/defense/coverage_matchup", None, None, None),
    "offense": ("/v1/facet/offense/summary", "offense_summary", ["player_id", "player", "team", "team_name", "position", "player_game_count", "snap_counts_total", "snap_counts_pass",
                                                                  "snap_counts_run", "snap_counts_pass_route", "snap_counts_pass_block", "snap_counts_run_block", "snap_counts_total_pass",
                                                                  "snap_counts_total_run", "grades_offense", "grades_pass_route", "grades_run_block", "grades_pass_block"], SKILL),
}


def pull(league, seasons, w0, w1, reports, out="data/raw/pff_hist", key=None):
    key = key or os.environ.get("PFF_API_KEY", "").strip()
    if not key:
        sys.exit("PFF_API_KEY is not set")
    os.makedirs(out, exist_ok=True)
    pre = "" if league == "nfl" else f"{league}_"
    for rep in reports:
        path, rk, cols, keep_pos = REPORTS[rep]
        fields = ["season", "week"] + [c for c in (cols or []) if c not in ("season", "week")]
        for s in seasons:
            rows = []
            for wk in range(w0, w1 + 1):
                r = get(path, dict(league=league, season=s, week=wk), key)
                if r.status_code != 200:
                    print(f"{league} {rep} {s} wk {wk}: HTTP {r.status_code} {r.text[:120]}")
                    time.sleep(0.8)
                    continue
                body = r.json()
                data = body.get(rk, []) if rk else next((v for v in body.values() if isinstance(v, list) and v and isinstance(v[0], dict)), [])    # rk None: the one list in the response
                n0 = len(data)
                for x in data:
                    if keep_pos and x.get("position") not in keep_pos:
                        continue
                    if cols is None:
                        fields += [k for k in x if k not in fields and not isinstance(x[k], (dict, list))]
                    rows.append({k: (s if k == "season" else wk if k == "week" else x.get(k)) for k in fields})
                print(f"{league} {rep} {s} wk {wk}: {n0} rows ({len(rows)} kept) remaining {r.headers.get('x-ratelimit-remaining')}", flush=True)
                time.sleep(0.8)
            if rows:
                with open(f"{out}/{pre}{rep}_{s}.csv" if league != "nfl" or rep != "receiving" else f"{out}/pff_receiving_{s}.csv", "w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(rows)
                print(f"{league} {rep} {s}: {len(rows)} rows written", flush=True)


def pull_team_games(seasons, out="data/raw/pff_hist", key=None):
    """Per-game PFF team grades (offense, pass, run, pass block, run block, coverage, pass rush, run defence ...) for every franchise: /v1/teams/summary, one call per franchise and season.
    Also the franchise id -> abbreviation map from /v1/teams/overview. Writes team_games_<season>.csv with every column the API returns."""
    key = key or os.environ.get("PFF_API_KEY", "").strip()
    if not key:
        sys.exit("PFF_API_KEY is not set")
    os.makedirs(out, exist_ok=True)
    for s in seasons:
        ov = get("/v1/teams/overview", dict(league="nfl", season=s), key)
        abbr = {}
        if ov.status_code == 200:
            for x in ov.json().get("teams", ov.json().get("overview", [])) if isinstance(ov.json(), dict) else []:
                abbr[x.get("franchise_id")] = x.get("abbreviation")
            if not abbr:
                body = ov.json()
                lst = next((v for v in body.values() if isinstance(v, list)), []) if isinstance(body, dict) else []
                abbr = {x.get("franchise_id"): x.get("abbreviation") for x in lst}
        rows, cols = [], []
        for fid in range(1, 33):
            r = get("/v1/teams/summary", dict(league="nfl", season=s, franchise_id=fid), key)
            if r.status_code != 200:
                print(f"{s} franchise {fid}: HTTP {r.status_code} {r.text[:120]}")
                time.sleep(0.8)
                continue
            body = r.json()
            data = next((v for v in body.values() if isinstance(v, list)), []) if isinstance(body, dict) else body
            for x in data:
                x = dict(x, season=s, team=abbr.get(fid, fid))
                rows.append(x)
                cols += [k for k in x if k not in cols]
            print(f"{s} franchise {fid} ({abbr.get(fid)}): {len(data)} games (remaining {r.headers.get('x-ratelimit-remaining')})", flush=True)
            time.sleep(0.8)
        if rows:
            with open(f"{out}/team_games_{s}.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                w.writerows(rows)
            print(f"{s}: {len(rows)} team-games written; columns: {', '.join(cols)}")


def main(seasons, w0, w1, out="data/raw/pff_hist"):
    key = os.environ.get("PFF_API_KEY", "").strip()
    if not key:
        sys.exit("PFF_API_KEY is not set")
    os.makedirs(out, exist_ok=True)
    for s in seasons:
        rows = []
        for wk in range(w0, w1 + 1):
            r = get("/v1/facet/receiving/summary", dict(league="nfl", season=s, week=wk), key)
            if r.status_code != 200:
                print(f"{s} wk {wk}: HTTP {r.status_code} {r.text[:150]}")
                continue
            data = r.json().get("receiving_summary", [])
            for x in data:
                rows.append({k: (x.get(k) if k not in ("season", "week") else (s if k == "season" else wk)) for k in KEEP})
            print(f"{s} wk {wk}: {len(data)} rows (remaining {r.headers.get('x-ratelimit-remaining')})", flush=True)
            time.sleep(0.8)
        if rows:
            with open(f"{out}/pff_receiving_{s}.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=KEEP)
                w.writeheader()
                w.writerows(rows)
            print(f"{s}: {len(rows)} rows written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="nfl")
    ap.add_argument("--seasons", type=int, nargs="+", default=[2022, 2023, 2024, 2025, 2026])
    ap.add_argument("--weeks", type=int, nargs=2, default=[1, 18])
    ap.add_argument("--reports", nargs="+", default=None)
    a = ap.parse_args()
    if a.reports == ["team_games"]:
        pull_team_games(a.seasons)
    elif a.league == "nfl" and a.reports is None:
        main(a.seasons, a.weeks[0], a.weeks[1])
    else:
        pull(a.league, a.seasons, a.weeks[0], a.weeks[1], a.reports or list(REPORTS))

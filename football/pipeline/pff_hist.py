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
    ap.add_argument("--seasons", type=int, nargs="+", default=[2022, 2023, 2024, 2025, 2026])
    ap.add_argument("--weeks", type=int, nargs=2, default=[1, 18])
    a = ap.parse_args()
    main(a.seasons, a.weeks[0], a.weeks[1])

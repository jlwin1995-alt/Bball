"""PFF API probe (runs in GitHub Actions; the key comes from the PFF_API_KEY secret and is never printed).

    python -m pipeline.pff_api openapi                       # public contract: every path, its parameters and response keys
    python -m pipeline.pff_api whoami                        # tier / entitlement (uses the key)
    python -m pipeline.pff_api call /path --params '{"league":"nfl","season":2025,"week":1}' [--rows 2]
                                                             # one authenticated GET; prints the SHAPE (column keys and labels, row count, one row) and the rate-limit headers

Everything is printed to the job log of a private repo for reading; nothing is written to the repository.
"""
import argparse, json, os, sys
import requests

BASE = "https://api.pff.com"


def hdr():
    k = os.environ.get("PFF_API_KEY", "").strip()
    if not k:
        sys.exit("PFF_API_KEY is not set (repository secret)")
    return {"Authorization": f"Bearer {k}", "Accept": "application/json", "User-Agent": "gridiron-model"}


def openapi():
    for path in ("/openapi.json", "/openapi.yaml", "/v1/openapi.json"):
        r = requests.get(BASE + path, timeout=60, headers={"Accept": "application/json", "User-Agent": "gridiron-model"})
        print(f"GET {path}: HTTP {r.status_code} {r.headers.get('content-type', '')} {len(r.text)} chars")
        if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
            spec = r.json()
            print("title:", spec.get("info", {}).get("title"), "| version:", spec.get("info", {}).get("version"), "| servers:", spec.get("servers"))
            paths = spec.get("paths", {})
            print(len(paths), "paths")
            for p, ops in sorted(paths.items()):
                for m, op in ops.items():
                    if m not in ("get", "post"):
                        continue
                    params = [(x.get("name"), x.get("in")) for x in op.get("parameters", []) if isinstance(x, dict)]
                    print(f"{m.upper():4} {p}  [{op.get('operationId', '')}]  {op.get('summary', '')}")
                    if params:
                        print("       params:", ", ".join(f"{n}({i[0]})" for n, i in params))
            return
        print(r.text[:300])


def call(path, params, rows):
    r = requests.get(BASE + path, params=params, headers=hdr(), timeout=120)
    print(f"GET {path} {params}: HTTP {r.status_code}  ratelimit: limit={r.headers.get('x-ratelimit-limit')} remaining={r.headers.get('x-ratelimit-remaining')} reset={r.headers.get('x-ratelimit-reset')}")
    if r.status_code != 200:
        print(r.text[:600])
        return
    try:
        j = r.json()
    except ValueError:
        print("non-JSON:", r.text[:300])
        return

    def shape(o, depth=0):
        if isinstance(o, dict):
            return {k: shape(v, depth + 1) if depth < 2 else type(v).__name__ for k, v in list(o.items())[:60]}
        if isinstance(o, list):
            return [f"list[{len(o)}]", shape(o[0], depth + 1) if o and depth < 3 else None]
        return type(o).__name__
    print("top-level keys:", list(j) if isinstance(j, dict) else type(j).__name__)
    print("shape:", json.dumps(shape(j), default=str)[:3000])
    tbl = j.get("rows") or next((v for v in (j.values() if isinstance(j, dict) else []) if isinstance(v, list) and v and isinstance(v[0], dict)), None)
    cols = j.get("columns")
    if cols:
        print("columns:", ", ".join(f"{c.get('key')}[{c.get('label')}]" for c in cols))
    if tbl:
        print(f"{len(tbl)} rows; keys of row 0 ({len(tbl[0])}):", ", ".join(tbl[0]))
        for row in tbl[:rows]:
            print(json.dumps(row, default=str)[:1500])
    if isinstance(j, dict) and j.get("updatedAt"):
        print("updatedAt:", j["updatedAt"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["openapi", "whoami", "call"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--rows", type=int, default=1)
    a = ap.parse_args()
    if a.cmd == "openapi":
        openapi()
    elif a.cmd == "whoami":
        call("/v1/whoami", {}, 1)
    else:
        call(a.path, json.loads(a.params), a.rows)

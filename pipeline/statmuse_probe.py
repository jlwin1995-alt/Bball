"""A handful of StatMuse API probes, to see what it returns before any integration  ->  data/log/statmuse_probe/

    STATMUSE_API_KEY=... python -m pipeline.statmuse_probe [--query "..."] [--max 10]

Each question costs one request of a 1,500-request period (4 per second at most), so the default list is short and --max caps it. The raw JSON of
every answer is saved (the key is never written), plus a summary.txt with status, size, top-level keys and the rate-limit headers, so the response
model (answer text vs structured rows), history depth and whether prop lines exist can be judged from the files. Nothing here feeds the model.
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request, urllib.error

BASE = "https://api.statmuse.com/sports/nba/v1/ask"
OUT = "data/log/statmuse_probe"
DEFAULT = [
    "Yaxel Lendeborg stats this season",
    "Jayson Tatum game log 2023-24",
    "Jayson Tatum points per game in 2022-23",
    "Nikola Jokic game log 2019-20",
    "Anthony Black minutes per game when Desmond Bane played vs did not play this season",
    "How many times has Cade Cunningham scored over 24.5 points this season",
    "NBA player prop lines for tonight",
    "Cooper Flagg last 5 games",
]


def ask(q, key):
    req = urllib.request.Request(BASE + "?" + urllib.parse.urlencode({"input": q}), headers={"x-statmuse-api-key": key, "accept": "application/json", "user-agent": "bball-probe"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8", "replace"); hdr = {k.lower(): v for k, v in r.headers.items()}; return r.status, hdr, body
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, {}, f"{type(e).__name__}: {e}"


def keys_of(o, depth=0):
    if isinstance(o, dict):
        return {k: (keys_of(v, depth + 1) if depth < 2 else type(v).__name__) for k, v in list(o.items())[:20]}
    if isinstance(o, list):
        return [f"list[{len(o)}]", keys_of(o[0], depth + 1) if o and depth < 2 else None]
    return type(o).__name__


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", action="append", help="a question to ask (repeatable); default: the built-in probe list")
    ap.add_argument("--max", type=int, default=10, help="most questions to send (each costs one request)")
    a = ap.parse_args()
    key = os.environ.get("STATMUSE_API_KEY", "")
    if not key:
        print("STATMUSE_API_KEY is not set; nothing sent"); return 0
    qs = [q.strip() for q in (a.query or DEFAULT) if q.strip()][: a.max]
    os.makedirs(OUT, exist_ok=True)
    lines = []
    for i, q in enumerate(qs, 1):
        st, hdr, body = ask(q, key)
        rl = {k: v for k, v in hdr.items() if "limit" in k or "remaining" in k or "quota" in k or "retry" in k}
        try:
            j = json.loads(body); shape = keys_of(j)
        except Exception:
            j, shape = None, "not JSON"
        with open(f"{OUT}/q{i:02d}.json", "w") as f:
            json.dump({"question": q, "status": st, "rate_headers": rl, "response": j if j is not None else body[:4000]}, f, indent=1)
        lines.append(f"q{i:02d} [{st}] {len(body):>7} bytes  {q}\n     shape: {json.dumps(shape)[:600]}\n     rate: {rl}")
        print(lines[-1], flush=True)
        time.sleep(0.5)                                              # well under 4 requests a second
    open(f"{OUT}/summary.txt", "w").write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

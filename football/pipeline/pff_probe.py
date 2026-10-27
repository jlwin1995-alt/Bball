"""Read PFF's public developer guide from inside a GitHub Actions run (the dev sandbox cannot reach the host) and print it to the log.

    python -m pipeline.pff_probe [--url https://developer.pff.com/guide/] [--depth 1] [--max-kb 200]

Fetches the start page, then follows same-host links one level and prints the visible text of each page (tags stripped), plus every link found, so the endpoints,
auth scheme and limits can be read from the job log. Does NOT use PFF_API_KEY and writes nothing to the repository.
"""
import argparse, html, re, sys
from urllib.parse import urljoin, urlparse
import requests

UA = {"User-Agent": "Mozilla/5.0 (gridiron-model docs probe)"}


def text_of(h):
    h = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", h)
    h = re.sub(r"(?s)<br\s*/?>|</(p|div|li|tr|h[1-6]|pre|section)>", "\n", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    h = html.unescape(h)
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", h)).strip()


def links_of(h, base):
    out = []
    for m in re.finditer(r'(?is)<a\s[^>]*href="([^"#]+)"', h):
        u = urljoin(base, m.group(1))
        if u not in out:
            out.append(u)
    return out


def main(url, depth, max_kb):
    host = urlparse(url).netloc
    seen, queue, used = set(), [(url, 0)], 0
    while queue and used < max_kb * 1024:
        u, d = queue.pop(0)
        if u in seen:
            continue
        seen.add(u)
        try:
            r = requests.get(u, headers=UA, timeout=30)
        except requests.RequestException as e:
            print(f"::warning::{u}: {e}")
            continue
        print(f"\n===== {u}  (HTTP {r.status_code}, {len(r.text)} chars, {r.headers.get('content-type', '')})")
        if r.status_code != 200:
            continue
        if "json" in r.headers.get("content-type", ""):
            body = r.text[:20000]
        else:
            body = text_of(r.text)
        print(body[: 40 * 1024])
        used += min(len(body), 40 * 1024)
        if d < depth:
            ls = links_of(r.text, u)
            same = [x for x in ls if urlparse(x).netloc == host and not re.search(r"\.(png|jpg|svg|css|js|ico|woff2?)(\?|$)", x)]
            print(f"--- {len(ls)} links ({len(same)} on {host}):")
            for x in same[:80]:
                print("   ", x)
            queue += [(x, d + 1) for x in same[:40]]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://developer.pff.com/guide/")
    ap.add_argument("--depth", type=int, default=1)
    ap.add_argument("--max-kb", type=int, default=200)
    a = ap.parse_args()
    main(a.url, a.depth, a.max_kb)

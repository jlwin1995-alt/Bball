"""PrizePicks fantasy-points lines -> site/data/fp_lines.json (NFL) and site/data/cfb/fp_lines.json (college).

The browser computes the lean: the player's median points under the PrizePicks scoring, turned into a mean-adjusted projection by cfg.mean, against the
line, in units of cfg.sigma. This file only carries the lines matched to projected players. Lines come from the pre-game log (data/log/fp_lines_log.csv,
data/log/cfb_fp_lines_log.csv), which keeps the last line before kickoff for every (event, player, book).
"""
import datetime as dt, json, os
from .fetch_odds import read_rows
from .lines import norm


def build(log_path, projections, out_path, cfg, now=None, keep_hours=6):
    now = now or dt.datetime.now(dt.timezone.utc)
    by_name = {}
    for p in projections:
        by_name.setdefault(norm(p["name"]), []).append(p)
    rows, unmatched = [], set()
    for x in read_rows(log_path):
        ko = dt.datetime.fromisoformat(x["commence"].replace("Z", "+00:00"))
        if (now - ko).total_seconds() > keep_hours * 3600:
            continue
        cands = [p for p in by_name.get(norm(x["player"]), []) if p["team"] in (x["home"], x["away"])]
        if len(cands) != 1:
            unmatched.add(x["player"])
            continue
        p = cands[0]
        try:
            rows.append(dict(id=p["id"], name=p["name"], team=p["team"], pos=p["pos"], game=p.get("game") or x["game"], commence=x["commence"], line=float(x["line"]),
                             over=x.get("over"), under=x.get("under"), book=x["book"]))
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda r: (r["commence"], -r["line"]))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump(dict(updated=now.isoformat(timespec="seconds"), cfg=cfg, n=len(rows), rows=rows, unmatched=sorted(unmatched)[:20]), open(out_path, "w"), separators=(",", ":"))
    return len(rows)


def fit(pairs, min_n=200):
    """pairs: (median projection, actual) in the PrizePicks scoring -> dict(mean=[a, b], sigma=[a, b], n): mean = a + b x median by least squares, then the
    spread of actual around that mean in five equal-count bins, as sigma = a + b x mean. None while there are too few pairs."""
    import math
    n = len(pairs)
    if n < min_n:
        return None
    mx, my = sum(p for p, _ in pairs) / n, sum(a for _, a in pairs) / n
    b1 = sum((p - mx) * (a - my) for p, a in pairs) / sum((p - mx) ** 2 for p, _ in pairs)
    b0 = my - b1 * mx
    pairs = sorted(pairs)
    xs, ys = [], []
    for i in range(5):
        bn = pairs[i * n // 5:(i + 1) * n // 5]
        res = [a - (b0 + b1 * p) for p, a in bn]
        m = sum(res) / len(res)
        ys.append(math.sqrt(sum((r - m) ** 2 for r in res) / max(1, len(res) - 1)))
        xs.append(sum(b0 + b1 * p for p, _ in bn) / len(bn))
    mxs, mys = sum(xs) / 5, sum(ys) / 5
    d = sum((x - mxs) ** 2 for x in xs)
    sb = sum((x - mxs) * (y - mys) for x, y in zip(xs, ys)) / d if d else 0.0
    return dict(mean=[round(b0, 3), round(b1, 3)], sigma=[round(mys - sb * mxs, 3), round(sb, 4)], n=n)

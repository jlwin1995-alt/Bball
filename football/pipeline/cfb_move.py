"""Does the opening line leave an edge the closing line removes?

    python -m pipeline.cfb_move

For every finished FBS-vs-FBS game with an opening and a closing line (CFBD, median across providers) and a walk-forward scores-only model prediction
(pipeline/cfb_spread.py): compare the model with the OPENING line and ask
  1. how much sharper is the close than the open (MAE of each against the result)?
  2. does the line MOVE toward the model (slope of close - open on model - open)?  CLV, in points, for betting the model's side at the open
  3. is the model worth anything against the OPEN (slope of result - open on model - open), and does betting the model's side at the open win?
Margin and total are both tested. 'open' is the first line CFBD recorded; a bettor pulling lines on a Tuesday sees something between open and close.
"""
import argparse, csv, json, math, os
from . import config as C
from . import cfb_spread as S


def load_opens(raw="data/raw"):
    out = {}
    paths = [(C.SEASON, f"{raw}/cfb_game_lines.csv")] + [(y, f"{raw}/cfb_hist/cfb_game_lines_{y}.csv") for y in (C.SEASON - 1, C.SEASON - 2)]
    for y, p in paths:
        if not os.path.exists(p):
            continue
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                g = lambda k: float(r[k]) if r.get(k) not in ("", None) else None
                out[(y, r["id"])] = (g("home_spread"), g("total"), g("open_spread"), g("open_total"))
    return out


def slope(x, y):
    n = len(x)
    sxx = sum(v * v for v in x)
    if n < 10 or not sxx:
        return None, None
    b = sum(a * c for a, c in zip(x, y)) / sxx
    res = [c - b * a for a, c in zip(x, y)]
    se = math.sqrt(sum(v * v for v in res) / (n - 2)) / math.sqrt(sxx)
    return round(b, 3), round(se, 3)


def analyse(rows, which):
    """rows: dict(model, open, close, actual). Returns the numbers for one market."""
    n = len(rows)
    if not n:
        return dict(n=0)
    gap = [r["model"] - r["open"] for r in rows]
    move = [r["close"] - r["open"] for r in rows]
    yo = [r["actual"] - r["open"] for r in rows]
    yc = [r["actual"] - r["close"] for r in rows]
    out = dict(n=n, open_mae=round(sum(abs(v) for v in yo) / n, 3), close_mae=round(sum(abs(v) for v in yc) / n, 3),
               mean_abs_move=round(sum(abs(v) for v in move) / n, 3), gap_sd=round(math.sqrt(sum(v * v for v in gap) / n), 2))
    out["move_on_gap"] = slope(gap, move)
    out["result_on_gap_open"] = slope(gap, yo)
    big = [i for i, g in enumerate(gap) if abs(g) >= 2]
    if big:
        out["clv_pts_gap2+"] = round(sum((1 if gap[i] > 0 else -1) * move[i] for i in big) / len(big), 3)
        out["n_gap2+"] = len(big)
        hits = [(yo[i] > 0) == (gap[i] > 0) for i in big if yo[i] != 0]
        out["bet_open_gap2+"] = dict(n=len(hits), hit=sum(hits), pct=round(sum(hits) / len(hits) * 100, 1))
    allb = [(yo[i] > 0) == (gap[i] > 0) for i in range(n) if yo[i] != 0 and gap[i] != 0]
    out["bet_open_all"] = dict(n=len(allb), hit=sum(allb), pct=round(sum(allb) / len(allb) * 100, 1))
    out["clv_pts_all"] = round(sum((1 if g > 0 else -1) * m for g, m in zip(gap, move)) / n, 3)
    return out


def main(raw="data/raw"):
    games, lines, fbs = S.load_games(raw)
    opens = load_opens(raw)
    res = {}
    for s in sorted(games):
        if s - 1 not in games and s != C.SEASON:
            continue
        mrows, trows = [], []
        for p in S.walk_forward(games, s, C.CFB_SPREAD_LAM, C.CFB_SPREAD_RHO, fbs=fbs):
            if not p["done"] or p["home"] not in fbs or p["away"] not in fbs:
                continue
            o = opens.get((s, p["id"]))
            if not o:
                continue
            sp, tt, osp, ott = o
            if sp is not None and osp is not None:
                mrows.append(dict(model=p["model_margin"], open=-osp, close=-sp, actual=p["hp"] - p["ap"]))
            if tt is not None and ott is not None:
                trows.append(dict(model=p["model_total"], open=ott, close=tt, actual=p["hp"] + p["ap"]))
        res[s] = dict(margin=analyse(mrows, "margin"), total=analyse(trows, "total"))
        print(s, json.dumps(res[s]))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    main(ap.parse_args().raw)

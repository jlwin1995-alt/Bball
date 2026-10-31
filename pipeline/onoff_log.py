"""Fill in the results of the manual with / without comparisons  ->  data/manual/onoff_picks.csv

    python -m pipeline.onoff_log

data/manual/onoff_picks.csv holds one row per posted line we compared against a with / without split (model projection, splits-adjusted projection,
Databallr per-100 implied projection, the model's lean). For every row dated before today with no result yet, the box score is looked up:
actual = the stat (a combo is not used here), hit = the lean won (blank on a push or when no lean was set), void if the player had 0 minutes.
Nothing here feeds the model; it is the record for the Nov 3 / Nov 17 rechecks.
"""
import pandas as pd

PATH = "data/manual/onoff_picks.csv"


def main(path=PATH, games="data/raw/games.csv"):
    P = pd.read_csv(path, dtype={"actual": "float", "hit": "object"})
    G = pd.read_csv(games, dtype={"pid": str})
    today = pd.Timestamp.now("UTC").tz_localize(None).normalize()
    n = 0
    for i, r in P.iterrows():
        if pd.notna(r.actual) or pd.Timestamp(r.date) >= today: continue
        g = G[(G["name"] == r.player) & (G["date"] == r.date) & (G["min"] > 0)]
        if g.empty:
            P.loc[i, "hit"] = "void"; continue
        a = float(g.iloc[0][r.stat]); P.loc[i, "actual"] = a
        if pd.notna(r.lean) and a != r.line: P.loc[i, "hit"] = "1" if (a > r.line) == (r.lean == "O") else "0"
        n += 1
    P.to_csv(path, index=False)
    print(f"onoff_log: graded {n} rows;", P.hit.value_counts().to_dict())


if __name__ == "__main__":
    main()

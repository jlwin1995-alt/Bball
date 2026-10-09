"""Shot quality and shot defense by floor zone, from data/raw/shots.csv.gz (see fetch_shots.py).

Zones from ESPN's court coordinates (feet; rim at x=25, y=0): rim, paint (non-rim, in the lane), mid-range, corner three,
above-the-break three. "Expected" = league FG% in that zone, so shot quality here is LOCATION + TYPE ONLY. ESPN publishes no
defender distance, so open vs contested cannot be measured.
"""
import numpy as np
import pandas as pd

ZONES = ["rim", "paint", "mid", "corner3", "arc3"]
ZLABEL = {"rim": "Rim", "paint": "Paint", "mid": "Mid-range", "corner3": "Corner 3", "arc3": "Above-break 3"}


def add_zone(s):
    """Adds dist and zone columns. Heaves beyond 40 feet are dropped (no signal, huge variance)."""
    s = s.copy()
    s["dist"] = np.hypot(s["x"] - 25, s["y"])
    s = s[s["dist"] <= 40].copy()
    three = s["three"] == 1
    corner = three & (s["y"] <= 14)
    paint = (~three) & (s["dist"] >= 4) & ((s["x"] - 25).abs() <= 8) & (s["y"] <= 19)
    s["zone"] = np.select([three & corner, three, (~three) & (s["dist"] < 4), paint], ["corner3", "arc3", "rim", "paint"], "mid")
    return s


def league_fg(s):
    """League FG% and points per shot by zone."""
    g = s.groupby("zone").agg(fga=("made", "size"), fgm=("made", "sum"), three=("three", "mean"))
    g["fg"] = g["fgm"] / g["fga"]
    g["pps"] = g["fg"] * np.where(g["three"] > 0.5, 3, 2)
    return g


def _team_zone(s, k=300.0):
    """Per defence and zone: share of the FGA it faces, FG% allowed and points per shot allowed vs league (shrunk by k shots)."""
    lg = s.groupby("zone").agg(n=("made", "size"), m=("made", "sum"), p=("pts", "sum"))
    lg_share, lg_fg, lg_pps = lg["n"] / lg["n"].sum(), lg["m"] / lg["n"], lg["p"] / lg["n"]
    t = s.groupby(["opp", "zone"]).agg(n=("made", "size"), m=("made", "sum"), p=("pts", "sum"))
    tot = t.groupby("opp")["n"].sum()
    out = {}
    for (team, z), r in t.iterrows():
        out[(team, z)] = {"share": r["n"] / tot[team] / lg_share[z] - 1,                       # + = faces more shots from here than average
                          "fg": (r["m"] + k * lg_fg[z]) / (r["n"] + k) - lg_fg[z],              # FG% allowed minus league (points of FG%)
                          "pps": ((r["p"] + k * lg_pps[z]) / (r["n"] + k)) / lg_pps[z] - 1, "n": r["n"]}
    return out


def team_defense(s):
    """Rows per team: for each zone, freq (% above/below league share of shots faced) and fg (FG% allowed minus league, in points).
    Also split-half reliability (odd vs even game days) of each. Display only: see module docs / Methodology for the projection test."""
    s = s.copy()
    s["pts"] = s["made"] * np.where(s["three"] == 1, 3, 2)
    n = s.groupby("opp")["event"].nunique()
    s = s[s["opp"].isin(n[n >= 0.5 * n.max()].index)]
    full = _team_zone(s)
    rows = {}
    for (team, z), v in full.items():
        r = rows.setdefault(team, {"team": team})
        r[f"{z}_freq"] = round(v["share"] * 100, 1)
        r[f"{z}_fg"] = round(v["fg"] * 100, 1)
    days = {d: i for i, d in enumerate(sorted(s["date"].unique()))}
    h = s["date"].map(days) % 2
    a, b = _team_zone(s[h == 0]), _team_zone(s[h == 1])
    rel = {}
    for z in ZONES:
        for key, nm in (("share", "freq"), ("fg", "fg")):
            ks = [k for k in a if k in b and k[1] == z]
            rel[f"{z}_{nm}"] = round(float(np.corrcoef([a[k][key] for k in ks], [b[k][key] for k in ks])[0, 1]), 2)
    return sorted(rows.values(), key=lambda r: r["team"]), rel


def player_profiles(s, names, min_shots=100):
    """Per player: zone mix, assisted share, expected points per shot from his locations (league FG% by zone), actual points per shot
    and the gap between them (shot-making). names: DataFrame pid, name, team, pos."""
    s = s.copy()
    s["pts"] = s["made"] * np.where(s["three"] == 1, 3, 2)
    lg = s.groupby("zone").agg(n=("made", "size"), p=("pts", "sum"))
    lg_pps = lg["p"] / lg["n"]
    s["xp"] = s["zone"].map(lg_pps)
    g = s.groupby("pid")
    base = g.agg(n=("made", "size"), pts=("pts", "sum"), xp=("xp", "sum"), ast=("assisted", "mean"), three=("three", "mean"))
    base = base[base["n"] >= min_shots]
    mix = s.groupby(["pid", "zone"]).size().unstack(fill_value=0).reindex(columns=ZONES, fill_value=0)
    mix = mix.div(mix.sum(axis=1), axis=0)
    fgz = s.groupby(["pid", "zone"])["made"].mean().unstack().reindex(columns=ZONES)
    nm = names.drop_duplicates("pid").set_index("pid")
    rows = []
    for pid, r in base.iterrows():
        if pid not in nm.index:
            continue
        row = {"pid": pid, "name": nm.loc[pid, "name"], "team": nm.loc[pid, "team"], "pos": nm.loc[pid, "pos"], "n": int(r["n"]),
               "xpps": round(r["xp"] / r["n"], 3), "pps": round(r["pts"] / r["n"], 3), "make": round((r["pts"] - r["xp"]) / r["n"], 3),
               "ast_pct": round(r["ast"] * 100, 0)}
        for z in ZONES:
            row[f"{z}_mix"] = round(float(mix.loc[pid, z]) * 100, 0)
            v = fgz.loc[pid, z]
            row[f"{z}_fg"] = None if pd.isna(v) else round(float(v) * 100, 1)
        rows.append(row)
    return sorted(rows, key=lambda r: -r["n"]), {z: round(float(v), 3) for z, v in (lg["p"] / lg["n"]).items()}


def split_half_player_skill(s, min_shots=150):
    """Reliability of 'shot-making' (points per shot minus location-expected) across odd/even game days, per player."""
    s = s.copy()
    s["pts"] = s["made"] * np.where(s["three"] == 1, 3, 2)
    s["xp"] = s["zone"].map(s.groupby("zone")["pts"].mean())
    days = {d: i for i, d in enumerate(sorted(s["date"].unique()))}
    s["h"] = s["date"].map(days) % 2
    t = s.groupby(["pid", "h"]).agg(n=("pts", "size"), r=("pts", "sum"), x=("xp", "sum")).unstack()
    t = t[(t["n"] >= min_shots / 2).all(axis=1)]
    a = (t["r"][0] - t["x"][0]) / t["n"][0]
    b = (t["r"][1] - t["x"][1]) / t["n"][1]
    return round(float(np.corrcoef(a, b)[0, 1]), 2), int(len(t))


# --- shot chart grids (display only) -------------------------------------------------------------------------------
CELL = 2.5                     # feet per square cell
GX, GY0, GY1 = 20, -5.0, 40.0  # 20 columns across 50 ft; rows from y=-5 (behind the rim) to y=40
GROWS = int((GY1 - GY0) / CELL)


def _cell(s):
    col = np.clip((s["x"] // CELL).astype(int), 0, GX - 1)
    row = np.clip(((s["y"] - GY0) // CELL).astype(int), 0, GROWS - 1)
    return row * GX + col


def defense_grids(s):
    """Per defence, FGA and FGM allowed in each CELL-ft square, flattened (index = row*GX + col, row 0 = behind the rim), plus the
    league's. The browser shrinks and colours them, so the smoothing can change without a rebuild."""
    s = s.copy()
    s["c"] = _cell(s)
    n = s.groupby("opp")["event"].nunique()
    s = s[s["opp"].isin(n[n >= 0.5 * n.max()].index)]
    size = GX * GROWS
    def arr(d):
        a = np.bincount(d["c"], minlength=size)
        m = np.bincount(d["c"], weights=d["made"], minlength=size).astype(int)
        return a.tolist(), m.tolist()
    teams = {t: dict(zip(("n", "m"), arr(d))) for t, d in s.groupby("opp")}
    ln, lm = arr(s)
    return {"cell": CELL, "cols": GX, "rows": GROWS, "y0": GY0, "teams": teams, "lg": {"n": ln, "m": lm}}


def player_shots(s, pids):
    """Compact per-player shot list [x, y, made, x, y, made, ...] for the overlay (lazy-loaded by the browser)."""
    out = {}
    for pid, d in s[s["pid"].isin(pids)].groupby("pid"):
        out[pid] = np.column_stack([d["x"].round().astype(int), d["y"].round().astype(int), d["made"].astype(int)]).ravel().tolist()
    return out

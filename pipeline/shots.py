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

"""Kickoff weather. Wind is the only variable that survived measurement (temperature is not monotonic; rain vanishes once wind is held).

Three sources, in order of preference:
  recorded  nflverse already has temp/wind for the game (it backfills after kickoff) - for a played game this is the truth
  forecast  Open-Meteo at the kickoff hour. Free, no key.
  -         indoor, unknown stadium, or the fetch failed -> multipliers of 1.000. Weather never gets to take a projection down with it.
"""
import json, os
import requests
from . import config as C
from .model import num, wx_factors, wx_indoor
from .slate import week_games, game_label


def stadium_id(r):
    return C.STADIUM_BY_NAME.get(r.get("stadium", "")) or r.get("stadium_id", "")


def fetch_forecast(games):
    """Fill forecast fields on the games handed in (in place). One request for every stadium: Open-Meteo takes comma-separated coordinates."""
    lats = [C.STADIUMS[g["sid"]][0] for g in games]
    lons = [C.STADIUMS[g["sid"]][1] for g in games]
    days = sorted(g["day"] for g in games)
    url = (f"{C.OPEN_METEO}?latitude={','.join(map(str, lats))}&longitude={','.join(map(str, lons))}"
           f"&start_date={days[0]}&end_date={days[-1]}"
           "&hourly=temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation_probability,precipitation"
           "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=America%2FNew_York")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    parsed = r.json()
    locs = parsed if isinstance(parsed, list) else [parsed]
    if len(locs) != len(games):
        raise RuntimeError(f"weather API returned {len(locs)} locations for {len(games)} games")
    for g, loc in zip(games, locs):
        h = (loc or {}).get("hourly")
        if not h or "time" not in h:
            continue
        key = f"{g['day']}T{g['time'][:2]}:00"
        if key not in h["time"]:
            continue
        k = h["time"].index(key)
        g["temp"], g["wind"], g["gust"] = h["temperature_2m"][k], h["wind_speed_10m"][k], h["wind_gusts_10m"][k]
        g["precip"] = h["precipitation_probability"][k]
        mm = [v for v in h["precipitation"][k:k + 4] if v is not None]
        g["rain"] = round(sum(mm), 2) if mm else ""
        g["src"] = "forecast"


def week_weather(sched, week, P, overrides=None, fetch=True):
    """-> (byTeam factors, rows for the Weather tab). A failure anywhere degrades to multipliers of 1.000."""
    overrides = overrides or {}
    games = []
    for r in week_games(sched, week):
        sid = stadium_id(r)
        games.append(dict(away=r["away_team"], home=r["home_team"], label=game_label(r["away_team"], r["home_team"]),
                          stadium=r.get("stadium", ""), sid=sid, roof=r.get("roof", ""), indoor=wx_indoor(r.get("roof", "")),
                          day=r.get("gameday", ""), time=r.get("gametime", ""),
                          temp=r.get("temp", ""), wind=r.get("wind", ""), gust="", precip="", rain="", src=""))
    need = [g for g in games if not g["indoor"] and g["wind"] in ("", "NA") and g["sid"] in C.STADIUMS and g["day"] and g["time"]]
    if P["WEATHER_ON"] and need and fetch:
        try:
            fetch_forecast(need)
        except Exception as e:                     # one dead API call must not cost the user their projections
            print(f"::warning::weather fetch failed, continuing without it: {e}")
    by_team, rows = {}, []
    for g in games:
        if g["wind"] not in ("", "NA") and not g["src"]:
            g["src"] = "recorded"
        used = overrides.get(g["label"], g["wind"])
        f = wx_factors(used, g["indoor"], P)
        by_team[g["away"]] = by_team[g["home"]] = f
        n = lambda v: None if v in ("", "NA", None) else num(v)
        rows.append(dict(game=g["label"], stadium=g["stadium"], roof="indoor" if g["indoor"] else (g["roof"] or "outdoors"),
                         day=g["day"], time=g["time"], temp=n(g["temp"]), wind=n(g["wind"]), gust=n(g["gust"]), precip=n(g["precip"]),
                         rain=n(g["rain"]), ovr=overrides.get(g["label"]), src="indoor" if g["indoor"] else (g["src"] or "unknown"),
                         yds=round(f["yds"], 3), rec=round(f["rec"], 3), rush=round(f["rush"], 3)))
    rows.sort(key=lambda x: x["yds"])                # roughest game first
    return by_team, rows


def load_overrides(path="data/wind_overrides.json"):
    """Optional {"BUF @ MIA": 22} file: force a wind reading you trust more than the forecast."""
    try:
        return json.load(open(path)) if os.path.exists(path) else {}
    except Exception:
        return {}

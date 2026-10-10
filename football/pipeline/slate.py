"""Schedule helpers: which week to project, who plays whom, kickoffs, injury designations."""
import csv
from . import config as C
from .model import num, wx_factors, wx_indoor


def load_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def target_week(sched, want="auto"):
    """First week that still has an unplayed game (empty `result`), unless a week is forced."""
    if want not in (None, "", "auto"):
        return int(want)
    wk = None
    for r in sched:
        if r.get("game_type", "REG") != "REG":
            continue
        if r["result"] in ("", "NA"):
            w = int(num(r["week"]))
            if wk is None or w < wk:
                wk = w
    return wk


def week_games(sched, week):
    return [r for r in sched if int(num(r["week"])) == week and r.get("game_type", "REG") == "REG"]


def matchups(sched, week):
    m = {}
    for r in week_games(sched, week):
        away, home = r["away_team"], r["home_team"]
        m[away] = dict(opp=home, site="@", rest=num(r["away_rest"]))
        m[home] = dict(opp=away, site="vs", rest=num(r["home_rest"]))
    return m


def recorded_wx(sched, week, P):
    """Played games: nflverse has the wind that actually blew. Returns team -> factors."""
    wx = {}
    for r in week_games(sched, week):
        f = wx_factors(r.get("wind", ""), wx_indoor(r.get("roof", "")), P)
        wx[r["away_team"]] = f
        wx[r["home_team"]] = f
    return wx


def game_label(away, home, neutral=False):
    return f"{away.replace(chr(39), '')}{' vs ' if neutral else ' @ '}{home.replace(chr(39), '')}"


def kickoffs(sched, week):
    out = {}
    for r in week_games(sched, week):
        k = C.kickoff(r["gameday"], r["gametime"])
        if k:
            out[r["away_team"]] = out[r["home_team"]] = k
    return out


def statuses(injuries, week):
    """gsis_id -> report_status for the week being projected."""
    out = {}
    for r in injuries:
        if int(num(r.get("week"))) == week and r.get("gsis_id") and r.get("report_status"):
            out[r["gsis_id"]] = r["report_status"]
    return out


def history_gaps(rows, sched, week):
    """Games in weeks BEFORE `week` whose box scores are missing from the stats file.

    nflverse updates the schedule's `result` before the player-stats release catches up, so on a Tuesday morning the target week can
    already have flipped while Monday night's players are still missing. A projection built then is built on incomplete history,
    and because the log is never rewritten it would be frozen that way. Returns "AWAY @ HOME (wk N)" labels; empty = complete.
    """
    seen = set()
    for r in rows:
        if r["carries"] + r["targets"] + r["attempts"] > 0:
            seen.add((r["team"], int(r["week"])))
    gaps = []
    for g in sched:
        w = int(num(g["week"]))
        if g.get("game_type", "REG") != "REG" or w >= week:
            continue
        if (g["away_team"], w) not in seen or (g["home_team"], w) not in seen:
            gaps.append(f"{g['away_team']} @ {g['home_team']} (wk {w})")
    return gaps

"""Team comparison for the Game Boards: per-game offence and defence (what a team gains and what it allows), with league rank.

Built from the same box scores the model uses, so there is nothing new to fetch:
  NFL  player rows summed to team-games; points from the schedule. Net passing yards = passing yards - sack yards (the way team totals are quoted).
       First downs = passing + rushing (receiving first downs are the same plays as passing ones).
  CFB  player rows summed to team-games; points from CFBD's games. College rushing already has sacks subtracted (the NCAA books a sack as a
       rush), so rushing + passing is the usual college total yards.
Per-game averages over COMPLETED games only. A stat the feed does not carry (third / fourth down, red zone, college first downs) is left out, not guessed.
"""
from .model import rnd

# key -> (label, higher_is_better, decimals).  "allowed" stats are better when LOWER.
ROWS = [("ppg", "Points per game", True, 1), ("papg", "Points allowed per game", False, 1),
        ("ypg", "Total yards", True, 1), ("ypg_a", "Total yards allowed", False, 1),
        ("pass", "Passing yards", True, 1), ("pass_a", "Passing yards allowed", False, 1),
        ("rush", "Rushing yards", True, 1), ("rush_a", "Rushing yards allowed", False, 1),
        ("to", "Turnovers", False, 1), ("ta", "Takeaways", True, 1),
        ("fd", "First downs", True, 1), ("fd_a", "First downs allowed", False, 1)]


def build(team_games, keep=None):
    """team_games: list of dict(team, opp, pts, pts_a, pass_y, rush_y, to, fd or None). -> {team: stats + ranks}"""
    by = {}
    for g in team_games:
        by.setdefault(g["team"], []).append(g)
    opp_of = {}
    for g in team_games:
        opp_of[(g["team"], g["key"])] = g
    out = {}
    for t, gs in by.items():
        n = len(gs)
        # what the OPPONENT did in each of this team's games is what this team allowed / took away
        theirs = [opp_of.get((g["opp"], g["key"])) for g in gs]
        theirs = [x for x in theirs if x]
        m = lambda xs, k: sum(x[k] for x in xs) / len(xs) if xs else None
        fd = m(gs, "fd") if all(g["fd"] is not None for g in gs) else None
        fd_a = m(theirs, "fd") if theirs and all(x["fd"] is not None for x in theirs) else None
        out[t] = dict(g=n, ppg=m(gs, "pts"), papg=m(theirs, "pts"), ypg=m(gs, "pass_y") + m(gs, "rush_y") if gs else None,
                      ypg_a=(m(theirs, "pass_y") + m(theirs, "rush_y")) if theirs else None, pass_=m(gs, "pass_y"), pass_a=m(theirs, "pass_y"),
                      rush=m(gs, "rush_y"), rush_a=m(theirs, "rush_y"), to=m(gs, "to"), ta=m(theirs, "to"), fd=fd, fd_a=fd_a)
    out = {t: {("pass" if k == "pass_" else k): v for k, v in s.items()} for t, s in out.items() if keep is None or t in keep}
    # rank 1 = best in the league on that stat (highest for gains, lowest for allowed / turnovers)
    for key, _, higher, _ in ROWS:
        have = [(t, s[key]) for t, s in out.items() if s.get(key) is not None]
        have.sort(key=lambda x: -x[1] if higher else x[1])
        for i, (t, _) in enumerate(have):
            out[t][key + "_rk"] = i + 1
    for s in out.values():
        for k, v in list(s.items()):
            if isinstance(v, float):
                s[k] = rnd(v, 2)
    return dict(rows=[dict(k=k, label=l, higher=h, dp=d) for k, l, h, d in ROWS if any(s.get(k) is not None for s in out.values())], teams=out, n=len(out))


def nfl_team_games(rows, sched):
    """rows: weekly player rows (model.load_weekly). sched: schedule rows. Completed games only."""
    from .model import num
    played = {}
    for g in sched:
        if g.get("game_type", "REG") == "REG" and g["result"] not in ("", "NA"):
            w = int(num(g["week"]))
            played[(g["away_team"], w)] = (num(g["away_score"]), num(g["home_score"]), g["home_team"])
            played[(g["home_team"], w)] = (num(g["home_score"]), num(g["away_score"]), g["away_team"])
    agg = {}
    for r in rows:
        k = (r["team"], int(r["week"]))
        if k not in played:
            continue
        a = agg.setdefault(k, dict(pass_y=0.0, rush_y=0.0, to=0.0, fd=0.0))
        a["pass_y"] += r["passing_yards"] - r["sack_yards_lost"]
        a["rush_y"] += r["rushing_yards"]
        a["to"] += r["passing_interceptions"] + r["rushing_fumbles_lost"] + r["receiving_fumbles_lost"] + r["sack_fumbles_lost"]
        a["fd"] += r.get("passing_first_downs", 0.0) + r.get("rushing_first_downs", 0.0)
    out = []
    for (t, w), a in agg.items():
        pts, pts_a, opp = played[(t, w)]
        if (opp, w) not in agg:
            continue                                                  # the other side is not in the box scores yet
        out.append(dict(team=t, opp=opp, key=w, pts=pts, pts_a=pts_a, **a))
    return out


FBS_CONFERENCES = {"Big Ten", "ACC", "Big 12", "SEC", "American Athletic", "Sun Belt", "Mid-American", "Mountain West", "Conference USA", "Pac-12", "FBS Independents"}


def fbs_teams(games):
    """Teams in an FBS conference. FCS opponents stay in the numbers (a team's real record includes them) but are not ranked."""
    t = set()
    for g in games:
        if g["homeConference"] in FBS_CONFERENCES:
            t.add(g["homeTeam"])
        if g["awayConference"] in FBS_CONFERENCES:
            t.add(g["awayTeam"])
    return t


def cfb_team_games(rows, games):
    """rows: college weekly rows (cfb_model.load_rows). games: cfb_games.csv rows. Completed games only."""
    done = {}
    for g in games:
        if str(g["completed"]).lower() == "true" and g["homePoints"] not in ("", None) and g["awayPoints"] not in ("", None):
            w = int(float(g["week"]))
            done[(g["homeTeam"], w)] = (float(g["homePoints"]), float(g["awayPoints"]), g["awayTeam"])
            done[(g["awayTeam"], w)] = (float(g["awayPoints"]), float(g["homePoints"]), g["homeTeam"])
    agg = {}
    for r in rows:
        k = (r["team"], int(r["week"]))
        if k not in done:
            continue
        a = agg.setdefault(k, dict(pass_y=0.0, rush_y=0.0, to=0.0, fd=None))
        a["pass_y"] += r["passing_yards"]
        a["rush_y"] += r["rushing_yards"]
        a["to"] += r["interceptions"] + r["fumbles_lost"]
    out = []
    for (t, w), a in agg.items():
        pts, pts_a, opp = done[(t, w)]
        if (opp, w) not in agg:
            continue          # FBS vs FCS: the FCS side is not in the FBS-only box scores, so those games would credit nothing to the defence
        out.append(dict(team=t, opp=opp, key=w, pts=pts, pts_a=pts_a, **a))
    return out

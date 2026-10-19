"""Offline checks that need no network and no key:  python -m pipeline.selftest

1. The Odds API response parser, on a stub shaped like the documented payload (the live API is not reachable from the dev sandbox).
2. Name matching: a shared name across two teams must never land one team's price on another team's player.
3. Consensus maths: de-vigged probability, median line snapped to a posted line, DFS books kept out of the consensus.
"""
import json, os, tempfile
from . import config as C, fetch_odds, lines


def stub(ev_id="e1", away="Buffalo Bills", home="Los Angeles Rams"):
    ev = dict(id=ev_id, away_team=away, home_team=home, commence_time="2026-10-11T17:00:00Z")
    def mk(key, outs):
        return dict(key=key, outcomes=[o for who, pt, ov, un in outs for o in (
            dict(name="Over", description=who, price=ov, point=pt), dict(name="Under", description=who, price=un, point=pt))])
    odds = dict(bookmakers=[
        dict(key="draftkings", markets=[mk("player_pass_yds", [("Josh Allen", 249.5, -115, -105)]), mk("player_sacks", [("Josh Allen", 1.5, 120, -150)])]),
        dict(key="fanduel", markets=[mk("player_pass_yds", [("Josh Allen", 249.5, -110, -110)])]),
        dict(key="betmgm", markets=[mk("player_pass_yds", [("Josh Allen", 251.5, -110, -110)])]),
        dict(key="prizepicks", markets=[mk("player_pass_yds", [("Josh Allen", 245.5, -119, -119)])]),
        # a shared name: this book posted two different lines for "Josh Allen" -> must be dropped, not guessed
        dict(key="betrivers", markets=[dict(key="player_pass_yds", outcomes=[
            dict(name="Over", description="Josh Allen", price=-110, point=249.5), dict(name="Under", description="Josh Allen", price=-110, point=249.5),
            dict(name="Over", description="Josh Allen", price=-110, point=0.5), dict(name="Under", description="Josh Allen", price=-110, point=0.5)])]),
    ])
    return ev, odds


def main():
    ev, odds = stub()
    rows = fetch_odds.parse_event(ev, odds, "2026-10-10T12:00:00+00:00")
    assert not [r for r in rows if r["book"] == "betrivers"], "a conflicting shared-name book must be dropped"
    assert {r["book"] for r in rows} == {"draftkings", "fanduel", "betmgm", "prizepicks"}, {r["book"] for r in rows}
    assert all(r["game"] == "BUF @ LA" for r in rows), rows[0]["game"]

    players = [dict(id="A", name="Josh Allen", team="BUF", pos="QB", att=32.1),
               dict(id="B", name="Josh Allen", team="JAX", pos="LB", att=0.0),          # the other Josh Allen is not in this game
               dict(id="C", name="Puka Nacua", team="LA", pos="WR", att=0.0)]
    res = lines.build_lines(rows, players)
    by = {(r["name"], r["stat"]): r for r in res["rows"]}
    pass_y = by[("Josh Allen", "passY")]
    assert pass_y["id"] == "A" and pass_y["team"] == "BUF"
    c = pass_y["cons"]
    assert c["line"] == 249.5 and c["n"] == 2 and c["n_books"] == 3 and (c["lo"], c["hi"]) == (249.5, 251.5), c   # median snapped to a posted line
    assert pass_y["dfs"] == {"prizepicks": 245.5}, pass_y["dfs"]                                                     # DFS stays out of the consensus
    # de-vigged: DK -115/-105 -> 0.5130, FD -110/-110 -> 0.5; consensus is their mean
    want = (lines.devig_over(-115, -105) + 0.5) / 2
    assert abs(c["p_over"] - round(want, 4)) < 1e-9, (c["p_over"], want)
    assert ("Josh Allen", "sacks") in by and by[("Josh Allen", "sacks")]["id"] == "A"
    assert fair_ok(lines.fair_american(0.6)) and lines.fair_american(0.4) == 150
    with tempfile.TemporaryDirectory() as d:
        log = os.path.join(d, "lines_log.csv")
        import datetime as dt
        before = dt.datetime(2026, 10, 10, 12, 0, tzinfo=dt.timezone.utc)
        assert lines.snapshot_pregame(res, log=log, now=before) == len(res["rows"])
        later = dt.datetime(2026, 10, 11, 18, 0, tzinfo=dt.timezone.utc)
        assert lines.snapshot_pregame(res, log=log, now=later) == 0                                                # started: frozen, not rewritten
    cfb_checks()
    cfb_lines_checks()
    print("selftest ok:", len(rows), "rows,", len(res["rows"]), "lines")


def cfb_stub():
    """A /games/players payload shaped like the documented response (game -> teams -> categories -> types -> athletes)."""
    def cat(name, **types):
        return dict(name=name, types=[dict(name=k, athletes=[dict(id=i, name=n, stat=v) for i, n, v in vs]) for k, vs in types.items()])
    home = dict(team="Ohio State", conference="Big Ten", homeAway="home", categories=[
        cat("passing", **{"C/ATT": [("1", "QB One", "27/41")], "YDS": [("1", "QB One", "310")], "TD": [("1", "QB One", "3")], "INT": [("1", "QB One", "1")]}),
        cat("rushing", **{"CAR": [("2", "RB Two", "18"), ("1", "QB One", "4")], "YDS": [("2", "RB Two", "96"), ("1", "QB One", "-3")], "TD": [("2", "RB Two", "1")]}),
        cat("receiving", **{"REC": [("3", "WR Three", "7")], "YDS": [("3", "WR Three", "121")], "TD": [("3", "WR Three", "2")]}),
        cat("fumbles", **{"LOST": [("2", "RB Two", "1")]}),
        cat("defensive", **{"TOT": [("9", "LB Nine", "11")]}),
    ])
    away = dict(team="Michigan", conference="Big Ten", homeAway="away", categories=[cat("rushing", **{"CAR": [("7", "RB Seven", "10")], "YDS": [("7", "RB Seven", "40")]})])
    return [dict(id=1, teams=[home, away])]


def cfb_checks():
    from . import cfb_data
    rows = cfb_data.flatten_week(cfb_stub(), 3, {"1": "QB"})
    by = {r["playerId"]: r for r in rows}
    assert set(by) == {"1", "2", "3", "7"}, set(by)                    # the linebacker (defence only) is dropped
    q = by["1"]
    assert (q["completions"], q["attempts"], q["passing_yards"], q["passing_tds"], q["interceptions"]) == (27, 41, 310, 3, 1), q
    assert (q["carries"], q["rushing_yards"]) == (4, -3) and q["position"] == "QB" and q["opponent"] == "Michigan" and q["home"] is True
    assert by["2"]["fumbles_lost"] == 1 and by["3"]["receiving_yards"] == 121 and by["7"]["opponent"] == "Ohio State" and by["7"]["home"] is False
    print("college parser ok")


def cfb_lines_checks():
    from . import cfb_lines as L
    names = ["Texas", "Texas A&M", "Washington", "Washington State", "Miami", "Miami (OH)", "San José State"]
    got = {n: L.resolve(n, names) for n in ("Texas A&M Aggies", "Texas Longhorns", "Washington State Cougars", "Washington Huskies", "Miami (OH) RedHawks", "Miami Hurricanes", "San Jose State Spartans")}
    assert list(got.values()) == ["Texas A&M", "Texas", "Washington State", "Washington", "Miami (OH)", "Miami", "San José State"], got
    ev = [dict(id="1", commence_time="2026-10-17T16:00:00Z", home_team="Texas Longhorns", away_team="Ohio State Buckeyes", bookmakers=[
        dict(key="a", markets=[dict(key="spreads", outcomes=[dict(name="Texas Longhorns", point=-3.5)]), dict(key="totals", outcomes=[dict(name="Over", point=55.5)])]),
        dict(key="b", markets=[dict(key="spreads", outcomes=[dict(name="Texas Longhorns", point=-4.5)]), dict(key="totals", outcomes=[dict(name="Over", point=56.5)])])])]
    lines = fetch_odds.parse_game_lines(ev)
    assert lines[0]["home_spread"] == -4.0 and lines[0]["total"] == 56.0
    games = [dict(home="Ohio State", away="Texas", ko="2026-10-17T16:00:00Z")]       # neutral site: CFBD calls the other team "home"
    assert L.attach(games, lines) == [] and games[0]["spread"] == -4.0 and games[0]["away_imp"] > games[0]["home_imp"], games
    print("college lines ok")
    cfb_props_checks()
    depth_checks()
    totals_checks()
    spread_checks()
    fp_lean_checks()
    partial_checks()
    fp_checks()


def fp_checks():
    import datetime as dt, tempfile
    ev = dict(id="f1", commence_time="2099-10-20T00:20:00Z", home_team="Green Bay Packers", away_team="Dallas Cowboys")
    odds = dict(bookmakers=[dict(key="prizepicks", markets=[dict(key="player_fantasy_points", outcomes=[
        dict(name="Over", description="Jordan Love", point=19.5, price=-119), dict(name="Under", description="Jordan Love", point=19.5, price=-119)])]),
        dict(key="underdog", markets=[dict(key="player_fantasy_points", outcomes=[dict(name="Over", description="Jordan Love", point=20.5, price=-110)])])])
    rows = [x for x in fetch_odds.parse_event(ev, odds, "2026-10-18T22:00:00", markets=fetch_odds.FP_SPEC) if x["book"] == C.FP_BOOK]
    assert len(rows) == 1 and rows[0]["stat"] == "fp" and rows[0]["line"] == 19.5, rows
    assert fetch_odds.parse_event(ev, odds, "t") == [], "the fantasy market must not leak into the prop rows"
    p = tempfile.mkdtemp() + "/fp.csv"
    assert fetch_odds.snapshot_fp(rows, dt.datetime(2026, 10, 18, tzinfo=dt.timezone.utc), p) == 1
    rows[0]["line"] = 20.5
    assert fetch_odds.snapshot_fp(rows, dt.datetime(2026, 10, 18, tzinfo=dt.timezone.utc), p) == 1 and len(fetch_odds.read_rows(p)) == 1
    assert fetch_odds.snapshot_fp(rows, dt.datetime(2099, 10, 21, tzinfo=dt.timezone.utc), p) == 0                     # started: untouched
    print("fantasy-points log ok")


def partial_checks():
    import csv, tempfile
    from .analysis import partial_games
    d = tempfile.mkdtemp(); p = d + "/snaps.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["season", "week", "player", "team", "position", "offense_snaps", "offense_pct"])
        for wk, pct, n in [(1, 0.8, 60), (2, 0.8, 58), (3, 0.7, 50), (4, 0.2, 14)]:
            w.writerow([2026, wk, "Some Back", "XXX", "RB", n, pct])
        for wk, pct, n in [(1, 0.8, 60), (2, 0.8, 58), (3, 0.7, 50), (4, 0.7, 50)]:
            w.writerow([2026, wk, "Steady Back", "XXX", "RB", n, pct])
        for wk, pct, n in [(1, 1.0, 70), (2, 1.0, 70), (3, 1.0, 70), (4, 0.0, 0)]:
            w.writerow([2026, wk, "Some Tackle", "XXX", "T", n, pct])
    rows = [dict(player_display_name=n, team="XXX", week=4, player_id=i) for n, i in (("Some Back", "a"), ("Steady Back", "b"), ("Some Tackle", "c"))]
    pb = d + "/pbp.csv"
    with open(pb, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["week", "posteam", "qtr", "passer_player_id", "rusher_player_id", "receiver_player_id"])
        w.writerow([4, "XXX", 1, "", "a", ""]); w.writerow([4, "XXX", 2, "", "a", ""]); w.writerow([4, "XXX", 4, "", "b", ""])
        for q in [1, 2] * 7:                      # plays with no skill player listed still count toward the team's first-half snaps
            w.writerow([4, "XXX", q, "", "", ""])
    got = partial_games(p, rows, pbp_path=pb)
    assert list(got) == [("a", 4)] and got[("a", 4)]["pct"] == 0.2 and got[("a", 4)]["last_q"] == 2 and got[("a", 4)]["void"] == "likely" and got[("a", 4)]["team_h1"] == 16, got
    print("partial games ok")


def fp_lean_checks():
    import random, tempfile
    from . import fp
    random.seed(3)
    pairs = []
    for _ in range(600):
        med = random.uniform(4, 22)
        mean = 2.0 + 0.9 * med
        pairs.append((med, mean + random.gauss(0, 4.0 + 0.25 * mean)))
    f = fp.fit(pairs)
    assert f and abs(f["mean"][1] - 0.9) < 0.12 and f["sigma"][1] > 0.05 and f["n"] == 600, f
    assert fp.fit(pairs[:50]) is None
    d = tempfile.mkdtemp()
    log = d + "/fp.csv"
    fetch_odds.write_rows  # noqa: B018 (module imported above)
    import csv as _csv
    with open(log, "w", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=fetch_odds.FP_COLS); w.writeheader()
        w.writerow(dict(ts="t", event="e", commence="2099-01-01T00:00:00Z", game="A @ B", home="B", away="A", player="Dak Prescott", book="prizepicks", line="19", over="-137", under="-137"))
        w.writerow(dict(ts="t", event="e", commence="2099-01-01T00:00:00Z", game="A @ B", home="B", away="A", player="Dak Prescott", book="prizepicks", line="19", over="-137", under="-137"))
    n = fp.build(log, [dict(id="1", name="Dak Prescott", team="B", pos="QB", game="A @ B"), dict(id="2", name="Dak Prescott", team="Z", pos="QB")], d + "/o.json", dict(mean=[2, 0.9], sigma=[4, 0.25]))
    assert n == 2 and json.load(open(d + "/o.json"))["rows"][0]["id"] == "1", n      # matched by name AND a team in the game
    print("fantasy-points lean ok")


def spread_checks():
    import random
    from . import cfb_spread as S, cfb_lines_data as LD
    random.seed(7)
    true = {f"T{i}": random.gauss(0, 10) for i in range(24)}
    games = []
    for wk in range(1, 11):
        names = list(true); random.shuffle(names)
        for h, a in zip(names[::2], names[1::2]):
            m = true[h] - true[a] + 2.5 + random.gauss(0, 13)
            games.append(dict(id=f"{wk}{h}", week=wk, home=h, away=a, neutral=False, done=True, hp=30 + m / 2, ap=30 - m / 2, date=""))
    rat, hfa = S.fit_margin(games, {}, 2.0, 1.0)
    xs = [true[t] for t in true]; ys = [rat[t] for t in true]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    corr = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    assert corr > 0.9 and 1.0 < hfa < 4.0, (corr, hfa)
    pp = S.walk_forward({2026: games}, 2026, 4.0, 1.0)
    assert pp and all("model_margin" in p for p in pp)
    rows = LD.parse_lines([dict(id=1, week=3, homeTeam="Texas", awayTeam="Ohio State", lines=[dict(spread=-3.5, overUnder=55.5, formattedSpread="Texas -3.5"), dict(spread=3.5, overUnder=56.5, formattedSpread="Texas -3.5")])], 2025)
    assert rows[0]["home_spread"] == -3.5 and rows[0]["total"] == 56.0, rows
    ro = LD.parse_lines([dict(id=1, week=3, homeTeam="Texas", awayTeam="Ohio State", lines=[dict(spread=-3.5, overUnder=55.5, spreadOpen=-2.5, overUnderOpen=54.5, formattedSpread="Texas -3.5")])], 2025)
    assert ro[0]["open_total"] == 54.5 and ro[0]["open_spread"] == -2.5, ro
    print("spread model ok")


def totals_checks():
    import random
    from . import cfb_totals as T
    random.seed(5)
    rows = [[random.gauss(0, 1), random.gauss(0, 2)] for _ in range(400)]
    ys = [3.0 * r[0] - 1.0 * r[1] + random.gauss(0, 0.5) for r in rows]
    coef, mean, sd, ym = T.ridge(rows, ys, 1.0)
    assert abs(coef[0] / sd[0] - 3.0) < 0.2 and abs(coef[1] / sd[1] + 1.0) < 0.2, (coef, sd)
    print("totals ridge ok")


def depth_checks():
    from .slate import depth_map
    rows = [dict(team="KC", gsis_id=g, pos_abb=p, pos_slot="1", pos_rank=str(r)) for g, p, r in
            [("a", "QB", 1), ("b", "QB", 2), ("c", "WR", 1), ("d", "WR", 3), ("e", "WR", 4), ("f", "RB", 1), ("f", "RB", 2)]]
    m = depth_map(rows)
    assert m["a"]["st"] == 1 and m["b"]["st"] == 0 and m["d"]["st"] == 1 and m["e"]["st"] == 0 and m["d"]["slot"] == "WR3" and m["f"]["rank"] == 1, m
    print("depth chart ok")


def cfb_props_checks():
    """College props: market subset, CFBD team names on the rows, and the lines builder matching a college player to the right team."""
    from . import lines
    ev = dict(id="c1", commence_time="2026-10-17T16:00:00Z", home_team="Tulane Green Wave", away_team="Memphis Tigers")
    odds = dict(bookmakers=[
        dict(key="fanduel", markets=[dict(key="player_rush_yds", outcomes=[dict(name="Over", description="Sutton Smith", point=62.5, price=-115), dict(name="Under", description="Sutton Smith", point=62.5, price=-105)]),
                                     dict(key="player_anytime_td", outcomes=[dict(name="Yes", description="Sutton Smith", price=100)])]),
        dict(key="prizepicks", markets=[dict(key="player_rush_yds", outcomes=[dict(name="Over", description="Sutton Smith", point=60.5, price=-119), dict(name="Under", description="Sutton Smith", point=60.5, price=-119)])])])
    specs = {k: C.ODDS_MARKETS[k] for k in C.CFB_ODDS_MARKETS}
    rows = fetch_odds.parse_event(ev, odds, "2026-10-16T12:00:00", markets=specs, teams=("Memphis", "Tulane"))
    assert len(rows) == 2 and {r["book"] for r in rows} == {"fanduel", "prizepicks"} and rows[0]["home"] == "Tulane" and rows[0]["stat"] == "rushY", rows
    res = lines.build_lines(rows, [dict(id="9", name="Sutton Smith", team="Tulane", pos="RB"), dict(id="8", name="Sutton Smith", team="Ohio", pos="RB")])
    assert res["n"] == 1 and res["rows"][0]["id"] == "9" and res["rows"][0]["cons"]["line"] == 62.5 and res["rows"][0]["dfs"]["prizepicks"] == 60.5, res
    print("college props ok")


def fair_ok(x):
    return x == -150


if __name__ == "__main__":
    main()

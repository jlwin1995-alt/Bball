"""Offline checks that need no network and no key:  python -m pipeline.selftest

1. The Odds API response parser, on a stub shaped like the documented payload (the live API is not reachable from the dev sandbox).
2. Name matching: a shared name across two teams must never land one team's price on another team's player.
3. Consensus maths: de-vigged probability, median line snapped to a posted line, DFS books kept out of the consensus.
"""
import json, os, tempfile
from . import fetch_odds, lines


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
        assert lines.snapshot_pregame(res, log=log) == len(res["rows"])
        import datetime as dt
        later = dt.datetime(2026, 10, 11, 18, 0, tzinfo=dt.timezone.utc)
        assert lines.snapshot_pregame(res, log=log, now=later) == 0                                                # started: frozen, not rewritten
    cfb_checks()
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


def fair_ok(x):
    return x == -150


if __name__ == "__main__":
    main()

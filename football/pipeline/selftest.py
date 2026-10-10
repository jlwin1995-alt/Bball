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
    print("selftest ok:", len(rows), "rows,", len(res["rows"]), "lines")


def fair_ok(x):
    return x == -150


if __name__ == "__main__":
    main()

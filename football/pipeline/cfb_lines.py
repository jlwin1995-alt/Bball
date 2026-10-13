"""College game lines: The Odds API's spread and total attached to CollegeFootballData games.

The two feeds name teams differently (CFBD "Ohio State", "Texas A&M", "Miami (OH)"; The Odds API "Ohio State Buckeyes", "Texas A&M Aggies",
"Miami (OH) RedHawks"), so a CFBD name matches an Odds API name when it is a whole-word PREFIX of it, and the LONGEST such CFBD name wins
("Texas A&M Aggies" is "Texas A&M", not "Texas"; "Washington State Cougars" is not "Washington"). A game is matched by both teams, in either order
(neutral sites have no real home team), with the kickoff as a tie-break when only one side resolves. Lines are display-only context.
"""
import json, os, re, unicodedata


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", s.lower())).strip()


def resolve(odds_name, cfbd_names):
    """The CFBD team an Odds API team name refers to, or None."""
    o = norm(odds_name)
    best = None
    for n in cfbd_names:
        k = norm(n)
        if k and (o == k or o.startswith(k + " ")) and (best is None or len(k) > len(norm(best))):
            best = n
    return best


def attach(games, lines, names=None):
    """games: the site's game rows (home, away, ko). Adds spread (positive = home favoured), total, implied totals and the book counts in place.
    Returns the Odds API games that matched nothing, for the log."""
    names = names or sorted({g["home"] for g in games} | {g["away"] for g in games})
    by_pair = {frozenset((g["home"], g["away"])): g for g in games}
    unmatched = []
    for L in lines:
        h, a = resolve(L["home"], names), resolve(L["away"], names)
        g = by_pair.get(frozenset((h, a))) if h and a else None
        if g is None and (h or a):                               # one side resolved: accept the only game with that team at about that time
            cand = [x for x in games if (h or a) in (x["home"], x["away"])]
            if len(cand) == 1:
                g, h, a = cand[0], h or (cand[0]["away"] if a == cand[0]["home"] else cand[0]["home"]), a or (cand[0]["away"] if h == cand[0]["home"] else cand[0]["home"])
        if g is None:
            unmatched.append(f"{L['away']} @ {L['home']}")
            continue
        flip = 1 if h == g["home"] else -1                      # Odds API's home may be CFBD's away at a neutral site
        sp = None if L["home_spread"] is None else round(-L["home_spread"] * flip, 1)
        tot = L["total"]
        g.update(spread=sp, total=tot, n_spread=L["n_spread"], n_total=L["n_total"])
        if sp is not None and tot is not None:
            g.update(home_imp=round(tot / 2 + sp / 2, 1), away_imp=round(tot / 2 - sp / 2, 1))
    return unmatched


def load(raw="data/raw"):
    p = f"{raw}/cfb_lines.json"
    return json.load(open(p)) if os.path.exists(p) else None

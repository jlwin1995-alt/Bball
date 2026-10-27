"""PFF college team strings (truncated, upper case: "E WASHGTON", "MICH STATE") -> CollegeFootballData team names, so PFF rows join the college model's players and games."""
import re

# CFBD name -> PFF string, where they do not agree after normalising ("state" -> "st", punctuation dropped)
MANUAL = {
    "Arkansas State": "ARK STATE", "Boston College": "BOSTON COL", "Bowling Green": "BOWL GREEN", "California": "CAL", "Central Michigan": "C MICHIGAN", "Coastal Carolina": "COAST CAR",
    "Colorado State": "COLO STATE", "Connecticut": "UCONN", "East Carolina": "E CAROLINA", "Eastern Illinois": "E ILLINOIS", "Eastern Kentucky": "E KENTUCKY", "Eastern Michigan": "E MICHIGAN",
    "Eastern Washington": "E WASHGTON", "Florida Atlantic": "FAU", "Florida International": "FIU", "Georgia Southern": "GA SOUTHRN", "Georgia State": "GA STATE", "Georgia Tech": "GA TECH",
    "Jacksonville State": "JVILLE ST", "James Madison": "JAMES MAD", "Kennesaw State": "KENNESAW", "Louisiana": "LA LAFAYET", "Louisiana Tech": "LA TECH", "Massachusetts": "UMASS",
    "Miami": "MIAMI FL", "Miami (OH)": "MIAMI OH", "Michigan State": "MICH STATE", "Middle Tennessee": "MIDDLE TN", "Mississippi State": "MISS STATE", "Missouri State": "MO STATE",
    "New Mexico State": "NEW MEX ST", "North Carolina": "N CAROLINA", "North Dakota State": "N DAK ST", "North Texas": "N TEXAS", "Northern Illinois": "N ILLINOIS", "Northwestern": "NWESTERN",
    "Oklahoma State": "OKLA STATE", "Old Dominion": "DOMINION", "Sacramento State": "SACRAMENTO", "Sam Houston": "SM HOUSTON", "San Diego State": "S DIEGO ST", "San José State": "S JOSE ST",
    "South Alabama": "S ALABAMA", "South Carolina": "S CAROLINA", "South Florida": "USF", "Southern Miss": "SO MISS", "UL Monroe": "LA MONROE", "Virginia Tech": "VA TECH",
    "Wake Forest": "WAKE", "Washington State": "WASH STATE", "West Virginia": "W VIRGINIA", "Western Kentucky": "W KENTUCKY", "Western Michigan": "W MICHIGAN",
    "Texas State": "TEXAS ST", "Appalachian State": "APP STATE", "Southern Methodist": "SMU", "UT San Antonio": "UTSA", "Northern Colorado": "N COLORADO", "Northern Arizona": "N ARIZONA",
}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("state", "st").replace("&", "and"))


def pff_name(cfbd, pff_names):
    """The PFF string for a CFBD team name, or None."""
    want = MANUAL.get(cfbd, cfbd)
    index = {norm(p): p for p in pff_names}
    return index.get(norm(want))


def cfbd_map(pff_names, cfbd_names):
    """{PFF string: CFBD name} for every CFBD team that has a PFF string."""
    out = {}
    for c in cfbd_names:
        p = pff_name(c, pff_names)
        if p:
            out[p] = c
    return out

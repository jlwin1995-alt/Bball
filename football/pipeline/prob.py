"""Probabilities for posted lines (Python twin of site/model.js `sides`): the model's P(over)/P(under) for a line given a median projection."""
import math
from . import config as C

SPEC = {v[0]: dict(label=v[1], a=v[2], b=v[3], law=v[4]) for v in C.ODDS_MARKETS.values()}


def norm_cdf(z):
    return 0.5 * math.erfc(-z / math.sqrt(2))


def pois_cdf(k, mean):
    if k < 0:
        return 0.0
    if mean <= 0:
        return 1.0
    term = cum = math.exp(-mean)
    for i in range(1, int(k) + 1):
        term *= mean / i
        cum += term
    return min(1.0, cum)


def sigma_for(spec, m):
    return max(spec["a"] + spec["b"] * m, max(0.12 * m, 0.5))


def sides(line, m, spec):
    """(P(over), P(under)) given no push: a book's de-vigged price is conditional on no push, so these sum to 1."""
    o, u = _raw_sides(line, m, spec)
    t = o + u
    return (o / t, u / t) if t > 0 else (0.5, 0.5)


def _raw_sides(line, m, spec):
    line = float(line)
    whole = line == int(line)
    if spec["law"] == "poisson":
        if m <= 0:
            return 0.0, 1.0
        if whole:
            return 1 - pois_cdf(line, m), pois_cdf(line - 1, m)
        return 1 - pois_cdf(math.floor(line), m), pois_cdf(math.floor(line), m)
    sd = sigma_for(spec, m)
    if whole:
        return 1 - norm_cdf((line + 0.5 - m) / sd), norm_cdf((line - 0.5 - m) / sd)
    o = 1 - norm_cdf((line - m) / sd)
    return o, 1 - o

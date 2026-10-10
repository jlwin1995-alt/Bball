"use strict";
// The projection arithmetic, client side. Mirrors pipeline/model.py `derive`: the pipeline ships each player's volumes, rates and
// matchup multipliers; the browser multiplies them, so overriding a volume (carries, targets, receptions, attempts) recalculates
// instantly and scoring presets change the points without a rebuild. test/parity.mjs checks this against the pipeline's own numbers.
(function (root) {
  const SCORING = {
    "Full PPR": {passYd: 0.04, passTd: 4, intr: -1, rushYd: 0.1, rushTd: 6, recYd: 0.1, recTd: 6, rec: 1, fum: -1, two: 2},
    "Half PPR": {passYd: 0.04, passTd: 4, intr: -1, rushYd: 0.1, rushTd: 6, recYd: 0.1, recTd: 6, rec: 0.5, fum: -1, two: 2},
    "Standard": {passYd: 0.04, passTd: 4, intr: -1, rushYd: 0.1, rushTd: 6, recYd: 0.1, recTd: 6, rec: 0, fum: -1, two: 2},
    "6-pt pass TD (PPR)": {passYd: 0.04, passTd: 6, intr: -2, rushYd: 0.1, rushTd: 6, recYd: 0.1, recTd: 6, rec: 1, fum: -2, two: 2},
    "FanDuel": {passYd: 0.04, passTd: 4, intr: -1, rushYd: 0.1, rushTd: 6, recYd: 0.1, recTd: 6, rec: 0.5, fum: -2, two: 2},
  };

  // Pull a projection toward the slate's mean by a measured factor; `weight` phases it in by how much of a quarterback the player is.
  function calShrink(x, pivot, slope, weight) {
    if (!pivot || !(slope < 1) || !(weight > 0)) return x;
    const w = Math.min(1, weight);
    return x + w * ((pivot + (x - pivot) * slope) - x);
  }

  // o: this player's overrides {car, tgt, rec, att} (any may be absent). meta: {cal_pass, cal_comp}.
  function calc(p, o, W, meta) {
    o = o || {};
    const car = o.car != null ? o.car : p.car, tgt = o.tgt != null ? o.tgt : p.tgt, att = o.att != null ? o.att : p.att;
    const rushY = car * p.ypc * p.a_rush;
    // an explicit receptions override wins; otherwise targets x catch rate x the catch-rate matchup for the player's position group
    const rec = o.rec != null ? o.rec : tgt * p.cr * p.a_catch;
    const recY = rec * p.ypr * p.a_ypr;
    const qbW = att / 15;                                   // full correction at 15+ projected attempts, none at 0
    const passY = calShrink(att * p.ypa * p.a_pass, p.pp, meta.cal_pass, qbW);
    const comp = calShrink(att * p.cmp * p.a_comp, p.cp, meta.cal_comp, qbW);
    const rushTD = car * p.rtd_r * p.a_rtd;
    const recTD = tgt * p.rectd_r * p.a_rectd;             // scales with targets, so an overridden Rec does not drag it
    const passTD = att * p.ptd_r * p.a_ptd;
    const int = att * p.int_r;
    // the sack rate is per dropback (an attempt OR a sack): solve sacks = rate x (att + sacks) for sacks
    const sr = Math.min(0.5, Math.max(0, p.sack_r * p.a_sack));
    const sacks = att > 0 ? att * sr / (1 - sr) : 0;
    const fum = (car + rec) * p.fum_t + att * p.fum_a;
    const two = (car + tgt + att) * p.two_r;
    const r = {car, tgt, att, rushY, rec, recY, passY, comp, sacks, rushTD, recTD, passTD, int, fum, two, td: rushTD + recTD};
    r.pts = points(r, W);
    r.carSh = p.tcar ? car / p.tcar * 100 : null;
    r.tgtSh = p.ttgt ? tgt / p.ttgt * 100 : null;
    return r;
  }

  function points(r, W) {
    return r.rushY * W.rushYd + r.recY * W.recYd + r.passY * W.passYd + r.rec * W.rec + r.rushTD * W.rushTd + r.recTD * W.recTd
      + r.passTD * W.passTd + r.int * W.intr + r.fum * W.fum + r.two * W.two;
  }

  const api = {SCORING, calShrink, calc, points};
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.FB = api;
})(typeof window !== "undefined" ? window : globalThis);

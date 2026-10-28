"use strict";
// Helpers shared by the NFL page (app.js) and the college page (college/college.js).
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const num = (x, d = 1) => x == null || x === "" || Number.isNaN(+x) ? "" : Number(x).toFixed(d);

const makeStore = prefix => ({
  get(k, d) { try { const v = localStorage.getItem(prefix + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(prefix + k, JSON.stringify(v)); } catch (e) {} },
});
// ---------- generic sortable table -------------------------------------------
function table(cols, rows, {sort = null, id = "t", rowClass = null} = {}) {
  const st = table.state[id] || (table.state[id] = {key: sort?.key, asc: sort?.asc ?? false});
  const sorted = [...rows];
  const col = cols.find(c => c.k === st.key);
  if (col) {
    const g = col.v || (r => r[col.k]);
    sorted.sort((a, b) => {
      const x = g(a), y = g(b);
      if (x == null || x === "") return 1;
      if (y == null || y === "") return -1;
      return (typeof x === "string" ? x.localeCompare(y) : x - y) * (st.asc ? 1 : -1);
    });
  }
  const head = cols.map(c => `<th class="${c.l ? "l" : ""} ${c.k === st.key ? "s " + (st.asc ? "asc" : "") : ""}" data-k="${c.k}" title="${esc(c.t || "")}">${c.h}</th>`).join("");
  const body = sorted.map(r => `<tr class="${rowClass ? rowClass(r) : ""}">` + cols.map(c => `<td class="${c.l ? "l" : ""}">${c.f ? c.f(r) : esc(r[c.k])}</td>`).join("") + "</tr>").join("");
  return `<div class="tw" data-tid="${id}"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}
table.state = {};
document.addEventListener("click", e => {
  const th = e.target.closest("th[data-k]");
  if (!th) return;
  const id = th.closest("[data-tid]").dataset.tid, st = table.state[id], k = th.dataset.k;
  st.asc = st.key === k ? !st.asc : false; st.key = k;
  render(true);
});

// ---------- small formatters ---------------------------------------------------
const adj = x => x == null ? "" : `<span class="${x > 1.005 ? "good" : x < 0.995 ? "bad" : "mut"}">${num((x - 1) * 100, 1)}%</span>`;
const signed = (x, d = 1) => x == null || x === "" ? "" : `<span class="${x > 0 ? "good" : x < 0 ? "bad" : "mut"}">${x > 0 ? "+" : ""}${num(x, d)}</span>`;

const plainSigned = x => x == null ? "" : (x > 0 ? "+" : "") + num(x, 1);
// change in error against a baseline: negative means the model made smaller misses, so negative is the good colour
const vsBase = x => x == null ? "" : `<span class="${x < 0 ? "good" : x > 0 ? "bad" : "mut"}">${x > 0 ? "+" : ""}${num(x, 1)}%</span>`;
const pc1 = (h, n) => n ? `${(h / n * 100).toFixed(1)}% <span class="mut">(${h}/${n})</span>` : "—";

// Side-by-side team comparison (away left, home right): one row per stat with both values, rank in the league, and a bar split by the two values.
// The better side of each row is highlighted (higher for what a team gains, lower for what it allows and for turnovers).
function compareCard(T, away, home) {
  const a = T?.teams?.[away], h = T?.teams?.[home];
  if (!a || !h) return "";
  const row = r => {
    const x = a[r.k], y = h[r.k];
    if (x == null || y == null) return "";
    const tot = Math.abs(x) + Math.abs(y), pa = tot ? Math.abs(x) / tot * 100 : 50;
    const better = r.neutral || x === y ? 0 : ((x > y) === r.higher ? -1 : 1);       // -1 = away side better, 1 = home side better
    const cell = (v, rk, win) => `<b class="${win ? "win" : ""}">${num(v, r.dp)}</b> <span class="mut">#${rk}</span>`;
    return `<div class="cmp"><div class="cmpv l">${cell(x, a[r.k + "_rk"], better === -1)}</div><div class="cmpl">${esc(r.label)}${r.neutral ? ' <span class="mut">(#1 = highest)</span>' : ""}
      <div class="cmpbar"><i class="${better === -1 ? "win" : ""}" style="width:${pa.toFixed(1)}%"></i><i class="${better === 1 ? "win" : ""}" style="width:${(100 - pa).toFixed(1)}%"></i></div></div>
      <div class="cmpv r">${cell(y, h[r.k + "_rk"], better === 1)}</div></div>`;
  };
  return `<div class="cmpcard"><h3>Team comparison <span class="mut">· per game, ${a.g} and ${h.g} games · #rank of ${T.n} (1 = best)</span></h3>
    <div class="cmphead"><span>${esc(away)}</span><span>${esc(home)}</span></div>${T.rows.map(row).join("")}
    <p class="mut cmpnote">${T.note || ""}</p></div>`;
}

// Depth-chart role: {slot: "WR2", rank, st: 1 if a starter, share?}. NFL = the ESPN depth chart (via nflverse); college = inferred from the last three games' usage.
const depthTip = (inferred, ts) => inferred ? "Inferred from who has actually been used in the team's last three games (college has no depth-chart feed). Share = fraction of the group's recent volume." : `ESPN depth chart as of ${ts ? new Date(ts).toLocaleString(undefined, {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}) : "the last update"}. Starter = QB/RB/TE rank 1, WR ranks 1-3. Teams can change it before kickoff: check the inactive list 90 minutes out.`;
const outFlag = s => /^(out|ir)/i.test(s || "") ? "OUT" : /doubt/i.test(s || "") ? "DOUBTFUL" : "";
// A starter the injury report has ruled out (or all but) is the one thing on the board the projection does NOT already know: his volume is not handed to teammates.
const starterOut = r => r.depth?.st && outFlag(r.status);
const depthPill = (d, tip, status) => {
  const f = d?.st ? outFlag(status) : "";
  return d ? `<span class="pill ${f ? "bad" : d.st ? "start" : "bkp"}" title="${esc(f ? `Listed ${f} on the injury report. ${tip}` : tip)}">${d.st ? "★ " : ""}${esc(d.slot)}${f ? ` · ${f}` : ""}${!f && d.share != null ? ` <span class="zs">${Math.round(d.share * 100)}%</span>` : ""}</span>` : `<span class="mut" title="${esc(tip)}">—</span>`;
};
// A player with fewer than THIN_G games of history is a thin sample: his projection is mostly the prior, so no lean is flagged for him (the sigma is still shown).
const THIN_G = 3;
const isThin = p => p.g != null && p.g < THIN_G;
// A teammate of a starter the injury report lists OUT (same position, RB or WR): his projected volume is the model's re-spread, not an observation, and it
// is still low on average (WR teammates 4.3 targets projected vs 5.2 actual), which would bias leans toward the UNDER. No lean is flagged for him.
const isShift = p => !!p.shift;
const isRet = p => !!p.ret;
const noLean = p => isThin(p) || isShift(p) || isRet(p);
const shiftTag = p => isShift(p) ? ` <span class="pill bkp" title="A starter at his position is listed OUT. His volume is the model's re-spread of that starter's share, so no lean is flagged.">role shift</span>` : "";
const thinTag = p => isThin(p) ? ` <span class="pill bkp" title="Only ${p.g} game${p.g === 1 ? "" : "s"} of history: the projection is mostly the league prior, so no lean is flagged.">thin</span>` : "";
const retTag = p => isRet(p) ? ` <span class="pill bkp" title="A starter who has missed games or left one early lately: his history understates the role he is expected to have back, so no lean is flagged.">returning</span>` : "";
const depthCol = (tip, inferred) => ({k: "depth", h: "Depth", l: 1, t: tip, v: r => r.depth ? (starterOut(r) ? -1 : (r.depth.st ? 0 : 1) * 100 + r.depth.rank) : 999, f: r => depthPill(r.depth, tip, r.status) + thinTag(r) + shiftTag(r) + retTag(r)});

// A player's name that opens his game on the Game Board (Lines tab): sets the board's game and highlights his row.
const gbLink = (name, game, id) => `<a href="#Game-Board" class="plink" data-game="${esc(game)}" data-pid="${esc(id)}" title="Open this player's game on the Game Board">${esc(name)}</a>`;
document.addEventListener("click", e => {
  const a = e.target.closest?.("a.plink");
  if (a && typeof F !== "undefined") { F.game = a.dataset.game; F.focus = a.dataset.pid; }
});
const focusRow = r => typeof F !== "undefined" && F.focus && r.id === F.focus ? "focus" : "";

// ---- Fantasy points (PrizePicks) ----
// The player's MEDIAN points under the PrizePicks scoring become a mean-adjusted projection (cfg.mean = [a, b]: mean = a + b x median, fitted on the backtest, since a
// median sits below the mean and PrizePicks' lines sit at about the mean), and the lean is (mean - line) / sigma with sigma = cfg.sigma[0] + cfg.sigma[1] x mean.
// MORE = over, LESS = under. Only STRONG (0.5 sigma or more) is flagged; thin samples and role-shift players never are. A LESS pick is not voided by an early exit.
function fpBuild(FPD, byId, medianPts) {
  if (!FPD?.rows?.length || !FPD.cfg) return [];
  const [m0, m1] = FPD.cfg.mean, [s0, s1] = FPD.cfg.sigma;
  return FPD.rows.map(r => {
    const p = byId[r.id];
    if (!p) return null;
    const med = medianPts(p), mean = m0 + m1 * med, sd = s0 + s1 * mean, z = (mean - r.line) / sd, st = Date.now() >= Date.parse(r.commence);
    return {...r, p, med, mean, sd, z, started: st, side: z > 0 ? "MORE" : "LESS", pm: FB.normCdf(z), tier: !st && Math.abs(z) >= 0.5 && !noLean(p) && med > 0 ? "strong" : ""};
  }).filter(Boolean);
}
function fpSection(FPD, byId, medianPts, F) {
  if (!FPD) return "";
  const head = `<h2 style="margin-top:28px">Fantasy points (PrizePicks)</h2>`;
  if (!FPD.cfg) return `${head}<p class="sub">PrizePicks fantasy-points lines are being collected, but the mean-adjustment and spread for this league need more backtest rows before a lean can be shown.</p>`;
  const rows = fpBuild(FPD, byId, medianPts).filter(r => (!F.q || (r.name + " " + r.team).toLowerCase().includes(F.q.trim().toLowerCase())) && (!F.pos || r.p.pos === F.pos));
  if (!rows.length) return `${head}<p class="sub">No PrizePicks fantasy-points lines yet: they post close to kickoff for each team's main players, and this fills in on its own.</p>`;
  const cols = [{k: "name", h: "Player", l: 1, f: r => gbLink(r.name, r.p.game, r.id) + thinTag(r.p) + shiftTag(r.p) + retTag(r.p)}, {k: "pos", h: "Pos", l: 1, f: r => esc(r.p.pos)}, {k: "team", h: "Team", l: 1},
    {k: "game", h: "Game", l: 1, f: r => esc(r.game) + (r.started ? ` <span class="pill hot">LIVE</span>` : "")},
    {k: "med", h: "Median", t: "The model's median points under the PrizePicks scoring", f: r => num(r.med)}, {k: "mean", h: "Mean-adj", t: "Median turned into a mean (backtest fit)", f: r => num(r.mean)},
    {k: "line", h: "Line", v: r => r.line, f: r => num(r.line, 1)}, {k: "z", h: "Lean σ", t: "(mean-adjusted projection - line) / sigma. Positive = MORE", v: r => Math.abs(r.z), f: r => `${r.z > 0 ? "+" : ""}${num(r.z, 2)}`},
    {k: "pick", h: "Lean", l: 1, v: r => r.tier ? Math.abs(r.z) : 0, f: r => r.tier ? `<span class="pill lean-strong" title="STRONG: 0.5 sigma or more. Ungraded for this market so far.">STRONG ${r.side}</span>` : ""},
    {k: "pm", h: "P(MORE)", t: "Model probability the player clears the line (normal around the mean-adjusted projection)", f: r => num(r.pm * 100, 0) + "%"}];
  return `${head}<p class="sub">${rows.length} lines, last updated ${esc(new Date(FPD.updated).toLocaleString(undefined, {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}))}. Median projection under the PrizePicks scoring, turned into a mean-adjusted projection and compared with the PrizePicks line in standard deviations (σ ≈ ${num(FPD.cfg.sigma[0], 1)} + ${num(FPD.cfg.sigma[1], 2)} × projection). Only STRONG (0.5σ or more) is flagged, and no pick is flagged for thin-sample or role-shift players. This market has no sportsbook price, so there is no vig to remove; check the break-even for your entry type. A LESS pick is not voided by an early exit, but a MORE pick can be (first-half exit, no return).</p>
    ${table(cols, rows, {id: "fp", sort: {key: "z"}, rowClass: r => r.started ? "started" : r.tier ? "lean-strong-row" : ""})}`;
}

// PFF display helpers shared by the NFL and college pages (matchup strength pill, alignment cell)
const MU_TIP = "Strength of the opposing coverage against his position group (PFF receiver-versus-defender data, season to date): the target-weighted coverage grade of the defenders thrown at by that group. Rank 32 = the weakest coverage in the league. A visual aid only: tested as a model input it did not improve the projections.";
const muCell = m => !m ? "" : `<span class="pill mu-${m.label.toLowerCase()}" title="${esc(MU_TIP)}${m.defs?.length ? "\n\nLikely coverage: " + m.defs.map(d => `${d.name} (${d.pos}, coverage ${d.rk}/${d.n}, ${d.share}% of the group's targets)`).join("; ") : ""}">${m.label} <span class="zs">${m.rank}/${m.of}</span></span>`;
const roleCell = ro => !ro ? "" : `<span title="Slot ${ro.sl}% · Wide ${ro.wd}% · Inline ${ro.il}% · Backfield ${ro.bk}% of his pass routes, last 3 games (PFF)">${esc(ro.label)}</span>`;

// usage-trend display helpers shared by the NFL and college pages
const moveCell = (v, pts = true) => v == null ? "" : `<span class="${v >= 5 ? "good" : v <= -5 ? "bad" : "mut"}">${v > 0 ? "+" : ""}${num(v, 1)}${pts ? "" : "%"}</span>`;
function spark(a) {
  if (!a || a.length < 2) return "";
  const w = 70, h = 18, mx = Math.max(...a, 1), mn = Math.min(...a, 0), step = w / (a.length - 1);
  const pts = a.map((v, i) => `${(i * step).toFixed(1)},${(h - 1 - (v - mn) / (mx - mn || 1) * (h - 2)).toFixed(1)}`).join(" ");
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
}

// Recent usage beside a player on the Game Board: his main share of the team's work over the last 3 games, the move against the games before, and the weekly line.
// RB: carries + targets (receptions in college); WR/TE and everyone else with targets: target share (reception share in college). Display only.
const USAGE_TIP = "Share of the team's work, last 3 games, and the move in points against the games before (green/red at 5+). RB: carries + targets (college: carries + receptions). WR/TE: target share (college: reception share). The line is week by week. Display only: usage trends have not improved the projections.";
function usageCell(u, college) {
  if (!u) return "";
  const k = u.pos === "RB" ? "opp" : college ? "rec" : "tgt", lab = u.pos === "RB" ? "opp" : college ? "rec" : "tgt";
  if (u[k + "_r"] == null) return "";
  const flag = u.flag ? `<span class="pill ${u.flag === "RISING" ? "lean-strong" : "lean-lean"}">${u.flag}</span> ` : "";
  const bits = [`${lab} ${num(u[k + "_b"])}% → ${num(u[k + "_r"])}%`, u.snap_r != null ? `snaps ${num(u.snap_b, 0)}% → ${num(u.snap_r, 0)}%` : "",
    u.pos === "RB" && u.car_r != null ? `carries ${num(u.car_b)}% → ${num(u.car_r)}%` : "", u.tm_d != null ? `team volume ${u.tm_d > 0 ? "+" : ""}${num(u.tm_d, 1)}%` : ""].filter(Boolean);
  return `<span title="${esc(bits.join("\n"))}">${flag}<span class="mut">${lab}</span> <b>${num(u[k + "_r"])}%</b> ${moveCell(u[k + "_d"])} ${spark((u[k + "_w"] || []).map(v => v ?? 0))}</span>`;
}
const usageCol = (getU, college) => ({k: "utr", h: "Usage trend", l: 1, t: USAGE_TIP, v: r => { const u = getU(r); return u ? u[(u.pos === "RB" ? "opp" : college ? "rec" : "tgt") + "_r"] : null; }, f: r => usageCell(getU(r), college)});

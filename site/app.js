"use strict";
// ---------- state ----------------------------------------------------------
const TABS = ["Projections", "Game Board", "Matchups", "Efficiency", "Usage", "Trends", "Lines", "Scorecard", "Config", "Methodology"];
const STATS = ["pts", "reb", "ast", "fg3m", "stl", "blk", "tov"];
const LABEL = {pts: "PTS", reb: "REB", ast: "AST", fg3m: "3PM", stl: "STL", blk: "BLK", tov: "TOV", fp: "FP", pra: "PTS+REB+AST", pr: "PTS+REB", pa: "PTS+AST", ra: "REB+AST"};
const COMBO = {pra: ["pts", "reb", "ast"], pr: ["pts", "reb"], pa: ["pts", "ast"], ra: ["reb", "ast"]};
const PRESETS = {
  DraftKings: {pts: 1, fg3m: 0.5, reb: 1.25, ast: 1.5, stl: 2, blk: 2, tov: -0.5},
  FanDuel: {pts: 1, fg3m: 0, reb: 1.2, ast: 1.5, stl: 3, blk: 3, tov: -1},
};
const D = {};
let CFG = {preset: "DraftKings", scoring: {...PRESETS.DraftKings}, mean: false, edgeMin: 4, ppBE: 57.7};
let OVR = {}, LINES = [];
const store = {
  get(k, d) { try { const v = localStorage.getItem("hm_" + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("hm_" + k, JSON.stringify(v)); } catch (e) {} },
};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const num = (x, d = 1) => x == null || Number.isNaN(x) ? "" : Number(x).toFixed(d);
const view = () => document.getElementById("view");

// ---------- model (client side: minutes x adjusted per-minute rate) ----------
function calc(p, forceMedian) {
  const o = OVR[p.pid] || {};
  const min = o.min != null ? o.min : p.out ? 0 : p.min;
  const f = CFG.mean && !forceMedian ? D.meta.mean_factor : 1;
  const r = {min};
  for (const s of STATS) r[s] = min * p["rate_" + s] * f;
  for (const [k, parts] of Object.entries(COMBO)) r[k] = parts.reduce((a, x) => a + r[x], 0);
  r.fp = Object.entries(CFG.scoring).reduce((a, [s, w]) => a + w * r[s], 0);
  return r;
}
const proj = () => D.projections.map(p => ({...p, c: calc(p)}));
const projMed = () => D.projections.map(p => ({...p, c: calc(p, true)}));   // lines are always compared to the median-style projection
const normCdf = z => { const t = 1 / (1 + 0.2316419 * Math.abs(z)), d = 0.3989423 * Math.exp(-z * z / 2);
  const q = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274)))); return z > 0 ? 1 - q : q; };
const impl = o => { o = +o; return !o ? null : o < 0 ? -o / (-o + 100) : 100 / (o + 100); };
const amer = p => p == null ? "" : (p >= 0.5 ? "-" + Math.round(100 * p / (1 - p)) : "+" + Math.round(100 * (1 - p) / p));
// P(over), P(under) for a line given projection m and spread sd; whole-number lines treat a push as neither side.
function sides(line, m, sd) { line = +line; const whole = Number.isInteger(line);
  return whole ? {o: 1 - normCdf((line + 0.5 - m) / sd), u: normCdf((line - 0.5 - m) / sd)} : (() => { const o = 1 - normCdf((line - m) / sd); return {o, u: 1 - o}; })(); }

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

const nameCols = [{k: "name", h: "Player", l: 1}, {k: "pos", h: "Pos", l: 1}, {k: "team", h: "Team", l: 1}];
function filters(extra = "") {
  return `<div class="bar"><input id="q" placeholder="Search player / team" value="${esc(F.q)}">
  <label>Pos <select id="pos">${["", "G", "F", "C"].map(p => `<option ${F.pos === p ? "selected" : ""} value="${p}">${p || "All"}</option>`).join("")}</select></label>${extra}</div>`;
}
const F = {q: "", pos: "", ming: 10, lstat: "", lgame: "", lpicks: false};
function passes(r) {
  if (F.pos && r.pos !== F.pos) return false;
  const q = F.q.trim().toLowerCase();
  return !q || (r.name + " " + r.team).toLowerCase().includes(q);
}
document.addEventListener("input", e => {
  if (e.target.id === "q") { F.q = e.target.value; render(true, "q"); }
});
document.addEventListener("change", e => {
  if (e.target.id === "pos") { F.pos = e.target.value; render(true); }
  if (e.target.id === "ming") { F.ming = +e.target.value || 0; render(true); }
  if (e.target.id === "lstat") { F.lstat = e.target.value; render(true); }
  if (e.target.id === "lgame") { F.lgame = e.target.value; render(true); }
  if (e.target.id === "lpicks") { F.lpicks = e.target.checked; render(true); }
});

// ---------- pages ---------------------------------------------------------------
const pct = x => x == null ? "" : `<span class="${x > 1.005 ? "good" : x < 0.995 ? "bad" : "mut"}">${num((x - 1) * 100, 1)}%</span>`;
const statusPill = s => s ? `<span class="pill ${s === "Out" ? "bad" : ""}">${esc(s)}</span>` : "";


const warn = e => e != null && Math.abs(e) >= 15 ? ` <span title="An edge this large is usually the model having the minutes or role wrong (injury news, rotation change), not a bargain. Check before trusting it." style="cursor:help">⚠</span>` : "";
function liveLines() {
  const L = D.lines;
  const M = L && L.meta, credits = M && M.credits != null ? ` · Odds API credits left: <b>${M.credits}</b>` : "";
  if (!L || !L.rows || !L.rows.length) {
    if (!M) return `<p class="sub">No live lines yet. They come from The Odds API: add your key as the <code>ODDS_API_KEY</code> repository secret and run the "Refresh odds" workflow (see the README).</p>`;
    const ago = Math.max(0, Math.round((Date.now() - Date.parse(M.ts)) / 60000)), when = ago < 90 ? ago + " min ago" : Math.round(ago / 60) + " h ago";
    const games = (M.games || []).map(g => `<li>${esc(g.game)} — tip ${new Date(g.commence).toLocaleString([], {weekday: "short", hour: "numeric", minute: "2-digit"})}: ${g.props ? g.props + " props posted" : "<b>no player props posted yet</b>"}</li>`).join("");
    return `<p class="sub">Last checked ${when}${credits}. ${games ? "Upcoming games found:" : "No games start in the next 30 hours."}</p>${games ? `<ul class="sub">${games}</ul>` : ""}
      <p class="sub">Books usually post player props a few hours before tip, and often skip preseason games entirely. This page fills in automatically on the next check (three a day on game days).</p>`;
  }
  const byId = Object.fromEntries(projMed().map(p => [p.pid, p]));
  const sp = D.spread || D.meta.spread, BE = CFG.ppBE / 100, mins = Math.round((Date.now() - Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(L.updated) ? L.updated : L.updated + "Z")) / 60000);
  let rows = L.rows.map(r => {
    const p = byId[r.pid]; if (!p) return null;
    const m = p.c[r.stat], [a, b] = sp[r.stat] || [1, 0.3], sd = Math.max(a + b * m, 0.1), c = r.cons, pp = r.dfs.prizepicks;
    const out = {name: p.name, pos: p.pos, team: p.team, game: r.game, stat: r.stat, m, c, r, pp, ud: r.dfs.underdog ?? r.dfs.pick6, out: p.c.min === 0};
    if (c) { const s = sides(c.line, m, sd); out.po = s.o; out.edge = (s.o - c.p_over) * 100; out.pick = out.out ? "OUT" : Math.abs(out.edge) >= CFG.edgeMin ? (out.edge > 0 ? "OVER" : "UNDER") : ""; }
    if (pp != null) { const s = sides(pp, m, sd); out.side = s.o >= s.u ? "OVER" : "UNDER"; out.pw = Math.max(s.o, s.u); out.ppEdge = (out.pw - BE) * 100;
      out.ppPick = out.out ? "OUT" : out.ppEdge >= CFG.edgeMin ? "PP " + out.side : ""; out.gap = c ? pp - c.line : null; }
    return out;
  }).filter(Boolean).filter(passes);
  if (F.lstat) rows = rows.filter(r => r.stat === F.lstat);
  if (F.lgame) rows = rows.filter(r => r.game === F.lgame);
  if (F.lpicks) rows = rows.filter(r => (r.pick && r.pick !== "OUT") || (r.ppPick && r.ppPick !== "OUT"));
  const tip = r => r.r.books.map(b => `${b.b} ${b.line} (${b.over ?? "-"}/${b.under ?? "-"})`).join("\n");
  const cols = [{k: "name", h: "Player", l: 1, f: r => esc(r.name)}, {k: "team", h: "Team", l: 1}, {k: "game", h: "Game", l: 1}, {k: "stat", h: "Stat", l: 1, f: r => LABEL[r.stat]},
    {k: "m", h: "Proj", t: "Median-style projection with your Min OVR overrides", f: r => num(r.m)},
    {k: "cl", h: "Cons line", t: "Median sportsbook line; hover for every book", v: r => r.c?.line, f: r => r.c ? `<span title="${esc(tip(r))}">${r.c.line} <span class="mut">${r.c.n}/${r.c.n_books}</span></span>` : ""},
    {k: "cp", h: "Cons P(over)", t: "Average vig-free P(over) of the books at the consensus line", v: r => r.c?.p_over, f: r => r.c ? num(r.c.p_over * 100) + "%" : ""},
    {k: "fo", h: "Fair odds", t: "Over / under, from the consensus probability", v: r => r.c?.p_over, f: r => r.c ? `${amer(r.c.p_over)} / ${amer(1 - r.c.p_over)}` : ""},
    {k: "po", h: "Model P(over)", v: r => r.po, f: r => r.po == null ? "" : num(r.po * 100) + "%"},
    {k: "edge", h: "Edge pp", v: r => r.edge, f: r => r.edge == null ? "" : `<span class="${r.edge > 0 ? "good" : "bad"}">${num(r.edge)}</span>`},
    {k: "pick", h: "Pick", l: 1, f: r => r.pick ? `<b>${r.pick}</b>${r.pick === "OUT" ? "" : warn(r.edge)}` : ""},
    {k: "pp", h: "PrizePicks", v: r => r.pp, f: r => r.pp ?? ""},
    {k: "gap", h: "PP − cons", t: "Positive: PrizePicks line is higher than the books' (easier UNDER); negative: lower (easier OVER)", v: r => r.gap, f: r => r.gap == null ? "" : `<span class="${r.gap < 0 ? "good" : r.gap > 0 ? "bad" : "mut"}">${r.gap > 0 ? "+" : ""}${num(r.gap)}</span>`},
    {k: "pw", h: "PP P(win)", t: "Model probability of the better side at the PrizePicks line", v: r => r.pw, f: r => r.pw == null ? "" : `${r.side[0]} ${num(r.pw * 100)}%`},
    {k: "ppEdge", h: "PP edge pp", t: `vs your break-even of ${CFG.ppBE}% (Config)`, v: r => r.ppEdge, f: r => r.ppEdge == null ? "" : `<span class="${r.ppEdge > 0 ? "good" : "bad"}">${num(r.ppEdge)}</span>`},
    {k: "ppPick", h: "PP pick", l: 1, f: r => r.ppPick ? `<b>${r.ppPick}</b>${r.ppPick === "OUT" ? "" : warn(r.ppEdge)}` : ""},
    {k: "ud", h: "UD/Pick6", v: r => r.ud, f: r => r.ud ?? ""}];
  const games = [...new Set(L.rows.map(r => r.game))].sort(), stats = [...new Set(L.rows.map(r => r.stat))];
  const extra = `<label>Stat <select id="lstat"><option value="">All</option>${stats.map(s => `<option value="${s}" ${F.lstat === s ? "selected" : ""}>${LABEL[s] || s}</option>`).join("")}</select></label>
    <label>Game <select id="lgame"><option value="">All</option>${games.map(g => `<option ${F.lgame === g ? "selected" : ""}>${esc(g)}</option>`).join("")}</select></label>
    <label><input type="checkbox" id="lpicks" ${F.lpicks ? "checked" : ""}> picks only</label>`;
  return `<p class="sub">Sportsbook consensus (median line; vig removed) beside PrizePicks / Underdog, with the model's edge against each${credits}. Updated ${mins < 90 ? mins + " min" : Math.round(mins / 60) + " h"} ago${mins > 360 ? " — <b>stale, lines move</b>" : ""}. DFS prices are nominal, so PrizePicks edge is measured against your break-even (Config) rather than odds. A k-pick entry paying M× needs M^(−1/k) per leg.</p>
    ${filters(extra)}${table(cols, rows, {id: "live", sort: {key: "edge"}})}`;
}

const pages = {
  Projections() {
    const rows = proj().filter(passes);
    const cols = [...nameCols, {k: "opp", h: "Opp", l: 1, f: r => (r.home ? "vs " : "@ ") + esc(r.opp), v: r => r.opp},
      {k: "rest", h: "Rest", t: "Days since the team's last game", f: r => r.rest ?? ""},
      {k: "status", h: "Status", l: 1, f: r => statusPill(r.status)},
      {k: "g", h: "G", t: "Weighted games in the sample (last season counts partially early on)"},
      {k: "mino", h: "Min OVR", t: "Type minutes to override; 0 = out. Teammates are NOT re-scaled in the browser. Saved on this device.", v: r => OVR[r.pid]?.min,
        f: r => `<input class="ovr" data-pid="${esc(r.pid)}" value="${OVR[r.pid]?.min ?? ""}" placeholder="${num(r.min)}">`},
      {k: "cmin", h: "Min", v: r => r.c.min, f: r => num(r.c.min)},
      ...STATS.map(s => ({k: "c" + s, h: LABEL[s], v: r => r.c[s], f: r => num(r.c[s], s === "pts" ? 1 : 1)})),
      {k: "cfp", h: CFG.mean ? "Mean FP" : "Proj FP", v: r => r.c.fp, f: r => `<b>${num(r.c.fp)}</b>`},
      {k: "apts", h: "Pts Adj", t: "Opponent multiplier on scoring, after damping", v: r => r.adj_pts, f: r => pct(r.adj_pts)},
      {k: "areb", h: "Reb Adj", v: r => r.adj_reb, f: r => pct(r.adj_reb)},
      {k: "aast", h: "Ast Adj", v: r => r.adj_ast, f: r => pct(r.adj_ast)}];
    return `<h2>Projections — ${esc(D.coverage.slate_date || "no slate")}</h2>
      <p class="sub">${CFG.mean ? "Mean" : "Median-style"} projection per player with a game. Shaded <b>Min OVR</b> is yours; everything recalculates instantly. Scoring: ${esc(CFG.preset)}.</p>
      ${filters(`<button id="clr">Clear overrides</button>`)}
      ${table(cols, rows, {id: "proj", sort: {key: "cfp"}, rowClass: r => r.c.min === 0 ? "out" : ""})}`;
  },

  "Game Board"() {
    const games = [...new Set(D.projections.filter(p => p.home).map(p => p.team + "|" + p.opp))].sort();
    F.game = F.game && games.includes(F.game) ? F.game : games[0];
    const [home, away] = (F.game || "|").split("|");
    const mk = t => {
      const rows = proj().filter(p => p.team === t);
      const cols = [...nameCols.slice(0, 2), {k: "status", h: "Status", l: 1, f: r => statusPill(r.status)},
        {k: "cmin", h: "Min", v: r => r.c.min, f: r => num(r.c.min)},
        ...["pts", "reb", "ast", "fg3m"].map(s => ({k: "c" + s, h: LABEL[s], v: r => r.c[s], f: r => num(r.c[s])})),
        {k: "cfp", h: "FP", v: r => r.c.fp, f: r => `<b>${num(r.c.fp)}</b>`}];
      return `<div><h3>${esc(t)} ${t === home ? "(home)" : "(away)"}</h3>${table(cols, rows, {id: "gb" + t, sort: {key: "cfp"}, rowClass: r => r.c.min === 0 ? "out" : ""})}</div>`;
    };
    return `<h2>Game Board</h2><p class="sub">Pick a game; both teams ranked by projected fantasy points.</p>
      <div class="bar"><select id="game">${games.map(g => `<option value="${g}" ${g === F.game ? "selected" : ""}>${g.split("|")[1]} @ ${g.split("|")[0]}</option>`).join("")}</select></div>
      <div class="two">${mk(away)}${mk(home)}</div>`;
  },

  Matchups() {
    const cols = [{k: "team", h: "Team", l: 1}, {k: "playing", h: "Plays", l: 1, f: r => r.playing ? "yes" : ""}, {k: "games", h: "G"},
      ...STATS.map(s => ({k: s + "_raw", h: LABEL[s], t: "What this defence allowed vs league, regressed by sample (not damped)", f: r => pct(r[s + "_raw"])}))];
    return `<h2>Matchups</h2><p class="sub">What each defence has allowed relative to league, regressed toward 1.0 by games played. Green = soft (stat inflates), red = tough. The projection uses a damped share of these (see Methodology). Opposing-offence strength is not removed.</p>
      ${table(cols, D.matchups, {id: "mu", sort: {key: "pts_raw"}})}`;
  },

  Efficiency() {
    const rows = D.efficiency.filter(passes).filter(r => r.mpg >= F.ming);
    const cols = [...nameCols, {k: "g", h: "G"}, {k: "mpg", h: "MPG"}, ...["pts", "reb", "ast", "stl", "blk", "tov"].map(s => ({k: s + "36", h: LABEL[s] + "/36", f: r => num(r[s + "36"], s === "stl" || s === "blk" || s === "tov" ? 2 : 1)})),
      {k: "ts", h: "TS%", t: "True shooting", f: r => r.ts == null ? "" : num(r.ts * 100)}, {k: "fg", h: "FG%", f: r => r.fg == null ? "" : num(r.fg * 100)},
      {k: "ft", h: "FT%", f: r => r.ft == null ? "" : num(r.ft * 100)}, {k: "ast_tov", h: "AST/TOV", f: r => num(r.ast_tov, 2)}];
    return `<h2>Efficiency</h2><p class="sub">Per-36 rates and shooting efficiency, so a bench player and a starter compare on equal terms. Defaults to 10+ MPG; lower it to see the end of the bench.</p>
      ${filters(`<label>Min MPG <input id="ming" size="3" value="${F.ming}"></label>`)}${table(cols, rows, {id: "eff", sort: {key: "pts36"}})}`;
  },

  Usage() {
    const rows = D.usage.filter(passes).filter(r => r.mpg >= F.ming);
    const cols = [...nameCols, {k: "g", h: "G"}, ...[["min_sh", "Min %"], ["fga_sh", "FGA %"], ["fta_sh", "FTA %"], ["ast_sh", "AST %"], ["reb_sh", "REB %"], ["tov_sh", "TOV %"], ["usg", "Usage %"]]
      .map(([k, h]) => ({k, h, f: r => num(r[k])}))];
    return `<h2>Usage</h2><p class="sub">Share of team opportunity so far — history, not projection. Usage % = (FGA + 0.44·FTA + TOV) share. Shares are over the games he played in, so missed time isn't held against him; read G beside them.</p>
      ${filters(`<label>Min MPG <input id="ming" size="3" value="${F.ming}"></label>`)}${table(cols, rows, {id: "use", sort: {key: "usg"}})}`;
  },

  Trends() {
    const spark = a => { const w = 70, h = 18, mx = Math.max(...a), mn = Math.min(...a), sp = (mx - mn) || 1;
      const pts = a.map((v, i) => `${(i / (a.length - 1) * w).toFixed(1)},${(h - (v - mn) / sp * h).toFixed(1)}`).join(" ");
      return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline points="${pts}" fill="none" stroke="var(--acc)" stroke-width="1.5"/></svg>`; };
    const rows = D.trends.filter(passes).filter(r => r.min_s >= F.ming);
    const cols = [...nameCols, {k: "g", h: "G"}, {k: "fp_s", h: "Season FP"}, {k: "fp_r", h: `Last ${D.meta.rolling_window}`},
      {k: "d_fp", h: "Δ FP %", f: r => `<span class="${r.d_fp > 0 ? "good" : "bad"}">${num(r.d_fp)}</span>`},
      {k: "min_s", h: "Min"}, {k: "min_r", h: `Min L${D.meta.rolling_window}`}, {k: "d_min", h: "Δ Min %", f: r => `<span class="${r.d_min > 0 ? "good" : "bad"}">${num(r.d_min)}</span>`},
      {k: "form", h: "Form", t: "HOT/COLD need scoring AND minutes moving the same way, so a hot shooting night on flat minutes does not register", f: r => r.form === "-" ? "" : `<span class="pill ${r.form === "HOT" ? "hot" : "cold"}">${r.form}</span>`},
      {k: "sd", h: "SD"}, {k: "cv", h: "CV", t: "SD / mean. Lower = steadier. Compare within a position."}, {k: "floor", h: "Floor", t: "10th percentile"}, {k: "ceil", h: "Ceiling", t: "90th percentile"},
      {k: "last", h: "Last 10", f: r => spark(r.last), v: r => r.d_fp}];
    return `<h2>Trends</h2><p class="sub">Rolling form against season baseline, plus consistency. FP uses the DraftKings default weights regardless of your Config choice.</p>
      ${filters(`<label>Min MPG <input id="ming" size="3" value="${F.ming}"></label>`)}${table(cols, rows, {id: "trend", sort: {key: "d_fp"}})}`;
  },

  Lines() {
    const byId = Object.fromEntries(proj().map(p => [p.pid, p]));
    const sp = D.spread || D.meta.spread;
    const rows = LINES.map((l, i) => {
      const p = byId[l.pid]; if (!p) return "";
      const m = l.stat === "fp" ? p.c.fp : p.c[l.stat], [a, b] = sp[l.stat] || [1, 0.3], sd = Math.max(a + b * m, 0.1);
      const po = sides(l.line, m, sd).o;
      const io = impl(l.over), iu = impl(l.under), book = io && iu ? io / (io + iu) : io;   // vig removed
      const edge = book == null ? null : (po - book) * 100;
      const pick = edge == null || Math.abs(edge) < CFG.edgeMin ? "" : edge > 0 ? "OVER" : "UNDER";
      return `<tr><td class="l">${esc(p.name)}</td><td>${LABEL[l.stat]}</td><td>${num(m)}</td><td><input class="ovr ln" data-i="${i}" data-f="line" value="${esc(l.line)}"></td>
        <td><input class="ovr ln" data-i="${i}" data-f="over" value="${esc(l.over)}"></td><td><input class="ovr ln" data-i="${i}" data-f="under" value="${esc(l.under)}"></td>
        <td>${num(sd, 2)}</td><td>${num(po * 100)}%</td><td>${book == null ? "" : num(book * 100) + "%"}</td>
        <td class="${edge > 0 ? "good" : "bad"}">${edge == null ? "" : num(edge)}</td><td><b>${pick}</b></td><td><button data-del="${i}">×</button></td></tr>`;
    }).join("");
    const opts = D.projections.filter(p => !p.out).sort((a, b) => a.name.localeCompare(b.name)).map(p => `<option value="${esc(p.pid)}">${esc(p.name)} (${esc(p.team)})</option>`).join("");
    return `<h2>Lines</h2>${liveLines()}<h3>Your own lines</h3><p class="sub">Compare a projection to a posted line. The probability uses a measured-style spread (sd = a + b × projection, per stat); treat it as directional until the spread is fitted on your data. Book P(over) has the vig removed. Pick only appears past the edge threshold (Config). The FP spread is fitted on DraftKings scoring, so FP lines under other scoring are rougher.</p>
      <div class="bar"><select id="lp">${opts}</select><select id="ls">${[...STATS, ...Object.keys(COMBO), "fp"].map(s => `<option value="${s}">${LABEL[s]}</option>`).join("")}</select>
        <input id="ll" size="5" placeholder="line"><input id="lo" size="5" placeholder="over odds" value="-110"><input id="lu" size="5" placeholder="under odds" value="-110"><button id="ladd">Add</button></div>
      <div class="tw"><table><thead><tr><th class="l">Player</th><th>Stat</th><th>Proj</th><th>Line</th><th>Over</th><th>Under</th><th>SD</th><th>P(over)</th><th>Book</th><th>Edge pp</th><th>Pick</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="sub">Note: the "Proj" here follows your Median/Mean choice in Config — use Median against a line.</p>`;
  },

  Scorecard() {
    const s = D.scorecard, sm = s && s.summary;
    if (!s || !s.days || !s.days.length) return `<h2>Scorecard</h2><div class="doc"><p>No scored games yet. Projections for each slate are written to <code>data/log/accuracy_log.csv</code> <i>before</i> tip-off and never rewritten; this tab fills in once those games finish. ${s ? s.logged_rows + " rows logged so far." : ""}</p></div>`;
    const cols = [{k: "date", h: "Date", l: 1}, {k: "stamp", h: "Settings", l: 1, f: r => esc(r.stamp) + (r.current ? " ●" : "")}, {k: "n", h: "N"},
      {k: "mae_model", h: "MAE model", f: r => num(r.mae_model, 2)}, {k: "mae_season", h: "MAE season avg", f: r => num(r.mae_season, 2)}, {k: "mae_last", h: "MAE last-N", f: r => num(r.mae_last, 2)},
      {k: "edge_pct", h: "Edge %", t: "How much smaller the model's error is than the season-average baseline", f: r => `<span class="${r.edge_pct > 0 ? "good" : "bad"}">${num(r.edge_pct)}</span>`},
      {k: "bias_pct", h: "Bias %", f: r => num(r.bias_pct)}, {k: "over_pct", h: "Over %", f: r => num(r.over_pct)},
      {k: "check", h: "Check", l: 1, t: "More than 15% better than the season average is far more likely to mean the projection could see the result than that the model got brilliant", f: r => r.check ? `<span class="pill bad">${r.check}</span>` : ""}];
    const card = (v, l) => `<div class="card"><b>${v}</b><span>${l}</span></div>`;
    return `<h2>Scorecard</h2><p class="sub">Frozen-before-the-game projections vs what happened, on fantasy points (DraftKings default), players projected for 15+ minutes. Only the current settings (●) count toward the headline.</p>
      ${sm ? `<div class="cards">${card(sm.n, "player-games")}${card(num(sm.mae_model, 2), "MAE model")}${card(num(sm.mae_season, 2), "MAE season avg")}${card(num(sm.edge_pct) + "%", "edge vs season avg")}${card(num(sm.bias_pct) + "%", "bias")}${card(num(sm.over_pct) + "%", "over %")}</div>` : ""}
      ${table(cols, s.days, {id: "sc", sort: {key: "date"}})}
      <p class="sub">Rule of thumb: breakage shows in one slate, a level bias in a few, and the size of the edge needs a few weeks of games.</p>`;
  },

  Config() {
    const row = s => `<label>${LABEL[s]} <input data-sc="${s}" size="4" value="${CFG.scoring[s]}"></label>`;
    return `<h2>Config</h2><p class="sub">Browser-side settings, saved on this device. Model knobs (rolling window, damping, etc.) live in <code>pipeline/config.py</code> and take effect on the next data build.</p>
      <div class="bar"><label>Scoring preset <select id="preset">${[...Object.keys(PRESETS), "Custom"].map(p => `<option ${CFG.preset === p ? "selected" : ""}>${p}</option>`).join("")}</select></label></div>
      <div class="bar">${STATS.map(row).join("")}</div>
      <div class="bar"><label>Projection type <select id="mean"><option value="0" ${CFG.mean ? "" : "selected"}>Median-style (use vs lines)</option><option value="1" ${CFG.mean ? "selected" : ""}>Mean (use for season-long value)</option></select></label>
        <label>Line edge threshold (pp) <input id="edge" size="3" value="${CFG.edgeMin}"></label><label title="A k-pick PrizePicks entry paying M× needs M^(-1/k) per leg: 2 picks at 3× = 57.7%. Check the current payout table.">PrizePicks break-even % <input id="ppbe" size="4" value="${CFG.ppBE}"></label><label>Mean factor <b>${D.meta.mean_factor}</b> (pipeline)</label></div>
      <p class="sub">Double-double / triple-double bonuses are not modelled, so DraftKings totals run slightly below the site's.</p>
      <div class="cards">${card2("Rolling window", D.meta.rolling_window + " games")}${card2("Season", D.meta.season)}${card2("Data generated", D.meta.generated.slice(0, 16).replace("T", " ") + " UTC")}</div>
      <h3>Coverage</h3><div class="cards">${Object.entries(D.coverage).map(([k, v]) => card2(k.replace(/_/g, " "), v ?? "—")).join("")}</div>`;
    function card2(l, v) { return `<div class="card"><b>${esc(v)}</b><span>${esc(l)}</span></div>`; }
  },

  Methodology() {
    return `<h2>Methodology</h2><div class="doc">
<h3>The projection</h3><p><b>Minutes × per-minute rate × opponent × situation.</b> Minutes are a blend of the rolling window and the season average, adjusted for back-to-backs and rest. They are conditional on the player suiting up; each team's expected minutes (weighted by how often every player actually plays) are rescaled to 240, so if a starter is out, his minutes flow to the rest. Players listed Out or Doubtful are dropped; Questionable players take a small minutes haircut.</p>
<h3>Rates</h3><p>Each stat per minute, shrunk toward the position average by minutes played, so a hot 40-minute sample does not become a forecast. Blocks and steals need far more minutes to mean anything than points do, so they are shrunk harder. Early in a season, last season's games count at half weight and fade as the new ones pile up.</p>
<h3>Matchups</h3><p>Each defence is measured against league average per stat, regressed by games played, capped, and then <b>damped</b> — only a share of the measured adjustment is applied, because most of it does not carry forward. Matchup tab shows the undamped number; Projections uses the damped one. These shares are starting values; <code>python -m pipeline.backtest</code> is how they get tuned on real data.</p>
<h3>Median or mean</h3><p>Stat lines are right-skewed: a few huge nights pull the average above the typical one. <b>Median-style</b> is the number to compare to a posted line; <b>Mean</b> (× MEAN_FACTOR) is for season-long value.</p>
<h3>Lines</h3><p>P(over) uses sd = a + b × projection per stat. Book probability has the vig removed first (a −110/−110 market prices at 104.8%). Pick shows only past the edge threshold.</p>
<h3>Scorecard</h3><p>Every slate's projections are logged before the games and never rewritten, then scored against the season-average and last-N baselines. Each row carries a settings stamp so a change to any knob starts a fresh record rather than blending into the old one.</p>
<h3>Not modelled</h3><p>Opposing-offence strength inside the defence rating, pace as its own term, double-double bonuses, garbage-time and blowout risk, player-vs-player matchups, and in-browser minute redistribution when you override a teammate. Injury status comes from ESPN's feed and is only as current as the last build.</p>
<h3>Data</h3><p>ESPN's public NBA JSON endpoints (box scores, schedule, injuries), refreshed by the scheduled GitHub Action. No API key.</p></div>`;
  },
};

// ---------- routing / render -----------------------------------------------------
let page = "Projections";
function render(keepFocus, focusId) {
  const act = document.activeElement, id = focusId || act?.id, pos = act?.selectionStart;
  view().innerHTML = pages[page]();
  if (keepFocus && id) { const el = document.getElementById(id); if (el) { el.focus(); try { el.setSelectionRange(pos, pos); } catch (e) {} } }
}
function nav() {
  document.getElementById("nav").innerHTML = TABS.map(t => `<a href="#${t.replace(" ", "-")}" class="${t === page ? "on" : ""}">${t}</a>`).join("");
}
function route() {
  const h = decodeURIComponent(location.hash.slice(1)).replace("-", " ");
  const next = TABS.includes(h) ? h : "Projections";
  if (next !== page) { F.q = ""; F.pos = ""; }          // a stale search should not silently filter the next tab
  page = next;
  nav(); render();
}
window.addEventListener("hashchange", route);

document.addEventListener("change", e => {
  const t = e.target;
  if (t.classList.contains("ovr") && t.dataset.pid) {
    const v = t.value.trim();
    if (v === "" || Number.isNaN(+v)) delete OVR[t.dataset.pid]; else OVR[t.dataset.pid] = {min: Math.max(0, Math.min(48, +v))};
    store.set("ovr", OVR); render();
  } else if (t.classList.contains("ln")) {
    LINES[+t.dataset.i][t.dataset.f] = t.value; store.set("lines", LINES); render();
  } else if (t.id === "game") { F.game = t.value; render(); }
  else if (t.id === "preset") { CFG.preset = t.value; if (PRESETS[t.value]) CFG.scoring = {...PRESETS[t.value]}; store.set("cfg", CFG); render(); }
  else if (t.dataset.sc) { CFG.scoring[t.dataset.sc] = +t.value || 0; CFG.preset = "Custom"; store.set("cfg", CFG); render(); }
  else if (t.id === "mean") { CFG.mean = t.value === "1"; store.set("cfg", CFG); render(); }
  else if (t.id === "edge") { CFG.edgeMin = +t.value || 0; store.set("cfg", CFG); }
  else if (t.id === "ppbe") { CFG.ppBE = +t.value || 57.7; store.set("cfg", CFG); render(); }
});
document.addEventListener("click", e => {
  const t = e.target;
  if (t.id === "clr") { OVR = {}; store.set("ovr", OVR); render(); }
  if (t.id === "ladd") {
    const line = document.getElementById("ll").value; if (line === "") return;
    LINES.push({pid: document.getElementById("lp").value, stat: document.getElementById("ls").value, line, over: document.getElementById("lo").value, under: document.getElementById("lu").value});
    store.set("lines", LINES); render();
  }
  if (t.dataset.del != null) { LINES.splice(+t.dataset.del, 1); store.set("lines", LINES); render(); }
});

async function boot() {
  CFG = {...CFG, ...store.get("cfg", {})}; OVR = store.get("ovr", {}); LINES = store.get("lines", []);
  const names = ["projections", "matchups", "efficiency", "usage", "trends", "coverage", "meta", "scorecard", "spread", "lines"];
  await Promise.all(names.map(async n => { try { const r = await fetch(`data/${n}.json`); if (r.ok) D[n] = await r.json(); } catch (e) {} }));
  if (!D.projections) { view().innerHTML = "<p>No data found in <code>data/</code>. Run <code>python -m pipeline.build</code>.</p>"; return; }
  document.getElementById("asof").textContent = `data through ${D.coverage.asof} · slate ${D.coverage.slate_date}`;
  const msgs = [];
  if (D.meta.sample) msgs.push("<b>SAMPLE DATA.</b> Players, teams' strengths and results are synthetic — nothing here is a real NBA projection. Run the fetch step to load real data.");
  if (D.meta.preseason) {
    const m = D.meta.minute_mult;
    const src = D.meta.mult_source === "fallback" ? " — a rough default, NOT learned from data yet" : " — learned from last preseason";
    msgs.push(m ? `<b>PRESEASON slate.</b> Minutes are scaled by tier (${Object.entries(m).map(([t, v]) => `${t} ×${v}`).join(", ")}; T1 = 30+ mpg)${src}, and each projection assumes the player suits up — stars often sit. Not logged to the Scorecard.`
                : "<b>PRESEASON slate with NO minutes adjustment</b> — stars will be projected for regular-season minutes. Run <code>python -m pipeline.preseason_minutes</code>.");
  }
  if (msgs.length) { const b = document.getElementById("banner"); b.hidden = false; b.innerHTML = msgs.join("<br>"); }
  route();
}
boot();

"use strict";
// ---------- state ----------------------------------------------------------
const TABS = ["Projections", "Live", "Game Board", "Matchups", "Team Tiers", "Shots", "Efficiency", "Usage", "Trends", "Lines", "Scorecard", "Results", "Config", "Methodology"];
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
const F = {q: "", pos: "", ming: 10, lstat: "", lgame: "", lpicks: false, rday: "", vstat: "pts", sview: "chart", cteam: "", cplayer: "", cheat: "fg", cdots: "all", rmode: null, rlines: false, rpicks: false};
const RES = {};                                     // results/<date>.json cache
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


// ---------- Live tab: polls ESPN straight from the browser (no credits, no CI) ------------------------------
const ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba";
const LIVE = {games: null, box: {}, err: null, ts: null, timer: null};
function parseBox(j) {
  const rows = [];
  for (const tm of (j.boxscore?.players || [])) {
    const ab = tm.team?.abbreviation || tm.team?.shortDisplayName || "";
    for (const grp of tm.statistics || []) {
      const k = grp.keys || [], ix = n => k.indexOf(n);
      for (const a of grp.athletes || []) {
        const st = a.stats || []; if (a.didNotPlay || !st.length) continue;
        const mn = parseFloat(st[ix("minutes")]); if (!(mn > 0)) continue;
        const n = key => { const v = st[ix(key)]; return v == null ? 0 : +v || 0; };
        rows.push({pid: String(a.athlete.id), name: a.athlete.displayName, team: ab, min: mn, pts: n("points"), reb: n("rebounds"), ast: n("assists"),
          fg3m: +String(st[ix("threePointFieldGoalsMade-threePointFieldGoalsAttempted")] ?? "0").split("-")[0] || 0, stl: n("steals"), blk: n("blocks"), tov: n("turnovers")});
      }
    }
  }
  return rows;
}
async function liveRefresh() {
  try {
    const sb = await (await fetch(`${ESPN}/scoreboard`, {cache: "no-store"})).json();
    LIVE.games = (sb.events || []).map(e => {
      const c = e.competitions[0], st = e.status.type, t = {};
      for (const x of c.competitors) t[x.homeAway] = {ab: x.team.abbreviation || x.team.shortDisplayName || x.team.displayName || "?", score: +x.score || 0};
      return {id: e.id, state: st.state, detail: st.shortDetail, home: t.home, away: t.away, tip: e.date};
    });
    await Promise.all(LIVE.games.filter(g => g.state === "in" || (g.state === "post" && !LIVE.box[g.id])).map(async g => {
      LIVE.box[g.id] = parseBox(await (await fetch(`${ESPN}/summary?event=${g.id}`, {cache: "no-store"})).json());
    }));
    LIVE.err = null; LIVE.ts = Date.now();
  } catch (e) { LIVE.err = String(e && e.message || e); }
  if (page === "Live") render(true);
}
function liveStart() { if (!LIVE.timer) { liveRefresh(); LIVE.timer = setInterval(() => { if (!document.hidden) liveRefresh(); }, 30000); } }
function liveStop() { clearInterval(LIVE.timer); LIVE.timer = null; }

// ---------- Results: pregame projection vs final box score, graded against the frozen pregame lines -------------------
const grade = (a, line, side) => a === line ? null : (side === "O" ? a > line : a < line);
const RES_PENDING = {};
const rdir = () => F.rmode ? "results_rehearsal" : "results";
async function loadResultsDay(date) {
  const key = rdir() + "/" + date;
  if (!date || RES[key] || RES_PENDING[key]) return;
  RES_PENDING[key] = true;
  try { RES[key] = await (await fetch(`data/${key}.json`)).json(); } catch (e) { RES[key] = {error: String(e)}; }
  if (page === "Results") render(true);
}
const pct1 = (h, n) => n ? `${(h / n * 100).toFixed(1)}% <span class="mut">(${h}/${n})</span>` : "—";

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
    const started = Date.now() >= Date.parse(r.commence);
    const out = {started, name: p.name, pos: p.pos, team: p.team, game: r.game, stat: r.stat, m, c, r, pp, ud: r.dfs.underdog ?? r.dfs.pick6, out: p.c.min === 0};
    if (c) { const s = sides(c.line, m, sd); out.po = s.o; out.edge = (s.o - c.p_over) * 100; out.pick = started ? "LIVE" : out.out ? "OUT" : Math.abs(out.edge) >= CFG.edgeMin ? (out.edge > 0 ? "OVER" : "UNDER") : ""; }
    if (pp != null) { const s = sides(pp, m, sd); out.side = s.o >= s.u ? "OVER" : "UNDER"; out.pw = Math.max(s.o, s.u); out.ppEdge = (out.pw - BE) * 100;
      out.ppPick = started ? "LIVE" : out.out ? "OUT" : out.ppEdge >= CFG.edgeMin ? "PP " + out.side : ""; out.gap = c ? pp - c.line : null; }
    return out;
  }).filter(Boolean).filter(passes);
  if (F.lstat) rows = rows.filter(r => r.stat === F.lstat);
  if (F.lgame) rows = rows.filter(r => r.game === F.lgame);
  if (F.lpicks) rows = rows.filter(r => (r.pick && r.pick !== "OUT" && r.pick !== "LIVE") || (r.ppPick && r.ppPick !== "OUT" && r.ppPick !== "LIVE"));
  const tip = r => r.r.books.map(b => `${b.b} ${b.line} (${b.over ?? "-"}/${b.under ?? "-"})`).join("\n");
  const cols = [{k: "name", h: "Player", l: 1, f: r => esc(r.name)}, {k: "team", h: "Team", l: 1}, {k: "game", h: "Game", l: 1, f: r => esc(r.game) + (r.started ? ` <span class="pill hot" title="Tipped off: these are the last PRE-game lines. The model's pregame probability no longer applies, so no pick is shown.">LIVE</span>` : "")}, {k: "stat", h: "Stat", l: 1, f: r => LABEL[r.stat]},
    {k: "m", h: "Proj", t: "Median-style projection with your Min OVR overrides", f: r => num(r.m)},
    {k: "cl", h: "Cons line", t: "Median sportsbook line; hover for every book", v: r => r.c?.line, f: r => r.c ? `<span title="${esc(tip(r))}">${r.c.line} <span class="mut">${r.c.n}/${r.c.n_books}</span></span>` : ""},
    {k: "cp", h: "Cons P(over)", t: "Average vig-free P(over) of the books at the consensus line", v: r => r.c?.p_over, f: r => r.c ? num(r.c.p_over * 100) + "%" : ""},
    {k: "fo", h: "Fair odds", t: "Over / under, from the consensus probability", v: r => r.c?.p_over, f: r => r.c ? `${amer(r.c.p_over)} / ${amer(1 - r.c.p_over)}` : ""},
    {k: "po", h: "Model P(over)", v: r => r.po, f: r => r.po == null ? "" : num(r.po * 100) + "%"},
    {k: "edge", h: "Edge pp", v: r => r.edge, f: r => r.edge == null ? "" : `<span class="${r.edge > 0 ? "good" : "bad"}">${num(r.edge)}</span>`},
    {k: "pick", h: "Pick", l: 1, f: r => r.pick ? `<b>${r.pick}</b>${r.pick === "OUT" || r.pick === "LIVE" ? "" : warn(r.edge)}` : ""},
    {k: "pp", h: "PrizePicks", v: r => r.pp, f: r => r.pp ?? ""},
    {k: "gap", h: "PP − cons", t: "Positive: PrizePicks line is higher than the books' (easier UNDER); negative: lower (easier OVER)", v: r => r.gap, f: r => r.gap == null ? "" : `<span class="${r.gap < 0 ? "good" : r.gap > 0 ? "bad" : "mut"}">${r.gap > 0 ? "+" : ""}${num(r.gap)}</span>`},
    {k: "pw", h: "PP P(win)", t: "Model probability of the better side at the PrizePicks line", v: r => r.pw, f: r => r.pw == null ? "" : `${r.side[0]} ${num(r.pw * 100)}%`},
    {k: "ppEdge", h: "PP edge pp", t: `vs your break-even of ${CFG.ppBE}% (Config)`, v: r => r.ppEdge, f: r => r.ppEdge == null ? "" : `<span class="${r.ppEdge > 0 ? "good" : "bad"}">${num(r.ppEdge)}</span>`},
    {k: "ppPick", h: "PP pick", l: 1, f: r => r.ppPick ? `<b>${r.ppPick}</b>${r.ppPick === "OUT" || r.ppPick === "LIVE" ? "" : warn(r.ppEdge)}` : ""},
    {k: "ud", h: "UD/Pick6", v: r => r.ud, f: r => r.ud ?? ""}];
  const games = [...new Set(L.rows.map(r => r.game))].sort(), stats = [...new Set(L.rows.map(r => r.stat))];
  const extra = `<label>Stat <select id="lstat"><option value="">All</option>${stats.map(s => `<option value="${s}" ${F.lstat === s ? "selected" : ""}>${LABEL[s] || s}</option>`).join("")}</select></label>
    <label>Game <select id="lgame"><option value="">All</option>${games.map(g => `<option ${F.lgame === g ? "selected" : ""}>${esc(g)}</option>`).join("")}</select></label>
    <label><input type="checkbox" id="lpicks" ${F.lpicks ? "checked" : ""}> picks only</label>`;
  return `<p class="sub">Sportsbook consensus (median line; vig removed) beside PrizePicks / Underdog, with the model's edge against each${credits}. Updated ${mins < 90 ? mins + " min" : Math.round(mins / 60) + " h"} ago${mins > 360 ? " — <b>stale, lines move</b>" : ""}. DFS prices are nominal, so PrizePicks edge is measured against your break-even (Config) rather than odds. A k-pick entry paying M× needs M^(−1/k) per leg.</p>
    ${filters(extra)}${table(cols, rows, {id: "live", sort: {key: "edge"}})}`;
}

function vsPosition() {
  const T = D.tiers;
  if (!T || !T.vspos || !T.vspos.length) return "";
  const st = F.vstat, rel = T.vspos_rel || {};
  const cell = pos => ({k: pos, h: {G: "Guards", F: "Forwards", C: "Centers"}[pos], t: `Reliability (split-half): ${rel[pos + "_" + st] ?? "n/a"}`,
    v: r => r[pos + "_" + st], f: r => { const x = r[pos + "_" + st]; return x == null ? "" : `<span class="${x > 1 ? "good" : x < -1 ? "bad" : "mut"}">${x > 0 ? "+" : ""}${num(x, 1)}%</span>`; }});
  return `<h3>Vs position</h3><p class="sub">Per-minute ${LABEL[st]} each defence allows to guards, forwards and centers, relative to the league at that position (green = soft). Shrunk toward zero by minutes seen. <b>Display only:</b> as a projection input it added nothing in a walk-forward test (the position-specific part beyond the team-wide matchup was noise and the two halves of the season disagreed), so the projections do not use it. Split-half reliability for ${LABEL[st]}: guards ${rel["G_" + st] ?? "–"}, forwards ${rel["F_" + st] ?? "–"}, centers ${rel["C_" + st] ?? "–"}.</p>
    <div class="bar"><label>Stat <select id="vstat">${STATS.map(s => `<option value="${s}" ${s === st ? "selected" : ""}>${LABEL[s]}</option>`).join("")}</select></label></div>
    ${table([{k: "team", h: "Team", l: 1}, cell("G"), cell("F"), cell("C")], T.vspos, {id: "vspos", sort: {key: "G"}})}`;
}


// ---------- shot chart: a defence's allowed-shot map under a shooter's shots --------------------------------------------------
const SCP = {data: null, pending: false};
async function loadShotPlayers() {
  if (SCP.data || SCP.pending) return;
  SCP.pending = true;
  try { SCP.data = await (await fetch("data/shotchart_players.json")).json(); } catch (e) { SCP.data = {}; }
  if (page === "Shots") render(true);
}
const HEAT = {                                      // diverging pair, cool = tough defence, warm = soft defence, neutral midpoint; equal steps per arm
  light: {mid: [240, 239, 236], cold: [42, 111, 187], warm: [200, 64, 42]},
  dark: {mid: [56, 56, 53], cold: [91, 155, 220], warm: [239, 122, 90]},
};
const HEAT_STEPS = 5;
function heatColor(v, cap) {                        // v in [-cap, cap] -> rgb string, quantised into HEAT_STEPS per arm
  const P = HEAT[matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"];
  const t = Math.min(1, Math.abs(v) / cap), k = Math.ceil(t * HEAT_STEPS - 1e-9) / HEAT_STEPS, pole = v < 0 ? P.cold : P.warm;
  return `rgb(${P.mid.map((m, i) => Math.round(m + (pole[i] - m) * k)).join(",")})`;
}
const SC_Y = y => 41.75 - y;                         // court feet -> svg y (basket at the bottom of the picture)
function courtLines() {
  const st = 'fill="none" stroke="var(--mut)" stroke-width="0.18" stroke-linejoin="round"';
  const r = Math.sqrt(23.75 ** 2 - 22 ** 2);
  return `<g ${st}>
    <rect x="0" y="0" width="50" height="47"/>
    <rect x="17" y="${SC_Y(13.75)}" width="16" height="${13.75 + 5.25}"/>
    <path d="M19 ${SC_Y(13.75)} A6 6 0 0 1 31 ${SC_Y(13.75)}"/>
    <path d="M19 ${SC_Y(13.75)} A6 6 0 0 0 31 ${SC_Y(13.75)}" stroke-dasharray="0.6 0.6"/>
    <path d="M21 ${SC_Y(0)} A4 4 0 0 1 29 ${SC_Y(0)}"/>
    <line x1="22" y1="${SC_Y(-1.25)}" x2="28" y2="${SC_Y(-1.25)}"/>
    <circle cx="25" cy="${SC_Y(0)}" r="0.75"/>
    <path d="M3 ${SC_Y(-5.25)} L3 ${SC_Y(r)} A23.75 23.75 0 0 1 47 ${SC_Y(r)} L47 ${SC_Y(-5.25)}"/>
    <path d="M19 0 A6 6 0 0 0 31 0"/>
  </g>`;
}
const SC_SMOOTH = new Map();
function scSmooth(a, cols) {                           // 3x3 kernel [1 2 1; 2 4 2; 1 2 1] / 4: neighbours lend their shots, so one lucky square cannot colour the court
  if (SC_SMOOTH.has(a)) return SC_SMOOTH.get(a);
  const rows = a.length / cols, out = new Array(a.length).fill(0);
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    let t = 0;
    for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
      const rr = r + dr, cc = c + dc;
      if (rr < 0 || rr >= rows || cc < 0 || cc >= cols) continue;
      t += a[rr * cols + cc] * (dr === 0 && dc === 0 ? 4 : (dr === 0 || dc === 0 ? 2 : 1));
    }
    out[r * cols + c] = t / 4;
  }
  SC_SMOOTH.set(a, out);
  return out;
}
function shotChartSVG(team, pid) {
  const G = D.shotchart, c = G.cols, CELL = G.cell, tm0 = G.teams[team];
  const ln = scSmooth(G.lg.n, c), lm = scSmooth(G.lg.m, c), tn = scSmooth(tm0.n, c), tmk = scSmooth(tm0.m, c);
  const tot = tn.reduce((a, b) => a + b, 0), Ltot = ln.reduce((a, b) => a + b, 0), K = 60;
  let cells = "";
  if (F.cheat !== "none") {
    for (let i = 0; i < ln.length; i++) {
      if (ln[i] < 160) continue;
      const col = i % c, row = (i - col) / c, y1 = G.y0 + (row + 1) * CELL, lf = lm[i] / ln[i];
      let v, cap, tip;
      if (F.cheat === "fg") {
        const sh = (tmk[i] + K * lf) / (tn[i] + K); v = (sh - lf) * 100; cap = 6;
        tip = `${team} allow about ${(sh * 100).toFixed(0)}% around here vs ${(lf * 100).toFixed(0)}% league (${v > 0 ? "+" : ""}${v.toFixed(1)} pts); ${tm0.n[i]} attempts in this square`;
      } else {
        const exp = ln[i] / Ltot * tot; v = (tn[i] + 12) / (exp + 12) - 1; cap = 0.6;
        tip = `${team} face ${tm0.n[i]} attempts in this square; around here ${(v > 0 ? "+" : "")}${(v * 100).toFixed(0)}% vs the league's share`;
      }
      cells += `<rect class="sccell" data-tip="${esc(tip)}" x="${(col * CELL + 0.1).toFixed(2)}" y="${(SC_Y(y1) + 0.1).toFixed(2)}" width="${CELL - 0.2}" height="${CELL - 0.2}" rx="0.4" fill="${heatColor(v, cap)}"/>`;
    }
  }
  let dots = "", n = 0;
  const sh = pid && SCP.data && SCP.data[pid];
  if (sh && F.cdots !== "none") {
    for (let i = 0; i < sh.length; i += 3) {
      const made = sh[i + 2] === 1;
      if ((F.cdots === "made" && !made) || (F.cdots === "miss" && made)) continue;
      n++;
      dots += made ? `<circle cx="${sh[i]}" cy="${SC_Y(sh[i + 1])}" r="0.42" fill="var(--fg)" fill-opacity="0.8" stroke="var(--bg)" stroke-width="0.1"/>`
                   : `<circle cx="${sh[i]}" cy="${SC_Y(sh[i + 1])}" r="0.36" fill="none" stroke="var(--fg)" stroke-opacity="0.7" stroke-width="0.14"/>`;
    }
  }
  return {n, svg: `<svg viewBox="-1 -1 52 49" class="scchart" role="img" aria-label="Shot chart: ${esc(team)} defence with shooter overlay"><g>${cells}</g>${courtLines()}<g pointer-events="none">${dots}</g></svg>`};
}
function shotChartView(T) {
  const G = D.shotchart;
  if (!G) return `<p class="sub">Shot chart data is not built yet.</p>`;
  loadShotPlayers();
  const teams = Object.keys(G.teams).sort(), players = T.players;
  const byId = Object.fromEntries(players.map(p => [p.pid, p]));
  if (!F.cplayer || !byId[F.cplayer]) {                                   // default: the best projected player on the slate who has shot data
    const top = [...D.projections].filter(p => !p.out && byId[p.pid]).sort((a, b) => b.fp - a.fp)[0];
    F.cplayer = top ? top.pid : players[0].pid; F.cteam = "";
  }
  const pl = byId[F.cplayer];
  if (!F.cteam || !G.teams[F.cteam]) {                                    // default defence: tonight's opponent, else the first team
    const pr = D.projections.find(p => p.pid === F.cplayer);
    F.cteam = pr && G.teams[pr.opp] ? pr.opp : (G.teams[pl.team] ? teams.find(t => t !== pl.team) : teams[0]);
  }
  const {n, svg} = shotChartSVG(F.cteam, F.cplayer);
  const opt = (v, cur, label) => `<option value="${v}" ${v === cur ? "selected" : ""}>${label}</option>`;
  const dark = matchMedia("(prefers-color-scheme: dark)").matches, P = HEAT[dark ? "dark" : "light"];
  const sw = Array.from({length: 2 * HEAT_STEPS + 1}, (_, i) => `<i style="background:${heatColor(i < HEAT_STEPS ? -(HEAT_STEPS - i) : i - HEAT_STEPS, HEAT_STEPS)}"></i>`).join("");
  const legend = F.cheat === "none" ? "" : `<div class="sclegend"><span>${F.cheat === "fg" ? "Tougher: allows fewer makes" : "Fewer shots from here"}</span><span class="scsw">${sw}</span><span>${F.cheat === "fg" ? "Softer: allows more makes" : "More shots from here"}</span></div>`;
  const ZN = {rim: "Rim", paint: "Paint", mid: "Mid-range", corner3: "Corner 3", arc3: "Above-break 3"}, Z = Object.keys(ZN);
  const dr = T.defense.find(r => r.team === F.cteam) || {};
  const rows = Z.map(z => ({z: ZN[z], mix: pl[z + "_mix"], fg: pl[z + "_fg"], lg: T.lg_fg[z], dfg: dr[z + "_fg"], dfreq: dr[z + "_freq"],
    edge: pl[z + "_fg"] == null || dr[z + "_fg"] == null ? null : dr[z + "_fg"]}));
  const sg = x => x == null ? "" : `${x > 0 ? "+" : ""}${num(x, 1)}`;
  const rel = T.defense_rel || {};
  const cols = [{k: "z", h: "Zone", l: 1}, {k: "mix", h: "His shots %", f: r => num(r.mix, 0)}, {k: "fg", h: "His FG%", f: r => num(r.fg, 0)},
    {k: "lg", h: "League FG%", f: r => num(r.lg, 0)},
    {k: "dfg", h: `${esc(F.cteam)} allow`, t: "FG% allowed in this zone minus the league FG% there, in points: + = soft, - = tough", f: r => `<span class="${r.dfg > 0.5 ? "good" : r.dfg < -0.5 ? "bad" : "mut"}">${sg(r.dfg)}</span>`},
    {k: "dfreq", h: `${esc(F.cteam)} freq`, t: "% more (+) or fewer (-) of the shots this defence faces come from this zone than the league average", f: r => sg(r.dfreq)}];
  return `<div class="bar scbar">
      <label>Shooter <input id="cplayer" list="scplayers" value="${esc(pl.name)}" size="22" autocomplete="off"></label>
      <datalist id="scplayers">${players.map(p => `<option value="${esc(p.name)}">${esc(p.team)}</option>`).join("")}</datalist>
      <label>Defence <select id="cteam">${teams.map(t => opt(t, F.cteam, t)).join("")}</select></label>
      <label>Under the dots <select id="cheat">${opt("fg", F.cheat, "FG% allowed vs league")}${opt("freq", F.cheat, "Where shots come from")}${opt("none", F.cheat, "Nothing (court only)")}</select></label>
      <label>Shots <select id="cdots">${opt("all", F.cdots, "Makes and misses")}${opt("made", F.cdots, "Makes only")}${opt("miss", F.cdots, "Misses only")}${opt("none", F.cdots, "Hide")}</select></label>
    </div>
    <div class="scwrap"><div>${svg}${legend}<div class="sclegend"><span><svg width="14" height="14" viewBox="-7 -7 14 14"><circle r="4.5" fill="var(--fg)" fill-opacity=".8"/></svg> make</span><span><svg width="14" height="14" viewBox="-7 -7 14 14"><circle r="4" fill="none" stroke="var(--fg)" stroke-opacity=".7" stroke-width="1.6"/></svg> miss</span><span class="mut">${SCP.data ? `${n} of ${pl.n} shots shown` : "loading shots…"}</span></div></div>
      <div class="scside"><h3>${esc(pl.name)} (${esc(pl.team)}) vs ${esc(F.cteam)}</h3>
        <p class="sub">Where he shoots and how well, next to what this defence allows from each zone. ${esc(pl.name)}: ${num(pl.pps, 2)} points per shot against ${num(pl.xpps, 2)} expected from his locations.</p>
        ${table(cols, rows, {id: "sczone"})}
        <p class="sub">Read the colours as cells: warm squares are spots where ${esc(F.cteam)} have let the league shoot better than average, cool squares where they have been tough (smoothed toward the league; small squares are mostly noise). Only the rim and paint numbers are reliable season to season (split-half ${rel.rim_fg} and ${rel.paint_fg}); mid-range and three-point FG% allowed are mostly luck. The chart is for reading a matchup and does not feed the projections.</p>
      </div></div>`;
}
document.addEventListener("pointermove", e => {
  let tip = document.getElementById("sctip");
  const t = e.target.closest && e.target.closest(".sccell");
  if (!t) { if (tip) tip.hidden = true; return; }
  if (!tip) { tip = document.createElement("div"); tip.id = "sctip"; document.body.appendChild(tip); }
  tip.textContent = t.dataset.tip; tip.hidden = false;
  tip.style.left = Math.min(e.clientX + 14, innerWidth - 280) + "px"; tip.style.top = (e.clientY + 14) + "px";
});

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
    const h0 = D.projections.find(p => p.team === home && p.exp_margin != null);
    const env = h0 ? ` Expected margin ${esc(home)} ${h0.exp_margin >= 0 ? "+" : ""}${num(h0.exp_margin)} (from each team's average point differential, a stand-in for the spread); pace ${h0.pace_f >= 1 ? "+" : ""}${num((h0.pace_f - 1) * 100)}% vs league.` : "";
    return `<h2>Game Board</h2><p class="sub">Pick a game; both teams ranked by projected fantasy points.${env}</p>
      <div class="bar"><select id="game">${games.map(g => `<option value="${g}" ${g === F.game ? "selected" : ""}>${g.split("|")[1]} @ ${g.split("|")[0]}</option>`).join("")}</select></div>
      <div class="two">${mk(away)}${mk(home)}</div>`;
  },

  Matchups() {
    const cols = [{k: "team", h: "Team", l: 1}, {k: "playing", h: "Plays", l: 1, f: r => r.playing ? "yes" : ""}, {k: "games", h: "G"},
      ...STATS.map(s => ({k: s + "_raw", h: LABEL[s], t: "What this defence allowed vs league, regressed by sample (not damped)", f: r => pct(r[s + "_raw"])}))];
    return `<h2>Matchups</h2><p class="sub">What each defence has allowed relative to league, regressed toward 1.0 by games played. Green = soft (stat inflates), red = tough. The projection uses a damped share of these (see Methodology). Opposing-offence strength is not removed.</p>
      ${table(cols, D.matchups, {id: "mu", sort: {key: "pts_raw"}})}
      ${vsPosition()}`;
  },

  "Team Tiers"() {
    const T = D.tiers;
    if (!T || !T.rows || !T.rows.length) return `<h2>Team Tiers</h2><p class="sub">No team data yet.</p>`;
    const rel = T.reliability || {}, rk = (v, n = 30) => `<span class="${v <= 6 ? "good" : v > n - 6 ? "bad" : ""}">${v}</span>`;
    const cols = [{k: "team", h: "Team", l: 1}, {k: "tier", h: "Tier", t: "1 = best fifth of the league by net rating, 5 = worst"},
      {k: "g", h: "G"}, {k: "rec", h: "W-L", v: r => r.w / Math.max(r.g, 1), f: r => `${r.w}-${r.l}`},
      {k: "off", h: "Off Rtg", t: "Points per 100 possessions"}, {k: "off_rk", h: "Off rk", f: r => rk(r.off_rk)},
      {k: "def", h: "Def Rtg", t: "Points allowed per 100 possessions. Lower is better."}, {k: "def_rk", h: "Def rk", f: r => rk(r.def_rk)},
      {k: "net", h: "Net", f: r => `<b class="${r.net > 0 ? "good" : "bad"}">${num(r.net)}</b>`}, {k: "net_rk", h: "Net rk", f: r => rk(r.net_rk)},
      {k: "net10", h: "Net L10", t: "Net rating over the last 10 games", f: r => `<span class="${r.net10 > 0 ? "good" : "bad"}">${num(r.net10)}</span>`}, {k: "pace", h: "Pace", t: "Possessions per game, both teams"}];
    return `<h2>Team Tiers</h2><p class="sub">${T.season ? `Season ending ${T.season}. ` : ""}Offensive and defensive rating (points per 100 possessions, possessions estimated from the box score, so levels run a few percent high but rankings hold), pace, and net rating. For reading a slate; it does <b>not</b> feed the projections. Split-half reliability across the season (odd vs even game days; 1 = all signal): offence ${rel.off ?? "–"}, defence ${rel.def ?? "–"}, net ${rel.net ?? "–"}, pace ${rel.pace ?? "–"}. Anything well under 0.5 would be mostly noise; these are usable but not gospel.</p>
      ${table(cols, T.rows, {id: "tiers", sort: {key: "net"}})}`;
  },

  Shots() {
    const T = D.shots;
    if (!T) return `<h2>Shots</h2><p class="sub">No shot-location data yet. It is pulled from ESPN play-by-play by the daily refresh.</p>`;
    const ZN = {rim: "Rim", paint: "Paint", mid: "Mid", corner3: "Corner 3", arc3: "Arc 3"}, Z = Object.keys(ZN);
    const toggle = `<div class="bar"><label>View <select id="sview"><option value="chart" ${F.sview === "chart" ? "selected" : ""}>Shot chart (defence under a shooter)</option><option value="team" ${F.sview === "team" ? "selected" : ""}>Team shot defense</option><option value="player" ${F.sview === "player" ? "selected" : ""}>Player shot profile</option></select></label></div>`;
    const sg = x => x == null ? "" : `${x > 0 ? "+" : ""}${num(x, 1)}`;
    let body, note;
    if (F.sview === "chart") {
      body = shotChartView(T);
      note = "";
    } else if (F.sview === "team") {
      const rel = T.defense_rel || {};
      const cols = [{k: "team", h: "Team", l: 1}, ...Z.flatMap(z => [
        {k: z + "_freq", h: ZN[z] + " freq", t: `% more (+) or fewer (-) of the shots this defence faces come from here than the league average. Split-half reliability ${rel[z + "_freq"]}`, f: r => sg(r[z + "_freq"])},
        {k: z + "_fg", h: ZN[z] + " FG%", t: `FG% it allows from here minus the league FG% there, in points (negative = better defence). Shrunk toward the league. Split-half reliability ${rel[z + "_fg"]}`,
          f: r => `<span class="${r[z + "_fg"] < -0.5 ? "bad" : r[z + "_fg"] > 0.5 ? "good" : "mut"}">${sg(r[z + "_fg"])}</span>`}])];
      body = table(cols, T.defense, {id: "sdef", sort: {key: "rim_fg"}});
      note = `Where each defence lets teams shoot from (freq) and how well they shoot from there (FG% vs league). Green = soft (offence does better), red = tough. Split-half reliability (odd vs even game days; 1 = all signal): shot mix allowed is steady (rim ${rel.rim_freq}, paint ${rel.paint_freq}, arc 3 ${rel.arc3_freq}), and so is FG% allowed at the rim (${rel.rim_fg}) and in the paint (${rel.paint_fg}); mid-range (${rel.mid_fg}), corner 3 (${rel.corner3_fg}) and above-break 3 (${rel.arc3_fg}) FG% allowed are mostly luck, so ignore those. Hover a header for details.`;
    } else {
      const rows = T.players.filter(passes);
      const cols = [...nameCols, {k: "n", h: "Shots", t: "Field-goal attempts logged"},
        ...Z.map(z => ({k: z + "_mix", h: ZN[z] + " %", t: "Share of his shots from this zone"})),
        {k: "ast_pct", h: "Ast %", t: "Share of his shots that were assisted"},
        {k: "xpps", h: "xPPS", t: "Expected points per shot from where he shoots (league FG% by zone). Location only: ESPN has no defender distance."},
        {k: "pps", h: "PPS", t: "Actual points per shot (field goals only)"},
        {k: "make", h: "Make", t: "PPS minus xPPS: shooting better (+) or worse (-) than his shot locations imply", f: r => `<span class="${r.make > 0.02 ? "good" : r.make < -0.02 ? "bad" : "mut"}">${r.make > 0 ? "+" : ""}${num(r.make, 3)}</span>`}];
      body = `${filters("")}${table(cols, rows, {id: "splay", sort: {key: "n"}})}`;
      note = `Shot quality is location only: xPPS is the points per shot an average player would get from his zones, so a high xPPS means good looks (rim and corner threes), not open ones. Make = how far his actual shooting sits above or below that. It is only partly skill: split-half reliability of Make across the season is ${T.skill_rel} (${T.skill_n} players), so small gaps are mostly luck.`;
    }
    return `<h2>Shots</h2><p class="sub">${num(T.shots, 0)} field-goal attempts from ${T.games} games, from ESPN play-by-play coordinates. <b>Display only</b>: tested as projection inputs (zone defence matched to a player's shot mix, and shot-making vs shot locations) neither survived the replication test, so the projections do not use them (see Methodology). ${note}</p>
      ${toggle}${body}`;
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

  Live() {
    if (LIVE.err && !LIVE.games) return `<h2>Live</h2><p class="sub">Couldn't load live data from ESPN in this browser (${esc(LIVE.err)}). If this keeps happening, ESPN is blocking cross-site requests; tell whoever maintains the site.</p>`;
    if (!LIVE.games) return `<h2>Live</h2><p class="sub">Loading today's games…</p>`;
    const byId = Object.fromEntries(projMed().map(p => [p.pid, p]));
    const rateOf = pid => { const p = byId[pid]; if (p && p.c.min > 0) return {min: p.c.min, per: st => p.c[st] / p.c.min};      // today's slate: matchup-adjusted, honours Min OVR
      const q = D.players && D.players[pid]; return q ? {min: q.m, per: st => q.r[STATS.indexOf(st)]} : null; };                 // anyone else: season rates, no matchup
    const lineOf = {};                                           // pid|stat -> consensus line, else PrizePicks
    for (const r of (D.lines?.rows || [])) lineOf[r.pid + "|" + r.stat] = r.cons?.line ?? r.dfs?.prizepicks ?? null;
    const order = {in: 0, pre: 1, post: 2}, games = [...LIVE.games].sort((a, b) => order[a.state] - order[b.state] || Date.parse(a.tip) - Date.parse(b.tip));
    const ago = LIVE.ts ? Math.round((Date.now() - LIVE.ts) / 1000) : null;
    const STATS_SHOWN = ["pts", "reb", "ast", "fg3m"];
    const card = g => {
      const head = `<strong>${esc(g.away.ab)} ${g.away.score}</strong> @ <strong>${esc(g.home.ab)} ${g.home.score}</strong>`;
      if (g.state === "pre") return `<div class="card"><span>${head.replace(/ \d+<\/strong>/g, "</strong>")}</span><br><span class="mut">tip ${new Date(g.tip).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})}</span></div>`;
      const badge = g.state === "in" ? `<span class="pill hot">LIVE</span> ` : `<span class="pill">FINAL</span> `;
      const rows = (LIVE.box[g.id] || []).map(b => {
        const q = rateOf(b.pid), remain = g.state === "post" || !q ? 0 : Math.max(q.min - b.min, 0), o = {...b, q};
        for (const st of STATS_SHOWN) { o["f_" + st] = q ? b[st] + remain * q.per(st) : null; o["l_" + st] = lineOf[b.pid + "|" + st] ?? null; }
        return o;
      });
      const cell = st => ({k: st, h: LABEL[st], t: "now → projected final (model rate × minutes still expected); [line] = consensus, else PrizePicks. Green = already over the line, orange = on pace to go over.",
        v: r => r["f_" + st] ?? r[st], f: r => { const f = r["f_" + st], l = r["l_" + st]; if (f == null && l == null) return String(r[st]);
          const cls = l != null ? (r[st] > l ? "good" : (f ?? r[st]) > l ? "" : "mut") : "";
          return `${r[st]}${f != null ? ` <span class="mut">→</span> <span class="${cls}">${num(f)}</span>` : ""}${l != null ? ` <span class="mut">[${l}]</span>` : ""}`; }});
      const cols = [{k: "name", h: "Player", l: 1}, {k: "team", h: "Team", l: 1}, {k: "min", h: "MIN", f: r => num(r.min, 0)}, ...STATS_SHOWN.map(cell)];
      return `<div class="card" style="grid-column:1/-1"><div>${badge}${head} <span class="mut">· ${esc(g.detail)}</span></div>
        <div style="margin-top:8px">${rows.length ? table(cols, rows, {id: "live" + g.id, sort: {key: "min"}}) : `<span class="mut">No box score yet.</span>`}</div></div>`;
    };
    return `<h2>Live</h2><p class="sub">Today's games, updated every 30 s${ago != null ? ` (refreshed ${ago}s ago)` : ""}${LIVE.err ? ` — <b>last refresh failed: ${esc(LIVE.err)}</b>` : ""}.
      Each stat shows <b>now → projected final</b> from the player's per-minute rate and the minutes still expected, with the posted line in brackets. Players in today's slate use the matchup-adjusted projection (and your Min OVR); everyone else uses season rates with no matchup adjustment. Blowouts and foul trouble aren't modelled.</p>
      ${games.length ? `<div class="cards" style="grid-template-columns:1fr">${games.map(card).join("")}</div>` : `<p class="sub">No games on ESPN's scoreboard today.</p>`}`;
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

  Results() {
    const has = i => i && i.days && i.days.length;
    if (!has(D.rIdx) && has(D.rIdxR) && F.rmode === null) F.rmode = "rehearsal";   // nothing real yet: show the dress rehearsal
    const I = F.rmode ? D.rIdxR : D.rIdx;
    const toggle = has(D.rIdxR) || F.rmode ? `<div class="bar"><label>Showing <select id="rmode"><option value="" ${F.rmode ? "" : "selected"}>Regular season (the real record)</option><option value="rehearsal" ${F.rmode ? "selected" : ""}>Preseason rehearsal</option></select></label></div>` : "";
    const banner = F.rmode ? `<p class="banner">PRESEASON REHEARSAL — a dry run of this tab on preseason games, projected the morning of with the preseason minutes adjustment. Starters sit and rotations are odd, so these numbers say nothing about regular-season accuracy; they are here to check that logging, scoring and grading work. Preseason lines are not available, so the hit-rate columns stay empty.</p>` : "";
    if (!has(I))
      return `<h2>Results</h2>${toggle}${banner}<div class="doc"><p>${F.rmode ? "No finished preseason games logged yet. The rehearsal fills in the morning after each preseason slate that was projected." : "No graded games yet. From the first regular-season slate on, each morning's projections are frozen before tip-off, the last pregame consensus and PrizePicks lines are saved, and once the box scores are in, every player's projection is shown here next to what happened. The first graded day appears the morning after the opener."}</p></div>`;
    const days = I.days, sum = k => days.reduce((a, d) => a + (d[k] || 0), 0), wavg = k => { const n = days.reduce((a, d) => a + (d[k] != null ? d.n : 0), 0); return n ? days.reduce((a, d) => a + (d[k] != null ? d[k] * d.n : 0), 0) / n : null; };
    const tot = k => [days.reduce((a, d) => a + d[k][0], 0), days.reduce((a, d) => a + d[k][1], 0)];
    const card = (v, l) => `<div class="card"><b>${v}</b><span>${l}</span></div>`;
    const [cn, ch] = tot("cons"), [kn, kh] = tot("picks"), [pn, ph] = tot("pp"), [qn, qh] = tot("pp_picks");
    if (!F.rday || !days.some(d => d.date === F.rday)) F.rday = days[0].date;
    loadResultsDay(F.rday);
    const dayCols = [{k: "date", h: "Day", l: 1}, {k: "n", h: "Players", t: `Projected for ${I.min_proj}+ minutes`}, {k: "min_mae", h: "Min MAE", f: r => num(r.min_mae, 1)}, {k: "fp_mae", h: "FP MAE", f: r => num(r.fp_mae, 1)},
      {k: "fp_bias", h: "FP bias %", f: r => num(r.fp_bias, 1)},
      {k: "c", h: "vs consensus", t: "Model side (over if its projection is above the line) vs the last pregame consensus line", v: r => r.cons[0] ? r.cons[1] / r.cons[0] : null, f: r => pct1(r.cons[1], r.cons[0])},
      {k: "pk", h: "Picks", t: `Lines where the model and the book differ by ${I.edge_pp}+ points`, v: r => r.picks[0] ? r.picks[1] / r.picks[0] : null, f: r => pct1(r.picks[1], r.picks[0])},
      {k: "pp", h: "vs PrizePicks", v: r => r.pp[0] ? r.pp[1] / r.pp[0] : null, f: r => pct1(r.pp[1], r.pp[0])},
      {k: "pq", h: "PP picks", t: `Model's better side clears the ${(I.pp_breakeven * 100).toFixed(1)}% break-even by ${I.edge_pp}+ points`, v: r => r.pp_picks[0] ? r.pp_picks[1] / r.pp_picks[0] : null, f: r => pct1(r.pp_picks[1], r.pp_picks[0])}];
    // selected day
    const det = RES[rdir() + "/" + F.rday];
    let body;
    if (!det) body = `<p class="sub">Loading ${esc(F.rday)}…</p>`;
    else if (det.error) body = `<p class="sub">Couldn't load that day (${esc(det.error)}).</p>`;
    else {
      let rows = det.filter(r => (r.n + " " + r.t).toLowerCase().includes(F.q.trim().toLowerCase()));
      const hasLine = r => Object.values(r.s).some(x => x[2] != null || x[3] != null), hasPick = r => Object.values(r.s).some(x => x[4] || x[5]);
      if (F.rlines) rows = rows.filter(hasLine);
      if (F.rpicks) rows = rows.filter(hasPick);
      const cell = st => ({k: st, h: LABEL[st] || st, t: "projected → actual. [line] = last pregame consensus, then PrizePicks; ✓/✗ = whether the model's side (over if its projection is above the line) won; ◆ = a pick (model and book differ by the edge threshold).",
        v: r => Math.abs(r.s[st][1] - r.s[st][0]), f: r => {
          const [p, a, cl, pl, pc, pk] = r.s[st], mk = (line, side, pick) => { const g = grade(a, line, side); return `<span class="${g === true ? "good" : g === false ? "bad" : "mut"}">${g === true ? "✓" : g === false ? "✗" : "="}</span>${pick ? "◆" : ""}`; };
          let t = `${num(p)} <span class="mut">→</span> ${num(a)}`;
          if (cl != null) t += ` <span class="mut">[${cl}]</span>${mk(cl, p > cl ? "O" : "U", pc)}`;
          if (pl != null) t += ` <span class="mut">PP ${pl}</span>${mk(pl, p >= pl ? "O" : "U", pk)}`;
          return t; }});
      const cols = [{k: "n", h: "Player", l: 1}, {k: "t", h: "Team", l: 1},
        {k: "mp", h: "MIN", t: "projected → actual minutes", v: r => Math.abs(r.ma - r.mp), f: r => `${num(r.mp, 0)} <span class="mut">→</span> ${num(r.ma, 0)}`},
        {k: "fp", h: "FP", t: "DraftKings scoring, projected → actual", v: r => Math.abs(r.fp[1] - r.fp[0]), f: r => `${num(r.fp[0])} <span class="mut">→</span> ${num(r.fp[1])}`},
        ...["pts", "reb", "ast", "fg3m", "pra", "pr", "pa", "ra"].map(cell)];
      body = `<div class="bar"><input id="q" placeholder="Search player / team" value="${esc(F.q)}"><label><input type="checkbox" id="rlines" ${F.rlines ? "checked" : ""}> has a line</label><label><input type="checkbox" id="rpicks" ${F.rpicks ? "checked" : ""}> has a pick</label><span class="mut">${rows.length} players · click a header to sort by the size of the miss</span></div>${table(cols, rows, {id: "resday", sort: {key: "fp"}})}`;
    }
    return `<h2>Results</h2>${toggle}${banner}<p class="sub">What the model said before the game vs what happened. Pregame projections are frozen before tip-off; lines are the last pregame consensus (and PrizePicks) pull. A single day is a few hundred coin flips, so judge the hit rates over weeks, not days: against a −110 market a bettor needs about 52.4% to break even, and PrizePicks needs about ${(I.pp_breakeven * 100).toFixed(1)}% per leg.</p>
      <div class="cards">${card(days.length, "graded game days")}${card(sum("n"), "player-games (15+ min)")}${card(num(wavg("min_mae"), 1), "minutes MAE")}${card(num(wavg("fp_mae"), 1), "fantasy-points MAE")}${card(num(wavg("fp_bias"), 1) + "%", "fantasy-points bias")}</div>
      <div class="cards">${card(pct1(ch, cn), "model side vs consensus line")}${card(pct1(kh, kn), "picks vs consensus")}${card(pct1(ph, pn), "model side vs PrizePicks")}${card(pct1(qh, qn), "PrizePicks picks")}</div>
      <div class="bar"><label>Day <select id="rday">${days.map(d => `<option value="${d.date}" ${d.date === F.rday ? "selected" : ""}>${d.date}</option>`).join("")}</select></label></div>
      ${body}
      <h3>All graded days</h3>${table(dayCols, days, {id: "resdays", sort: {key: "date"}})}`;
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
<h3>The projection</h3><p><b>Minutes × per-minute rate × opponent × situation.</b> Minutes are a blend of the rolling window and the season average, adjusted for back-to-backs and rest. They are conditional on the player suiting up; each team's expected minutes (weighted by how often every player actually plays) are rescaled to 240, so if a starter is out, part of his minutes flow to the rest. Only a quarter of the full rescale is applied (<code>RESCALE_STRENGTH</code>): measured on 2025-26 with <code>python -m pipeline.absence_test</code>, a full rescale over-credits teammates (minutes error −6%, fantasy-point error about −2% when the absences are known, in both halves of the season). An extra usage bump for the remaining players made things worse and was not added: the redistribution is already in the minutes. Players listed Out or Doubtful are dropped; Questionable players take a small minutes haircut.</p>
<h3>Rates</h3><p>Each stat per minute, shrunk toward the position average by minutes played, so a hot 40-minute sample does not become a forecast. Blocks and steals need far more minutes to mean anything than points do, so they are shrunk harder. Early in a season, last season's games count at half weight and fade as the new ones pile up.</p>
<h3>Matchups</h3><p>Each defence is measured against league average per stat, regressed by games played, capped, and then <b>damped</b> by a measured share (<code>DEF_STRENGTH</code>). Measured on the 2025-26 season with <code>python -m pipeline.measure</code> (regress what players actually did against the multiplier applied): the share that arrives is about 1.0 for points, rebounds, assists, steals, blocks and turnovers (intervals include 1) and 0.75 for threes, so 1.0 is used throughout. Earlier guessed shares of 0.15-0.5 cost accuracy. <b>Calibration:</b> projected per-minute rates were over-shrunk toward the league (actual results spread out 5-20% more than projections; replicated in both halves of the season), so rates are stretched about the league rate by <code>CAL_RATE_SLOPE</code>. Together these cut fantasy-point error by about 0.7% in the walk-forward backtest. Re-measure when a second season of data exists.</p>
<h3>Median or mean</h3><p>Stat lines are right-skewed: a few huge nights pull the average above the typical one. <b>Median-style</b> is the number to compare to a posted line; <b>Mean</b> (× MEAN_FACTOR) is for season-long value.</p>
<h3>Lines</h3><p>P(over) uses sd = a + b × projection per stat. Book probability has the vig removed first (a −110/−110 market prices at 104.8%). Pick shows only past the edge threshold.</p>
<h3>Results</h3><p>For each graded game day, every player's pregame projection next to his box score, with the last pregame consensus and PrizePicks lines. The model "takes" the over if its projection is above a line and the under if below; a result exactly on the line is a push and is left out. A <b>pick</b> is a line where the model's probability differs from the book's by the edge threshold (PrizePicks: from the break-even). Lines are snapshotted at each odds pull until tip-off and frozen after; if a game had no pull before tip, it has no line to grade against.</p><h3>Scorecard</h3><p>Every slate's projections are logged before the games and never rewritten, then scored against the season-average and last-N baselines. Each row carries a settings stamp so a change to any knob starts a fresh record rather than blending into the old one.</p>
<h3>Game environment</h3><p>Each team's pace (possessions per game, both sides) and average point margin are shrunk toward the league by games played. <b>Pace</b>: the average of the two teams' pace vs league scales per-minute rates; measured on 2025-26 the share that arrives is about 1.0 (points 1.36 [0.71, 2.06]), and the effect is small (about 1%). <b>Blowouts</b>: starters do lose about 0.3 minutes per point of expected margin beyond 9 (replicated in both halves), but fantasy-point error did not move and the half-by-half minutes error disagreed, so it is <b>tested and not modelled</b> (<code>BLOWOUT_SLOPE</code> = 0). The expected margin on the Game Board is a point-differential stand-in; swap in the real spread once pregame spreads are stored.</p>
<h3>Shot zones</h3><p>Shot locations come from ESPN's play-by-play (x/y in feet, free), grouped into rim, paint, mid-range, corner three and above-break three. No defender distance exists in the feed, so shot quality here is <b>location and type only</b>, not open vs contested. Two ideas were tested as projection inputs on 2025-26, the football way (measure how much arrives, check both halves): (1) the opponent's points-per-shot allowed in each zone, weighted by the player's own shot mix, on top of the team-wide matchup already applied: share arriving 0.19 [-0.09, 0.57], halves -0.02 and +0.42, error unchanged; (2) shooting better than his shot locations imply: it regresses further than the model already assumes (-0.24 [-0.35, -0.14], negative in both halves) but the effect is too small to move error. Neither is modelled; the Shots tab is for reading a game. Split-half reliability is shown there: shot mix allowed and rim/paint FG% allowed are steady, mid-range and three-point FG% allowed are mostly luck.</p>\n<h3>Not modelled</h3><p>Opposing-offence strength inside the defence rating, double-double bonuses, player-vs-player matchups, and in-browser minute redistribution when you override a teammate. Injury status comes from ESPN's feed and is only as current as the last build.</p>
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
  if (page === "Live") liveStart(); else liveStop();
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
  else if (t.id === "rday") { F.rday = t.value; render(); }
  else if (t.id === "sview") { F.sview = t.value; render(); }
  else if (t.id === "cteam") { F.cteam = t.value; render(); }
  else if (t.id === "cheat") { F.cheat = t.value; render(); }
  else if (t.id === "cdots") { F.cdots = t.value; render(); }
  else if (t.id === "cplayer") { const p = (D.shots?.players || []).find(x => x.name.toLowerCase() === t.value.trim().toLowerCase()); if (p) { F.cplayer = p.pid; F.cteam = ""; render(); } }
  else if (t.id === "vstat") { F.vstat = t.value; render(); }
  else if (t.id === "rmode") { F.rmode = t.value; F.rday = ""; render(); }
  else if (t.id === "rlines") { F.rlines = t.checked; render(); }
  else if (t.id === "rpicks") { F.rpicks = t.checked; render(); }
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
  const names = ["projections", "matchups", "efficiency", "usage", "trends", "coverage", "meta", "tiers", "shots", "shotchart", "scorecard", "spread", "lines", "players"];
  await Promise.all(names.map(async n => { try { const r = await fetch(`data/${n}.json`); if (r.ok) D[n] = await r.json(); } catch (e) {} }));
  try { const r = await fetch("data/results/index.json"); if (r.ok) D.rIdx = await r.json(); } catch (e) {}
  try { const r = await fetch("data/results_rehearsal/index.json"); if (r.ok) D.rIdxR = await r.json(); } catch (e) {}
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

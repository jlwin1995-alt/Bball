"use strict";
// ---------- state ----------------------------------------------------------
const TABS = ["Projections", "Live", "Game Board", "Matchups", "Team Tiers", "Shots", "Efficiency", "Usage", "Trends", "Lines", "Scorecard", "Results", "Config", "Methodology"];
const STATS = ["pts", "reb", "ast", "fg3m", "stl", "blk", "tov"];
const LABEL = {pts: "PTS", reb: "REB", ast: "AST", fg3m: "3PM", stl: "STL", blk: "BLK", tov: "TOV", fp: "FP", pra: "PTS+REB+AST", pr: "PTS+REB", pa: "PTS+AST", ra: "REB+AST"};
const COMBO = {pra: ["pts", "reb", "ast"], pr: ["pts", "reb"], pa: ["pts", "ast"], ra: ["reb", "ast"]};
const PRESETS = {
  PrizePicks: {pts: 1, fg3m: 0, reb: 1.2, ast: 1.5, stl: 3, blk: 3, tov: -1},
  DraftKings: {pts: 1, fg3m: 0.5, reb: 1.25, ast: 1.5, stl: 2, blk: 2, tov: -0.5},
  FanDuel: {pts: 1, fg3m: 0, reb: 1.2, ast: 1.5, stl: 3, blk: 3, tov: -1},
};
const D = {};
let CFG = {ver: 2, preset: "PrizePicks", scoring: {...PRESETS.PrizePicks}, mean: false, edgeMin: 4, ppBE: 54.4};
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
  r.fpPP = r.pts + 1.2 * r.reb + 1.5 * r.ast + 3 * r.stl + 3 * r.blk - r.tov;   // PrizePicks Fantasy Score, whatever scoring preset is chosen
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
function table(cols, rows, {sort = null, id = "t", rowClass = null, tight = false} = {}) {
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
  const head = cols.map(c => `<th class="${c.l ? "l" : ""} ${c.c || ""} ${c.k === st.key ? "s " + (st.asc ? "asc" : "") : ""}" data-k="${c.k}" title="${esc(c.t || "")}">${c.h}</th>`).join("");
  const body = sorted.map(r => `<tr class="${rowClass ? rowClass(r) : ""}">` + cols.map(c => `<td class="${c.l ? "l" : ""} ${c.c || ""}">${c.f ? c.f(r) : esc(r[c.k])}</td>`).join("") + "</tr>").join("");
  return `<div class="tw${tight ? " tight" : ""}" data-tid="${id}"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
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
// Typical-miss band around a projection: sd comes from the fitted spread (sd = a + b x projection); a typical miss (mean absolute error) is
// about 0.8 sd. Opening-week backtests ran about 13% less accurate than late season (fantasy-point MAE 8.8 vs 7.8), so the band is widened 15%
// until the new season has ~15 game days of data.
const bandWiden = () => ((D.coverage && D.coverage.cur_season_games) ?? 1e9) < 4500 ? 1.15 : 1.0;
function band(stat, m) {
  const [a, b] = (D.spread || D.meta.spread)[stat] || [1, 0.3], e = 0.8 * (a + b * m) * bandWiden();
  return [Math.max(m - e, 0), m + e];
}
const rangeLine = (stat, m) => { if (!F.range || m == null || !(m > 0)) return ""; const [lo, hi] = band(stat, m), d = m < 10 ? 1 : 0;
  return `<span class="mut rng" title="Typical-miss range: projection ± a typical error (${bandWiden() > 1 ? "widened 15% for the opening weeks" : "from the fitted spread"})">${num(lo, d)}–${num(hi, d)}</span>`; };
const rangeBox = () => `<label><input type="checkbox" id="rng" ${F.range ? "checked" : ""}> show ± typical-miss range</label>`;
function filters(extra = "") {
  return `<div class="bar"><input id="q" placeholder="Search player / team" value="${esc(F.q)}">
  <label>Pos <select id="pos">${["", "G", "F", "C"].map(p => `<option ${F.pos === p ? "selected" : ""} value="${p}">${p || "All"}</option>`).join("")}</select></label>${extra}</div>`;
}
const F = {q: "", pos: "", ming: 10, lstat: "", lgame: "", lside: "", lbucket: "", lcombo: false, lpicks: false, rday: "", vstat: "pts", vpos: "G", sview: "today", smode: "soft", cteam: "", cplayer: "", cheat: "fg", cdots: "all", rmode: null, rlines: false, rpicks: false, range: true};
const RES = {};                                     // results/<date>.json cache
function passes(r) {
  if (F.pos && r.pos !== F.pos) return false;
  const q = F.q.trim().toLowerCase();
  return !q || (r.name + " " + r.team).toLowerCase().includes(q);
}
document.addEventListener("input", e => {
  if (e.target.id === "q") { F.q = e.target.value; render(true, "q"); }
  if (e.target.id === "lvpaste") LIVE.paste = e.target.value;         // kept across the 30 s redraw, no redraw while typing
});
document.addEventListener("change", e => {
  if (e.target.id === "rng") { F.range = e.target.checked; render(true); }
  if (e.target.id === "pos") { F.pos = e.target.value; render(true); }
  if (e.target.id === "ming") { F.ming = +e.target.value || 0; render(true); }
  if (e.target.id === "lstat") { F.lstat = e.target.value; render(true); }
  if (e.target.id === "lgame") { F.lgame = e.target.value; render(true); }
  if (e.target.dataset && e.target.dataset.lv) { LIVE.lines[e.target.dataset.lv] = e.target.value.trim(); store.set("livelines", LIVE.lines); render(true, e.target.id); }
  if (e.target.id === "lcombo") { F.lcombo = e.target.checked; render(true); }
  if (e.target.id === "lside") { F.lside = e.target.value; render(true); }
  if (e.target.id === "lbucket") { F.lbucket = e.target.value; render(true); }
  if (e.target.id === "lpicks") { F.lpicks = e.target.checked; render(true); }
});

// ---------- pages ---------------------------------------------------------------
const pct = x => x == null ? "" : `<span class="${x > 1.005 ? "good" : x < 0.995 ? "bad" : "mut"}">${num((x - 1) * 100, 1)}%</span>`;
const statusPill = s => s ? `<span class="pill ${s === "Out" ? "bad" : ""}">${esc(s)}</span>` : "";


// ---------- Live tab: polls ESPN straight from the browser (no credits, no CI) ------------------------------
const ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba";
const LIVE = {games: null, box: {}, err: null, ts: null, timer: null, snap: {}, out: {}, lines: store.get("livelines", {}), paste: "", pasteMsg: ""};
// Second-half minutes from the halftime state, fitted on 26,600 player-games (2025-26 + this season): minutes = a + b*usual + c*first-half minutes
// + d*starter - a blowout term (halftime margin past 10). Average miss 3.2-3.4 min vs 5.3-6.1 for "usual minus minutes played".
const HALF = {a: 2.6109, usual: 0.1221, h1: 0.4872, starter: 1.4666, hinge: 0.0618, hingeS: -0.2737};
const halfMin = (usual, h1, starter, absm) => { const h = Math.max(absm - 10, 0); return Math.max(HALF.a + HALF.usual * usual + HALF.h1 * h1 + HALF.starter * starter + HALF.hinge * h * usual / 30 + HALF.hingeS * h * starter, 0); };
const LEFT = /won'?t return|will not return|did not return|didn'?t return|not return|ruled out for the (rest|remainder)|left .{0,40}game|exited/i;
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
        rows.push({pid: String(a.athlete.id), name: a.athlete.displayName, team: ab, starter: a.starter ? 1 : 0, min: mn, pts: n("points"), reb: n("rebounds"), ast: n("assists"),
          fg3m: +String(st[ix("threePointFieldGoalsMade-threePointFieldGoalsAttempted")] ?? "0").split("-")[0] || 0, stl: n("steals"), blk: n("blocks"), tov: n("turnovers")});
      }
    }
  }
  return rows;
}
const normName = n => String(n || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[.'’]/g, "").replace(/\b(jr|sr|ii|iii|iv)\b/g, "").replace(/[^a-z ]+/g, " ").replace(/\s+/g, " ").trim();
const LSTAT = [[/(pts?|points?)\s*\+\s*(rebs?|rebounds?)\s*\+\s*(asts?|assists?)|\bpra\b/i, "pra"], [/(rebs?|rebounds?)\s*\+\s*(asts?|assists?)|\bra\b/i, "ra"], [/(pts?|points?)\s*\+\s*(rebs?|rebounds?)|\bpr\b/i, "pr"],
  [/(pts?|points?)\s*\+\s*(asts?|assists?)|\bpa\b/i, "pa"], [/3\s*-?\s*pt\s*made|3pm|threes?|3-?pointers?( made)?/i, "fg3m"], [/\b(pts?|points?)\b/i, "pts"], [/\b(rebs?|rebounds?)\b/i, "reb"], [/\b(asts?|assists?)\b/i, "ast"]];
function applyPaste(text) {
  const all = Object.values(LIVE.box).flat(), byFull = {}, byLast = {};
  for (const b of all) { const k = normName(b.name); (byFull[k] = byFull[k] || []).push(b); const l = k.split(" ").pop(); (byLast[l] = byLast[l] || []).push(b); }
  let n = 0, prev = ""; const bad = [];
  for (const raw of String(text).split(/\n+/)) {
    const line = raw.trim(); if (!line) continue;
    const st = (LSTAT.find(([re]) => re.test(line)) || [])[1];
    const cleaned = line.replace(/cur\.?\s*\d+(\.\d+)?/i, " ");
    const nums = cleaned.match(/\d+(?:\.\d+)?/g);
    if (!st || !nums) { prev = line; continue; }                          // a name line: the stat line follows
    const ln = nums[nums.length - 1];
    let nm = normName(cleaned.replace(/\d+(?:\.\d+)?/g, " ").replace(LSTAT.find(([, s2]) => s2 === st)[0], " ").replace(/\b(more|less|over|under|points?|rebounds?|assists?)\b/gi, " "));
    if (!nm) nm = normName(prev);
    const hit = byFull[nm] || (byFull[nm.split(" ").slice(-2).join(" ")]) || (byLast[nm.split(" ").pop()]?.length === 1 ? byLast[nm.split(" ").pop()] : null);
    if (!hit || hit.length !== 1) { bad.push(line.slice(0, 40)); continue; }
    LIVE.lines[hit[0].pid + "|" + st] = ln; n++; prev = "";
  }
  store.set("livelines", LIVE.lines);
  LIVE.pasteMsg = `Applied ${n} line${n === 1 ? "" : "s"}${bad.length ? `; couldn't place: ${bad.slice(0, 4).join(" | ")}${bad.length > 4 ? ` (+${bad.length - 4} more)` : ""}` : ""}.`;
}
const clockMin = c => { const m = /^(\d+):(\d+)/.exec(c || ""); return m ? +m[1] + m[2] / 60 : 0; };
async function liveRefresh() {
  try {
    const sb = await (await fetch(`${ESPN}/scoreboard`, {cache: "no-store"})).json();
    LIVE.games = (sb.events || []).map(e => {
      const c = e.competitions[0], st = e.status.type, t = {};
      for (const x of c.competitors) t[x.homeAway] = {ab: x.team.abbreviation || x.team.shortDisplayName || x.team.displayName || "?", score: +x.score || 0};
      return {id: e.id, state: st.state, detail: st.shortDetail, period: e.status.period || 0, clock: e.status.displayClock || "", home: t.home, away: t.away, tip: e.date};
    });
    await Promise.all(LIVE.games.filter(g => g.state === "in" || (g.state === "post" && !LIVE.box[g.id])).map(async g => {
      LIVE.box[g.id] = parseBox(await (await fetch(`${ESPN}/summary?event=${g.id}`, {cache: "no-store"})).json());
      if (g.state === "in" && (/half/i.test(g.detail) && !/1st|2nd|3rd|4th/i.test(g.detail) || (g.period === 3 && !LIVE.snap[g.id] && clockMin(g.clock) >= 11.5)))   // first look at halftime (or the first seconds of Q3)
        LIVE.snap[g.id] = {h1: Object.fromEntries(LIVE.box[g.id].map(b => [b.pid, b.min])), margin: g.home.score - g.away.score};
    }));
    try {                                                      // players ESPN says left hurt and will not return
      const inj = await (await fetch(`${ESPN}/injuries`, {cache: "no-store"})).json();
      LIVE.out = {};
      for (const tm of inj.injuries || []) for (const i of tm.injuries || []) {
        const a = i.athlete || {}, id = a.id || ((a.links || []).map(l => /\/id\/(\d+)/.exec(l.href || "")).find(Boolean) || [])[1];
        if (id && LEFT.test(i.shortComment || "") && Date.now() - Date.parse(i.date) < 8 * 3600e3) LIVE.out[String(id)] = i.shortComment;
      }
    } catch (e) { /* the injury feed is a bonus: keep the board up without it */ }
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
  try { RES[key] = await (await fetch(`data/${key}.json`, {cache: "no-cache"})).json(); } catch (e) { RES[key] = {error: String(e)}; }
  if (page === "Results") render(true);
}
const pct1 = (h, n) => n ? `${(h / n * 100).toFixed(1)}% <span class="mut">(${h}/${n})</span>` : "—";

const warn = e => e != null && Math.abs(e) >= 15 ? ` <span title="An edge this large is usually the model having the minutes or role wrong (injury news, rotation change), not a bargain. Check before trusting it." style="cursor:help">⚠</span>` : "";
const LBUCKETS = [["50-54.4", "50–54.4% (under break-even)"], ["54.4-57.7", "54.4–57.7%"], ["57.7-65", "57.7–65%"], ["57-65", "57–65%"], ["60-65", "60–65%"], ["65-70", "65–70%"], ["70-101", "70%+"]];
// Calibrated P(win) at the PrizePicks line: 0.5 + beta x (model P - 0.5), beta fitted on the graded record (pipeline/calibrate.py, refit each refresh).
const calBeta = side => { const c = D.calib; if (!c) return null; const x = c[side] && c[side].beta != null ? c[side] : c.all; return x && x.beta != null ? x.beta : null; };
const calP = r => { if (r.pw == null || !r.side) return null; const b = calBeta(r.side); return b == null ? null : 0.5 + b * (r.pw - 0.5); };
const CAL_TIP = () => { const c = D.calib; if (!c || !c.all || c.all.beta == null) return "Calibrated P(win): not enough graded lines yet."; const f = k => c[k] && c[k].beta != null ? `${num(c[k].beta, 2)} ± ${num(c[k].se, 2)} (n ${c[k].n})` : "n/a";
  return `The model's P(win) shrunk toward 50% by how much it has held up on graded PrizePicks lines (${c.days} days to ${c.asof}): 0.5 + β × (P − 0.5). β overall ${f("all")}, Overs ${f("OVER")}, Unders ${f("UNDER")}. β 1 = the model is right, 0 = the line is a coin flip. Provisional: reviewed Nov 3.`; };
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
    const m = r.stat === "fp" ? p.c.fpPP : p.c[r.stat], [a, b] = sp[r.stat] || [1, 0.3], sd = Math.max(a + b * m, 0.1), c = r.cons, pp = r.dfs.prizepicks;
    const started = Date.now() >= Date.parse(r.commence);
    const out = {started, name: p.name, pos: p.pos, team: p.team, game: r.game, stat: r.stat, m, c, r, pp, ud: r.dfs.underdog ?? r.dfs.pick6, out: p.c.min === 0};
    if (c) { const s = sides(c.line, m, sd); out.po = s.o; out.edge = (s.o - c.p_over) * 100; out.pick = started ? "LIVE" : out.out ? "OUT" : Math.abs(out.edge) >= CFG.edgeMin ? (out.edge > 0 ? "OVER" : "UNDER") : ""; }
    if (pp != null) { const s = sides(pp, m, sd); out.side = s.o >= s.u ? "OVER" : "UNDER"; out.pw = Math.max(s.o, s.u); out.ppEdge = (out.pw - BE) * 100;
      out.ppPick = started ? "LIVE" : out.out ? "OUT" : out.ppEdge >= CFG.edgeMin ? "PP " + out.side : ""; out.gap = c ? pp - c.line : null; }
    return out;
  }).filter(Boolean).filter(passes);
  if (F.lstat) rows = rows.filter(r => r.stat === F.lstat);
  if (F.lgame) rows = rows.filter(r => r.game === F.lgame);
  if (F.lside) rows = rows.filter(r => r.side === F.lside);                   // PrizePicks side (the better side at the PrizePicks line)
  if (F.lbucket) { const [lo, hi] = F.lbucket.split("-").map(Number); rows = rows.filter(r => r.pw != null && r.pw * 100 >= lo && r.pw * 100 < hi); }
  if (F.lpicks) rows = rows.filter(r => (r.pick && r.pick !== "OUT" && r.pick !== "LIVE") || (r.ppPick && r.ppPick !== "OUT" && r.ppPick !== "LIVE"));
  const tip = r => r.r.books.map(b => `${b.b} ${b.line} (${b.over ?? "-"}/${b.under ?? "-"})`).join("\n");
  const cols = [{k: "name", h: "Player", l: 1, f: r => esc(r.name)}, {k: "team", h: "Team", l: 1}, {k: "game", h: "Game", l: 1, f: r => esc(r.game) + (r.started ? ` <span class="pill hot" title="Tipped off: these are the last PRE-game lines. The model's pregame probability no longer applies, so no pick is shown.">LIVE</span>` : "")}, {k: "stat", h: "Stat", l: 1, f: r => r.stat === "fp" ? "Fantasy score" : LABEL[r.stat]},
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
    {k: "cal", h: "Cal P(win)", t: CAL_TIP(), v: r => calP(r), f: r => { const c = calP(r); return c == null ? "" : `<span class="${c >= BE ? "good" : "mut"}">${num(c * 100, 1)}%</span>`; }},
    {k: "ppEdge", h: "PP edge pp", t: `vs your break-even of ${CFG.ppBE}% (Config)`, v: r => r.ppEdge, f: r => r.ppEdge == null ? "" : `<span class="${r.ppEdge > 0 ? "good" : "bad"}">${num(r.ppEdge)}</span>`},
    {k: "ppPick", h: "PP pick", l: 1, f: r => r.ppPick ? `<b>${r.ppPick}</b>${r.ppPick === "OUT" || r.ppPick === "LIVE" ? "" : warn(r.ppEdge)}` : ""}];
  const games = [...new Set(L.rows.map(r => r.game))].sort(), stats = [...new Set(L.rows.map(r => r.stat))];
  const extra = `<label>Stat <select id="lstat"><option value="">All</option>${stats.map(s => `<option value="${s}" ${F.lstat === s ? "selected" : ""}>${s === "fp" ? "Fantasy score" : LABEL[s] || s}</option>`).join("")}</select></label>
    <label>Game <select id="lgame"><option value="">All</option>${games.map(g => `<option ${F.lgame === g ? "selected" : ""}>${esc(g)}</option>`).join("")}</select></label>
    <label>Side <select id="lside"><option value="">Over + Under</option><option value="OVER" ${F.lside === "OVER" ? "selected" : ""}>Overs</option><option value="UNDER" ${F.lside === "UNDER" ? "selected" : ""}>Unders</option></select></label>
    <label title="Model probability of the better side at the PrizePicks line (PP P(win)). Filters to rows that have a PrizePicks line.">PP P(win) <select id="lbucket"><option value="">Any</option>${LBUCKETS.map(([v, t]) => `<option value="${v}" ${F.lbucket === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>
    <label><input type="checkbox" id="lpicks" ${F.lpicks ? "checked" : ""}> picks only</label>`;
  return `<p class="sub">Sportsbook consensus (median line; vig removed) beside PrizePicks, with the model's edge against each${credits}. Updated ${mins < 90 ? mins + " min" : Math.round(mins / 60) + " h"} ago${mins > 360 ? " — <b>stale, lines move</b>" : ""}. DFS prices are nominal, so PrizePicks edge is measured against your break-even (Config) rather than odds. A k-pick entry paying M× needs M^(−1/k) per leg. <b>Cal P(win)</b> is the model's PP P(win) shrunk toward 50% by how much it has actually held up on graded lines (hover the header for the numbers): provisional, to be reviewed Nov 3.</p>
    ${filters(extra)}${table(cols, rows, {id: "live", sort: {key: "edge"}})}`;
}

// Softest and toughest 10 defences for one position and stat, with the split-half reliability beside it. Display only (see the note under the heading).
function vsTop10(T, st, pos, rel) {
  const key = r => r[pos + "_" + st], rows = T.vspos.filter(r => key(r) != null).sort((a, b) => key(b) - key(a));
  if (rows.length < 20) return "";
  const rv = rel[pos + "_" + st], tag = rv == null ? "unknown" : rv < 0.2 ? "mostly noise" : rv < 0.4 ? "weak signal" : "some signal";
  const li = r => `<li><b>${esc(r.team)}</b> <span class="${key(r) > 1 ? "good" : key(r) < -1 ? "bad" : "mut"}">${key(r) > 0 ? "+" : ""}${num(key(r), 1)}%</span></li>`;
  const col = (title, arr) => `<div><h3>${title}</h3><ol class="movers">${arr.map(li).join("")}</ol></div>`;
  return `<p class="banner">Reliability for ${{G: "guards", F: "forwards", C: "centers"}[pos]} ${LABEL[st]}: <b>${rv ?? "n/a"}</b> (${tag}). Early in the season most of this ranking is schedule and a few big games, not a stable trait. Treat it as context, not a pick; it is to be rechecked after about 10 more games per team.</p>
    <div class="cols2">${col("Softest 10 (allows the most)", rows.slice(0, 10))}${col("Toughest 10 (allows the least)", rows.slice(-10).reverse())}</div>`;
}
function vsPosition() {
  const T = D.tiers;
  if (!T || !T.vspos || !T.vspos.length) return "";
  const st = F.vstat, rel = T.vspos_rel || {};
  const cell = pos => ({k: pos, h: {G: "Guards", F: "Forwards", C: "Centers"}[pos], t: `Reliability (split-half): ${rel[pos + "_" + st] ?? "n/a"}`,
    v: r => r[pos + "_" + st], f: r => { const x = r[pos + "_" + st]; return x == null ? "" : `<span class="${x > 1 ? "good" : x < -1 ? "bad" : "mut"}">${x > 0 ? "+" : ""}${num(x, 1)}%</span>`; }});
  return `<h3>Vs position</h3><p class="sub">Per-minute ${LABEL[st]} each defence allows to guards, forwards and centers, relative to the league at that position (green = soft). Shrunk toward zero by minutes seen. <b>Display only:</b> as a projection input it added nothing in a walk-forward test (the position-specific part beyond the team-wide matchup was noise and the two halves of the season disagreed), so the projections do not use it. Split-half reliability for ${LABEL[st]}: guards ${rel["G_" + st] ?? "–"}, forwards ${rel["F_" + st] ?? "–"}, centers ${rel["C_" + st] ?? "–"}.</p>
    <div class="bar"><label>Stat <select id="vstat">${STATS.map(s => `<option value="${s}" ${s === st ? "selected" : ""}>${LABEL[s]}</option>`).join("")}</select></label>
      <label>Position <select id="vpos">${[["G", "Guards"], ["F", "Forwards"], ["C", "Centers"]].map(([v, t]) => `<option value="${v}" ${F.vpos === v ? "selected" : ""}>${t}</option>`).join("")}</select></label></div>
    ${vsTop10(T, st, F.vpos, rel)}
    ${table([{k: "team", h: "Team", l: 1}, cell("G"), cell("F"), cell("C")], T.vspos, {id: "vspos", sort: {key: "G"}})}`;
}


// ---------- shot chart: a defence's allowed-shot map under a shooter's shots --------------------------------------------------

function todayMatchups(T) {
  const ZN = {rim: "Rim", paint: "Paint", mid: "Mid", corner3: "Corner 3", arc3: "Arc 3"};
  const byId = Object.fromEntries(T.players.map(p => [p.pid, p])), def = Object.fromEntries(T.defense.map(r => [r.team, r]));
  const LAMBDA = 0.49;                                          // measured share of the interior zone matchup that shows up in points (2025-26)
  const rows = [];
  for (const p of D.projections) {
    const pl = byId[p.pid], dr = def[p.opp];
    if (!pl || !dr || p.out || pl.n < 200) continue;
    const c = calc(p, true);
    if (c.min < 20) continue;
    let x = 0;
    for (const z of ["rim", "paint"]) x += (pl[z + "_mix"] / 100) * (dr[z + "_fg"] / T.lg_fg[z]);       // relative points-per-shot change on his interior shots
    const hot = Object.keys(ZN).filter(z => pl[z + "_mix"] >= 15 && pl[z + "_fg"] != null && pl[z + "_fg"] >= T.lg_fg[z] + 2 && pl[z + "_mix"] / 100 * pl.n >= 25);
    rows.push({pid: p.pid, name: p.name, team: p.team, opp: p.opp, home: p.home, pts: c.pts, min: c.min, fp: c.fp,
      inter: pl.rim_mix + pl.paint_mix, edge: LAMBDA * x * 100, edgePts: LAMBDA * x * c.pts,
      hot: hot.map(z => `${ZN[z]} ${pl[z + "_mix"]}% · ${num(pl[z + "_fg"], 0)}%`).join("; "),
      hotDef: hot.map(z => `${ZN[z]} ${dr[z + "_fg"] > 0 ? "+" : ""}${num(dr[z + "_fg"], 1)}`).join("; "),
      rimd: dr.rim_fg, paintd: dr.paint_fg});
  }
  return rows;
}
const SCP = {data: null, pending: false};
async function loadShotPlayers() {
  if (SCP.data || SCP.pending) return;
  SCP.pending = true;
  try { SCP.data = await (await fetch("data/shotchart_players.json", {cache: "no-cache"})).json(); } catch (e) { SCP.data = {}; }
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

function todayView(T) {
  const rows = todayMatchups(T);
  const soft = F.smode === "soft";
  const sorted = [...rows].sort((a, b) => soft ? b.edge - a.edge : a.edge - b.edge).slice(0, 40);
  const sg = x => `${x > 0 ? "+" : ""}${num(x, 1)}`;
  const cols = [{k: "name", h: "Player", l: 1}, {k: "team", h: "Team", l: 1},
    {k: "opp", h: "Vs", l: 1, f: r => `${r.home ? "" : "@"}${esc(r.opp)}`},
    {k: "pts", h: "Proj PTS", t: "Median projection, honours your Min OVR", f: r => num(r.pts)},
    {k: "inter", h: "Interior %", t: "Share of his shots at the rim or in the paint", f: r => num(r.inter, 0)},
    {k: "hot", h: "His hot zones", t: "Zones he shoots from a lot (15%+ of his shots) and above league FG% by 2+ points: share of his shots · his FG%", l: 1, f: r => esc(r.hot) || '<span class="mut">none</span>'},
    {k: "hotDef", h: "Defence allows there", t: "FG% allowed in those zones minus the league (points): + = soft", l: 1, f: r => esc(r.hotDef) || ""},
    {k: "rimd", h: "Rim", t: "FG% this defence allows at the rim vs league", f: r => `<span class="${r.rimd > 0.5 ? "good" : r.rimd < -0.5 ? "bad" : "mut"}">${sg(r.rimd)}</span>`},
    {k: "paintd", h: "Paint", f: r => `<span class="${r.paintd > 0.5 ? "good" : r.paintd < -0.5 ? "bad" : "mut"}">${sg(r.paintd)}</span>`},
    {k: "edge", h: "Edge %", t: "Expected change in his points from the interior matchup alone: his rim/paint shot mix x what this defence allows there, times the measured 0.49 share that shows up", f: r => `<b class="${r.edge > 0.3 ? "good" : r.edge < -0.3 ? "bad" : "mut"}">${sg(r.edge)}%</b>`},
    {k: "edgePts", h: "Edge pts", f: r => sg(r.edgePts)},
    {k: "go", h: "", f: r => `<a href="#" class="scgo" data-sc="${esc(r.pid)}|${esc(r.opp)}">chart</a>`}];
  return `<div class="bar"><label>Show <select id="smode"><option value="soft" ${soft ? "selected" : ""}>Soft interior matchups (players to like)</option><option value="tough" ${soft ? "" : "selected"}>Tough interior matchups (players to be careful with)</option></select></label>
      <span class="mut">${rows.length} players on the slate with 20+ projected minutes and 200+ shots of history</span></div>
    ${rows.length ? table(cols, sorted, {id: "stoday_" + F.smode, sort: {key: "edge", asc: !soft}}) : '<p class="sub">No players on the slate with enough shot history yet.</p>'}
    <p class="sub">Players going up against defences that are weak (or strong) where they actually shoot. Only the <b>rim and paint</b> count in the Edge: those are the zones where a defence's FG% allowed is steady across a season (split-half ${T.defense_rel.rim_fg} and ${T.defense_rel.paint_fg}). Mid-range and three-point FG% allowed are mostly luck, and including them made the signal worse, so they are shown in the hot-zones columns for context but not scored. Measured on 2025-26: the share of this interior matchup that showed up in points was 0.49 (interval 0.09 to 0.92, positive in both halves of the season), and the softest fifth of players beat their projections by about 4% on points against 2% for the toughest fifth. A real but small effect: the Edge is a nudge of a percent or so, not a reason to override a projection. It is not yet in the projections themselves.</p>`;
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
      <div class="scside"><h3>${esc(pl.name)} (${esc((D.projections.find(p => p.pid === F.cplayer) || pl).team)}) vs ${esc(F.cteam)}</h3>
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
    const cols = [{k: "name", h: "Player", l: 1, f: r => esc(r.name) + ` <span class="mut">${esc(r.pos)}</span> ` + statusPill(r.status), v: r => r.name}, {k: "team", h: "Team", l: 1, c: "opt"}, {k: "opp", h: "Opp", l: 1, f: r => (r.home ? "vs " : "@ ") + esc(r.opp), v: r => r.opp},
      {k: "rest", h: "Rest", c: "opt", t: "Days since the team's last game", f: r => r.rest ?? ""},
      {k: "g", h: "G", c: "opt", t: "Weighted games in the sample (last season counts partially early on)"},
      {k: "mino", h: "Min OVR", c: "opt", t: "Type minutes to override; 0 = out. Teammates are NOT re-scaled in the browser. Saved on this device.", v: r => OVR[r.pid]?.min,
        f: r => `<input class="ovr" data-pid="${esc(r.pid)}" value="${OVR[r.pid]?.min ?? ""}" placeholder="${num(r.min)}">`},
      {k: "cmin", h: "Min", c: "opt", v: r => r.c.min, f: r => num(r.c.min)},
      ...STATS.map(s => ({k: "c" + s, h: LABEL[s], v: r => r.c[s], f: r => num(r.c[s], 1) + (["pts", "reb", "ast", "fg3m"].includes(s) ? rangeLine(s, r.c[s]) : "")})),
      {k: "cfp", h: CFG.mean ? "Mean FP" : "Proj FP", v: r => r.c.fp, f: r => `<b>${num(r.c.fp)}</b>` + rangeLine("fp", r.c.fp)},
      {k: "apts", h: "Pts Adj", c: "opt", t: "Opponent multiplier on scoring, after damping", v: r => r.adj_pts, f: r => pct(r.adj_pts)},
      {k: "areb", h: "Reb Adj", c: "opt", v: r => r.adj_reb, f: r => pct(r.adj_reb)},
      {k: "aast", h: "Ast Adj", c: "opt", v: r => r.adj_ast, f: r => pct(r.adj_ast)}];
    return `<h2>Projections — ${esc(D.coverage.slate_date || "no slate")}</h2>
      <p class="sub">${CFG.mean ? "Mean" : "Median-style"} projection per player with a game. Shaded <b>Min OVR</b> is yours; everything recalculates instantly. Scoring: ${esc(CFG.preset)}.</p>
      ${filters(`${rangeBox()}<button id="clr">Clear overrides</button>`)}
      ${table(cols, rows, {id: "proj", sort: {key: "cfp"}, rowClass: r => r.c.min === 0 ? "out" : ""})}`;
  },

  "Game Board"() {
    const sp = D.spread || D.meta.spread, BE = CFG.ppBE / 100, lineRow = {};
    for (const r of (D.lines?.rows || [])) lineRow[r.pid + "|" + r.stat] = r;
    const cellVal = (r, s) => s === "pra" ? r.c.pts + r.c.reb + r.c.ast : r.c[s];
    const fpLine = CFG.preset === "PrizePicks";          // the posted Fantasy Score line only matches this scoring
    const boardCell = (r, s) => {
      const m = cellVal(r, s), L = s === "fp" && !fpLine ? null : lineRow[r.pid + "|" + s];
      if (!L || r.c.min === 0 || Date.now() >= Date.parse(L.commence)) return num(m) + rangeLine(s, m);
      const [a, b] = sp[s] || [1, 0.3], sd = Math.max(a + b * m, 0.1), c = L.cons, pp = L.dfs?.prizepicks;
      let line = c ? c.line : pp, lean = "";
      if (c) { const q = sides(c.line, m, sd).o, e = (q - c.p_over) * 100; if (Math.abs(e) >= CFG.edgeMin) lean = e > 0 ? "O" : "U"; }
      else if (pp != null) { const q = sides(pp, m, sd), w = Math.max(q.o, q.u); if ((w - BE) * 100 >= CFG.edgeMin) lean = q.o >= q.u ? "O" : "U"; }
      if (line == null) return num(m) + rangeLine(s, m);
      const tip = [...(L.books || []).map(x => `${x.b} ${x.line}`), ...Object.entries(L.dfs || {}).map(([k, v]) => `${k} ${v}`)].join("\n");
      return `<span title="${esc(tip)}">${num(m)} <span class="mut">[${line}]</span>${lean ? ` <b class="${lean === "O" ? "good" : "bad"}">${lean}</b>` : ""}</span>${rangeLine(s, m)}`;
    };
    // opposing defence vs his position: shown only where it is in the softest or toughest 10 for that stat (display only; see Matchups > Vs position)
    const VT = D.tiers?.vspos || [], VR = D.tiers?.vspos_rel || {}, vsRank = {};
    for (const pos of ["G", "F", "C"]) for (const s of ["pts", "reb", "ast", "fg3m"]) {
      const k = pos + "_" + s, ord = VT.filter(r => r[k] != null).sort((a, b) => b[k] - a[k]);
      ord.forEach((r, i) => { (vsRank[r.team] = vsRank[r.team] || {})[k] = {rank: i + 1, of: ord.length, v: r[k]}; });
    }
    const vsCell = r => {                                    // at most the two most telling stats: reliable ones first, then the most extreme rank
      if (r.c.min === 0) return "";
      const c = [];
      for (const s of ["pts", "reb", "ast", "fg3m"]) {
        const x = vsRank[r.opp]?.[r.pos + "_" + s]; if (!x || (x.rank > 10 && x.rank <= x.of - 10)) continue;
        const rel = VR[r.pos + "_" + s]; c.push({s, x, rel, weak: rel == null || rel < 0.2, ext: Math.abs(x.rank - (x.of + 1) / 2)});
      }
      c.sort((a, b) => a.weak - b.weak || b.ext - a.ext);
      return c.slice(0, 2).map(({s, x, rel, weak}) => { const soft = x.rank <= 10;
        return `<span class="${weak ? "mut" : soft ? "good" : "bad"}" title="${esc(r.opp)} has allowed ${x.v > 0 ? "+" : ""}${num(x.v, 1)}% per-minute ${LABEL[s]} to ${{G: "guards", F: "forwards", C: "centers"}[r.pos]}: rank ${x.rank} of ${x.of} (1 = softest). Reliability ${rel ?? "n/a"}${weak ? " (mostly noise)" : ""}. Display only.">${LABEL[s]}${soft ? "▲" : "▼"}${x.rank}</span>`; }).join(" ");
    };
    // his record against his own projection vs defences like tonight's (team-wide rank per stat, 1 = softest of 30). Display only.
    const SPL = D.splits || {}, MR = {};
    for (const s of ["pts", "reb", "ast", "fg3m"]) (D.matchups || []).filter(r => r[s + "_raw"] != null).sort((a, b) => b[s + "_raw"] - a[s + "_raw"]).forEach((r, i) => { (MR[r.team] = MR[r.team] || {})[s] = i + 1; });
    const splitCell = r => {
      const sp = SPL[r.pid]; if (!sp || r.c.min === 0) return "";
      const out = [];
      for (const s of ["pts", "reb", "ast", "fg3m"]) {
        const rk = MR[r.opp]?.[s]; if (!rk || (rk > 10 && rk < 21) || !sp[s]) continue;
        const soft = rk <= 10, [n, o] = sp[s][soft ? "s" : "t"], [na, oa] = sp[s].a; if (n < 3) continue;
        out.push(`<span class="${n < 5 ? "mut" : ""}" title="${esc(r.name)} went over his own pregame ${LABEL[s]} projection in ${o} of ${n} games against the ${soft ? "softest" : "toughest"} 10 defences for ${LABEL[s]} (${esc(r.opp)} is #${rk} of 30 tonight, 1 = softest), since 2024-25. All games: ${oa} of ${na} (${num(100 * oa / Math.max(na, 1), 0)}%).${n < 5 ? " Fewer than 5 games: treat as noise." : ""}">${LABEL[s]}${soft ? "▲" : "▼"} ${o}/${n}</span>`);
      }
      return out.join(" ");
    };
    const games = [...new Set(D.projections.filter(p => p.home).map(p => p.team + "|" + p.opp))].sort();
    F.game = F.game && games.includes(F.game) ? F.game : games[0];
    const [home, away] = (F.game || "|").split("|");
    const mk = t => {
      const rows = proj().filter(p => p.team === t);
      const cols = [{k: "name", h: "Player", l: 1, f: r => esc(r.name) + ` <span class="mut">${esc(r.pos)}</span> ` + statusPill(r.status), v: r => r.name},
        {k: "cmin", h: "Min", v: r => r.c.min, f: r => num(r.c.min)},
        ...["pts", "reb", "ast", "fg3m"].map(s => ({k: "c" + s, h: LABEL[s], t: "Projection [posted line]. Line = sportsbook consensus, else PrizePicks. Green O / orange U = the model is past your edge threshold (Config) on that side; hover for each book's line.",
          v: r => cellVal(r, s), f: r => boardCell(r, s)})),
        {k: "cfp", h: "FP", v: r => r.c.fp, f: r => `<b>${boardCell(r, "fp")}</b>`},
        {k: "cvs", h: "Opp vs pos", c: "opt", l: 1, t: "Where the opposing defence ranks against his position (guards / forwards / centers) on that stat: ▲ = among the softest 10 of 30, ▼ = among the toughest 10; the number is the rank. Grey = split-half reliability under 0.2 (mostly noise). Display only: it is not in the projections.", v: r => { const x = vsRank[r.opp]?.[r.pos + "_pts"]; return x ? x.rank : 99; }, f: vsCell},
        {k: "csp", h: "Over proj vs this D", c: "opt", l: 1, t: "Games he beat his own pregame projection against defences like tonight's: ▲ = opponent is among the softest 10 for that stat, ▼ = among the toughest 10; over / games, since 2024-25. Grey = under 5 games. Display only: a 2024-25 / 2025-26 test found this record does not predict his next game.", f: splitCell}];
      return `<div><h3>${esc(t)} ${t === home ? "(home)" : "(away)"}</h3>${table(cols, rows, {id: "gb" + t, tight: true, sort: {key: "cfp"}, rowClass: r => r.c.min === 0 ? "out" : ""})}</div>`;
    };
    const h0 = D.projections.find(p => p.team === home && p.exp_margin != null);
    const env = h0 ? ` Expected margin ${esc(home)} ${h0.exp_margin >= 0 ? "+" : ""}${num(h0.exp_margin)} (from each team's average point differential, a stand-in for the spread); pace ${h0.pace_f >= 1 ? "+" : ""}${num((h0.pace_f - 1) * 100)}% vs league.` : "";
    return `<h2>Game Board</h2><p class="sub">Pick a game; both teams ranked by projected fantasy points. [Line] = consensus, else PrizePicks; <b class="good">O</b> / <b class="bad">U</b> = a side past your edge threshold; grey = projection ± a typical miss (Methodology). <b>Opp vs pos</b> flags up to two stats where the opposing defence is among the softest (▲) or toughest (▼) 10 against his position, reliable ones first; grey means the stat is mostly noise so far.${env}</p>
      <div class="bar">${rangeBox()}<select id="game">${games.map(g => `<option value="${g}" ${g === F.game ? "selected" : ""}>${g.split("|")[1]} @ ${g.split("|")[0]}</option>`).join("")}</select></div>
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
    const toggle = `<div class="bar"><label>View <select id="sview"><option value="today" ${F.sview === "today" ? "selected" : ""}>Today's hot-zone matchups</option><option value="chart" ${F.sview === "chart" ? "selected" : ""}>Shot chart (defence under a shooter)</option><option value="team" ${F.sview === "team" ? "selected" : ""}>Team shot defense</option><option value="player" ${F.sview === "player" ? "selected" : ""}>Player shot profile</option></select></label></div>`;
    const sg = x => x == null ? "" : `${x > 0 ? "+" : ""}${num(x, 1)}`;
    let body, note;
    if (F.sview === "today") {
      body = todayView(T);
      note = "";
    } else if (F.sview === "chart") {
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
    return `<h2>Shots</h2><p class="sub">${num(T.shots, 0)} field-goal attempts from ${T.games} games, from ESPN play-by-play coordinates. <b>Display only</b>: not used in the projections (see Methodology). Matching all five zones to a player's shot mix did not hold up in testing; the rim-and-paint part alone does replicate, but the effect is small. ${note}</p>
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
    return `<h2>Trends</h2><p class="sub">Rolling form against season baseline, plus consistency. FP uses the PrizePicks default weights (pts 1, reb 1.2, ast 1.5, stl 3, blk 3, tov −1) regardless of your Config choice.</p>
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
    const STATS_SHOWN = ["pts", "reb", "ast", "fg3m"], sp = D.spread || D.meta.spread;
    const card = g => {
      const head = `<strong>${esc(g.away.ab)} ${g.away.score}</strong> @ <strong>${esc(g.home.ab)} ${g.home.score}</strong>`;
      if (g.state === "pre") return `<div class="card"><span>${head.replace(/ \d+<\/strong>/g, "</strong>")}</span><br><span class="mut">tip ${new Date(g.tip).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})}</span></div>`;
      const badge = g.state === "in" ? `<span class="pill hot">LIVE</span> ` : `<span class="pill">FINAL</span> `;
      const live = g.state === "in", sn = LIVE.snap[g.id], diff = g.home.score - g.away.score;
      const elapsed = !live ? 48 : g.period <= 4 ? (g.period - 1) * 12 + (12 - clockMin(g.clock)) : 48 + (g.period - 4) * 5 - clockMin(g.clock);
      const rows = (LIVE.box[g.id] || []).map(b => {
        const q = rateOf(b.pid), o = {...b, q, gone: live && LIVE.out[b.pid] != null}, sideDiff = b.team === g.home.ab ? diff : -diff;
        o.h2 = !o.gone ? undefined : g.period < 3 ? false : (sn && sn.h1[b.pid] != null ? b.min - sn.h1[b.pid] > 0.25 : null);   // did he touch the court after halftime? (a play voids only if not)
        let remain = 0;
        if (live && q && !o.gone) {
          const absm = Math.abs(sn ? sn.margin : diff), after = g.period >= 3;
          const h1 = after ? (sn && sn.h1[b.pid] != null ? sn.h1[b.pid] : Math.min(b.min * 24 / Math.max(elapsed, 24), 24)) : (elapsed >= 4 ? Math.min(b.min * 24 / elapsed, 24) : q.min / 2);
          const h2 = halfMin(q.min, h1, b.starter, absm);
          remain = Math.max(after ? h2 - Math.max(b.min - h1, 0) : h1 + h2 - b.min, 0);
          if (g.period > 4) remain = Math.max(q.min - b.min, 0);       // overtime: no halftime model, fall back to usual minutes
        }
        for (const st of STATS_SHOWN) {
          o["f_" + st] = q ? b[st] + remain * q.per(st) : null; o["l_" + st] = lineOf[b.pid + "|" + st] ?? null;
          const ln = LIVE.lines[b.pid + "|" + st];
          if (live && q && ln != null && ln !== "") { const [a, bb] = sp[st] || [1, 0.3], full = q.min * q.per(st), mr = Math.max(remain * q.per(st), 0.01);
            const sd = Math.max((a + bb * full) * Math.sqrt(mr / Math.max(full, 0.1)), 0.3), pr = sides(ln, o["f_" + st], sd); o["p_" + st] = pr; }
        }
        for (const [ck, comp] of Object.entries(COMBO)) {                // PTS+REB+AST etc.: sum of the parts
          o[ck] = comp.reduce((a, c) => a + b[c], 0); o["f_" + ck] = q ? comp.reduce((a, c) => a + o["f_" + c], 0) : null; o["l_" + ck] = lineOf[b.pid + "|" + ck] ?? null;
          const ln = LIVE.lines[b.pid + "|" + ck];
          if (live && q && ln != null && ln !== "") { const [a, bb] = sp[ck] || [1, 0.3], per = comp.reduce((x, c) => x + q.per(c), 0), full = q.min * per, mr = Math.max(remain * per, 0.01);
            const sd = Math.max((a + bb * full) * Math.sqrt(mr / Math.max(full, 0.1)), 0.3); o["p_" + ck] = sides(ln, o["f_" + ck], sd); }
        }
        o.remain = remain; return o;
      });
      const cell = st => ({k: st, h: LABEL[st], t: "so far → projected final; [line] = pregame consensus, else PrizePicks. Type a live line in the box for P(over). Green = already over, orange = on pace to go over.",
        v: r => r["f_" + st] ?? r[st], f: r => { const f = r["f_" + st], l = r["l_" + st]; if (f == null && l == null) return String(r[st]);
          const cls = l != null ? (r[st] > l ? "good" : (f ?? r[st]) > l ? "" : "mut") : "";
          const ln = LIVE.lines[r.pid + "|" + st] ?? "", p = r["p_" + st];
          const box = live && !r.gone && r.q ? `<br><input class="ovr lvl" id="lv_${r.pid}_${st}" data-lv="${r.pid}|${st}" value="${esc(ln)}" placeholder="live line" style="width:4.5em">${p ? ` <b class="${p.o >= p.u ? "good" : "bad"}">${p.o >= p.u ? "O" : "U"} ${num(Math.max(p.o, p.u) * 100, 0)}%</b>` : ""}` : "";
          return `${r[st]}${f != null ? ` <span class="mut">→</span> <span class="${cls}">${num(f)}</span>` : ""}${l != null ? ` <span class="mut">[${l}]</span>` : ""}${box}`; }});
      const cols = [{k: "name", h: "Player", l: 1, f: r => esc(r.name) + (r.gone ? (r.h2 === true ? ` <span class="pill" title="${esc(LIVE.out[r.pid])}\n\nHe touched the court after halftime, so this play does NOT void.">OUT · played 2nd half</span>` : r.h2 === null ? ` <span class="pill hot" title="${esc(LIVE.out[r.pid])}\n\nVoids only if he did not touch the court after halftime; the page has no halftime snapshot, so check his second-half minutes.">OUT · check</span>` : ` <span class="pill hot" title="${esc(LIVE.out[r.pid])}\n\nNo second-half time so far: this play voids.">OUT · VOID</span>`) : "")}, {k: "team", h: "Team", l: 1}, {k: "min", h: "MIN", t: "minutes so far (→ projected final minutes while live)", v: r => r.min, f: r => num(r.min, 0) + (live && !r.gone && r.q ? ` <span class="mut">→ ${num(r.min + r.remain, 0)}</span>` : "")}, ...[...STATS_SHOWN, ...Object.keys(COMBO).filter(ck => F.lcombo || Object.entries(LIVE.lines).some(([k, v]) => k.endsWith("|" + ck) && v !== ""))].map(cell)];
      return `<div class="card" style="grid-column:1/-1"><div>${badge}${head} <span class="mut">· ${esc(g.detail)}${live && g.period >= 3 && !sn ? " · halftime minutes estimated (page wasn't open at halftime)" : ""}</span></div>
        <div style="margin-top:8px">${rows.length ? table(cols, rows, {id: "live" + g.id, sort: {key: "min"}}) : `<span class="mut">No box score yet.</span>`}</div></div>`;
    };
    return `<h2>Live</h2><p class="sub">Today's games, updated every 30 s${ago != null ? ` (refreshed ${ago}s ago)` : ""}${LIVE.err ? ` — <b>last refresh failed: ${esc(LIVE.err)}</b>` : ""}.
      Each stat shows <b>so far → projected final</b>: the player's per-minute rate times the minutes still expected, with the pregame line in brackets. Minutes still expected come from the <b>halftime model</b> (usual minutes, minutes played in the first half, starter or not, and a blowout cut once the margin passes 10), not "usual minus played". Type a <b>live line</b> in a stat's box to get P(over/under) for that leg (only while the game is on); players ESPN reports as not returning show <b>OUT · VOID</b>. Players in today's slate use the matchup-adjusted projection (and your Min OVR); everyone else uses season rates. Fouls are not modelled (they added almost nothing once first-half minutes are in).</p>
      <details class="doc" ${LIVE.pasteMsg || LIVE.paste ? "open" : ""}><summary><b>Paste live lines</b> <span class="mut">(from the PrizePicks board or a list)</span></summary>
        <p class="sub">One line per leg, e.g. <code>Luka Doncic points 38.5</code>, <code>Austin Reaves 27.5 Points</code>, <code>Lillard rebs+asts 6.5</code>. A copied PrizePicks card works too (name line, then <code>Cur. 16 38.5 Points</code>). Stats: points, rebounds, assists, 3-PT made, and the Pts / Rebs / Asts combinations. Names match against the players in today's box scores.</p>
        <textarea id="lvpaste" rows="5" style="width:100%" placeholder="Luka Doncic points 38.5">${esc(LIVE.paste)}</textarea>
        <div class="bar"><button id="lvapply">Apply lines</button> <button id="lvclear">Clear all live lines</button> <label><input type="checkbox" id="lcombo" ${F.lcombo ? "checked" : ""}> show combo stats</label> <span class="mut">${esc(LIVE.pasteMsg)}</span></div></details>
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
    return `<h2>Lines</h2>${liveLines()}<h3>Your own lines</h3><p class="sub">Compare a projection to a posted line. The probability uses a measured-style spread (sd = a + b × projection, per stat); treat it as directional until the spread is fitted on your data. Book P(over) has the vig removed. Pick only appears past the edge threshold (Config). The FP spread is fitted on the default (PrizePicks) scoring, so FP lines under other scoring are rougher.</p>
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
      {k: "voids", h: "Void", t: "Players who did not touch the court after halftime (missed the whole second half, or left hurt before it and did not return). Leaving hurt in the 2nd half does not void. Their plays void, so they are left out of the hit rates (the error numbers still include them).", f: r => r.voids ?? ""},
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
      const cols = [{k: "n", h: "Player", l: 1, f: r => esc(r.n) + (r.v ? ` <span class="pill hot" title="${esc(r.v)}. This play voids, so it is left out of every hit rate.">VOID</span>` : "")}, {k: "t", h: "Team", l: 1},
        {k: "mp", h: "MIN", t: "projected → actual minutes", v: r => Math.abs(r.ma - r.mp), f: r => `${num(r.mp, 0)} <span class="mut">→</span> ${num(r.ma, 0)}`},
        {k: "fp", h: "FP", t: "PrizePicks scoring, projected → actual; PP = the PrizePicks Fantasy Score line when one was posted", v: r => Math.abs(r.fp[1] - r.fp[0]),
          f: r => r.s.fp ? cell("fp").f(r) : `${num(r.fp[0])} <span class="mut">→</span> ${num(r.fp[1])}`},
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
    return `<h2>Scorecard</h2><p class="sub">Frozen-before-the-game projections vs what happened, on fantasy points (PrizePicks default), players projected for 15+ minutes. Only the current settings (●) count toward the headline.</p>
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
        <label>Line edge threshold (pp) <input id="edge" size="3" value="${CFG.edgeMin}"></label><label title="A k-pick PrizePicks entry paying M× needs M^(-1/k) per leg: your current break-even is 54.4%. Check the current payout table.">PrizePicks break-even % <input id="ppbe" size="4" value="${CFG.ppBE}"></label><label>Mean factor <b>${D.meta.mean_factor}</b> (pipeline)</label></div>
      <p class="sub">Double-double / triple-double bonuses are not modelled, so a book's totals can run slightly above the site's.</p>
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
<h3>Calibrated P(win)</h3><p>The model\'s P(win) at a PrizePicks line has been overconfident: across the first week\'s graded lines the better side won about 50-53% at every confidence level, even where the model said 70%+. <b>Cal P(win)</b> on the Lines tab is 0.5 + β × (P − 0.5), with β (separately for Overs and Unders) fitted by least squares on every graded PrizePicks line so far (voids and pushes left out) and refit on each refresh. A β near 0 says the line is close to a coin flip whatever the model says; the standard error is shown in the header hover and is large early on. Provisional: reviewed again on Nov 3 with two weeks of data.</p><h3>Results</h3><p>For each graded game day, every player's pregame projection next to his box score, with the last pregame consensus and PrizePicks lines. The model "takes" the over if its projection is above a line and the under if below; a result exactly on the line is a push and is left out. A <b>pick</b> is a line where the model's probability differs from the book's by the edge threshold (PrizePicks: from the break-even). Lines are snapshotted at each odds pull until tip-off and frozen after; if a game had no pull before tip, it has no line to grade against.</p><p><b>Voids.</b> A play voids only when the player does not touch the court after halftime: he misses the whole second half, or leaves hurt before it and never returns. Leaving hurt in the second half does not void it (he played in that half). Those players are flagged <span class="pill hot">VOID</span> and left out of every hit rate; the error numbers still include them. They are found from the lineup stints (no time on the floor after halftime); ESPN's injury notes ("won't return") add the reason and count on their own only when a game's stints are not parsed yet. Rows can be edited by hand in <code>data/log/voids.csv</code>.</p><h3>Scorecard</h3><p>Every slate's projections are logged before the games and never rewritten, then scored against the season-average and last-N baselines. Each row carries a settings stamp so a change to any knob starts a fresh record rather than blending into the old one.</p>
<h3>Typical-miss range</h3><p>Under the projections (Projections and Game Board; untick to hide) is <b>projection ± a typical miss</b>: roughly the middle 55-60% of outcomes, not a floor and ceiling. The size comes from the fitted spread, sd = a + b × projection per stat (<code>spread.json</code>), times 0.8 (mean absolute error ≈ 0.8 sd). Backtests of the opening weeks of 2025-26 ran about 13% worse than late season (fantasy-point miss 8.8 vs 7.8), so the range is widened 15% until the new season has about 15 game days of data. Low ends are floored at 0. The FP spread is fitted on the default (PrizePicks) scoring, so ranges under other scoring are rougher.</p><h3>Opening-weeks rotations and blowouts</h3><p>Coaches shorten rotations early: in the first week of both 2025-26 and 2024-25, players ranked 6th or lower on their team by projected minutes played 1.4-2.6 minutes less than projected (starters about 0.8 less), then slightly more than projected for the rest of the year. Minutes are now cut by 3% / 8% / 12% (ranks 1-5, 6-8, 9+), fading to zero over a team's first 10 games (<code>EARLY_TIGHTEN_*</code>). On the same players this cut minutes error 1.2-1.5% and fantasy-point error 1.6-2.2% in both seasons. <b>Blowouts</b> are real (games decided by 15+ cost players about 3.4 minutes against 0.6 more in close ones) but not predictable: the model's expected margin correlates 0.07 with the real margin and even the market spread only 0.22, and cutting starters' minutes by the spread did not reduce out-of-sample error, so it stays <b>tested and not modelled</b>; it is variance, which the typical-miss range already includes. About 16-20% of players projected for 15+ minutes do not play at all (rest, late scratches, coach's choice); those are not in the graded rows.</p><h3>Game environment</h3><p>Each team's pace (possessions per game, both sides) and average point margin are shrunk toward the league by games played. <b>Pace</b>: the average of the two teams' pace vs league scales per-minute rates; measured on 2025-26 the share that arrives is about 1.0 (points 1.36 [0.71, 2.06]), and the effect is small (about 1%). <b>Blowouts</b>: starters do lose about 0.3 minutes per point of expected margin beyond 9 (replicated in both halves), but fantasy-point error did not move and the half-by-half minutes error disagreed, so it is <b>tested and not modelled</b> (<code>BLOWOUT_SLOPE</code> = 0). The expected margin on the Game Board is a point-differential stand-in; swap in the real spread once pregame spreads are stored.</p>
<h3>Shot zones</h3><p>Shot locations come from ESPN's play-by-play (x/y in feet, free), grouped into rim, paint, mid-range, corner three and above-break three. No defender distance exists in the feed, so shot quality here is <b>location and type only</b>, not open vs contested. Two ideas were tested as projection inputs on 2025-26, the football way (measure how much arrives, check both halves): (1) the opponent's points-per-shot allowed in each zone, weighted by the player's own shot mix, on top of the team-wide matchup already applied: share arriving 0.19 [-0.09, 0.57], halves -0.02 and +0.42, error unchanged; (2) shooting better than his shot locations imply: it regresses further than the model already assumes (-0.24 [-0.35, -0.14], negative in both halves) but the effect is too small to move error. Neither is modelled. A follow-up cut shows why (1) was weak: restricted to the <b>rim and paint</b> zones, whose FG% allowed is reliable (split-half 0.73 and 0.75), the share arriving is 0.49 [0.09, 0.92], positive in both halves (0.52 and 0.45), while the three-point zones were anti-signal (-0.97) and dragged the all-zone number down. Softest-fifth players beat projections by about 4% on points against 2% for the toughest fifth, so the daily hot-zone list scores only rim and paint; the effect is small enough that it is shown as a nudge, not folded into the projections. The Shots tab is for reading a game. Split-half reliability is shown there: shot mix allowed and rim/paint FG% allowed are steady, mid-range and three-point FG% allowed are mostly luck.</p>\n<h3>Rookies and players with no NBA history</h3><p>A player needs 3 games of regular-season history to be projected, which used to leave out every rookie and anyone back from a missed season (135 players on current rosters). They are now built from their <b>preseason box scores</b> until real games exist: per-minute rates shrink hard toward the position average (a few preseason games say little about a rate), and minutes come from their preseason minutes through a fitted line: minutes when playing = 1.7 + 0.68 x preseason minutes (59 no-history players of 2025-26: minutes error 9.3 to 7.4, and the bias of +6 minutes gone). The earlier flat 1.1x had been fitted on every preseason player, veterans included, who play more once the season starts; rookies play less, because preseason minutes are inflated while starters rest. A quarter of the team-240 cut falls on them alone (established players keep their minutes first). Opening night 2026-27 was the check that exposed it: 5 no-history players were projected 19.5 minutes and played 3.2, while established players were on target (23.8 projected, 23.2 actual). The preseason minute adjustment is not applied to them because their minutes already are preseason minutes. Still unmodelled: who is actually in the rotation (draft position and role are not in the data), so a rookie who got heavy preseason run on a thin bench is still projected too high. Players with no preseason games either are still not projected. Treat these rows as rough: the minutes are a guess and the rates are mostly the position average.</p>
<h3>Not modelled</h3><p>Opposing-offence strength inside the defence rating, double-double bonuses, player-vs-player matchups, and in-browser minute redistribution when you override a teammate. Injury status comes from ESPN's feed and is only as current as the last build.</p>
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
  else if (t.id === "smode") { F.smode = t.value; render(); }
  else if (t.id === "cteam") { F.cteam = t.value; render(); }
  else if (t.id === "cheat") { F.cheat = t.value; render(); }
  else if (t.id === "cdots") { F.cdots = t.value; render(); }
  else if (t.id === "cplayer") { const p = (D.shots?.players || []).find(x => x.name.toLowerCase() === t.value.trim().toLowerCase()); if (p) { F.cplayer = p.pid; F.cteam = ""; render(); } }
  else if (t.id === "vstat") { F.vstat = t.value; render(); }
  else if (t.id === "vpos") { F.vpos = t.value; render(); }
  else if (t.id === "rmode") { F.rmode = t.value; F.rday = ""; render(); }
  else if (t.id === "rlines") { F.rlines = t.checked; render(); }
  else if (t.id === "rpicks") { F.rpicks = t.checked; render(); }
  else if (t.id === "edge") { CFG.edgeMin = +t.value || 0; store.set("cfg", CFG); }
  else if (t.id === "ppbe") { CFG.ppBE = +t.value || 54.4; store.set("cfg", CFG); render(); }
});
document.addEventListener("click", e => {
  const t = e.target;
  if (t.classList && t.classList.contains("scgo")) { e.preventDefault(); const [pid, opp] = t.dataset.sc.split("|"); F.cplayer = pid; F.cteam = opp; F.sview = "chart"; render(); window.scrollTo(0, 0); return; }
  if (t.id === "clr") { OVR = {}; store.set("ovr", OVR); render(); }
  if (t.id === "lvapply") { const box = document.getElementById("lvpaste"); LIVE.paste = box ? box.value : LIVE.paste; applyPaste(LIVE.paste); LIVE.paste = ""; render(); }
  if (t.id === "lvclear") { LIVE.lines = {}; store.set("livelines", LIVE.lines); LIVE.pasteMsg = "Cleared."; render(); }
  if (t.id === "ladd") {
    const line = document.getElementById("ll").value; if (line === "") return;
    LINES.push({pid: document.getElementById("lp").value, stat: document.getElementById("ls").value, line, over: document.getElementById("lo").value, under: document.getElementById("lu").value});
    store.set("lines", LINES); render();
  }
  if (t.dataset.del != null) { LINES.splice(+t.dataset.del, 1); store.set("lines", LINES); render(); }
});

async function boot() {
  const saved = store.get("cfg", {}); if (saved.ver !== 2 && saved.preset === "DraftKings") { delete saved.preset; delete saved.scoring; }   // default scoring changed to PrizePicks; keep other saved settings
  if (saved.ppBE === 57.7) delete saved.ppBE;                                   // break-even default changed to 54.4% (Oct 29): drop the old default from saved settings, keep any other value
  CFG = {...CFG, ...saved}; OVR = store.get("ovr", {}); LINES = store.get("lines", []);
  const names = ["projections", "matchups", "efficiency", "usage", "trends", "coverage", "meta", "tiers", "shots", "shotchart", "scorecard", "spread", "lines", "players", "splits", "calib"];
  await Promise.all(names.map(async n => { try { const r = await fetch(`data/${n}.json`, {cache: "no-cache"}); if (r.ok) D[n] = await r.json(); } catch (e) {} }));
  try { const r = await fetch("data/results/index.json", {cache: "no-cache"}); if (r.ok) D.rIdx = await r.json(); } catch (e) {}
  try { const r = await fetch("data/results_rehearsal/index.json", {cache: "no-cache"}); if (r.ok) D.rIdxR = await r.json(); } catch (e) {}
  if (!D.projections) { view().innerHTML = "<p>No data found in <code>data/</code>. Run <code>python -m pipeline.build</code>.</p>"; return; }
  document.getElementById("asof").textContent = `data through ${D.coverage.asof} · slate ${D.coverage.slate_date}`;
  const msgs = [];
  if (D.meta.sample) msgs.push("<b>SAMPLE DATA.</b> Players, teams' strengths and results are synthetic — nothing here is a real NBA projection. Run the fetch step to load real data.");
  if (D.meta.preseason) {
    const m = D.meta.minute_mult;
    const src = D.meta.mult_source === "fallback" ? " — a rough default, NOT learned from data yet" : " — learned from last preseason and this one so far";
    const how = m && m.lin ? `Minutes follow a line fitted to preseason box scores: ${num(m.lin[0], 1)} + ${num(m.lin[1], 2)} × his usual minutes (a 34-minute starter projects to ${num(m.lin[0] + m.lin[1] * 34, 0)}, a 12-minute reserve to ${num(m.lin[0] + m.lin[1] * 12, 0)})`
      : m ? `Minutes are scaled by tier (${Object.entries(m).map(([t, v]) => `${t} ×${v}`).join(", ")}; T1 = 30+ mpg)` : "";
    msgs.push(m ? `<b>PRESEASON slate.</b> ${how}${src}, and each projection assumes the player suits up — stars often sit. Not logged to the Scorecard.`
                : "<b>PRESEASON slate with NO minutes adjustment</b> — stars will be projected for regular-season minutes. Run <code>python -m pipeline.preseason_minutes</code>.");
  }
  if (msgs.length) { const b = document.getElementById("banner"); b.hidden = false; b.innerHTML = msgs.join("<br>"); }
  route();
}
boot();

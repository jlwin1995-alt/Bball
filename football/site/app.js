"use strict";
// ---------- state ----------------------------------------------------------
const TABS = ["Projections", "Game Board", "Leaders", "Matchups", "Efficiency", "Usage", "Trends", "Weather", "Lines", "Results", "Scorecard", "Backtest", "Config", "Methodology"];
const D = {};
let CFG = {preset: "Full PPR", scoring: {...FB.SCORING["Full PPR"]}, mean: false, detail: false, edgeMin: 4, ppBE: 57.7};
let LINES = [];
const RES = {}, RES_PENDING = {};                    // results/<season>-<week>.json cache                                     // your own typed lines [{id, stat, line, over, under}]
let OVR = {};                                       // {playerId: {car, tgt, rec, att}}
const store = {
  get(k, d) { try { const v = localStorage.getItem("gm_" + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("gm_" + k, JSON.stringify(v)); } catch (e) {} },
};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const num = (x, d = 1) => x == null || x === "" || Number.isNaN(+x) ? "" : Number(x).toFixed(d);
const view = () => document.getElementById("view");
const SCORE_LABEL = {passYd: "Pass yd", passTd: "Pass TD", intr: "INT", rushYd: "Rush yd", rushTd: "Rush TD", recYd: "Rec yd", recTd: "Rec TD", rec: "Reception", fum: "Fumble lost", two: "2-pt conv"};
const POS = ["QB", "RB", "WR", "TE"];
// stat key (as the model and the odds feed name it) -> field on the calc() result
const MKT = {passY: "passY", rushY: "rushY", recY: "recY", rec: "rec", comp: "comp", sacks: "sacks"};
const mktSpec = k => D.meta.markets[k];
const warn = e => e != null && Math.abs(e) >= 15 ? ` <span title="An edge this large is usually the model having a player's role wrong (injury news, a depth-chart change, a game that has already started), not a bargain. Check before trusting it." style="cursor:help">⚠</span>` : "";

const isOut = s => /^(out|ir)/i.test(s || "");
const koDate = iso => iso ? new Date(iso) : null;
const started = iso => { const d = koDate(iso); return d ? d.getTime() <= Date.now() : false; };
const koLabel = iso => { const d = koDate(iso); return d ? d.toLocaleString(undefined, {weekday: "short", hour: "numeric", minute: "2-digit"}) : ""; };

// ---------- model (client side: pipeline volumes x rates x matchup multipliers) ----------
function calcFor(p) {
  const c = FB.calc(p, OVR[p.id], CFG.scoring, D.meta);
  c.shown = c.pts * (CFG.mean ? D.meta.mean_factor : 1);         // Proj Pts is a MEDIAN; Mean = median x MEAN_FACTOR
  return c;
}
const proj = () => D.projections.map(p => ({...p, c: calcFor(p)}));

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
const F = {q: "", pos: "", team: "", hideStarted: false, game: "", effView: "QB", year: "", minG: 0, lstat: "", lgame: "", lpicks: false, rweek: "", rmkt: "pts", rlines: false, rpicks: false};
function teams() { return [...new Set(D.projections.map(p => p.team))].sort(); }
function filters(extra = "", {team = false} = {}) {
  return `<div class="bar"><input id="q" placeholder="Search player / team" value="${esc(F.q)}">
  <label>Pos <select id="pos">${["", ...POS].map(p => `<option ${F.pos === p ? "selected" : ""} value="${p}">${p || "All"}</option>`).join("")}</select></label>
  ${team ? `<label>Team <select id="team">${["", ...teams()].map(t => `<option ${F.team === t ? "selected" : ""} value="${t}">${t || "All"}</option>`).join("")}</select></label>` : ""}${extra}</div>`;
}
function passes(r) {
  if (F.pos && r.pos !== F.pos) return false;
  if (F.team && r.team !== F.team && r.opp !== F.team) return false;
  const q = F.q.trim().toLowerCase();
  return !q || (r.name + " " + r.team).toLowerCase().includes(q);
}
document.addEventListener("input", e => { if (e.target.id === "q") { F.q = e.target.value; render(true, "q"); } });

// ---------- small formatters ---------------------------------------------------
const adj = x => x == null ? "" : `<span class="${x > 1.005 ? "good" : x < 0.995 ? "bad" : "mut"}">${num((x - 1) * 100, 1)}%</span>`;
const signed = (x, d = 1) => x == null || x === "" ? "" : `<span class="${x > 0 ? "good" : x < 0 ? "bad" : "mut"}">${x > 0 ? "+" : ""}${num(x, d)}</span>`;
const statusPill = s => s ? `<span class="pill ${isOut(s) || /doubt/i.test(s) ? "bad" : "q"}">${esc(s)}</span>` : "";
// change in error against a baseline: negative means the model made smaller misses, so negative is the good colour
const plainSigned = x => x == null ? "" : (x > 0 ? "+" : "") + num(x, 1);
const vsBase = x => x == null ? "" : `<span class="${x < 0 ? "good" : x > 0 ? "bad" : "mut"}">${x > 0 ? "+" : ""}${num(x, 1)}%</span>`;
const formPill = f => f === "HOT" ? `<span class="pill hot">HOT</span>` : f === "COLD" ? `<span class="pill cold">COLD</span>` : `<span class="mut">${esc(f || "")}</span>`;
const vsOpp = r => (r.home ? "vs " : "@ ") + esc(r.opp);
function spark(a) {
  if (!a || a.length < 2) return "";
  const w = 70, h = 18, mx = Math.max(...a, 1), mn = Math.min(...a, 0), step = w / (a.length - 1);
  const pts = a.map((v, i) => `${(i * step).toFixed(1)},${(h - 1 - (v - mn) / (mx - mn || 1) * (h - 2)).toFixed(1)}`).join(" ");
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
}
const ovrCell = (r, key, shown) => `<input class="ovr" data-id="${esc(r.id)}" data-key="${key}" value="${OVR[r.id]?.[key] ?? ""}" placeholder="${num(shown)}">`;

// ---------- pages ---------------------------------------------------------------
const pages = {
  Projections() {
    let rows = proj().filter(passes);
    if (F.hideStarted) rows = rows.filter(r => !started(r.ko));
    const det = CFG.detail;
    const cols = [...nameCols, {k: "opp", h: "Opp", l: 1, f: vsOpp, v: r => r.opp},
      {k: "status", h: "Status", l: 1, f: r => statusPill(r.status)},
      ...(det ? [{k: "g", h: "G", t: "Games in this season's sample"}, {k: "rest", h: "Rest", t: "Days since the team's last game"},
        {k: "wind", h: "Wind", t: "mph at kickoff (recorded, forecast, or blank = indoor/unknown)", f: r => num(r.wind)}] : []),
      {k: "caro", h: "Car OVR", t: "Type carries to override. Teammates are NOT re-scaled. Saved on this device.", v: r => OVR[r.id]?.car, f: r => ovrCell(r, "car", r.car)},
      {k: "ccar", h: "Car", v: r => r.c.car, f: r => num(r.c.car)},
      ...(det ? [{k: "ccsh", h: "Car %", t: "Share of the team's projected carries", v: r => r.c.carSh, f: r => num(r.c.carSh)},
        {k: "ypc", h: "Y/C", f: r => num(r.ypc, 2)}, {k: "arush", h: "Rush Adj", v: r => r.a_rush, f: r => adj(r.a_rush)}] : []),
      {k: "cry", h: "Rush Yds", v: r => r.c.rushY, f: r => num(r.c.rushY)},
      {k: "tgto", h: "Tgt OVR", t: "Type targets to override", v: r => OVR[r.id]?.tgt, f: r => ovrCell(r, "tgt", r.tgt)},
      {k: "ctgt", h: "Tgt", v: r => r.c.tgt, f: r => num(r.c.tgt)},
      ...(det ? [{k: "ctsh", h: "Tgt %", v: r => r.c.tgtSh, f: r => num(r.c.tgtSh)}, {k: "cr", h: "Catch %", f: r => num(r.cr * 100)},
        {k: "acatch", h: "Catch Adj", v: r => r.a_catch, f: r => adj(r.a_catch)},
        {k: "reco", h: "Rec OVR", t: "Type receptions to override (otherwise targets x catch rate x matchup)", v: r => OVR[r.id]?.rec, f: r => ovrCell(r, "rec", r.c.rec)}] : []),
      {k: "crec", h: "Rec", v: r => r.c.rec, f: r => num(r.c.rec)},
      ...(det ? [{k: "ypr", h: "Y/Rec", f: r => num(r.ypr, 1)}, {k: "aypr", h: "Y/Rec Adj", v: r => r.a_ypr, f: r => adj(r.a_ypr)}] : []),
      {k: "crecy", h: "Rec Yds", v: r => r.c.recY, f: r => num(r.c.recY)},
      {k: "atto", h: "Att OVR", t: "Type pass attempts to override", v: r => OVR[r.id]?.att, f: r => ovrCell(r, "att", r.att)},
      {k: "catt", h: "Att", v: r => r.c.att, f: r => num(r.c.att)},
      {k: "ccomp", h: "Comp", v: r => r.c.comp, f: r => r.c.att > 0 ? num(r.c.comp) : ""},
      ...(det ? [{k: "ypa", h: "Y/A", f: r => r.c.att > 0 ? num(r.ypa, 2) : ""}, {k: "apass", h: "Pass Adj", v: r => r.a_pass, f: r => r.c.att > 0 ? adj(r.a_pass) : ""}] : []),
      {k: "cpy", h: "Pass Yds", v: r => r.c.passY, f: r => r.c.att > 0 ? num(r.c.passY) : ""},
      {k: "csk", h: "Sacks", v: r => r.c.sacks, f: r => r.c.att > 0 ? num(r.c.sacks, 2) : ""},
      {k: "crtd", h: "Rush TD", v: r => r.c.rushTD, f: r => num(r.c.rushTD, 2)},
      {k: "crectd", h: "Rec TD", v: r => r.c.recTD, f: r => num(r.c.recTD, 2)},
      {k: "cptd", h: "Pass TD", v: r => r.c.passTD, f: r => r.c.att > 0 ? num(r.c.passTD, 2) : ""},
      ...(det ? [{k: "cint", h: "INT", v: r => r.c.int, f: r => r.c.att > 0 ? num(r.c.int, 2) : ""}, {k: "cfum", h: "Fum", v: r => r.c.fum, f: r => num(r.c.fum, 2)}] : []),
      {k: "cpts", h: CFG.mean ? "Mean Pts" : "Proj Pts", v: r => r.c.shown, f: r => `<b>${num(r.c.shown)}</b>`},
      {k: "ovp", h: "Opp vs Pos", t: "What the opponent gives up to this player's position group on his main market (rate-based, defence only), and where it ranks among the slate's defences (1 = most generous)",
        v: r => r.ovp, f: r => r.ovp == null ? "" : `${signed(r.ovp)}% <span class="mut">${esc(r.ork || "")}</span>`}];
    return `<h2>Projections — Week ${D.meta.week}</h2>
      <p class="sub">${CFG.mean ? "Mean" : "Median"} points for every player with a game this week. Shaded <b>OVR</b> boxes are yours; everything recalculates instantly (teammates are not re-scaled). Scoring: ${esc(CFG.preset)}.</p>
      ${filters(`<label><input type="checkbox" id="hidestarted" ${F.hideStarted ? "checked" : ""}> hide games already started</label>
        <label><input type="checkbox" id="detail" ${CFG.detail ? "checked" : ""}> more columns</label><button id="clr">Clear overrides</button>`, {team: true})}
      ${table(cols, rows, {id: "proj" + (det ? "d" : ""), sort: {key: "cpts"}, rowClass: r => isOut(r.status) ? "out" : started(r.ko) ? "started" : ""})}`;
  },

  "Game Board"() {
    const games = D.games;
    if (!F.game || !games.some(g => g.game === F.game)) F.game = (games.find(g => !started(g.ko)) || games[0]).game;
    const g = games.find(x => x.game === F.game);
    const all = proj();
    const mk = t => {
      const rows = all.filter(p => p.team === t && p.game === g.game);
      const cols = [{k: "name", h: "Player", l: 1}, {k: "pos", h: "Pos", l: 1}, {k: "status", h: "Status", l: 1, f: r => statusPill(r.status)},
        {k: "ccar", h: "Car", v: r => r.c.car, f: r => num(r.c.car)}, {k: "cry", h: "Rush", v: r => r.c.rushY, f: r => num(r.c.rushY, 0)},
        {k: "crec", h: "Rec", v: r => r.c.rec, f: r => num(r.c.rec)}, {k: "crecy", h: "Rec Yds", v: r => r.c.recY, f: r => num(r.c.recY, 0)},
        {k: "catt", h: "Att", v: r => r.c.att, f: r => r.c.att > 0 ? num(r.c.att) : ""}, {k: "cpy", h: "Pass Yds", v: r => r.c.passY, f: r => r.c.att > 0 ? num(r.c.passY, 0) : ""},
        {k: "ctd", h: "TD", v: r => r.c.rushTD + r.c.recTD + r.c.passTD, f: r => num(r.c.rushTD + r.c.recTD + r.c.passTD, 2)},
        {k: "cpts", h: "Pts", v: r => r.c.shown, f: r => `<b>${num(r.c.shown)}</b>`}];
      const live = rows.filter(r => !isOut(r.status)), nOut = rows.length - live.length;
      const tot = live.reduce((a, r) => a + r.c.shown, 0);
      return `<div><h3>${esc(t)} <span class="mut">· ${num(tot)} projected pts across ${live.length} players${nOut ? ` (${nOut} listed out, not counted)` : ""}</span></h3>${table(cols, rows, {id: "gb" + t, sort: {key: "cpts"}})}</div>`;
    };
    const wx = g.src === "indoor" || g.roof === "indoor" ? "indoors" : g.wind != null ? `${num(g.wind, 0)} mph wind${g.temp != null ? `, ${num(g.temp, 0)}°F` : ""} <span class="mut">(${esc(g.src)})</span>` : "weather unknown";
    const sp = g.spread == null ? "" : g.spread > 0 ? `${g.home} -${num(g.spread)}` : g.spread < 0 ? `${g.away} -${num(-g.spread)}` : "pick'em";
    return `<h2>Game Board</h2><p class="sub">Pick a game; both teams ranked by projected points.</p>
      <div class="bar"><label>Game <select id="game">${games.map(x => `<option value="${esc(x.game)}" ${x.game === g.game ? "selected" : ""}>${esc(x.game)} · ${esc(koLabel(x.ko))}${x.played ? " (final)" : started(x.ko) ? " (started)" : ""}</option>`).join("")}</select></label></div>
      <div class="gamehead"><div><span>Kickoff</span><b>${esc(koLabel(g.ko))}</b></div><div><span>Stadium</span><b>${esc(g.stadium)}</b></div>
        <div><span>Weather</span><b>${wx}</b></div>${g.spread == null ? "" : `<div><span>Line (nflverse)</span><b>${esc(sp)} · O/U ${num(g.total)}</b></div>
        <div><span>Implied total</span><b>${esc(g.away)} ${num(g.away_imp)} – ${esc(g.home)} ${num(g.home_imp)}</b></div>`}</div>
      <div class="two">${mk(g.away)}${mk(g.home)}</div>`;
  },

  Leaders() {
    const rows = proj().filter(r => !isOut(r.status));          // a player ruled out is shown on Projections but cannot lead a category
    const CATS = [["Projected points", r => r.c.shown, 1], ["Rushing yards", r => r.c.rushY, 1], ["Receiving yards", r => r.c.recY, 1],
      ["Passing yards", r => r.c.passY, 1], ["Receptions", r => r.c.rec, 1], ["Carries", r => r.c.car, 1], ["Pass attempts", r => r.c.att, 1],
      ["Completions", r => r.c.comp, 1], ["Total TDs", r => r.c.rushTD + r.c.recTD + r.c.passTD, 2]];
    const n = F.leaderN || 15;
    return `<h2>Projected Leaders — Week ${D.meta.week}</h2><p class="sub">Top ${n} by projected output for the week ahead, not season totals. Players listed Out are excluded.</p>
      <div class="lead">${CATS.map(([label, f, dp]) => {
        const top = [...rows].map(r => ({r, v: f(r)})).filter(x => x.v > 0).sort((a, b) => b.v - a.v).slice(0, n);
        return `<div class="card"><h4>${label}</h4><ol>${top.map(x => `<li><b>${esc(x.r.name)}</b> <span>${esc(x.r.team)} · ${num(x.v, dp)}</span></li>`).join("")}</ol></div>`;
      }).join("")}</div>`;
  },

  Matchups() {
    // per offence: the multipliers applied to its players this week (rushing, receiving yards-per-catch, passing) and one headline number
    const by = {};
    for (const p of D.projections) {
      const t = by[p.team] ||= {team: p.team, opp: p.opp, home: p.home, rush: 0, rn: 0, rec: 0, pass: 0, n: 0, pts: 0};
      if (p.a_rush) { t.rush += p.a_rush; t.rn++; }
      t.rec += p.a_ypr; t.pass += p.a_pass; t.n++; if (!isOut(p.status)) t.pts += calcFor(p).shown;
    }
    const rk = Object.values(by).map(t => {
      const rush = t.rn ? t.rush / t.rn : 1, rec = t.rec / t.n, pass = t.pass / t.n;
      return {...t, rush, rec, pass, overall: (rush + (rec + pass) / 2) / 2};
    });
    const c1 = [{k: "team", h: "Team", l: 1}, {k: "opp", h: "Opp", l: 1, f: vsOpp, v: r => r.opp},
      {k: "overall", h: "Overall", t: "Rushing weighted equally against the passing game as a whole", f: r => adj(r.overall)},
      {k: "rush", h: "Rush Adj", f: r => adj(r.rush)}, {k: "rec", h: "Y/Rec Adj", f: r => adj(r.rec)}, {k: "pass", h: "Pass Adj", f: r => adj(r.pass)},
      {k: "pts", h: "Team Proj Pts", f: r => num(r.pts)}];
    const M = D.matchups, a3 = k => r => adj(r[k]);
    const c2 = [{k: "team", h: "Defense", l: 1}, {k: "car", h: "Carries faced"}, {k: "ypc", h: "Y/C allowed", f: r => num(r.ypc, 2)},
      {k: "r10", h: "10+ run %", t: "Shown but NOT modelled: the steadiest rushing-defence number, but blending it in made the backtest marginally worse", f: r => num(r.r10)},
      {k: "rush", h: "Rush Adj", f: a3("rush")}, {k: "tgt", h: "Targets faced"}, {k: "catch_pct", h: "Catch % allowed", f: r => num(r.catch_pct * 100)},
      {k: "catch", h: "Catch Adj", f: a3("catch")}, {k: "ypr_a", h: "Y/Rec allowed", f: r => num(r.ypr_a, 2)}, {k: "ypr", h: "Y/Rec Adj", f: a3("ypr")},
      {k: "pass_", h: "Y/Tgt Adj", t: "Yards per target allowed (drives passing yards)", f: a3("pass_")}, {k: "comp", h: "Comp Adj", f: a3("comp")},
      {k: "rtd", h: "RushTD Adj", f: a3("rtd")}, {k: "rectd", h: "RecTD Adj", f: a3("rectd")}, {k: "ptd", h: "PassTD Adj", f: a3("ptd")},
      {k: "catch_wr", h: "Catch vs WR", f: a3("catch_wr")}, {k: "catch_te", h: "Catch vs TE", f: a3("catch_te")}, {k: "catch_rb", h: "Catch vs RB", f: a3("catch_rb")},
      {k: "ypr_wr", h: "Y/Rec vs WR", f: a3("ypr_wr")}, {k: "ypr_te", h: "Y/Rec vs TE", f: a3("ypr_te")}, {k: "ypr_rb", h: "Y/Rec vs RB", f: a3("ypr_rb")},
      {k: "faces", h: `Faces in wk ${M.week}`, l: 1}];
    return `<h2>Matchups — Week ${D.meta.week}</h2>
      <p class="sub">Above 0% means the opponent has been easier than average to gain on; below, harder. Every value is regressed by how many plays the defence has faced and then capped, so early in a season most sit near 0%.</p>
      <h3>This week, softest matchup first</h3>${table(c1, rk, {id: "mr", sort: {key: "overall"}})}
      <h3>Every defence</h3>${table(c2, M.rows, {id: "md", sort: {key: "rush"}})}
      <div class="doc"><p class="mut">League baseline: ${num(M.lg.ypc, 2)} Y/C, ${num(M.lg.catch, 3)} catch rate, ${num(M.lg.ypr, 2)} Y/Rec. Per position — ${Object.entries(M.lg.pos).map(([p, v]) => `${p} ${num(v.catch, 3)} / ${num(v.ypr, 1)} Y/Rec`).join(", ")}.
      The three TD columns are derived from the yardage columns, not from touchdowns allowed (a defence's own TD rate allowed barely predicts its future one). The position columns regress toward that defence's own overall number; tight-end splits are switched off because how a defence did against tight ends in one half of a season tells you nothing about the other.</p></div>`;
  },

  Efficiency() {
    const v = F.effView;
    const base = [...nameCols, {k: "g", h: "G"}, {k: "snap", h: "Snap %", f: r => num(r.snap)}];
    const sets = {
      QB: [{k: "att", h: "Att"}, {k: "ypa", h: "Y/A", f: r => num(r.ypa, 2)}, {k: "anya", h: "ANY/A", t: "(yards + 20 x TD - 45 x INT - sack yards) / dropbacks", f: r => num(r.anya, 2)},
        {k: "comp", h: "Comp %", f: r => num(r.comp)}, {k: "cpoe", h: "CPOE", f: r => signed(r.cpoe, 2)}, {k: "epa_db", h: "EPA/DB", f: r => signed(r.epa_db, 3)},
        {k: "adot", h: "aDOT", f: r => num(r.adot)}, {k: "ptd", h: "TD %", f: r => num(r.ptd)}, {k: "int", h: "INT %", f: r => num(r.int)}, {k: "sack", h: "Sack %", f: r => num(r.sack)}],
      Rushing: [{k: "car", h: "Car"}, {k: "ypc", h: "Y/C", f: r => num(r.ypc, 2)}, {k: "r1d", h: "1D %", f: r => num(r.r1d)}, {k: "epa_car", h: "EPA/Car", f: r => signed(r.epa_car, 3)}, {k: "rtd", h: "TD %", f: r => num(r.rtd)}],
      Receiving: [{k: "tgt", h: "Tgt"}, {k: "rec", h: "Rec"}, {k: "ypt", h: "Y/Tgt", f: r => num(r.ypt, 2)}, {k: "ypr", h: "Y/Rec", f: r => num(r.ypr, 2)},
        {k: "catch", h: "Catch %", f: r => num(r.catch)}, {k: "radot", h: "aDOT", f: r => num(r.radot)}, {k: "yac", h: "YAC/Rec", f: r => num(r.yac, 2)},
        {k: "epa_tgt", h: "EPA/Tgt", f: r => signed(r.epa_tgt, 3)}, {k: "racr", h: "RACR", t: "Receiving yards / air yards", f: r => num(r.racr, 2)}, {k: "r1dt", h: "1D %", f: r => num(r.r1dt)}],
    };
    const key = {QB: "att", Rushing: "car", Receiving: "tgt"}[v];
    const rows = D.efficiency.filter(passes).filter(r => r[key] != null);
    return `<h2>Efficiency</h2><p class="sub">Season to date, minimum ${key === "att" ? "25 attempts" : key === "car" ? "10 carries" : "8 targets"}. Snap % is offensive snaps.</p>
      ${filters(`<label>View <select id="effview">${Object.keys(sets).map(s => `<option ${v === s ? "selected" : ""}>${s}</option>`).join("")}</select></label>`)}
      ${table([...base, ...sets[v], {k: "ppr_g", h: "PPR/G", f: r => `<b>${num(r.ppr_g)}</b>`}], rows, {id: "eff" + v, sort: {key: sets[v][0].k}})}`;
  },

  Usage() {
    const rows = D.usage.filter(passes);
    const cols = [...nameCols, {k: "g", h: "G"}, {k: "snap", h: "Snap %", f: r => num(r.snap)}, {k: "tgt", h: "Tgt"}, {k: "tgt_g", h: "Tgt/G", f: r => num(r.tgt_g)},
      {k: "tgt_sh", h: "Tgt Share %", f: r => num(r.tgt_sh)}, {k: "air", h: "Air Yds", f: r => num(r.air, 0)}, {k: "air_sh", h: "Air Share %", f: r => num(r.air_sh)},
      {k: "wopr", h: "WOPR", t: "1.5 x target share + 0.7 x air-yards share", f: r => num(r.wopr, 3)}, {k: "car", h: "Car"}, {k: "car_g", h: "Car/G", f: r => num(r.car_g)},
      {k: "car_sh", h: "Carry Share %", f: r => num(r.car_sh)}, {k: "touches", h: "Touches"}, {k: "touch_g", h: "Touch/G", f: r => num(r.touch_g)},
      {k: "opp", h: "Opp"}, {k: "opp_g", h: "Opp/G", f: r => num(r.opp_g)}, {k: "opp_sh", h: "Opp Share %", t: "(carries + targets) over the team's", f: r => `<b>${num(r.opp_sh)}</b>`}];
    return `<h2>Usage</h2><p class="sub">Share of team opportunity, season to date. Opportunity = carries + targets.</p>${filters()}${table(cols, rows, {id: "usage", sort: {key: "opp_sh"}})}`;
  },

  Trends() {
    const rows = D.trends.filter(passes).filter(r => !F.minG || r.g >= F.minG);
    const cols = [...nameCols, {k: "g", h: "G"}, {k: "ppr_g", h: "PPR/G", f: r => num(r.ppr_g)}, {k: "ppr_r", h: "Last " + (D.meta.window || 3), f: r => `<b>${num(r.ppr_r)}</b>`},
      {k: "d", h: "Δ", f: r => signed(r.d)}, {k: "dpct", h: "Δ %", f: r => signed(r.dpct)}, {k: "yds_g", h: "Yds/G", f: r => num(r.yds_g)}, {k: "dyds", h: "Yds Δ", f: r => signed(r.dyds)},
      {k: "opp_g", h: "Opp/G", f: r => num(r.opp_g)}, {k: "dopp", h: "Opp Δ", f: r => signed(r.dopp)}, {k: "epa_g", h: "EPA/G", f: r => num(r.epa_g, 2)},
      {k: "sd", h: "StdDev", f: r => num(r.sd)}, {k: "cv", h: "CV", t: "Std dev / mean: lower = steadier", f: r => num(r.cv, 2)}, {k: "floor", h: "Floor", f: r => num(r.floor)}, {k: "ceil", h: "Ceiling", f: r => num(r.ceil)},
      {k: "last", h: "Weekly PPR", v: null, f: r => spark(r.last)}, {k: "form", h: "Form", l: 1, f: r => formPill(r.form)}];
    return `<h2>Trends</h2><p class="sub">Rolling form against the season. HOT/COLD needs scoring <i>and</i> opportunity to move together (PPR more than 15% off the season pace without opportunity moving the other way).</p>
      ${filters(`<label>Min games <input id="ming" type="number" min="0" max="18" style="width:60px" value="${F.minG}"></label>`)}${table(cols, rows, {id: "trends", sort: {key: "ppr_r"}})}`;
  },

  Weather() {
    const cols = [{k: "game", h: "Game", l: 1}, {k: "stadium", h: "Stadium", l: 1}, {k: "roof", h: "Roof", l: 1}, {k: "day", h: "Date", l: 1}, {k: "time", h: "Kickoff (ET)", l: 1},
      {k: "temp", h: "Temp F", f: r => num(r.temp, 0)}, {k: "wind", h: "Wind mph", f: r => num(r.wind)}, {k: "gust", h: "Gust mph", f: r => num(r.gust)},
      {k: "precip", h: "Precip %", f: r => num(r.precip, 0)}, {k: "rain", h: "Rain mm", f: r => num(r.rain, 2)}, {k: "src", h: "Source", l: 1},
      {k: "yds", h: "Yds Adj", t: "Multiplier on passing and receiving yardage", f: r => adj(r.yds)}, {k: "rec", h: "Rec Adj", t: "Receptions and completion rate: half the yardage move", f: r => adj(r.rec)},
      {k: "rush", h: "Rush Adj", f: r => adj(r.rush)}];
    return `<h2>Weather — Week ${D.meta.week}</h2>
      <p class="sub">Wind only starts to bite at ${D.meta.weather.threshold} mph; below that the multipliers are 1.000 by design. ${D.meta.weather.on ? "" : "<b class='bad'>WEATHER IS OFF: every multiplier is 1.000.</b>"}</p>
      ${table(cols, D.weather, {id: "wx", sort: {key: "yds", asc: true}})}
      <div class="doc"><p class="mut"><b>Source</b>: "recorded" is what actually blew (nflverse backfills it after kickoff), "forecast" is Open-Meteo at the kickoff hour, "unknown" means no reading and no adjustment. Retractable roofs with no state published are treated as indoor: between a false adjustment and a missed one, take the missed one.
      Temperature and rain are shown but deliberately <b>not modelled</b>: temperature is not even monotonic, and once wind is held constant rain moves residuals in no consistent direction (wet games mostly just blow harder).
      To force a reading you trust more, add <code>{"BUF @ MIA": 22}</code> to <code>football/data/wind_overrides.json</code> and rebuild.</p></div>`;
  },


  Lines() {
    const L = D.lines, M = L && L.meta;
    const credits = M && M.credits != null ? ` · Odds API credits left: <b>${M.credits}</b>` : "";
    const byId = Object.fromEntries(proj().map(p => [p.id, p]));
    let live = "";
    if (!L || !L.rows || !L.rows.length) {
      if (!M) live = `<p class="sub">No live lines yet. They come from The Odds API: add your key as the <code>ODDS_API_KEY</code> repository secret and run the "Football refresh odds" workflow (see the README).</p>`;
      else {
        const ago = Math.max(0, Math.round((Date.now() - Date.parse(M.ts)) / 60000)), when = ago < 90 ? ago + " min ago" : Math.round(ago / 60) + " h ago";
        const games = (M.games || []).map(g => `<li>${esc(g.game)} — kickoff ${new Date(g.commence).toLocaleString([], {weekday: "short", hour: "numeric", minute: "2-digit"})}: ${g.props ? g.props + " props posted" : "<b>no player props posted yet</b>"}</li>`).join("");
        live = `<p class="sub">Last checked ${when}${credits}. ${games ? "Upcoming games found:" : "No games start in the next 30 hours."}</p>${games ? `<ul class="sub">${games}</ul>` : ""}
          <p class="sub">Books usually post player props on Tuesday/Wednesday for Thursday, and a day or two ahead for Sunday. This page fills in automatically on the next check.</p>`;
      }
    } else {
      const BE = CFG.ppBE / 100;
      const upd = /[zZ]|[+-]\d\d:?\d\d$/.test(L.updated) ? L.updated : L.updated + "Z", mins = Math.round((Date.now() - Date.parse(upd)) / 60000);
      let rows = L.rows.map(r => {
        const p = byId[r.id]; if (!p) return null;
        const spec = mktSpec(r.stat), m = p.c[MKT[r.stat]], c = r.cons, pp = r.dfs.prizepicks;
        const st = Date.now() >= Date.parse(r.commence), outp = isOut(p.status);
        const o = {started: st, name: p.name, pos: p.pos, team: p.team, game: r.game, stat: r.stat, m, c, r, pp, ud: r.dfs.underdog ?? r.dfs.pick6};
        if (c) { const sd = FB.sides(c.line, m, spec); o.po = sd.o; o.edge = (sd.o - c.p_over) * 100; o.pick = st ? "LIVE" : outp ? "OUT" : Math.abs(o.edge) >= CFG.edgeMin ? (o.edge > 0 ? "OVER" : "UNDER") : ""; }
        if (pp != null) { const sd = FB.sides(pp, m, spec); o.side = sd.o >= sd.u ? "OVER" : "UNDER"; o.pw = Math.max(sd.o, sd.u); o.ppEdge = (o.pw - BE) * 100;
          o.ppPick = st ? "LIVE" : outp ? "OUT" : o.ppEdge >= CFG.edgeMin ? "PP " + o.side : ""; o.gap = c ? pp - c.line : null; }
        return o;
      }).filter(Boolean).filter(passes);
      if (F.lstat) rows = rows.filter(r => r.stat === F.lstat);
      if (F.lgame) rows = rows.filter(r => r.game === F.lgame);
      if (F.lpicks) rows = rows.filter(r => (r.pick && r.pick !== "OUT" && r.pick !== "LIVE") || (r.ppPick && r.ppPick !== "OUT" && r.ppPick !== "LIVE"));
      const tip = r => r.r.books.map(b => `${b.b} ${b.line} (${b.over ?? "-"}/${b.under ?? "-"})`).join("\n");
      const cols = [{k: "name", h: "Player", l: 1}, {k: "team", h: "Team", l: 1},
        {k: "game", h: "Game", l: 1, f: r => esc(r.game) + (r.started ? ` <span class="pill hot" title="Kicked off: these are the last PRE-game lines. The model's pregame probability no longer applies, so no pick is shown.">LIVE</span>` : "")},
        {k: "stat", h: "Market", l: 1, f: r => esc(mktSpec(r.stat).label)}, {k: "m", h: "Proj", t: "Median projection, with your volume overrides", f: r => num(r.m)},
        {k: "cl", h: "Cons line", t: "Median sportsbook line; hover for every book", v: r => r.c?.line, f: r => r.c ? `<span title="${esc(tip(r))}">${r.c.line} <span class="mut">${r.c.n}/${r.c.n_books}</span></span>` : ""},
        {k: "cp", h: "Cons P(over)", t: "Average vig-free P(over) of the books at the consensus line", v: r => r.c?.p_over, f: r => r.c ? num(r.c.p_over * 100) + "%" : ""},
        {k: "fo", h: "Fair odds", t: "Over / under, from the consensus probability", v: r => r.c?.p_over, f: r => r.c ? `${FB.amer(r.c.p_over)} / ${FB.amer(1 - r.c.p_over)}` : ""},
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
      const extra = `<label>Market <select id="lstat"><option value="">All</option>${stats.map(x => `<option value="${x}" ${F.lstat === x ? "selected" : ""}>${esc(mktSpec(x).label)}</option>`).join("")}</select></label>
        <label>Game <select id="lgame"><option value="">All</option>${games.map(g => `<option ${F.lgame === g ? "selected" : ""}>${esc(g)}</option>`).join("")}</select></label>
        <label><input type="checkbox" id="lpicks" ${F.lpicks ? "checked" : ""}> picks only</label>`;
      live = `<p class="sub">Sportsbook consensus (median line; vig removed) beside PrizePicks / Underdog, with the model's edge against each${credits}. Updated ${mins < 90 ? mins + " min" : Math.round(mins / 60) + " h"} ago${mins > 360 ? " — <b>stale, lines move</b>" : ""}. DFS prices are nominal, so PrizePicks edge is measured against your break-even (Config) rather than odds. A k-pick entry paying M× needs M^(−1/k) per leg.</p>
        ${filters(extra)}${table(cols, rows, {id: "live", sort: {key: "edge"}})}`;
    }
    const own = LINES.map((l, i) => {
      const p = byId[l.id]; if (!p) return "";
      const spec = mktSpec(l.stat), m = p.c[MKT[l.stat]], sd = FB.sides(l.line, m, spec);
      const io = FB.impl(l.over), iu = FB.impl(l.under), book = io && iu ? io / (io + iu) : io;   // vig removed
      const edge = book == null ? null : (sd.o - book) * 100;
      const pick = edge == null || Math.abs(edge) < CFG.edgeMin ? "" : edge > 0 ? "OVER" : "UNDER";
      return `<tr><td class="l">${esc(p.name)}</td><td>${esc(spec.label)}</td><td>${num(m)}</td><td><input class="ovr ln" data-i="${i}" data-f="line" value="${esc(l.line)}"></td>
        <td><input class="ovr ln" data-i="${i}" data-f="over" value="${esc(l.over)}"></td><td><input class="ovr ln" data-i="${i}" data-f="under" value="${esc(l.under)}"></td>
        <td>${spec.law === "poisson" ? "Poisson" : num(FB.sigmaFor(spec, m), 1)}</td><td>${num(sd.o * 100)}%</td><td>${book == null ? "" : num(book * 100) + "%"}</td>
        <td class="${edge > 0 ? "good" : "bad"}">${edge == null ? "" : num(edge)}</td><td><b>${pick}</b>${pick ? warn(edge) : ""}</td><td><button data-del="${i}">×</button></td></tr>`;
    }).join("");
    const opts = D.projections.filter(p => !isOut(p.status)).sort((a, b) => a.name.localeCompare(b.name)).map(p => `<option value="${esc(p.id)}">${esc(p.name)} (${esc(p.team)} ${esc(p.pos)})</option>`).join("");
    return `<h2>Lines</h2>${live}<h3>Your own lines</h3><p class="sub">Type a posted line and two prices and everything recalculates (this works without any API key). The spread is fitted per market on 2024-25 as <code>a + b × projection</code>; across ~130,000 simulated lines the probabilities missed by 1.6 points on average, near-exact through the middle and a little under-confident in the tails, so treat a 90% as directional. Book P(over) has the vig removed. Pick only appears past the edge threshold (Config).</p>
      <div class="bar"><select id="lp">${opts}</select><select id="ls">${Object.entries(D.meta.markets).map(([k, v]) => `<option value="${k}">${esc(v.label)}</option>`).join("")}</select>
        <input id="ll" size="6" placeholder="line"><input id="lo" size="6" placeholder="over odds" value="-110"><input id="lu" size="6" placeholder="under odds" value="-110"><button id="ladd">Add</button></div>
      <div class="tw"><table><thead><tr><th class="l">Player</th><th>Market</th><th>Proj</th><th>Line</th><th>Over</th><th>Under</th><th>SD</th><th>P(over)</th><th>Book</th><th>Edge pp</th><th>Pick</th><th></th></tr></thead><tbody>${own}</tbody></table></div>`;
  },


  Results() {
    const I = D.rIdx;
    if (!I || !I.weeks.length) return `<h2>Results</h2><div class="doc"><p>No graded weeks yet. Each week's projections are frozen before kickoff, the last pregame consensus and PrizePicks lines are saved at every odds pull, and once the box scores are in, every player's projection is shown here next to what happened. The first graded week appears the morning after the first week that was logged.</p></div>`;
    const key = w => `${w.season}-${w.week}`;
    if (!I.weeks.some(w => key(w) === F.rweek)) F.rweek = key(I.weeks[I.weeks.length - 1]);
    const pc = (h, n) => n ? `${(h / n * 100).toFixed(1)}% <span class="mut">(${h}/${n})</span>` : "—";
    const sumCols = [{k: "week", h: "Week", f: r => `<a href="#Results" data-wk="${key(r)}">${r.week}</a>`}, {k: "n", h: "Players"}, {k: "mae", h: "Pts MAE", f: r => `<b>${num(r.mae, 2)}</b>`},
      {k: "base", h: "Season avg", f: r => num(r.base, 2)}, {k: "last3", h: "Last-3", f: r => num(r.last3, 2)},
      {k: "cons", h: "Model side vs consensus", t: "How often the side the model leans (over if projection > line) won, over every line", v: r => r.cons[0] ? r.cons[1] / r.cons[0] : null, f: r => pc(r.cons[1], r.cons[0])},
      {k: "cp", h: "Consensus picks", t: `Lines where the model's probability differs from the book's by ${I.edge_pp}+ points`, v: r => r.cons_pick[0] ? r.cons_pick[1] / r.cons_pick[0] : null, f: r => pc(r.cons_pick[1], r.cons_pick[0])},
      {k: "pp", h: "PrizePicks side", v: r => r.pp[0] ? r.pp[1] / r.pp[0] : null, f: r => pc(r.pp[1], r.pp[0])},
      {k: "ppp", h: "PrizePicks picks", t: `Past the ${num(I.pp_breakeven, 1)}% per-leg break-even`, v: r => r.pp_pick[0] ? r.pp_pick[1] / r.pp_pick[0] : null, f: r => pc(r.pp_pick[1], r.pp_pick[0])}];
    const rate = a => a[0] ? (a[1] / a[0] * 100).toFixed(1) + "%" : "—";
    const tot = (a) => a.reduce((x, y) => [x[0] + y[0], x[1] + y[1]], [0, 0]);
    const all = {cons: tot(I.weeks.map(w => w.cons)), cp: tot(I.weeks.map(w => w.cons_pick)), pp: tot(I.weeks.map(w => w.pp)), ppp: tot(I.weeks.map(w => w.pp_pick))};
    const head = `<h2>Results</h2><p class="sub">What the model said before kickoff vs what happened. Projections are frozen before kickoff; lines are the last pregame consensus (and PrizePicks) pull. One week is a few hundred coin flips, so judge hit rates over many weeks: against a −110 market a bettor needs about 52.4% to break even, and PrizePicks needs about ${num(I.pp_breakeven, 1)}% per leg.</p>
      <div class="cards"><div class="card"><b>${rate(all.cons)}</b><span>model side vs consensus, all weeks (${all.cons[0]} lines)</span></div>
      <div class="card"><b>${rate(all.cp)}</b><span>consensus picks (${all.cp[0]})</span></div><div class="card"><b>${rate(all.ppp)}</b><span>PrizePicks picks (${all.ppp[0]})</span></div></div>
      ${table(sumCols, I.weeks, {id: "resw", sort: {key: "week", asc: true}})}`;
    const W = RES[F.rweek];
    if (!W) {
      if (!RES_PENDING[F.rweek]) { RES_PENDING[F.rweek] = 1; fetch(`data/results/${F.rweek}.json`, {cache: "no-cache"}).then(r => r.json()).then(j => { RES[F.rweek] = j; if (page === "Results") render(); }).catch(() => { RES[F.rweek] = {players: []}; if (page === "Results") render(); }); }
      return head + `<p>Loading week ${esc(F.rweek)}…</p>`;
    }
    const mk = F.rmkt, spec = mk === "pts" ? null : D.meta.markets[mk];
    const label = mk === "pts" ? "Points" : spec.label;
    const mkts = [["pts", "Points (full PPR)"], ...Object.entries(D.meta.markets).map(([k, v]) => [k, v.label])];
    const hitCell = (g) => g == null ? `<span class="mut">push</span>` : g ? `<span class="good">✓</span>` : `<span class="bad">✗</span>`;
    let rows = W.players.filter(passes).map(p => ({...p, e: p.m[mk]}));
    if (F.rlines) rows = rows.filter(r => r.e.line != null || r.e.pp != null);
    if (F.rpicks) rows = rows.filter(r => r.e.pick || r.e.pp_pick);
    const cols = [{k: "name", h: "Player", l: 1}, {k: "pos", h: "Pos", l: 1}, {k: "team", h: "Team", l: 1}, {k: "opp", h: "Opp", l: 1},
      {k: "p", h: "Projected", f: r => num(r.e.p, mk === "sacks" ? 2 : 1), v: r => r.e.p}, {k: "a", h: "Actual", f: r => `<b>${num(r.e.a, mk === "sacks" || mk === "rec" || mk === "comp" ? 0 : 1)}</b>`, v: r => r.e.a},
      {k: "d", h: "Miss", t: "Actual − projected", v: r => r.e.a - r.e.p, f: r => signed(r.e.a - r.e.p)},
      {k: "bs", h: "Season avg", t: "The baseline the model has to beat", f: r => num(r.e.bs, 1), v: r => r.e.bs},
      ...(mk === "pts" ? [["car", "Car"], ["tgt", "Tgt"], ["att", "Att"]].map(([v, h]) => ({k: "v" + v, h: h + " (proj → act)", v: r => r.vol[v][1] - r.vol[v][0], f: r => `${num(r.vol[v][0])} → ${num(r.vol[v][1], 0)}`})) : [
        {k: "line", h: "Cons line", v: r => r.e.line, f: r => r.e.line ?? ""}, {k: "side", h: "Model side", l: 1, f: r => r.e.side ? (r.e.side === "O" ? "Over" : "Under") : ""},
        {k: "hit", h: "Result", l: 1, f: r => r.e.side ? hitCell(r.e.hit) : ""}, {k: "pick", h: "Pick", l: 1, f: r => r.e.pick ? `<b>${r.e.pick === "O" ? "OVER" : "UNDER"}</b> ${hitCell(r.e.pick_hit)}` : ""},
        {k: "pp", h: "PrizePicks", v: r => r.e.pp, f: r => r.e.pp ?? ""}, {k: "pph", h: "PP result", l: 1, f: r => r.e.pp != null ? `${r.e.pp_side === "O" ? "O" : "U"} ${hitCell(r.e.pp_hit)}${r.e.pp_pick ? " <b>pick</b>" : ""}` : ""},
        {k: "ud", h: "UD/Pick6", f: r => r.e.ud ?? ""}])];
    const m = I.weeks.find(w => key(w) === F.rweek), mm = m && m.mkts[mk];
    const sub = mm ? `<p class="sub">${esc(label)}: model side ${pc(mm.cons[1], mm.cons[0])} · consensus picks ${pc(mm.cons_pick[1], mm.cons_pick[0])} · PrizePicks ${pc(mm.pp[1], mm.pp[0])} · PrizePicks picks ${pc(mm.pp_pick[1], mm.pp_pick[0])}.</p>` : "";
    return `${head}<h3>Week detail</h3><div class="bar"><label>Week <select id="rweek">${I.weeks.map(w => `<option value="${key(w)}" ${key(w) === F.rweek ? "selected" : ""}>${w.season} wk ${w.week}</option>`).join("")}</select></label>
      <label>Market <select id="rmkt">${mkts.map(([k, v]) => `<option value="${k}" ${k === mk ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
      <input id="q" placeholder="Search player / team" value="${esc(F.q)}"><label>Pos <select id="pos">${["", ...POS].map(p => `<option ${F.pos === p ? "selected" : ""} value="${p}">${p || "All"}</option>`).join("")}</select></label>
      ${mk === "pts" ? "" : `<label><input type="checkbox" id="rlines" ${F.rlines ? "checked" : ""}> has a line</label><label><input type="checkbox" id="rpicks" ${F.rpicks ? "checked" : ""}> has a pick</label>`}
      <span class="mut">${rows.length} players${W.dnp ? ` · ${W.dnp} did not play (not scored)` : ""} · click a header to sort</span></div>${sub}
      ${table(cols, rows, {id: "resday" + mk, sort: {key: "d"}})}`;
  },

  Scorecard() {
    const s = D.scorecard;
    const cards = `<div class="cards"><div class="card"><b>${s.scored}</b><span>player-weeks scored</span></div><div class="card"><b>${s.waiting}</b><span>logged, games not in yet</span></div>
      <div class="card"><b>${s.logged}</b><span>rows in the log</span></div><div class="card"><b>${s.late}</b><span>logged after kickoff (never scored)</span></div>
      <div class="card"><b>${s.other_models}</b><span>from earlier model settings (not counted)</span></div></div>`;
    if (!s.markets.length) return `<h2>Scorecard</h2><p class="sub">Projections are written to the log <b>before</b> each week's games and never rewritten, then scored against two baselines: the player's season average and his last three games, as of that week.</p>${cards}
      <p class="banner">Nothing scored yet under model <code>${esc(s.stamp)}</code>. The first scores appear once a logged week's games are final (the nightly refresh picks them up).</p>`;
    const mc = [{k: "label", h: "Market", l: 1}, {k: "n", h: "n"}, {k: "mae", h: "Model MAE", f: r => `<b>${num(r.mae, 2)}</b>`}, {k: "base", h: "Season-avg MAE", f: r => num(r.base, 2)},
      {k: "last3", h: "Last-3 MAE", f: r => num(r.last3, 2)}, {k: "vs", h: "vs season", t: "Negative = the model beat the baseline", f: r => vsBase(r.vs)},
      {k: "vs3", h: "vs last-3", f: r => vsBase(r.vs3)}, {k: "bias", h: "Bias %", f: r => plainSigned(r.bias)},
      {k: "over", h: "Over %", t: "How often the actual landed above the projection. 50 is the target: the projection is a median", f: r => r.over == null ? "" : `${num(r.over)} ± ${num(r.band)}`},
      {k: "read", h: "Read", l: 1}];
    const pc = [{k: "pos", h: "Pos", l: 1}, {k: "n", h: "n"}, {k: "mae", h: "Pts MAE", f: r => num(r.mae, 2)}, {k: "over", h: "Over %", f: r => `${num(r.over)} ± ${num(r.band)}`}, {k: "bias", h: "Bias %", f: r => plainSigned(r.bias)}, {k: "read", h: "Read", l: 1}];
    const wc = [{k: "week", h: "Week"}, {k: "n", h: "n"}, {k: "model", h: "Model", f: r => `<b>${num(r.model, 2)}</b>`}, {k: "season", h: "Season avg", f: r => num(r.season, 2)}, {k: "last3", h: "Last-3", f: r => num(r.last3, 2)}];
    return `<h2>Scorecard</h2><p class="sub">Live record under model <code>${esc(s.stamp)}</code> (full-PPR points). Change any knob and the stamp changes, starting a fresh record instead of blending into the old one.</p>${cards}
      <h3>By market</h3>${table(mc, s.markets, {id: "scm"})}<h3>By position (points)</h3>${table(pc, s.pos, {id: "scp"})}<h3>By week (points MAE)</h3>${table(wc, s.weeks, {id: "scw"})}
      <div class="doc"><p class="mut">MAE is the raw average miss, so it is comparable with the baselines in the same row but not between markets. A miss can be spotted from about 100 rows, but <i>no miss detected</i> is not <i>calibrated</i>: the word is held back until 400. Players who did not play are not scored.</p></div>`;
  },

  Backtest() {
    const ys = D.meta.backtests || [];
    if (!ys.length) return `<h2>Backtest</h2><p class="banner">No backtest has been run yet: <code>python -m pipeline.fetch --season 2025 && python -m pipeline.backtest --season 2025 --write</code></p>`;
    F.year = ys.includes(F.year) ? F.year : ys[ys.length - 1];
    const b = D.backtest[F.year];
    if (!b) return `<h2>Backtest</h2><p>Loading…</p>`;
    const c = [{k: "label", h: "Stat", l: 1}, {k: "n", h: "n"}, {k: "mae", h: "Model MAE", f: r => `<b>${num(r.mae, 3)}</b>`}, {k: "base", h: "Season-avg MAE", f: r => num(r.base, 3)}, {k: "last3", h: "Last-3 MAE", f: r => num(r.last3, 3)},
      {k: "rmse", h: "RMSE", f: r => num(r.rmse, 3)}, {k: "vs", h: "vs season", f: r => vsBase(r.vs)}, {k: "vs3", h: "vs last-3", f: r => vsBase(r.vs3)},
      {k: "bias", h: "Bias %", f: r => plainSigned(r.bias)}, {k: "over", h: "Over %", f: r => num(r.over)}];
    const pc = [{k: "pos", h: "Pos", l: 1}, {k: "n", h: "n"}, {k: "over", h: "Over %", f: r => num(r.over)}, {k: "band", h: "95% band ±", f: r => num(r.band)}, {k: "verdict", h: "Verdict", l: 1}, {k: "bias", h: "Bias %", f: r => plainSigned(r.bias)}];
    const wc = [{k: "week", h: "Week"}, {k: "n", h: "n"}, {k: "model", h: "Model", f: r => `<b>${num(r.model, 2)}</b>`}, {k: "season", h: "Season avg", f: r => num(r.season, 2)}, {k: "last3", h: "Last-3", f: r => num(r.last3, 2)}];
    return `<h2>Backtest</h2><p class="sub">Walk-forward over the ${esc(b.season)} season, weeks ${b.weeks[0]}–${b.weeks[1]}: each week is projected using only the weeks before it, then scored against what happened. A negative percentage against a baseline means the model beat it. Rows are limited to players projected for at least ${b.min_pts} points.</p>
      <div class="bar"><label>Season <select id="year">${ys.map(y => `<option ${y === F.year ? "selected" : ""}>${y}</option>`).join("")}</select></label></div>
      ${table(c, b.table, {id: "bt"})}<h3>Calibration by position — projected points against the median</h3>${table(pc, b.pos, {id: "btp"})}<h3>Points MAE by week</h3>${table(wc, b.per_week, {id: "btw"})}
      <div class="doc"><p class="mut"><b>Bias %</b> and <b>Over %</b> ask different questions. Bias compares total projected to total actual (the MEAN outcome); Over % is how often the actual landed above the projection (the MEDIAN). Scoring is right-skewed - the median week sits about 14% below the mean - so a Bias near −13% beside an Over % near 50 is not a fault: that is what a correctly calibrated median projection looks like. Weather in a backtest is the wind that actually blew, so its measured gain is a ceiling on what a forecast delivers.</p></div>`;
  },

  Config() {
    const sc = CFG.scoring;
    return `<h2>Config</h2><p class="sub">Saved on this device. Scoring only changes how stat lines are valued; the stat lines themselves come from the model.</p>
      <div class="bar"><label>Scoring preset <select id="preset">${[...Object.keys(FB.SCORING), "Custom"].map(p => `<option ${CFG.preset === p ? "selected" : ""}>${p}</option>`).join("")}</select></label>
        <label>Show <select id="mean"><option value="0" ${CFG.mean ? "" : "selected"}>Median (compare to lines)</option><option value="1" ${CFG.mean ? "selected" : ""}>Mean (season-long value)</option></select></label></div>
      <div class="bar">${Object.entries(SCORE_LABEL).map(([k, l]) => `<label>${l} <input data-sc="${k}" type="number" step="0.01" style="width:70px" value="${sc[k]}"></label>`).join("")}</div>
      <div class="bar"><label>Edge threshold (pp) <input id="edge" type="number" step="0.5" style="width:70px" value="${CFG.edgeMin}"></label>
        <label>PrizePicks per-leg break-even % <input id="ppbe" type="number" step="0.1" style="width:70px" value="${CFG.ppBE}"></label></div>
      <p class="mut">The edge threshold is the smallest gap between the model's probability and the book's that the Lines tab will call a pick: below about 4 points you are inside the model's own calibration error. A k-pick PrizePicks entry paying M× needs M^(−1/k) per leg (2 picks at 3× = 57.7%).</p>
      <p class="mut">Median vs mean: Proj Pts lands on the <b>median</b> outcome (the actual beat it 52.5% of the time across 2024-25), which is what you want against a posted line. Scoring is right-skewed, so the mean is about ${num((D.meta.mean_factor - 1) * 100, 0)}% higher: for season-long or DFS expected value use <b>Mean</b>, which multiplies by MEAN_FACTOR = ${D.meta.mean_factor}. Neither is a correction of the other.</p>
      <p><button id="clr">Clear all volume overrides</button></p>`;
  },

  Methodology() {
    return `<div class="doc"><h2>Methodology</h2>
<h3>The shape of a projection</h3><p>For every player with a game this week the model projects three <b>volumes</b> (carries, targets, pass attempts), multiplies each by the player's own regressed <b>rate</b> (yards per carry, catch rate, yards per reception, yards per attempt, completion rate, touchdown, interception, sack and fumble rates), and by the opposing defence's <b>matchup multiplier</b>. Points are then those stat lines under your scoring preset.</p>
<h3>Volumes</h3><p>A blend of the player's season average and his recent games (recency weight 0.20 for carries and targets, 0.80 for pass attempts, which track the current starter). Each team's players are then rescaled so they add up to a realistic team game, by at most ±20%. Pass attempts are shared by how often each quarterback has <i>actually been the one throwing</i> over the team's last six games, so a backup who threw once stops absorbing a fifth of the offence.</p>
<h3>Rates</h3><p>Every rate is shrunk toward the league (or toward the player's position group: a back catches ~80% of his targets for ~7 yards, a receiver ~64% for ~13) by a prior worth a fixed number of attempts. Touchdown rates shrink toward the player's <b>own offence, excluding him</b>, because red-zone trips are a property of an offence while yards per touch are a property of a player. Sacks and fumbles get very heavy priors because they are rare.</p>
<h3>Opponent adjustments</h3><p>Each defence is measured on yards per carry, catch rate, yards per reception, yards per target and completion rate allowed, regressed by how many plays it has faced and capped at ±15%. Then comes the step that matters: only a measured <b>share</b> of each matchup is applied (rushing 0.34, yards per reception 0.15, catch rate 0.39, yards per attempt 0.47, completion rate 0.66), found by regressing what players' rates actually did on the multiplier applied to them. Touchdown matchups are derived from the yardage matchup (60-78% of it) rather than from touchdowns allowed, which barely repeat from one half-season to the next. Tight-end splits are off for the same reason.</p>
<h3>Quarterback calibration</h3><p>Passing yards and completions came out too spread out (regressing actual on projected gave a slope of 0.68 in both seasons), so they are pulled toward the slate mean, phased in with projected attempts so receivers are untouched.</p>
<h3>Weather</h3><p>Wind only, as a hinge: nothing below 13 mph, then −2.2% of passing and receiving yardage per mph, floored at 0.70, with receptions taking half the move. Temperature and rain were tested and dropped.</p>
<h3>Median vs mean</h3><p>The projection is a median; scoring is right-skewed, so the mean is about 17% higher (MEAN_FACTOR).</p>
<h3>Lines</h3><p>Posted player props (pass, rush and receiving yards, receptions, completions, sacks) come from The Odds API. The <b>consensus</b> is the median sportsbook line with each book's vig removed (the two prices are converted to probabilities and rescaled to sum to 100%, or every market would look about four points worse than it is), averaged over the books posting that exact line. PrizePicks, Underdog and Pick6 keep only their <i>line</i>: their prices are nominal. The model's probability comes from the projection plus a spread fitted per market on 2024-25 as <code>a + b × projection</code> (passing and completions carry a negative slope, which is real: a quarterback projected for 150 yards is usually in an unsettled situation). Sacks is a count, so it uses a Poisson law, which beat a normal there. Across roughly 130,000 simulated lines the probabilities missed by 1.6 percentage points on average: near-exact through the middle and a little under-confident in the tails, so read a 90% as directional. An edge above 15 points gets a warning marker: it usually means the model has a player's role wrong, not that there is a bargain. Names are not unique across the league (there are two Josh Allens), so a price only attaches to a player on one of the two teams in the game, and a book posting two different lines for one name is dropped rather than guessed at.</p>
<h3>Results</h3><p>For each graded week, every player's frozen projection next to his box score, with the last pregame consensus and PrizePicks lines. The model "takes" the over if its projection is above a line and the under if below; a result exactly on the line is a push and is left out. A <b>pick</b> is a line where the model's probability differs from the book's by at least 4 points (PrizePicks: from the per-leg break-even). Lines are snapshotted at each odds pull until kickoff and frozen after; a game with no pull before kickoff has no line to grade against.</p>
<h3>Scorecard</h3><p>Every week's projections are written to a log <b>before</b> kickoff and never rewritten, with two naive baselines frozen alongside (season average and last three games). A row logged after its team's kickoff is never scored. Each row carries a settings stamp, so changing any knob starts a fresh record.</p>
<h3>Backtest</h3><p>The Backtest tab replays past seasons week by week with the same code the site runs. Treat the weather gain there as a ceiling: it uses observed wind, not a forecast.</p>
<h3>Not modelled</h3><p>Injuries beyond the listed status (a player listed Out is still projected; a teammate's absence is only reflected once the participation window sees it), game script and spread, kickers, defences, and in-browser redistribution of volume when you override a teammate.</p>
<h3>Data</h3><p>Box scores, schedule, snap counts and injuries from <a href="https://github.com/nflverse/nflverse-data/releases">nflverse</a> (free, no key); kickoff weather from Open-Meteo. The game lines on the Game Board are nflverse's and are context only - they do not feed the projections.</p></div>`;
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
  if (next !== page) { F.q = ""; F.pos = ""; F.team = ""; }          // a stale search should not silently filter the next tab
  page = next;
  nav(); render();
}
window.addEventListener("hashchange", route);

async function loadBacktests() {
  D.backtest = {};
  await Promise.all((D.meta.backtests || []).map(async y => { try { const r = await fetch(`data/backtest_${y}.json`, {cache: "no-cache"}); if (r.ok) D.backtest[y] = await r.json(); } catch (e) {} }));
}

document.addEventListener("change", e => {
  const t = e.target;
  if (t.classList.contains("ovr") && t.dataset.id) {
    const v = t.value.trim(), o = OVR[t.dataset.id] ||= {};
    if (v === "" || Number.isNaN(+v)) delete o[t.dataset.key]; else o[t.dataset.key] = Math.max(0, +v);
    if (!Object.keys(o).length) delete OVR[t.dataset.id];
    store.set("ovr", OVR); render();
  }
  else if (t.id === "pos") { F.pos = t.value; render(true); }
  else if (t.id === "team") { F.team = t.value; render(true); }
  else if (t.id === "game") { F.game = t.value; render(); }
  else if (t.id === "effview") { F.effView = t.value; render(); }
  else if (t.id === "year") { F.year = t.value; render(); }
  else if (t.id === "ming") { F.minG = +t.value || 0; render(true); }
  else if (t.id === "hidestarted") { F.hideStarted = t.checked; render(true); }
  else if (t.id === "detail") { CFG.detail = t.checked; store.set("cfg", CFG); render(true); }
  else if (t.id === "preset") { CFG.preset = t.value; if (FB.SCORING[t.value]) CFG.scoring = {...FB.SCORING[t.value]}; store.set("cfg", CFG); render(); }
  else if (t.dataset.sc) { CFG.scoring[t.dataset.sc] = +t.value || 0; CFG.preset = "Custom"; store.set("cfg", CFG); render(); }
  else if (t.id === "mean") { CFG.mean = t.value === "1"; store.set("cfg", CFG); render(); }
  else if (t.id === "rweek") { F.rweek = t.value; render(); }
  else if (t.id === "rmkt") { F.rmkt = t.value; render(); }
  else if (t.id === "rlines") { F.rlines = t.checked; render(); }
  else if (t.id === "rpicks") { F.rpicks = t.checked; render(); }
  else if (t.id === "lstat") { F.lstat = t.value; render(); }
  else if (t.id === "lgame") { F.lgame = t.value; render(); }
  else if (t.id === "lpicks") { F.lpicks = t.checked; render(); }
  else if (t.id === "edge") { CFG.edgeMin = +t.value || 0; store.set("cfg", CFG); }
  else if (t.id === "ppbe") { CFG.ppBE = +t.value || 57.7; store.set("cfg", CFG); render(); }
  else if (t.classList.contains("ln")) { LINES[+t.dataset.i][t.dataset.f] = t.value; store.set("lines", LINES); render(); }
});
document.addEventListener("click", e => {
  const t = e.target;
  if (t.id === "clr") { OVR = {}; store.set("ovr", OVR); render(); }
  if (t.dataset.wk) { e.preventDefault(); F.rweek = t.dataset.wk; render(); }
  if (t.id === "ladd") {
    const line = document.getElementById("ll").value; if (line === "" || Number.isNaN(+line)) return;
    LINES.push({id: document.getElementById("lp").value, stat: document.getElementById("ls").value, line, over: document.getElementById("lo").value, under: document.getElementById("lu").value});
    store.set("lines", LINES); render();
  }
  if (t.dataset.del != null) { LINES.splice(+t.dataset.del, 1); store.set("lines", LINES); render(); }
});

async function boot() {
  CFG = {...CFG, ...store.get("cfg", {})}; OVR = store.get("ovr", {}); LINES = store.get("lines", []);
  if (!CFG.scoring || Object.keys(CFG.scoring).some(k => !(k in SCORE_LABEL))) CFG = {...CFG, preset: "Full PPR", scoring: {...FB.SCORING["Full PPR"]}};
  const names = ["projections", "games", "matchups", "efficiency", "usage", "trends", "weather", "coverage", "scorecard", "meta", "lines"];
  await Promise.all(names.map(async n => { try { const r = await fetch(`data/${n}.json`, {cache: "no-cache"}); if (r.ok) D[n] = await r.json(); } catch (e) {} }));
  if (!D.projections || !D.meta) { view().innerHTML = "<p>No data found in <code>data/</code>. Run <code>python -m pipeline.build</code>.</p>"; return; }
  await loadBacktests();
  try { const r = await fetch("data/results/index.json", {cache: "no-cache"}); if (r.ok) D.rIdx = await r.json(); } catch (e) {}
  const gen = new Date(D.meta.generated);
  document.getElementById("asof").textContent = `Week ${D.meta.week} · data through week ${D.meta.asof_week} · built ${gen.toLocaleString(undefined, {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"})}`;
  const msgs = [];
  if (D.meta.history_gaps?.length) msgs.push(`<b>History incomplete:</b> box scores are still missing for ${D.meta.history_gaps.map(esc).join(", ")}${D.meta.history_gaps.length >= 6 ? "…" : ""}. These projections are provisional and are <b>not</b> being logged to the Scorecard until the data catches up.`);
  if (D.games.some(g => started(g.ko))) msgs.push(`Some of this week's games have already started: their rows are greyed out on Projections (a projection made after kickoff is not logged or scored).`);
  if (D.weather.some(w => w.src === "unknown")) msgs.push(`No weather reading yet for ${D.weather.filter(w => w.src === "unknown").length} outdoor game(s): they carry no wind adjustment.`);
  if (msgs.length) { const b = document.getElementById("banner"); b.hidden = false; b.innerHTML = msgs.join("<br>"); }
  route();
}
boot();

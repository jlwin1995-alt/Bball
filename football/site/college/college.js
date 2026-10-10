"use strict";
// College football. Same engine and look as the NFL page, with what CollegeFootballData actually reports: no targets (receptions are projected
// directly), no sacks, no weather, no injury report, no 2-point conversions and no betting lines.
const TABS = ["Projections", "Game Board", "Leaders", "Matchups", "Scorecard", "Backtest", "Config", "Methodology"];
const D = {};
const store = makeStore("gmc_");
let CFG = {preset: "Full PPR", scoring: {...FB.SCORING["Full PPR"]}, detail: false};
let OVR = {};
const POS = ["QB", "RB", "WR", "TE"];
const view = () => document.getElementById("view");
const SCORE_LABEL = {passYd: "Pass yd", passTd: "Pass TD", intr: "INT", rushYd: "Rush yd", rushTd: "Rush TD", recYd: "Rec yd", recTd: "Rec TD", rec: "Reception", fum: "Fumble lost"};
const koDate = iso => iso ? new Date(iso) : null;
const started = iso => { const d = koDate(iso); return d ? d.getTime() <= Date.now() : false; };
const koLabel = iso => { const d = koDate(iso); return d ? d.toLocaleString(undefined, {weekday: "short", hour: "numeric", minute: "2-digit"}) : ""; };
const calcFor = p => FB.calcCfb(p, OVR[p.id], CFG.scoring);
const proj = () => D.projections.map(p => ({...p, c: calcFor(p)}));
const siteTag = r => r.site === "N" ? "vs " + esc(r.opp) + " (neutral)" : (r.site === "vs" ? "vs " : "@ ") + esc(r.opp);
const nameCols = [{k: "name", h: "Player", l: 1}, {k: "pos", h: "Pos", l: 1}, {k: "team", h: "Team", l: 1}];
const F = {q: "", pos: "", team: "", conf: "", hideStarted: false, game: "", year: ""};
const ovrCell = (r, key, shown) => `<input class="ovr" data-id="${esc(r.id)}" data-key="${key}" value="${OVR[r.id]?.[key] ?? ""}" placeholder="${num(shown)}">`;
function passes(r) {
  if (F.pos && r.pos !== F.pos) return false;
  if (F.conf && r.conf !== F.conf) return false;
  if (F.team && r.team !== F.team && r.opp !== F.team) return false;
  const q = F.q.trim().toLowerCase();
  return !q || (r.name + " " + r.team).toLowerCase().includes(q);
}
function filters(extra = "") {
  const teams = [...new Set(D.projections.map(p => p.team))].sort(), confs = [...new Set(D.projections.map(p => p.conf).filter(Boolean))].sort();
  return `<div class="bar"><input id="q" placeholder="Search player / team" value="${esc(F.q)}">
    <label>Pos <select id="pos">${["", ...POS].map(p => `<option ${F.pos === p ? "selected" : ""} value="${p}">${p || "All"}</option>`).join("")}</select></label>
    <label>Conf <select id="conf">${["", ...confs].map(c => `<option ${F.conf === c ? "selected" : ""} value="${esc(c)}">${esc(c) || "All"}</option>`).join("")}</select></label>
    <label>Team <select id="team">${["", ...teams].map(t => `<option ${F.team === t ? "selected" : ""} value="${esc(t)}">${esc(t) || "All"}</option>`).join("")}</select></label>${extra}</div>`;
}
document.addEventListener("input", e => { if (e.target.id === "q") { F.q = e.target.value; render(true, "q"); } });

const pages = {
  Projections() {
    let rows = proj().filter(passes);
    if (F.hideStarted) rows = rows.filter(r => !started(r.ko));
    const det = CFG.detail;
    const cols = [...nameCols, {k: "conf", h: "Conf", l: 1}, {k: "opp", h: "Opp", l: 1, f: siteTag, v: r => r.opp},
      ...(det ? [{k: "g", h: "G", t: "Games in this season's sample"}] : []),
      {k: "caro", h: "Car OVR", t: "Type carries to override. Teammates are NOT re-scaled. Saved on this device.", v: r => OVR[r.id]?.car, f: r => ovrCell(r, "car", r.car)},
      {k: "ccar", h: "Car", v: r => r.c.car, f: r => num(r.c.car)},
      ...(det ? [{k: "ccsh", h: "Car %", v: r => r.c.carSh, f: r => num(r.c.carSh)}, {k: "ypc", h: "Y/C", f: r => num(r.ypc, 2)}, {k: "arush", h: "Rush Adj", v: r => r.a_rush, f: r => adj(r.a_rush)}] : []),
      {k: "cry", h: "Rush Yds", v: r => r.c.rushY, f: r => num(r.c.rushY)},
      {k: "reco", h: "Rec OVR", t: "Type receptions to override", v: r => OVR[r.id]?.rec, f: r => ovrCell(r, "rec", r.rec)},
      {k: "crec", h: "Rec", v: r => r.c.rec, f: r => num(r.c.rec)},
      ...(det ? [{k: "crsh", h: "Rec %", t: "Share of the team's projected RECEPTIONS (college has no target data)", v: r => r.c.recSh, f: r => num(r.c.recSh)},
        {k: "ypr", h: "Y/Rec", f: r => num(r.ypr, 1)}, {k: "arec", h: "Rec Adj", v: r => r.a_rec, f: r => adj(r.a_rec)}] : []),
      {k: "crecy", h: "Rec Yds", v: r => r.c.recY, f: r => num(r.c.recY)},
      {k: "atto", h: "Att OVR", t: "Type pass attempts to override", v: r => OVR[r.id]?.att, f: r => ovrCell(r, "att", r.att)},
      {k: "catt", h: "Att", v: r => r.c.att, f: r => num(r.c.att)}, {k: "ccomp", h: "Comp", v: r => r.c.comp, f: r => r.c.att > 0 ? num(r.c.comp) : ""},
      ...(det ? [{k: "ypa", h: "Y/A", f: r => r.c.att > 0 ? num(r.ypa, 2) : ""}, {k: "apass", h: "Pass Adj", v: r => r.a_pass, f: r => r.c.att > 0 ? adj(r.a_pass) : ""}] : []),
      {k: "cpy", h: "Pass Yds", v: r => r.c.passY, f: r => r.c.att > 0 ? num(r.c.passY) : ""},
      {k: "crtd", h: "Rush TD", v: r => r.c.rushTD, f: r => num(r.c.rushTD, 2)}, {k: "crectd", h: "Rec TD", v: r => r.c.recTD, f: r => num(r.c.recTD, 2)},
      {k: "cptd", h: "Pass TD", v: r => r.c.passTD, f: r => r.c.att > 0 ? num(r.c.passTD, 2) : ""},
      ...(det ? [{k: "cint", h: "INT", v: r => r.c.int, f: r => r.c.att > 0 ? num(r.c.int, 2) : ""}, {k: "cfum", h: "Fum", v: r => r.c.fum, f: r => num(r.c.fum, 2)}] : []),
      {k: "cpts", h: "Proj Pts", v: r => r.c.pts, f: r => `<b>${num(r.c.pts)}</b>`}];
    return `<h2>College Projections — Week ${D.meta.week}</h2>
      <p class="sub">Median points for every FBS player with an unplayed game this week and at least ${D.meta.min_opps ?? 8} touches or attempts this season. Shaded <b>OVR</b> boxes are yours; everything recalculates instantly (teammates are not re-scaled). Scoring: ${esc(CFG.preset)}. College has no injury report: availability is on you.</p>
      ${filters(`<label><input type="checkbox" id="hidestarted" ${F.hideStarted ? "checked" : ""}> hide games already started</label>
        <label><input type="checkbox" id="detail" ${CFG.detail ? "checked" : ""}> more columns</label><button id="clr">Clear overrides</button>`)}
      ${table(cols, rows, {id: "proj" + (det ? "d" : ""), sort: {key: "cpts"}, rowClass: r => started(r.ko) ? "started" : ""})}`;
  },

  "Game Board"() {
    const games = D.games.filter(g => D.projections.some(p => p.game === g.game));
    if (!games.length) return `<h2>Game Board</h2><p class="sub">No games with projections yet.</p>`;
    if (!F.game || !games.some(g => g.game === F.game)) F.game = (games.find(g => !started(g.ko)) || games[0]).game;
    const g = games.find(x => x.game === F.game), all = proj().filter(p => p.game === g.game);
    const mk = t => {
      const rows = all.filter(p => p.team === t);
      const cols = [{k: "name", h: "Player", l: 1}, {k: "pos", h: "Pos", l: 1}, {k: "ccar", h: "Car", v: r => r.c.car, f: r => num(r.c.car)}, {k: "cry", h: "Rush", v: r => r.c.rushY, f: r => num(r.c.rushY, 0)},
        {k: "crec", h: "Rec", v: r => r.c.rec, f: r => num(r.c.rec)}, {k: "crecy", h: "Rec Yds", v: r => r.c.recY, f: r => num(r.c.recY, 0)},
        {k: "catt", h: "Att", v: r => r.c.att, f: r => r.c.att > 0 ? num(r.c.att) : ""}, {k: "cpy", h: "Pass Yds", v: r => r.c.passY, f: r => r.c.att > 0 ? num(r.c.passY, 0) : ""},
        {k: "ctd", h: "TD", v: r => r.c.rushTD + r.c.recTD + r.c.passTD, f: r => num(r.c.rushTD + r.c.recTD + r.c.passTD, 2)}, {k: "cpts", h: "Pts", v: r => r.c.pts, f: r => `<b>${num(r.c.pts)}</b>`}];
      return `<div><h3>${esc(t)} <span class="mut">· ${num(rows.reduce((a, r) => a + r.c.pts, 0))} projected pts across ${rows.length} players</span></h3>${table(cols, rows, {id: "gb" + t, sort: {key: "cpts"}})}</div>`;
    };
    return `<h2>Game Board</h2><p class="sub">Pick a game; both teams ranked by projected points.</p>
      <div class="bar"><label>Game <select id="game">${games.map(x => `<option value="${esc(x.game)}" ${x.game === g.game ? "selected" : ""}>${esc(x.game)} · ${esc(koLabel(x.ko))}${started(x.ko) ? " (started)" : ""}</option>`).join("")}</select></label></div>
      <div class="gamehead"><div><span>Kickoff</span><b>${esc(koLabel(g.ko))}</b></div><div><span>Conferences</span><b>${esc(g.conf[0] || "-")} / ${esc(g.conf[1] || "-")}</b></div>${g.neutral ? `<div><span>Site</span><b>Neutral</b></div>` : ""}</div>
      <div class="two">${mk(g.away)}${mk(g.home)}</div>`;
  },

  Leaders() {
    const rows = proj();
    const CATS = [["Projected points", r => r.c.pts, 1], ["Rushing yards", r => r.c.rushY, 1], ["Receiving yards", r => r.c.recY, 1], ["Passing yards", r => r.c.passY, 1],
      ["Receptions", r => r.c.rec, 1], ["Carries", r => r.c.car, 1], ["Pass attempts", r => r.c.att, 1], ["Completions", r => r.c.comp, 1], ["Total TDs", r => r.c.rushTD + r.c.recTD + r.c.passTD, 2]];
    return `<h2>Projected Leaders — Week ${D.meta.week}</h2><p class="sub">Top 15 by projected output for the week ahead, not season totals.</p>${filters()}
      <div class="lead">${CATS.map(([label, f, dp]) => `<div class="card"><h4>${label}</h4><ol>${rows.filter(passes).map(r => ({r, v: f(r)})).filter(x => x.v > 0).sort((a, b) => b.v - a.v).slice(0, 15)
        .map(x => `<li><b>${esc(x.r.name)}</b> <span>${esc(x.r.team)} · ${num(x.v, dp)}</span></li>`).join("")}</ol></div>`).join("")}</div>`;
  },

  Matchups() {
    const M = D.matchups, a = k => r => adj(r[k]);
    const cols = [{k: "team", h: "Defense", l: 1}, {k: "conf", h: "Conf", l: 1}, {k: "car", h: "Carries faced"}, {k: "ypc", h: "Y/C allowed", f: r => num(r.ypc, 2)}, {k: "rush", h: "Rush Adj", f: a("rush")},
      {k: "rec", h: "Receptions faced"}, {k: "ypr_a", h: "Y/Rec allowed", f: r => num(r.ypr_a, 2)}, {k: "recadj", h: "Y/Rec Adj", f: a("recadj")}, {k: "pass_", h: "Y/Att Adj", t: "Yards per pass attempt allowed", f: a("pass_")},
      {k: "comp", h: "Comp Adj", f: a("comp")}, {k: "faces", h: `Faces in wk ${M.week}`, l: 1}];
    return `<h2>Matchups — Week ${M.week}</h2><p class="sub">Above 0% means the defence has been easier than average to gain on; below, harder. Each is regressed by how many plays it has faced and capped at ±15%. Unlike the NFL page, college defence strengths are applied in full, not damped by a measured share.</p>
      ${table(cols, M.rows, {id: "md", sort: {key: "rush"}})}
      <div class="doc"><p class="mut">League baseline: ${num(M.lg.ypc, 2)} Y/C, ${num(M.lg.ypr, 2)} Y/Rec, ${num(M.lg.ypa, 2)} Y/A. Quarterback rushing baseline ${num(M.lg.qb.ypc, 2)} Y/C against ${num(M.lg.qb.other, 2)} for everyone else: the NCAA charges a sack as a rushing attempt with the yardage lost, so a college QB's rushing line already has his sacks subtracted, and he regresses toward what quarterbacks do.</p></div>`;
  },

  Scorecard() {
    const s = D.scorecard;
    const cards = `<div class="cards"><div class="card"><b>${s.scored}</b><span>player-weeks scored</span></div><div class="card"><b>${s.waiting}</b><span>logged, games not in yet</span></div>
      <div class="card"><b>${s.logged}</b><span>rows in the log</span></div><div class="card"><b>${s.late}</b><span>logged after kickoff (never scored)</span></div></div>`;
    if (!s.markets.length) return `<h2>College Scorecard</h2><p class="sub">Projections are logged before each week's games and never rewritten, then scored against the player's season average and last three games.</p>${cards}<p class="banner">Nothing scored yet under model <code>${esc(s.stamp)}</code>.</p>`;
    const mc = [{k: "label", h: "Market", l: 1}, {k: "n", h: "n"}, {k: "mae", h: "Model MAE", f: r => `<b>${num(r.mae, 2)}</b>`}, {k: "base", h: "Season-avg MAE", f: r => num(r.base, 2)}, {k: "last3", h: "Last-3 MAE", f: r => num(r.last3, 2)},
      {k: "vs", h: "vs season", t: "Negative = the model beat the baseline", f: r => vsBase(r.vs)}, {k: "vs3", h: "vs last-3", f: r => vsBase(r.vs3)}, {k: "bias", h: "Bias %", f: r => plainSigned(r.bias)},
      {k: "over", h: "Over %", f: r => r.over == null ? "" : `${num(r.over)} ± ${num(r.band)}`}, {k: "read", h: "Read", l: 1}];
    const pc = [{k: "pos", h: "Pos", l: 1}, {k: "n", h: "n"}, {k: "mae", h: "Pts MAE", f: r => num(r.mae, 2)}, {k: "over", h: "Over %", f: r => `${num(r.over)} ± ${num(r.band)}`}, {k: "bias", h: "Bias %", f: r => plainSigned(r.bias)}, {k: "read", h: "Read", l: 1}];
    const wc = [{k: "week", h: "Week"}, {k: "n", h: "n"}, {k: "model", h: "Model", f: r => `<b>${num(r.model, 2)}</b>`}, {k: "season", h: "Season avg", f: r => num(r.season, 2)}, {k: "last3", h: "Last-3", f: r => num(r.last3, 2)}];
    return `<h2>College Scorecard</h2><p class="sub">Live record under model <code>${esc(s.stamp)}</code> (full-PPR points).</p>${cards}<h3>By market</h3>${table(mc, s.markets, {id: "scm"})}<h3>By position (points)</h3>${table(pc, s.pos, {id: "scp"})}<h3>By week</h3>${table(wc, s.weeks, {id: "scw"})}
      <div class="doc"><p class="mut">Never pooled with the NFL record: college scatters about 6-10% wider relative to its own mean and players sit much further apart. A miss can be spotted from about 100 rows, but "calibrated" is held back until 400.</p></div>`;
  },

  Backtest() {
    const ys = D.meta.backtests || [];
    if (!ys.length) return `<h2>College Backtest</h2><p class="banner">No backtest has been run yet: <code>python -m pipeline.cfb_build --backtest</code> (needs at least two fetched weeks).</p>`;
    F.year = ys.includes(F.year) ? F.year : ys[ys.length - 1];
    const b = D.backtest[F.year];
    if (!b) return `<h2>College Backtest</h2><p>Loading…</p>`;
    const c = [{k: "label", h: "Stat", l: 1}, {k: "n", h: "n"}, {k: "mae", h: "Model MAE", f: r => `<b>${num(r.mae, 3)}</b>`}, {k: "base", h: "Season-avg MAE", f: r => num(r.base, 3)}, {k: "last3", h: "Last-3 MAE", f: r => num(r.last3, 3)},
      {k: "rmse", h: "RMSE", f: r => num(r.rmse, 3)}, {k: "vs", h: "vs season", f: r => vsBase(r.vs)}, {k: "vs3", h: "vs last-3", f: r => vsBase(r.vs3)}, {k: "bias", h: "Bias %", f: r => plainSigned(r.bias)}, {k: "over", h: "Over %", f: r => num(r.over)}];
    const sp = [{k: "label", h: "Market", l: 1}, {k: "n", h: "n"}, {k: "a", h: "a", f: r => num(r.a, 3)}, {k: "b", h: "b", f: r => num(r.b, 4)}, {k: "fit", h: "Fitted sigma", l: 1, f: r => r.a == null ? "too few" : `≈ ${num(r.a, 2)} + ${num(r.b, 3)} × projection`}];
    return `<h2>College Backtest</h2><p class="sub">Walk-forward over ${esc(b.season)}, weeks ${b.weeks.join(", ") || "none"}: each week is projected from the weeks before it by the same code the site runs. ${b.scored} player-games. A negative percentage against a baseline means the model beat it.</p>
      ${b.thin ? `<p class="banner"><b>Read this before the numbers.</b> Only ${b.weeks.length} week(s) could be scored, so each projection was built from barely any history. With one prior week the season-average and last-3 baselines are the same number (what the player did last week), which is a hard baseline to beat on volume markets. A market losing to it here is a flag to re-check once more weeks exist, not a finding.</p>` : ""}
      <div class="bar"><label>Season <select id="year">${ys.map(y => `<option ${y === F.year ? "selected" : ""}>${y}</option>`).join("")}</select></label></div>
      ${table(c, b.table, {id: "bt"})}<h3>Measured college spread</h3>${table(sp, b.spread.map(s => ({...s, fit: 1})), {id: "bsp"})}
      <div class="doc"><p class="mut">Residual spread per market, fitted as <code>a + b × projection</code>: what a college P(over) should use. College lines are not on the site, so it is shown for reference; a negative slope on a market means the fit is reading noise until several weeks have scored.</p></div>`;
  },

  Config() {
    const sc = CFG.scoring;
    return `<h2>Config</h2><p class="sub">Saved on this device. Scoring only changes how stat lines are valued. College has no 2-point term and no mean/median switch (the median-to-mean factor was measured on the NFL only).</p>
      <div class="bar"><label>Scoring preset <select id="preset">${[...Object.keys(FB.SCORING), "Custom"].map(p => `<option ${CFG.preset === p ? "selected" : ""}>${p}</option>`).join("")}</select></label></div>
      <div class="bar">${Object.entries(SCORE_LABEL).map(([k, l]) => `<label>${l} <input data-sc="${k}" type="number" step="0.01" style="width:70px" value="${sc[k]}"></label>`).join("")}</div>
      <p><button id="clr">Clear all volume overrides</button></p>`;
  },

  Methodology() {
    return `<div class="doc"><h2>College methodology</h2>
<p>The same engine as the NFL page, fed by <a href="https://collegefootballdata.com">CollegeFootballData</a> box scores (one call per played week, FBS only). What is different is what the data allows:</p>
<h3>No targets</h3><p>CFBD reports receptions, not targets, so there is no catch rate. Receptions are projected directly, receiving touchdowns are per reception, and "Rec %" is a share of the team's projected receptions.</p>
<h3>Quarterbacks run differently</h3><p>The NCAA charges a sack as a rushing attempt with the yardage lost, which the NFL does not. Across the 2026 fixture weeks college QBs ran 3.03 yards a carry against 4.73 for everyone else, and 29 of 166 qualifying QBs finished with negative rushing yards. So rushing gets its own baseline per group (quarterbacks vs everyone else), measured from the season's own data, and a quarterback regresses toward what quarterbacks do rather than toward ball carriers.</p>
<h3>Opponent adjustments</h3><p>Each defence is rated on rushing, yards per reception, yards per attempt and completion rate allowed, regressed by plays faced (50, 45 and 60) and capped at ±15%. These are applied <b>in full</b>, unlike the NFL page where only a measured share arrives. Touchdown matchups are derived from the yardage matchup at the NFL's measured shares (60% rushing, 77% receiving, 78% passing).</p>
<h3>Not in the data</h3><p>No injury report at any tier, no 2-point conversions, no weather feed, no sack projection and no betting lines on this page. A neutral-site game has no home team, so it takes no home-field bump.</p>
<h3>Scorecard and backtest</h3><p>Same discipline as the NFL: projections are logged before kickoff and never rewritten, with a settings stamp. The two leagues are never pooled. College is about six times the sample (roughly 1,265 scoreable player-games a week against the NFL's 201), so a couple of weeks clear the 400-row calibration bar, but it does not calibrate the NFL model.</p></div>`;
  },
};

let page = "Projections";
function render(keepFocus, focusId) {
  const act = document.activeElement, id = focusId || act?.id, pos = act?.selectionStart;
  view().innerHTML = pages[page]();
  if (keepFocus && id) { const el = document.getElementById(id); if (el) { el.focus(); try { el.setSelectionRange(pos, pos); } catch (e) {} } }
}
function route() {
  const h = decodeURIComponent(location.hash.slice(1)).replace("-", " ");
  const next = TABS.includes(h) ? h : "Projections";
  if (next !== page) { F.q = ""; F.pos = ""; F.team = ""; F.conf = ""; }
  page = next;
  document.getElementById("nav").innerHTML = TABS.map(t => `<a href="#${t.replace(" ", "-")}" class="${t === page ? "on" : ""}">${t}</a>`).join("");
  render();
}
window.addEventListener("hashchange", route);
document.addEventListener("change", e => {
  const t = e.target;
  if (t.classList.contains("ovr") && t.dataset.id) {
    const v = t.value.trim(), o = OVR[t.dataset.id] ||= {};
    if (v === "" || Number.isNaN(+v)) delete o[t.dataset.key]; else o[t.dataset.key] = Math.max(0, +v);
    if (!Object.keys(o).length) delete OVR[t.dataset.id];
    store.set("ovr", OVR); render();
  }
  else if (t.id === "pos") { F.pos = t.value; render(true); } else if (t.id === "conf") { F.conf = t.value; render(true); } else if (t.id === "team") { F.team = t.value; render(true); }
  else if (t.id === "game") { F.game = t.value; render(); } else if (t.id === "year") { F.year = t.value; render(); }
  else if (t.id === "hidestarted") { F.hideStarted = t.checked; render(true); } else if (t.id === "detail") { CFG.detail = t.checked; store.set("cfg", CFG); render(true); }
  else if (t.id === "preset") { CFG.preset = t.value; if (FB.SCORING[t.value]) CFG.scoring = {...FB.SCORING[t.value]}; store.set("cfg", CFG); render(); }
  else if (t.dataset.sc) { CFG.scoring[t.dataset.sc] = +t.value || 0; CFG.preset = "Custom"; store.set("cfg", CFG); render(); }
});
document.addEventListener("click", e => { if (e.target.id === "clr") { OVR = {}; store.set("ovr", OVR); render(); } });

async function boot() {
  CFG = {...CFG, ...store.get("cfg", {})}; OVR = store.get("ovr", {});
  if (!CFG.scoring || Object.keys(CFG.scoring).some(k => !(k in SCORE_LABEL) && k !== "two")) CFG = {...CFG, preset: "Full PPR", scoring: {...FB.SCORING["Full PPR"]}};
  await Promise.all(["projections", "games", "matchups", "scorecard", "meta"].map(async n => { try { const r = await fetch(`../data/cfb/${n}.json`, {cache: "no-cache"}); if (r.ok) D[n] = await r.json(); } catch (e) {} }));
  if (!D.projections || !D.meta) {
    view().innerHTML = `<div class="doc"><h2>No college data yet</h2><p>College football needs a free CollegeFootballData key. Get one at <a href="https://collegefootballdata.com/key">collegefootballdata.com/key</a>, add it as the <code>CFBD_API_KEY</code> repository secret (Settings → Secrets and variables → Actions), and run the "Football refresh data and deploy" workflow. College data appears here once it has run during the college season.</p></div>`;
    return;
  }
  D.backtest = {};
  await Promise.all((D.meta.backtests || []).map(async y => { try { const r = await fetch(`../data/cfb/backtest_${y}.json`, {cache: "no-cache"}); if (r.ok) D.backtest[y] = await r.json(); } catch (e) {} }));
  document.getElementById("asof").textContent = `Week ${D.meta.week} · data through week ${D.meta.asof_week} · built ${new Date(D.meta.generated).toLocaleString(undefined, {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"})}`;
  const msgs = [];
  if (D.meta.history_gaps?.length) msgs.push(`<b>History incomplete:</b> weeks ${D.meta.history_gaps.map(esc).join(", ")} are not fully fetched yet. These projections are provisional and are <b>not</b> being logged to the Scorecard until the data catches up.`);
  if (D.games.some(g => !g.done && started(g.ko))) msgs.push("Some of this week's games have already started: their rows are greyed out on Projections.");
  if (msgs.length) { const b = document.getElementById("banner"); b.hidden = false; b.innerHTML = msgs.join("<br>"); }
  route();
}
boot();

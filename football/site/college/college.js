"use strict";
// College football. Same engine and look as the NFL page, with what CollegeFootballData actually reports: no targets (receptions are projected
// directly), no sacks, no weather, no injury report and no 2-point conversions. Player-prop lines (when books post them) give leans, as on the NFL page.
const TABS = ["Projections", "Game Board", "Lines", "Leaders", "Matchups", "Usage", "Scorecard", "Backtest", "Config", "Methodology"];
const D = {};
const store = makeStore("gmc_");
let CFG = {preset: "Full PPR", scoring: {...FB.SCORING["Full PPR"]}, detail: false, mean: false};
let OVR = {};
const POS = ["QB", "RB", "WR", "TE"];
const view = () => document.getElementById("view");
const SCORE_LABEL = {passYd: "Pass yd", passTd: "Pass TD", intr: "INT", rushYd: "Rush yd", rushTd: "Rush TD", recYd: "Rec yd", recTd: "Rec TD", rec: "Reception", fum: "Fumble lost"};
const koDate = iso => iso ? new Date(iso) : null;
const started = iso => { const d = koDate(iso); return d ? d.getTime() <= Date.now() : false; };
const koLabel = iso => { const d = koDate(iso); return d ? d.toLocaleString(undefined, {weekday: "short", hour: "numeric", minute: "2-digit"}) : ""; };
const calcFor = p => {
  const c = FB.calcCfb(p, OVR[p.id], CFG.scoring);
  c.shown = c.pts * (CFG.mean ? D.meta.mean_factor : 1);          // Proj Pts is a MEDIAN; Mean = median x the college mean factor
  return c;
};
const proj = () => D.projections.map(p => ({...p, c: calcFor(p)}));
const siteTag = r => r.site === "N" ? "vs " + esc(r.opp) + " (neutral)" : (r.site === "vs" ? "vs " : "@ ") + esc(r.opp);
const noLineTag = p => p.returning ? ` <span class="pill start" title="Missed his team's last 2 games but a prop line is posted: he looks set to return. Only 4 such cases so far (2 played, at about 0.8 of projected volume), so this is a tag, not an adjustment.">returning</span>`
  : p.noline ? ` <span class="pill bkp" title="${p.nl_absent ? "Missed his team's last 2 games and has no prop line while the books are pricing his team: 15% of such players played in weeks 7-9." : "The books are pricing this team's players and he has no prop line. In weeks 7-8 only 41% of such players (projected 10+ opportunities) played, against 96% of those with a line."} Treat him as likely out or not featuring; his teammates' projections already assume it.">no line</span>` : "";
const nameCols = [{k: "name", h: "Player", l: 1, f: r => esc(r.name) + noLineTag(r)}, {k: "pos", h: "Pos", l: 1}, {k: "team", h: "Team", l: 1}];
const UTM = () => (UTM.c ||= Object.fromEntries((D.usage_trend || []).map(u => [u.id, u])));
// A RISING player (his share of the team's work up 5+ points over the last 3 games) has a history that understates his role: in the college backtest his projections ran 28% low on carries,
// so an UNDER lean on him is the stale history talking (no Under lean; Overs are kept). Same idea as the NFL's thin / role-shift / returning-star tags.
const riserUnder = (p, z) => z < 0 && UTM()[p.id]?.flag === "RISING";
const roleCol = () => depthCol(depthTip(true), true);
const F = {q: "", pos: "", team: "", conf: "", hideStarted: false, game: "", year: "", minG: 0};
const ovrCell = (r, key, shown) => `<input class="ovr" data-id="${esc(r.id)}" data-key="${key}" value="${OVR[r.id]?.[key] ?? ""}" placeholder="${num(shown)}">`;

// Player-prop lines for college (The Odds API; thin: mostly each team's top few players, and posted late). A lean is the model vs the consensus
// line in standard deviations of that market, with the college sigma fitted by the backtest (NFL fit while a market has too few college rows).
const LEAN = {lean: 0.25, strong: 0.5};
// College shows STRONG only. Graded on week 7 (509 lines): STRONG (0.5σ or more) won 47 of 63 (75%); LEAN (0.25-0.5σ) won 77 of 156 (49%), no better than the lines with no lean, so it is no longer flagged.
const leanTier = z => Math.abs(z) >= LEAN.strong ? "strong" : "";
const leanTip = "Model vs the consensus line, in standard deviations of the market. Only STRONG (0.5 or more) is flagged for college: it won 47 of 63 lines (75%) on week 7; smaller gaps won about half. One slate, so treat the size of the edge with caution.";
const specOf = stat => D.lines?.specs?.[stat];
const zOf = (spec, m, line) => (m - line) / FB.sigmaFor(spec, m);
function playerLines(p) {
  const L = D.lines;
  if (!L?.rows) return [];
  return L.rows.filter(r => r.id === p.id && specOf(r.stat)).map(r => {
    const spec = specOf(r.stat), m = p.c[r.stat], c = r.cons, sd = c ? FB.sides(c.line, m, spec) : null, st = Date.now() >= Date.parse(r.commence);
    const z = c ? zOf(spec, m, c.line) : null;
    return {r, spec, m, c, po: sd?.o, edge: sd ? (sd.o - c.p_over) * 100 : null, pp: r.dfs.prizepicks, ud: r.dfs.underdog ?? r.dfs.pick6, started: st, z,
      tier: !st && z != null && m > 0 && !isThin(p) && !riserUnder(p, z) ? leanTier(z) : "", side: z == null ? null : z > 0 ? "OVER" : "UNDER"};
  }).sort((a, b) => Math.abs(b.z ?? 0) - Math.abs(a.z ?? 0));
}
function leanBlock(L) {
  if (!L) return "";
  const N = {strong: "STRONG (0.5σ or more)", lean: "LEAN (0.25–0.5σ)", none: "Under 0.25σ"};
  const row = r => ({tier: N[r.tier], n: r.n, hit: r.hit, pct: r.n ? r.hit / r.n * 100 : null});
  const tc = [{k: "tier", h: "Lean tier", l: 1}, {k: "n", h: "Lines graded"}, {k: "hit", h: "Model side won"}, {k: "pct", h: "Hit rate", v: r => r.pct, f: r => r.pct == null ? "" : num(r.pct, 1) + "%"}];
  return `<h3>Lean record (player props)</h3><p class="sub">The model's side (its frozen projection vs the last pre-game consensus line) graded against the box score; a result equal to the line is a push and is left out. ${L.graded} lines graded, ${L.waiting} waiting on games${L.voided ? `, ${L.voided} MORE pick${L.voided > 1 ? "s" : ""} void (first-half exit, PrizePicks rule)` : ""}. Break-even is about 52.4% at standard prices, and a few dozen lines say very little.</p>
    ${L.graded ? table(tc, L.tiers.map(row), {id: "lt"}) : `<p class="mut">Nothing graded yet: college props are only posted close to kickoff, and the pre-game lines are logged from now on.</p>`}`;
}
const bestLean = p => { const b = playerLines(p)[0]; return b && b.tier ? b : null; };
const leanPill = l => l ? `<span class="pill lean-${l.tier}" title="${esc(leanTip)}">${l.tier === "strong" ? "STRONG " : ""}${l.side} ${esc(l.spec.label)} ${l.c.line} <span class="zs">${l.z > 0 ? "+" : ""}${num(l.z, 2)}σ</span></span>` : "";
const leanRow = r => { const b = bestLean(r); return b ? "lean-" + b.tier + "-row" : ""; };
const rowCls = r => [started(r.ko) ? "started" : "", leanRow(r)].filter(Boolean).join(" ");
const leanCol = {k: "lean", h: "Lean", l: 1, t: leanTip, v: r => { const b = playerLines(r)[0]; return b?.z == null ? null : Math.abs(b.z); },
  f: r => { const ls = playerLines(r); if (!ls.length) return ""; const b = ls[0];
    const rows = ls.map(x => `<div>${esc(x.spec.label)}: proj ${num(x.m)} · ${x.c ? `cons ${x.c.line} (${num(x.c.p_over * 100)}% over, ${FB.amer(x.c.p_over)}/${FB.amer(1 - x.c.p_over)}) · lean <b>${x.z > 0 ? "+" : ""}${num(x.z, 2)}σ</b> ${x.tier ? `<span class="pill lean-${x.tier}">${x.tier === "strong" ? "STRONG " : ""}${x.side}</span>` : ""} · model ${num(x.po * 100)}%` : ""}${x.pp != null ? ` · PrizePicks ${x.pp}` : ""}${x.ud != null ? ` · UD/Pick6 ${x.ud}` : ""}<br><span class="mut">${x.r.books.map(k => `${esc(k.b)} ${k.line} (${k.over ?? "-"}/${k.under ?? "-"})`).join(" · ")}</span></div>`).join("");
    const head = b.c ? (b.tier ? leanPill(b) : `${esc(b.spec.label)} ${b.z >= 0 ? "o" : "u"}${b.c.line} <span class="mut">${b.z > 0 ? "+" : ""}${num(b.z, 2)}σ</span>`) : `${esc(b.spec.label)} PP ${b.pp ?? ""}`;
    return `<details><summary>${head}${b.started ? ` <span class="pill hot">LIVE</span>` : ""}</summary><div class="lines-pop">${rows}</div></details>`; }};
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
    const cols = [...nameCols, roleCol(), {k: "prole", h: "Alignment (PFF)", l: 1, t: "Where he lines up on his pass routes over the last 3 games (PFF) and routes per team pass play", v: r => r.role?.rr, f: r => r.role ? `${roleCell(r.role)} <span class="mut">${num(r.role.rr, 0)}%</span>` : ""}, usageCol(r => UTM()[r.id], true), {k: "mu", h: "Matchup (PFF)", l: 1, t: MU_TIP, v: r => r.mu?.rank, f: r => muCell(r.mu)}, {k: "conf", h: "Conf", l: 1}, {k: "opp", h: "Opp", l: 1, f: siteTag, v: r => r.opp},
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
      {k: "cpts", h: CFG.mean ? "Mean Pts" : "Proj Pts", v: r => r.c.shown, f: r => `<b>${num(r.c.shown)}</b>`}, ...(D.lines?.rows?.length ? [leanCol] : [])];
    return `<h2>College Projections — Week ${D.meta.week}</h2>
      <p class="sub">${CFG.mean ? "Mean" : "Median"} points for every FBS player with an unplayed game this week and at least ${D.meta.min_opps ?? 8} touches or attempts this season. Shaded <b>OVR</b> boxes are yours; everything recalculates instantly (teammates are not re-scaled). Scoring: ${esc(CFG.preset)}. College has no injury report: availability is on you.</p>
      ${filters(`<label><input type="checkbox" id="hidestarted" ${F.hideStarted ? "checked" : ""}> hide games already started</label>
        <label><input type="checkbox" id="detail" ${CFG.detail ? "checked" : ""}> more columns</label><button id="clr">Clear overrides</button>`)}
      ${table(cols, rows, {id: "proj" + (det ? "d" : ""), sort: {key: "cpts"}, rowClass: rowCls})}`;
  },

  "Game Board"() {
    const games = D.games.filter(g => D.projections.some(p => p.game === g.game));
    if (!games.length) return `<h2>Game Board</h2><p class="sub">No games with projections yet.</p>`;
    if (!F.game || !games.some(g => g.game === F.game)) F.game = (games.find(g => !started(g.ko)) || games[0]).game;
    const g = games.find(x => x.game === F.game), all = proj().filter(p => p.game === g.game);
    const UT = Object.fromEntries((D.usage_trend || []).map(u => [u.id, u]));
    const mk = t => {
      const rows = all.filter(p => p.team === t);
      const cols = [{k: "name", h: "Player", l: 1}, {k: "pos", h: "Pos", l: 1}, roleCol(), {k: "prole", h: "Alignment (PFF)", l: 1, t: "Where he lines up on his pass routes over the last 3 games (PFF) and routes per team pass play", v: r => r.role?.rr, f: r => r.role ? `${roleCell(r.role)} <span class="mut">${num(r.role.rr, 0)}%</span>` : ""}, {k: "mu", h: "Matchup (PFF)", l: 1, t: MU_TIP, v: r => r.mu?.rank, f: r => muCell(r.mu)}, usageCol(r => UT[r.id], true), {k: "ccar", h: "Car", v: r => r.c.car, f: r => num(r.c.car)}, {k: "cry", h: "Rush", v: r => r.c.rushY, f: r => num(r.c.rushY, 0)},
        {k: "crec", h: "Rec", v: r => r.c.rec, f: r => num(r.c.rec)}, {k: "crecy", h: "Rec Yds", v: r => r.c.recY, f: r => num(r.c.recY, 0)},
        {k: "catt", h: "Att", v: r => r.c.att, f: r => r.c.att > 0 ? num(r.c.att) : ""}, {k: "cpy", h: "Pass Yds", v: r => r.c.passY, f: r => r.c.att > 0 ? num(r.c.passY, 0) : ""},
        {k: "ctd", h: "TD", v: r => r.c.rushTD + r.c.recTD + r.c.passTD, f: r => num(r.c.rushTD + r.c.recTD + r.c.passTD, 2)}, {k: "cpts", h: "Pts", v: r => r.c.shown, f: r => `<b>${num(r.c.shown)}</b>`}, ...(D.lines?.rows?.length ? [leanCol] : [])];
      return `<div><h3>${esc(t)} <span class="mut">· ${num(rows.reduce((a, r) => a + r.c.shown, 0))} projected pts across ${rows.length} players</span></h3>${table(cols, rows, {id: "gb" + t, sort: {key: "cpts"}, rowClass: r => [leanRow(r), focusRow(r)].filter(Boolean).join(" ")})}</div>`;
    };
    return `<h2>Game Board</h2><p class="sub">Pick a game; both teams ranked by projected points.</p>
      <div class="bar"><label>Game <select id="game">${games.map(x => `<option value="${esc(x.game)}" ${x.game === g.game ? "selected" : ""}>${esc(x.game)} · ${esc(koLabel(x.ko))}${started(x.ko) ? " (started)" : ""}</option>`).join("")}</select></label></div>
      <div class="gamehead"><div><span>Kickoff</span><b>${esc(koLabel(g.ko))}</b></div><div><span>Conferences</span><b>${esc(g.conf[0] || "-")} / ${esc(g.conf[1] || "-")}</b></div>${g.neutral ? `<div><span>Site</span><b>Neutral</b></div>` : ""}${g.spread == null && g.total == null ? "" : `<div><span>Line (The Odds API)</span><b>${g.spread == null ? "" : g.spread > 0 ? esc(g.home) + " -" + num(g.spread) : g.spread < 0 ? esc(g.away) + " -" + num(-g.spread) : "pick'em"}${g.total == null ? "" : " · O/U " + num(g.total)}</b></div>`}${g.home_imp == null ? "" : `<div><span>Implied total</span><b>${esc(g.away)} ${num(g.away_imp)} – ${esc(g.home)} ${num(g.home_imp)}</b></div>`}</div>
      ${compareCard({...D.teams, note: "Completed games only, FBS teams ranked (games against FCS teams count in a team's numbers). The last three rows are tendencies, not good or bad: pass rate is attempts over attempts + rushes, \"faced\" is how opponents attacked this defence, plays are attempts + rushes a game (a pace proxy). College rushing has sacks subtracted, as the NCAA books them. Third/fourth down, red zone and first downs are not in the box-score feed."}, g.away, g.home)}
      <div class="stack">${mk(g.away)}${mk(g.home)}</div>`;
  },

  Lines() {
    const L = D.lines;
    if (!L || !L.rows?.length) {
      const M = L?.meta || D.oddsmeta, games = (M?.games || []).map(g => `<li>${esc(g.game)} — kickoff ${koLabel(g.commence)}: ${g.props ? g.props + " props posted" : "<b>no player props posted yet</b>"}</li>`).join("");
      return `<h2>College Lines</h2><p class="sub">No college player props pulled yet. Books post them late, often the day before: the odds workflow pulls games starting in the next ${D.meta.props_horizon ?? 30} hours and fills this page in on its own.</p>${games ? `<ul class="sub">${games}</ul>` : ""}`;
    }
    const byId = Object.fromEntries(proj().map(p => [p.id, p]));
    const rows = L.rows.map(r => {
      const p = byId[r.id], spec = specOf(r.stat);
      if (!p || !spec) return null;
      const m = p.c[r.stat], c = r.cons, st = Date.now() >= Date.parse(r.commence), z = c ? zOf(spec, m, c.line) : null, sd = c ? FB.sides(c.line, m, spec) : null;
      return {pid: p.id, gb: p.game, name: p.name, pos: p.pos, team: p.team, game: r.game, label: spec.label, m, c, z, st, pp: r.dfs.prizepicks, ud: r.dfs.underdog ?? r.dfs.pick6,
        tier: st || z == null || m <= 0 || isThin(p) || riserUnder(p, z) ? "" : leanTier(z), side: z == null ? null : z > 0 ? "OVER" : "UNDER", edge: sd ? (sd.o - c.p_over) * 100 : null, ko: r.commence};
    }).filter(Boolean).filter(r => (!F.q || (r.name + " " + r.team).toLowerCase().includes(F.q.trim().toLowerCase())) && (!F.pos || r.pos === F.pos));
    const upd = /[zZ]|[+-]\d\d:?\d\d$/.test(L.updated) ? L.updated : L.updated + "Z", mins = Math.max(0, Math.round((Date.now() - Date.parse(upd)) / 60000));
    const cols = [{k: "name", h: "Player", l: 1, f: r => gbLink(r.name, r.gb, r.pid)}, {k: "pos", h: "Pos", l: 1}, {k: "team", h: "Team", l: 1}, {k: "label", h: "Market", l: 1},
      {k: "m", h: "Proj", f: r => num(r.m)}, {k: "line", h: "Line", v: r => r.c?.line, f: r => r.c ? r.c.line : ""},
      {k: "po", h: "Book %over", v: r => r.c?.p_over, f: r => r.c ? num(r.c.p_over * 100) : ""},
      {k: "z", h: "Lean σ", t: leanTip, v: r => r.z == null ? null : Math.abs(r.z), f: r => r.z == null ? "" : `${r.z > 0 ? "+" : ""}${num(r.z, 2)}`},
      {k: "pick", h: "Lean", l: 1, v: r => r.tier ? Math.abs(r.z) : 0, f: r => r.st ? `<span class="pill hot">LIVE</span>` : r.tier ? `<span class="pill lean-${r.tier}">${r.tier === "strong" ? "STRONG " : ""}${r.side}</span>` : ""},
      {k: "pp", h: "PrizePicks", f: r => r.pp ?? ""}, {k: "ud", h: "UD/Pick6", f: r => r.ud ?? ""}, {k: "game", h: "Game", l: 1}];
    const strong = rows.filter(r => r.tier === "strong").length;
    return `<h2>College Lines</h2><p class="sub">${rows.length} player props across ${L.games.length} games, last pulled ${mins < 90 ? mins + " min" : Math.round(mins / 60) + " h"} ago. Consensus is the median sportsbook line with the vig removed; the lean is the model's median projection against it, in standard deviations of the market (college sigma fitted by the backtest: ${Object.values(L.specs).map(x => x.label + (x.src === "college" ? "" : "*")).join(", ")}; * = NFL fit until enough college rows). <b>${strong}</b> strong. Books post college props for only the top few players per team, so most players have no line. Only STRONG leans are flagged: on week 7 they won 47 of 63 (75%) while smaller gaps won about half. That is one slate, so treat the size of the edge with caution.</p>
      <div class="bar"><input id="q" placeholder="Search player / team" value="${esc(F.q)}"><label>Pos <select id="pos">${["", ...POS].map(p => `<option ${F.pos === p ? "selected" : ""} value="${p}">${p || "All"}</option>`).join("")}</select></label></div>
      ${table(cols, rows, {id: "cl", sort: {key: "z"}, rowClass: r => r.st ? "started" : r.tier ? "lean-" + r.tier + "-row" : ""})}`;
  },

  Leaders() {
    const rows = proj();
    const CATS = [["Projected points", r => r.c.shown, 1], ["Rushing yards", r => r.c.rushY, 1], ["Receiving yards", r => r.c.recY, 1], ["Passing yards", r => r.c.passY, 1],
      ["Receptions", r => r.c.rec, 1], ["Carries", r => r.c.car, 1], ["Pass attempts", r => r.c.att, 1], ["Completions", r => r.c.comp, 1], ["Total TDs", r => r.c.rushTD + r.c.recTD + r.c.passTD, 2]];
    return `<h2>Projected Leaders — Week ${D.meta.week}</h2><p class="sub">Top 15 by projected output for the week ahead, not season totals.</p>${filters()}
      <div class="lead">${CATS.map(([label, f, dp]) => `<div class="card"><h4>${label}</h4><ol>${rows.filter(passes).map(r => ({r, v: f(r)})).filter(x => x.v > 0).sort((a, b) => b.v - a.v).slice(0, 15)
        .map(x => `<li><b>${esc(x.r.name)}</b> <span>${esc(x.r.team)} · ${num(x.v, dp)}</span></li>`).join("")}</ol></div>`).join("")}</div>`;
  },

  Usage() {
    const win = 3;
    if (!D.usage_trend) return `<h2>Usage</h2><p class="sub">No usage data yet.</p>`;
    const rows = D.usage_trend.filter(r => (!F.pos || r.pos === F.pos) && (!F.team || r.team === F.team) && (!F.conf || r.conf === F.conf)
      && (!F.q || (r.name + " " + r.team).toLowerCase().includes(F.q.toLowerCase())) && (!F.minG || r.g >= F.minG));
    const flagPill = f => f ? `<span class="pill ${f === "RISING" ? "lean-strong" : "lean-lean"}">${f}</span>` : "";
    const cols = [...nameCols, {k: "conf", h: "Conf", l: 1}, {k: "g", h: "G"},
      {k: "flag", h: "Role", l: 1, t: "RISING / FALLING: his main share (reception share for WR/TE, share of the team's carries + receptions for RB) moved 5 points or more", f: r => flagPill(r.flag), v: r => r.move},
      {k: "rec_b", h: "Rec share before", t: "Share of the team's receptions in the games before the window (the whole season when fewer than 2 games precede it). College box scores carry no targets, so receptions stand in", f: r => num(r.rec_b)},
      {k: "rec_r", h: `last ${win}`, f: r => `<b>${num(r.rec_r)}</b>`}, {k: "rec_d", h: "Δ", f: r => moveCell(r.rec_d)}, {k: "rec_w", h: "Weekly rec %", v: null, f: r => spark(r.rec_w.map(v => v ?? 0))},
      {k: "car_b", h: "Carry share before", f: r => num(r.car_b)}, {k: "car_r", h: `last ${win}`, f: r => `<b>${num(r.car_r)}</b>`}, {k: "car_d", h: "Δ", f: r => moveCell(r.car_d)},
      {k: "car_w", h: "Weekly carry %", v: null, f: r => spark(r.car_w.map(v => v ?? 0))},
      {k: "opp_r", h: `Opp share last ${win}`, t: "Share of the team's carries + receptions", f: r => num(r.opp_r)}, {k: "opp_d", h: "Δ", f: r => moveCell(r.opp_d)},
      {k: "snap_r", h: "Snap % (PFF)", t: "Offensive snaps over the team's plays, last 3 games (PFF); blank when PFF has no row", f: r => r.snap_r == null ? "" : num(r.snap_r, 0)}, {k: "snap_d", h: "Δ", f: r => moveCell(r.snap_d)},
      {k: "route_r", h: "Route % (PFF)", t: "Routes run per team pass play, last 3 games (PFF)", f: r => r.route_r == null ? "" : num(r.route_r, 0)}, {k: "route_d", h: "Δ", f: r => moveCell(r.route_d)},
      {k: "route_w", h: "Weekly route %", v: null, f: r => r.route_w?.some(v => v != null) ? spark(r.route_w.map(v => v ?? 0)) : ""},
      {k: "tm_d", h: "Team vol Δ", t: "The team's own receptions a game (carries for a back) over the same split: a team-wide drop makes a raw-count fall look like a role change when the share did not move", f: r => moveCell(r.tm_d, false)}];
    const movers = dir => rows.filter(r => r.move != null && (dir > 0 ? r.move >= 5 : r.move <= -5)).sort((a, b) => dir * (b.move - a.move)).slice(0, 8);
    const list = (title, arr) => `<div><h3>${title}</h3>${arr.length ? `<ul class="movers">${arr.map(r => `<li><b>${esc(r.name)}</b> <span class="mut">${esc(r.pos)} · ${esc(r.team)}</span> ${r.pos === "RB" ? "opp share" : "reception share"} ${num(r.pos === "RB" ? r.opp_b : r.rec_b)}% → <b>${num(r.pos === "RB" ? r.opp_r : r.rec_r)}%</b> (${moveCell(r.move)}) ${r.snap_d != null ? `<span class="mut">· snaps ${num(r.snap_b, 0)}% → ${num(r.snap_r, 0)}%</span>` : ""}</li>`).join("")}</ul>` : `<p class="mut">None moved 5 points.</p>`}</div>`;
    return `<h2>Usage</h2><p class="sub">How each college rusher's and receiver's role has moved: the last ${win} games against the games before them (share of the team's carries and receptions from the box scores, snap % and route % from PFF). The sparklines are week by week. A <b>Team vol Δ</b> next to a drop tells you whether the team simply ran or threw less. Display only: usage changes did not predict projection misses in the NFL tests, and college rosters shuffle more (injuries, blowouts).</p>
      ${filters(`<label>Min games <input id="ming" type="number" min="0" max="18" style="width:60px" value="${F.minG}"></label>`)}
      <div class="cols2">${list("Biggest risers", movers(1))}${list("Biggest fallers", movers(-1))}</div>
      ${table(cols, rows, {id: "ustr", sort: {key: "flag"}})}`;
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
      <div class="card"><b>${s.logged}</b><span>rows in the log</span></div><div class="card"><b>${s.late}</b><span>logged after kickoff (never scored)</span></div>${s.excluded != null ? `<div class="card"><b>${s.excluded}</b><span>FCS / tier-gap games (not scored)</span></div>` : ""}</div>`;
    if (!s.markets.length) return `<h2>College Scorecard</h2><p class="sub">Projections are logged before each week's games and never rewritten, then scored against the player's season average and last three games.</p>${cards}<p class="banner">Nothing scored yet under model <code>${esc(s.stamp)}</code>.</p>`;
    const mc = [{k: "label", h: "Market", l: 1}, {k: "n", h: "n"}, {k: "mae", h: "Model MAE", f: r => `<b>${num(r.mae, 2)}</b>`}, {k: "base", h: "Season-avg MAE", f: r => num(r.base, 2)}, {k: "last3", h: "Last-3 MAE", f: r => num(r.last3, 2)},
      {k: "vs", h: "vs season", t: "Negative = the model beat the baseline", f: r => vsBase(r.vs)}, {k: "vs3", h: "vs last-3", f: r => vsBase(r.vs3)}, {k: "bias", h: "Bias %", f: r => plainSigned(r.bias)},
      {k: "over", h: "Over %", f: r => r.over == null ? "" : `${num(r.over)} ± ${num(r.band)}`}, {k: "read", h: "Read", l: 1}];
    const pc = [{k: "pos", h: "Pos", l: 1}, {k: "n", h: "n"}, {k: "mae", h: "Pts MAE", f: r => num(r.mae, 2)}, {k: "over", h: "Over %", f: r => `${num(r.over)} ± ${num(r.band)}`}, {k: "bias", h: "Bias %", f: r => plainSigned(r.bias)}, {k: "read", h: "Read", l: 1}];
    const wc = [{k: "week", h: "Week"}, {k: "n", h: "n"}, {k: "model", h: "Model", f: r => `<b>${num(r.model, 2)}</b>`}, {k: "season", h: "Season avg", f: r => num(r.season, 2)}, {k: "last3", h: "Last-3", f: r => num(r.last3, 2)}];
    return `<h2>College Scorecard</h2><p class="sub">Live record under model <code>${esc(s.stamp)}</code> (full-PPR points).</p>${cards}<h3>By market</h3>${table(mc, s.markets, {id: "scm"})}<h3>By position (points)</h3>${table(pc, s.pos, {id: "scp"})}<h3>By week</h3>${table(wc, s.weeks, {id: "scw"})}${leanBlock(s.leans)}
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
    return `<h2>College Backtest</h2><p class="sub">Walk-forward over ${esc(b.season)}, weeks ${b.weeks.join(", ") || "none"}: each week is projected from the weeks before it by the same code the site runs. ${b.scored} player-games${b.excluded != null ? ` (${b.excluded} more left out: games against FCS teams and non-conference Power 4 vs lower-tier games)` : ""}. A negative percentage against a baseline means the model beat it.</p>
      ${b.thin ? `<p class="banner"><b>Read this before the numbers.</b> Only ${b.weeks.length} week(s) could be scored, so each projection was built from barely any history. With one prior week the season-average and last-3 baselines are the same number (what the player did last week), which is a hard baseline to beat on volume markets. A market losing to it here is a flag to re-check once more weeks exist, not a finding.</p>` : ""}
      <div class="bar"><label>Season <select id="year">${ys.map(y => `<option ${y === F.year ? "selected" : ""}>${y}</option>`).join("")}</select></label></div>
      ${table(c, b.table, {id: "bt"})}<h3>Measured college spread</h3>${table(sp, b.spread.map(s => ({...s, fit: 1})), {id: "bsp"})}
      <div class="doc"><p class="mut">Residual spread per market, fitted as <code>a + b × projection</code>: what a college P(over) should use. College lines are not on the site, so it is shown for reference; a negative slope on a market means the fit is reading noise until several weeks have scored.</p></div>`;
  },

  Config() {
    const sc = CFG.scoring;
    return `<h2>Config</h2><p class="sub">Saved on this device. Scoring only changes how stat lines are valued. College has no 2-point term.</p>
      <div class="bar"><label>Scoring preset <select id="preset">${[...Object.keys(FB.SCORING), "Custom"].map(p => `<option ${CFG.preset === p ? "selected" : ""}>${p}</option>`).join("")}</select></label>
        <label>Show <select id="mean"><option value="0" ${CFG.mean ? "" : "selected"}>Median (compare to lines)</option><option value="1" ${CFG.mean ? "selected" : ""}>Mean (season-long value)</option></select></label></div>
      <p class="mut">Projected points land on the <b>median</b> outcome (a few big games pull the average above the typical one). <b>Mean</b> multiplies points by ${D.meta.mean_factor}: the ratio of actual to projected points in the college walk-forward backtest (the NFL's is 1.17). It was measured on weeks 2-7 only, so treat it as rough.</p>
      <div class="bar">${Object.entries(SCORE_LABEL).map(([k, l]) => `<label>${l} <input data-sc="${k}" type="number" step="0.01" style="width:70px" value="${sc[k]}"></label>`).join("")}</div>
      <p><button id="clr">Clear all volume overrides</button></p>`;
  },

  Methodology() {
    return `<div class="doc"><h2>College methodology</h2>
<p>The same engine as the NFL page, fed by <a href="https://collegefootballdata.com">CollegeFootballData</a> box scores (one call per played week, FBS only). What is different is what the data allows:</p>
<h3>No targets</h3><p>CFBD reports receptions, not targets, so there is no catch rate. Receptions are projected directly, receiving touchdowns are per reception, and "Rec %" is a share of the team's projected receptions.</p>
<h3>Team volume is shared over the whole roster</h3><p>A team's projected carries, receptions and attempts are rescaled to a realistic team game (by at most ±20%). That rescale now divides over every player on the roster, not just the ones selected for projection. Before, the selected few were scaled up to the whole team's baseline, which handed them the receptions that depth-chart players below the minimum really take: projected receptions per team ran about 14-17 against only 10-12 actually caught by those same players. Fixing it cut points error from 4.0% to 10.3% better than a season average, turned receptions and receiving yards from worse than baseline to better, and moved the points over-rate from 38% to 48% (target 50). It was tuned on the first five weeks only, so treat the size of the gain with caution; the Backtest tab keeps the walk-forward honest as weeks accrue.</p><h3>Pass attempts are shared by who actually throws</h3><p>The same participation weighting as the NFL model: a team's pass attempts are divided among everyone who might throw them, weighting each player by how often he has thrown in the team's last six games (regressed, prior 0.1). Without it a backup who threw once counted as a full passer, projected attempts ran 4-10% low, the actual beat the projected passing yards 57% of the time and completions 56%, and the starter was pulled down. With it the over-rates are 49% and 46% (target 50) and passing error against a season average improved from 2.4% to 4.0% better. Tuned on the first weeks only.</p><h3>Quarterbacks run differently</h3><p>The NCAA charges a sack as a rushing attempt with the yardage lost, which the NFL does not. Across the 2026 fixture weeks college QBs ran 3.03 yards a carry against 4.73 for everyone else, and 29 of 166 qualifying QBs finished with negative rushing yards. So rushing gets its own baseline per group (quarterbacks vs everyone else), measured from the season's own data, and a quarterback regresses toward what quarterbacks do rather than toward ball carriers.</p>
<h3>Opponent adjustments</h3><p>Each defence is rated on rushing, yards per reception, yards per attempt and completion rate allowed, regressed by plays faced (50, 45 and 60) and capped at ±15%. These are applied <b>in full</b>, unlike the NFL page where only a measured share arrives. Touchdown matchups are derived from the yardage matchup at the NFL's measured shares (60% rushing, 77% receiving, 78% passing).</p>
<h3>Not in the data</h3><p>No injury report at any tier, no 2-point conversions, no weather feed and no sack projection. Player-prop lines come from The Odds API when books post them (thin for college: mostly each team's top few players, posted late); the Lines tab and the Lean column turn them into leans against the market, using a college spread fitted by the backtest. A neutral-site game has no home team, so it takes no home-field bump.</p>
<h3>Scorecard and backtest</h3><p>Same discipline as the NFL: projections are logged before kickoff and never rewritten, with a settings stamp. The two leagues are never pooled. College is about six times the sample (roughly 1,265 scoreable player-games a week against the NFL's 201), so a couple of weeks clear the 400-row calibration bar, but it does not calibrate the NFL model.</p></div>`;
  },
};

{ const base = pages.Lines;
  pages.Lines = () => base() + fpSection(D.fp_lines, Object.fromEntries(proj().map(p => [p.id, p])), p => FB.calcCfb(p, OVR[p.id], FB.SCORING["PrizePicks"]).pts, F); }
let page = "Projections";
function render(keepFocus, focusId) {
  const act = document.activeElement, id = focusId || act?.id, pos = act?.selectionStart;
  view().innerHTML = pages[page]();
  const fr = document.querySelector("tr.focus");
  if (fr) { fr.scrollIntoView({block: "center"}); F.focus = null; }
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
  else if (t.id === "ming") { F.minG = +t.value || 0; render(true); }
  else if (t.id === "game") { F.game = t.value; render(); } else if (t.id === "year") { F.year = t.value; render(); }
  else if (t.id === "hidestarted") { F.hideStarted = t.checked; render(true); } else if (t.id === "detail") { CFG.detail = t.checked; store.set("cfg", CFG); render(true); }
  else if (t.id === "preset") { CFG.preset = t.value; if (FB.SCORING[t.value]) CFG.scoring = {...FB.SCORING[t.value]}; store.set("cfg", CFG); render(); }
  else if (t.id === "mean") { CFG.mean = t.value === "1"; store.set("cfg", CFG); render(); }
  else if (t.dataset.sc) { CFG.scoring[t.dataset.sc] = +t.value || 0; CFG.preset = "Custom"; store.set("cfg", CFG); render(); }
});
document.addEventListener("click", e => { if (e.target.id === "clr") { OVR = {}; store.set("ovr", OVR); render(); } });

async function boot() {
  CFG = {...CFG, ...store.get("cfg", {})}; OVR = store.get("ovr", {});
  if (!CFG.scoring || Object.keys(CFG.scoring).some(k => !(k in SCORE_LABEL) && k !== "two")) CFG = {...CFG, preset: "Full PPR", scoring: {...FB.SCORING["Full PPR"]}};
  await Promise.all(["projections", "games", "teams", "matchups", "scorecard", "meta", "usage_trend"].map(async n => { try { const r = await fetch(`../data/cfb/${n}.json`, {cache: "no-cache"}); if (r.ok) D[n] = await r.json(); } catch (e) {} }));
  if (!D.projections || !D.meta) {
    view().innerHTML = `<div class="doc"><h2>No college data yet</h2><p>College football needs a free CollegeFootballData key. Get one at <a href="https://collegefootballdata.com/key">collegefootballdata.com/key</a>, add it as the <code>CFBD_API_KEY</code> repository secret (Settings → Secrets and variables → Actions), and run the "Football refresh data and deploy" workflow. College data appears here once it has run during the college season.</p></div>`;
    return;
  }
  try { const r = await fetch("../data/cfb/lines.json", {cache: "no-cache"}); if (r.ok) D.lines = await r.json(); } catch (e) {}
  try { const r = await fetch("../data/cfb/fp_lines.json", {cache: "no-cache"}); if (r.ok) D.fp_lines = await r.json(); } catch (e) {}
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

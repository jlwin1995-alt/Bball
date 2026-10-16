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
    const better = x === y ? 0 : ((x > y) === r.higher ? -1 : 1);       // -1 = away side better, 1 = home side better
    const cell = (v, rk, win) => `<b class="${win ? "win" : ""}">${num(v, r.dp)}</b> <span class="mut">#${rk}</span>`;
    return `<div class="cmp"><div class="cmpv l">${cell(x, a[r.k + "_rk"], better === -1)}</div><div class="cmpl">${esc(r.label)}
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
const depthCol = (tip, inferred) => ({k: "depth", h: "Depth", l: 1, t: tip, v: r => r.depth ? (starterOut(r) ? -1 : (r.depth.st ? 0 : 1) * 100 + r.depth.rank) : 999, f: r => depthPill(r.depth, tip, r.status)});

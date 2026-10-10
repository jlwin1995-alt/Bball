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

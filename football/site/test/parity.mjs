// node football/site/test/parity.mjs  - the browser arithmetic must reproduce the pipeline's own stat lines and points.
import {createRequire} from "module";
import {readFileSync} from "fs";
const require = createRequire(import.meta.url);
const FB = require("../model.js");
const dir = new URL("../data/", import.meta.url).pathname;
const proj = JSON.parse(readFileSync(dir + "projections.json")), meta = JSON.parse(readFileSync(dir + "meta.json"));
const W = FB.SCORING["Full PPR"];
let worst = {}, bad = 0;
for (const p of proj) {
  const c = FB.calc(p, {}, W, meta);
  for (const [k, pk] of [["rushY", "ry"], ["rec", "rec"], ["recY", "recy"], ["passY", "py"], ["comp", "comp"], ["sacks", "sacks"], ["rushTD", "rtd"], ["recTD", "rectd"], ["passTD", "ptd"], ["int", "int"], ["fum", "fum"], ["two", "two"], ["pts", "pts"]]) {
    const d = Math.abs(c[k] - p[pk]);
    worst[k] = Math.max(worst[k] || 0, d);
    if (d > 0.02) { bad++; if (bad < 8) console.log("MISMATCH", p.name, k, c[k], p[pk]); }
  }
}
console.log("players", proj.length, "worst abs diff per field", JSON.stringify(worst));
// college (only when college data has been built)
import {existsSync} from "fs";
const cdir = process.argv[2] || dir + "cfb/";
if (existsSync(cdir + "projections.json")) {
  const cp = JSON.parse(readFileSync(cdir + "projections.json")); let cworst = 0, cbad = 0;
  for (const p of cp) {
    const c = FB.calcCfb(p, {}, W);
    for (const [k, pk] of [["rushY", "ry"], ["recY", "recy"], ["passY", "py"], ["comp", "comp"], ["rushTD", "rtd"], ["recTD", "rectd"], ["passTD", "ptd"], ["int", "int"], ["fum", "fum"], ["pts", "pts"]]) {
      const d = Math.abs(c[k] - p[pk]); cworst = Math.max(cworst, d); if (d > 0.02) { cbad++; if (cbad < 5) console.log("CFB MISMATCH", p.name, k, c[k], p[pk]); }
    }
  }
  console.log("college players", cp.length, "worst abs diff", cworst); bad += cbad;
}
process.exit(bad ? 1 : 0);

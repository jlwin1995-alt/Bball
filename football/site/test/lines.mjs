// node football/site/test/lines.mjs - probability maths used by the Lines tab.
import {createRequire} from "module";
const require = createRequire(import.meta.url);
const FB = require("../model.js");
let bad = 0;
const ok = (name, cond) => { if (!cond) { bad++; console.log("FAIL", name); } };
const near = (a, b, e = 1e-3) => Math.abs(a - b) < e;
ok("normCdf(0)", near(FB.normCdf(0), 0.5, 1e-9));
ok("normCdf(1.96)", near(FB.normCdf(1.96), 0.975, 1e-4));
ok("normCdf symmetric", near(FB.normCdf(-1.3) + FB.normCdf(1.3), 1, 1e-9));
const py = {a: 141.57, b: -0.281, law: "normal"};
ok("sigma pass yds at 250", near(FB.sigmaFor(py, 250), 141.57 - 0.281 * 250, 1e-9));
ok("sigma floor", FB.sigmaFor({a: 0.1, b: 0, law: "normal"}, 100) === 12);
const s = FB.sides(249.5, 249.5, py);
ok("half-point line at the median is a coin flip", near(s.o, 0.5) && near(s.u, 0.5));
ok("probabilities add to 1 on half lines", near(FB.sides(200.5, 249.5, py).o + FB.sides(200.5, 249.5, py).u, 1, 1e-9));
const w = FB.sides(250, 250, py);
ok("whole-number line: push removed, symmetric case is a coin flip", near(w.o + w.u, 1, 1e-9) && near(w.o, 0.5));
const rc = FB.sides(5, 5, {a: 1.25, b: 0.286, law: "normal"});
ok("receptions line 5 at projection 5 has no phantom under edge", near(rc.o, 0.5));
const sk = {a: 0.997, b: 0.308, law: "poisson"};
ok("poisson CDF", near(FB.poisCdf(2, 1.5), 0.8088, 1e-3));            // e^-1.5 (1 + 1.5 + 1.125)
ok("sacks over 1.5 at mean 1.5", near(FB.sides(1.5, 1.5, sk).o, 1 - 0.5578, 1e-3));
ok("sacks with no projection", FB.sides(0.5, 0, sk).o === 0);
ok("amer", FB.amer(0.6) === "-150" && FB.amer(0.4) === "+150");
ok("impl", near(FB.impl(-110), 0.5238, 1e-3) && near(FB.impl(150), 0.4, 1e-9));
console.log(bad ? `${bad} failed` : "lines maths ok");
process.exit(bad ? 1 : 0);

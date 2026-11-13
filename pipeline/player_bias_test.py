"""Walk-forward test of player_bias: flag players using only games BEFORE a cutoff, then measure their miss AFTER it (minus the league's miss over the same dates).

    python -m pipeline.player_bias_test [days_after]     # cutoff = the last `days_after` game days (default 6)

past = the flagged deviation (in the flagged direction) when flagged; fwd = the same measure on later games; kept = share of flagged players who kept the direction.
fwd / past is the share of the deviation that persisted; 1.0 would be a pure player effect, 0 pure noise. First run (Nov 13, 22 game days): past 4.18 -> fwd 2.83, kept 84% (242 flags).
"""
import sys
import pandas as pd
from pipeline import player_bias as P


def main(days_after=6):
    m, L = P.load(), P.lines(); dates = sorted(m.date.unique()); cut = dates[-days_after]
    f = P.build(m, L, upto=cut); f = f[f.flag_proj != ""]; fw = m[m.date >= cut]; res = []
    for r in f.itertuples():
        x = fw[fw.pid == r.pid]
        if len(x) < 2: continue
        sg = 1 if r.flag_proj == "over" else -1
        lg = (fw[r.stat] - fw[r.stat + "_p"]).mean()
        res.append((r.stat, len(x), r.vs_league * sg, ((x[r.stat] - x[r.stat + "_p"]).mean() - lg) * sg))
    d = pd.DataFrame(res, columns=["stat", "games_after", "past", "fwd"])
    if d.empty: print("not enough games after the cutoff"); return
    print(f"cutoff {cut}: {len(f)} flags, {len(d)} with 2+ later games; past {d.past.mean():.2f} -> forward {d.fwd.mean():.2f} ({d.fwd.mean() / d.past.mean():.0%} persisted), kept direction {(d.fwd > 0).mean():.0%}")
    print(d.groupby("stat").agg(flags=("fwd", "size"), past=("past", "mean"), fwd=("fwd", "mean"), kept=("fwd", lambda s: (s > 0).mean())).round(2).to_string())


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 6)

"""Where does compound growth actually peak?

The design claims leverage has an interior optimum. That is a claim about
this data, not a theorem to be quoted, so it gets measured: sweep the
volatility target and the leverage cap and look at where the COMPOUND
return turns over. If growth rises monotonically with leverage across the
whole range, the Kelly story is wrong here and the cap is just timidity.
"""
import sys, time
sys.path.insert(0, "research")
from growth import build, run, stats, P, TRADING

dates, px, bench, rf = build()
warm = max(P["trend_days"], P["mom_days"], P["cov_days"]) + 5
i0 = max(warm, next(i for i, d in enumerate(dates) if d >= "1996-09-30"))
bh = [100_000.0 * bench[i] / bench[i0] for i in range(i0, len(dates))]
B = stats(bh, rf[i0:])
print(f"S&P 500 TR over the same window: CAGR {B['cagr']:.2f}%  "
      f"vol {B['vol']:.1f}%  maxDD {B['mdd']:.1f}%  Sharpe {B['sharpe']:.2f}\n")

t0 = time.time()
print("compound growth vs how much risk the book is allowed to take")
print(f"{'lev cap':>8}" + "".join(f"{f'tgt {v:.0%}':>10}" for v in
      (0.10, 0.12, 0.15, 0.18, 0.22, 0.26)))
print("-" * 68)
grid = {}
for cap in (1.0, 1.25, 1.5, 2.0, 2.5, 3.0):
    line = []
    for tv in (0.10, 0.12, 0.15, 0.18, 0.22, 0.26):
        p = dict(P, max_lev=cap, target_vol=tv)
        r = run(dates, px, rf, p, start_i=i0)
        s = stats(r["curve"], rf[i0:])
        grid[(cap, tv)] = (s, r)
        line.append(s["cagr"])
    print(f"{cap:>7.2f}x" + "".join(f"{v:>9.2f}%" for v in line))

print(f"\n({time.time()-t0:.0f}s)\n")
print("the same grid, but realised volatility - did the target bind?")
print(f"{'lev cap':>8}" + "".join(f"{f'tgt {v:.0%}':>10}" for v in
      (0.10, 0.12, 0.15, 0.18, 0.22, 0.26)))
print("-" * 68)
for cap in (1.0, 1.25, 1.5, 2.0, 2.5, 3.0):
    print(f"{cap:>7.2f}x" + "".join(
        f"{grid[(cap,tv)][0]['vol']:>9.1f}%"
        for tv in (0.10, 0.12, 0.15, 0.18, 0.22, 0.26)))

print("\ndrawdown at the same points")
print(f"{'lev cap':>8}" + "".join(f"{f'tgt {v:.0%}':>10}" for v in
      (0.10, 0.12, 0.15, 0.18, 0.22, 0.26)))
print("-" * 68)
for cap in (1.0, 1.25, 1.5, 2.0, 2.5, 3.0):
    print(f"{cap:>7.2f}x" + "".join(
        f"{grid[(cap,tv)][0]['mdd']:>9.1f}%"
        for tv in (0.10, 0.12, 0.15, 0.18, 0.22, 0.26)))

best = max(grid, key=lambda k: grid[k][0]["cagr"])
s, r = grid[best]
print(f"\npeak compound growth at cap {best[0]:.2f}x / target {best[1]:.0%}: "
      f"{s['cagr']:.2f}%  vol {s['vol']:.1f}%  maxDD {s['mdd']:.1f}%  "
      f"Sharpe {s['sharpe']:.2f}  avg lev {r['avg_lev']:.2f}x")
print("Peak is where the data says growth stops rising. Whether to SIT")
print("there is a separate question - see the turnover and drawdown.")

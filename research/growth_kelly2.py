"""Push the leverage sweep until growth actually turns over."""
import sys
sys.path.insert(0, "research")
from growth import build, run, stats, P

dates, px, bench, rf = build()
warm = max(P["trend_days"], P["mom_days"], P["cov_days"]) + 5
i0 = max(warm, next(i for i, d in enumerate(dates) if d >= "1996-09-30"))

print("full sweep at target 30% (so the CAP is what binds)")
print(f"{'cap':>6}{'CAGR':>9}{'vol':>8}{'maxDD':>9}{'Sharpe':>8}"
      f"{'avg lev':>9}{'turnover':>10}{'costs':>12}")
print("-" * 71)
rows = {}
for cap in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0):
    r = run(dates, px, rf, dict(P, max_lev=cap, target_vol=0.30), start_i=i0)
    s = stats(r["curve"], rf[i0:])
    rows[cap] = s
    print(f"{cap:>5.1f}x{s['cagr']:>8.2f}%{s['vol']:>7.1f}%{s['mdd']:>8.1f}%"
          f"{s['sharpe']:>8.2f}{r['avg_lev']:>8.2f}x"
          f"{r['turnover']*100:>9.0f}%{'$'+format(round(r['costs']),','):>12}")

peak = max(rows, key=lambda k: rows[k]["cagr"])
print(f"\ngrowth peaks at {peak:.1f}x ({rows[peak]['cagr']:.2f}%), "
      f"then falls - the interior optimum is real, just far out")

print("\nwhat fraction of peak growth each cap buys, and at what drawdown")
print(f"{'cap':>6}{'% of peak CAGR':>17}{'% of peak maxDD':>18}")
print("-" * 41)
for cap in sorted(rows):
    print(f"{cap:>5.1f}x{rows[cap]['cagr']/rows[peak]['cagr']*100:>16.0f}%"
          f"{rows[cap]['mdd']/rows[peak]['mdd']*100:>17.0f}%")

# Financing at T-bill+100bp is credible for a futures/portfolio-margin
# book up to roughly 2x. Beyond that a retail investor pays far more, so
# the high-leverage columns above are optimistic by construction.
print("\nsame sweep with financing that widens as leverage rises")
print("(+100bp to 2x, +250bp to 3x, +500bp beyond - closer to a real broker)")
print(f"{'cap':>6}{'CAGR':>9}{'maxDD':>9}{'Sharpe':>8}")
print("-" * 32)
for cap in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0):
    spread = 0.010 if cap <= 2 else (0.025 if cap <= 3 else 0.050)
    r = run(dates, px, rf, dict(P, max_lev=cap, target_vol=0.30,
                                borrow_spread=spread), start_i=i0)
    s = stats(r["curve"], rf[i0:])
    print(f"{cap:>5.1f}x{s['cagr']:>8.2f}%{s['mdd']:>8.1f}%{s['sharpe']:>8.2f}")

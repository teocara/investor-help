"""Does trading less often, or in bigger steps, pay for itself?"""
import sys
sys.path.insert(0, "research")
from growth import build, run, stats, P

dates, px, bench, rf = build()
warm = max(P["trend_days"], P["mom_days"], P["cov_days"]) + 5
i0 = max(warm, next(i for i, d in enumerate(dates) if d >= "1996-09-30"))
BASE = dict(P, max_lev=2.0, target_vol=0.30)

print("no-trade bands, at 2.0x cap and 10 bps")
print(f"{'pos band':>10}{'lev band':>10}{'CAGR':>9}{'maxDD':>9}"
      f"{'Sharpe':>8}{'turnover':>10}{'costs':>12}")
print("-" * 68)
for pb in (0.005, 0.02, 0.04):
    for lb in (0.0, 0.10, 0.20):
        r = run(dates, px, rf, dict(BASE, band=pb, lev_band=lb), start_i=i0)
        s = stats(r["curve"], rf[i0:])
        print(f"{pb:>9.1%}{lb:>10.0%}{s['cagr']:>8.2f}%{s['mdd']:>8.1f}%"
              f"{s['sharpe']:>8.2f}{r['turnover']*100:>9.0f}%"
              f"{'$'+format(round(r['costs']),','):>12}")

print("\nsensitivity to the cost assumption itself (best band settings)")
print(f"{'cost':>8}{'CAGR':>9}{'vs S&P':>9}")
print("-" * 26)
bh = [100_000.0 * bench[i] / bench[i0] for i in range(i0, len(dates))]
B = stats(bh, rf[i0:])
for c in (0.0, 0.0005, 0.0010, 0.0020, 0.0050):
    r = run(dates, px, rf, dict(BASE, band=0.02, lev_band=0.10, cost_bps=c),
            start_i=i0)
    s = stats(r["curve"], rf[i0:])
    print(f"{c*1e4:>6.0f}bp{s['cagr']:>8.2f}%{s['cagr']-B['cagr']:>+8.2f}")

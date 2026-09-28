"""Is the result a plateau or a knife edge?

A backtest that only works at one parameter setting is a fitted curve, not
a strategy. Every knob gets moved and the whole surface gets printed -
including the settings that make it look worse.
"""
import sys
sys.path.insert(0, "research")
from growth import build, run, stats, P

dates, px, bench, rf = build()
warm = max(P["trend_days"], P["mom_days"], P["cov_days"]) + 5
i0 = max(warm, next(i for i, d in enumerate(dates) if d >= "1996-09-30"))
bh = [100_000.0 * bench[i] / bench[i0] for i in range(i0, len(dates))]
B = stats(bh, rf[i0:])
BASE = dict(P, max_lev=2.0, target_vol=0.30, band=0.02, lev_band=0.10)

def go(**kw):
    r = run(dates, px, rf, dict(BASE, **kw), start_i=i0)
    return stats(r["curve"], rf[i0:]), r

print("rebalance cadence (cost 10 bps)")
print(f"{'every':>10}{'CAGR':>9}{'maxDD':>9}{'Sharpe':>8}"
      f"{'turnover':>10}{'costs':>12}{'@30bp':>9}")
print("-" * 67)
for m, lbl in ((1,"month"),(2,"2 months"),(3,"quarter"),(6,"6 months"),(12,"year")):
    s, r = go(rebal_months=m)
    s30, _ = go(rebal_months=m, cost_bps=0.0030)
    print(f"{lbl:>10}{s['cagr']:>8.2f}%{s['mdd']:>8.1f}%{s['sharpe']:>8.2f}"
          f"{r['turnover']*100:>9.0f}%{'$'+format(round(r['costs']),','):>12}"
          f"{s30['cagr']:>8.2f}%")

print("\ntrend window (the 10-month SMA is the published default, 210d)")
print(f"{'days':>8}{'CAGR':>9}{'maxDD':>9}{'Sharpe':>8}")
print("-" * 34)
for d in (100, 150, 180, 210, 250, 300):
    s, _ = go(trend_days=d)
    print(f"{d:>8}{s['cagr']:>8.2f}%{s['mdd']:>8.1f}%{s['sharpe']:>8.2f}")

print("\nabsolute-momentum lookback")
print(f"{'days':>8}{'CAGR':>9}{'maxDD':>9}{'Sharpe':>8}")
print("-" * 34)
for d in (126, 189, 252, 378, 504):
    s, _ = go(mom_days=d)
    print(f"{d:>8}{s['cagr']:>8.2f}%{s['mdd']:>8.1f}%{s['sharpe']:>8.2f}")

print("\nsleeve cap / equity cap")
print(f"{'sleeve':>8}{'equity':>9}{'CAGR':>9}{'maxDD':>9}{'Sharpe':>8}")
print("-" * 43)
for sc in (0.20, 0.25, 0.35):
    for ec in (0.60, 0.70, 1.00):
        s, _ = go(max_sleeve=sc, max_equity=ec)
        print(f"{sc:>7.0%}{ec:>9.0%}{s['cagr']:>8.2f}%{s['mdd']:>8.1f}%"
              f"{s['sharpe']:>8.2f}")

print("\nturning individual rules OFF, to see which ones carry the result")
print(f"{'':<34}{'CAGR':>9}{'maxDD':>9}{'Sharpe':>8}")
print("-" * 60)
s, _ = go()
print(f"{'everything on':<34}{s['cagr']:>8.2f}%{s['mdd']:>8.1f}%{s['sharpe']:>8.2f}")
for lbl, kw in (
    ("no trend gate",            dict(trend_days=1)),
    ("no absolute momentum",     dict(mom_days=1)),
    ("no vol targeting (flat 1x)", dict(target_vol=0.0, max_lev=1.0)),
    ("no leverage (cap 1.0x)",   dict(max_lev=1.0)),
    ("equal weight, not inverse-vol", dict(vol_days=-1)),
):
    try:
        s, _ = go(**kw)
        print(f"{lbl:<34}{s['cagr']:>8.2f}%{s['mdd']:>8.1f}%{s['sharpe']:>8.2f}")
    except Exception as e:
        print(f"{lbl:<34}  n/a ({type(e).__name__})")
print(f"{'S&P 500 total return':<34}{B['cagr']:>8.2f}%{B['mdd']:>8.1f}%"
      f"{B['sharpe']:>8.2f}")

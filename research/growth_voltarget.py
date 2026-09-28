"""Does vol targeting earn its place, or is it a rule I like the sound of?

Over 30 years it looks slightly NEGATIVE on return. That is not by itself
a reason to drop it - it is bought as tail insurance, so the place to
look is the tails, not the average.
"""
import sys
sys.path.insert(0, "research")
from growth import build, run, stats, P

dates, px, bench, rf = build()
warm = max(P["trend_days"], P["mom_days"], P["cov_days"]) + 5
i0 = max(warm, next(i for i, d in enumerate(dates) if d >= "1996-09-30"))
BASE = dict(P, max_lev=2.0, target_vol=0.30, band=0.02, lev_band=0.10)

on  = run(dates, px, rf, BASE, start_i=i0)
off = run(dates, px, rf, dict(BASE, use_voltarget=False), start_i=i0)
d = dates[i0:]

def window(curve, a, b):
    ia = next((k for k, x in enumerate(d) if x >= a), 0)
    ib = next((k for k, x in enumerate(d) if x >= b), len(curve) - 1)
    seg = curve[ia:ib + 1]
    peak, mdd = seg[0], 0.0
    for x in seg:
        peak = max(peak, x); mdd = min(mdd, x / peak - 1)
    return (seg[-1] / seg[0] - 1) * 100, mdd * 100

print("the episodes vol targeting is supposed to be bought for")
print(f"{'':<22}{'targeted':>20}{'flat 2x':>20}")
print(f"{'':<22}{'return':>10}{'maxDD':>10}{'return':>10}{'maxDD':>10}")
print("-" * 62)
for a, b, lbl in (("2000-03-24","2002-10-09","dotcom bust"),
                  ("2007-10-09","2009-03-09","financial crisis"),
                  ("2020-02-19","2020-03-23","covid crash"),
                  ("2022-01-03","2022-10-12","2022 bear"),
                  ("1998-07-17","1998-10-08","LTCM"),
                  ("2018-09-20","2018-12-24","Q4 2018")):
    r1, m1 = window(on["curve"], a, b)
    r2, m2 = window(off["curve"], a, b)
    print(f"{lbl:<22}{r1:>9.1f}%{m1:>9.1f}%{r2:>9.1f}%{m2:>9.1f}%")

s1, s2 = stats(on["curve"], rf[i0:]), stats(off["curve"], rf[i0:])
print(f"\n{'full 30 years':<22}{s1['cagr']:>9.2f}%{s1['mdd']:>9.1f}%"
      f"{s2['cagr']:>9.2f}%{s2['mdd']:>9.1f}%")

# Worst single days and months - the part an average cannot show.
def tail(curve, lbl):
    r = [curve[i] / curve[i - 1] - 1 for i in range(1, len(curve))]
    r.sort()
    mo = []
    for i in range(21, len(curve), 21):
        mo.append(curve[i] / curve[i - 21] - 1)
    mo.sort()
    print(f"{lbl:<14}{r[0]*100:>10.2f}%{sum(r[:5])/5*100:>12.2f}%"
          f"{mo[0]*100:>12.1f}%{sum(mo[:5])/5*100:>13.1f}%")

print(f"\n{'':<14}{'worst day':>10}{'avg worst 5':>12}"
      f"{'worst month':>12}{'avg worst 5':>13}")
print("-" * 61)
tail(on["curve"], "targeted")
tail(off["curve"], "flat 2x")
print(f"\nturnover: targeted {on['turnover']*100:.0f}%/yr, "
      f"flat {off['turnover']*100:.0f}%/yr")

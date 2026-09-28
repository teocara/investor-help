"""Do the caps work when they are made to actually bind?"""
import sys
sys.path.insert(0, "research")
from growth import build, run, stats, P
dates, px, bench, rf = build()
warm = max(P["trend_days"], P["mom_days"], P["cov_days"]) + 5
i0 = max(warm, next(i for i, d in enumerate(dates) if d >= "1996-09-30"))
bh = [100_000.0 * bench[i] / bench[i0] for i in range(i0, len(dates))]
B = stats(bh, rf[i0:])
print(f"{'':<42}{'CAGR':>9}{'vol':>8}{'maxDD':>9}{'Sharpe':>8}{'lev':>8}")
print("-"*84)
for lbl, kw in (
    ("caps renormalised away (as tested)", dict()),
    ("caps binding on gross, 25% / 70%",   dict(hard_caps=True)),
    ("caps binding, 30% sleeve / 80% eq",  dict(hard_caps=True, max_sleeve=.30, max_equity=.80)),
    ("caps binding, 20% sleeve / 60% eq",  dict(hard_caps=True, max_sleeve=.20, max_equity=.60)),
):
    r = run(dates, px, rf, dict(P, **kw), start_i=i0)
    s = stats(r["curve"], rf[i0:])
    print(f"{lbl:<42}{s['cagr']:>8.2f}%{s['vol']:>7.1f}%{s['mdd']:>8.1f}%"
          f"{s['sharpe']:>8.2f}{r['avg_lev']:>7.2f}x")
print(f"{'S&P 500 total return':<42}{B['cagr']:>8.2f}%{B['vol']:>7.1f}%"
      f"{B['mdd']:>8.1f}%{B['sharpe']:>8.2f}{1.0:>7.2f}x")

print("\nthe episodes where an all-equity book should hurt")
d = dates[i0:]
def win(c,a,b):
    ia=next((k for k,x in enumerate(d) if x>=a),0); ib=next((k for k,x in enumerate(d) if x>=b),len(c)-1)
    seg=c[ia:ib+1]; pk=seg[0]; m=0.0
    for x in seg: pk=max(pk,x); m=min(m,x/pk-1)
    return (seg[-1]/seg[0]-1)*100, m*100
soft = run(dates, px, rf, P, start_i=i0)["curve"]
hard = run(dates, px, rf, dict(P, hard_caps=True), start_i=i0)["curve"]
print(f"{'':<20}{'as tested':>20}{'caps binding':>20}")
print(f"{'':<20}{'return':>10}{'maxDD':>10}{'return':>10}{'maxDD':>10}")
print("-"*60)
for a,b,l in (("2000-03-24","2002-10-09","dotcom"),("2007-10-09","2009-03-09","GFC"),
              ("2020-02-19","2020-03-23","covid"),("2022-01-03","2022-10-12","2022")):
    r1,m1=win(soft,a,b); r2,m2=win(hard,a,b)
    print(f"{l:<20}{r1:>9.1f}%{m1:>9.1f}%{r2:>9.1f}%{m2:>9.1f}%")

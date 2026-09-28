"""Run the 30-year study and print it."""
import sys, math, json
sys.path.insert(0, "research")
from growth import (build, run, stats, SLEEVES, P, TRADING, load)

dates, px, bench, rf = build()
print(f"calendar {dates[0]} -> {dates[-1]}   {len(dates)} sessions, "
      f"{len(px)} sleeves\n")

# Book goes live after warmup; pin it to a whole 30 years.
warm = max(P["trend_days"], P["mom_days"], P["cov_days"]) + 5
i0 = max(warm, next(i for i, d in enumerate(dates) if d >= "1996-09-30"))
print(f"live from {dates[i0]} ({(len(dates)-i0)/TRADING:.1f} years)\n")

res = run(dates, px, rf, P, start_i=i0)
S = stats(res["curve"], rf[i0:])

# Buy and hold the S&P, total return, same window, same start capital.
bh = [100_000.0 * bench[i] / bench[i0] for i in range(i0, len(dates))]
B = stats(bh, rf[i0:])

# 60/40 rebalanced monthly, the other honest alternative.
def sixty_forty():
    from growth import month_ends
    eq, bd = px["VFINX"], px["VUSTX"]
    cash, se, sb = 0.0, 0.0, 0.0
    rbs = {i for i in month_ends(dates) if i >= i0}
    out, v = [], 100_000.0
    se, sb = v * .6 / eq[i0], v * .4 / bd[i0]
    for i in range(i0, len(dates)):
        v = se * eq[i] + sb * bd[i]
        if i in rbs:
            se, sb = v * .6 / eq[i], v * .4 / bd[i]
        out.append(v)
    return out
SF = stats(sixty_forty(), rf[i0:])

def row(n, s, extra=""):
    print(f"{n:<26}{s['cagr']:>7.2f}%{s['vol']:>8.1f}%{s['mdd']:>9.1f}%"
          f"{s['sharpe']:>8.2f}{s['sortino']:>9.2f}{s['calmar']:>8.2f}"
          f"{s['mult']:>10.1f}x  {extra}")

print(f"{'':<26}{'CAGR':>8}{'vol':>8}{'maxDD':>9}{'Sharpe':>8}"
      f"{'Sortino':>9}{'Calmar':>8}{'growth':>11}")
print("-"*94)
row("Growth book", S, f"lev {res['avg_lev']:.2f}x, {res['avg_n']:.1f} sleeves")
row("S&P 500 total return", B, "VFINX buy & hold")
row("60/40 monthly rebalanced", SF, "VFINX / VUSTX")
print()
print(f"turnover {res['turnover']*100:.0f}%/yr on gross exposure, "
      f"total costs ${res['costs']:,.0f} on a $100k start")
print(f"average gross exposure {res['avg_lev']:.2f}x, "
      f"{res['avg_n']:.1f} sleeves held")
print()

print("how much of this survives a worse execution assumption")
print(f"{'cost per fill':>15}{'CAGR':>9}{'vs S&P':>9}")
print("-" * 33)
for c in (0.0, 0.0005, 0.0010, 0.0020, 0.0030, 0.0050):
    r2 = run(dates, px, rf, dict(P, cost_bps=c), start_i=i0)
    s2 = stats(r2["curve"], rf[i0:])
    mark = "  <- assumed" if abs(c - P["cost_bps"]) < 1e-9 else ""
    print(f"{c*1e4:>13.0f}bp{s2['cagr']:>8.2f}%"
          f"{s2['cagr']-B['cagr']:>+8.2f}{mark}")
print()

# The identity the design is built on.
print("arithmetic mean vs what actually compounds")
print(f"{'':<26}{'arith mean':>12}{'compound':>11}{'variance drag':>15}")
print("-"*64)
for n, s in (("Growth book", S), ("S&P 500 TR", B), ("60/40", SF)):
    print(f"{n:<26}{s['arith']:>11.2f}%{s['cagr']:>10.2f}%{-s['drag']:>14.2f}%")
print()

# Decade by decade - does it survive regimes, or is it one lucky stretch?
print("by period")
print(f"{'':<16}{'growth':>9}{'S&P TR':>9}{'diff':>8}"
      f"{'g.maxDD':>10}{'S&P maxDD':>11}")
print("-"*63)
def sub(a, b, lbl):
    ia = next((k for k, d in enumerate(dates[i0:]) if d >= a), None)
    ib = next((k for k, d in enumerate(dates[i0:]) if d >= b), len(res["curve"]))
    if ia is None or ib - ia < 200: return
    g, h = res["curve"][ia:ib], bh[ia:ib]
    gs, hs = stats(g), stats(h)
    print(f"{lbl:<16}{gs['cagr']:>8.1f}%{hs['cagr']:>8.1f}%"
          f"{gs['cagr']-hs['cagr']:>+7.1f}{gs['mdd']:>9.1f}%{hs['mdd']:>10.1f}%")
for a, b, l in [("1996-09-30","2000-03-24","96-00 boom"),
                ("2000-03-24","2002-10-09","00-02 dotcom"),
                ("2002-10-09","2007-10-09","02-07 recovery"),
                ("2007-10-09","2009-03-09","07-09 GFC"),
                ("2009-03-09","2020-02-19","09-20 bull"),
                ("2020-02-19","2020-03-23","2020 covid"),
                ("2020-03-23","2022-01-03","20-22 rebound"),
                ("2022-01-03","2022-10-12","2022 bear"),
                ("2022-10-12","2026-09-25","22-26 latest")]:
    sub(a, b, l)
print()

# Worst years, since the left tail is what the design is paying to avoid.
import collections
def by_year(c, d):
    y = collections.OrderedDict()
    for i, dt_ in enumerate(d):
        y.setdefault(dt_[:4], [i, i])[1] = i
    return {k: c[v[1]]/c[v[0]]-1 for k, v in y.items()}
gy, hy = by_year(res["curve"], dates[i0:]), by_year(bh, dates[i0:])
worst = sorted(hy, key=lambda k: hy[k])[:6]
print("the six worst years for the S&P, and what the book did")
print(f"{'year':<8}{'S&P TR':>10}{'growth':>10}")
print("-"*28)
for k in sorted(worst):
    print(f"{k:<8}{hy[k]*100:>9.1f}%{gy[k]*100:>9.1f}%")
print()
wins = sum(1 for k in gy if gy[k] > hy[k])
print(f"beat the S&P in {wins}/{len(gy)} calendar years")

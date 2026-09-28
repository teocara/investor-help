"""Which rules carry the result, and which are decoration?"""
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

print(f"{'':<36}{'CAGR':>9}{'vol':>8}{'maxDD':>9}{'Sharpe':>8}{'lev':>8}")
print("-" * 78)
s, r = go()
print(f"{'everything on':<36}{s['cagr']:>8.2f}%{s['vol']:>7.1f}%"
      f"{s['mdd']:>8.1f}%{s['sharpe']:>8.2f}{r['avg_lev']:>7.2f}x")
for lbl, kw in (
    ("without the trend gate",        dict(use_trend=False)),
    ("without absolute momentum",     dict(use_mom=False)),
    ("without either gate",           dict(use_trend=False, use_mom=False)),
    ("equal weight, not inverse-vol", dict(use_ivol=False)),
    ("without vol targeting",         dict(use_voltarget=False)),
    ("without leverage (1.0x cap)",   dict(max_lev=1.0)),
    ("US large cap sleeve only",      dict()),
):
    if lbl.startswith("US large"):
        r2 = run(dates, {"VFINX": px["VFINX"]}, rf, BASE,
                 names=["VFINX"], start_i=i0)
        s2 = stats(r2["curve"], rf[i0:])
        print(f"{lbl:<36}{s2['cagr']:>8.2f}%{s2['vol']:>7.1f}%"
              f"{s2['mdd']:>8.1f}%{s2['sharpe']:>8.2f}{r2['avg_lev']:>7.2f}x")
        continue
    s2, r2 = go(**kw)
    print(f"{lbl:<36}{s2['cagr']:>8.2f}%{s2['vol']:>7.1f}%"
          f"{s2['mdd']:>8.1f}%{s2['sharpe']:>8.2f}{r2['avg_lev']:>7.2f}x")
print(f"{'S&P 500 total return':<36}{B['cagr']:>8.2f}%{B['vol']:>7.1f}%"
      f"{B['mdd']:>8.1f}%{B['sharpe']:>8.2f}{1.0:>7.2f}x")

print("\nlook-ahead check: how much does the 1-day execution lag cost?")
for lag, lbl in ((0, "same close (cheating)"), (1, "next close (used)"),
                 (2, "two days later"), (5, "a week later")):
    s2, _ = go(exec_lag=lag)
    print(f"  {lbl:<24}{s2['cagr']:>8.2f}%  maxDD {s2['mdd']:>6.1f}%")

print("\nevery rolling 10-year window, growth book vs S&P total return")
import collections
TR = 252
cur, bhc = go()[1]["curve"], bh
n = len(cur)
wins, tot, worst = 0, 0, (99.0, "")
out = []
for st in range(0, n - 10 * TR, TR // 2):
    en = st + 10 * TR
    g = (cur[en] / cur[st]) ** (1 / 10) - 1
    h = (bhc[en] / bhc[st]) ** (1 / 10) - 1
    tot += 1
    wins += g > h
    if g - h < worst[0]:
        worst = (g - h, dates[i0 + st][:7])
    out.append((dates[i0 + st][:7], g * 100, h * 100))
print(f"  beat buy & hold in {wins}/{tot} rolling 10-year windows")
print(f"  worst 10-year shortfall: {worst[0]*100:+.1f} pts/yr, "
      f"window starting {worst[1]}")
print(f"  {'start':<10}{'growth':>9}{'S&P':>9}{'diff':>8}")
for d, g, h in out[::6]:
    print(f"  {d:<10}{g:>8.1f}%{h:>8.1f}%{g-h:>+7.1f}")

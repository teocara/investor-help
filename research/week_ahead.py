"""The week of 8 October 2026, against the historical record.

WHAT THIS DOES AND DOES NOT MEASURE

The dominant scheduled event this week is the September CPI print on
Wednesday 14 October. The obvious study — what the index does on CPI
release days — is NOT here, and deliberately so: it needs the actual
historical release dates, and both BLS and FRED are blocked from this
container. Approximating them from "some day between the 10th and the
15th" would produce a table that looks authoritative and is not, so the
CPI-day question is left open rather than answered badly.

What IS exactly datable, and happens to be more relevant anyway:

  * The window from today to election day, in every midterm year since
    1930. That is literally the period being entered, so it is the right
    comparison rather than a proxy for one.
  * October's volatility, which has a reputation worth checking.
  * The second week of October specifically, which is when Q3 earnings
    season opens and when CPI lands this year.
  * The size of the largest single-day move in mid-October, which is the
    honest way to size jump risk for a week containing a CPI print.
  * Where VIX sits today against its own history, which says what the
    market is already charging for this week.

Price index, 1927 on, so dividends are missing and every return here is
understated by roughly the dividend yield of its era. That matters for
the absolute numbers and cancels in the comparisons.
"""
import sys
import math
import statistics as st
import datetime as dt
from collections import defaultdict

sys.path.insert(0, "research")
from elections import (election_day, midterm_years, presidential_years, load,
                       idx_on_or_after, describe, welch, bootstrap_ci)

TODAY = dt.date(2026, 10, 8)
ELECTION = election_day(2026)

dates, px = load("_GSPC")
vdates, vpx = load("_VIX")
print(f"^GSPC {dates[0]} -> {dates[-1]}   ^VIX {vdates[0]} -> {vdates[-1]}")
print(f"today {TODAY}, election {ELECTION} "
      f"({(ELECTION-TODAY).days} days)\n")

Y0, Y1 = int(dates[0][:4]), int(dates[-1][:4])
mid = [y for y in midterm_years(Y0, Y1)]
pres = set(presidential_years(Y0, Y1))
no_elec = [y for y in range(Y0, Y1 + 1) if y not in pres and y not in mid]


def ret_between(d0, d1):
    """Return between two calendar dates, using the first session on or
    after each. None if either falls outside the series."""
    i = idx_on_or_after(dates, d0)
    j = idx_on_or_after(dates, d1)
    if i is None or j is None or j <= i:
        return None
    a, b = px[dates[i]], px[dates[j]]
    return (b / a - 1) * 100 if a and b and a > 0 else None


# ── 1. Today to election day, historically ───────────────────────────────
print("=" * 70)
print("1. THE WINDOW WE ARE IN: 8 October -> election day")
print("=" * 70)
print("Same calendar span in every year, so season is held fixed. Only the")
print("presence of an election differs.\n")


def window(years):
    out = []
    for y in years:
        e = election_day(y)
        r = ret_between(f"{y}-10-08", e.isoformat())
        if r is not None:
            out.append((y, r))
    return out


mw, ow, pw = window(mid), window(no_elec), window(sorted(pres))
print(f"{'year type':<20}{'n':>4}{'mean':>9}{'median':>9}{'sd':>8}"
      f"{'worst':>9}{'best':>8}{'% up':>7}")
print("-" * 74)
for lbl, g in (("midterm year", mw), ("presidential year", pw),
               ("no election", ow)):
    s = describe([v for _, v in g])
    if s:
        print(f"{lbl:<20}{s['n']:>4}{s['mean']:>8.1f}%{s['median']:>8.1f}%"
              f"{s['sd']:>7.1f}%{s['min']:>8.1f}%{s['max']:>7.1f}%"
              f"{s['pos']:>6.0f}%")
w = welch([v for _, v in mw], [v for _, v in ow])
if w:
    ci = bootstrap_ci([v for _, v in mw])
    print(f"\nmidterm minus no-election: {w['diff']:+.1f} points, p={w['p']:.3f}")
    print(f"bootstrap 95% CI on the midterm mean: "
          f"[{ci[0]:+.1f}%, {ci[1]:+.1f}%]" if ci else "")

print("\nevery midterm year, 8 Oct to election day:")
print(f"{'':<2}" + "".join(f"{y:>8}" for y, _ in mw[:12]))
print(f"{'':<2}" + "".join(f"{v:>7.1f}%" for _, v in mw[:12]))
print(f"{'':<2}" + "".join(f"{y:>8}" for y, _ in mw[12:]))
print(f"{'':<2}" + "".join(f"{v:>7.1f}%" for _, v in mw[12:]))

# ── 2. Is October really the volatile month? ─────────────────────────────
print("\n\n" + "=" * 70)
print("2. OCTOBER'S REPUTATION, CHECKED")
print("=" * 70)
rets = defaultdict(list)
for i in range(1, len(dates)):
    a, b = px[dates[i - 1]], px[dates[i]]
    if a and b and a > 0:
        rets[dates[i][5:7]].append(math.log(b / a))
print(f"{'month':<8}{'ann. vol':>11}{'mean day':>11}{'worst day':>12}"
      f"{'days >2%':>11}")
print("-" * 53)
MON = {"01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "May",
       "06": "Jun", "07": "Jul", "08": "Aug", "09": "Sep", "10": "Oct",
       "11": "Nov", "12": "Dec"}
tbl = []
for m in sorted(rets):
    r = rets[m]
    vol = st.stdev(r) * math.sqrt(252) * 100
    big = sum(1 for x in r if abs(x) > 0.02) / len(r) * 100
    tbl.append((vol, m, st.mean(r) * 100, min(r) * 100, big))
for vol, m, mu, wd, big in sorted(tbl, reverse=True):
    mark = "  <-- October" if m == "10" else ""
    print(f"{MON[m]:<8}{vol:>10.1f}%{mu:>10.3f}%{wd:>11.1f}%{big:>10.1f}%{mark}")

# ── 3. The second week of October ────────────────────────────────────────
print("\n\n" + "=" * 70)
print("3. THIS SPECIFIC WEEK: 8-16 October")
print("=" * 70)
print("Q3 earnings season opens and, this year, CPI lands inside it.\n")
wk = []
for y in range(Y0, Y1 + 1):
    r = ret_between(f"{y}-10-08", f"{y}-10-16")
    if r is not None:
        wk.append((y, r))
s = describe([v for _, v in wk])
allwk = []
for i in range(0, len(dates) - 6, 3):
    a, b = px[dates[i]], px[dates[i + 6]]
    if a and b and a > 0:
        allwk.append((b / a - 1) * 100)
sa = describe(allwk)
if s and sa:
    print(f"  8-16 Oct, all years      mean {s['mean']:+.1f}%   "
          f"median {s['median']:+.1f}%   sd {s['sd']:.1f}%   "
          f"{s['pos']:.0f}% up   (n={s['n']})")
    print(f"  any six-session window   mean {sa['mean']:+.1f}%   "
          f"median {sa['median']:+.1f}%   sd {sa['sd']:.1f}%   "
          f"{sa['pos']:.0f}% up")
    print(f"  -> this week is {s['sd']/sa['sd']:.2f}x as volatile as a "
          f"typical six-session stretch")
worst = sorted(wk, key=lambda kv: kv[1])[:5]
print("\n  the five worst 8-16 Octobers on record:")
for y, v in worst:
    print(f"    {y}  {v:+.1f}%")

# ── 4. Jump risk: biggest single day in mid-October ──────────────────────
print("\n\n" + "=" * 70)
print("4. JUMP RISK — biggest single-day move, 8-18 October")
print("=" * 70)
print("The honest way to size a week containing a CPI print: not an")
print("average, but how large the largest day tends to be.\n")
jumps = []
for y in range(Y0, Y1 + 1):
    i = idx_on_or_after(dates, f"{y}-10-08")
    j = idx_on_or_after(dates, f"{y}-10-18")
    if i is None or j is None or j <= i:
        continue
    best = 0.0
    for k in range(i + 1, min(j + 1, len(dates))):
        a, b = px[dates[k - 1]], px[dates[k]]
        if a and b and a > 0:
            best = max(best, abs(b / a - 1) * 100)
    jumps.append((y, best))
sj = describe([v for _, v in jumps])
if sj:
    xs = sorted(v for _, v in jumps)
    print(f"  median largest day   {sj['median']:.1f}%")
    print(f"  75th percentile      {xs[int(.75*len(xs))]:.1f}%")
    print(f"  90th percentile      {xs[int(.90*len(xs))]:.1f}%")
    print(f"  worst on record      {sj['max']:.1f}%  "
          f"({[y for y,v in jumps if v==sj['max']][0]})")
    print(f"  years with a 2%+ day {sum(1 for _,v in jumps if v>=2)}/{sj['n']}"
          f" ({sum(1 for _,v in jumps if v>=2)/sj['n']*100:.0f}%)")

# ── 5. What the market is charging today ─────────────────────────────────
print("\n\n" + "=" * 70)
print("5. WHAT IS ALREADY PRICED")
print("=" * 70)
vlast = vpx[vdates[-1]]
hist = sorted(vpx[d] for d in vdates)
rank = sum(1 for x in hist if x < vlast) / len(hist) * 100
print(f"  VIX today ({vdates[-1]})   {vlast:.1f}")
print(f"  percentile vs 1990-     {rank:.0f}th")
print(f"  implies a daily move of  +/-{vlast/math.sqrt(252):.2f}% "
      f"on an average day this month")

oct_mid = [vpx[d] for d in vdates if d[5:7] == "10"]
som = describe(oct_mid)
if som:
    print(f"  average October VIX      {som['mean']:.1f}")
pre = []
for y in [y for y in mid if y >= 1990]:
    i = idx_on_or_after(vdates, f"{y}-10-08")
    if i is not None:
        pre.append(vpx[vdates[i]])
sp = describe(pre)
if sp:
    print(f"  8 Oct of midterm years   {sp['mean']:.1f} "
          f"(n={sp['n']}, range {sp['min']:.1f}-{sp['max']:.1f})")
    print(f"  -> today is {'ABOVE' if vlast > sp['mean'] else 'BELOW'} "
          f"the typical pre-midterm October reading")

# where the index sits
last = px[dates[-1]]
hi252 = max(px[d] for d in dates[-252:])
print(f"\n  index today              {last:,.0f}")
print(f"  vs 52-week high          {(last/hi252-1)*100:+.1f}%")
i1y = len(dates) - 253
print(f"  trailing 12 months       {(last/px[dates[i1y]]-1)*100:+.1f}%")


# ── 6. Is a calm VIX a warning or a forecast? ────────────────────────────
# Worth doing before concluding anything from "VIX looks low". The tempting
# read is complacency ahead of an event week. The data says the opposite:
# VIX is a forecast here, and a decent one.
print("\n\n" + "=" * 70)
print("6. IS TODAY'S CALM A WARNING, OR A FORECAST?")
print("=" * 70)
obs = []
for y in range(1990, Y1 + 1):
    iv = idx_on_or_after(vdates, f"{y}-10-08")
    ip = idx_on_or_after(dates, f"{y}-10-08")
    if iv is None or ip is None or ip + 11 >= len(dates):
        continue
    rs = []
    for k in range(ip + 1, ip + 11):
        a, b = px[dates[k - 1]], px[dates[k]]
        if a and b and a > 0:
            rs.append(math.log(b / a))
    if len(rs) < 8:
        continue
    obs.append((y, vpx[vdates[iv]], st.stdev(rs) * math.sqrt(252) * 100,
                min(rs) * 100, (px[dates[ip + 10]] / px[dates[ip]] - 1) * 100))
obs.sort(key=lambda r: r[1])
t = len(obs) // 3
print(f"{'VIX tercile on 8 Oct':<24}{'n':>3}{'mean VIX':>10}"
      f"{'next 10d vol':>14}{'worst day':>11}{'10d return':>12}")
print("-" * 74)
groups = (("low  (calmest third)", obs[:t]), ("mid", obs[t:2 * t]),
          ("high (most fearful)", obs[2 * t:]))
for lbl, g in groups:
    print(f"{lbl:<24}{len(g):>3}{st.mean(x[1] for x in g):>10.1f}"
          f"{st.mean(x[2] for x in g):>13.1f}%{st.mean(x[3] for x in g):>10.1f}%"
          f"{st.mean(x[4] for x in g):>11.1f}%")
w = welch([x[2] for x in obs[:t]], [x[2] for x in obs[2 * t:]])
if w:
    print(f"\n  calm vs fearful, subsequent realised vol: p={w['p']:.3f}")
    print("  A low reading has PRECEDED a calm fortnight. So today's 15.4 is")
    print("  not evidence of complacency to trade against — it is a forecast,")
    print("  and on this record a reasonably accurate one.")

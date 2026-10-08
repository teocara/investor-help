"""Has the midterm effect decayed, and is there a mechanism behind it?

The pattern survived the seasonal and Depression controls, which makes it
worth two harder questions.

DECAY. This is one of the most repeated regularities in markets. A real,
exploitable edge that everyone knows should erode as it gets traded. If it
is just as strong in the last forty years as in the first forty, that is
mildly suspicious of a statistical artifact rather than reassuring.

MECHANISM. The standard story is that an election resolves policy
uncertainty, and that stocks pay a premium for uncertainty beforehand. If
true, implied volatility should be elevated going into a midterm and fall
afterwards. VIX starts in 1990, which gives nine midterms — too few to
prove anything, but enough to check the story is not contradicted.
"""
import sys
import statistics as st

sys.path.insert(0, "research")
from elections import (election_day, midterm_years, presidential_years, load,
                       idx_on_or_after, fwd_return, back_return, describe,
                       welch)

dates, px = load("_GSPC")
Y0, Y1 = int(dates[0][:4]), int(dates[-1][:4])
mid = [y for y in midterm_years(Y0, Y1)
       if idx_on_or_after(dates, election_day(y).isoformat()) is not None]
pres = set(presidential_years(Y0, Y1))
no_elec = [y for y in range(Y0, Y1 + 1) if y not in pres and y not in mid]


def at(y):
    return idx_on_or_after(dates, election_day(y).isoformat())


def vals(years, bars):
    out = []
    for y in years:
        i = at(y)
        if i is None:
            continue
        v = fwd_return(dates, px, i, bars)
        if v is not None:
            out.append((y, v))
    return out


# ── Decay ────────────────────────────────────────────────────────────────
print("DECAY — the 6-month effect split into non-overlapping eras")
print(f"{'era':<14}{'midterms':>9}{'midterm 6m':>13}{'no-election 6m':>16}"
       f"{'diff':>8}{'p':>8}")
print("-" * 68)
ERAS = [(1930, 1958), (1962, 1986), (1990, 2010), (2014, 2026)]
for a, b in ERAS:
    m = [v for y, v in vals([y for y in mid if a <= y <= b], 126)]
    o = [v for y, v in vals([y for y in no_elec if a <= y <= b], 126)]
    sm, so, w = describe(m), describe(o), welch(m, o)
    if sm and so and w:
        print(f"{f'{a}-{b}':<14}{sm['n']:>9}{sm['mean']:>12.1f}%"
              f"{so['mean']:>15.1f}%{w['diff']:>+7.1f}{w['p']:>8.3f}")
    elif sm:
        print(f"{f'{a}-{b}':<14}{sm['n']:>9}{sm['mean']:>12.1f}%"
              f"{'—':>15}{'—':>8}{'—':>8}")

print("\nfirst half vs second half of the sample")
half = 1974
for lbl, yrs in (("1930-1970", [y for y in mid if y <= 1970]),
                 ("1974-2022", [y for y in mid if y >= half])):
    m = [v for _, v in vals(yrs, 126)]
    s = describe(m)
    if s:
        print(f"  {lbl:<12}n={s['n']:<4}mean {s['mean']:+6.1f}%   "
              f"median {s['median']:+6.1f}%   {s['pos']:.0f}% positive")

# ── Mechanism: implied volatility ────────────────────────────────────────
vdates, vpx = load("_VIX")
if vdates:
    print(f"\n\nMECHANISM — VIX around midterms ({vdates[0]} on)")
    print("If elections price an uncertainty premium, VIX should be high")
    print("going in and fall after. Nine observations: suggestive at best.")
    print(f"{'year':<7}{'VIX -1m':>9}{'VIX day':>9}{'VIX +1m':>9}"
          f"{'change':>9}")
    print("-" * 43)
    drops = []
    for y in [y for y in mid if y >= 1990]:
        i = idx_on_or_after(vdates, election_day(y).isoformat())
        if i is None or i + 21 >= len(vdates) or i - 21 < 0:
            continue
        pre, on, post = (vpx[vdates[i - 21]], vpx[vdates[i]],
                         vpx[vdates[i + 21]])
        drops.append(post - on)
        print(f"{y:<7}{pre:>9.1f}{on:>9.1f}{post:>9.1f}{post-on:>+9.1f}")
    s = describe(drops)
    if s:
        print(f"\n  mean change in VIX over the month after: {s['mean']:+.1f} "
              f"points (n={s['n']}, {sum(1 for x in drops if x<0)}/{s['n']} fell)")
        print(f"  95% CI: [{s['lo']:+.1f}, {s['hi']:+.1f}]")
        if s["lo"] < 0 < s["hi"]:
            print("  The interval spans zero: the uncertainty-release story is")
            print("  NOT established by this. It is only not contradicted.")

# ── What an investor would actually have to live through ─────────────────
print("\n\nTHE PART A BACKTEST HIDES — drawdown inside the winning window")
print("Even when the 6 months ended up, how far down did it go first?")
print(f"{'year':<7}{'6m return':>11}{'worst dip':>11}")
print("-" * 29)
dips = []
for y in mid:
    i = at(y)
    if i is None or i + 126 >= len(dates):
        continue
    seg = [px[d] for d in dates[i:i + 127]]
    peak, mdd = seg[0], 0.0
    for v in seg:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    r = (seg[-1] / seg[0] - 1) * 100
    dips.append(mdd * 100)
    print(f"{y:<7}{r:>10.1f}%{mdd*100:>10.1f}%")
s = describe(dips)
if s:
    print(f"\n  median worst dip inside the window: {s['median']:.1f}%")
    print(f"  worst: {s['min']:.1f}%   "
          f"{sum(1 for x in dips if x < -5)}/{s['n']} saw a 5%+ drawdown")

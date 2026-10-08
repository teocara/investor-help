"""Is the post-midterm rally actually about elections?

Two confounds can produce the whole result without any election effect:

  SEASONALITY. Midterms land in the first week of November, every time.
  November-to-April is the strongest six-month stretch of the calendar
  year — the "Halloween effect", documented long before anyone linked it
  to elections. Comparing post-midterm windows against windows starting
  in an arbitrary month compares November with the average month, and
  November wins that for reasons that have nothing to do with voting.
  The correct baseline is the SAME calendar window in years with no
  midterm.

  THE 1930s. The sample opens in 1930, and the baseline therefore
  contains the Depression's continuous collapse, where almost every
  12-month window is deeply negative. That drags the baseline down
  without telling us anything about elections.

Both are tested here. If the effect survives both, it is worth something.
If it does not, the honest answer is that the midterm story is a seasonal
pattern with an election sticker on it.
"""
import sys
import statistics as st

sys.path.insert(0, "research")
from elections import (election_day, midterm_years, presidential_years, load,
                       idx_on_or_after, fwd_return, describe, welch,
                       bootstrap_ci)

dates, px = load("_GSPC")
print(f"^GSPC {dates[0]} -> {dates[-1]}\n")

HOR = [("3m", 63), ("6m", 126), ("12m", 252)]
Y0, Y1 = int(dates[0][:4]), int(dates[-1][:4])

mid_years = [y for y in midterm_years(Y0, Y1)
             if idx_on_or_after(dates, election_day(y).isoformat()) is not None]
pres_years = set(presidential_years(Y0, Y1))


def nov_anchor(y):
    """The index of election day in year y, whether or not y has one. Uses
    the same first-Tuesday-after-first-Monday rule so the calendar window
    is identical across years and only the election differs."""
    return idx_on_or_after(dates, election_day(y).isoformat())


def group(years, bars):
    out = []
    for y in years:
        i = nov_anchor(y)
        if i is None:
            continue
        v = fwd_return(dates, px, i, bars)
        if v is not None:
            out.append((y, v))
    return out


# ── TEST 1: same calendar window, election years vs not ──────────────────
print("TEST 1 — same November anchor, midterm years vs non-election years")
print("(both start in the first week of November, so the season is held fixed)")
print(f"{'horizon':<9}{'midterm':>10}{'no election':>14}{'diff':>9}{'p':>8}"
      f"{'n mid':>7}{'n other':>9}")
print("-" * 66)
no_elec = [y for y in range(Y0, Y1 + 1)
           if y not in pres_years and y not in mid_years]
t1 = {}
for l, b in HOR:
    m = [v for _, v in group(mid_years, b)]
    o = [v for _, v in group(no_elec, b)]
    w = welch(m, o)
    sm, so = describe(m), describe(o)
    if w and sm and so:
        t1[l] = w
        print(f"{l:<9}{sm['mean']:>9.1f}%{so['mean']:>13.1f}%"
              f"{w['diff']:>+8.1f}{w['p']:>8.3f}{sm['n']:>7}{so['n']:>9}")

# ── TEST 2: all three election states, one calendar window ───────────────
print("\n\nTEST 2 — November anchor, all three year types side by side")
print(f"{'horizon':<9}{'midterm':>10}{'presidential':>14}{'odd year':>11}"
      f"{'% up mid':>10}{'% up odd':>10}")
print("-" * 65)
odd = [y for y in range(Y0, Y1 + 1) if y % 2 == 1]
for l, b in HOR:
    m = [v for _, v in group(mid_years, b)]
    p = [v for _, v in group(sorted(pres_years), b)]
    o = [v for _, v in group(odd, b)]
    sm, sp, so = describe(m), describe(p), describe(o)
    if sm and sp and so:
        print(f"{l:<9}{sm['mean']:>9.1f}%{sp['mean']:>13.1f}%{so['mean']:>10.1f}%"
              f"{sm['pos']:>9.0f}%{so['pos']:>9.0f}%")

# ── TEST 3: drop the Depression ──────────────────────────────────────────
print("\n\nTEST 3 — does it survive dropping the 1930s and 1940s?")
print(f"{'sample':<16}{'horizon':<8}{'midterm':>10}{'no election':>13}"
      f"{'diff':>9}{'p':>8}{'n':>5}")
print("-" * 69)
for cut, lbl in ((1930, "1930 on (all)"), (1950, "1950 on"), (1970, "1970 on")):
    for l, b in HOR:
        if l != "6m" and cut != 1930:
            continue
        m = [v for y, v in group(mid_years, b) if y >= cut]
        o = [v for y, v in group(no_elec, b) if y >= cut]
        w = welch(m, o)
        sm, so = describe(m), describe(o)
        if w and sm and so:
            print(f"{lbl:<16}{l:<8}{sm['mean']:>9.1f}%{so['mean']:>12.1f}%"
                  f"{w['diff']:>+8.1f}{w['p']:>8.3f}{sm['n']:>5}")

# ── TEST 4: how much of it is just "November is good" ────────────────────
print("\n\nTEST 4 — the seasonal share of the effect")
print("Nov-anchored 6-month windows, every year type pooled, vs the")
print("average 6-month window starting in any other month:")
b = 126
nov_all = [v for _, v in group(list(range(Y0, Y1 + 1)), b)]
anymonth = []
for i in range(0, len(dates) - b, 5):
    if dates[i][5:7] == "11":
        continue
    v = fwd_return(dates, px, i, b)
    if v is not None:
        anymonth.append(v)
sn, sa = describe(nov_all), describe(anymonth)
w = welch(nov_all, anymonth)
print(f"  November start, any year : {sn['mean']:+.1f}%  (n={sn['n']})")
print(f"  any other month          : {sa['mean']:+.1f}%  (n={sa['n']})")
print(f"  seasonal gap             : {w['diff']:+.1f} points  (p={w['p']:.3f})")
m6 = [v for _, v in group(mid_years, b)]
sm = describe(m6)
print(f"\n  post-midterm 6m          : {sm['mean']:+.1f}%")
print(f"  of which seasonal        : {w['diff']:+.1f} points "
      f"({w['diff']/sm['mean']*100:.0f}% of it)")
print(f"  left for the election    : {t1['6m']['diff']:+.1f} points "
      f"(p={t1['6m']['p']:.3f})")

# ── TEST 5: the hit rate, which looked like the strongest claim ──────────
print("\n\nTEST 5 — the 88%-of-the-time claim, against the right baseline")
print("A high hit rate is only interesting if the baseline's is lower.")
print(f"{'horizon':<9}{'midterm % up':>14}{'no-election % up':>18}"
      f"{'n mid':>7}")
print("-" * 49)
for l, b in HOR:
    sm = describe([v for _, v in group(mid_years, b)])
    so = describe([v for _, v in group(no_elec, b)])
    if sm and so:
        print(f"{l:<9}{sm['pos']:>13.0f}%{so['pos']:>17.0f}%{sm['n']:>7}")

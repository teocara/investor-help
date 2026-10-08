"""The midterm event study, and a forward simulation for November 2026."""
import sys
import math
import statistics as st
import datetime as dt

sys.path.insert(0, "research")
from elections import (election_day, midterm_years, presidential_years, load,
                       idx_on_or_after, fwd_return, back_return, describe,
                       welch, bootstrap_ci, TRADING)

SERIES = sys.argv[1] if len(sys.argv) > 1 else "^GSPC"
dates, px = load(SERIES.replace("^", "_"))
if not dates:
    sys.exit(f"no data for {SERIES}")
print(f"series {SERIES}: {dates[0]} -> {dates[-1]}, {len(dates)} sessions\n")

HORIZONS = [("1w", 5), ("1m", 21), ("3m", 63), ("6m", 126), ("12m", 252)]
LOOKBACKS = [("-3m", 63), ("-1m", 21)]

# ── Which elections are in the data ──────────────────────────────────────
mid = []
for y in midterm_years(int(dates[0][:4]), int(dates[-1][:4])):
    d = election_day(y)
    i = idx_on_or_after(dates, d.isoformat())
    if i is None:
        continue
    # Needs a full year of data after it to enter the 12-month column.
    mid.append((y, d, i))
print(f"{len(mid)} midterm elections in range: "
      f"{mid[0][0]}–{mid[-1][0]}\n")

# ── Event table ──────────────────────────────────────────────────────────
print("every midterm, anchored on ELECTION DAY (not on a hindsight low)")
hdr = f"{'year':<6}{'date':<12}" + "".join(f"{l:>8}" for l, _ in LOOKBACKS) \
      + " |" + "".join(f"{l:>8}" for l, _ in HORIZONS)
print(hdr)
print("-" * len(hdr))
rows = {l: [] for l, _ in HORIZONS}
backs = {l: [] for l, _ in LOOKBACKS}
for y, d, i in mid:
    line = f"{y:<6}{d.isoformat():<12}"
    for l, b in LOOKBACKS:
        v = back_return(dates, px, i, b)
        backs[l].append(v)
        line += f"{v:>7.1f}%" if v is not None else f"{'—':>8}"
    line += " |"
    for l, b in HORIZONS:
        v = fwd_return(dates, px, i, b)
        rows[l].append(v)
        line += f"{v:>7.1f}%" if v is not None else f"{'—':>8}"
    print(line)

# ── Baseline: every other trading day, same series ───────────────────────
# The comparison that matters. "Stocks rose 12% after midterms" is only
# interesting if stocks did NOT rise 12% after an arbitrary Tuesday.
# Overlapping windows are used for the baseline, so its standard error is
# understated and the test is therefore CONSERVATIVE against the election
# effect — exactly the direction an honest test should lean.
print("\n\nmidterm windows vs every other day in the same series")
print(f"{'horizon':<9}{'midterm mean':>14}{'95% CI (boot)':>20}"
      f"{'baseline':>11}{'diff':>9}{'p':>8}")
print("-" * 71)
verdicts = []
for l, b in HORIZONS:
    base = []
    for i in range(0, len(dates) - b, 5):     # every 5th day, to decorrelate
        if any(abs(i - mi) < b for _, _, mi in mid):
            continue                          # exclude election windows
        v = fwd_return(dates, px, i, b)
        if v is not None:
            base.append(v)
    s = describe(rows[l])
    bs = describe(base)
    if not s or not bs:
        continue
    ci = bootstrap_ci(rows[l])
    w = welch(rows[l], base)
    ci_s = f"[{ci[0]:+.1f}, {ci[1]:+.1f}]" if ci else "—"
    print(f"{l:<9}{s['mean']:>13.1f}%{ci_s:>20}{bs['mean']:>10.1f}%"
          f"{w['diff']:>+8.1f}{w['p']:>8.3f}")
    verdicts.append((l, w["p"], w["diff"], ci))

# ── Shape, not just the average ──────────────────────────────────────────
print("\n\nthe average hides the spread — this is what 24 draws look like")
print(f"{'horizon':<9}{'median':>9}{'sd':>8}{'worst':>9}{'best':>9}{'% up':>8}")
print("-" * 52)
for l, _ in HORIZONS:
    s = describe(rows[l])
    if s:
        print(f"{l:<9}{s['median']:>8.1f}%{s['sd']:>7.1f}%{s['min']:>8.1f}%"
              f"{s['max']:>8.1f}%{s['pos']:>7.0f}%")

# ── Is it a midterm effect, or the four-year cycle? ───────────────────────
print("\n\nmidterm vs PRESIDENTIAL election, same windows")
print("(if both rally the same, this is not about midterms)")
pres = []
for y in presidential_years(int(dates[0][:4]), int(dates[-1][:4])):
    i = idx_on_or_after(dates, election_day(y).isoformat())
    if i is not None:
        pres.append(i)
print(f"{'horizon':<9}{'midterm':>10}{'presidential':>15}{'diff':>9}{'p':>8}")
print("-" * 51)
for l, b in HORIZONS:
    pv = [fwd_return(dates, px, i, b) for i in pres]
    s, ps = describe(rows[l]), describe(pv)
    w = welch(rows[l], pv)
    if s and ps and w:
        print(f"{l:<9}{s['mean']:>9.1f}%{ps['mean']:>14.1f}%"
              f"{w['diff']:>+8.1f}{w['p']:>8.3f}")

# ── How much data would settle it ────────────────────────────────────────
print("\n\nhow many midterms would be needed to call the 12-month gap real")
s12 = describe(rows["12m"])
base12 = []
for i in range(0, len(dates) - 252, 5):
    if any(abs(i - mi) < 252 for _, _, mi in mid):
        continue
    v = fwd_return(dates, px, i, 252)
    if v is not None:
        base12.append(v)
b12 = describe(base12)
if s12 and b12:
    gap = s12["mean"] - b12["mean"]
    sd = s12["sd"]
    # n for 80% power at 5% two-sided: ~ (2.8 * sd / gap)^2
    need = (2.8 * sd / gap) ** 2 if gap else float("inf")
    print(f"  observed gap        {gap:+.1f} points")
    print(f"  spread of outcomes  {sd:.1f} points")
    print(f"  midterms needed     {need:.0f}  "
          f"(= {need*4:.0f} years of elections)")
    print(f"  we have             {s12['n']}")

# ── Forward simulation for 2026 ──────────────────────────────────────────
print("\n\n" + "=" * 71)
nxt = election_day(2026)
print(f"SIMULATION — midterm {nxt.isoformat()}, "
      f"{(nxt - dt.date.today()).days} days away")
print("=" * 71)
print("""
Two distributions, drawn the same way. The first resamples the 12-month
returns that FOLLOWED each historical midterm. The second resamples
12-month returns from every other period in the series. If the midterm
story carries information, the first should sit visibly to the right of
the second. Read the OVERLAP, not the two averages.
""")

import random
rng = random.Random(11)


def simulate(pool, reps=50000):
    pool = [x for x in pool if x is not None]
    return sorted(rng.choice(pool) for _ in range(reps))


def pct(s, q):
    return s[int(q * (len(s) - 1))]


sim_mid = simulate(rows["12m"])
sim_base = simulate(base12)
print(f"{'':<22}{'5%':>9}{'25%':>9}{'median':>9}{'75%':>9}{'95%':>9}"
      f"{'P(up)':>8}")
print("-" * 75)
for lbl, s in (("after a midterm", sim_mid), ("any other period", sim_base)):
    up = sum(1 for x in s if x > 0) / len(s) * 100
    print(f"{lbl:<22}{pct(s,.05):>8.1f}%{pct(s,.25):>8.1f}%"
          f"{pct(s,.50):>8.1f}%{pct(s,.75):>8.1f}%{pct(s,.95):>8.1f}%"
          f"{up:>7.0f}%")

# How often does the midterm draw actually beat the baseline draw?
wins = sum(1 for a, b in zip(sim_mid, sorted(sim_base, key=lambda _: rng.random()))
           if a > b)
pair = [1 if rng.choice(rows["12m"]) > rng.choice(base12) else 0
        for _ in range(50000)]
print(f"\nPick one year at random from each pool: the post-midterm year is "
      f"higher {sum(pair)/len(pair)*100:.0f}% of the time.")
print("50% would mean the midterm label carries no information at all.")

# Translate to a portfolio, since that is the only form the answer is
# actually usable in.
print("\nwhat that means for $100,000 held for the twelve months after:")
for lbl, s in (("after a midterm", sim_mid), ("any other period", sim_base)):
    print(f"  {lbl:<20}median ${100000*(1+pct(s,.50)/100):>10,.0f}   "
          f"90% range ${100000*(1+pct(s,.05)/100):>10,.0f} – "
          f"${100000*(1+pct(s,.95)/100):>9,.0f}")

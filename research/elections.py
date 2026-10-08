"""What US midterm elections have actually done to the stock market.

The folklore is specific and widely repeated: stocks are weak into a
midterm, then rally hard afterwards, and the twelve months following a
midterm are the strongest of the four-year cycle. The claim is testable,
so it gets tested rather than repeated.

THE PROBLEM WITH THIS QUESTION, STATED FIRST

Midterms happen every four years. The index reaches 1927, so the sample
is 24 events. That is the binding constraint on everything below, and it
is worth seeing the arithmetic before the results:

  annual volatility of the index          ~ 18%
  standard error of a mean over 24 events = 18 / sqrt(24) = 3.7 points

So a measured "post-midterm twelve months average +12%" carries a 95%
interval of roughly +5% to +19%. The unconditional average is about +8%.
An interval that wide cannot separate "midterms matter" from "stocks go
up." To call an effect real at this sample size it has to be enormous.

Three further hazards, all of which inflate an effect that is not there:

  1. OVERLAP. Midterms sit inside the presidential cycle, so the
     post-midterm year is also the pre-presidential-election year. Any
     "midterm effect" measured naively is partly a cycle effect, and the
     two cannot be separated with 24 observations.

  2. CHOICE OF ANCHOR. Measuring from a midterm-year LOW to the following
     year flatters the result enormously, because the low is picked with
     hindsight. Every window here is anchored on the ELECTION DATE, which
     was knowable in advance.

  3. EVENT CLUSTERING. 2002 lands three weeks from the dot-com bottom,
     2022 three weeks from that bear market's bottom, 2018 three weeks
     before a 19% quarter. A handful of events drive the average, so the
     median and the spread are reported alongside it, not instead of it.

Price index, not total return: dividends are missing, and they were worth
5-6% a year in the early decades. That biases every window DOWN by the
same amount, so it cancels in the election-versus-baseline comparison,
which is the only comparison this file draws a conclusion from.
"""
import json
import math
import statistics as st
from pathlib import Path

DATA = Path("public/growth-history")
TRADING = 252


# ── Election dates ───────────────────────────────────────────────────────
def election_day(year):
    """US federal election day: the first Tuesday AFTER the first Monday
    in November. Not simply the first Tuesday — in a year where 1 Nov is
    a Tuesday the election is on the 8th."""
    import datetime as dt
    d = dt.date(year, 11, 1)
    while d.weekday() != 0:              # 0 = Monday
        d += dt.timedelta(days=1)
    return d + dt.timedelta(days=1)


def midterm_years(lo, hi):
    """Even years not divisible by four: the off-presidential elections."""
    return [y for y in range(lo, hi + 1) if y % 2 == 0 and y % 4 != 0]


def presidential_years(lo, hi):
    return [y for y in range(lo, hi + 1) if y % 4 == 0]


# ── Data ─────────────────────────────────────────────────────────────────
def load(name):
    p = DATA / f"{name}.json"
    if not p.exists():
        return [], {}
    rows = json.load(open(p))
    series = [(r["time"], r["close"]) for r in rows if r.get("close")]
    return [d for d, _ in series], {d: c for d, c in series}


def idx_on_or_after(dates, target):
    """First trading day on or after a calendar date. Returns None past the
    end of the series, so a window that runs off the data is dropped rather
    than silently truncated to a shorter horizon."""
    lo, hi = 0, len(dates)
    while lo < hi:
        mid = (lo + hi) // 2
        if dates[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo if lo < len(dates) else None


def fwd_return(dates, px, i, bars):
    j = i + bars
    if i is None or j >= len(dates):
        return None
    a, b = px[dates[i]], px[dates[j]]
    return (b / a - 1) * 100 if a and b and a > 0 else None


def back_return(dates, px, i, bars):
    j = i - bars
    if i is None or j < 0:
        return None
    a, b = px[dates[j]], px[dates[i]]
    return (b / a - 1) * 100 if a and b and a > 0 else None


# ── Statistics ───────────────────────────────────────────────────────────
def describe(xs):
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if n < 2:
        return None
    m = st.mean(xs)
    sd = st.stdev(xs)
    se = sd / math.sqrt(n)
    return {"n": n, "mean": m, "median": st.median(xs), "sd": sd, "se": se,
            "lo": m - 1.96 * se, "hi": m + 1.96 * se,
            "pos": sum(1 for x in xs if x > 0) / n * 100,
            "min": min(xs), "max": max(xs), "xs": xs}


def welch(a, b):
    """Welch t-test: unequal variances, which is the realistic assumption
    when one group is 24 election windows and the other is 400 baseline
    windows from the same series."""
    a = [x for x in a if x is not None]
    b = [x for x in b if x is not None]
    if len(a) < 2 or len(b) < 2:
        return None
    ma, mb = st.mean(a), st.mean(b)
    va, vb = st.variance(a), st.variance(b)
    na, nb = len(a), len(b)
    se = math.sqrt(va / na + vb / nb)
    if se == 0:
        return None
    t = (ma - mb) / se
    df = (va / na + vb / nb) ** 2 / (
        (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    # Normal approximation to the two-sided p-value; df is comfortably
    # above 20 in every comparison here, where the two agree closely.
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))
    return {"t": t, "df": df, "p": p, "diff": ma - mb, "se": se}


def bootstrap_ci(xs, reps=20000, seed=7):
    """Percentile bootstrap. With n=24 the normal interval leans on a
    symmetry the data does not have — 2002 and 2022 are both far out in
    one tail — so the empirical distribution is resampled instead."""
    import random
    xs = [x for x in xs if x is not None]
    if len(xs) < 3:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(reps):
        means.append(st.mean(rng.choices(xs, k=len(xs))))
    means.sort()
    return means[int(0.025 * reps)], means[int(0.975 * reps)]

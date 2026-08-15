"""Where does professional trend-following actually get its Sharpe?

The single-instrument test says trend filters beat buy & hold on CAGR only
~14% of the time. Yet CTAs run trend for decades at Sharpe ~0.7-1.0. The
usual explanation is that the edge is not in the signal, it is in applying
a mediocre signal across many weakly-correlated markets and letting the
diversification do the work.

That is testable here: run the same rule on one instrument vs on an
equal-weight basket of many, and compare Sharpe.
"""
import json, glob, math, os, random, statistics as st

BARS_YR, COST = 52, 0.0005

def sma(v, n):
    o, s = [None]*len(v), 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n: s -= v[i-n]
        if i >= n-1: o[i] = s/n
    return o

def rvol(v, n=13):
    o = [None]*len(v)
    lr = [0.0]+[math.log(v[i]/v[i-1]) if v[i-1] > 0 else 0.0 for i in range(1, len(v))]
    for i in range(n, len(v)):
        w = lr[i-n+1:i+1]; m = sum(w)/n
        o[i] = math.sqrt(max(1e-12, sum((x-m)**2 for x in w)/(n-1))*BARS_YR)
    return o

LB = [max(2, round(d*BARS_YR/252)) for d in (20, 60, 120, 250)]

def load():
    """Weekly closes keyed by date, for instruments with a long common span."""
    out = {}
    for f in sorted(glob.glob("/home/user/investor-help/public/ohlcv-long/*.json")):
        t = os.path.basename(f)[:-5]
        try: rows = json.load(open(f))
        except Exception: continue
        m = {r["time"]: r["close"] for r in rows if r.get("close")}
        if len(m) >= 700: out[t] = m
    return out

S = load()
# common calendar: dates present for at least 80% of instruments
from collections import Counter
cnt = Counter()
for m in S.values():
    for d in m: cnt[d] += 1
need = len(S)*0.8
dates = sorted(d for d, c in cnt.items() if c >= need)
S = {t: m for t, m in S.items() if sum(1 for d in dates if d in m) > len(dates)*0.95}
print(f"{len(S)} instruments on a {len(dates)}-bar common calendar "
      f"({dates[0]} -> {dates[-1]}, {len(dates)/BARS_YR:.1f} yrs)")

def series(t):
    m = S[t]; out = []; last = None
    for d in dates:
        v = m.get(d, last)
        if v: last = v
        out.append(last if last else 0.0)
    return out

PX = {t: series(t) for t in S}
WARM = max(LB)+5

def sig_weights(c):
    mas = {k: sma(c, k) for k in LB}
    vol = rvol(c)
    w = []
    for i in range(len(c)):
        f = sum(1.0 if (mas[k][i] is not None and c[i] > mas[k][i]) else 0.0 for k in LB)/len(LB)
        v = vol[i]
        w.append(min(1.0, f*(min(1.0, 0.15/v) if v and v > 0 else 0.0)))
    return w

W = {t: sig_weights(PX[t]) for t in S}

def basket(tickers, timed):
    """Equal-weight across tickers, rebalanced each bar."""
    eq = 1.0; curve = [1.0]; prev = {t: 0.0 for t in tickers}
    n = len(tickers)
    for i in range(WARM, len(dates)-1):
        tot = 0.0; turn = 0.0
        for t in tickers:
            c = PX[t]
            if c[i] <= 0 or c[i+1] <= 0: continue
            wt = (W[t][i] if timed else 1.0)/n
            turn += abs(wt-prev[t]); prev[t] = wt
            tot += wt*(c[i+1]/c[i]-1)
        eq *= (1-COST*turn*2)
        eq *= (1+tot)
        curve.append(eq)
    return curve

def stats(v):
    yrs = len(v)/BARS_YR; mult = v[-1]/v[0]
    peak, mdd = v[0], 0.0
    for x in v:
        peak = max(peak, x); mdd = min(mdd, x/peak-1)
    dr = [v[i]/v[i-1]-1 for i in range(1, len(v))]
    mu = sum(dr)/len(dr)
    sd = math.sqrt(max(1e-12, sum((x-mu)**2 for x in dr)/(len(dr)-1)))
    cagr = (mult**(1/yrs)-1)*100
    return dict(cagr=cagr, mdd=mdd*100, sharpe=(mu*BARS_YR)/(sd*math.sqrt(BARS_YR)),
                calmar=cagr/abs(mdd*100) if mdd else 0)

random.seed(7)
alls = sorted(S)
print(f"\n{'basket size':<14}{'timed Sharpe':>14}{'B&H Sharpe':>13}{'timed CAGR':>13}"
      f"{'timed MaxDD':>14}{'timed Calmar':>14}")
print("-"*82)
for k in (1, 3, 10, 30, 100, len(alls)):
    sh_t, sh_b, cg, dd, cal = [], [], [], [], []
    trials = 30 if k < len(alls) else 1
    for _ in range(trials):
        pick = alls if k == len(alls) else random.sample(alls, k)
        t = stats(basket(pick, True)); b = stats(basket(pick, False))
        sh_t.append(t['sharpe']); sh_b.append(b['sharpe'])
        cg.append(t['cagr']); dd.append(t['mdd']); cal.append(t['calmar'])
    print(f"{k:<14}{st.median(sh_t):>14.2f}{st.median(sh_b):>13.2f}"
          f"{st.median(cg):>12.1f}%{st.median(dd):>13.1f}%{st.median(cal):>14.2f}")
print("\n(30 random baskets per size; last row is all instruments)")

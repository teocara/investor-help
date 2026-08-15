"""2x vs 3x leveraged Nasdaq, and what Danish taxation does to both.

Two separate questions:

1. LEVERAGE. Volatility decay scales as (L^2 - L)/2 * sigma^2, so it is not
   linear in leverage: 2x gives up 1*sigma^2 a year, 3x gives up 3*sigma^2.
   Going from 2x to 3x buys 50% more exposure for 3x the decay.

2. DANISH TAX. Denmark taxes most foreign ETFs under lagerprincippet
   (mark-to-market): you owe tax on unrealized gains every year, whether or
   not you sell. That removes the deferral advantage buy-and-hold enjoys in
   a realization-based system, which changes the passive-vs-active trade-off.
"""
import json, math

D = json.load(open("/home/user/investor-help/public/study/leveraged.json"))
S = {k: {r["t"]: r["c"] for r in v["rows"]} for k, v in D.items()}

def common(*ks):
    s = set(S[ks[0]])
    for k in ks[1:]:
        s &= set(S[k])
    return sorted(s)

def stats(vals, dates):
    yrs = len(vals) / 252
    mult = vals[-1] / vals[0]
    peak, mdd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    dr = [vals[i]/vals[i-1]-1 for i in range(1, len(vals))]
    mu = sum(dr)/len(dr)
    sd = math.sqrt(sum((x-mu)**2 for x in dr)/(len(dr)-1))
    cagr = (mult**(1/yrs)-1)*100 if mult > 0 else float('nan')
    return dict(mult=mult, cagr=cagr, mdd=mdd*100, yrs=yrs,
                sharpe=(mu*252)/(sd*math.sqrt(252)) if sd else 0,
                calmar=cagr/abs(mdd*100) if mdd else 0)

def sigma_of(closes):
    lr = [math.log(closes[i]/closes[i-1]) for i in range(1, len(closes))]
    m = sum(lr)/len(lr)
    return math.sqrt(sum((x-m)**2 for x in lr)/(len(lr)-1)*252)

def decompose(base, lev, L, label):
    """Same decomposition the dashboard does: reference = base^L."""
    n = len(base); yrs = n/252
    g_base = base[-1]/base[0]
    ref = g_base**L
    dec = 1.0
    for i in range(1, n):
        dec *= (1 + L*(base[i]/base[i-1]-1))
    act = lev[-1]/lev[0]
    d = lambda a, b: ((a/b)**(1/yrs)-1)*100
    sig = sigma_of(base)
    theory = -(L*L - L)/2 * sig*sig * 100
    print(f"  {label:<26}{ref:>12.1f}x{dec:>11.1f}x{act:>10.1f}x"
          f"{d(dec,ref):>9.2f}{theory:>9.2f}{d(act,dec):>9.2f}{d(act,ref):>9.2f}")
    return d(dec, ref), d(act, dec), d(act, ref)

# ── 1. actual funds, common window ──────────────────────────────────────
print("="*100)
print("ACTUAL FUNDS — QQQ / QLD (2x) / TQQQ (3x), common window")
ds = common("QQQ", "QLD", "TQQQ")
q = [S["QQQ"][d] for d in ds]; q2 = [S["QLD"][d] for d in ds]; q3 = [S["TQQQ"][d] for d in ds]
print(f"{ds[0]} -> {ds[-1]}   {len(ds)/252:.1f} yrs   QQQ sigma {sigma_of(q)*100:.1f}%\n")
print(f"  {'':<26}{'multiple':>10}{'CAGR':>9}{'MaxDD':>10}{'Sharpe':>9}{'Calmar':>9}")
for nm, v in [("QQQ 1x", q), ("QLD 2x", q2), ("TQQQ 3x", q3)]:
    s = stats(v, ds)
    print(f"  {nm:<26}{s['mult']:>9.1f}x{s['cagr']:>8.1f}%{s['mdd']:>9.1f}%{s['sharpe']:>9.2f}{s['calmar']:>9.2f}")

print("\n  cost decomposition (annualized ratio drag, pts/yr)")
print(f"  {'':<26}{'reference':>12}{'no-fee':>11}{'actual':>10}{'decay':>9}{'theory':>9}{'fees':>9}{'total':>9}")
decompose(q, q2, 2, "QLD 2x")
decompose(q, q3, 3, "TQQQ 3x")

# ── 2. QLD's longer history: includes the GFC ───────────────────────────
print("\n" + "="*100)
print("QLD 2x BACK TO 2006 — includes the global financial crisis")
ds2 = common("QQQ", "QLD")
qa = [S["QQQ"][d] for d in ds2]; qb = [S["QLD"][d] for d in ds2]
print(f"{ds2[0]} -> {ds2[-1]}   {len(ds2)/252:.1f} yrs\n")
print(f"  {'':<26}{'multiple':>10}{'CAGR':>9}{'MaxDD':>10}{'Sharpe':>9}{'Calmar':>9}")
for nm, v in [("QQQ 1x", qa), ("QLD 2x", qb)]:
    s = stats(v, ds2)
    print(f"  {nm:<26}{s['mult']:>9.1f}x{s['cagr']:>8.1f}%{s['mdd']:>9.1f}%{s['sharpe']:>9.2f}{s['calmar']:>9.2f}")
print("\n  cost decomposition")
print(f"  {'':<26}{'reference':>12}{'no-fee':>11}{'actual':>10}{'decay':>9}{'theory':>9}{'fees':>9}{'total':>9}")
decompose(qa, qb, 2, "QLD 2x (2006-2026)")

# ── 3. synthetic sweep over leverage, full cycle from 1999 ──────────────
print("\n" + "="*100)
print("SYNTHETIC LEVERAGE SWEEP 1999-2026 (full cycle incl. dot-com)")
RATES = {1999:4.64,2000:5.82,2001:3.39,2002:1.60,2003:1.01,2004:1.37,2005:3.15,
         2006:4.73,2007:4.36,2008:1.37,2009:0.15,2010:0.14,2011:0.05,2012:0.09,
         2013:0.06,2014:0.03,2015:0.05,2016:0.32,2017:0.93,2018:1.94,2019:2.06,
         2020:0.37,2021:0.04,2022:2.02,2023:5.07,2024:5.15,2025:4.20,2026:3.80}

def synth(L, dts, er, spread=0.0040, extra=0.0018):
    out = [100.0]
    for i in range(1, len(dts)):
        r = S["QQQ"][dts[i]]/S["QQQ"][dts[i-1]] - 1
        rf = RATES.get(int(dts[i][:4]), 3.0)/100
        cost = (er + abs(L-1)*(rf+spread) + extra)/252
        out.append(out[-1]*(1 + L*r - cost))
    return out

full = sorted(S["QQQ"])
def sma(v, n):
    o, s = [None]*len(v), 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n: s -= v[i-n]
        if i >= n-1: o[i] = s/n
    return o
def rvol(v, n=20):
    o = [None]*len(v)
    lr = [0.0]+[math.log(v[i]/v[i-1]) for i in range(1, len(v))]
    for i in range(n, len(v)):
        w = lr[i-n+1:i+1]; m = sum(w)/n
        o[i] = math.sqrt(sum((x-m)**2 for x in w)/(n-1)*252)
    return o

qv = [S["QQQ"][d] for d in full]
MA200, VOL = sma(qv, 200), rvol(qv, 20)

def run(L, er, timed, volmax=0.35, cost=0.0005):
    lev = synth(L, full, er)
    eq, on = 1.0, False
    curve = [1.0]
    for i in range(250, len(full)-1):
        want = True
        if timed:
            want = MA200[i] is not None and qv[i] > MA200[i]
            if want and volmax and (VOL[i] is None or VOL[i] >= volmax): want = False
        if want != on:
            eq *= (1-cost); on = want
        if want: eq *= lev[i+1]/lev[i]
        curve.append(eq)
    return curve

print(f"\n  {'':<16}{'BUY & HOLD':>32}   |{'200d + vol<35% TIMED':>32}")
print(f"  {'leverage':<16}{'multiple':>11}{'CAGR':>9}{'MaxDD':>11}   |{'multiple':>11}{'CAGR':>9}{'MaxDD':>11}")
for L, er in [(1,0.0020),(1.5,0.0075),(2,0.0060),(2.5,0.0085),(3,0.0095),(4,0.0110)]:
    bh = stats(run(L, er, False), full)
    tm = stats(run(L, er, True), full)
    print(f"  {str(L)+'x':<16}{bh['mult']:>10.2f}x{bh['cagr']:>8.1f}%{bh['mdd']:>10.1f}%   |"
          f"{tm['mult']:>10.2f}x{tm['cagr']:>8.1f}%{tm['mdd']:>10.1f}%")
print("\n  (2x uses LQQ's 0.60% TER, 3x uses TQQQ's 0.95%)")

# ── 4. Danish taxation: realization vs lagerprincippet ──────────────────
print("\n" + "="*100)
print("DANISH TAX — realization vs lagerprincippet (annual mark-to-market)")
print("Lagerbeskatning taxes unrealized gains every year, so buy & hold loses")
print("the deferral advantage it has under a realization-based system.\n")

def tax_lager(curve, dates, rate):
    """Mark to market at each calendar year end. Gains are taxed whether or
    not anything was sold; losses carry forward against future gains."""
    n = min(len(curve), len(dates))
    out = [curve[0]]
    carry = 0.0            # accumulated unused losses
    mark = curve[0]        # last year's taxed value
    scale = 1.0            # cumulative haircut from tax already paid
    for i in range(1, n):
        v = curve[i] * scale
        last_bar_of_year = (i == n-1) or (dates[i][:4] != dates[i+1][:4])
        if last_bar_of_year:
            gain = v - mark
            if gain > 0:
                taxable = max(0.0, gain - carry)
                carry = max(0.0, carry - gain)
                t = taxable * rate
                if t > 0 and v > 0:
                    scale *= (v - t) / v
                    v -= t
            else:
                carry += -gain
            mark = v
        out.append(v)
    return out

def tax_realized(curve, rate):
    """Single realization at the end — the buy & hold base case elsewhere."""
    g = curve[-1]-curve[0]
    return curve[:-1]+[curve[-1]-max(0.0, g)*rate]

RATE = 0.42     # Danish kapitalindkomst, typical marginal rate
dates_run = full[250:]
for L, er, nm in [(1,0.0020,"QQQ 1x"),(2,0.0060,"LQQ-like 2x"),(3,0.0095,"TQQQ-like 3x")]:
    bh = run(L, er, False)
    tm = run(L, er, True)
    n = min(len(bh), len(dates_run))
    rows = []
    for label, c in [("buy & hold", bh), ("200d+vol timed", tm)]:
        c = c[:n]
        pre = stats(c, dates_run)
        lager = stats(tax_lager(c, dates_run[:n], RATE), dates_run)
        real = stats(tax_realized(c, RATE), dates_run)
        rows.append((label, pre, lager, real))
    print(f"  {nm}")
    print(f"    {'':<18}{'pre-tax':>10}{'lager 42%':>12}{'realized 42%':>14}{'lager cost':>12}")
    for label, pre, lager, real in rows:
        print(f"    {label:<18}{pre['cagr']:>9.1f}%{lager['cagr']:>11.1f}%{real['cagr']:>13.1f}%"
              f"{lager['cagr']-real['cagr']:>11.1f}p")
    print()

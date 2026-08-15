"""LQQ (Amundi Nasdaq-100 Daily 2x Leveraged UCITS, Paris) vs TQQQ, for a
Danish investor.

Everything is expressed in EUR, because that is what a DKK investor actually
experiences: the krone is pegged to the euro inside a +/-2.25% band and in
practice trades within a fraction of a percent of 7.46 DKK/EUR, so EUR returns
are DKK returns to a very good approximation. USD-quoted funds are converted
at spot so the comparison is like for like.
"""
import json, math

D = json.load(open("/home/user/investor-help/public/study/leveraged.json"))
S = {k: {r["t"]: r["c"] for r in v["rows"]} for k, v in D.items()}
FX = S["EURUSD=X"]            # USD per 1 EUR

def to_eur(series):
    out = {}
    for d, v in series.items():
        f = FX.get(d)
        if f:
            out[d] = v / f
    return out

QQQ_E, TQQQ_E, QLD_E = to_eur(S["QQQ"]), to_eur(S["TQQQ"]), to_eur(S["QLD"])
LQQ = S["LQQ.PA"]

def common(*ds):
    s = set(ds[0])
    for x in ds[1:]:
        s &= set(x)
    return sorted(s)

def sigma_of(c):
    lr = [math.log(c[i]/c[i-1]) for i in range(1, len(c))]
    m = sum(lr)/len(lr)
    return math.sqrt(sum((x-m)**2 for x in lr)/(len(lr)-1)*252)

def stats(v):
    yrs = len(v)/252
    mult = v[-1]/v[0]
    peak, mdd = v[0], 0.0
    for x in v:
        peak = max(peak, x); mdd = min(mdd, x/peak-1)
    dr = [v[i]/v[i-1]-1 for i in range(1, len(v))]
    mu = sum(dr)/len(dr)
    sd = math.sqrt(sum((x-mu)**2 for x in dr)/(len(dr)-1))
    cagr = (mult**(1/yrs)-1)*100 if mult > 0 else float('nan')
    return dict(mult=mult, cagr=cagr, mdd=mdd*100,
                sharpe=(mu*252)/(sd*math.sqrt(252)) if sd else 0,
                calmar=cagr/abs(mdd*100) if mdd else 0, yrs=yrs)

def beta(a, b):
    ra = [a[i]/a[i-1]-1 for i in range(1, len(a))]
    rb = [b[i]/b[i-1]-1 for i in range(1, len(b))]
    ma, mb = sum(ra)/len(ra), sum(rb)/len(rb)
    cov = sum((x-ma)*(y-mb) for x, y in zip(ra, rb))/(len(ra)-1)
    var = sum((y-mb)**2 for y in rb)/(len(rb)-1)
    return cov/var

def decompose(base, lev, L, label):
    n = len(base); yrs = n/252
    ref = (base[-1]/base[0])**L
    dec = 1.0
    for i in range(1, n):
        dec *= (1 + L*(base[i]/base[i-1]-1))
    act = lev[-1]/lev[0]
    d = lambda a, b: ((a/b)**(1/yrs)-1)*100
    sig = sigma_of(base)
    theory = -(L*L-L)/2*sig*sig*100
    print(f"  {label:<24}{ref:>11.1f}x{dec:>10.1f}x{act:>9.1f}x"
          f"{d(dec,ref):>9.2f}{theory:>9.2f}{d(act,dec):>9.2f}{d(act,ref):>9.2f}")

# ── does LQQ actually deliver 2x? ───────────────────────────────────────
ds = common(QQQ_E, LQQ)
qe = [QQQ_E[d] for d in ds]; lq = [LQQ[d] for d in ds]
print("="*98)
print(f"LQQ.PA vs Nasdaq-100 in EUR   {ds[0]} -> {ds[-1]}   {len(ds)/252:.1f} yrs")
print(f"  realized daily beta vs QQQ(EUR): {beta(lq, qe):+.3f}   (target +2.00)")
print(f"  QQQ(EUR) realized volatility   : {sigma_of(qe)*100:.1f}%")
print(f"  QQQ(USD) realized volatility   : {sigma_of([S['QQQ'][d] for d in ds])*100:.1f}%")

# ── head to head, EUR, common window with TQQQ ──────────────────────────
ds2 = common(QQQ_E, LQQ, TQQQ_E, QLD_E)
print("\n" + "="*98)
print(f"HEAD TO HEAD IN EUR   {ds2[0]} -> {ds2[-1]}   {len(ds2)/252:.1f} yrs")
print(f"\n  {'':<24}{'multiple':>10}{'CAGR':>9}{'MaxDD':>10}{'Sharpe':>9}{'Calmar':>9}")
rows = [("QQQ 1x (EUR)", [QQQ_E[d] for d in ds2]),
        ("LQQ 2x UCITS (EUR)", [LQQ[d] for d in ds2]),
        ("QLD 2x US (EUR)", [QLD_E[d] for d in ds2]),
        ("TQQQ 3x US (EUR)", [TQQQ_E[d] for d in ds2])]
for nm, v in rows:
    s = stats(v)
    print(f"  {nm:<24}{s['mult']:>9.1f}x{s['cagr']:>8.1f}%{s['mdd']:>9.1f}%{s['sharpe']:>9.2f}{s['calmar']:>9.2f}")

print("\n  cost decomposition in EUR (annualized ratio drag, pts/yr)")
print(f"  {'':<24}{'reference':>11}{'no-fee':>10}{'actual':>9}{'decay':>9}{'theory':>9}{'fees':>9}{'total':>9}")
qe2 = [QQQ_E[d] for d in ds2]
decompose(qe2, [LQQ[d] for d in ds2], 2, "LQQ 2x UCITS")
decompose(qe2, [QLD_E[d] for d in ds2], 2, "QLD 2x US")
decompose(qe2, [TQQQ_E[d] for d in ds2], 3, "TQQQ 3x US")

# ── strategy on both, EUR ───────────────────────────────────────────────
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

MA, VOL = sma(qe2, 200), rvol(qe2, 20)
def timed(levv, volmax=0.35, cost=0.0005):
    eq, on = 1.0, False; c = [1.0]
    for i in range(250, len(ds2)-1):
        want = MA[i] is not None and qe2[i] > MA[i]
        if want and volmax and (VOL[i] is None or VOL[i] >= volmax): want = False
        if want != on: eq *= (1-cost); on = want
        if want: eq *= levv[i+1]/levv[i]
        c.append(eq)
    return c

print(f"\n  200d + vol<35% timing, executed on each fund (EUR)")
print(f"  {'':<24}{'multiple':>10}{'CAGR':>9}{'MaxDD':>10}{'Sharpe':>9}{'Calmar':>9}")
for nm, v in rows:
    s = stats(timed(v))
    print(f"  {nm:<24}{s['mult']:>9.1f}x{s['cagr']:>8.1f}%{s['mdd']:>9.1f}%{s['sharpe']:>9.2f}{s['calmar']:>9.2f}")

# ── Danish tax ──────────────────────────────────────────────────────────
def tax_lager(curve, dates, rate):
    n = min(len(curve), len(dates))
    out = [curve[0]]; carry = 0.0; mark = curve[0]; scale = 1.0
    for i in range(1, n):
        v = curve[i]*scale
        if (i == n-1) or (dates[i][:4] != dates[i+1][:4]):
            gain = v-mark
            if gain > 0:
                taxable = max(0.0, gain-carry); carry = max(0.0, carry-gain)
                t = taxable*rate
                if t > 0 and v > 0:
                    scale *= (v-t)/v; v -= t
            else:
                carry += -gain
            mark = v
        out.append(v)
    return out

print("\n" + "="*98)
print("DANISH TAX — lagerprincippet (annual mark-to-market on unrealized gains)")
print("Applies to foreign investment companies regardless of whether you sell.\n")
dts = ds2[250:]
print(f"  {'':<24}{'pre-tax':>10}{'27% aktie':>12}{'42% kapital':>13}{'17% ASK':>10}")
for nm, v in rows:
    for lbl, c in [("  buy & hold", v[250:]), ("  200d+vol timed", timed(v))]:
        c = c[:len(dts)]
        pre = stats(c)['cagr']
        a27 = stats(tax_lager(c, dts, 0.27))['cagr']
        k42 = stats(tax_lager(c, dts, 0.42))['cagr']
        ask = stats(tax_lager(c, dts, 0.17))['cagr']
        tag = (nm + lbl.strip()) if False else f"{nm.split(' (')[0][:14]:<14}{lbl.strip()[:9]:<10}"
        print(f"  {tag}{pre:>9.1f}%{a27:>11.1f}%{k42:>12.1f}%{ask:>9.1f}%")

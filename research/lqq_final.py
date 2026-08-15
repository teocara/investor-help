"""LQQ vs TQQQ for a Danish investor — consolidated.

Handles three things the naive comparison gets wrong:
  1. LQQ.PA carries an unadjusted 204.8:1 split (repaired in splitfix.py).
  2. Paris closes 4.5h before New York, so a signal taken from the US close
     cannot be executed in Paris until the following day. Modelled explicitly.
  3. Denmark taxes foreign investment companies on unrealized gains annually
     (lagerprincippet), which removes buy & hold's deferral advantage.
"""
import json, math

D = json.load(open("/home/user/investor-help/public/study/leveraged.json"))
S = {k: {r["t"]: r["c"] for r in v["rows"]} for k, v in D.items()}
FX = S["EURUSD=X"]
eur = lambda m: {d: v/FX[d] for d, v in m.items() if d in FX}
QQQ_E, TQQQ_E, QLD_E = eur(S["QQQ"]), eur(S["TQQQ"]), eur(S["QLD"])
LQQ = S["LQQ.PA"]

def stats(v):
    yrs = len(v)/252; mult = v[-1]/v[0]
    peak, mdd = v[0], 0.0
    for x in v:
        peak = max(peak, x); mdd = min(mdd, x/peak-1)
    dr = [v[i]/v[i-1]-1 for i in range(1, len(v))]
    mu = sum(dr)/len(dr); sd = math.sqrt(sum((x-mu)**2 for x in dr)/(len(dr)-1))
    cagr = (mult**(1/yrs)-1)*100 if mult > 0 else float('nan')
    return dict(mult=mult, cagr=cagr, mdd=mdd*100,
                sharpe=(mu*252)/(sd*math.sqrt(252)) if sd else 0,
                calmar=cagr/abs(mdd*100) if mdd else 0)

def sma(v, n):
    o, s = [None]*len(v), 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n: s -= v[i-n]
        if i >= n-1: o[i] = s/n
    return o
def rvol(v, n=20):
    o = [None]*len(v); lr = [0.0]+[math.log(v[i]/v[i-1]) for i in range(1, len(v))]
    for i in range(n, len(v)):
        w = lr[i-n+1:i+1]; m = sum(w)/n
        o[i] = math.sqrt(sum((x-m)**2 for x in w)/(n-1)*252)
    return o

ds = sorted(set(QQQ_E) & set(LQQ) & set(TQQQ_E) & set(QLD_E))
q = [QQQ_E[d] for d in ds]
MA, VOL = sma(q, 200), rvol(q, 20)

def timed(lev, lag=0, volmax=0.35, cost=0.0005):
    """lag=1 means the signal from bar i is only executed from bar i+1,
    which is the reality for a Paris listing signalled off the US close."""
    eq, on = 1.0, False; c = [1.0]
    for i in range(250, len(ds)-1-lag):
        j = i  # signal bar
        want = MA[j] is not None and q[j] > MA[j]
        if want and volmax and (VOL[j] is None or VOL[j] >= volmax): want = False
        if want != on: eq *= (1-cost); on = want
        k = i+lag
        if want: eq *= lev[k+1]/lev[k]
        c.append(eq)
    return c

def tax_lager(curve, dates, rate):
    n = min(len(curve), len(dates)); out = [curve[0]]
    carry = 0.0; mark = curve[0]; scale = 1.0
    for i in range(1, n):
        v = curve[i]*scale
        if (i == n-1) or (dates[i][:4] != dates[i+1][:4]):
            gain = v-mark
            if gain > 0:
                taxable = max(0.0, gain-carry); carry = max(0.0, carry-gain)
                t = taxable*rate
                if t > 0 and v > 0: scale *= (v-t)/v; v -= t
            else: carry += -gain
            mark = v
        out.append(v)
    return out

FUNDS = [("QQQ 1× (EUR)", q, 0),
         ("LQQ 2× UCITS", [LQQ[d] for d in ds], 1),      # Paris: 1-day lag
         ("QLD 2× US", [QLD_E[d] for d in ds], 0),
         ("TQQQ 3× US", [TQQQ_E[d] for d in ds], 0)]

print("="*96)
print(f"BUY & HOLD, EUR   {ds[0]} -> {ds[-1]}   {len(ds)/252:.1f} yrs")
print(f"  {'':<20}{'multiple':>10}{'CAGR':>9}{'MaxDD':>10}{'Sharpe':>9}{'Calmar':>9}")
for nm, v, _ in FUNDS:
    s = stats(v); print(f"  {nm:<20}{s['mult']:>9.1f}x{s['cagr']:>8.1f}%{s['mdd']:>9.1f}%{s['sharpe']:>9.2f}{s['calmar']:>9.2f}")

print("\n" + "="*96)
print("200d + vol<35% TIMED — effect of the Paris execution lag")
print(f"  {'':<20}{'lag':>5}{'multiple':>11}{'CAGR':>9}{'MaxDD':>10}{'Sharpe':>9}{'Calmar':>9}")
for nm, v, lag in FUNDS:
    for L in ({0, lag} if lag else {0}):
        s = stats(timed(v, L))
        tag = f"{nm} " + (f"(+{L}d)" if L else "(same day)")
        print(f"  {tag:<20}{L:>5}{s['mult']:>10.1f}x{s['cagr']:>8.1f}%{s['mdd']:>9.1f}%{s['sharpe']:>9.2f}{s['calmar']:>9.2f}")

print("\n" + "="*96)
print("DANISH TAX — lagerprincippet, annual mark-to-market on unrealized gains")
print("27% = aktieindkomst (if SKAT lists the fund as share-based)")
print("42% = kapitalindkomst (the likely treatment for a swap-based leveraged fund)")
print("17% = aktiesparekonto rate (leveraged funds are generally NOT eligible)\n")
dts = ds[250:]
print(f"  {'fund':<16}{'strategy':<12}{'pre-tax':>10}{'27%':>9}{'42%':>9}{'17%':>9}")
for nm, v, lag in FUNDS:
    for lbl, c in [("buy & hold", v[250:]), ("200d+vol", timed(v, lag))]:
        c = c[:len(dts)]
        pre = stats(c)['cagr']
        row = [stats(tax_lager(c, dts, r))['cagr'] for r in (0.27, 0.42, 0.17)]
        print(f"  {nm.split(' (')[0][:15]:<16}{lbl:<12}{pre:>9.1f}%"
              + "".join(f"{x:>8.1f}%" for x in row))

print("\n" + "="*96)
print("KEY RATIOS")
lqq_bh = stats([LQQ[d] for d in ds]); tq_bh = stats([TQQQ_E[d] for d in ds])
lqq_t = stats(timed([LQQ[d] for d in ds], 1)); tq_t = stats(timed([TQQQ_E[d] for d in ds], 0))
print(f"  buy & hold   LQQ {lqq_bh['cagr']:.1f}% / {lqq_bh['mdd']:.0f}%   "
      f"TQQQ {tq_bh['cagr']:.1f}% / {tq_bh['mdd']:.0f}%")
print(f"  timed        LQQ {lqq_t['cagr']:.1f}% / {lqq_t['mdd']:.0f}%   "
      f"TQQQ {tq_t['cagr']:.1f}% / {tq_t['mdd']:.0f}%")
print(f"  Calmar timed LQQ {lqq_t['calmar']:.2f}          TQQQ {tq_t['calmar']:.2f}")

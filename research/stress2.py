"""Full-cycle test (1999-2026) of the leading candidates, including the
volatility filter that the 2010-2026 sample suggested was valuable.

Uses the synthetic 3x series calibrated in stress.py (residual error
-0.18%/yr against the real TQQQ over 2010-2026).
"""
import json, math

raw = json.load(open("/home/user/investor-help/public/study/leveraged.json"))
qq = {r["t"]: r["c"] for r in raw["QQQ"]["rows"]}
tq = {r["t"]: r["c"] for r in raw["TQQQ"]["rows"]}
dates = sorted(qq)

RATES = {1999:4.64,2000:5.82,2001:3.39,2002:1.60,2003:1.01,2004:1.37,
         2005:3.15,2006:4.73,2007:4.36,2008:1.37,2009:0.15,2010:0.14,
         2011:0.05,2012:0.09,2013:0.06,2014:0.03,2015:0.05,2016:0.32,
         2017:0.93,2018:1.94,2019:2.06,2020:0.37,2021:0.04,2022:2.02,
         2023:5.07,2024:5.15,2025:4.20,2026:3.80}
ER, SPREAD, EXTRA = 0.0095, 0.0040, 0.0018

def synth(L, dts):
    out = {dts[0]: 100.0}
    for i in range(1, len(dts)):
        d0, d1 = dts[i-1], dts[i]
        r = qq[d1]/qq[d0] - 1
        rf = RATES.get(int(d1[:4]), 3.0)/100
        cost = (ER + abs(L-1)*(rf+SPREAD) + EXTRA)/252
        out[d1] = out[d0]*(1 + L*r - cost)
    return out

def sma(v, n):
    out, s = [None]*len(v), 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n: s -= v[i-n]
        if i >= n-1: out[i] = s/n
    return out

def rvol(v, n=20):
    out = [None]*len(v)
    lr = [0.0]+[math.log(v[i]/v[i-1]) for i in range(1, len(v))]
    for i in range(n, len(v)):
        w = lr[i-n+1:i+1]
        m = sum(w)/n
        out[i] = math.sqrt(sum((x-m)**2 for x in w)/(n-1)*252)
    return out

def stats(vals):
    yrs = len(vals)/252
    mult = vals[-1]/vals[0]
    peak, mdd = vals[0], 0.0
    for x in vals:
        peak = max(peak, x); mdd = min(mdd, x/peak-1)
    dr = [vals[i]/vals[i-1]-1 for i in range(1, len(vals))]
    mu = sum(dr)/len(dr)
    sd = math.sqrt(sum((x-mu)**2 for x in dr)/(len(dr)-1))
    cagr = (mult**(1/yrs)-1)*100 if mult > 0 else float('nan')
    return dict(mult=mult, cagr=cagr, mdd=mdd*100,
                sharpe=(mu*252)/(sd*math.sqrt(252)) if sd else 0,
                calmar=cagr/abs(mdd*100) if mdd else 0)

def backtest(dts, alloc, cost=0.0005, warm=250):
    """alloc(i) -> dict of {'3x'|'1x': weight}"""
    s3 = synth(3, dts)
    qv = [qq[d] for d in dts]
    eq, held = 1.0, {}
    curve = [1.0]
    for i in range(warm, len(dts)-1):
        tgt = {k: v for k, v in (alloc(i) or {}).items() if v > 1e-9}
        keys = set(tgt)|set(held)
        to = sum(abs(tgt.get(k,0)-held.get(k,0)) for k in keys)
        if to > 1e-9:
            eq *= (1-cost*to)
        d0, d1 = dts[i], dts[i+1]
        r3 = s3[d1]/s3[d0]-1
        r1 = qq[d1]/qq[d0]-1
        eq *= (1 + tgt.get('3x',0)*r3 + tgt.get('1x',0)*r1)
        held = tgt
        curve.append(eq)
    return curve

def report(a, b, title):
    dts = [d for d in dates if a <= d <= b]
    if len(dts) < 400: return
    qv = [qq[d] for d in dts]
    MA = {n: sma(qv, n) for n in (150, 200, 250)}
    VOL = rvol(qv, 20)
    def above(i, n): return MA[n][i] is not None and qv[i] > MA[n][i]

    STR = {
      "Buy & hold QQQ (1x)":            lambda i: {'1x':1},
      "Buy & hold TQQQ (3x)":           lambda i: {'3x':1},
      "200d -> 3x / cash":              lambda i: {'3x':1} if above(i,200) else {},
      "250d -> 3x / cash":              lambda i: {'3x':1} if above(i,250) else {},
      "200d -> 3x / 1x":                lambda i: {'3x':1} if above(i,200) else {'1x':1},
      "200d + vol<25% -> 3x / cash":    lambda i: {'3x':1} if above(i,200) and VOL[i] is not None and VOL[i]<0.25 else {},
      "200d + vol<25% -> 3x else 1x":   lambda i: ({'3x':1} if VOL[i] is not None and VOL[i]<0.25 else {'1x':1}) if above(i,200) else {},
      "200d + vol<35% -> 3x / cash":    lambda i: {'3x':1} if above(i,200) and VOL[i] is not None and VOL[i]<0.35 else {},
      "200d vol-scaled 3x/1x":          None,
      "200d vol-target 25%":            None,
      "200d vol-target 40%":            None,
    }
    def vs(i):
        if not above(i,200) or VOL[i] is None: return {}
        w = min(1.0, 0.20/VOL[i]); return {'3x':w, '1x':1-w}
    def vt(target):
        def f(i):
            if not above(i,200) or VOL[i] is None: return {}
            return {'3x': min(1.0, target/(3*VOL[i]))}
        return f
    STR["200d vol-scaled 3x/1x"] = vs
    STR["200d vol-target 25%"] = vt(0.25)
    STR["200d vol-target 40%"] = vt(0.40)

    print(f"\n{title}   ({dts[0]} -> {dts[-1]}, {len(dts)/252:.1f}y)")
    print(f"  {'strategy':<32}{'multiple':>12}{'CAGR':>8}{'MaxDD':>9}{'Sharpe':>8}{'Calmar':>8}")
    print("  " + "-"*77)
    rows = []
    for name, fn in STR.items():
        s = stats(backtest(dts, fn))
        rows.append((name, s))
    for name, s in rows:
        print(f"  {name:<32}{s['mult']:>11.2f}x{s['cagr']:>7.1f}%{s['mdd']:>8.1f}%"
              f"{s['sharpe']:>8.2f}{s['calmar']:>8.2f}")

report("1999-03-10","2026-08-14","FULL CYCLE 1999-2026 (includes dot-com + GFC)")
report("1999-03-10","2010-02-10","BEAR-HEAVY 1999-2010")
report("2010-02-11","2026-08-14","BULL-HEAVY 2010-2026 (TQQQ live era)")

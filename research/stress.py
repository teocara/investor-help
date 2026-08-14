"""Stress test: how would a 3x QQQ ETF have behaved through 2000-2010?

TQQQ launched in Feb 2010, so the entire live record sits inside a secular
Nasdaq bull market. That is the single biggest bias in the study. This builds
a synthetic 3x series from QQQ daily returns, calibrates it against the real
TQQQ over the overlapping period, then replays 1999-2010 (dot-com bust and
the GFC).

Synthetic model, applied to DAILY returns so path dependency is preserved:
    r_lev = L*r_qqq - (expense_ratio + (L-1)*financing_rate)/252
Financing tracks the short rate, which matters enormously: in 2000 the
3-month bill yielded ~6%, so carrying 2x borrowed notional cost ~12%/yr,
versus ~0% through the 2010s ZIRP era.
"""
import json, math

raw = json.load(open("/home/user/investor-help/public/study/leveraged.json"))
qq = {r["t"]: r["c"] for r in raw["QQQ"]["rows"]}
tq = {r["t"]: r["c"] for r in raw["TQQQ"]["rows"]}
dates = sorted(qq)

# approximate annual average 3-month T-bill yield (%)
RATES = {1999:4.64,2000:5.82,2001:3.39,2002:1.60,2003:1.01,2004:1.37,
         2005:3.15,2006:4.73,2007:4.36,2008:1.37,2009:0.15,2010:0.14,
         2011:0.05,2012:0.09,2013:0.06,2014:0.03,2015:0.05,2016:0.32,
         2017:0.93,2018:1.94,2019:2.06,2020:0.37,2021:0.04,2022:2.02,
         2023:5.07,2024:5.15,2025:4.20,2026:3.80}
ER = 0.0095          # ProShares stated expense ratio
SPREAD = 0.0040      # swap/financing spread over the risk-free rate

def synth(L, dts, extra_drag=0.0):
    """Daily-reset synthetic leveraged series, starting at 100."""
    out = {dts[0]: 100.0}
    for i in range(1, len(dts)):
        d0, d1 = dts[i-1], dts[i]
        r = qq[d1] / qq[d0] - 1
        yr = int(d1[:4])
        rf = RATES.get(yr, 3.0) / 100
        cost = (ER + abs(L - 1) * (rf + SPREAD) + extra_drag) / 252
        out[d1] = out[d0] * (1 + L * r - cost)
    return out

# ── calibrate against the real TQQQ ─────────────────────────────────────
overlap = [d for d in dates if d in tq]
syn = synth(3, overlap)
act_mult = tq[overlap[-1]] / tq[overlap[0]]
syn_mult = syn[overlap[-1]] / syn[overlap[0]]
yrs = len(overlap) / 252
print(f"calibration over {overlap[0]} -> {overlap[-1]} ({yrs:.1f}y)")
print(f"  actual TQQQ    {act_mult:8.1f}x   CAGR {(act_mult**(1/yrs)-1)*100:6.2f}%")
print(f"  synthetic 3x   {syn_mult:8.1f}x   CAGR {(syn_mult**(1/yrs)-1)*100:6.2f}%")
resid = (act_mult / syn_mult) ** (1 / yrs) - 1
print(f"  residual model error: {resid*100:+.2f}%/yr -> folding into extra_drag")

syn2 = synth(3, overlap, extra_drag=-resid)
m2 = syn2[overlap[-1]] / syn2[overlap[0]]
print(f"  calibrated synthetic {m2:8.1f}x   CAGR {(m2**(1/yrs)-1)*100:6.2f}%  "
      f"(target {(act_mult**(1/yrs)-1)*100:.2f}%)")
EXTRA = -resid

# ── replay the dot-com era ──────────────────────────────────────────────
def window(a, b):
    return [d for d in dates if a <= d <= b]

def stats(ser, dts, label):
    v = [ser[d] for d in dts]
    yrs = len(v) / 252
    mult = v[-1] / v[0]
    peak, mdd = v[0], 0.0
    for x in v:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    cagr = (mult ** (1 / yrs) - 1) * 100 if mult > 0 else float("nan")
    print(f"  {label:<34}{mult:>10.4f}x{cagr:>9.1f}%{mdd*100:>10.1f}%")

def sma(vals, n):
    out, s = [None]*len(vals), 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n: s -= vals[i-n]
        if i >= n-1: out[i] = s/n
    return out

def run_ma(dts, lev_ser, n=200, cost=0.0005):
    """QQQ above its n-day SMA -> hold the leveraged fund, else cash."""
    qv = [qq[d] for d in dts]
    ma = sma(qv, n)
    eq, held = 1.0, False
    curve = {dts[n]: 1.0}
    for i in range(n, len(dts)-1):
        want = ma[i] is not None and qv[i] > ma[i]
        if want != held:
            eq *= (1 - cost)
            held = want
        if want:
            d0, d1 = dts[i], dts[i+1]
            eq *= lev_ser[d1] / lev_ser[d0]
        curve[dts[i+1]] = eq
    return curve

for a, b, name in [("1999-03-10","2010-02-10","DOT-COM + GFC  1999-2010"),
                   ("1999-03-10","2003-01-01","DOT-COM BUST   1999-2002"),
                   ("2007-10-01","2009-06-30","GFC            2007-2009"),
                   ("1999-03-10","2026-08-14","FULL           1999-2026")]:
    dts = window(a, b)
    if len(dts) < 260:
        continue
    s3 = synth(3, dts, EXTRA)
    print(f"\n{name}   ({dts[0]} -> {dts[-1]}, {len(dts)/252:.1f}y)")
    print(f"  {'':<34}{'multiple':>11}{'CAGR':>9}{'MaxDD':>10}")
    stats({d: qq[d] for d in dts}, dts, "Buy & hold QQQ (1x)")
    stats(s3, dts, "Buy & hold synthetic TQQQ (3x)")
    for n in (150, 200, 250):
        c = run_ma(dts, s3, n)
        cd = sorted(c)
        stats(c, cd, f"QQQ>{n}d -> 3x / cash")
    c1 = run_ma(dts, {d: qq[d] for d in dts}, 200)
    stats(c1, sorted(c1), "QQQ>200d -> QQQ / cash")

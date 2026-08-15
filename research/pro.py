"""Does what professional trend-followers actually do beat a single moving
average, and does it generalize beyond the Nasdaq?

Tests four approaches across all 294 watchlist instruments (weekly bars, full
history), rather than tuning on one series:

  BH        buy & hold
  MA200     single 200-day trend filter, binary in/out   (the retail default)
  ENSEMBLE  four lookbacks (20/60/120/250d) averaged into a fractional weight
            -- this is the core of how CTAs actually build a trend signal
  ENS+VOL   the same, then scaled to a constant volatility target
            -- vol targeting is near-universal in institutional portfolios

The point of the ensemble is not that any lookback is better; it is that
averaging removes the parameter choice, which is where single-MA backtests
get their flattery.
"""
import json, glob, math, os, statistics as st

BARS_YR = 52          # weekly files
COST = 0.0005

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

def stats(vals):
    if len(vals) < 30: return None
    yrs = len(vals)/BARS_YR
    mult = vals[-1]/vals[0]
    if mult <= 0: return None
    peak, mdd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v); mdd = min(mdd, v/peak-1)
    dr = [vals[i]/vals[i-1]-1 for i in range(1, len(vals))]
    mu = sum(dr)/len(dr)
    sd = math.sqrt(max(1e-12, sum((x-mu)**2 for x in dr)/(len(dr)-1)))
    cagr = (mult**(1/yrs)-1)*100
    return dict(cagr=cagr, mdd=mdd*100, sharpe=(mu*BARS_YR)/(sd*math.sqrt(BARS_YR)),
                calmar=cagr/abs(mdd*100) if mdd else 0, mult=mult)

# lookbacks in trading days -> weekly bars
LB = [max(2, round(d*BARS_YR/252)) for d in (20, 60, 120, 250)]

def weights(closes, kind, target=0.15):
    n = len(closes)
    mas = {k: sma(closes, k) for k in LB}
    ma200 = sma(closes, max(2, round(200*BARS_YR/252)))
    vol = rvol(closes)
    w = [0.0]*n
    for i in range(n):
        if kind == "bh":
            w[i] = 1.0
        elif kind == "ma200":
            w[i] = 1.0 if (ma200[i] is not None and closes[i] > ma200[i]) else 0.0
        else:
            sig = [1.0 if (mas[k][i] is not None and closes[i] > mas[k][i]) else 0.0 for k in LB]
            f = sum(sig)/len(sig)
            if kind == "ensvol":
                v = vol[i]
                f *= min(1.0, target/v) if v and v > 0 else 0.0
            w[i] = min(1.0, f)
    return w

def run(closes, w, warm):
    eq = 1.0; cur = 0.0; curve = [1.0]
    for i in range(warm, len(closes)-1):
        tgt = w[i]
        if abs(tgt-cur) > 1e-9:
            eq *= (1-COST*abs(tgt-cur)*2); cur = tgt
        r = closes[i+1]/closes[i]-1
        eq *= (1+cur*r)
        curve.append(eq)
    return curve

KINDS = ["bh", "ma200", "ens", "ensvol"]
NAMES = {"bh": "Buy & hold", "ma200": "MA200 binary",
         "ens": "Ensemble 4-LB", "ensvol": "Ensemble + vol target"}

def evaluate(path):
    try:
        rows = json.load(open(path))
    except Exception:
        return None
    closes = [r["close"] for r in rows if r.get("close")]
    if len(closes) < 400:          # need ~8y of weekly bars
        return None
    warm = max(LB+[round(200*BARS_YR/252)])+5
    out = {}
    for k in KINDS:
        s = stats(run(closes, weights(closes, k), warm))
        if not s: return None
        out[k] = s
    return out

if __name__ == "__main__":
    files = sorted(glob.glob("/home/user/investor-help/public/ohlcv-long/*.json"))
    res = {}
    for f in files:
        t = os.path.basename(f)[:-5]
        r = evaluate(f)
        if r: res[t] = r
    print(f"evaluated {len(res)} instruments with >=8y of weekly history\n")

    def med(k, m): return st.median([v[k][m] for v in res.values()])
    print(f"{'approach':<24}{'med CAGR':>10}{'med MaxDD':>11}{'med Sharpe':>12}{'med Calmar':>12}")
    print("-"*69)
    for k in KINDS:
        print(f"{NAMES[k]:<24}{med(k,'cagr'):>9.1f}%{med(k,'mdd'):>10.1f}%"
              f"{med(k,'sharpe'):>12.2f}{med(k,'calmar'):>12.2f}")

    print(f"\n{'approach':<24}{'beats B&H CAGR':>16}{'beats B&H Calmar':>18}{'lower MaxDD':>14}")
    print("-"*72)
    n = len(res)
    for k in KINDS[1:]:
        c = sum(1 for v in res.values() if v[k]['cagr'] > v['bh']['cagr'])
        m = sum(1 for v in res.values() if v[k]['calmar'] > v['bh']['calmar'])
        d = sum(1 for v in res.values() if abs(v[k]['mdd']) < abs(v['bh']['mdd']))
        print(f"{NAMES[k]:<24}{c/n*100:>15.0f}%{m/n*100:>17.0f}%{d/n*100:>13.0f}%")

    print("\nensemble vs the single moving average, head to head")
    better_c = sum(1 for v in res.values() if v['ens']['calmar'] > v['ma200']['calmar'])
    better_r = sum(1 for v in res.values() if v['ens']['cagr'] > v['ma200']['cagr'])
    print(f"  ensemble beats MA200 on Calmar in {better_c/n*100:.0f}% of instruments")
    print(f"  ensemble beats MA200 on CAGR   in {better_r/n*100:.0f}% of instruments")

    # spread of outcomes: the honest measure of how transferable a rule is
    print("\ndispersion of Calmar across instruments (10th / 50th / 90th pct)")
    for k in KINDS:
        xs = sorted(v[k]['calmar'] for v in res.values())
        q = lambda p: xs[int(p*(len(xs)-1))]
        print(f"  {NAMES[k]:<24}{q(.1):>7.2f}{q(.5):>8.2f}{q(.9):>8.2f}")

    for t in ("QQQ", "TQQQ", "SPY", "AAPL", "NVDA", "GLD", "TLT"):
        if t in res:
            v = res[t]
            print(f"\n{t}")
            for k in KINDS:
                s = v[k]
                print(f"  {NAMES[k]:<24}{s['cagr']:>7.1f}%{s['mdd']:>9.1f}%{s['calmar']:>8.2f}")

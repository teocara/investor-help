"""Leveraged QQQ strategy study.

Uses ACTUAL TQQQ / SQQQ price series rather than synthetic 3x returns, so the
funds' real expense ratios, financing costs and daily-reset volatility decay
are already embedded in the data. The only cost added on top is the trading
cost of switching between instruments.

Signals are computed on QQQ from data up to and including bar i, and the
resulting position is held over bar i+1's return — no same-bar lookahead.
"""
import json, math

DATA = "/home/user/investor-help/public/study/leveraged.json"

raw = json.load(open(DATA))
series = {k: {r["t"]: r["c"] for r in v["rows"]} for k, v in raw.items()}

need = ["QQQ", "TQQQ", "SQQQ"]
dates = sorted(set.intersection(*[set(series[t]) for t in need]))
px = {t: [series[t][d] for d in dates] for t in need}
N = len(dates)

def rets(p):
    return [0.0] + [p[i] / p[i - 1] - 1 for i in range(1, len(p))]

R = {t: rets(px[t]) for t in need}
q = px["QQQ"]

# ── data validation ─────────────────────────────────────────────────────
def validate():
    rq, rt, rs = R["QQQ"], R["TQQQ"], R["SQQQ"]
    n = len(rq) - 1
    def beta(a, b):
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) - 1)
        var = sum((y - mb) ** 2 for y in b) / (len(b) - 1)
        return cov / var
    bt = beta(rt[1:], rq[1:])
    bs = beta(rs[1:], rq[1:])
    print(f"daily beta  TQQQ vs QQQ = {bt:+.3f}   (expect ~ +3.00)")
    print(f"daily beta  SQQQ vs QQQ = {bs:+.3f}   (expect ~ -3.00)")
    worst_t = min(rt[1:]); best_t = max(rt[1:])
    print(f"TQQQ daily range: {worst_t*100:+.1f}% .. {best_t*100:+.1f}%")
    # realized decay: actual TQQQ vs naive daily-compounded 3x with no costs
    naive = 1.0
    for r in rq[1:]:
        naive *= (1 + 3 * r)
    actual = px["TQQQ"][-1] / px["TQQQ"][0]
    yrs = n / 252
    print(f"over {yrs:.1f}y:  actual TQQQ {actual:.1f}x   vs naive-3x-daily {naive:.1f}x"
          f"   -> fee/financing drag {((actual/naive)**(1/yrs)-1)*100:+.2f}%/yr")
    print(f"buy&hold QQQ {px['QQQ'][-1]/px['QQQ'][0]:.1f}x, "
          f"SQQQ {px['SQQQ'][-1]/px['SQQQ'][0]:.5f}x")

# ── indicators on QQQ ───────────────────────────────────────────────────
def sma(a, n):
    out, s = [None] * len(a), 0.0
    for i, v in enumerate(a):
        s += v
        if i >= n:
            s -= a[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out

def ema(a, n):
    k = 2 / (n + 1)
    out = [a[0]]
    for v in a[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out

def rsi(a, n=14):
    out = [None] * len(a)
    g = l = 0.0
    for i in range(1, len(a)):
        d = a[i] - a[i - 1]
        gi, li = max(d, 0.0), max(-d, 0.0)
        if i <= n:
            g += gi; l += li
            if i == n:
                g /= n; l /= n
                out[i] = 100 - 100 / (1 + (g / l if l else 999))
        else:
            g = (g * (n - 1) + gi) / n
            l = (l * (n - 1) + li) / n
            out[i] = 100 - 100 / (1 + (g / l if l else 999))
    return out

def realized_vol(a, n=20):
    out = [None] * len(a)
    lr = [0.0] + [math.log(a[i] / a[i - 1]) for i in range(1, len(a))]
    for i in range(n, len(a)):
        w = lr[i - n + 1:i + 1]
        m = sum(w) / n
        v = sum((x - m) ** 2 for x in w) / (n - 1)
        out[i] = math.sqrt(v * 252)
    return out

def dd_from_peak(a, n):
    out = [None] * len(a)
    for i in range(len(a)):
        pk = max(a[max(0, i - n + 1):i + 1])
        out[i] = a[i] / pk - 1
    return out

IND = {
    "sma20": sma(q, 20), "sma50": sma(q, 50), "sma100": sma(q, 100),
    "sma150": sma(q, 150), "sma200": sma(q, 200), "sma250": sma(q, 250),
    "rsi14": rsi(q), "vol20": realized_vol(q, 20), "dd60": dd_from_peak(q, 60),
}
_f, _s = ema(q, 12), ema(q, 26)
MACD = [_f[i] - _s[i] for i in range(N)]
MACD_SIG = ema(MACD, 9)

WARMUP = 250
TRADE_COST = 0.0005      # 5 bps per unit traded (spread + commission)

# ── engine ──────────────────────────────────────────────────────────────
def run(fn, cost=TRADE_COST, lo=WARMUP, hi=None):
    hi = (N - 1) if hi is None else min(hi, N - 1)
    eq, held, trades, expo = 1.0, {}, 0, 0
    curve = []
    for i in range(lo, hi):
        tgt = {k: v for k, v in (fn(i) or {}).items() if v > 1e-9}
        keys = set(tgt) | set(held)
        turnover = sum(abs(tgt.get(k, 0) - held.get(k, 0)) for k in keys)
        if turnover > 1e-9:
            eq *= (1 - cost * turnover)
            trades += 1
        eq *= (1 + sum(w * R[k][i + 1] for k, w in tgt.items()))
        if tgt:
            expo += 1
        held = tgt
        curve.append((dates[i + 1], eq))
    return curve, trades, expo, (hi - lo)

def metrics(curve, trades, expo, bars):
    if len(curve) < 30:
        return None
    vals = [v for _, v in curve]
    yrs = len(vals) / 252
    growth = vals[-1]
    if growth <= 0:
        return None
    cagr = growth ** (1 / yrs) - 1
    peak, mdd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    dr = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]
    mu = sum(dr) / len(dr)
    sd = math.sqrt(sum((x - mu) ** 2 for x in dr) / (len(dr) - 1))
    sharpe = (mu * 252) / (sd * math.sqrt(252)) if sd else 0
    ds = [x for x in dr if x < 0]
    dsd = math.sqrt(sum(x * x for x in ds) / len(ds)) if ds else 0
    sortino = (mu * 252) / (dsd * math.sqrt(252)) if dsd else 0
    yrs_inv = expo / 252
    roti = (growth ** (1 / yrs_inv) - 1) * 100 if yrs_inv > 0 else None
    return dict(cagr=cagr * 100, mdd=mdd * 100, sharpe=sharpe, sortino=sortino,
                calmar=(cagr * 100) / abs(mdd * 100) if mdd else 0,
                final=growth, expo=expo / bars * 100 if bars else 0,
                roti=roti, trades=trades, tpy=trades / yrs, yrs=yrs)

# ── strategies ──────────────────────────────────────────────────────────
STRATS = {}
def S(name):
    def deco(f):
        STRATS[name] = f
        return f
    return deco

def above(i, key):
    v = IND[key][i]
    return v is not None and q[i] > v

S("Buy & hold TQQQ")(lambda i: {"TQQQ": 1})
S("Buy & hold QQQ")(lambda i: {"QQQ": 1})
S("QQQ>50d -> TQQQ / cash")(lambda i: {"TQQQ": 1} if above(i, "sma50") else {})
S("QQQ>100d -> TQQQ / cash")(lambda i: {"TQQQ": 1} if above(i, "sma100") else {})
S("QQQ>150d -> TQQQ / cash")(lambda i: {"TQQQ": 1} if above(i, "sma150") else {})
S("QQQ>200d -> TQQQ / cash")(lambda i: {"TQQQ": 1} if above(i, "sma200") else {})
S("QQQ>250d -> TQQQ / cash")(lambda i: {"TQQQ": 1} if above(i, "sma250") else {})
S("QQQ>200d -> TQQQ / SQQQ")(lambda i: {"TQQQ": 1} if above(i, "sma200") else {"SQQQ": 1})
S("QQQ>200d -> TQQQ / QQQ")(lambda i: {"TQQQ": 1} if above(i, "sma200") else {"QQQ": 1})
S("RSI>50 -> TQQQ / cash")(
    lambda i: {"TQQQ": 1} if (IND["rsi14"][i] or 0) > 50 else {})
S("MACD>sig -> TQQQ / cash")(
    lambda i: {"TQQQ": 1} if MACD[i] > MACD_SIG[i] else {})

@S("Golden cross 50/200 -> TQQQ / cash")
def _(i):
    a, b = IND["sma50"][i], IND["sma200"][i]
    return {"TQQQ": 1} if a and b and a > b else {}

@S("200d + vol<35% -> TQQQ / cash")
def _(i):
    v = IND["vol20"][i]
    return {"TQQQ": 1} if above(i, "sma200") and v is not None and v < 0.35 else {}

@S("200d + vol<25% -> TQQQ / cash")
def _(i):
    v = IND["vol20"][i]
    return {"TQQQ": 1} if above(i, "sma200") and v is not None and v < 0.25 else {}

@S("200d + vol<25% -> TQQQ else QQQ")
def _(i):
    v = IND["vol20"][i]
    if above(i, "sma200"):
        return {"TQQQ": 1} if v is not None and v < 0.25 else {"QQQ": 1}
    return {}

@S("200d, vol-scaled TQQQ/QQQ")
def _(i):
    if not above(i, "sma200"):
        return {}
    v = IND["vol20"][i]
    if v is None:
        return {}
    w = min(1.0, 0.20 / v)
    return {"TQQQ": w, "QQQ": 1 - w}

@S("Vol-target 25% on TQQQ sleeve")
def _(i):
    v = IND["vol20"][i]
    if v is None or not above(i, "sma200"):
        return {}
    return {"TQQQ": min(1.0, 0.25 / (3 * v))}

@S("Vol-target 40% on TQQQ sleeve")
def _(i):
    v = IND["vol20"][i]
    if v is None or not above(i, "sma200"):
        return {}
    return {"TQQQ": min(1.0, 0.40 / (3 * v))}

@S("200d + 20d confirm -> TQQQ / cash")
def _(i):
    return {"TQQQ": 1} if above(i, "sma200") and above(i, "sma20") else {}

@S("200d; SQQQ only if 50d<200d")
def _(i):
    if above(i, "sma200"):
        return {"TQQQ": 1}
    a, b = IND["sma50"][i], IND["sma200"][i]
    return {"SQQQ": 1} if a and b and a < b else {}

@S("200d + dd>-8% -> TQQQ else QQQ")
def _(i):
    if not above(i, "sma200"):
        return {}
    return {"TQQQ": 1} if IND["dd60"][i] > -0.08 else {"QQQ": 1}

@S("Half TQQQ when QQQ>200d")
def _(i):
    return {"TQQQ": 0.5} if above(i, "sma200") else {}

@S("200d checked weekly -> TQQQ / cash")
def _(i):
    j = i - (i % 5)
    return {"TQQQ": 1} if above(j, "sma200") else {}

@S("200d with 2% band -> TQQQ / cash")
def _(i):
    v = IND["sma200"][i]
    if v is None:
        return {}
    return {"TQQQ": 1} if q[i] > v * 1.02 else ({} if q[i] < v * 0.98 else None)

# stateful hysteresis variant needs its own wrapper
def make_band(band):
    state = {"on": False}
    def f(i):
        v = IND["sma200"][i]
        if v is None:
            return {}
        if q[i] > v * (1 + band):
            state["on"] = True
        elif q[i] < v * (1 - band):
            state["on"] = False
        return {"TQQQ": 1} if state["on"] else {}
    return f

for b in (0.01, 0.02, 0.03, 0.05):
    STRATS[f"200d +/-{int(b*100)}% band -> TQQQ / cash"] = make_band(b)

# ── reporting ───────────────────────────────────────────────────────────
HDR = (f"{'strategy':<38}{'CAGR':>8}{'MaxDD':>9}{'Sharpe':>8}{'Calmar':>8}"
       f"{'Expo':>7}{'RoTI':>9}{'tr/yr':>7}{'mult':>9}")

def show(title, rows):
    print(f"\n{title}")
    print(HDR); print("-" * 103)
    for name, m in rows:
        if not m:
            continue
        print(f"{name:<38}{m['cagr']:>7.1f}%{m['mdd']:>8.1f}%{m['sharpe']:>8.2f}"
              f"{m['calmar']:>8.2f}{m['expo']:>6.0f}%"
              f"{(m['roti'] or 0):>8.1f}%{m['tpy']:>7.1f}{m['final']:>8.1f}x")

def evaluate(label, lo=WARMUP, hi=None, cost=TRADE_COST, sort="cagr"):
    res = []
    for name, fn in STRATS.items():
        # rebuild stateful closures so each evaluation starts clean
        if name.endswith("band -> TQQQ / cash") and "+/-" in name:
            b = int(name.split("+/-")[1].split("%")[0]) / 100
            fn = make_band(b)
        c, t, e, b_ = run(fn, cost=cost, lo=lo, hi=hi)
        res.append((name, metrics(c, t, e, b_)))
    res.sort(key=lambda r: -(r[1][sort] if r[1] else -999))
    show(label, res)
    return res

def find(dstr):
    for i, d in enumerate(dates):
        if d >= dstr:
            return i
    return N

if __name__ == "__main__":
    print("=" * 103)
    validate()
    print("=" * 103)
    print(f"calendar: {len(dates)} bars  {dates[0]} -> {dates[-1]}")

    full = evaluate(f"FULL PERIOD {dates[WARMUP]} -> {dates[-1]}   (5 bps per unit traded)")

    split = find("2019-01-01")
    evaluate(f"IN-SAMPLE  {dates[WARMUP]} -> {dates[split-1]}", hi=split)
    evaluate(f"OUT-OF-SAMPLE  {dates[split]} -> {dates[-1]}", lo=split)

    print("\n\nCOST SENSITIVITY (full period CAGR %)")
    print(f"{'strategy':<38}{'0bps':>9}{'5bps':>9}{'20bps':>9}{'50bps':>9}")
    print("-" * 74)
    for name, _m in full[:12]:
        row = []
        for c in (0.0, 0.0005, 0.002, 0.005):
            fn = STRATS[name]
            if "+/-" in name:
                fn = make_band(int(name.split("+/-")[1].split("%")[0]) / 100)
            cc, t, e, b_ = run(fn, cost=c)
            mm = metrics(cc, t, e, b_)
            row.append(mm['cagr'] if mm else float('nan'))
        print(f"{name:<38}" + "".join(f"{v:>8.1f}%" for v in row))

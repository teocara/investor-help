"""Backtest the exact rules the live paper account will run.

Uses the weekly long-history files so the test spans multiple regimes rather
than the last two years. Windows are converted from trading days to weeks.
"""
import json, glob, math, os, re, statistics as st

W = 52
MOM_LB, MOM_SKIP = round(252/252*W), round(21/252*W)   # 52w lookback, skip 4w
TREND = round(200/252*W)                                # ~41 weeks
VOLW  = round(60/252*W)
MINH  = round(300/252*W)
NPOS, MAXW, MINW, COST, MAXSEC = 15, 0.15, 0.02, 0.0005, 0.40
EXCLUDE = {"TQQQ","SQQQ","QLD","PSQ","LQQ.PA","EURUSD=X","UVXY","SOXL","SOXS"}

html = open("/home/user/investor-help/investor-dashboard.html", encoding="utf-8").read()
rows = re.findall(r'ticker:"([^"]+)"[^}]*?sector:"([^"]*)"', html)
SEC, seen = {}, set()
for t, s in rows:
    if t in seen: continue
    seen.add(t)
    if t in EXCLUDE or "." in t or "=" in t: continue
    SEC[t] = s or "Unknown"

PX = {}
for f in glob.glob("/home/user/investor-help/public/ohlcv-long/*.json"):
    t = os.path.basename(f)[:-5]
    if t not in SEC and t not in ("SPY","QQQ"): continue
    try: rs = json.load(open(f))
    except Exception: continue
    m = {r["time"]: r["close"] for r in rs if r.get("close")}
    if len(m) >= MINH + 30: PX[t] = m

from collections import Counter
cnt = Counter()
for m in PX.values():
    for d in m: cnt[d] += 1
dates = sorted(d for d, c in cnt.items() if c >= len(PX)*0.7)
print(f"{len(PX)} series, {len(dates)} weekly bars  {dates[0]} -> {dates[-1]}  ({len(dates)/W:.1f} yrs)")

def series(t):
    m = PX[t]; out, last = [], None
    for d in dates:
        last = m.get(d, last); out.append(last)
    return out
S = {t: series(t) for t in PX}

def mom(c, i):
    if i < MOM_LB or c[i-MOM_LB] is None or c[i-MOM_SKIP] is None: return None
    a, b = c[i-MOM_LB], c[i-MOM_SKIP]
    return None if not a or a <= 0 else b/a - 1
def trend(c, i):
    w = [x for x in c[max(0,i-TREND+1):i+1] if x]
    return len(w) >= TREND*0.8 and c[i] and c[i] > sum(w)/len(w)
def vol(c, i):
    w = [c[j] for j in range(max(1,i-VOLW+1), i+1) if c[j] and c[j-1]]
    if len(w) < 8: return None
    r = [math.log(c[j]/c[j-1]) for j in range(max(1,i-VOLW+1), i+1) if c[j] and c[j-1]]
    m = sum(r)/len(r)
    return math.sqrt(sum((x-m)**2 for x in r)/(len(r)-1)*W)

def run(rebalance_every=4):
    cash, pos = 100000.0, {}
    curve, nheld = [], []
    last_rb = -99
    for i in range(MINH, len(dates)):
        # daily-equivalent risk check every bar
        for t in list(pos):
            c = S[t]
            if not trend(c, i):
                cash += pos.pop(t)["sh"]*c[i]*(1-COST)
        if i - last_rb >= rebalance_every:
            last_rb = i
            ranked = []
            for t in SEC:
                if t not in S: continue
                c = S[t]
                if c[i] is None: continue
                m = mom(c, i)
                if m is None or m <= 0 or not trend(c, i): continue
                v = vol(c, i)
                if not v or v <= 0: continue
                ranked.append((m, t, v, c[i]))
            ranked.sort(reverse=True)
            picks, per = [], {}
            cap = max(1, int(NPOS*MAXSEC))
            for m, t, v, p in ranked:
                s = SEC.get(t,"Unknown")
                if per.get(s,0) >= cap: continue
                picks.append((t,v,p)); per[s] = per.get(s,0)+1
                if len(picks) >= NPOS: break
            keep = {t for t,_,_ in picks}
            for t in list(pos):
                if t not in keep:
                    cash += pos.pop(t)["sh"]*S[t][i]*(1-COST)
            eq = cash + sum(p["sh"]*S[t][i] for t,p in pos.items())
            if picks:
                raw = {t: 1/v for t,v,_ in picks}
                tot = sum(raw.values())
                wts = {t: max(MINW, min(MAXW, raw[t]/tot)) for t,_,_ in picks}
                sw = sum(wts.values())
                scale = min(1.0, len(picks)/NPOS)
                wts = {t: w/sw*scale for t,w in wts.items()}
                for t,v,p in picks:
                    tgt = eq*wts[t]
                    cur = pos.get(t)
                    cv = cur["sh"]*p if cur else 0
                    if cur and abs(tgt-cv)/max(tgt,1) < 0.20: continue
                    if cur: cash += pos.pop(t)["sh"]*p*(1-COST)
                    spend = min(tgt, max(0.0, cash))
                    if spend > 1:
                        cash -= spend
                        pos[t] = {"sh": spend*(1-COST)/p}
        eq = cash + sum(p["sh"]*S[t][i] for t,p in pos.items() if S[t][i])
        curve.append(eq); nheld.append(len(pos))
    return curve, nheld

def stats(v):
    yrs = len(v)/W; mult = v[-1]/v[0]
    peak, mdd = v[0], 0.0
    for x in v:
        peak = max(peak,x); mdd = min(mdd, x/peak-1)
    dr = [v[i]/v[i-1]-1 for i in range(1,len(v))]
    m = sum(dr)/len(dr)
    sd = math.sqrt(sum((x-m)**2 for x in dr)/(len(dr)-1))
    cagr = (mult**(1/yrs)-1)*100
    return cagr, mdd*100, (m*W)/(sd*math.sqrt(W)), cagr/abs(mdd*100) if mdd else 0

curve, nheld = run()
print(f"\n{'':<22}{'CAGR':>8}{'MaxDD':>9}{'Sharpe':>8}{'Calmar':>8}")
c, d, s, k = stats(curve)
print(f"{'Paper strategy':<22}{c:>7.1f}%{d:>8.1f}%{s:>8.2f}{k:>8.2f}")
for b in ("SPY","QQQ"):
    if b in S:
        bc = [x for x in S[b][MINH:] if x]
        cc, dd, ss, kk = stats(bc)
        print(f"{b+' buy & hold':<22}{cc:>7.1f}%{dd:>8.1f}%{ss:>8.2f}{kk:>8.2f}")
print(f"\naverage positions held: {sum(nheld)/len(nheld):.1f} of {NPOS}")
print(f"fully-invested weeks:   {sum(1 for n in nheld if n>=NPOS)/len(nheld)*100:.0f}%")
print(f"weeks with <5 holdings: {sum(1 for n in nheld if n<5)/len(nheld)*100:.0f}%  (risk-off)")

# calendar-year returns
print("\nby calendar year")
yr = {}
for i, d0 in enumerate(dates[MINH:]):
    yr.setdefault(d0[:4], []).append(curve[i])
sp = {}
for i, d0 in enumerate(dates[MINH:]):
    if S.get("SPY") and S["SPY"][MINH+i]: sp.setdefault(d0[:4], []).append(S["SPY"][MINH+i])
for y in sorted(yr):
    a = yr[y]; r = (a[-1]/a[0]-1)*100
    b = sp.get(y); rb = (b[-1]/b[0]-1)*100 if b and len(b)>1 else float('nan')
    print(f"  {y}  strategy {r:>7.1f}%   SPY {rb:>7.1f}%   {'+' if r>rb else '-'}{abs(r-rb):.1f} pts")

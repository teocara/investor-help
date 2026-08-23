"""Rebalance frequency against transaction costs.

More frequent rebalancing reacts faster to the ranking but pays for it in
turnover. The question is where the crossover sits, so the frequency is
chosen on evidence rather than preference.

Same survivorship caveat as everything else here: the universe is today's
watchlist, so absolute numbers are inflated. The COMPARISON across
frequencies is what carries information, since every row shares the bias.
"""
import json, glob, math, os, re, statistics as st

W = 52
NPOS, MAXW, MINW, MAXSEC = 15, 0.15, 0.02, 0.40
MINH = round(300/252*W)
TREND = round(200/252*W)
LB12, SK1 = W, round(21/252*W)
EXCLUDE = {"TQQQ","SQQQ","QLD","PSQ","LQQ.PA","EURUSD=X","UVXY","SOXL","SOXS"}

html = open("/home/user/investor-help/investor-dashboard.html", encoding="utf-8").read()
SEC, seen = {}, set()
for t, s in re.findall(r'ticker:"([^"]+)"[^}]*?sector:"([^"]*)"', html):
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
def ser(t):
    m = PX[t]; out, last = [], None
    for d in dates:
        last = m.get(d, last); out.append(last)
    return out
S = {t: ser(t) for t in PX}
print(f"{len(S)} strumenti, {len(dates)} barre settimanali "
      f"{dates[0]} -> {dates[-1]} ({len(dates)/W:.1f} anni)\n")

def sma_at(c, i, n):
    w = [x for x in c[max(0,i-n+1):i+1] if x]
    return sum(w)/len(w) if len(w) >= n*0.8 else None
def mom(c, i):
    a, b = c[i-LB12] if i >= LB12 else None, c[i-SK1]
    return None if not a or not b or a <= 0 else b/a - 1
def vol_at(c, i, n=round(60/252*W)):
    r = [math.log(c[j]/c[j-1]) for j in range(max(1,i-n+1), i+1) if c[j] and c[j-1]]
    if len(r) < 8: return None
    m = sum(r)/len(r)
    return math.sqrt(sum((x-m)**2 for x in r)/(len(r)-1)*W)

def run(every, cost, drift_band=0.20):
    cash, pos = 100000.0, {}
    curve, fees, ntrade = [], 0.0, 0
    last_rb = -99
    for i in range(MINH, len(dates)):
        for t in list(pos):                       # weekly trend stop
            c = S[t]
            m = sma_at(c, i, TREND)
            if c[i] and m and c[i] <= m:
                v = pos.pop(t)["sh"]*c[i]
                fees += v*cost; ntrade += 1
                cash += v*(1-cost)
        if i - last_rb >= every:
            last_rb = i
            ranked = []
            for t in SEC:
                if t not in S: continue
                c = S[t]
                if not c[i]: continue
                mm = mom(c, i)
                if mm is None or mm <= 0: continue
                sm = sma_at(c, i, TREND)
                if not sm or c[i] <= sm: continue
                v = vol_at(c, i)
                if not v or v <= 0: continue
                ranked.append((mm, t, v, c[i]))
            ranked.sort(reverse=True)
            picks, per = [], {}
            cap = max(1, int(NPOS*MAXSEC))
            for mm, t, v, p in ranked:
                s = SEC.get(t,"Unknown")
                if per.get(s,0) >= cap: continue
                picks.append((t,v,p)); per[s] = per.get(s,0)+1
                if len(picks) >= NPOS: break
            keep = {t for t,_,_ in picks}
            for t in list(pos):
                if t not in keep:
                    v = pos.pop(t)["sh"]*S[t][i]
                    fees += v*cost; ntrade += 1
                    cash += v*(1-cost)
            eq = cash + sum(p["sh"]*S[t][i] for t,p in pos.items() if S[t][i])
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
                    if cur and abs(tgt-cv)/max(tgt,1) < drift_band: continue
                    if cur:
                        val = pos.pop(t)["sh"]*p
                        fees += val*cost; ntrade += 1
                        cash += val*(1-cost)
                    spend = min(tgt, max(0.0, cash))
                    if spend > 1:
                        fees += spend*cost; ntrade += 1
                        cash -= spend; pos[t] = {"sh": spend*(1-cost)/p}
        eq = cash + sum(p["sh"]*S[t][i] for t,p in pos.items() if S[t][i])
        curve.append(eq)
    return curve, fees, ntrade

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

FREQ = [(1,"settimanale"),(2,"ogni 2 settimane"),(4,"mensile (attuale)"),(8,"ogni 2 mesi")]
COSTS = [(0.0,"0 bps"),(0.0005,"5 bps"),(0.001,"10 bps"),(0.002,"20 bps"),(0.005,"50 bps")]

print("CAGR per frequenza di ribilanciamento x costo per eseguito")
print(f"{'frequenza':<20}" + "".join(f"{lbl:>10}" for _,lbl in COSTS) + f"{'trade/anno':>12}")
print("-"*(20+10*len(COSTS)+12))
rows = {}
for every, name in FREQ:
    line, base_n = [], None
    for cost, _ in COSTS:
        c, fees, n = run(every, cost)
        a,b,s,k = stats(c)
        line.append(a)
        if base_n is None: base_n = n
        rows[(every,cost)] = (a,b,s,k,fees,n)
    yrs = (len(dates)-MINH)/W
    print(f"{name:<20}" + "".join(f"{v:>9.1f}%" for v in line) + f"{base_n/yrs:>12.0f}")

print("\nA 5 bps — profilo di rischio completo")
print(f"{'frequenza':<20}{'CAGR':>8}{'MaxDD':>9}{'Sharpe':>8}{'Calmar':>8}{'costi tot':>12}{'trade/anno':>12}")
print("-"*77)
yrs = (len(dates)-MINH)/W
for every, name in FREQ:
    a,b,s,k,fees,n = rows[(every,0.0005)]
    print(f"{name:<20}{a:>7.1f}%{b:>8.1f}%{s:>8.2f}{k:>8.2f}{'$'+format(round(fees),','):>12}{n/yrs:>12.0f}")

print("\nquanto costa passare da mensile a settimanale (punti di CAGR)")
for cost, lbl in COSTS:
    wk = rows[(1,cost)][0]; mo = rows[(4,cost)][0]
    print(f"  a {lbl:<8} settimanale {wk:>6.1f}%  vs mensile {mo:>6.1f}%   differenza {wk-mo:>+5.1f}")

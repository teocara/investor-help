"""Parameter sensitivity: is the trend+volatility filter a broad plateau or a
single lucky cell? A result that only works at one parameter value is an
artefact; one that works across a contiguous region is a real effect."""
import json, math
exec(open("/tmp/claude-0/-home-user-investor-help/345b4408-9ee1-5a20-ba7d-375a70838d96/scratchpad/stress2.py")
     .read().split('report("1999')[0])

dts = [d for d in dates if d >= "1999-03-10"]
qv = [qq[d] for d in dts]
VOLS = {n: rvol(qv, n) for n in (10, 20, 40, 60)}
MAS = {n: sma(qv, n) for n in (100, 150, 200, 250, 300)}

def build(ma_n, vol_n, thr):
    MA, VOL = MAS[ma_n], VOLS[vol_n]
    def f(i):
        if MA[i] is None or qv[i] <= MA[i]:
            return {}
        v = VOL[vol_n and i]
        return {'3x': 1} if v is not None and v < thr else {}
    return f

print("FULL CYCLE 1999-2026 — CAGR % by MA length x volatility threshold")
print("(20-day realized vol, cash when filtered out, 5bps per switch)\n")
thrs = [0.18, 0.20, 0.22, 0.25, 0.28, 0.30, 0.35, 0.40, 0.50, 9.9]
print(f"{'MA':>5}" + "".join(f"{('<'+str(int(t*100))+'%') if t<9 else 'none':>8}" for t in thrs))
print("-"*(5+8*len(thrs)))
best = []
for ma_n in (100, 150, 200, 250, 300):
    row = []
    for t in thrs:
        s = stats(backtest(dts, build(ma_n, 20, t)))
        row.append(s['cagr'])
        best.append((s['cagr'], s['mdd'], s['calmar'], ma_n, t))
    print(f"{ma_n:>5}" + "".join(f"{v:>7.1f}%" for v in row))

print("\nFULL CYCLE 1999-2026 — MaxDD % by MA length x volatility threshold\n")
print(f"{'MA':>5}" + "".join(f"{('<'+str(int(t*100))+'%') if t<9 else 'none':>8}" for t in thrs))
print("-"*(5+8*len(thrs)))
for ma_n in (100, 150, 200, 250, 300):
    row = []
    for t in thrs:
        s = stats(backtest(dts, build(ma_n, 20, t)))
        row.append(s['mdd'])
    print(f"{ma_n:>5}" + "".join(f"{v:>7.0f}%" for v in row))

print("\ntop 10 cells by Calmar (full cycle):")
best.sort(key=lambda r: -r[2])
for c, m, cal, n, t in best[:10]:
    print(f"  MA{n:<4} vol<{t*100:>4.0f}%   CAGR {c:5.1f}%   MaxDD {m:6.1f}%   Calmar {cal:.2f}")

print("\nvolatility lookback sensitivity (MA200, threshold 30%):")
for vn in (10, 20, 40, 60):
    MA, VOL = MAS[200], VOLS[vn]
    def f(i, MA=MA, VOL=VOL):
        if MA[i] is None or qv[i] <= MA[i]: return {}
        v = VOL[i]
        return {'3x':1} if v is not None and v < 0.30 else {}
    s = stats(backtest(dts, f))
    print(f"  vol lookback {vn:>3}d   CAGR {s['cagr']:5.1f}%   MaxDD {s['mdd']:6.1f}%   Calmar {s['calmar']:.2f}")

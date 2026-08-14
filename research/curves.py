import json, math
exec(open("/tmp/claude-0/-home-user-investor-help/345b4408-9ee1-5a20-ba7d-375a70838d96/scratchpad/stress2.py")
     .read().split('report("1999')[0])

dts = [d for d in dates if d >= "1999-03-10"]
qv = [qq[d] for d in dts]
MA200, MA150 = sma(qv, 200), sma(qv, 150)
VOL = rvol(qv, 20)

def A(i):  # buy & hold QQQ
    return {'1x': 1}
def B(i):  # buy & hold 3x
    return {'3x': 1}
def C(i):  # 200d trend only
    return {'3x': 1} if MA200[i] and qv[i] > MA200[i] else {}
def D(i):  # 200d + vol<35%
    if not (MA200[i] and qv[i] > MA200[i]): return {}
    return {'3x': 1} if VOL[i] is not None and VOL[i] < 0.35 else {}
def E(i):  # 150d + vol<30%
    if not (MA150[i] and qv[i] > MA150[i]): return {}
    return {'3x': 1} if VOL[i] is not None and VOL[i] < 0.30 else {}

names = ["QQQ 1x", "TQQQ 3x buy&hold", "200d trend only", "200d + vol<35%", "150d + vol<30%"]
fns = [A, B, C, D, E]
out = {}
for nm, fn in zip(names, fns):
    c = backtest(dts, fn)
    out[nm] = c

# monthly samples to keep the payload small
labels = dts[250:250+len(out[names[0]])]
step = 21
idxs = list(range(0, len(labels), step))
if idxs[-1] != len(labels) - 1:
    idxs.append(len(labels) - 1)          # always include the final bar
series = {nm: [round(c[i], 6) for i in idxs] for nm, c in out.items()}
lbl = [labels[i] for i in idxs]
json.dump({"dates": lbl, "series": series},
          open("/tmp/claude-0/-home-user-investor-help/345b4408-9ee1-5a20-ba7d-375a70838d96/scratchpad/curves.json", "w"))
print("points:", len(lbl))
for nm, c in out.items():
    s = stats(c)
    print(f"{nm:<22}{s['mult']:>10.2f}x{s['cagr']:>8.1f}%{s['mdd']:>9.1f}%{s['sharpe']:>7.2f}{s['calmar']:>7.2f}")

# calendar year returns for the top pick vs TQQQ
print("\ncalendar-year returns (%)")
years = sorted({d[:4] for d in labels})
def yearly(c):
    res = {}
    prev = None
    for i, d in enumerate(labels):
        y = d[:4]
        res.setdefault(y, [None, None])
        if res[y][0] is None: res[y][0] = c[i]
        res[y][1] = c[i]
    return {y: (v[1]/v[0]-1)*100 for y, v in res.items() if v[0]}
ya, yb, yd = yearly(out["QQQ 1x"]), yearly(out["TQQQ 3x buy&hold"]), yearly(out["200d + vol<35%"])
print(f"{'yr':<6}{'QQQ':>9}{'TQQQ B&H':>11}{'200d+vol':>11}")
for y in years:
    print(f"{y:<6}{ya.get(y,0):>8.0f}%{yb.get(y,0):>10.0f}%{yd.get(y,0):>10.0f}%")

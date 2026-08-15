"""Fetch daily history for the leveraged-ETF study.

Leveraged ETFs reset exposure daily, so their path dependency (volatility
decay) only shows up correctly at daily resolution — the weekly files the
dashboard uses would understate it badly. This pulls full daily history for
the QQQ family plus a short-rate proxy for financing costs, and writes one
compact JSON for offline analysis.

Run via the "Leveraged study data" workflow (workflow_dispatch).
"""

import json
from pathlib import Path

import yfinance as yf

TICKERS = {
    "QQQ":  "Nasdaq-100 ETF (1x)",
    "TQQQ": "ProShares UltraPro QQQ (3x)",
    "SQQQ": "ProShares UltraPro Short QQQ (-3x)",
    "QLD":  "ProShares Ultra QQQ (2x)",
    "PSQ":  "ProShares Short QQQ (-1x)",
    "^IRX": "13-week T-bill discount rate (financing proxy)",
    "^VXN": "Nasdaq-100 volatility index",
    # European UCITS equivalents — the only leveraged Nasdaq exposure an
    # EU/EEA retail investor can actually buy (TQQQ has no PRIIPs KID).
    "LQQ.PA":  "Amundi Nasdaq-100 Daily (2x) Leveraged UCITS ETF, EUR (Paris)",
    "LQQ.MI":  "Same fund, Milan listing",
    "CL2.PA":  "Amundi MSCI USA Daily (2x) Leveraged UCITS ETF, EUR",
    "EURUSD=X": "EUR/USD spot — DKK is pegged to EUR, so this is the FX leg",
    "DKKUSD=X": "DKK/USD spot",
}

def despike(rows, thresh=0.45):
    """Drop isolated bad prints — an extreme move undone by the next bar.
    Several Euronext listings carry these; rescaling around them as if they
    were splits corrupts the entire series."""
    n = 0
    for i in range(1, len(rows) - 1):
        a, b, c = rows[i-1]["c"], rows[i]["c"], rows[i+1]["c"]
        if min(a, b, c) <= 0:
            continue
        r1, r2 = b/a - 1, c/b - 1
        if abs(r1) > thresh and abs(r2) > thresh and r1*r2 < 0 and abs(c/a - 1) < 0.25:
            rows[i]["c"] = round((a + c)/2, 6)
            n += 1
    return n


def fix_splits(rows, ref, thresh=0.45):
    """Repair share splits yfinance failed to adjust. LQQ.PA carries an
    unadjusted ~205:1 split on 2015-01-02 which, left alone, reads as a 99.5%
    single-day loss. A real move shows up in the underlying index too, so the
    index is used to tell corporate actions from price action."""
    notes = []
    for i in range(1, len(rows)):
        prev, cur = rows[i-1]["c"], rows[i]["c"]
        if min(prev, cur) <= 0:
            continue
        r = cur/prev - 1
        if abs(r) < thresh:
            continue
        a, b = ref.get(rows[i]["t"]), ref.get(rows[i-1]["t"])
        if a and b and abs(a/b - 1) > abs(r)/4:
            continue                      # corroborated by the index: real
        factor = cur/prev
        for j in range(i):
            rows[j]["c"] = round(rows[j]["c"]*factor, 6)
        notes.append({"date": rows[i]["t"], "ratio": round(1/factor, 4)})
    return notes


out = {}

for ticker, desc in TICKERS.items():
    try:
        df = yf.download(
            ticker, period="max", interval="1d",
            auto_adjust=True, progress=False, threads=False,
        )
        if df is None or df.empty:
            print(f"  {ticker}: EMPTY")
            continue
        # yfinance may return single- or multi-level columns
        close = df["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        close = close.dropna()

        rows = [
            {"t": dt.strftime("%Y-%m-%d"), "c": round(float(v), 4)}
            for dt, v in close.items()
        ]
        entry = {"desc": desc, "rows": rows}
        # QQQ is the reference and is clean; repair the rest against it
        if ticker != "QQQ" and "QQQ" in out and not ticker.endswith("=X"):
            ref = {r["t"]: r["c"] for r in out["QQQ"]["rows"]}
            spikes = despike(rows)
            splits = fix_splits(rows, ref)
            if spikes:
                entry["despiked"] = spikes
            if splits:
                entry["split_adjusted"] = splits
                for s in splits:
                    print(f"    repaired {s['ratio']}:1 split on {s['date']}")
            if spikes:
                print(f"    removed {spikes} isolated bad tick(s)")
        out[ticker] = entry
        print(f"  {ticker}: {len(rows)} rows  {rows[0]['t']} -> {rows[-1]['t']}")
    except Exception as e:
        print(f"  {ticker}: FAILED {e}")

Path("public/study").mkdir(parents=True, exist_ok=True)
Path("public/study/leveraged.json").write_text(
    json.dumps(out, separators=(",", ":")), encoding="utf-8"
)
print(f"wrote public/study/leveraged.json with {len(out)} series")

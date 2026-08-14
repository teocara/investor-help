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
}

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
        out[ticker] = {"desc": desc, "rows": rows}
        print(f"  {ticker}: {len(rows)} rows  {rows[0]['t']} -> {rows[-1]['t']}")
    except Exception as e:
        print(f"  {ticker}: FAILED {e}")

Path("public/study").mkdir(parents=True, exist_ok=True)
Path("public/study/leveraged.json").write_text(
    json.dumps(out, separators=(",", ":")), encoding="utf-8"
)
print(f"wrote public/study/leveraged.json with {len(out)} series")

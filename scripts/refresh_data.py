"""
Nightly data refresh — fetches prices, fundamentals, and 2-year OHLCV
for every ticker in investor-dashboard.html using yfinance, then writes:
  public/quotes.json        — prices + fundamentals for all tickers
  public/ohlcv/<TICKER>.json — 2-year daily OHLCV per ticker
"""

import json
import math
import re
import datetime
import os
from pathlib import Path

import pandas as pd
import yfinance as yf

# ── Helpers ──────────────────────────────────────────────────────────────

def safe(v, decimals=2):
    """Round a value; return None if missing/NaN/Inf."""
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, decimals)
    except Exception:
        return None

def compute_rsi(closes, n=14):
    """Wilder RSI on a plain list of close prices."""
    if len(closes) < n + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    ag = sum(max(0.0, d) for d in deltas[-n:]) / n
    al = sum(max(0.0, -d) for d in deltas[-n:]) / n
    if al == 0:
        return 100.0
    return round(100.0 - 100.0 / (1.0 + ag / al), 1)

def range_to_cutoff(days):
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    return cutoff.isoformat()

# ── Read tickers from dashboard ──────────────────────────────────────────

html = Path("investor-dashboard.html").read_text(encoding="utf-8")
tickers = list(dict.fromkeys(re.findall(r'ticker:"([^"]+)"', html)))
print(f"Found {len(tickers)} tickers")

# ── Batch OHLCV download (2 years daily) ─────────────────────────────────

print("Downloading 2-year OHLCV (batch)…")
raw_hist = yf.download(
    tickers,
    period="2y",
    interval="1d",
    auto_adjust=True,
    threads=True,
    progress=False,
)
print("  download complete")

# yf.download returns MultiIndex (metric, ticker) when >1 tickers
multi = len(tickers) > 1

def get_series(metric, ticker):
    try:
        if multi:
            return raw_hist[metric][ticker].dropna()
        return raw_hist[metric].dropna()
    except Exception:
        return pd.Series(dtype=float)

# ── Per-ticker fundamentals (individual Ticker.info) ─────────────────────

Path("public/ohlcv").mkdir(parents=True, exist_ok=True)

quotes = {}
ohlcv_errors = []

for i, ticker in enumerate(tickers):
    try:
        closes_s = get_series("Close", ticker)
        opens_s  = get_series("Open",  ticker)
        highs_s  = get_series("High",  ticker)
        lows_s   = get_series("Low",   ticker)
        vols_s   = get_series("Volume",ticker)

        close_list = closes_s.tolist()

        # ── OHLCV file ────────────────────────────────────────────────────
        rows = []
        for dt, c in closes_s.items():
            date_str = dt.strftime("%Y-%m-%d")
            o = safe(opens_s.get(dt), 2)
            h = safe(highs_s.get(dt), 2)
            l = safe(lows_s.get(dt), 2)
            cl = safe(c, 2)
            v = int(vols_s.get(dt, 0) or 0)
            if cl is None:
                continue
            rows.append({"time": date_str, "open": o or cl,
                         "high": h or cl, "low": l or cl,
                         "close": cl, "volume": v})
        if rows:
            Path(f"public/ohlcv/{ticker}.json").write_text(
                json.dumps(rows, separators=(",", ":")), encoding="utf-8"
            )

        # ── Fundamentals ──────────────────────────────────────────────────
        info = {}
        try:
            info = yf.Ticker(ticker).info or {}
        except Exception:
            pass

        last_price = safe(close_list[-1], 2) if close_list else None
        prev_price = safe(close_list[-2], 2) if len(close_list) > 1 else None
        chg_pct = safe((last_price / prev_price - 1) * 100, 2) \
            if last_price and prev_price else None

        rsi = compute_rsi(close_list)

        pe     = safe(info.get("trailingPE"), 1)
        fwd_pe = safe(info.get("forwardPE"), 1)
        peg    = safe(info.get("pegRatio"), 2)
        eps_g  = safe((info.get("earningsGrowth") or 0) * 100, 1) \
                 if info.get("earningsGrowth") is not None else None
        rev_g  = safe((info.get("revenueGrowth") or 0) * 100, 1) \
                 if info.get("revenueGrowth") is not None else None
        roe    = safe((info.get("returnOnEquity") or 0) * 100, 1) \
                 if info.get("returnOnEquity") is not None else None
        de     = safe((info.get("debtToEquity") or 0) / 100, 2) \
                 if info.get("debtToEquity") is not None else None
        div_y  = safe(info.get("dividendYield"), 4)
        h52    = safe(info.get("fiftyTwoWeekHigh"), 2)
        l52    = safe(info.get("fiftyTwoWeekLow"), 2)
        mcap   = safe((info.get("marketCap") or 0) / 1e9, 1) \
                 if info.get("marketCap") else None

        quotes[ticker] = {
            "price":    last_price,
            "chgPct":   chg_pct,
            "rsi":      rsi,
            "pe":       pe,
            "fwdPe":    fwd_pe,
            "peg":      peg,
            "eps_growth": eps_g,
            "rev_growth": rev_g,
            "roe":      roe,
            "debt_equity": de,
            "divYield": div_y,
            "high52":   h52,
            "low52":    l52,
            "market_cap_b": mcap,
        }

        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(tickers)} done")

    except Exception as e:
        print(f"  ERROR {ticker}: {e}")
        ohlcv_errors.append(ticker)
        quotes[ticker] = {}

# ── Write quotes.json ─────────────────────────────────────────────────────

output = {
    "updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "tickers": quotes,
}
Path("public/quotes.json").write_text(
    json.dumps(output, separators=(",", ":")), encoding="utf-8"
)

ok  = len(quotes) - len(ohlcv_errors)
print(f"\nDone: {ok}/{len(tickers)} successful, {len(ohlcv_errors)} errors")
if ohlcv_errors:
    print("  Failed:", ", ".join(ohlcv_errors))

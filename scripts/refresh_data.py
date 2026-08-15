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

# Instruments the backtester needs that are not watchlist rows. LQQ is the
# European 2x Nasdaq UCITS ETF — the only leveraged Nasdaq exposure an EU/EEA
# retail investor can buy, since TQQQ has no PRIIPs KID.
EXTRA_TICKERS = ["LQQ.PA", "EURUSD=X"]
for t in EXTRA_TICKERS:
    if t not in tickers:
        tickers.append(t)
print(f"Found {len(tickers)} tickers ({len(EXTRA_TICKERS)} extra)")

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

# ── Batch long-history download (full history, weekly) ───────────────────
# Daily bars for 20+ years would be ~140 MB across all tickers and the file
# set is rewritten on every nightly run, so long history is stored weekly.
# ~1k rows per ticker instead of ~5k, at a resolution that is appropriate
# for multi-year charting and backtesting anyway.

print("Downloading full-history weekly OHLCV (batch)…")
try:
    raw_long = yf.download(
        tickers,
        period="max",
        interval="1wk",
        auto_adjust=True,
        threads=True,
        progress=False,
    )
    print("  long-history download complete")
except Exception as e:
    print(f"  long-history download FAILED: {e}")
    raw_long = None

# yf.download returns MultiIndex (metric, ticker) when >1 tickers
multi = len(tickers) > 1

def _series(frame, metric, ticker):
    try:
        if frame is None:
            return pd.Series(dtype=float)
        if multi:
            return frame[metric][ticker].dropna()
        return frame[metric].dropna()
    except Exception:
        return pd.Series(dtype=float)

def get_series(metric, ticker):
    return _series(raw_hist, metric, ticker)

def get_long_series(metric, ticker):
    return _series(raw_long, metric, ticker)

def repair_rows(rows, ref, thresh=0.45):
    """Fix data defects yfinance leaves in some non-US listings: isolated bad
    prints, and share splits it failed to adjust (LQQ.PA carries a ~205:1
    split on 2015-01-02 that otherwise reads as a 99.5% one-day loss).
    A genuine price move is corroborated by the underlying index."""
    for i in range(1, len(rows) - 1):                    # isolated bad ticks
        a, b, c = rows[i-1]["close"], rows[i]["close"], rows[i+1]["close"]
        if min(a, b, c) <= 0:
            continue
        r1, r2 = b/a - 1, c/b - 1
        if abs(r1) > thresh and abs(r2) > thresh and r1*r2 < 0 and abs(c/a - 1) < 0.25:
            mid = round((a + c)/2, 2)
            rows[i].update(open=mid, high=mid, low=mid, close=mid)
    for i in range(1, len(rows)):                        # unadjusted splits
        prev, cur = rows[i-1]["close"], rows[i]["close"]
        if min(prev, cur) <= 0 or abs(cur/prev - 1) < thresh:
            continue
        a, b = ref.get(rows[i]["time"]), ref.get(rows[i-1]["time"])
        if a and b and abs(a/b - 1) > abs(cur/prev - 1)/4:
            continue
        f = cur/prev
        for j in range(i):
            for k in ("open", "high", "low", "close"):
                rows[j][k] = round(rows[j][k]*f, 4)
    return rows


def build_rows(closes_s, opens_s, highs_s, lows_s, vols_s):
    """Assemble OHLCV dicts, skipping bars with no usable close."""
    out = []
    for dt, c in closes_s.items():
        cl = safe(c, 2)
        if cl is None:
            continue
        out.append({
            "time": dt.strftime("%Y-%m-%d"),
            "open": safe(opens_s.get(dt), 2) or cl,
            "high": safe(highs_s.get(dt), 2) or cl,
            "low": safe(lows_s.get(dt), 2) or cl,
            "close": cl,
            "volume": int(vols_s.get(dt, 0) or 0),
        })
    return out

# ── Per-ticker fundamentals (individual Ticker.info) ─────────────────────

Path("public/ohlcv").mkdir(parents=True, exist_ok=True)
Path("public/ohlcv-long").mkdir(parents=True, exist_ok=True)

quotes = {}
ohlcv_errors = []

# QQQ is a clean US listing and serves as the reference for detecting
# corporate actions in the non-US tickers.
_qq = get_series("Close", "QQQ")
QQQ_REF = {dt.strftime("%Y-%m-%d"): float(v) for dt, v in _qq.items()} if len(_qq) else {}
_qql = get_long_series("Close", "QQQ")
QQQ_REF_LONG = {dt.strftime("%Y-%m-%d"): float(v) for dt, v in _qql.items()} if len(_qql) else {}

for i, ticker in enumerate(tickers):
    try:
        closes_s = get_series("Close", ticker)
        opens_s  = get_series("Open",  ticker)
        highs_s  = get_series("High",  ticker)
        lows_s   = get_series("Low",   ticker)
        vols_s   = get_series("Volume",ticker)

        close_list = closes_s.tolist()

        # ── OHLCV file (2y daily) ─────────────────────────────────────────
        rows = build_rows(closes_s, opens_s, highs_s, lows_s, vols_s)
        if rows and "." in ticker and QQQ_REF:
            rows = repair_rows(rows, QQQ_REF)      # non-US listings only
        if rows:
            Path(f"public/ohlcv/{ticker}.json").write_text(
                json.dumps(rows, separators=(",", ":")), encoding="utf-8"
            )

        # ── Long-history file (max weekly) ────────────────────────────────
        long_rows = build_rows(
            get_long_series("Close",  ticker),
            get_long_series("Open",   ticker),
            get_long_series("High",   ticker),
            get_long_series("Low",    ticker),
            get_long_series("Volume", ticker),
        )
        if long_rows and "." in ticker and QQQ_REF_LONG:
            long_rows = repair_rows(long_rows, QQQ_REF_LONG)
        if len(long_rows) > 26:
            Path(f"public/ohlcv-long/{ticker}.json").write_text(
                json.dumps(long_rows, separators=(",", ":")), encoding="utf-8"
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

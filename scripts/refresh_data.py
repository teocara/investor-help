"""
Nightly data refresh — fetches prices, fundamentals and OHLCV for every
ticker in investor-dashboard.html using yfinance, then writes:
  public/quotes.json              — prices + fundamentals for all tickers
  public/ohlcv/<TICKER>.json      — 3-year daily OHLCV per ticker
  public/ohlcv-long/<TICKER>.json — full history, weekly, per ticker
"""

import json
import math
import re
import sys
import time
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

# Market cap comes back in the LISTING's currency. Left unconverted, the
# "largest 40 companies" heatmap and the scatter axes compare yen-billions
# with dollar-billions, which ranks Shin-Etsu (10,790 JPY bn) above Apple
# (4,977 USD bn) purely because the yen is a smaller unit. Every cap is
# normalised to USD before it is written, so the field means one thing.
FX_PAIRS = {
    "EUR": "EURUSD=X", "GBP": "GBPUSD=X", "GBp": "GBPUSD=X",
    "JPY": "JPYUSD=X", "CHF": "CHFUSD=X", "HKD": "HKDUSD=X",
    "CAD": "CADUSD=X", "AUD": "AUDUSD=X", "SEK": "SEKUSD=X",
    "DKK": "DKKUSD=X", "NOK": "NOKUSD=X", "KRW": "KRWUSD=X",
    "TWD": "TWDUSD=X", "INR": "INRUSD=X", "BRL": "BRLUSD=X",
    "MXN": "MXNUSD=X", "SAR": "SARUSD=X", "SGD": "SGDUSD=X",
    "USD": None,
}
for _pair in {v for v in FX_PAIRS.values() if v}:
    if _pair not in EXTRA_TICKERS:
        EXTRA_TICKERS.append(_pair)
for t in EXTRA_TICKERS:
    if t not in tickers:
        tickers.append(t)
print(f"Found {len(tickers)} tickers ({len(EXTRA_TICKERS)} extra)")

# ── Batch OHLCV download (3 years daily) ─────────────────────────────────
# Three years rather than two so a 2-year chart still has a full 250-bar
# warmup behind it for the long moving average.

print("Downloading 3-year OHLCV (batch)…")
raw_hist = yf.download(
    tickers,
    period="3y",
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

# ── FX rates, for normalising market cap ─────────────────────────────────
# Read out of the batch that was just downloaded, so no extra requests and
# the rate is from the same session as the prices it converts.
fx_to_usd = {"USD": 1.0}

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

def _populate_fx():
    """Fill fx_to_usd from the batch. Falls back to the inverted pair.

    Yahoo carries both directions for most crosses but not reliably, so a
    missing JPYUSD is recovered from USDJPY rather than silently leaving
    every Japanese market cap blank.
    """
    for cur, pair in FX_PAIRS.items():
        if not pair or cur in fx_to_usd:
            continue
        rate = None
        ser = _series(raw_hist, "Close", pair)
        if len(ser):
            rate = float(ser.iloc[-1])
        if not rate or rate <= 0:
            inv = f"USD{cur[:3].upper()}=X"
            ser = _series(raw_hist, "Close", inv)
            if len(ser) and float(ser.iloc[-1]) > 0:
                rate = 1.0 / float(ser.iloc[-1])
        if rate and rate > 0:
            fx_to_usd[cur] = rate
    # London quotes in PENCE. Whether a given field comes back in pence or
    # pounds is not consistent, so GBp is carried as its own rate rather
    # than folded into GBP by upper-casing.
    if "GBP" in fx_to_usd:
        fx_to_usd["GBp"] = fx_to_usd["GBP"] / 100.0


def get_series(metric, ticker):
    return _series(raw_hist, metric, ticker)

def get_long_series(metric, ticker):
    return _series(raw_long, metric, ticker)

_populate_fx()
print(f"FX rates resolved: {len(fx_to_usd)-1} currencies")

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
info_ok = 0
info_failed = []
carried = 0

# The previous snapshot, so a ticker whose fundamentals cannot be fetched
# keeps the ones it had rather than being blanked. Valuation fields move
# quarterly; a day-old P/E is worth far more than a null, and the fourth
# paper book reads pe/peg/eps_growth straight off this file to build its
# signal. Without this, one bad night silently rewrites what that book
# thinks it is looking at.
prev_quotes = {}
try:
    _p = Path("public/quotes.json")
    if _p.exists():
        prev_quotes = (json.loads(_p.read_text()) or {}).get("tickers", {})
        print(f"carry-forward source: {len(prev_quotes)} tickers "
              "from the previous snapshot")
except Exception as e:
    print(f"  could not read the previous snapshot ({e}) — "
          "fundamentals cannot be carried forward this run")

CARRY = ["pe", "fwdPe", "peg", "eps_growth", "rev_growth", "roe",
         "debt_equity", "divYield", "high52", "low52", "market_cap_b"]

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

        # ── OHLCV file (3y daily) ─────────────────────────────────────────
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
        # Retried, because a single transient refusal used to blank every
        # valuation field for that ticker. With ~900 tickers the source
        # throttles, and on 2026-09-30 it refused ALL of them: the job
        # still exited 0 and committed a quotes.json with every P/E, PEG,
        # market cap and 52-week range null. Nothing noticed, because the
        # failure was swallowed by a bare except.
        info = {}
        for attempt in range(3):
            try:
                info = yf.Ticker(ticker).info or {}
                if info:
                    break
            except Exception:
                pass
            time.sleep(0.4 * (attempt + 1))
        if info:
            info_ok += 1
        else:
            info_failed.append(ticker)

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
        # Normalise to USD billions. If the rate is missing the cap is
        # dropped rather than written in the wrong unit — a blank cell is
        # honest, a number that means yen while the column says dollars
        # is not.
        mcap = None
        if info.get("marketCap"):
            cur = info.get("currency") or "USD"
            rate = fx_to_usd.get(cur) or fx_to_usd.get(cur.upper())
            if rate:
                mcap = safe(info["marketCap"] * rate / 1e9, 1)

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

        # Anything the fetch could not supply keeps its previous value.
        # Price, chgPct and RSI are deliberately NOT carried forward: they
        # come from the batch download, which either works or leaves the
        # ticker genuinely unpriced, and a stale price is actively
        # misleading in a way a stale P/E is not.
        was = prev_quotes.get(ticker) or {}
        for field in CARRY:
            if quotes[ticker].get(field) is None and was.get(field) is not None:
                quotes[ticker][field] = was[field]
                carried += 1

        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(tickers)} done")

    except Exception as e:
        print(f"  ERROR {ticker}: {e}")
        ohlcv_errors.append(ticker)
        quotes[ticker] = {}

# ── Write quotes.json ─────────────────────────────────────────────────────

fresh_rate = info_ok / len(tickers) if tickers else 0.0

output = {
    "updated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    # Recorded so staleness is auditable from the file itself rather than
    # only from a log nobody reads.
    "fundamentals": {
        "fresh": info_ok,
        "carried_forward": carried,
        "requested": len(tickers),
        "fresh_rate": round(fresh_rate, 3),
    },
    "tickers": quotes,
}
Path("public/quotes.json").write_text(
    json.dumps(output, separators=(",", ":")), encoding="utf-8"
)

ok  = len(quotes) - len(ohlcv_errors)
print(f"\nDone: {ok}/{len(tickers)} successful, {len(ohlcv_errors)} errors")
if ohlcv_errors:
    print("  Failed:", ", ".join(ohlcv_errors))
print(f"Fundamentals: {info_ok}/{len(tickers)} fetched fresh "
      f"({fresh_rate:.0%}), {carried} values carried forward")

# A run that quietly loses every valuation field used to look exactly like
# a healthy one: it exited 0 and committed. It must not. Prices and RSI
# are still good and still worth committing, so this fails AFTER the
# write, leaving the commit step to the workflow's own decision.
if fresh_rate < 0.25:
    print(f"\nFUNDAMENTALS COLLAPSED: only {info_ok} of {len(tickers)} "
          "tickers returned any fundamentals at all. The valuation columns "
          "in this file are carried forward, not fresh. This usually means "
          "the source is throttling the runner.")
    sys.exit(1)

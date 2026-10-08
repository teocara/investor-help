"""Fetch the long-history series the growth book needs.

The other two paper books trade single stocks drawn from the dashboard
watchlist. That watchlist is today's list, so any backtest over it is
survivorship-biased by construction and its absolute numbers are inflated.

This book is deliberately built on something else: broad INDEX funds. An
index fund already contains the companies that failed, because the index
held them while they were failing and the fund tracked it down. There is
no selection to be biased by, so a 30-year backtest on these series is
worth reading in a way that a 30-year backtest on the watchlist is not.

Mutual funds rather than ETFs, because the history is roughly a decade
longer — VGSIX opens in 1996, VNQ not until 2004 — and because Yahoo's
adjusted close for a fund is a genuine total-return series: distributions
are reinvested, so the numbers include income rather than price only.

Written to public/growth-history/<TICKER>.json as daily total-return
closes. Run on Actions via .github/workflows/growth-history.yml; the
session container cannot reach Yahoo.
"""

import json
import sys
import datetime as dt
from pathlib import Path

import pandas as pd
import yfinance as yf

OUT = Path("public/growth-history")

# ── The sleeves ──────────────────────────────────────────────────────────
# One fund per economic exposure, chosen for length of history first and
# breadth second. Inception dates are why these specific tickers.
SERIES = {
    # US equity
    "VFINX": "US large cap (S&P 500 index fund, 1976)",
    "NAESX": "US small cap (Small-Cap index fund, 1960)",
    "VIVAX": "US large value (Value index fund, 1992)",
    # Outside the US
    "VEURX": "Europe (Europe index fund, 1990)",
    "VPACX": "Pacific (Pacific index fund, 1990)",
    "VEIEX": "Emerging markets (EM index fund, 1994)",
    # Real assets
    "VGSIX": "US REITs (REIT index fund, 1996)",
    "VGPMX": "Precious metals and mining (1984)",
    # Duration and credit
    "VUSTX": "Long Treasuries (Long-Term Treasury, 1986)",
    "VFITX": "Intermediate Treasuries (1991)",
    "VWESX": "Long investment-grade credit (1973)",
    # Reference series, not tradeable sleeves
    "^IRX":  "13-week T-bill discount rate, for the financing cost",
    # For the midterm-election event study. The index goes back to 1927,
    # which is the difference between 11 midterms and 24 — and with a
    # sample this small, every extra observation moves the error bars.
    # Price-only, so it understates total return, and by MORE in the
    # decades when dividend yields were 5-6%. That is tolerable here only
    # because the study compares election windows against non-election
    # windows drawn from the same decades, so the missing dividend is in
    # both sides of the comparison.
    "^GSPC": "S&P 500 price index, 1927 — the long sample for the event study",
    "^SP500TR": "S&P 500 TOTAL return, 1988 — cross-check on the price index",
    "^VIX":  "Implied volatility, 1990 — for the pre-election risk premium",
    "^RUT":  "Russell 2000, 1987 — small caps, said to be more policy-sensitive",
    "VFISX": "Short Treasuries, the cash sleeve (1991)",
}

# Fetched so the backtest can be repeated against the ETFs a retail
# investor would actually buy today, to check the funds are not flattering.
CROSSCHECK = ["SPY", "IWM", "EFA", "EEM", "VNQ", "TLT", "IEF", "LQD", "GLD", "BIL"]


def fetch(ticker):
    df = yf.download(
        # 1927, not 1970: the index reaches back that far and the election
        # study lives or dies on sample size — 1970 gives 14 midterms, 1927
        # gives 24. The fund series simply start when they start.
        ticker, start="1927-01-01", auto_adjust=True,
        progress=False, threads=False, actions=False,
    )
    if df is None or df.empty:
        return None
    close = df["Close"]
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]
    close = close.dropna()
    if close.empty:
        return None
    return [
        {"time": idx.strftime("%Y-%m-%d"), "close": round(float(v), 6)}
        for idx, v in close.items()
        if pd.notna(v) and float(v) > 0
    ]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest, failed = {}, []

    for ticker in list(SERIES) + CROSSCHECK:
        try:
            rows = fetch(ticker)
        except Exception as exc:                       # noqa: BLE001
            print(f"  {ticker:<8} ERROR {type(exc).__name__}: {exc}")
            failed.append(ticker)
            continue
        if not rows:
            print(f"  {ticker:<8} no data")
            failed.append(ticker)
            continue

        safe_name = ticker.replace("^", "_").replace("=", "_")
        (OUT / f"{safe_name}.json").write_text(
            json.dumps(rows, separators=(",", ":")), encoding="utf-8"
        )
        manifest[ticker] = {
            "file": f"{safe_name}.json",
            "role": SERIES.get(ticker, "cross-check against the fund series"),
            "start": rows[0]["time"],
            "end": rows[-1]["time"],
            "bars": len(rows),
        }
        print(f"  {ticker:<8} {rows[0]['time']} -> {rows[-1]['time']}  "
              f"{len(rows):>5} bars")

    (OUT / "manifest.json").write_text(
        json.dumps(
            {
                "generated": dt.datetime.now(dt.timezone.utc)
                .isoformat(timespec="seconds"),
                "note": "Daily TOTAL-RETURN closes (Yahoo adjusted close: "
                        "distributions reinvested). ^IRX is a rate in "
                        "percent, not a price.",
                "series": manifest,
                "failed": failed,
            },
            indent=1,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"\n{len(manifest)} series written, {len(failed)} failed")
    # A couple of stragglers is survivable; losing the core is not.
    core = {"VFINX", "VUSTX", "VGSIX", "^IRX"}
    if core & set(failed):
        print(f"FATAL: core series missing: {sorted(core & set(failed))}")
        sys.exit(1)


if __name__ == "__main__":
    main()

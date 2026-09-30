"""Validate a candidate list of world large caps, and emit real metadata.

Why this exists rather than typing rows straight into the page: a ticker I
remember is a ticker I might be inventing. Every symbol below is checked
against the data source before it reaches the watchlist, and the name,
currency, sector and price that get written come from the FETCH, not from
me. Anything that does not resolve is reported and dropped.

Runs on Actions; the session container cannot reach the data source.
Writes public/world-candidates.json for the generator step to read.
"""
import json
import sys
import datetime as dt
from pathlib import Path

import yfinance as yf

# Candidates, grouped by home market. Only the symbol and my sector guess
# are mine; everything else is taken from the source. The sector guess is
# a fallback for when the source does not report one.
CANDIDATES = {
 "Japan": [
  ("7203.T","Consumer Disc."),("6758.T","Technology"),("8306.T","Financials"),
  ("6861.T","Industrials"),("9984.T","Technology"),("6501.T","Industrials"),
  ("8035.T","Technology"),("9983.T","Consumer Disc."),("4063.T","Materials"),
  ("7974.T","Communication"),("8316.T","Financials"),("8058.T","Industrials"),
  ("4568.T","Healthcare"),("6098.T","Industrials"),("6857.T","Technology"),
  ("7267.T","Consumer Disc."),("6902.T","Consumer Disc."),("9433.T","Communication"),
  ("9432.T","Communication"),("4502.T","Healthcare"),("6981.T","Technology"),
  ("6146.T","Technology"),("8766.T","Financials"),("6367.T","Industrials"),
  ("7741.T","Healthcare"),("4519.T","Healthcare"),("8411.T","Financials"),
  ("9434.T","Communication"),("6954.T","Industrials"),("7751.T","Technology"),
 ],
 "France": [
  ("TTE.PA","Energy"),("SU.PA","Industrials"),("AI.PA","Materials"),
  ("RMS.PA","Consumer Disc."),("SAF.PA","Industrials"),("EL.PA","Healthcare"),
  ("BNP.PA","Financials"),("CS.PA","Financials"),("DG.PA","Industrials"),
  ("BN.PA","Consumer Staples"),("RI.PA","Consumer Staples"),("KER.PA","Consumer Disc."),
  ("ACA.PA","Financials"),("ORA.PA","Communication"),("VIE.PA","Utilities"),
  ("CAP.PA","Technology"),("LR.PA","Industrials"),("HO.PA","Industrials"),
 ],
 "Germany": [
  ("DTE.DE","Communication"),("MUV2.DE","Financials"),("MBG.DE","Consumer Disc."),
  ("VOW3.DE","Consumer Disc."),("ADS.DE","Consumer Disc."),("IFX.DE","Technology"),
  ("BAYN.DE","Healthcare"),("BAS.DE","Materials"),("DBK.DE","Financials"),
  ("RHM.DE","Industrials"),("DHL.DE","Industrials"),("EOAN.DE","Utilities"),
  ("RWE.DE","Utilities"),("HEN3.DE","Consumer Staples"),("MRK.DE","Healthcare"),
  ("DB1.DE","Financials"),("SY1.DE","Materials"),("VNA.DE","Real Estate"),
 ],
 "Switzerland": [
  ("ZURN.SW","Financials"),("UBSG.SW","Financials"),("ABBN.SW","Industrials"),
  ("CFR.SW","Consumer Disc."),("HOLN.SW","Materials"),("SIKA.SW","Materials"),
  ("LONN.SW","Healthcare"),("GIVN.SW","Materials"),("SREN.SW","Financials"),
  ("ALC.SW","Healthcare"),
 ],
 "UK": [
  ("BATS.L","Consumer Staples"),("RIO.L","Materials"),("GSK.L","Healthcare"),
  ("DGE.L","Consumer Staples"),("REL.L","Industrials"),("LSEG.L","Financials"),
  ("BARC.L","Financials"),("LLOY.L","Financials"),("NG.L","Utilities"),
  ("RR.L","Industrials"),("BP.L","Energy"),("GLEN.L","Materials"),
  ("PRU.L","Financials"),("TSCO.L","Consumer Staples"),("BA.L","Industrials"),
  ("CPG.L","Consumer Disc."),("AAL.L","Materials"),("SHEL.L","Energy"),
 ],
 "Netherlands": [
  ("PRX.AS","Technology"),("INGA.AS","Financials"),("AD.AS","Consumer Staples"),
  ("HEIA.AS","Consumer Staples"),("WKL.AS","Industrials"),("ADYEN.AS","Technology"),
  ("PHIA.AS","Healthcare"),("AKZA.AS","Materials"),
 ],
 "Spain": [
  ("ITX.MC","Consumer Disc."),("SAN.MC","Financials"),("IBE.MC","Utilities"),
  ("BBVA.MC","Financials"),("TEF.MC","Communication"),("AENA.MC","Industrials"),
  ("FER.MC","Industrials"),("REP.MC","Energy"),
 ],
 "Italy": [
  ("UCG.MI","Financials"),("PRY.MI","Industrials"),("MONC.MI","Consumer Disc."),
  ("SRG.MI","Utilities"),("TRN.MI","Utilities"),("LDO.MI","Industrials"),
  ("A2A.MI","Utilities"),("BAMI.MI","Financials"),
 ],
 "Nordics": [
  ("NOVO-B.CO","Healthcare"),("DSV.CO","Industrials"),("MAERSK-B.CO","Industrials"),
  ("ATCO-A.ST","Industrials"),("INVE-B.ST","Financials"),("VOLV-B.ST","Industrials"),
  ("ERIC-B.ST","Technology"),("SEB-A.ST","Financials"),("ASSA-B.ST","Industrials"),
  ("HEXA-B.ST","Technology"),("EQNR.OL","Energy"),("DNB.OL","Financials"),
  ("NOKIA.HE","Technology"),("SAMPO.HE","Financials"),("NDA-FI.HE","Financials"),
  ("ORSTED.CO","Renewables"),("VWS.CO","Renewables"),("CARL-B.CO","Consumer Staples"),
 ],
 "Canada": [
  ("RY.TO","Financials"),("TD.TO","Financials"),("ENB.TO","Energy"),
  ("CNR.TO","Industrials"),("BN.TO","Financials"),("CP.TO","Industrials"),
  ("BMO.TO","Financials"),("BNS.TO","Financials"),("SU.TO","Energy"),
  ("TRP.TO","Energy"),("CNQ.TO","Energy"),("ATD.TO","Consumer Staples"),
  ("WCN.TO","Industrials"),("MFC.TO","Financials"),("FTS.TO","Utilities"),
 ],
 "Australia": [
  ("CBA.AX","Financials"),("CSL.AX","Healthcare"),("NAB.AX","Financials"),
  ("WBC.AX","Financials"),("ANZ.AX","Financials"),("WES.AX","Consumer Disc."),
  ("MQG.AX","Financials"),("WDS.AX","Energy"),("RIO.AX","Materials"),
  ("FMG.AX","Materials"),("TLS.AX","Communication"),("GMG.AX","Real Estate"),
  ("BHP.AX","Materials"),("WOW.AX","Consumer Staples"),("TCL.AX","Industrials"),
 ],
 "Hong Kong": [
  ("0941.HK","Communication"),("1398.HK","Financials"),("3690.HK","Consumer Disc."),
  ("1810.HK","Technology"),("2318.HK","Financials"),("0883.HK","Energy"),
  ("0005.HK","Financials"),("1288.HK","Financials"),("9618.HK","Consumer Disc."),
  ("9999.HK","Communication"),("0386.HK","Energy"),("1211.HK","Consumer Disc."),
  ("2020.HK","Consumer Disc."),("0688.HK","Real Estate"),("2388.HK","Financials"),
  ("0267.HK","Industrials"),("1024.HK","Communication"),("2269.HK","Healthcare"),
  ("0316.HK","Industrials"),("1113.HK","Real Estate"),
 ],
 "Korea": [
  ("005930.KS","Technology"),("000660.KS","Technology"),("005380.KS","Consumer Disc."),
  ("051910.KS","Materials"),("035420.KS","Communication"),("207940.KS","Healthcare"),
  ("005490.KS","Materials"),("068270.KS","Healthcare"),
 ],
 "Taiwan": [
  ("2330.TW","Technology"),("2317.TW","Technology"),("2454.TW","Technology"),
  ("2308.TW","Technology"),("2881.TW","Financials"),("2412.TW","Communication"),
 ],
 "India": [
  ("RELIANCE.NS","Energy"),("TCS.NS","Technology"),("HDFCBANK.NS","Financials"),
  ("INFY.NS","Technology"),("ICICIBANK.NS","Financials"),("BHARTIARTL.NS","Communication"),
  ("ITC.NS","Consumer Staples"),("SBIN.NS","Financials"),("LT.NS","Industrials"),
  ("HINDUNILVR.NS","Consumer Staples"),("BAJFINANCE.NS","Financials"),
  ("MARUTI.NS","Consumer Disc."),("SUNPHARMA.NS","Healthcare"),("TITAN.NS","Consumer Disc."),
 ],
 "Brazil": [
  ("PETR4.SA","Energy"),("VALE3.SA","Materials"),("ITUB4.SA","Financials"),
  ("BBDC4.SA","Financials"),("ABEV3.SA","Consumer Staples"),("WEGE3.SA","Industrials"),
  ("BBAS3.SA","Financials"),("B3SA3.SA","Financials"),
 ],
 "Mexico": [
  ("WALMEX.MX","Consumer Staples"),("AMXB.MX","Communication"),
  ("FEMSAUBD.MX","Consumer Staples"),("GFNORTEO.MX","Financials"),
  ("GMEXICOB.MX","Materials"),
 ],
 "Middle East": [
  ("2222.SR","Energy"),("1120.SR","Financials"),
 ],
}


def main():
    existing = set()
    html = Path("investor-dashboard.html").read_text(encoding="utf-8")
    import re
    existing = set(re.findall(r'ticker:"([^"]+)"', html))

    out, failed, dupes = {}, [], []
    flat = [(t, s, mkt) for mkt, lst in CANDIDATES.items() for t, s in lst]
    print(f"{len(flat)} candidates, {len(existing)} already on the watchlist\n")

    for ticker, sector_guess, market in flat:
        if ticker in existing:
            dupes.append(ticker)
            continue
        try:
            tk = yf.Ticker(ticker)
            hist = tk.history(period="1mo", auto_adjust=True)
            if hist is None or hist.empty:
                failed.append((ticker, "no price history"))
                continue
            price = float(hist["Close"].dropna().iloc[-1])
            info = {}
            try:
                info = tk.info or {}
            except Exception:
                pass
            name = (info.get("shortName") or info.get("longName") or "").strip()
            if not name:
                failed.append((ticker, "no name from source"))
                continue
            cur = (info.get("currency") or "").upper()
            mcap = info.get("marketCap")
            out[ticker] = {
                "name": name,
                "market": market,
                "currency": cur or None,
                "price": round(price, 4),
                "sector": info.get("sector") or sector_guess,
                "sector_guess": sector_guess,
                "market_cap_b": round(mcap / 1e9, 1) if mcap else None,
                "trailingPE": info.get("trailingPE"),
                "forwardPE": info.get("forwardPE"),
                "exchange": info.get("exchange"),
            }
            print(f"  OK   {ticker:<14}{cur or '???':<5}{price:>12,.2f}  {name[:38]}")
        except Exception as exc:                                  # noqa: BLE001
            failed.append((ticker, f"{type(exc).__name__}: {exc}"))
            print(f"  FAIL {ticker:<14}{type(exc).__name__}")

    Path("public").mkdir(exist_ok=True)
    Path("public/world-candidates.json").write_text(json.dumps({
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "resolved": out,
        "failed": [{"ticker": t, "why": w} for t, w in failed],
        "already_present": sorted(dupes),
    }, indent=1) + "\n", encoding="utf-8")

    print(f"\nresolved {len(out)}, failed {len(failed)}, "
          f"already present {len(dupes)}")
    if failed:
        print("\ndropped:")
        for t, w in failed:
            print(f"  {t:<14}{w[:70]}")
    # Currencies matter: a JPY price rendered with a dollar sign is a lie.
    from collections import Counter
    print("\ncurrencies:",
          dict(Counter(v["currency"] for v in out.values()).most_common()))


if __name__ == "__main__":
    main()

"""Turn validated world large caps into watchlist rows.

Reads public/world-candidates.json, which only contains symbols that
actually resolved, and inserts a RAW row per name into
investor-dashboard.html.

What these rows deliberately do NOT carry, and why:

  score   — omitted. `score` is a hand-authored 1-10 conviction number,
            and it drives two live systems: signalBadge(), where score>=7
            is half of a Buy, and the Asset Allocation Planner, which
            recommends names by score. Inventing a number for a company I
            have not assessed would push fabricated conviction into both.
            Left absent, these rows can still show Entry/Hold/Neutral from
            RSI and valuation, but can never manufacture a Buy and are
            never offered as an allocation pick.

  rsi, peg, eps_growth, rev_growth, roe, debt_equity
          — omitted. The nightly job fills RSI and the valuation fields
            from live data for every watchlist ticker; seeding them with
            placeholders would just be wrong for a day and indistinguishable
            from real data.

price, name, sector, market cap and currency come from the validation
fetch. `currency` is set explicitly rather than inferred from the ticker
suffix, so the table formats the quote correctly even where the suffix
mapping is ambiguous.
"""
import json
import re
import sys
from pathlib import Path

HTML = Path("investor-dashboard.html")
DATA = Path("public/world-candidates.json")

# The page's own sector vocabulary. Anything outside it gets mapped, so a
# new row cannot invent a sector the filters and sector cap do not know.
SECTOR_MAP = {
    "Technology": "Technology", "Information Technology": "Technology",
    "Financial Services": "Financials", "Financial": "Financials",
    "Financials": "Financials",
    "Healthcare": "Healthcare", "Health Care": "Healthcare",
    "Consumer Cyclical": "Consumer Disc.", "Consumer Discretionary": "Consumer Disc.",
    "Consumer Disc.": "Consumer Disc.",
    "Consumer Defensive": "Consumer Staples", "Consumer Staples": "Consumer Staples",
    "Industrials": "Industrials", "Industrial": "Industrials",
    "Energy": "Energy",
    "Basic Materials": "Materials", "Materials": "Materials",
    "Utilities": "Utilities",
    "Communication Services": "Communication", "Communication": "Communication",
    "Real Estate": "Real Estate",
    "Renewables": "Renewables",
}


# The currency a listing's suffix implies. A row whose source-reported
# currency disagrees is dropped: the nightly job refreshes price from the
# same source, so a ticker the source is inconsistent about can silently
# swap units and move the displayed price by 100x.
SUFFIX_CCY = {
    "T": "JPY", "HK": "HKD", "KS": "KRW", "KQ": "KRW", "TW": "TWD",
    "NS": "INR", "BO": "INR", "SA": "BRL", "MX": "MXN", "SR": "SAR",
    "AX": "AUD", "TO": "CAD", "V": "CAD", "L": "GBP", "PA": "EUR",
    "DE": "EUR", "AS": "EUR", "MI": "EUR", "MC": "EUR", "BR": "EUR",
    "LS": "EUR", "VI": "EUR", "HE": "EUR", "IR": "EUR", "SW": "CHF",
    "ST": "SEK", "CO": "DKK", "OL": "NOK",
}


def js_str(v):
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def num(v, nd=2):
    if v is None:
        return "null"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "null"
    if f != f or f in (float("inf"), float("-inf")):
        return "null"
    return str(round(f, nd))


def main():
    if not DATA.exists():
        sys.exit("public/world-candidates.json missing — run the validator first")
    blob = json.loads(DATA.read_text())
    resolved = blob.get("resolved") or {}
    if not resolved:
        sys.exit("no resolved candidates")

    html = HTML.read_text(encoding="utf-8")
    existing = set(re.findall(r'ticker:"([^"]+)"', html))

    by_market = {}
    skipped, mismatched = [], []
    for ticker, d in sorted(resolved.items()):
        if ticker in existing:
            skipped.append(ticker)
            continue
        suffix = ticker.rsplit(".", 1)[-1] if "." in ticker else ""
        expect = SUFFIX_CCY.get(suffix)
        got = (d.get("currency") or "").upper()
        if expect and got and got != expect:
            mismatched.append((ticker, expect, got, d.get("price")))
            continue
        sector = SECTOR_MAP.get(d.get("sector") or "")
        if not sector:
            sector = SECTOR_MAP.get(d.get("sector_guess") or "", "Industrials")
        by_market.setdefault(d.get("market") or "World", []).append((ticker, d, sector))

    rows, n = [], 0
    for market in sorted(by_market):
        rows.append(f"// {market} — main listings")
        for ticker, d, sector in by_market[market]:
            parts = [
                f'ticker:{js_str(ticker)}',
                f'name:{js_str(d["name"])}',
                f'sector:{js_str(sector)}',
                'type:"Stock"',
                f'currency:{js_str(d["currency"] or "USD")}',
                f'price:{num(d.get("price"), 4)}',
                'rsi:null', 'pe:' + num(d.get("trailingPE")),
                'fwdPe:' + num(d.get("forwardPE")),
                'eps_growth:null', 'rev_growth:null', 'roe:null',
                'debt_equity:null',
                # Left null on purpose. The validation fetch returns market
                # cap in the LISTING's currency, and the heatmap ranks the
                # largest 40 companies by this field — a yen-billions figure
                # sitting next to a dollar-billions one would put Shin-Etsu
                # above Apple. refresh_data.py now normalises caps to USD, so
                # the nightly run fills this in correctly; a blank cell until
                # then beats a wrong ranking.
                'market_cap_b:null',
                f'notes:{js_str(market + " main-market listing. Local currency: " + (d["currency"] or "USD") + ". Not scored.")}',
            ]
            rows.append("{" + ",".join(parts) + "},")
            n += 1

    marker = "\n// ── World main-market listings "
    block = (marker + "─" * 44 + "\n"
             "// Added from a validated fetch, not from memory: every symbol below\n"
             "// resolved against the data source, and name, currency, price, sector\n"
             "// and market cap are the values it returned. These rows carry NO score\n"
             "// — see scripts/add_world_rows.py for why that matters.\n"
             + "\n".join(rows) + "\n")

    # RAW ends with "];" — insert immediately before it.
    start = html.find("const RAW = [")
    if start < 0:
        sys.exit("could not locate RAW")
    end = html.find("\n];", start)
    if end < 0:
        sys.exit("could not locate the end of RAW")
    html = html[:end] + "\n" + block + html[end:]
    HTML.write_text(html, encoding="utf-8")

    print(f"inserted {n} rows across {len(by_market)} markets")
    if skipped:
        print(f"skipped {len(skipped)} already present: {', '.join(skipped[:8])}"
              + (" ..." if len(skipped) > 8 else ""))
    if mismatched:
        print(f"\ndropped {len(mismatched)} for inconsistent currency "
              f"(exchange says one thing, the source another):")
        for t, exp, got, px in mismatched:
            print(f"  {t:<14}suffix implies {exp}, source says {got} @ {px}")
    for market in sorted(by_market):
        print(f"  {market:<14}{len(by_market[market])}")


if __name__ == "__main__":
    main()

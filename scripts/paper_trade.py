"""Autonomous paper-trading engine.

Runs unattended on a schedule, decides what to hold, executes at real market
closes, and records every action to paper/portfolio.json for later audit.

── Why this strategy ────────────────────────────────────────────────────
Chosen from what was actually measured in research/ rather than from taste:

  * Trend-following a SINGLE instrument beat buy-and-hold on return in only
    14% of 264 instruments tested. Betting the year on one signal applied to
    one index would very likely lose.
  * The same rule went from Sharpe 0.26 on one instrument to 0.76 across a
    hundred. Diversification, not signal quality, is where the edge lives.
  * So: apply a mediocre-but-robust signal across many names, and let breadth
    do the work.

The design is dual momentum (Antonacci): relative momentum picks WHAT to own,
absolute momentum decides WHETHER to own anything at all.

  Universe     watchlist names with enough history and real liquidity
  Selection    rank by 12-1 month return; take the top N
  Trend gate   a name is only eligible while above its own 200-day average
  Sizing       inverse volatility, capped, so one wild name cannot dominate
  Risk-off     names failing the gate are not replaced — the book moves to
               cash on its own when breadth collapses
  Rebalance    per book: the primary runs weekly, a parallel book runs
               bi-weekly on identical prices and signals so the cadence can
               be compared forward instead of argued from a backtest

Long only, no leverage, no shorting. Costs are charged on every fill.
"""

import json
import math
import os
import re
import sys
import datetime as dt
from pathlib import Path

# ── Books ────────────────────────────────────────────────────────────────
# Two portfolios run side by side on the SAME prices, the SAME session dates
# and the SAME signals. The only difference is the rebalance cadence, so any
# gap between them is attributable to that and nothing else — which is the
# whole point of running the second one rather than trusting a backtest.
BOOKS = [
    {"id": "weekly",   "file": "paper/portfolio.json", "kind": "momentum",
     "rebalance_days": 7,  "label": "Weekly rebalance"},
    {"id": "biweekly", "file": "paper/portfolio-biweekly.json", "kind": "momentum",
     "rebalance_days": 14, "label": "Bi-weekly rebalance"},
    # The third book is a different animal entirely: asset classes rather
    # than single stocks, monthly rather than weekly, and levered. It is
    # not a cadence variant of the first two and is not comparable to them
    # — it is there to answer a different question. See GROWTH_* below.
    {"id": "growth",   "file": "paper/portfolio-growth.json", "kind": "growth",
     "rebalance_days": 30, "label": "Long-run growth"},
]

# ── The growth book ──────────────────────────────────────────────────────
# Objective: maximise COMPOUND growth, which is not the same as maximising
# average return. The gap between them is the design:
#
#       g  ~=  mu  -  sigma^2 / 2
#
# g is what multiplies the money. Volatility is a direct subtraction from
# terminal wealth, so a book built to compound looks different from one
# built to score well in an average year.
#
# Every number below was chosen by the 30-year study in research/growth.py,
# run on broad index funds back to 1996 — not on the dashboard watchlist,
# which is today's list of survivors and cannot support a claim about
# thirty years. What the study found, including where it contradicted the
# design it was meant to confirm, is written up in that file's docstring.
#
# Headline, 1996-10 to 2026-09, 10 bps per fill, financing charged:
#   growth book   10.69% CAGR   14.1% vol   -27.2% maxDD   Sharpe 0.63
#   S&P 500 TR    10.20% CAGR   19.1% vol   -55.3% maxDD   Sharpe 0.49
# Half a point more growth at half the drawdown. The modest return edge is
# the honest one: an earlier version showed 11.62%, but only because the
# sleeve caps were being normalised away and the book was running hotter
# than its own rules claimed.
#
# Two caveats that belong next to those numbers, not in a footnote:
#   * the edge dies at ~30 bps per fill. It needs cheap execution.
#   * it is concentrated in 1996-2008. Over rolling 10-year windows it beat
#     buy-and-hold in 23 of 40, and the most recent decade it LOST by about
#     9 points a year. This is a book that earns its keep in bad regimes.
#
# ETFs stand in for the index funds the study used, sleeve for sleeve.
GROWTH_SLEEVES = {
    "SPY": ("US large cap",        "equity"),
    "IWM": ("US small cap",        "equity"),
    "VTV": ("US large value",      "equity"),
    "VGK": ("Europe",              "equity"),
    "EFA": ("Developed ex-US",     "equity"),
    "VWO": ("Emerging markets",    "equity"),
    "VNQ": ("US REITs",            "real"),
    "GLD": ("Gold",                "real"),
    "TLT": ("Long Treasuries",     "bond"),
    "IEF": ("Interm. Treasuries",  "bond"),
    "LQD": ("Long IG credit",      "bond"),
}
GROWTH_TREND      = 210     # 10-month SMA (Faber 2007), mid-plateau in the sweep
GROWTH_MOM        = 252     # 12-month absolute momentum, measured against T-bills
GROWTH_VOL        = 126     # 6-month realised vol for the risk weights
GROWTH_MAX_SLEEVE = 0.25
GROWTH_MAX_EQUITY = 0.70    # or it quietly becomes an all-equity book
GROWTH_MAX_LEV    = 2.00    # where growth PEAKS once financing is charged
                            # realistically, and falls hard after. This is
                            # set by the cost of money, not by Kelly.
GROWTH_BAND       = 0.02    # no-trade band, fraction of equity
GROWTH_BORROW     = 0.0100  # over T-bills, charged on borrowed cash
GROWTH_MIN_BARS   = GROWTH_MOM + 10
DEFAULT_TBILL     = 0.042   # only if the rate file is missing entirely

# ── Rules (fixed for the duration of the run) ────────────────────────────
START_CAPITAL   = 100_000.0
MAX_POSITIONS   = 15
MAX_WEIGHT      = 0.15      # no single name above 15% of the book
MIN_WEIGHT      = 0.02
COST_BPS        = 0.0010    # 10 bps per fill: the universe now includes
                            # small caps and thin ADRs, where 5 bps is
                            # optimistic. Weekly rebalancing only beats
                            # monthly below roughly 10-15 bps, so the
                            # assumption has to be honest or the choice
                            # of frequency is decided by wishful thinking.
MOM_LOOKBACK    = 252       # 12 months
MOM_SKIP        = 21        # skip the most recent month (short-term reversal)
TREND_WINDOW    = 200
VOL_WINDOW      = 60
MIN_HISTORY     = 300       # bars required before a name is tradeable
MAX_SECTOR      = 0.40      # at most 40% of the slots in any one sector
BENCHMARKS      = ["SPY", "QQQ"]

# Instruments excluded from the tradeable universe: leveraged and inverse
# funds compound daily and do not belong in a monthly-rebalanced book.
EXCLUDE = {"TQQQ", "SQQQ", "QLD", "PSQ", "LQQ.PA", "EURUSD=X", "UVXY", "SOXL", "SOXS"}


# ── Data ─────────────────────────────────────────────────────────────────
def load_universe():
    """Tradeable names plus their sector, for the concentration cap.

    Foreign listings are excluded outright: their prices are quoted in local
    currency, and the book keeps its accounts in dollars. Holding 9984.T at
    a yen price would silently value a 5,886 yen share as 5,886 dollars.
    """
    html = Path("investor-dashboard.html").read_text(encoding="utf-8")
    rows = re.findall(r'ticker:"([^"]+)"[^}]*?sector:"([^"]*)"', html)
    seen, out = set(), {}
    for t, sec in rows:
        if t in seen:
            continue
        seen.add(t)
        if t in EXCLUDE or "." in t or "=" in t:
            continue
        out[t] = sec or "Unknown"
    return out


def load_prices_offline(tickers):
    """Committed daily files — used for testing without network access."""
    out = {}
    for t in tickers:
        p = Path(f"public/ohlcv/{t}.json")
        if not p.exists():
            continue
        try:
            rows = json.loads(p.read_text())
        except Exception:
            continue
        series = {r["time"]: r["close"] for r in rows if r.get("close")}
        if len(series) >= MIN_HISTORY:
            out[t] = series
    return out


def load_prices_live(tickers):
    import yfinance as yf
    raw = yf.download(tickers, period="2y", interval="1d",
                      auto_adjust=True, threads=True, progress=False)
    multi = len(tickers) > 1
    out = {}
    for t in tickers:
        try:
            s = raw["Close"][t].dropna() if multi else raw["Close"].dropna()
        except Exception:
            continue
        series = {d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()}
        if len(series) >= MIN_HISTORY:
            out[t] = series
    return out


# ── Indicators ───────────────────────────────────────────────────────────
def momentum(closes):
    """12-month return excluding the most recent month."""
    if len(closes) < MOM_LOOKBACK + 1:
        return None
    past, recent = closes[-MOM_LOOKBACK], closes[-1 - MOM_SKIP]
    if past <= 0:
        return None
    return recent / past - 1


def above_trend(closes):
    if len(closes) < TREND_WINDOW:
        return False
    return closes[-1] > sum(closes[-TREND_WINDOW:]) / TREND_WINDOW


def volatility(closes, n=VOL_WINDOW):
    if len(closes) < n + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1])
            for i in range(len(closes) - n, len(closes)) if closes[i - 1] > 0]
    if len(rets) < 5:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * 252)


# ── State ────────────────────────────────────────────────────────────────
def blank_state(today, cfg):
    if cfg.get("kind") == "growth":
        return {
            "started": today,
            "book": cfg["id"], "label": cfg["label"],
            "rules": {
                "strategy": "Asset-class trend following, inverse-vol sized, "
                            "levered to the financing-aware growth optimum",
                "objective": "maximise compound growth (g = mu - sigma^2/2), "
                             "not average return",
                "start_capital": START_CAPITAL,
                "sleeves": len(GROWTH_SLEEVES),
                "trend_days": GROWTH_TREND,
                "momentum_days": GROWTH_MOM,
                "momentum_hurdle": "13-week T-bill over the same window",
                "sizing": "inverse volatility, 6-month lookback",
                "max_sleeve": GROWTH_MAX_SLEEVE,
                "max_equity_block": GROWTH_MAX_EQUITY,
                "max_leverage": GROWTH_MAX_LEV,
                "borrow_spread_bps": GROWTH_BORROW * 1e4,
                "cost_bps": COST_BPS * 1e4,
                "rebalance": "monthly (30 days), plus daily trend stop-out",
                "rebalance_days": cfg["rebalance_days"],
                "long_only": True, "leverage": GROWTH_MAX_LEV,
                "backtest": "research/growth.py, 1996-10 to 2026-09 on index "
                            "funds: 10.69% CAGR vs 10.20% for the S&P 500 TR, "
                            "-27.2% vs -55.3% max drawdown",
            },
            "cash": START_CAPITAL,
            "positions": {},
            "equity": [],
            "trades": [],
            "benchmarks": {},
            "last_rebalance": None,
            "log": [],
        }
    every = cfg["rebalance_days"]
    cadence = "weekly" if every == 7 else "bi-weekly" if every == 14 else f"every {every} days"
    return {
        "started": today,
        "book": cfg["id"], "label": cfg["label"],
        "rules": {
            "strategy": "Dual momentum — 12-1 relative rank, 200d absolute trend gate",
            "start_capital": START_CAPITAL, "max_positions": MAX_POSITIONS,
            "max_weight": MAX_WEIGHT, "cost_bps": COST_BPS * 1e4,
            "rebalance": f"{cadence}, plus daily stop-out on trend break",
            "rebalance_days": every,
            "max_sector": MAX_SECTOR, "universe": "USD-quoted only",
            "long_only": True, "leverage": None,
        },
        "cash": START_CAPITAL,
        "positions": {},          # ticker -> {shares, avg_price, opened}
        "equity": [],             # [{date, value, invested, cash}]
        "trades": [],
        "benchmarks": {},         # ticker -> {shares, start_price}
        "last_rebalance": None,
        "log": [],
    }


def load_state(today, cfg):
    path = Path(cfg["file"])
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception as e:
            print(f"  {cfg['id']}: state unreadable ({e}) — refusing to overwrite")
            sys.exit(1)
    return blank_state(today, cfg)


def save_state(state, cfg):
    path = Path(cfg["file"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")


# ── Trading ──────────────────────────────────────────────────────────────
def mark_to_market(state, px, date):
    invested = 0.0
    for t, p in state["positions"].items():
        price = px.get(t, {}).get(date)
        if price:
            p["last"] = price
        invested += p["shares"] * p.get("last", p["avg_price"])
    return invested + state["cash"], invested


def sell(state, ticker, price, date, reason):
    pos = state["positions"].pop(ticker, None)
    if not pos:
        return
    proceeds = pos["shares"] * price
    fee = proceeds * COST_BPS
    state["cash"] += proceeds - fee
    pnl = (price - pos["avg_price"]) * pos["shares"] - fee
    state["trades"].append({
        "date": date, "side": "SELL", "ticker": ticker,
        "shares": round(pos["shares"], 4), "price": round(price, 4),
        "fee": round(fee, 2), "pnl": round(pnl, 2),
        "held_days": days_between(pos["opened"], date), "reason": reason,
    })


def buy(state, ticker, price, dollars, date, reason):
    if dollars < 1 or price <= 0:
        return
    fee = dollars * COST_BPS
    shares = (dollars - fee) / price
    if shares <= 0:
        return
    state["cash"] -= dollars
    state["positions"][ticker] = {
        "shares": shares, "avg_price": price, "last": price, "opened": date,
    }
    state["trades"].append({
        "date": date, "side": "BUY", "ticker": ticker,
        "shares": round(shares, 4), "price": round(price, 4),
        "fee": round(fee, 2), "reason": reason,
    })


def days_between(a, b):
    try:
        return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
    except Exception:
        return None


# ── Main ─────────────────────────────────────────────────────────────────
def main(offline=False):
    sectors = load_universe()
    universe = list(sectors)
    # The growth sleeves are priced explicitly: most are watchlist rows, but
    # the book must not silently lose a sleeve if one is ever removed.
    tickers = sorted(set(universe) | set(BENCHMARKS) | set(GROWTH_SLEEVES))
    print(f"universe: {len(universe)} USD-quoted names")

    # Prices are fetched ONCE and shared by every book, so the comparison
    # between them can never be contaminated by two different snapshots.
    px = (load_prices_offline if offline else load_prices_live)(tickers)
    print(f"priced:   {len(px)} series")
    if len(px) < 30:
        print("too few priced series — aborting without changing state")
        sys.exit(1)

    all_dates = {}
    for s in px.values():
        for d in s:
            all_dates[d] = all_dates.get(d, 0) + 1
    sessions = sorted(d for d, c in all_dates.items() if c >= len(px) * 0.6)
    if not sessions:
        print("no session date has enough coverage — aborting")
        sys.exit(1)
    print(f"as of:    {sessions[-1]}\n")

    for cfg in BOOKS:
        run_book(cfg, sectors, universe, px, sessions)


def run_book(cfg, sectors, universe, px, sessions):
    """Replay every session the ledger is missing, in order.

    Processing only the newest date would leave permanent holes whenever the
    scheduler misses a day — a holiday, a runner outage, a workflow paused and
    resumed. Worse than the gap in the curve, the trend stops that should have
    fired on those days would never fire at all, so the book would drift away
    from the rules it claims to follow. Catching up keeps the simulation
    faithful over an open-ended run.
    """
    tag = cfg["id"]
    latest = sessions[-1]
    state = load_state(latest, cfg)

    if not state["equity"]:
        pending = [latest]          # first run: open today, do not replay history
    else:
        done = state["equity"][-1]["date"]
        pending = [d for d in sessions if d > done]

    if not pending:
        print(f"[{tag}] already recorded this session — nothing to do")
        return
    if len(pending) > 1:
        print(f"[{tag}] catching up {len(pending)} missed sessions: "
              f"{pending[0]} -> {pending[-1]}")
        state.setdefault("log", []).append({
            "date": latest,
            "msg": f"backfilled {len(pending)} missed sessions ({pending[0]} to {pending[-1]})",
        })

    session = (run_growth_session if cfg.get("kind") == "growth"
               else run_session)
    for date in pending:
        session(cfg, state, sectors, universe, px, date, tag)
    save_state(state, cfg)


def run_session(cfg, state, sectors, universe, px, date, tag):

    # Only once we know a session will actually be written: keep the recorded rules in step with the code, and leave an audit trail
    # whenever they change — a year-long run is worthless if we cannot tell
    # later which rules produced which stretch of the curve.
    state["book"], state["label"] = cfg["id"], cfg["label"]
    current = blank_state(date, cfg)["rules"]
    old = state.get("rules", {})
    changed = {k: [old.get(k), v] for k, v in current.items() if old.get(k) != v}
    if changed and state.get("equity"):
        state.setdefault("rule_changes", []).append({"date": date, "changed": changed})
        state["log"].append({
            "date": date,
            "msg": "rules changed: " + ", ".join(
                f"{k} {a} -> {b}" for k, (a, b) in changed.items()),
        })
        print(f"[{tag}] rule change recorded:", changed)
    state["rules"] = current

    def closes_upto(t):
        s = px.get(t, {})
        return [s[d] for d in sorted(s) if d <= date]

    # ── seed benchmarks on the first run ────────────────────────────────
    if not state["benchmarks"]:
        for b in BENCHMARKS:
            c = closes_upto(b)
            if c:
                state["benchmarks"][b] = {
                    "shares": START_CAPITAL / c[-1], "start_price": c[-1],
                }
        state["log"].append({"date": date, "msg": "portfolio opened"})

    # ── daily risk check: exit anything that broke its trend ────────────
    for t in list(state["positions"]):
        c = closes_upto(t)
        if not c:
            continue
        if not above_trend(c):
            sell(state, t, c[-1], date, "trend break")

    # ── monthly rebalance ───────────────────────────────────────────────
    # Weekly cadence measured in calendar days, so a missed session (holiday,
    # a delayed runner) does not silently skip a whole period the way a
    # month-boundary test would.
    due = state["last_rebalance"] is None or \
        (days_between(state["last_rebalance"], date) or 99) >= cfg["rebalance_days"]
    if due:
        ranked = []
        for t in universe:
            c = closes_upto(t)
            if len(c) < MIN_HISTORY:
                continue
            m = momentum(c)
            if m is None or m <= 0:          # absolute momentum must be positive
                continue
            if not above_trend(c):           # and the trend gate must pass
                continue
            v = volatility(c)
            if not v or v <= 0:
                continue
            ranked.append({"t": t, "mom": m, "vol": v, "px": c[-1]})
        ranked.sort(key=lambda r: -r["mom"])

        # Momentum piles into whatever has been leading, which in practice
        # means one sector can take the whole book. Walk the ranking in order
        # and skip a name once its sector is full.
        picks, per_sector = [], {}
        cap = max(1, int(MAX_POSITIONS * MAX_SECTOR))
        for r in ranked:
            sec = sectors.get(r["t"], "Unknown")
            if per_sector.get(sec, 0) >= cap:
                continue
            picks.append(r)
            per_sector[sec] = per_sector.get(sec, 0) + 1
            if len(picks) >= MAX_POSITIONS:
                break
        spread = ", ".join(f"{k} {v}" for k, v in sorted(per_sector.items(),
                                                         key=lambda kv: -kv[1]))
        print(f"[{tag}] qualified {len(ranked)} -> holding {len(picks)}  [{spread}]")

        keep = {p["t"] for p in picks}
        for t in list(state["positions"]):
            if t not in keep:
                c = closes_upto(t)
                if c:
                    sell(state, t, c[-1], date, "dropped from ranking")

        equity, _ = mark_to_market(state, px, date)
        if picks:
            # inverse-volatility weights, capped, then scaled to the slots used
            raw = {p["t"]: 1.0 / p["vol"] for p in picks}
            tot = sum(raw.values())
            weights = {}
            for p in picks:
                w = raw[p["t"]] / tot
                # A book of N names should not become one name; cap and floor.
                weights[p["t"]] = max(MIN_WEIGHT, min(MAX_WEIGHT, w))
            # Never invest more than the slots justify: an incomplete ranking
            # leaves the rest in cash, which is the de-risking mechanism.
            budget = equity * (len(picks) / MAX_POSITIONS)
            s = sum(weights.values())
            weights = {t: w / s * min(1.0, budget / equity) for t, w in weights.items()}

            for p in picks:
                t = p["t"]
                target = equity * weights[t]
                cur = state["positions"].get(t)
                curval = cur["shares"] * p["px"] if cur else 0.0
                drift = abs(target - curval) / max(target, 1)
                if cur and drift < 0.20:
                    continue                     # close enough; don't churn
                if cur:
                    sell(state, t, p["px"], date, "rebalance")
                cash_avail = max(0.0, state["cash"])
                buy(state, t, p["px"], min(target, cash_avail), date,
                    "rebalance" if cur else "new position")
        state["last_rebalance"] = date
        state["log"].append({
            "date": date,
            "msg": f"rebalanced — {len(ranked)} qualified, {len(picks)} held",
        })

    # ── record the day ──────────────────────────────────────────────────
    equity, invested = mark_to_market(state, px, date)
    bench = {}
    for b, info in state["benchmarks"].items():
        c = closes_upto(b)
        if c:
            bench[b] = round(info["shares"] * c[-1], 2)
    state["equity"].append({
        "date": date, "value": round(equity, 2),
        "invested": round(invested, 2), "cash": round(state["cash"], 2),
        "n": len(state["positions"]), "bench": bench,
    })

    ret = equity / START_CAPITAL - 1
    line = (f"[{tag}] equity ${equity:,.0f} ({ret:+.2%})  "
            f"positions {len(state['positions'])}  trades {len(state['trades'])}")
    for b, v in bench.items():
        line += f"   {b} {v/START_CAPITAL-1:+.2%}"
    print(line)




# ── The growth book ──────────────────────────────────────────────────────
def tbill_rate(date):
    """Annualised 13-week T-bill, for the momentum hurdle and the margin cost.

    Read from the monthly growth-history pull rather than the nightly job,
    because ^IRX is a RATE and the nightly job's split/spike repair is
    written for prices — it would happily "fix" a genuine rate move. A rate
    up to a month stale is immaterial here; a repaired one would not be.
    """
    path = Path("public/growth-history/_IRX.json")
    if not path.exists():
        return DEFAULT_TBILL
    try:
        rows = json.loads(path.read_text())
    except Exception:
        return DEFAULT_TBILL
    last = None
    for r in rows:
        if r.get("time", "") > date:
            break
        v = r.get("close")
        if v is not None and 0 <= v < 25:
            last = v / 100.0
    return last if last is not None else DEFAULT_TBILL


def _series(px, ticker, date):
    """Closes up to and including `date`, oldest first."""
    s = px.get(ticker) or {}
    return [s[d] for d in sorted(s) if d <= date and s[d]]


def growth_targets(px, date):
    """The weight vector the book wants today. Returns (weights, diagnostics)."""
    rf = tbill_rate(date)
    elig, rejected = [], {}

    for t, (label, block) in GROWTH_SLEEVES.items():
        closes = _series(px, t, date)
        if len(closes) < GROWTH_MIN_BARS:
            rejected[t] = "not enough history"
            continue
        price = closes[-1]

        sma = sum(closes[-GROWTH_TREND:]) / GROWTH_TREND
        if price <= sma:
            rejected[t] = "below its 210-day average"
            continue

        past = closes[-GROWTH_MOM - 1]
        hurdle = (1 + rf) ** (GROWTH_MOM / 252) - 1
        excess = price / past - 1 - hurdle
        if excess <= 0:
            # Absolute momentum is measured against CASH, not against zero:
            # an asset that returned 2% while T-bills paid 4% did not earn
            # its place, whatever its chart looks like.
            rejected[t] = f"12m return below T-bills by {-excess*100:.1f}pts"
            continue

        vol = volatility(closes, GROWTH_VOL)
        if not vol or vol <= 0:
            rejected[t] = "no volatility estimate"
            continue
        elig.append((t, vol, excess))

    if not elig:
        return {}, {"rejected": rejected, "gross": 0.0, "rf": rf}

    # Inverse volatility, so a quiet bond sleeve and a wild EM sleeve
    # contribute comparable risk rather than comparable dollars.
    raw = {t: 1.0 / v for t, v, _ in elig}
    total = sum(raw.values())
    if total <= 0:
        return {}, {"rejected": rejected, "gross": 0.0, "rf": rf}
    w = {t: raw[t] / total for t in raw}

    # Normalise FIRST, then cap, and do not normalise again. Capping before
    # normalising means the next line scales the weights straight back up
    # and the cap never binds - which bites hardest when every eligible
    # sleeve is equity, i.e. exactly when the equity cap is wanted. The
    # book then holds LESS than full gross, which is the intended answer:
    # if the only things trending are equities, own less, not more.
    w = {t: min(x, GROWTH_MAX_SLEEVE) for t, x in w.items()}
    eq = [t for t in w if GROWTH_SLEEVES[t][1] == "equity"]
    se = sum(w[t] for t in eq)
    if se > GROWTH_MAX_EQUITY:
        for t in eq:
            w[t] *= GROWTH_MAX_EQUITY / se

    # Leverage applies to the sleeves that PASSED. Sleeves that failed are
    # not replaced, so when breadth collapses the book de-levers on its own
    # — the trend gate is the risk control, and this is how it acts.
    # Breadth only cuts exposure once FEWER THAN HALF the sleeves pass.
    # Above that the cap stands: de-levering linearly with breadth would be
    # a different rule from the one the 30-year study tested, and the
    # headline numbers would no longer describe this book.
    breadth = len(elig) / len(GROWTH_SLEEVES)
    gross = GROWTH_MAX_LEV * min(1.0, breadth / 0.5)
    w = {t: x * gross for t, x in w.items()}
    return w, {"rejected": rejected, "gross": gross, "rf": rf,
               "breadth": breadth}


def run_growth_session(cfg, state, sectors, universe, px, date, tag):
    state["book"], state["label"] = cfg["id"], cfg["label"]
    current = blank_state(date, cfg)["rules"]
    old = state.get("rules", {})
    changed = {k: [old.get(k), v] for k, v in current.items() if old.get(k) != v}
    if changed and state.get("equity"):
        state.setdefault("rule_changes", []).append({"date": date, "changed": changed})
        state.setdefault("log", []).append(
            {"date": date, "msg": f"rules changed: {', '.join(sorted(changed))}"})
    state["rules"] = current

    prices = {t: px.get(t, {}).get(date) for t in GROWTH_SLEEVES}
    prices = {t: p for t, p in prices.items() if p}
    if len(prices) < len(GROWTH_SLEEVES) * 0.7:
        state.setdefault("log", []).append(
            {"date": date, "msg": f"only {len(prices)} sleeves priced — session skipped"})
        return

    if not state["benchmarks"]:
        for b in BENCHMARKS:
            p0 = px.get(b, {}).get(date)
            if p0:
                state["benchmarks"][b] = {"shares": START_CAPITAL / p0,
                                          "start_price": p0}
        state.setdefault("log", []).append({"date": date, "msg": "portfolio opened"})

    # Financing. Cash earns the T-bill rate; borrowed cash costs T-bills
    # plus a spread. Without this the leverage would be free, which is the
    # single easiest way to make a levered backtest lie.
    rf = tbill_rate(date)
    prev = state["equity"][-1]["date"] if state["equity"] else None
    elapsed = (days_between(prev, date) or 0) if prev else 0
    if elapsed > 0:
        daily = (1 + rf) ** (1 / 365) - 1
        if state["cash"] >= 0:
            state["cash"] *= (1 + daily) ** elapsed
        else:
            state["cash"] *= (1 + daily + GROWTH_BORROW / 365) ** elapsed

    equity, _ = mark_to_market(state, px, date)

    # Daily trend stop, same as the other books: a sleeve that breaks its
    # average is sold the day it breaks, not at the next month end.
    for t in list(state["positions"]):
        closes = _series(px, t, date)
        if len(closes) < GROWTH_TREND:
            continue
        sma = sum(closes[-GROWTH_TREND:]) / GROWTH_TREND
        if closes[-1] <= sma:
            growth_trim(state, t, closes[-1], date, 0.0, "trend break")

    due = state["last_rebalance"] is None or \
        (days_between(state["last_rebalance"], date) or 99) >= cfg["rebalance_days"]

    if due:
        state["last_rebalance"] = date
        weights, diag = growth_targets(px, date)
        equity, _ = mark_to_market(state, px, date)

        for t in list(state["positions"]):
            if t not in weights and prices.get(t):
                growth_trim(state, t, prices[t], date, 0.0, "no longer eligible")

        for t, w in sorted(weights.items(), key=lambda kv: -kv[1]):
            price = prices.get(t)
            if not price:
                continue
            want = equity * w
            have = state["positions"].get(t, {}).get("shares", 0.0) * price
            if abs(want - have) < equity * GROWTH_BAND:
                continue
            if want > have:
                growth_add(state, t, price, want - have, date,
                           f"{GROWTH_SLEEVES[t][0]} — target {w*100:.1f}%")
            else:
                growth_trim(state, t, price, date, want,
                            f"trim to target {w*100:.1f}%")

        state.setdefault("log", []).append({
            "date": date,
            "msg": f"rebalanced — {len(weights)} of {len(GROWTH_SLEEVES)} sleeves "
                   f"pass, gross {diag['gross']:.2f}x, T-bill {diag['rf']*100:.2f}%",
            "rejected": diag["rejected"],
        })

    equity, invested = mark_to_market(state, px, date)
    row = {"date": date, "value": round(equity, 2),
           "invested": round(invested, 2), "cash": round(state["cash"], 2),
           "n": len(state["positions"]),
           "gross": round(invested / equity, 3) if equity > 0 else 0.0,
           "bench": {}}
    for b, bp in state["benchmarks"].items():
        p = px.get(b, {}).get(date)
        if p:
            row["bench"][b] = round(bp["shares"] * p, 2)
    state["equity"].append(row)
    print(f"[{tag}] {date}  ${equity:,.0f}  {len(state['positions'])} sleeves  "
          f"gross {row['gross']:.2f}x  cash ${state['cash']:,.0f}")


def growth_add(state, ticker, price, dollars, date, reason):
    """Buy into a sleeve, adding to any existing position."""
    if dollars < 1 or price <= 0:
        return
    fee = dollars * COST_BPS
    shares = (dollars - fee) / price
    if shares <= 0:
        return
    state["cash"] -= dollars          # may go negative: that is the leverage
    pos = state["positions"].get(ticker)
    if pos:
        total = pos["shares"] + shares
        pos["avg_price"] = (pos["avg_price"] * pos["shares"] + price * shares) / total
        pos["shares"], pos["last"] = total, price
    else:
        state["positions"][ticker] = {"shares": shares, "avg_price": price,
                                      "last": price, "opened": date}
    state["trades"].append({
        "date": date, "side": "BUY", "ticker": ticker,
        "shares": round(shares, 4), "price": round(price, 4),
        "fee": round(fee, 2), "reason": reason,
    })


def growth_trim(state, ticker, price, date, keep_dollars, reason):
    """Sell down to `keep_dollars`; 0 closes the position outright."""
    pos = state["positions"].get(ticker)
    if not pos or price <= 0:
        return
    keep_shares = max(0.0, keep_dollars / price)
    sell_shares = pos["shares"] - keep_shares
    if sell_shares <= 1e-9:
        return
    proceeds = sell_shares * price
    fee = proceeds * COST_BPS
    state["cash"] += proceeds - fee
    pnl = (price - pos["avg_price"]) * sell_shares - fee
    if keep_shares <= 1e-9:
        state["positions"].pop(ticker, None)
    else:
        pos["shares"], pos["last"] = keep_shares, price
    state["trades"].append({
        "date": date, "side": "SELL", "ticker": ticker,
        "shares": round(sell_shares, 4), "price": round(price, 4),
        "fee": round(fee, 2), "pnl": round(pnl, 2),
        "held_days": days_between(pos["opened"], date), "reason": reason,
    })

if __name__ == "__main__":
    main(offline="--offline" in sys.argv)

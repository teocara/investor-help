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
    {"id": "weekly",   "file": "paper/portfolio.json",
     "rebalance_days": 7,  "label": "Weekly rebalance"},
    {"id": "biweekly", "file": "paper/portfolio-biweekly.json",
     "rebalance_days": 14, "label": "Bi-weekly rebalance"},
]

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
    tickers = sorted(set(universe) | set(BENCHMARKS))
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

    for date in pending:
        run_session(cfg, state, sectors, universe, px, date, tag)
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


if __name__ == "__main__":
    main(offline="--offline" in sys.argv)

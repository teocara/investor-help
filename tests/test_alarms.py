"""Fire every alarm rule against a fabricated failure, in a scratch copy.

An alarm system nobody has seen fire is a guess. Each rule here is given
the condition it exists for, including replays of the real failures from
this repo's history, and has to produce the expected key.

THE FIXTURE IS SYNTHETIC, AND THAT IS THE WHOLE POINT

An earlier version of this file copied the LIVE ledgers and asserted that
they fired nothing. That held only while the portfolios happened to be
healthy. On 2026-11-03 the momentum books went into a 27% drawdown, the
assertion started failing, and because the workflow ran these tests as a
GATE in front of the evaluation step, the alarm system went silent for
twelve days — silent precisely when it had something to say. The books
lost 27% and nothing was reported.

So the healthy baseline is now built here, from nothing, with known
values. A test that depends on production data being quiet is not a test;
it is a tripwire pointed the wrong way.
"""
import json
import shutil
import sys
import tempfile
import datetime as dt
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TODAY = dt.date.today()
PASS, FAIL = [], []


# ── A known-good world, constructed ──────────────────────────────────────
def sessions(n=30):
    """n weekday dates ending today."""
    out, d = [], TODAY
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= dt.timedelta(days=1)
    return list(reversed(out))


SESS = sessions()


def healthy_momentum_book(label="Weekly rebalance", book="weekly"):
    """Flat-to-up equity, positions comfortably inside a 15% cap."""
    eq = []
    for i, d in enumerate(SESS):
        eq.append({"date": d, "value": 100000.0 + i * 100,
                   "invested": 100000.0 + i * 100, "cash": 0.0, "n": 10,
                   "bench": {"SPY": 100000.0 + i * 50}})
    pos = {f"T{i}": {"shares": 100.0, "avg_price": 100.0, "last": 100.0,
                     "prev_close": 100.0, "opened": SESS[0]}
           for i in range(10)}
    return {"started": SESS[0], "book": book, "label": label,
            "rules": {"start_capital": 100000.0, "max_positions": 15,
                      "max_weight": 0.15, "cost_bps": 10.0,
                      "rebalance_days": 7},
            "cash": 0.0, "positions": pos, "equity": eq, "trades": [],
            "benchmarks": {"SPY": {"shares": 1.0, "start_price": 100000.0}},
            "last_rebalance": SESS[-1], "log": []}


def healthy_growth_book():
    """Eight sleeves at 12.5% each: inside a 25%-of-gross cap."""
    eq = []
    for i, d in enumerate(SESS):
        eq.append({"date": d, "value": 100000.0 + i * 80,
                   "invested": 140000.0, "cash": -40000.0, "n": 8,
                   "gross": 1.4, "bench": {"SPY": 100000.0 + i * 50}})
    pos = {f"S{i}": {"shares": 100.0, "avg_price": 175.0, "last": 175.0,
                     "prev_close": 175.0, "opened": SESS[0]}
           for i in range(8)}
    return {"started": SESS[0], "book": "growth", "label": "Long-run growth",
            "rules": {"start_capital": 100000.0, "sleeves": 11,
                      "max_sleeve": 0.25, "max_equity_block": 0.70,
                      "max_leverage": 2.0, "cost_bps": 10.0,
                      "rebalance_days": 30},
            "cash": -40000.0, "positions": pos, "equity": eq, "trades": [],
            "benchmarks": {"SPY": {"shares": 1.0, "start_price": 100000.0}},
            "last_rebalance": SESS[-1], "log": []}


def healthy_quotes():
    return {"updated": TODAY.isoformat() + "T00:00:00Z",
            "fundamentals": {"fresh": 850, "carried_forward": 20,
                             "requested": 897, "fresh_rate": 0.948},
            "tickers": {"AAPL": {"price": 200.0, "rsi": 50.0}}}


def build_world():
    """A scratch tree the alarm module can be pointed at."""
    w = Path(tempfile.mkdtemp(prefix="alarmtest-"))
    (w / "paper").mkdir()
    (w / "public" / "ohlcv").mkdir(parents=True)
    (w / "paper" / "portfolio.json").write_text(
        json.dumps(healthy_momentum_book()))
    (w / "paper" / "portfolio-biweekly.json").write_text(
        json.dumps(healthy_momentum_book("Bi-weekly rebalance", "biweekly")))
    (w / "paper" / "portfolio-growth.json").write_text(
        json.dumps(healthy_growth_book()))
    (w / "public" / "quotes.json").write_text(json.dumps(healthy_quotes()))
    # Price files only supply the trading calendar.
    rows = [{"time": d, "open": 1.0, "high": 1.0, "low": 1.0,
             "close": 1.0, "volume": 1} for d in SESS]
    for i in range(5):
        (w / "public" / "ohlcv" / f"T{i}.json").write_text(json.dumps(rows))
    return w


work = build_world()
shutil.copytree(REPO / "scripts", work / "scripts")
sys.path.insert(0, str(work / "scripts"))
import alarms as A                                              # noqa: E402
A.ROOT = work
A.STATE_PATH = work / "paper" / "alarms.json"
NOW = TODAY.isoformat()


def evaluate():
    return A.check_data(NOW) + A.check_books(NOW, A.latest_sessions())


def run(label, expect, mutate, severity=None, forbid=None):
    """expect=None asserts total silence; a prefix asserts it appears.

    `forbid` asserts one specific prefix does NOT appear while allowing
    others — needed where a fixture legitimately trips a different rule,
    e.g. a two-sleeve growth book must not raise CONCENTRATION but
    should raise BREADTH COLLAPSE.
    """
    snap = {p: p.read_bytes() for p in work.rglob("*.json")}
    try:
        mutate()
        got = evaluate()
        keys = [a.key for a in got]
        if forbid is not None:
            bad = [k for k in keys if k.startswith(forbid)]
            ok = not bad
            detail = (f"{forbid}* quiet; fired {keys}" if ok
                      else f"should not have fired {bad}")
            (PASS if ok else FAIL).append(label)
            print(f"  [{'PASS' if ok else 'FAIL'}] {label:<44}{detail}")
            return
        if expect is None:
            ok = not got
            detail = "silent" if ok else f"unexpectedly fired {keys}"
        else:
            hit = next((a for a in got if a.key.startswith(expect)), None)
            ok = hit is not None and (severity is None
                                      or hit.severity == severity)
            detail = f"{hit.severity}: {hit.title}" if hit else f"got {keys}"
        (PASS if ok else FAIL).append(label)
        print(f"  [{'PASS' if ok else 'FAIL'}] {label:<44}{detail}")
    finally:
        for p in list(work.rglob("*.json")):
            if p not in snap:
                p.unlink()
        for p, b in snap.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)


def wq(fn):
    p = work / "public" / "quotes.json"
    q = json.loads(p.read_text())
    fn(q)
    p.write_text(json.dumps(q))


def wbook(name, fn):
    p = work / "paper" / name
    d = json.loads(p.read_text())
    fn(d)
    p.write_text(json.dumps(d))


print("the baseline: a constructed healthy world must be silent\n")
quiet = evaluate()
if quiet:
    FAIL.append("synthetic healthy world is silent")
    print(f"  [FAIL] synthetic healthy world fires {[a.key for a in quiet]}")
else:
    PASS.append("synthetic healthy world is silent")
    print("  [PASS] synthetic healthy world fires nothing")

print("\nreplaying the real failures from this repo's history\n")

run("2026-09-30 fundamentals collapse", "fundamentals_degraded",
    lambda: wq(lambda q: q.__setitem__(
        "fundamentals", {"fresh": 0, "carried_forward": 5184,
                         "requested": 897, "fresh_rate": 0.0})),
    severity="critical")

run("stale quotes (refresh stopped)", "quotes_stale",
    lambda: wq(lambda q: q.__setitem__("updated", "2026-01-01T00:00:00Z")),
    severity="critical")

run("ledger stopped recording", "ledger_stale",
    lambda: wbook("portfolio.json", lambda d: d["equity"].__setitem__(
        -1, {**d["equity"][-1], "date": "2026-01-02"})),
    severity="critical")

print("\nportfolio conditions\n")

run("drawdown breach (momentum book)", "drawdown",
    lambda: wbook("portfolio.json", lambda d: d["equity"].append(
        {**d["equity"][-1],
         "value": max(x["value"] for x in d["equity"]) * 0.75})),
    severity="warning")

run("drawdown within tolerance (stays silent)", None,
    lambda: wbook("portfolio.json", lambda d: d["equity"].append(
        {**d["equity"][-1],
         "value": max(x["value"] for x in d["equity"]) * 0.95})))

run("name past its stated cap", "concentration",
    lambda: wbook("portfolio.json", lambda d: d["positions"].__setitem__(
        "T0", {**d["positions"]["T0"], "shares": 1e5, "last": 100.0})),
    severity="warning")

# The condition that produced a false positive on the live books: when
# only two sleeves pass the gate, each is ~50% of the book and NO sizing
# rule can honour a 25% cap. That is arithmetic, not a fault.
run("2 sleeves: no concentration alarm", None,
    lambda: wbook("portfolio-growth.json", lambda d: (
        d.__setitem__("positions", {
            "VTV": {"shares": 100.0, "avg_price": 400.0, "last": 400.0,
                    "prev_close": 400.0, "opened": SESS[0]},
            "SPY": {"shares": 100.0, "avg_price": 340.0, "last": 340.0,
                    "prev_close": 340.0, "opened": SESS[0]}}),
        d["equity"].__setitem__(-1, {**d["equity"][-1], "n": 2,
                                     "gross": 0.75}))),
    forbid="concentration")

run("held position gaps 40% in a day", "shock",
    lambda: wbook("portfolio.json", lambda d: d["positions"].__setitem__(
        "T0", {**d["positions"]["T0"], "prev_close": 100.0, "last": 140.0})),
    severity="warning")

run("growth book de-levers to cash", "breadth_collapse",
    lambda: wbook("portfolio-growth.json", lambda d: d["equity"].__setitem__(
        -1, {**d["equity"][-1], "gross": 0.0, "n": 0})),
    severity="warning")

print("\ncorrupted inputs\n")

run("ledger file corrupted", "ledger_unreadable",
    lambda: (work / "paper" / "portfolio.json").write_text("{ broken"),
    severity="critical")

run("quotes.json corrupted", "quotes_unreadable",
    lambda: (work / "public" / "quotes.json").write_text("not json"),
    severity="critical")

run("quotes.json deleted", "quotes_missing",
    lambda: (work / "public" / "quotes.json").unlink(),
    severity="critical")

run("old refresh script, no freshness block", "fundamentals_unreported",
    lambda: wq(lambda q: q.pop("fundamentals", None)),
    severity="warning")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("  failures:", ", ".join(FAIL))
shutil.rmtree(work, ignore_errors=True)
sys.exit(1 if FAIL else 0)

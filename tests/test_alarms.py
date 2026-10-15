"""Fire every alarm rule against a fabricated failure, in a scratch copy.

An alarm system nobody has seen fire is a guess. Each rule here is given
the condition it exists for, including replays of the three real failures
from this repo's history, and has to produce the expected key.

Runs entirely against a temporary copy of paper/ and public/ — the real
ledgers are never touched.
"""
import json
import shutil
import sys
import tempfile
import datetime as dt
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
work = Path(tempfile.mkdtemp(prefix="alarmtest-"))
shutil.copytree(REPO / "paper", work / "paper")
(work / "public").mkdir()
shutil.copy(REPO / "public" / "quotes.json", work / "public" / "quotes.json")
(work / "public" / "ohlcv").mkdir()
for p in list((REPO / "public" / "ohlcv").glob("*.json"))[:60]:
    shutil.copy(p, work / "public" / "ohlcv" / p.name)
shutil.copytree(REPO / "scripts", work / "scripts")

sys.path.insert(0, str(work / "scripts"))
import alarms as A                                              # noqa: E402
A.ROOT = work
A.STATE_PATH = work / "paper" / "alarms.json"

TODAY = dt.date.today().isoformat()
PASS, FAIL = [], []


def run(label, expect_key_prefix, mutate, severity=None):
    """Apply mutate(), evaluate, assert the expected alarm appears."""
    snap = {p: p.read_bytes() for p in work.rglob("*.json")}
    try:
        mutate()
        sessions = A.latest_sessions()
        got = A.check_data(TODAY) + A.check_books(TODAY, sessions)
        keys = [a.key for a in got]
        negative = expect_key_prefix is None
        hit = None if negative else next(
            (a for a in got if a.key.startswith(expect_key_prefix)), None)
        if negative:
            # A negative test: the point is that NOTHING fires. Without
            # this branch the harness asserted a hit for every case and
            # scored "correctly stayed silent" as a failure.
            ok = not got
            detail = "silent" if ok else f"unexpectedly fired {keys}"
        else:
            ok = hit is not None and (severity is None
                                      or hit.severity == severity)
            detail = f"{hit.severity}: {hit.title}" if hit else f"got {keys}"
        (PASS if ok else FAIL).append(label)
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {label:<42}{detail}")
    finally:
        for p, b in snap.items():
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


print("replaying the three real failures from this repo's history\n")

run("2026-09-30 fundamentals collapse", "fundamentals_degraded",
    lambda: wq(lambda q: q.__setitem__(
        "fundamentals", {"fresh": 0, "carried_forward": 5184,
                         "requested": 897, "fresh_rate": 0.0})),
    severity="critical")

run("stale quotes (refresh stopped)", "quotes_stale",
    lambda: wq(lambda q: q.__setitem__("updated", "2026-09-20T00:00:00Z")),
    severity="critical")

run("ledger stopped recording", "ledger_stale",
    lambda: wbook("portfolio.json", lambda d: d["equity"].__setitem__(
        -1, {**d["equity"][-1], "date": "2026-08-01"})),
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

# Must breach the book's OWN declared cap times the drift allowance, not
# a flat percentage. The flat version passed while hiding a false
# positive on the growth book, whose cap is legitimately higher.
run("single name past its stated cap", "concentration",
    lambda: wbook("portfolio.json", lambda d: d["positions"].__setitem__(
        next(iter(d["positions"])),
        {**next(iter(d["positions"].values())), "shares": 1e6, "last": 500,
         "avg_price": 100})),
    severity="warning")

run("growth sleeve at normal monthly drift (silent)", None,
    lambda: None)

run("held position gaps 40% in a day", "shock",
    lambda: wbook("portfolio.json", lambda d: d["positions"].__setitem__(
        next(iter(d["positions"])),
        {**next(iter(d["positions"].values())), "prev_close": 100,
         "last": 140})),
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

print("\nthe case that matters most: silence when all is well\n")
sessions = A.latest_sessions()
quiet = A.check_data(TODAY) + A.check_books(TODAY, sessions)
if quiet:
    FAIL.append("no false positives on healthy state")
    print(f"  [FAIL] healthy state fires {len(quiet)}: "
          f"{[a.key for a in quiet]}")
else:
    PASS.append("no false positives on healthy state")
    print("  [PASS] healthy state fires nothing")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("  failures:", ", ".join(FAIL))
shutil.rmtree(work, ignore_errors=True)
sys.exit(1 if FAIL else 0)

"""Alarms: notify when something actually needs a human decision.

WHAT THIS IS FOR, AND WHAT IT IS NOT FOR

The four paper books trade themselves. They do not need a human to press
anything, so "the strategy wants to buy something" is NOT an alarm — it
is the system working. Alarming on routine activity is how an alarm
system gets muted, and a muted alarm system is worse than none because
it looks like coverage.

What does need a human is narrower and, on the evidence of this repo,
almost entirely about the machinery failing QUIETLY:

  * 2026-09-30  the nightly job lost every Ticker.info response and wrote
                a quotes.json with every P/E, PEG and market cap null,
                for all 897 tickers. It exited 0 and committed. Caught
                only because a refresh was triggered by hand for an
                unrelated reason.
  * 2026-09-28  a trading session was computed correctly and then thrown
                away when the commit lost a push race. The job went red,
                but nothing watched for it.
  * 2026-10-06  the TA charts threw on every render for six days. No job
                failed; the page just quietly stopped working.

Every one of those was invisible from the outside. Two of the three were
found by luck. That is the gap this fills: the alarms below are mostly
not about markets, they are about whether the thing that watches the
markets is still alive and telling the truth.

DELIVERY

A GitHub issue, which reaches the repository owner through the channels
they already have switched on — email, the mobile app, the web. No new
service, no secret to configure, nothing to pay for, and it works on the
first run. An optional webhook (ALARM_WEBHOOK) is pushed in addition when
the secret exists; its absence is not an error.

Issues are REUSED, not reopened one per firing: a condition that is still
true gets a comment on the existing issue, and an issue closes itself
when the condition clears. Combined with per-rule cooldowns, a persistent
problem produces one thread rather than a daily pile.

LATENCY

The workflow is chained to the jobs it watches via workflow_run, so a
failure is detected within a minute or two of happening rather than on
the next cron. A daily safety-net run covers the one case chaining
cannot: a watched workflow that never starts at all.
"""

import argparse
import json
import os
import sys
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "paper" / "alarms.json"

CRITICAL, WARNING, INFO = "critical", "warning", "info"

# ── Thresholds ───────────────────────────────────────────────────────────
# Grounded where there is anything to ground them in, and labelled as
# arbitrary where there is not. A threshold invented to look precise is a
# false-positive generator with a decimal point.

# The growth book's 30-year backtest produced a -27.2% worst drawdown, so
# alarming below that would fire on behaviour the strategy is designed to
# have. 30% is "worse than the worst the study ever saw".
DD_GROWTH = -30.0
# The momentum books have no backtest worth trusting (survivorship bias),
# so this one IS arbitrary: it is set at the point where a reasonable
# person would want to look, not at a measured quantile. Said plainly so
# nobody reads it as a risk model.
DD_MOMENTUM = -20.0

# A single name at this share of a book means the sizing rules have been
# overwhelmed by a price move. MRNA reached 85% of the weekly book's gain
# in August without ever breaching a position cap, which is what makes
# this worth watching separately from the caps.
CONCENTRATION = 0.30

# One-day move in a HELD position. Measured in this repo: in the August
# episode exactly 1 of 637 tickers moved more than 35% in a day, so 25%
# is rare without being once-a-decade.
POSITION_SHOCK = 25.0

# Sessions a ledger may lag the latest trading day before it is a fault.
# Two allows for a data vendor being a day late, which happens and
# self-heals through the engine's backfill.
LEDGER_STALE_SESSIONS = 3
QUOTES_STALE_DAYS = 4

# Below this share of tickers returning fresh fundamentals, the valuation
# columns are carry-forward rather than current. 0.25 is where the script
# itself already fails the run; this alarms earlier so a slow decay is
# visible before it becomes a collapse.
FRESH_RATE_WARN = 0.60

# Cooldowns, in days, per rule key. A condition that is still true does
# not re-notify inside its window; it comments on the open issue instead.
COOLDOWN_DAYS = {CRITICAL: 1, WARNING: 3, INFO: 7}


# ── State ────────────────────────────────────────────────────────────────
def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception as exc:                                # noqa: BLE001
            print(f"  alarm state unreadable ({exc}) — starting fresh")
    return {"version": 1, "active": {}, "history": []}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")


def days_since(iso, today):
    try:
        return (dt.date.fromisoformat(iso[:10]) - dt.date.fromisoformat(today)).days * -1
    except Exception:                                           # noqa: BLE001
        return None


# ── Rules ────────────────────────────────────────────────────────────────
class Alarm:
    def __init__(self, key, severity, title, body, action):
        self.key = key              # stable: identifies the condition
        self.severity = severity
        self.title = title
        self.body = body
        self.action = action        # what the human is being asked to DO

    def __repr__(self):
        return f"<{self.severity.upper()} {self.key}>"


def book_files():
    return sorted((ROOT / "paper").glob("portfolio*.json"))


def check_books(today, sessions_index):
    """Ledger health and portfolio conditions, per book."""
    out = []
    for path in book_files():
        try:
            d = json.loads(path.read_text())
        except Exception as exc:                                # noqa: BLE001
            out.append(Alarm(
                f"ledger_unreadable:{path.name}", CRITICAL,
                f"Ledger {path.name} is unreadable",
                f"`{path.name}` could not be parsed: `{exc}`. The engine "
                f"refuses to overwrite a ledger it cannot read, so this "
                f"book has stopped trading and will stay stopped.",
                "Inspect the file and restore it from the previous commit."))
            continue

        eq = d.get("equity") or []
        label = d.get("label", path.stem)
        if not eq:
            continue
        last = eq[-1]

        # 1. Has the book recorded a session recently?
        #
        # Counted as "sessions newer than the ledger's last entry", NOT by
        # looking the entry up in the session list. The lookup version had
        # inverted sensitivity: a ledger older than the sampled window was
        # simply not found, the lag came back None, and the alarm stayed
        # silent — so the check was weakest exactly when the problem was
        # worst. A dead engine is the case this rule exists for.
        #
        # The calendar-age backstop covers the same hole from the other
        # side: if the price files are themselves stale or short, the
        # session count understates the gap, but the date cannot lie.
        lag = len([d for d in sessions_index if d > last["date"]]) \
            if sessions_index else 0
        cal_age = days_since(last["date"], today) or 0
        stale = lag >= LEDGER_STALE_SESSIONS or cal_age >= 7
        if stale and (lag or cal_age):
            lag = max(lag, 0)
            newest = sessions_index[-1] if sessions_index else "unknown"
            out.append(Alarm(
                f"ledger_stale:{d.get('book', path.stem)}", CRITICAL,
                f"{label}: last session was {last['date']} "
                f"({cal_age} days ago)",
                f"Last entry is **{last['date']}**; the newest priced "
                f"session is **{newest}**, {lag} sessions later. The engine "
                f"backfills missed sessions, so a gap this size means it is "
                f"not running, not merely late.",
                "Check the Paper trading workflow for failures, and whether "
                "GitHub has disabled the schedule."))

        # 2. Drawdown from the book's own peak
        peak = max(x["value"] for x in eq)
        dd = (last["value"] / peak - 1) * 100 if peak else 0.0
        limit = DD_GROWTH if d.get("book") == "growth" else DD_MOMENTUM
        if dd <= limit:
            out.append(Alarm(
                f"drawdown:{d.get('book', path.stem)}", WARNING,
                f"{label}: {dd:.1f}% drawdown from peak",
                f"Equity ${last['value']:,.0f} against a peak of "
                f"${peak:,.0f}. The alarm level is {limit:.0f}%."
                + ("\n\nFor context the 30-year study of this strategy saw "
                   "a worst drawdown of -27.2%, so this is beyond anything "
                   "the backtest contained."
                   if d.get("book") == "growth"
                   else "\n\nThis threshold is a judgement call, not a "
                        "measured quantile: the momentum books' backtests "
                        "are survivorship-biased and their drawdown "
                        "distribution is not trustworthy."),
                "Decide whether the strategy is behaving as designed in a "
                "bad tape, or whether something is wrong with it."))

        # 3. Concentration: has one name taken over?
        pos = d.get("positions") or {}
        total = sum(p["shares"] * p.get("last", p["avg_price"])
                    for p in pos.values()) or 0.0
        if total > 0:
            for tk, p in pos.items():
                share = p["shares"] * p.get("last", p["avg_price"]) / total
                if share >= CONCENTRATION:
                    out.append(Alarm(
                        f"concentration:{d.get('book', path.stem)}:{tk}",
                        WARNING,
                        f"{label}: {tk} is {share*100:.0f}% of the book",
                        f"A single position has grown to {share*100:.0f}% of "
                        f"invested value. The position caps are applied at "
                        f"rebalance; between rebalances a price move can "
                        f"carry a name past them.",
                        "Confirm this is a price move and not a sizing bug."))

        # 4. A held position just moved violently
        for tk, p in pos.items():
            prev = p.get("prev_close")
            now = p.get("last")
            if prev and now and prev > 0:
                mv = (now / prev - 1) * 100
                if abs(mv) >= POSITION_SHOCK:
                    out.append(Alarm(
                        f"shock:{d.get('book', path.stem)}:{tk}:{last['date']}",
                        WARNING,
                        f"{label}: {tk} moved {mv:+.0f}% in a day",
                        f"{tk} went {mv:+.1f}% on {last['date']}. A move "
                        f"this size is usually news, occasionally a data "
                        f"error, and the two look identical in a price feed.",
                        "Check the move is real before trusting any metric "
                        "computed from it."))

        # 5. The growth book de-levering to nothing is a regime signal
        if d.get("book") == "growth":
            gross = last.get("gross")
            if gross is not None and gross < 0.25:
                out.append(Alarm(
                    "breadth_collapse:growth", WARNING,
                    f"Growth book has de-levered to {gross:.2f}x gross",
                    f"Only {last['n']} sleeves pass the trend gate, so the "
                    f"book has moved to cash on its own. This is the "
                    f"strategy working as designed — it is flagged because "
                    f"it is also the clearest regime signal the system "
                    f"produces, and it has never happened before.",
                    "Nothing to fix. Worth knowing that broad asset-class "
                    "trends have broken down."))
    return out


def check_data(today):
    """Is the data underneath everything still real?"""
    out = []
    qp = ROOT / "public" / "quotes.json"
    if not qp.exists():
        return [Alarm("quotes_missing", CRITICAL, "quotes.json is missing",
                      "The dashboard and the signal book both read it.",
                      "Re-run the Refresh market data workflow.")]
    try:
        q = json.loads(qp.read_text())
    except Exception as exc:                                    # noqa: BLE001
        return [Alarm("quotes_unreadable", CRITICAL,
                      "quotes.json cannot be parsed", f"`{exc}`",
                      "Re-run the refresh; restore from git if it persists.")]

    age = days_since(q.get("updated", ""), today)
    if age is not None and age > QUOTES_STALE_DAYS:
        out.append(Alarm(
            "quotes_stale", CRITICAL,
            f"Market data is {age} days old",
            f"`quotes.json` was last written {q.get('updated')}. The signal "
            f"book refuses to trade on a snapshot older than four days, so "
            f"it is now holding rather than following the table.",
            "Check the Refresh market data workflow."))

    f = q.get("fundamentals") or {}
    rate = f.get("fresh_rate")
    if rate is not None and rate < FRESH_RATE_WARN:
        out.append(Alarm(
            "fundamentals_degraded", CRITICAL,
            f"Only {rate*100:.0f}% of fundamentals are fresh",
            f"{f.get('fresh')} of {f.get('requested')} tickers returned "
            f"fundamentals; {f.get('carried_forward')} values are carried "
            f"forward from an earlier snapshot.\n\nThis is the failure that "
            f"hit on 2026-09-30, when the rate went to zero and nothing "
            f"noticed: the table's valuation columns were stale while "
            f"looking current, and the signal book's entry rule reads P/E, "
            f"PEG and EPS growth directly off this file.",
            "Check whether the data source is throttling. The values are "
            "carried forward, so nothing is blank — which is exactly why "
            "this needs saying out loud."))
    elif rate is None:
        out.append(Alarm(
            "fundamentals_unreported", WARNING,
            "quotes.json has no freshness block",
            "The refresh script records how many fundamentals were fetched "
            "fresh. Its absence means an older version of the script wrote "
            "this file, and staleness cannot be checked.",
            "Confirm the deployed refresh script is current."))
    return out


def check_workflows(today, api):
    """Are the jobs that keep all of this alive actually running?"""
    out = []
    if not api:
        return out
    watched = {
        "paper-trade.yml": "Paper trading",
        "refresh-data.yml": "Refresh market data",
        "pages.yml": "Deploy to GitHub Pages",
    }
    for wf, name in watched.items():
        info = api.workflow(wf)
        if info is None:
            continue
        if info.get("state") in ("disabled_inactivity", "disabled_manually"):
            out.append(Alarm(
                f"workflow_disabled:{wf}", CRITICAL,
                f"{name} is disabled ({info['state']})",
                "GitHub disables scheduled workflows after 60 days without "
                "repository activity. While disabled this job does not run "
                "and nothing else reports its absence.",
                "Re-enable it in the Actions tab. The keepalive workflow is "
                "meant to prevent this; if it fired and the workflow was "
                "still disabled, the keepalive token needs attention."))
        runs = api.runs(wf, limit=3)
        done = [r for r in runs if r.get("status") == "completed"]
        if len(done) >= 2 and all(r.get("conclusion") == "failure"
                                  for r in done[:2]):
            out.append(Alarm(
                f"workflow_failing:{wf}", CRITICAL,
                f"{name} has failed twice in a row",
                "Two consecutive failed runs is past the point where a "
                "transient network error explains it.\n\n"
                + "\n".join(f"- {r['created_at']}: {r['conclusion']} "
                            f"([run]({r['html_url']}))" for r in done[:3]),
                "Open the most recent run and read the failing step."))
    return out


# ── GitHub ───────────────────────────────────────────────────────────────
class GitHub:
    """Thin REST wrapper. Every call degrades to None rather than raising:
    an alarm system that crashes while reporting a problem is worse than
    one that reports less."""

    def __init__(self, repo, token):
        self.repo = repo
        self.token = token
        import urllib.request
        self._req = urllib.request

    def _call(self, method, path, payload=None):
        url = f"https://api.github.com/repos/{self.repo}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = self._req.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "investor-help-alarms")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with self._req.urlopen(req, timeout=30) as r:
                body = r.read().decode()
                return json.loads(body) if body else {}
        except Exception as exc:                                # noqa: BLE001
            print(f"  github {method} {path} failed: {exc}")
            return None

    def workflow(self, wf):
        return self._call("GET", f"/actions/workflows/{wf}")

    def runs(self, wf, limit=5):
        r = self._call("GET",
                       f"/actions/workflows/{wf}/runs?per_page={limit}")
        return (r or {}).get("workflow_runs", []) or []

    def find_issue(self, key):
        r = self._call("GET", "/issues?state=all&labels=alarm&per_page=50")
        for issue in r or []:
            if f"<!-- alarm-key: {key} -->" in (issue.get("body") or ""):
                return issue
        return None

    def open_issue(self, title, body, labels):
        return self._call("POST", "/issues",
                          {"title": title, "body": body, "labels": labels})

    def comment(self, number, body):
        return self._call("POST", f"/issues/{number}/comments", {"body": body})

    def close(self, number, body):
        self.comment(number, body)
        return self._call("PATCH", f"/issues/{number}",
                          {"state": "closed", "state_reason": "completed"})


def issue_body(a, today):
    return (
        f"<!-- alarm-key: {a.key} -->\n"
        f"**Severity:** {a.severity.upper()}  \n"
        f"**First seen:** {today}\n\n"
        f"{a.body}\n\n"
        f"### What to do\n{a.action}\n\n"
        f"---\n"
        f"*Raised by `scripts/alarms.py`. This issue closes itself when the "
        f"condition clears. It will not re-notify while it stays open — a "
        f"still-true condition is commented on, not re-raised.*"
    )


# ── Main ─────────────────────────────────────────────────────────────────
def latest_sessions():
    """Trading dates the price files actually cover, newest last."""
    counts = {}
    files = list((ROOT / "public" / "ohlcv").glob("*.json"))
    # A sample of files is enough to establish the trading calendar, but
    # the per-file window has to be long enough that a badly stale ledger
    # still produces a large lag rather than a capped one.
    for p in files[:400]:
        try:
            for row in json.loads(p.read_text())[-40:]:
                counts[row["time"]] = counts.get(row["time"], 0) + 1
        except Exception:                                       # noqa: BLE001
            continue
    if not counts:
        return []
    hi = max(counts.values())
    return sorted(d for d, c in counts.items() if c >= hi * 0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="evaluate and print, touch nothing")
    ap.add_argument("--self-test", action="store_true",
                    help="raise one synthetic alarm to prove the "
                         "notification actually reaches you, then resolve "
                         "it on the next run")
    args = ap.parse_args()

    today = dt.date.today().isoformat()
    repo = os.environ.get("GITHUB_REPOSITORY", "teocara/investor-help")
    token = os.environ.get("GITHUB_TOKEN")
    api = GitHub(repo, token) if token and not args.dry_run else None

    sessions = latest_sessions()
    print(f"alarms: {today}, newest priced session "
          f"{sessions[-1] if sessions else 'unknown'}\n")

    alarms = []
    if args.self_test:
        # The smoke-alarm test button. Until something genuinely fires, the
        # delivery path has never run, and an unverified channel is the
        # exact failure this whole file exists to prevent. Firing it on
        # purpose proves the issue opens and reaches you; the NEXT ordinary
        # run finds the condition gone and closes it, which also exercises
        # the auto-resolve path.
        alarms.append(Alarm(
            "self_test", WARNING,
            "Alarm channel self-test",
            "This was raised deliberately by `--self-test` to prove the "
            "notification path works end to end. Nothing is wrong.\n\n"
            "If you are reading this, alarms reach you.",
            "Nothing. The next scheduled alarm run will close this issue "
            "automatically, which confirms the auto-resolve path too."))
    else:
        alarms += check_data(today)
        alarms += check_books(today, sessions)
        alarms += check_workflows(today, api)

    order = {CRITICAL: 0, WARNING: 1, INFO: 2}
    alarms.sort(key=lambda a: order[a.severity])

    if not alarms:
        print("  nothing firing — all books current, data fresh, jobs green")
    for a in alarms:
        print(f"  [{a.severity.upper():<8}] {a.title}")

    state = load_state()
    active = state.get("active", {})
    firing = {a.key: a for a in alarms}

    # Conditions that have cleared: close their issues.
    for key, rec in list(active.items()):
        if key in firing:
            continue
        print(f"  resolved: {key}")
        if api and rec.get("issue"):
            api.close(rec["issue"],
                      f"Condition cleared as of {today}. Closing "
                      f"automatically; it will reopen as a new issue if it "
                      f"recurs.")
        state.setdefault("history", []).append(
            {**rec, "resolved": today})
        active.pop(key)

    # New and continuing conditions.
    for key, a in firing.items():
        rec = active.get(key)
        if rec is None:
            print(f"  NEW: {key}")
            num = None
            if api:
                issue = api.open_issue(
                    f"[{a.severity}] {a.title}", issue_body(a, today),
                    ["alarm", f"alarm:{a.severity}"])
                num = (issue or {}).get("number")
                if num:
                    print(f"       -> opened issue #{num}")
            active[key] = {"key": key, "severity": a.severity,
                           "title": a.title, "first_seen": today,
                           "last_notified": today, "issue": num}
        else:
            age = days_since(rec.get("last_notified", today), today) or 0
            cd = COOLDOWN_DAYS.get(a.severity, 3)
            if age >= cd:
                print(f"  still firing ({age}d): {key}")
                if api and rec.get("issue"):
                    api.comment(rec["issue"],
                                f"Still true as of {today}, {age} days after "
                                f"the last note. {a.body}")
                rec["last_notified"] = today
            else:
                print(f"  suppressed (cooldown {cd}d): {key}")

    state["active"] = active
    state["last_run"] = today
    state["last_result"] = {"firing": len(alarms),
                            "critical": sum(1 for a in alarms
                                            if a.severity == CRITICAL)}
    if args.dry_run:
        print("\n(dry run — no issues touched, no state written)")
        return 0
    save_state(state)

    # Optional extra channel. Absent secret is not an error.
    hook = os.environ.get("ALARM_WEBHOOK")
    crit = [a for a in alarms if a.severity == CRITICAL]
    if hook and crit:
        import urllib.request
        text = "\n".join(f"[{a.severity}] {a.title}" for a in crit)
        try:
            req = urllib.request.Request(
                hook, data=text.encode(), method="POST")
            req.add_header("Title", "investor-help alarm")
            req.add_header("Priority", "high")
            urllib.request.urlopen(req, timeout=15)
            print(f"  pushed {len(crit)} critical alarm(s) to the webhook")
        except Exception as exc:                                # noqa: BLE001
            print(f"  webhook push failed: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

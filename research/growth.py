"""Thirty-year test of the long-run growth book.

WHAT IS BEING MAXIMISED

Not average return — compound return. The two are not the same, and the
gap between them is the whole design:

    g  ~=  mu  -  sigma^2 / 2

g is what actually multiplies the money. Volatility is not merely
discomfort, it is a direct subtraction from terminal wealth, which is why
a book built to compound looks different from a book built to score well
in an average year. Cutting sigma from 20% to 14% adds ~1.0 point of
compound return even if mu does not move at all.

Three consequences drive every rule below:
  1. imperfectly correlated sleeves lower sigma at constant mu
  2. a -50% needs +100% back, so avoiding the deep left tail beats
     catching the top of the rally
  3. leverage has an interior optimum, so exposure is capped

The universe is broad index funds, so the result is not survivorship
biased the way a watchlist backtest is.

WHAT THE 30-YEAR TEST ACTUALLY SAID, including where it contradicted
the design it was meant to confirm:

  * The optimum in (3) is NOT the textbook Kelly point. Sweeping the cap
    on frictionless financing, growth still rises at 3x and only flattens
    near 3.5x, because the Kelly fraction for an 8%-vol book is enormous.
    What creates a usable optimum is the FINANCING CURVE: charge what a
    broker actually charges as leverage rises and growth peaks at 2.0x
    and falls hard after. The cap is set by the cost of money, not by
    Kelly. The docstring used to claim otherwise; the sweep disagreed.

  * Volatility targeting does nothing here. At a 2x cap the cap binds
    first, so the target never engages - and forcing it to engage costs
    ~1.5 points of CAGR while improving max drawdown by ~3 points. The
    reason is that the trend gate is ALREADY a volatility control: when
    vol spikes, sleeves break their moving averages and are sold, so
    exposure falls mechanically. The target is kept only as a backstop
    for a regime the 30 years did not contain. It did not bind once.

  * The gates are the strategy. Remove both and the book returns 10.20%
    with a -52.9% drawdown - indistinguishable from just holding the
    index. Everything else is sizing.

  * The sleeve and equity-block caps did not work as written. They were
    applied and then normalised away on the next line, so they never bound
    in the one case they exist for - every eligible sleeve being equity.
    Fixing them costs ~0.9 points of CAGR and buys 4 points of drawdown at
    identical Sharpe, and is better in every crisis window. Taken, because
    a constraint that silently does nothing is worse than no constraint:
    it is a claim about the book that is not true.

  * The edge is fragile to costs and concentrated in time. See
    growth_report.py, which prints both.
"""
import json, math, statistics as st
from pathlib import Path

DATA = Path("public/growth-history")

# Exactly thirty years back from the last full session in the data.
START = "1995-09-29"      # warmup runs here; the book goes live 1996-09-30
TRADING = 252

# ── Sleeves ──────────────────────────────────────────────────────────────
SLEEVES = {
    "VFINX": ("US large cap",        "equity"),
    "NAESX": ("US small cap",        "equity"),
    "VIVAX": ("US large value",      "equity"),
    "VEURX": ("Europe",              "equity"),
    "VPACX": ("Pacific",             "equity"),
    "VEIEX": ("Emerging markets",    "equity"),
    "VGSIX": ("US REITs",            "real"),
    "VGPMX": ("Precious metals",     "real"),
    "VUSTX": ("Long Treasuries",     "bond"),
    "VFITX": ("Interm. Treasuries",  "bond"),
    "VWESX": ("Long IG credit",      "bond"),
}
BENCH = "VFINX"

# ── Rules ────────────────────────────────────────────────────────────────
P = dict(
    band         = 0.02,   # no-trade band, fraction of equity
    lev_band     = 0.10,   # leave the exposure alone unless it moved >10%
    trend_days   = 210,    # 10-month SMA (Faber 2007) - not fitted here
    mom_days     = 252,    # 12-month absolute momentum vs T-bills
    vol_days     = 126,    # 6-month realised vol for the risk weights
    cov_days     = 252,    # 12-month covariance for portfolio vol
    shrink       = 0.30,   # toward the diagonal; 11 assets on 252 days is noisy
    target_vol   = 0.30,   # BACKSTOP only - see the note above. At a 2x cap
                           # this never bound in 30 years; it exists for a
                           # vol regime the test period did not contain.
    max_lev      = 2.00,   # where growth peaks once financing is charged
                           # realistically. Not a Kelly number.
    hard_caps    = True,   # caps bind on GROSS exposure. With the caps
                           # applied before normalisation they were undone
                           # by the very next line, so they never bound when
                           # every eligible sleeve was equity - exactly when
                           # they were wanted. See growth_caps.py.
    max_sleeve   = 0.25,
    max_equity   = 0.70,   # or it becomes a closet all-equity book
    cost_bps     = 0.0010,
    borrow_spread= 0.0100, # over T-bills, on the part above 1.0x
    exec_lag     = 1,      # signal at the close, fill at the NEXT close
    rebal_months = 1,      # asset-class trends are slow; this is the knob
)


# ── Data ─────────────────────────────────────────────────────────────────
def load(name):
    p = DATA / f"{name}.json"
    if not p.exists():
        return {}
    return {r["time"]: r["close"] for r in json.load(open(p)) if r.get("close")}


def build():
    raw = {t: load(t) for t in SLEEVES}
    raw = {t: m for t, m in raw.items() if m}
    missing = [t for t in SLEEVES if t not in raw]
    if missing:
        print(f"  (missing sleeves, skipped: {', '.join(missing)})")

    bench = load(BENCH)
    irx = load("_IRX")

    # Calendar starts at a fixed date, NOT at the youngest sleeve's
    # inception. A sleeve with too little history simply fails the gates
    # and is not held — which is also the truth an investor faced: no one
    # could own a REIT index fund in 1996 either. Truncating the window to
    # the youngest sleeve would instead hand the early years a universe
    # chosen with hindsight.
    dates = sorted(d for d in bench if d >= START)

    def align(m):
        out, last = [], None
        for d in dates:
            if d in m:
                last = m[d]
            out.append(last)
        return out

    px = {t: align(m) for t, m in raw.items()}
    # ^IRX is an annualised discount rate in percent, not a price.
    rf_ann, last = [], 5.0
    for d in dates:
        if d in irx and 0 <= irx[d] < 25:
            last = irx[d]
        rf_ann.append(last / 100.0)
    return dates, px, align(bench), rf_ann


# ── Indicators ───────────────────────────────────────────────────────────
def sma(series, i, n):
    w = [x for x in series[max(0, i - n + 1): i + 1] if x]
    return sum(w) / len(w) if len(w) >= n * 0.8 else None


def rets(series, i, n):
    out = []
    for j in range(max(1, i - n + 1), i + 1):
        a, b = series[j - 1], series[j]
        if a and b and a > 0:
            out.append(b / a - 1)
    return out


def vol(series, i, n):
    r = rets(series, i, n)
    if len(r) < n * 0.5:
        return None
    m = sum(r) / len(r)
    v = sum((x - m) ** 2 for x in r) / (len(r) - 1)
    return math.sqrt(v * TRADING)


def port_vol(px, names, w, i, n, shrink):
    """Annualised vol of the weight vector, on a shrunk covariance."""
    cols = {t: rets(px[t], i, n) for t in names}
    k = min(len(c) for c in cols.values()) if cols else 0
    if k < n * 0.5:
        return None
    cols = {t: c[-k:] for t, c in cols.items()}
    mu = {t: sum(c) / k for t, c in cols.items()}
    var = 0.0
    for a in names:
        for b in names:
            cov = sum((cols[a][z] - mu[a]) * (cols[b][z] - mu[b])
                      for z in range(k)) / (k - 1)
            if a != b:
                cov *= (1 - shrink)          # shrink the off-diagonal only
            var += w[a] * w[b] * cov
    return math.sqrt(max(var, 1e-12) * TRADING)


# ── The book ─────────────────────────────────────────────────────────────
def month_ends(dates):
    out = []
    for i in range(len(dates) - 1):
        if dates[i][:7] != dates[i + 1][:7]:
            out.append(i)
    return out


def run(dates, px, rf_ann, p, names=None, start_i=None):
    names = names or sorted(px)
    warm = max(p["trend_days"], p["mom_days"], p["cov_days"]) + 5
    i0 = start_i if start_i is not None else warm
    every = p.get("rebal_months", 1)
    rb = {i + p["exec_lag"]
          for k, i in enumerate(month_ends(dates))
          if i >= i0 and k % every == 0}

    equity, cash = 100_000.0, 100_000.0
    pos = {}                     # ticker -> shares
    curve, wlog, costs, turn = [], [], 0.0, 0.0
    turn_frac = []               # traded value / equity, per rebalance
    prev_scale = None
    lev_log, nheld = [], []

    for i in range(i0, len(dates)):
        rf_d = (1 + rf_ann[i]) ** (1 / TRADING) - 1

        held = sum(sh * px[t][i] for t, sh in pos.items() if px[t][i])
        equity = held + cash
        if cash >= 0:
            cash *= (1 + rf_d)                                   # T-bill yield
        else:
            cash *= (1 + rf_d + p["borrow_spread"] / TRADING)    # margin cost
        equity = held + cash

        if i in rb and equity > 0:
            # 1. absolute momentum + trend gate
            elig = []
            for t in names:
                s = px[t]
                if not s[i]:
                    continue
                if p.get("use_trend", True):
                    m = sma(s, i, p["trend_days"])
                    if not m or s[i] <= m:
                        continue
                if p.get("use_mom", True):
                    j = i - p["mom_days"]
                    if j < 0 or not s[j] or s[j] <= 0:
                        continue
                    tbill = (1 + rf_ann[i]) ** (p["mom_days"] / TRADING) - 1
                    if s[i] / s[j] - 1 <= tbill:  # must beat cash, not just 0
                        continue
                v = vol(s, i, p["vol_days"])
                if not v or v <= 0:
                    continue
                elig.append((t, v))

            w = {}
            if elig:
                # 2. inverse-vol weights, capped, equity block capped
                raw = ({t: 1 / v for t, v in elig} if p.get("use_ivol", True)
                       else {t: 1.0 for t, _ in elig})
                tot = sum(raw.values())
                w = {t: raw[t] / tot for t, _ in elig}
                if p.get("hard_caps", False):
                    # Cap as a share of GROSS: normalise first, then cut, and
                    # do NOT renormalise. Otherwise the cut is undone by the
                    # very next line and the cap never binds - which is
                    # precisely what happens when every eligible sleeve is
                    # equity, i.e. exactly when the cap is wanted.
                    s0 = sum(w.values())
                    w = {t: x / s0 for t, x in w.items()} if s0 > 0 else w
                    w = {t: min(x, p["max_sleeve"]) for t, x in w.items()}
                    eq = [t for t in w if SLEEVES[t][1] == "equity"]
                    se = sum(w[t] for t in eq)
                    if se > p["max_equity"]:
                        for t in eq:
                            w[t] *= p["max_equity"] / se
                else:
                    w = {t: min(x, p["max_sleeve"]) for t, x in w.items()}
                    eq = [t for t in w if SLEEVES[t][1] == "equity"]
                    se = sum(w[t] for t in eq)
                    if se > p["max_equity"]:
                        for t in eq:
                            w[t] *= p["max_equity"] / se
                    s = sum(w.values())
                    if s > 0:
                        w = {t: x / s for t, x in w.items()}

                # 3. volatility targeting, 4. leverage cap
                if p.get("use_voltarget", True):
                    pv = port_vol(px, list(w), w, i, p["cov_days"], p["shrink"])
                    scale = min(p["max_lev"], p["target_vol"] / pv) if pv else 1.0
                else:
                    scale = p["max_lev"]
                # Re-levering for a 2% move in estimated vol is pure churn.
                if (prev_scale is not None and prev_scale > 0
                        and abs(scale - prev_scale) / prev_scale
                        < p.get("lev_band", 0.0)):
                    scale = prev_scale
                prev_scale = scale
                # Sleeves that failed the gate are NOT replaced: the book
                # de-risks on its own when breadth collapses.
                gate = len(w) / len(names)
                scale *= min(1.0, gate / 0.5) if gate < 0.5 else 1.0
                w = {t: x * scale for t, x in w.items()}
            lev_log.append(sum(w.values()))
            nheld.append(len(w))

            # 5. trade to target
            tgt = {t: equity * x for t, x in w.items()}
            traded = 0.0
            for t in list(pos):
                if t not in tgt:
                    v = pos.pop(t) * px[t][i]
                    costs += v * p["cost_bps"]; turn += v; traded += v
                    cash += v * (1 - p["cost_bps"])
            for t, want in tgt.items():
                have = pos.get(t, 0.0) * px[t][i]
                d = want - have
                if abs(d) < equity * p.get("band", 0.005):
                    continue
                turn += abs(d); traded += abs(d)
                costs += abs(d) * p["cost_bps"]
                if d > 0:
                    cash -= d
                    pos[t] = pos.get(t, 0.0) + d * (1 - p["cost_bps"]) / px[t][i]
                else:
                    cash += -d * (1 - p["cost_bps"])
                    pos[t] = pos.get(t, 0.0) + d / px[t][i]
                if pos.get(t, 0) <= 1e-9:
                    pos.pop(t, None)
            turn_frac.append(traded / equity if equity > 0 else 0.0)
            wlog.append((dates[i], {t: round(x, 4) for t, x in w.items()}))

        held = sum(sh * px[t][i] for t, sh in pos.items() if px[t][i])
        curve.append(held + cash)

    years = (len(curve) / TRADING)
    # Turnover as traded value over the equity AT THE TIME, annualised -
    # dividing by the $100k start would grow with the book and mean nothing.
    tpy = (sum(turn_frac) / years) if turn_frac else 0.0
    return dict(curve=curve, dates=dates[i0:], costs=costs,
                turnover=tpy, weights=wlog,
                avg_lev=sum(lev_log) / len(lev_log) if lev_log else 0,
                avg_n=sum(nheld) / len(nheld) if nheld else 0)


# ── Statistics ───────────────────────────────────────────────────────────
def stats(curve, rf_ann=None):
    n = len(curve)
    yrs = n / TRADING
    mult = curve[-1] / curve[0]
    cagr = (mult ** (1 / yrs) - 1) * 100
    peak, mdd = curve[0], 0.0
    for x in curve:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    r = [curve[i] / curve[i - 1] - 1 for i in range(1, n)]
    m = sum(r) / len(r)
    sd = math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1))
    ann_sd = sd * math.sqrt(TRADING)
    rf = (sum(rf_ann) / len(rf_ann)) if rf_ann else 0.0
    sharpe = (m * TRADING - rf) / ann_sd if ann_sd else 0
    dn = [x for x in r if x < 0]
    dsd = (math.sqrt(sum(x * x for x in dn) / len(dn)) * math.sqrt(TRADING)
           if dn else 0)
    sortino = (m * TRADING - rf) / dsd if dsd else 0
    # the quantity the whole design targets
    drag = (m * TRADING * 100) - cagr
    return dict(cagr=cagr, mdd=mdd * 100, vol=ann_sd * 100, sharpe=sharpe,
                sortino=sortino, calmar=cagr / abs(mdd * 100) if mdd else 0,
                mult=mult, years=yrs, arith=m * TRADING * 100, drag=drag)

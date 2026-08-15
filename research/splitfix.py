"""Repair unadjusted share splits in the study data.

yfinance's auto_adjust misses corporate actions on some Euronext listings.
LQQ.PA carries a ~205x split on 2015-01-02 that is not adjusted, which makes
the fund look like it lost 99.5% in a day. Left uncorrected it destroys every
statistic computed from the series.

Detection: a single-bar move so large it cannot be a price move for a fund of
this leverage, AND not corroborated by the underlying index on the same day.
Repair: rescale everything before the break so the series is continuous.
"""
import json, math

PATH = "/home/user/investor-help/public/study/leveraged.json"

def despike(rows, thresh=0.45):
    """Remove isolated bad prints: a bar whose move is extreme and is undone
    by the very next bar. These are data errors, not corporate actions, and
    rescaling around them corrupts the whole series."""
    fixed = [dict(r) for r in rows]
    n = 0
    for i in range(1, len(fixed)-1):
        a, b, c = fixed[i-1]["c"], fixed[i]["c"], fixed[i+1]["c"]
        if a <= 0 or b <= 0 or c <= 0:
            continue
        r1, r2 = b/a-1, c/b-1
        # extreme move immediately reversed, and the level returns to where it was
        if abs(r1) > thresh and abs(r2) > thresh and r1*r2 < 0 and abs(c/a-1) < 0.25:
            fixed[i]["c"] = round((a+c)/2, 6)
            n += 1
    return fixed, n

def find_splits(rows, ref=None, thresh=0.45):
    """Return [(index, factor)] where factor rescales the PRE-break history."""
    out = []
    for i in range(1, len(rows)):
        prev, cur = rows[i-1]["c"], rows[i]["c"]
        if prev <= 0 or cur <= 0:
            continue
        r = cur/prev - 1
        if abs(r) < thresh:
            continue
        # corroborate against the underlying: a real move shows up there too
        if ref is not None:
            rr = ref.get(rows[i]["t"]), ref.get(rows[i-1]["t"])
            if rr[0] and rr[1]:
                idx_move = rr[0]/rr[1]-1
                # a genuine 2-3x move is bounded by ~4x the index move
                if abs(idx_move) > abs(r)/4:
                    continue
        out.append((i, cur/prev))
    return out

def repair(rows, splits):
    if not splits:
        return rows, []
    fixed = [dict(r) for r in rows]
    notes = []
    for idx, factor in splits:
        for j in range(idx):
            fixed[j]["c"] = round(fixed[j]["c"]*factor, 6)
        notes.append((rows[idx]["t"], 1/factor))
    return fixed, notes

if __name__ == "__main__":
    D = json.load(open(PATH))
    ref = {r["t"]: r["c"] for r in D["QQQ"]["rows"]}
    changed = False
    for k in list(D):
        if k in ("QQQ", "^IRX", "^VXN", "EURUSD=X", "DKKUSD=X"):
            continue
        rows = D[k]["rows"]
        rows, nspike = despike(rows)
        if nspike:
            D[k]["rows"] = rows
            D[k]["despiked"] = nspike
            changed = True
            print(f"{k:10} removed {nspike} isolated bad tick(s)")
        sp = find_splits(rows, ref)
        if sp:
            fixed, notes = repair(rows, sp)
            D[k]["rows"] = fixed
            D[k]["split_adjusted"] = [{"date": d, "ratio": round(x, 4)} for d, x in notes]
            changed = True
            for d, x in notes:
                print(f"{k:10} repaired {x:.1f}:1 split on {d}")
            print(f"{k:10} now {fixed[0]['c']:.4f} -> {fixed[-1]['c']:.4f}"
                  f"   total {fixed[-1]['c']/fixed[0]['c']:.1f}x")
        else:
            print(f"{k:10} no unadjusted splits found")
    if changed:
        json.dump(D, open(PATH, "w"), separators=(",", ":"))
        print("\nwrote repaired dataset")

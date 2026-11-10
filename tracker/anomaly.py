#!/usr/bin/env python3
"""anomaly.py - flag unusual accounts in boards_log.csv (descriptive, no accusations).

Usage:
    python3 anomaly.py /path/to/boards_log.csv [output_dir] [days]
      output_dir  default: ./anomaly_out      days  default: 14 (look-back window)

Writes (inside output_dir):
    anomaly_report.txt   plain-language summary of the top flagged accounts
    anomaly_metrics.csv  every metric for every account (open in a spreadsheet)
On the Pi: python3 anomaly.py ~/docker/territory-tracker/data/boards_log.csv ~/anomaly_out
Nothing is uploaded anywhere.

What it looks at (all from public board numbers, no locations):
  steady_share   share of hourly intervals with ANY gain (24/7 steady feed vs human sessions)
  top3_share     share of the window's gain that came from the 3 biggest hours (batch uploads)
  old_data_gap   week-board gain vs all-time gain over the same 7 days (low = old data uploaded now)
  wifi_decay     share of intervals where WiFi total went DOWN (a few accounts barely ever do)
  ble_share      BLE as a share of total gain
  cells_24h      biggest 24h jump in presence cells (2 km each) -> distance of all-new road needed
  cells_jump     biggest single-interval presence jump
A flag means "different from peers on this measure", not "doing something wrong".
"""
import csv, sys, os, statistics as st
from collections import defaultdict
from datetime import datetime, timedelta

if len(sys.argv) < 2:
    sys.exit(__doc__)
SRC = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "anomaly_out"
DAYS = int(sys.argv[3]) if len(sys.argv) > 3 else 14
os.makedirs(OUT, exist_ok=True)

def T(s):
    return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")

def num(x):
    try:
        return int(float(x))
    except Exception:
        return None

series = defaultdict(dict)   # (board, pid) -> {ts: (value, wifi, ble)}
names = {}
tmax = None
for r in csv.DictReader(open(SRC, encoding="utf-8")):
    t = T(r["sample_ts"])
    tmax = t if tmax is None or t > tmax else tmax
    pid = r["player_id"]
    names[pid] = r["username"]
    series[(r["board"], pid)][t] = (num(r["value"]), num(r["wifi"]), num(r["ble"]))
cut = tmax - timedelta(days=DAYS)

def pts(board, pid, since=None):
    d = series.get((board, pid), {})
    return [(t, d[t]) for t in sorted(d) if since is None or t >= since]

rows = []
for pid in sorted({p for (b, p) in series if b == "all_time"}, key=int):
    a = pts("all_time", pid, cut)
    if len(a) < 40 or a[0][1][1] is None:
        continue
    gains, wifi_dec, active, n = [], 0, 0, 0
    wsum = bsum = 0
    for (t0, v0), (t1, v1) in zip(a, a[1:]):
        if v0[1] is None or v1[1] is None:
            continue
        dw, db = v1[1] - v0[1], v1[2] - v0[2]
        n += 1
        if dw < 0:
            wifi_dec += 1
        if dw > 0 or db > 0:
            active += 1
        g = max(dw, 0) + max(db, 0)
        gains.append(g)
        wsum += max(dw, 0)
        bsum += max(db, 0)
    tot = sum(gains)
    if n < 30 or tot <= 0:
        continue
    top3 = sum(sorted(gains, reverse=True)[:3]) / tot
    # week board vs all-time gain over the same 7 days
    gap = None
    w = pts("week", pid)
    if w and a:
        t_end = a[-1][0]
        base = [x for x in a if x[0] <= t_end - timedelta(days=7)]
        wv = [x for x in w if x[0] == t_end]
        if base and wv and wv[0][1][0] is not None and a[-1][1][0] is not None:
            at_gain = a[-1][1][0] - base[-1][1][0]
            if at_gain > 20000:
                gap = wv[0][1][0] / at_gain
    # presence cells
    c = pts("cells", pid, cut)
    c24 = cj = None
    if len(c) > 5:
        vals = [(t, v[0]) for t, v in c if v[0] is not None]
        cj = max((b[1] - a_[1] for a_, b in zip(vals, vals[1:])), default=0)
        best = 0
        j = 0
        for i in range(len(vals)):
            while vals[i][0] - vals[j][0] > timedelta(hours=24):
                j += 1
            best = max(best, vals[i][1] - vals[j][1])
        c24 = best
    rows.append(dict(pid=pid, name=names[pid], intervals=n, total_gain=tot,
                     steady_share=round(active / n, 3), top3_share=round(top3, 3),
                     old_data_gap=None if gap is None else round(gap, 2),
                     wifi_decay=round(wifi_dec / n, 3), ble_share=round(bsum / tot, 3),
                     cells_24h=c24, cells_jump=cj))

def robust_z(vals, x):
    v = [y for y in vals if y is not None]
    if len(v) < 8 or x is None:
        return 0.0
    m = st.median(v)
    mad = st.median([abs(y - m) for y in v]) or 1e-9
    return 0.6745 * (x - m) / mad

metrics = ["steady_share", "top3_share", "wifi_decay", "ble_share", "cells_24h"]
for r in rows:
    flags = []
    for m in metrics:
        z = robust_z([q[m] for q in rows], r[m])
        r["z_" + m] = round(z, 1)
    if r["steady_share"] >= 0.9 and r["total_gain"] > 100000:
        flags.append("gains in %d%% of hourly intervals (very steady feed)" % round(r["steady_share"] * 100))
    if r["wifi_decay"] < 0.4 and st.median([q["wifi_decay"] for q in rows]) > 0.5:
        flags.append("WiFi total decreases in only %d%% of intervals (peers: about %d%%)" % (round(r["wifi_decay"] * 100), round(st.median([q["wifi_decay"] for q in rows]) * 100)))
    if r["top3_share"] >= 0.8 and r["total_gain"] > 100000:
        flags.append("%d%% of gain came from 3 hours (batch uploads)" % round(r["top3_share"] * 100))
    if r["old_data_gap"] is not None and r["old_data_gap"] < 0.5:
        flags.append("week board counts only %d%% of 7-day all-time gain (mostly older data)" % round(r["old_data_gap"] * 100))
    if r["cells_24h"] is not None and r["cells_24h"] >= 500:
        flags.append("+%d presence cells in 24h (about %d km of all-new road)" % (r["cells_24h"], r["cells_24h"] * 2))
    if r["cells_jump"] is not None and r["cells_jump"] >= 300:
        flags.append("single-interval presence jump of +%d cells" % r["cells_jump"])
    if r["z_ble_share"] >= 3:
        flags.append("BLE share unusually high (%d%% of gain)" % round(r["ble_share"] * 100))
    r["flags"] = " | ".join(flags)
    r["n_flags"] = len(flags)

rows.sort(key=lambda r: (-r["n_flags"], -r["total_gain"]))
with open(os.path.join(OUT, "anomaly_metrics.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

lines = ["Anomaly report - window: last %d days up to %s UTC, %d accounts with enough hourly data" % (DAYS, tmax, len(rows)),
         "A flag means 'different from peers', not 'doing something wrong'.", ""]
shown = 0
for r in rows:
    if r["n_flags"] == 0:
        break
    shown += 1
    lines.append("%s (id %s)  gain %s in window" % (r["name"], r["pid"], format(r["total_gain"], ",")))
    for fl in r["flags"].split(" | "):
        lines.append("   - " + fl)
    if shown >= 25:
        break
lines += ["", "Accounts with no flags: %d" % (len(rows) - shown)]
open(os.path.join(OUT, "anomaly_report.txt"), "w", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines))
print("\nFiles written to:", os.path.abspath(OUT))

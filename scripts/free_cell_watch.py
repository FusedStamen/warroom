#!/usr/bin/env python3
"""Unowned-cell anomaly inspection for warroom (cells where you have APs but no gang is listed as owner).

Two modes:
  python3 free_cell_watch.py snap   <workdir>   take one snapshot (run this on a timer)
  python3 free_cell_watch.py report <workdir>   analyze all snapshots, write the report

Needs:   <workdir>/warroom.token    the warroom token alone on one line (never printed or saved elsewhere)
Output:  <workdir>/snapshots/state_YYYYmmdd_HHMMSS.csv.gz   one file per snapshot (UTC time of the run)
         <workdir>/free_cell_watch_log.txt                    one line per snap run (ok / skipped / error)
         <workdir>/free_cell_report.txt                       written by "report"

What a snapshot holds: every cell where my_aps > 0, plus the 8 neighbors of each unowned cell with
my_aps >= 100 (so neighbor ownership changes are visible too). Columns:
  i, j, sw_lat, sw_lon, status, gang, count, my_aps, towers, owner, held, poll
status is the warroom value: mine / enemy / free. "free" = no gang listed as owner.

The report only describes what changed in the data. It does not decide why.
Nothing is sent anywhere except one GET to the warroom API with your token.
"""
import os as _os, sys as _sys
WARROOM_URL = _os.environ.get("WARROOM_URL", "").rstrip("/")
if not WARROOM_URL:
    _sys.exit("Set the WARROOM_URL environment variable to your warroom address first, e.g.  WARROOM_URL=https://warroom.example.com")
import csv
import gzip
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = WARROOM_URL
UA = "curl/8.5.0"          # warroom blocks other User-Agents
NEIGHBOR_MIN_APS = 100
COLS = ["i", "j", "sw_lat", "sw_lon", "status", "gang", "count", "my_aps", "towers", "owner", "held", "poll"]


def log(work, msg):
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z  {msg}"
    print(line)
    with (work / "free_cell_watch_log.txt").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def snap(work):
    tokf = work / "warroom.token"
    if not tokf.exists():
        sys.exit(f"Missing {tokf} (put the warroom token alone on one line)")
    token = tokf.read_text().strip()
    req = urllib.request.Request(BASE + "/api/state", headers={"Authorization": f"Bearer {token}", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
    except Exception as e:  # never include the token in error text
        log(work, f"ERROR fetching state: {type(e).__name__}")
        sys.exit(1)
    poll = (d.get("meta") or {}).get("last_poll", "")
    snaps = work / "snapshots"
    snaps.mkdir(exist_ok=True)
    # skip if the server state has not been refreshed since the last snapshot
    last = sorted(snaps.glob("state_*.csv.gz"))
    if last:
        with gzip.open(last[-1], "rt", encoding="utf-8", newline="") as f:
            first = next(csv.DictReader(f), None)
        if first and first.get("poll") == poll:
            log(work, f"skipped: server last_poll unchanged ({poll})")
            return
    cells = d["cells"]
    idx = {(c["i"], c["j"]): c for c in cells}
    keep = {}
    for c in cells:
        if (c.get("my_aps") or 0) > 0:
            keep[(c["i"], c["j"])] = c
        if c.get("status") == "free" and (c.get("my_aps") or 0) >= NEIGHBOR_MIN_APS:
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    n = idx.get((c["i"] + di, c["j"] + dj))
                    if n:
                        keep[(n["i"], n["j"])] = n
    name = datetime.now(timezone.utc).strftime("state_%Y%m%d_%H%M%S.csv.gz")
    with gzip.open(snaps / name, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for (i, j), c in sorted(keep.items()):
            w.writerow([i, j, c["b"][0][0], c["b"][0][1], c.get("status"), c.get("gang") or "",
                        "" if c.get("count") is None else c["count"], c.get("my_aps") or 0,
                        c.get("towers") or 0, "" if c.get("owner") is None else c["owner"],
                        c.get("held"), poll])
    nfree = sum(1 for c in keep.values() if c.get("status") == "free" and (c.get("my_aps") or 0) > 0)
    log(work, f"ok: {name} rows={len(keep)} free_with_my_aps={nfree} poll={poll}")


def load(work):
    out = []
    for p in sorted((work / "snapshots").glob("state_*.csv.gz")):
        ts = datetime.strptime(p.name[6:21], "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        rows = {}
        with gzip.open(p, "rt", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                r["my_aps"] = int(r["my_aps"] or 0)
                r["count"] = int(r["count"]) if r["count"] != "" else None
                rows[(int(r["i"]), int(r["j"]))] = r
        out.append((ts, rows))
    return out


def report(work):
    snaps = load(work)
    if len(snaps) < 2:
        sys.exit(f"Need at least 2 snapshots in {work/'snapshots'} (found {len(snaps)}). Let the timer run longer.")
    L = []
    P = L.append
    t0, t1 = snaps[0][0], snaps[-1][0]
    P("UNOWNED-CELL ANOMALY INSPECTION")
    P(f"Snapshots: {len(snaps)}   first {t0:%Y-%m-%d %H:%M}Z   last {t1:%Y-%m-%d %H:%M}Z   span {(t1 - t0).total_seconds() / 3600:.1f} h")
    P("status 'free' = warroom lists no owner. Only describes changes in the data, not causes.")
    P("")

    def is_free(r):
        return r["status"] == "free"

    P("1. Count of cells with my_aps>0 that are unowned, per snapshot")
    for ts, rows in snaps:
        nf = sum(1 for r in rows.values() if is_free(r) and r["my_aps"] > 0)
        na = sum(1 for r in rows.values() if r["my_aps"] > 0)
        P(f"   {ts:%m-%d %H:%M}Z  unowned={nf:4d}  of {na} cells with my_aps>0")
    P("")

    first_rows, last_rows = snaps[0][1], snaps[-1][1]
    base_free = {k for k, r in first_rows.items() if is_free(r) and r["my_aps"] > 0}

    # per-cell timeline of status
    keys = set()
    for _, rows in snaps:
        keys |= set(rows)
    flips_to_owned, flips_to_free, ever_free = [], [], set()
    for k in keys:
        prev = None
        for ts, rows in snaps:
            r = rows.get(k)
            if r is None:
                continue
            if is_free(r) and r["my_aps"] > 0:
                ever_free.add(k)
            if prev is not None:
                if is_free(prev[1]) and not is_free(r):
                    flips_to_owned.append((ts, k, prev[1], r))
                elif (not is_free(prev[1])) and is_free(r) and r["my_aps"] > 0:
                    flips_to_free.append((ts, k, prev[1], r))
            prev = (ts, r)

    P(f"2. Baseline unowned cells (first snapshot): {len(base_free)}")
    still = [k for k in base_free if k in last_rows and is_free(last_rows[k])]
    gone = [k for k in base_free if k in last_rows and not is_free(last_rows[k])]
    P(f"   still unowned at last snapshot: {len(still)}")
    P(f"   became owned by some gang:       {len(gone)}")
    P(f"   no longer in the snapshot:       {len(base_free) - len(still) - len(gone)}")
    P("")

    def line(ts, k, a, b):
        return (f"   {ts:%m-%d %H:%M}Z cell {k[0]},{k[1]} ({b['sw_lat']},{b['sw_lon']})  "
                f"{a['status']}:{a['gang'] or '-'} -> {b['status']}:{b['gang'] or '-'}  "
                f"my_aps {a['my_aps']} -> {b['my_aps']}  count {a['count']} -> {b['count']}")

    P(f"3. Unowned -> owned changes: {len(flips_to_owned)}")
    for ts, k, a, b in sorted(flips_to_owned)[:60]:
        P(line(ts, k, a, b))
    P("")
    P(f"4. Owned -> unowned changes (cells with my_aps>0): {len(flips_to_free)}")
    for ts, k, a, b in sorted(flips_to_free)[:60]:
        P(line(ts, k, a, b))
    P("")

    P("5. Largest unowned cells at the last snapshot (my_aps over the whole window)")
    P("   cell            sw_lat,sw_lon     my_aps first -> last   unowned in all snapshots seen?   neighbors at last snapshot (mine/enemy/free)")
    big = sorted((r for r in last_rows.values() if is_free(r) and r["my_aps"] > 0), key=lambda r: -r["my_aps"])[:25]
    for r in big:
        k = (int(r["i"]), int(r["j"]))
        seen = [rows[k] for _, rows in snaps if k in rows]
        always = all(is_free(x) for x in seen)
        fa = seen[0]["my_aps"]
        nb = [last_rows.get((k[0] + a, k[1] + b)) for a in (-1, 0, 1) for b in (-1, 0, 1) if (a, b) != (0, 0)]
        nb = [n for n in nb if n]
        cnt = lambda s: sum(1 for n in nb if n["status"] == s)
        P(f"   {k[0]},{k[1]:<7d} {r['sw_lat']:>7},{r['sw_lon']:<8}  {fa:>6} -> {r['my_aps']:<6}  {'yes' if always else 'NO':<4}  {cnt('mine')}/{cnt('enemy')}/{cnt('free')}")
    P("")

    P("6. Unowned cells whose my_aps changed during the window (APs added or lost while still unowned)")
    ch = []
    for k in still:
        seen = [rows[k]["my_aps"] for _, rows in snaps if k in rows]
        if seen and seen[0] != seen[-1]:
            ch.append((k, seen[0], seen[-1]))
    ch.sort(key=lambda x: -abs(x[2] - x[1]))
    P(f"   {len(ch)} cells")
    for k, a, b in ch[:25]:
        P(f"   cell {k[0]},{k[1]}  my_aps {a} -> {b}")
    P("")

    new_free = [k for k in ever_free if k not in base_free]
    P(f"7. Cells that were not in the baseline unowned set but appeared unowned later: {len(new_free)}")
    for k in sorted(new_free)[:25]:
        r = last_rows.get(k) or next(rows[k] for _, rows in reversed(snaps) if k in rows)
        P(f"   cell {k[0]},{k[1]} ({r['sw_lat']},{r['sw_lon']})  status now {r['status']}  my_aps {r['my_aps']}")
    P("")
    P("Reading this: if section 3 is empty and section 2 shows all baseline cells still unowned,")
    P("the cells are not just waiting on a recalculation during this window. If section 3 has rows,")
    P("compare their times with your upload times and with section 6.")
    out = work / "free_cell_report.txt"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:12]))
    print(f"\nFull report: {out}")


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("snap", "report"):
        sys.exit(__doc__)
    work = Path(sys.argv[2]).resolve()
    work.mkdir(parents=True, exist_ok=True)
    (snap if sys.argv[1] == "snap" else report)(work)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""trip_report.py - before/after totals for one player around a trip window.

Usage:  python3 trip_report.py PLAYER_ID [start_utc="2026-11-05 13:00:00"] [end_utc=now]   (start defaults to 24 hours ago)
Token: env WARROOM_TOKEN, or a file named .token next to this script / in the current folder.
Output: prints to screen AND writes trip_report.txt in the current folder. 
Nothing is uploaded anywhere; it only reads your warroom (WARROOM_URL).
Times are UTC (ET = UTC-5 now). Board day is UTC.
"""
import os as _os, sys as _sys
WARROOM_URL = _os.environ.get("WARROOM_URL", "").rstrip("/")
if not WARROOM_URL:
    _sys.exit("Set the WARROOM_URL environment variable to your warroom address first, e.g.  WARROOM_URL=https://warroom.example.com")
import os, sys, json, urllib.request
from datetime import datetime
if len(sys.argv) < 2:
    sys.exit("Usage: python3 trip_report.py PLAYER_ID [start_utc] [end_utc]")
pid = sys.argv[1]
from datetime import timedelta, timezone
start = sys.argv[2] if len(sys.argv) > 2 else (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
end = sys.argv[3] if len(sys.argv) > 3 else "9999-01-01 00:00:00"
tok = os.environ.get("WARROOM_TOKEN", "")
for p in (".token", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".token")):
    if not tok and os.path.exists(p):
        tok = open(p).read().strip()
if not tok:
    sys.exit("No token: set WARROOM_TOKEN or put it in a file named .token")
def get(path):
    r = urllib.request.Request(WARROOM_URL + path,
        headers={"Authorization": "Bearer " + tok, "User-Agent": "curl/8.5.0"})
    return json.load(urllib.request.urlopen(r, timeout=60))
out = []
for board in ("all_time", "cells"):
    h = sorted(get("/api/boards?board=%s&id=%s" % (board, pid))["history"], key=lambda x: x["ts"])
    win = [x for x in h if start <= x["ts"] <= end]
    out.append("== %s  (player %s)  window %s to %s UTC" % (board, pid, start, end))
    if len(win) < 2:
        out.append("  not enough samples in window"); continue
    a, b = win[0], win[-1]
    out.append("  first sample %s  value %s wifi %s ble %s" % (a["ts"], a["value"], a["wifi"], a["ble"]))
    out.append("  last  sample %s  value %s wifi %s ble %s" % (b["ts"], b["value"], b["wifi"], b["ble"]))
    out.append("  change: total %+d" % (b["value"] - a["value"]) + ("" if a["wifi"] is None else "  wifi %+d  ble %+d" % (b["wifi"] - a["wifi"], b["ble"] - a["ble"])))
    out.append("  hourly:")
    for x, y in zip(win, win[1:]):
        d = y["value"] - x["value"]
        extra = "" if x["wifi"] is None else "  wifi %+d ble %+d" % (y["wifi"] - x["wifi"], y["ble"] - x["ble"])
        out.append("    %s  %+d%s" % (y["ts"], d, extra))
txt = "\n".join(out)
print(txt)
open("trip_report.txt", "w").write(txt)
print("\nWritten to:", os.path.abspath("trip_report.txt"))

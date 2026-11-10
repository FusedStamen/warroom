#!/usr/bin/env python3
"""trip_analysis.py - split a multi-day wardrive trip by GPS and time and compare the drive down with the drive back.

Usage:   python trip_analysis.py <folder_with_csvs> [outdir]
Input:   every .csv in the folder (WiGLE-format: MAC,SSID,...,FirstSeen,...,CurrentLatitude,CurrentLongitude,...,Type).
         File names are ignored. Everything is based on FirstSeen (UTC) and GPS only.
Output:  <outdir>/trip_analysis.txt, trip_segments.csv, trip_buckets.csv  (outdir defaults to the input folder)
Nothing is uploaded anywhere. Times are shown in ET (UTC-5 after Nov 1 2026).
"""
import calendar
import csv
import glob
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

D = sys.argv[1] if len(sys.argv) > 1 else "."
OUT = sys.argv[2] if len(sys.argv) > 2 else D
os.makedirs(OUT, exist_ok=True)
ET = timedelta(hours=-5)
NB = (40.49, -74.42)   # New Brunswick NJ, used only to split legs
CITIES = {"Boston": (42.37, -71.21), "Worcester": (42.26, -71.80), "Hartford": (41.76, -72.67),
          "Providence": (41.82, -71.41), "New Haven": (41.31, -72.92), "Stamford": (41.05, -73.54),
          "New York City": (40.75, -73.99), "Newark": (40.73, -74.17), "New Brunswick": NB,
          "Trenton": (40.22, -74.76), "Philadelphia": (39.95, -75.17), "Wilmington": (39.74, -75.55),
          "New London": (41.36, -72.10), "Springfield MA": (42.10, -72.59), "Framingham": (42.28, -71.42)}


def hav(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


def city(la, lo):
    n, d = min(((k, hav(la, lo, *v)) for k, v in CITIES.items()), key=lambda z: z[1])
    return n if d < 30 else "near " + n


def fmt(ts):
    return (datetime(1970, 1, 1) + timedelta(seconds=ts) + ET).strftime("%a %m-%d %I:%M %p")


# ---------- load ----------
rows, seen, dups = [], set(), [0]
for f in sorted(glob.glob(os.path.join(D, "*.csv"))):
    with open(f, newline="", encoding="utf-8", errors="replace") as fh:
        first = fh.readline()
        if not first.startswith("WigleWifi"):
            fh.seek(0)
        for x in csv.DictReader(fh):
            try:
                la, lo = float(x["CurrentLatitude"]), float(x["CurrentLongitude"])
                if abs(la) < 1 or abs(lo) < 1:
                    continue
                ts = calendar.timegm(datetime.strptime(x["FirstSeen"][:19], "%Y-%m-%d %H:%M:%S").timetuple())
            except Exception:
                continue
            key = (x["MAC"].lower(), ts)
            if key in seen:
                dups[0] += 1
            seen.add(key)
            ty = "WIFI" if x["Type"].upper() in ("WIFI", "WLAN") else "BLE"
            rows.append((ts, ty, x["MAC"].lower(), la, lo))
del seen
rows.sort()
print("rows loaded:", len(rows), "of which same MAC in the same second:", dups[0])

# ---------- 10 s track bins ----------
bins = defaultdict(list)
for ts, ty, m, la, lo in rows:
    bins[ts // 10].append((la, lo))
pts = []
for k in sorted(bins):
    v = bins[k]
    pts.append((k * 10, sorted(a for a, b in v)[len(v) // 2], sorted(b for a, b in v)[len(v) // 2]))

# ---------- sessions (gap > 3 h) then segments (gap > 10 min) ----------
sessions = [[pts[0]]]
for p in pts[1:]:
    if p[0] - sessions[-1][-1][0] > 3 * 3600:
        sessions.append([p])
    else:
        sessions[-1].append(p)


def track_stats(track):
    """distance km, stopped seconds, moving seconds (speed<5 km/h counts as stopped; glitches >200 km/h skipped)"""
    dist = stop = move = 0.0
    cum = [0.0]
    for a, b in zip(track, track[1:]):
        dt = b[0] - a[0]
        km = hav(a[1], a[2], b[1], b[2])
        sp = km / dt * 3600 if dt > 0 else 0
        if dt <= 120 and sp < 200:
            dist += km
            if sp < 5:
                stop += dt
            else:
                move += dt
        cum.append(dist)
    return dist, stop, move, cum


# ---------- label legs ----------
legs = []   # (name, t0, t1)
for i, s in enumerate(sessions):
    t0, t1 = s[0][0], s[-1][0]
    near = [j for j, p in enumerate(s) if hav(p[1], p[2], *NB) < 6]
    if i == 0 and near:
        j = near[0]
        legs.append(("Leg A: drive down, start to New Brunswick", s[0][0], s[j][0]))
        legs.append(("Leg B: New Brunswick to Philadelphia area", s[j][0], t1))
    elif i == len(sessions) - 1 and near and hav(s[0][1], s[0][2], *NB) < 6:
        j = near[-1]
        if j > 0:
            legs.append(("Local around New Brunswick (before the drive back)", t0, s[j][0]))
        legs.append(("Leg R: drive back, New Brunswick to home", s[j][0], t1))
    else:
        legs.append(("Travel while there (session %d)" % (i + 1), t0, t1))

idx = {p[0]: p for p in pts}
leg_rows = {n: [r for r in rows if t0 <= r[0] <= t1] for n, t0, t1 in legs}
leg_pts = {n: [p for p in pts if t0 <= p[0] <= t1] for n, t0, t1 in legs}

lines, seg_csv = [], []
lines.append("TRIP ANALYSIS (GPS and FirstSeen only; file names ignored; times ET)")
lines.append("Input rows: %d (raw, matching what uploads count as received). Rows repeating the same MAC in the same second: %d (%.0f%%)." % (len(rows), dups[0], 100.0 * dups[0] / len(rows)))
lines.append("")
lines.append("1. LEGS")
hdr = "%-52s %-17s %-17s %5s %6s %5s %6s %7s %8s %8s %8s %8s" % (
    "leg", "start", "end", "hours", "km", "stopm", "kmh", "rows", "wifi", "ble", "uWiFi", "uBLE")
lines.append(hdr)
summary = {}
for n, t0, t1 in legs:
    r, tp = leg_rows[n], leg_pts[n]
    dist, stop, move, cum = track_stats(tp)
    w = [x for x in r if x[1] == "WIFI"]
    b = [x for x in r if x[1] == "BLE"]
    uw, ub = len({x[2] for x in w}), len({x[2] for x in b})
    hrs = (t1 - t0) / 3600
    kmh = dist / (move / 3600) if move else 0
    summary[n] = dict(dist=dist, hrs=hrs, rows=len(r), wifi=len(w), ble=len(b), uw=uw, ub=ub, moving=move / 3600)
    lines.append("%-52s %-17s %-17s %5.1f %6.0f %5.0f %6.0f %7d %8d %8d %8d %8d" % (
        n[:52], fmt(t0), fmt(t1), hrs, dist, stop / 60, kmh, len(r), len(w), len(b), uw, ub))
    lines.append("      from %s (%.3f,%.3f) to %s (%.3f,%.3f)" % (city(tp[0][1], tp[0][2]), tp[0][1], tp[0][2],
                                                               city(tp[-1][1], tp[-1][2]), tp[-1][1], tp[-1][2]))
    seg_csv.append([n, fmt(t0), fmt(t1), round(hrs, 2), round(dist, 1), round(stop / 60), round(kmh), len(r), len(w), len(b), uw, ub])
lines.append("stopm = minutes below 5 km/h; kmh = average while moving; uWiFi/uBLE = distinct addresses (BLE uses rotating addresses, so uBLE overstates devices)")
lines.append("")

# ---------- per-km yield ----------
lines.append("2. YIELD PER KM (rows and distinct addresses per km driven)")
lines.append("%-52s %8s %8s %8s %8s %8s" % ("leg", "rows/km", "wifi/km", "ble/km", "uWiFi/km", "rows/h"))
for n, t0, t1 in legs:
    s = summary[n]
    if s["dist"] < 1:
        continue
    lines.append("%-52s %8.0f %8.0f %8.0f %8.1f %8.0f" % (n[:52], s["rows"] / s["dist"], s["wifi"] / s["dist"], s["ble"] / s["dist"],
                                                      s["uw"] / s["dist"], s["rows"] / s["hrs"]))
lines.append("")

# ---------- down vs back along the same road ----------
A = next((n for n in summary if n.startswith("Leg A")), None)
R = next((n for n in summary if n.startswith("Leg R")), None)
if A and R:
    lines.append("3. DRIVE DOWN (Boston to New Brunswick) vs DRIVE BACK (New Brunswick to Boston)")
    ta, tr = leg_pts[A], leg_pts[R]
    da, _, _, ca = track_stats(ta)
    dr, _, _, cr = track_stats(tr)
    home = ta[0]
    # distance-from-Boston coordinate for the down leg
    down_pos = [(p[1], p[2], c) for p, c in zip(ta, ca)]
    # return bins: nearest down bin within 5 km
    ret_pos = []
    for p, c in zip(tr, cr):
        best, bd = None, 1e9
        for q in down_pos[::3]:   # every 30 s is plenty for a nearest-road match
            d = hav(p[1], p[2], q[0], q[1])
            if d < bd:
                bd, best = d, q[2]
        ret_pos.append((bd, best, (dr - c)))
    near2 = sum(1 for b in ret_pos if b[0] <= 2) / len(ret_pos)
    near5 = sum(1 for b in ret_pos if b[0] <= 5) / len(ret_pos)
    lines.append("Route overlap: %.0f%% of the drive back was within 2 km of the drive down; %.0f%% within 5 km." % (100 * near2, 100 * near5))
    lines.append("Distance driven: down %.0f km, back %.0f km." % (da, dr))
    sa, sr = summary[A], summary[R]
    lines.append("Time: down %.1f h (%.1f h moving), back %.1f h (%.1f h moving)." % (sa["hrs"], sa["moving"], sr["hrs"], sr["moving"]))
    lines.append("Rows: down %d (%d WiFi, %d BLE); back %d (%d WiFi, %d BLE)." % (sa["rows"], sa["wifi"], sa["ble"], sr["rows"], sr["wifi"], sr["ble"]))
    lines.append("Distinct WiFi BSSIDs: down %d, back %d." % (sa["uw"], sr["uw"]))
    wa = {x[2] for x in leg_rows[A] if x[1] == "WIFI"}
    wr = {x[2] for x in leg_rows[R] if x[1] == "WIFI"}
    lines.append("WiFi BSSIDs on the way back that were already seen on the way down: %d of %d (%.0f%%); new on the way back: %d." % (
        len(wr & wa), len(wr), 100 * len(wr & wa) / max(1, len(wr)), len(wr - wa)))
    wl = {x[2] for x in rows if x[1] == "WIFI" and x[0] < leg_pts[A][0][0]}
    lines.append("")
    # buckets of 25 km from Boston
    B = 25.0
    nb = int(math.ceil(da / B))
    bk = {}
    for k in range(nb):
        bk[k] = dict(a_w=0, a_b=0, a_uw=set(), a_ub=set(), r_w=0, r_b=0, r_uw=set(), r_ub=set(), lat=[], lon=[])
    # down rows by time -> bin position
    cum_by_bin = {p[0] // 10: c for p, c in zip(ta, ca)}
    for ts, ty, m, la, lo in leg_rows[A]:
        c = cum_by_bin.get(ts // 10)
        if c is None:
            continue
        k = min(nb - 1, int(c // B))
        d = bk[k]
        d["lat"].append(la); d["lon"].append(lo)
        if ty == "WIFI":
            d["a_w"] += 1; d["a_uw"].add(m)
        else:
            d["a_b"] += 1; d["a_ub"].add(m)
    pos_by_bin = {p[0] // 10: b for p, b in zip(tr, ret_pos)}
    off = 0
    for ts, ty, m, la, lo in leg_rows[R]:
        b = pos_by_bin.get(ts // 10)
        if b is None or b[0] > 5 or b[1] is None:
            off += 1
            continue
        k = min(nb - 1, int(b[1] // B))
        d = bk[k]
        if ty == "WIFI":
            d["r_w"] += 1; d["r_uw"].add(m)
        else:
            d["r_b"] += 1; d["r_ub"].add(m)
    lines.append("   Buckets are 25 km of the drive-down distance from the start. Back-trip rows are matched to the nearest point of the road driven down (within 5 km; %d back rows were off that road and are left out)." % off)
    lines.append("%-4s %-8s %-26s | %7s %7s %7s %7s | %7s %7s %7s %7s | %7s" % (
        "km", "to", "nearest place", "dnWiFi", "dnBLE", "dn uW", "dn uB", "bkWiFi", "bkBLE", "bk uW", "bk uB", "bk uW seen on way down"))
    bcsv = []
    for k in range(nb):
        d = bk[k]
        mla = sum(d["lat"]) / len(d["lat"]) if d["lat"] else 0
        mlo = sum(d["lon"]) / len(d["lon"]) if d["lon"] else 0
        rep = len(d["r_uw"] & d["a_uw"])
        lines.append("%-4d %-8d %-26s | %7d %7d %7d %7d | %7d %7d %7d %7d | %7d" % (
            k * B, (k + 1) * B, city(mla, mlo)[:26] if d["lat"] else "-", d["a_w"], d["a_b"], len(d["a_uw"]), len(d["a_ub"]),
            d["r_w"], d["r_b"], len(d["r_uw"]), len(d["r_ub"]), rep))
        bcsv.append([k * B, (k + 1) * B, city(mla, mlo) if d["lat"] else "", d["a_w"], d["a_b"], len(d["a_uw"]), len(d["a_ub"]),
                     d["r_w"], d["r_b"], len(d["r_uw"]), len(d["r_ub"]), rep])
    with open(os.path.join(OUT, "trip_buckets.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["km_from", "km_to", "nearest_place", "down_wifi_rows", "down_ble_rows", "down_unique_wifi", "down_unique_ble",
                    "back_wifi_rows", "back_ble_rows", "back_unique_wifi", "back_unique_ble", "back_unique_wifi_seen_on_way_down"])
        w.writerows(bcsv)
    lines.append("")
    lines.append("   Reading the table: dn = drive down, bk = drive back, uW = distinct WiFi BSSIDs, uB = distinct BLE addresses.")

with open(os.path.join(OUT, "trip_segments.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["leg", "start_ET", "end_ET", "hours", "km", "stopped_min", "avg_moving_kmh", "rows", "wifi_rows", "ble_rows", "unique_wifi", "unique_ble"])
    w.writerows(seg_csv)

txt = "\n".join(lines)
open(os.path.join(OUT, "trip_analysis.txt"), "w").write(txt)
print(txt)
print("\nWritten to:", os.path.abspath(os.path.join(OUT, "trip_analysis.txt")))

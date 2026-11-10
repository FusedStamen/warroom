#!/usr/bin/env python3
r"""
wigle_cell_heat.py - turn your own WiGLE CSV exports into a per-cell heat table.

Reads every WiGLE-format CSV (.csv, .csv.gz, or .zip containing csvs) found under
the folder you give it, and counts, per 0.02 degree cell (same grid WDGWars uses:
i = floor(lat/0.02), j = floor(lon/0.02)):
  obs        - total observation rows in that cell
  nets       - distinct networks (MAC) seen in that cell, WiFi and BLE counted separately below
  wifi_nets / ble_nets
  files      - how many of your log files touched the cell
  first/last - earliest and latest FirstSeen timestamp seen

It makes NO network requests. It only reads files.

USAGE (Windows):
    py wigle_cell_heat.py "C:\path\to\folder\with\wigle\exports"

USAGE (Linux/Mac):
    python3 wigle_cell_heat.py /path/to/folder

OUTPUT (written inside the folder you pass in):
    wigle_cell_heat.csv     one row per cell, sorted heaviest first
    wigle_cell_heat_summary.txt   totals, how many cells, top 30 cells, files skipped

The output files contain cell coordinates and counts only - no MACs or SSIDs.
"""
import csv
import gzip
import io
import math
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

GRID = 0.02


def open_text(path):
    """Yield (name, text_stream) for every csv-like thing at path."""
    s = path.name.lower()
    if s.endswith(".csv.gz") or s.endswith(".gz"):
        yield path.name, io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace", newline="")
    elif s.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.lower().endswith((".csv", ".csv.gz")) and not n.endswith("/"):
                    raw = z.open(n)
                    if n.lower().endswith(".gz"):
                        raw = gzip.open(raw, "rb")
                    yield f"{path.name}:{n}", io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
    elif s.endswith(".csv"):
        yield path.name, open(path, "r", encoding="utf-8", errors="replace", newline="")


def parse_stream(name, f, cells, skipped):
    """Parse one WiGLE-format csv. Line 1 is a WigleWifi-1.x preamble, line 2 is the header."""
    first = f.readline()
    if not first:
        skipped.append((name, "empty"))
        return 0
    if first.startswith("WigleWifi"):
        header_line = f.readline()
    else:
        header_line = first  # plain csv with a header on line 1
    header = [h.strip() for h in next(csv.reader([header_line]))]
    idx = {h.lower(): i for i, h in enumerate(header)}

    def col(*names):
        for n in names:
            if n.lower() in idx:
                return idx[n.lower()]
        return None

    c_mac = col("MAC", "netid", "bssid")
    c_lat = col("CurrentLatitude", "trilat", "lat", "latitude")
    c_lon = col("CurrentLongitude", "trilong", "lon", "lng", "longitude")
    c_type = col("Type")
    c_first = col("FirstSeen", "firsttime")
    if c_mac is None or c_lat is None or c_lon is None:
        skipped.append((name, "no MAC/lat/lon columns: " + ",".join(header[:12])))
        return 0

    n = 0
    seen_cells_in_file = set()
    for row in csv.reader(f):
        try:
            lat = float(row[c_lat])
            lon = float(row[c_lon])
        except (ValueError, IndexError):
            continue
        if lat == 0.0 and lon == 0.0:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        k = (math.floor(lat / GRID), math.floor(lon / GRID))
        cell = cells[k]
        cell["obs"] += 1
        mac = row[c_mac].strip().upper()
        t = (row[c_type].strip().upper() if c_type is not None and c_type < len(row) else "WIFI")
        is_ble = t in ("BLE", "BT", "BLUETOOTH")
        key = ("B" if is_ble else "W") + mac
        cell["nets"].add(key)
        if k not in seen_cells_in_file:
            seen_cells_in_file.add(k)
            cell["files"] += 1
        if c_first is not None and c_first < len(row):
            ts = row[c_first].strip()
            if ts:
                if not cell["first"] or ts < cell["first"]:
                    cell["first"] = ts
                if not cell["last"] or ts > cell["last"]:
                    cell["last"] = ts
        n += 1
    return n


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    root = Path(sys.argv[1]).expanduser().resolve()
    if not root.is_dir():
        print(f"Not a folder: {root}")
        sys.exit(1)

    cells = defaultdict(lambda: {"obs": 0, "nets": set(), "files": 0, "first": "", "last": ""})
    skipped = []
    files_read = 0
    rows_total = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.name in ("wigle_cell_heat.csv", "wigle_cell_heat_summary.txt"):
            continue
        try:
            for name, stream in open_text(p):
                with stream:
                    r = parse_stream(name, stream, cells, skipped)
                files_read += 1
                rows_total += r
        except Exception as e:  # keep going on a bad file
            skipped.append((str(p.name), f"error: {e}"))

    out_csv = root / "wigle_cell_heat.csv"
    out_txt = root / "wigle_cell_heat_summary.txt"
    rows = []
    for (i, j), c in cells.items():
        wifi = sum(1 for k in c["nets"] if k[0] == "W")
        ble = sum(1 for k in c["nets"] if k[0] == "B")
        rows.append({
            "i": i, "j": j,
            "lat": round((i + 0.5) * GRID, 4), "lon": round((j + 0.5) * GRID, 4),
            "obs": c["obs"], "nets": len(c["nets"]), "wifi_nets": wifi, "ble_nets": ble,
            "files": c["files"], "first": c["first"], "last": c["last"],
        })
    rows.sort(key=lambda r: (-r["nets"], -r["obs"]))
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["i", "j", "lat", "lon", "obs", "nets", "wifi_nets", "ble_nets", "files", "first", "last"])
        w.writeheader()
        w.writerows(rows)

    lines = []
    lines.append(f"folder: {root}")
    lines.append(f"files read: {files_read}   rows used: {rows_total}   cells touched: {len(rows)}")
    if rows:
        nets = [r["nets"] for r in rows]
        nets_sorted = sorted(nets)
        med = nets_sorted[len(nets_sorted) // 2]
        lines.append(f"distinct networks per cell: median {med}, max {nets_sorted[-1]}")
        for thr in (100, 500, 1000, 5000):
            lines.append(f"  cells with >= {thr} distinct networks: {sum(1 for x in nets if x >= thr)}")
        lines.append("")
        lines.append("top 30 cells (heaviest coverage - the ones to avoid):")
        lines.append("   i      j      lat      lon     nets  wifi   ble  files")
        for r in rows[:30]:
            lines.append(f"{r['i']:5d} {r['j']:6d} {r['lat']:8.3f} {r['lon']:8.3f} {r['nets']:7d} {r['wifi_nets']:5d} {r['ble_nets']:5d} {r['files']:5d}")
    if skipped:
        lines.append("")
        lines.append(f"skipped {len(skipped)} item(s):")
        for n, why in skipped[:40]:
            lines.append(f"  {n}: {why}")
    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:12]))
    print(f"\nWrote:\n  {out_csv}\n  {out_txt}")


if __name__ == "__main__":
    main()

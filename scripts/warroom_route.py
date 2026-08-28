#!/usr/bin/env python3
"""
warroom_route.py

Pulls "virgin" (uncaptured) grid cells that contain roads from warroom's
sqlite DB, orders them into a reasonable driving route (greedy nearest-
neighbor), and exports a GPX file you can load into OsmAnd (or Gaia GPS)
for turn-by-turn navigation through the stops.

Usage:
    python3 warroom_route.py --user-id 1 --bbox 42.36 42.40 -71.22 -71.13 --out route.gpx

Run this ON THE PI (or copy warroom.sqlite somewhere you can run Python +
sqlite3 stdlib, which is all this needs — no extra pip installs required).
"""

import argparse
import sqlite3
import math
import sys
from xml.sax.saxutils import escape

DB_PATH_DEFAULT = "/home/fusedstamen/docker/warroom/data/warroom.sqlite"


def haversine_m(lat1, lng1, lat2, lng2):
    """Distance in meters between two lat/lng points."""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def fetch_target_cells(db_path, user_id, bbox):
    """
    bbox = (lat_min, lat_max, lng_min, lng_max)
    Returns list of (cell_key, lat, lng) for cells this user hasn't
    captured yet, that are known to actually contain a road.
    """
    lat_min, lat_max, lng_min, lng_max = bbox
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT vc.cell_key, vc.lat, vc.lng
        FROM virgin_cells vc
        JOIN cell_roads cr ON vc.cell_key = cr.cell_key
        WHERE vc.user_id = ?
          AND cr.found = 1
          AND vc.lat BETWEEN ? AND ?
          AND vc.lng BETWEEN ? AND ?
        """,
        (user_id, lat_min, lat_max, lng_min, lng_max),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def greedy_route(cells, start=None):
    """
    Simple greedy nearest-neighbor ordering. Good enough for a point list
    like this — not solving full TSP optimally, just avoiding a route
    that zigzags across town.
    """
    if not cells:
        return []
    remaining = cells[:]
    if start is None:
        # start from the westmost/southmost point as an arbitrary anchor
        remaining.sort(key=lambda c: (c[2], c[1]))
        route = [remaining.pop(0)]
    else:
        route = [start]
        remaining = [c for c in remaining if c != start]

    while remaining:
        last = route[-1]
        remaining.sort(key=lambda c: haversine_m(last[1], last[2], c[1], c[2]))
        route.append(remaining.pop(0))
    return route


def write_gpx(route, out_path):
    with open(out_path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<gpx version="1.1" creator="warroom_route.py" xmlns="http://www.topografix.com/GPX/1/1">\n')
        for idx, (cell_key, lat, lng) in enumerate(route, start=1):
            name = escape(f"Target {idx} ({cell_key})")
            f.write(f'  <wpt lat="{lat}" lon="{lng}"><name>{name}</name></wpt>\n')
        # also emit as a route (rte) so nav apps that expect an ordered
        # sequence of route points (not just scattered waypoints) get one
        f.write('  <rte>\n')
        f.write('    <name>Warroom target cells</name>\n')
        for idx, (cell_key, lat, lng) in enumerate(route, start=1):
            name = escape(f"Target {idx} ({cell_key})")
            f.write(f'    <rtept lat="{lat}" lon="{lng}"><name>{name}</name></rtept>\n')
        f.write('  </rte>\n')
        f.write('</gpx>\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH_DEFAULT, help="path to warroom.sqlite")
    ap.add_argument("--user-id", type=int, required=True, help="your warroom user_id")
    ap.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        metavar=("LAT_MIN", "LAT_MAX", "LNG_MIN", "LNG_MAX"),
        required=True,
        help="bounding box to search within",
    )
    ap.add_argument("--out", default="route.gpx", help="output GPX file path")
    ap.add_argument(
        "--max-stops",
        type=int,
        default=None,
        help="optional cap on number of stops (useful if a bbox returns a huge number of cells)",
    )
    args = ap.parse_args()

    cells = fetch_target_cells(args.db, args.user_id, tuple(args.bbox))
    if not cells:
        print("No uncaptured road cells found in that bbox for that user_id.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(cells)} uncaptured road cells in bbox.")

    route = greedy_route(cells)
    if args.max_stops:
        route = route[: args.max_stops]
        print(f"Trimmed to first {len(route)} stops (--max-stops).")

    write_gpx(route, args.out)
    print(f"Wrote {len(route)} ordered stops to {args.out}")
    print("Load this into OsmAnd (My Places > Import GPX) for turn-by-turn navigation through the stops.")


if __name__ == "__main__":
    main()

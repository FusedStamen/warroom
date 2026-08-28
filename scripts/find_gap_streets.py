#!/usr/bin/env python3
"""
find_gap_streets.py

1. Pulls WiGLE network records inside a bounding box (tiled to respect
   WiGLE's 100-results-per-page limit and avoid burning your whole daily
   quota on redundant queries).
2. Builds a drivable residential road graph for the same bbox via OSMnx.
3. Snaps every WiGLE point to its nearest road edge and counts APs per edge.
4. Flags residential/living_street/unclassified edges with (near) zero
   nearby APs as "gap streets".
5. Groups gap streets into connected clusters and, per cluster, builds an
   approximate route-inspection path (covers every gap edge in the
   cluster with minimal backtracking) using networkx's eulerize +
   eulerian_circuit.
6. Exports everything as a single GPX file with one track per cluster,
   for import into OsmAnd (or Gaia GPS) for turn-by-turn navigation.

SETUP (run this on your main PC, not the Pi — OSMnx/geopandas are heavy):
    pip install osmnx networkx requests --break-system-packages

WiGLE credentials: create an account, get your API token from
https://wigle.net/account -> your name / token become env vars:
    export WIGLE_API_NAME=xxxxxxxx
    export WIGLE_API_TOKEN=xxxxxxxx

Usage:
    python3 find_gap_streets.py --bbox 42.00 42.17 -71.75 -71.53 --out gaps.gpx
"""

import argparse
import os
import sys
import time
import json

import requests
import networkx as nx
import osmnx as ox

WIGLE_SEARCH_URL = "https://api.wigle.net/api/v2/network/search"


def wigle_auth():
    name = os.environ.get("WIGLE_API_NAME")
    token = os.environ.get("WIGLE_API_TOKEN")
    if not name or not token:
        print("Set WIGLE_API_NAME and WIGLE_API_TOKEN env vars first.", file=sys.stderr)
        sys.exit(1)
    return (name, token)


def tile_bbox(lat_min, lat_max, lng_min, lng_max, step_deg=0.02):
    """Break a big bbox into smaller tiles so each WiGLE query has a
    manageable result count (WiGLE paginates at 100/page)."""
    tiles = []
    lat = lat_min
    while lat < lat_max:
        lng = lng_min
        lat_top = min(lat + step_deg, lat_max)
        while lng < lng_max:
            lng_right = min(lng + step_deg, lng_max)
            tiles.append((lat, lat_top, lng, lng_right))
            lng = lng_right
        lat = lat_top
    return tiles


def fetch_wigle_tile(auth, lat_min, lat_max, lng_min, lng_max, max_pages=5):
    """Fetch all networks in a tile, following pagination up to max_pages
    (safety cap so one dense tile can't eat your whole daily quota)."""
    results = []
    offset = 0
    for _ in range(max_pages):
        params = {
            "latrange1": lat_min,
            "latrange2": lat_max,
            "longrange1": lng_min,
            "longrange2": lng_max,
            "resultsPerPage": 100,
            "pagestart": offset,
        }
        resp = requests.get(WIGLE_SEARCH_URL, params=params, auth=auth, timeout=30)
        if resp.status_code == 429:
            print("Hit WiGLE rate limit — stopping early.", file=sys.stderr)
            break
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("results", [])
        results.extend(batch)
        if not data.get("moreResults") or not batch:
            break
        offset += 100
        time.sleep(0.5)  # be polite
    return results


def fetch_all_wigle_points(auth, bbox, tile_step=0.02):
    lat_min, lat_max, lng_min, lng_max = bbox
    tiles = tile_bbox(lat_min, lat_max, lng_min, lng_max, tile_step)
    print(f"Querying {len(tiles)} WiGLE tiles...")
    all_points = []
    for idx, (t_lat_min, t_lat_max, t_lng_min, t_lng_max) in enumerate(tiles, 1):
        try:
            batch = fetch_wigle_tile(auth, t_lat_min, t_lat_max, t_lng_min, t_lng_max)
        except requests.HTTPError as e:
            print(f"  tile {idx}/{len(tiles)}: HTTP error {e}", file=sys.stderr)
            continue
        for net in batch:
            lat, lng = net.get("trilat"), net.get("trilong")
            if lat is not None and lng is not None:
                all_points.append((lat, lng))
        print(f"  tile {idx}/{len(tiles)}: {len(batch)} networks (running total {len(all_points)})")
    return all_points


def build_residential_graph(bbox):
    lat_min, lat_max, lng_min, lng_max = bbox
    print("Downloading road graph from OSM (residential/living_street/unclassified)...")
    custom_filter = (
        '["highway"~"residential|living_street|unclassified"]'
    )
    G = ox.graph_from_bbox(
        bbox=(lng_min, lat_min, lng_max, lat_max),
        custom_filter=custom_filter,
        simplify=True,
        retain_all=True,
    )
    return G


def flag_gap_edges(G, ap_points, min_aps=1):
    """Snap each AP point to nearest edge, count per edge, return the
    set of edge keys (u, v, key) with fewer than min_aps nearby APs."""
    if not ap_points:
        print("No AP points to snap — treating all edges as gaps.", file=sys.stderr)
        counts = {}
    else:
        lats = [p[0] for p in ap_points]
        lngs = [p[1] for p in ap_points]
        nearest = ox.distance.nearest_edges(G, X=lngs, Y=lats)
        counts = {}
        for edge in nearest:
            counts[edge] = counts.get(edge, 0) + 1

    gap_edges = []
    for u, v, k in G.edges(keys=True):
        c = counts.get((u, v, k), 0)
        if c < min_aps:
            gap_edges.append((u, v, k))
    print(f"{len(gap_edges)} / {G.number_of_edges()} residential edges flagged as gaps.")
    return gap_edges


def cluster_and_route(G, gap_edges):
    """Build a subgraph of just the gap edges, split into connected
    components (clusters of contiguous uncovered streets), and for each
    cluster produce an approximate route-inspection path."""
    H = nx.MultiGraph()
    for u, v, k in gap_edges:
        data = G.get_edge_data(u, v, k)
        H.add_edge(u, v, **data)
        H.nodes[u].update(G.nodes[u])
        H.nodes[v].update(G.nodes[v])

    routes = []
    for component_nodes in nx.connected_components(H):
        sub = H.subgraph(component_nodes).copy()
        if sub.number_of_edges() == 0:
            continue
        try:
            euler_sub = nx.eulerize(nx.MultiGraph(sub))
            circuit = list(nx.eulerian_circuit(euler_sub))
            coords = []
            for u, v in circuit:
                coords.append((sub.nodes[u]["y"], sub.nodes[u]["x"]))
            # close the loop
            last = circuit[-1][1]
            coords.append((sub.nodes[last]["y"], sub.nodes[last]["x"]))
            routes.append(coords)
        except Exception as e:
            # fall back: just list edge endpoints in arbitrary order
            print(f"  eulerize failed on a cluster ({e}), using simple fallback", file=sys.stderr)
            coords = []
            for u, v in sub.edges():
                coords.append((sub.nodes[u]["y"], sub.nodes[u]["x"]))
                coords.append((sub.nodes[v]["y"], sub.nodes[v]["x"]))
            routes.append(coords)
    print(f"Built {len(routes)} cluster routes.")
    return routes


def write_gpx(routes, out_path):
    with open(out_path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<gpx version="1.1" creator="find_gap_streets.py" xmlns="http://www.topografix.com/GPX/1/1">\n')
        for i, coords in enumerate(routes, 1):
            f.write(f'  <trk><name>Gap cluster {i}</name><trkseg>\n')
            for lat, lng in coords:
                f.write(f'    <trkpt lat="{lat}" lon="{lng}"></trkpt>\n')
            f.write('  </trkseg></trk>\n')
        f.write('</gpx>\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", type=float, nargs=4, metavar=("LAT_MIN", "LAT_MAX", "LNG_MIN", "LNG_MAX"), required=True)
    ap.add_argument("--out", default="gaps.gpx")
    ap.add_argument("--tile-step", type=float, default=0.02, help="WiGLE query tile size in degrees")
    ap.add_argument("--min-aps", type=int, default=1, help="edges with fewer APs than this count as a gap")
    ap.add_argument("--cache", default="wigle_points_cache.json", help="cache WiGLE results here to avoid re-querying")
    args = ap.parse_args()

    bbox = tuple(args.bbox)

    if os.path.exists(args.cache):
        print(f"Loading cached WiGLE points from {args.cache}")
        with open(args.cache) as f:
            ap_points = json.load(f)
    else:
        auth = wigle_auth()
        ap_points = fetch_all_wigle_points(auth, bbox, args.tile_step)
        with open(args.cache, "w") as f:
            json.dump(ap_points, f)

    G = build_residential_graph(bbox)
    gap_edges = flag_gap_edges(G, ap_points, args.min_aps)
    routes = cluster_and_route(G, gap_edges)
    write_gpx(routes, args.out)
    print(f"Wrote {args.out} — import into OsmAnd for turn-by-turn nav through the gap streets.")


if __name__ == "__main__":
    main()

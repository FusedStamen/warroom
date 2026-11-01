#!/usr/bin/env python3
"""
find_gap_streets.py  (low-quota edition)

Finds residential streets where nobody on WiGLE has logged any WiFi APs, and
builds a driving route (GPX) that covers them.

1. Splits your bounding box into tiles that line up with the WDGWars cell
   grid (0.02 degrees, so tile = game cell when --tile-step is left alone).
2. Asks the WiGLE API how many networks are in each tile and fetches up to
   --max-pages pages (100 networks per page) per tile. Default is 1 page.
3. Caches every tile separately, so a run that hits your daily limit can be
   re-run later and picks up where it stopped.
4. Downloads the residential road graph for the bbox from OpenStreetMap
   (OSMnx), snaps the fetched APs to streets, and flags streets with fewer
   than --min-aps nearby APs as gaps.
5. Groups gap streets into connected clusters and builds an approximate
   route-inspection path per cluster (networkx eulerize + eulerian_circuit).
6. Writes one GPX file (one track per cluster) for OsmAnd or Gaia GPS, and a
   tile_counts.csv with the WiGLE network count for every tile.

WHAT CHANGED IN THIS VERSION (all aimed at small API quotas)
  - --dry-run: shows how many API calls a run could use, then exits. Uses no
    quota, needs no WiGLE credentials, and does not need osmnx installed.
  - --max-calls N: stops cleanly after N API calls.
  - --max-pages N (default 1, was 5): pages fetched per tile. 1 page = 100
    networks, which is plenty to tell "covered" from "empty".
  - Per-tile cache with resume. The old version saved one cache file only
    after the whole run finished, and a rate-limit stop was saved as if it
    were a complete result. Now every tile is saved as it finishes, and the
    cache records whether each tile is complete, partial or not fetched.
  - HTTP 429 (daily limit) and 401/403 (bad credentials) now stop the run
    with a clear message instead of carrying on silently.
  - Streets inside tiles with unknown or partial coverage are SKIPPED, not
    reported as gaps. Before, unfetched or truncated areas looked empty and
    produced false gap streets.
  - --counts-only: fetch tile counts, write tile_counts.csv, and stop. No
    road download, so osmnx is not needed.
  - --center LAT LNG: fetch the tiles closest to a point first, so a small
    quota is spent where you care about.
  - Networks are de-duplicated by BSSID, so repeated pages cannot inflate
    counts.
  - --check-quota: makes ONE tiny API call and says whether your quota is
    available. Needs no --bbox. The script now records when WiGLE answers
    429 (in the cache file), so repeated checks show how long the cutoff
    lasted and whether it looks like a rolling window or a fixed daily reset.

SETUP
  Dry run and --counts-only need only:   pip install requests
  Full route building also needs:        pip install osmnx networkx
  (Run the full version on a normal PC. OSMnx is heavy for a Raspberry Pi.)

WiGLE credentials: your own account, from https://wigle.net/account
(API token section). Set them as environment variables:
    export WIGLE_API_NAME=xxxxxxxx
    export WIGLE_API_TOKEN=xxxxxxxx
Never put your token in the script or in a repository.

USAGE
    python3 find_gap_streets.py --check-quota
    python3 find_gap_streets.py --bbox LAT_MIN LAT_MAX LNG_MIN LNG_MAX --dry-run
    python3 find_gap_streets.py --bbox LAT_MIN LAT_MAX LNG_MIN LNG_MAX --max-calls 40
    python3 find_gap_streets.py --bbox LAT_MIN LAT_MAX LNG_MIN LNG_MAX --counts-only

OUTPUT (written to the folder you run it from, unless you pass other paths)
    gaps.gpx                   route tracks for OsmAnd / Gaia GPS
    tile_counts.csv            WiGLE network count per tile
    wigle_points_cache.json    per-tile cache (delete a tile's entry or the
                               whole file to force a fresh pull)

NOTES
  - WiGLE data is for planning only. Never upload WiGLE data to WDGWars.
  - The paging parameter (first=offset) follows the WiGLE v2 search API but
    has not been verified for page 2 and later. The script detects when a
    page returns nothing new, marks the tile as stuck and stops paging it.
    With the default of 1 page per tile this does not matter.
"""

import argparse
import csv
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

import requests

WIGLE_SEARCH_URL = "https://api.wigle.net/api/v2/network/search"
PAGE_SIZE = 100
CACHE_VERSION = 2


class StopRun(Exception):
    """Raised to end the fetch loop early (budget, rate limit, bad creds)."""


class Budget:
    def __init__(self, limit):
        self.limit = limit
        self.used = 0

    def spend(self):
        if self.limit is not None and self.used >= self.limit:
            return False
        self.used += 1
        return True


# ---------------------------------------------------------------- tiles

def grid_index(value, step):
    return math.floor(value / step + 1e-9)


def tile_key(i, j):
    return f"{i}:{j}"


def tile_bounds(i, j, step):
    return (round(i * step, 6), round((i + 1) * step, 6),
            round(j * step, 6), round((j + 1) * step, 6))


def tiles_for_bbox(bbox, step):
    """Grid-aligned tiles covering the bbox. With step 0.02 these are the
    same cells WDGWars uses (index = floor(coordinate / 0.02))."""
    lat_min, lat_max, lng_min, lng_max = bbox
    i0 = grid_index(lat_min, step)
    i1 = max(i0, math.ceil(lat_max / step - 1e-9) - 1)
    j0 = grid_index(lng_min, step)
    j1 = max(j0, math.ceil(lng_max / step - 1e-9) - 1)
    return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]


def order_tiles(tiles, center, step):
    if not center:
        return tiles
    clat, clng = center
    ci, cj = grid_index(clat, step), grid_index(clng, step)
    scale = math.cos(math.radians(clat))
    return sorted(tiles, key=lambda t: (t[0] - ci) ** 2 + ((t[1] - cj) * scale) ** 2)


# ---------------------------------------------------------------- cache

def new_cache(step):
    return {"version": CACHE_VERSION, "step": step, "tiles": {}}


def load_cache(path, step):
    if not os.path.exists(path):
        return new_cache(step)
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        backup = path + ".v1.bak"
        os.replace(path, backup)
        print(f"Old-format cache found. It cannot say which tiles were finished,"
              f" so it was moved to {backup} and a fresh cache will be used.",
              file=sys.stderr)
        return new_cache(step)
    if data.get("version") != CACHE_VERSION:
        sys.exit(f"Unknown cache version in {path}. Delete it or pass --cache with another file name.")
    if abs(data.get("step", step) - step) > 1e-12:
        sys.exit(f"{path} was built with --tile-step {data.get('step')}, not {step}. "
                 f"Use the same step or pass --cache with another file name.")
    return data


def save_cache(path, cache):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f)
    os.replace(tmp, path)


# ---------------------------------------------------------------- limit log

def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def _show(iso):
    """Local-time display of a stored UTC timestamp."""
    if not iso:
        return "unknown"
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _hours_between(start_iso, end_iso):
    delta = datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)
    return delta.total_seconds() / 3600.0


def _open_entry(cache):
    for e in reversed(cache.get("limit_log", [])):
        if e.get("back_at") is None:
            return e
    return None


def record_limited(cache, calls_before):
    """Note that WiGLE answered 429. calls_before is how many calls worked
    first in this run; 0 means we only found out we were already limited."""
    now = _iso(_now())
    entry = _open_entry(cache)
    if entry is not None:
        entry["last_limited_at"] = now
        return
    log = cache.setdefault("limit_log", [])
    log.append({
        "hit_at": now if calls_before > 0 else None,
        "first_seen": now,
        "calls_before_limit": calls_before if calls_before > 0 else None,
        "last_limited_at": now,
        "back_at": None,
    })
    del log[:-20]


def mark_back(cache):
    """A call worked after a recorded limit. Returns the closed entry or None.
    back_at is the first moment we SAW it working, so the true reset was at
    or before it."""
    entry = _open_entry(cache)
    if entry is None:
        return None
    entry["back_at"] = _iso(_now())
    return entry


def print_limit_history(cache):
    log = cache.get("limit_log", [])
    if not log:
        return
    print("Limit history (newest last):")
    for e in log[-5:]:
        ref = e.get("hit_at") or e.get("first_seen")
        how = "hit" if e.get("hit_at") else "first seen limited"
        line = f"  {how} {_show(ref)}"
        if e.get("calls_before_limit"):
            line += f", {e['calls_before_limit']} calls worked before the 429"
        if e.get("back_at"):
            line += f", seen working again {_show(e['back_at'])} (at most {_hours_between(ref, e['back_at']):.1f} h later)"
        else:
            line += ", not seen working again yet"
        print(line)


def check_quota(auth, cache, cache_path):
    """One tiny API call to see whether the quota is available. Needs no bbox."""
    params = {"latrange1": 0.0, "latrange2": 0.001, "longrange1": 0.0,
              "longrange2": 0.001, "resultsPerPage": 1}
    try:
        resp = requests.get(WIGLE_SEARCH_URL, params=params, auth=auth, timeout=30)
    except requests.RequestException as e:
        sys.exit(f"Could not reach WiGLE: {e}")
    code = resp.status_code
    if code in (401, 403):
        sys.exit(f"WiGLE rejected the credentials (HTTP {code}). Check WIGLE_API_NAME and WIGLE_API_TOKEN.")
    if code == 429:
        record_limited(cache, 0)
        save_cache(cache_path, cache)
        e = _open_entry(cache)
        ref = e.get("hit_at") or e.get("first_seen")
        print(f"STILL LIMITED (HTTP 429). Limited since {_show(ref)}"
              + ("" if e.get("hit_at") else " (first seen then; the real cutoff was earlier)") + ".")
        print_limit_history(cache)
        print("Check again later. Each check uses one call once you are back.")
        return
    if code >= 400:
        sys.exit(f"WiGLE returned HTTP {code}. Try again later.")
    closed = mark_back(cache)
    save_cache(cache_path, cache)
    print("QUOTA AVAILABLE: the test call worked (it used 1 call).")
    if closed is not None:
        print("This closes the last recorded limit. If the same clock time shows up each day, the reset is "
              "at a fixed time. If it is about the same number of hours after the cutoff each time, "
              "it is a rolling window.")
    print_limit_history(cache)


def tile_status(rec):
    """unfetched / partial / complete / stuck"""
    if rec is None or rec["pages"] == 0:
        return "unfetched"
    if rec["status"] == "complete":
        return "complete"
    if rec.get("stuck"):
        return "stuck"
    return "partial"


def calls_needed(rec, max_pages):
    st = tile_status(rec)
    if st in ("complete", "stuck"):
        return 0
    pages = 0 if rec is None else rec["pages"]
    return max(0, max_pages - pages)


# ---------------------------------------------------------------- WiGLE

def wigle_auth():
    name = os.environ.get("WIGLE_API_NAME")
    token = os.environ.get("WIGLE_API_TOKEN")
    if not name or not token:
        print("Set WIGLE_API_NAME and WIGLE_API_TOKEN environment variables first.", file=sys.stderr)
        sys.exit(1)
    return (name, token)


def fetch_tiles(auth, tiles, cache, cache_path, step, max_pages, budget):
    """Fetch every tile that still needs calls. Saves after each tile.
    Returns a reason string if the run stopped early, else None."""
    todo = [t for t in tiles if calls_needed(cache["tiles"].get(tile_key(*t)), max_pages) > 0]
    print(f"{len(todo)} of {len(tiles)} tiles need fetching "
          f"(max {max_pages} page(s) each"
          + (f", budget {budget.limit} calls" if budget.limit is not None else "") + ").")
    stop_reason = None
    try:
        for n, (i, j) in enumerate(todo, 1):
            k = tile_key(i, j)
            rec = cache["tiles"].get(k) or {"pts": [], "total": None, "pages": 0, "status": "partial"}
            cache["tiles"][k] = rec
            seen = {p[2] for p in rec["pts"]}
            lat_min, lat_max, lng_min, lng_max = tile_bounds(i, j, step)

            while rec["status"] != "complete" and not rec.get("stuck") and rec["pages"] < max_pages:
                if not budget.spend():
                    raise StopRun("call budget reached")
                params = {
                    "latrange1": lat_min, "latrange2": lat_max,
                    "longrange1": lng_min, "longrange2": lng_max,
                    "resultsPerPage": PAGE_SIZE,
                    "first": rec["pages"] * PAGE_SIZE,
                }
                try:
                    resp = requests.get(WIGLE_SEARCH_URL, params=params, auth=auth, timeout=30)
                except requests.RequestException as e:
                    print(f"  tile {k}: network error ({e}), skipping for now", file=sys.stderr)
                    break
                if resp.status_code == 429:
                    record_limited(cache, budget.used - 1)
                    raise StopRun("WiGLE daily limit reached (HTTP 429)")
                if resp.status_code in (401, 403):
                    raise StopRun(f"WiGLE rejected the credentials (HTTP {resp.status_code}). "
                                  f"Check WIGLE_API_NAME and WIGLE_API_TOKEN.")
                try:
                    resp.raise_for_status()
                    data = resp.json()
                except (requests.RequestException, ValueError) as e:
                    print(f"  tile {k}: bad response ({e}), skipping for now", file=sys.stderr)
                    break
                mark_back(cache)

                batch = data.get("results") or []
                new = 0
                for net in batch:
                    nid, lat, lng = net.get("netid"), net.get("trilat"), net.get("trilong")
                    if nid is None or lat is None or lng is None or nid in seen:
                        continue
                    seen.add(nid)
                    rec["pts"].append([lat, lng, nid])
                    new += 1
                rec["pages"] += 1
                if data.get("totalResults") is not None:
                    rec["total"] = data["totalResults"]

                if rec["total"] is not None:
                    done = len(rec["pts"]) >= rec["total"]
                else:
                    done = not data.get("moreResults")
                if not batch:
                    done = True
                if batch and new == 0 and not done:
                    rec["stuck"] = True
                    print(f"  tile {k}: paging did not return anything new, "
                          f"keeping the first {len(rec['pts'])} networks only", file=sys.stderr)
                rec["status"] = "complete" if done else "partial"
                time.sleep(0.5)

            total = rec["total"] if rec["total"] is not None else "?"
            print(f"  [{n}/{len(todo)}] tile {k}: {len(rec['pts'])}/{total} networks "
                  f"({tile_status(rec)}), calls used {budget.used}")
            save_cache(cache_path, cache)
    except StopRun as e:
        stop_reason = str(e)
    finally:
        save_cache(cache_path, cache)
    return stop_reason


# ---------------------------------------------------------------- reporting

def coverage_counts(tiles, cache):
    c = {"complete": 0, "partial": 0, "stuck": 0, "unfetched": 0}
    for t in tiles:
        c[tile_status(cache["tiles"].get(tile_key(*t)))] += 1
    return c


def print_plan(tiles, cache, max_pages, max_calls):
    c = coverage_counts(tiles, cache)
    needed = [t for t in tiles if calls_needed(cache["tiles"].get(tile_key(*t)), max_pages) > 0]
    best = len(needed)
    worst = sum(calls_needed(cache["tiles"].get(tile_key(*t)), max_pages) for t in needed)
    print("DRY RUN - no API calls made, no quota used.")
    print(f"  tiles in bbox:            {len(tiles)}")
    print(f"  already complete:         {c['complete']}")
    print(f"  partial / stuck:          {c['partial']} / {c['stuck']}")
    print(f"  not fetched yet:          {c['unfetched']}")
    print(f"  tiles that need calls:    {len(needed)}")
    print(f"  API calls, best case:     {best}  (every tile has 100 networks or fewer)")
    print(f"  API calls, worst case:    {worst}  (every tile uses all {max_pages} page(s))")
    if max_calls is not None:
        print(f"  --max-calls {max_calls}: the run would stop after {min(max_calls, worst)} call(s) at most.")
    else:
        print("  Tip: add --max-calls N to cap a run. Check your daily limit on your WiGLE account page.")
    print("  Tip: add --center LAT LNG to fetch the tiles nearest a point first.")


def write_counts_csv(path, tiles, cache, step):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tile_i", "tile_j", "lat_min", "lat_max", "lng_min", "lng_max",
                    "wigle_total", "fetched", "status"])
        for i, j in tiles:
            rec = cache["tiles"].get(tile_key(i, j))
            lat_min, lat_max, lng_min, lng_max = tile_bounds(i, j, step)
            w.writerow([i, j, lat_min, lat_max, lng_min, lng_max,
                        "" if rec is None or rec["total"] is None else rec["total"],
                        0 if rec is None else len(rec["pts"]),
                        tile_status(rec)])
    print(f"Wrote tile counts to {path}")


# ---------------------------------------------------------------- roads and routes

def build_residential_graph(bbox):
    import osmnx as ox
    lat_min, lat_max, lng_min, lng_max = bbox
    print("Downloading road graph from OSM (residential/living_street/unclassified)...")
    custom_filter = '["highway"~"residential|living_street|unclassified"]'
    return ox.graph_from_bbox(
        bbox=(lng_min, lat_min, lng_max, lat_max),
        custom_filter=custom_filter,
        simplify=True,
        retain_all=True,
    )


def flag_gap_edges(G, ap_points, min_aps, trusted_tiles, step):
    """Count APs per street. Only streets whose midpoint is in a COMPLETE tile
    can be called gaps; anywhere else we simply do not know."""
    import osmnx as ox

    # OSM graphs hold two-way streets as two directed edges (u,v) and (v,u),
    # and an AP snaps to only one of them. Count per street (unordered node
    # pair) so a street with APs is never reported as a gap through its
    # other direction.
    def street(u, v):
        return (u, v) if u <= v else (v, u)

    counts = {}
    if ap_points:
        lats = [p[0] for p in ap_points]
        lngs = [p[1] for p in ap_points]
        nearest = ox.distance.nearest_edges(G, X=lngs, Y=lats)
        for edge in nearest:
            pair = street(edge[0], edge[1])
            counts[pair] = counts.get(pair, 0) + 1

    gap_edges = []
    skipped = 0
    seen = set()
    for u, v, k in G.edges(keys=True):
        pair = street(u, v)
        if pair in seen:
            continue
        seen.add(pair)
        lat = (G.nodes[u]["y"] + G.nodes[v]["y"]) / 2
        lng = (G.nodes[u]["x"] + G.nodes[v]["x"]) / 2
        if tile_key(grid_index(lat, step), grid_index(lng, step)) not in trusted_tiles:
            skipped += 1
            continue
        if counts.get(pair, 0) < min_aps:
            gap_edges.append((u, v, k))
    print(f"{len(gap_edges)} streets flagged as gaps "
          f"({skipped} of {len(seen)} streets skipped: tile not fully fetched).")
    return gap_edges


def cluster_and_route(G, gap_edges):
    """Group contiguous gap streets and build a route-inspection path per group."""
    import networkx as nx
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
            last = circuit[-1][1]
            coords.append((sub.nodes[last]["y"], sub.nodes[last]["x"]))
            routes.append(coords)
        except Exception as e:
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


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Find unscanned residential streets using WiGLE data, low-quota friendly.")
    ap.add_argument("--bbox", type=float, nargs=4, metavar=("LAT_MIN", "LAT_MAX", "LNG_MIN", "LNG_MAX"),
                    help="area to search (required unless you use --check-quota)")
    ap.add_argument("--check-quota", action="store_true",
                    help="make one tiny API call to see if your quota is available; needs no --bbox")
    ap.add_argument("--out", default="gaps.gpx", help="output GPX file")
    ap.add_argument("--tile-step", type=float, default=0.02, help="tile size in degrees (0.02 = one WDGWars cell)")
    ap.add_argument("--min-aps", type=int, default=1, help="streets with fewer APs than this count as gaps")
    ap.add_argument("--cache", default="wigle_points_cache.json", help="per-tile cache file")
    ap.add_argument("--max-pages", type=int, default=1, help="pages (100 networks each) to fetch per tile")
    ap.add_argument("--max-calls", type=int, default=None, help="stop after this many WiGLE API calls")
    ap.add_argument("--center", type=float, nargs=2, metavar=("LAT", "LNG"), help="fetch tiles nearest this point first")
    ap.add_argument("--dry-run", action="store_true", help="show the API call estimate and exit; uses no quota")
    ap.add_argument("--counts-only", action="store_true", help="fetch tile counts, write the CSV, skip road download and routing")
    ap.add_argument("--counts-csv", default="tile_counts.csv", help="where to write per-tile WiGLE counts")
    args = ap.parse_args()

    if args.check_quota:
        check_quota(wigle_auth(), load_cache(args.cache, args.tile_step), args.cache)
        return
    if not args.bbox:
        ap.error("--bbox is required (unless you use --check-quota)")

    lat_min, lat_max, lng_min, lng_max = args.bbox
    if lat_min >= lat_max or lng_min >= lng_max:
        sys.exit("--bbox must be LAT_MIN LAT_MAX LNG_MIN LNG_MAX with min smaller than max.")
    if args.max_pages < 1:
        sys.exit("--max-pages must be at least 1.")
    step = args.tile_step

    tiles = order_tiles(tiles_for_bbox(tuple(args.bbox), step), args.center, step)
    cache = load_cache(args.cache, step)

    if args.dry_run:
        print_plan(tiles, cache, args.max_pages, args.max_calls)
        return

    budget = Budget(args.max_calls)
    stop_reason = None
    if any(calls_needed(cache["tiles"].get(tile_key(*t)), args.max_pages) > 0 for t in tiles):
        auth = wigle_auth()
        stop_reason = fetch_tiles(auth, tiles, cache, args.cache, step, args.max_pages, budget)
    else:
        print("Every tile in this bbox is already cached. No API calls needed.")

    write_counts_csv(args.counts_csv, tiles, cache, step)
    c = coverage_counts(tiles, cache)
    print(f"Coverage: {c['complete']} complete, {c['partial']} partial, "
          f"{c['stuck']} stuck, {c['unfetched']} not fetched (of {len(tiles)} tiles). "
          f"API calls used this run: {budget.used}.")
    if stop_reason:
        print(f"Stopped early: {stop_reason}. Run the same command again later and it resumes from the cache.")
        if "429" in stop_reason:
            e = _open_entry(cache)
            if e and e.get("calls_before_limit"):
                print(f"{e['calls_before_limit']} calls worked before the 429 (the count above also includes the "
                      f"rejected call). If your quota was fresh when you started, that is your daily limit.")
            print("Later, run with --check-quota (no --bbox needed) to see when it is back.")

    if args.counts_only:
        return

    trusted = {tile_key(*t) for t in tiles if tile_status(cache["tiles"].get(tile_key(*t))) == "complete"}
    if not trusted:
        print("No tile is fully fetched yet, so there is nothing to analyze. Run again later or raise --max-calls.")
        return
    if len(trusted) < len(tiles):
        print("Note: routes only cover streets inside complete tiles. Partial, stuck and unfetched tiles are skipped.")

    ap_points = []
    for t in tiles:
        rec = cache["tiles"].get(tile_key(*t))
        if rec:
            ap_points.extend((p[0], p[1]) for p in rec["pts"])

    G = build_residential_graph(tuple(args.bbox))
    gap_edges = flag_gap_edges(G, ap_points, args.min_aps, trusted, step)
    if not gap_edges:
        print("No gap streets found in the complete tiles.")
        return
    routes = cluster_and_route(G, gap_edges)
    write_gpx(routes, args.out)
    print(f"Wrote {args.out} - import into OsmAnd for turn-by-turn nav through the gap streets.")


if __name__ == "__main__":
    main()

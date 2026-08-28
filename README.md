# Wardrive Gap-Finding Scripts

Two scripts for planning wardrives against unscanned territory, pulling from different data sources at different resolutions. Both output a GPX file for OsmAnd.

---

## 1. `warroom_route.py` — coarse, fast, no external API

Pulls "virgin" (uncaptured) grid cells that contain roads directly from your self-hosted [warroom](https://github.com/Taccooh/warroom) SQLite database. No internet calls needed — just reads the DB.

**Resolution:** ~2km grid cells. Good for "which large areas have I not touched at all," not for finding individual missed streets — a cell with even one AP found on a main road counts as fully captured.

**Where to run:** On the Pi itself (or anywhere with a copy of `warroom.sqlite`). Only needs Python's stdlib `sqlite3` — no pip installs.

### Setup

Find your `user_id` first:
```bash
sqlite3 /home/fusedstamen/docker/warroom/data/warroom.sqlite "SELECT id, name FROM users;"
```
(If the `name` column errors, run `.schema users` to find the actual username column — could be `username`, `wdg_username`, etc.)

### Run

```bash
python3 warroom_route.py --user-id <your_id> --bbox <lat_min> <lat_max> <lng_min> <lng_max> --out route.gpx
```

Example (Belmont-area bbox):
```bash
python3 warroom_route.py --user-id 1 --bbox 42.3691 42.3979 -71.2205 -71.1381 --out belmont_route.gpx
```

One-liner that looks up your user_id from your username automatically:
```bash
USER_ID=$(sqlite3 /home/fusedstamen/docker/warroom/data/warroom.sqlite "SELECT id FROM users WHERE name='fusedstamen';") && python3 warroom_route.py --user-id $USER_ID --bbox 42.3691 42.3979 -71.2205 -71.1381 --out belmont_route.gpx
```

### Options

| Flag | Default | Purpose |
|---|---|---|
| `--db` | `/home/fusedstamen/docker/warroom/data/warroom.sqlite` | Path to the warroom DB |
| `--user-id` | *(required)* | Your warroom user ID |
| `--bbox` | *(required)* | `lat_min lat_max lng_min lng_max` |
| `--out` | `route.gpx` | Output file |
| `--max-stops` | none | Cap the number of stops if a bbox returns a huge number of cells |

### What it does

1. Queries `virgin_cells` joined with `cell_roads` for cells you haven't captured that actually contain a road.
2. Orders them into a drivable route using greedy nearest-neighbor (not full TSP — just avoids zigzagging).
3. Writes both `<wpt>` waypoints and an ordered `<rte>` route to the GPX file.

### Notes

- The DB path is absolute, so the script itself can live anywhere (home directory is simplest — the `docker/` directory is often not writable).
- If a bbox returns hundreds of cells, use `--max-stops` rather than planning an unreasonably long drive.

---

## 2. `find_gap_streets.py` — precise, slower, needs WiGLE API + OSMnx

Pulls **all** WiGLE network points in a bbox (not just yours — useful if your team scans jointly) and snaps them to an actual OSM residential road graph, so it can flag individual streets with no nearby APs rather than a whole coarse grid cell.

**Resolution:** street-level. This is the one to use when `warroom_route.py`'s grid cells are too coarse to find specific missed streets.

**Where to run:** On your main PC, **not** the Pi — OSMnx/geopandas are heavy.

### Setup

```bash
pip install osmnx networkx requests --break-system-packages
export WIGLE_API_NAME=your_name
export WIGLE_API_TOKEN=your_token
```
(Get your API name/token from your WiGLE account page → API tokens.)

### Run

```bash
python3 find_gap_streets.py --bbox <lat_min> <lat_max> <lng_min> <lng_max> --out gaps.gpx
```

Example:
```bash
python3 find_gap_streets.py --bbox 42.00 42.17 -71.75 -71.53 --out gaps.gpx
```

### Options

| Flag | Default | Purpose |
|---|---|---|
| `--bbox` | *(required)* | `lat_min lat_max lng_min lng_max` |
| `--out` | `gaps.gpx` | Output file |
| `--tile-step` | `0.02` | WiGLE query tile size in degrees (keeps each query under WiGLE's 100-results/page limit) |
| `--min-aps` | `1` | Edges with fewer APs than this count as a gap |
| `--cache` | `wigle_points_cache.json` | Caches WiGLE results here so re-runs don't burn API quota |

### What it does

1. Tiles the bbox and pulls every WiGLE network point in it (cached locally after the first run).
2. Downloads the residential/living_street/unclassified road graph from OpenStreetMap via OSMnx — deliberately excludes highways/primary roads, since those get covered by through-traffic anyway.
3. Snaps every AP point to its nearest road edge and counts APs per edge.
4. Flags edges with fewer than `--min-aps` nearby APs as gaps.
5. Clusters contiguous gap streets into connected components and builds an approximate route-inspection path per cluster (via networkx `eulerize` + `eulerian_circuit`), so the route covers every gap street in a cluster with minimal backtracking.
6. Exports one GPX track per cluster.

### Notes

- Large regions (city/multi-town scale) are a heavy job for both the WiGLE quota and OSMnx/geopandas memory — that's why it's meant for your PC, not the Pi.
- The `--cache` file means you only pay the WiGLE API cost once per bbox; delete it to force a fresh pull.
- If `eulerize` fails on a cluster (can happen on disconnected/odd graphs), the script falls back to just listing edge endpoints in arbitrary order for that cluster rather than erroring out.

---

## Which one to use

- **Quick check of a whole region, no internet needed:** `warroom_route.py`
- **Precise, street-level gaps within a smaller area (or checking team-wide coverage, not just your own):** `find_gap_streets.py`

Both output GPX — import into OsmAnd via *My Places → Import GPX* for turn-by-turn navigation through the stops/streets.

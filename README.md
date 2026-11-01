# Wardrive Gap-Finding Scripts

Two scripts for planning wardrives against unscanned territory. Both write a GPX file you can load into OsmAnd or Gaia GPS for turn-by-turn navigation.

| Script | Needs | Resolution | Best for |
|---|---|---|---|
| `find_gap_streets.py` | A WiGLE account, Python | Street level | Anyone. Start here. |
| `warroom_route.py` | Your own copy of the warroom database | ~2 km grid cells | People who self-host [warroom](https://github.com/Taccooh/warroom) |

Both scripts have only been tested on one person's setup and data. Expect rough edges and tell the author what breaks.

---

## Start here if you are new

You almost certainly want `find_gap_streets.py`. It only needs a free WiGLE account, and it was changed to work with small API quotas.

1. Get your own WiGLE API name and token from your WiGLE account page (the API token section). Check the page for your daily limit. Brand-new accounts usually get less.
2. Install the basics:
   ```bash
   pip install requests
   ```
   (Route building needs two more packages, covered below. The dry run and the count export do not.)
3. Set your credentials. Use your own, and never put them in a script or a repository:
   ```bash
   export WIGLE_API_NAME=your_api_name
   export WIGLE_API_TOKEN=your_api_token
   ```
4. Pick a SMALL area first, such as one town, as a bounding box: `LAT_MIN LAT_MAX LNG_MIN LNG_MAX`.
5. See what it would cost before spending anything:
   ```bash
   python3 find_gap_streets.py --bbox LAT_MIN LAT_MAX LNG_MIN LNG_MAX --dry-run
   ```
6. Run it with a cap that fits your limit:
   ```bash
   python3 find_gap_streets.py --bbox LAT_MIN LAT_MAX LNG_MIN LNG_MAX --max-calls 40
   ```
   If you run out of calls or hit the daily limit, nothing is lost. Run the same command again later and it continues where it stopped.

---

## `find_gap_streets.py` - street-level gaps using WiGLE

Finds residential streets where nobody on WiGLE has logged any WiFi networks, then builds a driving route through them. It uses all WiGLE data in the area, not only your own.

### Setup

Dry run and count export:
```bash
pip install requests
```

Full route building, which also downloads road data from OpenStreetMap:
```bash
pip install requests osmnx networkx
```
Run the full version on a normal PC. OSMnx is too heavy for a Raspberry Pi.

### Commands

```bash
# 1. Estimate the cost. Uses no quota and needs no WiGLE credentials.
python3 find_gap_streets.py --bbox LAT_MIN LAT_MAX LNG_MIN LNG_MAX --dry-run

# 2. Cheapest useful run: only count networks per tile, no routes.
python3 find_gap_streets.py --bbox LAT_MIN LAT_MAX LNG_MIN LNG_MAX --counts-only

# 3. Full run with a call cap, nearest tiles first.
python3 find_gap_streets.py --bbox LAT_MIN LAT_MAX LNG_MIN LNG_MAX --max-calls 40 --center LAT LNG
```

### Where the output goes

Files are written to the folder you run the command from, unless you pass other paths:

| File | What it is |
|---|---|
| `gaps.gpx` | Route tracks, one per cluster of gap streets. Import into OsmAnd (*My Places, Import GPX*). |
| `tile_counts.csv` | WiGLE network count for every tile in your box. |
| `wigle_points_cache.json` | Saved results, one entry per tile. This is what makes re-runs free. |

### Options

| Flag | Default | Purpose |
|---|---|---|
| `--bbox` | required | `lat_min lat_max lng_min lng_max` |
| `--out` | `gaps.gpx` | Route output file |
| `--dry-run` | off | Print the API call estimate and exit. No quota used. |
| `--max-calls` | none | Stop cleanly after this many WiGLE API calls |
| `--max-pages` | `1` | Pages fetched per tile. One page is 100 networks. |
| `--center LAT LNG` | none | Fetch the tiles closest to this point first |
| `--counts-only` | off | Fetch counts, write `tile_counts.csv`, skip roads and routing |
| `--counts-csv` | `tile_counts.csv` | Where to write the counts |
| `--tile-step` | `0.02` | Tile size in degrees. Leave it alone to match game cells. |
| `--min-aps` | `1` | A street with fewer networks than this counts as a gap |
| `--cache` | `wigle_points_cache.json` | Cache file |

### How it works

1. Splits your box into tiles on a fixed 0.02 degree grid. This is the same grid WDGWars uses for its cells, so one tile is one game cell.
2. Asks WiGLE for the networks in each tile. Each tile is saved to the cache as soon as it finishes, marked complete, partial, stuck or not fetched.
3. Downloads the residential, living-street and unclassified roads for your box from OpenStreetMap. Highways and primary roads are left out on purpose, since through-traffic already covers them.
4. Matches each network to its nearest street and counts networks per street.
5. Flags streets with fewer than `--min-aps` networks as gaps, but only inside tiles that were fully fetched.
6. Groups touching gap streets into clusters and builds an approximate route through each cluster with minimal backtracking.
7. Writes one GPX track per cluster.

### Quota: what to know

- **Your daily limit is set by WiGLE, per account.** It depends on your account and is not the same for everyone. Check your WiGLE account page. If you need more, WiGLE says to email WiGLE-admin with your username and what you are using it for.
- **One call per tile is the normal cost.** A tile with 100 networks or fewer takes one call at the default `--max-pages 1`. The dry run shows both the best and worst case for your box.
- **Big boxes add up fast.** A box of about 19 km by 18 km (for example `42.00 42.17 -71.75 -71.53`) is 108 tiles, so at least 108 calls. Start with one town.
- **A tile with more than 100 networks is only partly fetched at the default.** Its streets are skipped, not guessed at, and the dense areas are the ones that already have coverage. Raise `--max-pages` if you need to look inside them, at a higher cost.
- **Running out is safe.** On the daily-limit error (HTTP 429) or when `--max-calls` is reached, the script saves everything and stops. Run the same command again later.
- **Cached tiles cost nothing.** Delete `wigle_points_cache.json` only if you want fresh data.
- **Old cache files:** a cache from the earlier version of this script is moved to `wigle_points_cache.json.v1.bak` and ignored, because it could not tell finished tiles from unfinished ones.

### Things that can surprise you

- If only some tiles are fetched, the routes cover only those tiles. The script prints how many tiles are complete.
- Routes follow intersections in straight lines, so the GPX can cut corners on curved streets. Check it in your map app before driving.
- WiGLE counts include old data and every contributor, so "has networks" does not mean the networks are currently captured in any game.
- The paging parameter for page 2 and later (`first`) follows the WiGLE v2 search API but has not been checked against the live service. If a page returns nothing new, the script marks the tile as stuck, keeps what it has, and stops paging that tile. The default of one page per tile is unaffected.

---

## `warroom_route.py` - coarse, fast, no internet needed

Reads "virgin" (not yet captured) grid cells that contain roads straight from a warroom SQLite database, orders them into a driving route (nearest neighbour), and writes a GPX file.

**This only works if you run your own warroom** and have a copy of its `warroom.sqlite`. If you use someone else's hosted warroom, you do not have that file, and you should use `find_gap_streets.py` instead.

**Resolution:** about 2 km cells. Good for "which large areas have I not touched at all", not for finding individual missed streets. A cell with even one network on a main road counts as captured.

**Where to run:** on the machine that holds the database (for example the Pi that hosts warroom). It needs only Python's built-in `sqlite3`, no installs.

### Setup

Find your `user_id`:
```bash
sqlite3 /path/to/warroom.sqlite "SELECT id, name FROM users;"
```
If the `name` column does not exist, run `sqlite3 /path/to/warroom.sqlite ".schema users"` to find the username column. It may be `username` or `wdg_username`.

### Run

```bash
python3 warroom_route.py --db /path/to/warroom.sqlite --user-id YOUR_ID --bbox LAT_MIN LAT_MAX LNG_MIN LNG_MAX --out route.gpx
```

The built-in default database path in the script is the author's own, so always pass `--db` with your path.

The output file is written to the folder you run the command from, unless you pass a different `--out` path.

### Options

| Flag | Default | Purpose |
|---|---|---|
| `--db` | the author's path, so set your own | Path to the warroom database |
| `--user-id` | required | Your warroom user ID |
| `--bbox` | required | `lat_min lat_max lng_min lng_max` |
| `--out` | `route.gpx` | Output file |
| `--max-stops` | none | Cap the number of stops if a box returns a huge number of cells |

### How it works

1. Queries `virgin_cells` joined with `cell_roads` for cells you have not captured that contain a road.
2. Orders them into a route with a nearest-neighbour pass (not a full optimal route, just no zigzagging).
3. Writes both waypoints and an ordered route to the GPX file.

If a box returns hundreds of cells, use `--max-stops` rather than planning an unreasonably long drive. The script can live anywhere. A home folder is simplest, since the warroom `docker/` folder is often not writable.

---

## Which one to use

- **You do not run warroom, or you want specific streets:** `find_gap_streets.py`
- **You run warroom and want a quick look at whole regions you have not touched:** `warroom_route.py`

## Before you share or reuse this

- WiGLE data is for planning only. Never upload WiGLE data to WDGWars or anywhere else as your own collection.
- Use your own WiGLE and warroom tokens. Do not share them, paste them into chats, or commit them.
- Both scripts have only been proven on one person's data. If something looks wrong, say so rather than assuming it is right.

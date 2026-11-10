# Wardrive Tools

Scripts for planning wardrives, tracking WDGWars data through a self-hosted [warroom](https://github.com/Taccooh/warroom), and checking Wardrift. Every script has usage in its header, and most print it when run with no arguments. Nothing here uploads your data anywhere unless the script says so.

| Folder | What is in it |
|---|---|
| [`scripts/`](scripts) | Route planning and gap finding, cell watching, trip reports, your own WiGLE coverage heat table |
| [`tracker/`](tracker) | Pull warroom data and look at leaderboard patterns (descriptive only) |
| [`wardrift/`](wardrift) | Read-only probes and a log uploader for Wardrift |

Sections below: [gap-finding scripts](#gap-finding-scripts), [shared setup](#shared-setup-for-the-other-tools), [scripts/](#other-scripts-in-scripts), [tracker/](#tracker), [wardrift/](#wardrift), [data limits](#what-the-data-can-and-cannot-show).

---

## Gap-finding scripts

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
| `--bbox` | required (except with `--check-quota`) | `lat_min lat_max lng_min lng_max` |
| `--out` | `gaps.gpx` | Route output file |
| `--check-quota` | off | Make one tiny API call and say whether your quota is available. Needs no `--bbox`. |
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

### Find your own daily limit and when it resets

WiGLE does not publish a fixed number, and the limit can differ per account. You can measure yours. This deliberately uses up the rest of your day's allowance, so do it when you do not need the API.

1. Run a count export over a box big enough that you run out of quota before you run out of tiles. About 3 degrees each way around you is roughly 22,500 tiles. Use `--dry-run` with the same arguments first to see the tile count. Start from a folder with no old cache file.
   ```bash
   export WIGLE_API_NAME=your_api_name
   export WIGLE_API_TOKEN=your_api_token
   python3 find_gap_streets.py --bbox LAT_MIN LAT_MAX LNG_MIN LNG_MAX --counts-only --center LAT LNG
   ```
2. It stops at the first HTTP 429 and prints how many calls worked. If your quota was fresh when you started, that is your daily limit. The call count it prints also includes the rejected call, so the limit is that number minus 1. The cutoff time is saved in `wigle_points_cache.json`.
3. Later, check whether you are back. This needs no `--bbox` and uses at most one call:
   ```bash
   python3 find_gap_streets.py --check-quota
   ```
   Run it once an hour. It reports "still limited" or "quota available" and shows how long the cutoff lasted.
4. Compare a few days. If you come back at the same clock time every day, the reset is at a fixed time. If you come back about the same number of hours after each cutoff, it is a rolling window.

Notes: `--check-quota` also needs your credentials and writes to the cache file in the folder you run it from. It makes calls at the same gentle pace as the rest of the script and stops at the first 429.

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

## Shared setup for the other tools

Python 3.9 or newer. Everything uses only the standard library except `find_gap_streets.py` (`requests`, `osmnx`, `networkx`) and the Wardrift scripts (`requests`). On Windows use `py` instead of `python3`.

**Your warroom address.** Scripts that talk to warroom read it from the `WARROOM_URL` environment variable and stop with a message if it is missing.

```bash
# Linux / Mac / Pi
export WARROOM_URL=https://your-warroom.example.com

# Windows PowerShell (this window only)
$env:WARROOM_URL = "https://your-warroom.example.com"

# Windows, saved for new windows
setx WARROOM_URL https://your-warroom.example.com
```

In a cron line, put it in front of the command: `WARROOM_URL=https://... python3 free_cell_watch.py snap ~/free_cell_watch`

**Your warroom token.** A file in the work folder holding the token alone on one line. Tracker scripts want `.token`, `free_cell_watch.py` wants `warroom.token`, `trip_report.py` also accepts the `WARROOM_TOKEN` variable. The token is read-only, is never printed, and `.gitignore` keeps these files out of git. Do not paste it into chats or commit it.

**Python on its own.** The scripts send a `User-Agent: curl/8.5.0` header because the hosted warroom blocks the default Python one.

---

## Other scripts in `scripts/`

| Script | What it does | Run | Output |
|---|---|---|---|
| `wigle_cell_heat.py` | Turns your own downloaded WiGLE CSV exports (`.csv`, `.csv.gz`, `.zip`, any depth) into a per-cell heat table on the same 0.02 degree grid as the game. Shows which cells you have already collected heavily, so you can avoid them. No network calls, streams large files. | `py wigle_cell_heat.py "C:\path\to\exports"` | `wigle_cell_heat.csv` (heaviest first) and `wigle_cell_heat_summary.txt` inside that folder. Counts only, no MACs or SSIDs. |
| `free_cell_watch.py` | Takes a snapshot of every cell where you have APs, plus neighbors of unowned cells, and later reports what changed. Run `snap` on a timer, `report` when you want the summary. | `python3 free_cell_watch.py snap WORKDIR` and `python3 free_cell_watch.py report WORKDIR` | `WORKDIR/snapshots/state_*.csv.gz`, `free_cell_watch_log.txt`, `free_cell_report.txt`. Needs `WORKDIR/warroom.token` and `WARROOM_URL`. Example cron, every 30 minutes: `*/30 * * * * WARROOM_URL=... python3 ~/free_cell_watch.py snap ~/free_cell_watch` |
| `trip_report.py` | Before and after totals (all-time APs, presence cells) for one player over a time window, from the warroom board history. | `python3 trip_report.py PLAYER_ID ["2026-11-05 13:00:00"] ["end"]`. Start defaults to 24 hours ago. Times are UTC. | Prints and writes `trip_report.txt` in the current folder. |
| `trip_analysis.py` | Splits a multi-day wardrive from your WiGLE-format CSVs by GPS and time, and compares the drive out with the drive back. | `python3 trip_analysis.py FOLDER_WITH_CSVS [OUTDIR]` | `trip_analysis.txt`, `trip_segments.csv`, `trip_buckets.csv` in OUTDIR. |
| `route_eval.py` | Example: asks the public OSRM demo server for driving routes between waypoints, then lists active cells you have not visited that are next to each route. Edit the `W` (waypoints) and `R` (routes) tables at the top to your own. | Run `tracker/pull.py` first so `out/state.json` exists in the current folder, then `python3 route_eval.py` | `route/detour_cells.csv` and `route/detour_cells.gpx` in the current folder. |

---

## `tracker/`

For anyone running a warroom who wants to watch the leaderboards. Everything is descriptive: it shows how numbers move, not why. A flag means "different from the others on this measure", never proof of anything, and the scripts only read public board numbers.

Set up a work folder (for example `~/warroom_work`) containing:
- `.token` with your warroom token
- `watchlist.json`, copied from `tracker/watchlist.example.json` and edited. Format: `{"players": {"123": "name"}, "gangs": ["Gang Name"]}`. Keep your real list out of the repository (it is in `.gitignore`).

| Script | What it does | Run | Output |
|---|---|---|---|
| `pull.py` | Pulls state, all boards, per-player history for everyone on your watchlist, and each listed gang. | `python3 pull.py WORKDIR` | `WORKDIR/out/` with `state.json`, `board_*.json`, `player_*.json`, `hist_*.json`, `gang_*.json`, `watch.json`. |
| `review.py` | Prints a summary of what `pull.py` collected: where each watched player sits on each board, growth rates, top 10s, gang totals. | `python3 review.py WORKDIR` | Screen only. |
| `anomaly.py` | Flags accounts that differ from their peers: steady 24/7 gain, batch uploads, week-versus-all-time gap (old data uploaded now), WiFi totals that never decrease, large presence jumps, BLE share. | `python3 anomaly.py boards_log.csv [OUTDIR] [DAYS]` | `anomaly_report.txt` and `anomaly_metrics.csv` in OUTDIR (default `./anomaly_out`, 14 days). |
| `boards_analysis.py` | Coverage of the hourly board log per player, then a per-day breakdown for one username. | `python3 boards_analysis.py boards_log.csv USERNAME` | Screen only. |
| `floor_analysis.py` | Compares hourly gain rates ("floor" versus typical) for the usernames you give, with a daily breakdown for the first one. | `python3 floor_analysis.py boards_log.csv NAME1 [NAME2 ...]` | Screen only. |
| `decay.py` | For each account, how often its WiFi total goes down between hourly samples. | `python3 decay.py boards_log.csv` | Screen only. |
| `decay_corr.py` | Compares WiFi-total decreases on the board with held-cell and AP changes from player history. Uses a fixed start date near the top of the file. | `python3 decay_corr.py WORKDIR boards_log.csv` | Screen only. |
| `patterns.py` | For the top players, shows two-day WiFi and BLE gain, BLE share, how much came from the three biggest hours, and active hours. | `python3 patterns.py WORKDIR` (run `pull.py` first) | Screen only. |
| `regions.py` | Where each player's visible held cells are, by broad region and 50 km block. Needs cell owner ids, which the API no longer exposes, so it is mostly historical now. | `python3 regions.py WORKDIR` | Screen only. |
| `add_watch.py` | Appends players to the `WARROOM_WATCH` line in `compose.tracker.yml` (the warroom tracker container) and prints the new value. Backs up the file the first time. | `python3 add_watch.py --players players.json [--dry-run] [--file PATH]` | Edits the compose file, prints the new `WARROOM_WATCH` value only. Copy `players.example.json` to start. |
| `diag.sh` | One-shot API check: token validity, key endpoints, state download, and which token endpoints exist. | `bash diag.sh WORKDIR [PLAYER_ID]` | Screen only. The token is never printed. |

`boards_log.csv` is the hourly board log the warroom territory tracker writes into its `data/` folder (columns include `board`, `source`, `player_id`, `username`, `sample_ts`, `wifi`, `ble`, `rank`).

---

## `wardrift/`

Needs `pip install requests` and your own Wardrift account. Read-only except the uploader.

| Script | What it does | Run | Output |
|---|---|---|---|
| `wardrift_probe.py` | Checks that your Wardrift API key works and which authentication style it accepts. | `python3 wardrift_probe.py WORKDIR` with `WORKDIR/wardrift.key` | `wardrift_probe_out.txt`: status codes and JSON field names only, never the key. |
| `wardrift_area_probe.py` | For a bounding box, lists who controls each hex and the public daily influence history for up to 40 hexes. Asks for your username and password when run; they are used only to sign in. | `py wardrift_area_probe.py WORKDIR SOUTH NORTH WEST EAST` | `wardrift_area_report.txt` and `wardrift_area_tiles.csv`. |
| `wardrift_upload.py` | Uploads WiGLE-format CSV logs to Wardrift in compliant parts: gzip, size limits, the daily allowance, no duplicates on re-run. | `python3 wardrift_upload.py WORKDIR [--dry-run]` with `WORKDIR/wardrift.key` and `WORKDIR/to_upload/` | `wardrift_upload_log.csv`. Use `--dry-run` first. It reports how many rows are older than 72 hours, which earn no credit. |

---

## What the data can and cannot show

- Boards list only the top 50 players, so most players cannot be looked up on a board.
- Since late October the warroom API returns owner id 0 for enemy cells, and per-player held-cell history stopped updating for everyone except the key owner. Board numbers still update hourly.
- A cell shown as `free` has no team listed as owner. It may still be held by a player with no team, which the WDGWars site shows but this feed does not.
- Presence (cells you have APs in), held cells, and leaderboard WiFi and BLE totals are different measures. Do not compare them with each other.
- Leaderboard totals include BLE. Only WiFi with a normal MAC counts toward territory.

## Which one to use

- **You do not run warroom, or you want specific streets:** `find_gap_streets.py`
- **You run warroom and want a quick look at whole regions you have not touched:** `warroom_route.py`

## Before you share or reuse this

- WiGLE data is for planning only. Never upload WiGLE data to WDGWars or anywhere else as your own collection.
- Use your own WiGLE, warroom and Wardrift credentials. Do not share them, paste them into chats, or commit them. `.gitignore` already skips the usual token, key and watchlist files.
- The `tracker/` scripts describe public numbers only. Treat results as questions to ask, not accusations, and keep any named watchlist private.
- Both scripts have only been proven on one person's data. If something looks wrong, say so rather than assuming it is right.

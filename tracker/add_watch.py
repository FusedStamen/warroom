#!/usr/bin/env python3
"""add_watch.py - append more players to WARROOM_WATCH in compose.tracker.yml (run on the Pi).

Usage (from anywhere):
    python3 add_watch.py --players players.json   # edits ~/docker/territory-tracker/compose.tracker.yml
    python3 add_watch.py --players players.json --dry-run   # shows what would change, writes nothing
    python3 add_watch.py --file /path/to/compose.tracker.yml

What it does:
  - finds the WARROOM_WATCH line, keeps every entry already there, adds the players from your --players file that are missing
  - saves a backup next to the file as compose.tracker.yml.bak (only the first time it changes something)
  - prints ONLY the new WARROOM_WATCH value (your API token is never printed)
Output: terminal only.
Then restart the tracker (this script prints the exact command).
"""
import argparse, json, os, re, shutil, sys


ap = argparse.ArgumentParser()
ap.add_argument("--file", default=os.path.expanduser("~/docker/territory-tracker/compose.tracker.yml"))
ap.add_argument("--players", required=True, help='JSON file: [[123, "name"], [456, "other"]] - the players to add')
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()
ADD = [(int(p), str(n)) for p, n in json.load(open(a.players, encoding="utf-8"))]

try:
    text = open(a.file, encoding="utf-8").read()
except OSError as e:
    sys.exit(f"Cannot read {a.file}: {e}\nUse --file to point at compose.tracker.yml")

pat = re.compile(r'(WARROOM_WATCH:\s*")([^"]*)(")')
m = pat.search(text)
if not m:
    sys.exit("Could not find a line like  WARROOM_WATCH: \"...\"  in the file. Nothing changed.")

entries = [e for e in m.group(2).split(",") if e.strip()]
have = set()
for e in entries:
    pid = e.split(":", 1)[0].strip()
    if pid.isdigit():
        have.add(int(pid))

added = [(p, n) for p, n in ADD if p not in have]
if not added:
    print("Nothing to add - all of these players are already in WARROOM_WATCH.")
    print("WARROOM_WATCH:", ",".join(entries))
    sys.exit(0)

new_entries = entries + [f"{p}:{n}" for p, n in added]
new_val = ",".join(new_entries)
print(f"Existing entries: {len(entries)}   Adding: {len(added)}   New total: {len(new_entries)}")
print("Adding:", ", ".join(f"{p}:{n}" for p, n in added))
print("\nNew WARROOM_WATCH value:\n" + new_val)

if a.dry_run:
    print("\n(dry run - file not changed)")
    sys.exit(0)

bak = a.file + ".bak"
if not os.path.exists(bak):
    shutil.copy2(a.file, bak)
    print(f"\nBackup saved: {bak}")
new_text = text[:m.start(2)] + new_val + text[m.end(2):]
open(a.file, "w", encoding="utf-8").write(new_text)
print(f"Updated: {a.file}")
d = os.path.dirname(os.path.abspath(a.file))
print(f"\nNext, restart the tracker so it picks this up (env-only change, no rebuild):\n  cd {d} && docker compose -f compose.tracker.yml up -d --force-recreate\nThen check the first cycle:\n  docker compose -f compose.tracker.yml logs -f   (Ctrl+C stops following; the container keeps running)")

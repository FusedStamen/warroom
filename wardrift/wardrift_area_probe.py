#!/usr/bin/env python3
"""Wardrift area probe - who holds the hexes in an area, and how they got their influence.

Usage:   py wardrift_area_probe.py <workdir> south north west east
Needs:   Python with "requests" installed (py -m pip install requests).
         Your Wardrift username and password. The script asks for them when it runs (the password is not shown
         as you type). They are used only to sign in to wardrift.net, never written to any file or printed.
Output:  <workdir>/wardrift_area_report.txt   readable summary
         <workdir>/wardrift_area_tiles.csv    one row per hex in the area

What it does (read-only, Wardrift API v3 docs):
  1. Signs in (POST /v1/auth/sign-in/username) to get a session token.
  2. GET /v1/map/viewport?mode=hex for the area: hex ids, centers, controlling faction/guild, outposts, influence.
  3. For up to 40 hexes (the highest-influence ones plus an even spread), GET /v1/territory/{hex}/history:
     public daily totals of influence awards, with no player, upload or device identifiers.
  4. Signs out (POST /v1/auth/sign-out).
Rate limits respected: history reads are paced under 30 per minute and wait out any 429.
It only reports what the data shows. It does not decide whether anything is real or fake.
"""
import csv
import getpass
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://wardrift.net/v1"
UA = "wardrift-area-probe/1.0"
HISTORY_SAMPLE = 40
HISTORY_PAUSE = 2.3          # seconds between history calls (limit is 30/min)
MAX_HISTORY_PAGES = 4


def die(msg):
    sys.exit(f"ERROR: {msg}")


def call(sess, method, path, **kw):
    for attempt in range(4):
        try:
            r = sess.request(method, BASE + path, timeout=60, **kw)
        except requests.RequestException as e:
            die(f"request failed on {path}: {type(e).__name__}")
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "30") or 30)
            print(f"  rate limited, waiting {wait}s")
            time.sleep(min(wait, 90) + 1)
            continue
        return r
    die(f"still rate limited on {path}")


def hav_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def main():
    args = sys.argv[1:]
    if not args:
        die("give a work folder, e.g.  py wardrift_area_probe.py .")
    work = Path(args[0])
    work.mkdir(parents=True, exist_ok=True)
    if len(args) < 5:
        die("give the area too, e.g.  py wardrift_area_probe.py . SOUTH NORTH WEST EAST")
    south, north, west, east = map(float, args[1:5])

    username = input("Wardrift username: ").strip()
    password = getpass.getpass("Wardrift password (hidden): ")
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA, "Accept": "application/json"})
    r = call(sess, "POST", "/auth/sign-in/username",
             json={"username": username, "password": password, "remember_me": False})
    password = None
    if r.status_code != 200:
        die(f"sign-in failed (HTTP {r.status_code}). Check the username and password.")
    try:
        token = r.json()["session"]["token"]
    except Exception:
        die("sign-in worked but the response had no session token in the expected place")
    sess.headers["Authorization"] = f"Bearer {token}"
    print("Signed in.")

    r = call(sess, "GET", "/map/viewport", params={
        "mode": "hex", "south": south, "north": north, "west": west, "east": east,
        "territoryLimit": 4000, "outpostLimit": 200})
    if r.status_code != 200:
        die(f"map viewport failed (HTTP {r.status_code})")
    data = r.json()
    tiles = data.get("territory") or []
    outposts = data.get("outposts") or []
    print(f"Hexes returned: {len(tiles)}   outposts: {len(outposts)}")

    rows = []
    for t in tiles:
        infl = t.get("influence") or []
        scores = {i.get("faction_id"): float(i.get("score") or 0) for i in infl}
        total = sum(scores.values())
        top_f, top_s = (max(scores.items(), key=lambda kv: kv[1]) if scores else (None, 0.0))
        rows.append({
            "h3_index": t.get("h3_index"), "resolution": t.get("resolution"),
            "center_lat": t.get("center_lat"), "center_lon": t.get("center_lon"),
            "controlling_faction_id": t.get("controlling_faction_id"),
            "controlling_guild": t.get("controlling_guild_name") or "",
            "owning_outpost_id": t.get("owning_outpost_id") or "",
            "is_privateer": t.get("is_privateer"),
            "total_active_influence": round(total, 2),
            "top_faction_id": top_f, "top_faction_score": round(top_s, 2),
            "factions_with_influence": sum(1 for v in scores.values() if v > 0),
        })
    with (work / "wardrift_area_tiles.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["h3_index"])
        w.writeheader()
        w.writerows(rows)

    L = []
    P = L.append
    P("WARDRIFT AREA PROBE")
    P(f"Run (UTC): {datetime.now(timezone.utc):%Y-%m-%d %H:%M}   area: lat {south} to {north}, lon {west} to {east}")
    P(f"Hexes returned: {len(rows)}   outposts in area: {len(outposts)}   (viewport limit is 4000 hexes)")
    P("")
    if not rows:
        P("No hexes returned for this area.")
    else:
        res = Counter(r["resolution"] for r in rows)
        P(f"Hex resolution: {dict(res)}")
        # hex size from nearest-neighbor spacing
        pts = [(r["center_lat"], r["center_lon"]) for r in rows if r["center_lat"] is not None]
        nn = []
        for i, a in enumerate(pts[:300]):
            best = min((hav_km(a, b) for j, b in enumerate(pts) if j != i), default=None)
            if best:
                nn.append(best)
        if nn:
            P(f"Typical spacing between neighboring hex centers: about {statistics.median(nn):.1f} km "
              f"(so a hex is roughly that wide)")
        P("")
        P("1. Who controls the hexes")
        by_guild = Counter(r["controlling_guild"] or "(no controlling guild)" for r in rows)
        by_fac = Counter(r["controlling_faction_id"] for r in rows)
        for g, n in by_guild.most_common(12):
            infl = [r["total_active_influence"] for r in rows if (r["controlling_guild"] or "(no controlling guild)") == g]
            P(f"   {g:34s} hexes={n:4d}  median active influence={statistics.median(infl):.0f}  max={max(infl):.0f}")
        P(f"   by faction id: {dict(by_fac)}")
        P(f"   hexes with an outpost: {sum(1 for r in rows if r['owning_outpost_id'])}")
        P("")
        P("2. Active influence (after decay) across all hexes")
        tot = sorted(r["total_active_influence"] for r in rows)
        q = lambda p: tot[int(p * (len(tot) - 1))]
        P(f"   min={tot[0]:.0f}  p25={q(.25):.0f}  median={q(.5):.0f}  p75={q(.75):.0f}  max={tot[-1]:.0f}")
        P("")

        # history sample
        ranked = sorted(rows, key=lambda r: -r["total_active_influence"])
        pick = ranked[:HISTORY_SAMPLE // 2]
        rest = ranked[HISTORY_SAMPLE // 2:]
        if rest:
            step = max(1, len(rest) // (HISTORY_SAMPLE - len(pick)))
            pick += rest[::step][:HISTORY_SAMPLE - len(pick)]
        P(f"3. Award history for {len(pick)} sampled hexes (public daily totals, no player identifiers)")
        P("   hex id           guild controlling        first day   last day   days  total awarded  biggest single day  (share of total)")
        summaries = []
        for n, r in enumerate(pick, 1):
            entries, before = [], None
            for _ in range(MAX_HISTORY_PAGES):
                params = {"before": before} if before else None
                hr = call(sess, "GET", f"/territory/{r['h3_index']}/history", params=params)
                time.sleep(HISTORY_PAUSE)
                if hr.status_code != 200:
                    entries = None
                    P(f"   {r['h3_index']}  history failed HTTP {hr.status_code}")
                    break
                body = hr.json()
                entries += body.get("entries") or []
                before = body.get("next_before")
                if not before:
                    break
            if entries is None:
                continue
            contrib = [e for e in entries if e.get("kind") in ("contribution", "opening_balance")]
            if not contrib:
                P(f"   {r['h3_index']:16s} {(r['controlling_guild'] or '-')[:22]:22s}  no recorded awards in the pages read")
                continue
            per_day = defaultdict(float)
            for e in contrib:
                per_day[e["day"]] += float(e.get("influence") or 0)
            days = sorted(per_day)
            total = sum(per_day.values())
            big_day = max(per_day, key=per_day.get)
            share = per_day[big_day] / total if total else 0
            summaries.append((r["h3_index"], len(days), total, share))
            P(f"   {r['h3_index']:16s} {(r['controlling_guild'] or '-')[:22]:22s}  {days[0]}  {days[-1]}  {len(days):4d}  "
              f"{total:12.0f}  {per_day[big_day]:12.0f} on {big_day}  ({share:.0%})")
            if n % 10 == 0:
                print(f"  history {n}/{len(pick)}")
        P("")
        if summaries:
            one_day = sum(1 for s in summaries if s[1] == 1)
            heavy = sum(1 for s in summaries if s[3] >= 0.9)
            P("4. Pattern across the sample")
            P(f"   hexes whose awards all came on a single day: {one_day} of {len(summaries)}")
            P(f"   hexes where one day holds 90% or more of all awards: {heavy} of {len(summaries)}")
            P(f"   median number of distinct award days: {statistics.median(s[1] for s in summaries)}")
            P("")
        P("Reading this: hex tiles are not tied to roads, and the docs say mesh node positions and uploads both award")
        P("influence, so a filled area on its own does not say how it was made. The award history shows WHEN influence")
        P("arrived (one burst vs steady days). It carries no player names, so it cannot say WHO uploaded.")

    out = work / "wardrift_area_report.txt"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    call(sess, "POST", "/auth/sign-out")
    print("\n".join(L[:14]))
    print(f"\nReport: {out}\nTiles:  {work / 'wardrift_area_tiles.csv'}")


if __name__ == "__main__":
    main()

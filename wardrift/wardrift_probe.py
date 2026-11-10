#!/usr/bin/env python3
"""Wardrift read-access probe.

Usage:  python3 wardrift_probe.py <workdir>
Needs:  <workdir>/wardrift.key  (the wdk_ key alone on one line)
Output: <workdir>/wardrift_probe_out.txt  (status codes + top-level JSON field names only;
        the key is never printed or saved)
"""
import json
import sys
from pathlib import Path

import requests

BASE = "https://wardrift.net/v1"
UA = "wardrift-probe/1.0"

work = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
key = (work / "wardrift.key").read_text().strip()
if not key:
    sys.exit("wardrift.key is empty")

auth_modes = {
    "X-API-Key": {"X-API-Key": key},
    "Bearer": {"Authorization": f"Bearer {key}"},
    "none": {},
}

paths = [
    "/ingest/mesh",  # known to accept the key (control)
    "/leaderboard?scope=global&timeframe=all_time&includeStandings=true",
    "/leaderboard?scope=global&timeframe=daily&includeStandings=true",
    "/dashboard",
    "/openapi.json",
    "/openapi",
    "/docs",
    "/",
]


def describe(resp):
    ctype = resp.headers.get("Content-Type", "")
    info = f"HTTP {resp.status_code}  type={ctype.split(';')[0]}  bytes={len(resp.content)}"
    try:
        data = resp.json()
    except ValueError:
        return info + "  (not JSON)"
    if isinstance(data, dict):
        keys = sorted(data.keys())
        # never echo values; field names only
        info += f"  fields={keys[:25]}"
        if "error" in data:
            info += f"  error={str(data['error'])[:60]}"
    elif isinstance(data, list):
        info += f"  list_len={len(data)}"
    return info


lines = ["Wardrift read-access probe (key not recorded)", ""]
for path in paths:
    lines.append(path)
    for mode, hdrs in auth_modes.items():
        h = {"User-Agent": UA, "Accept": "application/json", **hdrs}
        try:
            r = requests.get(BASE + path, headers=h, timeout=20, allow_redirects=False)
            text = describe(r)
        except requests.RequestException as e:
            text = f"request failed: {type(e).__name__}"
        text = text.replace(key, "[redacted]")
        lines.append(f"  {mode:10s} {text}")
    lines.append("")

out = work / "wardrift_probe_out.txt"
out.write_text("\n".join(lines))
print(f"Wrote {out}")

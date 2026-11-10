#!/usr/bin/env python3
"""Upload WiGLE-format CSV logs to Wardrift (POST /v1/ingest/signals).

Usage:   python wardrift_upload.py <workdir> [--dry-run]
Needs:   <workdir>/wardrift.key     the wdk_ key alone on one line
         <workdir>/to_upload/       your .csv / .wiglecsv files
Output:  <workdir>/wardrift_upload_log.csv   one row per uploaded part (receipt fields, no key)

Behavior (from Wardrift API docs v3):
 - Each request is gzip, max 10 MiB decompressed and 200,000 records; files are split into parts under that.
 - Daily allowance is 256 MiB decompressed per UTC day (resets 00:00 UTC). The script stops at 250 MiB
   and tells you what is left for the next day.
 - Observations older than 72 hours are archived but earn no credit. --dry-run reports how many rows
   are older so you know before sending. Nothing is filtered or altered.
 - Parts already uploaded (matched by content hash in the log) are skipped, so re-running is safe.
 - Stops on the first error (bad key, daily limit, rejected file).
"""
import csv
import gzip
import hashlib
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = "https://wardrift.net/v1"
UA = "wardrift-upload/1.0"
MAX_RAW = 9 * 1024 * 1024        # stay under the 10 MiB decompressed cap
MAX_ROWS = 190_000               # stay under the 200,000 record cap
DAILY_STOP = 250 * 1024 * 1024   # stay under the 256 MiB daily allowance
EXTS = {".csv", ".wiglecsv"}
LOG_FIELDS = ["utc_time", "file", "part", "sha256", "http", "accepted", "duplicate", "outcome",
              "parsed_rows", "skipped_rows", "wifi_count", "bluetooth_count", "reward_candidate_count",
              "new_reward_count", "awarded_exp", "awarded_influence", "flags", "error"]


def split_file(path):
    """Return (preamble_text, header_index_ok, [row_lines]) keeping the WiGLE preamble + header."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    hdr = next((i for i, l in enumerate(lines[:20]) if l.lower().startswith("mac,")), None)
    if hdr is None:
        return None, None, []
    return lines[: hdr + 1], lines[hdr], [l for l in lines[hdr + 1:] if l.strip()]


def parts(preamble, rows):
    base = sum(len(l.encode("utf-8")) + 1 for l in preamble)
    cur, size = [], base
    for r in rows:
        n = len(r.encode("utf-8")) + 1
        if cur and (size + n > MAX_RAW or len(cur) >= MAX_ROWS):
            yield cur
            cur, size = [], base
        cur.append(r)
        size += n
    if cur:
        yield cur


def count_old(header, rows):
    cols = next(csv.reader([header]))
    try:
        idx = [c.strip().lower() for c in cols].index("firstseen")
    except ValueError:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    old = bad = 0
    for row in csv.reader(rows):
        try:
            t = datetime.fromisoformat(row[idx].strip().replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            old += t < cutoff
        except (ValueError, IndexError):
            bad += 1
    return old, bad


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    work = Path(args[0] if args else ".")
    src = work / "to_upload"
    logp = work / "wardrift_upload_log.csv"
    files = sorted(p for p in src.glob("*") if p.suffix.lower() in EXTS) if src.is_dir() else []
    if not files:
        sys.exit(f"No .csv/.wiglecsv files in {src}")

    key = ""
    if not dry:
        key = (work / "wardrift.key").read_text().strip()
        if not key:
            sys.exit("wardrift.key is empty")

    done = set()
    if logp.exists():
        with logp.open(newline="", encoding="utf-8") as f:
            done = {r["sha256"] for r in csv.DictReader(f) if r.get("accepted", "").lower() == "true"}
    new_log = not logp.exists()
    logf = None if dry else logp.open("a", newline="", encoding="utf-8")
    writer = None
    if logf:
        writer = csv.DictWriter(logf, fieldnames=LOG_FIELDS)
        if new_log:
            writer.writeheader()

    sess = requests.Session()
    sess.headers.update({"X-API-Key": key, "User-Agent": UA})
    sent_bytes = 0
    stop = False
    for p in files:
        pre, header, rows = split_file(p)
        if pre is None:
            print(f"SKIP {p.name}: no MAC,... header row found in first 20 lines")
            continue
        old = count_old(header, rows)
        print(f"{p.name}: {len(rows)} rows" + (f", {old[0]} older than 72h, {old[1]} unreadable times" if old else ""))
        for n, chunk in enumerate(parts(pre, rows), 1):
            raw = ("\n".join(pre + chunk) + "\n").encode("utf-8")
            sha = hashlib.sha256(raw).hexdigest()
            if sha in done:
                print(f"  part {n}: already uploaded, skipped")
                continue
            if sent_bytes + len(raw) > DAILY_STOP:
                print(f"  part {n}: would pass the 250 MiB daily limit, stopping. Rerun after 00:00 UTC.")
                stop = True
                break
            print(f"  part {n}: {len(chunk)} rows, {len(raw)/1048576:.2f} MiB" + ("  (dry run)" if dry else ""))
            if dry:
                sent_bytes += len(raw)
                continue
            gz = gzip.compress(raw)
            name = f"{p.stem}.part{n}.csv.gz"
            resp = None
            for attempt in range(3):
                try:
                    resp = sess.post(f"{BASE}/ingest/signals", data=gz, timeout=120, headers={
                        "Content-Type": "application/gzip", "X-File-Name": name})
                except requests.RequestException as e:
                    print(f"    request failed: {type(e).__name__}")
                    stop = True
                    break
                try:
                    body = resp.json()
                except ValueError:
                    body = {}
                if resp.status_code == 409 and body.get("error") == "sequence_conflict" and attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                break
            if resp is None:
                break
            sent_bytes += len(raw)
            body = body if isinstance(body, dict) else {}
            ok = resp.status_code == 200
            row = {"utc_time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "file": p.name,
                   "part": n, "sha256": sha, "http": resp.status_code, "accepted": body.get("accepted", ""),
                   "duplicate": body.get("duplicate", ""), "outcome": body.get("outcome", body.get("decision", "")),
                   "parsed_rows": body.get("parsed_rows", ""), "skipped_rows": body.get("skipped_rows", ""),
                   "wifi_count": body.get("wifi_count", ""), "bluetooth_count": body.get("bluetooth_count", ""),
                   "reward_candidate_count": body.get("reward_candidate_count", ""),
                   "new_reward_count": body.get("new_reward_count", ""),
                   "awarded_exp": body.get("awarded_exp", ""), "awarded_influence": body.get("awarded_influence", ""),
                   "flags": ";".join(map(str, body.get("flags", []) or [])),
                   "error": "" if ok else f"{body.get('error', '')} {body.get('message', '')}".strip()}
            writer.writerow(row)
            logf.flush()
            if ok:
                print(f"    OK outcome={row['outcome']} new_rewards={row['new_reward_count']} "
                      f"xp={row['awarded_exp']} influence={row['awarded_influence']} duplicate={row['duplicate']}")
            else:
                msg = row["error"] or f"HTTP {resp.status_code}"
                if resp.status_code == 429:
                    msg += f" (Retry-After {resp.headers.get('Retry-After', '?')}s)"
                if resp.status_code in (401, 403):
                    msg = f"key rejected (HTTP {resp.status_code})"
                print(f"    FAILED {msg}")
                stop = True
                break
        if stop:
            break
    if logf:
        logf.close()
        print(f"\nLog: {logp}")
    print(f"Decompressed bytes this run: {sent_bytes/1048576:.1f} MiB of 256 MiB daily allowance")


if __name__ == "__main__":
    main()

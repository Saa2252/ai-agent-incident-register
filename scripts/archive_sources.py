#!/usr/bin/env python3
"""Submit every source link to the Wayback Machine and record the snapshot.

Usage:
    python3 scripts/archive_sources.py [project_dir] [--check-only]

The register's claim is that a reader can check any assertion in two clicks. Link rot
breaks that claim quietly over months, and the rows most likely to rot are news articles
rather than rulings. So every source gets an archived copy and the archive URL goes in
the CSV next to the live one.

Run by hand, not in CI. The Wayback Machine rate-limits and occasionally refuses, and a
red build nobody can fix by retrying is a red build people learn to ignore.

--check-only looks up existing snapshots without asking for new ones.
"""

import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HEADERS = {"User-Agent": "ai-agent-incident-register archiver (+https://github.com/Saa2252/ai-agent-incident-register)"}
AVAILABLE = "https://archive.org/wayback/available?url="
SAVE = "https://web.archive.org/save/"
PAUSE = 6  # the Save Page Now endpoint is strict about pacing


def existing_snapshot(url):
    """Return the newest snapshot the Wayback Machine already holds, or None."""
    try:
        request = urllib.request.Request(AVAILABLE + urllib.parse.quote(url, safe=""), headers=HEADERS)
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except Exception:  # noqa: BLE001
        return None
    snap = data.get("archived_snapshots", {}).get("closest") or {}
    return snap.get("url") if snap.get("available") else None


def request_snapshot(url):
    """Ask for a new capture. Returns the snapshot URL or None."""
    try:
        request = urllib.request.Request(SAVE + url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=90) as response:
            final = response.geturl()
        return final if "/web/" in final else None
    except urllib.error.HTTPError as error:
        print(f"      save refused: HTTP {error.code}")
    except Exception as error:  # noqa: BLE001
        print(f"      save failed: {type(error).__name__}")
    return None


SOURCE_FIELDS = ["source_1_url", "source_2_url", "aftermath_source_url",
                 "deploy_evidence_source", "deploy_stop_authority_source",
                 "deploy_review_date_source"]


def main(argv):
    project_dir = Path(argv[1] if len(argv) > 1 and not argv[1].startswith("--") else ".").resolve()
    check_only = "--check-only" in argv
    csv_path = project_dir / "data" / "incidents.csv"

    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames)
        rows = list(reader)

    if "archive_urls" not in fields:
        fields.append("archive_urls")

    seen = {}
    for row in rows:
        archived = []
        urls = []
        for field in SOURCE_FIELDS:
            value = row.get(field, "").strip()
            if value and value not in urls:
                urls.append(value)
        for url in urls:
            if url in seen:
                archived.append(seen[url])
                continue
            print(f"  {row['id']}  {url[:78]}")
            snapshot = existing_snapshot(url)
            if snapshot:
                print(f"      already archived")
            elif not check_only:
                snapshot = request_snapshot(url)
                if snapshot:
                    print(f"      archived now")
                time.sleep(PAUSE)
            if snapshot:
                seen[url] = snapshot
                archived.append(snapshot)
        # Merge, never replace. A lookup that times out must not erase a snapshot that
        # was recorded on an earlier run. An earlier version of this script overwrote the
        # column from whatever the availability API happened to return that minute, and
        # quietly deleted good data.
        already = [a for a in row.get("archive_urls", "").split() if a]
        for snapshot in already:
            if snapshot not in archived:
                archived.append(snapshot)
        row["archive_urls"] = " ".join(archived)

    if check_only:
        print("\n--check-only: nothing written.")
    else:
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    total = sum(len(r["archive_urls"].split()) for r in rows if r["archive_urls"])
    print(f"\n{total} archived snapshots recorded across {len(rows)} rows.")
    missing = [r["id"] for r in rows if not r["archive_urls"]]
    if missing:
        print(f"No snapshot yet for: {', '.join(missing)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

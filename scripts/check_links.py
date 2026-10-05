#!/usr/bin/env python3
"""Check that every source link in the register still resolves.

Usage:
    python3 scripts/check_links.py [project_dir]

Kept out of CI on purpose. A link check that fails on somebody's rate limit would
train whoever maintains this to ignore a red build, and a red build nobody reads is
worse than no build. Run it by hand before publishing and before each promotion, then
update date_checked on the rows you confirmed.

Exit code 0 means every link answered. Exit code 1 means at least one did not, which
is a prompt to look rather than proof the source is gone.
"""

import csv
import sys
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT = 20
# Some publishers refuse a bare Python user agent. The point here is to find dead
# links, not to argue with bot rules, so the request identifies itself honestly.
HEADERS = {
    "User-Agent": "ai-agent-incident-register link checker (+https://github.com/Saa2252/ai-agent-incident-register)",
    "Accept": "text/html,application/xhtml+xml,*/*",
}


def check(url):
    request = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, ""
    except urllib.error.HTTPError as error:
        return error.code, error.reason
    except Exception as error:  # noqa: BLE001
        return None, f"{type(error).__name__}: {error}"


def main(argv):
    project_dir = Path(argv[1] if len(argv) > 1 else ".").resolve()
    csv_path = project_dir / "data" / "incidents.csv"
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    problems = []
    checked = 0
    for row in rows:
        for index in (1, 2):
            url = row[f"source_{index}_url"].strip()
            if not url:
                continue
            checked += 1
            status, note = check(url)
            where = f"{row['id']} source {index}"
            if status == 200:
                print(f"  ok   {where}  {url}")
            elif status in (401, 403, 405, 429):
                # A publisher blocking an automated request is not a dead link. It does
                # mean a person has to open it, so it is reported as something to look at.
                print(f"  look {where}  HTTP {status}  {url}")
                problems.append(f"{where}: HTTP {status}, blocked to automation. Open it by hand.")
            else:
                print(f"  FAIL {where}  {status or 'no response'} {note}  {url}")
                problems.append(f"{where}: {status or 'no response'} {note}")

    print(f"\nChecked {checked} links across {len(rows)} rows.")
    if problems:
        print(f"{len(problems)} need a look:")
        for line in problems:
            print(f"  {line}")
        return 1
    print("Every link answered 200.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

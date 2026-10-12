#!/usr/bin/env python3
"""Recompute every number the app displays and compare it with the data.

Usage:
    python3 scripts/check_displayed_numbers.py [project_dir]

The register's whole claim is that no number on screen is typed in. This renders the
app headlessly, pulls the figures out of what it rendered, and recomputes each one
straight from the CSV. A number that only agrees because someone updated both places is
exactly what this is for.

Runs in CI alongside the smoke test.
"""

import csv
import re
import sys
from pathlib import Path


def main(argv):
    project_dir = Path(argv[1] if len(argv) > 1 else ".").resolve()
    with open(project_dir / "data" / "incidents.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    counted = [r for r in rows if r["evidence_grade"] in {"A", "B"}]
    with open(project_dir / "data" / "case_harm_ratings.csv", newline="", encoding="utf-8") as fh:
        ratings = list(csv.DictReader(fh))

    expected = {
        "cases": len(rows),
        "counted": len(counted),
        "no false statement": sum(1 for r in counted if r["said_something_untrue"] == "No"),
        "record silent on stop": sum(1 for r in counted if r["deploy_stop_authority"] == "Not disclosed"),
        "control never built": sum(1 for r in counted if r["control_maturity"] == "Absent"),
        "control did not hold": sum(1 for r in counted if r["control_maturity"] == "Implemented"),
        "missing control not accuracy": sum(1 for r in counted if r["control_class"] != "Accuracy"),
        "no review date": sum(1 for r in counted if r["deploy_review_date"] == "Not disclosed"),
        "not attacker misuse": sum(1 for r in counted if r["directed_by"] != "Attacker"),
        "stated": sum(1 for r in counted if r["missing_control_basis"].startswith("Stated")),
        "entailed": sum(1 for r in counted if r["missing_control_basis"].startswith("Entailed")),
        "reading": sum(1 for r in counted if r["missing_control_basis"].startswith("Reading")),
        # Severity now lives in its own file on MIT's five-level framework. The checksum
        # is the total filled meter bars across every case's headline level.
        "filled meter bars": sum(
            max(int(x["level"]) for x in ratings if x["case_id"] == r["id"]) for r in rows
        ),
    }

    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        print("streamlit is not installed", file=sys.stderr)
        return 1

    at = AppTest.from_file(str(project_dir / "app.py"), default_timeout=180)
    at.run()
    if at.exception:
        for problem in at.exception:
            print(f"ERROR the app raised on load: {problem.value}", file=sys.stderr)
        return 1
    if not at.radio:
        print("ERROR no navigation rendered, so no screen could be checked", file=sys.stderr)
        return 1
    problems = []
    home_markdown = "\n".join(str(getattr(e, "value", "")) for e in at.markdown)

    # The three Home cards were re-picked on 12 October 2026 and will be again. This list
    # has to match what the page renders, and the dot checksum below depends on it, so a
    # re-pick that forgets this file fails here rather than going quiet.
    home_cards = (
        ("missing control not accuracy", "missing control not accuracy"),
        ("record silent on stop", "record silent on who could stop it"),
        ("not attacker misuse", "not attacker misuse"),
    )
    for key, label in home_cards:
        want = expected[key]
        if f'aria-label="{want} of {expected["counted"]}"' not in home_markdown:
            problems.append(
                f"home card '{label}' has no dot row for {want} of {expected['counted']}"
            )
        else:
            print(f"  ok   home card '{label}' = {want} of {expected['counted']}")

    dots_on = home_markdown.count('<i class="on">')
    want_dots = sum(expected[key] for key, _ in home_cards)
    if dots_on != want_dots:
        problems.append(f"{dots_on} filled dots on Home, data says {want_dots}")
    else:
        print(f"  ok   filled dots across the three cards = {dots_on}")

    counter = re.search(r"Showing (\d+) of (\d+) cases", home_markdown)
    if not counter:
        problems.append("could not find the case counter")
    else:
        shown, total = (int(g) for g in counter.groups())
        if (shown, total) != (expected["cases"], expected["cases"]):
            problems.append(f"counter says {shown} of {total}, data says {expected['cases']}")
        else:
            print(f"  ok   counter = {shown} of {total}")

    # Count only inside the case table. The open case below it renders its own pill, so
    # a whole-page count would include that case twice.
    table = re.search(r'<table class="cases">.*?</table>', home_markdown, re.S)
    filled = table.group(0).count('class="f"') if table else 0
    if filled and filled != expected["filled meter bars"]:
        problems.append(
            f"severity meters have {filled} filled bars, data says {expected['filled meter bars']}"
        )
    elif filled:
        print(f"  ok   severity meters = {filled} filled bars")

    # The not-accuracy claim moved to the Findings tab, so it is read there.
    findings = AppTest.from_file(str(project_dir / "app.py"), default_timeout=180)
    findings.run()
    findings.radio[0].set_value("Findings").run()
    if findings.exception:
        problems.append(f"the findings screen raised: {findings.exception[0].value}")
    else:
        text = "\n".join(str(getattr(e, "value", "")) for e in findings.markdown)
        claim = re.search(
            r"In (\d+) of (\d+) counted cases the missing control was not accuracy", text
        )
        if not claim:
            problems.append("could not find the not-accuracy claim on Findings")
        else:
            got, of = (int(g) for g in claim.groups())
            if (got, of) != (expected["missing control not accuracy"], expected["counted"]):
                problems.append(
                    f"findings claim says {got} of {of}, data says "
                    f"{expected['missing control not accuracy']} of {expected['counted']}"
                )
            else:
                print(f"  ok   findings claim = {got} of {of}")

    for line in problems:
        print(f"ERROR {line}", file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} displayed number(s) do not match the data.", file=sys.stderr)
        return 1
    print("\nEvery displayed number matches the data.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

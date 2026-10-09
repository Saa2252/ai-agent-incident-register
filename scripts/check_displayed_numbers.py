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

    expected = {
        "cases": len(rows),
        "counted": len(counted),
        "no false statement": sum(1 for r in counted if r["said_something_untrue"] == "No"),
        "record silent on stop": sum(1 for r in counted if r["deploy_stop_authority"] == "Not disclosed"),
        "control never built": sum(1 for r in counted if r["control_maturity"] == "Absent"),
        "control did not hold": sum(1 for r in counted if r["control_maturity"] == "Implemented"),
        "missing control not accuracy": sum(1 for r in counted if r["control_class"] != "Accuracy"),
        "stated": sum(1 for r in counted if r["missing_control_basis"].startswith("Stated")),
        "entailed": sum(1 for r in counted if r["missing_control_basis"].startswith("Entailed")),
        "reading": sum(1 for r in counted if r["missing_control_basis"].startswith("Reading")),
        "filled meter bars": sum(
            {"Severe": 4, "Serious": 3, "Moderate": 2, "Negligible": 1}[r["severity"]] for r in rows
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
    at.radio[0].set_value("The register").run()
    if at.exception:
        for problem in at.exception:
            print(f"ERROR the register screen raised: {problem.value}", file=sys.stderr)
        return 1

    register_markdown = "\n".join(str(getattr(e, "value", "")) for e in at.markdown)
    register_metrics = {m.label: m.value for m in at.metric}

    # Home carries its own computed figures, so it is read in the same pass.
    home = AppTest.from_file(str(project_dir / "app.py"), default_timeout=180)
    home.run()
    if home.exception:
        for problem in home.exception:
            print(f"ERROR the home screen raised: {problem.value}", file=sys.stderr)
        return 1
    home_markdown = "\n".join(str(getattr(e, "value", "")) for e in home.markdown)
    home_metrics = {m.label: m.value for m in home.metric}

    # Home renders its figures as HTML cards, so they are read back out of the markup.
    for key, label in (
        ("no false statement", "said nothing untrue"),
        ("record silent on stop", "record silent on who could stop it"),
        ("control never built", "control never built"),
    ):
        want = expected[key]
        if f'aria-label="{want} of {expected["counted"]}"' not in home_markdown:
            print(
                f"ERROR home card '{label}' has no dot row for {want} of "
                f"{expected['counted']}",
                file=sys.stderr,
            )
            return 1
        print(f"  ok   home card '{label}' = {want} of {expected['counted']}")

    certainty = (
        f'aria-label="Stated {expected["stated"]}, Entailed {expected["entailed"]}, '
        f'Our reading {expected["reading"]}, out of {expected["counted"]}"'
    )
    if certainty not in home_markdown:
        print("ERROR the certainty bar does not match the data", file=sys.stderr)
        return 1
    print(
        f"  ok   certainty bar = {expected['stated']} stated, {expected['entailed']} "
        f"entailed, {expected['reading']} our reading"
    )

    dots_on = home_markdown.count('<i class="on">')
    want_dots = expected["no false statement"] + expected["record silent on stop"] + expected["control never built"]
    if dots_on != want_dots:
        print(f"ERROR {dots_on} filled dots on Home, data says {want_dots}", file=sys.stderr)
        return 1
    print(f"  ok   filled dots across the three cards = {dots_on}")

    rendered = "\n".join(
        str(getattr(element, "value", "")) for element in at.markdown
    ) + "\n".join(str(getattr(element, "body", "")) for element in at.markdown)
    metrics = {m.label: m.value for m in at.metric}

    problems = []

    # The three tiles are metrics, and each should read "N of TOTAL".
    for label, key in (
        ("Said nothing untrue", "no false statement"),
        ("Record silent on who could stop it", "record silent on stop"),
        ("Control never built", "control never built"),
    ):
        shown = metrics.get(label)
        want = f"{expected[key]} of {expected['counted']}"
        if shown != want:
            problems.append(f"tile '{label}' shows {shown!r}, data says {want!r}")
        else:
            print(f"  ok   tile '{label}' = {want}")

    # The counter and the chart title are computed, so they are read back too.
    counter = re.search(r"Showing (\d+) of (\d+) cases\W+(\d+) counted", rendered)
    if not counter:
        problems.append("could not find the case counter in what was rendered")
    else:
        shown, total, shown_counted = (int(g) for g in counter.groups())
        if (total, shown, shown_counted) != (expected["cases"], expected["cases"], expected["counted"]):
            problems.append(
                f"counter says {shown}/{total}, {shown_counted} counted. Data says "
                f"{expected['cases']}/{expected['cases']}, {expected['counted']} counted"
            )
        else:
            print(f"  ok   counter = {shown} of {total}, {shown_counted} counted")

    claim = re.search(r"In (\d+) of (\d+) counted cases, the missing control was not accuracy", rendered)
    if not claim:
        problems.append("could not find the chart's claim title")
    else:
        got, of = (int(g) for g in claim.groups())
        if (got, of) != (expected["missing control not accuracy"], expected["counted"]):
            problems.append(
                f"chart title says {got} of {of}, data says "
                f"{expected['missing control not accuracy']} of {expected['counted']}"
            )
        else:
            print(f"  ok   chart title = {got} of {of}")

    # Severity meters are generated per row, so the total filled bars is a checksum on
    # the whole severity column reaching the page intact.
    filled = sum(block.count('class="f"') for block in
                 [str(getattr(e, "value", "")) for e in at.markdown])
    if filled and filled != expected["filled meter bars"]:
        problems.append(
            f"severity meters have {filled} filled bars, data says {expected['filled meter bars']}"
        )
    elif filled:
        print(f"  ok   severity meters = {filled} filled bars")

    for line in problems:
        print(f"ERROR {line}", file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} displayed number(s) do not match the data.", file=sys.stderr)
        return 1
    print("\nEvery displayed number matches the data.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

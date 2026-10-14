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


def screen_radio(at):
    """The sidebar's screen selector, found by its label.

    These scripts used at.radio[0], which meant "the first radio on the page". Adding
    the public and internal register toggle to Home put a radio ahead of it and every
    screen in every scenario silently became Home.
    """
    for widget in at.radio:
        if widget.label == "Screen":
            return widget
    raise AssertionError("no radio labelled 'Screen' on this page")


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
        # The sensitivity printed on the first Home card. Accuracy is tested last in the
        # rubric, so the card has to carry what the count becomes if it is tested first.
        "accuracy first": len(counted) - sum(
            1 for r in counted if r["said_something_untrue"] == "Yes"
        ),
        "stated": sum(1 for r in counted if r["missing_control_basis"].startswith("Stated")),
        "entailed": sum(1 for r in counted if r["missing_control_basis"].startswith("Entailed")),
        "reading": sum(1 for r in counted if r["missing_control_basis"].startswith("Reading")),
        # Two sentences on two screens describe the same set: Findings says how many
        # primary records the organisation published itself, Limits says how many of
        # those rest on one party's account. They read as a contradiction if either
        # drifts, so both are recomputed here. "reporting" in a label marks a news
        # outlet relaying the account, which is not the organisation publishing it.
        "own publication": sum(
            1 for r in counted
            if "own account" in r["source_1_label"].lower()
            and "reporting" not in r["source_1_label"].lower()
        ),
        "one party only": sum(
            1 for r in counted
            if "own account" in r["source_1_label"].lower()
            and "reporting" not in r["source_1_label"].lower()
            and r["evidence_grade"] == "B"
        ),
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

    # This check has had to chase the card's wording three times. It now anchors on the
    # one fragment that has survived every rewrite, so a reworded card does not silently
    # stop being checked.
    sensitivity = re.search(
        r"it is still (\d+) of (\d+)", home_markdown, re.IGNORECASE
    )
    if not sensitivity:
        problems.append("the first card carries no accuracy-first sensitivity line")
    elif (int(sensitivity.group(1)), int(sensitivity.group(2))) != (
        expected["accuracy first"], expected["counted"]
    ):
        problems.append(
            f"card sensitivity says {sensitivity.group(1)} of {sensitivity.group(2)}, "
            f"data says {expected['accuracy first']} of {expected['counted']}"
        )
    else:
        print(
            f"  ok   card sensitivity, accuracy first = "
            f"{expected['accuracy first']} of {expected['counted']}"
        )

    counter = re.search(r"Showing (\d+) of (\d+) cases", home_markdown)
    if not counter:
        problems.append("could not find the case counter")
    else:
        shown, total = (int(g) for g in counter.groups())
        if (shown, total) != (expected["cases"], expected["cases"]):
            problems.append(f"counter says {shown} of {total}, data says {expected['cases']}")
        else:
            print(f"  ok   counter = {shown} of {total}")

    # Count only inside the case table, and only the summary rows: an open row renders
    # the same pill again inside its Evidence pane, which would double some cases.
    #
    # This check scoped to <table class="cases"> until 13 October 2026, when the rows
    # became <details> elements. The selector matched nothing, filled came out zero, and
    # the guard was written so that zero skipped the check instead of failing it. It went
    # quiet for several releases. A check that can pass by finding nothing is not a check,
    # so a zero is now a failure.
    table = re.search(r'<div class="ctbl">.*</div>', home_markdown, re.S)
    summaries = re.findall(r"<summary>.*?</summary>", table.group(0), re.S) if table else []
    filled = sum(part.count('class="f"') for part in summaries)
    if not filled:
        problems.append(
            "found no severity meters in the case table, so the checksum did not run"
        )
    elif filled != expected["filled meter bars"]:
        problems.append(
            f"severity meters have {filled} filled bars, data says {expected['filled meter bars']}"
        )
    else:
        print(f"  ok   severity meters = {filled} filled bars")

    # The not-accuracy claim moved to the Findings tab, so it is read there.
    findings = AppTest.from_file(str(project_dir / "app.py"), default_timeout=180)
    findings.run()
    screen_radio(findings).set_value("Findings").run()
    if findings.exception:
        problems.append(f"the findings screen raised: {findings.exception[0].value}")
    else:
        text = "\n".join(str(getattr(e, "value", "")) for e in findings.markdown)
        claim = re.search(
            r"If accuracy is checked first, (\d+) of (\d+) still involve no false statement",
            text,
        )
        if not claim:
            problems.append("could not find the accuracy-first claim on Findings")
        else:
            got, of = (int(g) for g in claim.groups())
            if (got, of) != (expected["accuracy first"], expected["counted"]):
                problems.append(
                    f"findings accuracy-first claim says {got} of {of}, data says "
                    f"{expected['accuracy first']} of {expected['counted']}"
                )
            else:
                print(f"  ok   findings accuracy-first claim = {got} of {of}")

        own = re.search(
            r"In (\d+) of the (\d+) counted cases the primary record is the implicated "
            r"organisation's own published account",
            text,
        )
        if not own:
            problems.append("could not find the own-account sentence on Findings")
        elif (int(own.group(1)), int(own.group(2))) != (
            expected["own publication"], expected["counted"]
        ):
            problems.append(
                f"findings own-account sentence says {own.group(1)} of {own.group(2)}, "
                f"data says {expected['own publication']} of {expected['counted']}"
            )
        else:
            print(
                f"  ok   findings own-account sentence = {own.group(1)} of "
                f"{own.group(2)}"
            )
        subset = re.search(
            r"of which (\d+) have no corroboration beyond restatement", text
        )
        if not subset:
            problems.append("the own-account sentence does not name the Limits subset")
        elif int(subset.group(1)) != expected["one party only"]:
            problems.append(
                f"findings subset clause says {subset.group(1)}, data says "
                f"{expected['one party only']}"
            )
        else:
            print(f"  ok   findings subset clause = {subset.group(1)} of the above")

    # Same two numbers again, from the Limits bullet on Method. A reader sees them side
    # by side, so a disagreement between the screens is the failure worth catching.
    method = AppTest.from_file(str(project_dir / "app.py"), default_timeout=180)
    method.run()
    screen_radio(method).set_value("Method").run()
    if method.exception:
        problems.append(f"the method screen raised: {method.exception[0].value}")
    else:
        text = "\n".join(str(getattr(e, "value", "")) for e in method.markdown)
        words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
        bullet = re.search(
            r"These are the (\w+) rows the Findings page points here, out of the (\w+)",
            text,
        )
        got = (
            tuple(words.get(g, g if not g.isdigit() else int(g)) for g in bullet.groups())
            if bullet else None
        )
        if not bullet:
            problems.append("could not find the one-party bullet on Method")
        elif got != (expected["one party only"], expected["own publication"]):
            problems.append(
                f"method one-party bullet says {got[0]} of {got[1]}, "
                f"data says {expected['one party only']} of "
                f"{expected['own publication']}"
            )
        else:
            print(
                f"  ok   method one-party bullet = {got[0]} of "
                f"{got[1]}, agreeing with Findings"
            )

    # The cross-reference count appears on two screens and is a claim about work that
    # was actually done, so it is recomputed from the column rather than trusted.
    cross = sum(1 for r in rows if r["aiid_id"])
    for screen, pattern in (
        ("Findings",
         rf"{cross} of the {len(rows)} cases here are also in the AI Incident Database"),
        ("Method",
         rf"{cross} of the {len(rows)} cases here carry the same event's number"),
    ):
        at_x = AppTest.from_file(str(project_dir / "app.py"), default_timeout=180)
        at_x.run()
        screen_radio(at_x).set_value(screen).run()
        shown = "\n".join(str(getattr(e, "value", "")) for e in at_x.markdown)
        if not re.search(pattern, shown):
            problems.append(
                f"{screen} does not say {cross} of {len(rows)} cases are cross "
                "referenced, which is what the column holds"
            )
        else:
            print(f"  ok   {screen} cross-references = {cross} of {len(rows)}")

    # The four framework views. Each heading names the category with the most cases and
    # prints its count, and the bar chart prints a count per category. Both are
    # recomputed from the case data and from the published lists in frameworks/, so a
    # heading that stops matching its own chart fails here.
    def catalogue(name, key):
        path = project_dir / "frameworks" / name
        with open(path, newline="", encoding="utf-8") as fh:
            return [row[key] for row in csv.DictReader(fh)], list(csv.DictReader(
                open(path, newline="", encoding="utf-8")
            ))

    owasp_order, owasp_rows = catalogue("owasp_agentic_2026.csv", "code")
    owasp_names = {r["code"]: r["name"] for r in owasp_rows}
    rmf_order, _ = catalogue("nist_ai_rmf_1.0.csv", "subcategory")
    mon_order, _ = catalogue("nist_ai_800_4_categories.csv", "category")

    def tally(field, over=None):
        """Primary mappings only, which is the first value in the list.

        This counted every value until the mapping rule landed, so a case with two
        articles was counted under both and the bars added to more cases than exist.
        """
        found = {}
        for r in (counted if over is None else over):
            values = [v.strip() for v in r[field].split(",") if v.strip()]
            if values:
                found[values[0]] = found.get(values[0], 0) + 1
        return found

    # A case that is not counted still appears in its group, marked. A case with two
    # values appears in two groups and is marked in both, so the marks are counted the
    # same way the bars are: once per mapping. Under the primary-mapping rule each case
    # carries one value per lens and this becomes the number of uncounted cases.
    shelved = [r for r in rows if r["evidence_grade"] not in {"A", "B"}]
    lens_field = {
        "owasp": "owasp_code", "rmf": "nist_ai_rmf",
        "articles": "eu_ai_act", "monitoring": "nist_800_4_category",
    }

    def top_of(found, order):
        """The app walks its row order and keeps the first strict maximum. Same here."""
        keys = order if order else sorted(found, key=lambda k: (-found[k], k))
        keys = [k for k in keys if k in found] or list(keys)
        best = keys[0]
        for key in keys:
            if found.get(key, 0) > found.get(best, 0):
                best = key
        return best, found.get(best, 0)

    owasp = tally("owasp_code")
    rmf = tally("nist_ai_rmf")
    articles = tally("eu_ai_act")
    monitoring = tally("nist_800_4_category")
    lens_checks = [
        ("owasp", *top_of(owasp, owasp_order), owasp,
         lambda top, n: rf"{n} of {len(counted)} cases fall under {top}: "
                        rf"{re.escape(owasp_names[top])}\."),
        ("rmf", *top_of(rmf, rmf_order), rmf,
         lambda top, n: rf"{n} of {len(counted)} cases point to {re.escape(top)}\."),
        ("articles", *top_of(articles, None), articles,
         lambda top, n: rf"{re.escape(top)} is the closest provision in {n} of "
                        rf"{len(counted)} cases\."),
        ("monitoring", *top_of(monitoring, mon_order), monitoring,
         lambda top, n: rf"{n} of {len(counted)} would have been caught by {top} "
                        r"monitoring\."),
    ]
    for slug, top, n, found, pattern in lens_checks:
        at_lens = AppTest.from_file(str(project_dir / "app.py"), default_timeout=180)
        at_lens.query_params["screen"] = "Findings"
        at_lens.query_params["lens"] = slug
        at_lens.run()
        if at_lens.exception:
            problems.append(f"?lens={slug} raised: {at_lens.exception[0].value}")
            continue
        shown = "\n".join(str(getattr(e, "value", "")) for e in at_lens.markdown)
        if not re.search(pattern(top, n), shown):
            problems.append(
                f"?lens={slug} heading does not state {top} in {n} of {len(counted)} "
                "cases, which is what the data says"
            )
            continue
        chart = re.search(r'<div class="srows lens">.*?</div></div>', shown, re.S)
        printed = sum(
            int(x) for x in re.findall(
                r'<span class="scount">(\d+)', chart.group(0) if chart else ""
            )
        )
        if printed != sum(found.values()):
            problems.append(
                f"?lens={slug} bars print {printed} cases in total, data says "
                f"{sum(found.values())}"
            )
            continue
        # The group labels under the chart have to be on the same basis as the bars
        # above it. They counted every row in the group, including the single-source
        # one, so a group read one higher than its own bar.
        heads = re.findall(
            r'<div class="ghead lens">.*?<span class="gcount">(\d+) cases?(.*?)</span>',
            shown,
        )
        labelled = sum(int(h[0]) for h in heads)
        not_counted = sum(
            int(x) for h in heads for x in re.findall(r"\+(\d+) not counted", h[1])
        )
        uncounted_rows = sum(tally(lens_field[slug], over=shelved).values())
        if labelled != printed:
            problems.append(
                f"?lens={slug} group labels total {labelled}, the bars above them "
                f"total {printed}"
            )
            continue
        if not_counted != uncounted_rows:
            problems.append(
                f"?lens={slug} marks {not_counted} mappings as not counted, the "
                f"data has {uncounted_rows}"
            )
            continue
        print(
            f"  ok   ?lens={slug} heading = {top} in {n} of {len(counted)}, bars and "
            f"group labels both {printed}, {not_counted} marked not counted"
        )

    for line in problems:
        print(f"ERROR {line}", file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} displayed number(s) do not match the data.", file=sys.stderr)
        return 1
    print("\nEvery displayed number matches the data.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

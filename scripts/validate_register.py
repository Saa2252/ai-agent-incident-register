#!/usr/bin/env python3
"""Validate data/incidents.csv against the register's own rules.

Usage:
    python3 scripts/validate_register.py [project_dir]

project_dir defaults to the current directory. Pure stdlib by design, so it runs in
CI without a data-science environment.

The checks are the published method turned into code. Every claim the app makes on
screen has a rule here that would fail if the data stopped supporting it:

  Evidence       A needs a primary record and a second source. B needs two
                 independent sources on different sites. C gets one source and is
                 excluded from every count the app displays.
  Vocabulary     Severity, harm class, monitoring category and failure pattern come
                 from fixed lists, so the counts mean the same thing in every row.
  Clauses        Each row carries a NIST AI RMF subcategory, an ISO/IEC 42001 Annex A
                 control and an EU AI Act article, in a shape that can be looked up.
  Traceability   Every rule in the watch list points at incidents that exist.
  Voice          No em dashes, no semicolons, no double hyphens. The register is meant
                 to read as though a person wrote it, because a person did.

Exit code 0 means valid, warnings allowed. Exit code 1 means errors were found.
"""

import csv
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

FIELDS = [
    "id", "title", "event_date", "deployer", "sector", "agent_type",
    "what_happened", "incident_or_hazard", "harm_type", "severity",
    "authority", "human_approval",
    "failure_pattern", "owasp_code", "control_class", "missing_control",
    "test_before_launch", "test_pass_mark",
    "signal_after_launch", "nist_800_4_category", "owner_role",
    "nist_ai_rmf", "iso_42001", "eu_ai_act",
    "what_changed_after", "disputed",
    "evidence_grade", "source_1_label", "source_1_url",
    "source_2_label", "source_2_url", "date_checked",
]

# source_2_label and source_2_url may be blank, and only on a grade C row. Everything
# else must carry a value.
OPTIONAL_FIELDS = {"source_2_label", "source_2_url"}

# ---- fixed vocabularies ----
# These exist so that a count means the same thing in every row. If a new row needs a
# value that is not here, the choice is to argue it into the list or to pick an
# existing one, never to invent a value quietly in the CSV.

KINDS = {"Incident", "Hazard"}

# Four levels, defined on the Method page in terms of what happened to people, not in
# terms of how it felt to read about.
SEVERITIES = {"Negligible", "Moderate", "Serious", "Severe"}

# What the missing control governed. This is the field the headline finding counts, so
# a row gets exactly one, chosen by the rubric on the Method page.
CONTROL_CLASSES = {
    "Accuracy": "The agent said something that was not true.",
    "Authority": "The agent was allowed to do more than it should have been able to do.",
    "Boundary": "The agent acted on instructions that came from content, not from its operator.",
    "Oversight": "No person was positioned to catch it, stop it, or verify the claim it ran on.",
    "Vendor": "The failure arrived through a third party holding access to the organisation.",
}

# NIST AI 800-4, Challenges to the Monitoring of Deployed AI Systems, March 2026.
NIST_800_4_CATEGORIES = {
    "Functionality", "Operational", "Human factors",
    "Security", "Compliance", "Large-scale impacts",
}

# OWASP Top 10 for Agentic Applications 2026, published 9 December 2025.
OWASP_CODES = {
    "ASI01": "Agent Goal Hijack",
    "ASI02": "Tool Misuse and Exploitation",
    "ASI03": "Identity and Privilege Abuse",
    "ASI04": "Agentic Supply Chain Vulnerabilities",
    "ASI05": "Unexpected Code Execution",
    "ASI06": "Memory and Context Poisoning",
    "ASI07": "Insecure Inter-Agent Communication",
    "ASI08": "Cascading Failures",
    "ASI09": "Human-Agent Trust Exploitation",
    "ASI10": "Rogue Agents",
}

# What the agent was able to do, not what it was supposed to do.
AUTHORITIES = {"Read", "Write", "Delete", "Pay", "Promise"}

# "Yes, bypassed" is its own state because it is the most common one. A gate that
# existed on paper and did not hold is not the same as no gate, and it is not the same
# as a gate that worked.
APPROVAL_STATES = {"Yes", "No", "Unknown", "Yes, bypassed"}

GRADES = {"A", "B", "C"}
COUNTED_GRADES = {"A", "B"}  # the only grades any displayed number may include

YES_NO = {"Yes", "No"}

# A grade A row needs a record made by the body that decided the matter, not a report
# about it. These words in the source label are how the validator recognises one.
PRIMARY_MARKERS = (
    "tribunal", "court", "attorney general", "regulator", "press release",
    "security response center", "cve-", "threat intelligence", "trust portal",
    "assurance of voluntary compliance", "judgment", "decision", "monitor",
)

# ---- clause shapes ----
# These check the shape of a reference, not whether the clause says what the row
# claims. That check is a human reading the official text, and the Method page says so.
NIST_RMF_PATTERN = re.compile(r"^(GOVERN|MAP|MEASURE|MANAGE) \d+\.\d+$")
ISO_PATTERN = re.compile(r"^A\.\d+(\.\d+){1,2}$")
EU_PATTERN = re.compile(r"^Article \d+(\(\d+\))?$")

ID_PATTERN = re.compile(r"^AIR-\d{3}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Punctuation that reads as machine written. Checked on every field so nobody has to
# remember the rule by hand when adding a row later.
AI_TELLS = {"—": "em dash", ";": "semicolon", "--": "double hyphen"}

MIN_SENTENCES = 2
MAX_SENTENCES = 5


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, where, message):
        self.errors.append(f"{where}: {message}")

    def warn(self, where, message):
        self.warnings.append(f"{where}: {message}")


def parse_date(value):
    if not DATE_PATTERN.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def sentence_count(text):
    return len([part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part])


def check_style(report, where, row):
    for field, value in row.items():
        if field.endswith("_url"):
            continue
        for tell, name in AI_TELLS.items():
            if tell in value:
                report.error(f"{where}.{field}", f"contains a {name}, which the voice rule forbids")


def check_clauses(report, where, row):
    for field, pattern, shape in (
        ("nist_ai_rmf", NIST_RMF_PATTERN, "FUNCTION N.N, for example MANAGE 4.1"),
        ("iso_42001", ISO_PATTERN, "A.N.N or A.N.N.N, for example A.6.2.6"),
        ("eu_ai_act", EU_PATTERN, "Article N or Article N(N), for example Article 26"),
    ):
        refs = [part.strip() for part in row[field].split(",") if part.strip()]
        if not refs:
            report.error(f"{where}.{field}", "no clause reference given")
        for ref in refs:
            if not pattern.match(ref):
                report.error(f"{where}.{field}", f"'{ref}' is not shaped like {shape}")


def check_evidence(report, where, row):
    grade = row["evidence_grade"]
    if grade not in GRADES:
        report.error(f"{where}.evidence_grade", f"'{grade}' is not one of {sorted(GRADES)}")
        return

    sources = []
    for index in (1, 2):
        label = row[f"source_{index}_label"].strip()
        url = row[f"source_{index}_url"].strip()
        if label and not url:
            report.error(f"{where}.source_{index}", "has a label but no link")
        if url and not label:
            report.error(f"{where}.source_{index}", "has a link but no label")
        if label and url:
            sources.append((label, url))

    for label, url in sources:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            report.error(f"{where}.sources", f"'{url}' is not an https link with a host")

    hosts = {urlparse(url).netloc.lower().removeprefix("www.") for _, url in sources}

    if grade == "A":
        if len(sources) < 2:
            report.error(f"{where}.evidence_grade", "grade A needs a primary record and a second source")
        label = sources[0][0].lower() if sources else ""
        if not any(marker in label for marker in PRIMARY_MARKERS):
            report.error(
                f"{where}.source_1_label",
                "grade A needs source 1 to name a primary record, such as a ruling, a "
                "regulator notice, a vendor advisory or a threat intelligence report",
            )
    elif grade == "B":
        if len(sources) < 2:
            report.error(f"{where}.evidence_grade", "grade B needs two independent sources")
        elif len(hosts) < 2:
            report.error(f"{where}.evidence_grade", "grade B needs sources on two different sites")
    elif grade == "C":
        if len(sources) != 1:
            report.error(
                f"{where}.evidence_grade",
                "grade C means a single source. Two sources on different sites make it a B",
            )
        report.warn(
            where,
            "grade C. This row must be excluded from every count the app displays and "
            "labelled as single source on its card",
        )


def validate_rows(report, rows, today):
    seen = set()
    for index, row in enumerate(rows, start=1):
        where = row.get("id") or f"row {index}"

        for field in FIELDS:
            if field in OPTIONAL_FIELDS:
                continue
            if not row.get(field, "").strip():
                report.error(f"{where}.{field}", "is blank")

        if not ID_PATTERN.match(row["id"]):
            report.error(where, "id must look like AIR-001")
        if row["id"] in seen:
            report.error(where, "duplicate id")
        seen.add(row["id"])

        event = parse_date(row["event_date"])
        checked = parse_date(row["date_checked"])
        if event is None:
            report.error(f"{where}.event_date", "is not an ISO date")
        if checked is None:
            report.error(f"{where}.date_checked", "is not an ISO date")
        if event and checked and event > checked:
            report.error(where, "event_date is later than date_checked")
        if checked and checked > today:
            report.error(f"{where}.date_checked", "is in the future")
        if checked and (today - checked).days > 180:
            report.warn(where, f"sources were last checked {(today - checked).days} days ago")

        if row["incident_or_hazard"] not in KINDS:
            report.error(f"{where}.incident_or_hazard", f"must be one of {sorted(KINDS)}")
        if row["severity"] not in SEVERITIES:
            report.error(f"{where}.severity", f"'{row['severity']}' is not one of {sorted(SEVERITIES)}")
        if row["control_class"] not in CONTROL_CLASSES:
            report.error(f"{where}.control_class", f"'{row['control_class']}' is not one of {sorted(CONTROL_CLASSES)}")
        if row["nist_800_4_category"] not in NIST_800_4_CATEGORIES:
            report.error(f"{where}.nist_800_4_category", f"'{row['nist_800_4_category']}' is not a NIST AI 800-4 category")
        if row["owasp_code"] not in OWASP_CODES:
            report.error(f"{where}.owasp_code", f"'{row['owasp_code']}' is not an OWASP Agentic Top 10 2026 code")
        if row["human_approval"] not in APPROVAL_STATES:
            report.error(f"{where}.human_approval", f"'{row['human_approval']}' is not one of {sorted(APPROVAL_STATES)}")
        if row["disputed"] not in YES_NO:
            report.error(f"{where}.disputed", "must be Yes or No")

        granted = [part.strip() for part in row["authority"].split("|") if part.strip()]
        if not granted:
            report.error(f"{where}.authority", "no authority recorded")
        for item in granted:
            if item not in AUTHORITIES:
                report.error(f"{where}.authority", f"'{item}' is not one of {sorted(AUTHORITIES)}")

        # A hazard is a near miss, so it cannot also claim that harm occurred. The OECD
        # definitions are the point of the field and the register has to honour them.
        if row["incident_or_hazard"] == "Hazard" and row["severity"] == "Severe":
            report.warn(where, "a hazard graded Severe. Check this is potential harm, not harm that occurred")

        # The register's own argument is that a deletion by an agent with no approval is
        # an authority failure, so the data has to agree with the argument.
        if "Delete" in granted and row["human_approval"] == "No" and row["control_class"] != "Authority":
            report.warn(where, "delete rights with no approval but control_class is not Authority. Check the rubric")

        if row["disputed"] == "Yes" and "statement" not in row["what_changed_after"].lower() \
                and "said" not in row["what_changed_after"].lower():
            report.error(where, "marked disputed but what_changed_after does not carry the deployer's position")

        count = sentence_count(row["what_happened"])
        if not MIN_SENTENCES <= count <= MAX_SENTENCES:
            report.error(f"{where}.what_happened", f"{count} sentences, the rule is {MIN_SENTENCES} to {MAX_SENTENCES}")

        for field in ("missing_control", "test_before_launch", "test_pass_mark", "signal_after_launch"):
            if sentence_count(row[field]) > 2:
                report.warn(f"{where}.{field}", "more than two sentences. Keep the coding fields short")

        check_clauses(report, where, row)
        check_evidence(report, where, row)
        check_style(report, where, row)


def validate_rules(report, project_dir, register_ids):
    path = project_dir / "rules" / "watchlist_rules.json"
    if not path.exists():
        report.error("rules", "watchlist_rules.json is missing")
        return
    with open(path, encoding="utf-8") as fh:
        rules = json.load(fh)

    question_ids = {question["id"] for question in rules["questions"]}
    if len(question_ids) != 6:
        report.error("rules", f"expected 6 questions, found {len(question_ids)}")

    fired = set()
    for rule in rules["rules"]:
        where = f"rules.{rule['id']}"
        trigger = rule["trigger"]
        if trigger != "always":
            question_id, _, answer = trigger.partition(":")
            if question_id not in question_ids:
                report.error(where, f"triggers on unknown question {question_id}")
            if answer not in {"yes", "no"}:
                report.error(where, f"trigger answer '{answer}' must be yes or no")
            fired.add(question_id)
        if rule["nist_800_4_category"] not in NIST_800_4_CATEGORIES:
            report.error(where, f"'{rule['nist_800_4_category']}' is not a NIST AI 800-4 category")
        if rule["owasp_code"] not in OWASP_CODES:
            report.error(where, f"'{rule['owasp_code']}' is not an OWASP Agentic Top 10 2026 code")
        for incident in rule["incident_ids"]:
            if incident not in register_ids:
                report.error(where, f"points at {incident}, which is not in the register")
        for tell, name in AI_TELLS.items():
            for field in ("title", "test", "pass_mark", "signal", "why"):
                if tell in rule[field]:
                    report.error(f"{where}.{field}", f"contains a {name}, which the voice rule forbids")

    # Every question has to change the output, otherwise it is on the form for show.
    for question_id in sorted(question_ids - fired):
        report.error("rules", f"{question_id} is asked but triggers no rule")

    # Every row in the register has to be used by at least one rule, otherwise the
    # register is carrying a case that teaches nothing.
    used = {incident for rule in rules["rules"] for incident in rule["incident_ids"]}
    for incident in sorted(register_ids - used):
        report.warn("rules", f"{incident} is in the register but no watch-list rule cites it")


def main(argv):
    project_dir = Path(argv[1] if len(argv) > 1 else ".").resolve()
    csv_path = project_dir / "data" / "incidents.csv"
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found", file=sys.stderr)
        return 1

    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        rows = list(reader)

    report = Report()
    if header != FIELDS:
        missing = [f for f in FIELDS if f not in header]
        extra = [f for f in header if f not in FIELDS]
        report.error("header", f"does not match the schema. Missing {missing}. Unexpected {extra}")
        print("ERROR: header mismatch, stopping before row checks", file=sys.stderr)
        for line in report.errors:
            print(f"  {line}", file=sys.stderr)
        return 1

    today = date.today()
    validate_rows(report, rows, today)
    validate_rules(report, project_dir, {row["id"] for row in rows})

    counted = [row for row in rows if row["evidence_grade"] in COUNTED_GRADES]
    print(f"Register: {len(rows)} rows, {len(counted)} counted (grades A and B).")
    by_class = {}
    for row in counted:
        by_class[row["control_class"]] = by_class.get(row["control_class"], 0) + 1
    for name, count in sorted(by_class.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {name}: {count}")

    for line in report.warnings:
        print(f"WARNING {line}")
    for line in report.errors:
        print(f"ERROR {line}", file=sys.stderr)

    if report.errors:
        print(f"\n{len(report.errors)} error(s). Register is not valid.", file=sys.stderr)
        return 1
    print(f"\nValid. {len(report.warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

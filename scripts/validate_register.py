#!/usr/bin/env python3
"""Validate data/incidents.csv against the register's own rules.

Usage:
    python3 scripts/validate_register.py [project_dir]

project_dir defaults to the current directory. Pure stdlib by design, so it runs in
CI without a data-science environment.

The checks are the published method turned into code. Every claim the app makes on
screen has a rule here that would fail if the data stopped supporting it:

  Evidence       A needs a primary record and a second source. B needs two
                 independent sources on different sites. C gets one source, appears in
                 descriptive counts, and is excluded from every analytical one.
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
    "id", "title", "event_date", "deployer", "sector", "agent_type", "what_happened",
    "why_in_register", "incident_or_hazard", "harm_type", "harm_borne_by",
    "could_have_prevented", "harm_bearer_had_control", "eu_serious_incident",
    "eu_closest_limb", "eu_basis", "eu_basis_type", "authority", "human_approval",
    "deploy_evidence_seen", "deploy_evidence_source", "deploy_stop_authority",
    "deploy_stop_authority_source", "deploy_review_date", "deploy_review_date_source",
    "directed_by", "directed_by_basis",
    "failure_pattern", "owasp_code", "owasp_code_basis", "said_something_untrue",
    "control_class", "secondary_class", "control_maturity", "missing_control",
    "missing_control_basis", "test_before_launch", "test_pass_mark",
    "signal_after_launch", "nist_800_4_category", "control_owner_role",
    "accountable_role", "nist_ai_rmf", "iso_42001", "eu_ai_act",
    "nist_ai_rmf_basis", "eu_ai_act_basis", "what_changed_after",
    "disputed", "aftermath_status", "aftermath_source_url", "inclusion",
    "evidence_grade", "source_1_label", "source_1_url", "source_2_label",
    "source_2_url", "date_checked", "facts_changed_at", "derived_rechecked_at",
    "archive_urls", "aiid_id", "aiid_match_basis", "aiid_checked_on",
    "evidence_note", "missing_control_note",
]

# source_2_label and source_2_url may be blank, and only on a grade C row. Everything
# else must carry a value.
OPTIONAL_FIELDS = {
    "source_2_label", "source_2_url",
    # A deployment source is empty exactly when its answer is "Not disclosed", which is
    # checked by rule below rather than by presence.
    "deploy_evidence_source", "deploy_stop_authority_source", "deploy_review_date_source",
    # Blank where the case has one clean reading and no genuine second one.
    "secondary_class",
    # Filled by scripts/archive_sources.py. A row may legitimately have no snapshot yet
    # if the Wayback Machine refused the capture, which is reported as a warning.
    "archive_urls",
    # The AI Incident Database's own number for the same event, where one exists. A
    # cross-reference for a reader, never a source: incidentdatabase.ai is on the
    # aggregator list above and is how cases are found, not evidence that they happened.
    "aiid_id",
    # The reasoning that used to sit in the narrative. Most rows have none, because most
    # rows raise no question about their grade or their class.
    "evidence_note", "missing_control_note",
}

# ---- fixed vocabularies ----
# These exist so that a count means the same thing in every row. If a new row needs a
# value that is not here, the choice is to argue it into the list or to pick an
# existing one, never to invent a value quietly in the CSV.

KINDS = {"Incident", "Hazard"}

# Four levels, defined on the Method page in terms of what happened to people, not in
# terms of how it felt to read about.
# Severity lives in data/case_harm_ratings.csv on MIT's framework. The register's own
# four-level scale was retired in the same change, not converted.
EU_SERIOUS = {"Meets", "Does not meet", "Not determinable from the record"}

# Whether a case was admitted under the dated inclusion rule or predates it. A rule
# written after the fact cannot be claimed to have governed the cases that came first.
INCLUSION_STATES = {"Passed the inclusion rule", "Included before the inclusion rule"}
EU_LIMBS = {"a", "b", "c", "d"}

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


# OWASP Top 10 for Agentic Applications 2026, published 9 December 2025.
# Allowed values come from frameworks/*.csv, copied from the source with a URL, a
# retrieval date and a status saying whether the framework owner's own publication was
# reachable. That makes "verified against the framework" something the build enforces
# rather than something the page asserts.
def _load_framework(name):
    path = Path(__file__).parent.parent / "frameworks" / name
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {row["code"]: row for row in csv.DictReader(fh)}


def _load_framework_by(name, key):
    path = Path(__file__).parent.parent / "frameworks" / name
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {row[key]: row for row in csv.DictReader(fh)}


# Added 14 October 2026. These were shape checks before: anything matching "FUNCTION N.N"
# or "Article N" passed, including a subcategory or an article that does not exist. The
# values are now checked against the published lists, the same way OWASP codes are.
NIST_RMF_ROWS = _load_framework_by("nist_ai_rmf_1.0.csv", "subcategory")
EU_ARTICLE_ROWS = _load_framework_by("eu_ai_act_articles.csv", "article")
NIST_800_4_ROWS = _load_framework_by("nist_ai_800_4_categories.csv", "category")

NIST_800_4_CATEGORIES = set(NIST_800_4_ROWS) or {
    "Functionality", "Operational", "Human factors",
    "Security", "Compliance", "Large-scale impacts",
}

OWASP_ROWS = _load_framework("owasp_agentic_2026.csv")
OWASP_CODES = {code: row["name"] for code, row in OWASP_ROWS.items()}
OWASP_STATUS = {code: row["status"] for code, row in OWASP_ROWS.items()}

# How a framework value was arrived at. Stated means the framework's own publication
# applied it to this case. Our reading means this register applied it.
FRAMEWORK_BASIS = {"Stated", "Our reading"}

# What the agent was able to do, not what it was supposed to do.
AUTHORITIES = {"Read", "Write", "Delete", "Pay", "Promise"}

# "Yes, bypassed" is its own state because it is the most common one. A gate that
# existed on paper and did not hold is not the same as no gate, and it is not the same
# as a gate that worked.
APPROVAL_STATES = {"Yes", "No", "Unknown", "Yes, bypassed"}

# Recorded independently of control_class, so the rubric's ordering can be measured
# rather than argued about. A row where the agent stated nothing untrue cannot become an
# accuracy failure under any ordering of the rubric.
UNTRUE_STATES = {"Yes", "No"}

# How completely the ending is on the record. An audit of endings in v0.9.4 found that
# several rows stopped at the dramatic moment: the failure was news, the recovery was a
# postmortem nobody aggregated. Recording this makes the bias countable rather than
# merely confessed, and forces a row to say when it does not know how the story ended.
AFTERMATH_STATES = {"Documented", "Partial", "Undocumented"}

# What state the missing control was actually in. These are four different findings and
# collapsing them loses the most useful one. AIR-004 is why the field exists: a two
# person approval gate that was implemented, wired in, and not operating. "Operating" is
# in the vocabulary only so the validator can reject it, because a control that was
# operating is not a missing control.
CONTROL_MATURITY = {"Absent", "Designed", "Implemented", "Bypassable", "Unknown"}

# Who pointed the agent at the thing that caused harm. Added 12 October 2026, because a
# register that mixes attacker misuse with a deployment's own behaviour cannot say which
# of the two its findings are about. "No one" is the common case and is not a shrug: it
# means the agent did it in ordinary use, with nobody steering it.
DIRECTED_BY = {"Deployer", "Attacker", "No one"}
# "Operating" is deliberately absent: a control that was operating is not a missing
# control. "Bypassable" was added on 11 October 2026 for AIR-015, where the gate was
# built and wired in and the caller could switch it off with a documented flag. That
# is a different failure from a gate that engaged and did not hold.
HARM_CONTROL_STATES = {"Yes", "No", "Partly"}

# Whether accountability was locatable when the agent went live. These ask whether the
# thing existed and could be found, not whether it worked. Whether a control held is
# carried by control_maturity, and the two are kept apart on purpose: a review date that
# existed and was ignored is a different finding from one that was never set.
#
# "Not disclosed" is the default and the correct answer whenever the record is silent.
# Both "Yes" and "No" require a source, because "No" is a claim that something was
# absent, not a note that nothing turned up. Coding "No" from a failed search would mean
# accusing a deployer of having had no stop authority on no evidence, which is the exact
# drift this register has already had to correct twice.
# How the register knows the control was missing. Only missing_control carries this.
# The test and signal columns are engineering recommendations rather than claims about
# the company, and marking them would be hedging the wrong thing.
#
# Published as a distribution rather than as a disclaimer, because the useful fact is
# how few of the rows rest on the register's own judgement.
MISSING_CONTROL_TIERS = {
    "Stated": "The deployer, a regulator or a ruling said it.",
    "Entailed": "It follows from the record. A control added afterwards is evidence of its prior absence.",
    "Reading": "Neither. This is the register's own judgement, labelled as such.",
}

DEPLOY_STATES = {"Yes", "No", "Not disclosed"}
DEPLOY_PAIRS = (
    ("deploy_evidence_seen", "deploy_evidence_source"),
    ("deploy_stop_authority", "deploy_stop_authority_source"),
    ("deploy_review_date", "deploy_review_date_source"),
)

# Aggregators are how cases are found. They are never the evidence for one. An index of
# other people's reporting is weaker than the reporting, and citing the index hides which
# report the claim actually rests on. This rule was written in version 0.9.2 and the
# first audit under it was not systematic: it caught one violation by luck and missed a
# second that the same commit had introduced. Hence the list rather than the intention.
AGGREGATOR_HOSTS = {
    "incidentdatabase.ai",
    "oecd.ai",
    "aiaaic.org",
    "icd-ai.org",
    "en.wikipedia.org",
    "grokipedia.com",
}

GRADES = {"A", "B", "C"}
COUNTED_GRADES = {"A", "B"}  # the only grades any displayed number may include

YES_NO = {"Yes", "No"}

# A grade A row needs a record made by the body that decided the matter, not a report
# about it. These words in the source label are how the validator recognises one.
PRIMARY_MARKERS = (
    "tribunal", "court", "attorney general", "regulator", "press release",
    "security response center", "cve-", "threat intelligence", "trust portal",
    "assurance of voluntary compliance", "judgment", "decision",
    "postmortem", "advisory", "own account",
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


NONE_CLOSEST = re.compile(r"^None \(closest: Article \d+\)$")

NOT_APPLICABLE = "Not applicable"

# The EU AI Act ordering published on the Method page. Specific before general, and the
# first value in a row's list is its primary mapping. This is checked rather than
# trusted, because the ordering is the whole claim: without it the mapping is one
# person's pick and the bar on the Findings page is that pick counted up.
EU_GROUPS = (
    ("Article 14", "Article 15", "Article 9", "Article 10"),
    ("Article 16", "Article 26"),
    ("Article 50",),
    ("Article 53", "Article 55"),
    ("Article 72", "Article 73"),
)
EU_RANK = {
    article: (group, position)
    for group, articles in enumerate(EU_GROUPS)
    for position, article in enumerate(articles)
}


def check_aiid(report, where, row):
    """The cross-reference is a pointer for a reader, never a source.

    Every row says whether the AI Incident Database holds the same event and when that
    was last checked, including the rows where it holds nothing. A blank basis would
    leave "no number here" and "nobody looked" indistinguishable.
    """
    if row["aiid_id"] and not row["aiid_id"].isdigit():
        report.error(f"{where}.aiid_id", "must be the database's incident number")
    if not row["aiid_match_basis"]:
        report.error(
            f"{where}.aiid_match_basis",
            "every row says why it does or does not match, including the rows with no "
            "match",
        )
    if not DATE_PATTERN.match(row["aiid_checked_on"] or ""):
        report.error(f"{where}.aiid_checked_on", "needs the date the match was checked")


def check_eu_order(report, where, row):
    """The first article in the list has to be the one the rule puts first."""
    values = [v.strip() for v in row["eu_ai_act"].split(",") if v.strip()]
    if not values or NONE_CLOSEST.match(values[0]):
        return
    unknown = [v for v in values if v not in EU_RANK]
    if unknown:
        report.error(
            f"{where}.eu_ai_act",
            f"{', '.join(unknown)} is not in the published ordering, so the rule "
            "cannot say whether it is the primary mapping",
        )
        return
    best = min(EU_RANK[v] for v in values)
    if EU_RANK[values[0]] != best:
        should = [v for v in values if EU_RANK[v] == best][0]
        report.error(
            f"{where}.eu_ai_act",
            f"{values[0]} is listed first but the rule makes {should} the primary",
        )


def check_clauses(report, where, row):
    """Clause references must exist, not merely look right.

    ISO/IEC 42001 is checked for shape only and is not shown on any page. The standard
    is paywalled, so its Annex A numbers have never been read against the text.
    """
    for field, known, shape, name in (
        ("nist_ai_rmf", set(NIST_RMF_ROWS), "FUNCTION N.N, for example MANAGE 4.1",
         "frameworks/nist_ai_rmf_1.0.csv"),
        ("eu_ai_act", set(EU_ARTICLE_ROWS), "Article N, for example Article 26",
         "frameworks/eu_ai_act_articles.csv"),
    ):
        refs = [part.strip() for part in row[field].split(",") if part.strip()]
        if not refs:
            report.error(f"{where}.{field}", "no clause reference given")
        for ref in refs:
            # "None (closest: Article N)" says no provision addresses the missing
            # safeguard, which is a real answer and not a gap in the coding.
            if field == "eu_ai_act" and NONE_CLOSEST.match(ref):
                inner = "Article " + ref.split("Article ")[1].rstrip(")")
                if known and inner not in known:
                    report.error(f"{where}.{field}", f"'{inner}' is not in {name}")
                continue
            if known and ref not in known:
                report.error(
                    f"{where}.{field}",
                    f"'{ref}' is not in {name}. Add it from the published list, with its "
                    "source and retrieval date, before using it",
                )
            elif not known and not re.match(r"^(GOVERN|MAP|MEASURE|MANAGE) \d+\.\d+$|^Article \d+", ref):
                report.error(f"{where}.{field}", f"'{ref}' is not shaped like {shape}")

    refs = [part.strip() for part in row["iso_42001"].split(",") if part.strip()]
    for ref in refs:
        if not ISO_PATTERN.match(ref):
            report.error(f"{where}.iso_42001", f"'{ref}' is not shaped like A.N.N")

    for field in ("nist_ai_rmf_basis", "eu_ai_act_basis"):
        if row[field] not in FRAMEWORK_BASIS:
            report.error(f"{where}.{field}", f"must be one of {sorted(FRAMEWORK_BASIS)}")


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

    if not row.get("archive_urls", "").strip():
        report.warn(
            where,
            "no archived snapshot. Run scripts/archive_sources.py. A live link is not a "
            "durable one, and the rows most likely to rot are the news reports",
        )

    for label, url in sources:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            report.error(f"{where}.sources", f"'{url}' is not an https link with a host")
        host = parsed.netloc.lower().removeprefix("www.")
        if host in AGGREGATOR_HOSTS:
            report.error(
                f"{where}.sources",
                f"'{host}' is an aggregator. Use it to find the case, then cite the report "
                "it points at. An index of other people's reporting is not evidence",
            )

    hosts = {urlparse(url).netloc.lower().removeprefix("www.") for _, url in sources}

    if grade == "A":
        if len(sources) < 2:
            report.error(
                f"{where}.evidence_grade",
                "grade A needs a primary record and an independent second source",
            )
        label = sources[0][0].lower() if sources else ""
        if not any(marker in label for marker in PRIMARY_MARKERS):
            report.error(
                f"{where}.source_1_label",
                "grade A needs source 1 to name a primary record, such as a ruling, a "
                "regulator notice, a vendor advisory or a threat intelligence report",
            )
        # Added 11 October 2026. Grade A used to ask only for "a second source", which a
        # vendor blog restating the primary record satisfies while corroborating nothing.
        # Independence itself cannot be checked by code, so this enforces the part that
        # can be (a different host) and the Method page carries the part that cannot.
        if len(hosts) < len(sources):
            report.error(
                f"{where}.sources",
                "grade A needs its second source on a different host from the primary "
                "record. A restatement on the same site corroborates nothing",
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
            "grade C. This row appears in descriptive counts of the register's "
            "composition, is excluded from every analytical count, and must be labelled "
            "as single source on its card",
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
        second = row["secondary_class"].strip()
        if second:
            if second not in CONTROL_CLASSES:
                report.error(f"{where}.secondary_class", f"'{second}' is not one of {sorted(CONTROL_CLASSES)}")
            elif second == row["control_class"]:
                report.error(
                    where,
                    "secondary_class repeats control_class. It exists to record the "
                    "reading the ordered rubric discarded, not to restate the one it kept",
                )
        if row["control_class"] not in CONTROL_CLASSES:
            report.error(f"{where}.control_class", f"'{row['control_class']}' is not one of {sorted(CONTROL_CLASSES)}")
        if row["nist_800_4_category"] not in NIST_800_4_CATEGORIES:
            report.error(f"{where}.nist_800_4_category", f"'{row['nist_800_4_category']}' is not a NIST AI 800-4 category")
        # Added 14 October 2026 with the mapping rule. A case with no security path has
        # no OWASP pattern, and picking the closest-looking code to avoid a blank was
        # how five accuracy rows came to be labelled Human-Agent Trust Exploitation.
        if row["owasp_code"] == NOT_APPLICABLE:
            pass
        elif row["owasp_code"] not in OWASP_CODES:
            report.error(
                f"{where}.owasp_code",
                f"'{row['owasp_code']}' is not in frameworks/owasp_agentic_2026.csv",
            )
        elif OWASP_STATUS.get(row["owasp_code"]) != "confirmed":
            report.warn(
                where,
                f"{row['owasp_code']} is not marked confirmed in "
                "frameworks/owasp_agentic_2026.csv, so the page must say so",
            )
        # Every framework value carries a basis, the same discipline as
        # missing_control_basis. Stated means the framework owner picked this code for
        # this case, not that this register read the framework and chose it.
        if row["owasp_code_basis"] not in FRAMEWORK_BASIS:
            report.error(
                f"{where}.owasp_code_basis", f"must be one of {sorted(FRAMEWORK_BASIS)}"
            )
        if row["human_approval"] not in APPROVAL_STATES:
            report.error(f"{where}.human_approval", f"'{row['human_approval']}' is not one of {sorted(APPROVAL_STATES)}")
        if row["disputed"] not in YES_NO:
            report.error(f"{where}.disputed", "must be Yes or No")
        if row["aftermath_status"] not in AFTERMATH_STATES:
            report.error(f"{where}.aftermath_status", f"must be one of {sorted(AFTERMATH_STATES)}")
        # A row that does not know how the story ended has to say so in the text, not
        # leave the reader with the failure as the last word.
        if row["aftermath_status"] in {"Partial", "Undocumented"}:
            text = row["what_changed_after"].lower()
            if not any(p in text for p in ("not on the public record", "not documented", "nothing further")):
                report.error(
                    where,
                    f"aftermath_status is {row['aftermath_status']} but what_changed_after "
                    "does not tell the reader the ending is unknown. Stopping at the "
                    "failure overstates the harm",
                )
        basis = row["missing_control_basis"].strip()
        tier = basis.split(".")[0].strip()
        if tier not in MISSING_CONTROL_TIERS:
            report.error(
                f"{where}.missing_control_basis",
                f"must begin with one of {sorted(MISSING_CONTROL_TIERS)} followed by a "
                "full stop and the reason",
            )
        elif len(basis) <= len(tier) + 2:
            report.error(
                f"{where}.missing_control_basis",
                f"says '{tier}' with no reason after it. The tier without the working is "
                "a label, not a basis",
            )

        if row["inclusion"] not in INCLUSION_STATES:
            report.error(f"{where}.inclusion", f"must be one of {sorted(INCLUSION_STATES)}")
        # The window is part of the rule, so a row claiming to have passed it is checked
        # against it rather than trusted.
        elif row["inclusion"] == "Passed the inclusion rule" and not (
            "2025-01-01" <= row["event_date"] <= "2026-09-30"
        ):
            report.error(
                where,
                f"claims to have passed the inclusion rule but its event date "
                f"{row['event_date']} is outside the window of 1 January 2025 to "
                "30 September 2026",
            )
        if row["eu_serious_incident"] not in EU_SERIOUS:
            report.error(f"{where}.eu_serious_incident", f"must be one of {sorted(EU_SERIOUS)}")
        if row["eu_closest_limb"] not in EU_LIMBS:
            report.error(f"{where}.eu_closest_limb", "must be a, b, c or d")
        if row["eu_basis_type"] not in FRAMEWORK_BASIS:
            report.error(f"{where}.eu_basis_type", f"must be one of {sorted(FRAMEWORK_BASIS)}")
        if not row["eu_basis"].strip():
            report.error(f"{where}.eu_basis", "has no basis")
        if row["directed_by"] not in DIRECTED_BY:
            report.error(f"{where}.directed_by", f"must be one of {sorted(DIRECTED_BY)}")
        if not row["directed_by_basis"].strip():
            report.error(f"{where}.directed_by_basis", "has no basis")
        if row["control_maturity"] not in CONTROL_MATURITY:
            report.error(f"{where}.control_maturity", f"must be one of {sorted(CONTROL_MATURITY)}")
        if row["harm_bearer_had_control"] not in HARM_CONTROL_STATES:
            report.error(f"{where}.harm_bearer_had_control", f"must be one of {sorted(HARM_CONTROL_STATES)}")
        # The split owner has to be a real split. Two names for one role is a field
        # doing nothing while looking like governance.
        if row["control_owner_role"].strip().lower() == row["accountable_role"].strip().lower():
            report.error(
                where,
                "control_owner_role and accountable_role are the same. The split exists to "
                "show who runs the control and who answers when it fails. If they are "
                "genuinely one role, say so in the text rather than duplicating the cell",
            )
        for answer_field, source_field in DEPLOY_PAIRS:
            answer = row[answer_field].strip()
            source = row[source_field].strip()
            if answer not in DEPLOY_STATES:
                report.error(f"{where}.{answer_field}", f"must be one of {sorted(DEPLOY_STATES)}")
                continue
            if answer in {"Yes", "No"} and not source:
                report.error(
                    f"{where}.{answer_field}",
                    f"is '{answer}' with no source. Both answers are claims about the "
                    "record and need a link. Use 'Not disclosed' when the record is silent",
                )
            if answer == "Not disclosed" and source:
                report.error(
                    f"{where}.{source_field}",
                    "has a source but the answer is 'Not disclosed'. If a source says "
                    "something, the answer is Yes or No",
                )
            if source and not source.startswith("https://"):
                report.error(f"{where}.{source_field}", f"'{source}' is not an https link")

        # Everything computed from what_happened has to be re-examined when the facts
        # move. Severity already had this rule. This extends it to the derived fields the
        # headline actually counts.
        changed = parse_date(row["facts_changed_at"])
        rechecked = parse_date(row["derived_rechecked_at"])
        if changed is None:
            report.error(f"{where}.facts_changed_at", "is not an ISO date")
        if rechecked is None:
            report.error(f"{where}.derived_rechecked_at", "is not an ISO date")
        if changed and rechecked and rechecked < changed:
            report.error(
                where,
                f"facts changed on {changed} but the derived fields were last re-checked "
                f"on {rechecked}. control_class, said_something_untrue, "
                "incident_or_hazard and severity all depend on the facts and must be "
                "re-examined when they move",
            )

        if row["said_something_untrue"] not in UNTRUE_STATES:
            report.error(f"{where}.said_something_untrue", "must be Yes or No")

        # The rubric classes a row Accuracy only where the agent stated something untrue.
        # The reverse is allowed, because a row can be both and the ordering decides.
        if row["control_class"] == "Accuracy" and row["said_something_untrue"] == "No":
            report.error(
                where,
                "classed Accuracy but recorded as having stated nothing untrue. One of the "
                "two is wrong",
            )

        granted = [part.strip() for part in row["authority"].split("|") if part.strip()]
        if not granted:
            report.error(f"{where}.authority", "no authority recorded")
        for item in granted:
            if item not in AUTHORITIES:
                report.error(f"{where}.authority", f"'{item}' is not one of {sorted(AUTHORITIES)}")

        # A hazard is a near miss, so it cannot also claim that harm occurred. The OECD
        # definitions are the point of the field and the register has to honour them.

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

        # what_changed_after makes a claim about the deployer's response, which is a
        # different claim from the incident itself. It gets its own named citation rather
        # than an assumption that the incident sources happen to cover it.
        aftermath = row["aftermath_source_url"].strip()
        if not aftermath:
            report.error(
                f"{where}.aftermath_source_url",
                "what_changed_after has no citation. The deployer response is a separate "
                "claim from the incident and needs its own source, even when that source "
                "is one of the two already listed",
            )
        else:
            parsed = urlparse(aftermath)
            if parsed.scheme != "https" or not parsed.netloc:
                report.error(f"{where}.aftermath_source_url", f"'{aftermath}' is not an https link")
            elif parsed.netloc.lower().removeprefix("www.") in AGGREGATOR_HOSTS:
                report.error(
                    f"{where}.aftermath_source_url",
                    "cites an aggregator. Cite the report it points at",
                )

        check_clauses(report, where, row)
        check_eu_order(report, where, row)
        check_aiid(report, where, row)
        check_evidence(report, where, row)
        check_style(report, where, row)


def validate_mit_framework(report, project_dir, register_ids):
    """The MIT framework file must be the whole table, and every rating must sit in it.

    Five levels by ten harm types is 50 cells. A transcription that quietly lost a
    column would still look like a framework file, so the shape is checked rather than
    assumed.
    """
    path = project_dir / "frameworks" / "mit_severity_framework.csv"
    if not path.exists():
        report.error("frameworks", "mit_severity_framework.csv is missing")
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        cells = list(csv.DictReader(fh))

    levels = {row["level"] for row in cells}
    harms = {row["harm_type"] for row in cells}
    if len(levels) != 5:
        report.error("frameworks.mit", f"{len(levels)} severity levels, expected 5")
    if len(harms) != 10:
        report.error("frameworks.mit", f"{len(harms)} harm types, expected 10")
    if len(cells) != 50:
        report.error(
            "frameworks.mit",
            f"{len(cells)} cells, expected 50. The table is five levels by ten harm types",
        )
    for row in cells:
        if not row["descriptor"].strip():
            report.error(
                "frameworks.mit",
                f"level {row['level']} and {row['harm_type']} has no descriptor",
            )

    ratings_path = project_dir / "data" / "case_harm_ratings.csv"
    if not ratings_path.exists():
        report.warn("ratings", "case_harm_ratings.csv is missing, so no case is scored yet")
        return {}
    with open(ratings_path, newline="", encoding="utf-8") as fh:
        ratings = list(csv.DictReader(fh))

    headline = {}
    for row in ratings:
        where = f"ratings.{row['case_id']}.{row['harm_type']}"
        if row["case_id"] not in register_ids:
            report.error(where, "rates a case that is not in the register")
        if row["harm_type"] not in harms:
            report.error(where, "is not one of the framework's ten harm types")
        if row["level"] not in levels:
            report.error(where, f"level '{row['level']}' is not one of the framework's five")
        if row["basis_type"] not in FRAMEWORK_BASIS:
            report.error(where, f"basis_type must be one of {sorted(FRAMEWORK_BASIS)}")
        if not row["basis"].strip():
            report.error(where, "has no basis. A rating without its working cannot be checked")
        headline[row["case_id"]] = max(headline.get(row["case_id"], 0), int(row["level"]))

    for case in sorted(register_ids - set(headline)):
        report.error("ratings", f"{case} has no harm rating, so it has no severity")
    return headline


def check_analytical_split(report, project_dir, rows):
    """The register's load-bearing claim, checked rather than remembered.

    Two reviewers independently found the same contradiction in version 0.8: the page
    said only grade A and B rows feed a number, and then printed composition counts
    totalling all rows. The fix is not to remember harder. It is this.

    Descriptive counts describe the register and cover every row. Analytical counts
    support a claim and cover only the counted grades. This checks three things:

      1. the app's headline function actually filters to counted rows
      2. the distinction is not vacuous, meaning the two sets of numbers really differ
      3. the headline cannot be restated more favourably by reordering the rubric
    """
    app = project_dir / "app.py"
    if not app.exists():
        report.warn("app", "app.py not found, skipping the analytical split check")
        return

    source = app.read_text(encoding="utf-8")
    try:
        body = source.split("def headline(", 1)[1].split("\ndef ", 1)[0]
    except IndexError:
        report.error("app.headline", "no headline() function found to check")
        return
    if 'counted = frame[frame["counted"]]' not in body:
        report.error(
            "app.headline",
            "does not filter to counted rows. Every analytical figure must exclude "
            "grade C",
        )

    counted = [r for r in rows if r["evidence_grade"] in COUNTED_GRADES]
    uncounted = [r for r in rows if r["evidence_grade"] not in COUNTED_GRADES]
    if not uncounted:
        return

    # If every analytical figure came out the same over all rows, the separation would
    # be real in the prose and meaningless in the data, which is the version of this
    # bug that survives a careless fix.
    def figures(subset):
        return (
            len(subset),
            sum(1 for r in subset if r["control_class"] != "Accuracy"),
            sum(1 for r in subset if r["said_something_untrue"] == "No"),
        )

    if figures(counted) == figures(rows):
        report.error(
            "analytical split",
            "the counted and all-row figures are identical, so the exclusion rule is "
            "doing nothing. Check that grade C rows are really being excluded",
        )

    # The structural finding, which is what the register actually rests on now that the
    # ordering effect has been measured: no case caused harm through an untrue statement
    # alone. A row that did would need the agent to have stated something untrue while
    # holding no authority beyond reading, with a person approving its actions, and with
    # nothing structural recorded as the missing control. The home screen asserts that no
    # such row exists, so the build refuses one.
    for row in counted:
        untruth_alone = (
            row["said_something_untrue"] == "Yes"
            and not ({"Write", "Delete", "Pay", "Promise"} & set(row["authority"].split("|")))
            and row["human_approval"] == "Yes"
            and row["control_class"] == "Accuracy"
        )
        if untruth_alone:
            report.error(
                row["id"],
                "harm came from an untrue statement alone, with no authority beyond read, "
                "a person approving, and no structural missing control. The home screen "
                "claims no such case exists. Either the coding is wrong or the claim is",
            )

    # The ordering sensitivity has to stay reportable, because the headline rests on it.
    ordered = sum(1 for r in counted if r["control_class"] != "Accuracy")
    floor = sum(1 for r in counted if r["said_something_untrue"] == "No")
    if floor > ordered:
        report.error(
            "analytical split",
            f"the order-independent floor ({floor}) exceeds the ordered-rubric count "
            f"({ordered}), which should be impossible. Check said_something_untrue",
        )
    print(
        f"Ordering sensitivity: {ordered} of {len(counted)} not accuracy under the "
        f"published rubric, {floor} of {len(counted)} with accuracy tested first."
    )
    print(
        f"Structural finding holds: 0 of {len(counted)} cases caused harm through an "
        "untrue statement alone."
    )
    tiers = {}
    for row in counted:
        tier = row["missing_control_basis"].split(".")[0].strip()
        tiers[tier] = tiers.get(tier, 0) + 1
    print(
        "Missing control basis: "
        + ", ".join(f"{n} {t.lower()}" for t, n in sorted(tiers.items(), key=lambda x: -x[1]))
    )


def check_freshness(report, project_dir):
    """The stated date must not be older than the newest commit.

    A reviewer noticed the page said 3 October while files had landed on the 6th. A
    register whose own date is stale is making a small version of the mistake it
    documents, so the build now refuses it.
    """
    import subprocess

    app = project_dir / "app.py"
    if not app.exists():
        return
    source = app.read_text(encoding="utf-8")
    match = re.search(r'UPDATED = "([^"]+)"', source)
    if not match:
        report.error("app", "no UPDATED date found in app.py")
        return
    stated_text = match.group(1)
    try:
        stated = date(
            int(stated_text.split()[2]),
            MONTHS[stated_text.split()[1]],
            int(stated_text.split()[0]),
        )
    except (ValueError, KeyError, IndexError):
        report.error("app.UPDATED", f"'{stated_text}' is not a date like '7 October 2026'")
        return

    try:
        out = subprocess.run(
            ["git", "-C", str(project_dir), "log", "-1", "--format=%cs"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:  # noqa: BLE001
        return
    if out.returncode != 0 or not out.stdout.strip():
        return
    last_commit = parse_date(out.stdout.strip())
    if last_commit and last_commit > stated:
        report.error(
            "app.UPDATED",
            f"says {stated_text} but the newest commit is {last_commit}. Bump the date "
            "or the page is telling readers something false about itself",
        )


MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
}


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
    mit = validate_mit_framework(report, project_dir, {row["id"] for row in rows})
    check_analytical_split(report, project_dir, rows)
    check_freshness(report, project_dir)

    counted = [row for row in rows if row["evidence_grade"] in COUNTED_GRADES]
    print(f"Register: {len(rows)} rows, {len(counted)} counted (grades A and B).")
    by_class = {}
    for row in counted:
        by_class[row["control_class"]] = by_class.get(row["control_class"], 0) + 1
    for name, count in sorted(by_class.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {name}: {count}")

    if mit:
        names = {1: "Negligible", 2: "Minor", 3: "Substantial", 4: "Severe", 5: "Catastrophic"}
        spread = {}
        for case, level in mit.items():
            spread[names[level]] = spread.get(names[level], 0) + 1
        counted_ids = {row["id"] for row in counted}
        spread_counted = {}
        for case, level in mit.items():
            if case in counted_ids:
                spread_counted[names[level]] = spread_counted.get(names[level], 0) + 1
        # Both bases, each labelled. An unlabelled severity spread printed next to a
        # counted-rows total is how a descriptive figure gets quoted as an analytical one.
        print(
            f"MIT severity, all {len(rows)} rows (descriptive): "
            + ", ".join(f"{v} {k}" for k, v in sorted(spread.items()))
        )
        print(
            f"MIT severity, {len(counted)} counted rows (analytical): "
            + ", ".join(f"{v} {k}" for k, v in sorted(spread_counted.items()))
        )

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

"""AI Agent Incident Register.

Twelve real AI agent failures, each traced to the control that was missing, the test
that would have caught it before launch, and the signal that would have shown it
after. A visitor can also answer six questions about their own agent and download a
watch list built from the same cases.

Three rules run through this file.

1. Every number on screen is computed from data/incidents.csv. Nothing is typed into
   the page, so no count can drift away from the rows behind it.
2. Only grade A and grade B rows feed a number. Grade C rows appear in the register,
   labelled, and are excluded from every count.
3. The watch list runs on fixed rules in rules/watchlist_rules.json. No model runs
   inside this app, and every output line shows the rule and the incidents behind it.
"""

import csv
import html
from collections import Counter
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="AI Agent Incident Register",
    page_icon="🛑",
    layout="wide",
    initial_sidebar_state="auto",  # collapses itself on a phone, where an open sidebar covers the page
)

# Wide tables scroll inside their own box rather than pushing the page sideways.
#
# The register index carries ten facet columns and is rendered as Markdown rather than
# with st.table or st.dataframe. st.dataframe draws to a canvas and leaves its contents
# out of the accessibility tree entirely. st.table is a real table but does not render
# Markdown on the pinned Streamlit version, so links in cells come out as literal
# bracket syntax. Markdown gives a real table, with headers, that a screen reader can
# read and that can hold a link. The only thing it lacks is this, and this is four lines.
# Colour means severity of harm. Nothing else on the page is a data colour.
#
# A page with a colour per class, per grade and per status reads as marketing to a
# governance audience, and colour carrying three meanings carries none. Grade is
# monochrome, and every severity pill pairs its colour with a five-bar meter and the word,
# so nothing depends on colour alone. The bar chart this comment used to mention was
# removed in the layout pass of 11 October 2026.
# MIT AI Risk Initiative, AI Incident Tracker harm severity framework, CSET-based as
# modified by MIT. Captured 10 October 2026 and transcribed into
# frameworks/mit_severity_framework.csv. A case's headline level is the highest level it
# reached on any harm type.
MATURITY_MEANING = {
    "Absent": "The control did not exist in any form.",
    "Designed": "It existed on paper, in a policy or an instruction, with nothing enforcing it.",
    "Implemented": "It was built and wired in, and it did not stop the thing it was there to stop.",
    "Bypassable": "It was built and wired in, and whatever it was there to stop could switch it off.",
    "Unknown": "The public record does not say what state it was in.",
}

DIRECTED_MEANING = {
    "Deployer": "It was doing what the people running it had configured or told it to do.",
    "Attacker": "An outside party pointed it at this, whether by stealing access, hiding "
                "instructions in content it read, or simply asking.",
    "No one": "Nobody steered it. It did this in ordinary use.",
}

MIT_LEVELS = {
    1: "Negligible", 2: "Minor", 3: "Substantial", 4: "Severe", 5: "Catastrophic",
}
MIT_SLUG = {1: "neg", 2: "min", 3: "sub", 4: "sev", 5: "cat"}
MIT_ORDER = [5, 4, 3, 2, 1]

MIT_ATTRIBUTION = (
    "Framework: MIT AI Risk Initiative, AI Incident Tracker (CC BY 4.0), based on CSET's "
    "Taxonomy of AI Harm, as modified by MIT. Captured 10 October 2026. Scores are this "
    "register's, not MIT's."
)

PAGE_CSS = """
<style>
:root {
  --sev-cat:#8f1d1d; --sev-sev:#d03b3b; --sev-sub:#ec835a; --sev-min:#fab219; --sev-neg:#898781;
  --tint-cat:rgba(143,29,29,0.16); --tint-sev:rgba(208,59,59,0.14);
  --tint-sub:rgba(236,131,90,0.18); --tint-min:rgba(250,178,25,0.18);
  --tint-neg:rgba(137,135,129,0.14);
  --meter-off:#c3c2b7; --track:#e1e0d9; --grid-line:#e1e0d9; --ink-2:#52514e; --muted:#898781;
}
@media (prefers-color-scheme: dark) {
  :root {
    --sev-cat:#f08a8a;
    --tint-cat:rgba(240,138,138,0.22); --tint-sev:rgba(208,59,59,0.26);
    --tint-sub:rgba(236,131,90,0.22); --tint-min:rgba(250,178,25,0.20);
    --tint-neg:rgba(137,135,129,0.22);
    --meter-off:#66655f; --track:#2c2c2a; --grid-line:#2c2c2a; --ink-2:#c3c2b7;
  }
}

/* Wide tables scroll in their own box rather than pushing the page sideways. */
div[data-testid="stMarkdownContainer"]:has(> table) { overflow-x: auto; }
div[data-testid="stMarkdownContainer"] > table { min-width: max-content; }
div[data-testid="stTable"] { overflow-x: auto; }
div[data-testid="stTable"] table { min-width: max-content; }
div[data-testid="stTable"] th, div[data-testid="stTable"] td { white-space: nowrap; }

/* The case table. A real table with real headers, built as HTML because a severity
   meter cannot be expressed in a dataframe cell. */
.case-table-wrap { overflow-x: auto; border: 1px solid var(--grid-line); border-radius: 12px; }
table.cases { border-collapse: collapse; width: 100%; min-width: 720px; font-size: 14px; }
table.cases th, table.cases td {
  text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--grid-line);
  vertical-align: middle;
}
table.cases th {
  font-size: 12px; color: var(--muted); font-weight: 600;
  text-transform: uppercase; letter-spacing: .04em; white-space: nowrap;
}
table.cases tr:last-child td { border-bottom: 0; }
table.cases td.id { white-space: nowrap; font-variant-numeric: tabular-nums; }
table.cases tr.notcounted td { color: var(--muted); }

.sev {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 3px 10px 3px 8px; border-radius: 999px; font-size: 13px; white-space: nowrap;
}
.meter { display: inline-flex; gap: 2px; align-items: flex-end; height: 12px; }
.meter i { width: 3px; border-radius: 1px; background: var(--meter-off); display: block; }
.meter i:nth-child(1){height:4px} .meter i:nth-child(2){height:6px}
.meter i:nth-child(3){height:8px} .meter i:nth-child(4){height:10px}
.meter i:nth-child(5){height:12px}
.s-neg{background:var(--tint-neg)} .s-neg .meter i.f{background:var(--sev-neg)}
.s-min{background:var(--tint-min)} .s-min .meter i.f{background:var(--sev-min)}
.s-sub{background:var(--tint-sub)} .s-sub .meter i.f{background:var(--sev-sub)}
.s-sev{background:var(--tint-sev)} .s-sev .meter i.f{background:var(--sev-sev)}
.s-cat{background:var(--tint-cat)} .s-cat .meter i.f{background:var(--sev-cat)}

.grade {
  display:inline-block; min-width:26px; text-align:center; padding:1px 7px;
  border-radius:6px; font-size:12px; font-weight:650;
}
.g-a { background: currentColor; }
.g-a span { color: Canvas; }
.g-b { border: 1.5px solid currentColor; }
.g-c { border: 1.5px dashed var(--muted); color: var(--muted); }

.hero-band {
  background:#0d2440; color:#fff; border-radius:14px; padding:44px 48px; margin:4px 0 48px;
}
@media (prefers-color-scheme: dark) { .hero-band { background:#13263d; } }
@media (max-width: 640px) { .hero-band { padding:28px 20px; } }
.hero-band h1 { font-size:40px; line-height:1.1; margin:0 0 12px; font-weight:700; color:#fff; }
.hero-band p.tagline {
  font-size:22px; line-height:1.35; margin:0 0 28px; font-weight:500; color:#fff;
  background:none;
}
.hero-band p.fact { color:#c9d8ec; margin:0 0 10px; font-size:15px; font-weight:600; }
.hero-band p.fact .sep { display:inline-block; padding:0 16px; }
.hero-band p.def {
  color:#c9d8ec; margin:0; font-size:14px; font-weight:400; max-width:720px; line-height:1.5;
}

/* One grid rather than three Streamlit columns, so the cards are the same height and
   each button sits inside its own card at the bottom with the three lined up. */
.cards { display:grid; grid-template-columns:repeat(3, 1fr); gap:16px; margin:24px 0 8px; }
@media (max-width: 900px) { .cards { grid-template-columns:1fr; } }
.fcard {
  background:var(--surface,#fcfcfb); border:1px solid var(--ring,rgba(11,11,11,.10));
  border-radius:14px; padding:18px; display:flex; flex-direction:column; height:100%;
}
.fcard .big { font-size:38px; font-weight:700; line-height:1; margin:0 0 12px; }
.fcard .big small { font-size:16px; color:var(--muted); font-weight:500; margin-left:4px; }
.dots { display:flex; gap:5px; margin:0 0 16px; flex-wrap:wrap; }
.dots i { width:14px; height:14px; border-radius:50%; background:#d6d4cc; display:block; }
.dots i.on { background:#2a78d6; }
@media (prefers-color-scheme: dark) { .dots i { background:#3a3a37; } .dots i.on { background:#3987e5; } }
.fcard .say { font-size:16px; font-weight:600; margin:0 0 8px; line-height:1.35; }
.fcard .more { color:#52514e; font-size:14px; margin:0; line-height:1.5; }
.fcard .note { color:var(--muted); font-size:13px; margin:10px 0 0; line-height:1.45; }
.fcard .cardbtn {
  margin-top:auto; padding-top:16px; display:block; text-align:center;
}
.fcard .cardbtn a {
  display:block; padding:9px 12px; border-radius:8px; font-size:14px; font-weight:600;
  border:1px solid var(--ring,rgba(11,11,11,.18)); color:inherit; text-decoration:none;
}
.fcard .cardbtn a:hover { background:var(--track,#e1e0d9); }

.seg { display:flex; gap:2px; height:28px; margin:10px 0 8px; }
.seg div:first-child { border-radius:6px 0 0 6px; }
.seg div:last-child { border-radius:0 6px 6px 0; }
.seglabels { display:flex; gap:2px; font-size:13px; color:var(--ink-2); }
.seglabels b { color:var(--ink); display:block; font-size:14px; }

.thesis {
  background:var(--surface,#fcfcfb); border:1px solid var(--ring,rgba(11,11,11,.10));
  border-left:4px solid #2a78d6; border-radius:10px; padding:18px 20px;
}
.thesis .t { font-size:19px; font-weight:650; line-height:1.3; margin:0 0 8px; }
.thesis p { margin:0; color:var(--ink-2); }
</style>
"""

APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "data" / "incidents.csv"

VERSION = "1.0"
UPDATED = "13 October 2026"

# The app imports its vocabularies and its evidence rule from the validator rather than
# restating them. A value the validator would reject cannot be displayed as valid here.
sys.path.insert(0, str(APP_DIR / "scripts"))
import validate_register as rules_check  # noqa: E402

# The rule engine is loaded by explicit path. "evaluate" is a common module name and
# this must always resolve to the one in this repo.
_spec = importlib.util.spec_from_file_location(
    "watchlist_engine", APP_DIR / "rules" / "evaluate.py"
)
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)

COUNTED_GRADES = rules_check.COUNTED_GRADES
CONTROL_CLASSES = rules_check.CONTROL_CLASSES
OWASP_CODES = rules_check.OWASP_CODES
OWASP_STATUS = rules_check.OWASP_STATUS

GRADE_MEANING = {
    "A": "A primary record, meaning a ruling, a regulator notice, a vendor security advisory or a threat intelligence report, plus a second source on another site that corroborates it rather than restating it.",
    "B": "Two independent reputable reports on different sites, usually including the deployer's own public statement.",
    "C": "A single source, or an account the deployer has not addressed. Shown here, counted nowhere.",
}

KIND_MEANING = {
    "Incident": "Harm occurred. This follows the OECD definition.",
    "Hazard": "A near miss. The failure was demonstrated but no harm has been established.",
}

APPROVAL_MEANING = {
    "No": "No person saw the action before it took effect.",
    "Yes": "A person approved, and the approval did not prevent the failure.",
    "Yes, bypassed": "An approval gate existed on paper and did not hold.",
    "Unknown": "The public record does not say.",
}

# Colour is a second signal here, never the only one. Every badge carries its own words.

NIST_GAP_QUOTE = (
    "NIST names an immature information sharing ecosystem and a lack of trusted "
    "guidelines for monitoring methods and tools among the field's central gaps, in "
    "[AI 800-4, Challenges to the Monitoring of Deployed AI Systems]"
    "(https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.800-4.pdf), published 6 March 2026. "
    "Both phrases are gap headings in sections 3.1.1 and 3.1.2."
)


# --------------------------------------------------------------------------- loading


def data_stamp(*paths):
    """A cache key that changes when the data changes.

    st.cache_data keys on the function's code and arguments, never on the files the
    function happens to open. Adding a column to incidents.csv therefore left the key
    identical, and a hot reload on the hosted app ran new code against a DataFrame
    cached before the column existed, which is how v1.0 reached the live site as a
    KeyError while every local check passed. Local runs never caught it because each
    one starts with a cold cache.
    """
    return tuple(
        (path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else (0, 0)
        for path in paths
    )


RATINGS_FILE = APP_DIR / "data" / "case_harm_ratings.csv"
MIT_FRAMEWORK_FILE = APP_DIR / "frameworks" / "mit_severity_framework.csv"
RULES_FILE = APP_DIR / "rules" / "watchlist_rules.json"


@st.cache_data
def load_register(_stamp):
    frame = pd.read_csv(DATA_FILE, dtype=str).fillna("")
    frame["counted"] = frame["evidence_grade"].isin(COUNTED_GRADES)
    frame["year"] = frame["event_date"].str.slice(0, 4)
    ratings = pd.read_csv(RATINGS_FILE, dtype=str).fillna("")
    ratings["level"] = ratings["level"].astype(int)
    frame["mit_level"] = frame["id"].map(ratings.groupby("case_id")["level"].max())
    frame["mit_floored"] = frame["id"].map(
        ratings[ratings["at_least"] == "Yes"].groupby("case_id")["level"].max()
    ).notna() & (
        frame["id"].map(ratings[ratings["at_least"] == "Yes"].groupby("case_id")["level"].max())
        == frame["id"].map(ratings.groupby("case_id")["level"].max())
    )
    return frame


@st.cache_data
def load_harm_ratings(_stamp):
    """Per-case harm ratings on MIT's framework, and the headline level per case."""
    ratings = pd.read_csv(RATINGS_FILE, dtype=str).fillna("")
    ratings["level"] = ratings["level"].astype(int)
    headline = ratings.groupby("case_id")["level"].max().to_dict()
    floored = (
        ratings[ratings["at_least"] == "Yes"].groupby("case_id")["level"].max().to_dict()
    )
    return ratings, headline, floored


@st.cache_data
def load_mit_framework(_stamp):
    frame = pd.read_csv(MIT_FRAMEWORK_FILE, dtype=str)
    frame["level"] = frame["level"].astype(int)
    return frame


@st.cache_data
def load_rules(_stamp):
    return engine.load_rules()


def esc(value) -> str:
    """Escape CSV-derived text before it reaches any raw-HTML render.

    This repo is public and meant to be forked, so CSV content is treated as untrusted
    input even though today it is hand written.
    """
    return html.escape(str(value), quote=True)


RUNNABLE_TESTS = {
    "AIR-002": ("tests/test_authority.py", "DestructiveActionsNeedAGate"),
    "AIR-004": ("tests/test_authority.py", "TheGateMustBeOperating"),
    "AIR-010": ("tests/test_injection.py", "UntrustedContentCannotAct"),
}


def tag(text):
    """A neutral outlined tag. Nothing here encodes data, so nothing here is coloured.

    Only the severity pill is coloured on a card, because severity is the only thing
    colour means on this site.
    """
    return (
        '<span style="display:inline-block;border:1px solid rgba(128,128,128,.4);'
        "border-radius:4px;padding:2px 8px;font-size:0.78rem;font-weight:600;"
        f'margin:0 6px 4px 0;white-space:nowrap">{esc(text)}</span>'
    )


def severity_pill(level, floored=False):
    """Colour, a five-bar meter and the word. Never colour alone."""
    name = MIT_LEVELS[level]
    bars = "".join(f'<i class="{"f" if i <= level else ""}"></i>' for i in range(1, 6))
    prefix = "at least " if floored else ""
    return (
        f'<span class="sev s-{MIT_SLUG[level]}">'
        f'<span class="meter" aria-hidden="true">{bars}</span>{esc(prefix + name)}</span>'
    )


def grade_badge(grade):
    """Monochrome. A filled, B outlined, C dashed and followed by the words."""
    badge = f'<span class="grade g-{grade.lower()}"><span>{esc(grade)}</span></span>'
    if grade == "C":
        badge += ' <span style="font-size:12px;color:var(--muted)">not counted</span>'
    return badge


def _home_link(chosen, show_uncounted=False, case=None):
    """A Home URL that keeps the filter the reader is already in.

    Every link on Home has to carry the current view forward, or clicking a case ID
    silently drops the filter and the table stops matching the heading above it.
    """
    parts = [f"view={key}" for key in chosen]
    if show_uncounted:
        parts.append("c=1")
    if case:
        parts.append(f"case={case}")
    query = "?" + "&".join(parts) if parts else "?"
    return query + ("#full-record" if case else "")


def case_table(view, case_href=None):
    """The case index as HTML.

    An HTML table rather than st.table or st.dataframe, because a severity meter cannot
    be expressed in a dataframe cell and st.dataframe draws to a canvas its contents
    never leave. This is a real table with real headers, so a screen reader reads it.
    """
    head = (
        "<thead><tr><th>ID</th><th>What happened</th><th>Missing control</th>"
        "<th>Severity</th><th>Evidence</th></tr></thead>"
    )
    body = []
    for _, row in view.iterrows():
        klass = ' class="notcounted"' if not row["counted"] else ""
        body.append(
            f"<tr{klass}>"
            f'<td class="id"><a href="{esc(case_href(row["id"])) if case_href else "#" + row["id"].lower()}" target="_self">{esc(row["id"])}</a></td>'
            f"<td>{esc(row['title'])}</td>"
            f"<td>{esc(row['control_class'])}</td>"
            f"<td>{severity_pill(row['mit_level'], row['mit_floored'])}</td>"
            f"<td>{grade_badge(row['evidence_grade'])}</td>"
            "</tr>"
        )
    return (
        f'<div class="case-table-wrap"><table class="cases">{head}'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def describe_count(total, counted):
    """Render a composition count, saying plainly how much of it feeds a number."""
    rows = "row" if total == 1 else "rows"
    if total == counted:
        return f"{total} {rows}"
    if counted == 0:
        return f"{total} {rows}, not counted"
    return f"{total} {rows}, {counted} of them counted"


def headline(frame):
    """The opening line of the register, computed from the rows that count.

    The claim the register makes is about which control was missing, so the number
    that carries it is a count of control classes. Grade C rows are excluded.
    """
    counted = frame[frame["counted"]]
    total = len(counted)
    accuracy = int((counted["control_class"] == "Accuracy").sum())
    not_accuracy = total - accuracy
    by_class = counted["control_class"].value_counts().to_dict()
    # The rubric tests accuracy last, so a case that is both a permissions failure and
    # an accuracy failure is classed as the former. That ordering could be producing
    # the finding on its own, so the register measures the effect rather than arguing
    # about it. A row where the agent stated nothing untrue cannot become an accuracy
    # failure under any ordering, which makes it an order-independent floor.
    said_untrue = counted["said_something_untrue"] == "Yes"
    # Could the agent do more than read. This is the authority it actually held at the
    # time, which is not always the authority its owners believed it held.
    acted = counted["authority"].apply(
        lambda value: bool({"Write", "Delete", "Pay", "Promise"} & set(value.split("|")))
    )
    return {
        "total": total,
        "all_rows": len(frame),
        "accuracy": accuracy,
        "not_accuracy": not_accuracy,
        "by_class": by_class,
        "accuracy_first": int(len(counted) - said_untrue.sum()),
        "would_change_class": int(said_untrue.sum() - accuracy),
        "said_nothing_untrue": int((~said_untrue).sum()),
        "said_untrue": int(said_untrue.sum()),
        "aftermath_documented": int((counted["aftermath_status"] == "Documented").sum()),
        "aftermath_partial": int((counted["aftermath_status"] == "Partial").sum()),
        "aftermath_undocumented": int((counted["aftermath_status"] == "Undocumented").sum()),
        "control_absent": int((counted["control_maturity"] == "Absent").sum()),
        "basis_stated": int(counted["missing_control_basis"].str.startswith("Stated").sum()),
        "basis_entailed": int(counted["missing_control_basis"].str.startswith("Entailed").sum()),
        "basis_reading": int(counted["missing_control_basis"].str.startswith("Reading").sum()),
        "roles": (
            pd.concat([counted["control_owner_role"], counted["accountable_role"]])
            .value_counts().to_dict()
        ),
        "control_designed": int((counted["control_maturity"] == "Designed").sum()),
        "control_implemented": int((counted["control_maturity"] == "Implemented").sum()),
        "control_bypassable": int((counted["control_maturity"] == "Bypassable").sum()),
        "control_unknown": int((counted["control_maturity"] == "Unknown").sum()),
        "no_stop_authority_recorded": int((counted["deploy_stop_authority"] == "Not disclosed").sum()),
        "no_review_recorded": int((counted["deploy_review_date"] == "Not disclosed").sum()),
        "no_evidence_recorded": int((counted["deploy_evidence_seen"] == "Not disclosed").sum()),
        "bearer_no_control": int((counted["harm_bearer_had_control"] == "No").sum()),
        "no_approval": int((counted["human_approval"] != "Yes").sum()),
        "could_act": int(acted.sum()),
        "read_only": int((~acted).sum()),

        "years": f"{counted['year'].min()} to {counted['year'].max()}",
    }


# ------------------------------------------------------------------------------ home


def severity_strip(frame):
    """The MIT severity spread as one bar. Severity is this site's only data colour."""
    total = len(frame)
    segments, key = [], []
    for level in MIT_ORDER:
        count = int((frame["mit_level"] == level).sum())
        if not count:
            continue
        segments.append(
            f'<div style="width:{100 * count / total:.4f}%;'
            f'background:var(--sev-{MIT_SLUG[level]});height:30px;display:flex;'
            f'align-items:center;justify-content:center;color:#fff;font-size:13px;'
            f'font-weight:650" title="{esc(MIT_LEVELS[level])}: {count} of {total}">'
            f"{count}</div>"
        )
        key.append(
            f'<span style="display:inline-flex;align-items:center;gap:6px;'
            f'margin:0 14px 4px 0"><i style="width:11px;height:11px;border-radius:3px;'
            f'display:inline-block;background:var(--sev-{MIT_SLUG[level]})"></i>'
            f"{esc(MIT_LEVELS[level])} {count}</span>"
        )
    return (
        '<div style="display:flex;border-radius:8px;overflow:hidden;margin:4px 0 10px">'
        f'{"".join(segments)}</div>'
        f'<div style="font-size:13px;color:var(--ink-2)">{"".join(key)}</div>'
    )


def dots(filled, total):
    """A row of dots so "5 of 11" reads without arithmetic."""
    return (
        '<div class="dots" role="img" aria-label="' + f"{filled} of {total}" + '">'
        + "".join(f'<i class="{"on" if i < filled else ""}"></i>' for i in range(total))
        + "</div>"
    )


def how_to_read(text):
    """One grey line under every table, saying what it is and is not."""
    st.caption(text)


def tab_what_was_missing(frame):
    facts = headline(frame)
    counted = frame[frame["counted"]]

    by_class = Counter(counted["control_class"])
    attacker = int((counted["directed_by"] == "Attacker").sum())
    # The cases where the operator got in by claiming the work was authorised. Derived
    # from the rows rather than listed by hand, so a fourth case joins the sentence on its
    # own. Each of these three carries the claim in its own account or its basis, and for
    # the extortion campaign it is in the provider's full threat intelligence report.
    claim = "authorised security test|authorised penetration test|authorised security tester"
    bypass = sorted(
        counted[
            counted["what_happened"].str.contains(claim, case=False, regex=True)
            | counted["missing_control_basis"].str.contains(claim, case=False, regex=True)
        ]["id"]
    )
    uncounted = sorted(frame[~frame["counted"]]["id"])

    st.caption(
        "Every figure on this page is calculated from the register's data, never typed "
        "in by hand."
    )
    st.markdown("#### What was missing?")
    st.markdown(
        "**In most of these cases, the AI didn't fail by getting facts wrong. It failed "
        "because it was allowed to do too much, or because it obeyed instructions it "
        "should have ignored.**"
    )
    st.markdown(
        f"Of the {facts['total']} cases with strong enough evidence to count, only "
        f"{by_class['Accuracy']} come down to the agent saying something untrue. In "
        f"{by_class['Authority']}, the agent had more power than its task needed: it "
        "could delete, send or change things with no check (Authority). In "
        f"{by_class['Boundary']}, it treated text it was reading, such as an email, web "
        "page or document, as an instruction to follow (Boundary). The table below "
        "defines all five types. This split depends partly on the order the types are "
        f"checked in. If accuracy is checked first, {facts['accuracy_first']} of "
        f"{facts['total']} still involve no false statement at all."
    )
    st.markdown("##### Who set the agent in motion?")
    st.markdown(
        f"In {attacker} of the {facts['total']} cases, an attacker was directing the "
        f"agent. In the other {facts['total'] - attacker}, no attacker was involved. The "
        "harm came from ordinary use, or from the agent doing what the organisation "
        "running it had set it up to do. Most failures in this register were not attacks. "
        "They came from how the agent was deployed."
    )
    st.markdown(f"##### One trick worked {len(bypass)} times")
    st.markdown(
        f"In {', '.join(bypass[:-1])} and {bypass[-1]}, attackers got past the model's "
        "safeguards simply by telling it the work was authorised security testing. This "
        "worked on two different AI providers. Nothing in the public record shows either "
        "provider has since changed how its models handle that claim. If your agent can "
        "take security-sensitive actions, test whether this claim gets it past your own "
        "safeguards."
    )
    st.markdown(
        f"**The five types of missing safeguard, across the {facts['total']} counted "
        "cases**"
    )
    rows = []
    for name in sorted(frame["control_class"].unique()):
        n = int((counted["control_class"] == name).sum())
        ids = ", ".join(sorted(counted[counted["control_class"] == name]["id"]))
        extra = sorted(frame[(frame["control_class"] == name) & ~frame["counted"]]["id"])
        if extra:
            ids += f" (+ {', '.join(extra)}, not counted)"
        rows.append(
            f"<tr><td>{esc(name)}</td><td>{esc(CONTROL_CLASSES[name])}</td>"
            f'<td style="text-align:right">{n}</td><td>{esc(ids)}</td></tr>'
        )
    rows.append(
        f'<tr><td><b>Total</b></td><td></td><td style="text-align:right"><b>'
        f"{facts['total']}</b></td><td></td></tr>"
    )
    st.markdown(
        '<div class="case-table-wrap"><table class="cases"><thead><tr>'
        "<th>Missing control</th><th>What it means</th><th>Counted cases</th>"
        f"<th>Case IDs</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    how_to_read(
        f"One more case, {uncounted[0] if uncounted else 'none'}, is shown in the register "
        "but not counted, because it rests on a single source. Each case is given one "
        "missing safeguard, chosen by a fixed order of checks that tests accuracy last."
        if len(uncounted) == 1 else
        f"{len(uncounted)} cases are shown in the register but not counted, because they "
        "rest on a single source. Each case is given one missing safeguard, chosen by a "
        "fixed order of checks that tests accuracy last."
    )

    st.markdown("")
    st.markdown("#### What state was that control in?")
    st.markdown(
        f"**{facts['control_absent']} of {facts['total']} had no such control in any form.**"
    )
    labels = [("Absent", "Never built"), ("Designed", "On paper only"),
              ("Implemented", "Built but did not hold"),
              ("Bypassable", "Built but the attacker could switch it off"),
              ("Unknown", "Record does not say")]
    rows = []
    for key, label in labels:
        subset = counted[counted["control_maturity"] == key]
        rows.append(
            f"<tr><td>{esc(label)}</td>"
            f'<td style="text-align:right">{len(subset)}</td>'
            f"<td>{esc(', '.join(sorted(subset['id'])))}</td></tr>"
        )
    st.markdown(f"**What state that safeguard was in, across {facts['total']} counted cases**")
    st.markdown(
        '<div class="case-table-wrap"><table class="cases"><thead><tr>'
        "<th>State of the control</th><th>Cases</th><th>Case IDs</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    how_to_read(
        "A control can be designed, implemented, evidenced in an audit, and still not be "
        "stopping anything. That third row is the one worth dwelling on."
    )

    st.markdown("")
    st.markdown("#### Two counts that change where you look")
    st.markdown(
        f"In {facts['no_approval']} of the {facts['total']} counted cases, the record "
        "shows no person approving the action before it took effect. In some of those, a "
        "check existed and did not hold."
    )
    st.markdown(
        f"In {facts['read_only']} of the {facts['total']}, the agent could only read. It "
        "could not delete, send, buy or change anything. That did not keep those cases "
        "out of this register. An agent that only reads can still speak, and what it says "
        "can bind the organisation running it. Check what your own agent can say, not "
        "only what it can do."
    )
    how_to_read(
        "The approval field carries no source of its own, unlike the stop-authority "
        "field, so read it as this register's reading of each account rather than a "
        "sourced absence."
    )
    with st.expander("Why it matters"):
        st.markdown(
            "Putting accuracy last in the rubric is a choice that could manufacture the "
            "result, so the register measures the effect rather than asking to be trusted "
            f"on it. {facts['would_change_class']} rows change class when accuracy is "
            "tested first. The finding the register actually rests on is structural: in "
            "none of the counted cases was an untrue statement sufficient on its own. "
            "Harm always also required authority the agent should not have held, reach it "
            "should not have had, or a path nobody was monitoring."
        )


def tab_how_severe(frame):
    ratings, headline_levels, _ = load_harm_ratings(data_stamp(RATINGS_FILE))
    definitions = load_mit_framework(data_stamp(MIT_FRAMEWORK_FILE))
    harms = list(definitions["harm_type"].drop_duplicates())
    limbs = {
        r["limb"]: r["text"]
        for r in csv.DictReader(
            open(APP_DIR / "frameworks" / "eu_ai_act_serious_incident.csv", encoding="utf-8")
        )
    }

    counted_here = frame[frame["counted"]]
    worst = Counter(counted_here["mit_level"].map(MIT_LEVELS))
    st.markdown("#### How severe was the harm?")
    st.markdown(
        "**Measured against all the harm AI could do, the cases in this register are "
        "small.** That is not a reassurance. It is a reason to read them for the shape of "
        "the failure rather than the size of it."
    )
    st.markdown(
        f"Severity here uses MIT's five-level scale, from 1 Negligible to 5 Catastrophic, "
        "which was built to rank every kind of AI harm up to the global level. On that "
        f"scale the worst case in this register reaches level 3, Substantial. Of the "
        f"{len(counted_here)} counted cases, {worst.get('Substantial', 0)} are "
        f"Substantial, {worst.get('Minor', 0)} are Minor and "
        f"{worst.get('Negligible', 0)} are Negligible. A counted case is one with a "
        "primary record plus an independent report. When you read the table, look at how "
        "each harm happened, then ask whether your own agent could reach further than "
        "these did."
    )

    body = []
    for row in frame.sort_values("id").itertuples():
        mine = ratings[ratings["case_id"] == row.id].sort_values("level", ascending=False)
        affected = "<br>".join(
            f"{esc(r.harm_type)} "
            f"<b>{r.level} {MIT_LEVELS[r.level]}</b>{' (at least)' if r.at_least == 'Yes' else ''}"
            for r in mine.itertuples()
        )
        body.append(
            f'<tr><td class="id"><a href="?case={row.id}">{esc(row.id)}</a></td>'
            f"<td>{esc(row.title)}</td>"
            f"<td>{severity_pill(row.mit_level, row.mit_floored)}</td>"
            f'<td style="font-size:13px">{affected}</td>'
            f"<td>{esc(row.eu_serious_incident)}</td>"
            f'<td style="font-size:13px">({esc(row.eu_closest_limb)}) '
            f"{esc(limbs[row.eu_closest_limb])}</td></tr>"
        )
    st.markdown(f"**Harm severity and the closest EU limb, case by case, all {len(frame)} cases**")
    st.markdown(
        '<div class="case-table-wrap"><table class="cases"><thead><tr><th>Case</th>'
        "<th>What happened</th><th>Highest MIT level</th><th>Harm types affected</th>"
        "<th>EU threshold</th><th>Closest limb</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    how_to_read(
        "One row per case. A case's headline level is the highest it reached on any harm "
        "type. \"At least\" means the record does not establish the magnitude, so the "
        "level is a floor rather than a measurement. Closest limb, not a legal "
        "classification."
    )

    st.markdown("")
    st.markdown("**Cases by headline severity**")
    bars = []
    for level in MIT_ORDER:
        n = sum(1 for v in headline_levels.values() if v == level)
        width = 100 * n / max(1, len(headline_levels))
        bars.append(
            '<div style="display:flex;align-items:center;gap:10px;margin:4px 0">'
            f'<span style="width:160px;flex:none">{severity_pill(level)}</span>'
            f'<span style="flex:1;background:var(--track);border-radius:4px">'
            f'<span style="display:block;width:{width:.2f}%;height:16px;border-radius:4px;'
            f'background:var(--sev-{MIT_SLUG[level]})"></span></span>'
            f'<b style="width:28px;text-align:right">{n}</b></div>'
        )
    st.markdown("".join(bars), unsafe_allow_html=True)

    eu_counts = frame["eu_serious_incident"].value_counts().to_dict()
    st.caption(
        "EU Article 3(49): "
        + ", ".join(
            f"{eu_counts.get(k, 0)} {k.lower()}"
            for k in ["Meets", "Does not meet", "Not determinable from the record"]
        )
        + ". Several of these deployers are outside the Act's scope entirely."
    )

    with st.expander("MIT's full definitions"):
        header = "".join(f"<th>{esc(h)}</th>" for h in harms)
        grid = []
        for level in MIT_ORDER:
            cells = "".join(
                "<td>"
                + esc(definitions[(definitions["level"] == level)
                                  & (definitions["harm_type"] == harm)]["descriptor"].iloc[0])
                + "</td>"
                for harm in harms
            )
            grid.append(
                f'<tr><td style="white-space:nowrap">{severity_pill(level)}</td>{cells}</tr>'
            )
        st.markdown("**MIT's severity bands, and how many cases sit in each**")
        st.markdown(
            '<div class="case-table-wrap"><table class="cases">'
            f"<thead><tr><th>Level</th>{header}</tr></thead>"
            f"<tbody>{''.join(grid)}</tbody></table></div>",
            unsafe_allow_html=True,
        )
        st.caption(MIT_ATTRIBUTION)


def tab_what_the_record_shows(frame):
    facts = headline(frame)

    counted = frame[frame["counted"]]
    own_report = sorted(counted[counted["id"].isin(
        ["AIR-013", "AIR-015", "AIR-020", "AIR-021"]
    )]["id"])

    st.markdown("#### What does the record actually show?")
    st.markdown(
        "**Who documents a failure decides which failures exist on paper.** Failures make "
        "the news. Recoveries rarely do."
    )
    st.markdown(
        "**In this register, almost nothing was set up to notice the failure.**"
    )
    st.markdown(
        f"In {facts['no_stop_authority_recorded']} of the {facts['total']} counted cases, "
        "the public record does not name a role that could have halted the deployment. In "
        f"{facts['no_review_recorded']} of {facts['total']}, there is no date set to look "
        "at the agent again. That second figure is every counted case here."
    )
    st.markdown(
        "Neither number says nobody could have stopped it, and neither says nobody ever "
        "looked. They say the published account does not answer the question. A safeguard "
        "nobody can name is one a reader cannot check. For your own agent, write down who "
        "can switch it off and the date you will next review it."
    )
    st.markdown("**Where the newest cases came from is itself a finding.**")
    st.markdown(
        f"{len(own_report)} of the cases added in this release rest on a report published "
        "by an AI company or an AI evaluation body about its own product or its own "
        f"testing. They are {', '.join(own_report)}. Those organisations run threat "
        "intelligence teams and publish what they find. Most companies do neither."
    )
    st.markdown(
        "So the failures that exist on paper are the ones the best instrumented "
        "organisations chose to write up. Agent failures inside ordinary companies are "
        "almost certainly more common, and none of them are here. Read every count in "
        "this register as a count of what was documented, not of what happened."
    )
    corrections = [
        ("A database and its backups were destroyed, newest copy three months old",
         "The platform published a postmortem saying the data was recovered two and a "
         "half days later"),
        ("An eating disorder helpline was shut",
         "The number was taken over by another charity and still reaches therapists"),
        ("A regulator's settlement terms, with no mention of the company's response",
         "The company denied wrongdoing"),
    ]
    st.markdown("**Three corrections an earlier version of this register needed**")
    st.markdown(
        '<div class="case-table-wrap"><table class="cases"><thead><tr>'
        "<th>What an earlier version of this register said</th>"
        "<th>What the record shows</th></tr></thead><tbody>"
        + "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td></tr>" for a, b in corrections)
        + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    how_to_read(
        "Every one of those omissions made the deployer look worse than the record "
        "supports. They were this register's errors, not a source's."
    )

    st.markdown("")
    st.markdown("#### How completely is each ending known?")
    st.markdown(
        f"**{facts['aftermath_documented']} of {facts['total']} counted cases have a "
        f"fully documented ending.** {facts['aftermath_partial']} stop part way and "
        f"{facts['aftermath_undocumented']} has no recorded ending at all."
    )
    how_to_read(
        "A register built from public sources will tend to overstate harm rather than "
        "understate it, because the destruction is news and the recovery is a postmortem "
        "nobody aggregated. Each card says when its record stops early."
    )

    st.markdown("")
    st.markdown("#### What do deployment records contain?")
    st.markdown(
        f"**In {facts['no_review_recorded']} of {facts['total']}, the record does not say "
        "whether any date was set to re-examine the agent.**"
    )
    deploy = [
        ("anyone reviewed the agent's behaviour before launch", facts["no_evidence_recorded"]),
        ("any role could halt or roll back the deployment", facts["no_stop_authority_recorded"]),
        ("any date was set to re-examine it", facts["no_review_recorded"]),
    ]
    st.markdown(f"**What the record is silent about, across {facts['total']} counted cases**")
    st.markdown(
        '<div class="case-table-wrap"><table class="cases"><thead><tr>'
        "<th>Does the public record say whether...</th><th>Silent</th></tr></thead><tbody>"
        + "".join(
            f'<tr><td>{esc(q)}</td><td style="text-align:right">{n} of {facts["total"]}</td></tr>'
            for q, n in deploy
        )
        + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    how_to_read(
        "Statements about the record, not about the deployers. This register does not "
        "claim that any organisation set no review date, only that the record does not "
        "say. Every row defaults to not disclosed, and both yes and no require a source."
    )

    st.markdown("")
    st.markdown("#### How much of this is the register's own judgement?")
    st.markdown(
        f"**{facts['basis_stated'] + facts['basis_entailed']} of {facts['total']} do not "
        "rest on this register's opinion.**"
    )
    tiers = [
        ("Stated", facts["basis_stated"], "The deployer, a regulator or a ruling said it."),
        ("Entailed", facts["basis_entailed"],
         "It follows from the record. A control added afterwards is evidence of its prior absence."),
        ("Our reading", facts["basis_reading"],
         "Neither. This is judgement, and it is labelled as such on the card."),
    ]
    st.markdown("**Where the register's own judgement enters, and where it does not**")
    st.markdown(
        '<div class="case-table-wrap"><table class="cases"><thead><tr>'
        "<th>How the register knows</th><th>Cases</th><th>What it means</th>"
        "</tr></thead><tbody>"
        + "".join(
            f'<tr><td>{esc(n)}</td><td style="text-align:right">{c} of {facts["total"]}</td>'
            f"<td>{esc(d)}</td></tr>"
            for n, c, d in tiers
        )
        + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    how_to_read(
        "Naming the missing control is the only place this register makes a claim about a "
        "company that the company did not make about itself, so it is the only field that "
        "carries this. The test and signal columns are recommendations to the reader."
    )

    with st.expander("Why it matters"):
        st.markdown(
            "Primary records exist mainly for legal and security events: rulings, CVEs, "
            "threat intelligence reports, enforcement notices. A chatbot that quietly "
            "gave wrong answers for a year produces no document at all. A security "
            "vendor's catalogue of agent failures is mostly security failures. And "
            "searching for these cases returns a large volume of generated write-ups with "
            "nothing behind them. Every register of AI incidents, this one included, is a "
            "map of the documentation regime rather than a map of the harm."
        )


def screen_findings(frame, rules):
    st.title("Findings")
    st.markdown(
        f"Every number here is computed from the {len(frame)} rows in "
        "data/incidents.csv and data/case_harm_ratings.csv."
    )
    missing, severe, record = st.tabs(
        ["What was missing", "How severe", "What the record shows"]
    )
    with missing:
        tab_what_was_missing(frame)
    with severe:
        tab_how_severe(frame)
    with record:
        tab_what_the_record_shows(frame)


def incident_card(row):
    """One record, in four tabs.

    Eight rounds of review each added a field, and nothing was watching the total. The
    flat version carried thirty-two fields and six coloured boxes in a single scroll,
    which is unreadable however correct each line is. So the story is always visible and
    the governance detail sits behind tabs, where a reader who wants it can find it and a
    reader who does not is not made to scroll past it.

    The repeated definitions went to the Method page. They were the same words on every
    card, twelve times over.
    """
    st.markdown(
        tag(row["id"])
        + tag(row["incident_or_hazard"])
        + severity_pill(row["mit_level"], row["mit_floored"])
        + tag(f"Missing control: {row['control_class']}")
        + tag(f"Evidence grade {row['evidence_grade']}")
        + (tag("Facts disputed by the deployer") if row["disputed"] == "Yes" else "")
        + (tag("Not counted in any number") if not row["counted"] else "")
        + (tag("Included before the inclusion rule")
           if row["inclusion"] == "Included before the inclusion rule" else ""),
        unsafe_allow_html=True,
    )
    st.markdown(
        f"**{esc(row['deployer'])}** · {esc(row['sector'])} · {esc(row['agent_type'])} "
        f"· {esc(row['event_date'])}"
    )

    happened, missing, test, evidence, aftermath = st.tabs(
        ["What happened", "What was missing", "Test before launch", "Evidence", "Aftermath"]
    )

    with happened:
        st.markdown(esc(row["what_happened"]))
        st.markdown(f"**Why this is in the register.** {esc(row['why_in_register'])}")
        granted = ", ".join(part for part in row["authority"].split("|") if part)
        st.markdown(
            f"**The agent could:** {esc(granted)}.  \n"
            f"**A person approved first:** {esc(row['human_approval'])}."
        )
        st.markdown(
            f"**Harm fell on.** {esc(row['harm_borne_by'])}  \n"
            f"**Could have prevented it.** {esc(row['could_have_prevented'])}"
        )

    with aftermath:
        st.markdown(esc(row["what_changed_after"]))
        if row["aftermath_status"] != "Documented":
            st.markdown(
                f":orange[**The ending is {row['aftermath_status'].lower()}.** The public "
                "record stops before this story does. Read the harm above as what was "
                "reported, not as what finally happened.]"
            )
        if row["disputed"] == "Yes":
            st.markdown(
                ":orange[**The facts here are disputed.** The deployer's own position is "
                "in the paragraph above and in the second source.]"
            )
        if row["aftermath_source_url"]:
            st.caption(f"[The source for this]({row['aftermath_source_url']}).")

    with missing:
        directed_tier = row["directed_by_basis"].split(".")[0].strip()
        st.markdown(
            f"**Who pointed it at this: {row['directed_by']}.** "
            f"{DIRECTED_MEANING[row['directed_by']]}\n\n"
            f"{esc(row['directed_by_basis'])}"
        )
        st.markdown("")
        tier = row["missing_control_basis"].split(".")[0].strip()
        st.markdown(
            f"**State it was in: {row['control_maturity']}.** "
            f"{MATURITY_MEANING[row['control_maturity']]}\n\n"
            f"**How the register knows: {tier}.** "
            f"{esc(row['missing_control_basis'].split('.', 1)[1].strip())}"
        )
        basis = row["owasp_code_basis"]
        mark = (
            ", applied to this case by OWASP's own list"
            if basis == "Stated"
            else ", this register's reading"
        )
        st.caption(
            f"Failure pattern: {esc(row['failure_pattern'])}. OWASP "
            f"{row['owasp_code']}, {OWASP_CODES[row['owasp_code']]}{mark}."
        )

    with test:
        st.markdown(
            f"**Test before launch.** {esc(row['test_before_launch'])}\n\n"
            f"**Pass mark.** {esc(row['test_pass_mark'])}\n\n"
            f"**Signal after launch.** {esc(row['signal_after_launch'])}"
        )
        st.caption(
            f"Monitoring category, NIST AI 800-4: {esc(row['nist_800_4_category'])}. "
            f"Runs the control: {esc(row['control_owner_role'])}. Answers when it fails: "
            f"{esc(row['accountable_role'])}."
        )
        if row["id"] in RUNNABLE_TESTS:
            path, cls = RUNNABLE_TESTS[row["id"]]
            st.success(
                f"**This one runs.** `{path}` · `{cls}`\n\n"
                "`python3 -m unittest discover tests`",
                icon="🧪",
            )

    with evidence:
        rows_md = []
        for label, answer_field, source_field in (
            ("Someone reviewed its behaviour first", "deploy_evidence_seen", "deploy_evidence_source"),
            ("A role could halt or roll it back", "deploy_stop_authority", "deploy_stop_authority_source"),
            ("A date was set to look at it again", "deploy_review_date", "deploy_review_date_source"),
        ):
            link = f" [source]({row[source_field]})" if row[source_field] else ""
            rows_md.append(f"| {label} | {row[answer_field]}{link} |")
        st.markdown(
            "**Does the public record say whether...**\n\n"
            "| | |\n| --- | --- |\n" + "\n".join(rows_md)
        )
        st.caption("Not disclosed means the record is silent, not that the thing was missing.")
        st.markdown(f"**Grade {row['evidence_grade']}.** {GRADE_MEANING[row['evidence_grade']]}")
        st.markdown(f"1. [{esc(row['source_1_label'])}]({row['source_1_url']})")
        if row["source_2_url"]:
            st.markdown(f"2. [{esc(row['source_2_label'])}]({row['source_2_url']})")
        archives = [a for a in row.get("archive_urls", "").split() if a]
        if archives:
            links = ", ".join(f"[{i}]({a})" for i, a in enumerate(archives, start=1))
            st.caption(
                f"Checked {row['date_checked']}. Archived copies: {links}. Some publishers "
                "block automated access, so an archived copy may be the one that opens."
            )
        else:
            st.caption(f"Checked {row['date_checked']}. No archived copy yet.")
        st.markdown(
            f"**Closest clauses.** NIST AI RMF {esc(row['nist_ai_rmf'])} · "
            f"ISO/IEC 42001 {esc(row['iso_42001'])} · EU AI Act {esc(row['eu_ai_act'])}"
        )
        st.caption(
            "Closest clause, not a legal classification."
        )


# Every finding is a filter, and every filter is a link that can be posted on its own.
# The predicates are the single source for the card numbers and the filtering, so a card
# saying 10 and a table showing 9 is not a state this can reach.
#
# "Record silent" is the wording throughout, never "nobody could". The field says the
# public record does not say. Turning that into a claim about the deployer is the same
# error as coding a sourceless No.
#
# There were two FINDINGS dicts here until 12 October 2026. The first carried the tile
# text from before the layout pass and was silently overwritten by this one, so editing
# it changed nothing on the page.
FINDINGS = {
    "no-false-statement": {
        "heading": "{n} cases where the agent said nothing untrue",
        "chip": "Said nothing untrue",
        "test": lambda r: r["said_something_untrue"] == "No",
    },
    "record-silent-on-stop": {
        "heading": "{n} cases where the record doesn't say who could have halted the deployment",
        "chip": "Record silent on who could stop it",
        "test": lambda r: r["deploy_stop_authority"] == "Not disclosed",
    },
    "control-never-built": {
        "heading": "{n} cases where the safeguard was never built",
        "chip": "Control never built",
        "test": lambda r: r["control_maturity"] == "Absent",
    },
    "control-did-not-hold": {
        "heading": "{n} cases where the safeguard existed and did not hold",
        "chip": "Control existed, did not hold",
        "test": lambda r: r["control_maturity"] == "Implemented",
    },
    # Added 12 October 2026 when the register reached 20 counted cases and the three
    # cards were re-picked on what the data now supports.
    "not-accuracy": {
        "heading": "{n} cases where the missing safeguard was not accuracy",
        "chip": "Missing control was not accuracy",
        "test": lambda r: r["control_class"] != "Accuracy",
    },
    "no-review-date": {
        "heading": "{n} cases with no date set to look at the agent again",
        "chip": "No date set to look again",
        "test": lambda r: r["deploy_review_date"] == "Not disclosed",
    },
    "not-attacker": {
        "heading": "{n} cases with no attacker involved",
        "chip": "Not attacker misuse",
        "test": lambda r: r["directed_by"] != "Attacker",
    },
}


def finding_counts(frame):
    """How many counted cases each finding covers. Computed, never typed."""
    counted = frame[frame["counted"]]
    return {
        key: int(counted.apply(spec["test"], axis=1).sum())
        for key, spec in FINDINGS.items()
    }


def screen_home(frame, rules):
    """Home is the register. The case list used to be a second page showing the same
    twelve rows under a second set of headline numbers, which meant a reader met the
    findings twice before reaching a case."""
    facts = headline(frame)
    counts = finding_counts(frame)
    total = facts["total"]

    years = sorted(frame["event_date"].str.slice(0, 4))
    st.markdown(
        '<div class="hero-band">'
        "<h1>AI Agent Incident Register</h1>"
        '<p class="tagline">A public record of AI agents that caused harm, and the '
        "safeguard that was missing in each case.</p>"
        f'<p class="fact">{facts["all_rows"]} documented incidents, {years[0]}&ndash;'
        f'{years[-1]}<span class="sep">·</span>{facts["total"]} with strong enough '
        "evidence to count</p>"
        '<p class="def">An AI agent here means a system that takes actions (runs code, '
        "changes data, sends, buys, posts), not one that only answers.</p></div>",
        unsafe_allow_html=True,
    )

    st.markdown("## What the cases show")
    st.markdown(
        "None of these failures was only the AI being wrong. Every one needed the agent "
        "to be allowed to act."
    )

    # Re-picked on 12 October 2026, at 20 counted cases, and rewritten on 13 October so
    # each card states the finding before the number. The whole row is one grid so the
    # three cards match in height and their buttons line up.
    by_class = Counter(frame[frame["counted"]]["control_class"])
    cards = [
        ("not-accuracy",
         "The missing safeguard wasn't about accuracy.",
         f"In {by_class['Authority']} cases the agent could do more than its task needed. "
         f"In {by_class['Boundary']} it obeyed instructions hidden in content it was "
         f"reading. Only {by_class['Accuracy']} came down to a false statement.",
         f"Even if every case with a false statement is counted as an accuracy failure, "
         f"it is still {facts['accuracy_first']} of {total}."),
        ("record-silent-on-stop",
         "The public record doesn't say who could have stopped it.",
         "That doesn't mean no one could, only that no published account names them. None "
         f"of the {total} records a date to review the agent again. Could you name both "
         "for your own agent?",
         None),
        ("not-attacker",
         "No attacker was involved.",
         "The harm came from normal use, or from the agent doing what its own organisation "
         "set it up to do. Most failures here weren't attacks. They came from how the "
         "agent was deployed.",
         None),
    ]
    blocks = []
    for key, say, more, note in cards:
        n = counts[key]
        blocks.append(
            f'<div class="fcard"><div class="big">{n}<small>of {total}</small></div>'
            f'{dots(n, total)}<p class="say">{esc(say)}</p>'
            f'<p class="more">{esc(more)}</p>'
            + (f'<p class="note">{esc(note)}</p>' if note else "")
            + f'<div class="cardbtn"><a href="?view={key}" target="_self">'
            f"Show these {n}</a></div></div>"
        )
    st.markdown(f'<div class="cards">{"".join(blocks)}</div>', unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("### Filter the cases")
        classes = st.multiselect("Missing control", sorted(frame["control_class"].unique()))
        severities = st.multiselect(
            "Harm severity (MIT)",
            [MIT_LEVELS[l] for l in MIT_ORDER if l in set(frame["mit_level"])],
        )
        grades = st.multiselect("Evidence grade", sorted(frame["evidence_grade"].unique()))
        directed = st.multiselect(
            "Who directed the agent",
            [v for v in ("Deployer", "Attacker", "No one") if v in set(frame["directed_by"])],
        )
        query = st.text_input("Search", placeholder="Case, deployer, pattern")
        counted_only = st.checkbox("Only rows that feed the numbers", value=False)

    # The finding filters live in the URL so a filtered view stays shareable, even though
    # the chips that used to set them are gone.
    chosen = [k for k in st.query_params.get_all("view") if k in FINDINGS]

    show_uncounted = st.query_params.get("c") == "1"

    view = frame
    for key in chosen:
        view = view[view.apply(FINDINGS[key]["test"], axis=1)]
    # A card says "17 of 20", and 20 is the counted rows. Its button therefore has to
    # land on 17 rows, not on 18 with a grade C row quietly making up the difference.
    uncounted_matches = int((~view["counted"]).sum()) if chosen else 0
    if chosen and not show_uncounted:
        view = view[view["counted"]]
    if classes:
        view = view[view["control_class"].isin(classes)]
    if severities:
        view = view[view["mit_level"].map(MIT_LEVELS).isin(severities)]
    if grades:
        view = view[view["evidence_grade"].isin(grades)]
    if directed:
        view = view[view["directed_by"].isin(directed)]
    if counted_only:
        view = view[view["counted"]]
    if query:
        needle = query.lower()
        columns_to_search = [
            "id", "title", "deployer", "failure_pattern", "control_class", "directed_by",
        ]
        view = view[view[columns_to_search].apply(
            lambda r: needle in " ".join(r).lower(), axis=1
        )]
    view = view.sort_values("id")

    st.markdown("---")
    if chosen:
        heading = " and ".join(
            FINDINGS[k]["heading"].format(n=len(view)) for k in chosen
        )
        denominator = f"{facts['total']} counted cases"
    else:
        heading = f"All {len(view)} cases"
        denominator = f"{len(frame)} cases"
    st.markdown(f"#### {esc(heading)}")

    left, right = st.columns([3, 1])
    left.markdown(f"**Showing {len(view)} of {denominator}**")
    right.download_button(
        "Download the data", data=DATA_FILE.read_bytes(),
        file_name="ai_agent_incident_register.csv", mime="text/csv",
        on_click="ignore", width="stretch",
    )
    if chosen and uncounted_matches and not show_uncounted:
        plural = "case matches" if uncounted_matches == 1 else "cases match"
        st.caption(
            f"{uncounted_matches} more {plural} but "
            + ("is" if uncounted_matches == 1 else "are")
            + " grade C and not counted. ["
            + ("Show it" if uncounted_matches == 1 else "Show them")
            + f"]({_home_link(chosen, show_uncounted=True)})"
        )
    if chosen:
        st.caption(
            "Filtered by: " + ", ".join(FINDINGS[k]["chip"] for k in chosen)
            + ". [Clear](?)"
        )

    if view.empty:
        st.info("No cases match these filters. [Clear them](?) and try again.", icon="🔍")
        return

    st.markdown(
        case_table(
            view,
            case_href=lambda case_id: _home_link(
                chosen, show_uncounted=show_uncounted, case=case_id
            ),
        ),
        unsafe_allow_html=True,
    )
    st.caption(
        "Colour means one thing here: how severe the harm was, on MIT's scale. Every pill "
        "carries the word and a bar meter too. Grade A is filled, B outlined, C dashed."
    )

    # No case opens by default. A record the reader did not ask for pushes the table off
    # the screen and makes one arbitrary case look like the featured one.
    st.markdown('<div id="full-record"></div>', unsafe_allow_html=True)
    wanted = st.query_params.get("case")
    ids = list(view["id"])
    if wanted not in ids:
        st.markdown("---")
        st.markdown("Click a case ID to read its full record.")
    else:
        row = frame[frame["id"] == wanted].iloc[0]
        st.markdown("---")
        st.markdown(
            f"#### Full record: {esc(row['id'])} · {esc(row['title'])}  "
            f"[Close]({_home_link(chosen, show_uncounted=show_uncounted)})"
        )
        incident_card(row)

    st.markdown("---")
    foot = st.columns(3)
    foot[0].caption(f"Version {VERSION} · {UPDATED} · Built by Sana Asif Ahmad")
    foot[1].caption(
        "Every number is computed from data/incidents.csv and "
        "data/case_harm_ratings.csv, and uses grade A and B rows only."
    )
    foot[2].caption(
        "Not legal advice and not a compliance assessment. Use it to generate questions "
        "about your own system, not conclusions about somebody else's."
    )


# ------------------------------------------------------------------------ watch list


def screen_watchlist(frame, rules):
    st.title("Build your watch list")
    st.markdown(
        "Six plain questions about your own agent. The answers trigger fixed rules and "
        "return the tests to run before launch and the signals to watch after. Nothing "
        "here is generated, so every line shows the rule that produced it and the "
        "incidents behind that rule."
    )
    st.info(
        "No model runs in this tool and nothing you answer is stored or sent anywhere. "
        f"The rules are in rules/watchlist_rules.json, version {rules['version']}.",
        icon="🔒",
    )

    answers = {}
    st.markdown("### The six questions")
    for question in rules["questions"]:
        choice = st.radio(
            f"**{question['id']}. {question['text']}**",
            ["Not sure yet", "Yes", "No"],
            horizontal=True,
            key=f"answer_{question['id']}",
        )
        st.caption(question["plain"])
        if choice == "Yes":
            answers[question["id"]] = True
        elif choice == "No":
            answers[question["id"]] = False

    selected = engine.evaluate(answers, rules)
    unanswered = [q["id"] for q in rules["questions"] if q["id"] not in answers]

    st.markdown("---")

    st.markdown("---")
    st.markdown("### Who holds these controls in your organisation?")
    st.markdown(
        "This register names organisations and never individuals, and that is the "
        "stronger version rather than the cautious one. A name is unusable to you. A "
        "**role** is a lookup into your own org chart. These are the roles that came up "
        f"across all {headline(frame)['all_rows']} cases, and the useful exercise is to put a "
        "name against each one for your own agent and see which lines you cannot fill."
    )
    role_rows = sorted(headline(frame)["roles"].items(), key=lambda item: (-item[1], item[0]))
    template = pd.DataFrame(
        [{"Role": name, "Cases": count, "Who is this in your organisation?": ""}
         for name, count in role_rows]
    )
    # The return value, not session state. Session state holds a pending-edits object
    # rather than the frame. on_click="ignore" keeps the download from re-running the
    # script, which would otherwise throw away whatever the reader has typed.
    edited = st.data_editor(
        template,
        key="roles_checklist",
        num_rows="fixed",
        hide_index=True,
        width="stretch",
        column_config={
            "Role": st.column_config.TextColumn("Role", width=300, disabled=True),
            "Cases": st.column_config.NumberColumn(
                "Cases", width=80, disabled=True,
                help="Cases out of 11 where this role was the one that mattered.",
            ),
            "Who is this in your organisation?": st.column_config.TextColumn(
                "Who is this in your organisation?", width="large", max_chars=120,
            ),
        },
    )
    st.download_button(
        "Download your filled checklist",
        data=edited.to_csv(index=False).encode("utf-8"),
        file_name="roles-checklist.csv",
        mime="text/csv",
        on_click="ignore",
        help="Type into the third column first. Your answers stay in your browser.",
    )
    st.caption(
        "Type into the third column and download it. Each case names the role that runs "
        "the control and the role that answers when it fails, which are rarely the same. "
        "A row you cannot fill is the finding, and it is the row worth taking to whoever "
        "owns the agent."
    )

    if not answers:
        st.markdown("### Your list")
        st.info(
            "Answer the questions above and the list builds itself as you go. Two items "
            "apply to every agent regardless of the answers, and they are already waiting "
            "below.",
            icon="👆",
        )
        with st.expander("See the two that apply to every agent"):
            for rule in selected:
                st.markdown(f"**{rule['id']}. {rule['title']}**")
                st.caption(rule["test"])
        st.caption(
            "This is a starting point built from 12 public cases, not an assessment of "
            "your system."
        )
        return

    st.markdown(f"### Your list, {len(selected)} items")

    if unanswered:
        note = (
            "Still unanswered: " + ", ".join(unanswered) + ". Those questions trigger no "
            "rules, so your list is shorter than it should be."
        )
        if {"Q1", "Q6"} & set(unanswered):
            note += (
                " An agent nobody can say whether it can delete data, or whether a person "
                "approves what it does, is itself a finding. Go and find out before you "
                "use this list."
            )
        st.warning(note, icon="⚠️")

    # Q6 is "does a person approve", so a yes there is the narrow case rather than a risk.
    # Counting it inside any() made this branch unsatisfiable and the message never showed.
    risk_answers = [value for key, value in answers.items() if key != "Q6"]
    if answers and not any(risk_answers) and answers.get("Q6") is True:
        st.success(
            "A read-only agent with a person approving its actions is the narrowest case "
            f"in this register, and {_narrowest(frame)} of the {headline(frame)['all_rows']} "
            "cases still apply to it.",
            icon="✅",
        )

    categories = {}
    for rule in selected:
        categories[rule["nist_800_4_category"]] = categories.get(rule["nist_800_4_category"], 0) + 1
    if categories:
        st.caption(
            "By NIST AI 800-4 monitoring category: "
            + ", ".join(f"{name} {count}" for name, count in sorted(categories.items()))
        )

    titles = dict(zip(frame["id"], frame["title"]))
    for rule in selected:
        with st.expander(f"{rule['id']} · {rule['title']}", expanded=False):
            st.markdown(f"**Why this is on your list.** {esc(rule['triggered_by'])}")
            st.warning(
                f"**Test before launch.** {esc(rule['test'])}\n\n"
                f"**Pass mark.** {esc(rule['pass_mark'])}",
                icon="🧪",
            )
            st.success(f"**Signal after launch.** {esc(rule['signal'])}", icon="📈")
            st.markdown(
                f"- **Owner.** {esc(rule['owner_role'])}\n"
                f"- **Monitoring category, NIST AI 800-4.** {esc(rule['nist_800_4_category'])}\n"
                f"- **Failure pattern, OWASP Agentic Top 10 2026.** {rule['owasp_code']}, "
                f"{OWASP_CODES[rule['owasp_code']]}"
            )
            st.markdown("**Incidents behind this rule**")
            for incident in rule["incident_ids"]:
                st.markdown(f"- **{incident}** {esc(titles.get(incident, 'not found'))}")
            st.markdown(f"**What those cases show.** {esc(rule['why'])}")



    st.markdown("---")
    if selected:
        st.download_button(
            "Download your watch list",
            data=engine.to_markdown(selected, answers, rules),
            file_name="agent_watch_list.md",
            mime="text/markdown",
            type="primary",
        )
    st.caption(
        "This is a starting point built from 12 public cases, not an assessment of your "
        "system. It will miss risks specific to your setting, and passing every test here "
        "does not make an agent safe."
    )


# ---------------------------------------------------------------------------- method


def _narrowest(frame):
    """Cases a read-only agent with a human approval step still applies to. Computed."""
    acts = {"Write", "Delete", "Pay", "Promise"}
    return int(
        frame.apply(
            lambda row: not (acts & set(row["authority"].split("|")))
            and row["human_approval"].startswith("Yes"),
            axis=1,
        ).sum()
    )


def _leads():
    """How many leads were checked and not included. Read from the file, never typed."""
    path = Path(__file__).parent / "data" / "leads" / "considered_not_included.csv"
    with open(path, encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def screen_method(frame, rules):
    st.title("Method")
    st.markdown(f"Version {VERSION}, last updated {UPDATED}. Single coder.")
    st.markdown(
        "This page is the argument for trusting the register, and the fastest way through "
        "it is to start with what it cannot do. **Limits** is four sections down and names "
        "four weaknesses: the sample is biased along the same axis the headline measures, "
        "the ISO/IEC 42001 clause numbers come from the standard's structure rather than "
        "its paywalled text, one person coded every row, and the secondary class has no "
        "rubric. The **change log** at the bottom records every correction, including the "
        "ones that went against this project. If you only read two things here, read those."
    )

    st.markdown("### What counts as a case")
    st.markdown(
        "> A case where an AI system that could act or make promises for an organisation "
        "caused harm or a near miss in real use.\n\n"
        "Three parts of that sentence do the work. **Act or make promises** keeps out "
        "systems that only produce text for a person to check. **For an organisation** "
        "keeps out individuals experimenting on their own. **In real use** keeps out "
        "laboratory demonstrations, with one exception noted below."
    )
    st.markdown(
        "The one exception is a demonstrated vulnerability in a widely deployed agent, "
        "recorded as a hazard rather than an incident. A zero-click data exfiltration path "
        "in an assistant with access to a company's mail and files is a control failure "
        "whether or not anyone is known to have used it."
    )

    st.markdown("### Two kinds of count, and which is which")
    st.markdown(
        f"**Descriptive counts** describe what is in the register and cover all "
        f"{len(frame)} rows, including the grade C one. **Analytical counts** are any "
        f"number used to support a claim, and those use only the {int(frame['counted'].sum())} "
        "grade A and grade B rows. Every table below says which it is. The validator "
        "enforces three things on this: that the function producing the headline filters "
        "to counted rows, that the two sets of figures genuinely differ so the rule is not "
        "doing nothing, and that the order-independent floor never exceeds the "
        "ordered-rubric count."
    )

    st.markdown("### Which cases get in")
    st.markdown(
        "Dated 11 October 2026 and committed before any case was added under it. A lead "
        "is included only if it passes all six tests."
    )
    tests = [
        ("1. Agent action", "An AI agent took an action, a tool call, a data change or deletion, a send, a purchase, a post, or made a commitment binding an organisation. Not output that nobody acted on. Not robotics or vehicles."),
        ("2. Harm", "Actual harm, or a near miss confirmed by the organisation."),
        ("3. Organisation", "At least one named organisation, deployer, platform or vendor, whose control failed. Personal use only is excluded."),
        ("4. Evidence", "Grade A or B: a primary record, meaning a postmortem, advisory, CVE, ruling, regulator notice or company statement, plus one independent report."),
        ("5. Traceable", "The record describes the sequence well enough to name the missing control."),
        ("6. Window", "Event and publication both between 1 January 2025 and 30 September 2026, and not already in the register."),
    ]
    st.markdown(
        '<div class="case-table-wrap"><table class="cases"><thead><tr><th>Test</th>'
        "<th>What it asks</th></tr></thead><tbody>"
        + "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td></tr>" for a, b in tests)
        + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "**Census, not selection.** Every lead that passes is included. The inclusion "
        "decision never looks at a case's missing-control class, its severity or whether "
        "the agent said something untrue, because those are the things the findings "
        "count. They are coded after a case is in."
    )
    pre = int((frame["inclusion"] == "Included before the inclusion rule").sum())
    st.markdown(
        f"**{pre} of the {len(frame)} cases predate this rule** and are marked *Included "
        "before the inclusion rule* on their cards. A rule written after the fact cannot "
        "be claimed to have governed the cases that came first. Every lead that was "
        "checked and not admitted is listed in data/leads/considered_not_included.csv "
        "with the test it failed, so the shape of what the evidence rule excluded can be "
        "seen rather than guessed at."
    )

    st.markdown("### Incident or hazard")
    for kind, meaning in KIND_MEANING.items():
        count = int((frame["incident_or_hazard"] == kind).sum())
        counted_count = int(((frame["incident_or_hazard"] == kind) & frame["counted"]).sum())
        st.markdown(f"- **{kind}** ({describe_count(count, counted_count)}). {meaning}")
    st.caption(
        "Descriptive. These follow the OECD AI Incidents and Hazards Monitor definitions."
    )

    st.markdown("### Evidence grades")
    st.markdown(
        "Only grade A and grade B rows feed a number anywhere on this site. That rule is "
        "enforced by the validator, not by me remembering it."
    )
    grade_rows = []
    for grade, meaning in GRADE_MEANING.items():
        grade_rows.append({
            "Grade": grade,
            "Rows": int((frame["evidence_grade"] == grade).sum()),
            "Counted": "Yes" if grade in COUNTED_GRADES else "No",
            "What it means": meaning,
        })
    st.markdown(
        "| Grade | Rows | Counted | What it means |\n| --- | --- | --- | --- |\n"
        + "\n".join(
            f"| {r['Grade']} | {r['Rows']} | {r['Counted']} | {r['What it means']} |"
            for r in grade_rows
        )
    )
    st.markdown(
        "A grade B row needs two reports on two different sites, and in practice usually "
        "includes the deployer's own public statement. Where the deployer confirmed the "
        "event but the harm is known only from reporting, the row stays at B rather than "
        "rising to A. The register keeps one grade C row, labelled on its card and "
        "excluded from every count, because dropping it would hide a failure pattern that "
        "no counted row shows as plainly."
    )
    st.markdown(
        "**A note on sources, which turned into a finding of its own.** Searching for these "
        "cases returns a large volume of pages that read as incident write-ups but are "
        "generated summaries of other summaries, often with invented detail and no primary "
        "record. Several candidate cases were dropped because no primary source existed "
        "behind the reporting. If you build something similar, budget most of your time "
        "for verification rather than for finding cases."
    )

    st.markdown("### The coding rubric")
    st.markdown(
        "Each row gets exactly one class for what the missing control governed. The rubric "
        "is applied in the order below, so the first match wins and a row cannot be "
        "classed twice."
    )
    rubric = [
        ("1. Vendor", "The failure arrived through a third party that held access to the organisation."),
        ("2. Boundary", "The agent acted on instructions that came from content it read rather than from its operator."),
        ("3. Authority", "The agent was able to take an action it should not have been able to take at all."),
        ("4. Oversight", "No person was positioned to catch it, stop it, or verify the claim the deployment ran on."),
        ("5. Accuracy", "What is left. The agent stated something untrue and nothing checked it against the source."),
    ]
    st.markdown(
        "| Order | Class | The test applied |\n| --- | --- | --- |\n"
        + "\n".join(
            f"| {name.split('.')[0]} | {name.split('. ')[1]} | {test} |"
            for name, test in rubric
        )
    )
    st.caption(
        "Accuracy is last on purpose. An agent that says something wrong and an agent that "
        "deletes a database both look like accuracy problems if accuracy is the first "
        "question you ask."
    )

    st.markdown(
        "Every row also carries a `secondary_class`: the reading the ordered rubric "
        "discarded. It is recorded on the card, it is never counted anywhere, and it "
        "exists because first-match-wins twice threw away a classification that had "
        "already been identified as real. AIR-009 is the clearest: a vendor compromise "
        "that nobody detected for months is an oversight failure as well as a vendor one, "
        "and Vendor simply gets tested first."
    )

    st.markdown("#### What that ordering does to the finding")
    facts = headline(frame)
    st.markdown(
        "Putting accuracy last is a choice, and a choice that could manufacture the "
        "result. If a case is both a permissions failure and an accuracy failure, this "
        "rubric classes it as the former. So the register measures the effect rather than "
        "asking to be trusted on it."
    )
    st.markdown(
        f"| Ordering | Cases classed as not accuracy |\n| --- | --- |\n"
        f"| Accuracy last, as published | {facts['not_accuracy']} of {facts['total']} |\n"
        f"| Accuracy first | {facts['accuracy_first']} of {facts['total']} |"
    )
    st.warning(
        "**These are two numbers, not three, and an earlier version of this page implied "
        "otherwise.** Under this coding, testing accuracy first classes a row as Accuracy "
        "exactly when the agent stated something untrue, so 'accuracy first' and 'the "
        "agent stated nothing untrue' are the same computation under two names. Showing "
        "both as separate rows would be showing one result twice and calling it "
        "corroboration. A reviewer caught that and it is recorded in the change log.",
        icon="⚠️",
    )
    st.markdown(
        f"**{facts['would_change_class']} rows change class** when accuracy is tested "
        f"first (AIR-002, AIR-011, AIR-012), so the published ordering accounts for a real "
        f"part of the gap. {facts['accuracy_first']} of {facts['total']} is therefore the "
        "floor, and the home screen headline uses it rather than the larger number. Every "
        "row carries a `said_something_untrue` field recorded independently of its class. "
        "The one genuinely arguable row, AIR-012, is marked as having stated something "
        "untrue, which counts against this finding rather than for it."
    )
    st.markdown(
        "**What the ordering cannot touch.** The finding the register actually rests on is "
        "structural rather than a count. In none of the counted cases was an untrue "
        "statement sufficient on its own: harm always also required authority the agent "
        "should not have held, reach it should not have had, or a path nobody was "
        "monitoring. Rearranging the rubric changes which bucket a row sits in. It does "
        "not produce a single case where a wrong answer alone did the damage."
    )

    st.markdown("### Why these two scales")
    st.markdown(
        "Severity is reported on two recognised scales, because they answer different "
        "questions and neither answers the other's.\n\n"
        "- **How big was this, compared with all AI harm?** MIT's harm severity "
        "framework, five levels across ten harm types, built on CSET's Taxonomy of AI "
        "Harm as modified by MIT. It puts these cases on the same scale as the 1,700-odd "
        "incidents in MIT's own tracker.\n"
        "- **Would it cross the EU AI Act's serious-incident threshold?** Article 3(49). "
        "A legal reporting threshold rather than a measure of size, recorded as the "
        "closest limb and never as a legal classification."
    )
    st.markdown(
        "**The register used to carry its own four-level scale: Negligible, Moderate, "
        "Serious, Severe.** It had no external source. It was written for this register "
        "and it ranked the twelve cases it then covered against each other, which meant its "
        "middle was wherever those cases happened to sit. It has been retired rather than converted, "
        "and the old labels are gone from the site and from the data, because the word "
        "Severe does not mean on MIT's scale what it meant on that one."
    )
    st.caption(
        "NIST SP 800-61 Rev 2's impact tables were considered and not used: Rev 2 was "
        "withdrawn on 3 April 2025."
    )

    st.markdown("### Naming policy")
    st.markdown(
        "**This policy governs people who appear in the cases.** Deployers and vendors are "
        "named, because the public record names them and a register of anonymous cases "
        "cannot be checked. Individuals in the cases are not named, including the people "
        "who found these failures and the staff involved, even where reporting names them. "
        "The one exception is a named party to a published legal or regulatory decision, "
        "where the name is part of the citation.\n\n"
        "**Contributors to the register are a separate matter and are named with their "
        "consent.** A reviewer who reads this cold is doing work in their own name and "
        "should get the credit for it, which is the opposite of the situation the policy "
        "above protects against."
    )

    st.markdown("### The watch list")
    st.markdown(
        f"Six questions, {len(rules['rules'])} fixed rules, version {rules['version']}. No "
        "model runs in the tool. Each question maps to rules by a trigger written in the "
        "rule file, and the validator fails if a question triggers nothing, if a rule "
        "points at an incident that does not exist, or if a rule carries a category or a "
        "pattern code outside the published taxonomies."
    )
    trigger_rows = []
    for question in rules["questions"]:
        fired = [r["id"] for r in rules["rules"] if r["trigger"].startswith(question["id"])]
        trigger_rows.append({
            "Question": f"{question['id']}. {question['text']}",
            "Rules it can trigger": ", ".join(fired),
        })
    trigger_rows.append({
        "Question": "Applies to every agent",
        "Rules it can trigger": ", ".join(r["id"] for r in rules["rules"] if r["trigger"] == "always"),
    })
    st.markdown(
        "| Question | Rules it can trigger |\n| --- | --- |\n"
        + "\n".join(f"| {r['Question']} | {r['Rules it can trigger']} |" for r in trigger_rows)
    )

    st.markdown("### Standards and frameworks used")
    st.markdown(
        "Each one links to the thing itself, not to a summary of it. That is the same bar "
        "the incident rows are held to.\n\n"
        "- **[NIST AI RMF 1.0](https://doi.org/10.6028/NIST.AI.100-1).** The closest "
        "subcategory per row, for the control that was missing.\n"
        "- **[NIST AI 800-4](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.800-4.pdf), "
        "March 2026.** A research report, not a standard. It proposes six monitoring "
        "categories and this register uses them to tag every signal: functionality, "
        "operational, human factors, security, compliance, large-scale impacts.\n"
        "- **ISO/IEC 42001:2023 Annex A.** Mostly A.6.2.6 on operation and monitoring, "
        "A.6.2.8 on event logs, A.8.4 on communication of incidents and A.10.3 on "
        "suppliers. Deliberately unlinked, because the standard is paywalled and a link "
        "to a shop is not a link to the text. See the limits below.\n"
        "- **[EU AI Act, Regulation (EU) 2024/1689]"
        "(https://eur-lex.europa.eu/eli/reg/2024/1689/oj).** Articles 9, 14, 15, 26, 50 "
        "and 73 as closest clauses. Article 3(49) defines a serious incident, which is the "
        "threshold the reporting duty in Article 73 hangs on.\n"
        "- **[OWASP Top 10 for Agentic Applications 2026]"
        "(https://genai.owasp.org/2025/12/09/owasp-genai-security-project-releases-top-10-"
        "risks-and-mitigations-for-agentic-ai-security/),** published 9 December 2025, for "
        "the failure pattern code. All ten codes and names were read on 10 October 2026 "
        "from [OWASP's own coded list](https://genai.owasp.org/2025/12/09/owasp-top-10-"
        "for-agentic-applications-the-benchmark-for-agent). OWASP's press release of the "
        "same day describes the same risks in looser wording and without codes, so this "
        "register follows the page that gives the codes. The allowed values live in "
        "frameworks/owasp_agentic_2026.csv with their source and retrieval date, and the "
        "validator reads that file rather than a list typed into the code. Each case also "
        "records whether its code was applied by OWASP or by this register.\n"
        "- **[Commission draft guidance and reporting template for serious AI incidents]"
        "(https://digital-strategy.ec.europa.eu/en/consultations/ai-act-commission-issues-"
        "draft-guidance-and-reporting-template-serious-ai-incidents-and-seeks).** A "
        "September 2025 draft. The fields on each incident card were shaped to sit close "
        "to it, so a row here can be lifted into that template rather than rewritten. "
        "Check whether a final version has landed before relying on it."
    )

    st.markdown("### Where the cases were found")
    st.markdown(
        "Finding a case and admitting a case are different steps, and only the second one "
        "has a rule. These three were used to build the candidate list. None of them "
        "decides what goes in. The evidence rule does that, and every candidate had to "
        "survive it independently of where it came from.\n\n"
        "- **[AI Incident Database](https://incidentdatabase.ai/).** Indexed incidents with "
        "linked reports. Useful for finding, never cited as the evidence for a row, "
        "because an aggregator indexing other people's reporting is weaker than the "
        "reporting.\n"
        "- **[OECD AI Incidents and Hazards Monitor](https://oecd.ai/en/incidents-methodology).** "
        "News-derived candidates, and the incident versus hazard definitions this register "
        "uses.\n"
        "- **[Cyera, Agent-Inflicted Damage](https://www.cyera.com/research/agent-inflicted-"
        "damage-inside-the-real-world-failures-of-enterprise-ai-systems).** A vendor study "
        "of agent-caused cases, treated as a lead list only. A security vendor counting "
        "security failures has an interest in the total, which is the same structural "
        "problem this register discloses about its own sample.\n\n"
        "Field names and definitions follow the [OECD common reporting framework]"
        "(https://one.oecd.org/document/DSTI/DPC/GPAI(2024)5/FINAL/en/pdf) where they map "
        "cleanly onto the fields here."
    )

    st.markdown("### Limits")
    st.markdown(
        "- **One coder.** Every judgement on this site is mine. There is no second rater and "
        "no inter-rater reliability figure, so the coding should be read as one defensible "
        "reading rather than as a measurement.\n"
        "- **The secondary class has no rubric.** The primary class is assigned by an "
        "ordered, published, first-match-wins test. The secondary class, added in version "
        "0.9.9 to record the reading that ordering discards, was assigned case by case "
        "with no rule behind it. It is shown on cards and counted nowhere, and that is "
        "deliberate: a matrix built on it would display one person's unruled judgement as "
        "structure. Oversight is the tell. It wins the primary test twice and was "
        "assigned as a secondary six times.\n"
        "- **The rubric is stated, not pre-registered.** It was written before the rows "
        "were coded, but the rule file and the data file were first committed together, so "
        "nothing in the repository proves that order and you should not take my word for "
        "it. From version 0.9 onward any change to the rubric lands in its own commit "
        "ahead of any recoding, which makes the claim checkable from here forward even "
        "though it is not checkable backward.\n"
        "- **The sampling frame runs along the axis the finding measures.** This is the "
        "sharpest objection to this register and it deserves to be made here rather than "
        "by someone else. Primary records exist for events that produce legal, security or "
        "regulatory paperwork: rulings, CVEs, threat intelligence reports, enforcement "
        "notices. Those are disproportionately the authority, boundary and vendor cases. A "
        "chatbot that quietly gave wrong answers for a year generates no such document, so "
        "accuracy failures are systematically harder to admit to this register. The "
        "evidence rule that makes every row checkable is the same rule that biases the "
        "sample toward the finding. Read the headline as a floor on the non-accuracy "
        "cases, not as a ratio between the two.\n"
        "- **Fixing the rubric did not fix this.** Version 0.9 measured what the rubric's "
        "ordering was doing and rewrote the headline around the part that survives it. "
        "That closes one threat and leaves this one standing, and the two are often "
        "confused. The cases where the agent stated nothing untrue are largely the "
        "security and legal ones, which are precisely the cases that generate primary "
        "records, so the current headline is at least as exposed to this bias as the one "
        "it replaced. The repair was to publish the long list of candidates that were "
        "considered and dropped, with the test each failed, so the shape of what the rules "
        f"excluded can be read rather than guessed at. That is now done: {_leads()} leads are "
        "listed in data/leads/considered_not_included.csv, and the largest group by far is "
        "cases where an AI system produced text and a person read it, which this register "
        "excludes by design and which is where most public reporting of AI harm sits.\n"
        "- **The clearest case this rule excludes.** In February 2026 a coding agent ran "
        "terraform destroy against the production infrastructure of a course platform, "
        "taking the database, the environment and every automated backup with it, and about "
        "two and a half years of student submissions. The founder published a detailed "
        "first-hand postmortem naming the stale state file, the auto-approve, the row count "
        "and the recovery, and it even records that the agent advised against the approach "
        "and a person approved anyway. It is not in this register. No reputable independent "
        "outlet covered it, so a single source makes it grade C, and the inclusion rule "
        "admits only A and B. That is the rule excluding a case documented better than "
        "several that are in, and the trade is deliberate: the bar is set on what a reader "
        "can check from two directions, not on how good the one account is. It is listed in "
        "the considered and not included table with that reasoning.\n"
        "- **Three rows rest on one party's account.** AIR-013, AIR-020 and AIR-021 are "
        "graded B with a reputable outlet as the second source, and in each case that outlet "
        "is reporting the primary account rather than verifying it. No indicators of "
        "compromise, no victim statement and no third-party investigation exist for any of "
        "them. They clear grade B, which asks for two independent reputable reports, and "
        "they would not clear grade A, which asks the second source to corroborate rather "
        "than restate. Read them as the organisation's own account, carefully written and "
        "unverified.\n"
        "- **A convenience sample, not a population.** These cases are the ones with "
        "a usable public record. Agent failures that were handled quietly are the majority "
        "and none of them are here, which also biases the counts toward the visible and "
        "the embarrassing.\n"
        f"- **{headline(frame)['total']} is a small number.** A count this size is an "
        "illustration of a pattern, not evidence of its distribution. Treat the finding as a hypothesis worth testing "
        "against your own incidents.\n"
        "- **Closest clause, not legal classification.** The clause references are the "
        "nearest fit for a reader who needs a starting point. Whether any obligation "
        "actually applies depends on the role, the system and the jurisdiction. This is not "
        "legal advice.\n"
        "- **Tests are not proof.** Every test on this site is a test that would have caught "
        "the specific failure described. Passing all of them does not make an agent safe.\n"
        "- **Every structural correction in this log was prompted by a reader.** The "
        "checks catch regressions, not errors of judgement. The validator has never once "
        "told this project that a framing was wrong, a count was misleading or a claim "
        "outran its source. People did that, every time, and the automation's job turned "
        "out to be holding the line afterwards rather than finding it.\n"
        "- **This register has already produced its own example of a control that was "
        "implemented and not operating.** The repository has a validator, a test suite and "
        "a green build. While all three were passing, a maintenance script was writing back "
        "a stale copy of the data file and silently reverting edits made while it ran. One "
        "published commit carried a reverted account of AIR-001, with a fact in the "
        "deployer's favour missing from it, and the build was green throughout. Nothing in "
        "the checks was watching for it, because the checks validate the file's contents "
        "and not whether the contents are the ones somebody meant to write. An audit of "
        "every commit that touched the data has since bounded the damage to that one row, "
        "two fields and one commit. It happened twice: a crash on the register screen also "
        "survived six green builds, because the build parsed the app and never rendered "
        "it. The register codes that failure mode as Implemented in other people's "
        "systems, and it is the honest label for both of these.\n"
        "- **The clause references have not been line-checked against every official text.** "
        "The NIST AI RMF and the EU AI Act are public and were used directly. ISO/IEC 42001 "
        "is paywalled, and the Annex A control numbers here come from the standard's "
        "published structure rather than from a reading of the clause text, because "
        "secondary sites disagree on the numbering and do not count as a check. Treat the "
        "ISO column as the weakest part of this register, and corrections to it are the "
        "most useful thing you can send."
    )

    st.markdown("### Dates that matter")
    st.markdown(
        "The Digital Omnibus on AI is [Regulation (EU) 2026/1744]"
        "(https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32026R1744) of 8 July "
        "2026, published in the Official Journal on 24 July 2026 and in force from the "
        "third day after that. It moved some AI Act deadlines and left others alone, and "
        "the difference matters for how you read the clause column.\n\n"
        "| Obligation | Applies from | Where this came from |\n| --- | --- | --- |\n"
        "| Article 50 transparency | 2 August 2026, already in force | **Derived.** Article 113 sets a general application date of 2 August 2026 and does not list Chapter IV among its exceptions. Read from a consolidated rendering, not the Official Journal page itself. |\n"
        "| Article 50(2) machine-readable marking, for systems placed on the market before 2 August 2026 | 2 December 2026 | **Derived** from the four month transitional period in Regulation (EU) 2026/1744, whose recital text was read on EUR-Lex. The regulation gives the period, not the date. |\n"
        "| High-risk, standalone Annex III systems | 2 December 2027 | **Official Journal text** on EUR-Lex |\n"
        "| High-risk, AI embedded in Annex I regulated products | 2 August 2028 | **Official Journal text** on EUR-Lex |\n"
    )
    st.markdown(
        "**Two of these four are derived rather than quoted, and that distinction matters "
        "more here than anywhere else on this page.** These are the claims a lawyer in the "
        "audience knows better than I do, and an earlier version of this page took them "
        "from legal commentary without saying so. The regulation number, its entry into "
        "force and the two high-risk dates were since read on EUR-Lex. The Article 50 "
        "dates were not quoted from an article that states them, they were worked out from "
        "Article 113's structure and from a transitional period given in months. That "
        "reasoning is shown so you can check it rather than trust it, and a correction "
        "here is the most useful one you could send."
    )
    st.markdown(
        "The practical point for this register is that the chatbot cases are not waiting on "
        "a future deadline. Article 50 has applied since August 2026, so a deployer whose "
        "customer-facing agent misstates its own policy today is already inside a live "
        "transparency regime, not a forthcoming one."
    )

    st.markdown("### Corrections")
    st.markdown(
        "Corrections are recorded in the change log below with the date and what changed. "
        "A register nobody corrects is a blog post, so the log is kept whether or not "
        "anyone is asked to read it."
    )

    st.markdown("### Change log")
    st.markdown(
        "| Version | Date | What changed |\n| --- | --- | --- |\n"
        "| 1.0 | 2026-10-13 | **The release broke the live site, and the cause is this "
        "register's own subject.** v1.0 reached the hosted app as a KeyError on the home "
        "screen. The data loaders were cached, and the cache keys on the function's code "
        "and arguments rather than on the files it opens. Adding a column to the case data "
        "left that key identical, so new code ran against a table cached before the column "
        "existed. Every local check passed because each run starts with an empty cache, "
        "which is the difference between a control that is implemented and one that is "
        "operating. The loaders now take a stamp built from the data files, so the cache "
        "falls when the data changes. The site was broken for the time between the push "
        "and this fix. |\n"
        "| 1.0 | 2026-10-12 | **Pre-merge review.** AIR-021 moved from grade A to B: its "
        "only readable independent coverage is substantially a summary of the institute's "
        "own report, and grade A asks the second source to corroborate rather than restate. "
        "A read audit of every source on the nine new cases found four cited on a "
        "reachability check rather than a reading, and all four have now been read: two "
        "needed no change, one produced that regrade, and one had already been caught. Ten "
        "of the ninety four title-stage rejections were drawn at random with a recorded "
        "seed and checked in depth. None was wrongly rejected, so the remaining eighty four "
        "were not re-screened, but two had the wrong test named and were corrected. A new "
        "field records who pointed the agent at the harm, with a basis on every row, shown "
        "on the cards and in the filters. The three Home cards were re-picked for twenty "
        "cases. Two dead code paths were removed: a duplicate findings table that silently "
        "overwrote the one above it, and a stale comment. |\n"
        "| 1.0 | 2026-10-12 | **Release. Twelve cases to twenty one, eleven counted to twenty.** "
        "Every number below is recomputed from the data on each page load, including the case "
        "count itself. Old is version 0.9, new is this release. Said nothing untrue 5 of 11 to "
        "10 of 20. Record silent on who could stop it 10 of 11 to 19 of 20. Control never built "
        "6 of 11 to 9 of 20. Control existed and did not hold 1 of 11 to 6 of 20, plus one case "
        "in a new state, Bypassable, where the gate was built and the caller could switch it "
        "off. Missing control was not accuracy 8 of 11 to 17 of 20. Read-only agents 6 of 11 to "
        "6 of 20, the only count that did not move at all. Evidence grades 5 A and 6 B to 7 A "
        "and 13 B. Endings 8 documented, 2 partial, 1 undocumented to 14, 5 and 1. Severity on "
        "MIT's scale, counted rows only, 5 Minor, 5 Negligible and 1 Substantial to 7, 7 and 6. "
        "Missing control class 3 Accuracy, 3 Authority, 2 Boundary, 2 Oversight and 1 Vendor to "
        "3, 7, 6, 3 and 1. Event years unchanged at 2022 to 2026. |\n"
        "| 1.0 | 2026-10-12 | **Which findings held and which moved.** Held: no case in the "
        "register was only the AI being wrong, which is still true at 20 counted cases as it was "
        "at 11. Held and strengthened: the record is almost always silent on who could have "
        "halted the deployment, now 19 of 20, and a scheduled date to look again appears in "
        "none of the 20. Moved against the register's own framing: Accuracy did not grow at "
        "all, staying at 3 cases while Authority went from 3 to 7 and Boundary from 2 to 6, so "
        "the register is now mostly about what agents were allowed to do rather than what they "
        "got wrong. Weakened: Vendor is still a single case after nine admissions, so any "
        "statement about that class remains a description of one row. Worth saying rather than "
        "hiding: the two strongest Vendor candidates found in the census both failed, one on the "
        "organisation test and one on evidence. |\n"
        "| 1.0 | 2026-10-12 | **What the census says about selection.** 115 leads were checked "
        "and not included, each listed with the test it failed: 59 on agent action, 23 on harm, "
        "21 on organisation, 9 on evidence, 2 on traceability and 1 already in the register. "
        "That shape is the honest answer to how narrow this register is. The largest group is "
        "cases where an AI system produced text and a person read it, which the register "
        "excludes on purpose and which is where most public AI harm reporting sits. The "
        "evidence test excluded nine, including a first-hand postmortem of an agent destroying "
        "two and a half years of production data, which no reputable outlet covered. A single "
        "source is grade C and the inclusion rule admits only A and B, so the rule excluded a "
        "case better documented than some that are in. |\n"
        "| 1.0 in progress | 2026-10-12 | Census complete against the lead lists. Every lead in "
        "the window was screened and 115 are listed with the test each failed. Nine cases "
        "admitted: AIR-013 and AIR-020, two campaigns run through one platform's coding agent, "
        "one espionage and one extortion of at least seventeen organisations. AIR-015, malware "
        "that asked the agents already on a machine to find its secrets. AIR-016 and AIR-019, "
        "the same posting assistant two months apart, once after an update restored deprecated "
        "code and once after an unreviewed edit to its prompt. AIR-017, an account recovery "
        "assistant that handed accounts to whoever asked. AIR-018, a research agent that routed "
        "around a government portal's blocks and wrote to an internal server. AIR-021, an "
        "evaluation body's own agents reaching the live internet and working on real people. "
        "AIR-022, a multi-agent framework running four days of government intrusion. A tenth "
        "case was admitted and withdrawn the same day for failing the organisation test. |\n"
        "| 1.0 in progress | 2026-10-12 | Two corrections from reviewing the admitted cases. "
        "Every new case had its stop-authority answer recoded to Not disclosed. Each had been "
        "marked Yes on the strength of a platform suspending accounts, removing packages or "
        "disabling a tool after the event, which is a response and not a record of a role that "
        "could have halted the deployment. One of the original twelve still holds that answer, "
        "on a source describing sign off by two people. And AIR-016 was rewritten from the "
        "article itself after it turned out to have been drafted from a search summary, which "
        "changed what the company is quoted as saying and what it froze. |\n"
        "| 1.0 in progress | 2026-10-11 | Three method changes forced by reviewing the first "
        "batch. Grade A now requires its second source to be on a different host from the "
        "primary record and to corroborate rather than restate it, which is what moved AIR-013 "
        "to B. A fifth control state, Bypassable, was added for a gate that was built and wired "
        "in and that the caller could switch off with a documented flag, which is a different "
        "failure from a gate that engaged and did not hold. And the pre-commit hook now runs "
        "the validator: a row had been committed with the register invalid, because the "
        "validator printed the error, the output was read by its last few lines, and nothing "
        "local refused the commit. |\n"
        "| 1.0 in progress | 2026-10-11 | Lead sources amended, with the six inclusion tests "
        "unchanged. The MIT AI Incident Tracker was dropped as a lead list, because its "
        "incidents sit behind an embedded spreadsheet application rather than in the page and "
        "it is built from AI Incident Database reports in any case. The database's own weekly "
        "export is used instead, recorded in data/leads with its URL, download date and a "
        "checksum. Both remain lead lists and neither is ever cited: the denylist that keeps "
        "aggregators out of the evidence fields is unchanged. |\n"
        "| 0.9 | 2026-10-11 | Committed a dated inclusion rule before adding any case "
        "under it. Six tests, all of which must pass, with the window set to events and "
        "publication between 1 January 2025 and 30 September 2026. The decision never "
        "looks at a case's class, severity or whether the agent said something untrue, "
        "because those are what the findings count. Six of the original twelve predate "
        "the rule and are marked as such rather than retrofitted into it. The validator "
        "rejects any row claiming to have passed the rule with an event date outside the "
        "window. |\n"
        "| 0.9 | 2026-10-11 | Layout pass, no numbers changed. The case list merged into "
        "Home, which had been showing the same twelve rows under a second set of headline "
        "numbers. Removed every comment and review invitation, the citation block, the "
        "certainty strip, the shortcut links and a bar chart that labelled three of its "
        "five bars. Findings became three tabs on one pattern: a question, a one-sentence "
        "answer, a table, one line on how to read it. The severity grid became one row "
        "per case, because the grid cut off the Privacy column and hid the only "
        "Substantial case. On a card, only the severity pill is coloured now. |\n"
        "| 0.9 | 2026-10-11 | Severity moved from the register's own 4-level scale, which "
        "ranked cases against each other and had no external source, to MIT's 5-level "
        "harm severity framework (CSET-based, up to global scale). The two scales use "
        "different reference points, so old labels were retired, not converted. Each case "
        "was re-scored from its facts: 6 Negligible, 5 Minor, 1 Substantial. An EU AI Act "
        "serious-incident threshold view was added alongside it. |\n"
        "| 0.9 | 2026-10-10 | Checked OWASP labels against OWASP's own coded list. No "
        "change to codes. All ten names confirmed from the page that carries the codes, "
        "with the shorter official forms adopted and the longer forms kept as aliases. "
        "The same day's press release uses looser wording without codes, so it is not the "
        "source. AIR-010's code is now recorded as Stated, because that list cites "
        "EchoLeak as its own ASI01 example. Every framework value now carries a basis. |\n"
        "| 0.9 | 2026-10-10 | Removed the comment deadline, keeping the route and the "
        "commitment to log everything. Started the framework work by trying to verify the "
        "two lists it depends on, and did not get them. The OWASP entry names sit in a "
        "PDF behind a download form, and checking the ones that are public found OWASP's "
        "own announcement wording ASI01 differently from the secondary source this "
        "register used, on three cases. Allowed values now live in frameworks/, each with "
        "its source, retrieval date and whether the owner's own publication was reachable. "
        "The validator reads that file and warns on a disputed name, and the cards say so. "
        "The MIT scales are not coded, because their reachable pages give counts without "
        "naming the values. |\n"
        "| 0.9 | 2026-10-10 | Line-by-line fact check of Home, which found four claims "
        "the evidence did not carry. The headline said most of these failures were not "
        "the AI being wrong, which only holds under the accuracy-last rubric the page "
        "itself says the finding does not rest on. It is now the claim the validator "
        "enforces: none was only the AI being wrong. Three sentences asserted an absence "
        "with no source, including one about approval steps whose field, unlike the "
        "stop-authority field, carries no source at all. The Article 73 note claimed "
        "every row maps onto the Commission's template and could be lifted into a report, "
        "when that duty falls on providers of high-risk systems and most of these are "
        "not. Rebuilt Home as a hero, three dot cards and a certainty bar. |\n"
        "| 0.9 | 2026-10-09 | Home cut from about 2,000 words and eleven headings to 500 "
        "and four, after it was read as information overload. Nothing was deleted: the "
        "analysis moved to a Findings screen somebody can choose. Home now carries the "
        "finding, a chart of what the missing control governed, and the severity spread "
        "as a bar. Extended the displayed-number check to cover Home. |\n"
        "| 0.9 | 2026-10-09 | Redesign. Colour now means one thing, severity of harm, and "
        "every severity pill carries a four-bar meter and the word so nothing depends on "
        "colour alone. Evidence grade is monochrome and the chart is one hue. The cases "
        "screen leads with the question, three findings as tiles, and filters where each "
        "selection writes itself into the URL so a filtered view can be posted. Each case "
        "opens into five tabs, and the three cases with a runnable test name the file and "
        "class that runs it. Added a check that recomputes every number on screen from the "
        "data file and fails the build if a typed number ever diverges. |\n"
        "| 0.9 | 2026-10-09 | Reviewer rounds, consolidated. Late in the day, rebuilt the "
        "incident card into four tabs after it had accumulated thirty-two fields and six "
        "coloured boxes in one scroll, which was unreadable however correct each line "
        "was. Moved the repeated definitions to this page. Replaced the red block at the "
        "top of Method with plain text, because a page that opens on an alarm reads as an "
        "apology rather than as a method. |\n"
        "| 0.9 | 2026-10-09 | Earlier that day. Measured what the rubric's "
        "ordering does to the finding and rewrote the headline around the part that "
        "survives it. Separated descriptive counts from analytical ones. Decoupled "
        "severity from recovery effort. Corrected the EU AI Act dates against EUR-Lex, "
        "including that Article 50 is already in force, and labelled the two derived "
        "dates as derived. Withdrew the pre-registration claim and a nine second figure, "
        "both unevidenced. Audited how every story ended and corrected three accounts "
        "that stopped at the failure. Added an aggregator denylist, per-row aftermath "
        "citations, a stated basis for every severity rating, and the three deployment "
        "questions where Not disclosed is the default. Split the owner, added control "
        "maturity, and recorded who bore the harm against who could have prevented it. "
        "Marked how the register knows each missing control, in three tiers. Fixed a "
        "crash that had broken the register screen for six commits under a green build, "
        "and added a headless render of every screen to CI. Archived every source after "
        "finding the archiver was reverting hand edits. |\n"
        "| 0.8 | 2026-10-03 | First build. 12 cases, 11 counted, 18 watch-list rules. |"
    )
    st.markdown(
        "**No corrections from readers yet.** When one arrives it goes in the table above "
        "with the date, what was wrong, and who sent it."
    )

    st.markdown("### If this stops being maintained")
    st.markdown(
        "A register that quietly goes stale is worse than one that never existed, because "
        "a reader cannot tell the difference between current and abandoned. So: if "
        "maintenance stops, this page will say so. The line below is the status, and it "
        "is the first thing that changes if the project is parked."
    )
    st.success(
        f"**Status: actively maintained.** Last reviewed {UPDATED}. If this line has not "
        "moved in six months, treat the register as a static archive of what was true at "
        "that date and check every source yourself before relying on it.",
        icon="🟢",
    )

    st.markdown("### Reviewed by")
    st.markdown(
        ":orange[**Not yet reviewed.**] One practitioner read is planned, and the reviewer "
        "will be credited here by name with the date."
    )
    st.markdown(
        f"This is why the register is at version {VERSION} and not 1.0. A thing cannot be "
        "both a finished release and a single-author draft, and of the two the draft is "
        "the true one until somebody outside has read it cold. Version 1.0 is the cold "
        "read landing, not a date."
    )


# ------------------------------------------------------------------------------ main


def main():
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    frame = load_register(data_stamp(DATA_FILE, RATINGS_FILE))
    rules = load_rules(data_stamp(RULES_FILE))

    with st.sidebar:
        st.markdown("## AI Agent Incident Register")
        screen = st.radio(
            "Screen",
            ["Home", "Findings", "Build your watch list", "Method"],
            label_visibility="collapsed",
        )
        st.markdown("---")

    if screen == "Home":
        screen_home(frame, rules)
    elif screen == "Findings":
        screen_findings(frame, rules)
    elif screen == "Build your watch list":
        screen_watchlist(frame, rules)
    else:
        screen_method(frame, rules)

    with st.sidebar:
        st.caption(
            f"Version {VERSION}, {UPDATED}. {len(frame)} cases, "
            f"{int(frame['counted'].sum())} counted. Built by Sana Asif Ahmad. "
            "Not legal advice."
        )

    st.markdown("---")
    st.caption(
        f"AI Agent Incident Register, version {VERSION}. Every number on this site is "
        "computed from data/incidents.csv and data/case_harm_ratings.csv, and uses grade "
        "A and grade B rows only. Closest clause, not legal classification."
    )


if __name__ == "__main__":
    main()

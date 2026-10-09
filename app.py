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

import html
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
# monochrome, the bar chart is one hue, and every severity pill pairs its colour with a
# four-bar meter and the word, so nothing depends on colour alone.
SEVERITY_RANK = {"Severe": 4, "Serious": 3, "Moderate": 2, "Negligible": 1}
SEVERITY_SLUG = {"Severe": "sev", "Serious": "ser", "Moderate": "mod", "Negligible": "neg"}

PAGE_CSS = """
<style>
:root {
  --sev-sev:#d03b3b; --sev-ser:#ec835a; --sev-mod:#fab219; --sev-neg:#898781;
  --tint-sev:rgba(208,59,59,0.14); --tint-ser:rgba(236,131,90,0.18);
  --tint-mod:rgba(250,178,25,0.18); --tint-neg:rgba(137,135,129,0.14);
  --meter-off:#c3c2b7; --grid-line:#e1e0d9; --ink-2:#52514e; --muted:#898781;
}
@media (prefers-color-scheme: dark) {
  :root {
    --tint-sev:rgba(208,59,59,0.26); --tint-ser:rgba(236,131,90,0.22);
    --tint-mod:rgba(250,178,25,0.20); --tint-neg:rgba(137,135,129,0.22);
    --meter-off:#66655f; --grid-line:#2c2c2a; --ink-2:#c3c2b7;
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
.meter i:nth-child(1){height:5px} .meter i:nth-child(2){height:7px}
.meter i:nth-child(3){height:10px} .meter i:nth-child(4){height:12px}
.s-neg{background:var(--tint-neg)} .s-neg .meter i.f{background:var(--sev-neg)}
.s-mod{background:var(--tint-mod)} .s-mod .meter i.f{background:var(--sev-mod)}
.s-ser{background:var(--tint-ser)} .s-ser .meter i.f{background:var(--sev-ser)}
.s-sev{background:var(--tint-sev)} .s-sev .meter i.f{background:var(--sev-sev)}

.grade {
  display:inline-block; min-width:26px; text-align:center; padding:1px 7px;
  border-radius:6px; font-size:12px; font-weight:650;
}
.g-a { background: currentColor; }
.g-a span { color: Canvas; }
.g-b { border: 1.5px solid currentColor; }
.g-c { border: 1.5px dashed var(--muted); color: var(--muted); }
</style>
"""

APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "data" / "incidents.csv"

VERSION = "0.9"
UPDATED = "9 October 2026"
CORRECTIONS_URL = "https://github.com/Saa2252/ai-agent-incident-register/issues"

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

SEVERITY_ORDER = ["Severe", "Serious", "Moderate", "Negligible"]
# The scale measures one thing only: who was affected and how badly. Recovery time and
# effort are deliberately not in it. A failure that happened to be cheap to fix is not a
# smaller failure, and bundling the two axes leaves no home for a case that cost someone
# real money and was put right in an hour.
SEVERITY_MEANING = {
    "Severe": "People outside the deploying organisation lost data, money, or access to a service they depend on.",
    "Serious": "Unlawful or unsafe guidance reached the public, or data was exposed or destroyed, or a service people rely on went down.",
    "Moderate": "One or more identifiable people were misled or left out of pocket, and the organisation had to make it good.",
    "Negligible": "No harm occurred.",
}
SEVERITY_NOTE = (
    "A hazard is rated on the harm it could have caused, not on harm that occurred, and "
    "its card says Hazard next to the rating. That is why one hazard in this register is "
    "rated Serious: a zero-click path out of a company's mail and files is a serious "
    "exposure whether or not anyone is known to have walked it."
)

MATURITY_MEANING = {
    "Absent": "The control did not exist in any form.",
    "Designed": "It existed on paper, in a policy or an instruction, with nothing enforcing it.",
    "Implemented": "It was built and wired in, and it did not stop the thing it was there to stop.",
    "Unknown": "The public record does not say what state it was in.",
}
MATURITY_COLOR = {"Absent": "#B3261E", "Designed": "#8A4B00", "Implemented": "#5B3A8A", "Unknown": "#6B7280"}

GRADE_MEANING = {
    "A": "A primary record. A ruling, a regulator notice, a vendor security advisory or a threat intelligence report, plus a second source.",
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
CLASS_COLOR = {
    "Authority": "#B3261E",
    "Boundary": "#8A4B00",
    "Accuracy": "#1B5E8A",
    "Oversight": "#5B3A8A",
    "Vendor": "#2E6B3A",
}
SEVERITY_COLOR = {
    "Severe": "#B3261E",
    "Serious": "#8A4B00",
    "Moderate": "#1B5E8A",
    "Negligible": "#4A5568",
}
GRADE_COLOR = {"A": "#2E6B3A", "B": "#1B5E8A", "C": "#6B7280"}

NIST_GAP_QUOTE = (
    "NIST's March 2026 report on monitoring deployed AI systems names an immature "
    "information sharing ecosystem and a lack of trusted guidelines for monitoring "
    "methods and tools among the field's central gaps."
)


# --------------------------------------------------------------------------- loading


@st.cache_data
def load_register():
    frame = pd.read_csv(DATA_FILE, dtype=str).fillna("")
    frame["counted"] = frame["evidence_grade"].isin(COUNTED_GRADES)
    frame["year"] = frame["event_date"].str.slice(0, 4)
    return frame


@st.cache_data
def load_rules():
    return engine.load_rules()


def esc(value) -> str:
    """Escape CSV-derived text before it reaches any raw-HTML render.

    This repo is public and meant to be forked, so CSV content is treated as untrusted
    input even though today it is hand written.
    """
    return html.escape(str(value), quote=True)


def badge(text, color):
    return (
        f'<span style="display:inline-block;background:{color};color:#fff;'
        f'border-radius:4px;padding:2px 8px;font-size:0.78rem;font-weight:600;'
        f'margin:0 6px 4px 0;white-space:nowrap">{esc(text)}</span>'
    )


# --------------------------------------------------------------------------- findings


RUNNABLE_TESTS = {
    "AIR-002": ("tests/test_authority.py", "DestructiveActionsNeedAGate"),
    "AIR-004": ("tests/test_authority.py", "TheGateMustBeOperating"),
    "AIR-010": ("tests/test_injection.py", "UntrustedContentCannotAct"),
}

def severity_pill(level):
    """Colour, a four-bar meter and the word. Never colour alone."""
    rank = SEVERITY_RANK[level]
    bars = "".join(f'<i class="{"f" if i <= rank else ""}"></i>' for i in range(1, 5))
    return (
        f'<span class="sev s-{SEVERITY_SLUG[level]}">'
        f'<span class="meter" aria-hidden="true">{bars}</span>{esc(level)}</span>'
    )


def grade_badge(grade):
    """Monochrome. A filled, B outlined, C dashed and followed by the words."""
    badge = f'<span class="grade g-{grade.lower()}"><span>{esc(grade)}</span></span>'
    if grade == "C":
        badge += ' <span style="font-size:12px;color:var(--muted)">not counted</span>'
    return badge


def case_table(view):
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
            f'<td class="id"><a href="#{row["id"].lower()}">{esc(row["id"])}</a></td>'
            f"<td>{esc(row['title'])}</td>"
            f"<td>{esc(row['control_class'])}</td>"
            f"<td>{severity_pill(row['severity'])}</td>"
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
        "control_unknown": int((counted["control_maturity"] == "Unknown").sum()),
        "no_stop_authority_recorded": int((counted["deploy_stop_authority"] == "Not disclosed").sum()),
        "no_review_recorded": int((counted["deploy_review_date"] == "Not disclosed").sum()),
        "no_evidence_recorded": int((counted["deploy_evidence_seen"] == "Not disclosed").sum()),
        "bearer_no_control": int((counted["harm_bearer_had_control"] == "No").sum()),
        "no_approval": int((counted["human_approval"] != "Yes").sum()),
        "could_act": int(acted.sum()),
        "read_only": int((~acted).sum()),
        "read_only_bad": int((~acted & counted["severity"].isin(["Serious", "Severe"])).sum()),
        "years": f"{counted['year'].min()} to {counted['year'].max()}",
    }


# ------------------------------------------------------------------------------ home


def screen_home(frame, rules):
    facts = headline(frame)

    st.title("AI Agent Incident Register")
    st.markdown(
        "#### Most of these failures were not the AI being wrong. They were the AI being "
        "allowed to act."
    )
    st.markdown(
        f"{facts['all_rows']} real AI agent failures, each traced to the control that was "
        "missing, the test that would have caught it before launch, and the signal that "
        "would have shown it after."
    )

    left, middle, right = st.columns(3)
    left.metric("Incidents in the register", facts["all_rows"], help="Grades A, B and C. One grade C row is shown but counted nowhere.")
    middle.metric("Rows that feed the numbers", facts["total"], help="Grade A and grade B only. Every count on this site uses these rows.")
    right.metric("Watch-list rules built from them", len(rules["rules"]), help="Fixed rules. No model runs in this tool.")

    st.markdown("---")

    st.markdown("### The finding")
    st.markdown(
        f"**In {facts['said_nothing_untrue']} of the {facts['total']} cases the agent said "
        "nothing untrue, and harm happened anyway.** In those cases a more accurate model "
        "would have changed nothing. What was missing governed what the agent was allowed "
        "to do, what it was allowed to treat as an instruction, or who was positioned to "
        "stop it."
    )
    st.markdown(
        f"**And in the other {facts['said_untrue']}, saying something untrue was never "
        f"sufficient on its own.** Every one of the {facts['total']} also required "
        "authority the agent should not have held, reach it should not have had, or a "
        "path nobody was monitoring. That is the part that does not flip when you "
        "rearrange the counting: a control on what an agent may **do** catches both "
        "groups, and a control on what it **says** catches one."
    )
    st.caption(
        f"The second claim is checkable on every row. No case in the register caused harm "
        f"through an untrue statement alone, and the validator fails the build if a row is "
        f"ever added that does."
    )

    order = sorted(facts["by_class"].items(), key=lambda item: (-item[1], item[0]))
    rows = []
    for name, count in order:
        rows.append({
            "What the missing control governed": name,
            "Cases": count,
            "What that means": CONTROL_CLASSES[name],
        })
    st.markdown(
        "| What the missing control governed | Cases | What that means |\n| --- | --- | --- |\n"
        + "\n".join(
            f"| {r['What the missing control governed']} | {r['Cases']} | {r['What that means']} |"
            for r in rows
        )
    )

    st.caption(
        f"How the {facts['total']} grade A and grade B rows fall out under the ordered "
        f"rubric, events from {facts['years']}. One row per case, one class per row. This "
        "table describes the register. The finding above does not rest on it, for the "
        "reason given in the paragraph above."
    )

    st.markdown("---")

    first, second = st.columns(2)
    with first:
        st.markdown("### Two counts that change where you look")
        st.markdown(
            f"- In **{facts['no_approval']} of {facts['total']}** cases no person approved "
            "the action before it took effect, or the gate that should have stopped it did "
            "not hold.\n"
            f"- **{facts['read_only']} of the {facts['total']}** agents could only read. "
            f"**{facts['read_only_bad']} of those {facts['read_only']}** still produced a "
            "serious or severe outcome. Read-only is not the same as low risk, because an "
            "agent that only reads can still speak, and what it says binds the "
            "organisation."
        )
    with second:
        st.markdown("### Why this register exists")
        st.markdown(NIST_GAP_QUOTE)
        st.markdown(
            "Teams are asked to monitor agents in production without an agreed way to do "
            "it and without a shared record of what has already gone wrong. This is a "
            "small, checkable contribution to the second problem."
        )

    st.markdown("---")
    st.markdown("### Who could have stopped it, and whether anyone can tell")
    st.markdown(
        f"**In {facts['no_stop_authority_recorded']} of the {facts['total']} counted "
        "cases, the public record does not say which role could have halted the "
        "deployment.** Not that nobody could. That the record does not say. That is a "
        "harder claim than naming anyone, and it is the one the evidence supports."
    )
    st.markdown(
        "This register names organisations and never individuals, and that is the "
        "stronger version rather than the cautious one. A name is unusable to you. A "
        "**role** is a lookup into your own org chart. These are the roles that came up "
        "across the twelve cases, and the useful exercise is to put a name against each "
        "one for your own agent and see which lines you cannot fill."
    )
    role_rows = sorted(facts["roles"].items(), key=lambda item: (-item[1], item[0]))
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

    st.markdown("---")
    st.markdown("### What state the missing control was in")
    st.markdown(
        f"Of the {facts['total']} counted cases, **{facts['control_absent']} had no such "
        f"control in any form**, {facts['control_designed']} had one on paper with nothing "
        f"enforcing it, {facts['control_implemented']} had one built and wired in that did "
        f"not hold, and for {facts['control_unknown']} the record does not say. "
        f"({facts['control_absent']} plus {facts['control_designed']} plus "
        f"{facts['control_implemented']} plus {facts['control_unknown']} is "
        f"{facts['total']}.)"
    )
    st.markdown(
        "The third category is the one worth dwelling on. A control can be designed, "
        "implemented, evidenced in an audit, and still not be stopping anything. Every "
        "card says which of the four it was."
    )
    st.markdown(
        "Every row also records who bore the harm against who could have prevented it, and "
        "in all of them those are different people. On its own that is unremarkable, since "
        "it is true of most consumer harm. An airline passenger cannot fix airline policy "
        "either. **What is specific to agents is that there was no moment to intervene "
        "in.** In the destructive cases the agent went from hitting a problem to taking "
        "the irreversible action inside a single uninterrupted task, with no checkpoint "
        "where a person was asked anything. In one case the path required no user action "
        "at all: an email nobody opened was enough."
    )

    st.markdown("---")
    st.markdown("### How much of this is the register's own judgement")
    st.markdown(
        "Naming the control that was missing is the only place this register makes a "
        "claim about a company that the company did not make about itself. So every row "
        "says how it knows."
    )
    st.markdown(
        f"| How the register knows | Cases | What it means |\n| --- | --- | --- |\n"
        f"| Stated | {facts['basis_stated']} of {facts['total']} | The deployer, a regulator or a ruling said it. |\n"
        f"| Entailed | {facts['basis_entailed']} of {facts['total']} | It follows from the record. A control added afterwards is evidence of its prior absence. |\n"
        f"| Our reading | {facts['basis_reading']} of {facts['total']} | Neither. This is judgement, and it is labelled as such on the card. |"
    )
    st.markdown(
        f"**{facts['basis_stated'] + facts['basis_entailed']} of {facts['total']} do not "
        "rest on this register's opinion.** The test and signal columns carry no such "
        "marking, deliberately: those are engineering recommendations rather than claims "
        "about anybody, and hedging them would be hedging the wrong thing."
    )

    st.markdown("---")
    st.markdown("### The second finding, which is about the evidence rather than the agents")
    st.markdown(
        "Building this register produced three observations that looked separate and are "
        "not.\n\n"
        "1. **Primary records exist mainly for legal and security events.** Rulings, CVEs, "
        "threat intelligence reports and enforcement notices. A chatbot that quietly gave "
        "wrong answers for a year produces no document at all.\n"
        "2. **A security vendor's catalogue of agent failures is mostly security "
        "failures.** One of the lead lists used here is exactly that, and the shape of its "
        "total follows from who compiled it.\n"
        "3. **Searching for these cases returns a large volume of generated write-ups with "
        "no record behind them.** Confident, detailed, cited to each other, traceable to "
        "nothing."
    )
    st.markdown(
        "A fourth observation came from auditing how each of these stories ended, and "
        "three rows show the direction directly. **One said a database and its backups "
        "were destroyed with the newest copy three months old, when the platform had "
        "published a postmortem saying the data was recovered two and a half days later. "
        "One said an eating disorder helpline was shut, when the number had been taken "
        "over by another charity and still reaches therapists. One recorded a regulator's "
        "settlement terms and omitted that the company denied wrongdoing.** Every one of "
        "those omissions made the deployer look worse than the record supports."
    )
    st.markdown(
        f"Underneath that, the measurement: **{facts['aftermath_documented']} of the "
        f"{facts['total']} counted cases have a fully documented ending, "
        f"{facts['aftermath_partial']} stop part way, and {facts['aftermath_undocumented']} "
        "has no recorded ending at all.** The destruction was news. The recovery was a "
        "postmortem nobody aggregated."
    )
    st.info(
        "**Who documents a failure determines which failures exist on paper.** Every "
        "register of AI incidents, this one included, is a map of the documentation "
        "regime rather than a map of the harm. The failure modes that generate paperwork "
        "are overrepresented in every count anyone publishes, and the ones handled quietly "
        "between a vendor and a customer are absent from all of them.",
        icon="🔍",
    )
    st.markdown(
        "That bias has a direction as well as a shape. Failures generate coverage and "
        "recoveries generate, at best, a postmortem on a vendor's own blog. So every "
        "register of incidents, including this one before it was checked, will tend to "
        "overstate harm rather than understate it. Each row here now records how "
        "completely its ending is known, and says so on the card when the record stops "
        "early."
    )
    st.markdown(
        "That has a practical edge for anyone reading this to decide where to look. The "
        "categories that are easiest to find public cases for are the ones your own "
        "organisation is most likely to already be watching, because they are the ones "
        "that produce an external artefact. The categories with no public cases are not "
        "the safe ones. They are the ones nobody had to write down."
    )

    st.markdown("---")
    st.markdown("### A fourth instance, about what deployment records contain")
    st.markdown(
        "Each row was asked three questions about the moment the agent went into real "
        "use, and each question is about **what the public record says**, not about what "
        "the organisation did."
    )
    st.markdown(
        f"| Does the public record say whether... | Silent |\n| --- | --- |\n"
        f"| anyone reviewed the agent's behaviour before launch | {facts['no_evidence_recorded']} of {facts['total']} |\n"
        f"| any role could halt or roll back the deployment | {facts['no_stop_authority_recorded']} of {facts['total']} |\n"
        f"| any date was set to re-examine it | {facts['no_review_recorded']} of {facts['total']} |"
    )
    st.info(
        "**Read these as statements about the record, not about the deployers.** This "
        f"register cannot and does not claim that {facts['no_review_recorded']} "
        "organisations set no review date. Review dates are internal artefacts that "
        "essentially never appear in press coverage, a tribunal ruling or a CVE. The "
        "claim is only that the record does not say. Every row defaults to *not "
        "disclosed*, and both *yes* and *no* require a source, because coding *no* from a "
        "failed search would be an accusation on no evidence.",
        icon="📋",
    )
    st.markdown(
        f"**The gradient is the finding, more than any one number.** "
        f"{facts['no_evidence_recorded']}, then {facts['no_stop_authority_recorded']}, "
        f"then {facts['no_review_recorded']}. The more internal the governance artefact, "
        "the less likely it survives into the public record. Evidence that someone "
        "reviewed the thing sometimes surfaces, usually because a regulator went looking. "
        "A named role that could halt it, rarely. A scheduled date to look again, never. "
        "That shape says something about what incident reporting captures, and it is "
        "harder to argue with than a bare hundred per cent."
    )

    st.markdown("---")
    st.success(
        "**Every row on this register maps onto the European Commission's own serious "
        "incident reporting template.** The fields were chosen to sit close to it, so a "
        "case here can be lifted into an Article 73 report rather than rewritten from "
        "scratch. That is the point of the format, not a side effect of it.",
        icon="📋",
    )
    st.caption(
        "Checked on 8 October 2026: the Commission's guidance and template are still the "
        "draft of 26 September 2025. Its consultation closed on 7 November 2025 and the "
        "final was expected to apply from 2 August 2026, which has passed. If a final "
        "version has landed and this page has not caught up, that is exactly the kind of "
        "correction worth sending."
    )

    st.markdown("---")
    st.markdown("### How this works")
    st.markdown(
        "**The register** lists every case with its evidence grade and a link you can "
        "follow. Nothing is on a card that is not in the source.\n\n"
        "**Build your watch list** asks six plain questions about your own agent and "
        "returns the tests and signals those answers trigger. It runs on fixed rules, not "
        "on a model, so every line shows the rule and the incidents behind it.\n\n"
        "**Method** gives the inclusion rule, the evidence grades, the coding rubric, the "
        "limits and the change log. Start there if you want to disagree with something."
    )
    st.markdown("---")
    st.markdown("### Published for comment until 7 November 2026")
    st.markdown(
        f"This is version {VERSION}. It is published for comment rather than as a "
        "finished reference, and the version number is the least important part of that "
        "sentence. What makes it real is the three things below."
    )
    st.markdown(
        f"- **One route.** Open an issue at [{CORRECTIONS_URL}]({CORRECTIONS_URL}). That "
        "is the only channel. Comments elsewhere are welcome but the change log is driven "
        "from issues, so a correction sent anywhere else may not reach it.\n"
        "- **A window with a date on it.** Comments received up to **7 November 2026** "
        "will be worked through and answered before this moves to 1.0. The window closing "
        "does not close the route, it just marks the point at which the open questions "
        "stop being open.\n"
        "- **Every substantive comment goes in the change log**, with the date, whether "
        "or not it is acted on. A comment recorded and declined is better served than one "
        "silently dropped."
    )
    st.error(
        "**What this register must not be used for.** It is not legal advice and not a "
        "compliance assessment. It must not be used to decide whether any organisation "
        "named here met a legal obligation, to assess a vendor, or as evidence in a "
        "procurement or enforcement decision. The clause references are the closest fit "
        "for a reader who needs a starting point, several of the facts rest on reporting "
        "rather than on findings, and one person coded all of it. Use it to generate "
        "questions about your own system. Do not use it to reach conclusions about "
        "somebody else's.",
        icon="⛔",
    )


# -------------------------------------------------------------------------- register


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
        badge(row["id"], "#374151")
        + badge(row["incident_or_hazard"], "#374151")
        + badge(f"{row['severity']} severity", SEVERITY_COLOR[row["severity"]])
        + badge(f"Missing control: {row['control_class']}", CLASS_COLOR[row["control_class"]])
        + badge(f"Evidence grade {row['evidence_grade']}", GRADE_COLOR[row["evidence_grade"]])
        + (badge("Facts disputed by the deployer", "#8A4B00") if row["disputed"] == "Yes" else "")
        + (badge("Not counted in any number", "#6B7280") if not row["counted"] else ""),
        unsafe_allow_html=True,
    )
    st.markdown(
        f"**{esc(row['deployer'])}** · {esc(row['sector'])} · {esc(row['agent_type'])} "
        f"· {esc(row['event_date'])}"
    )
    st.markdown(esc(row["what_happened"]))
    st.markdown(f"**What was missing.** {esc(row['missing_control'])}")

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
        tier = row["missing_control_basis"].split(".")[0].strip()
        st.markdown(
            f"**State it was in: {row['control_maturity']}.** "
            f"{MATURITY_MEANING[row['control_maturity']]}\n\n"
            f"**How the register knows: {tier}.** "
            f"{esc(row['missing_control_basis'].split('.', 1)[1].strip())}"
        )
        st.caption(
            f"Failure pattern: {esc(row['failure_pattern'])}. OWASP {row['owasp_code']}, "
            f"{OWASP_CODES[row['owasp_code']]}."
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
            f"Severity basis: {esc(row['severity_basis'])} Closest clause, not a legal "
            "classification."
        )


# Every finding is a filter, and every filter is a link that can be posted on its own.
# The predicates are the single source for the tile numbers, the chip counts and the
# filtering, so a chip saying 10 and a table showing 9 is not a state this can reach.
#
# "Record silent" is the wording throughout, never "nobody could". The field says the
# public record does not say. Turning that into a claim about the deployer is the same
# error as coding a sourceless No.
FINDINGS = {
    "no-false-statement": {
        "chip": "Said nothing untrue",
        "tile": "The agent said nothing untrue, and harm happened anyway.",
        "test": lambda r: r["said_something_untrue"] == "No",
    },
    "record-silent-on-stop": {
        "chip": "Record silent on who could stop it",
        "tile": "The public record does not say who could have stopped the deployment.",
        "test": lambda r: r["deploy_stop_authority"] == "Not disclosed",
    },
    "control-never-built": {
        "chip": "Control never built",
        "tile": "The control that would have prevented it was never built.",
        "test": lambda r: r["control_maturity"] == "Absent",
    },
    "control-did-not-hold": {
        "chip": "Control existed, did not hold",
        "tile": "A control was built and wired in, and it did not stop the thing.",
        "test": lambda r: r["control_maturity"] == "Implemented",
    },
}


def finding_counts(frame):
    """How many counted cases each finding covers. Computed, never typed."""
    counted = frame[frame["counted"]]
    return {
        key: int(counted.apply(spec["test"], axis=1).sum())
        for key, spec in FINDINGS.items()
    }


def screen_register(frame):
    counts = finding_counts(frame)
    total_counted = int(frame["counted"].sum())

    st.markdown("### When AI agents caused harm, what was actually missing?")
    st.markdown(
        f"{len(frame)} documented failures, each traced to the control that was not "
        "there, the test that would have caught it before launch, and the signal that "
        "would have caught it after."
    )

    head = st.columns(3)
    with head[0]:
        st.download_button(
            "Download the data (CSV)", data=DATA_FILE.read_bytes(),
            file_name="ai_agent_incident_register.csv", mime="text/csv",
            on_click="ignore", width="stretch",
        )
    with head[1]:
        st.link_button("Comment on GitHub", CORRECTIONS_URL, width="stretch")
    with head[2]:
        with st.popover("Cite this register", width="stretch"):
            st.code(
                f"Ahmad, S. A. ({UPDATED.split()[-1]}). AI Agent Incident Register, "
                f"version {VERSION}. Retrieved {UPDATED}. {CORRECTIONS_URL.rsplit('/', 1)[0]}",
                language=None,
            )

    # The three tiles are the three findings, each a link that applies its own filter.
    st.markdown("")
    tiles = st.columns(3)
    for column, key in zip(tiles, list(FINDINGS)[:3]):
        spec = FINDINGS[key]
        with column:
            st.metric(spec["chip"], f"{counts[key]} of {total_counted}")
            st.caption(spec["tile"])

    st.markdown("---")

    with st.sidebar:
        st.markdown("### Filter the register")
        chosen = st.pills(
            "Findings",
            options=list(FINDINGS),
            format_func=lambda k: f"{FINDINGS[k]['chip']}  {counts[k]}",
            selection_mode="multi",
            default=[k for k in st.query_params.get_all("view") if k in FINDINGS],
            help="Each one is a claim on the home screen. Selecting it shows the cases behind it.",
        )
        classes = st.multiselect("Missing control", sorted(frame["control_class"].unique()))
        severities = st.multiselect(
            "Severity", [s for s in SEVERITY_ORDER if s in set(frame["severity"])]
        )
        grades = st.multiselect("Evidence grade", sorted(frame["evidence_grade"].unique()))
        query = st.text_input("Search", placeholder="Case, deployer, pattern")
        counted_only = st.checkbox("Only rows that feed the numbers", value=False)

    # The selection lives in the URL, so a filtered view is a link somebody can post.
    if chosen:
        st.query_params["view"] = chosen
    elif "view" in st.query_params:
        del st.query_params["view"]

    view = frame
    for key in chosen:
        view = view[view.apply(FINDINGS[key]["test"], axis=1)]
    if classes:
        view = view[view["control_class"].isin(classes)]
    if severities:
        view = view[view["severity"].isin(severities)]
    if grades:
        view = view[view["evidence_grade"].isin(grades)]
    if counted_only:
        view = view[view["counted"]]
    if query:
        needle = query.lower()
        haystack = view[["id", "title", "deployer", "failure_pattern", "control_class"]]
        view = view[haystack.apply(lambda r: needle in " ".join(r).lower(), axis=1)]

    view = view.sort_values("id")
    shown_counted = int(view["counted"].sum())
    st.markdown(
        f"**Showing {len(view)} of {len(frame)} cases** · {shown_counted} counted in the "
        "findings"
    )
    if chosen:
        st.caption(
            "Filtered by: "
            + ", ".join(FINDINGS[k]["chip"] for k in chosen)
            + ". This view has its own link in your address bar."
        )

    if view.empty:
        st.info(
            "No cases match these filters. Clear one in the sidebar, or reload the page "
            "to start again.",
            icon="🔍",
        )
        return

    st.markdown(case_table(view), unsafe_allow_html=True)
    st.caption(
        "Colour appears in one place on this page: severity. Every pill also carries a "
        "bar meter and the word, so nothing depends on colour alone. Grade A is filled, "
        "B is outlined, C is dashed and says so."
    )

    st.markdown("---")
    not_accuracy = total_counted - int(
        (frame[frame["counted"]]["control_class"] == "Accuracy").sum()
    )
    floor = int((frame[frame["counted"]]["said_something_untrue"] == "No").sum())
    st.markdown(
        f"#### In {not_accuracy} of {total_counted} counted cases, the missing control "
        "was not accuracy"
    )
    st.caption(
        "Accuracy is tested last in the rubric. Test it first instead and "
        f"{floor} of {total_counted} still land elsewhere. Grade C is shown as an open "
        "segment and counted nowhere."
    )
    st.altair_chart(class_chart(frame), use_container_width=True)

    st.markdown("---")
    st.markdown("### Full records")
    for _, row in view.iterrows():
        st.markdown(f"<div id='{row['id'].lower()}'></div>", unsafe_allow_html=True)
        label = f"{row['id']} · {row['title']}"
        if not row["counted"]:
            label += "  (grade C, not counted)"
        with st.expander(label):
            incident_card(row)


def class_chart(frame):
    """Cases by missing control. One hue, because the classes have no order and the bar
    length already carries the count. Grade C is a separate open mark."""
    import altair as alt

    counted = frame[frame["counted"]]
    data = []
    for name in sorted(frame["control_class"].unique()):
        data.append({
            "Missing control": name,
            "Cases": int((counted["control_class"] == name).sum()),
            "Not counted": int(((frame["control_class"] == name) & ~frame["counted"]).sum()),
        })
    table = pd.DataFrame(data).sort_values("Cases", ascending=False)
    table["Label"] = table.apply(
        lambda r: f"{r['Cases']}" + (f" +{r['Not counted']}" if r["Not counted"] else ""),
        axis=1,
    )
    base = alt.Chart(table).encode(
        y=alt.Y("Missing control:N", sort="-x", title=None),
    )
    bars = base.mark_bar(color="#2a78d6", cornerRadiusEnd=4, height=18).encode(
        x=alt.X("Cases:Q", title="cases", axis=alt.Axis(tickMinStep=1)),
        tooltip=["Missing control", "Cases", "Not counted"],
    )
    labels = base.mark_text(align="left", dx=6, fontWeight="bold").encode(
        x="Cases:Q", text="Label:N",
    )
    return (bars + labels).properties(height=max(150, 34 * len(table)))


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

    if answers and not any(answers.values()) and answers.get("Q6") is True:
        st.success(
            "A read-only agent with a person approving its actions is the narrowest case "
            "in this register, and two of the twelve cases still apply to it.",
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

    st.markdown("### Severity")
    st.markdown(
        "The scale measures one thing: who was affected and how badly. Recovery time and "
        "effort are deliberately not in it. A failure that happened to be cheap to fix is "
        "not a smaller failure."
    )
    bands = []
    for level in SEVERITY_ORDER:
        count = int((frame["severity"] == level).sum())
        counted_count = int(((frame["severity"] == level) & frame["counted"]).sum())
        bands.append(
            f'<tr class="s-{SEVERITY_SLUG[level]}">'
            f'<td style="width:170px">{severity_pill(level)}</td>'
            f'<td>{esc(SEVERITY_MEANING[level])}</td>'
            f'<td style="width:130px;text-align:right;white-space:nowrap">'
            f"{describe_count(count, counted_count)}</td></tr>"
        )
    st.markdown(
        '<div class="case-table-wrap"><table class="cases">'
        "<thead><tr><th>Band</th><th>What it means</th><th>Cases</th></tr></thead>"
        f"<tbody>{''.join(bands)}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    st.markdown(SEVERITY_NOTE)
    st.caption("Descriptive, over all rows in the register.")

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
        "the failure pattern code.\n"
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
        "it replaced. The honest repair is to publish the long list of candidates that "
        "were considered and dropped, with the reason for each, so the shape of what the "
        "evidence rule excluded can be seen rather than guessed at. That is not done yet "
        "and it is the largest hole in this method.\n"
        "- **A convenience sample, not a population.** These twelve cases are the ones with "
        "a usable public record. Agent failures that were handled quietly are the majority "
        "and none of them are here, which also biases the counts toward the visible and "
        "the embarrassing.\n"
        "- **Twelve is a small number.** A count of 12 is an illustration of a pattern, not "
        "evidence of its distribution. Treat the finding as a hypothesis worth testing "
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
        f"If a fact, a grade, a clause or a class is wrong, open an issue at "
        f"[{CORRECTIONS_URL}]({CORRECTIONS_URL}). That is the route. Every correction goes "
        "in the change log below with the date and what changed, and with who sent it **if "
        "they want to be named**. Say so in the issue either way. A register nobody "
        "corrects is a blog post."
    )

    st.markdown("### Change log")
    st.markdown(
        "| Version | Date | What changed |\n| --- | --- | --- |\n"
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
        "finding the archiver was reverting hand edits. Published for comment. |\n"
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
    frame = load_register()
    rules = load_rules()

    with st.sidebar:
        st.markdown("## AI Agent Incident Register")
        screen = st.radio(
            "Screen",
            ["Home", "The register", "Build your watch list", "Method"],
            label_visibility="collapsed",
        )
        st.markdown("---")

    if screen == "Home":
        screen_home(frame, rules)
    elif screen == "The register":
        screen_register(frame)
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
        "computed from data/incidents.csv and uses grade A and grade B rows only. "
        "Closest clause, not legal classification. Corrections welcome."
    )


if __name__ == "__main__":
    main()

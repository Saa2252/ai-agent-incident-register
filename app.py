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

APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "data" / "incidents.csv"

VERSION = "0.9.9"
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
    "Serious": "Unlawful or unsafe guidance reached the public, or data was exposed, or a service people rely on went down.",
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
        f"#### {facts['all_rows']} real AI agent failures, each traced to the control that "
        "was missing, the test that would have caught it before launch, and the signal "
        "that would have shown it after."
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
    st.markdown(
        "| Role | Cases where it was the one that mattered | Who is this in your organisation? |\n"
        "| --- | --- | --- |\n"
        + "\n".join(f"| {name} | {count} | |" for name, count in role_rows)
    )
    st.caption(
        "Each case names the role that runs the control and the role that answers when it "
        "fails, which are rarely the same. A blank in the third column is the finding."
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
    st.error(
        "**Read these as statements about the record, not about the deployers.** This "
        f"register cannot and does not claim that {facts['no_review_recorded']} "
        "organisations set no review date. Review dates are internal artefacts that "
        "essentially never appear in press coverage, a tribunal ruling or a CVE. The "
        "claim is only that the record does not say. Every row defaults to *not "
        "disclosed*, and both *yes* and *no* require a source, because coding *no* from a "
        "failed search would be an accusation on no evidence.",
        icon="⚠️",
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
    st.info(
        "This is a public register built by one person from public records. It is not "
        "legal advice, and the clause references are the closest fit rather than a legal "
        "classification. Corrections are welcome and logged.",
        icon="ℹ️",
    )


# -------------------------------------------------------------------------- register


def incident_card(row):
    st.markdown(
        badge(row["id"], "#374151")
        + badge(row["incident_or_hazard"], "#374151")
        + badge(f"{row['severity']} severity", SEVERITY_COLOR[row["severity"]])
        + badge(f"Missing control: {row['control_class']}", CLASS_COLOR[row["control_class"]])
        + (badge(f"Also reads as: {row['secondary_class']}", "#6B7280") if row["secondary_class"] else "")
        + badge(f"Evidence grade {row['evidence_grade']}", GRADE_COLOR[row["evidence_grade"]])
        + badge(f"Control was {row['control_maturity'].lower()}", MATURITY_COLOR[row["control_maturity"]])
        + (badge("Facts disputed by the deployer", "#8A4B00") if row["disputed"] == "Yes" else "")
        + (badge("Not counted in any number", "#6B7280") if not row["counted"] else ""),
        unsafe_allow_html=True,
    )

    st.markdown(f"**{esc(row['deployer'])}** · {esc(row['sector'])} · {esc(row['agent_type'])} · {esc(row['event_date'])}")

    st.markdown("**What happened**")
    st.markdown(esc(row["what_happened"]))

    with st.expander("Why is this in the register?"):
        st.markdown(esc(row["why_in_register"]))
        st.caption(
            "The scope line is on the Method page. This is that line applied to this row."
        )

    left, right = st.columns(2)
    with left:
        st.markdown("**What the agent was allowed to do**")
        granted = [part for part in row["authority"].split("|") if part]
        st.markdown("\n".join(f"- {esc(item)}" for item in granted))
        st.markdown(f"**A person approved first:** {esc(row['human_approval'])}")
        st.caption(APPROVAL_MEANING.get(row["human_approval"], ""))
        st.markdown("**Was accountability locatable at launch?**")
        for label, answer_field, source_field in (
            ("Someone reviewed its behaviour first", "deploy_evidence_seen", "deploy_evidence_source"),
            ("A role could halt or roll it back", "deploy_stop_authority", "deploy_stop_authority_source"),
            ("A date was set to look at it again", "deploy_review_date", "deploy_review_date_source"),
        ):
            answer = row[answer_field]
            link = f" [[source]]({row[source_field]})" if row[source_field] else ""
            st.markdown(f"- {label}: **{answer}**{link}")
        st.caption(
            "Not disclosed means the public record is silent, which is the default. It is "
            "not a finding that the thing was missing."
        )
    with right:
        st.markdown("**Failure pattern**")
        st.markdown(f"{esc(row['failure_pattern'])}")
        st.caption(f"OWASP Agentic Top 10 2026: {row['owasp_code']}, {OWASP_CODES[row['owasp_code']]}")
        if row["secondary_class"]:
            st.caption(
                f"This case also reads as a **{row['secondary_class']}** failure. The "
                "rubric tests classes in a fixed order and takes the first match, so only "
                f"**{row['control_class']}** is counted. The second reading is recorded "
                "here because discarding it would lose something real."
            )
        st.markdown(f"**Harm:** {esc(row['harm_type'])}")
        st.caption(f"{row['severity']} on this register's scale means: {SEVERITY_MEANING[row['severity']][0].lower()}{SEVERITY_MEANING[row['severity']][1:]}")
        st.caption(f"**Why this row meets it.** {esc(row['severity_basis'])}")

    tier = row["missing_control_basis"].split(".")[0].strip()
    st.error(
        f"**The missing control.** {esc(row['missing_control'])}\n\n"
        f"**State it was in: {row['control_maturity']}.** {MATURITY_MEANING[row['control_maturity']]}",
        icon="🚫",
    )
    st.caption(
        f"**How the register knows this: {tier}.** "
        f"{esc(row['missing_control_basis'].split('.', 1)[1].strip())}"
    )
    st.warning(
        f"**Test before launch.** {esc(row['test_before_launch'])}\n\n"
        f"**Pass mark.** {esc(row['test_pass_mark'])}",
        icon="🧪",
    )
    st.success(
        f"**Signal after launch.** {esc(row['signal_after_launch'])}\n\n"
        f"**Monitoring category, NIST AI 800-4.** {esc(row['nist_800_4_category'])}",
        icon="📈",
    )
    st.markdown(
        f"**Runs the control:** {esc(row['control_owner_role'])}  \n"
        f"**Answers when it fails:** {esc(row['accountable_role'])}"
    )

    st.markdown("**Who bore it, and who could have stopped it**")
    st.markdown(
        f"- **Harm fell on.** {esc(row['harm_borne_by'])}\n"
        f"- **Could have prevented it.** {esc(row['could_have_prevented'])}\n"
        f"- **Were they the same people?** {row['harm_bearer_had_control']}"
    )

    st.markdown("**What changed after**")
    st.markdown(esc(row["what_changed_after"]))
    if row["aftermath_status"] != "Documented":
        st.markdown(
            f":orange[**The ending is {row['aftermath_status'].lower()}.** The public record "
            "stops before this story does. Read the harm above as what was reported, not "
            "as what finally happened.]"
        )
    if row["aftermath_source_url"]:
        same = row["aftermath_source_url"] in (row["source_1_url"], row["source_2_url"])
        which = "Source 1 below" if row["aftermath_source_url"] == row["source_1_url"] else (
            "Source 2 below" if same else "A separate source")
        st.caption(f"[{which}]({row['aftermath_source_url']}) carries this claim.")
    if row["disputed"] == "Yes":
        st.markdown(
            ":orange[**The facts here are disputed.** The deployer's own position is in the "
            "paragraph above and in the second source. Read both before using this case.]"
        )

    st.markdown("**Closest clauses**")
    st.markdown(
        f"- NIST AI RMF 1.0: {esc(row['nist_ai_rmf'])}\n"
        f"- ISO/IEC 42001:2023 Annex A: {esc(row['iso_42001'])}\n"
        f"- EU AI Act: {esc(row['eu_ai_act'])}"
    )
    st.caption(
        "Closest clause, not a legal classification. The duty in any real case depends on "
        "the role, the system and the jurisdiction."
    )

    st.markdown(f"**Evidence, grade {row['evidence_grade']}.** {GRADE_MEANING[row['evidence_grade']]}")
    st.markdown(f"1. [{esc(row['source_1_label'])}]({row['source_1_url']})")
    if row["source_2_url"]:
        st.markdown(f"2. [{esc(row['source_2_label'])}]({row['source_2_url']})")
    archives = [a for a in row.get("archive_urls", "").split() if a]
    if archives:
        links = ", ".join(f"[{i}]({a})" for i, a in enumerate(archives, start=1))
        st.caption(
            f"Sources last checked {row['date_checked']}. Archived copies: {links}. "
            "Some publishers block automated access, so the archived copy may be the one "
            "that opens for you."
        )
    else:
        st.caption(f"Sources last checked {row['date_checked']}. No archived copy yet.")


def screen_register(frame):
    st.title("The register")
    st.markdown(
        "Every case on one page. Filter it, then open a row for the full record. The "
        "sources are links, so you can check any claim in two clicks."
    )

    with st.sidebar:
        st.markdown("### Filter the register")
        classes = st.multiselect(
            "What the missing control governed",
            sorted(frame["control_class"].unique()),
            help="One class per case, assigned by the rubric on the Method page.",
        )
        severities = st.multiselect(
            "Severity",
            [s for s in SEVERITY_ORDER if s in set(frame["severity"])],
        )
        kinds = st.multiselect("Incident or hazard", sorted(frame["incident_or_hazard"].unique()))
        grades = st.multiselect("Evidence grade", sorted(frame["evidence_grade"].unique()))
        authority_filter = st.multiselect(
            "The agent could",
            sorted(rules_check.AUTHORITIES),
            help="What the agent was actually able to do at the time of the event.",
        )
        counted_only = st.checkbox(
            "Only rows that feed the numbers",
            value=False,
            help="Grade A and grade B. This is the set every count on this site uses.",
        )

    view = frame
    if classes:
        view = view[view["control_class"].isin(classes)]
    if severities:
        view = view[view["severity"].isin(severities)]
    if kinds:
        view = view[view["incident_or_hazard"].isin(kinds)]
    if grades:
        view = view[view["evidence_grade"].isin(grades)]
    if authority_filter:
        view = view[view["authority"].apply(
            lambda value: bool(set(authority_filter) & set(value.split("|")))
        )]
    if counted_only:
        view = view[view["counted"]]

    st.markdown(f"**{len(view)} of {len(frame)} cases shown.**")

    if view.empty:
        st.info("No case matches those filters. Clear one and try again.")
        return

    # Sorted by ID ascending, always. A register that opens sorted by severity is making
    # an editorial claim in its furniture, and the sort order is the one piece of
    # furniture a reader cannot see the reasoning behind. CVE, the AI Incident Database
    # and ATLAS all do the same. The filters in the sidebar do the real work.
    #
    # Rendered as Markdown rather than st.dataframe because Streamlit's dataframe draws
    # to a canvas, leaving its contents out of the accessibility tree entirely.
    view = view.sort_values("id")

    group = st.toggle(
        "Group by what the missing control governed",
        value=False,
        help=(
            "Off by default. Grouping by control class arranges the register around this "
            "site's own argument, so it is offered as a view you choose rather than the "
            "order you are given."
        ),
    )

    columns = [
        ("id", "ID"), ("title", "What happened"), ("deployer", "Deployer"),
        ("event_date", "Date"), ("severity", "Severity"),
        ("control_class", "Missing control"), ("control_maturity", "Control was"),
        ("aftermath_status", "Ending"), ("deploy_stop_authority", "Stop authority on record"),
        ("evidence_grade", "Evidence"),
    ]

    def render(frame_part):
        head = "| " + " | ".join(label for _, label in columns) + " |"
        rule = "| " + " | ".join("---" for _ in columns) + " |"
        body = "\n".join(
            "| " + " | ".join(esc(r[field]) for field, _ in columns) + " |"
            for _, r in frame_part.iterrows()
        )
        st.markdown(f"{head}\n{rule}\n{body}")

    if group:
        for name in sorted(view["control_class"].unique()):
            part = view[view["control_class"] == name]
            st.markdown(f"**{name}**  ({len(part)})")
            st.caption(CONTROL_CLASSES[name])
            render(part)
            st.markdown("")
    else:
        render(view)

    st.markdown("### Full records")
    for _, row in view.iterrows():
        label = f"{row['id']} · {row['title']}"
        if not row["counted"]:
            label += "  (grade C, not counted)"
        with st.expander(label):
            incident_card(row)

    st.download_button(
        "Download the whole register as CSV",
        data=DATA_FILE.read_bytes(),
        file_name="ai_agent_incident_register.csv",
        mime="text/csv",
        help="The same file the app reads. Every number here is computed from it.",
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
                st.markdown(f"- `{incident}` {esc(titles.get(incident, 'not found'))}")
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
    st.warning(
        "**A note on sources, which turned into a finding of its own.** Searching for these "
        "cases returns a large volume of pages that read as incident write-ups but are "
        "generated summaries of other summaries, often with invented detail and no primary "
        "record. Several candidate cases were dropped because no primary source existed "
        "behind the reporting. If you build something similar, budget most of your time "
        "for verification rather than for finding cases.",
        icon="⚠️",
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
    for level in SEVERITY_ORDER:
        count = int((frame["severity"] == level).sum())
        counted_count = int(((frame["severity"] == level) & frame["counted"]).sum())
        st.markdown(
            f"- **{level}** ({describe_count(count, counted_count)}). "
            f"{SEVERITY_MEANING[level]}"
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
        "- **This register has already produced its own example of a control that was "
        "implemented and not operating.** The repository has a validator, a test suite and "
        "a green build. While all three were passing, a maintenance script was writing back "
        "a stale copy of the data file and silently reverting edits made while it ran. One "
        "published commit carried a reverted account of AIR-001, with a fact in the "
        "deployer's favour missing from it, and the build was green throughout. Nothing in "
        "the checks was watching for it, because the checks validate the file's contents "
        "and not whether the contents are the ones somebody meant to write. An audit of "
        "every commit that touched the data has since bounded the damage to that one row, "
        "two fields and one commit. The register codes that failure mode as Implemented in "
        "other people's systems, and it is the honest label for this one.\n"
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
    st.warning(
        "**Two of these four are derived rather than quoted, and that distinction matters "
        "more here than anywhere else on this page.** These are the claims a lawyer in the "
        "audience knows better than I do, and an earlier version of this page took them "
        "from legal commentary without saying so. The regulation number, its entry into "
        "force and the two high-risk dates were since read on EUR-Lex. The Article 50 "
        "dates were not quoted from an article that states them, they were worked out from "
        "Article 113's structure and from a transitional period given in months. That "
        "reasoning is shown so you can check it rather than trust it, and a correction "
        "here is the most useful one you could send.",
        icon="⚠️",
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
        f"[{CORRECTIONS_URL}]({CORRECTIONS_URL}) or say so in the comments wherever you "
        "found this. Every correction goes in the change log below with the date and what "
        "changed. A register nobody corrects is a blog post."
    )

    st.markdown("### Change log")
    st.markdown(
        "| Version | Date | What changed |\n| --- | --- | --- |\n"
        "| 0.9.9 | 2026-10-09 | Pre-launch round. Marked how the register knows each "
        "missing control, in three tiers, and published the distribution as a statistic "
        "rather than a disclaimer. Left the test and signal columns unmarked, because "
        "they are recommendations to the reader rather than claims about a deployer. "
        "Fixed the register index to sort by ID with ten filterable columns and an "
        "optional grouping, so the sort order stops carrying an argument. Put the "
        "recurring roles on the home screen as a checklist to run against your own "
        "organisation. |\n"
        "| 0.9.8 | 2026-10-09 | Audit and hygiene round. Walked every commit that touched "
        "the data file looking for edits lost to the archiver's stale writes, and bounded "
        "the damage to one row, two fields and one published commit. Moved the page's own "
        "updated date from hand maintenance to a commit hook, so the validator rule "
        "becomes a backstop rather than the mechanism. Recorded in the limits that this "
        "repository produced its own implemented-and-not-operating failure. |\n"
        "| 0.9.7 | 2026-10-09 | Framing round. Withdrew a nine second figure from the home "
        "screen: it was attributed to a platform postmortem that does not contain it, and "
        "it was being used to mean an intervention window, which no source establishes. "
        "Reframed the deployment counts as statements about the public record rather than "
        "about deployers, and led on the gradient across the three questions instead of "
        "the bare hundred per cent. Added a secondary class to record the reading the "
        "ordered rubric discards. Rewrote AIR-001's aftermath from the tribunal ruling "
        "itself, read at last through an archived copy, which added a goodwill coupon the "
        "airline had offered and the row had omitted. Added archived snapshots for every "
        "source. Archived every source link, after the archiver was found to be reverting "
        "hand-written corrections by writing back a stale copy of the whole file. |\n"
        "| 0.9.6 | 2026-10-08 | Correctness and deployment round. Extended the "
        "re-evaluation rule from severity to every field derived from the facts, enforced "
        "by a pair of dates. Re-checked AIR-009's class after its causal account changed "
        "and found it holds, because Vendor is tested before Oversight and still matches, "
        "with the headline unaffected either way. Wrote AIR-009's inclusion rationale onto "
        "its card rather than leaving it assumed. Led the aftermath finding on the three "
        "cases that show its direction instead of on the count. Separated the naming "
        "policy for people in the cases from contributors to the register. Added the three "
        "deployment questions as coded fields, where Not disclosed is the default and both "
        "Yes and No require a source. |\n"
        "| 0.9.5 | 2026-10-08 | Schema round, building four fields that were specified "
        "early and never made it in while the project was busy correcting itself. Split "
        "the single owner into the role that runs the control and the role that answers "
        "when it fails. Added control maturity, which separates a control that never "
        "existed from one that was wired in and did not hold. Added who bore the harm "
        "against who could have prevented it. The three deployment questions are still "
        "outstanding, because the specification for them has not reached this repository. |\n"
        "| 0.9.4 | 2026-10-08 | Audit of endings, prompted by AIR-003 turning out to "
        "overstate harm. Checked how every story finished. Found that the Drift product "
        "was retired rather than merely disabled, that the eating disorder helpline was "
        "taken over by another charity and still runs, and that the healthcare vendor "
        "denied wrongdoing, which the row had omitted. Added a recorded completeness "
        "status for every ending, a stated basis for every severity rating, and a "
        "validator rule that refuses a row whose ending is unknown unless it says so. |\n"
        "| 0.9.3 | 2026-10-08 | Audit round. Added an aggregator denylist to the validator "
        "after finding the previous round's audit had been unsystematic and had missed a "
        "violation it introduced itself. Gave every row a named citation for its deployer "
        "response, which was previously assumed rather than stated. Re-checked the weaker "
        "B rows and found AIR-003 both under-graded and factually incomplete: the platform "
        "published its own postmortem and the data was recovered, neither of which the row "
        "said. Added the second finding, on documentation regimes. Put the Article 73 "
        "alignment on the home screen. |\n"
        "| 0.9.2 | 2026-10-08 | Sourcing round. Linked every standard to the thing itself "
        "rather than naming it, and said plainly why ISO/IEC 42001 is the one left "
        "unlinked. Credited the three databases used to find candidates and separated "
        "finding a case from admitting one. Replaced the aggregator citation on AIR-002 "
        "and the weakest source on AIR-003 with original reporting. |\n"
        "| 0.9.1 | 2026-10-07 | Second reviewer round. Corrected the sensitivity table, "
        "which showed one computation twice and implied two checks agreeing. Added the "
        "structural finding, that no case caused harm through an untrue statement alone, "
        "and made the validator enforce it. Verified the Omnibus regulation and the two "
        "high-risk dates against EUR-Lex and labelled the two Article 50 dates as derived "
        "rather than quoted. Stated that fixing the rubric's ordering did not fix the "
        "sampling bias. Replaced every interactive table with a semantic one, after finding "
        "that Streamlit's dataframe renders to a canvas and leaves its contents out of the "
        "accessibility tree completely. |\n"
        "| 0.9 | 2026-10-07 | First reviewer round. Measured what the rubric's ordering does to "
        "the finding and rewrote the headline around the order-independent floor. "
        "Separated descriptive counts from analytical ones. Decoupled severity from "
        "recovery effort. Corrected the EU AI Act dates, including that Article 50 is "
        "already in force. Withdrew the pre-registration claim as unevidenced. Added "
        "runnable control tests for three rows. |\n"
        "| 0.8 | 2026-10-03 | First build. 12 cases, 11 counted, 18 watch-list rules. |"
    )
    st.markdown(
        "**No corrections from readers yet.** When one arrives it goes in the table above "
        "with the date, what was wrong, and who sent it."
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

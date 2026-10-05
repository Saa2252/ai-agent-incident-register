#!/usr/bin/env python3
"""Apply the watch-list rules to a set of answers.

Six yes or no answers go in, a list of tests and signals comes out. No model runs
here and nothing is generated. The same answers always produce the same list, and
every line carries the rule that produced it and the incidents behind that rule, so
a reader can check the reasoning instead of trusting it.

Run this file directly to execute the self-test:

    python3 rules/evaluate.py
"""

import json
from pathlib import Path

RULES_FILE = Path(__file__).parent / "watchlist_rules.json"

ALWAYS = "always"


def load_rules(path=RULES_FILE):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def parse_trigger(trigger):
    """Return (question_id, required_answer) or (None, None) for an always rule."""
    if trigger == ALWAYS:
        return None, None
    question_id, _, answer = trigger.partition(":")
    return question_id, answer


def evaluate(answers, rules=None):
    """Select the rules that apply to one set of answers.

    answers maps a question id to True (yes) or False (no), for example
    {"Q1": True, "Q2": False, ...}. A question left out is treated as unanswered
    and no rule that depends on it fires.

    Returns a list of dicts, each the rule as written in the file plus a
    "triggered_by" field naming the question and answer that selected it.
    """
    rules = rules or load_rules()
    known = {question["id"] for question in rules["questions"]}
    unknown = set(answers) - known
    if unknown:
        raise ValueError(f"unknown question ids: {sorted(unknown)}")

    selected = []
    for rule in rules["rules"]:
        question_id, required = parse_trigger(rule["trigger"])
        if question_id is None:
            selected.append(dict(rule, triggered_by="Applies to every agent"))
            continue
        if question_id not in known:
            raise ValueError(f"rule {rule['id']} triggers on unknown question {question_id}")
        if question_id not in answers:
            continue
        given = "yes" if answers[question_id] else "no"
        if given == required:
            text = next(q["text"] for q in rules["questions"] if q["id"] == question_id)
            selected.append(dict(rule, triggered_by=f"You answered {required} to {question_id}. {text}"))
    return selected


def owners(selected):
    """Group the selected rules by the role that should hold the control."""
    grouped = {}
    for rule in selected:
        grouped.setdefault(rule["owner_role"], []).append(rule["id"])
    return dict(sorted(grouped.items()))


def incident_ids(selected):
    """Every incident referenced by the selected rules, in register order."""
    found = set()
    for rule in selected:
        found.update(rule["incident_ids"])
    return sorted(found)


def to_markdown(selected, answers, rules=None):
    """Render the watch list as plain Markdown for download."""
    rules = rules or load_rules()
    question_text = {q["id"]: q["text"] for q in rules["questions"]}
    lines = [
        "# Your agent watch list",
        "",
        f"Built from the AI Agent Incident Register, rules version {rules['version']}.",
        "",
        "Fixed rules, no AI. Every line below names the rule that produced it and the",
        "incidents behind that rule. If you disagree with a line, the rule is in",
        "rules/watchlist_rules.json and you can check it.",
        "",
        "## What you told us",
        "",
    ]
    for question_id in sorted(question_text):
        if question_id in answers:
            given = "Yes" if answers[question_id] else "No"
        else:
            given = "Not answered"
        lines.append(f"- {question_id}. {question_text[question_id]} **{given}**")
    lines += ["", f"## Your list, {len(selected)} items", ""]
    for rule in selected:
        lines += [
            f"### {rule['id']}. {rule['title']}",
            "",
            f"- **Why this is on your list.** {rule['triggered_by']}",
            f"- **Test before launch.** {rule['test']}",
            f"- **Pass mark.** {rule['pass_mark']}",
            f"- **Signal after launch.** {rule['signal']}",
            f"- **Monitoring category, NIST AI 800-4.** {rule['nist_800_4_category']}",
            f"- **Failure pattern, OWASP Agentic Top 10.** {rule['owasp_code']}",
            f"- **Owner.** {rule['owner_role']}",
            f"- **Incidents behind this rule.** {', '.join(rule['incident_ids'])}",
            f"- **What those incidents show.** {rule['why']}",
            "",
        ]
    lines += [
        "## Limits",
        "",
        "This list is a starting point built from 12 public cases, not an assessment of",
        "your system. It will miss risks specific to your setting, and passing every test",
        "here does not make an agent safe. Nobody at the register has seen your system.",
        "",
    ]
    return "\n".join(lines)


def _self_test():
    rules = load_rules()
    question_ids = {q["id"] for q in rules["questions"]}
    assert len(question_ids) == 6, question_ids

    rule_ids = [r["id"] for r in rules["rules"]]
    assert len(rule_ids) == len(set(rule_ids)), "duplicate rule id"

    # Every rule triggers on a question that exists, or on every agent.
    for rule in rules["rules"]:
        question_id, required = parse_trigger(rule["trigger"])
        if question_id is not None:
            assert question_id in question_ids, rule["id"]
            assert required in {"yes", "no"}, rule["id"]
        for field in ("title", "test", "pass_mark", "signal", "nist_800_4_category",
                      "owasp_code", "owner_role", "incident_ids", "why"):
            assert rule.get(field), (rule["id"], field)

    # Answering nothing still returns the rules that apply to every agent.
    baseline = evaluate({}, rules)
    assert all(r["trigger"] == ALWAYS for r in baseline), baseline
    assert len(baseline) == 2, len(baseline)

    # The lowest risk answer set: reads only, no money, internal, no outside content,
    # no vendors, a person approves. Should still produce a short list.
    low = evaluate({"Q1": False, "Q2": False, "Q3": False, "Q4": False, "Q5": False, "Q6": True}, rules)
    assert len(low) == 4, [r["id"] for r in low]

    # The highest risk answer set: everything yes except human approval.
    high = evaluate({"Q1": True, "Q2": True, "Q3": True, "Q4": True, "Q5": True, "Q6": False}, rules)
    assert len(high) == len(rules["rules"]) - 2, [r["id"] for r in high]
    assert {"W-15", "W-16"} <= {r["id"] for r in high}
    assert not {"W-17", "W-18"} & {r["id"] for r in high}

    # Q6 is the one question where no is the risky answer, so both branches fire rules.
    yes_six = {r["id"] for r in evaluate({"Q6": True}, rules)}
    no_six = {r["id"] for r in evaluate({"Q6": False}, rules)}
    assert yes_six != no_six
    assert len(yes_six) == len(no_six) == 4

    # Unknown question ids are an error, not something to guess at.
    try:
        evaluate({"Q9": True}, rules)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown question id was accepted")

    # Every incident a rule points at must exist in the register.
    csv_path = Path(__file__).parent.parent / "data" / "incidents.csv"
    if csv_path.exists():
        import csv as csv_module
        with open(csv_path, encoding="utf-8") as fh:
            register_ids = {row["id"] for row in csv_module.DictReader(fh)}
        for rule in rules["rules"]:
            for incident in rule["incident_ids"]:
                assert incident in register_ids, (rule["id"], incident)

    # The Markdown render must mention every selected rule.
    answers = {"Q1": True, "Q2": True, "Q3": True, "Q4": True, "Q5": True, "Q6": False}
    text = to_markdown(evaluate(answers, rules), answers, rules)
    for rule in evaluate(answers, rules):
        assert rule["id"] in text, rule["id"]

    print(f"rules self-test passed. {len(rules['rules'])} rules, {len(question_ids)} questions.")


if __name__ == "__main__":
    _self_test()

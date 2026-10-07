# Data dictionary

One file, `incidents.csv`, 33 fields, one row per case. The app computes every number
it shows from this file, so a change here changes the site. `scripts/validate_register.py`
enforces everything below and fails the build if a row stops obeying it.

Three conventions apply to every field.

- **No em dashes, no semicolons, no double hyphens.** The register is meant to read as
  though a person wrote it. The validator checks this on every field.
- **Multi-value fields use a pipe.** Only `authority` is multi-value today.
- **Clause fields use a comma and a space** between references.

## Identity and context

| Field | Allowed values | Notes |
| --- | --- | --- |
| `id` | `AIR-NNN` | Stable. Never reused, never renumbered, even if a row is retired. |
| `title` | Free text, one line | What happened, in plain words. Not the deployer's name. |
| `event_date` | ISO date | The date of the event, or the date the failure became public where the event ran over a period. |
| `deployer` | Free text | Who ran the agent. Where the deployer and the tool maker differ, both are named. |
| `sector` | Free text | Kept loose on purpose. Twelve rows is too few for a controlled sector list to mean anything. |
| `agent_type` | Free text | What kind of agent it was, in the words a reader would use. |
| `what_happened` | 2 to 5 sentences | Facts only, no interpretation. The validator counts the sentences. |

## Classification

| Field | Allowed values | Notes |
| --- | --- | --- |
| `incident_or_hazard` | `Incident`, `Hazard` | OECD definitions. An incident means harm occurred. A hazard is a near miss. |
| `harm_type` | Free text | What kind of harm, in plain words. Not a code, because twelve rows cannot support one. |
| `severity` | `Negligible`, `Moderate`, `Serious`, `Severe` | Defined on the Method page in terms of what happened to people. |
| `authority` | Pipe-joined subset of `Read`, `Write`, `Delete`, `Pay`, `Promise` | What the agent was **able** to do at the time, not what it was supposed to do. |
| `human_approval` | `Yes`, `No`, `Unknown`, `Yes, bypassed` | `Yes, bypassed` is its own state. A gate that existed on paper and did not hold is not the same as no gate. |
| `failure_pattern` | Free text, one line | The primary pattern in plain words. |
| `owasp_code` | `ASI01` to `ASI10` | OWASP Top 10 for Agentic Applications 2026, published 9 December 2025. One code per row. |
| `said_something_untrue` | `Yes`, `No` | Did the agent itself state something untrue? Recorded **independently of `control_class`**, so the rubric's ordering can be measured rather than argued about. A `No` row cannot become an accuracy failure under any ordering, which makes the count of them an order-independent floor under the headline. A row classed `Accuracy` with `No` here is a contradiction and the validator rejects it. |
| `control_class` | `Accuracy`, `Authority`, `Boundary`, `Oversight`, `Vendor` | What the missing control governed. **This is the field the headline finding counts.** One per row, assigned by the ordered rubric on the Method page. |
| `disputed` | `Yes`, `No` | `Yes` means the deployer publicly contests the facts. A `Yes` row must carry the deployer's position in `what_changed_after`, and the validator checks for it. |

## The control

| Field | Allowed values | Notes |
| --- | --- | --- |
| `missing_control` | 1 to 2 sentences | One plain sentence on the control that was not there. Not a list of everything that could have been better. |
| `test_before_launch` | 1 to 2 sentences | A test somebody could actually run next week. |
| `test_pass_mark` | 1 to 2 sentences | What counts as a pass. A test with no pass mark is a conversation. |
| `signal_after_launch` | 1 to 2 sentences | The metric or alert that would have shown this once live. |
| `nist_800_4_category` | `Functionality`, `Operational`, `Human factors`, `Security`, `Compliance`, `Large-scale impacts` | The six categories in NIST AI 800-4, March 2026. |
| `owner_role` | Free text | The role that should hold the control. A role, never a person. |

## Clauses

Shape is checked. Meaning is not, because that check is a human reading the official
text. The Method page says so on the page itself.

| Field | Required shape | Example |
| --- | --- | --- |
| `nist_ai_rmf` | `FUNCTION N.N` | `MANAGE 4.1, MEASURE 2.4` |
| `iso_42001` | `A.N.N` or `A.N.N.N` | `A.6.2.6, A.8.4` |
| `eu_ai_act` | `Article N` or `Article N(N)` | `Article 14, Article 26` |

## Aftermath and evidence

| Field | Allowed values | Notes |
| --- | --- | --- |
| `what_changed_after` | Free text | What the deployer did or said. Their position goes here even when it contradicts the reporting, and especially then. |
| `evidence_grade` | `A`, `B`, `C` | See below. Only A and B feed a number anywhere on the site. |
| `source_1_label` | Free text | The most authoritative source. For grade A this must name a primary record. |
| `source_1_url` | `https://` URL | Required. |
| `source_2_label` | Free text, blank only on grade C | Required for A and B. |
| `source_2_url` | `https://` URL, blank only on grade C | Must be a different host from source 1 on a grade B row. |
| `date_checked` | ISO date | When the links were last confirmed. The validator warns after 180 days. |

### The evidence rule, as the validator enforces it

| Grade | Requires | Counted in displayed numbers |
| --- | --- | --- |
| `A` | A primary record as source 1, plus a second source. A primary record is a ruling, a regulator notice, a vendor security advisory, a CVE, a threat intelligence report or the deployer's own published statement. | Yes |
| `B` | Two independent sources on two different hosts. | Yes |
| `C` | Exactly one source. | **No.** The row is shown in the register, labelled on its card, and excluded from every count. |

Where the deployer confirmed the event but the harm is known only from reporting, the
row stays at B rather than rising to A.

## Descriptive counts and analytical counts

These are different things and the register keeps them apart, because version 0.8 did
not and two reviewers found the contradiction in the first minute.

- A **descriptive count** describes what is in the register. It covers all rows,
  including grade C. Composition tables say so underneath.
- An **analytical count** supports a claim. It covers only grades A and B.

`scripts/validate_register.py` enforces this. It checks that the app's `headline()`
filters to counted rows, that the two sets of figures genuinely differ so the rule is
not doing nothing, and that the order-independent floor never exceeds the ordered-rubric
count.

## Adding a row

1. Write `what_happened` from the sources, facts only, before you code anything else.
2. Grade the evidence. If it lands at C, decide whether the pattern it shows is worth
   carrying a labelled, uncounted row for. Usually it is not.
3. Apply the control-class rubric in its published order and take the first match.
4. Add the clause references by reading the official text, not a summary of it.
5. Run `python3 scripts/validate_register.py .` and `python3 rules/evaluate.py`.
6. Add a line to the change log on the Method page in `app.py`.

Point at the new row from at least one watch-list rule in `rules/watchlist_rules.json`,
or the validator will warn that the register is carrying a case that teaches nothing.

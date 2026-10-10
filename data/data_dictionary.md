# Data dictionary

Two files. `incidents.csv`, 56 fields, one row per case. `case_harm_ratings.csv`, one row per harm type a case affected. The app computes every number
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
| `eu_serious_incident` | `Meets`, `Does not meet`, `Not determinable from the record` | Whether the case crosses the EU AI Act's serious-incident threshold in Article 3(49). Not determinable is the honest answer where the record cannot settle it, the same rule as the deployment questions. |
| `eu_closest_limb` | `a`, `b`, `c`, `d` | The limb of Article 3(49) nearest to this case, from `frameworks/eu_ai_act_serious_incident.csv`. **Closest limb, never a legal classification**, and several deployers here are outside the Act's scope entirely. |
| `eu_basis`, `eu_basis_type` | Free text, `Stated` or `Our reading` | The working behind the value. |

**Severity is not in this file.** It lives in `case_harm_ratings.csv`, one row per harm
type a case affected, scored on MIT's framework in `frameworks/mit_severity_framework.csv`.
A case's headline severity is the highest level it reached. `at_least` marks a rating
where the record does not establish the magnitude, so the level is a floor rather than a
measurement.

The register's own four-level scale, Negligible / Moderate / Serious / Severe, was
**retired** in version 0.9 rather than converted. It had no external source and it ranked
these twelve cases against each other, so its middle sat wherever these cases happened to
sit. Severe does not mean on MIT's scale what it meant on that one.
| `aftermath_status` | `Documented`, `Partial`, `Undocumented` | How completely the ending is on the record. A `Partial` or `Undocumented` row **must** say so in `what_changed_after`, and the validator rejects it otherwise. Stopping at the failure overstates the harm. |
| `aftermath_source_url` | `https://` URL | Which source carries the `what_changed_after` claim. The deployer's response is a **separate claim** from the incident, so it gets a named citation rather than an assumption that the incident sources happen to cover it. Usually this is `source_1_url` or `source_2_url`, named explicitly. Where neither covers it, it is a third link. Required on every row. |
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

## Only one column makes a claim about a company

`missing_control` is the single field where this register asserts something about an
organisation that the organisation did not assert about itself. It is the only field
that carries an inference tier, and the distribution is published on the home screen as
a statistic rather than tucked into a disclaimer.

`test_before_launch`, `test_pass_mark` and `signal_after_launch` deliberately carry no
such marking. They are engineering recommendations addressed to the reader about the
reader's own system. They are not claims about the deployer, and hedging them would be
hedging the wrong thing.

## Was accountability locatable at launch?

Three questions asked of the moment each agent went into real use, coded from the public
record. They measure whether accountability could be **found**, not whether the deployer
was careless, and not whether anything worked. Whether a control held is
`control_maturity`, and the two are kept apart deliberately: a review date that existed
and was ignored is a different finding from one that was never set.

| Field | Values |
| --- | --- |
| `deploy_evidence_seen` | Was there a record that someone reviewed the agent's behaviour before launch? |
| `deploy_stop_authority` | Was there a record of a role that could halt or roll back the deployment? |
| `deploy_review_date` | Was there a record of a date it would be re-examined? |

Each takes `Yes`, `No` or `Not disclosed`, and each has a paired `_source` field.

**`Not disclosed` is the default, and `No` needs a source too.** `No` is a claim that
something was absent, not a note that nothing turned up. Coding `No` from a failed
search would mean accusing a deployer of having had no stop authority on no evidence,
which is the exact drift this register has already had to correct twice. A `No` is only
valid where a source states the absence: a postmortem admitting there was no gate, a
regulator's finding, a ruling. No row currently meets that bar, so there are no `No`
values at all, and that is the correct result rather than a gap.

The validator refuses `Yes` or `No` without a source, and refuses a source attached to
`Not disclosed`.

## Everything derived from the facts gets re-checked when they move

`facts_changed_at` and `derived_rechecked_at` are a pair. The validator refuses any row
where the second is earlier than the first.

Severity already had this rule via `severity_basis`. It now covers everything computed
from `what_happened`: `control_class` (which the headline counts),
`said_something_untrue`, `incident_or_hazard` and `severity`. When the facts of a case
move, those four have to be re-examined, not assumed to survive.

## Archived copies

`archive_urls` holds Wayback Machine snapshots for every source on the row, written by
`scripts/archive_sources.py`. The validator **warns** on a row with no snapshot.

Two reasons this matters more than it looks. Link rot breaks the two-clicks claim
quietly over months, and the rows most likely to rot are news reports rather than
rulings. And several publishers block automated access from some hosts entirely, so for
those sources the archived copy is the one a reader can actually open.

The archiver merges and never replaces, and it re-reads the file immediately before
writing so it touches only the `archive_urls` column. Both of those rules exist because
earlier versions broke them.

The first version overwrote the column from whatever the availability API returned that
minute, and silently deleted snapshots already recorded. It was caught because the
archived count went **down** between runs.

The second version took minutes to run and then wrote back the copy of the file it had
read at the start, reverting a hand-written correction to one row's account that had
been made while it ran. It was caught by diffing against the last commit before
committing, which is now worth doing after any long-running script touches the data.

## Endings are evidence too

An audit in v0.9.4 found that rows stopped at the dramatic moment. One said a database
and its backups were destroyed and the newest copy was three months old. The platform
had published a postmortem saying the data was recovered two and a half days later.

The error had a direction. Failures generate news, recoveries generate at most a
postmortem on a vendor's own blog, so a register built from public sources will tend to
**overstate** harm. That is the opposite of the error a register of failures is usually
accused of, and it is the one this project's fairness bar specifically claims to avoid.

Hence `aftermath_status`, a required citation for the deployer response, and a validator
rule that refuses a row whose ending is unknown unless the row says so plainly.

## Aggregators are not evidence

`incidentdatabase.ai`, `oecd.ai`, `aiaaic.org`, `icd-ai.org`, Wikipedia and Grokipedia
are on a denylist in the validator and **fail the build** if they appear in any source
field, including the aftermath one. They are how cases are found. They are never the
evidence for one, because an index of other people's reporting is weaker than the
reporting and citing the index hides which report the claim actually rests on.

This rule arrived in v0.9.2, after the rows were already coded. The first audit under it
was not systematic: it caught one violation by luck and missed a second that the same
commit had introduced. The denylist exists because of that, not in spite of it.

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

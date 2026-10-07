# AI Agent Incident Register

Twelve real AI agent failures, each traced to the control that was missing, the test
that would have caught it before launch, and the signal that would have shown it after.

Live app: https://ai-agent-incident-register.streamlit.app

Eight of the eleven counted cases were not accuracy failures. The model being wrong was
the smaller half of the problem. In most of these cases the missing control governed
what the agent was allowed to **do**, what it was allowed to treat as an
**instruction**, or who was positioned to **stop** it.

## Why this exists

NIST's March 2026 report on monitoring deployed AI systems names an immature
information sharing ecosystem and a lack of trusted guidelines for monitoring methods
and tools among the field's central gaps. Teams are asked to monitor agents in
production without an agreed way to do it and without a shared record of what has
already gone wrong. This is a small, checkable contribution to the second problem.

## What is in it

**The register.** Twelve cases with a named deployer, the authority the agent actually
held, whether a person approved anything, the missing control, a test with a pass mark,
a monitoring signal tagged to a NIST AI 800-4 category, the closest NIST AI RMF, ISO/IEC
42001 and EU AI Act clauses, the deployer's own response, and an evidence grade with
links you can follow.

**Build your watch list.** Six plain questions about your own agent. The answers trigger
18 fixed rules and return the tests to run before launch and the signals to watch after,
with the owner for each. No model runs in the tool, so every output line names the rule
that produced it and the incidents behind that rule. The list downloads as Markdown.

**Method.** The inclusion rule, the four-level severity scale, the evidence grades, the
ordered coding rubric, the naming policy, the standards used, the limits, and the change
log.

## The rules this repo enforces on itself

`scripts/validate_register.py` is the published method turned into code. CI fails if any
of this stops being true.

- **Only grade A and grade B rows feed a number.** Grade A needs a primary record plus a
  second source. Grade B needs two independent sources on different hosts. Grade C gets
  one source, is labelled on its card, and is excluded from every count on the site. The
  register carries one grade C row.
- **Every number on screen is computed from the CSV.** Nothing is typed into a page, so
  no count can drift away from the rows behind it.
- **Fixed vocabularies.** Severity, control class, monitoring category and failure
  pattern come from published lists, so a count means the same thing in every row.
- **Every watch-list rule points at incidents that exist,** and every question triggers
  at least one rule. A question on the form that changes nothing is a failure.
- **A disputed row must carry the deployer's position.**
- **No em dashes, no semicolons, no double hyphens,** in any field or any rule. The
  register should read as though a person wrote it, because a person did.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Check the data and the rules:

```bash
python3 scripts/validate_register.py .
python3 rules/evaluate.py
```

Check that every source link still resolves. This is deliberately not in CI, because a
link check that fails on somebody's rate limit trains you to ignore a red build:

```bash
python3 scripts/check_links.py .
```

## Staying reachable

The app is hosted on Streamlit Community Cloud, which sleeps an app after 12 hours
with no traffic. Since April 2025 a push to this repository no longer wakes it, and a
plain uptime ping does not either, because an HTTP request returns 200 from the static
page shell without starting the Python process. The backend only starts when a browser
runs the page JavaScript and opens a websocket.

`.github/workflows/keepalive.yml` runs headless Chromium against the published app
every 6 hours, clicks the wake button if it finds one, and then checks that real
content rendered rather than trusting the response code. Run it by hand with:

```bash
pip install playwright && playwright install chromium
python3 scripts/keepalive.py https://your-app-url
```

Two honest limits. GitHub disables scheduled workflows on a repository with no activity
for 60 days, and nothing announces it when that happens. And this works against the
economics of free hosting, so if Streamlit changes what counts as activity again the
workflow will start failing. That is why it checks what rendered: a keepalive that
reports success without looking at the response is the same mistake this register has a
row about.

## Layout

```
app.py                        Four screens. Home, register, watch list, method.
data/incidents.csv            One row per case, 32 fields. The source of truth.
data/data_dictionary.md       Every field, every allowed value, and how to add a row.
rules/watchlist_rules.json    Six questions, 18 fixed rules. Readable without running anything.
rules/evaluate.py             Applies the rules. Pure stdlib, with a self-test.
scripts/validate_register.py  The method as code. Runs in CI.
scripts/check_links.py        Link checker. Run by hand.
scripts/keepalive.py          Wakes the published app and checks it rendered. CI only.
tests/                        Three cases turned into tests that run. Stdlib, no model calls.
```

Three of the register's rows are not only described but executable. `tests/` turns
AIR-010 (untrusted content treated as an instruction) and AIR-002 and AIR-004
(destructive authority without a gate, and a gate that stopped holding) into 19 tests
that run in about two milliseconds:

```bash
python3 -m unittest discover tests
```

Each guard was checked by breaking it. Removing the provenance guard fails 9 tests,
making the approval gate's self-check vacuous fails 1, dropping the two-person
de-duplication fails 1, and letting trust launder through a derived message fails 2. A
test that still passes when the thing it tests is deleted is decoration. See
`tests/README.md` for what these prove and, more usefully, what they do not.

## Limits, stated up front

One coder, so no second rater and no inter-rater reliability figure. A convenience
sample of twelve, which is an illustration of a pattern and not evidence of its
distribution. The clause references are the closest fit for a reader who needs a
starting point, not a legal classification, and this is not legal advice. The NIST AI
RMF and EU AI Act references were taken from the public texts. ISO/IEC 42001 is
paywalled, so its Annex A numbers come from the standard's published structure rather
than from a reading of the clause text, which makes that column the weakest part of the
register. Every test here is one that would have caught the specific failure described,
and passing all of them does not make an agent safe. The full list is on the Method
page.

A note that became a finding of its own: searching for these cases returns a large
volume of pages that read as incident write-ups but are generated summaries of other
summaries, often with invented detail and no primary record behind them. Several
candidate cases were dropped for exactly that reason. If you build something similar,
budget most of your time for verification rather than for finding cases.

## Corrections

Open an issue. Every correction goes in the change log with the date and what changed.
A register nobody corrects is a blog post.

## Licence

Code under the MIT licence. The register content, meaning `data/incidents.csv`,
`data/data_dictionary.md` and `rules/watchlist_rules.json`, under CC BY 4.0. Attribute
to the AI Agent Incident Register and link back. The underlying facts belong to the
public record and to the publishers cited in each row.

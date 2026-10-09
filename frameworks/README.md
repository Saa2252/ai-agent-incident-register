# Allowed values, copied from their sources

One file per framework. Each row carries the value, where it was verified, the source
URL and the date it was retrieved. The validator reads these files, so an allowed value
is enforced by the build rather than asserted in prose.

**The `status` column is the point of these files.** It records whether a value was read
from the framework owner's own publication or from somebody writing about it.

| status | meaning |
| --- | --- |
| `confirmed` | Read from the framework owner's own page or document |
| `unconfirmed` | Only a secondary source was reachable. Usable, but the page must say so |
| `disputed` | A secondary source and the owner's own wording disagree |

## owasp_agentic_2026.csv

All ten codes and names confirmed on 10 October 2026 from OWASP's own coded list:
https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agent

**Two OWASP pages published the same day say different things, and which one you read
matters.** The press release describes the risks in looser prose and gives no codes, and
it words ASI01 as "Agent Behavior Hijacking". The page above gives the codes and words
it "Agent Goal Hijack". This register follows the page with the codes, because codes are
what it uses.

That disagreement is why the `verified_against` column exists rather than a plain
yes-or-no. "Confirmed against the owner's own publication" was not specific enough: the
owner published twice.

The `alias` column holds the longer forms this register used before the check, so a
reader searching for "Tool Misuse and Exploitation" still finds ASI02.

## Not built yet

The MIT severity scale, harm categories and risk subdomains. The reachable MIT pages
state the counts without naming the values: five levels from Negligible to Catastrophic
with the middle three unnamed, and ten harm categories unnamed. The endpoints, the count
of ten, the CSET basis and the CC BY 4.0 licence are all confirmed.

A dated screenshot of the source is being added to the repository, and these files get
built from that.

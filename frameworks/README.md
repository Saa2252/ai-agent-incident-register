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

Published 9 December 2025, confirmed on the OWASP GenAI Security Project's own resource
page. **The entry names are a different matter.**

The full list is in a PDF behind a download form, and the codes do not appear in the
HTML of either the resource page or the release announcement. So the names in this
register came from a secondary source.

Checking them on 10 October 2026 found a disagreement. OWASP's own release announcement
names **"Agent Behavior Hijacking"**. The secondary source this register used says
**"Agent Goal Hijack"** for ASI01. Two of the three names the announcement does mention,
`ASI02 Tool Misuse and Exploitation` and `ASI03 Identity and Privilege Abuse`, match.

ASI01 is coded on three cases, so this is not academic. Until somebody reads the
official PDF, the app labels ASI01 as disputed and the other seven as unconfirmed.

**To close this:** download the PDF from
https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ ,
copy the ten names from it, set every `status` to `confirmed` and change
`verified_against` to `official PDF`.

## Not built yet, deliberately

The MIT severity scale, harm categories and risk subdomains are **not** in this
directory, because the reachable MIT pages state the counts without naming the values.
The severity endpoints (1 Negligible, 5 Catastrophic), the count of 10 harm categories,
the CSET basis and the CC BY 4.0 licence are all confirmed. The intermediate severity
names and the category names are not.

Coding 12 cases onto a five-level scale whose middle three names came from a summary
would put the same error into 12 rows that ASI01 put into three. It waits for the
source.

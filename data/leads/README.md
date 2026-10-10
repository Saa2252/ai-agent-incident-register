# Leads and what happened to them

Lead lists are used to **find** candidates and are never cited as evidence for one. The
aggregator denylist in the validator still applies: a case is admitted on its primary
record and an independent report, not on an index entry.

`considered_not_included.csv` is the census trail. Every lead that was checked and not
admitted appears there with the test it failed, so the shape of what the evidence rule
excluded can be seen rather than guessed at.

## The six tests

A lead is included only if it passes all six.

1. **Agent action.** An AI agent took an action, a tool call, a data change or deletion,
   a send, a purchase, a post, or made a commitment binding an organisation. Not output
   that nobody acted on. Not robotics or vehicles.
2. **Harm.** Actual harm, or a near miss confirmed by the organisation.
3. **Organisation.** At least one named organisation, deployer, platform or vendor,
   whose control failed. Personal use only is excluded.
4. **Evidence.** Grade A or B: a primary record, meaning a postmortem, advisory, CVE,
   ruling, regulator notice or company statement, plus one independent report.
5. **Traceable.** The record describes the sequence well enough to name the missing
   control.
6. **Window.** Event and publication both between 1 January 2025 and 30 September 2026,
   and not already in the register.

## Census, not selection

Every lead that passes is included. The inclusion decision never looks at the case's
class, severity or `said_something_untrue`, because those are what the register's
findings count. They are coded after a case is in.

## The twelve that came first

Six of the original twelve have event dates before the window. They stay, and their
cards and the Method page say **"Included before the inclusion rule"**, because a rule
written after the fact cannot be claimed to have governed them.

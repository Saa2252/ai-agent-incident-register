# Runnable tests

Two of the register's cases, turned from a sentence in a column into a
test that runs.

```
python3 -m unittest discover tests      # from the repository root
```

19 tests, standard library only, no model calls, about two milliseconds.

| File | Case | Pattern |
| --- | --- | --- |
| `test_injection.py` | AIR-010 (EchoLeak, CVE-2025-32711) | Untrusted content treated as an instruction |
| `test_authority.py` | AIR-002 (Replit/SaaStr), AIR-004 (AWS) | Destructive authority without a gate, and a gate that stopped holding |
| `agent_harness.py` | none | The toy agent the tests drive |

## What these prove

That a control holds under conditions chosen to break it. The
`Test before launch` column of the register says what test would have
caught each case. For these two rows you can now run it.

Three of them are worth reading on their own:

- **`PhrasingDoesNotMatter`** runs six wordings of the same injection,
  in two languages and one HTML comment, and expects all six refused.
  A keyword blocklist fails on the second or third. The guard here is
  structural. It never looks at the text, so the phrasing is
  irrelevant. That is the difference between a control and a filter.

- **`TrustDoesNotLaunder`** is the failure that actually happens.
  Nobody wires untrusted text straight into a tool call. The content
  gets summarised, ranked or folded into a plan, and somewhere in that
  chain the derived text starts being treated as though the operator
  wrote it. Each hop looks reasonable. The chain is the bug.

- **`TheGateMustBeOperating`** is the AIR-004 distinction. Every other
  test in `test_authority.py` would pass on a system whose approval
  gate had been silently bypassed, because each one configures the gate
  itself. This class probes the gate with an action nobody submitted.
  A gate that approves it is implemented but not operating effectively,
  which is exactly the state a control-evidence field cannot see, since
  the evidence that the gate exists is still perfectly good evidence.

## What these do not prove

**That a model resists a persuasive instruction.** Nothing here calls a
model. You cannot unit-test judgment, and a test that pretends to passes
right up until the day the wording changes. These tests assert the
property underneath judgment: an instruction from untrusted content
cannot reach a tool that changes anything, and a destructive tool is
unreachable without a gate that is currently standing. Hold those, and
the model's judgment stops being load-bearing.

**That your agent is safe.** The harness is a stand-in. It has three
tools and two guards. A real system has dozens of each, and the gap
between them is where the work is.

**That these were the only controls that failed.** Each case had more
going on than one test can carry. The register's own row is the fuller
account.

## Why the suite is trustworthy

Every test class includes a control case, an action that is *allowed*
through. Without them a suite passes by refusing everything, which is
not a working system, and a control nobody can live with gets switched
off within a quarter.

The guards were also checked by breaking them. Removing the provenance
guard fails 9 tests. Making the gate's self-check vacuous fails 1.
Dropping the two-person de-duplication fails 1. Stopping trust
propagating through `derive()` fails 2. A test that passes when the
thing it tests is deleted is decoration.

## Adding to CI

Alongside the existing validator step in `.github/workflows/validate.yml`:

```yaml
      - name: Run control tests
        run: python3 -m unittest discover tests
```

No dependency to pin. It is all standard library, and it should stay
that way. These run beside `validate_register.py` or they rot.

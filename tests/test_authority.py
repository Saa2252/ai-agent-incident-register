"""AIR-002 (Replit/SaaStr) and AIR-004 (AWS). Pattern: authority without a gate.

Two cases, two different failures, and the difference between them is
the whole argument of the register.

AIR-002: the agent could reach a destructive action at all. No gate was
designed. The control was missing.

AIR-004: a two-person gate existed and was wired in. An access
misconfiguration meant it no longer applied. Nobody removed it. It
simply stopped stopping things. In the register's coding that is
"implemented, not operating effectively" - and it is the state a
control-evidence field cannot see, because the evidence that the gate
exists is still perfectly good evidence.

The second class below is the one worth reading. It tests the gate
rather than the agent.

Run: python3 -m unittest discover tests
"""

from __future__ import annotations

import unittest

from agent_harness import ApprovalGate, ControlError, Message, Trust, build_agent


OPERATOR = Message("clean up the staging database", Trust.TRUSTED)


class DestructiveActionsNeedAGate(unittest.TestCase):
    """AIR-002. Even the operator cannot delete unsupervised."""

    def test_no_gate_configured_means_refused(self) -> None:
        agent, world = build_agent(gate=None)

        with self.assertRaises(ControlError) as caught:
            agent.act(OPERATOR, "drop_table", table="customers")

        self.assertIn("no gate configured", str(caught.exception))
        self.assertIn("customers", world.database)

    def test_gate_present_but_not_granted_means_refused(self) -> None:
        agent, world = build_agent(gate=ApprovalGate())

        with self.assertRaises(ControlError):
            agent.act(OPERATOR, "drop_table", action_id="drop-customers",
                      table="customers")

        self.assertIn("customers", world.database)

    def test_approval_for_one_action_does_not_cover_another(self) -> None:
        """Scope the approval to the action, or the first yes becomes a
        standing yes - which is how a code freeze gets deleted through."""
        gate = ApprovalGate()
        gate.grant("drop-scratch", approvers=["ana", "boris"])
        agent, world = build_agent(gate=gate)

        with self.assertRaises(ControlError):
            agent.act(OPERATOR, "drop_table", action_id="drop-customers",
                      table="customers")

        self.assertIn("customers", world.database)

    def test_two_approvers_lets_it_through(self) -> None:
        """Control case. Without this the suite passes by refusing
        everything, which is not a working system."""
        gate = ApprovalGate()
        gate.grant("drop-scratch", approvers=["ana", "boris"])
        agent, world = build_agent(gate=gate)
        world.database["scratch"] = "0 rows"

        self.assertEqual(
            agent.act(OPERATOR, "drop_table", action_id="drop-scratch",
                      table="scratch"),
            "dropped scratch",
        )
        self.assertNotIn("scratch", world.database)

    def test_one_approver_is_not_two(self) -> None:
        gate = ApprovalGate()
        with self.assertRaises(ControlError):
            gate.grant("drop-customers", approvers=["ana"])

    def test_the_same_person_twice_is_not_two_people(self) -> None:
        """The failure a two-person rule has in every system that has
        one: the same account approving its own request twice."""
        gate = ApprovalGate()
        with self.assertRaises(ControlError):
            gate.grant("drop-customers", approvers=["ana", "ana"])


class TheGateMustBeOperating(unittest.TestCase):
    """AIR-004. Testing the control's effectiveness, not its existence.

    Every test above would pass on a system where the gate had been
    silently bypassed, because every one of them configures the gate
    itself. This class is the difference between "we have an approval
    process" and "the approval process is currently stopping things".
    """

    def test_self_check_passes_on_a_working_gate(self) -> None:
        ApprovalGate().self_check()  # raises if it does not

    def test_self_check_catches_a_bypassed_gate(self) -> None:
        bypassed = ApprovalGate(operating=False)

        with self.assertRaises(ControlError) as caught:
            bypassed.self_check()

        self.assertIn("not operating", str(caught.exception))

    def test_a_bypassed_gate_really_does_let_deletes_through(self) -> None:
        """Proves the self-check is worth running, by showing what it
        catches. Without the probe, nothing here raises and the
        destructive call simply succeeds."""
        agent, world = build_agent(gate=ApprovalGate(operating=False))

        agent.act(OPERATOR, "drop_table", action_id="never-approved",
                  table="customers")

        self.assertNotIn("customers", world.database)
        self.assertEqual(agent.audit, ["drop_table:never-approved"])

    def test_every_gate_in_the_suite_is_checked_before_use(self) -> None:
        """The habit this is meant to install: run the probe at startup
        and on a schedule, not once at design review."""
        for gate in (ApprovalGate(), ApprovalGate(approvers_required=3)):
            with self.subTest(required=gate.approvers_required):
                gate.self_check()


if __name__ == "__main__":
    unittest.main()

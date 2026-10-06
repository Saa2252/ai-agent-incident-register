"""A deliberately small agent harness, written so it can be broken.

Nothing here calls a model. That is the point. You cannot unit-test
whether a model resists a persuasive instruction, and a test that tries
is a test that passes until the day it matters. What you can test is the
property underneath: whether an instruction from untrusted content can
reach a tool that changes something, and whether a destructive tool is
reachable without a human gate that is actually standing.

The harness models the three things every case in the register turned on:

  1. provenance - did the operator say this, or did the agent read it
     somewhere
  2. capability - can this tool read, write, or destroy
  3. the gate   - was a human between the two, and was it operating

Used by test_injection.py (AIR-010) and test_authority.py (AIR-002,
AIR-004). Pure standard library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class Trust(Enum):
    """Where an instruction came from.

    TRUSTED is the operator. UNTRUSTED is anything the agent read: an
    email, a web page, a document, a tool result, a code comment.
    """

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class Capability(Enum):
    """What a tool can do, in increasing order of regret."""

    READ = "read"
    WRITE = "write"
    DESTROY = "destroy"


class ControlError(Exception):
    """A guard refused an action.

    In these tests a refusal is a pass. The failure mode being tested is
    an action going through, not an exception being raised.
    """


@dataclass(frozen=True)
class Message:
    """An instruction, carrying where it came from."""

    text: str
    trust: Trust

    def derive(self, text: str) -> "Message":
        """Produce new content from this one, keeping its trust level.

        This is the method that catches real systems. Untrusted content
        gets summarised, translated, ranked or pasted into a planning
        step, and somewhere in that chain the result starts being treated
        as though the operator wrote it. Trust does not launder.
        """
        return Message(text=text, trust=self.trust)


@dataclass
class Tool:
    name: str
    capability: Capability
    fn: Callable[..., str]
    requires_approval: bool = False


@dataclass
class ApprovalGate:
    """A human approval gate, and a way to ask whether it is real.

    `operating` is the field that carries the argument. A gate can be
    designed (this class exists), implemented (an Agent holds one) and
    still not be operating - AIR-004, where a two-person rule was in
    place and an access misconfiguration meant it no longer applied to
    anyone. Nobody removed the gate. It just stopped stopping things.
    """

    approvers_required: int = 2
    operating: bool = True
    _granted: set[str] = field(default_factory=set)

    def grant(self, action_id: str, approvers: list[str]) -> None:
        """Record approval for one action by one set of named people."""
        distinct = set(approvers)
        if len(distinct) < self.approvers_required:
            raise ControlError(
                f"{action_id}: {len(distinct)} distinct approver(s), "
                f"{self.approvers_required} required"
            )
        self._granted.add(action_id)

    def holds(self, action_id: str) -> bool:
        if not self.operating:
            # The gate is present and answers yes to everything.
            return True
        return action_id in self._granted

    def self_check(self) -> None:
        """Raise unless the gate is actually standing.

        Probes with an action nobody submitted. A gate that approves it
        is implemented but not operating effectively - the distinction
        the register codes for, and the one a control-evidence field
        that only describes what evidence *would* exist cannot see.
        """
        probe = "__self_check_probe__"
        if probe in self._granted:  # pragma: no cover - defensive
            raise ControlError("self-check probe collided with a real action")
        if self.holds(probe):
            raise ControlError(
                "approval gate is not operating: it approved an action "
                "that was never submitted for approval"
            )


@dataclass
class Agent:
    """An agent that dispatches tool calls, with two guards in front."""

    tools: dict[str, Tool]
    gate: ApprovalGate | None = None
    audit: list[str] = field(default_factory=list)

    def act(
        self,
        instruction: Message,
        tool_name: str,
        action_id: str = "action",
        **kwargs: object,
    ) -> str:
        tool = self.tools.get(tool_name)
        if tool is None:
            raise ControlError(f"no such tool: {tool_name}")

        # Guard 1 - provenance. Untrusted content may cause reads and
        # nothing else. Note this is structural: it does not inspect the
        # wording of the instruction, so there is no phrasing that gets
        # around it.
        if instruction.trust is Trust.UNTRUSTED and tool.capability is not Capability.READ:
            raise ControlError(
                f"refused {tool.name} ({tool.capability.value}): instruction "
                f"came from untrusted content"
            )

        # Guard 2 - approval, for anything that cannot be undone.
        if tool.requires_approval:
            if self.gate is None:
                raise ControlError(
                    f"refused {tool.name}: requires approval, no gate configured"
                )
            if not self.gate.holds(action_id):
                raise ControlError(
                    f"refused {tool.name}: no approval recorded for {action_id}"
                )

        self.audit.append(f"{tool.name}:{action_id}")
        return tool.fn(**kwargs)


# --------------------------------------------------------------------
# A toy environment the tests drive. Stands in for a production system
# with a database, a mailbox and an outbound channel.
# --------------------------------------------------------------------


@dataclass
class World:
    database: dict[str, str] = field(default_factory=lambda: {"customers": "12 rows"})
    sent: list[str] = field(default_factory=list)

    def read_doc(self, name: str = "doc") -> str:
        return f"contents of {name}"

    def send(self, to: str = "", body: str = "") -> str:
        self.sent.append(f"{to}:{body}")
        return "sent"

    def drop_table(self, table: str = "") -> str:
        self.database.pop(table, None)
        return f"dropped {table}"


def build_agent(gate: ApprovalGate | None = None) -> tuple[Agent, World]:
    """An agent with one tool per capability, and the world it acts on."""
    world = World()
    tools = {
        "read_doc": Tool("read_doc", Capability.READ, world.read_doc),
        "send": Tool("send", Capability.WRITE, world.send),
        "drop_table": Tool(
            "drop_table", Capability.DESTROY, world.drop_table, requires_approval=True
        ),
    }
    return Agent(tools=tools, gate=gate), world

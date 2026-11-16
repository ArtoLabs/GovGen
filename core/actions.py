"""Actions: every decision a player can make, as plain data.

The engine lists the legal actions for a player; a controller (human menu, NPC brain, network
client, Unreal agent) picks one and sends it back. Because actions are plain data they can be
logged, replayed, and sent over a network unchanged.

Action types and their params:
    end_turn        {}
    vote            {ballot, choice}          optional free param: ranking (list, ranked-choice only)
    nominate        {ballot, candidate}
    appoint         {position, appointee}
    dismiss         {position, holder}
    call_vote       {kind, subject, target}   kind: remove_office | grant_status | revoke_status
    reform          {government}              by decree or by calling a vote, as the government allows
    research        {interface, innovation}
    role_command    {interface, command}      free param: text
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

# Params the actor fills in freely; they are not part of an action's identity.
FREE_PARAMS = {"text", "ranking"}


@dataclass
class Action:
    type: str
    params: Dict[str, Any] = field(default_factory=dict)
    label: str = ""  # this particular choice, for display ("Bob")
    group: str = ""  # what it belongs to, for menus ("Elder (Seat 2)", an interface key, ...)

    def key(self) -> Tuple:
        """Identity used to check an action against the legal list."""
        return (self.type, tuple(sorted((k, v) for k, v in self.params.items() if k not in FREE_PARAMS)))

    def with_params(self, **extra) -> 'Action':
        return Action(self.type, {**self.params, **extra}, self.label, self.group)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Action':
        return cls(data["type"], dict(data.get("params", {})))

    def __str__(self) -> str:
        return f"{self.type}({', '.join(f'{k}={v}' for k, v in self.params.items())})"

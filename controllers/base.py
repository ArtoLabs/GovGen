"""Controllers decide for one player. The engine never knows which kind it is talking to."""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.actions import Action
from utils.messages import Message


@dataclass
class Decision:
    action: Action
    reason: Optional[str] = None  # shown in full-detail logs; NPCs explain themselves


class Controller:
    """Base class. Subclasses: TerminalController (a human at this keyboard), NPCController,
    HUDController (a human at the real-time HUD). Future: a network client for online humans, a
    graphical client, or an adapter for Unreal Engine AI agents — all only need to turn
    (view, legal actions) into a Decision.

    Turn-based controllers (realtime = False) are asked with decide() and the clock waits for them.
    Real-time controllers (realtime = True) are never waited for: the game loop keeps sending them
    the latest view with update() and collects whatever they chose with take_decisions()."""
    is_human = False
    realtime = False

    def decide(self, view: Dict[str, Any], legal: List[Action]) -> Optional[Decision]:
        """Pick one of `legal`. Return None to quit the game."""
        raise NotImplementedError

    def notify(self, messages: List[Message]):
        """Receive game events as they happen (all events are public for now)."""

    def answer_offer(self, view: Dict[str, Any], offer: Dict[str, Any]) -> Optional[Decision]:
        """Someone offers this player a trade (core/possessions.py). Return an 'answer_trade' decision, or
        None to leave it open for now. Asked as soon as the player's hands are free."""
        return None

    # Real-time controllers only ------------------------------------------------
    def update(self, view: Dict[str, Any], legal: List[Action]):
        """The latest view and legal actions (sent whenever something changes)."""

    def take_decisions(self) -> List[Optional[Decision]]:
        """Decisions made since the last call, oldest first. None means: save and quit."""
        return []

    def has_decisions(self) -> bool:
        """True if take_decisions() has something (lets the game stop waiting at once)."""
        return False

    def action_result(self, decision: Decision, ok: bool, why: str = ""):
        """Whether a real-time decision was carried out (and if not, the engine's explanation)."""

    def to_dict(self) -> Dict[str, Any]:
        """Anything this controller needs to remember across a save."""
        return {}

    def load_state(self, data: Dict[str, Any]):
        """Restore what to_dict saved."""

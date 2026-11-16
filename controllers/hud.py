"""A human playing in real time through a display (the terminal HUD today, a graphical client later).

The game loop runs in its own thread and never waits for this controller. It pushes the latest
view, legal actions and events in; the display reads them whenever it redraws and pushes decisions
back. Everything that crosses between the two threads goes through this class, under a lock, so the
display never touches the engine directly.
"""
import threading
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple  # noqa: F401

from controllers.base import Controller, Decision
from core.actions import Action
from utils.messages import Message


class HUDController(Controller):
    is_human = True
    realtime = True

    def __init__(self, name: str, detail: str = "full"):
        self.name = name
        self.detail = detail
        self._lock = threading.Lock()
        self._view: Optional[Dict[str, Any]] = None
        self._legal: List[Action] = []
        self._version = 0
        self._messages: Deque[Message] = deque()
        self._decisions: Deque[Optional[Decision]] = deque()
        self._results: Deque[Tuple[Decision, bool, str]] = deque()
        # Auto: the game decides for you exactly as for an NPC (controllers/npc.py) until you switch back to manual.
        self.auto = False
        self._npc = None
        self._npc_state: Dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    # Auto (played like an NPC) or manual
    # ------------------------------------------------------------------ #
    def set_auto(self, on: bool):
        """Switch between manual (you choose) and auto (the NPC rules choose for you). Thread-safe."""
        with self._lock:
            self.auto = bool(on)
            if self.auto:
                self._decisions = deque(d for d in self._decisions if d is None)  # drop unsent manual choices

    def npc(self):
        """The NPC brain that plays for you on auto (a fresh one for whoever you play now)."""
        if self._npc is None or self._npc.name != self.name:
            import random
            from controllers.npc import NPCController
            self._npc = NPCController(self.name, rng=random.Random(f"auto:{self.name}"))
            if self._npc_state.get("name") == self.name:
                self._npc.load_state(self._npc_state.get("state", {}))
        return self._npc

    def decide(self, view: Dict[str, Any], legal: List[Action]) -> Optional[Decision]:
        return self.npc().decide(view, legal)  # only asked while on auto

    def answer_offer(self, view: Dict[str, Any], offer: Dict[str, Any]) -> Optional[Decision]:
        return self.npc().answer_offer(view, offer) if self.auto else None

    # ------------------------------------------------------------------ #
    # Game thread side
    # ------------------------------------------------------------------ #
    def notify(self, messages: List[Message]):
        with self._lock:
            self._messages.extend(messages)

    def update(self, view: Dict[str, Any], legal: List[Action]):
        with self._lock:
            self._view, self._legal = view, list(legal)
            self._version += 1

    def take_decisions(self) -> List[Optional[Decision]]:
        with self._lock:
            out = list(self._decisions)
            self._decisions.clear()
        return out

    def has_decisions(self) -> bool:
        return bool(self._decisions)

    def action_result(self, decision: Decision, ok: bool, why: str = ""):
        with self._lock:
            self._results.append((decision, ok, why))

    def to_dict(self) -> Dict[str, Any]:
        out = {"kind": "human", "detail": self.detail, "auto": self.auto}
        if self._npc is not None:
            out["npc"] = {"name": self._npc.name, "state": self._npc.to_dict()}
        return out

    def load_state(self, data: Dict[str, Any]):
        if data and data.get("kind") == "human":
            self.detail = data.get("detail", self.detail)
            self.auto = bool(data.get("auto", False))
            self._npc_state = dict(data.get("npc", {}))

    # ------------------------------------------------------------------ #
    # Display side
    # ------------------------------------------------------------------ #
    def snapshot(self) -> Tuple[int, Optional[Dict[str, Any]], List[Action]]:
        with self._lock:
            return self._version, self._view, list(self._legal)

    def drain_messages(self) -> List[Message]:
        with self._lock:
            out = list(self._messages)
            self._messages.clear()
        return out

    def drain_results(self) -> List[Tuple[Decision, bool, str]]:
        with self._lock:
            out = list(self._results)
            self._results.clear()
        return out

    def submit(self, decision: Decision):
        with self._lock:
            self._decisions.append(decision)

    def quit(self):
        """Ask the game to save and stop."""
        with self._lock:
            self._decisions.append(None)

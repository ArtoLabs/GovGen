from dataclasses import dataclass
from typing import Callable, List, Optional
from utils.logging_config import logger


@dataclass
class Message:
    text: str
    important: bool = True        # shown in "summary" detail; unimportant ones only in "full"
    reason: Optional[str] = None  # why an actor did something (NPCs explain themselves)
    header: bool = False          # date / season separators
    time: Optional[int] = None    # game clock (hours) when it happened
    category: str = ""            # "life" for everyday doings (eating, sleeping, resting); "" for the rest


class Messages:
    """Game event log. Controllers drain it to show what happened since they last looked."""
    _messages: List[Message] = []
    clock: Optional[Callable[[], int]] = None  # set by the engine so messages carry the game date

    @classmethod
    def add(cls, text: str, important: bool = True, reason: Optional[str] = None, header: bool = False,
            category: str = ""):
        cls._messages.append(Message(text, important, reason, header, cls.clock() if cls.clock else None, category))
        logger.debug(f"Message added: {text}")

    @classmethod
    def drain(cls) -> List[Message]:
        msgs, cls._messages = cls._messages, []
        return msgs

    @classmethod
    def clear(cls):
        cls._messages = []

    @staticmethod
    def format(msgs: List[Message], detail: str = "full") -> str:
        """Render messages. detail='full' shows everything with reasons; 'summary' only important events."""
        from core.calendar import format_date
        yellow, grey, cyan, reset = "\033[93m", "\033[90m", "\033[96m", "\033[0m"
        lines = []
        for m in msgs:
            if detail == "summary" and not m.important:
                continue
            if m.header:
                lines.append(f"{cyan}{m.text}{reset}")
                continue
            stamp = f"{grey}[{format_date(m.time, short=True)}]{reset} " if m.time is not None else ""
            lines.append(stamp + (f"{yellow}{m.text}{reset}" if m.important else m.text))
            if m.reason and detail == "full":
                lines.append(f"{grey}    ({m.reason}){reset}")
        return "\n".join(lines)

    @classmethod
    def to_str(cls) -> str:
        return cls.format(cls._messages)

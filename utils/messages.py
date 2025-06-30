from typing import List
from utils.logging_config import logger

class Messages:
    _messages: List[str] = []

    @classmethod
    def add(cls, message: str):
        """Add a message to the queue and log it."""
        cls._messages.append(message)
        logger.debug(f"Message added: {message}")

    @classmethod
    def clear(cls):
        """Clear all messages."""
        cls._messages = []
        logger.debug("Messages cleared")

    @classmethod
    def to_str(cls) -> str:
        """Return all messages as a yellow-colored string for display."""
        if not cls._messages:
            return ""
        yellow = "\033[93m"
        reset = "\033[0m"
        message_str = "\n".join(f"{yellow}{msg}{reset}" for msg in cls._messages)
        logger.debug(f"Messages retrieved: {message_str}")
        return message_str
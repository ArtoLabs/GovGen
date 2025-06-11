# messages.py

class Messages:
    _messages = []

    @classmethod
    def add(cls, message: str):
        cls._messages.append(message)

    @classmethod
    def print_and_clear(cls):
        for msg in cls._messages:
            print(f"\033[93m{msg}\033[0m")  # Yellow text
        cls._messages.clear()

    @classmethod
    def get_all(cls):
        return list(cls._messages)

    @classmethod
    def clear(cls):
        cls._messages.clear()

    @classmethod
    def to_str(cls, color: bool = True) -> str:
        if color:
            return "\n".join(f"\033[93m{msg}\033[0m" for msg in cls._messages)
        return "\n".join(cls._messages)
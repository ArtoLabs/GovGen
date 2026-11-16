import json
from pathlib import Path
from typing import Any, List

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class DataError(ValueError):
    """Raised when a game data file is missing or invalid."""


def load_json(path: Path) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise DataError(f"Missing data file: {path}")
    except json.JSONDecodeError as e:
        raise DataError(f"{path.name}: invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}")


def json_files(subdir: str) -> List[Path]:
    folder = DATA_DIR / subdir
    if not folder.is_dir():
        raise DataError(f"Missing data folder: {folder}")
    return sorted(folder.glob("*.json"))


def require(condition: bool, where: str, message: str):
    if not condition:
        raise DataError(f"{where}: {message}")

"""One save slot: saves/savegame.json. Plain JSON, written atomically, with a version number."""
import json
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from core.calendar import format_date

SAVE_VERSION = 1
SAVE_FILE = Path(__file__).resolve().parent.parent / "saves" / "savegame.json"


def rng_state_to_json(state) -> list:
    version, internal, gauss = state
    return [version, list(internal), gauss]


def rng_state_from_json(data) -> tuple:
    version, internal, gauss = data
    return version, tuple(internal), gauss


def save_game(game, path: Path = SAVE_FILE) -> Path:
    data = {
        "version": SAVE_VERSION,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "game_date": format_date(game.engine.clock),
        "engine": game.engine.to_dict(),
        "controllers": {name: c.to_dict() for name, c in game.controllers.items()},
        "random_state": rng_state_to_json(random.getstate()),  # dice rolls and tie-breaks
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)  # never leaves a half-written save
    return path


def load_save(path: Path = SAVE_FILE) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("version") != SAVE_VERSION:
        raise ValueError(f"Save file version {data.get('version')} is not supported (expected {SAVE_VERSION})")
    return data


def save_summary(path: Path = SAVE_FILE) -> Optional[str]:
    """'Year 3, Summer day 12 (saved 2026-11-12T18:03:00)', or None if there is no usable save."""
    if not path.exists():
        return None
    try:
        data = load_save(path)
    except (OSError, ValueError, KeyError):
        return None
    return f"{data['game_date']} (saved {data['saved_at'].replace('T', ' ')})"

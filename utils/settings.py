from typing import Any, Dict
from utils.data_files import DATA_DIR, load_json, require

DEFAULTS = {"npc_detail": "full", "seed": None, "real_seconds_per_game_year": 300, "playback_speed": 1}


def load_settings() -> Dict[str, Any]:
    path = DATA_DIR / "settings.json"
    data = load_json(path) if path.exists() else {}
    settings = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    require(settings["npc_detail"] in ("full", "summary"), "settings.json", "'npc_detail' must be 'full' or 'summary'")
    require(isinstance(settings["real_seconds_per_game_year"], (int, float)) and settings["real_seconds_per_game_year"] > 0,
            "settings.json", "'real_seconds_per_game_year' must be a positive number")
    return settings

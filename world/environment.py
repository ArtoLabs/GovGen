"""The natural world around the tribe: the day-night cycle and the weather.

The calendar (core/calendar.py) runs fast so that ages pass in a playable time. People live on a
slower clock: one day-night cycle lasts `day_night_cycle_days` calendar days (data/time.json), about
15 real minutes at normal speed. Needs, sleep and the cold of night follow this cycle.
"""
import math
from typing import Any, Dict

from core.calendar import HOURS_PER_DAY, season_of, _data as _time
from utils.data_files import DATA_DIR, load_json, require

CYCLE_DAYS: float = _time.get("day_night_cycle_days", 1080)
CYCLE_HOURS: float = CYCLE_DAYS * HOURS_PER_DAY
DAWN: float = _time.get("dawn", 0.25)
DUSK: float = _time.get("dusk", 0.75)
require(0 < DAWN < DUSK < 1, "time.json", "'dawn' and 'dusk' must satisfy 0 < dawn < dusk < 1")
START: float = DAWN + float(_time.get("start_after_dawn", 0.02))  # the game begins just after dawn

_world = load_json(DATA_DIR / "world.json") if (DATA_DIR / "world.json").exists() else {}
CLIMATE: Dict[str, Any] = _world.get("climate", {})
SEASON_TEMPS: Dict[str, float] = CLIMATE.get("seasons", {})
SWING: float = CLIMATE.get("day_night_swing", 0)
COMFORT: float = CLIMATE.get("comfort", 18)
FIRE: Dict[str, Any] = _world.get("fire", {})
HOURS_PER_LIFE_HOUR: float = CYCLE_HOURS / 24  # calendar hours in one hour of the day-night cycle


def life_hours_to_calendar(life_hours: float) -> int:
    return int(round(life_hours * HOURS_PER_LIFE_HOUR))


def format_life_duration(calendar_hours: float) -> str:
    """A span of game time as people feel it, in hours and minutes of the day-night cycle."""
    minutes = calendar_hours / HOURS_PER_LIFE_HOUR * 60
    if minutes < 1:
        return "a moment"
    if minutes < 60:
        return f"{round(minutes)} min"
    hours = minutes / 60
    return f"{hours:.1f} h" if hours < 10 else f"{round(hours)} h"


def fire_temperature(firekeeping_skill: float) -> float:
    return FIRE.get("temperature", 22) + FIRE.get("per_skill", 0) * firekeeping_skill


def resting_temperature(fire: float) -> float:
    """What someone sleeping, eating or resting at camp feels by a burning fire: at most 'resting_warmth' degrees
    above comfort (world.json 'fire'; 0 = it only keeps the cold off). To get warm, you sit by the fire (warm up)."""
    return min(fire, COMFORT + FIRE.get("resting_warmth", 0))


def life_days(calendar_hours: float) -> float:
    """How much of a day-night cycle `calendar_hours` of game time is."""
    return calendar_hours / CYCLE_HOURS


def phase(clock: float) -> float:
    """Where we are in the day-night cycle: 0 = midnight, 0.5 = noon."""
    return ((clock % CYCLE_HOURS) / CYCLE_HOURS + START) % 1


def is_night(clock: float) -> bool:
    p = phase(clock)
    return p < DAWN or p >= DUSK


def time_of_day(clock: float) -> str:
    p = phase(clock)
    if p < DAWN - 0.04 or p >= DUSK + 0.08:
        return "Night"
    if p < DAWN + 0.04:
        return "Dawn"
    if p < 0.45:
        return "Morning"
    if p < 0.6:
        return "Midday"
    if p < DUSK - 0.04:
        return "Afternoon"
    return "Dusk"


def temperature(clock: float) -> float:
    """Air temperature: the season's average, warmest at noon, coldest at midnight."""
    base = SEASON_TEMPS.get(season_of(clock), COMFORT)
    return round(base - SWING * math.cos(2 * math.pi * phase(clock)), 1)


def observe(clock: float, fire: Any = None) -> Dict[str, Any]:
    """Plain data about the world now. `fire`: None, or the temperature by the communal fire."""
    p = phase(clock)
    night = is_night(clock)
    # Progress through the current half (day or night), for a progress bar.
    if night:
        length = DAWN + 1 - DUSK
        into = (p - DUSK) % 1
    else:
        length = DUSK - DAWN
        into = p - DAWN
    return {"phase": round(p, 4), "time_of_day": time_of_day(clock), "night": night,
            "half_progress": round(into / length, 3), "temperature": temperature(clock), "comfort": COMFORT,
            "cycle_days": CYCLE_DAYS, "fire": fire is not None,
            "fire_temperature": None if fire is None else round(fire, 1),
            "life_hour_in_calendar_days": round(HOURS_PER_LIFE_HOUR / 24, 1)}

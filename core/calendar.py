"""Game time. The clock counts hours since the start of the game; data/rules/time.json sets the calendar."""
import math
from typing import Dict, List

from utils.game_data import RULES_DIR
from utils.data_files import DATA_DIR, load_json, require

_data = load_json(RULES_DIR / "time.json")
require(isinstance(_data.get("days_per_year"), int) and _data["days_per_year"] > 0, "time.json", "'days_per_year' must be a positive integer")
require(_data.get("seasons") and _data["days_per_year"] % len(_data["seasons"]) == 0, "time.json",
        "'seasons' must divide the year evenly")

HOURS_PER_DAY = 24
DAYS_PER_YEAR: int = _data["days_per_year"]
HOURS_PER_YEAR = DAYS_PER_YEAR * HOURS_PER_DAY
SEASONS: List[str] = _data["seasons"]
DAYS_PER_SEASON = DAYS_PER_YEAR // len(SEASONS)
ACTION_HOURS: Dict[str, int] = _data.get("action_hours", {})
WAIT_DAYS: List[int] = _data.get("wait_days", [1, 7, 30])
NOMINATION_HOURS = int(_data.get("nomination_days", 30) * HOURS_PER_DAY)
VOTING_HOURS = int(_data.get("voting_days", 30) * HOURS_PER_DAY)
MOTION_HOURS = int(_data.get("motion_days", 30) * HOURS_PER_DAY)
REFORM_COOLDOWN_HOURS = int(_data.get("reform_cooldown_years", 3) * HOURS_PER_YEAR)


def year_of(hours: float) -> int:
    return int(hours // HOURS_PER_YEAR)


def day_of_year(hours: float) -> int:
    return int(hours % HOURS_PER_YEAR // HOURS_PER_DAY)


def season_of(hours: float) -> str:
    return SEASONS[day_of_year(hours) // DAYS_PER_SEASON]


def format_date(hours: float, short: bool = False) -> str:
    day = day_of_year(hours) % DAYS_PER_SEASON + 1
    if short:
        return f"Y{year_of(hours)} {season_of(hours)[:3]} {day:>2}"
    return f"Year {year_of(hours)}, {season_of(hours)} day {day}"


def format_duration(hours: float) -> str:
    if hours < HOURS_PER_DAY:
        return f"{int(hours)} hour{'s' if hours != 1 else ''}"
    days = hours / HOURS_PER_DAY
    if days == DAYS_PER_SEASON:
        return "a season"
    if days == 7:
        return "a week"
    return f"{days:g} day{'s' if days != 1 else ''}"


def days_until(now: float, then: float) -> int:
    return max(0, math.ceil((then - now) / HOURS_PER_DAY))

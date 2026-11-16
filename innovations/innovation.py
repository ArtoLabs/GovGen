"""Innovations and ages, loaded from data/ages.json and data/innovations/*.json."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import random

from core.calendar import INNOVATION_COST_MULTIPLIER
from utils.data_files import DATA_DIR, load_json, json_files, require

# Interfaces that may research innovations. Kept here (not imported from roles_config)
# to avoid an import cycle: roles_config -> interfaces -> innovations.
INTERFACE_ICONS = {
    "leadership": "👑",
    "legislative": "📜",
    "judicial": "⚖️",
    "military": "⚔️",
    "intelligence": "🕵️",
    "economic": "💰",
    "infrastructure": "🏗️",
    "religious": "🙏",
    "civic_representation": "🏛️",
}


@dataclass
class Age:
    key: str
    name: str
    description: str
    requires: List[str]
    starting_innovations: List[str] = field(default_factory=list)
    index: int = 0
    government_on_arrival: List[str] = field(default_factory=list)  # first whose research is done, on entering


@dataclass
class Innovation:
    name: str
    interface: str
    age: str
    cost: int = 10
    prerequisites: List[str] = field(default_factory=list)
    description: str = ""
    icon: Optional[str] = None

    def __post_init__(self):
        self.icon = self.icon or INTERFACE_ICONS.get(self.interface, "?")

    @property
    def age_index(self) -> int:
        return AGES_BY_KEY[self.age].index

    def is_discoverable(self, discovered_names: Set[str]) -> bool:
        """Prerequisites met and the innovation's age has been reached."""
        return (
            self.age_index <= reached_age_index(discovered_names)
            and all(prereq in discovered_names for prereq in self.prerequisites)
        )

    def __repr__(self):
        return f"<Innovation {self.name} (Cost: {self.cost})>"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
AGES: List[Age] = []
AGES_BY_KEY: Dict[str, Age] = {}
ALL_INNOVATIONS: Dict[str, Innovation] = {}


def _load():
    AGES.clear(); AGES_BY_KEY.clear(); ALL_INNOVATIONS.clear()

    ages_data = load_json(DATA_DIR / "ages.json")
    require(isinstance(ages_data.get("ages"), list) and ages_data["ages"], "ages.json", "needs a non-empty 'ages' list")
    for i, a in enumerate(ages_data["ages"]):
        where = f"ages.json age #{i + 1}"
        require("key" in a and "name" in a, where, "needs 'key' and 'name'")
        require(a["key"] not in AGES_BY_KEY, where, f"duplicate age key '{a['key']}'")
        age = Age(key=a["key"], name=a["name"], description=a.get("description", ""),
                  requires=a.get("requires", []), starting_innovations=a.get("starting_innovations", []), index=i,
                  government_on_arrival=list(a.get("government_on_arrival", [])))
        AGES.append(age)
        AGES_BY_KEY[age.key] = age

    for path in json_files("innovations"):
        data = load_json(path)
        age_key = data.get("age")
        require(age_key in AGES_BY_KEY, path.name, f"'age' must be one of {list(AGES_BY_KEY)}, got {age_key!r}")
        for entry in data.get("innovations", []):
            where = f"{path.name} '{entry.get('name', '?')}'"
            require("name" in entry and "interface" in entry, where, "needs 'name' and 'interface'")
            require(entry["interface"] in INTERFACE_ICONS, where,
                    f"unknown interface '{entry['interface']}' (use one of {list(INTERFACE_ICONS)})")
            require(entry["name"] not in ALL_INNOVATIONS, where, "duplicate innovation name")
            unknown = set(entry) - {"name", "interface", "cost", "prerequisites", "description", "icon"}
            require(not unknown, where, f"unknown fields {sorted(unknown)}")
            entry = dict(entry)
            entry["cost"] = round(entry.get("cost", 10) * INNOVATION_COST_MULTIPLIER)
            ALL_INNOVATIONS[entry["name"]] = Innovation(age=age_key, **entry)

    # Cross-checks once everything is loaded.
    for innov in ALL_INNOVATIONS.values():
        for prereq in innov.prerequisites:
            require(prereq in ALL_INNOVATIONS, f"innovation '{innov.name}'", f"unknown prerequisite '{prereq}'")
            require(ALL_INNOVATIONS[prereq].age_index <= innov.age_index, f"innovation '{innov.name}'",
                    f"prerequisite '{prereq}' belongs to a later age ({ALL_INNOVATIONS[prereq].age})")
    for age in AGES:
        for name in age.requires:
            require(name in ALL_INNOVATIONS, f"ages.json '{age.key}'", f"unknown required innovation '{name}'")
            require(ALL_INNOVATIONS[name].age_index < age.index, f"ages.json '{age.key}'",
                    f"required innovation '{name}' must come from an earlier age, or the age can never be reached")
        for name in age.starting_innovations:
            require(name in ALL_INNOVATIONS, f"ages.json '{age.key}'", f"unknown starting innovation '{name}'")
    _check_cycles()


def _check_cycles():
    state: Dict[str, int] = {}  # 1 = visiting, 2 = done

    def visit(name: str, path: List[str]):
        if state.get(name) == 2:
            return
        if state.get(name) == 1:
            cycle = path[path.index(name):] + [name]
            require(False, "innovations", "prerequisite cycle: " + " -> ".join(cycle))
        state[name] = 1
        for prereq in ALL_INNOVATIONS[name].prerequisites:
            visit(prereq, path + [prereq])
        state[name] = 2

    for name in ALL_INNOVATIONS:
        visit(name, [name])


def reached_age_index(discovered: Set[str]) -> int:
    """Index of the latest age whose requirements (and all earlier ones) are met."""
    reached = 0
    for age in AGES[1:]:
        if all(req in discovered for req in age.requires):
            reached = age.index
        else:
            break
    return reached


_load()


# --------------------------------------------------------------------------- #
# Pool
# --------------------------------------------------------------------------- #
class InnovationPool:
    def __init__(self):
        self.discovered: Set[str] = set()
        self.points = 100  # Total accumulated innovation points

    def add_points(self, points: int):
        self.points += points

    def spend_points(self, cost: int) -> bool:
        if self.points >= cost:
            self.points -= cost
            return True
        return False

    def discover(self, name: str) -> bool:
        """Attempt to discover a specific innovation (targeted research)."""
        if name not in ALL_INNOVATIONS:
            raise ValueError(f"Unknown innovation: {name}")
        innovation = ALL_INNOVATIONS[name]
        if name not in self.discovered and innovation.is_discoverable(self.discovered) and self.spend_points(innovation.cost):
            self.discovered.add(name)
            return True
        return False

    def discover_random(self) -> Optional[str]:
        affordable = [i for i in self.get_discoverable() if i.cost <= self.points]
        if not affordable:
            return None
        innovation = random.choice(affordable)
        self.discovered.add(innovation.name)
        self.points -= innovation.cost
        return innovation.name

    def get_discovered(self) -> List[Innovation]:
        return [ALL_INNOVATIONS[n] for n in self.discovered]

    def get_discoverable(self) -> List[Innovation]:
        return [i for i in ALL_INNOVATIONS.values()
                if i.name not in self.discovered and i.is_discoverable(self.discovered)]

    def __repr__(self):
        return f"<InnovationPool Points: {self.points}, Discovered: {sorted(self.discovered)}>"

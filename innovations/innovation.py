"""Innovations and ages, loaded from the age folders: data/ages/<age>/age.json and innovations.json."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import random

from utils import game_data
from utils.data_files import require

# The branches of government that may research innovations (data/rules/interfaces.json): key -> symbol.
INTERFACE_ICONS: Dict[str, str] = {
    key: spec.get("symbol", "•")
    for key, spec in game_data.public(game_data.rules("interfaces").get("interfaces", {})).items()}
require(bool(INTERFACE_ICONS), "rules/interfaces.json", "needs at least one interface")


@dataclass
class Age:
    key: str
    name: str
    description: str
    requires: List[str]
    starting_innovations: List[str] = field(default_factory=list)
    index: int = 0
    government_on_arrival: List[str] = field(default_factory=list)  # first whose research is done, on entering
    cost_multiplier: float = 1.0  # every cost in this age's innovations.json is multiplied by it


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

    for i, folder in enumerate(game_data.AGE_FOLDERS):
        a, where = folder.data, f"ages/{folder.key}/age.json"
        mult = a.get("innovation_cost_multiplier", 1)
        require(isinstance(mult, (int, float)) and mult > 0, where, "'innovation_cost_multiplier' must be above 0")
        age = Age(key=folder.key, name=a["name"], description=a.get("description", ""),
                  requires=a.get("requires", []), starting_innovations=a.get("starting_innovations", []), index=i,
                  government_on_arrival=list(a.get("government_on_arrival", [])), cost_multiplier=float(mult))
        AGES.append(age)
        AGES_BY_KEY[age.key] = age

    for folder, file, data in game_data.age_files("innovations"):
        age_key = folder.key
        for entry in data.get("innovations", []):
            where = f"{file} '{entry.get('name', '?')}'"
            require("name" in entry and "interface" in entry, where, "needs 'name' and 'interface'")
            require(entry["interface"] in INTERFACE_ICONS, where,
                    f"unknown interface '{entry['interface']}' (use one of {list(INTERFACE_ICONS)})")
            require(entry["name"] not in ALL_INNOVATIONS, where, "duplicate innovation name")
            unknown = set(entry) - {"name", "interface", "cost", "prerequisites", "description", "icon"}
            require(not unknown, where, f"unknown fields {sorted(unknown)}")
            require(isinstance(entry.get("cost", 10), (int, float)) and entry.get("cost", 10) >= 0, where,
                    "'cost' must be a number of innovation points (0 or more)")
            entry = dict(entry)
            entry["cost"] = round(entry.get("cost", 10) * AGES_BY_KEY[age_key].cost_multiplier)
            ALL_INNOVATIONS[entry["name"]] = Innovation(age=age_key, **entry)

    # Cross-checks once everything is loaded.
    for innov in ALL_INNOVATIONS.values():
        for prereq in innov.prerequisites:
            require(prereq in ALL_INNOVATIONS, f"innovation '{innov.name}'", f"unknown prerequisite '{prereq}'")
            require(ALL_INNOVATIONS[prereq].age_index <= innov.age_index, f"innovation '{innov.name}'",
                    f"prerequisite '{prereq}' belongs to a later age ({ALL_INNOVATIONS[prereq].age})")
    for age in AGES:
        for name in age.requires:
            require(name in ALL_INNOVATIONS, f"ages/{age.key}/age.json", f"unknown required innovation '{name}'")
            require(ALL_INNOVATIONS[name].age_index < age.index, f"ages/{age.key}/age.json",
                    f"required innovation '{name}' must come from an earlier age, or the age can never be reached")
        for name in age.starting_innovations:
            require(name in ALL_INNOVATIONS, f"ages/{age.key}/age.json", f"unknown starting innovation '{name}'")
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

"""Occupations: the work people do (Hunter, Gatherer, Warrior...), loaded from data/occupations.json.

Offices govern; statuses mark standing; occupations are jobs. A person can hold an occupation as well
as an office. Occupations belong to the society rather than to one form of government, so they last
through reforms: each lists the offices (from any government) whose holders may appoint to it, and the
current government decides who that is. When the government has none of those offices, or the
occupation is open to volunteers, members may take it up themselves.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from innovations.innovation import AGES_BY_KEY, ALL_INNOVATIONS, INTERFACE_ICONS
from utils.data_files import DATA_DIR, load_json, require
from world.character import RULES


@dataclass
class Occupation:
    name: str
    description: str
    icon: str
    seats: Optional[int]          # None (the default) = no limit
    appointed_by: List[str]       # office names from any government
    volunteer: bool
    attributes: List[str]         # what makes someone good at it
    skill: Optional[str]          # trained by doing the work
    points: int = 0               # innovation points a year per holder
    requires: List[str] = field(default_factory=list)
    interfaces: List[str] = field(default_factory=list)
    provides: List[str] = field(default_factory=list)  # amenities the group has while anyone holds it
    also_trains: Dict[str, float] = field(default_factory=dict)  # other skills, as a share of the main practice
    needs_tools: List[str] = field(default_factory=list)  # one of these items must exist before anyone takes it up
    age_index: int = 0            # the age it belongs to (counts toward that age's choice of work)
    rank: Optional[float] = None  # place in the hierarchy of work; None = worked out (society.json 'job_rank')


def _load():
    path = DATA_DIR / "occupations.json"
    data = load_json(path) if path.exists() else {"occupations": {}}
    max_per_player = data.get("max_per_player", 1)
    occupations: Dict[str, Occupation] = {}
    for name, o in data.get("occupations", {}).items():
        where = f"occupations.json '{name}'"
        seats = o.get("seats")
        require(seats is None or (isinstance(seats, int) and seats >= 1), where, "'seats' must be a positive integer or null")
        for req in o.get("requires", []):
            require(req in ALL_INNOVATIONS, where, f"unknown innovation '{req}'")
        for a in o.get("attributes", []):
            require(a in RULES.attributes, where, f"unknown attribute '{a}'")
        require(o.get("skill") in (None, *RULES.skills), where, f"unknown skill '{o.get('skill')}'")
        for i in o.get("interfaces", []):
            require(i in INTERFACE_ICONS, where, f"unknown interface '{i}'")
        require(o.get("rank") is None or isinstance(o["rank"], (int, float)), where, "'rank' must be a number")
        require(o.get("age") is None or o["age"] in AGES_BY_KEY, where, f"unknown age '{o.get('age')}'")
        # An occupation belongs to the latest age among the innovations it requires, unless 'age' says otherwise.
        age_index = AGES_BY_KEY[o["age"]].index if o.get("age") else \
            max((ALL_INNOVATIONS[r].age_index for r in o.get("requires", [])), default=0)
        occupations[name] = Occupation(
            name=name, description=o.get("description", ""), icon=o.get("icon", "•"), seats=seats,
            appointed_by=list(o.get("appointed_by", [])), volunteer=bool(o.get("volunteer", False)),
            attributes=list(o.get("attributes", [])), skill=o.get("skill"), points=o.get("points", 0),
            requires=list(o.get("requires", [])), interfaces=list(o.get("interfaces", [])),
            provides=list(o.get("provides", [])), also_trains=dict(o.get("also_trains", {})),
            needs_tools=list(o.get("needs_tools", [])), age_index=age_index, rank=o.get("rank"))
    from world.items import ITEMS
    for name, o in occupations.items():
        for tool in o.needs_tools:
            require(tool in ITEMS, f"occupations.json '{name}'", f"needs_tools names unknown item '{tool}'")
        for skill in o.also_trains:
            require(skill in RULES.skills, f"occupations.json '{name}'", f"also_trains unknown skill '{skill}'")
    return max_per_player, occupations, bool(data.get("office_is_work", False))


MAX_OCCUPATIONS_PER_PLAYER, OCCUPATIONS, OFFICE_IS_WORK = _load()


def check_against_governments(government_types: Dict[str, Any]):
    """Every appointing office must exist in some government, and no name may clash with an office or status."""
    offices = {name for g in government_types.values() for name in g.offices}
    for occ in OCCUPATIONS.values():
        for appointer in occ.appointed_by:
            require(appointer in offices, f"occupations.json '{occ.name}'",
                    f"'appointed_by' names '{appointer}', which is not an office in any government")
        for g in government_types.values():
            require(occ.name not in g.offices and occ.name not in g.statuses, f"occupations.json '{occ.name}'",
                    f"the name is also an office or status in {g.key}.json")

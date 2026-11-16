"""Occupations: the work people do (Hunter, Gatherer, Warrior...). Each is one file in its age's folder,
data/ages/<age>/occupations/<name>.json, holding everything about it: who may do it and what makes them
good at it (here), its tasks and recipes (core/work.py), and what it does for the society ('contributes'
and 'speeds_contentment', core/society.py). A new age brings new occupations by adding files to its folder.

Offices govern; statuses mark standing; occupations are jobs. A person can hold an occupation as well
as an office. Occupations belong to the society rather than to one form of government, so they last
through reforms: each lists the offices (from any government) whose holders may appoint to it, and the
current government decides who that is. When the government has none of those offices, or the
occupation is open to volunteers, members may take it up themselves.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from innovations.innovation import AGES_BY_KEY, ALL_INNOVATIONS, INTERFACE_ICONS
from utils import game_data
from utils.data_files import require
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
    age: str = ""                 # the key of the age whose folder it is in
    contributes: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # society quality -> what a holder adds
    speeds_contentment: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # meter -> curve while working
    rank: Optional[float] = None  # place in the hierarchy of work; None = worked out (society.json 'job_rank')


# The fields of an occupation file that this module reads; 'tasks' and 'recipes' are core/work.py's.
FIELDS = {"name", "description", "icon", "seats", "appointed_by", "volunteer", "attributes", "skill", "points",
          "requires", "interfaces", "provides", "also_trains", "needs_tools", "age", "rank", "contributes",
          "speeds_contentment", "tasks", "recipes"}
OCCUPATION_FILES: Dict[str, Dict[str, Any]] = {}  # name -> the file as written (core/work.py reads its work)
OCCUPATION_WHERE: Dict[str, str] = {}             # name -> 'ages/tribal/occupations/scout.json'


def _load():
    data = game_data.rules("occupations", {})
    max_per_player = data.get("max_per_player", 1)
    occupations: Dict[str, Occupation] = {}
    for folder, where, o in game_data.age_folder_files("occupations"):
        require(isinstance(o.get("name"), str) and o["name"], where, "needs a 'name'")
        name = o["name"]
        require(name not in occupations, where, f"'{name}' is already an occupation ({OCCUPATION_WHERE.get(name)})")
        unknown = set(game_data.public(o)) - FIELDS
        require(not unknown, where, f"unknown fields {sorted(unknown)}")
        OCCUPATION_FILES[name], OCCUPATION_WHERE[name] = o, where
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
        # An occupation counts toward the choice of work of the age whose folder it is in (or 'age', if given).
        # Its research can't come from a later age than that, or nobody could ever take it up in its own age.
        age_key = o.get("age") or folder.key
        age_index = AGES_BY_KEY[age_key].index
        for req in o.get("requires", []):
            require(ALL_INNOVATIONS[req].age_index <= age_index, where,
                    f"requires '{req}', an innovation of a later age ({ALL_INNOVATIONS[req].age}) than its own")
        occupations[name] = Occupation(
            name=name, description=o.get("description", ""), icon=o.get("icon", "•"), seats=seats,
            appointed_by=list(o.get("appointed_by", [])), volunteer=bool(o.get("volunteer", False)),
            attributes=list(o.get("attributes", [])), skill=o.get("skill"), points=o.get("points", 0),
            requires=list(o.get("requires", [])), interfaces=list(o.get("interfaces", [])),
            provides=list(o.get("provides", [])), also_trains=dict(o.get("also_trains", {})),
            needs_tools=list(o.get("needs_tools", [])), age_index=age_index, rank=o.get("rank"), age=age_key,
            contributes={k: dict(v) for k, v in game_data.public(o.get("contributes", {})).items()},
            speeds_contentment={k: dict(v) for k, v in game_data.public(o.get("speeds_contentment", {})).items()})
    from world.items import ITEMS
    for name, o in occupations.items():
        for tool in o.needs_tools:
            require(tool in ITEMS, OCCUPATION_WHERE[name], f"needs_tools names unknown item '{tool}'")
        for skill in o.also_trains:
            require(skill in RULES.skills, OCCUPATION_WHERE[name], f"also_trains unknown skill '{skill}'")
    return max_per_player, occupations, bool(data.get("office_is_work", False))


MAX_OCCUPATIONS_PER_PLAYER, OCCUPATIONS, OFFICE_IS_WORK = _load()


def check_against_governments(government_types: Dict[str, Any]):
    """Every appointing office must exist in some government, and no name may clash with an office or status."""
    offices = {name for g in government_types.values() for name in g.offices}
    for occ in OCCUPATIONS.values():
        for appointer in occ.appointed_by:
            require(appointer in offices, OCCUPATION_WHERE[occ.name],
                    f"'appointed_by' names '{appointer}', which is not an office in any government")
        for g in government_types.values():
            require(occ.name not in g.offices and occ.name not in g.statuses, OCCUPATION_WHERE[occ.name],
                    f"the name is also an office or status in {g.key}.json")

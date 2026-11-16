"""Government types, loaded from data/governments/*.json. See data/README.md for the format."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from innovations.innovation import ALL_INNOVATIONS, AGES, AGES_BY_KEY, INTERFACE_ICONS, reached_age_index
from utils.data_files import json_files, load_json, require

SELECTION_METHODS = {"tribe_vote", "council_vote", "appointment", "divine_sign", "seniority"}
REMOVAL_METHODS = {"tribe_vote", "council_vote", "appointment", "none"}
VOTE_METHODS = {"tribe_vote", "council_vote"}
REFORM_METHODS = {"tribe_vote", "council_vote", "appointment"}
STATUS_EFFECTS = {"loses_office", "cannot_hold_office", "cannot_vote", "no_member_interfaces"}
VOTING_SYSTEM_NAMES = {"first_past_the_post", "ranked_choice", "two_round_runoff"}

METHOD_DESCRIPTIONS = {
    "tribe_vote": "vote of all members",
    "council_vote": "vote of the {council}s",
    "appointment": "appointed by the {appointer}",
    "divine_sign": "a divine sign",
    "seniority": "the oldest eligible member",
    "none": "cannot be removed",
}


def describe_method(spec: Dict[str, Any]) -> str:
    text = METHOD_DESCRIPTIONS[spec["method"]].format(**spec)
    if spec.get("fallback"):
        text += f" ({METHOD_DESCRIPTIONS[spec['fallback']].format(**spec)} while there are none)"
    return text


@dataclass
class Office:
    name: str
    seats: int
    interfaces: List[str]
    selected_by: Dict[str, Any]
    removed_by: Dict[str, Any]
    points: int = 0
    requires: List[str] = field(default_factory=list)
    description: str = ""
    # Other ways to take the office (see data/contests.json): {"persuasion": True, "challenge": ["fight", ...]}
    contested_by: Dict[str, Any] = field(default_factory=dict)
    # How well a holder does the job (see data/society.json): {"attributes": {...}, "skill": "..."}; {} = default
    quality: Dict[str, Any] = field(default_factory=dict)
    rank: Optional[float] = None  # place in the hierarchy of work; None = from points (society.json 'job_rank')
    authority: Optional[float] = None  # place in the hierarchy of appointments; None = its points

    @property
    def persuadable(self) -> bool:
        return bool(self.contested_by.get("persuasion"))

    @property
    def challenge_kinds(self) -> List[str]:
        return list(self.contested_by.get("challenge") or [])


@dataclass
class Status:
    name: str
    granted_by: Dict[str, Any]
    revoked_by: Dict[str, Any]
    effects: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class GovernmentType:
    key: str
    name: str
    age: str
    offices: Dict[str, Office]
    statuses: Dict[str, Status]
    description: str = ""
    requires: List[str] = field(default_factory=list)
    reformed_by: Dict[str, Any] = field(default_factory=lambda: {"method": "tribe_vote"})
    max_offices_per_player: int = 1
    member_interfaces: List[str] = field(default_factory=list)
    member_points: int = 0
    carry_over: Dict[str, str] = field(default_factory=dict)

    @property
    def age_name(self) -> str:
        return AGES_BY_KEY[self.age].name

    @property
    def age_index(self) -> int:
        return AGES_BY_KEY[self.age].index

    def is_available(self, discovered: Set[str]) -> bool:
        return (
            AGES_BY_KEY[self.age].index <= reached_age_index(discovered)
            and all(req in discovered for req in self.requires)
        )


# --------------------------------------------------------------------------- #
# Loading and validation
# --------------------------------------------------------------------------- #
def _check_method(spec: Any, allowed: Set[str], offices: Dict[str, Any], where: str) -> Dict[str, Any]:
    require(isinstance(spec, dict) and spec.get("method") in allowed, where,
            f"'method' must be one of {sorted(allowed)}")
    method = spec["method"]
    if method == "council_vote":
        require(spec.get("council") in offices, where, f"'council' must name an office, got {spec.get('council')!r}")
    if method == "appointment":
        require(spec.get("appointer") in offices, where, f"'appointer' must name an office, got {spec.get('appointer')!r}")
    if "fallback" in spec:
        require(method == "council_vote", where, "'fallback' only applies to council_vote")
        require(spec["fallback"] in VOTE_METHODS - {"council_vote"}, where, "'fallback' must be tribe_vote")
    if "voting_system" in spec:
        require(spec["voting_system"] in VOTING_SYSTEM_NAMES, where,
                f"'voting_system' must be one of {sorted(VOTING_SYSTEM_NAMES)}")
    if "chance" in spec:
        require(isinstance(spec["chance"], (int, float)) and 0 < spec["chance"] <= 1, where, "'chance' must be between 0 and 1")
    return spec


def _check_contested(spec: Any, where: str) -> Dict[str, Any]:
    from core.contests import CHALLENGE_KINDS
    require(isinstance(spec, dict), where, "'contested_by' must be an object")
    unknown = set(spec) - {"persuasion", "challenge"}
    require(not unknown, where, f"'contested_by' has unknown keys {sorted(unknown)} (use persuasion, challenge)")
    for kind in spec.get("challenge") or []:
        require(kind == "skill" or kind in CHALLENGE_KINDS, where,
                f"unknown challenge '{kind}' (use 'skill' or one of {sorted(CHALLENGE_KINDS)})")
    return spec


def _check_innovations(names: List[str], where: str):
    for name in names:
        require(name in ALL_INNOVATIONS, where, f"unknown innovation '{name}'")


def _check_interfaces(names: List[str], where: str):
    for name in names:
        require(name in INTERFACE_ICONS, where, f"unknown interface '{name}' (use one of {list(INTERFACE_ICONS)})")


def _parse(data: Dict[str, Any], file: str) -> GovernmentType:
    for key in ("key", "name", "age", "offices"):
        require(key in data, file, f"missing '{key}'")
    require(data["age"] in AGES_BY_KEY, file, f"'age' must be one of {list(AGES_BY_KEY)}")
    _check_innovations(data.get("requires", []), f"{file} requires")
    _check_interfaces(data.get("member_interfaces", []), f"{file} member_interfaces")

    raw_offices = data["offices"]
    offices: Dict[str, Office] = {}
    for name, o in raw_offices.items():
        where = f"{file} office '{name}'"
        require(isinstance(o.get("seats"), int) and o["seats"] >= 1, where, "'seats' must be a positive integer")
        _check_interfaces(o.get("interfaces", []), where)
        _check_innovations(o.get("requires", []), where)
        require(o.get("rank") is None or isinstance(o["rank"], (int, float)), where, "'rank' must be a number")
        require(o.get("authority") is None or isinstance(o["authority"], (int, float)), where,
                "'authority' must be a number")
        offices[name] = Office(
            name=name,
            seats=o["seats"],
            interfaces=o.get("interfaces", []),
            selected_by=_check_method(o.get("selected_by"), SELECTION_METHODS, raw_offices, f"{where} selected_by"),
            removed_by=_check_method(o.get("removed_by", {"method": "none"}), REMOVAL_METHODS, raw_offices, f"{where} removed_by"),
            points=o.get("points", 0),
            requires=o.get("requires", []),
            description=o.get("description", ""),
            contested_by=_check_contested(o.get("contested_by", {}), where),
            quality=o.get("quality", {}),
            rank=o.get("rank"),
            authority=o.get("authority"),
        )

    statuses: Dict[str, Status] = {}
    for name, s in data.get("statuses", {}).items():
        where = f"{file} status '{name}'"
        require(name not in offices, where, "a status cannot share a name with an office")
        _check_innovations(s.get("requires", []), where)
        for effect in s.get("effects", []):
            require(effect in STATUS_EFFECTS, where, f"unknown effect '{effect}' (use {sorted(STATUS_EFFECTS)})")
        statuses[name] = Status(
            name=name,
            granted_by=_check_method(s.get("granted_by"), REMOVAL_METHODS - {"none"}, raw_offices, f"{where} granted_by"),
            revoked_by=_check_method(s.get("revoked_by", {"method": "none"}), REMOVAL_METHODS, raw_offices, f"{where} revoked_by"),
            effects=s.get("effects", []),
            requires=s.get("requires", []),
            description=s.get("description", ""),
        )

    require("leader_office" not in data, file, "'leader_office' was replaced by 'reformed_by' (see data/README.md)")
    reformed_by = _check_method(data.get("reformed_by", {"method": "tribe_vote"}), REFORM_METHODS, raw_offices,
                                f"{file} reformed_by")
    for old, new in data.get("carry_over", {}).items():
        require(new in offices, f"{file} carry_over", f"'{old}' maps to unknown office '{new}'")

    return GovernmentType(
        key=data["key"], name=data["name"], age=data["age"], offices=offices, statuses=statuses,
        description=data.get("description", ""), requires=data.get("requires", []), reformed_by=reformed_by,
        max_offices_per_player=data.get("max_offices_per_player", 1),
        member_interfaces=data.get("member_interfaces", []), member_points=data.get("member_points", 0),
        carry_over=data.get("carry_over", {}),
    )


def _load() -> Dict[str, GovernmentType]:
    types: Dict[str, GovernmentType] = {}
    for path in json_files("governments"):
        gov = _parse(load_json(path), path.name)
        require(gov.key not in types, path.name, f"duplicate government key '{gov.key}'")
        types[gov.key] = gov
    require(any(g.age == AGES[0].key for g in types.values()), "governments",
            f"at least one government must belong to the first age ('{AGES[0].key}')")
    for age in AGES:
        for key in age.government_on_arrival:
            require(key in types and types[key].age == age.key, f"ages.json '{age.key}' government_on_arrival",
                    f"'{key}' is not a government of the {age.name}")
    all_offices = {name for g in types.values() for name in g.offices}
    for g in types.values():
        for old in g.carry_over:
            require(old in all_offices, f"{g.key}.json carry_over", f"'{old}' is not an office in any government")
    return types


GOVERNMENT_TYPES: Dict[str, GovernmentType] = _load()


def get_government_type(key: str) -> Optional[GovernmentType]:
    return GOVERNMENT_TYPES.get(key.lower())


def starting_government_type() -> GovernmentType:
    return next(g for g in GOVERNMENT_TYPES.values() if g.age == AGES[0].key)


def get_available_government_types(discovered: Set[str]) -> List[GovernmentType]:
    return [g for g in GOVERNMENT_TYPES.values() if g.is_available(discovered)]


def _check_occupations():
    from core.occupations import check_against_governments
    check_against_governments(GOVERNMENT_TYPES)
    from core.work import check_against_governments as check_work
    check_work(GOVERNMENT_TYPES)


_check_occupations()

"""How well the society works and how its members feel about it (data/rules/society.json).

Three layers, each built on the one before:
  Work quality   How well one person does one job or office (0-100): their attributes and skill,
                 scaled down when they are unwell.
  Society        Qualities such as food, leadership, safety, fire, care and culture (0-100), from the
                 work being done against what the group needs. Their weighted average is the society
                 score.
  Satisfaction   Each person's meters (food, work, leaders, society, comfort, safety...), moving over
                 time toward what that person experiences. How fast a meter rises can depend on more
                 (multipliers): Work rises only while someone works their job, faster with the right tools
                 and a wide choice of work for the age; Safety faster while Warriors patrol; Comfort while
                 the Spirit Keeper leads a ritual; Leaders while the other meters rise.

NPCs read these to decide when to act (an unhappy tribe challenges its leaders; a hungry one wants
more hunters), and leadership skill grows or shrinks with the tribe's mood. Everything is data-driven:
add a quality or a meter to the data file and it flows through.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from core import work as work_rules
from core.occupations import OCCUPATIONS
from utils import game_data
from utils.game_data import RULES_DIR
from utils.data_files import DATA_DIR, load_json, require
from world.character import RULES as CHARACTER

if TYPE_CHECKING:
    from core.government import Government
    from world.player import Player

# data/rules/society.json as it is in every age. An age (data/ages/<age>/rules/society.json) or a government
# (its file's "rules": {"society": {...}}) may change any of it, add qualities and meters, or drop them; use_rules()
# below puts the version in force into the tables that follow, in place.
BASE_RULES: Dict[str, Any] = load_json(RULES_DIR / "society.json")
_data: Dict[str, Any] = BASE_RULES
WORK: Dict[str, Any] = {}
OFFICE_DEFAULT: Dict[str, Any] = {}
SATISFACTION: Dict[str, Any] = {}
LEADERSHIP_TRAINING: Dict[str, Any] = {}
JOB_LOSS: Dict[str, Any] = {}
INPUT_VALUES: Dict[str, Dict[str, float]] = {}
POSITIONS: Dict[str, Any] = {}
PATIENCE: Dict[str, Any] = {}
HARDSHIP: Dict[str, Any] = {}
JOB_RANK: Dict[str, Any] = {}
QUALITY_EVENTS: Dict[str, Any] = {}
SUPPLY_CURVE: float = 0.8


def _fill_tables(r: Dict[str, Any]):
    global _data, SUPPLY_CURVE
    _data = r
    fill = game_data.fill
    fill(WORK, r.get("work_quality", {}))
    fill(OFFICE_DEFAULT, r.get("office_quality_default", {"attributes": {"charisma": 1.0}, "skill": None}))
    fill(SATISFACTION, r.get("satisfaction", {}))
    fill(LEADERSHIP_TRAINING, r.get("leadership_training", {}))
    fill(QUALITY_EVENTS, r.get("quality_events", {}))
    # The parts of 'satisfaction' with a table of their own stay one and the same object as that part.
    for table, key in ((JOB_LOSS, "job_loss"), (INPUT_VALUES, "input_values"), (POSITIONS, "positions"),
                       (PATIENCE, "patience"), (HARDSHIP, "hardship"), (JOB_RANK, "job_rank")):
        SATISFACTION[key] = fill(table, SATISFACTION.get(key, {}))
    SUPPLY_CURVE = float(r.get("supply_curve", 0.8))


_fill_tables(BASE_RULES)


@dataclass
class QualityDef:
    key: str
    name: str
    icon: str
    weight: float
    style: str                                  # supply | offices | use
    per_person: float = 0.0
    variety: float = 0.0
    sources: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    requires: List[str] = field(default_factory=list)
    on_hand: Dict[str, Any] = field(default_factory=dict)  # share of the value from what the tribe holds
    sick: Dict[str, Any] = field(default_factory=dict)  # share of the value from how few are ill (data/rules/life.json)
    events: Dict[str, float] = field(default_factory=dict)  # event ('death') -> points it adds at once (fading)
    uses: List[str] = field(default_factory=list)  # style 'use': what raises it ('care:warm_up')
    per_use: float = 0.0               # style 'use': points each use adds
    fall_per_day: float = 0.0          # style 'use': points lost per day-night cycle (0: it stays the same)
    start: float = 50.0                # style 'use': where it begins


@dataclass
class MeterDef:
    key: str
    name: str
    inputs: Dict[str, float]
    bonus: Dict[str, float] = field(default_factory=dict)
    variety_rates: List[float] = field(default_factory=list)  # points per day by kinds of food carried
    expectations: bool = True          # part of it is measured against what they have grown used to
    rise_per_day: float = 1.5          # share of the gap to the target closed per day-night cycle, rising...
    fall_per_day: float = 1.5          # ...and falling
    multipliers: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # what speeds (or slows) the rise
    hunger: Dict[str, Any] = field(default_factory=dict)  # variety meters: going hungry pulls it down
    hardship: List[Dict[str, Any]] = field(default_factory=list)  # troubles that drag the meter down fast

    @property
    def depends_on(self) -> List[str]:
        """Other meters it takes as inputs ('meter:<key>')."""
        return [i[6:] for i in self.inputs if i.startswith("meter:")]


HARDSHIP_SOURCES = ("health", "tribe_distress")  # and 'need:<need>'
SPECIAL_INPUTS = ("society", "needs", "own_work", "working", "fire", "positions_filled")
MULTIPLIERS = ("tools", "job_variety", "fit", "positions_filled", "meters_rising")  # and 'working_now:<job>'


def _check_curve(points, where: str):
    ok = isinstance(points, list) and points and all(
        isinstance(pt, list) and len(pt) == 2 and all(isinstance(x, (int, float)) for x in pt) for pt in points)
    require(ok, where, "'curve' must be a list of [x, multiplier] pairs")


def _job_sources() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """What every occupation adds to each quality, from the occupations' own files ('contributes'):
    {quality: {occupation: spec}}. Offices add theirs when the governments are loaded (register_offices)."""
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for occ in OCCUPATIONS.values():
        for quality, spec in occ.contributes.items():
            out.setdefault(quality, {})[occ.name] = dict(spec)
    return out


def _load():
    qualities = {}
    job_sources = _job_sources()
    for key, q in _data.get("qualities", {}).items():
        if key.startswith("_"):
            continue
        where = f"society.json quality '{key}'"
        q = {**q, "sources": {**q.get("sources", {}), **job_sources.get(key, {})}}
        require(q.get("style") in ("supply", "offices", "use"), where, "'style' must be supply, offices or use")
        require(q.get("style") != "use" or q.get("uses"), where, "a 'use' quality needs 'uses' (e.g. care:warm_up)")
        for src in q.get("sources", {}):
            require(src.startswith("office:") or src in OCCUPATIONS, where, f"unknown source '{src}'")
        on_hand = q.get("on_hand", {})
        if on_hand:
            require(on_hand.get("need") in CHARACTER.needs, where, f"on_hand: unknown need '{on_hand.get('need')}'")
            require(0 <= on_hand.get("share", 0) <= 1, where, "on_hand: 'share' must be between 0 and 1")
            require(on_hand.get("per_member", 0) > 0, where, "on_hand: 'per_member' must be above 0")
        sick = q.get("sick", {})
        if sick:
            require(0 <= sick.get("share", 0) <= 1, where, "sick: 'share' must be between 0 and 1")
            require(sick.get("per_sick", 0) > 0, where, "sick: 'per_sick' must be above 0")
        qualities[key] = QualityDef(key, q.get("name", key), q.get("icon", ""), float(q.get("weight", 1)), q["style"],
                                    float(q.get("per_person", 0)), float(q.get("variety", 0)), q.get("sources", {}),
                                    q.get("requires", []), dict(on_hand), {k: v for k, v in sick.items() if not k.startswith("_")},
                                    {k: float(v) for k, v in q.get("events", {}).items() if not k.startswith("_")},
                                    list(q.get("uses", [])), float(q.get("per_use", 0)), float(q.get("fall_per_day", 0)),
                                    float(q.get("start", 50)))
    meters = {}
    raw = {k: m for k, m in SATISFACTION.get("meters", {}).items() if not k.startswith("_")}
    drift = float(SATISFACTION.get("drift_per_day", 1.5))
    for key, m in raw.items():
        where = f"society.json meter '{key}'"
        for inp in m.get("inputs", {}):
            ok = (inp in SPECIAL_INPUTS or (inp.startswith("quality:") and inp[8:] in qualities)
                  or (inp.startswith("need:") and inp[5:] in CHARACTER.needs)
                  or (inp.startswith("meter:") and inp[6:] in raw and inp[6:] != key))
            require(ok, where, f"unknown input '{inp}'")
        for name, spec in m.get("multipliers", {}).items():
            if name.startswith("working_now:"):
                job = name[12:]
                require(job.startswith("office:") or job in OCCUPATIONS, where,
                        f"multiplier '{name}': unknown occupation '{job}' (offices are 'office:<name>')")
            else:
                require(name in MULTIPLIERS, where, f"unknown multiplier '{name}' (known: {', '.join(MULTIPLIERS)}, "
                                                    "working_now:<job>)")
            _check_curve(spec.get("curve"), f"{where} multiplier '{name}'")
        m = {**m, "multipliers": {**m.get("multipliers", {}),
                                   **{f"working_now:{o.name}": dict(o.speeds_contentment[key])
                                      for o in OCCUPATIONS.values() if key in o.speeds_contentment}}}
        for name, spec in m["multipliers"].items():
            if name.startswith("working_now:"):
                _check_curve(spec.get("curve"), f"{where} multiplier '{name}'")
        meters[key] = MeterDef(key, m.get("name", key), m.get("inputs", {}), m.get("bonus", {}),
                               [float(x) for x in m.get("variety_rates", [])], bool(m.get("expectations", True)),
                               float(m.get("rise_per_day", drift)), float(m.get("fall_per_day", drift)),
                               dict(m.get("multipliers", {})), dict(m.get("hunger", {})),
                               [dict(x) for x in m.get("hardship", []) if isinstance(x, dict)])
        for hs in meters[key].hardship:
            src = hs.get("source", "")
            require(src in HARDSHIP_SOURCES or (src.startswith("need:") and src[5:] in CHARACTER.needs), where,
                    f"hardship: unknown source '{src}' ({', '.join(HARDSHIP_SOURCES)}, need:<need>)")
            require(hs.get("below", 0) > 0, where, "hardship: 'below' must be above 0")
        h = meters[key].hunger
        if h:
            require(h.get("need") in CHARACTER.needs, where, f"hunger: unknown need '{h.get('need')}'")
    return qualities, meters


def _update_order(meters: Dict[str, MeterDef]) -> List[str]:
    """Meters that take other meters as inputs are worked out after those (no meter may depend on itself)."""
    order: List[str] = []
    visiting: set = set()

    def visit(key: str):
        if key in order:
            return
        require(key not in visiting, "society.json meters", f"meter '{key}' depends on itself through 'meter:' inputs")
        visiting.add(key)
        for dep in meters[key].depends_on:
            visit(dep)
        visiting.discard(key)
        order.append(key)
    for k in meters:
        visit(k)
    return order


QUALITIES: Dict[str, QualityDef] = {}
METERS: Dict[str, MeterDef] = {}
UPDATE_ORDER: List[str] = []
_government_types: Dict[str, Any] = {}  # set by register_offices() once the governments are loaded


def _add_offices():
    """What offices add, from the government files: an office's 'contributes' ({quality: spec}) becomes a
    source of that quality, and its 'speeds_contentment' ({meter: {curve}}) a multiplier of that meter while
    a holder works the office. (A quality or meter this age doesn't have is left out.)"""
    for g in _government_types.values():
        for office in g.offices.values():
            for quality, spec in office.contributes.items():
                if quality in QUALITIES:
                    QUALITIES[quality].sources[f"office:{office.name}"] = dict(spec)
            for meter, spec in office.speeds_contentment.items():
                if meter in METERS:
                    METERS[meter].multipliers[f"working_now:office:{office.name}"] = dict(spec)


def use_rules(r: Dict[str, Any]):
    """Put these society rules in force (utils/game_data.py RuleSet does this for the game being played):
    every table of this module is refilled in place, and the qualities and meters are built again."""
    _fill_tables(r)
    qualities, meters = _load()
    game_data.fill(QUALITIES, qualities)
    game_data.fill(METERS, meters)
    UPDATE_ORDER[:] = _update_order(METERS)
    for key, spec in PATIENCE.get("meters", {}).items():
        where = f"society.json satisfaction.patience '{key}'"
        require(key in METERS, where, "unknown meter")
        require(spec.get("grace_life_hours", 0) >= 0 and spec.get("build_up_life_hours", 1) > 0, where,
                "'grace_life_hours' must be 0 or more and 'build_up_life_hours' above 0")
    _add_offices()


use_rules(BASE_RULES)
# Every quality and meter of any age: what occupations and offices may name in 'contributes' and
# 'speeds_contentment' (an occupation of a later age may feed a quality only that age has).
KNOWN_QUALITIES = {k for v in game_data.all_versions("society", BASE_RULES)
                   for k in game_data.public(v.get("qualities", {}))}
KNOWN_METERS = {k for v in game_data.all_versions("society", BASE_RULES)
                for k in game_data.public(v.get("satisfaction", {}).get("meters", {}))}
for _occ in OCCUPATIONS.values():
    for _quality in _occ.contributes:
        require(_quality in KNOWN_QUALITIES, f"occupation '{_occ.name}' contributes",
                f"unknown society quality '{_quality}' (known: {', '.join(sorted(KNOWN_QUALITIES))})")
    for _meter in _occ.speeds_contentment:
        require(_meter in KNOWN_METERS, f"occupation '{_occ.name}' speeds_contentment",
                f"unknown contentment meter '{_meter}'")
game_data.switchable("society", BASE_RULES, use_rules)


def register_offices(government_types: Dict[str, Any]):
    """The governments are loaded (core/government_types.py): check what their offices add, and add it."""
    global _government_types
    for g in government_types.values():
        for office in g.offices.values():
            where = f"{g.key}.json office '{office.name}'"
            for quality in office.contributes:
                require(quality in KNOWN_QUALITIES, f"{where} contributes", f"unknown society quality '{quality}'")
            for meter, spec in office.speeds_contentment.items():
                require(meter in KNOWN_METERS, f"{where} speeds_contentment", f"unknown contentment meter '{meter}'")
                _check_curve(spec.get("curve"), f"{where} speeds_contentment '{meter}'")
    _government_types = government_types
    _add_offices()


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def work_quality(person: 'Player', attributes: Dict[str, float], skill: Optional[str]) -> float:
    """How well `person` does work that needs these attributes and this skill, 0-100."""
    total = sum(attributes.values()) or 1.0
    attr = sum(person.attribute(a) * w for a, w in attributes.items()) / total          # 1-10
    sk = person.skills.get(skill, 0.0) if skill else 0.0                                   # 0-10
    a_share, s_share = WORK.get("attribute_share", 0.6), WORK.get("skill_share", 0.4)
    base = 100 * (a_share * attr / 10 + s_share * sk / 10)
    cond = WORK.get("condition", {})
    base *= 1 - cond.get("health", 0.5) * (1 - person.health / 100)
    base *= 1 - cond.get("energy", 0.3) * (1 - person.needs.get("energy", 100) / 100)
    return round(_clamp(base), 1)


def office_spec(gov: 'Government', office_name: str) -> Dict[str, Any]:
    office = gov.government_type.offices.get(office_name)
    spec = dict(OFFICE_DEFAULT)
    if office is not None and office.quality:
        spec.update(office.quality)
    return spec


def office_quality(gov: 'Government', office_name: str, person: 'Player') -> float:
    spec = office_spec(gov, office_name)
    return work_quality(person, spec.get("attributes", {}), spec.get("skill"))


def occupation_quality(occupation: str, person: 'Player') -> float:
    occ = OCCUPATIONS[occupation]
    return work_quality(person, {a: 1.0 for a in occ.attributes} or {"strength": 1.0}, occ.skill)


def job_quality(gov: 'Government', job: str, person: 'Player') -> float:
    """How well `person` does a job: an occupation's name, or 'office:<name>'."""
    return office_quality(gov, job[7:], person) if job.startswith("office:") else occupation_quality(job, person)


def ability_detail(gov: 'Government', person: 'Player') -> Optional[Dict[str, Any]]:
    """How well someone does their best job right now and why (for display): the job, its skill and their
    level in it, and the points being tired or unwell takes off. None without a job."""
    jobs = [f"office:{o}" for o in gov.offices_of(person)] + gov.occupations_of(person)
    if not jobs:
        return None
    job = max(jobs, key=lambda j: job_quality(gov, j, person))
    if job.startswith("office:"):
        spec = office_spec(gov, job[7:])
        attributes, skill = spec.get("attributes", {}), spec.get("skill")
    else:
        occ = OCCUPATIONS[job]
        attributes, skill = {a: 1.0 for a in occ.attributes} or {"strength": 1.0}, occ.skill
    total = sum(attributes.values()) or 1.0
    attr = sum(person.attribute(a) * w for a, w in attributes.items()) / total
    sk = person.skills.get(skill, 0.0) if skill else 0.0
    rested = 100 * (WORK.get("attribute_share", 0.6) * attr / 10 + WORK.get("skill_share", 0.4) * sk / 10)
    cond = WORK.get("condition", {})
    unwell = rested * cond.get("health", 0.5) * (1 - person.health / 100)
    tired = (rested - unwell) * cond.get("energy", 0.3) * (1 - person.needs.get("energy", 100) / 100)
    return {"job": job[7:] if job.startswith("office:") else job, "value": job_quality(gov, job, person),
            "skill": skill, "skill_name": CHARACTER.skills[skill].name if skill else None, "skill_level": round(sk, 2),
            "attributes": sorted(attributes, key=attributes.get, reverse=True),
            "rested": round(_clamp(rested), 1), "tired": round(tired, 1), "unwell": round(unwell, 1)}


def own_work(gov: 'Government', person: 'Player') -> Optional[float]:
    """The quality of the best work this person holds (office or occupation), or None."""
    scores = [office_quality(gov, o, person) for o in gov.offices_of(person)]
    scores += [occupation_quality(o, person) for o in gov.occupations_of(person)]
    return max(scores) if scores else None


def compute_qualities(gov: 'Government') -> Dict[str, Dict[str, Any]]:
    """Every society quality, with what feeds it: {key: {value, name, icon, weight, active, detail}}."""
    out = {}
    members = [p for p in gov.players if not gov.has_effect(p, "no_member_interfaces")]
    for key, q in QUALITIES.items():
        active = gov.is_unlocked(q.requires)
        if q.style == "use":
            # Raised only by being used (people warming themselves at the fire), not by merely existing.
            level = gov.quality_level(key, q.start)
            detail = {"level": round(level, 1), "per_use": q.per_use, "uses": list(q.uses),
                      "fall_per_day": q.fall_per_day, "shock": round(gov.quality_shock(key), 1)}
            out[key] = {"key": key, "name": q.name, "icon": q.icon, "weight": q.weight, "active": active,
                        "value": round(supply_value(detail), 1), "detail": detail}
            continue
        if q.style == "offices":
            total_w, score = 0.0, 0.0
            seats = []
            for office in gov.government_type.offices.values():
                if not gov.is_unlocked(office.requires):
                    continue
                holders = gov.get_role_holders(office.name)
                w = max(1, office.points)
                for i in range(office.seats):
                    val = office_quality(gov, office.name, holders[i]) if i < len(holders) else 0.0
                    score += w * val
                    total_w += w
                    seats.append((office.name, holders[i].name if i < len(holders) else None, val))
            value = score / total_w if total_w else 0.0
            detail = {"seats": seats}
            shock = gov.quality_shock(key)
            if shock:
                detail["shock"] = round(shock, 1)
                value += shock
        else:
            supply, categories, all_categories = 0.0, set(), set()
            workers, contrib = [], {}
            for src, spec in q.sources.items():
                cat = spec.get("category")
                if cat:
                    all_categories.add(cat)
                # A job counts only while it is being worked (core/work.py), and 'while_working' times over
                # while its work is being done right now (a Warrior out on patrol). An office counts always
                # if it has no work of its own.
                busy = float(spec.get("while_working", 1.0))
                if src.startswith("office:"):
                    office = src[7:]
                    gated = bool(work_rules.tasks_of_job(src))
                    people = [(p, office_quality(gov, office, p) * (gov.work_activity(p.name) if gated else 1.0)
                               * (busy if gov.working_now(p.name) == src else 1.0)) for p in gov.get_role_holders(office)]
                else:
                    people = [(p, occupation_quality(src, p) * gov.work_activity(p.name)
                               * (busy if gov.working_now(p.name) == src else 1.0)) for p in gov.occupations.get(src, [])]
                for p, wq in people:
                    supply += spec.get("amount", 1.0) * wq / 50
                    contrib[p.name] = contrib.get(p.name, 0.0) + spec.get("amount", 1.0) * wq / 50
                    workers.append((src, p.name, wq))
                    if cat and wq > 0:  # a Fisher with no spear brings in no fish
                        categories.add(cat)
            need = q.per_person * max(1, len(members))
            detail = {"supply": round(supply, 2), "need": round(need, 2), "workers": workers,
                      "contrib": {k: round(v, 3) for k, v in contrib.items()}, "variety": q.variety,
                      "sources": {s: {"amount": sp.get("amount", 1.0), "category": sp.get("category")}
                                  for s, sp in q.sources.items()},
                      "categories": sorted(categories), "all_categories": sorted(all_categories)}
            have = gov.supply_of(q.on_hand["need"]) if q.on_hand else None
            if have is not None:
                # What the tribe actually holds (camp store and packs) against what it should, so the quality
                # can't read full while people go hungry.
                want = q.on_hand["per_member"] * max(1, len(members))
                detail["on_hand"] = {"have": round(have), "want": round(want), "share": q.on_hand["share"],
                                     "value": round(100 * min(1.0, have / want), 1)}
            if q.sick:
                # How many are ill (core/life.py): the Care quality can't read full while people lie sick, so
                # leaders see that a Healer is needed (and that taking one away would hurt).
                n = gov.sick_count()
                cover = float(q.sick.get("cover_supply", 1.0))
                detail["sick"] = {"count": n, "share": q.sick["share"], "per_sick": q.sick["per_sick"], "cover_supply": cover,
                                  "value": round(_clamp(100 - q.sick["per_sick"] * n * (1 - min(1.0, supply / cover))), 1)}
            shock = gov.quality_shock(key)
            if shock:
                detail["shock"] = round(shock, 1)  # a death, say: a chunk out of it that slowly comes back
            value = supply_value(detail)
        out[key] = {"key": key, "name": q.name, "icon": q.icon, "weight": q.weight, "active": active,
                    "value": round(_clamp(value), 1), "detail": detail}
    return out


def supply_value(detail: Dict[str, Any], supply_delta: float = 0.0, categories=None) -> float:
    """What a supply-style quality would be worth with `supply_delta` more (or less) supply and these
    food categories (default: as now). Plain data in, so a client or an NPC can weigh a change. With an
    'on_hand' part, more supply is reckoned to fill the tribe's stocks in proportion: supply worth the
    whole need fills them completely."""
    if "level" in detail:  # a 'use' quality: only using it moves it
        return _clamp(detail["level"] + detail.get("shock", 0.0))
    need = detail.get("need", 0)
    ratio = (detail.get("supply", 0) + supply_delta) / need if need else 1.0
    value = 100 * min(1.0, max(0.0, ratio)) ** SUPPLY_CURVE
    held = detail.get("on_hand")
    if held:
        # From the actual stock, not the capped value: a store already overflowing doesn't miss one worker.
        base = 100 * held["have"] / held["want"] if held.get("want") else held["value"]
        stock = _clamp(base + (100 * supply_delta / need if need else 0.0))
        value = (1 - held["share"]) * value + held["share"] * stock
    sick = detail.get("sick")
    if sick:
        # Healing work sees to the sick: supply of 'cover_supply' (about one Healer) sees to them all.
        covered = min(1.0, max(0.0, detail.get("supply", 0) + supply_delta) / max(1e-6, sick.get("cover_supply", 1.0)))
        well = _clamp(100 - sick["per_sick"] * sick["count"] * (1 - covered))
        value = (1 - sick["share"]) * value + sick["share"] * well
    variety, all_cats = detail.get("variety", 0), detail.get("all_categories", [])
    cats = set(detail.get("categories", [])) if categories is None else set(categories)
    if variety and all_cats:
        value *= 1 - variety + variety * len(cats & set(all_cats)) / len(all_cats)
    return _clamp(value + detail.get("shock", 0.0))


def society_score(qualities: Dict[str, Dict[str, Any]]) -> float:
    active = [q for q in qualities.values() if q["active"]]
    total = sum(q["weight"] for q in active)
    return round(sum(q["value"] * q["weight"] for q in active) / total, 1) if total else 50.0


def curve(points: List[List[float]], x: float) -> float:
    """Read a multiplier off a curve of [x, value] points: a straight line between them, flat beyond the ends."""
    pts = sorted(points)
    if x <= pts[0][0]:
        return float(pts[0][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return float(y1 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0))
    return float(pts[-1][1])


def job_variety(gov: 'Government') -> Tuple[int, int]:
    """(open, possible): occupations researched so far, out of every occupation of the ages reached."""
    possible = [o for o in OCCUPATIONS.values() if o.age_index <= gov.age_index]
    return sum(gov.is_unlocked(o.requires) for o in possible), len(possible)


def positions_filled(gov: 'Government') -> Tuple[int, int]:
    """(filled, out of): office seats taken and occupations someone does, out of all there are (see
    society.json 'positions'; never more than the tribe has members, with 'cap_at_members')."""
    members = [p for p in gov.players if not gov.has_effect(p, "no_member_interfaces")]
    filled = total = 0
    if POSITIONS.get("office_seats", True):
        for office in gov.government_type.offices.values():
            if gov.is_unlocked(office.requires):
                total += office.seats
                filled += min(office.seats, len(gov.get_role_holders(office.name)))
    if POSITIONS.get("occupations", True):
        for occ in OCCUPATIONS.values():
            if not gov.is_unlocked(occ.requires):
                continue
            held = bool(gov.occupations.get(occ.name))
            if held or not occ.needs_tools or any(gov.tools_available(occ.needs_tools, p) for p in members):
                total += 1
                filled += held
    if POSITIONS.get("cap_at_members", True) and members:
        total = min(total, len(members))
    return min(filled, total), total


def contentment_context(gov: 'Government') -> Dict[str, Any]:
    """What everyone's meters share: who is doing their job's work right now, the choice of work, how many
    positions are filled, and the fire."""
    working = {p.name: gov.working_now(p.name) for p in gov.players}
    counts: Dict[str, int] = {}
    for job in working.values():
        if job:
            counts[job] = counts.get(job, 0) + 1
    return {"working": working, "working_counts": counts, "variety": job_variety(gov),
            "filled": positions_filled(gov), "fire": gov.fire_state()}


def _share(pair: Tuple[int, int]) -> float:
    return pair[0] / pair[1] if pair[1] else 1.0


def _input_value(inp: str, person: 'Player', gov: 'Government', qualities: Dict[str, Dict[str, Any]],
                 overall: float, ctx: Dict[str, Any]) -> Optional[float]:
    """What one input of a meter is worth for this person now (None: it doesn't count yet)."""
    if inp == "society":
        return overall
    if inp == "needs":
        return sum(person.needs.values()) / max(1, len(person.needs))
    if inp == "own_work":
        x = own_work(gov, person)
        return SATISFACTION.get("no_work", 35) if x is None else x
    if inp == "working":
        vals = INPUT_VALUES.get("working", {})
        if ctx["working"].get(person.name):
            return vals.get("working", 100)
        return vals.get("idle_with_job", 20) if gov.jobs_of(person) else vals.get("idle_without_job", 5)
    if inp == "fire":
        return INPUT_VALUES.get("fire", {}).get(ctx["fire"], {"tended": 100, "untended": 55}.get(ctx["fire"], 0))
    if inp == "positions_filled":
        return 100 * _share(ctx["filled"])
    if inp.startswith("need:"):
        return person.needs.get(inp[5:], 50)
    if inp.startswith("meter:"):
        return person.satisfaction.get(inp[6:], SATISFACTION.get("start", 60))
    q = qualities.get(inp[8:])
    return q["value"] if q is not None and q["active"] else None


def meter_target(meter: MeterDef, person: 'Player', gov: 'Government', qualities: Dict[str, Dict[str, Any]],
                 overall: float, ctx: Optional[Dict[str, Any]] = None) -> float:
    """Where the meter is heading for this person: the weighted average of its inputs, plus bonuses."""
    ctx = ctx if ctx is not None else contentment_context(gov)
    total, value = 0.0, 0.0
    for inp, w in meter.inputs.items():
        x = _input_value(inp, person, gov, qualities, overall, ctx)
        if x is None:
            continue
        value += w * x
        total += w
    target = value / total if total else 50.0
    if meter.bonus.get("holds_office") and gov.offices_of(person):
        target += meter.bonus["holds_office"]
    return _clamp(target)


def _job_label(job: str) -> str:
    return job[7:] if job.startswith("office:") else job


def rise_multiplier(meter: MeterDef, person: 'Player', gov: 'Government', ctx: Dict[str, Any],
                    rose: Optional[Dict[str, bool]] = None) -> Tuple[float, List[Dict[str, Any]]]:
    """How much faster (or slower) than 'rise_per_day' the meter rises for this person now, and why:
    (product, [{'key', 'label', 'detail', 'mult'}, ...]). `rose`: which meters rose this update."""
    total, factors = 1.0, []
    for name, spec in meter.multipliers.items():
        points = spec["curve"]
        if name == "tools":
            if not gov.jobs_of(person):
                continue
            have, invented = gov.job_tools(person)
            if not invented:
                m, label, detail = float(spec.get("none_invented", 1.0)), "Tools", "none made for this work yet"
            else:
                m, label, detail = curve(points, have), "Tools", f"{have} for the job" if have else "none for the job"
        elif name == "job_variety":
            n_open, possible = ctx["variety"]
            m, label, detail = curve(points, _share(ctx["variety"])), "Choice of work", f"{n_open} of {possible} jobs of the age"
        elif name == "fit":
            job = gov.appointed_job(person) if spec.get("appointed_only") else None
            if spec.get("appointed_only"):
                if not job:
                    continue
                q = job_quality(gov, job, person)
                label, detail = "Fit", f"{q:.0f} as the appointed {_job_label(job)}"
            else:
                q = own_work(gov, person)
                if q is None:
                    continue
                label, detail = "Fit", f"{q:.0f}"
            m = curve(points, q)
        elif name == "positions_filled":
            filled, out_of = ctx["filled"]
            m, label, detail = curve(points, _share(ctx["filled"])), "Positions", f"{filled} of {out_of} filled"
        elif name == "meters_rising":
            deps = meter.depends_on
            if not deps or rose is None:
                continue
            up = sum(1 for d in deps if rose.get(d))
            m, label, detail = curve(points, up / len(deps)), "Life getting better", f"{up} of {len(deps)} rising"
        else:  # working_now:<job>
            job = name[12:]
            n = ctx["working_counts"].get(job, 0)
            m = curve(points, n)
            label = f"{_job_label(job)} at work"
            detail = f"{n} now" if n else "nobody now"
        total *= m
        factors.append({"key": name, "label": label, "detail": detail, "mult": round(m, 2)})
    return total, factors


def update_satisfaction(people: List['Player'], gov: 'Government', qualities, overall: float, life_days: float):
    """Move everyone's meters a step toward what they experience. Part of most meters is relative to
    what the person has grown used to (their expectation, which slowly follows reality): things
    getting better pleases, things getting worse displeases, even when they are still good. Rising is
    faster or slower by the meter's multipliers (tools, choice of work, Warriors on patrol...)."""
    fade = 0.5 ** (life_days * 24 / max(1e-6, JOB_LOSS.get("grievance_half_life_life_hours", 24)))
    exp_cfg = SATISFACTION.get("expectations", {})
    share = exp_cfg.get("share", 0.0)
    exp_rate = min(1.0, exp_cfg.get("drift_per_day", 0.35) * life_days)
    start = SATISFACTION.get("start", 60)
    ctx = contentment_context(gov)
    distress = tribe_distress(people)
    from world.items import food_variety
    events: List[Tuple['Player', Dict[str, str]]] = []
    for p in people:
        rose: Dict[str, bool] = {}
        detail: Dict[str, Dict[str, Any]] = {}
        for key in UPDATE_ORDER:
            meter = METERS[key]
            current = p.satisfaction.get(key, start)
            if meter.variety_rates:
                # Food contentment follows what is in the person's own pack, not how the tribe looks.
                rates = meter.variety_rates
                kinds = food_variety(p.inventory)
                per_day = rates[min(kinds, len(rates) - 1)]
                factors = [{"key": "variety", "label": "Kinds of food carried", "detail": str(kinds), "mult": None}]
                # Going hungry: whatever the pack holds, a starving person is not content with food
                # ('hunger': falls faster the hungrier, and can't sit more than 'cap_above_need' above the need).
                h, cap = meter.hunger, 100.0
                level = p.needs.get(h.get("need", ""), 100) if h else 100
                if h and level < h.get("below", 40):
                    short = 1 - level / max(1e-6, h.get("below", 40))
                    per_day -= h.get("fall_per_day_at_zero", 120) * short
                    cap = level + h.get("cap_above_need", 30)
                    factors.append({"key": "hunger", "label": "Going hungry", "detail": f"{level:.0f}", "mult": None})
                p.satisfaction[key] = min(cap, _clamp(current + per_day * life_days - p.grievances.get(key, 0) * life_days))
                hard = _hardship(meter, p, distress, life_days)
                factors += hard
                rose[key] = p.satisfaction[key] > current
                detail[key] = {"rising": per_day > 0 and not hard, "per_day": per_day, "factors": factors}
                continue
            actual = meter_target(meter, p, gov, qualities, overall, ctx)
            grievance = p.grievances.get(key, 0)
            if meter.expectations and share:
                expected = p.expectations.get(key, actual)
                target = _clamp((1 - share) * actual + share * (50 + actual - expected) - grievance)
                p.expectations[key] = expected + (actual - expected) * exp_rate
            else:
                target = _clamp(actual - grievance)
            mult, factors = rise_multiplier(meter, p, gov, ctx, rose)
            rising = target > current
            speed = meter.rise_per_day * mult if rising else meter.fall_per_day
            p.satisfaction[key] = current + (target - current) * min(1.0, speed * life_days)
            hard = _hardship(meter, p, distress, life_days)
            factors = factors + hard
            if hard:
                rising = False
            rose[key] = p.satisfaction[key] > current + 1e-9
            detail[key] = {"target": round(target, 1), "rising": rising, "multiplier": round(mult, 2),
                           "per_day": round(speed, 3), "factors": factors}
        p.content_detail = detail
        changes = _update_unrest(p, life_days)
        if changes:
            events.append((p, changes))
        for key in list(p.grievances):
            p.grievances[key] *= fade
            if abs(p.grievances[key]) < 0.5:  # (goodwill is a grievance below 0)
                del p.grievances[key]
    return events




def in_distress(p: 'Player') -> bool:
    """Ill, starving, parched or freezing (a need below critical), or with health very low."""
    return bool(p.illness) or bool(p.critical_needs()) or p.health < HARDSHIP.get("weak_below", 35)


def tribe_distress(people: List['Player']) -> float:
    """0-100: how well the tribe is doing in body, 100 when nobody is in distress (see in_distress)."""
    return 100.0 * (1 - sum(1 for p in people if in_distress(p)) / len(people)) if people else 100.0


def _hardship(meter: MeterDef, p: 'Player', distress: float, life_days: float) -> List[Dict[str, Any]]:
    """Troubles that drag a meter down fast (society.json meters' 'hardship'): while the source (a need, health,
    or how much of the tribe is in distress) is below 'below', the meter loses up to 'fall_per_day_at_zero'
    (all of it at 0) and can't sit more than 'cap_above' above the source. Returns the factors, for display."""
    out = []
    for hs in meter.hardship:
        src = hs["source"]
        level = p.needs.get(src[5:], 100) if src.startswith("need:") else p.health if src == "health" else distress
        below = hs["below"]
        if level >= below:
            continue
        short = 1 - level / below
        val = p.satisfaction.get(meter.key, 50) - hs.get("fall_per_day_at_zero", 100) * short * life_days
        if "cap_above" in hs:
            val = min(val, level + hs["cap_above"])
        p.satisfaction[meter.key] = _clamp(min(val, p.satisfaction.get(meter.key, 50)))
        label = hs.get("label") or (CHARACTER.needs[src[5:]].name if src.startswith("need:") else
                                    "Health" if src == "health" else "The tribe suffering")
        out.append({"key": "hardship", "label": label, "detail": f"{level:.0f} (below {below:g})", "mult": None})
    return out


def _update_unrest(p: 'Player', life_days: float) -> Dict[str, str]:
    """Count the cycle-hours each patience meter (society.json 'satisfaction.patience') has been low,
    draining faster once it is back up. Returns {meter: 'thin' | 'out'} for patience that just wore thin
    or ran out (for the chronicle)."""
    hours = life_days * 24
    changes: Dict[str, str] = {}
    for key, spec in PATIENCE.get("meters", {}).items():
        before = patience_left(p, key)
        unrest = p.unrest.get(key, 0.0)
        if p.satisfaction.get(key, 50) < spec.get("below", 55):
            unrest = min(PATIENCE.get("max_life_hours", 30), unrest + hours)
        else:
            unrest = max(0.0, unrest - hours * PATIENCE.get("recover", 2.0))
        if unrest > 0:
            p.unrest[key] = unrest
        else:
            p.unrest.pop(key, None)
        after = patience_left(p, key)
        warn = 1 - PATIENCE.get("warn_at", 0.6)
        if before > 0 and after <= 0:
            changes[key] = "out"
        elif before > warn >= after:
            changes[key] = "thin"
    return changes


def patience_left(p: 'Player', meter: str) -> float:
    """1 while someone hasn't been unhappy with this meter at all, down to 0 once their patience has run
    out (meters without patience rules: always 0, their discontent counts at once)."""
    spec = PATIENCE.get("meters", {}).get(meter)
    if not spec:
        return 0.0
    grace = spec.get("grace_life_hours", 10)
    return max(0.0, 1 - p.unrest.get(meter, 0.0) / grace) if grace > 0 else 0.0


def restless(p: 'Player', meter: str) -> float:
    """How much of someone's discontent with this meter they are ready to act on: 0 during the grace
    period, rising to 1 over 'build_up_life_hours' after it (1 for meters without patience rules)."""
    spec = PATIENCE.get("meters", {}).get(meter)
    if not spec:
        return 1.0
    over = p.unrest.get(meter, 0.0) - spec.get("grace_life_hours", 10)
    return max(0.0, min(1.0, over / spec.get("build_up_life_hours", 6)))


def patience_view(p: 'Player') -> Dict[str, Dict[str, float]]:
    """For the view: per patience meter, unrest hours, the grace, how much patience is left, how restless."""
    return {k: {"unrest": round(p.unrest.get(k, 0.0), 1), "grace": spec.get("grace_life_hours", 10),
                "below": spec.get("below", 55), "left": round(patience_left(p, k), 2), "restless": round(restless(p, k), 2)}
            for k, spec in PATIENCE.get("meters", {}).items()}


def job_loss(person: 'Player', how: str, people: List['Player']) -> Dict[str, float]:
    """`person` was dismissed from their work ('dismissed') or moved to other work ('reassigned').
    Their meters drop at once ('hit') and a grievance holds them down for a while, fading by half every
    'grievance_half_life_life_hours'; repeated dismissals add up (to 'max_grievance'). Everyone else's
    meters take the 'onlookers' hit: a leader who keeps shuffling people unsettles the whole tribe.
    Returns the hit to the person, for the chronicle."""
    def strike(p: 'Player', spec: Dict[str, Any]):
        for key, n in spec.get("hit", {}).items():
            if key in METERS:
                p.satisfaction[key] = _clamp(p.satisfaction.get(key, SATISFACTION.get("start", 60)) - n)
        for key, n in spec.get("grievance", {}).items():
            if key in METERS:
                p.grievances[key] = min(JOB_LOSS.get("max_grievance", 60), p.grievances.get(key, 0) + n)
    spec = JOB_LOSS.get(how, {})
    strike(person, spec)
    onlookers = spec.get("onlookers", JOB_LOSS.get("onlookers", {}))  # a kind of loss may set its own
    for other in people:
        if other is not person:
            strike(other, onlookers)
    return {METERS[k].name: n for k, n in spec.get("hit", {}).items() if k in METERS}




def _research_steps(name: str, memo: Dict[str, int]) -> int:
    """The longest chain of researched innovations ending in this one (starting innovations count 0)."""
    from innovations.innovation import AGES, ALL_INNOVATIONS
    if name not in memo:
        starting = {n for a in AGES for n in a.starting_innovations}
        memo[name] = 0  # (no cycles: innovations are checked for them)
        if name not in starting:
            memo[name] = 1 + max((_research_steps(p, memo) for p in ALL_INNOVATIONS[name].prerequisites), default=0)
    return memo[name]


def job_rank(gov: 'Government', job: Optional[str]) -> float:
    """Where a job stands in the hierarchy of work (society.json 'job_rank'): None (no work) is 0; an
    occupation counts its research steps and whether it needs tools; an office its points. A 'rank' in
    the data overrides either."""
    if not job:
        return 0.0
    if job.startswith("office:"):
        office = gov.government_type.offices.get(job[7:])
        if office is None:
            return 0.0
        return float(office.rank) if office.rank is not None else JOB_RANK.get("office_per_point", 1) * office.points
    occ = OCCUPATIONS[job]
    if occ.rank is not None:
        return float(occ.rank)
    memo: Dict[str, int] = {}
    steps = max((_research_steps(r, memo) for r in occ.requires), default=0)
    return JOB_RANK.get("research_step", 1) * steps + (JOB_RANK.get("tools", 1) if occ.needs_tools else 0)


def job_change(gov: 'Government', person: 'Player', old: Optional[str], new: Optional[str]) -> float:
    """`person` was appointed from `old` work (None: none) to `new`. Moving up the hierarchy warms them to
    the leaders, moving down sours them; the same rank leaves them as they were. Returns the points their
    meter moved at once (for the chronicle)."""
    key = JOB_RANK.get("meter", "leaders")
    if key not in METERS:
        return 0.0
    steps = job_rank(gov, new) - job_rank(gov, old)
    if not steps:
        return 0.0
    cap = JOB_RANK.get("max_points", 20)
    spec = JOB_RANK.get("up" if steps > 0 else "down", {})
    hit = min(cap, abs(steps) * spec.get("hit", 0)) * (1 if steps > 0 else -1)
    lasting = min(cap, abs(steps) * spec.get("goodwill" if steps > 0 else "grievance", 0))
    person.satisfaction[key] = _clamp(person.satisfaction.get(key, SATISFACTION.get("start", 60)) + hit)
    limit = JOB_LOSS.get("max_grievance", 60)
    person.grievances[key] = max(-limit, min(limit, person.grievances.get(key, 0) + (-lasting if steps > 0 else lasting)))
    return hit


def init_satisfaction(people: List['Player']):
    """Give everyone each meter at its starting value (a loaded save overrides this)."""
    for p in people:
        for key in METERS:
            p.satisfaction.setdefault(key, float(SATISFACTION.get("start", 60)))


def mood(person: 'Player') -> float:
    """Overall satisfaction: the average of a person's meters."""
    vals = [person.satisfaction.get(k, 50) for k in METERS]
    return sum(vals) / len(vals) if vals else 50.0


def leadership_direction(people: List['Player']) -> float:
    """+1 when the tribe is content, -1 when it is not (scales office-skill practice)."""
    meter = LEADERSHIP_TRAINING.get("meter", "society")
    vals = [p.satisfaction.get(meter, 50) for p in people]
    avg = sum(vals) / len(vals) if vals else 50
    return max(-1.0, min(1.0, (avg - LEADERSHIP_TRAINING.get("neutral_at", 50)) / LEADERSHIP_TRAINING.get("span", 25)))


def leadership_practice(worked: float, direction: float) -> float:
    """Share of a day's practice the office skill gets: 'while_working' x how recently they worked their
    office, plus 'tribe_share' x the tribe's mood (leadership_direction, -1 to 1)."""
    t = LEADERSHIP_TRAINING
    return t.get("while_working", 1.0) * worked + t.get("tribe_share", 1.0) * direction




def event_points(event: str) -> Dict[str, float]:
    """What an event ('death') does at once to the qualities that name it in their 'events'."""
    return {k: q.events[event] for k, q in QUALITIES.items() if event in q.events}


def use_points(use: str) -> Dict[str, float]:
    """What one use ('care:warm_up') adds to the 'use' qualities it raises."""
    return {k: q.per_use for k, q in QUALITIES.items() if q.style == "use" and use in q.uses}


def quality_fed_by(occupation: str) -> List[str]:
    """Which society qualities this occupation feeds."""
    return [k for k, q in QUALITIES.items() if occupation in q.sources]

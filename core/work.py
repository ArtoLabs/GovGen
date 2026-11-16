"""Work that produces things (data/work.json): tasks people do in their job, and recipes they craft.

The engine (core/engine.py) offers them as 'work' and 'craft' actions, takes inputs and tools when the
work starts, and delivers what it yields into the camp store when it is done. This module only loads and
checks the data and works out yields, so a server or an Unreal client can use the same rules.
"""
import random
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from core.occupations import OCCUPATIONS
from innovations.innovation import ALL_INNOVATIONS
from utils.data_files import DATA_DIR, load_json, require
from world.character import RULES as CHARACTER
from world.items import ITEMS

_data = load_json(DATA_DIR / "work.json")


@dataclass
class Task:
    key: str
    label: str
    occupations: List[str]            # empty (and no 'offices'): anyone may do it
    life_hours: float
    skill: Optional[str] = None
    requires: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)      # needs one of these (first found)
    consumes: List[Dict[str, Any]] = field(default_factory=list)
    yields: List[Dict[str, Any]] = field(default_factory=list)
    boost: Dict[str, float] = field(default_factory=dict)
    tool_yields: Dict[str, float] = field(default_factory=dict)
    tool_consumes: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    fire_life_hours: float = 0.0
    recipe: bool = False
    site: Optional[str] = None        # a trip out: succeeds far more often at a known site of this kind
    finds_sites: bool = False         # the Scout's ranging: may find a site
    scouts_for: Optional[str] = None  # the site kind this ranging looks for (one task per kind, see _load)
    offices: List[str] = field(default_factory=list)  # offices whose holders do this as their work
    any_office: bool = False          # the work of any office that has no task of its own
    chance: Optional[float] = None    # a trip's own chance of finding anything (default: trips.base_chance)
    makes_sites: Dict[str, Any] = field(default_factory=dict)  # {kinds: {kind: weight}, life_hours}: plants a site
    speed_tools: Dict[str, float] = field(default_factory=dict)  # tool -> how many times faster the work goes
    disposes_of_dead: bool = False    # lays one of the dead lying in camp to rest (core/life.py)
    illness_risk: Optional[float] = None  # x the illness 'work_chance' (life.json); None: 1 for job work, else 0
    done_text: str = ""               # what the chronicle says when done ('carries {body} away')

    @property
    def output_items(self) -> List[str]:
        return [y["item"] for y in self.yields]

    @property
    def open_to_anyone(self) -> bool:
        return not self.occupations and not self.offices and not self.any_office


def _stacks(entries, where) -> List[Dict[str, Any]]:
    for e in entries:
        require(e.get("item") in ITEMS, where, f"unknown item '{e.get('item')}'")
    return [{"item": e["item"], "count": int(e.get("count", 1))} for e in entries]


def _check_common(t: Dict[str, Any], where: str):
    for o in t.get("occupations", []):
        require(o in OCCUPATIONS, where, f"unknown occupation '{o}'")
    require(isinstance(t.get("offices", []), list), where, "'offices' must be a list of office names")
    for r in t.get("requires", []):
        require(r in ALL_INNOVATIONS, where, f"unknown innovation '{r}'")
    require(t.get("skill") in (None, *CHARACTER.skills), where, f"unknown skill '{t.get('skill')}'")
    for tool in t.get("tools", []):
        require(tool in ITEMS, where, f"unknown tool '{tool}'")
    for tool in t.get("boost", {}):
        require(tool in ITEMS, where, f"unknown boost tool '{tool}'")
    for tool, x in t.get("speed_tools", {}).items():
        require(tool in ITEMS and x > 0, where, f"speed_tools: unknown tool '{tool}' or speed not above 0")


def _load():
    tasks: Dict[str, Task] = {}
    for key, t in _data.get("tasks", {}).items():
        where = f"work.json task '{key}'"
        _check_common(t, where)
        for y in t.get("yields", []):
            require(y.get("item") in ITEMS, where, f"unknown item '{y.get('item')}'")
        tasks[key] = Task(key, t.get("label", key), list(t.get("occupations", [])), float(t.get("life_hours", 1)),
                          t.get("skill"), list(t.get("requires", [])), list(t.get("tools", [])),
                          _stacks(t.get("consumes", []), where),
                          [{"item": y["item"], "amount": float(y.get("amount", 1)), "chance": float(y.get("chance", 1))}
                           for y in t.get("yields", [])],
                          dict(t.get("boost", {})), dict(t.get("tool_yields", {})),
                          {k: _stacks(v, where) for k, v in t.get("tool_consumes", {}).items()},
                          float(t.get("fire_life_hours", 0)), site=t.get("site"),
                          finds_sites=bool(t.get("finds_sites", False)), offices=list(t.get("offices", [])),
                          any_office=bool(t.get("any_office", False)),
                          chance=None if t.get("chance") is None else float(t["chance"]),
                          makes_sites=dict(t.get("makes_sites", {})), speed_tools=dict(t.get("speed_tools", {})),
                          disposes_of_dead=bool(t.get("disposes_of_dead", False)),
                          illness_risk=None if t.get("illness_risk") is None else float(t["illness_risk"]),
                          done_text=str(t.get("done_text", "")))
        if t.get("finds_sites"):  # one task per site kind: the Scout chooses what to look for (work.json 'sites')
            base = tasks.pop(key)
            for kind, spec in _data.get("sites", {}).get("kinds", {}).items():
                tasks[f"{key}_{kind}"] = replace(base, key=f"{key}_{kind}", scouts_for=kind,
                                                 label=base.label.format(short=spec.get("short", kind),
                                                                         name=spec.get("name", kind)))
        for kind in t.get("makes_sites", {}).get("kinds", {}):
            require(kind in _data.get("sites", {}).get("kinds", {}), where, f"makes_sites: unknown site kind '{kind}'")
        require(t.get("site") is None or t["site"] in _data.get("sites", {}).get("kinds", {}), where,
                f"unknown site kind '{t.get('site')}' (see 'sites.kinds')")
    recipes: Dict[str, Task] = {}
    for key, r in _data.get("recipes", {}).items():
        where = f"work.json recipe '{key}'"
        _check_common(r, where)
        out = r.get("output", {})
        require(out.get("item") in ITEMS, where, f"unknown output item '{out.get('item')}'")
        name = ITEMS[out["item"]].name
        recipes[key] = Task(key, f"Make {name}" + (f" ×{out.get('count', 1)}" if out.get("count", 1) > 1 else ""),
                            list(r.get("occupations", [])), float(r.get("life_hours", 1)), r.get("skill"),
                            list(r.get("requires", [])), list(r.get("tools", [])), _stacks(r.get("inputs", []), where),
                            [{"item": out["item"], "amount": float(out.get("count", 1)), "chance": 1.0, "exact": True}],
                            recipe=True, offices=list(r.get("offices", [])),
                            speed_tools=dict(r.get("speed_tools", _data.get("craft_speed_tools", {}))),
                            illness_risk=None if r.get("illness_risk") is None else float(r["illness_risk"]))
    return tasks, recipes


TASKS, RECIPES = _load()
WORK_COUNTS_LIFE_HOURS: float = float(_data.get("work_counts_life_hours", 18))
FIRE: Dict[str, float] = _data.get("fire", {"start_life_hours": 8, "max_life_hours": 14})
TRIPS: Dict[str, float] = _data.get("trips", {})
SITES: Dict[str, Any] = _data.get("sites", {})
SITE_KINDS: Dict[str, Dict[str, str]] = SITES.get("kinds", {})
WORK_FADES_LIFE_HOURS: float = float(_data.get("work_fades_life_hours", WORK_COUNTS_LIFE_HOURS))
PRACTICE_DAYS_PER_TASK: float = float(_data.get("practice_days_per_task", 6))
YIELD_ROLL: Dict[str, float] = _data.get("yield_roll", {})
ANYONE_ATTRIBUTES: Dict[str, float] = dict(_data.get("anyone_attributes", {"constitution": 1.0, "wisdom": 1.0}))
STOCK_TARGETS: Dict[str, float] = dict(_data.get("stock_targets", {}))
AUTO_TAKE_TOOLS: bool = bool(_data.get("auto_take_tools", True))
for _k in STOCK_TARGETS:
    require(_k in ("food", "water") or _k in ITEMS, "work.json stock_targets", f"unknown item '{_k}'")


# Offices with work of their own; the holders of any other office do the 'any_office' tasks.
OFFICES_WITH_TASKS = {o for t in [*TASKS.values(), *RECIPES.values()] for o in t.offices}


def check_against_governments(government_types: Dict[str, Any]):
    """Every office a task names must be an office in some government."""
    offices = {name for g in government_types.values() for name in g.offices}
    for kind, table in (("task", TASKS), ("recipe", RECIPES)):
        for key, t in table.items():
            for o in t.offices:
                require(o in offices, f"work.json {kind} '{key}'", f"'offices' names '{o}', which is not an office "
                                                                    "in any government")


def work(kind: str, key: str) -> Optional[Task]:
    return (RECIPES if kind == "craft" else TASKS).get(key)


def job_for(t: Task, occupations: List[str], offices: List[str]) -> Optional[str]:
    """Which of someone's jobs this work belongs to: an occupation's name, or 'office:<name>' for an office.
    None if it is not their job's work (work open to anyone belongs to no job)."""
    occ = next((o for o in t.occupations if o in occupations), None)
    if occ:
        return occ
    office = next((o for o in t.offices if o in offices), None)
    if office:
        return f"office:{office}"
    if t.any_office:
        office = next((o for o in offices if o not in OFFICES_WITH_TASKS), None)
        if office:
            return f"office:{office}"
    return None


def tasks_of_job(job: str) -> List[Task]:
    """The tasks and recipes that are this job's work ('Hunter', or 'office:Elder')."""
    out = []
    for t in [*TASKS.values(), *RECIPES.values()]:
        if job.startswith("office:"):
            office = job[7:]
            if office in t.offices or (t.any_office and office not in OFFICES_WITH_TASKS):
                out.append(t)
        elif job in t.occupations:
            out.append(t)
    return out


def tools_for_job(job: str) -> List[str]:
    """Every tool that helps with this job's work: those its tasks need ('tools') or are better with
    ('boost'), and those the occupation needs before anyone may take it up ('needs_tools')."""
    tools: List[str] = []
    for t in tasks_of_job(job):
        tools += [x for x in [*t.tools, *t.boost] if x not in tools]
    occ = OCCUPATIONS.get(job)
    if occ:
        tools += [x for x in occ.needs_tools if x not in tools]
    return tools


def recipes_making(item: str) -> List[Task]:
    return [r for r in RECIPES.values() if r.yields and r.yields[0]["item"] == item]


def roll_yields(task: Task, quality: float, multiplier: float = 1.0,
                rng: Optional[random.Random] = None) -> List[Dict[str, Any]]:
    """What one piece of work brings back. Recipes make exactly their output; tasks yield around
    'amount' for an average worker (quality 50), more for better workers, with some luck."""
    r = rng or random
    out = []
    for y in task.yields:
        if y.get("exact"):
            out.append({"item": y["item"], "count": int(y["amount"])})
            continue
        if y["chance"] < 1 and r.random() >= y["chance"]:
            continue
        skill = YIELD_ROLL.get("at_quality_0", 0.5) + (YIELD_ROLL.get("at_quality_100", 1.5)
                                                          - YIELD_ROLL.get("at_quality_0", 0.5)) * quality / 100
        luck = YIELD_ROLL.get("luck", 0.3)
        expected = y["amount"] * skill * multiplier * r.uniform(1 - luck, 1 + luck)
        n = int(expected) + (1 if r.random() < expected - int(expected) else 0)
        if n > 0:
            out.append({"item": y["item"], "count": n})
    return out


def _scaled(base: float, effect: float, quality: float) -> float:
    return base + effect * (quality - 50) / 50


def trip_chance(task: Task, quality: float, site_known: bool) -> float:
    """The chance a trip out brings anything back (1 for work that isn't a trip)."""
    if not task.site:
        return 1.0
    if site_known:  # a Scout (or a gardener) found the place: the trip is only a matter of going there
        return TRIPS.get("with_site_chance", 1.0)
    base = task.chance if task.chance is not None else TRIPS.get("base_chance", 0.4)
    return max(TRIPS.get("min_chance", 0.05), min(TRIPS.get("max_chance", 0.97),
                                                    _scaled(base, TRIPS.get("quality_effect", 0.1), quality)))


def site_find_chance(quality: float) -> float:
    return max(0.0, min(1.0, _scaled(SITES.get("find_chance", 0.55), SITES.get("find_quality_effect", 0.2), quality)))


def site_tasks(kind: str) -> List[Task]:
    return [t for t in TASKS.values() if t.site == kind]


def site_loads(spec: Any = None) -> float:
    """How many ordinary trip hauls a newly found place holds: a number, or a [min, max] range rolled."""
    spec = SITES.get("loads", [3, 5]) if spec is None else spec
    if isinstance(spec, (list, tuple)):
        return round(random.uniform(float(spec[0]), float(spec[-1])), 1)
    return float(spec)


def opened_by(innovation: str) -> List[str]:
    """Recipes and tasks an innovation opens, by name (for 'opens ...' notes)."""
    names = [ITEMS[r.yields[0]["item"]].name for r in RECIPES.values() if innovation in r.requires]
    names += [t.label for t in TASKS.values() if innovation in t.requires]
    return names

"""Characters: attributes, skills, bodily needs, health and aging, all defined by data/rules/character.json.

This module knows nothing about governments, the engine or any display. It holds the rules for one
person's body and abilities, so the same rules can later run on a server or be mirrored by an Unreal
Engine character component. Add an attribute, skill, need or care action to the data file and every
part of the game picks it up.

Needs are levels from 0 (desperate) to 100 (fully satisfied). They fall over the day-night cycle
(see world/environment.py), not over calendar days, and care actions (eat, drink, sleep...) restore
them. A need below its 'critical' level wears down health; health at zero means a collapse.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from utils import game_data
from utils.game_data import RULES_DIR
from utils.data_files import DATA_DIR, load_json, require


@dataclass
class AttributeDef:
    key: str
    name: str
    abbr: str
    default: int
    description: str


@dataclass
class SkillDef:
    key: str
    name: str
    attribute: str
    description: str


@dataclass
class NeedDef:
    key: str
    name: str
    icon: str
    decay_per_day: float
    critical: float
    levels: List[Tuple[float, str]]
    night_factor: float = 1.0
    cold_factor_per_degree: float = 0.0
    warm_gain_per_degree: float = 0.0
    season_factors: Dict[str, float] = field(default_factory=dict)  # season -> how fast it falls (warmth)
    no_fire_factors: Dict[str, float] = field(default_factory=dict)  # season -> faster still with no fire in camp
    death_cause: str = ""             # what someone dies of when this need empties their health ('starvation')
    health_loss_per_day: Optional[float] = None  # health lost per day-night cycle while critical (default: health's)

    def label(self, value: float) -> str:
        for threshold, name in self.levels:
            if value >= threshold:
                return name
        return self.levels[-1][1]


@dataclass
class Activity:
    """What someone's body is doing for a while: how fast each need is restored (per day-night cycle)
    and how the normal fall of other needs is scaled. Care actions and resting are activities."""
    key: str
    restores_per_day: Dict[str, float] = field(default_factory=dict)
    factors: Dict[str, float] = field(default_factory=dict)
    at_camp: bool = False  # by the fire, if there is one


@dataclass
class CareAction:
    key: str
    label: str
    announce: str
    restores: Dict[str, float]
    life_hours: float               # of the day-night cycle; 0 = instant
    factors: Dict[str, float] = field(default_factory=dict)
    at_camp: bool = False
    interruptible: bool = False
    requires: List[str] = field(default_factory=list)
    needs_amenity: Optional[str] = None
    scaled_by_quality: Optional[str] = None  # a society quality (core/society.py) that scales what it restores
    consumes: bool = False  # eats or drinks items that restore its needs (world/items.py)
    max_share: float = 1.5  # consumes: the most of a normal portion one sitting can be (a feast)
    quality_floor: float = 0.4  # scaled_by_quality: what is left of the effect when the quality is 0

    @property
    def instant(self) -> bool:
        return self.life_hours <= 0

    def activity(self) -> Activity:
        per_day = {} if self.instant else {k: v * 24 / self.life_hours for k, v in self.restores.items()}
        return Activity(self.key, per_day, dict(self.factors), self.at_camp)


class CharacterRules:
    """The parsed contents of data/rules/character.json."""

    def __init__(self, data: Dict[str, Any]):
        where = "character.json"
        self.attr_min, self.attr_max = data.get("attribute_range", [1, 10])
        self.talent: Dict[str, float] = data.get("talent", {"per_point": 0.1, "average": 5})
        self.new_characters: Dict[str, Any] = data.get("new_characters", {"random": False})
        self.skill_min, self.skill_max = data.get("skill_range", [0, 10])
        self.attributes: Dict[str, AttributeDef] = {
            k: AttributeDef(k, a["name"], a.get("abbr", k[:3].upper()), a.get("default", 5), a.get("description", ""))
            for k, a in data.get("attributes", {}).items()}
        require(self.attributes, where, "needs at least one attribute")
        self.skills: Dict[str, SkillDef] = {}
        for k, s in data.get("skills", {}).items():
            require(s.get("attribute") in self.attributes, f"{where} skill '{k}'", "'attribute' must name an attribute")
            self.skills[k] = SkillDef(k, s["name"], s["attribute"], s.get("description", ""))
        require(data.get("office_skill") in (None, *self.skills), where, "'office_skill' must name a skill")
        self.office_skill: Optional[str] = data.get("office_skill")
        self.training_per_year: float = data.get("training_per_year", 0.5)
        self.mastery_slowdown: float = data.get("mastery_slowdown", 0.0)
        self.needs: Dict[str, NeedDef] = {}
        for k, n in data.get("needs", {}).items():
            levels = sorted(((float(t), name) for t, name in n["levels"]), reverse=True)
            self.needs[k] = NeedDef(k, n["name"], n.get("icon", ""), n["decay_per_day"], n.get("critical", 10), levels,
                                    n.get("night_factor", 1.0), n.get("cold_factor_per_degree", 0.0),
                                    n.get("warm_gain_per_degree", 0.0), dict(n.get("season_factors", {})),
                                    dict(n.get("no_fire_factors", {})), n.get("death_cause", n["name"].lower()),
                                    n.get("health_loss_per_day"))
        self.genders: Dict[str, Dict[str, Any]] = {k: g for k, g in data.get("genders", {}).items() if not k.startswith("_")}
        self.constitution_resists: float = data.get("constitution_resists", 0.0)
        self.health: Dict[str, float] = data.get("health", {})
        self.health_max: float = self.health.get("max", 100)
        require(self.health.get("at_zero", "collapse") in ("death", "collapse"), f"{where} health",
                "'at_zero' must be 'death' or 'collapse'")
        self.zero_health_kills: bool = self.health.get("at_zero", "collapse") == "death"
        self.body_temperature: Dict[str, Any] = data.get("body_temperature", {})
        self.care_actions: Dict[str, CareAction] = {}
        for k, c in data.get("care_actions", {}).items():
            if k.startswith("_"):
                continue
            for need in list(c["restores"]) + list(c.get("factors", {})):
                require(need in self.needs, f"{where} care action '{k}'", f"unknown need '{need}'")
            self.care_actions[k] = CareAction(
                k, c["label"], c.get("announce", c["label"].lower()), c["restores"], float(c.get("life_hours", 1)),
                c.get("factors", {}), bool(c.get("at_camp", False)), bool(c.get("interruptible", False)),
                c.get("requires", []), c.get("needs_amenity"), c.get("scaled_by_quality"), bool(c.get("consumes", False)),
                float(c.get("max_share", 1.5)), float(c.get("quality_floor", 0.4)))
        r = data.get("resting", {})
        self.resting = Activity("rest", {}, r.get("factors", {}), bool(r.get("at_camp", False)))
        self.life_stages: List[Tuple[int, str]] = sorted((int(a), n) for a, n in data.get("life_stages", [[0, "Adult"]]))
        self.aging: List[Dict[str, Any]] = data.get("aging", [])
        for rule in self.aging:
            for a in rule["attributes"]:
                require(a in self.attributes, f"{where} aging", f"unknown attribute '{a}'")

    def life_stage(self, age: int) -> str:
        stage = self.life_stages[0][1]
        for start, name in self.life_stages:
            if age >= start:
                stage = name
        return stage


# data/rules/character.json as it is in every age. An age (data/ages/<age>/rules/character.json) or a government
# may change any of it: how fast needs fall, health, care actions, training... RULES is then set up again in
# place from the version in force. Skills and attributes are different: the ones a later age adds are known
# from the start (everyone simply has 0 in a skill nobody can use yet), so that occupations and offices of any
# age can name them and nobody's sheet changes shape in the middle of a game.
BASE_RULES: Dict[str, Any] = load_json(RULES_DIR / "character.json")
for _over in game_data.age_rules("character").values():
    for _table in ("skills", "attributes"):
        for _key, _spec in game_data.public(_over.get(_table, {})).items():
            BASE_RULES.setdefault(_table, {}).setdefault(_key, _spec)
RULES = CharacterRules(BASE_RULES)
game_data.switchable("character", BASE_RULES, RULES.__init__)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class Character:
    """One person's body and abilities. world.player.Player builds on this."""

    def __init__(self, age: int, attributes: Optional[Dict[str, int]] = None, skills: Optional[Dict[str, float]] = None):
        self.age = age
        attributes = attributes or {}
        skills = skills or {}
        for key in attributes:
            require(key in RULES.attributes, "players.json", f"unknown attribute '{key}' (see character.json)")
        for key in skills:
            require(key in RULES.skills, "players.json", f"unknown skill '{key}' (see character.json)")
        self.attributes: Dict[str, int] = {k: int(attributes.get(k, a.default)) for k, a in RULES.attributes.items()}
        self.skills: Dict[str, float] = {k: float(skills.get(k, 0)) for k in RULES.skills}
        self.needs: Dict[str, float] = {k: 100.0 for k in RULES.needs}
        self.health: float = RULES.health_max

    # ------------------------------------------------------------------ #
    # Reading
    # ------------------------------------------------------------------ #
    def attribute(self, key: str) -> int:
        return self.attributes.get(key, 0)

    @property
    def life_stage(self) -> str:
        return RULES.life_stage(self.age)

    def need_label(self, key: str) -> str:
        return RULES.needs[key].label(self.needs[key])

    def critical_needs(self) -> List[str]:
        return [k for k, n in RULES.needs.items() if self.needs[k] < n.critical]

    def death_cause(self) -> str:
        """What their emptiest critical need would kill them of ('starvation', 'cold')."""
        worst = min(self.needs, key=lambda k: self.needs[k] - RULES.needs[k].critical)
        return RULES.needs[worst].death_cause

    def body_temperature(self) -> Optional[float]:
        spec = RULES.body_temperature
        need = spec.get("need")
        if need not in self.needs:
            return None
        low, high = spec.get("at_zero", 33.0), spec.get("at_full", 37.0)
        return round(low + (high - low) * self.needs[need] / 100, 1)

    def urgency(self, key: str) -> float:
        """0 when the need is comfortably met, rising to 1 as it empties."""
        return _clamp((70 - self.needs[key]) / 70, 0, 1)

    def sheet(self) -> Dict[str, Any]:
        """Plain data for observations and saving-free display."""
        return {
            "attributes": dict(self.attributes),
            "skills": {k: round(v, 1) for k, v in self.skills.items()},
            "needs": {k: {"value": round(v), "label": self.need_label(k), "critical": v < RULES.needs[k].critical}
                      for k, v in self.needs.items()},
            "health": round(self.health),
            "body_temperature": self.body_temperature(),
            "life_stage": self.life_stage,
        }

    # ------------------------------------------------------------------ #
    # Changing
    # ------------------------------------------------------------------ #
    def live(self, life_days: float, night: bool, temperature: float, comfort: float,
             activity: Optional[Activity] = None, season: Optional[str] = None,
             need_factors: Optional[Dict[str, float]] = None, health_drain: float = 0.0,
             regen_factor: float = 1.0, fatal: bool = False, no_fire: bool = False) -> Optional[str]:
        """Let `life_days` of the day-night cycle pass while doing `activity` (None = up and about) in air
        of `temperature`. Returns a collapse message, or None.
        `need_factors`: how fast each need falls for this person (children eat less: life.json).
        `health_drain`: health lost per day-night cycle to an illness; while ill nothing heals.
        `regen_factor`: how fast health comes back now (character.json 'health.regen_factors').
        `fatal`: health reaching 0 is death, not a collapse (the caller deals with it; health stays 0).
        `no_fire`: the camp has no fire: needs with 'no_fire_factors' (warmth) fall faster still."""
        toughness = 1 - RULES.constitution_resists * (self.attribute("constitution") - 5)
        for key, need in RULES.needs.items():
            rate = need.decay_per_day * toughness * (need_factors or {}).get(key, 1.0)
            if night:
                rate *= need.night_factor
            if need.cold_factor_per_degree:
                cold = comfort - temperature
                rate = rate * (1 + need.cold_factor_per_degree * cold) if cold > 0 \
                    else -need.warm_gain_per_degree * -cold  # warm air warms you up
            if rate > 0 and season in need.season_factors:
                rate *= need.season_factors[season]  # winter chills fast; summer hardly at all
            if rate > 0 and no_fire and season in need.no_fire_factors:
                rate *= need.no_fire_factors[season]  # and with no fire in camp, faster still
            if activity is not None:
                if rate > 0:
                    rate *= activity.factors.get(key, 1.0)
                rate -= activity.restores_per_day.get(key, 0.0)
            self.needs[key] = _clamp(self.needs[key] - rate * life_days, 0, 100)
        h = RULES.health
        critical = self.critical_needs()
        if critical:
            self.health -= sum(RULES.needs[k].health_loss_per_day if RULES.needs[k].health_loss_per_day is not None
                               else h.get("loss_per_day_per_critical_need", 50) for k in critical) * life_days
        elif not health_drain and all(v >= h.get("regen_when_all_above", 40) for v in self.needs.values()):
            self.health += h.get("regen_per_day", 30) * regen_factor * life_days
        self.health -= health_drain * life_days
        self.health = _clamp(self.health, 0, RULES.health_max)
        if self.health <= 0 and fatal:
            return None
        if self.health <= 0:
            worst = min(self.needs, key=self.needs.get)
            label = self.need_label(worst).lower()
            restore = h.get("collapse_restores", 40)
            for key in h.get("collapse_restores_needs", list(self.needs)):
                if key in self.needs:
                    self.needs[key] = max(self.needs[key], restore)
            self.health = restore
            return f"collapses ({RULES.needs[worst].name.lower()}: {label})"
        return None

    def care_now(self, action_key: str, share: float = 1.0) -> Dict[str, float]:
        """Apply an instant care action (drinking) at once; returns how much each need rose. `share` scales
        it (only part of a drink was there). Care actions that take time work gradually instead, as an
        Activity passed to live()."""
        action = RULES.care_actions[action_key]
        gained = {}
        for need, amount in ((n, a * share) for n, a in action.restores.items()):
            before = self.needs[need]
            self.needs[need] = _clamp(before + amount, 0, 100)
            gained[need] = self.needs[need] - before
        return gained

    def train(self, skill: str, amount: float) -> float:
        """Practise a skill; returns how much it changed."""
        if skill not in self.skills:
            return 0.0
        before = self.skills[skill]
        # Talent helps: each attribute point above average adds to learning (character.json 'talent').
        t = RULES.talent
        talent = 1 + t.get("per_point", 0.1) * (self.attribute(RULES.skills[skill].attribute) - t.get("average", 5))
        if amount > 0:
            # Diminishing returns: the better you are, the slower you improve.
            amount *= 1 - RULES.mastery_slowdown * self.skills[skill] / RULES.skill_max
        self.skills[skill] = _clamp(self.skills[skill] + amount * talent, RULES.skill_min, RULES.skill_max)
        return self.skills[skill] - before

    def birthday(self, aging: Optional[List[Dict[str, Any]]] = None) -> List[str]:
        """Age one year. Returns descriptions of attribute changes ('STR -1'). `aging` replaces
        character.json 'aging' (life.json gives each age its own)."""
        self.age += 1
        changes = []
        for rule in (RULES.aging if aging is None else aging):
            start, every = rule["from_age"], rule["every_years"]
            if self.age >= start and (self.age - start) % every == 0 and self.age > start:
                for key in rule["attributes"]:
                    before = self.attributes[key]
                    self.attributes[key] = int(_clamp(before + rule["change"], RULES.attr_min, RULES.attr_max))
                    if self.attributes[key] != before:
                        changes.append(f"{RULES.attributes[key].abbr} {rule['change']:+d}")
        return changes

    # ------------------------------------------------------------------ #
    # Saving
    # ------------------------------------------------------------------ #
    def character_state(self) -> Dict[str, Any]:
        return {"age": self.age, "attributes": dict(self.attributes), "skills": dict(self.skills),
                "needs": dict(self.needs), "health": self.health}

    def load_character_state(self, data: Dict[str, Any]):
        self.age = data.get("age", self.age)
        self.attributes.update({k: v for k, v in data.get("attributes", {}).items() if k in self.attributes})
        self.skills.update({k: v for k, v in data.get("skills", {}).items() if k in self.skills})
        self.needs.update({k: v for k, v in data.get("needs", {}).items() if k in self.needs})
        self.health = data.get("health", self.health)

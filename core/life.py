"""Life and death (data/rules/life.json): how old people get, illness and healing, death and the dead,
pregnancy and birth, and childhood.

The rules come in layers: life.json 'base', then the overrides of every age reached, of the current
government and of every innovation discovered. So a later age, another government or a new discovery
changes lifespans, illnesses, births and childhood purely by data.

The engine (core/engine.py) calls the Life manager once a calendar day (illness, pregnancy, births,
birthdays), whenever a piece of work is done (illness from working, laying the dead to rest), and for
the two actions it adds: seeing a healer ('treat') and a child's play or study ('activity'). It knows
nothing of displays; everything it shows goes out through observe_person() and observe() as plain data.
"""
import copy
import math
import random
from typing import Any, Dict, List, Optional, Tuple

from core.calendar import DAYS_PER_YEAR, HOURS_PER_DAY, HOURS_PER_YEAR, day_of_year, format_date
from core.occupations import OCCUPATIONS
from innovations.innovation import ALL_INNOVATIONS, AGES, AGES_BY_KEY
from utils import game_data
from utils.data_files import require
from utils.messages import Messages
from world.character import RULES as CHARACTER
from world.items import ITEMS

_data = game_data.rules("life")


def _public(d: Dict[str, Any]) -> Dict[str, Any]:
    """A data table without its '_comment' entries."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    """Lay `over` onto `base` (in place): objects merge key by key, anything else is replaced."""
    for k, v in over.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def curve(points: List[List[float]], x: float) -> float:
    """A value from [x, value] points joined by straight lines, flat past the ends."""
    if not points:
        return 0.0
    pts = sorted((float(a), float(b)) for a, b in points)
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y1
    return pts[-1][1]


def _check_curve(points, where: str):
    require(isinstance(points, list) and points and all(isinstance(p, list) and len(p) == 2 for p in points),
            where, "must be a curve: a list of [x, value] points")


def _check(r: Dict[str, Any], where: str):
    """Stop with a clear message if the rules (after an override) name something that doesn't exist."""
    for key in ("work_age", "politics_age"):
        require(isinstance(r.get(key), (int, float)) and r[key] >= 0, where, f"'{key}' must be an age (0 or more)")
    for need, points in _public(r.get("need_factors", {})).items():
        require(need in CHARACTER.needs, f"{where} need_factors", f"unknown need '{need}'")
        _check_curve(points, f"{where} need_factors.{need}")
    for rule in r.get("aging", []):
        for a in rule.get("attributes", []):
            require(a in CHARACTER.attributes, f"{where} aging", f"unknown attribute '{a}'")
    for key, ill in _public(r.get("illnesses", {})).items():
        w = f"{where} illness '{key}'"
        for c in ("rate_per_year", "work_chance", "cure_chance"):
            _check_curve(ill.get(c), f"{w} {c}")
        for req in ill.get("requires", []):
            require(req in ALL_INNOVATIONS, w, f"unknown innovation '{req}'")
    t = r.get("treatment", {})
    for occ in t.get("healers", []):
        require(occ in OCCUPATIONS, f"{where} treatment", f"unknown occupation '{occ}'")
    for m in t.get("medicine", []):
        require(m.get("item") in ITEMS, f"{where} treatment", f"unknown medicine item '{m.get('item')}'")
    _check_curve(t.get("healer_factor", [[0, 1]]), f"{where} treatment.healer_factor")
    _check_curve(r.get("pregnancy", {}).get("fertility", [[0, 0]]), f"{where} pregnancy.fertility")
    b = r.get("birth", {})
    for g in b.get("genders", {}):
        require(g in CHARACTER.genders, f"{where} birth", f"unknown gender '{g}' (character.json 'genders')")
        require(b.get("names", {}).get(g), f"{where} birth", f"'names' needs a list of names for '{g}'")
    for key, a in _public(r.get("childhood", {}).get("activities", {})).items():
        w = f"{where} childhood activity '{key}'"
        for attr in a.get("attributes", {}):
            require(attr in CHARACTER.attributes, w, f"unknown attribute '{attr}'")
        for skill in a.get("skills", {}):
            require(skill in CHARACTER.skills, w, f"unknown skill '{skill}'")
        for req in a.get("requires", []):
            require(req in ALL_INNOVATIONS, w, f"unknown innovation '{req}'")
    for rule in r.get("successor", {}).get("order", []):
        require(rule in ("children", "youngest_adult", "anyone"), f"{where} successor",
                f"unknown rule '{rule}' (children, youngest_adult, anyone)")


BASE: Dict[str, Any] = _data.get("base", {})
# An age's changes: data/ages/<age>/rules/life.json (and, as before, life.json 'ages'). A government's: its
# file's "rules": {"life": {...}} (read when the governments load), and life.json 'governments'.
AGE_OVERRIDES: Dict[str, Dict[str, Any]] = _public(_data.get("ages", {}))
for _k, _o in game_data.age_rules("life").items():
    AGE_OVERRIDES[_k] = merge(copy.deepcopy(AGE_OVERRIDES.get(_k, {})), _o)
GOVERNMENT_OVERRIDES: Dict[str, Dict[str, Any]] = _public(_data.get("governments", {}))
INNOVATION_OVERRIDES: Dict[str, Dict[str, Any]] = _public(_data.get("innovations", {}))
_check(BASE, "life.json base")
for _k, _o in AGE_OVERRIDES.items():
    require(_k in AGES_BY_KEY, "life.json ages", f"unknown age '{_k}' (age.json)")
    _check(merge(copy.deepcopy(BASE), _o), f"life.json ages.{_k}")
for _k, _o in INNOVATION_OVERRIDES.items():
    require(_k in ALL_INNOVATIONS, "life.json innovations", f"unknown innovation '{_k}'")
    _check(merge(copy.deepcopy(BASE), _o), f"life.json innovations.{_k}")
for _k, _o in GOVERNMENT_OVERRIDES.items():
    _check(merge(copy.deepcopy(BASE), _o), f"life.json governments.{_k}")


def rules_for(age_keys: List[str], government_key: Optional[str], discovered) -> Dict[str, Any]:
    """The life rules in force: base, then each age reached, the government, and each discovery."""
    r = copy.deepcopy(BASE)
    for key in age_keys:
        merge(r, AGE_OVERRIDES.get(key, {}))
    if government_key:
        merge(r, GOVERNMENT_OVERRIDES.get(government_key, {}))
        merge(r, game_data.GOVERNMENT_RULES.get(government_key, {}).get("life", {}))
    for name, over in INNOVATION_OVERRIDES.items():
        if name in discovered:
            merge(r, over)
    return r


ROMAN = ["II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


class Life:
    """Illness, healing, death and the dead, pregnancy and birth, and childhood for one game."""

    def __init__(self, engine):
        self.engine = engine
        self.bodies: List[Dict[str, Any]] = []   # the dead lying in camp: {name, age, gender, died, cause, handler}
        self.used_names = {p.name for p in engine.players}  # names are never given twice in one game
        self.births = 0
        self.deaths = 0
        self._cache: Dict[Any, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    # The rules in force
    # ------------------------------------------------------------------ #
    @property
    def gov(self):
        return self.engine.government

    @property
    def players(self):
        return self.engine.players

    @property
    def clock(self) -> int:
        return self.engine.clock

    @property
    def rules(self) -> Dict[str, Any]:
        gov = self.gov
        ages = tuple(a.key for a in AGES[:gov.age_index + 1])
        found = frozenset(k for k in INNOVATION_OVERRIDES if k in gov.innovation_pool.discovered)
        key = (ages, gov.government_type.key, found)
        if key not in self._cache:
            self._cache[key] = rules_for(list(ages), gov.government_type.key, found)
        return self._cache[key]

    # ------------------------------------------------------------------ #
    # Ages of life
    # ------------------------------------------------------------------ #
    def of_age(self, person, what: str) -> bool:
        """Old enough for 'work' or for 'politics' (life.json 'work_age', 'politics_age')?"""
        return person.age >= self.rules.get(f"{what}_age", 0)

    def is_child(self, person) -> bool:
        return not self.of_age(person, "work")

    def life_stage(self, person) -> str:
        stage = "Adult"
        for start, name in sorted((int(a), n) for a, n in self.rules.get("life_stages", [])):
            if person.age >= start:
                stage = name
        return stage

    def need_factors(self, person) -> Dict[str, float]:
        return {need: curve(points, person.age) for need, points in _public(self.rules.get("need_factors", {})).items()}

    def cannot_work(self, person) -> Optional[str]:
        """Why this person can't do any work now (too young, about to give birth), or None."""
        if self.is_child(person):
            return f"too young to work (from age {self.rules['work_age']:g})"
        nw = self.rules.get("no_work", {})
        if person.illness and nw.get("while_ill", False):
            return "too ill to work (see the healer, and rest)"
        if person.health < nw.get("health_below", 0):
            return f"too weak to work (health {person.health:.0f}; rest until it is {nw['health_below']:g})"
        pr = person.pregnancy
        if pr and self.clock >= pr["due"] - self.rules["pregnancy"].get("no_work_last_days", 90) * HOURS_PER_DAY:
            return "too close to giving birth to work"
        return None

    # ------------------------------------------------------------------ #
    # Every calendar day
    # ------------------------------------------------------------------ #
    def daily(self):
        self._births()
        self._birthdays()
        self._illness_rolls()
        self._pregnancy_roll()
        self._healers_restock()

    def _birthdays(self):
        today = day_of_year(self.clock)
        work_age, politics_age = self.rules["work_age"], self.rules["politics_age"]
        for p in self.players:
            if p.birth_day != today or (p.born is not None and self.clock - p.born < HOURS_PER_DAY * 300):
                continue
            changes = p.birthday(self.rules.get("aging"))
            if p.age == work_age:
                p.growth = {}  # childhood is over: what play and study made of them is set
                stats = ", ".join(f"{a.abbr} {p.attributes[k]}" for k, a in CHARACTER.attributes.items())
                Messages.add(f"{p.name} turns {p.age} and is old enough to work ({stats})", reason="came of working age")
            elif p.age == politics_age:
                Messages.add(f"{p.name} turns {p.age} and comes of age: may now vote, stand for office and lead",
                             reason="came of age")
            elif changes:
                Messages.add(f"{p.name} turns {p.age}: {', '.join(changes)}", important=False)

    # ------------------------------------------------------------------ #
    # Illness
    # ------------------------------------------------------------------ #
    def illnesses(self) -> Dict[str, Dict[str, Any]]:
        """Illnesses that can be caught now (their 'requires' known)."""
        return {k: ill for k, ill in _public(self.rules.get("illnesses", {})).items()
                if self.gov.is_unlocked(ill.get("requires", []))}

    def illness_of(self, person) -> Optional[Dict[str, Any]]:
        if not person.illness:
            return None
        return _public(self.rules.get("illnesses", {})).get(person.illness["key"])

    def body_factor(self) -> float:
        """How many times more easily everyone falls ill while the dead lie in camp."""
        rem = self.rules.get("remains", {})
        f = 1.0
        for b in self.bodies:
            years = max(0.0, (self.clock - b["died"]) / HOURS_PER_YEAR)
            f += rem.get("illness_factor_per_body", 1.0) + rem.get("illness_factor_per_year", 0.0) * years
        return f

    def health_drain(self, person) -> Tuple[float, bool]:
        """(health lost per day-night cycle to illness, whether health at 0 is death)."""
        ill = self.illness_of(person)
        if not ill:
            return 0.0, False
        return float(ill.get("health_loss_per_day", 100)), bool(ill.get("fatal", True))

    def _pick_illness(self, person, chance_of) -> Optional[str]:
        """Roll for falling ill: `chance_of(spec)` is each illness's chance now. Returns the key caught."""
        options = self.illnesses()
        if person.illness or not options:
            return None
        total = sum(chance_of(spec) for spec in options.values())
        if total <= 0 or random.random() >= min(1.0, total):
            return None
        keys = list(options)
        return random.choices(keys, [options[k].get("weight", 1) * max(1e-9, chance_of(options[k])) for k in keys])[0]

    def _illness_rolls(self):
        factor = self.body_factor()
        for p in list(self.players):
            def chance(spec):
                rate = curve(spec["rate_per_year"], p.age) * factor
                return 1 - math.exp(-rate / DAYS_PER_YEAR)
            key = self._pick_illness(p, chance)
            if key:
                why = "the dead lie unburied in camp" if self.bodies else None
                self.fall_ill(p, key, reason=why)

    def after_work(self, person, task, own_job: bool):
        """A piece of work is done: working wears people down (the illness's 'work_chance', by age, times the
        task's 'illness_risk'; work that is nobody's job is risky only with an 'illness_risk')."""
        risk = task.illness_risk if task.illness_risk is not None else (1.0 if own_job else 0.0)
        if not risk or person not in self.players:
            return
        factor = self.body_factor()
        key = self._pick_illness(person, lambda spec: curve(spec["work_chance"], person.age) * risk * factor)
        if key:
            self.fall_ill(person, key, how=f" while working ({task.label.lower()})")

    def fall_ill(self, person, key: str, how: str = "", reason: Optional[str] = None):
        spec = _public(self.rules.get("illnesses", {}))[key]
        person.illness = {"key": key, "since": self.clock}
        Messages.add(f"{spec.get('icon', '🤒')} {person.name} has fallen ill ({spec['name'].lower()}){how}: their health "
                     f"is draining, and only a healer can cure it", reason=reason, category="illness")

    # ------------------------------------------------------------------ #
    # Healing
    # ------------------------------------------------------------------ #
    def treatment_for(self, patient, healer=None) -> Optional[Dict[str, Any]]:
        """The best healer who could see this patient now, with the medicine they would use, or None:
        {'healer', 'occupation', 'medicine', 'quality', 'factor', 'cure_chance'}."""
        t = self.rules.get("treatment", {})
        if not patient.illness and patient.health >= t.get("below_health", 60):
            return None
        from core.society import job_quality
        best = None
        for occ in t.get("healers", []):
            for h in self.gov.occupations.get(occ, []):
                if h is patient and not t.get("self", True):
                    continue
                if healer is not None and h is not healer:
                    continue
                meds = sorted(t.get("medicine", []), key=lambda m: -m.get("power", 1.0))
                med = next((m for m in meds if h.inventory.count(m["item"]) >= m.get("count", 1)), None)
                if med is None:
                    continue
                q = job_quality(self.gov, occ, h)
                f = curve(t.get("healer_factor", [[0, 1]]), q)
                score = f * med.get("power", 1.0)
                if best is None or score > best["score"]:
                    best = {"healer": h, "occupation": occ, "medicine": med, "quality": q, "factor": f, "score": score}
        if best is not None:
            ill = self.illness_of(patient)
            best["cure_chance"] = min(1.0, curve(ill["cure_chance"], patient.age) * best["score"]) if ill else None
        return best

    def healers_with_nothing(self) -> List[str]:
        """Healers who have no medicine in their pack (so can't treat anyone)."""
        t = self.rules.get("treatment", {})
        out = []
        for occ in t.get("healers", []):
            for h in self.gov.occupations.get(occ, []):
                if not any(h.inventory.count(m["item"]) >= m.get("count", 1) for m in t.get("medicine", [])):
                    out.append(h.name)
        return out

    def patients_for(self, healer) -> List[Any]:
        """Whom this healer could go and treat now (with the medicine in their pack): the ill first, then the
        weakest."""
        out = [p for p in self.players if self.treatment_for(p, healer) is not None]
        return sorted(out, key=lambda p: (not p.illness, p.health))

    def treat(self, patient, reason: Optional[str] = None, healer=None) -> bool:
        """A visit to the healer (or the healer coming to them): uses up their best medicine, may cure the
        illness, and gives back some health."""
        opt = self.treatment_for(patient, healer)
        if opt is None:
            Messages.add(f"{patient.name} can't see a healer now: nobody holding the work of a healer has any medicine "
                         f"in their pack.", important=False)
            return False
        t = self.rules["treatment"]
        healer, med = opt["healer"], opt["medicine"]
        healer.inventory.take(med["item"], med.get("count", 1))
        ill = self.illness_of(patient)
        cured = ill is not None and random.random() < opt["cure_chance"]
        before = patient.health
        patient.health = min(CHARACTER.health_max, patient.health + t.get("health_gain", 20) * opt["score"])
        if cured:
            patient.illness = None
        # Treating someone is the healer's work: their job counts as worked, and they learn from it.
        from core import work as WORK
        self.engine.production.last_worked[healer.name] = self.clock
        skill = OCCUPATIONS[opt["occupation"]].skill
        if skill:
            healer.train(skill, CHARACTER.training_per_year / DAYS_PER_YEAR * WORK.PRACTICE_DAYS_PER_TASK)
        who = "treats themselves" if healer is patient else f"treats {patient.name}"
        what = ITEMS[med["item"]].name.lower()
        if ill is None:
            outcome = "to speed their recovery"
        elif cured:
            outcome = f"and the {ill['name'].lower()} breaks: {patient.name} is cured (now to rest and recover)"
        else:
            outcome = f"but the {ill['name'].lower()} holds on ({opt['cure_chance']:.0%} chance this time)"
        Messages.add(f"🌿 {healer.name} {who} with {what} {outcome} (health {before:.0f} → {patient.health:.0f})",
                     important=cured or ill is not None, reason=reason, category="illness" if ill else "life")
        return True

    def _healers_restock(self):
        """NPC healers with too little medicine in their pack take some from the camp store."""
        t = self.rules.get("treatment", {})
        keep = int(t.get("healer_keeps", 0))
        poss = self.engine.possessions
        for occ in t.get("healers", []):
            for h in list(self.gov.occupations.get(occ, [])):
                if poss._keeps_all(h) or poss.hands_free(h):  # you look after your own pack; asleep: later
                    continue
                for m in sorted(t.get("medicine", []), key=lambda m: -m.get("power", 1.0)):
                    have = sum(h.inventory.count(x["item"]) for x in t.get("medicine", []))
                    if have >= keep:
                        break
                    if poss.ground.get(m["item"], 0):
                        poss._pick_up(h, {"item": m["item"], "count": keep - have}, "keeps medicine for the sick")

    # ------------------------------------------------------------------ #
    # Death and the dead
    # ------------------------------------------------------------------ #
    def die(self, person, cause: Optional[str] = None):
        ill = self.illness_of(person)
        cause = cause or (ill["name"].lower() if ill else "exhaustion")
        lost = " She was with child; the child is lost with her." if person.pregnancy else ""
        Messages.add(f"💀 {person.name} has died of {cause}, aged {person.age}.{lost}", category="vital")
        self.bodies.append({"name": person.name, "age": person.age, "gender": person.gender, "died": self.clock,
                            "cause": cause, "handler": None})
        self.deaths += 1
        self.engine.remove_person(person)
        self.engine.quality_event("death")  # one big chunk out of the tribe's Care (society.json qualities 'events')
        Messages.add(f"{self.rules.get('remains', {}).get('icon', '💀')} {person.name}'s body lies in camp. Until someone "
                     f"carries it away, burns or buries it (W), sickness spreads more easily.")

    def unclaimed_body(self) -> Optional[Dict[str, Any]]:
        return next((b for b in self.bodies if not b["handler"]), None)

    def reserve_body(self, person) -> Optional[str]:
        b = self.unclaimed_body()
        if b is None:
            return None
        b["handler"] = person.name
        return b["name"]

    def release_bodies(self, name: str):
        for b in self.bodies:
            if b["handler"] == name:
                b["handler"] = None

    def dispose(self, body_name: Optional[str], person, task):
        """Someone has laid one of the dead to rest: the body is gone from camp and from the tribe list."""
        b = next((b for b in self.bodies if b["name"] == body_name), None)
        if b is None:
            return
        self.bodies.remove(b)
        text = (task.done_text or "lays {body} to rest").format(name=person.name, body=b["name"])
        Messages.add(f"{person.name} {text}. {b['name']} is gone from the tribe.", category="vital")

    # ------------------------------------------------------------------ #
    # Pregnancy and birth
    # ------------------------------------------------------------------ #
    def can_conceive(self, person) -> float:
        """How likely (a weight) this person is to be the one who becomes pregnant (0 = can't)."""
        pr = self.rules.get("pregnancy", {})
        if not person.bears_children or person.pregnancy:
            return 0.0
        if person.illness and pr.get("not_while_ill", True):
            return 0.0
        if person.last_birth is not None and \
                self.clock - person.last_birth < pr.get("rest_after_birth_days", 0) * HOURS_PER_DAY:
            return 0.0
        return max(0.0, curve(pr.get("fertility", [[0, 0]]), person.age))

    def _pregnancy_roll(self):
        pr = self.rules.get("pregnancy", {})
        every = int(pr.get("roll_every_days", 28))
        if every <= 0 or (self.clock // HOURS_PER_DAY) % every:
            return
        if random.random() >= pr.get("chance", 0.0):
            return
        options = [(p, w) for p in self.players if (w := self.can_conceive(p)) > 0]
        if not options:
            return
        mother = random.choices([p for p, _ in options], [w for _, w in options])[0]
        self.conceive(mother)

    def conceive(self, mother):
        pr = self.rules.get("pregnancy", {})
        due = self.clock + int(pr.get("term_days", 270) * HOURS_PER_DAY)
        mother.pregnancy = {"since": self.clock, "due": due}
        Messages.add(f"{pr.get('icon', '🤰')} {mother.name} is with child: the baby is due around {format_date(due)}",
                     category="vital")

    def _births(self):
        for p in list(self.players):
            if p.pregnancy and self.clock >= p.pregnancy["due"]:
                self.give_birth(p)

    def _new_name(self, gender: str) -> str:
        names = list(self.rules["birth"]["names"][gender])
        for n in names:
            if n not in self.used_names:
                return n
        for numeral in ROMAN:
            for n in names:
                if f"{n} {numeral}" not in self.used_names:
                    return f"{n} {numeral}"
        return f"{names[0]} {len(self.used_names)}"

    def give_birth(self, mother):
        from world.player import Player
        b = self.rules["birth"]
        genders = {g: w for g, w in b.get("genders", {}).items() if w > 0} or {next(iter(CHARACTER.genders)): 1}
        gender = random.choices(list(genders), list(genders.values()))[0]
        name = self._new_name(gender)
        pool = list(b.get("trait_pool", []))
        traits = random.sample(pool, min(int(b.get("traits", 0)), len(pool)))
        start = int(b.get("attribute_start", 5))
        child = Player(player_id=max((p.id for p in self.players), default=0) + 1, name=name, age=0,
                       description=b.get("description", "").format(mother=mother.name, date=format_date(self.clock)),
                       attributes={a: start for a in CHARACTER.attributes}, skills={}, traits=traits,
                       controller="npc", gender=gender, birth_day=day_of_year(self.clock), mother=mother.name,
                       born=self.clock, starting_items=False)
        mother.pregnancy = None
        mother.last_birth = self.clock
        self.used_names.add(name)
        self.births += 1
        self.engine.add_person(child)
        word = CHARACTER.genders.get(gender, {}).get("child", "child")
        Messages.add(f"👶 {mother.name} has given birth to a {word}, {name}!", category="vital")
        return child

    # ------------------------------------------------------------------ #
    # Childhood: play and study
    # ------------------------------------------------------------------ #
    def activity(self, key: str) -> Optional[Dict[str, Any]]:
        return _public(self.rules.get("childhood", {}).get("activities", {})).get(key)

    def activities_for(self, person) -> List[Tuple[str, Dict[str, Any]]]:
        """The play and study open to this child now (none for anyone old enough to work)."""
        if not self.is_child(person):
            return []
        out = []
        for key, a in _public(self.rules.get("childhood", {}).get("activities", {})).items():
            if person.age < a.get("min_age", 0) or not self.gov.is_unlocked(a.get("requires", [])):
                continue
            if a.get("needs_company") and not any(q is not person and self.is_child(q) and q.age >= a.get("min_age", 0)
                                                  for q in self.players):
                continue
            out.append((key, a))
        return out

    def finish_activity(self, person, key: str):
        """A child has finished playing or studying: it shapes their attributes and skills."""
        a = self.activity(key)
        if a is None or person not in self.players:
            return
        if not self.is_child(person):
            Messages.add(f"{person.name} finishes: {a['label'].lower()}", important=False, category="life")
            return  # grew up meanwhile: what they are is set
        grew = []
        for attr, pts in a.get("attributes", {}).items():
            person.growth[attr] = person.growth.get(attr, 0.0) + float(pts)
            while person.growth[attr] >= 1 and person.attributes[attr] < CHARACTER.attr_max:
                person.attributes[attr] += 1
                person.growth[attr] -= 1
                grew.append(f"{CHARACTER.attributes[attr].abbr} {person.attributes[attr]}")
            if person.attributes[attr] >= CHARACTER.attr_max:
                person.growth[attr] = 0.0
        for skill, amount in a.get("skills", {}).items():
            person.train(skill, float(amount))
        more = f" and grows ({', '.join(grew)})" if grew else ""
        Messages.add(f"{person.name} finishes: {a['label'].lower()}{more}", important=False, category="life")

    # ------------------------------------------------------------------ #
    # Playing on after you die
    # ------------------------------------------------------------------ #
    def successor_for(self, dead_name: str):
        """Whom someone who has died plays on as (life.json 'successor'), or None if nobody is left."""
        for rule in self.rules.get("successor", {}).get("order", ["anyone"]):
            if rule == "children":
                pool = [p for p in self.players if p.mother == dead_name]
                if pool:
                    return max(pool, key=lambda p: p.age)
            elif rule == "youngest_adult":
                pool = [p for p in self.players if self.of_age(p, "politics")]
                if pool:
                    return min(pool, key=lambda p: p.age)
            elif rule == "anyone" and self.players:
                return min(self.players, key=lambda p: p.age)
        return None

    # ------------------------------------------------------------------ #
    # Observation and saving
    # ------------------------------------------------------------------ #
    def observe_person(self, person) -> Dict[str, Any]:
        r = self.rules
        g = CHARACTER.genders.get(person.gender, {})
        ill = self.illness_of(person)
        out: Dict[str, Any] = {
            "gender": person.gender, "gender_name": g.get("name", person.gender or ""), "gender_icon": g.get("icon", ""),
            "stage": self.life_stage(person), "child": self.is_child(person),
            "of_age": self.of_age(person, "politics"), "work_age": r["work_age"], "politics_age": r["politics_age"],
            "mother": person.mother, "illness": None, "pregnancy": None, "growth": None,
        }
        if ill:
            days = (self.clock - person.illness["since"]) // HOURS_PER_DAY
            opt = self.treatment_for(person)
            out["illness"] = {"key": person.illness["key"], "name": ill["name"], "icon": ill.get("icon", "🤒"),
                              "description": ill.get("description", ""), "days": int(days),
                              "health_loss_per_day": ill.get("health_loss_per_day", 0), "fatal": ill.get("fatal", True),
                              "healer": opt["healer"].name if opt else None,
                              "cure_chance": round(opt["cure_chance"], 2) if opt and opt.get("cure_chance") is not None else None}
        if person.pregnancy:
            pr = r.get("pregnancy", {})
            term = max(1, person.pregnancy["due"] - person.pregnancy["since"])
            done = max(0, min(term, self.clock - person.pregnancy["since"]))
            stop = person.pregnancy["due"] - pr.get("no_work_last_days", 90) * HOURS_PER_DAY
            out["pregnancy"] = {"icon": pr.get("icon", "🤰"), "done_hours": done, "term_hours": term,
                                "share": round(done / term, 3), "months": round(done / (30 * HOURS_PER_DAY), 1),
                                "term_months": round(term / (30 * HOURS_PER_DAY), 1),
                                "due": format_date(person.pregnancy["due"]),
                                "no_work": self.clock >= stop, "no_work_from": format_date(stop),
                                "days_to_rest": max(0, (stop - self.clock) // HOURS_PER_DAY)}
        if self.is_child(person):
            out["growth"] = {k: round(v, 2) for k, v in person.growth.items() if v > 0}
            out["years_to_work"] = max(0, r["work_age"] - person.age)
            out["activities"] = {k: {"label": a["label"], "group": a.get("group", "play"),
                                     "life_hours": a.get("life_hours", 1.5), "attributes": dict(a.get("attributes", {})),
                                     "skills": dict(a.get("skills", {})), "needs_company": bool(a.get("needs_company"))}
                                 for k, a in _public(r.get("childhood", {}).get("activities", {})).items()}
        t = r.get("treatment", {})
        out["can_see_healer"] = self.treatment_for(person) is not None
        out["needs_healer"] = bool(person.illness) or person.health < t.get("below_health", 60)
        return out

    def observe(self) -> Dict[str, Any]:
        r = self.rules
        icon = r.get("remains", {}).get("icon", "💀")
        return {"bodies": [{"name": b["name"], "age": b["age"], "gender": b.get("gender"), "cause": b["cause"],
                            "died": format_date(b["died"]), "days": int((self.clock - b["died"]) // HOURS_PER_DAY),
                            "handler": b["handler"], "icon": icon} for b in self.bodies],
                "illness_factor": round(self.body_factor(), 2), "work_age": r["work_age"],
                "politics_age": r["politics_age"], "births": self.births, "deaths": self.deaths,
                "healers_with_nothing": self.healers_with_nothing(),
                "illnesses": {k: {"name": i["name"], "icon": i.get("icon", "🤒")} for k, i in self.illnesses().items()}}

    def to_dict(self) -> Dict[str, Any]:
        return {"bodies": [dict(b) for b in self.bodies], "used_names": sorted(self.used_names),
                "births": self.births, "deaths": self.deaths}

    def load_state(self, data: Dict[str, Any]):
        self.bodies = [dict(b) for b in data.get("bodies", [])]
        self.used_names |= set(data.get("used_names", []))
        self.births = int(data.get("births", 0))
        self.deaths = int(data.get("deaths", 0))

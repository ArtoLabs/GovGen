"""Rule-based NPCs using utility scoring.

Whenever an NPC is free to act it scores every legal action and takes the best one. If nothing
scores above END_TURN_SCORE it waits instead, for longer or shorter depending on temperament. Scores come from
the NPC's stats and traits (data/players.json), its self-interest, and a little randomness. Every
choice carries a short reason, shown in full-detail logs.

The NPC sees only the engine's observation and legal actions, so the same slot can later be filled
by a smarter planner, an LLM, or an Unreal Engine AI agent.
"""
import random
import zlib
from typing import Any, Dict, List, Optional, Tuple

from controllers.base import Controller, Decision
from core.actions import Action
from core.interfaces import unlock_note
from innovations.innovation import ALL_INNOVATIONS  # static game data, known to every client
from world.character import RULES as CHARACTER  # static game data too
from core.contests import CHALLENGE, kinds_allowed
from core.occupations import OCCUPATIONS
from utils import game_data
from utils.game_data import RULES_DIR
from utils.data_files import DATA_DIR, load_json

# How eager NPCs are (data/rules/npc.json): they look after their bodies as always, but do everything else far
# less than the player, and turn to politics only when unhappy.
# data/rules/npc.json as it is in every age; an age or a government may change any of it, and TUNING is then
# refilled in place with the version in force.
BASE_TUNING = load_json(RULES_DIR / "npc.json")
TUNING = dict(BASE_TUNING)
game_data.switchable("npc", BASE_TUNING, lambda r: game_data.fill(TUNING, r))
from core.contests import CHALLENGE_KINDS, power as contest_power, persuasion_power

from core.life import BASE as _LIFE
MEDICINE = {m["item"] for m in _LIFE.get("treatment", {}).get("medicine", [])}  # items a healer heals with

END_TURN_SCORE = 1.0  # below this, the NPC would rather wait
VOTE_BASE = 10.0  # voting always beats ending the turn

HARMFUL_EFFECTS = {"loses_office", "cannot_hold_office", "cannot_vote", "no_member_interfaces"}

# Which stat makes someone suited to an interface.
STAT_FOR_INTERFACE = {
    "leadership": "charisma", "civic_representation": "charisma", "religious": "wisdom",
    "legislative": "intelligence", "judicial": "wisdom", "economic": "intelligence",
    "intelligence": "wisdom", "military": "strength", "infrastructure": "constitution",
}
STAT_ABBR = {k: a.abbr for k, a in CHARACTER.attributes.items()}
NEED_WEIGHT = 9.0  # how strongly an empty need pulls an NPC towards looking after it

# Traits push four tendencies; unknown traits are ignored.
TRAIT_TENDENCIES = {
    "ambition":   {"ambitious", "reckless", "passionate", "shrewd", "calculating", "persuasive"},
    "tradition":  {"conservative", "traditional", "stubborn", "patient", "respected"},
    "compassion": {"caring", "empathetic", "fair", "diplomatic", "justice-driven"},
    "curiosity":  {"inventive", "observant", "rational", "practical", "impatient"},
}


class Persona:
    def __init__(self, info: Dict[str, Any]):
        self.name = info["name"]
        traits = set(info.get("traits", []))
        for tendency, words in TRAIT_TENDENCIES.items():
            setattr(self, tendency, min(1.0, 0.2 + 0.5 * len(traits & words)))

    def strongest(self) -> str:
        return max(TRAIT_TENDENCIES, key=lambda t: getattr(self, t))


class NPCController(Controller):
    def __init__(self, name: str, rng: Optional[random.Random] = None):
        self.name = name
        self.rng = rng or random.Random()
        self.persona: Optional[Persona] = None
        self._nominated: set = set()         # elections this NPC has already nominated in
        self._researched_at: Optional[int] = None
        self._appointed_at: Optional[int] = None
        self._contested_year: Optional[int] = None  # last time this NPC went for an office by persuasion or challenge
        self._last_motion_year: Optional[int] = None
        self._proposed: Dict[str, int] = {}   # proposal key -> year; don't repeat the same one for a while
        self._engaged: Dict[str, bool] = {}   # ballot id -> whether this NPC bothers to take part

    # ------------------------------------------------------------------ #
    def decide(self, view: Dict[str, Any], legal: List[Action]) -> Optional[Decision]:
        if self.persona is None:
            self.persona = Persona(self._player(view, self.name))
        scored: List[Tuple[float, str, Action]] = []
        # A hungry, thirsty, cold or exhausted person has less mind for anything else (npc.json
        # 'distress_damping'), except for work that would bring back what they lack: a starving Gatherer
        # still goes foraging, or nobody would ever eat again.
        needs = view["character"]["needs"]
        damping = TUNING.get("distress_damping", 0.6)
        # The sick and the badly hurt rest rather than work or play (npc.json 'health'): health comes back
        # only while not working.
        h = TUNING.get("health", {})
        life = view["character"].get("life", {})
        hp = view["character"]["health"]
        unwell = h.get("work_when_ill", 0.2) if life.get("illness") else \
            h.get("work_when_hurt", 0.5) if hp < h.get("rest_below", 50) else 1.0
        # Research goes cheapest first (npc.json 'research.cheapest_first'): only the lowest cost they could queue.
        costs = [ALL_INNOVATIONS[a.params["innovation"]].cost for a in legal if a.type == "research"]
        self._cheapest = min(costs) if costs else None
        for action in legal:
            if action.type != "wait":
                score, reason = self._score(view, action)
                if action.type not in ("care", "vote", "treat"):
                    relieved = self._relieves(view, action)
                    distress = max((self._urgency(needs[k]["value"]) for k in needs if k not in relieved), default=0.0)
                    score *= 1 - damping * distress
                if action.type in ("work", "craft", "activity") and not self._relieves(view, action):
                    score *= unwell
                scored.append((score, reason, action))
        if scored:
            score, reason, best = max(scored, key=lambda s: s[0])
            if score >= END_TURN_SCORE:
                self._remember(view, best)
                return Decision(best, reason)
        return Decision(self._choose_wait(legal))

    # ------------------------------------------------------------------ #
    # Work: produce what the tribe is short of
    # ------------------------------------------------------------------ #
    @staticmethod
    def _shortage(view, item: str) -> float:
        """0 when the camp has enough of it (data/rules/work.json stock_targets), up to 1 when it has none."""
        from world.items import ITEMS
        camp = view["camp"]
        targets = camp["stock_targets"]
        kind = ITEMS[item].kind
        if kind in ("food", "water"):
            # What the store holds counts: people with nothing can only take from there.
            have = camp.get(f"store_{kind}_per_member", camp[f"{kind}_per_member"])
            want = targets.get(kind, 100) * TUNING.get("work", {}).get("store_share_of_target", 0.5)
        else:
            from world.items import substitutes
            store = {s["item"]: s["count"] for s in view["possessions"]["ground"]}
            have = sum(store.get(k, 0) for k in substitutes(item))  # a flint spear does for a wooden one
            want = targets.get(item, 0)
            if item in camp.get("tools_waited_for", []):
                # Someone appointed to work they can't do without it is waiting for one (npc.json 'work').
                return TUNING.get("work", {}).get("waiting_tool_need", 1.0)
        if not want:
            return 0.0
        return max(0.0, min(1.0, 1 - have / want))

    def _score_work_like(self, view, action: Action, info: Dict[str, Any]) -> Tuple[float, str]:
        from world.items import ITEMS
        camp = view["camp"]
        if info.get("fire_life_hours"):
            short = max(0.0, 1 - camp["fire_hours_left"] / max(1, camp["fire_max_hours"]))
            why = "the fire is burning low" if short > 0.5 else "keeps the fire fed"
        elif info["yields"]:
            shorts = [(self._shortage(view, y["item"]), y["item"]) for y in info["yields"]]
            short, item = max(shorts)
            kind = ITEMS[item].kind
            why = (f"the tribe is short of {kind}" if kind in ("food", "water") else
                   f"the camp needs {ITEMS[item].name.lower()}")
        else:
            short, why = 0.0, "does their duty"
        cfg = TUNING.get("work", {})
        if info.get("site"):
            # A trip is a gamble: worth less where nobody knows of a good place (data/rules/work.json 'trips').
            luck = cfg.get("luck_weight", 0.6)
            short *= 1 - luck + luck * info.get("chance", 1.0)
            if info.get("site_known"):
                why += " (a Scout found a good place)"
        if info.get("scouts_for"):
            short, why = self._scout_need(view, info)
        mine = info.get("own_job", False)
        idle = 0.0 if camp["worked_recently"] else 1.0
        # Their own hunger or thirst counts too: they keep a few meals of what they bring back
        # (npc.json 'work.own_need_weight').
        needs = view["character"]["needs"]
        relieved = self._relieves(view, action)
        own = max((self._urgency(needs[n]["value"]) for n in relieved), default=0.0)
        if not mine and max(short, own) < 0.25:
            return 0.0, ""  # chores outside one's job: only when the tribe (or they themselves) really need it
        # Contentment with work grows only while working it (society.json 'work'): someone whose Work meter
        # has sunk wants to get on with their job (npc.json 'work.content_weight', 'content_wanted').
        wanted = cfg.get("content_wanted", 70)
        work_meter = view.get("satisfaction", {}).get("work", {}).get("value", wanted)
        restless = max(0.0, (wanted - work_meter) / max(1.0, wanted)) if mine else 0.0
        score = 0.6 + 5.5 * short + (1.6 * idle if mine else 0) + cfg.get("content_weight", 1.5) * restless \
            + cfg.get("own_need_weight", 3.0) * own + self._noise(0.6)
        if not short and idle:
            why = "has not worked in a while"
        elif not short and restless > 0.3:
            why = "wants to get on with their work"
        if own > 0.3 and own * cfg.get("own_need_weight", 3.0) > 5.5 * short:
            why = "is hungry" if "food" in relieved else "is thirsty" if "water" in relieved else "needs it themselves"
        if view["world"]["night"]:
            score *= 0.35
        return score, why

    def _scout_need(self, view, info: Dict[str, Any]) -> Tuple[float, str]:
        """How much the tribe needs a Scout to find this kind of place: as short as it is of what trips there
        bring back (no food: berry grounds, game trails, fishing pools), less when a found place of that kind still
        has plenty left (npc.json 'work.scout_known_factor'), and a little always ('scout_need': knowing where to
        go never hurts)."""
        from world.items import ITEMS
        cfg = TUNING.get("work", {})
        kind = info["scouts_for"]
        left = sum(x["loads"] for x in view["camp"].get("sites", []) if x["kind"] == kind)
        shorts = [(self._shortage(view, item), item) for item in info.get("scout_items", [])]
        short, item = max(shorts, default=(0.0, ""))
        if left:
            short *= cfg.get("scout_known_factor", 0.25) ** min(2.0, left / 2)
        if short < cfg.get("scout_need", 0.15):
            return cfg.get("scout_need", 0.15), "knowing where to find things never hurts"
        what = ITEMS[item].kind if ITEMS[item].kind in ("food", "water") else ITEMS[item].name.lower()
        return short, f"the tribe is short of {what}"

    def _relieves(self, view, action: Action) -> set:
        """Needs (food, water...) that what this work brings back would restore; keeping the fire (tending it, or
        taking up the work of keeping it) relieves the cold, since warming up needs a fire."""
        warm = {n for c in CHARACTER.care_actions.values() if c.needs_amenity == "fire" for n in c.restores}
        if action.type == "take_occupation":
            return warm if "fire" in view["occupations"].get(action.params["occupation"], {}).get("provides", []) else set()
        if action.type not in ("work", "craft"):
            return set()
        from world.items import ITEMS
        info = self._work_info(view, action)
        if (info or {}).get("fire_life_hours"):
            return warm
        return {need for y in (info or {}).get("yields", []) for need, v in ITEMS[y["item"]].use.items()
                if v > 0 and need in view["character"]["needs"]}

    def _work_info(self, view, action: Action) -> Optional[Dict[str, Any]]:
        key = action.params.get("task") or action.params.get("recipe")
        return next((w for w in view["camp"]["work"] if w["kind"] == action.type and w["key"] == key), None)

    def _score_work(self, view, action: Action) -> Tuple[float, str]:
        info = self._work_info(view, action)
        if info and info.get("disposes_of_dead"):
            return self._score_dispose(view, info)
        return self._score_work_like(view, action, info) if info else (0.0, "")

    # ------------------------------------------------------------------ #
    # Life: the sick, the dead, and children (data/rules/life.json)
    # ------------------------------------------------------------------ #
    def _score_dispose(self, view, info) -> Tuple[float, str]:
        """The dead must be laid to rest before sickness spreads: someone without other pressing work goes,
        preferring the safer way (lower 'illness_risk')."""
        cfg = TUNING.get("remains", {})
        bodies = [b for b in view.get("life", {}).get("bodies", []) if not b["handler"]]
        if not bodies:
            return 0.0, ""
        busy_job = 1.0 if view["camp"]["work"] and any(w["own_job"] and not w["problem"] for w in view["camp"]["work"]) else 0.0
        score = cfg.get("base", 3.0) + cfg.get("per_body", 1.0) * len(bodies) + cfg.get("per_year", 2.0) * \
            max(b["days"] for b in bodies) / 360 - cfg.get("own_work_weight", 0.8) * busy_job \
            - cfg.get("risk_weight", 0.3) * (info.get("illness_risk") or 1.0) + self._noise(0.8)
        if view["world"]["night"]:
            score *= 0.5
        return score, f"{bodies[0]['name']} must be laid to rest before sickness spreads"

    def _score_heal(self, view, action: Action) -> Tuple[float, str]:
        """A healer goes to the sick before anything else (npc.json 'health.heal_ill', 'heal_hurt')."""
        cfg = TUNING.get("health", {})
        p = self._player(view, action.params["patient"])
        ill = (p.get("life") or {}).get("illness")
        hp = p["sheet"]["health"]
        if ill:
            return cfg.get("heal_ill", 10.0) + 4 * (1 - hp / 100) + self._noise(0.3), \
                f"{p['name']} is ill ({ill['name'].lower()}) and needs healing"
        return cfg.get("heal_hurt", 5.0) * (1 - hp / 100) + self._noise(0.3), f"{p['name']} is weak (health {hp:.0f})"

    def _score_treat(self, view, action: Action) -> Tuple[float, str]:
        """Go to the healer: at once when ill, now and then when badly hurt."""
        cfg = TUNING.get("health", {})
        life = view["character"].get("life", {})
        hp = view["character"]["health"]
        if life.get("illness"):
            return cfg.get("treat_when_ill", 9.0) + 4 * (1 - hp / 100) + self._noise(0.5), \
                f"is ill ({life['illness']['name'].lower()}) and needs a healer"
        return cfg.get("treat_when_hurt", 4.0) * (1 - hp / 100) + self._noise(0.3), f"is weak (health {hp:.0f})"

    def _taste(self, key: str) -> float:
        """A child's lasting liking (0-1) for one kind of play or study: the same every time for the same child."""
        return (zlib.crc32(f"{self.name}:{key}".encode()) % 1000) / 1000

    def _score_activity(self, view, action: Action) -> Tuple[float, str]:
        """Children play and study whenever their bodies allow, each after their own tastes, which is what
        shapes the adult they become."""
        cfg = TUNING.get("childhood", {})
        key = action.params["activity"]
        wanted = TUNING.get("work", {}).get("content_wanted", 70)
        work_meter = view.get("satisfaction", {}).get("work", {}).get("value", wanted)
        bored = max(0.0, (wanted - work_meter) / max(1.0, wanted))
        score = cfg.get("base", 1.8) + cfg.get("taste", 2.5) * self._taste(key) + cfg.get("bored_weight", 1.0) * bored \
            + self._noise(cfg.get("noise", 1.0))
        if view["world"]["night"]:
            score *= cfg.get("night_factor", 0.35)
        return score, "likes " + ("to " + action.label[0].lower() + action.label[1:] if action.group == "play" else
                                  "learning: " + action.label.lower())

    def _score_craft(self, view, action: Action) -> Tuple[float, str]:
        info = self._work_info(view, action)
        if not info:
            return 0.0, ""
        score, why = self._score_work_like(view, action, info)
        # While anyone is ill, medicine is for the sick: no turning herbs into something else (a poultice).
        from world.items import ITEMS
        uses_medicine = any(s["item"] in MEDICINE for s in info.get("consumes", []))
        if uses_medicine and any((p.get("life") or {}).get("illness") for p in view["players"]):
            score *= TUNING.get("health", {}).get("craft_medicine_while_ill", 0.1)
            why += " (but the sick need the herbs)"
        # Rather make the better version of a tool when they can (items.json 'counts_as').
        from world.items import ITEMS
        made = {y["item"] for y in info["yields"]}
        better = {w["yields"][0]["item"] for w in view["camp"]["work"] if w["kind"] == "craft" and not w["problem"]
                  and w["yields"] and made & set(ITEMS[w["yields"][0]["item"]].counts_as)}
        if better:
            score *= TUNING.get("work", {}).get("lesser_tool_factor", 0.4)
        return score, why

    # ------------------------------------------------------------------ #
    # Trades
    # ------------------------------------------------------------------ #
    def _worth(self, view, stacks) -> float:
        """What items are worth to this NPC: their trade value, more for food and water they need now."""
        from world.items import ITEMS
        needs = view["character"]["needs"]
        total = 0.0
        for s in stacks:
            item = ITEMS[s["item"]]
            want = max((self._urgency(needs[n]["value"]) for n in item.use if n in needs), default=0.0)
            total += item.value * (1 + 2 * want) * s["count"]
        return total

    def _willing_to_part(self, view, stacks) -> float:
        """Chance (0-1) this NPC hands over `stacks` for nothing (npc.json 'asking'): good-natured people
        share more readily, and asking for 1 of their 10 is easy where asking for all they have is not.
        Food or water they badly need themselves they part with less readily still."""
        from world.items import ITEMS
        cfg = TUNING.get("asking", {})
        p = self.persona
        g = cfg.get("base", 0.85) + cfg.get("compassion", 0.3) * p.compassion - cfg.get("ambition", 0.25) * p.ambition
        g = max(0.0, min(1.0, g))
        have: Dict[str, int] = {}
        for slot in view["possessions"]["inventory"]["slots"]:
            if slot:
                have[slot["item"]] = have.get(slot["item"], 0) + slot["count"]
        needs = view["character"]["needs"]
        floor, curve = cfg.get("all_of_it", 0.05), cfg.get("curve", 1.5)
        chance = g
        for s in stacks:
            ratio = min(1.0, s["count"] / max(1, have.get(s["item"], 0)))
            chance *= floor + (1 - floor) * (1 - ratio) ** curve
            want = max((self._urgency(needs[n]["value"]) for n in ITEMS[s["item"]].use if n in needs), default=0.0)
            chance *= 1 - cfg.get("own_need", 0.8) * want
        return chance

    def answer_offer(self, view: Dict[str, Any], offer: Dict[str, Any]) -> Optional[Decision]:
        """Take a trade that leaves them no worse off (a shrewd trader wants a little more). What a trade
        (or a plain request) doesn't pay for, they may still give out of goodwill: likelier the smaller
        a share of what they have it is (npc.json 'asking')."""
        if self.persona is None:
            self.persona = Persona(self._player(view, self.name))
        get, lose = self._worth(view, offer["give"]), self._worth(view, offer["want"])
        margin = 1.0 + 0.2 * self.persona.ambition - 0.15 * self.persona.compassion
        if get >= lose * margin:
            reason = f"a fair trade ({get:.0f} for {lose:.0f})" if lose else "a gift"
            return Decision(Action("answer_trade", {"offer": offer["id"], "accept": True}), reason)
        unpaid = 1 - get / (lose * margin)
        chance = 1 - unpaid * (1 - self._willing_to_part(view, offer["want"]))
        accept = self.rng.random() < chance
        if not offer["give"]:
            reason = ("can spare it" if accept else "would rather keep it") + f" ({chance:.0%} likely to share)"
        else:
            reason = (f"not quite worth it ({get:.0f} for {lose:.0f}) but agrees anyway" if accept else
                      f"not worth it ({get:.0f} for {lose:.0f})")
        return Decision(Action("answer_trade", {"offer": offer["id"], "accept": accept}), reason)

    @staticmethod
    def _urgency(value: float) -> float:
        return max(0.0, min(1.0, (70 - value) / 70))

    def _score_care(self, view, action: Action) -> Tuple[float, str]:
        """Look after the body: the emptier the need, the stronger the pull. People sleep at night,
        and only nap by day when worn out."""
        care = CHARACTER.care_actions[action.params["kind"]]
        needs = view["character"]["needs"]
        night = view["world"]["night"]
        best, why = 0.0, ""
        for need, amount in care.restores.items():
            value = needs[need]["value"]
            u = self._urgency(value)
            score = NEED_WEIGHT * u ** 1.5
            if need != "energy" and value < CHARACTER.needs[need].critical:
                score += TUNING.get("care", {}).get("critical_bonus", 6)  # starving or parched comes first
            if need == "energy":
                if night and value < 75:
                    score += 3 + 3 * (1 - value / 100)
                    why_night = "it is night and they are tired"
                elif not night and value > 25:
                    score = 0.0  # no daytime naps unless exhausted
            if score > best:
                best = score
                why = why_night if need == "energy" and night and value < 75 else f"feels {needs[need]['label'].lower()}"
        if best < 0.5:
            return 0.0, ""
        return best + self._noise(0.3), why

    def _occupation_fit(self, view, name: str, occupation: str) -> Tuple[float, str]:
        occ = view["occupations"][occupation]
        p = self._player(view, name)
        attrs = occ["attributes"] or ["strength"]
        fit = sum(p[a] for a in attrs) / len(attrs)
        skill = p["sheet"]["skills"].get(occ["skill"], 0) if occ["skill"] else 0
        best = max(attrs, key=lambda a: p[a])
        return fit + skill / 2, f"{STAT_ABBR[best]} {p[best]}" + (f", {occ['skill']} {skill:g}" if skill else "")

    def _quality_gap(self, view, occupation: str) -> Tuple[float, str]:
        """How short the tribe is of the society qualities this work feeds (0 = enough, 1 = none), and
        the shortest one's name."""
        qualities = view["society"]["qualities"]
        gap_below = TUNING.get("appoint", {}).get("gap_below", 65)
        gaps = [(max(0.0, (gap_below - qualities[k]["value"]) / gap_below), qualities[k]["name"])
                for k in view["occupations"][occupation].get("feeds", []) if qualities.get(k, {}).get("active")]
        return max(gaps + [self._store_gap(view, occupation)], default=(0.0, ""))

    def _store_gap(self, view, occupation: str) -> Tuple[float, str]:
        """What the camp store actually lacks, of what this work brings back: an empty store needs
        Gatherers however well the tribe looks on paper, and nobody knowing where to go needs Scouts."""
        gaps: List[Tuple[float, str]] = []
        from core import work as WORK
        from world.items import ITEMS
        camp = view.get("camp", {})
        weight = TUNING.get("appoint", {}).get("store_weight", 0.8)
        for t in WORK.TASKS.values():
            if occupation not in t.occupations:
                continue
            for y in t.yields:
                kind = ITEMS[y["item"]].kind
                gaps.append((weight * self._shortage(view, y["item"]),
                             kind if kind in ("food", "water") else ITEMS[y["item"]].name.lower()))
            if t.scouts_for and t.scouts_for in camp.get("useful_sites", []):
                items = [y["item"] for x in WORK.site_tasks(t.scouts_for) for y in x.yields]
                short, _ = self._scout_need(view, {"scouts_for": t.scouts_for, "scout_items": items})
                gaps.append((weight * short, f"places to find {WORK.SITE_KINDS[t.scouts_for]['short']}"))
        # Work that keeps something the camp has (the fire): needed when nobody does it, more as it burns low.
        occ = view.get("occupations", {}).get(occupation, {})
        if "fire" in occ.get("provides", []) and camp.get("fire_max_hours"):
            keepers = [n for o in view["occupations"].values() if "fire" in o.get("provides", []) for n in o["holders"]]
            low = 1 - camp.get("fire_hours_left", 0) / camp["fire_max_hours"]
            gaps.append((weight * (1.0 if not keepers else 0.5 * low), "a fire to keep warm by"))
        return max(gaps, default=(0.0, ""))

    def _score_take_occupation(self, view, action: Action) -> Tuple[float, str]:
        name = action.params["occupation"]
        fit, why = self._occupation_fit(view, self.name, name)
        p = self.persona
        # There is no limit on how many do the same work, so people spread out: work many already do is
        # less attractive, work the tribe is short of more (npc.json 'volunteer').
        cfg = TUNING.get("volunteer", {})
        share = len(view["occupations"][name]["holders"]) / max(1, len(view["players"]))
        gap, _ = self._quality_gap(view, name)
        return (0.6 + (fit - 4) / 3 + 0.3 * p.curiosity + cfg.get("need", 1.0) * gap
                - cfg.get("crowding", 3.0) * share + self._noise(0.6)), f"is suited to be a {name} ({why})"

    def _score_leave_occupation(self, view, action: Action) -> Tuple[float, str]:
        fit, why = self._occupation_fit(view, self.name, action.params["occupation"])
        return (3.5 - fit) / 3 + self._noise(0.2), f"is not cut out for it ({why})"

    def _choose_wait(self, legal: List[Action]) -> Action:
        """Patient, traditional NPCs let more time pass between actions; restless ones less."""
        waits = sorted((a for a in legal if a.type == "wait"), key=lambda a: a.params["days"])
        p = self.persona
        preferred = 30 * (1 + p.tradition - 0.4 * p.curiosity - 0.4 * p.ambition) * self.rng.uniform(0.5, 1.5)
        return min(waits, key=lambda a: abs(a.params["days"] - preferred))

    def _remember(self, view, action: Action):
        if action.type == "nominate":
            self._nominated.add(self._election_id(view, action.params["ballot"]))
        elif action.type == "research":
            self._researched_at = view["time"]
        elif action.type == "appoint":
            self._appointed_at = view["time"]
        elif action.type in ("persuade", "challenge"):
            self._contested_year = view["year"]
        elif action.type in ("call_vote", "reform", "dismiss"):
            self._last_motion_year = view["year"]
            self._proposed[str(action.key())] = view["year"]

    # Saving -------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        version, internal, gauss = self.rng.getstate()
        return {"kind": "npc", "rng": [version, list(internal), gauss], "nominated": sorted(self._nominated),
                "researched_at": self._researched_at, "appointed_at": self._appointed_at, "contested_year": self._contested_year, "engaged": dict(self._engaged), "last_motion_year": self._last_motion_year,
                "proposed": self._proposed}

    def load_state(self, data: Dict[str, Any]):
        if not data or data.get("kind") != "npc":
            return
        version, internal, gauss = data["rng"]
        self.rng.setstate((version, tuple(internal), gauss))
        self._nominated = set(data["nominated"])
        self._researched_at = data["researched_at"]
        self._appointed_at = data.get("appointed_at")
        self._contested_year = data.get("contested_year")
        self._engaged = dict(data.get("engaged", {}))
        self._last_motion_year = data["last_motion_year"]
        self._proposed = dict(data["proposed"])

    def _recently_proposed(self, view, action: Action, years: int = 10) -> bool:
        year = self._proposed.get(str(action.key()))
        return year is not None and view["year"] - year < years

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _player(view, name: str) -> Dict[str, Any]:
        return next(p for p in view["players"] if p["name"] == name)

    def _fit(self, view, name: str, interfaces: List[str]) -> Tuple[float, str]:
        """How suited a player is (1-10) to an office with these interfaces, and the stat that decided it."""
        p = self._player(view, name)
        stats = [STAT_FOR_INTERFACE.get(i, "intelligence") for i in interfaces] or ["intelligence"]
        main = max(dict.fromkeys(stats), key=stats.count)  # ordered, so results never depend on hash order
        return sum(p[s] for s in stats) / len(stats), f"{STAT_ABBR[main]} {p[main]}"

    def _office_interfaces(self, view, office: str) -> List[str]:
        return view["offices"].get(office, {}).get("interfaces", [])

    def _noise(self, scale: float = 1.0) -> float:
        return self.rng.uniform(0, scale)

    def _my_offices(self, view) -> List[str]:
        return self._player(view, self.name)["offices"]

    # ------------------------------------------------------------------ #
    # Scoring
    # ------------------------------------------------------------------ #
    def _score(self, view, action: Action) -> Tuple[float, str]:
        return getattr(self, f"_score_{action.type}", lambda v, a: (0.0, ""))(view, action)

    # ------------------------------------------------------------------ #
    # Satisfaction: what moves an NPC to act at all
    # ------------------------------------------------------------------ #
    @staticmethod
    def _discontent_of(value: float) -> float:
        """0 while content, rising to 1 as a satisfaction meter falls (data/rules/npc.json 'discontent')."""
        cfg = TUNING.get("discontent", {})
        start, full = cfg.get("starts_below", 50), cfg.get("full_at", 20)
        return max(0.0, min(1.0, (start - value) / max(1.0, start - full)))

    def _discontent(self, view, meter: str) -> float:
        sat = view.get("satisfaction", {}).get(meter)
        return self._discontent_of(sat["value"]) if sat else 0.0

    def _unrest(self, view, meter: str) -> float:
        """Discontent this NPC is ready to act on: none while they are still being patient with the leaders
        (data/rules/society.json 'satisfaction.patience'), all of it once their patience has run out."""
        patience = view.get("patience", {}).get(meter)
        return self._discontent(view, meter) * (patience["restless"] if patience else 1.0)

    def _blame(self, view, office: str) -> float:
        """How much of the tribe's discontent falls on this office: the top office (most points) carries it
        all, lesser ones (points / top) ^ 'blame_exponent' of it (npc.json 'politics')."""
        offices = view["offices"]
        top = max((o["points"] for o in offices.values() if o.get("unlocked", True)), default=1) or 1
        return (offices[office]["points"] / top) ** TUNING.get("politics", {}).get("blame_exponent", 2)

    def _grievance(self, view, office: str, holder: Optional[str]) -> float:
        """Why move against this holder: the tribe's discontent with its leaders, weighted by how much of it
        this office carries, or the holder doing the job badly."""
        gap = self._holder_gap(view, office, holder) if holder else 0.0
        return max(self._unrest(view, "leaders") * self._blame(view, office), gap)

    def _holder_gap(self, view, office: str, holder: Optional[str]) -> float:
        """How badly a holder does their office: 0 if fine, up to 1 if hopeless (or the seat is empty)."""
        if not holder:
            return 1.0
        q = view["offices"][office]["holder_quality"].get(holder, 50)
        return max(0.0, min(1.0, (40 - q) / 30))

    def _engaged_in(self, view, ballot_id: str, chance: float) -> bool:
        """Decide once per ballot whether to bother taking part; keep the decision."""
        ids = {self._election_id(view, b["key"]) for b in view["ballots"]}
        live = ids | {"nom:" + i for i in ids} | {"decl:" + i for i in ids}
        for old in [k for k in self._engaged if k not in live]:
            del self._engaged[old]
        if ballot_id not in self._engaged:
            self._engaged[ballot_id] = self.rng.random() < chance
        return self._engaged[ballot_id]

    def _score_vote(self, view, action: Action) -> Tuple[float, str]:
        ballot = next(b for b in view["ballots"] if b["key"] == action.params["ballot"])
        choice = action.params["choice"]
        me, persona = self.name, self.persona
        # Not everyone votes: those who care (unhappy, ambitious, or with something at stake) are likelier to.
        at_stake = me in ballot.get("choices", []) or ballot.get("target") == me
        t = TUNING.get("turnout", {})
        chance = (t.get("base", 0.45) + t.get("discontent", 0.35) * self._discontent(view, "leaders")
                  + t.get("ambition", 0.15) * persona.ambition)
        if not at_stake and not self._engaged_in(view, self._election_id(view, ballot["key"]), chance):
            return 0.0, ""
        if ballot["kind"] == "election":
            fit, stat = self._fit(view, choice, self._office_interfaces(view, ballot["office"]))
            if choice == me:
                # Most people only back themselves when they are ambitious or plainly the best fit.
                bonus = 1.8 * persona.ambition - 0.6 - 0.6 * persona.compassion
                return VOTE_BASE + fit / 2 + bonus + self._noise(1.5), "votes for themselves"
            age = self._player(view, choice)["age"]
            score = VOTE_BASE + fit / 2 + persona.tradition * age / 20 + self._noise(1.5)
            if persona.tradition >= 0.7 and age >= 45:
                return score, f"trusts the experience of {choice} (age {age})"
            return score, f"thinks {choice} suits {ballot['office']} ({stat})"
        lean, why = self._motion_lean(view, ballot)
        yes = choice == "Yes"
        return VOTE_BASE + (lean if yes else -lean), why

    def _motion_lean(self, view, ballot) -> Tuple[float, str]:
        """Positive = inclined to vote Yes."""
        p, me, kind, target = self.persona, self.name, ballot["kind"], ballot.get("target")
        noise = self.rng.uniform(-0.5, 0.5)
        if target == me:
            return -5, "will not vote against themselves"
        if kind == "remove_office":
            fit, stat = self._fit(view, target, self._office_interfaces(view, ballot["subject"]))
            lean = (5 - fit) / 5 + p.ambition * 0.3 - p.tradition * 0.5 + noise
            why = (f"thinks {target} is unfit to be {ballot['subject']} ({stat})" if lean > 0
                   else f"sees no reason to remove {target}")
            return lean, why
        if kind == "grant_status":
            lean = -0.4 + p.ambition * 0.3 - p.compassion * 0.6 + noise
            return lean, ("wants to make an example of " + target) if lean > 0 else f"will not punish {target}"
        if kind == "revoke_status":
            lean = 0.2 + p.compassion * 0.6 - p.tradition * 0.3 + noise
            return lean, (f"believes {target} deserves another chance" if lean > 0 else f"wants {target} to stay {ballot['subject']}")
        if kind == "reform":
            reform = next((r for r in view["government"]["available_reforms"] if r["key"] == ballot["subject"]), None)
            delta, how = self._reform_delta(view, reform)
            stability, why_stable = self._stability(view)
            newer = reform and reform["age"] != view["government"]["age"]
            lean = (delta * 0.9 + p.curiosity * 0.4 + p.ambition * 0.2 - p.tradition * 0.7
                    - 0.3 + (0.5 if newer else 0) + stability + noise)
            if delta:
                return lean, how
            if lean <= 0:
                return lean, why_stable or "is wary of change"
            return lean, (f"wants a government fit for the {reform['age']}" if newer else "welcomes a new way of governing")
        return noise, "undecided"

    def _reform_delta(self, view, reform) -> Tuple[int, str]:
        """+1 if this NPC would gain standing under the reform, -1 if it would lose it, 0 otherwise.
        An office's importance is judged by the innovation points it is worth in the data files."""
        if not reform:
            return 0, ""
        before = self._my_offices(view)
        after = reform["outcome"].get(self.name)
        old_points = view["offices"][before[0]]["points"] if before else 0
        new_points = reform["offices"][after]["points"] if after else 0
        if new_points > old_points:
            return 1, f"would become {after} under a {reform['name']}"
        if new_points < old_points:
            what = f"be reduced to {after}" if after else f"lose the office of {before[0]}"
            return -1, f"would {what} under a {reform['name']}"
        return 0, ""

    def _stability(self, view) -> Tuple[float, str]:
        """Reluctance to reform again soon after the last reform."""
        since = view["government"]["years_since_reform"]
        if since is not None and since < 8:
            return -0.8 * (8 - since) / 8, f"the last reform was only {since:.1f} years ago"
        return 0.0, ""

    @staticmethod
    def _election_id(view, key: str) -> str:
        """Ballot keys repeat (every Elder election is 'elect:Elder'); add the closing date to tell them apart."""
        ballot = next(b for b in view["ballots"] if b["key"] == key)
        return f"{key}@{ballot['closes']}"

    def _score_nominate(self, view, action: Action) -> Tuple[float, str]:
        if self._election_id(view, action.params["ballot"]) in self._nominated:
            return 0.0, ""
        chance = TUNING.get("nominate_chance", 0.35) + 0.3 * self.persona.ambition
        if not self._engaged_in(view, "nom:" + self._election_id(view, action.params["ballot"]), chance):
            return 0.0, ""
        ballot = next(b for b in view["ballots"] if b["key"] == action.params["ballot"])
        cand = action.params["candidate"]
        fit, stat = self._fit(view, cand, self._office_interfaces(view, ballot["office"]))
        interfaces = self._office_interfaces(view, ballot["office"])
        best_so_far = max((self._fit(view, n, interfaces)[0] for n in ballot["nominations"]), default=0)
        if cand == self.name:
            # Putting yourself forward takes ambition, and is less likely if someone better already stands.
            p = self.persona
            score = (-1.5 + 4 * max(0.0, p.ambition - 0.3) - 0.5 * p.compassion + (fit - 6) / 3
                     - max(0.0, best_so_far - fit) / 3 + self._noise(0.8))
            return score, (f"is ambitious and wants to be {ballot['office']}" if self.persona.ambition >= 0.7
                           else f"believes they would make a good {ballot['office']} ({stat})")
        # Only put someone forward if they beat the field already nominated.
        score = (fit - 5) / 4 + (fit - max(best_so_far, 5)) / 3 - 0.2 * len(ballot["nominations"]) + self._noise(0.8)
        return score, f"thinks {cand} would make a good {ballot['office']} ({stat})"

    def _score_decline_nomination(self, view, action: Action) -> Tuple[float, str]:
        """Someone else put this NPC forward. The modest, the ill-suited and those happy in their own
        work may turn it down (taking an office means giving up one's work). Decided once per election."""
        ballot = next(b for b in view["ballots"] if b["key"] == action.params["ballot"])
        if ballot.get("nominated_by", {}).get(self.name) == self.name:
            return 0.0, ""  # they put themselves forward
        office = ballot.get("office", "")
        fit, _ = self._fit(view, self.name, self._office_interfaces(view, office))
        me = self._player(view, self.name)
        work = me.get("work_quality") if me.get("occupations") else None
        p = self.persona
        lean = 0.6 + 5 * (0.45 - p.ambition) + (5 - fit) / 3 + (((work or 50) - 50) / 30 if work else -0.3) \
            + 0.6 * p.tradition * (1 if work else 0) + self._noise(0.5)
        key = "decl:" + self._election_id(view, ballot["key"])
        if key not in self._engaged:
            self._engaged[key] = lean > 0
        if not self._engaged[key]:
            return 0.0, ""
        if work and work >= 50:
            return 4.0, f"would rather keep their work as {', '.join(me['occupations'])} than be {office}"
        return 4.0, f"does not want to be {office}"

    def _score_appoint(self, view, action: Action) -> Tuple[float, str]:
        position, cand = action.params["position"], action.params["appointee"]
        if position in view["occupations"]:
            occ = view["occupations"][position]
            cfg = TUNING.get("appoint", {})
            if self._appointed_at is not None and view["time"] - self._appointed_at < cfg.get("days_between", 60) * 24:
                return 0.0, ""  # one appointment at a time; let it settle
            # Appoint only to mend something the tribe lacks: a society quality this work feeds is low.
            gap, what = self._quality_gap(view, position)
            if gap <= 0:
                return 0.0, ""
            fit, why = self._occupation_fit(view, cand, position)
            current = self._player(view, cand)["occupations"]
            # Rather someone without work than someone who already helps: moving people makes them resent it.
            switch = cfg.get("reassign_reluctance", 1.0) if current else 0.0
            gain, loss = self._move_worth(view, cand, position)
            if gain <= 0 or (current and gain <= 1.3 * loss + 1.0):
                return 0.0, ""  # taking them from their work would cost the tribe as much as it gains
            # People welcome higher work and resent lower work (society.json 'job_rank').
            ranks = [view["occupations"][o]["rank"] for o in current] or [0.0]
            step = occ.get("rank", 0.0) - max(ranks)
            # A step down still sours them, but in real need (an empty store: nobody fetching water) a leader
            # moves people down anyway: the reluctance fades as the need grows ('demote_gap_full').
            urgency = max(0.0, 1 - gap / max(1e-6, cfg.get("demote_gap_full", 0.5)))
            rank_pull = cfg.get("rank_weight", 0.3) * step if step > 0 else cfg.get("demote_weight", 0.6) * step * urgency
            if not occ.get("tools_ready", True):
                rank_pull -= cfg.get("no_tool_reluctance", 1.0)  # they'd only wait for a tool to be made
            return (0.2 + 3.0 * gap + (fit - 5) / 2.5 - switch + rank_pull + self._noise(0.5),
                    f"the tribe needs better {what.lower()}; {cand} would make a good {position} ({why})")
        if position in view["statuses"]:
            status = view["statuses"][position]
            if HARMFUL_EFFECTS & set(status["effects"]):
                # A punishment handed out alone (e.g. a monarch banishing someone): rare.
                p = self.persona
                return 0.1 + p.ambition * 0.3 - p.compassion * 0.5 + self._noise(0.4), f"wants {cand} gone"
            # Helpful statuses granted by appointment (e.g. Warrior): give them to the strong.
            strength = self._player(view, cand)["strength"]
            return strength / 5 - 0.6 + self._noise(0.6), f"{cand} is strong (STR {strength})"
        office = view["offices"][position]
        fit, stat = self._fit(view, cand, office["interfaces"])
        if len(office["holders"]) < office["seats"]:
            return 3 + fit / 2 + self._noise(), f"{cand} is the best choice for {position} ({stat})"
        # Filling a one-seat office means replacing the incumbent: only for a much better fit.
        old_fit, _ = self._fit(view, office["holders"][0], office["interfaces"])
        gain = fit - old_fit
        return gain / 3 * self.persona.ambition + self._noise(0.3), f"{cand} would do better than {office['holders'][0]} ({stat})"

    def _move_worth(self, view, cand: str, position: str) -> Tuple[float, float]:
        """(gain, loss) to the society, in weighted quality points, of `cand` becoming `position` and
        giving up their current work."""
        from core.society import supply_value
        qualities = view["society"]["qualities"]
        me = self._player(view, cand)

        def worth(k, delta, cats):
            q = qualities[k]
            return q["weight"] * (supply_value(q["detail"], delta, cats) - q["value"])

        gain = 0.0
        for k in view["occupations"][position].get("feeds", []):
            q = qualities.get(k)
            if not q or not q["active"] or "sources" not in q["detail"]:
                continue
            src = q["detail"]["sources"].get(position, {})
            add = src.get("amount", 1.0) * me.get("occupation_quality", {}).get(position, 50) / 50
            cats = set(q["detail"]["categories"]) | ({src["category"]} if src.get("category") else set())
            gain += worth(k, add, cats)
        loss = 0.0
        for old in me["occupations"]:
            for k in view["occupations"][old].get("feeds", []):
                q = qualities.get(k)
                if not q or not q["active"] or "sources" not in q["detail"]:
                    continue
                d = q["detail"]
                if not d.get("contrib", {}).get(cand):
                    continue  # not adding anything now (waiting for a tool, say): nothing lost by moving them
                cats = {d["sources"].get(s, {}).get("category") for s, n, _ in d["workers"] if n != cand} - {None}
                loss -= worth(k, -d.get("contrib", {}).get(cand, 0), cats)
        # The camp's fire (an amenity) rests on whoever keeps it: the only keeper is worth a lot (npc.json
        # 'appoint.sole_provider_worth'), since the Fire quality follows people using the fire, not the keeper.
        sole = TUNING.get("appoint", {}).get("sole_provider_worth", 40)
        occs = view["occupations"]
        for amenity in occs[position].get("provides", []):
            if not any(occs[o]["holders"] for o in occs if amenity in occs[o].get("provides", [])):
                gain += sole
        for old in me["occupations"]:
            for amenity in occs[old].get("provides", []):
                if [n for o in occs if amenity in occs[o].get("provides", []) for n in occs[o]["holders"]] == [cand]:
                    loss += sole
        return gain, loss

    def _score_dismiss(self, view, action: Action) -> Tuple[float, str]:
        if self._last_motion_year == view["year"]:
            return 0.0, ""
        position, holder = action.params["position"], action.params["holder"]
        if position in view["occupations"]:
            q = view["occupations"][position]["holder_quality"].get(holder, 50)
            poor_below = TUNING.get("dismiss", {}).get("poor_below", 25)  # dismissing makes people resent it
            return (poor_below - q) / 10 * self.persona.ambition + self._noise(0.3), f"{holder} is a poor {position} (quality {q:.0f})"
        if position in view["statuses"]:
            return 0.2 + self._noise(0.3), f"no longer needs {holder} as {position}"
        d = self._grievance(view, position, holder)
        return -0.5 + 2.5 * d * self.persona.ambition + self._noise(0.4), f"{holder} is failing as {position}"

    def _score_call_vote(self, view, action: Action) -> Tuple[float, str]:
        if (self._last_motion_year is not None and view["year"] - self._last_motion_year < 5) \
                or self._recently_proposed(view, action):
            return 0.0, ""
        p, kind, target, subject = self.persona, action.params["kind"], action.params["target"], action.params["subject"]
        if kind == "remove_office":
            # Only an unhappy tribe moves to remove someone: discontent with the leaders, or a holder doing badly.
            d = self._grievance(view, subject, target)
            if d <= 0:
                return 0.0, ""
            q = view["offices"][subject]["holder_quality"].get(target, 50)
            score = -1.0 + 3.0 * d + p.ambition * 0.4 - p.tradition * 0.4 + self._noise(0.6)
            return score, f"is unhappy with {target} as {subject} (doing the job at {q:.0f}/100)"
        if kind == "grant_status":
            d = self._unrest(view, "society")
            return (-0.6 + d + p.ambition * 0.3 - p.compassion * 0.5 + self._noise(0.5),
                    f"thinks {target} should be {subject}")
        return 0.5 + p.compassion * 0.6 + self._noise(0.4), f"thinks {target} has suffered enough"

    def _score_reform(self, view, action: Action) -> Tuple[float, str]:
        if (self._last_motion_year is not None and view["year"] - self._last_motion_year < 2) \
                or self._recently_proposed(view, action):
            return 0.0, ""
        reform = next(r for r in view["government"]["available_reforms"] if r["key"] == action.params["government"])
        delta, how = self._reform_delta(view, reform)
        if delta < 0:
            return 0.0, ""
        p = self.persona
        newer = reform["age"] != view["government"]["age"]
        stability, _ = self._stability(view)
        d = self._unrest(view, "society")  # people change their way of governing when long unhappy with it
        score = (-0.8 + 2.5 * d + p.curiosity * 0.5 + p.ambition * 0.3 - p.tradition * 0.6 + delta * 0.8
                 + (0.6 if newer else -0.2) + 2 * stability + self._noise(0.5))
        return score, how or (f"wants a government fit for the {reform['age']}" if newer else f"prefers a {reform['name']}")

    def _score_research(self, view, action: Action) -> Tuple[float, str]:
        cfg = TUNING.get("research", {})
        if (self._researched_at is not None and view["time"] - self._researched_at < cfg.get("days_between", 30) * 24) \
                or len(view["research_queue"]) >= cfg.get("max_queue", 3):
            return 0.0, ""
        name = action.params["innovation"]
        cheapest = getattr(self, "_cheapest", None)
        if cfg.get("cheapest_first", True) and cheapest is not None and ALL_INNOVATIONS[name].cost > cheapest:
            return 0.0, ""  # something cheaper comes first
        opens = unlock_note(name).replace("  * opens ", "")
        # Judge cost against the game's price level (data/rules/time.json innovation_cost_multiplier), not raw points.
        cost = ALL_INNOVATIONS[name].cost / TUNING.get("research", {}).get("cost_scale", 650)
        score = (cfg.get("base", 1.0) + self.persona.curiosity * cfg.get("curiosity", 0.8)
                 + (cfg.get("opens", 1.5) if opens else 0) - cost + self._noise(0.5)
                 # Nobody researching anything, or something free to learn: whoever can, queues it.
                 + (cfg.get("empty_queue", 2.5) if not view["research_queue"] and not view.get("researching") else 0)
                 + (cfg.get("free", 2.0) if not ALL_INNOVATIONS[name].cost else 0))
        why = f"{name} opens {opens}" if opens else "costs nothing to learn" if not ALL_INNOVATIONS[name].cost \
            else f"wants to learn {name}"
        if cfg.get("cheapest_first", True) and ALL_INNOVATIONS[name].cost:
            why += " (the cheapest to learn)"
        return score, why

    def _score_role_command(self, view, action: Action) -> Tuple[float, str]:
        return 0.0, ""  # flavor commands have no effect yet

    # ------------------------------------------------------------------ #
    # Contests: persuasion and challenges
    # ------------------------------------------------------------------ #
    def _wants_office(self, view, office: str) -> bool:
        """Only reach for an office more important than the one already held, and not every year:
        going after an office is a big step most people take rarely, if ever."""
        if self._contested_year is not None and view["year"] - self._contested_year < 12:
            return False
        mine = self._my_offices(view)
        return not mine or view["offices"][mine[0]]["points"] < view["offices"][office]["points"]

    def _contest_power(self, view, name: str, kind: str) -> float:
        p = self._player(view, name)
        if kind == "persuasion":
            return persuasion_power(p, p["sheet"]["skills"])
        ck = CHALLENGE_KINDS[kind]
        return contest_power(p, p["sheet"]["skills"], ck.attributes, ck.skill)

    def _score_persuade(self, view, action: Action) -> Tuple[float, str]:
        office, target = action.params["office"], action.params["target"] or None
        if not self._wants_office(view, office):
            return 0.0, ""
        p = self.persona
        d = self._grievance(view, office, target) if target else self._unrest(view, "leaders") * self._blame(view, office)
        if target is None:  # an empty seat needs filling now: no waiting for patience to run out
            d += TUNING.get("politics", {}).get("vacant_seat", 0.6) * self._blame(view, office)
        if target and d <= 0:
            return 0.0, ""  # no grievance, no campaign
        interfaces = self._office_interfaces(view, office)
        fit, stat = self._fit(view, self.name, interfaces)
        rival = self._fit(view, target, interfaces)[0] if target else 4.0
        mine = self._contest_power(view, self.name, "persuasion")
        score = (-2.6 + 2.0 * p.ambition + 3.0 * d - 0.6 * p.tradition + 2.0 * (mine - 1) + (fit - rival) / 4
                 + (0.4 if target is None else 0) + self._noise(0.6))
        if target is None and any(b.get("office") == office for b in view["ballots"]):
            score -= 2.0  # an election is already under way for the seat
        why = (f"believes they can talk the tribe round (persuasion {mine:.1f})" if target is None else
               f"wants {target}'s place as {office} and trusts their tongue (persuasion {mine:.1f})")
        return score, why

    def _kinds_for(self, view, office: str, name: str) -> List[str]:
        """Contests the office allows, 'skill' meaning one in `name`'s own work."""
        return kinds_allowed(view["offices"][office].get("challenges", []), self._player(view, name).get("trades", []))

    def _score_challenge(self, view, action: Action) -> Tuple[float, str]:
        office, holder, kind = action.params["office"], action.params["holder"], action.params["kind"]
        if not self._wants_office(view, office):
            return 0.0, ""
        d = self._grievance(view, office, holder)
        if d <= 0:
            return 0.0, ""  # no grievance, no challenge
        p = self.persona
        standing = 1 + CHALLENGE.get("defender_standing", 0)
        # The one challenged picks the contest, so expect the one they are best at.
        kinds = [kind] if kind else self._kinds_for(view, office, holder)
        if not kinds:
            return 0.0, ""
        edges = {k: (self._contest_power(view, self.name, k) - self._contest_power(view, holder, k) * standing)
                 / max(self._contest_power(view, holder, k) * standing, 0.1) for k in kinds}
        worst = min(edges, key=edges.get)
        edge = min(0.5, edges[worst])
        score = (-2.4 + 2.2 * p.ambition + 3.0 * d - 0.6 * p.tradition - 0.4 * p.compassion + 3.0 * edge
                 + self._noise(0.6))
        return score, (f"is fed up with {holder} as {office} and thinks they can win even at "
                       f"{CHALLENGE_KINDS[worst].name.lower()}")

    def _score_answer_challenge(self, view, action: Action) -> Tuple[float, str]:
        """Answer at once, choosing the contest where the challenger is weakest against us."""
        c = self._contest_view(view, action.params["contest"])
        kind = action.params["kind"]
        challenger = c["challenger"] if c else None
        mine = self._contest_power(view, self.name, kind)
        theirs = self._contest_power(view, challenger, kind) if challenger else 1.0
        return 30 + 5 * mine / max(theirs, 0.1), f"chooses {CHALLENGE_KINDS[kind].name.lower()}, where they are strongest"

    def _contest_view(self, view, key: str):
        return next((c for c in view.get("contests", []) if c["key"] == key), None)

    def _score_canvass(self, view, action: Action) -> Tuple[float, str]:
        c = self._contest_view(view, action.params["contest"])
        listener = action.params["listener"]
        meter = c["meters"].get(listener, 0) if c else 100
        if meter >= 90:
            return 0.0, ""
        return 3.5 + (70 - meter) / 40 + self._noise(0.4), f"needs {listener} on side ({meter:.0f}% persuaded)"

    def _score_rally(self, view, action: Action) -> Tuple[float, str]:
        c = self._contest_view(view, action.params["contest"])
        listener = action.params["listener"]
        meter = c["meters"].get(listener, 0) if c else 0
        if meter <= 10:
            return 0.0, ""
        return 3.0 + (meter - 30) / 40 + self._noise(0.4), f"wants to keep {listener} loyal ({meter:.0f}% swayed)"

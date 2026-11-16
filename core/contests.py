"""Contests: taking an office by persuasion or by challenge, instead of by election.

Rules and numbers come from data/rules/contests.json; which offices allow which contests comes from each
office's 'contested_by' in data/ages/<age>/governments. Two families:

  Persuasion  A campaign lasting some hours of the day-night cycle. Every member of the tribe gets a
              persuasion meter (0-100) that exists only while the campaign runs. It creeps up on its
              own as word spreads, jumps when the campaigner speaks to someone directly (canvass), and
              falls when the office holder under threat speaks to them (rally). At the end the average
              meter, plus a little chance, decides whether the tribe accepts the campaigner.
  Challenge   A direct contest with an office holder: oration (both speak; the crowd's meters swing),
              a ritual fight (momentum swings until someone yields; nobody dies, both may be hurt), or
              a skill contest from the challenger's line of work (largest animal, most food...).

The winner takes the office; whoever held it loses it. Everything here is plain data plus rules, so
an Unreal server can run the same contests and the HUD can draw the meters.
"""
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from utils import game_data
from utils.game_data import RULES_DIR
from utils.data_files import DATA_DIR, load_json, require
from utils.messages import Messages
from world.character import RULES as CHARACTER

# data/rules/contests.json as it is in every age; an age or a government may change any of it (use_rules below
# refills these tables in place).
BASE_RULES: Dict[str, Any] = load_json(RULES_DIR / "contests.json")
_data: Dict[str, Any] = BASE_RULES
SKILL_WEIGHT: float = 0.5
PERSUASION: Dict[str, Any] = {}
CHALLENGE: Dict[str, Any] = {}
LUCK: Dict[str, Any] = {}
CHALLENGE_KINDS: Dict[str, "ChallengeKind"] = {}
SPEAK: Dict[str, Any] = {}
DURING_CONTEST: Dict[str, Any] = {}
DEFENDER_CHOOSES: bool = False
_LUCK_DEFAULTS = {"speech": 0.3, "audience": 0.7, "duel": 0.8}


def _luck(what: str) -> float:
    """A random factor of 1 +/- contests.json 'luck.<what>'."""
    x = LUCK.get(what, _LUCK_DEFAULTS[what])
    return random.uniform(1 - x, 1 + x)


@dataclass
class ChallengeKind:
    key: str
    name: str
    icon: str
    description: str
    style: str                       # audience | duel | best | total
    life_hours: float
    attributes: Dict[str, float]
    skill: Optional[str] = None
    skill_contest: bool = False      # offered as 'skill': a contest in the challenger's own line of work
    unit: str = ""
    scale: float = 1.0
    finds_per_hour: float = 1.0
    swing_per_day: float = 5.0
    yield_at: float = 0.0
    injury: Dict[str, float] = field(default_factory=dict)
    practice: float = 0.2                       # skill points both contestants gain, win or lose
    also_practice: Dict[str, float] = field(default_factory=dict)


def _load_kinds() -> Dict[str, ChallengeKind]:
    kinds = {}
    for key, k in CHALLENGE.get("kinds", {}).items():
        where = f"contests.json challenge '{key}'"
        require(k.get("style") in ("audience", "duel", "best", "total"), where, "'style' must be audience, duel, best or total")
        for a in k.get("attributes", {}):
            require(a in CHARACTER.attributes, where, f"unknown attribute '{a}'")
        require(k.get("skill") in (None, *CHARACTER.skills), where, f"unknown skill '{k.get('skill')}'")
        kinds[key] = ChallengeKind(
            key=key, name=k.get("name", key), icon=k.get("icon", "•"), description=k.get("description", ""),
            style=k["style"], life_hours=float(k.get("life_hours", 1)), attributes=k.get("attributes", {}),
            skill=k.get("skill"), skill_contest=bool(k.get("skill_contest", False)), unit=k.get("unit", ""),
            scale=float(k.get("scale", 1)), finds_per_hour=float(k.get("finds_per_hour", 1)),
            swing_per_day=float(k.get("swing_per_day", 5)), yield_at=float(k.get("yield_at", 0)),
            injury=k.get("injury", {}), practice=float(k.get("practice", CHALLENGE.get("skill_practice", 0.2))),
            also_practice=k.get("also_practice", {}))
    return kinds


def use_rules(r: Dict[str, Any]):
    """Put these contest rules in force (utils/game_data.py RuleSet does this for the game being played)."""
    global _data, SKILL_WEIGHT, DEFENDER_CHOOSES
    _data = r
    SKILL_WEIGHT = r.get("skill_weight", 0.5)
    game_data.fill(PERSUASION, r.get("persuasion", {}))
    game_data.fill(CHALLENGE, r.get("challenge", {}))
    game_data.fill(LUCK, r.get("luck", {}))
    game_data.fill(CHALLENGE_KINDS, _load_kinds())
    for a in PERSUASION.get("attributes", {}):
        require(a in CHARACTER.attributes, "contests.json persuasion", f"unknown attribute '{a}'")
    DEFENDER_CHOOSES = CHALLENGE.get("chosen_by", "challenger") == "defender"
    game_data.fill(SPEAK, CHALLENGE.get("speak", {"life_hours": 0.25, "gain": 20, "practice": 0.04}))
    game_data.fill(DURING_CONTEST, game_data.public(CHALLENGE.get("during_contest", {})))


use_rules(BASE_RULES)
# Every kind of challenge of any age: what an office's 'contested_by' may name.
KNOWN_CHALLENGE_KINDS = {k for v in game_data.all_versions("contests", BASE_RULES)
                         for k in v.get("challenge", {}).get("kinds", {})}
game_data.switchable("contests", BASE_RULES, use_rules)


def power(attributes: Dict[str, float], skills: Dict[str, float], weights: Dict[str, float],
          skill: Optional[str]) -> float:
    """Strength in a contest, about 1.0 for an average untrained person: weighted attributes (5 = average)
    plus skill_weight per skill point, divided by 5."""
    total = sum(weights.values()) or 1.0
    base = sum(attributes.get(a, 5) * w for a, w in weights.items()) / total
    return (base + (SKILL_WEIGHT * skills.get(skill, 0) if skill else 0)) / 5


def persuasion_power(attributes, skills) -> float:
    return power(attributes, skills, PERSUASION.get("attributes", {"charisma": 1.0}), PERSUASION.get("skill"))


def trade_skills(gov, player) -> List[str]:
    """The skills of someone's line of work: their occupations' skills and their offices' skills.
    A 'skill' contest is held in one of these."""
    from core.occupations import OCCUPATIONS
    from core.society import office_spec
    skills = [OCCUPATIONS[o].skill for o in gov.occupations_of(player) if OCCUPATIONS[o].skill]
    skills += [office_spec(gov, o).get("skill") for o in gov.offices_of(player)]
    return [s for s in dict.fromkeys(skills) if s]


def kinds_allowed(office_challenges: List[str], trades: List[str]) -> List[str]:
    """The contests an office allows, expanding 'skill' to the contests in these trade skills."""
    trades = set(trades)
    kinds = []
    for k in office_challenges:
        if k == "skill":
            kinds += [key for key, ck in CHALLENGE_KINDS.items() if ck.skill_contest and ck.skill in trades]
        elif k in CHALLENGE_KINDS:
            kinds.append(k)
    return list(dict.fromkeys(kinds))


def kind_name(kind: str) -> str:
    if not kind:
        return "Challenge"
    return PERSUASION.get("name", "Persuasion") if kind == "persuasion" else CHALLENGE_KINDS[kind].name


@dataclass
class Contest:
    id: int
    kind: str                        # "persuasion" or a challenge kind key
    office: str
    challenger: str
    defender: Optional[str]          # the holder to be displaced (None = a vacant seat)
    started: int
    ends: int
    meters: Dict[str, float] = field(default_factory=dict)   # persuasion/audience: per listener; duel: momentum
    scores: Dict[str, float] = field(default_factory=dict)   # best/total: per contestant
    bias: Dict[str, float] = field(default_factory=dict)     # audience: each listener's leaning
    allowed: List[str] = field(default_factory=list)          # contests the defender may choose from
    floor: Dict[str, float] = field(default_factory=dict)     # persuasion: rallies never push a listener below this

    @property
    def key(self) -> str:
        return f"contest:{self.id}"

    @property
    def is_persuasion(self) -> bool:
        return self.kind == "persuasion"

    @property
    def label(self) -> str:
        if self.is_persuasion:
            whom = f", replacing {self.defender}" if self.defender else ""
            return f"{self.challenger} persuades the tribe to accept them as {self.office}{whom}"
        if self.awaiting_answer:
            return f"{self.challenger} challenges {self.defender} for {self.office}; {self.defender} chooses the contest"
        return f"{self.challenger} challenges {self.defender} for {self.office}: {kind_name(self.kind).lower()}"

    @property
    def awaiting_answer(self) -> bool:
        return self.kind == ""

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'Contest':
        return cls(**d)


class ContestManager:
    """Runs every contest for offices. The engine asks it for options, starts contests, ticks it once a
    calendar day, and lets it resolve contests when they end."""

    def __init__(self, game_state):
        self.game_state = game_state
        self.contests: List[Contest] = []
        self.next_id = 1
        self.cooldown_until: Dict[str, int] = {}   # challenger -> when they may contest again
        self.safe_until: Dict[str, int] = {}       # office holder -> when they may be contested again
        self.just_started: List[Contest] = []      # challenges that began this step (the engine pulls people in)

    # ------------------------------------------------------------------ #
    @property
    def gov(self):
        return self.game_state.government

    @property
    def now(self) -> int:
        return self.game_state.clock

    def _player(self, name: Optional[str]):
        return next((p for p in self.game_state.players if p.name == name), None) if name else None

    @staticmethod
    def _cycle_hours() -> float:
        from world.environment import CYCLE_HOURS
        return CYCLE_HOURS

    def _life_hours(self, h: float) -> int:
        return max(1, int(round(h * self._cycle_hours() / 24)))

    def contest(self, key_or_id) -> Optional[Contest]:
        cid = int(str(key_or_id).split(":")[-1])
        return next((c for c in self.contests if c.id == cid), None)

    def involving(self, name: str) -> Optional[Contest]:
        return next((c for c in self.contests if name in (c.challenger, c.defender)), None)

    def next_deadline(self) -> Optional[int]:
        return min((c.ends for c in self.contests), default=None)

    def audience(self, c: Contest) -> List[str]:
        """Who is being persuaded (or judges an audience contest): every member who has a voice,
        except the contestants."""
        return [p.name for p in self.game_state.players
                if p.name not in (c.challenger, c.defender) and self.gov.can_vote(p)]

    def _susceptibility(self, listener, office: str) -> float:
        r = PERSUASION.get("resistance", {})
        s = 1 - r.get("per_wisdom", 0.07) * (listener.attribute("wisdom") - 5)
        if office in self.gov.offices_of(listener):
            s *= r.get("same_office", 0.6)
        return max(r.get("min", 0.3), min(r.get("max", 1.6), s))

    # ------------------------------------------------------------------ #
    # What a player may start
    # ------------------------------------------------------------------ #
    def campaigning(self, name: str) -> Optional[Contest]:
        """The persuasion campaign or challenge this person has started for an office, if any."""
        return next((c for c in self.contests if c.challenger == name), None)

    def _standing_for_election(self, player) -> bool:
        """Nominated or on a ballot: such a person can't also campaign or challenge for an office."""
        vm = self.game_state.voting_manager
        return vm is not None and vm.standing_in(player) is not None

    def cooldown_hours_left(self, name: str) -> int:
        """Calendar hours before this person may start another campaign or challenge (after losing one)."""
        return max(0, self.cooldown_until.get(name, -1) - self.now)

    def protected_hours_left(self, office: str, holder) -> int:
        """Calendar hours before this holder may be contested for this office: new to it (grace), or
        resting after defending it."""
        return max(self.gov.grace_hours_left(office, holder), self.safe_until.get(holder.name, -1) - self.now, 0)

    def _free_to_contest(self, player) -> bool:
        return self.involving(player.name) is None and self.cooldown_until.get(player.name, -1) <= self.now

    def _targetable(self, holder_name: str) -> bool:
        return self.involving(holder_name) is None and self.safe_until.get(holder_name, -1) <= self.now

    def persuasion_targets(self, player) -> List[Tuple[str, Optional[str]]]:
        """(office, holder to replace or None for a vacant seat) this player may campaign for."""
        gov = self.gov
        if not self._free_to_contest(player):
            return []
        if self._standing_for_election(player):
            return []  # someone nominated (or on a ballot) can't also campaign by persuasion
        out = []
        for office in gov.government_type.offices.values():
            if not office.persuadable or not gov.can_contest_office(office.name, player)[0]:
                continue
            holders = gov.get_role_holders(office.name)
            if len(holders) < office.seats:
                if not any(c.office == office.name and c.defender is None for c in self.contests):
                    out.append((office.name, None))
            else:
                out += [(office.name, h.name) for h in holders
                        if self._targetable(h.name) and not gov.in_grace(office.name, h)]
        return out

    def challenge_kinds_for(self, player, office) -> List[str]:
        """Contests this office allows, with 'skill' meaning one in `player`'s own line of work."""
        return kinds_allowed(office.challenge_kinds, trade_skills(self.gov, player))

    def running_challenge(self, name: str) -> Optional[Contest]:
        """The challenge (begun, not awaiting an answer) this person is a contestant in, if any."""
        return next((c for c in self.contests if not c.is_persuasion and not c.awaiting_answer
                     and name in (c.challenger, c.defender)), None)

    def restriction(self, name: str) -> Optional[Dict[str, Any]]:
        """What a contestant may still do while their challenge runs: None if they are in no challenge,
        else {'contest', 'locked', 'may'} from 'during_contest' for the contest's style."""
        c = self.running_challenge(name)
        if c is None:
            return None
        rule = DURING_CONTEST.get(CHALLENGE_KINDS[c.kind].style, {"locked": True})
        return {"contest": c, "locked": bool(rule.get("locked")), "may": set(rule.get("may", []))}

    def is_locked_in(self, c: Contest) -> bool:
        """Do this contest's contestants do nothing else until it ends (a ritual fight)?"""
        if c.is_persuasion or c.awaiting_answer:
            return False
        return bool(DURING_CONTEST.get(CHALLENGE_KINDS[c.kind].style, {"locked": True}).get("locked"))

    def _speaks(self, c: Contest) -> bool:
        """Is this an audience challenge whose contestants may speak to listeners?"""
        if c.is_persuasion or c.awaiting_answer:
            return False
        ck = CHALLENGE_KINDS[c.kind]
        return ck.style == "audience" and "speak" in DURING_CONTEST.get(ck.style, {}).get("may", [])

    @staticmethod
    def _occupation_skill(name: str) -> Optional[str]:
        from core.occupations import OCCUPATIONS
        return OCCUPATIONS[name].skill if name in OCCUPATIONS else None

    def challenge_options(self, player) -> List[Tuple[str, str, str]]:
        """(office, holder, kind) this player may challenge. When the defender chooses the contest,
        kind is "" (the challenger only names whom they challenge)."""
        gov = self.gov
        if not self._free_to_contest(player) or self._standing_for_election(player):
            return []
        out = []
        for office in gov.government_type.offices.values():
            if not office.challenge_kinds or not gov.can_contest_office(office.name, player)[0]:
                continue
            for h in gov.get_role_holders(office.name):
                if not self._targetable(h.name) or gov.in_grace(office.name, h):
                    continue  # busy in a contest, resting after one, or new to the office
                if DEFENDER_CHOOSES:
                    if self.challenge_kinds_for(h, office):
                        out.append((office.name, h.name, ""))
                else:
                    out += [(office.name, h.name, k) for k in self.challenge_kinds_for(player, office)]
        return out

    def answer_options(self, player) -> List[Tuple[Contest, str]]:
        """(contest, kind) the challenged player may pick."""
        return [(c, k) for c in self.contests if c.awaiting_answer and c.defender == player.name for k in c.allowed]

    def canvass_options(self, player) -> List[Tuple[Contest, str]]:
        """Listeners the campaigner (or the challenger in an oration) may speak to, to win them over."""
        return [(c, n) for c in self.contests if (c.is_persuasion or self._speaks(c)) and c.challenger == player.name
                for n in c.meters if self._player(n)]

    def rally_options(self, player) -> List[Tuple[Contest, str]]:
        """Listeners the office holder under threat may speak to, to keep them on side."""
        return [(c, n) for c in self.contests if (c.is_persuasion or self._speaks(c)) and c.defender == player.name
                for n in c.meters if self._player(n)]

    def speech_hours(self, contest_key: str, kind: str) -> float:
        """Day-night hours one canvass or rally takes: a campaign conversation, or a speech in a contest."""
        c = self.contest(contest_key)
        if c is not None and not c.is_persuasion:
            return float(SPEAK.get("life_hours", 0.25))
        return float(PERSUASION.get(kind, {}).get("life_hours", 0.5))

    # ------------------------------------------------------------------ #
    # Starting and acting
    # ------------------------------------------------------------------ #
    def start_persuasion(self, player, office: str, target: Optional[str], reason: str = None) -> Optional[Contest]:
        if (office, target) not in self.persuasion_targets(player):
            Messages.add(f"{player.name} cannot start persuading for {office} now.", important=False)
            return None
        c = Contest(self.next_id, "persuasion", office, player.name, target, self.now,
                    self.now + self._life_hours(PERSUASION.get("life_hours", 6)))
        self.next_id += 1
        base = PERSUASION.get("start_meter", 15) + PERSUASION.get("start_per_charisma", 3) * (player.attribute("charisma") - 5)
        base += self._holder_failing(office, target)
        c.meters = {n: max(0.0, min(100.0, float(base + self._unrest(self._player(n))))) for n in self.audience(c)}
        c.floor = dict(c.meters)  # however hard the holder rallies, nobody ends up less persuaded than this
        self.contests.append(c)
        hours = PERSUASION.get("life_hours", 6)
        Messages.add(f"{c.label} ({hours:g} hours to win them over)", reason=reason)
        return c

    def start_challenge(self, player, office: str, holder: str, kind: str = "", reason: str = None) -> Optional[Contest]:
        if (office, holder, kind) not in self.challenge_options(player):
            Messages.add(f"{player.name} cannot challenge {holder} that way now.", important=False)
            return None
        if not kind:
            # The one challenged picks the contest, within a short time.
            defender = self._player(holder)
            allowed = self.challenge_kinds_for(defender, self.gov.government_type.offices[office])
            c = Contest(self.next_id, "", office, player.name, holder, self.now,
                        self.now + self._life_hours(CHALLENGE.get("answer_life_hours", 1)), allowed=allowed)
            self.next_id += 1
            self.contests.append(c)
            choices = ", ".join(CHALLENGE_KINDS[k].name.lower() for k in allowed)
            Messages.add(f"{player.name} challenges {holder} for the office of {office}! {holder} must choose the "
                         f"contest: {choices}", reason=reason)
            return c
        c = Contest(self.next_id, kind, office, player.name, holder, self.now, self.now)
        self.next_id += 1
        self.contests.append(c)
        self._begin(c, kind)
        return c

    def answer(self, player, contest_key: str, kind: str, reason: str = None) -> Optional[Contest]:
        c = self.contest(contest_key)
        if c is None or (c, kind) not in self.answer_options(player):
            Messages.add(f"{player.name} cannot choose that contest.", important=False)
            return None
        Messages.add(f"{player.name} chooses {CHALLENGE_KINDS[kind].name.lower()} to answer {c.challenger}'s challenge",
                     reason=reason)
        self._begin(c, kind)
        return c

    def _best_kind_for(self, name: str, c: Contest) -> str:
        """The contest the defender is strongest at, relative to the challenger."""
        def edge(kind):
            ck = CHALLENGE_KINDS[kind]
            d, a = self._player(name), self._player(c.challenger)
            pd = power(d.attributes, d.skills, ck.attributes, ck.skill) if d else 1
            pa = power(a.attributes, a.skills, ck.attributes, ck.skill) if a else 1
            return pd / max(pa, 0.01)
        return max(c.allowed, key=edge)

    def _begin(self, c: Contest, kind: str):
        """Start the contest proper: set its clock and meters, and tell the tribe."""
        ck = CHALLENGE_KINDS[kind]
        c.kind = kind
        c.started = self.now
        c.ends = self.now + self._life_hours(ck.life_hours)
        if ck.style == "audience":
            c.meters = {n: 50.0 for n in self.audience(c)}
            b = LUCK.get("listener_bias", 12)
            c.bias = {n: random.uniform(-b, b) for n in c.meters}
        elif ck.style == "duel":
            c.meters = {"momentum": 50.0}
        else:
            c.scores = {c.challenger: 0.0, c.defender: 0.0}
        self.just_started.append(c)
        Messages.add(f"The {ck.name.lower()} between {c.challenger} and {c.defender} for {c.office} begins. "
                     f"{ck.description}")

    def drain_started(self) -> List[Contest]:
        out, self.just_started = self.just_started, []
        return out

    def _unrest(self, listener) -> float:
        """Extra starting persuasion from a listener unhappy with the leaders (contests.json
        'persuasion.unrest'): each point of their 'meter' below 'neutral' adds 'per_point'."""
        u = PERSUASION.get("unrest", {})
        if listener is None:
            return 0.0
        sat = listener.satisfaction.get(u.get("meter", "leaders"), 50)
        return max(0.0, u.get("neutral", 60) - sat) * u.get("per_point", 0.7)

    def _holder_failing(self, office: str, holder: Optional[str]) -> float:
        """Extra starting persuasion for everyone when the holder does the office badly: each point of
        their office quality below 'holder_neutral' adds 'holder_per_point'."""
        from core.society import office_quality
        u = PERSUASION.get("unrest", {})
        h = self._player(holder) if holder else None
        if h is None:
            return 0.0
        return max(0.0, u.get("holder_neutral", 50) - office_quality(self.gov, office, h)) * u.get("holder_per_point", 0.4)

    def _loyalty(self, listener) -> float:
        """How much a holder's rally moves this listener: content people are easily kept, unhappy ones
        hardly ('persuasion.unrest': leaders meter / neutral, between 'rally_min' and 'rally_max')."""
        u = PERSUASION.get("unrest", {})
        if listener is None:
            return 1.0
        sat = listener.satisfaction.get(u.get("meter", "leaders"), 50)
        return max(u.get("rally_min", 0.3), min(u.get("rally_max", 1.2), sat / max(1, u.get("neutral", 60))))

    def standing(self) -> float:
        """How much weight the tribe gives the holder defending their office, from the tribe's average contentment
        with its leaders (contests.json 'defender_contentment'): a hated leader's rallies and speeches barely land."""
        from core.society import curve
        spec = _data.get("defender_contentment", {})
        people = [p for p in self.game_state.players if self.gov.can_vote(p)] or self.game_state.players
        if not people or not spec.get("curve"):
            return 1.0
        avg = sum(p.satisfaction.get(spec.get("meter", "leaders"), 50) for p in people) / len(people)
        return curve(spec["curve"], avg)

    def _pp(self, name: str) -> float:
        p = self._player(name)
        return persuasion_power(p.attributes, p.skills) if p else 1.0

    def canvass(self, player, contest_key: str, listener: str, reason: str = None) -> bool:
        c = self.contest(contest_key)
        if c is None or (c, listener) not in [(x, n) for x, n in self.canvass_options(player)]:
            Messages.add(f"{player.name} cannot speak to {listener} about that now.", important=False)
            return False
        lp = self._player(listener)
        if not c.is_persuasion:
            return self._speak(player, c, lp, +1, reason)
        gain = PERSUASION.get("canvass", {}).get("gain", 28) * self._pp(player.name) * \
            self._susceptibility(lp, c.office) * _luck("speech")
        gain = max(PERSUASION.get("canvass", {}).get("min_gain", 1), gain)  # always some effect, never less
        before = c.meters[listener]
        c.meters[listener] = min(100.0, before + gain)
        self._practice(player, PERSUASION.get("skill"), PERSUASION.get("practice_per_conversation", 0.05))
        Messages.add(f"{player.name} speaks with {listener} about becoming {c.office} "
                     f"(+{c.meters[listener] - before:.0f}: {listener} now {c.meters[listener]:.0f}% persuaded)",
                     important=False, reason=reason)
        return True

    def rally(self, player, contest_key: str, listener: str, reason: str = None) -> bool:
        c = self.contest(contest_key)
        if c is None or (c, listener) not in [(x, n) for x, n in self.rally_options(player)]:
            Messages.add(f"{player.name} cannot speak to {listener} about that now.", important=False)
            return False
        lp = self._player(listener)
        if not c.is_persuasion:
            return self._speak(player, c, lp, -1, reason)
        loss = PERSUASION.get("rally", {}).get("loss", 22) * self._pp(player.name) * \
            self._susceptibility(lp, c.office) * self._loyalty(lp) * self.standing() * _luck("speech")
        before = c.meters[listener]
        # The holder can undo the challenger's progress, never push someone below where they started.
        c.meters[listener] = max(c.floor.get(listener, 0.0), min(before, c.meters[listener] - loss))
        self._practice(player, PERSUASION.get("skill"), PERSUASION.get("practice_per_conversation", 0.05))
        Messages.add(f"{player.name} asks {listener} to stand by them as {c.office} "
                     f"(pulls them back {before - c.meters[listener]:.0f}: {listener} now "
                     f"{c.meters[listener]:.0f}% persuaded by {c.challenger})", important=False, reason=reason)
        return True

    def _speak(self, player, c: Contest, listener, direction: int, reason: str = None) -> bool:
        """A contestant in an audience challenge speaks to one listener: the challenger draws them
        toward themselves (direction +1), the defender pulls them back (-1). Strength is the contest's."""
        ck = CHALLENGE_KINDS[c.kind]
        mine = power(player.attributes, player.skills, ck.attributes, ck.skill)
        if player.name == c.defender:
            mine *= (1 + CHALLENGE.get("defender_standing", 0.0)) * self.standing()
        move = SPEAK.get("gain", 20) * mine * self._susceptibility(listener, c.office) * _luck("speech")
        before = c.meters[listener.name]
        c.meters[listener.name] = max(0.0, min(100.0, c.meters[listener.name] + direction * move))
        self._practice(player, ck.skill, SPEAK.get("practice", 0.04))
        towards = c.meters[listener.name] if player.name == c.challenger else 100 - c.meters[listener.name]
        Messages.add(f"{player.name} speaks to {listener.name} in the {ck.name.lower()} against "
                     f"{c.defender if player.name == c.challenger else c.challenger} "
                     f"(+{abs(c.meters[listener.name] - before):.0f}: {listener.name} now {towards:.0f}% for "
                     f"{player.name})", important=False, reason=reason)
        return True

    # ------------------------------------------------------------------ #
    # Time
    # ------------------------------------------------------------------ #
    def tick(self, life_days: float):
        """One calendar day of every running contest."""
        for c in self.contests:
            if c.awaiting_answer:
                continue
            if c.is_persuasion:
                self._tick_persuasion(c, life_days)
            else:
                getattr(self, f"_tick_{CHALLENGE_KINDS[c.kind].style}")(c, CHALLENGE_KINDS[c.kind], life_days)

    def _tick_persuasion(self, c: Contest, life_days: float):
        pc = self._pp(c.challenger)
        rate = PERSUASION.get("passive_per_day", 30)
        for name in list(c.meters):
            listener = self._player(name)
            if listener is None:
                continue
            c.meters[name] = min(100.0, c.meters[name] + rate * life_days * pc * self._susceptibility(listener, c.office))

    def _powers(self, c: Contest, ck: ChallengeKind) -> Tuple[float, float]:
        """Contest strength of challenger and defender; the defender has the standing of the office."""
        a, d = self._player(c.challenger), self._player(c.defender)
        standing = 1 + CHALLENGE.get("defender_standing", 0.0)
        return (power(a.attributes, a.skills, ck.attributes, ck.skill) if a else 0.5,
                power(d.attributes, d.skills, ck.attributes, ck.skill) * standing if d else 0.5)

    def _tick_audience(self, c: Contest, ck: ChallengeKind, life_days: float):
        pa, pd = self._powers(c, ck)
        pd *= self.standing()  # an oration before a tribe that is unhappy with its leaders
        for name in c.meters:
            listener = self._player(name)
            sa, sd = pa * _luck("audience"), pd * _luck("audience")
            pull = (sa - sd) / (sa + sd) + c.bias.get(name, 0) / 100
            s = self._susceptibility(listener, c.office) if listener else 1.0
            c.meters[name] = max(0.0, min(100.0, c.meters[name] + ck.swing_per_day * life_days * 100 * pull * s))

    def _tick_duel(self, c: Contest, ck: ChallengeKind, life_days: float):
        pa, pd = self._powers(c, ck)
        sa, sd = pa * _luck("duel"), pd * _luck("duel")
        m = c.meters["momentum"] + ck.swing_per_day * life_days * 100 * (sa - sd) / (sa + sd)
        c.meters["momentum"] = max(0.0, min(100.0, m))
        if ck.yield_at and (m <= ck.yield_at or m >= 100 - ck.yield_at):
            c.ends = self.now  # someone yields; the bout is over

    def _tick_finds(self, c: Contest, ck: ChallengeKind, life_days: float, best: bool):
        for name, p in zip((c.challenger, c.defender), self._powers(c, ck)):
            chance = ck.finds_per_hour * 24 * life_days * p
            if random.random() < chance:
                size = ck.scale * (0.5 + 0.5 * p) * random.uniform(*LUCK.get("find_size", {}).get("best" if best else "total", [0.2, 1.0] if best else [0.5, 1.5]))
                c.scores[name] = max(c.scores.get(name, 0), size) if best else c.scores.get(name, 0) + size

    def _tick_best(self, c, ck, life_days):
        self._tick_finds(c, ck, life_days, best=True)

    def _tick_total(self, c, ck, life_days):
        self._tick_finds(c, ck, life_days, best=False)

    # ------------------------------------------------------------------ #
    # Results
    # ------------------------------------------------------------------ #
    def process(self) -> List[Contest]:
        """Resolve every contest whose time is up. Returns the finished contests."""
        for c in [c for c in self.contests if c.awaiting_answer and c.ends <= self.now]:
            kind = self._best_kind_for(c.defender, c)
            Messages.add(f"{c.defender} did not answer in time; the contest will be {CHALLENGE_KINDS[kind].name.lower()}, "
                         f"where they are strongest")
            self._begin(c, kind)
        done = [c for c in self.contests if c.ends <= self.now and not c.awaiting_answer]
        for c in done:
            self.contests.remove(c)
            if c.is_persuasion:
                self._resolve_persuasion(c)
            else:
                self._resolve_challenge(c)
            rest = self._cycle_hours()
            won = c.office in self.gov.offices_of(self._player(c.challenger)) if self._player(c.challenger) else False
            if not won:  # only a loser waits before trying again; a winner holds the office
                self.cooldown_until[c.challenger] = self.now + int(rest * (PERSUASION if c.is_persuasion else CHALLENGE)
                                                                   .get("cooldown_life_days", 1))
            if c.defender and CHALLENGE.get("defender_rest_life_days", 0):
                self.safe_until[c.defender] = self.now + int(rest * CHALLENGE.get("defender_rest_life_days", 0))
        return done

    def forget(self, name: str):
        """Someone has died: a contest they were fighting is over (nobody wins it), and they no longer listen."""
        for c in list(self.contests):
            if name in (c.challenger, c.defender):
                self.contests.remove(c)
                Messages.add(f"The {kind_name(c.kind).lower()} for {c.office} ends: {name} has died")
                continue
            c.meters.pop(name, None)
            c.scores.pop(name, None)
            if hasattr(c, "floor"):
                c.floor.pop(name, None)

    def support(self, c: Contest) -> float:
        return sum(c.meters.values()) / len(c.meters) if c.meters else 0.0

    def _resolve_persuasion(self, c: Contest):
        winner = self._player(c.challenger)
        support = self.support(c)
        chance = PERSUASION.get("randomness", 8)
        verdict = support + random.uniform(-chance, chance)
        self._practice(winner, PERSUASION.get("skill"), PERSUASION.get("skill_practice", 0.3))
        if winner and verdict >= PERSUASION.get("success_at", 50):
            if self.gov.seize_office(c.office, winner, self._player(c.defender)):
                whom = f", replacing {c.defender}" if c.defender else ""
                Messages.add(f"{c.challenger} has won the tribe over ({support:.0f}% persuaded) and is now {c.office}{whom}")
            else:
                Messages.add(f"{c.challenger} won the tribe over ({support:.0f}% persuaded), but the office of "
                             f"{c.office} was filled meanwhile")
        else:
            stays = f"; {c.defender} remains {c.office}" if c.defender else ""
            Messages.add(f"{c.challenger} failed to win the tribe over for {c.office} ({support:.0f}% persuaded){stays}")

    def _resolve_challenge(self, c: Contest):
        ck = CHALLENGE_KINDS[c.kind]
        a, d = self._player(c.challenger), self._player(c.defender)
        if ck.style in ("audience", "duel"):
            score = self.support(c) if ck.style == "audience" else c.meters.get("momentum", 50)
            challenger_wins = score > 50
            detail = f"{score:.0f}% for {c.challenger}" if ck.style == "audience" else \
                ("yielded" if score <= ck.yield_at or score >= 100 - ck.yield_at else "on points")
        else:
            sa, sd = c.scores.get(c.challenger, 0), c.scores.get(c.defender, 0)
            challenger_wins = sa > sd
            fmt = (lambda x: f"{x:.0f} {ck.unit}") if ck.scale >= 5 else (lambda x: f"{x:.1f} {ck.unit}")
            detail = f"{c.challenger} {fmt(sa)} vs {c.defender} {fmt(sd)}"
        if ck.injury:
            for person, hurt in ((a, ck.injury.get("winner" if challenger_wins else "loser", 0)),
                                 (d, ck.injury.get("loser" if challenger_wins else "winner", 0))):
                if person:
                    person.health = max(min(person.health, ck.injury.get("min_health", 15)) if hurt else person.health,
                                        person.health - hurt)
        for person in (a, d):
            self._practice(person, ck.skill, ck.practice)
            for skill, amount in ck.also_practice.items():
                self._practice(person, skill, amount)
        if challenger_wins and a and self.gov.seize_office(c.office, a, d):
            Messages.add(f"{c.challenger} wins the {ck.name.lower()} against {c.defender} ({detail}) "
                         f"and is now {c.office}")
        elif challenger_wins:
            Messages.add(f"{c.challenger} wins the {ck.name.lower()} ({detail}) but cannot take the office of {c.office}")
        else:
            Messages.add(f"{c.defender} defends the office of {c.office} against {c.challenger} "
                         f"in the {ck.name.lower()} ({detail})")

    @staticmethod
    def _practice(person, skill: Optional[str], amount: float):
        if person and skill:
            person.train(skill, amount)

    # ------------------------------------------------------------------ #
    # Observation and saving
    # ------------------------------------------------------------------ #
    def observe(self, viewer) -> List[Dict[str, Any]]:
        out = []
        for c in self.contests:
            ck = None if (c.is_persuasion or c.awaiting_answer) else CHALLENGE_KINDS[c.kind]
            out.append({
                "key": c.key, "kind": c.kind, "name": kind_name(c.kind),
                "icon": "💬" if c.is_persuasion else ck.icon if ck else "⏳",
                "style": "persuasion" if c.is_persuasion else ck.style if ck else "pending", "office": c.office,
                "allowed": [{"kind": k, "name": CHALLENGE_KINDS[k].name} for k in c.allowed],
                "challenger": c.challenger, "defender": c.defender, "label": c.label,
                "started": c.started, "ends": c.ends, "hours_left": max(0, c.ends - self.now),
                "total_hours": max(1, c.ends - c.started),
                "meters": {k: round(v, 1) for k, v in c.meters.items()},
                "scores": {k: round(v, 1) for k, v in c.scores.items()},
                "unit": ck.unit if ck else "", "support": round(self.support(c), 1),
                "success_at": PERSUASION.get("success_at", 50) if c.is_persuasion else 50,
                "your_role": ("challenger" if viewer.name == c.challenger else "defender" if viewer.name == c.defender
                              else "audience" if viewer.name in c.meters else "watching"),
            })
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {"contests": [c.to_dict() for c in self.contests], "next_id": self.next_id,
                "cooldown_until": dict(self.cooldown_until), "safe_until": dict(self.safe_until)}

    def load_state(self, data: Dict[str, Any]):
        self.contests = [Contest.from_dict(d) for d in data.get("contests", [])]
        self.next_id = data.get("next_id", 1)
        self.cooldown_until = dict(data.get("cooldown_until", {}))
        longest = max(PERSUASION.get("cooldown_life_days", 1), CHALLENGE.get("cooldown_life_days", 1))
        cap = self.now + int(self._cycle_hours() * longest)  # older saves stored longer cooldowns
        self.cooldown_until = {n: min(t, cap) for n, t in self.cooldown_until.items()}
        rest_cap = self.now + int(self._cycle_hours() * CHALLENGE.get("defender_rest_life_days", 0))
        self.safe_until = {n: min(t, rest_cap) for n, t in data.get("safe_until", {}).items()}  # older saves: capped

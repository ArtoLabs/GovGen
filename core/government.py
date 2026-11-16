import random
from typing import List, Dict, Optional, Set, Tuple, Union

from innovations.innovation import InnovationPool, AGES, Age, reached_age_index
from core.rules import can_hold_office
from world.player import Player
from core.interfaces import RoleInterface, get_interface
from core.government_types import (
    GovernmentType, Office, Status, get_government_type, get_available_government_types, starting_government_type,
)
from utils.messages import Messages
from core.occupations import OCCUPATIONS, MAX_OCCUPATIONS_PER_PLAYER, OFFICE_IS_WORK, Occupation
from utils.dice import DiceBag
from utils.logging_config import logger
from core.game_state import GameState

from core.calendar import REFORM_COOLDOWN_HOURS, DAYS_PER_YEAR, _data as _time_data


class Government:
    """Who holds which office and status, under the current government type."""

    def __init__(self, game_state: GameState):
        self.game_state = game_state
        self.innovation_pool = InnovationPool()
        self.players: List[Player] = []
        self.government_type: GovernmentType = starting_government_type()
        self.assignments: Dict[str, List[Player]] = {name: [] for name in self.government_type.offices}
        self.statuses: Dict[str, List[Player]] = {name: [] for name in self.government_type.statuses}
        self.occupations: Dict[str, List[Player]] = {name: [] for name in OCCUPATIONS}  # survive reforms
        self.research_queue: List[str] = []
        self.dice_bag = DiceBag()
        self.age_index = 0
        self.last_reform_hour: Optional[int] = None
        self.took_office: Dict[str, Dict[str, int]] = {}  # name -> office -> when they took it (grace period)
        self.research_progress: float = 0  # points put into the innovation at the front of the queue
        # Set by the engine, which knows about items and work: is one of these tools at hand for this
        # player, and how much has this person been working lately (0-1)?
        self.tools_available = lambda tools, player: True
        self.work_activity = lambda name: 1.0
        # ...is this person working their own job right now (which job: 'Hunter', 'office:Elder'), how many
        # tools for their job do they carry (and does any such tool exist yet), and is the fire burning and
        # tended ('tended', 'untended' or 'out')? Contentment uses these (core/society.py).
        self.working_now = lambda name: None
        self.job_tools = lambda player: (0, False)
        self.fire_state = lambda: "out"
        self.supply_of = lambda need: None  # food (or water) points the tribe holds: camp store and packs
        self.appointed: Dict[str, str] = {}  # name -> the job a leader appointed them to ('Hunter', 'office:...')
        # name -> the office that appointed them to their occupation: they must keep it until that office (or
        # one above it, by 'authority') releases them or moves them, and nobody lower may change it.
        self.appointed_by: Dict[str, str] = {}
        # Someone was dismissed from a job ('dismissed') or moved to another ('reassigned'); the engine
        # makes them (and onlookers) resent it (data/society.json 'satisfaction.job_loss').
        self.on_job_loss = lambda player, how, job: None
        # Called when a leader appoints someone (from their old work, None if none, to the new): moving up or
        # down the hierarchy of work warms or sours them to the leaders (data/society.json 'job_rank').
        self.on_job_change = lambda player, old, new: None
        # Set by the engine (core/life.py): is this person old enough for 'work' or for 'politics' (voting,
        # office, leading, research)? Ages come from data/life.json.
        self.of_age = lambda player, what: True
        self.sick_count = lambda: 0  # how many people are ill now (core/life.py)
        # Set by the engine: a 'use' quality's level (society.json style 'use'), and the fading chunk an event (a
        # death) has taken out of a quality.
        self.quality_level = lambda key, start: start
        self.quality_shock = lambda key: 0.0

    def initialize(self):
        """Discover the first age's starting innovations. Offices are filled through play."""
        for name in AGES[0].starting_innovations:
            self.innovation_pool.discovered.add(name)
        self.age_index = reached_age_index(self.innovation_pool.discovered)

    def add_player(self, player: Player):
        self.players.append(player)

    def remove_player(self, player: Player):
        """Someone has died: they leave every office, status and occupation (seats fall vacant)."""
        for holders in [*self.assignments.values(), *self.statuses.values(), *self.occupations.values()]:
            while player in holders:
                holders.remove(player)
        for table in (self.took_office, self.appointed, self.appointed_by):
            table.pop(player.name, None)
        if player in self.players:
            self.players.remove(player)

    # ------------------------------------------------------------------ #
    # Lookups
    # ------------------------------------------------------------------ #
    @property
    def age(self) -> Age:
        return AGES[self.age_index]

    def is_unlocked(self, requires: List[str]) -> bool:
        return all(req in self.innovation_pool.discovered for req in requires)

    def get_role_holders(self, office_name: str) -> List[Player]:
        return self.assignments.get(office_name, [])

    def is_player_assigned(self, player_name: str, office_name: str) -> bool:
        return any(p.name == player_name for p in self.get_role_holders(office_name))

    def offices_of(self, player: Player) -> List[str]:
        return [name for name, holders in self.assignments.items() if player in holders]

    def statuses_of(self, player: Player) -> List[str]:
        return [name for name, holders in self.statuses.items() if player in holders]

    def has_effect(self, player: Player, effect: str) -> bool:
        return any(effect in self.government_type.statuses[name].effects for name in self.statuses_of(player))

    def can_vote(self, player: Player) -> bool:
        return not self.has_effect(player, "cannot_vote") and self.of_age(player, "politics")

    def _entry(self, name: str) -> Union[Office, Status, None]:
        return self.government_type.offices.get(name) or self.government_type.statuses.get(name)

    # ------------------------------------------------------------------ #
    # Electorates
    # ------------------------------------------------------------------ #
    def resolve_vote_method(self, spec: Dict) -> Optional[Tuple[str, Optional[str]]]:
        """The (method, council) actually in force for a vote spec, or None if nobody may vote."""
        if spec["method"] == "council_vote":
            council = spec["council"]
            if any(self.can_vote(p) for p in self.get_role_holders(council)):
                return "council_vote", council
            if spec.get("fallback") == "tribe_vote":
                return "tribe_vote", None
            return None
        return "tribe_vote", None

    def electorate(self, method: str, council: Optional[str], exclude: Optional[Player] = None) -> List[Player]:
        pool = self.players if method == "tribe_vote" else self.get_role_holders(council)
        return [p for p in pool if self.can_vote(p) and p is not exclude]

    # ------------------------------------------------------------------ #
    # Holding offices
    # ------------------------------------------------------------------ #
    def can_hold_office(self, office_name: str, player: Player, ignore_seat_limit: bool = False) -> Tuple[bool, List[str]]:
        return can_hold_office(self, office_name, player, ignore_seat_limit)

    def assign_office(self, office_name: str, player: Player, announce: bool = True) -> bool:
        ok, reasons = self.can_hold_office(office_name, player)
        logger.debug(f"Assign {office_name} to {player.name}: {ok} {reasons}")
        if not ok:
            Messages.add(f"{player.name} cannot become {office_name}: {'; '.join(reasons)}")
            return False
        self.assignments.setdefault(office_name, []).append(player)
        self.took_office.setdefault(player.name, {})[office_name] = self.game_state.clock
        if announce:
            Messages.add(f"{player.name} is now {office_name}")
        self._office_becomes_work(player, office_name)
        return True

    def _office_becomes_work(self, player: Player, office_name: str):
        """With 'office_is_work', an office is the holder's work: they give up any occupation."""
        if not OFFICE_IS_WORK:
            return
        for occ in self.occupations_of(player):
            self.occupations[occ].remove(player)
            Messages.add(f"{player.name} gives up the work of {occ} to serve as {office_name}")

    def grace_hours_left(self, office_name: str, player: Player) -> int:
        """Calendar hours before someone new to an office may be persuaded against, challenged or voted
        out (time.json 'office_grace_life_days')."""
        from world.environment import CYCLE_HOURS
        took = self.took_office.get(player.name, {}).get(office_name)
        if took is None:
            return 0
        return max(0, int(took + _time_data.get("office_grace_life_days", 1) * CYCLE_HOURS - self.game_state.clock))

    def in_grace(self, office_name: str, player: Player) -> bool:
        return self.grace_hours_left(office_name, player) > 0

    def resign(self, office_name: str, player: Player, reason: str = None) -> bool:
        if player not in self.assignments.get(office_name, []):
            Messages.add(f"{player.name} does not hold {office_name}.", important=False)
            return False
        self.assignments[office_name].remove(player)
        self.took_office.get(player.name, {}).pop(office_name, None)
        Messages.add(f"{player.name} resigns as {office_name}", reason=reason)
        return True

    def remove_office(self, office_name: str, player: Player, announce: bool = True) -> bool:
        if player in self.assignments.get(office_name, []):
            self.assignments[office_name].remove(player)
            if announce:
                Messages.add(f"{player.name} is no longer {office_name}")
            return True
        Messages.add(f"{player.name} does not hold {office_name}")
        return False

    # ------------------------------------------------------------------ #
    # Contests: taking an office by persuasion or challenge (core/contests.py)
    # ------------------------------------------------------------------ #
    def can_contest_office(self, office_name: str, player: Player) -> Tuple[bool, List[str]]:
        """May this player try to take the office by persuasion or challenge? (Seats and the
        one-office limit don't count: a winner displaces someone and gives up any other office.)"""
        office = self.government_type.offices.get(office_name)
        if office is None:
            return False, [f"'{office_name}' is not an office here"]
        if not self.is_unlocked(office.requires):
            return False, [f"'{office_name}' requires {', '.join(office.requires)}"]
        if self.has_effect(player, "cannot_hold_office"):
            return False, [f"{player.name} may not hold office"]
        if not self.of_age(player, "politics"):
            return False, [f"{player.name} is too young to hold office"]
        if player in self.get_role_holders(office_name):
            return False, [f"{player.name} already holds '{office_name}'"]
        return True, []

    def seize_office(self, office_name: str, winner: Player, displaced: Optional[Player] = None) -> bool:
        """The winner of a contest takes the office: the displaced holder loses it, and the winner gives
        up other offices if they may only hold one. Elections for a seat that is no longer vacant end."""
        office = self.government_type.offices.get(office_name)
        if office is None or not self.can_contest_office(office_name, winner)[0]:
            return False
        holders = self.get_role_holders(office_name)
        if displaced is not None and displaced in holders:
            self.remove_office(office_name, displaced, announce=False)
            Messages.add(f"{displaced.name} is no longer {office_name}")
        if len(self.get_role_holders(office_name)) >= office.seats:
            return False
        held = self.offices_of(winner)
        while held and len(held) >= self.government_type.max_offices_per_player:
            old = held.pop(0)
            self.remove_office(old, winner, announce=False)
            Messages.add(f"{winner.name} gives up the office of {old}")
        if not self.assign_office(office_name, winner, announce=False):
            return False
        vm = self.game_state.voting_manager
        if vm is not None:
            vm.cancel_unneeded_elections()
        return True

    # ------------------------------------------------------------------ #
    # Statuses
    # ------------------------------------------------------------------ #
    def grant_status(self, status_name: str, player: Player, announce: bool = True) -> bool:
        status = self.government_type.statuses.get(status_name)
        if status is None or not self.is_unlocked(status.requires):
            Messages.add(f"'{status_name}' is not available.")
            return False
        if player in self.statuses[status_name]:
            Messages.add(f"{player.name} is already {status_name}.")
            return False
        self.statuses[status_name].append(player)
        if "loses_office" in status.effects:
            for office_name in self.offices_of(player):
                self.remove_office(office_name, player, announce=False)
                Messages.add(f"{player.name} loses the office of {office_name}")
            for occ in self.occupations_of(player):
                self.occupations[occ].remove(player)
                Messages.add(f"{player.name} is no longer {occ}")
        if announce:
            Messages.add(f"{player.name} is now {status_name}")
        return True

    def revoke_status(self, status_name: str, player: Player, announce: bool = True) -> bool:
        if player not in self.statuses.get(status_name, []):
            Messages.add(f"{player.name} is not {status_name}.")
            return False
        self.statuses[status_name].remove(player)
        if announce:
            Messages.add(f"{player.name} is no longer {status_name}")
        return True

    # ------------------------------------------------------------------ #
    # Occupations: work held alongside offices
    # ------------------------------------------------------------------ #
    def occupations_of(self, player: Player) -> List[str]:
        return [name for name, holders in self.occupations.items() if player in holders]

    def jobs_of(self, player: Player) -> List[str]:
        """Everything that is this person's work: occupations by name, offices as 'office:<name>'."""
        return self.occupations_of(player) + [f"office:{o}" for o in self.offices_of(player)]

    def appointed_job(self, player: Player) -> Optional[str]:
        """The job a leader appointed this person to, if they still hold it (None if they chose their work,
        were chosen some other way, or have moved on)."""
        job = self.appointed.get(player.name)
        return job if job and job in self.jobs_of(player) else None

    # ------------------------------------------------------------------ #
    # The hierarchy of appointments (offices' 'authority' in data/governments)
    # ------------------------------------------------------------------ #
    def office_authority(self, office: str) -> float:
        o = self.government_type.offices.get(office)
        if o is None:
            return 0.0
        return float(o.authority) if o.authority is not None else float(o.points)

    def authority_of(self, player: Player) -> float:
        """The highest authority among the offices this player holds (0 with none)."""
        return max((self.office_authority(o) for o in self.offices_of(player)), default=0.0)

    def binding(self, player: Player) -> Optional[Tuple[str, str]]:
        """(occupation, office) if this person was appointed to the occupation they hold, else None."""
        office = self.appointed_by.get(player.name)
        job = self.appointed.get(player.name)
        if office and job in self.occupations_of(player):
            return job, office
        return None

    def may_change(self, appointer: Player, holder: Player) -> bool:
        """May `appointer` move, dismiss or release `holder`? Yes unless an office above theirs appointed them."""
        bound = self.binding(holder)
        return bound is None or self.authority_of(appointer) >= self.office_authority(bound[1])

    def _release(self, player: Player):
        self.appointed.pop(player.name, None)
        self.appointed_by.pop(player.name, None)

    def release(self, releaser: Player, holder: Player, reason: str = None) -> bool:
        """End an appointment: the holder keeps the work, but as their own choice (free to leave it)."""
        bound = self.binding(holder)
        if bound is None:
            Messages.add(f"{holder.name} is not under appointment.", important=False)
            return False
        if not self.offices_of(releaser) or not self.may_change(releaser, holder):
            Messages.add(f"{releaser.name} has no authority to release {holder.name} (appointed by the {bound[1]}).")
            return False
        self._release(holder)
        Messages.add(f"{releaser.name} released {holder.name} from their appointment as {bound[0]}", reason=reason)
        return True

    def releasable(self, releaser: Player) -> List[Player]:
        """People under appointment this player may release."""
        if not self.offices_of(releaser):
            return []
        return [p for p in self.players if p is not releaser and self.binding(p) and self.may_change(releaser, p)]

    def occupation_appointers(self, occ: Occupation) -> List[str]:
        """Offices of the current government whose holders may appoint to this occupation."""
        return [o for o in occ.appointed_by if o in self.government_type.offices]

    def occupation_is_open(self, occ: Occupation) -> bool:
        """May members take this work up themselves? Yes if it is open to volunteers, or if this form of
        government has no office that appoints to it. (A vacant appointing office means waiting for one.)"""
        return occ.volunteer or not self.occupation_appointers(occ)

    def can_take_occupation(self, name: str, player: Player, switching: bool = False,
                            appointer: Optional[Player] = None) -> Tuple[bool, List[str]]:
        """switching=True: the player would give up their current work for this (appointments do that).
        `appointer`: who is appointing; they may move someone out of work they themselves control."""
        occ = OCCUPATIONS.get(name)
        if occ is None:
            return False, [f"'{name}' is not an occupation"]
        missing = [r for r in occ.requires if r not in self.innovation_pool.discovered]
        if missing:
            return False, [f"'{name}' requires {', '.join(missing)}"]
        # (No tool needed to take the work up: without one they wait for one; see work.json 'auto_take_tools'.)
        if not self.of_age(player, "work"):
            return False, [f"{player.name} is too young to work"]
        if self.has_effect(player, "cannot_hold_office"):
            return False, [f"{player.name} has no place in the group's work"]
        holders = self.occupations[name]
        if player in holders:
            return False, [f"{player.name} is already {name}"]
        if OFFICE_IS_WORK and self.offices_of(player):
            return False, [f"{player.name} serves as {', '.join(self.offices_of(player))}; that is their work"]
        if occ.seats is not None and len(holders) >= occ.seats:
            return False, [f"all {occ.seats} {name} places are taken"]
        held = self.occupations_of(player)
        bound = self.binding(player)
        if bound and (appointer is None or not self.may_change(appointer, player)):
            return False, [f"{player.name} was appointed {bound[0]} by the {bound[1]} and must be released first"]
        if switching:
            pass  # an appointment replaces their current work
        elif len(held) >= MAX_OCCUPATIONS_PER_PLAYER:
            return False, [f"{player.name} is already {', '.join(held)}"]
        return True, []

    def volunteer_options(self, player: Player) -> List[str]:
        """Occupations this player could take up on their own right now."""
        return [n for n, occ in OCCUPATIONS.items()
                if self.occupation_is_open(occ) and self.can_take_occupation(n, player)[0]]

    def take_occupation(self, name: str, player: Player, reason: str = None) -> bool:
        ok, why = self.can_take_occupation(name, player)
        if not ok or not self.occupation_is_open(OCCUPATIONS[name]):
            Messages.add(f"{player.name} cannot become {name}: {'; '.join(why) or 'it is filled by appointment'}",
                         important=False)
            return False
        self.occupations[name].append(player)
        self._release(player)  # their own choice
        Messages.add(f"{player.name} takes up the work of {name}", important=False, reason=reason)
        return True

    def leave_occupation(self, name: str, player: Player, reason: str = None) -> bool:
        if player not in self.occupations.get(name, []):
            Messages.add(f"{player.name} is not {name}.", important=False)
            return False
        bound = self.binding(player)
        if bound and bound[0] == name:
            Messages.add(f"{player.name} was appointed {name} by the {bound[1]} and can't quit until released.",
                         important=False)
            return False
        self.occupations[name].remove(player)
        Messages.add(f"{player.name} gives up the work of {name}", important=False, reason=reason)
        return True

    # ------------------------------------------------------------------ #
    # Appointment: offices and statuses chosen by a single office holder
    # ------------------------------------------------------------------ #
    def _controls(self, player: Player, spec: Dict) -> bool:
        return spec["method"] == "appointment" and player in self.get_role_holders(spec["appointer"])

    def appointable(self, appointer: Player) -> List[str]:
        """Offices and statuses this player may fill or grant."""
        names = [o.name for o in self.government_type.offices.values()
                 if self._controls(appointer, o.selected_by) and self.is_unlocked(o.requires)]
        names += [s.name for s in self.government_type.statuses.values()
                  if self._controls(appointer, s.granted_by) and self.is_unlocked(s.requires)]
        names += [o.name for o in OCCUPATIONS.values() if self._appoints_occupation(appointer, o)
                  and self.is_unlocked(o.requires)]
        return names

    def _appoints_occupation(self, player: Player, occ: Occupation) -> bool:
        return any(player in self.get_role_holders(o) for o in self.occupation_appointers(occ))

    def dismissable(self, appointer: Player) -> List[str]:
        """Offices and statuses this player may remove someone from (and someone currently holds)."""
        names = [o.name for o in self.government_type.offices.values()
                 if self._controls(appointer, o.removed_by) and self.assignments.get(o.name)]
        names += [s.name for s in self.government_type.statuses.values()
                  if self._controls(appointer, s.revoked_by) and self.statuses.get(s.name)]
        names += [o.name for o in OCCUPATIONS.values()
                  if self._appoints_occupation(appointer, o) and self.occupations.get(o.name)]
        return names

    def appoint(self, appointer: Player, name: str, appointee: Player, reason: str = None) -> bool:
        if name not in self.appointable(appointer):
            Messages.add(f"{appointer.name} has no authority to appoint the {name}.")
            return False
        if appointee is appointer:
            Messages.add("You cannot appoint yourself.")
            return False
        if name in OCCUPATIONS:
            ok, why = self.can_take_occupation(name, appointee, switching=True, appointer=appointer)
            if not ok:
                Messages.add(f"{appointee.name} cannot become {name}: {'; '.join(why)}")
                return False
            before = self.jobs_of(appointee)
            previous = self.occupations_of(appointee)
            for old in previous:  # new work replaces the old
                self.occupations[old].remove(appointee)
            self.occupations[name].append(appointee)
            self.appointed[appointee.name] = name
            self.appointed_by[appointee.name] = max(
                [o for o in self.occupation_appointers(OCCUPATIONS[name]) if appointer in self.get_role_holders(o)],
                key=self.office_authority)
            was = f" (was {', '.join(previous)})" if previous else ""
            Messages.add(f"{appointer.name} made {appointee.name} a {name}{was}", reason=reason)
            if previous:
                self.on_job_loss(appointee, "reassigned", previous[0])
            self.on_job_change(appointee, before, name)
            return True
        if name in self.government_type.statuses:
            if self.grant_status(name, appointee, announce=False):
                Messages.add(f"{appointer.name} made {appointee.name} {name}", reason=reason)
                return True
            return False

        office = self.government_type.offices[name]
        holders = self.get_role_holders(name)
        before = self.jobs_of(appointee)
        deposed = None
        if len(holders) >= office.seats:
            if office.seats > 1:
                Messages.add(f"All {name} seats are filled; dismiss someone first.")
                return False
            # A one-seat office changes hands: the incumbent is replaced, not joined.
            ok, reasons = self.can_hold_office(name, appointee, ignore_seat_limit=True)
            if not ok:
                Messages.add(f"{appointee.name} cannot become {name}: {'; '.join(reasons)}")
                return False
            deposed = holders[0]
            self.remove_office(name, deposed, announce=False)
        if not self.assign_office(name, appointee, announce=False):
            if deposed:
                self.assignments[name].append(deposed)
            return False
        self.appointed[appointee.name] = f"office:{name}"
        self.on_job_change(appointee, before, f"office:{name}")
        if deposed:
            Messages.add(f"{appointer.name} replaced {deposed.name} with {appointee.name} as {name}", reason=reason)
        else:
            Messages.add(f"{appointer.name} appointed {appointee.name} as {name}", reason=reason)
        return True

    def dismiss(self, dismisser: Player, name: str, holder: Player, reason: str = None) -> bool:
        if name not in self.dismissable(dismisser):
            Messages.add(f"{dismisser.name} has no authority to remove anyone from {name}.")
            return False
        if name in OCCUPATIONS:
            if not self.may_change(dismisser, holder):
                Messages.add(f"{dismisser.name} can't dismiss {holder.name}: the {self.binding(holder)[1]} "
                             f"appointed them.")
                return False
            removed = holder in self.occupations[name]
            if removed:
                self.occupations[name].remove(holder)
                self._release(holder)
        elif name in self.government_type.statuses:
            removed = self.revoke_status(name, holder, announce=False)
        else:
            removed = self.remove_office(name, holder, announce=False)
        if removed:
            Messages.add(f"{dismisser.name} removed {holder.name} from {name}", reason=reason)
            if name in OCCUPATIONS:
                self.on_job_loss(holder, "dismissed", name)
        return removed

    # ------------------------------------------------------------------ #
    # Automatic selection methods
    # ------------------------------------------------------------------ #
    def _vacant(self, office: Office) -> bool:
        return self.is_unlocked(office.requires) and len(self.get_role_holders(office.name)) < office.seats

    def _eligible_for(self, office_name: str) -> List[Player]:
        return [p for p in self.players if self.can_hold_office(office_name, p)[0]]

    def process_divine_signs(self):
        """Once a year, each vacant divine_sign office has `chance` of being filled by a random eligible member."""
        for office in self.government_type.offices.values():
            if office.selected_by["method"] != "divine_sign" or not self._vacant(office):
                continue
            roll, _ = self.dice_bag.roll("d100")
            if roll > office.selected_by.get("chance", 0.05) * 100:
                continue
            candidates = self._eligible_for(office.name)
            if candidates:
                chosen = random.choice(candidates)
                self.assign_office(office.name, chosen, announce=False)
                Messages.add(f"A sign is seen: {chosen.name} is chosen as {office.name}")

    def fill_by_seniority(self):
        for office in self.government_type.offices.values():
            while office.selected_by["method"] == "seniority" and self._vacant(office):
                candidates = self._eligible_for(office.name)
                if not candidates:
                    break
                eldest = max(candidates, key=lambda p: p.age)
                self.assign_office(office.name, eldest, announce=False)
                Messages.add(f"{eldest.name}, the eldest eligible member, becomes {office.name}")

    # ------------------------------------------------------------------ #
    # Interfaces and innovation points
    # ------------------------------------------------------------------ #
    def research_roles(self) -> Dict[str, List[str]]:
        """Who may research each kind of innovation (its interface) in this government: 'everyone' (member
        interfaces), its offices and its occupations, from the data."""
        roles: Dict[str, List[str]] = {}
        for key in self.government_type.member_interfaces:
            roles.setdefault(key, []).append("everyone")
        for office in self.government_type.offices.values():
            for key in office.interfaces:
                roles.setdefault(key, []).append(office.name)
        for occ in OCCUPATIONS.values():
            for key in occ.interfaces:
                roles.setdefault(key, []).append(occ.name)
        return roles

    def player_interface_keys(self, player: Player) -> List[str]:
        keys: List[str] = []
        if not self.of_age(player, "politics"):
            return keys  # children have no say in research or orders
        if not self.has_effect(player, "no_member_interfaces"):
            keys += self.government_type.member_interfaces
        for office_name in self.offices_of(player):
            keys += self.government_type.offices[office_name].interfaces
        for occ in self.occupations_of(player):
            keys += OCCUPATIONS[occ].interfaces
        return list(dict.fromkeys(keys))

    def get_player_interfaces(self, player: Player) -> List[RoleInterface]:
        return [i for i in (get_interface(k) for k in self.player_interface_keys(player)) if i]

    def active_interfaces(self) -> Set[str]:
        return {key for p in self.players for key in self.player_interface_keys(p)}

    def annual_points(self) -> int:
        """Points per year: each office held is worth its 'points', plus 'member_points' per member."""
        gov = self.government_type
        total = sum(gov.offices[name].points * len(holders) for name, holders in self.assignments.items())
        total += gov.member_points * sum(1 for p in self.players if not self.has_effect(p, "no_member_interfaces")
                                         and self.of_age(p, "politics"))
        total += sum(OCCUPATIONS[name].points * len(holders) for name, holders in self.occupations.items())
        return total

    def daily_income(self) -> float:
        """Points flow in continuously: each day brings 1/days_per_year of the annual rate."""
        return self.annual_points() / DAYS_PER_YEAR

    def discover_innovation(self, innovation_name: str) -> bool:
        return self.innovation_pool.discover(innovation_name)

    # ------------------------------------------------------------------ #
    # Ages and reform
    # ------------------------------------------------------------------ #
    def next_age_progress(self) -> Optional[Tuple[Age, List[Tuple[str, bool]]]]:
        """The next age and, for each innovation it needs, whether it has been discovered."""
        if self.age_index + 1 >= len(AGES):
            return None
        nxt = AGES[self.age_index + 1]
        return nxt, [(name, name in self.innovation_pool.discovered) for name in nxt.requires]

    def check_new_age(self):
        new_index = reached_age_index(self.innovation_pool.discovered)
        while self.age_index < new_index:
            self.age_index += 1
            Messages.add(f"*** The society enters the {self.age.name}! {self.age.description} ***")
        self.evolve_government()

    def arrival_government(self) -> Optional[GovernmentType]:
        """The government the society grows into in its current age (ages.json 'government_on_arrival'):
        the first whose research is done, else the last one. None if the age has no such list."""
        discovered = self.innovation_pool.discovered
        forms = [get_government_type(k) for k in self.age.government_on_arrival]
        for g in forms:
            if g and all(r in discovered for r in g.requires):
                return g
        return forms[-1] if forms else None  # the last one is what a society becomes without the others

    def evolve_government(self) -> bool:
        """Entering a new age changes the government by itself: no vote, no decree. Office holders carry
        over into the new offices; the rest start empty."""
        if self.government_type.age_index >= self.age_index:
            return False
        new = self.arrival_government()
        if new is None:
            return False
        return self._change_government(new, f"The society has grown into a {new.name} with the {self.age.name}.",
                                       reason="a new age")

    def available_reforms(self) -> List[GovernmentType]:
        """Other forms of government of the current age the society could adopt (a new age brings its own
        government by itself, see evolve_government)."""
        current = self.government_type
        return [g for g in get_available_government_types(self.innovation_pool.discovered)
                if g.key != current.key and g.age_index == current.age_index]

    def reform_cooldown_left(self) -> int:
        """Game hours until another reform may be proposed."""
        if self.last_reform_hour is None:
            return 0
        return max(0, self.last_reform_hour + REFORM_COOLDOWN_HOURS - self.game_state.clock)

    def reform_vote_method(self) -> Optional[Tuple[str, Optional[str]]]:
        """(method, council) used when a reform is put to a vote, or None if it is by decree."""
        spec = self.government_type.reformed_by
        if spec["method"] == "appointment":
            if self.get_role_holders(spec["appointer"]):
                return None
            spec = {"method": "tribe_vote"}  # nobody to decree: the members decide
        return self.resolve_vote_method(spec)

    def reform_mode(self, player: Player) -> Optional[str]:
        """'decree' if this player may reform alone, 'vote' if they may call a reform vote, else None."""
        if not self.available_reforms() or self.reform_cooldown_left():
            return None
        spec = self.government_type.reformed_by
        if spec["method"] == "appointment" and self.get_role_holders(spec["appointer"]):
            return "decree" if player in self.get_role_holders(spec["appointer"]) else None
        resolved = self.reform_vote_method()
        voting = self.game_state.voting_manager
        if voting and any(getattr(v, "kind", None) == "reform" for v in voting.active_votes):
            return None  # one reform vote at a time
        return "vote" if resolved and player in self.electorate(*resolved) else None

    def can_reform(self, player: Player) -> bool:
        return self.reform_mode(player) is not None

    def _carry_target(self, new: GovernmentType, old_office: str) -> Optional[str]:
        return new.carry_over.get(old_office, old_office if old_office in new.offices else None)

    def preview_reform(self, government_key: str) -> Dict[str, Optional[str]]:
        """Office each current office holder would have after reforming into `government_key` (None = loses it)."""
        new = get_government_type(government_key)
        result: Dict[str, Optional[str]] = {}
        filled: Dict[str, int] = {}
        for old_office, holders in self.assignments.items():
            target = self._carry_target(new, old_office)
            for player in holders:
                if target and filled.get(target, 0) < new.offices[target].seats:
                    filled[target] = filled.get(target, 0) + 1
                    result[player.name] = target
                else:
                    result[player.name] = None
        return result

    def reform(self, government_key: str, decreed_by: Optional[Player] = None, reason: str = None) -> bool:
        """Change government type, carrying office holders over where the new type says so."""
        new = get_government_type(government_key)
        if not new or new.key not in {g.key for g in self.available_reforms()}:
            return False
        how = f" by decree of {decreed_by.name}" if decreed_by else ""
        return self._change_government(new, f"The society reforms from {self.government_type.name} into a "
                                            f"{new.name}{how}.", reason=reason)

    def _change_government(self, new: GovernmentType, announce: str, reason: str = None) -> bool:
        old_assignments, old_statuses = self.assignments, self.statuses
        self.government_type = new
        self.assignments = {name: [] for name in new.offices}
        self.statuses = {name: list(old_statuses.get(name, [])) for name in new.statuses}
        self.last_reform_hour = self.game_state.clock
        # Appointments carry over with their offices (the Clan Leader's become the Chieftain's); an
        # office that has no successor leaves its appointees free.
        self.appointed_by = {n: self._carry_target(new, o) for n, o in self.appointed_by.items()
                             if self._carry_target(new, o)}
        Messages.add(announce, reason=reason)
        for old_office, holders in old_assignments.items():
            target = self._carry_target(new, old_office)
            for player in holders:
                if target and self.assign_office(target, player, announce=False):
                    Messages.add(f"{player.name}: {old_office} -> {target}" if target != old_office
                                 else f"{player.name} remains {target}")
                else:
                    Messages.add(f"{player.name} loses the office of {old_office}")
        if self.game_state.voting_manager:
            # Elections in progress were for the old offices; open those of the new government.
            self.game_state.voting_manager.clear()
            self.game_state.voting_manager.initiate_votes()
        return True

    # ------------------------------------------------------------------ #
    # Saving
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict:
        names = lambda people: [p.name for p in people]
        return {
            "government_type": self.government_type.key,
            "assignments": {office: names(holders) for office, holders in self.assignments.items()},
            "statuses": {status: names(holders) for status, holders in self.statuses.items()},
            "occupations": {occ: names(holders) for occ, holders in self.occupations.items() if holders},
            "discovered": sorted(self.innovation_pool.discovered),
            "points": self.innovation_pool.points,
            "research_queue": list(self.research_queue),
            "research_progress": self.research_progress,
            "age_index": self.age_index,
            "last_reform_hour": self.last_reform_hour,
            "took_office": {n: dict(o) for n, o in self.took_office.items()},
            "appointed": dict(self.appointed),
            "appointed_by": dict(self.appointed_by),
        }

    def load_state(self, data: Dict, player):
        gov_type = get_government_type(data["government_type"])
        if gov_type is None:
            raise ValueError(f"Saved government type '{data['government_type']}' no longer exists in data/governments")
        self.government_type = gov_type
        self.assignments = {o: [player(n) for n in data["assignments"].get(o, [])] for o in gov_type.offices}
        self.statuses = {s: [player(n) for n in data["statuses"].get(s, [])] for s in gov_type.statuses}
        saved = data.get("occupations", {})
        self.occupations = {o: [player(n) for n in saved.get(o, [])] for o in OCCUPATIONS}
        if OFFICE_IS_WORK:  # older saves let office holders keep an occupation too
            for occ, holders in self.occupations.items():
                holders[:] = [p for p in holders if not self.offices_of(p)]
        self.innovation_pool.discovered = set(data["discovered"])
        self.innovation_pool.points = data["points"]
        self.research_queue = list(data["research_queue"])
        self.research_progress = data["research_progress"]
        self.age_index = data["age_index"]
        self.last_reform_hour = data["last_reform_hour"]
        self.took_office = {n: dict(o) for n, o in data.get("took_office", {}).items()}
        self.appointed = dict(data.get("appointed", {}))
        self.appointed_by = dict(data.get("appointed_by", {}))

    # Kept for older callers.
    def set_government_type(self, government_type_name: str) -> bool:
        return self.reform(government_type_name)

    def __repr__(self):
        return (f"<Government Type: {self.government_type.name}, Age: {self.age.name}, Players: {len(self.players)}, "
                f"Innovations: {len(self.innovation_pool.discovered)}, Points: {self.innovation_pool.points}>")

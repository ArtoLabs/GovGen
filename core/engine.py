"""The headless game engine: rules, state and the game clock. No input, printing or real-time waiting.

Time: the clock counts game hours (see core/calendar.py). Each player is busy until some moment;
actions take game time. The engine always moves to whatever happens next — a scheduled event
(the daily tick, which also starts seasons and years), a ballot deadline, or a player becoming
free to act — and events at the same moment come first.

Controllers talk to it through:
    observe(player)        -> what that player can see (plain JSON-friendly data)
    legal_actions(player)  -> what that player may do now (only the player whose moment it is)
    apply(player, action)  -> do it; the player is then busy for the action's duration
The game loop (core/game.py) calls peek_next_time() / step() to move time forward.

Real-time players (a human at the HUD) don't hold up the clock while they think: when one becomes
free the loop parks them (park(player)) and time keeps moving; whenever they choose, act_now()
applies their action at the current moment.
"""
import heapq
import random
from typing import Any, Dict, List, Optional, Set, Tuple

from core.actions import Action
from core.calendar import _data as _time_data
from core.calendar import (ACTION_HOURS, MOTION_HOURS, DAYS_PER_YEAR, WAIT_DAYS, HOURS_PER_DAY, HOURS_PER_YEAR, DAYS_PER_SEASON,
                           day_of_year, days_until, format_date, format_duration, season_of, year_of)
from core.game_state import GameState
from core.government import Government
from core.government_types import describe_method
from core.interfaces import initialize_interfaces, get_interface, unlock_note
from core.voting import Motion, VotingSystem
from core.voting_manager import VotingManager
from innovations.innovation_manager import InnovationManager
from utils.messages import Messages
from core.occupations import OCCUPATIONS
from core.contests import CHALLENGE, CHALLENGE_KINDS, DURING_CONTEST, PERSUASION, ContestManager, kind_name, trade_skills
from core import society
from core.possessions import QUICK_ACTIONS, Possessions
from core import work as WORK
from core.life import Life
from world.items import ITEMS, describe
from world import environment
from world.character import RULES as CHARACTER
from world.player import Player, load_players

CALL_VOTE_LABELS = {
    "remove_office": "Remove {target} as {subject}",
    "grant_status": "Make {target} {subject}",
    "revoke_status": "Lift {target}'s {subject} status",
}


class GameEngine:
    def __init__(self, players: Optional[List[Player]] = None):
        self.players: List[Player] = list(players or load_players())  # fresh people for every game
        self.game_state = GameState(players=self.players)
        self.government = Government(self.game_state)
        self.game_state.government = self.government
        self.game_state.voting_manager = VotingManager(self.game_state)
        self.innovation_manager = InnovationManager(self.government)
        for player in self.players:
            self.government.add_player(player)
        self.government.initialize()
        initialize_interfaces(self.government)
        self.contests = ContestManager(self.game_state)  # persuasion and challenges for offices
        self.game_state.contests = self.contests
        self.qualities: Dict[str, Dict[str, Any]] = {}  # society qualities, recomputed daily (core/society.py)
        society.init_satisfaction(self.players)
        self.possessions = Possessions(self)  # inventories in use, the camp store, trade offers
        self.fire_until: int = 0  # the communal fire burns until then (core/work.py: the Firekeeper feeds it wood)
        self.last_worked: Dict[str, int] = {p.name: 0 for p in self.players}  # when each last finished some work
        self.meals: Dict[str, float] = {}  # name -> how full a meal they are eating (share of a full meal)
        self.aside_checked: Dict[str, int] = {}  # when each busy NPC last considered politics on the side
        self.aside_looked: Dict[str, int] = {}
        self.talk_free_at: Dict[str, int] = {}   # a talk done on the side: no other talk until then
        self.talk_what: Dict[str, str] = {}      # what that talk is ('winning over Bob')   # when it was last seen whether anything waits on them
        # Good places Scouts found (or gardeners made), oldest first: {'id', 'kind', 'by', 'loads', 'total',
        # 'found', 'until'}; and the last few used up or lost, for the Found places panel (work.json 'sites').
        self.sites: List[Dict[str, Any]] = []
        self.spent_sites: List[Dict[str, Any]] = []
        self.next_site_id = 1
        self.government.tools_available = lambda tools, player: self.possessions.find_tool(player, tools) is not None
        self.government.work_activity = self.work_activity
        self.government.working_now = self.working_now
        self.government.job_tools = self.job_tools
        self.government.fire_state = self.fire_state
        self.government.supply_of = self.possessions.supply
        self.government.on_job_loss = self._job_loss
        self.government.on_job_change = self._job_change
        self.life = Life(self)  # illness, healing, death, birth and childhood (core/life.py, data/life.json)
        self.government.of_age = self.life.of_age
        self.government.sick_count = lambda: sum(1 for p in self.players if p.illness)
        self.quality_levels: Dict[str, float] = {}  # society.json style 'use' qualities (Fire): raised by use
        self.quality_shocks: Dict[str, float] = {}  # chunks events (a death) took out of qualities, fading back
        self.government.quality_level = lambda key, start: self.quality_levels.get(key, start)
        self.government.quality_shock = lambda key: self.quality_shocks.get(key, 0.0)
        self.free_at: Dict[str, int] = {p.name: 0 for p in self.players}  # when each player can act next
        self.events: List[Tuple[int, int, str, Dict[str, Any]]] = []      # heap of (time, seq, kind, data)
        self._seq = 0
        self.acting: Optional[Player] = None
        self.idle: Set[str] = set()  # free real-time players: they act whenever they like (not saved)
        self.last_action: Dict[str, Dict[str, Any]] = {}  # name -> latest action log entry
        self.last_deeds: Dict[str, Dict[str, Any]] = {}  # name -> latest action that wasn't resting
        self.resting: Set[str] = set()  # players whose current action is "wait" (they can be woken)
        self._ballot_stages: Set[Tuple[str, str]] = set()  # (ballot key, stage) already announced
        self.started = False
        self.action_log: List[Dict[str, Any]] = []
        Messages.clock = lambda: self.clock

    # ------------------------------------------------------------------ #
    @property
    def voting(self) -> VotingManager:
        return self.game_state.voting_manager

    @property
    def clock(self) -> int:
        return self.game_state.clock

    @property
    def year(self) -> int:
        return self.game_state.current_year

    def player(self, name: str) -> Optional[Player]:
        return next((p for p in self.players if p.name == name), None)

    def start(self):
        """Begin a new game at Year 0, Spring day 1."""
        Messages.add("Welcome to Government Simulation!")
        Messages.add(f"Players: {', '.join(p.name for p in self.players)}")
        Messages.add(f"-- {format_date(self.clock)} - {self.government.age.name} --", header=True)
        self.schedule(HOURS_PER_DAY, "day")
        self.fire_until = self.clock + environment.life_hours_to_calendar(WORK.FIRE.get("start_life_hours", 8))
        self._settle()
        self.started = True

    # ------------------------------------------------------------------ #
    # Time
    # ------------------------------------------------------------------ #
    def schedule(self, at: int, kind: str, data: Optional[Dict[str, Any]] = None):
        self._seq += 1
        heapq.heappush(self.events, (at, self._seq, kind, data or {}))

    def next_actor(self) -> Optional[Player]:
        """The player who becomes free soonest (ties go to the earlier player in players.json).
        Parked real-time players are skipped; None if every player is parked."""
        waiting = [p for p in self.players if p.name not in self.idle]
        if not waiting:
            return None
        return min(waiting, key=lambda p: (self.free_at[p.name], self.players.index(p)))

    def is_free(self, player: Player) -> bool:
        """May this player act right now (it is their moment, or they are parked)?"""
        return player is self.acting or player.name in self.idle

    def _next_event_time(self) -> Optional[int]:
        times = [t for t in (self.events[0][0] if self.events else None, self.voting.next_deadline(),
                             self.contests.next_deadline()) if t is not None]
        return min(times) if times else None

    def peek_next_time(self) -> int:
        """When the next thing (event or player action) will happen."""
        actor = self.next_actor()
        times = [t for t in (self._next_event_time(), self.free_at[actor.name] if actor else None) if t is not None]
        return min(times) if times else self.clock

    def step(self) -> Optional[Player]:
        """Move time to the next thing that happens. Process due events and return None, or return
        the player who is now free to act (they stay the actor until they apply an action)."""
        if self.acting:
            return self.acting
        actor = self.next_actor()
        event_time = self._next_event_time()
        if actor is None or (event_time is not None and event_time <= self.free_at[actor.name]):
            if event_time is None:
                return None
            self.game_state.clock = max(self.clock, event_time)
            self._process_due()
            return None
        self.game_state.clock = max(self.clock, self.free_at[actor.name])
        self.acting = actor
        return actor

    def park(self, player: Player):
        """The player now free to act decides in real time: let the clock run on without them."""
        if player is self.acting:
            self.acting = None
        self.idle.add(player.name)

    def advance_clock(self, hours: float):
        """Move the clock forward without passing anything that is due (used while real-time
        players think, so their actions land at the right moment)."""
        self.game_state.clock = max(self.clock, min(int(self.clock + hours), self.peek_next_time()))

    def act_now(self, player: Player, action: Action, reason: Optional[str] = None) -> bool:
        """A parked real-time player acts at the current moment. If the action fails they stay free.
        A busy player may only 'stop' (wake up, get up) and handle items (quick actions)."""
        if action.type == "stop":
            return self.interrupt(player)
        if action.type in QUICK_ACTIONS:
            return self.quick(player, action, reason)
        if player.name not in self.idle and self.can_act_aside(player):
            return self.act_aside(player, action, reason)
        if player.name not in self.idle or self.acting is not None:
            Messages.add(f"{player.name} is busy and cannot act yet.", important=False)
            return False
        self.idle.discard(player.name)
        self.acting = player
        if self.apply(player, action, reason):
            return True
        self.acting = None
        self.idle.add(player.name)
        return False

    def quick(self, player: Player, action: Action, reason: Optional[str] = None) -> bool:
        """A quick action (handling items: core/possessions.py). Takes no time and needs no moment to act."""
        ok = self.possessions.act(player, action, reason)
        if ok:
            self.action_log.append({"time": self.clock, "date": format_date(self.clock), "player": player.name,
                                    **action.to_dict(), "reason": reason})
        return ok

    def _process_due(self):
        while self.events and self.events[0][0] <= self.clock:
            _, _, kind, data = heapq.heappop(self.events)
            getattr(self, f"_event_{kind}")(data)
        for contest in self.contests.process():  # persuasion campaigns and challenges whose time is up
            for name in (contest.challenger, contest.defender):
                last = self.last_action.get(name, {})
                if name and last.get("type") == "contest" and self.free_at.get(name, 0) > self.clock:
                    self.free_at[name] = self.clock  # a bout that ended early frees both contestants
        for contest in self.contests.drain_started():
            self._pull_into_contest(contest)
        self.voting.process_votes()  # nominations and votes whose period has ended
        self._settle()

    def _settle(self):
        """Fill seats that fill themselves and open elections for vacancies."""
        self.government.fill_by_seniority()
        self.voting.initiate_votes()
        self._wake_for_new_ballots()

    WAKE_DAYS = int(_time_data.get("news_travel_days", 5))  # a resting player hears about a new ballot within this many days

    def _wake_for_new_ballots(self):
        """News travels: when nominations or voting open, players resting at home come back within a
        few days (staggered by turn order, so no randomness) if they can take part."""
        stages = set()
        for b in self.voting.active_votes:
            stage = "nominating" if getattr(b, "is_nomination_open", False) else "voting"
            stages.add((b.key, stage))
        new = stages - self._ballot_stages
        self._ballot_stages = stages
        if not new or not self.resting:
            return
        new_keys = {key for key, _ in new}
        for i, p in enumerate(self.players):
            if p.name not in self.resting:
                continue
            last = self.last_action.get(p.name, {})
            if last.get("type") == "care" and p.needs.get("energy", 100) < 60:
                continue  # too tired to be woken
            involved = any(b.key in new_keys for b in self.voting.pending_votes(p)) or \
                any(b.key in new_keys for b in self.voting.nominatable_votes(p))
            if involved:
                back = self.clock + (1 + i % self.WAKE_DAYS) * HOURS_PER_DAY
                if back < self.free_at[p.name]:
                    self.free_at[p.name] = back
                    self.resting.discard(p.name)

    def _event_day(self, data):
        gov = self.government
        self._expire_sites()
        self._live_one_day()
        self.life.daily()  # births, birthdays, falling ill, pregnancies
        self.contests.tick(environment.life_days(HOURS_PER_DAY))
        self.innovation_manager.advance_research(gov.daily_income())
        gov.check_new_age()
        if self.clock % HOURS_PER_YEAR == 0:
            Messages.add(f"-- {format_date(self.clock)}: Year {self.year} begins. "
                         f"Innovation points: {int(gov.innovation_pool.points)} (+{gov.annual_points()} a year) --", header=True)
            self.innovation_manager.yearly_random_discovery()
            gov.check_new_age()
            gov.process_divine_signs()
        elif day_of_year(self.clock) % DAYS_PER_SEASON == 0:
            Messages.add(f"-- {format_date(self.clock)}: {season_of(self.clock)} begins --", header=True)
        self.schedule(self.clock + HOURS_PER_DAY, "day")

    # ------------------------------------------------------------------ #
    # Everyday life: needs, skills, aging
    # ------------------------------------------------------------------ #
    def amenities(self) -> Dict[str, float]:
        """What the group has thanks to people's work: {'fire': best firekeeping skill among those who provide it}.
        The fire is there only while it has been fed (see fire_hours_left)."""
        have: Dict[str, float] = {}
        for name, holders in self.government.occupations.items():
            occ = OCCUPATIONS[name]
            for amenity in occ.provides:
                for h in holders:
                    skill = h.skills.get(occ.skill, 0) if occ.skill else 0
                    have[amenity] = max(have.get(amenity, 0), skill)
        if self.clock < self.fire_until:
            have.setdefault("fire", 0.0)  # it still burns, even with nobody tending it
        else:
            have.pop("fire", None)
        return have

    def fire_hours_left(self) -> float:
        """Day-night hours the fire will still burn without more wood."""
        return max(0, self.fire_until - self.clock) / environment.HOURS_PER_LIFE_HOUR

    def roll_characters(self, rng: Optional[random.Random] = None):
        """A new game: everyone's attributes are rolled with dice, and skills start at 0 except those of
        the jobs open from the start (character.json 'new_characters')."""
        cfg = CHARACTER.new_characters
        if not cfg.get("random", False):
            return
        r = rng or random
        gov = self.government
        open_skills = {o.skill for o in OCCUPATIONS.values() if o.skill and gov.is_unlocked(o.requires)}

        def roll(n, sides, plus):
            return sum(r.randint(1, int(sides)) for _ in range(int(n))) + plus
        work_age = max(1, self.life.rules.get("work_age", 1))
        for p in self.players:
            # A child has had only part of their childhood (life.json 'childhood'): that part of the roll.
            grown = min(1.0, p.age / work_age)
            for a in CHARACTER.attributes:
                # Everyone starts at the base (average) and the dice only add to it.
                bonus = max(0, roll(cfg.get("attribute_dice", 2), cfg.get("sides", 3), cfg.get("plus", -2)))
                bonus = int(round(bonus * grown))
                p.attributes[a] = max(CHARACTER.attr_min, min(CHARACTER.attr_max, cfg.get("attribute_base", 5) + bonus))
            for s in CHARACTER.skills:
                p.skills[s] = float(max(0, roll(cfg.get("open_job_skill_dice", 1), cfg.get("open_job_skill_sides", 3),
                                                cfg.get("open_job_skill_plus", -1)))) \
                    if s in open_skills and grown >= 1 else 0.0

    @staticmethod
    def _patience_news(events):
        """Group (person, {meter: 'thin'|'out'}) into (meter, how, [names]) for one chronicle line each."""
        grouped: Dict[Tuple[str, str], List[str]] = {}
        for p, changes in events:
            for meter, how in changes.items():
                grouped.setdefault((meter, how), []).append(p.name)
        return [(m, h, names) for (m, h), names in grouped.items()]

    def _job_change(self, player: Player, before: List[str], new: str):
        """Appointed from `before` (their jobs, maybe none) to `new`: higher work pleases, lower work sours."""
        gov = self.government
        old = max(before, key=lambda j: society.job_rank(gov, j), default=None)
        moved = society.job_change(gov, player, old, new)
        if moved:
            meter = society.METERS[society.JOB_RANK.get("meter", "leaders")].name
            label = lambda j: j[7:] if j and j.startswith("office:") else (j or "no work")
            Messages.add(f"{player.name} {'welcomes' if moved > 0 else 'resents'} the move from {label(old)} to "
                         f"{label(new)} ({meter} {moved:+g})",
                         reason="higher work" if moved > 0 else "lower work")

    def _job_loss(self, player: Player, how: str, job: str):
        """Someone was dismissed from work or moved to other work: they (and the tribe) resent it."""
        hit = society.job_loss(player, how, self.players)
        if hit:
            what = "being dismissed as" if how == "dismissed" else "being taken off the work of"
            Messages.add(f"{player.name} resents {what} {job} ("
                         + ", ".join(f"{k} -{v:g}" for k, v in hit.items()) + ")")

    def work_activity(self, name: str) -> float:
        """1 while someone has worked recently, fading to 0: a job held but not worked stops counting."""
        window = environment.life_hours_to_calendar(WORK.WORK_COUNTS_LIFE_HOURS)
        since = self.clock - self.last_worked.get(name, 0)
        if since <= window:
            return 1.0
        fade = environment.life_hours_to_calendar(WORK.WORK_FADES_LIFE_HOURS)
        return max(0.0, 1 - (since - window) / max(1, fade))

    def working_now(self, name: str) -> Optional[str]:
        """The job whose work this person is doing right now ('Hunter', 'office:Elder'), or None: they are
        not working, or what they are doing isn't their job's work (fetching water, say)."""
        p = self.player(name)
        last = self.last_action.get(name)
        if p is not None and last and last["type"] == "activity" and self.free_at.get(name, 0) > self.clock:
            return "childhood"
        if p is not None and last and last["type"] == "heal" and self.free_at.get(name, 0) > self.clock:
            return next((o for o in self.government.occupations_of(p)
                         if o in self.life.rules.get("treatment", {}).get("healers", [])), None)  # a child's play and study is their work (life.json 'childhood')
        if p is None or not last or last["type"] not in ("work", "craft") or self.free_at.get(name, 0) <= self.clock:
            return None
        t = WORK.work(last["type"], last["params"].get("task") or last["params"].get("recipe"))
        gov = self.government
        return WORK.job_for(t, gov.occupations_of(p), gov.offices_of(p)) if t else None

    def job_tools(self, player: Player) -> Tuple[int, bool]:
        """(how many different tools for their job the player carries, whether any such tool exists yet:
        one can be made with what the tribe has researched, or someone has one)."""
        tools = {x for job in self.government.jobs_of(player) for x in WORK.tools_for_job(job)}
        if not tools:
            return 0, False
        have = sum(1 for x in tools if player.inventory.count(x))
        invented = have > 0 or any(
            any(self.government.is_unlocked(r.requires) for r in WORK.recipes_making(x))
            or self.possessions.ground.get(x, 0) or any(q.inventory.count(x) for q in self.players)
            for x in tools)
        return have, bool(invented)

    def fire_state(self) -> str:
        """'tended' (burning, and a Firekeeper has worked lately), 'untended' (burning) or 'out'."""
        if self.clock >= self.fire_until:
            return "out"
        keepers = [p for name, holders in self.government.occupations.items() if "fire" in OCCUPATIONS[name].provides
                   for p in holders]
        return "tended" if any(self.work_activity(p.name) >= 1.0 for p in keepers) else "untended"

    def fire_temperature(self) -> Optional[float]:
        have = self.amenities()
        return environment.fire_temperature(have["fire"]) if "fire" in have else None

    def activity_of(self, player: Player):
        """What the player's body is doing now: a care action, resting, or None (up and about)."""
        if self.is_free(player) or self.free_at[player.name] <= self.clock:
            return None
        last = self.last_action.get(player.name)
        if not last:
            return None
        if last["type"] == "care":
            care = CHARACTER.care_actions.get(last["params"]["kind"])
            return care.activity() if care and not care.instant else None
        if last["type"] in ("wait", "collapse", "treat"):
            return CHARACTER.resting
        return None

    def _live_one_day(self):
        """One calendar day passes for everyone's body (a small slice of the day-night cycle), and
        everyone gets a little better at the work they do."""
        gov = self.government
        slice_ = environment.life_days(HOURS_PER_DAY)
        night = environment.is_night(self.clock)
        air = environment.temperature(self.clock)
        fire = self.fire_temperature()
        season = environment.season_of(self.clock)
        practice = CHARACTER.training_per_year / DAYS_PER_YEAR
        self.possessions.take_tools_for_work()
        self._settle_qualities(slice_)
        for p in self.players:  # NPCs out of food or water take some from the camp store first thing
            if not self.possessions._keeps_all(p) and not self.possessions.hands_free(p):
                self.possessions.restock(p)
        self.qualities = society.compute_qualities(gov)
        overall = society.society_score(self.qualities)
        for meter, how, names in self._patience_news(society.update_satisfaction(self.players, gov, self.qualities,
                                                                                 overall, slice_)):
            what = society.METERS[meter].name.lower()
            who = ", ".join(names)
            if how == "out":
                Messages.add(f"{who} {'has' if len(names) == 1 else 'have'} run out of patience with the {what} "
                             f"and may move against those in charge", reason=f"{what} contentment low for long")
            else:
                Messages.add(f"{who}: patience with the {what} wearing thin", important=False,
                             reason=f"{what} contentment low")
        leadership_way = society.leadership_direction(self.players)
        for p in list(self.players):
            activity = self._scaled_activity(self.activity_of(p), p)
            temp = max(air, environment.resting_temperature(fire)) \
                if (fire is not None and activity is not None and activity.at_camp) else air
            drain, fatal = self.life.health_drain(p)
            fatal = fatal or CHARACTER.zero_health_kills  # character.json health 'at_zero': no more collapsing
            collapsed = p.live(slice_, night, temp, environment.COMFORT, activity, season,
                               need_factors=self.life.need_factors(p), health_drain=drain,
                               regen_factor=self.regen_factor(p), fatal=fatal, no_fire=fire is None)
            if fatal and p.health <= 0:
                # An illness ran its course, or hunger, thirst or cold emptied their health.
                self.life.die(p, None if p.illness else p.death_cause())
                continue
            if collapsed:
                Messages.add(f"{p.name} {collapsed} and must rest", reason="health ran out")
                rest = int(CHARACTER.health.get("collapse_rest_days", 30) * HOURS_PER_DAY)
                self.idle.discard(p.name)
                self.resting.discard(p.name)
                if self.acting is p:
                    self.acting = None
                self.free_at[p.name] = max(self.free_at[p.name], self.clock + rest)
                self.last_action[p.name] = {"type": "collapse", "params": {}, "label": "", "group": ""}
            for occ in gov.occupations_of(p) if self.work_activity(p.name) > 0 else []:  # practice comes from working
                o = OCCUPATIONS[occ]
                if o.skill:
                    p.train(o.skill, practice)
                for skill, share in o.also_trains.items():
                    p.train(skill, practice * share)
            worked = self.work_activity(p.name)  # office holders learn from working their office (W)
            for office in gov.offices_of(p):
                skill = society.office_spec(gov, office).get("skill")
                if skill and skill != CHARACTER.office_skill and worked > 0:
                    p.train(skill, practice * worked)
            if CHARACTER.office_skill and gov.offices_of(p):
                # Leadership grows from working the office, faster while the tribe is content, and withers
                # while the tribe is unhappy (society.json 'leadership_training').
                p.train(CHARACTER.office_skill, practice * society.leadership_practice(worked, leadership_way))

    def _scaled_activity(self, activity, player=None):
        """A meal restores what was eaten (care actions that 'consume'); care actions with 'scaled_by_quality'
        follow that society quality."""
        if activity is None:
            return None
        care = CHARACTER.care_actions.get(activity.key)
        if care is not None and care.consumes and player is not None:
            from world.character import Activity
            f = self.meals.get(player.name, 1.0)
            return Activity(activity.key, {k: v * f for k, v in activity.restores_per_day.items()},
                            activity.factors, activity.at_camp)
        key = getattr(care, "scaled_by_quality", None) if care else None
        if not key or key not in self.qualities:
            return activity
        low = care.quality_floor  # what is left of the effect when the quality is 0
        f = low + (1 - low) * self.qualities[key]["value"] / 100
        from world.character import Activity
        return Activity(activity.key, {k: v * f for k, v in activity.restores_per_day.items()},
                        activity.factors, activity.at_camp)

    def quality_event(self, event: str):
        """Something happened that hits the tribe's qualities at once (society.json qualities' 'events': a death
        takes a chunk out of Care). The chunk comes back slowly ('quality_events.recover_half_life_life_hours')."""
        for key, points in society.event_points(event).items():
            self.quality_shocks[key] = self.quality_shocks.get(key, 0.0) + points
            q = society.QUALITIES[key]
            Messages.add(f"{q.icon} The tribe's {q.name.lower()} {'falls' if points < 0 else 'rises'} by "
                         f"{abs(points):g} ({event})", reason=event)
        self.qualities = society.compute_qualities(self.government)

    def quality_use(self, use: str):
        """Someone used something a 'use' quality follows (warmed themselves at the fire): it rises."""
        for key, points in society.use_points(use).items():
            q = society.QUALITIES[key]
            self.quality_levels[key] = max(0.0, min(100.0, self.quality_levels.get(key, q.start) + points))

    def _settle_qualities(self, life_days: float):
        """Event chunks come back a little each day; 'use' qualities lose 'fall_per_day' (0: they stay put)."""
        half = society.QUALITY_EVENTS.get("recover_half_life_life_hours", 12)
        keep = 0.5 ** (life_days * 24 / max(1e-6, half))
        for key in list(self.quality_shocks):
            self.quality_shocks[key] *= keep
            if abs(self.quality_shocks[key]) < 0.1:
                del self.quality_shocks[key]
        for key, q in society.QUALITIES.items():
            if q.style == "use" and q.fall_per_day:
                self.quality_levels[key] = max(0.0, self.quality_levels.get(key, q.start) - q.fall_per_day * life_days)

    def regen_factor(self, p: Player) -> float:
        """How fast health comes back for what this person is doing now (character.json
        'health.regen_factors'): not at all while working, faster while resting, asleep or being tended."""
        f = CHARACTER.health.get("regen_factors", {})
        if self.is_free(p) or self.free_at.get(p.name, 0) <= self.clock:
            return float(f.get("awake", 1.0))
        last = self.last_action.get(p.name, {})
        kind = last.get("type")
        if kind in ("work", "craft"):
            return float(f.get("work", 0.0))
        if kind == "care" and last.get("params", {}).get("kind") == "sleep":
            return float(f.get("sleep", 1.0))
        if kind in ("wait", "collapse"):
            return float(f.get("rest", 1.0))
        if kind == "treat":
            return float(f.get("treatment", 1.0))
        return float(f.get("awake", 1.0))

    # ------------------------------------------------------------------ #
    # People joining (born) and leaving (dying)
    # ------------------------------------------------------------------ #
    def add_person(self, p: Player):
        """A newborn joins the tribe (core/life.py). Their controller comes from the game loop."""
        self.players.append(p)  # the same list as game_state.players
        self.government.add_player(p)
        society.init_satisfaction([p])
        self.free_at[p.name] = self.clock
        self.last_worked[p.name] = 0

    def remove_person(self, p: Player):
        """Someone has died (core/life.py): they leave every office and job, every ballot and contest; what they
        carried goes to the camp store. Their body stays in camp (Life.bodies) until laid to rest. An office they
        held opens to an election at once (life.json 'succession')."""
        held = self.government.offices_of(p)
        self.government.remove_player(p)
        self.voting.forget(p.name)
        self.contests.forget(p.name)
        self.possessions.forget(p)
        self.life.release_bodies(p.name)
        if p in self.players:
            self.players.remove(p)
        for table in (self.free_at, self.last_worked, self.last_action, self.last_deeds, self.meals,
                      self.aside_checked, self.aside_looked, self.talk_free_at, self.talk_what):
            table.pop(p.name, None)
        self.idle.discard(p.name)
        self.resting.discard(p.name)
        if self.acting is p:
            self.acting = None
        succ = self.life.rules.get("succession", {})
        for office in held if succ.get("snap_election", True) else []:
            if self.government.is_unlocked(self.government.government_type.offices[office].requires):
                self.voting.snap_election(office, succ.get("nomination_days", 5), succ.get("voting_days", 10))

    # ------------------------------------------------------------------ #
    # Legal actions
    # ------------------------------------------------------------------ #
    def can_interrupt(self, player: Player) -> bool:
        """Is the player busy with something they can break off (sleeping, resting, warming up)?"""
        if self.is_free(player) or self.free_at[player.name] <= self.clock:
            return False
        last = self.last_action.get(player.name, {})
        if last.get("type") == "wait":
            return True
        if last.get("type") == "care":
            care = CHARACTER.care_actions.get(last["params"]["kind"])
            return bool(care and care.interruptible)
        return False

    def interrupt(self, player: Player) -> bool:
        """Break off what the player is doing; they are free at once."""
        if not self.can_interrupt(player):
            Messages.add(f"{player.name} can't stop what they are doing.", important=False)
            return False
        last = self.last_action.get(player.name, {})
        verb = "wakes up" if last.get("params", {}).get("kind") == "sleep" else "gets up"
        self.free_at[player.name] = self.clock
        self.resting.discard(player.name)
        self.last_action[player.name] = {"type": "stop", "params": {}, "label": "", "group": ""}
        Messages.add(f"{player.name} {verb}", important=False, category="life")
        return True

    WHILE_BUSY: Dict[str, Any] = _time_data.get("while_busy", {})

    def can_act_aside(self, player: Player) -> bool:
        """Busy with something that leaves room for politics (time.json 'while_busy': work, crafting,
        resting, a meal), so they may vote, nominate, appoint... without breaking it off?"""
        if self.is_free(player) or self.free_at[player.name] <= self.clock:
            return False
        rule = self.contests.restriction(player.name)
        if rule is not None and rule["locked"]:
            return False  # held in a ritual fight
        last = self.last_action.get(player.name, {})
        kind = last.get("type")
        if kind == "care":
            kind = f"care:{last.get('params', {}).get('kind')}"
        return kind in self.WHILE_BUSY.get("during", ["work", "craft", "wait"])

    def aside_actions(self, player: Player) -> List[Action]:
        """What a busy player may still do at once (see can_act_aside)."""
        if not self.can_act_aside(player):
            return []
        allowed = set(self.WHILE_BUSY.get("actions", []))
        talking = self.talk_free_at.get(player.name, 0) > self.clock  # still in the middle of a talk
        return [a for a in self._options(player) if a.type in allowed
                and not (talking and a.type in self.TALKS)]

    TALKS = ("canvass", "rally")  # talks take their time even on the side

    def act_aside(self, player: Player, action: Action, reason: Optional[str] = None) -> bool:
        """A busy player votes, nominates, appoints... without stopping what they are doing."""
        if action.key() not in {a.key() for a in self.aside_actions(player)}:
            Messages.add(f"{player.name} cannot do that right now: {action}", important=False)
            return False
        entry = {"time": self.clock, "date": format_date(self.clock), "player": player.name,
                 **action.to_dict(), "reason": reason}
        if not getattr(self, f"_do_{action.type}")(player, action.params, reason):
            return False
        self.action_log.append(entry)
        self.last_deeds[player.name] = {**entry, "label": action.label, "group": action.group}
        if action.type in self.TALKS:
            self.talk_free_at[player.name] = self.clock + self.duration(action)
            who = action.params.get("listener", "")
            self.talk_what[player.name] = (f"winning over {who}" if action.type == "canvass" else f"rallying {who}")
        self._settle()
        return True

    def legal_actions(self, player: Player) -> List[Action]:
        if not self.is_free(player):
            acts = [Action("stop", {}, "Stop and get up", "")] if self.can_interrupt(player) else []
            return acts + self.aside_actions(player)
        return self._options(player)

    def _options(self, player: Player) -> List[Action]:
        """Everything the player could do if it were their moment."""
        gov, vm = self.government, self.voting
        acts: List[Action] = []
        if not self.life.of_age(player, "politics"):
            return self._while_contesting(player, self._personal_options(player, acts))

        for ballot in vm.pending_votes(player):
            for choice in ballot.choices():
                acts.append(Action("vote", {"ballot": ballot.key, "choice": choice}, choice, ballot.label))

        for election in vm.nominatable_votes(player):
            for cand in vm.nomination_candidates(election):
                acts.append(Action("nominate", {"ballot": election.key, "candidate": cand.name}, cand.name, election.label))

        for position in gov.appointable(player):
            if position in gov.government_type.offices:
                office = gov.government_type.offices[position]
                holders = gov.get_role_holders(position)
                if office.seats > 1 and len(holders) >= office.seats:
                    continue  # full multi-seat office: someone must be dismissed first
                candidates = [p for p in self.players if p is not player
                              and gov.can_hold_office(position, p, ignore_seat_limit=True)[0]]
            elif position in OCCUPATIONS:
                seats = OCCUPATIONS[position].seats
                if seats is not None and len(gov.occupations[position]) >= seats:
                    continue  # every place is taken: dismiss someone first
                candidates = [p for p in self.players if p is not player
                              and gov.can_take_occupation(position, p, switching=True, appointer=player)[0]]
            else:
                candidates = [p for p in self.players if p is not player and p not in gov.statuses.get(position, [])]
            for cand in candidates:
                acts.append(Action("appoint", {"position": position, "appointee": cand.name}, cand.name, position))

        for position in gov.dismissable(player):
            if position in gov.government_type.offices:
                holders = gov.get_role_holders(position)
            elif position in OCCUPATIONS:
                holders = gov.occupations[position]
            else:
                holders = gov.statuses.get(position, [])
            for holder in holders:
                if position in OCCUPATIONS and not gov.may_change(player, holder):
                    continue  # appointed by a higher office: not theirs to undo
                acts.append(Action("dismiss", {"position": position, "holder": holder.name}, holder.name, position))
        for holder in gov.releasable(player):
            job, office = gov.binding(holder)
            acts.append(Action("release", {"holder": holder.name}, f"{holder.name} ({job}, appointed by the {office})",
                               "release"))

        cm = self.contests
        for office, target in cm.persuasion_targets(player):
            label = f"{office}" + (f" (replacing {target})" if target else " (a vacant seat)")
            acts.append(Action("persuade", {"office": office, "target": target or ""}, label, "persuade"))
        for c, listener in cm.canvass_options(player):
            acts.append(Action("canvass", {"contest": c.key, "listener": listener}, listener, "canvass"))
        for c, listener in cm.rally_options(player):
            acts.append(Action("rally", {"contest": c.key, "listener": listener}, listener, "rally"))
        for office, holder, kind in cm.challenge_options(player):
            label = kind_name(kind) if kind else f"Challenge {holder} for {office}"
            acts.append(Action("challenge", {"office": office, "holder": holder, "kind": kind}, label,
                               f"{office}: {holder}"))
        for c, kind in cm.answer_options(player):
            acts.append(Action("answer_challenge", {"contest": c.key, "kind": kind}, kind_name(kind), c.challenger))

        for kind, subject, target in vm.available_motions(player):
            label = CALL_VOTE_LABELS[kind].format(target=target.name, subject=subject)
            acts.append(Action("call_vote", {"kind": kind, "subject": subject, "target": target.name}, label, kind))

        mode = gov.reform_mode(player)
        if mode:
            for g in gov.available_reforms():
                acts.append(Action("reform", {"government": g.key}, g.name, "decree" if mode == "decree" else "vote"))

        for interface in gov.get_player_interfaces(player):
            for innov in interface.research_options():
                acts.append(Action("research", {"interface": interface.role_key, "innovation": innov.name},
                                   f"{innov.name} (Cost: {innov.cost}){unlock_note(innov.name)}", interface.role_key))
            for cmd in interface.available_commands():
                acts.append(Action("role_command", {"interface": interface.role_key, "command": cmd.key},
                                   cmd.description, interface.role_key))

        acts = self._personal_options(player, acts)

        for office in gov.offices_of(player):
            if not any(c.office == office for c in [self.contests.involving(player.name)] if c):
                acts.append(Action("resign", {"office": office}, f"Resign as {office}", "resign"))

        for ballot in vm.declinable(player):
            what = "Decline the nomination for" if getattr(ballot, "is_nomination_open", False) else "Withdraw from"
            acts.append(Action("decline_nomination", {"ballot": ballot.key}, f"{what} {ballot.label}", ballot.label))

        for days in WAIT_DAYS:
            acts.append(Action("wait", {"days": days}, f"Wait {format_duration(days * HOURS_PER_DAY)}"))
        return self._while_contesting(player, acts)

    def _personal_options(self, player: Player, acts: List[Action]) -> List[Action]:
        """Jobs, looking after oneself, seeing a healer, work, and (for children) play and study."""
        gov = self.government
        for name in gov.volunteer_options(player):
            acts.append(Action("take_occupation", {"occupation": name}, name, "work"))
        bound = gov.binding(player)
        for name in gov.occupations_of(player):
            if bound and bound[0] == name:
                continue  # appointed: they keep it until released
            acts.append(Action("leave_occupation", {"occupation": name}, f"Give up being {name}", "work"))

        have = self.amenities()
        for key, care in CHARACTER.care_actions.items():
            if gov.is_unlocked(care.requires) and (care.needs_amenity is None or care.needs_amenity in have) \
                    and (not care.consumes or self._meal_for(player, care)):
                acts.append(Action("care", {"kind": key}, care.label, "needs"))
        opt = self.life.treatment_for(player)
        if opt is not None:
            label = self.life.rules["treatment"].get("label", "See the healer")
            acts.append(Action("treat", {}, f"{label} ({opt['healer'].name}, {ITEMS[opt['medicine']['item']].name.lower()})",
                               "needs"))

        for kind, key, label in self.work_options(player):
            acts.append(Action(kind, {"task" if kind == "work" else "recipe": key}, label, "work"))
        if not self.life.cannot_work(player):  # a healer goes to the sick (life.json 'treatment')
            for patient in self.life.patients_for(player):
                ill = self.life.illness_of(patient)
                what = ill["name"].lower() if ill else f"health {patient.health:.0f}"
                who = "yourself" if patient is player else patient.name
                acts.append(Action("heal", {"patient": patient.name}, f"Heal {who} ({what})", "work"))
        for key, a in self.life.activities_for(player):
            acts.append(Action("activity", {"activity": key}, a["label"], a.get("group", "play")))
        if not self.life.of_age(player, "politics"):
            for days in WAIT_DAYS:
                acts.append(Action("wait", {"days": days}, f"Wait {format_duration(days * HOURS_PER_DAY)}"))
        return acts

    def _while_contesting(self, player: Player, acts: List[Action]) -> List[Action]:
        """A contestant in a running challenge may only do what 'during_contest' allows for its style
        (speak to listeners in an oration, eat and drink on a hunt...), plus short waits."""
        rule = self.contests.restriction(player.name)
        if rule is None:
            return acts
        c, may = rule["contest"], rule["may"]
        if rule["locked"]:
            return []
        left_days = max(1, (c.ends - self.clock) // HOURS_PER_DAY)

        def allowed(a: Action) -> bool:
            if a.type == "wait":
                return a.params["days"] <= max(left_days, min(WAIT_DAYS))
            if a.type == "care":
                return f"care:{a.params['kind']}" in may
            if a.type in ("canvass", "rally"):
                return "speak" in may and a.params["contest"] == c.key
            return a.type in may
        return [a for a in acts if allowed(a)]

    # ------------------------------------------------------------------ #
    # Work that produces things (core/work.py)
    # ------------------------------------------------------------------ #
    def _meal_for(self, player: Player, care) -> List[Dict[str, Any]]:
        """What a meal or drink would use up (empty if there is nothing to eat or drink)."""
        need = next(iter(care.restores))
        wanted = min(care.restores[need], 100 - player.needs.get(need, 100))
        return self.possessions.pick_meal(player, need, max(wanted, 1))

    def work_problem(self, player: Player, kind: str, key: str) -> Optional[str]:
        """Why the player can't do this work now ('needs a spear'), or None if they can."""
        t = WORK.work(kind, key)
        gov = self.government
        if t is None:
            return "no such work"
        why = self.life.cannot_work(player)
        if why:
            return why
        if t.scouts_for and t.scouts_for not in self.useful_site_kinds():
            return f"nobody could use {WORK.SITE_KINDS[t.scouts_for]['name']} yet"
        if t.disposes_of_dead and self.life.unclaimed_body() is None:
            return "nobody lies dead in camp" if not self.life.bodies else "someone is already seeing to the dead"
        if not t.open_to_anyone and WORK.job_for(t, gov.occupations_of(player), gov.offices_of(player)) is None:
            if t.any_office and not t.occupations and not t.offices:
                return "only someone holding an office does this"
            return f"only a {' or '.join(t.occupations + t.offices)} does this"
        if not gov.is_unlocked(t.requires):
            return f"needs {', '.join(r for r in t.requires if not gov.is_unlocked([r]))}"
        if t.tools and self.possessions.find_tool(player, t.tools) is None:
            return f"needs a {' or '.join(ITEMS[x].name for x in t.tools)}"
        if t.tools and self._tool_for(player, t) is None:
            tool = self.possessions.find_tool(player, t.tools)
            return f"needs {describe(self._tool_consumes(t, tool))}"
        if not self.possessions.has_all(player, t.consumes):
            return f"needs {describe(t.consumes)}"
        if t.fire_life_hours and self.fire_hours_left() >= WORK.FIRE.get("max_life_hours", 14) - 0.5:
            return "the fire has all the wood it can take"
        return None

    def work_options(self, player: Player) -> List[Tuple[str, str, str]]:
        """(kind, key, label) for every task and recipe the player can do now."""
        out = []
        for kind, table in (("work", WORK.TASKS), ("craft", WORK.RECIPES)):
            for key, t in table.items():
                if self.work_problem(player, kind, key) is None:
                    out.append((kind, key, t.label))
        return out

    def work_quality(self, player: Player, t) -> float:
        """How well the player does this work (0-100): as in their job, or by skill for anyone's tasks."""
        gov = self.government
        job = WORK.job_for(t, gov.occupations_of(player), gov.offices_of(player))
        if job:
            return society.job_quality(gov, job, player)
        from core.society import work_quality
        return work_quality(player, WORK.ANYONE_ATTRIBUTES, t.skill)

    def _do_work(self, player, params, reason) -> bool:
        return self._start_work(player, "work", params["task"], reason)

    def _do_craft(self, player, params, reason) -> bool:
        return self._start_work(player, "craft", params["recipe"], reason)

    def _start_work(self, player, kind: str, key: str, reason) -> bool:
        why = self.work_problem(player, kind, key)
        if why:
            Messages.add(f"{player.name} can't do that: {why}.", important=False)
            return False
        t = WORK.work(kind, key)
        tool = self._tool_for(player, t) if t.tools else None
        if tool and not self.possessions.take_tool(player, tool):
            Messages.add(f"{player.name} has no room in their pack for the {ITEMS[tool].name}.", important=False)
            return False
        if t.consumes and not self.possessions.consume(player, t.consumes):
            return False
        ammo = self.possessions.consume_used(player, self._tool_consumes(t, tool)) if tool else []
        if ammo is None:
            return False
        body = self.life.reserve_body(player) if t.disposes_of_dead else None
        boost = next((b for b in t.boost if self.possessions.find_tool(player, [b])), None)
        speed = self._speed_tool(player, t)
        if speed and speed != tool:
            self.possessions.take_tool(player, speed)  # fetched from the store, if it isn't in the pack already
        self.schedule(self.clock + self.duration(Action(kind, {"task" if kind == "work" else "recipe": key}), player),
                      "work_done", {"player": player.name, "kind": kind, "key": key, "tool": tool, "boost": boost,
                                    "ammo": [a["item"] for a in ammo], "speed_tool": speed if speed != tool else None,
                                    "body": body})
        what = t.label[0].lower() + t.label[1:]
        with_ = f" with a {ITEMS[tool].name.lower()}" if tool else ""
        Messages.add(f"{player.name} sets out to {what}{with_}" if not t.recipe else f"{player.name} sets to work: {what}",
                     important=False, reason=reason, category="life")
        return True

    @staticmethod
    def _tool_consumes(t, tool: Optional[str]) -> List[Dict[str, Any]]:
        """What working with this tool uses up (a bow: an arrow); a better tool standing in for a lesser one
        (items.json 'counts_as') uses what the lesser one would, unless the task names it itself."""
        for key in [tool, *ITEMS[tool].counts_as] if tool else []:
            if key in t.tool_consumes:
                return t.tool_consumes[key]
        return []

    @staticmethod
    def _tool_yield(t, item: Optional[str]) -> float:
        """The task's 'tool_yields' multiplier for this tool or ammunition (or what it stands in for)."""
        for key in [item, *ITEMS[item].counts_as] if item else []:
            if key in t.tool_yields:
                return t.tool_yields[key]
        return 1.0

    def _tool_for(self, player: Player, t) -> Optional[str]:
        """The tool this player would work with: the first of the task's tools they can lay hands on whose
        ammunition is there too (a bow is no use without arrows)."""
        return self.possessions.find_tool(player, t.tools, lambda tool: self.possessions.has_all(
            player, self._tool_consumes(t, tool)))

    def _office_skill_of(self, p: Player, t) -> Optional[str]:
        """Office work with no skill of its own (holding council, office duties) practises the office's
        skill (the office's 'quality' in data/governments, e.g. Clan Leader: leadership)."""
        job = WORK.job_for(t, self.government.occupations_of(p), self.government.offices_of(p))
        return society.office_spec(self.government, job[7:]).get("skill") if job and job.startswith("office:") else None

    def _event_work_done(self, data):
        p = self.player(data["player"])
        t = WORK.work(data["kind"], data["key"])
        if p is None or t is None:
            return
        quality = self.work_quality(p, t)
        mult = self._tool_yield(t, data.get("tool"))
        for item in data.get("ammo", []):  # better ammunition (flint arrows) does better
            mult *= self._tool_yield(t, item)
        if data.get("boost"):
            mult *= t.boost.get(data["boost"], 1.0)
        site = self.site_of(t.site) if t.site else None
        lucky = random.random() < WORK.trip_chance(t, quality, site is not None)
        took = 0.0
        if site is not None and lucky:  # the trip goes to a place a Scout found and takes a big share of what is there
            took = min(site["loads"], WORK.SITES.get("take_per_trip", 2.0))
            if site["loads"] - took < WORK.SITES.get("least_left", 0.3):
                took = site["loads"]
            site["loads"] = round(site["loads"] - took, 2)
            mult *= took
        got = WORK.roll_yields(t, quality, mult) if lucky else []
        kept, shared = self.possessions.bring_back(p, got)
        if t.scouts_for:
            self._scout_for_sites(p, t.scouts_for, quality)
        if t.makes_sites:
            self._make_site(p, t)
        own_job = WORK.job_for(t, self.government.occupations_of(p), self.government.offices_of(p)) is not None
        if own_job:
            self.last_worked[p.name] = self.clock  # only their own job's work counts as working (not fetching water)
        skill = t.skill or self._office_skill_of(p, t)
        if skill:
            practice = CHARACTER.training_per_year / DAYS_PER_YEAR * WORK.PRACTICE_DAYS_PER_TASK
            p.train(skill, practice)
        if t.disposes_of_dead:
            self.life.dispose(data.get("body"), p, t)
        elif t.fire_life_hours:
            most = self.clock + environment.life_hours_to_calendar(WORK.FIRE.get("max_life_hours", 14))
            self.fire_until = min(most, max(self.fire_until, self.clock)
                                  + environment.life_hours_to_calendar(t.fire_life_hours * (WORK.FIRE.get("feed_at_quality_0", 0.7) + (WORK.FIRE.get("feed_at_quality_100", 1.29)
                                                           - WORK.FIRE.get("feed_at_quality_0", 0.7)) * quality / 100)))
            Messages.add(f"{p.name} feeds the fire (it will burn {environment.format_life_duration(self.fire_until - self.clock)})",
                         important=False, category="life")
        elif got:
            where = ("keeps it all" if not shared else "puts it all in the camp store" if not kept else
                     f"keeps {describe(kept)}, the rest to the camp store")
            source = f" from the {WORK.SITE_KINDS[t.site]['short']} {site['by']} found" if site else ""
            Messages.add((f"{p.name} brings back {describe(got)}{source}" if not t.recipe else
                          f"{p.name} makes {describe(got)}") + f" and {where}", important=False, category="life")
        elif t.scouts_for:
            pass  # _scout_for_sites told the chronicle what was found
        elif t.yields:
            why = "" if not t.site or site else \
                f" (nobody knows of {WORK.SITE_KINDS[t.site]['name']}: a Scout could find some)"
            Messages.add(f"{p.name} comes back empty-handed{why}", important=False, category="life")
        else:
            Messages.add(f"{p.name} finishes: {t.label.lower()}", important=False, category="life")
        if took and site["loads"] <= 0:
            self._spend_site(site, "used up")
            Messages.add(f"{p.name} has taken the last of the {WORK.SITE_KINDS[t.site]['short']} {site['by']} found"
                         + ("; the next trip goes to the next place found" if self.site_of(t.site) else
                            "; a Scout must find more"), category="find")
        elif took:
            Messages.add(f"About {site['loads']:g} trips' worth is left at the {WORK.SITE_KINDS[t.site]['short']} "
                         f"{site['by']} found", important=False)
        for tool in (data.get("tool"), data.get("speed_tool")):
            self._use_up_tool(p, tool)
        self.life.after_work(p, t, own_job)  # hard work wears people down (life.json 'work_chance')

    def _use_up_tool(self, p: Player, tool: Optional[str]):
        """A tool used for work may break (items.json tool 'breaks') and wears down one use ('uses'): worn
        all the way down, it breaks for certain. The Toolmaker must make another, and its user fetch it."""
        if not tool:
            return
        name = ITEMS[tool].name.lower()
        if ITEMS[tool].breaks and random.random() < ITEMS[tool].breaks:
            self.possessions.break_tool(p, tool)
            Messages.add(f"{p.name}'s {name} breaks", important=False, category="life")
        elif self.possessions.wear_tool(p, tool):
            Messages.add(f"{p.name}'s {name} is worn out and falls apart", important=False, category="life")

    # ------------------------------------------------------------------ #
    # Sites: good places a Scout finds, where trips succeed far more often
    # ------------------------------------------------------------------ #
    def site_of(self, kind: str) -> Optional[Dict[str, Any]]:
        """The place of this kind trips go to now: the oldest found that still has something left."""
        return next((x for x in self.sites if x["kind"] == kind and x["loads"] > 0 and x["until"] > self.clock), None)

    def site_known(self, kind: str) -> bool:
        return self.site_of(kind) is not None

    def useful_site_kinds(self) -> List[str]:
        """Site kinds someone could make use of now: a task of that kind is unlocked and someone may do it
        (it is open to anyone, or one of its jobs is unlocked)."""
        gov = self.government
        out = []
        for kind in WORK.SITE_KINDS:
            for t in WORK.site_tasks(kind):
                jobs_open = not t.occupations or any(o in OCCUPATIONS and gov.is_unlocked(OCCUPATIONS[o].requires)
                                                     for o in t.occupations)
                if gov.is_unlocked(t.requires) and jobs_open:
                    out.append(kind)
                    break
        return out

    def _add_site(self, kind: str, by: str, loads: float, life_hours: float) -> Dict[str, Any]:
        site = {"id": self.next_site_id, "kind": kind, "by": by, "loads": loads, "total": loads,
                "found": self.clock, "until": self.clock + environment.life_hours_to_calendar(life_hours)}
        self.next_site_id += 1
        self.sites.append(site)
        return site

    def _spend_site(self, site: Dict[str, Any], how: str):
        """A place is used up (or lost): off the list of places, onto the greyed list of spent ones."""
        if site in self.sites:
            self.sites.remove(site)
        self.spent_sites.append(dict(site, spent=self.clock, how=how))
        del self.spent_sites[:-max(0, int(WORK.SITES.get("spent_shown", 4))) or len(self.spent_sites)]

    def _scout_for_sites(self, scout: Player, kind: str, quality: float):
        """A Scout looked for one kind of place (their choice): found with 'sites.find_chance', it holds an
        abundance of trips' worth for the tribe's Gatherers, Hunters or Fishers (work.json 'sites')."""
        spec = WORK.SITE_KINDS[kind]
        if random.random() >= WORK.site_find_chance(quality):
            Messages.add(f"{scout.name} scouted for {spec['name']} but found none this time", important=False)
            return
        site = self._add_site(kind, scout.name, WORK.site_loads(spec.get("loads")), WORK.SITES.get("life_hours", 24))
        what = " or ".join(t.label.lower() for t in WORK.site_tasks(kind))
        Messages.add(f"{spec.get('icon', '')} {scout.name} found {spec['name']}! About {site['loads']:g} trips' "
                     f"worth: trips to {what} will surely pay off until it is used up", category="find")

    def _make_site(self, worker: Player, t):
        """Work that makes a good place rather than finding one (a Sustenance Gardener's plot): one of the
        task's 'makes_sites' kinds, by weight, holding 'loads' trips' worth (topping up their own plot)."""
        kinds = t.makes_sites.get("kinds", {})
        if not kinds:
            return
        kind = random.choices(list(kinds), list(kinds.values()))[0]
        loads = WORK.site_loads(t.makes_sites.get("loads", 1))
        until = self.clock + environment.life_hours_to_calendar(t.makes_sites.get("life_hours", 6))
        mine = next((x for x in self.sites if x["kind"] == kind and x["by"] == worker.name and x["loads"] > 0), None)
        if mine:
            mine["loads"] = round(mine["loads"] + loads, 2)
            mine["total"] = max(mine["total"], mine["loads"])
            mine["until"] = max(mine["until"], until)
        else:
            mine = self._add_site(kind, worker.name, loads, t.makes_sites.get("life_hours", 6))
        what = " or ".join(x.label.lower() for x in WORK.site_tasks(kind))
        Messages.add(f"{worker.name} tends {WORK.SITE_KINDS[kind]['name']}: about {mine['loads']:g} trips' worth "
                     f"to {what}", important=False, category="life")

    def _expire_sites(self):
        for site in [x for x in self.sites if x["until"] <= self.clock]:
            self._spend_site(site, "lost")
            Messages.add(f"Nobody went back to the {WORK.SITE_KINDS[site['kind']]['short']} {site['by']} found in "
                         f"time: about {site['loads']:g} trips' worth is lost", important=False)

    def site_hours_left(self, site: Dict[str, Any]) -> float:
        return max(0.0, (site["until"] - self.clock) / environment.HOURS_PER_LIFE_HOUR)

    def _site_view(self, site: Dict[str, Any]) -> Dict[str, Any]:
        spec = WORK.SITE_KINDS[site["kind"]]
        return {"id": site["id"], "kind": site["kind"], "name": spec["name"], "short": spec["short"],
                "icon": spec.get("icon", "•"), "by": site["by"], "loads": site["loads"], "total": site["total"],
                "hours_left": round(self.site_hours_left(site), 1), "how": site.get("how")}

    def _speed_tool(self, player: Player, t) -> Optional[str]:
        """The best of the work's 'speed_tools' the player can lay hands on (pack, else camp store)."""
        for key in sorted(t.speed_tools, key=t.speed_tools.get, reverse=True):
            if player.inventory.count(key) or self.possessions.ground.get(key, 0):
                return key
        return None

    def duration(self, action: Action, player: Optional[Player] = None) -> int:
        """Game hours the action keeps the player busy. Work goes faster with a speed tool in the pack
        (a Toolmaker with a stone knife)."""
        if action.type in ("work", "craft"):
            t = WORK.work(action.type, action.params.get("task") or action.params.get("recipe"))
            hours = t.life_hours if t else 1
            if t and player is not None and t.speed_tools:
                held = [x for k, x in t.speed_tools.items() if player.inventory.count(k)]
                hours /= max(held, default=1.0)
            return max(1, environment.life_hours_to_calendar(hours))
        if action.type == "wait":
            return int(action.params["days"] * HOURS_PER_DAY)
        if action.type in ("treat", "heal"):
            return max(1, environment.life_hours_to_calendar(self.life.rules["treatment"].get("life_hours", 1)))
        if action.type == "activity":
            a = self.life.activity(action.params["activity"]) or {}
            return max(1, environment.life_hours_to_calendar(a.get("life_hours", 1.5)))
        if action.type == "care":
            care = CHARACTER.care_actions[action.params["kind"]]
            return max(1, environment.life_hours_to_calendar(care.life_hours))
        if action.type == "persuade":
            return max(1, environment.life_hours_to_calendar(PERSUASION.get("announce_life_hours", 0.25)))
        if action.type in ("canvass", "rally"):
            hours = self.contests.speech_hours(action.params["contest"], action.type)
            return max(1, environment.life_hours_to_calendar(hours))
        if action.type in ("challenge", "answer_challenge") and action.params.get("kind"):
            ck = CHALLENGE_KINDS[action.params["kind"]]
            if DURING_CONTEST.get(ck.style, {"locked": True}).get("locked"):
                return max(1, environment.life_hours_to_calendar(ck.life_hours))  # busy until the bout ends
        if action.type in ("challenge", "answer_challenge"):
            return max(1, environment.life_hours_to_calendar(PERSUASION.get("announce_life_hours", 0.25)))
        return ACTION_HOURS.get(action.type, 1)

    # ------------------------------------------------------------------ #
    # Applying actions
    # ------------------------------------------------------------------ #
    def apply(self, player: Player, action: Action, reason: Optional[str] = None) -> bool:
        if player is not self.acting:
            Messages.add(f"It is not {player.name}'s moment to act.", important=False)
            return False
        if action.key() not in {a.key() for a in self.legal_actions(player)}:
            Messages.add(f"{player.name} cannot do that right now: {action}", important=False)
            return False
        entry = {"time": self.clock, "date": format_date(self.clock), "player": player.name,
                 **action.to_dict(), "reason": reason}
        if not getattr(self, f"_do_{action.type}")(player, action.params, reason):
            return False  # still this player's moment; they may choose again
        self.action_log.append(entry)
        care = CHARACTER.care_actions.get(action.params.get("kind")) if action.type == "care" else None
        if action.type == "wait" or (care and care.interruptible):
            self.resting.add(player.name)
        else:
            self.resting.discard(player.name)
        self.last_action[player.name] = {**entry, "label": action.label, "group": action.group}
        if action.type not in ("wait", "care"):
            self.last_deeds[player.name] = self.last_action[player.name]
        self.free_at[player.name] = self.clock + self.duration(action, player)
        self.acting = None
        self._settle()
        return True

    def _do_wait(self, player, params, reason) -> bool:
        Messages.add(f"{player.name} rests at home "
                     f"({environment.format_life_duration(params['days'] * HOURS_PER_DAY)})",
                     important=False, reason=reason, category="life")
        return True

    def _do_vote(self, player, params, reason) -> bool:
        ballot = self.voting.ballot(params["ballot"])
        ranking = list(params.get("ranking") or [params["choice"]])
        if ranking[0] != params["choice"]:
            Messages.add("A ranking must start with the chosen candidate.", important=False)
            return False
        return self.voting.cast_vote(player, ballot.key, ranking, reason=reason)

    def _do_nominate(self, player, params, reason) -> bool:
        election = self.voting.ballot(params["ballot"])
        cand = next((p for p in self.players if p.name == params["candidate"]), None)
        if election is not None and cand is not None and self.contests.campaigning(cand.name):
            c = self.contests.campaigning(cand.name)
            Messages.add(f"{cand.name} is {'campaigning by persuasion' if c.is_persuasion else 'challenging'} for {c.office} "
                         f"and cannot also stand for {election.label}.", important=False)
            return False
        try:
            election.nominate(player, params["candidate"])
        except ValueError as e:
            Messages.add(f"Nomination failed: {e}", important=False)
            return False
        who = "themselves" if params["candidate"] == player.name else params["candidate"]
        Messages.add(f"{player.name} nominated {who} for {election.label}", important=False, reason=reason)
        return True

    def _do_decline_nomination(self, player, params, reason) -> bool:
        return self.voting.decline(player, params["ballot"], reason=reason)

    def _do_appoint(self, player, params, reason) -> bool:
        return self.government.appoint(player, params["position"], self.player(params["appointee"]), reason=reason)

    def _do_release(self, player, params, reason) -> bool:
        return self.government.release(player, self.player(params["holder"]), reason=reason)

    def _do_dismiss(self, player, params, reason) -> bool:
        return self.government.dismiss(player, params["position"], self.player(params["holder"]), reason=reason)

    def _do_call_vote(self, player, params, reason) -> bool:
        return self.voting.propose_motion(player, params["kind"], params["subject"], self.player(params["target"]), reason=reason)

    def _do_reform(self, player, params, reason) -> bool:
        if self.government.reform_mode(player) == "decree":
            return self.government.reform(params["government"], decreed_by=player, reason=reason)
        return self.voting.propose_reform(player, params["government"], reason=reason)

    def _do_research(self, player, params, reason) -> bool:
        if not self.innovation_manager.add_to_research_queue(params["innovation"]):
            return False
        Messages.add(f"{player.name} added {params['innovation']} to the research queue", important=False, reason=reason)
        return True

    def _do_care(self, player, params, reason) -> bool:
        care = CHARACTER.care_actions[params["kind"]]
        if care.needs_amenity and care.needs_amenity not in self.amenities():
            Messages.add(f"There is no {care.needs_amenity} to {care.label.lower()}.", important=False)
            return False
        share, what = 1.0, ""
        if care.consumes:
            meal = self._meal_for(player, care)
            if not meal or not all(player.inventory.take(s["item"], s["count"]) for s in meal):
                what = next(iter(care.restores))
                Messages.add(f"Sorry, {player.name} can't {care.label.split()[0].lower()} right now: there is no "
                             f"{what} in their inventory (take some from the camp store first).", important=False)
                return False
            need = next(iter(care.restores))
            got = sum(ITEMS[s["item"]].use.get(need, 0) * s["count"] for s in meal)
            share = min(care.max_share, got / care.restores[need])
            what = f" ({describe(meal)})"
            if not care.instant:
                self.meals[player.name] = share
        if care.instant:
            player.care_now(params["kind"], share)
        Messages.add(f"{player.name} {care.announce}{what}", important=False, reason=reason, category="life")
        self.quality_use(f"care:{params['kind']}")  # warming up at the fire is what makes the tribe content with it
        return True

    def _do_treat(self, player, params, reason) -> bool:
        return self.life.treat(player, reason=reason)

    def _do_heal(self, player, params, reason) -> bool:
        patient = self.player(params["patient"])
        return patient is not None and self.life.treat(patient, reason=reason, healer=player)

    def _do_activity(self, player, params, reason) -> bool:
        a = self.life.activity(params["activity"])
        if a is None or params["activity"] not in dict(self.life.activities_for(player)):
            Messages.add(f"{player.name} can't do that now.", important=False)
            return False
        self.schedule(self.clock + self.duration(Action("activity", params)), "activity_done",
                      {"player": player.name, "activity": params["activity"]})
        Messages.add(f"{player.name} goes to {a['label'][0].lower() + a['label'][1:]}", important=False, reason=reason,
                     category="life")
        return True

    def _event_activity_done(self, data):
        p = self.player(data["player"])
        if p is not None:
            self.life.finish_activity(p, data["activity"])

    def _do_persuade(self, player, params, reason) -> bool:
        return self.contests.start_persuasion(player, params["office"], params["target"] or None, reason=reason) is not None

    def _do_canvass(self, player, params, reason) -> bool:
        return self.contests.canvass(player, params["contest"], params["listener"], reason=reason)

    def _do_rally(self, player, params, reason) -> bool:
        return self.contests.rally(player, params["contest"], params["listener"], reason=reason)

    def _do_challenge(self, player, params, reason) -> bool:
        c = self.contests.start_challenge(player, params["office"], params["holder"], params["kind"], reason=reason)
        if c is None:
            return False
        for started in self.contests.drain_started():  # a contest the challenger chose begins at once
            self._pull_into_contest(started)
        if c.awaiting_answer:
            # The one challenged must choose the contest: wake them if they are asleep or resting.
            d = self.player(c.defender)
            if d is not None and self.can_interrupt(d):
                self.interrupt(d)
        return True

    def _do_answer_challenge(self, player, params, reason) -> bool:
        if self.contests.answer(player, params["contest"], params["kind"], reason=reason) is None:
            return False
        for c in self.contests.drain_started():
            self._pull_into_contest(c)
        return True

    def _pull_into_contest(self, c):
        """The contest calls both contestants. A ritual fight takes them up until it ends, whatever they
        were doing; in other contests they are woken if asleep or resting, and may then do only what
        'during_contest' allows (speak to listeners, eat, drink...)."""
        if not self.contests.is_locked_in(c):
            for name in (c.challenger, c.defender):
                p = self.player(name) if name else None
                if p is not None and self.can_interrupt(p):
                    self.interrupt(p)
            return
        for name, other in ((c.challenger, c.defender), (c.defender, c.challenger)):
            if name is None:
                continue
            self.idle.discard(name)
            self.resting.discard(name)
            if self.acting is not None and self.acting.name == name:
                continue  # they are choosing the contest right now; apply() keeps them busy until the end
            self.free_at[name] = c.ends
            self.last_action[name] = {"type": "contest", "params": {"contest": c.key, "kind": c.kind,
                                                                     "office": c.office, "opponent": other},
                                      "label": "", "group": ""}

    def _do_resign(self, player, params, reason) -> bool:
        return self.government.resign(params["office"], player, reason=reason)

    def _do_take_occupation(self, player, params, reason) -> bool:
        return self.government.take_occupation(params["occupation"], player, reason=reason)

    def _do_leave_occupation(self, player, params, reason) -> bool:
        return self.government.leave_occupation(params["occupation"], player, reason=reason)

    def _do_role_command(self, player, params, reason) -> bool:
        return get_interface(params["interface"]).perform(params["command"], player, params.get("text", ""), reason=reason)

    # ------------------------------------------------------------------ #
    # Observation
    # ------------------------------------------------------------------ #
    def observe(self, player: Player) -> Dict[str, Any]:
        """Everything `player` can see, as plain data (no live objects), so it can be sent anywhere."""
        gov, vm = self.government, self.voting
        gtype = gov.government_type
        progress = gov.next_age_progress()
        research = self.innovation_manager.research_progress()
        return {
            "you": player.name,
            "time": self.clock,
            "date": format_date(self.clock),
            "year": self.year,
            "season": season_of(self.clock),
            "your_turn": player is self.acting,
            "free": self.is_free(player) or self.free_at[player.name] <= self.clock,
            "busy_until": None if self.is_free(player) or self.free_at[player.name] <= self.clock
            else format_date(self.free_at[player.name]),
            "contest_cooldown_hours": self.contests.cooldown_hours_left(player.name),
            "busy_hours_left": 0 if self.is_free(player) else max(0, self.free_at[player.name] - self.clock),
            # Something done on the side while busy (a campaign talk): what, and how long it has left.
            "side": ({"doing": self.talk_what.get(player.name, "talking"),
                      "hours_left": self.talk_free_at[player.name] - self.clock}
                     if self.talk_free_at.get(player.name, 0) > self.clock else
                     {"doing": "", "hours_left": 0, "can_talk": self.contests.involving(player.name) is not None
                      and any(a.type in self.TALKS for a in self.aside_actions(player))}
                     if not self.is_free(player) else None),
            "doing": self._doing(player),
            "age": {"key": gov.age.key, "name": gov.age.name},
            "next_age": None if not progress else {
                "name": progress[0].name, "needs": {name: done for name, done in progress[1]}},
            "points": int(gov.innovation_pool.points),
            "points_per_year": gov.annual_points(),
            "research_queue": list(gov.research_queue),
            "researching": None if not research else {"innovation": research[0], "points": research[1], "cost": research[2]},
            "discovered": sorted(gov.innovation_pool.discovered),
            "your_positions": gov.offices_of(player) + gov.statuses_of(player),
            "your_occupations": gov.occupations_of(player),
            "satisfaction": {k: {"name": m.name, "value": round(player.satisfaction.get(k, 50), 1),
                                 **player.content_detail.get(k, {})}
                             for k, m in society.METERS.items()},
            "working_now": self.working_now(player.name),
            "patience": society.patience_view(player),
            "ability": society.ability_detail(gov, player),
            "mood": round(society.mood(player), 1),
            "society": self._observe_society(),
            "character": {**player.sheet(), "life_stage": self.life.life_stage(player), "age": player.age,
                          "traits": list(player.traits), "life": self.life.observe_person(player)},
            "life": self.life.observe(),
            "world": environment.observe(self.clock, self.fire_temperature()),
            "activity": (lambda a: a.key if a else None)(self.activity_of(player)),
            "can_stop": self.can_interrupt(player),
            "crafts": self._observe_crafts(),
            "occupations": {
                o.name: {"icon": o.icon, "description": o.description, "seats": o.seats,
                         "holders": [p.name for p in gov.occupations[o.name]],
                         "appointed_by": gov.occupation_appointers(o), "open": gov.occupation_is_open(o),
                         "unlocked": gov.is_unlocked(o.requires), "requires": list(o.requires),
                         "attributes": list(o.attributes), "skill": o.skill, "points": o.points,
                         "rank": society.job_rank(gov, o.name),
                         "tools_ready": not o.needs_tools or any(self.possessions.ground.get(k, 0)
                                                                 for k in self.possessions.tool_options(o.needs_tools)),
                         "interfaces": list(o.interfaces), "provides": list(o.provides),
                         "feeds": society.quality_fed_by(o.name), "also_trains": dict(o.also_trains),
                         "holder_quality": {p.name: society.occupation_quality(o.name, p)
                                            for p in gov.occupations[o.name]}}
                for o in OCCUPATIONS.values()},
            "your_interfaces": gov.player_interface_keys(player),
            "research_roles": gov.research_roles(),
            "government": {
                "key": gtype.key, "name": gtype.name, "age": gtype.age_name, "description": gtype.description,
                "reformed_by": describe_method(gtype.reformed_by),
                "max_offices_per_player": gtype.max_offices_per_player,
                "member_interfaces": list(gtype.member_interfaces),
                "reform_mode": gov.reform_mode(player),
                "reform_cooldown_days": days_until(0, gov.reform_cooldown_left()),
                "years_since_reform": None if gov.last_reform_hour is None
                else (self.clock - gov.last_reform_hour) / HOURS_PER_YEAR,
                "available_reforms": [
                    {"key": g.key, "name": g.name, "age": g.age_name, "description": g.description,
                     "offices": {o.name: {"seats": o.seats, "points": o.points} for o in g.offices.values()},
                     "outcome": gov.preview_reform(g.key)}
                    for g in gov.available_reforms()],
            },
            "offices": {
                o.name: {"seats": o.seats, "points": o.points, "rank": society.job_rank(gov, f"office:{o.name}"), "holders": [p.name for p in gov.get_role_holders(o.name)],
                         "interfaces": list(o.interfaces), "description": o.description,
                         "unlocked": gov.is_unlocked(o.requires), "requires": list(o.requires),
                         "selected_by": describe_method(o.selected_by), "removed_by": describe_method(o.removed_by),
                         "persuadable": o.persuadable, "challenges": o.challenge_kinds,
                         "holder_quality": {p.name: society.office_quality(gov, o.name, p)
                                            for p in gov.get_role_holders(o.name)},
                         "protected_hours": {p.name: h for p in gov.get_role_holders(o.name)
                                             if (h := self.contests.protected_hours_left(o.name, p))},
                         "quality_skill": society.office_spec(gov, o.name).get("skill"),
                         "quality_attributes": dict(society.office_spec(gov, o.name).get("attributes", {}))}
                for o in gtype.offices.values()},
            "statuses": {
                s.name: {"holders": [p.name for p in gov.statuses.get(s.name, [])], "description": s.description,
                         "unlocked": gov.is_unlocked(s.requires), "requires": list(s.requires),
                         "granted_by": describe_method(s.granted_by), "effects": list(s.effects)}
                for s in gtype.statuses.values()},
            "players": [
                {"name": p.name, "age": p.age, "description": p.description, **p.attributes,
                 "sheet": {**p.sheet(), "life_stage": self.life.life_stage(p)}, "occupations": gov.occupations_of(p),
                 "traits": list(p.traits), "life": self.life.observe_person(p),
                 "trades": trade_skills(gov, p),
                 "occupation_quality": {o: society.occupation_quality(o, p) for o in OCCUPATIONS},
                 "office_quality": {o: society.office_quality(gov, o, p) for o in gtype.offices},
                 "satisfaction": {k: round(v, 1) for k, v in p.satisfaction.items()}, "mood": round(society.mood(p), 1),
                 "content_rising": {k: d.get("rising") for k, d in p.content_detail.items()},
                 "patience": society.patience_view(p),
                 "work_quality": society.own_work(gov, p),
                 "offices": gov.offices_of(p), "statuses": gov.statuses_of(p), "can_vote": gov.can_vote(p),
                 "busy": not self.is_free(p) and self.free_at[p.name] > self.clock, "doing": self._doing(p),
                 "last_deed": self._last_deed(p), "inventory": p.inventory.observe(),
                 "waiting_for": self._waiting_for(p)}
                for p in self.players],
            "ballots": [self._observe_ballot(b, player) for b in vm.active_votes],
            "contests": self.contests.observe(player),
            "in_contest": self._observe_in_contest(player),
            "possessions": self.possessions.observe(player),
            "camp": self._observe_camp(player),
        }

    def _observe_camp(self, player: Player) -> Dict[str, Any]:
        """The fire, the tribe's food and water, and the work this player could do (with why not)."""
        members = max(1, len(self.players))
        work = []
        for kind, table in (("work", WORK.TASKS), ("craft", WORK.RECIPES)):
            gov = self.government
            for key, t in table.items():
                job = WORK.job_for(t, gov.occupations_of(player), gov.offices_of(player))
                if not t.open_to_anyone and job is None:
                    continue
                if not gov.is_unlocked(t.requires) or (t.disposes_of_dead and not self.life.bodies):
                    continue
                work.append({"kind": kind, "key": key, "label": t.label, "problem": self.work_problem(player, kind, key),
                             "own_job": job is not None,
                             "life_hours": t.life_hours, "tools": list(t.tools), "consumes": t.consumes,
                             "yields": [dict(y) for y in t.yields], "skill": t.skill,
                             "quality": round(self.work_quality(player, t), 1), "fire_life_hours": t.fire_life_hours,
                             "site": t.site, "site_known": bool(t.site and self.site_known(t.site)),
                             "scouts_for": t.scouts_for,
                             "find_chance": round(WORK.site_find_chance(self.work_quality(player, t)), 2)
                             if t.scouts_for else None,
                             "scout_items": [y["item"] for x in WORK.site_tasks(t.scouts_for) for y in x.yields]
                             if t.scouts_for else [],
                             "chance": round(WORK.trip_chance(t, self.work_quality(player, t),
                                                              bool(t.site and self.site_known(t.site))), 2),
                             "finds_sites": t.finds_sites, "disposes_of_dead": t.disposes_of_dead,
                             "illness_risk": t.illness_risk})
        return {"fire_hours_left": round(self.fire_hours_left(), 2),
                "fire_max_hours": WORK.FIRE.get("max_life_hours", 14),
                "food": round(self.possessions.supply("food")), "water": round(self.possessions.supply("water")),
                "food_per_member": round(self.possessions.supply("food") / members, 1),
                "store_food_per_member": round(self.possessions.store_supply("food") / members, 1),
                "store_water_per_member": round(self.possessions.store_supply("water") / members, 1),
                "water_per_member": round(self.possessions.supply("water") / members, 1),
                "stock_targets": {k: v for k, v in WORK.STOCK_TARGETS.items() if k in self._wanted_items()},
                "tools_waited_for": self.possessions.tools_waited_for(),
                "sites": [self._site_view(x) for x in self.sites if x["loads"] > 0 and x["until"] > self.clock],
                "spent_sites": [self._site_view(x) for x in reversed(self.spent_sites)],
                "useful_sites": self.useful_site_kinds(),
                "work": work, "worked_recently": self.work_activity(player.name) >= 1.0,
                "work_activity": {p.name: round(self.work_activity(p.name), 2) for p in self.players}}

    def _observe_crafts(self) -> Dict[str, Any]:
        """The crafting chart (F12): every item the tribe can make or find in this age (and earlier ones),
        what it takes (work, research, tools, materials), what it is used for, and whether it can be had
        now. Plain data, so another client can draw the same chart."""
        from innovations.innovation import ALL_INNOVATIONS
        gov, store = self.government, self.possessions.ground
        held = {name: [p.name for p in holders] for name, holders in gov.occupations.items()}

        def needed(t) -> List[str]:
            """The work's own research, plus a job's when none of the jobs that do it is open yet."""
            reqs = list(t.requires)
            jobs = [OCCUPATIONS[o] for o in t.occupations if o in OCCUPATIONS]
            if jobs and not any(gov.is_unlocked(o.requires) for o in jobs):
                reqs += [r for r in jobs[0].requires if r not in reqs]
            return reqs

        def research(t):
            return [{"name": r, "done": gov.is_unlocked([r])} for r in needed(t)]

        def in_age(t) -> bool:
            return all(ALL_INNOVATIONS[r].age_index <= gov.age_index for r in needed(t) if r in ALL_INNOVATIONS)

        def workers(t) -> List[str]:
            if not t.occupations:
                return [p.name for p in self.players]
            return [n for o in t.occupations for n in held.get(o, [])]

        def status(t, inputs) -> Tuple[str, str]:
            missing = [r for r in needed(t) if not gov.is_unlocked([r])]
            if missing:
                return "research", f"needs {', '.join(missing)}"
            if not workers(t):
                return "no_worker", f"nobody is a {' or '.join(t.occupations)}"
            if t.tools and not any(store.get(x, 0) or any(p.inventory.count(x) for p in self.players) for x in t.tools):
                return "no_tool", f"needs a {' or '.join(ITEMS[x].name for x in t.tools)}"
            short = [s for s in inputs if store.get(s["item"], 0) < s["count"]]
            if short:
                return "short", "store short of " + ", ".join(ITEMS[s["item"]].name for s in short)
            return "ready", "can be made now" if t.recipe else "being found"

        uses: Dict[str, List[str]] = {}
        used_by: Dict[str, Dict[str, List[str]]] = {}  # item -> job ('everyone' for anyone) -> what for

        def use_by(item: str, t, what: str):
            for job in (t.occupations or ["everyone"]):
                whats = used_by.setdefault(item, {}).setdefault(job, [])
                if what not in whats:
                    whats.append(what)

        for t in [*WORK.TASKS.values(), *WORK.RECIPES.values()]:
            if not in_age(t):
                continue
            label = t.label[0].lower() + t.label[1:]
            for x in t.tools:
                mult = t.tool_yields.get(x, 1.0)
                use_by(x, t, label + (f" x{mult:g}" if mult != 1.0 else ""))
            for x, mult in t.boost.items():
                use_by(x, t, f"{label} x{mult:g}")
            for x, stacks in t.tool_consumes.items():
                for st in stacks:
                    use_by(st["item"], t, f"{label} with a {ITEMS[x].name.lower()}")
            for st in t.consumes:
                use_by(st["item"], t, f"to make {ITEMS[t.yields[0]['item']].name.lower()}" if t.recipe else label)
            for x in t.tools:
                uses.setdefault(x, []).append(f"tool for: {t.label}")
            for x, mult in t.boost.items():
                uses.setdefault(x, []).append(f"{t.label}: {mult:g}x the yield")
            for x, stacks in t.tool_consumes.items():
                for st in stacks:
                    uses.setdefault(st["item"], []).append(f"used up by: {t.label} with a {ITEMS[x].name}")
            for st in (t.consumes if not t.recipe else []):
                uses.setdefault(st["item"], []).append(f"used up by: {t.label}")
            if t.recipe:
                for st in t.consumes:
                    uses.setdefault(st["item"], []).append(f"to make: {ITEMS[t.yields[0]['item']].name}")
        for occ in OCCUPATIONS.values():
            for x in occ.needs_tools:
                uses.setdefault(x, []).append(f"a {occ.name} can't work without one")
        for key, item in ITEMS.items():
            for need, amount in item.use.items():
                uses.setdefault(key, []).append(f"{item.use_label.lower()}: +{amount:g} {need}")
                whats = used_by.setdefault(key, {}).setdefault("everyone", [])
                what = {"food": "eating", "water": "drinking", "health": "healing"}.get(need, need)
                if what not in whats:
                    whats.append(what)

        recipes, sources = [], []
        for key, t in WORK.RECIPES.items():
            if not in_age(t):
                continue
            out = t.yields[0]
            inputs = [dict(s) for s in t.consumes]
            st, why = status(t, inputs)
            recipes.append({"key": key, "item": out["item"], "count": int(out["amount"]), "occupations": list(t.occupations),
                            "workers": workers(t), "research": research(t), "inputs": inputs,
                            "have": {s["item"]: store.get(s["item"], 0) for s in inputs},
                            "life_hours": t.life_hours, "skill": t.skill, "status": st, "why": why})
        for key, t in WORK.TASKS.items():
            if not in_age(t) or not t.yields:
                continue
            st, why = status(t, [dict(s) for s in t.consumes])
            sources.append({"key": key, "label": t.label, "occupations": list(t.occupations), "workers": workers(t),
                            "research": research(t), "tools": list(t.tools), "consumes": [dict(s) for s in t.consumes],
                            "yields": [{"item": y["item"], "amount": y["amount"], "chance": y.get("chance", 1.0)}
                                       for y in t.yields],
                            "life_hours": t.life_hours, "status": st, "why": why})
        return {"age": gov.age.name, "recipes": recipes, "sources": sources,
                "uses": uses, "used_by": used_by, "store": {k: v for k, v in store.items() if v > 0}}

    def _wanted_items(self) -> set:
        """What the tribe has a use for now: food, water, and whatever an unlocked task or recipe uses or
        makes (no point stockpiling flint before anyone can knap it)."""
        gov = self.government
        wanted = {"food", "water"}
        for t in [*WORK.TASKS.values(), *WORK.RECIPES.values()]:
            if not gov.is_unlocked(t.requires):
                continue
            wanted.update(s["item"] for s in t.consumes)
            wanted.update(t.tools)
            for stacks in t.tool_consumes.values():
                wanted.update(s["item"] for s in stacks)
            if t.recipe:
                wanted.update(y["item"] for y in t.yields)
        return wanted

    def _observe_in_contest(self, player: Player) -> Optional[Dict[str, Any]]:
        """The challenge this player is a contestant in, and what they may still do meanwhile."""
        rule = self.contests.restriction(player.name)
        if rule is None:
            return None
        c = rule["contest"]
        return {"key": c.key, "kind": c.kind, "name": kind_name(c.kind), "style": CHALLENGE_KINDS[c.kind].style,
                "opponent": c.defender if c.challenger == player.name else c.challenger, "office": c.office,
                "locked": rule["locked"], "may": sorted(rule["may"])}

    def _observe_society(self) -> Dict[str, Any]:
        if not self.qualities:
            self.qualities = society.compute_qualities(self.government)
        return {"score": society.society_score(self.qualities), "qualities": self.qualities}

    def _waiting_for(self, player: Player) -> Optional[str]:
        """'a Wooden Spear' when every piece of this player's job work needs a tool there is none of (they
        were appointed before one was made, or it broke), else None."""
        gov = self.government
        tasks = [t for job in gov.jobs_of(player) for t in WORK.tasks_of_job(job) if gov.is_unlocked(t.requires)]
        if not tasks or any(not t.tools or self.possessions.find_tool(player, t.tools) for t in tasks):
            return None
        return "a " + " or ".join(dict.fromkeys(ITEMS[k].name for t in tasks for k in t.tools))

    def _doing(self, player: Player) -> Optional[str]:
        """What the player is busy with ('voting', 'researching Fire Making'), or None if free."""
        if self.is_free(player) or self.free_at[player.name] <= self.clock:
            return None
        last = self.last_action.get(player.name)
        if not last:
            return "busy"
        verbs = {"vote": "voting", "nominate": "nominating", "appoint": "appointing", "dismiss": "dismissing",
                 "call_vote": "calling a vote", "reform": "reforming", "research": "researching",
                 "role_command": "on duty", "wait": "resting", "take_occupation": "starting work as", "resign": "resigning as",
                 "leave_occupation": "leaving work as", "collapse": "recovering (collapsed)",
                 "persuade": "starting to persuade for", "canvass": "persuading", "rally": "rallying",
                 "decline_nomination": "declining a nomination", "treat": "being tended by the healer",
                 "heal": "healing"}
        if last["type"] in ("work", "craft"):
            t = WORK.work(last["type"], last["params"].get("task") or last["params"].get("recipe"))
            return (t.label[0].lower() + t.label[1:]) if t else "working"
        if last["type"] == "activity":
            a = self.life.activity(last["params"].get("activity", "")) or {"label": "playing"}
            return a["label"][0].lower() + a["label"][1:]
        if last["type"] in ("challenge", "contest", "answer_challenge"):
            p = last["params"]
            c = self.contests.contest(p["contest"]) if p.get("contest") else None
            other = p.get("holder") or p.get("opponent") or (c.challenger if c else "")
            if last["type"] == "challenge" and not p.get("kind"):
                return f"challenging {other}"
            return f"{kind_name(p['kind']).lower()} vs {other}"
        if last["type"] == "care":
            return {"eat": "eating", "drink": "drinking", "sleep": "sleeping", "warm_up": "warming up"}.get(
                last["params"]["kind"], CHARACTER.care_actions[last["params"]["kind"]].label.lower())
        verb = verbs.get(last["type"], last["type"])
        detail = (last["params"].get("innovation") or last["params"].get("candidate") or last["params"].get("appointee")
                  or last["params"].get("occupation") or last["params"].get("listener") or last["params"].get("office"))
        return f"{verb} {detail}" if detail else verb

    def _last_deed(self, player: Player) -> Optional[str]:
        """The player's latest action other than resting, in a few words ('voted Hiro')."""
        last = self.last_deeds.get(player.name)
        if not last:
            return None
        p = last["params"]
        words = {"vote": f"voted {p.get('choice', '')}", "nominate": f"nominated {p.get('candidate', '')}",
                 "appoint": f"appointed {p.get('appointee', '')}", "dismiss": f"dismissed {p.get('holder', '')}",
                 "call_vote": "called a vote", "reform": "proposed reform", "research": f"queued {p.get('innovation', '')}",
                 "role_command": "gave an order", "take_occupation": f"became {p.get('occupation', '')}",
                 "leave_occupation": f"quit as {p.get('occupation', '')}",
                 "decline_nomination": "declined a nomination", "resign": f"resigned as {p.get('office', '')}",
                 "work": f"worked ({p.get('task', '').replace('_', ' ')})",
                 "craft": f"made {ITEMS[p['recipe']].name if p.get('recipe') in ITEMS else 'something'}",
                 "persuade": f"campaigned for {p.get('office', '')}", "canvass": f"won over {p.get('listener', '')}",
                 "rally": f"rallied {p.get('listener', '')}", "challenge": f"challenged {p.get('holder', '')}",
                 "treat": "saw the healer", "heal": f"healed {p.get('patient', '')}", "activity": last.get("group") == "study" and "studied" or "played"}
        if last["type"] == "care":
            return None
        return words.get(last["type"], last["type"])

    def _observe_ballot(self, b, player: Player) -> Dict[str, Any]:
        deadline = b.next_deadline()
        if isinstance(b, VotingSystem):
            phase_hours = b.nomination_hours if b.is_nomination_open else b.voting_hours
        else:
            phase_hours = MOTION_HOURS
        data: Dict[str, Any] = {"key": b.key, "label": b.label, "voting": b.is_voting_active(),
                                "phase_days": max(1, phase_hours // HOURS_PER_DAY),
                                "choices": b.choices(), "ranked": b.ranked,
                                "closes": format_date(deadline) if deadline is not None else None,
                                "days_left": days_until(self.clock, deadline) if deadline is not None else None,
                                "you_can_vote": b.in_electorate(player), "you_voted": b.has_voted(player),
                                "votes_cast": sum(1 for v in b.votes.values() if v), "electorate_size": len(b.votes)}
        if isinstance(b, VotingSystem):
            standing = b.nominations if b.is_nomination_open else b.choices()
            data.update({"kind": "election", "office": b.role, "nominating": b.is_nomination_open,
                         "nominations": list(b.nominations), "nominated_by": dict(b.nominated_by),
                         "declined": list(b.declined), "you_stand": player.name in standing})
        elif isinstance(b, Motion):
            data.update({"kind": b.kind, "subject": b.subject, "target": b.target.name if b.target else None,
                         "proposer": b.proposer.name, "nominating": False})
        return data

    # ------------------------------------------------------------------ #
    # Saving
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        return {
            "players": [p.name for p in self.players],
            "roster": [p.roster_entry() for p in self.players],  # who is alive (births and deaths change it)
            "life": self.life.to_dict(),
            "characters": {p.name: p.character_state() for p in self.players},
            "clock": self.clock,
            "free_at": dict(self.free_at),
            "events": [list(e) for e in sorted(self.events)],
            "seq": self._seq,
            "government": self.government.to_dict(),
            "voting": self.voting.to_dict(),
            "contests": self.contests.to_dict(),
            "qualities": self.qualities,
            "contest_rules": 2,  # contestants act during a contest (older saves held them busy)
            "last_action": self.last_action,  # what each person is doing (sleeping, eating...)
            "last_deeds": self.last_deeds,
            "resting": sorted(self.resting),
            "ballot_stages": sorted([list(x) for x in self._ballot_stages]),
            "possessions": self.possessions.to_dict(),
            "fire_until": self.fire_until,
            "quality_levels": dict(self.quality_levels),
            "quality_shocks": dict(self.quality_shocks),
            "last_worked": dict(self.last_worked),
            "meals": dict(self.meals),
            "sites": [dict(x) for x in self.sites],
            "spent_sites": [dict(x) for x in self.spent_sites],
            "next_site_id": self.next_site_id,
            "aside_checked": dict(self.aside_checked),
            "aside_looked": dict(self.aside_looked),
            "talk_free_at": dict(self.talk_free_at),
            "talk_what": dict(self.talk_what),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], players: Optional[List[Player]] = None) -> 'GameEngine':
        if players is None and "roster" in data:
            players = [Player.from_roster(e) for e in data["roster"]]  # the tribe as it was, born and lost
        elif players is None:
            # A save from before births and deaths: the same people, as players.json describes them now.
            by_name = {p.name: p for p in load_players()}
            if all(n in by_name for n in data["players"]):
                players = [by_name[n] for n in data["players"]]
        engine = cls(players)
        names = [p.name for p in engine.players]
        if names != data["players"]:
            raise ValueError("The saved game's players don't match data/players.json "
                             f"(saved: {', '.join(data['players'])}; now: {', '.join(names)})")
        engine.game_state.clock = data["clock"]
        engine.free_at = dict(data["free_at"])
        engine.events = [tuple(e) for e in data["events"]]
        heapq.heapify(engine.events)
        engine._seq = data["seq"]
        for p in engine.players:
            p.load_character_state(data.get("characters", {}).get(p.name, {}))
        engine.government.load_state(data["government"], engine.player)
        engine.voting.load_state(data["voting"], engine.player)
        engine.contests.load_state(data.get("contests", {}))
        engine.possessions.load_state(data.get("possessions", {}))
        engine.life.load_state(data.get("life", {}))
        engine.fire_until = data.get("fire_until", engine.clock + environment.life_hours_to_calendar(
            WORK.FIRE.get("start_life_hours", 8)))
        engine.last_worked.update({k: v for k, v in data.get("last_worked", {}).items() if k in engine.last_worked})
        if "last_worked" not in data:
            engine.last_worked = {name: engine.clock for name in engine.last_worked}
        engine.meals = dict(data.get("meals", {}))
        engine.quality_levels = {k: float(v) for k, v in data.get("quality_levels", {}).items()}
        engine.quality_shocks = {k: float(v) for k, v in data.get("quality_shocks", {}).items()}
        engine.aside_checked = dict(data.get("aside_checked", {}))
        engine.aside_looked = dict(data.get("aside_looked", {}))
        engine.talk_free_at = dict(data.get("talk_free_at", {}))
        engine.talk_what = dict(data.get("talk_what", {}))
        sites = data.get("sites", [])
        if isinstance(sites, dict):  # older saves: one place per kind, good for a number of trips
            sites = [dict(v, kind=k, id=i + 1, loads=float(v.get("trips", 1)), total=float(v.get("trips", 1)),
                          found=v["until"]) for i, (k, v) in enumerate(sites.items())]
        engine.sites = [dict(x) for x in sites if x.get("kind") in WORK.SITE_KINDS]
        engine.spent_sites = [dict(x) for x in data.get("spent_sites", []) if x.get("kind") in WORK.SITE_KINDS]
        engine.next_site_id = int(data.get("next_site_id", 1 + max((x["id"] for x in engine.sites), default=0)))
        for c in engine.contests.contests if "contest_rules" not in data else []:
            if not c.is_persuasion and not c.awaiting_answer and not engine.contests.is_locked_in(c):
                for name in (c.challenger, c.defender):  # older saves held contestants busy until the end
                    if name and engine.free_at.get(name, 0) >= c.ends:
                        engine.free_at[name] = engine.clock
        engine.qualities = data.get("qualities", {})
        engine.last_action = dict(data.get("last_action", {}))
        engine.last_deeds = dict(data.get("last_deeds", {}))
        engine.resting = set(data.get("resting", []))
        if "ballot_stages" in data:
            engine._ballot_stages = {tuple(x) for x in data["ballot_stages"]}
        engine.started = True
        return engine

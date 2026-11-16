"""Production: doing the work of an age. Jobs' tasks and recipes, tools and what they use up, trips and the
good places found for them, the communal fire, and what all of that brings into the shared store.

The engine (core/engine.py) knows only that people 'work' and 'craft' and that work finishes later; what the
work is and what it does comes from the data of the ages (core/work.py: data/ages/<age>/occupations/ and
work.json, with the numbers of data/rules/work.json). A task says what it does with plain fields ('yields',
'site', 'finds_sites', 'makes_sites', 'fire_life_hours', 'tools'...), and this module carries them out, so a
new age's occupations work by being written down, with no code of their own.

Like Life (core/life.py) and Possessions (core/possessions.py) this is one of the engine's managers: it keeps
its own state (who last worked, the fire, the places found), saves and loads it, and shows it to players
through observe().
"""
import random
from typing import Any, Dict, List, Optional, Tuple

from core import society
from core import work as WORK
from core.actions import Action
from core.calendar import DAYS_PER_YEAR
from core.occupations import OCCUPATIONS
from utils.messages import Messages
from world import environment
from world.character import RULES as CHARACTER
from world.items import ITEMS, describe
from world.player import Player


class Production:
    def __init__(self, engine):
        self.engine = engine
        self.fire_until: int = 0  # the communal fire burns until then (a task with 'fire_life_hours' feeds it)
        self.last_worked: Dict[str, int] = {p.name: 0 for p in engine.players}  # when each last finished own work
        # Good places found (or made), oldest first: {'id', 'kind', 'by', 'loads', 'total', 'found', 'until'};
        # and the last few used up or lost, for the Found places panel (rules/work.json 'sites').
        self.sites: List[Dict[str, Any]] = []
        self.spent_sites: List[Dict[str, Any]] = []
        self.next_site_id = 1

    # The engine's state this manager works with.
    @property
    def government(self):
        return self.engine.government

    @property
    def possessions(self):
        return self.engine.possessions

    @property
    def life(self):
        return self.engine.life

    @property
    def clock(self) -> int:
        return self.engine.clock

    @property
    def players(self) -> List[Player]:
        return self.engine.players

    @property
    def free_at(self) -> Dict[str, int]:
        return self.engine.free_at

    @property
    def last_action(self) -> Dict[str, Dict[str, Any]]:
        return self.engine.last_action

    def player(self, name: str) -> Optional[Player]:
        return self.engine.player(name)

    def start(self):
        """A new game: the fire is burning."""
        self.fire_until = self.clock + environment.life_hours_to_calendar(WORK.FIRE.get("start_life_hours", 8))

    def add_person(self, name: str):
        self.last_worked[name] = 0

    def forget(self, name: str):
        self.last_worked.pop(name, None)

    def daily(self):
        self._expire_sites()

    def start_work(self, player: Player, kind: str, key: str, reason) -> bool:
        return self._start_work(player, kind, key, reason)

    def finish_work(self, data: Dict[str, Any]):
        self._event_work_done(data)

    def work_hours(self, kind: str, key: str, player: Optional[Player] = None) -> float:
        """Day-night hours a piece of work takes: quicker with one of its speed tools in the pack."""
        t = WORK.work(kind, key)
        hours = t.life_hours if t else 1
        if t and player is not None and t.speed_tools:
            held = [x for k, x in t.speed_tools.items() if player.inventory.count(k)]
            hours /= max(held, default=1.0)
        return hours

    def doing(self, kind: str, params: Dict[str, Any]) -> str:
        """'forage for plants' for the chronicle and the panels."""
        t = WORK.work(kind, params.get("task") or params.get("recipe"))
        return (t.label[0].lower() + t.label[1:]) if t else "working"

    # ------------------------------------------------------------------ #
    # Who is working, and the fire
    # ------------------------------------------------------------------ #
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

    def fire_hours_left(self) -> float:
        """Day-night hours the fire will still burn without more wood."""
        return max(0, self.fire_until - self.clock) / environment.HOURS_PER_LIFE_HOUR

    # ------------------------------------------------------------------ #
    # Tasks and recipes
    # ------------------------------------------------------------------ #
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
            return f"nobody lies dead in {self.engine.terms()['home']}" if not self.life.bodies \
                else "someone is already seeing to the dead"
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
        self.engine.schedule(self.clock + self.engine.duration(Action(kind, {"task" if kind == "work" else "recipe": key}), player),
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
        skill (the office's 'quality' in data/ages/<age>/governments, e.g. Clan Leader: leadership)."""
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
            store = self.engine.terms()["store_name"]
            where = ("keeps it all" if not shared else f"puts it all in the {store}" if not kept else
                     f"keeps {describe(kept)}, the rest to the {store}")
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
    # Sites: good places found or made, where trips succeed far more often
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

    # ------------------------------------------------------------------ #
    # What players see
    # ------------------------------------------------------------------ #
    def observe(self, player: Player) -> Dict[str, Any]:
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

    def observe_crafts(self) -> Dict[str, Any]:
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

    def waiting_for(self, player: Player) -> Optional[str]:
        """'a Wooden Spear' when every piece of this player's job work needs a tool there is none of (they
        were appointed before one was made, or it broke), else None."""
        gov = self.government
        tasks = [t for job in gov.jobs_of(player) for t in WORK.tasks_of_job(job) if gov.is_unlocked(t.requires)]
        if not tasks or any(not t.tools or self.possessions.find_tool(player, t.tools) for t in tasks):
            return None
        return "a " + " or ".join(dict.fromkeys(ITEMS[k].name for t in tasks for k in t.tools))

    # ------------------------------------------------------------------ #
    # Saving
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        return {"fire_until": self.fire_until, "last_worked": dict(self.last_worked),
                "sites": [dict(x) for x in self.sites], "spent_sites": [dict(x) for x in self.spent_sites],
                "next_site_id": self.next_site_id}

    def load_state(self, data: Dict[str, Any]):
        self.fire_until = data.get("fire_until", self.clock + environment.life_hours_to_calendar(
            WORK.FIRE.get("start_life_hours", 8)))
        self.last_worked.update({k: v for k, v in data.get("last_worked", {}).items() if k in self.last_worked})
        if "last_worked" not in data:
            self.last_worked = {name: self.clock for name in self.last_worked}
        sites = data.get("sites", [])
        if isinstance(sites, dict):  # older saves: one place per kind, good for a number of trips
            sites = [dict(v, kind=k, id=i + 1, loads=float(v.get("trips", 1)), total=float(v.get("trips", 1)),
                          found=v["until"]) for i, (k, v) in enumerate(sites.items())]
        self.sites = [dict(x) for x in sites if x.get("kind") in WORK.SITE_KINDS]
        self.spent_sites = [dict(x) for x in data.get("spent_sites", []) if x.get("kind") in WORK.SITE_KINDS]
        self.next_site_id = int(data.get("next_site_id", 1 + max((x["id"] for x in self.sites), default=0)))

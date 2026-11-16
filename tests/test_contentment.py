"""Contentment (data/rules/society.json 'satisfaction'): Work rises only while someone works their job, faster
with the right tools and a wide choice of work for the age; Comfort follows a tended fire, care and the
Spirit Keeper's rituals; Safety follows Warriors on patrol and filled positions; Leaders follows
everything else, and slowly for someone appointed to work they are poorly suited for."""
import random
import unittest

from core import society
from core.engine import GameEngine
from core.occupations import OCCUPATIONS, Occupation
from tests.helpers import become_actor, find, new_engine, seat

METERS = society.METERS
VALUES = society.INPUT_VALUES


def factor(meter_key: str, person, gov, rose=None, key=None):
    """The multiplier `key` (default: the product of all) on how fast this meter rises for `person`."""
    total, factors = society.rise_multiplier(METERS[meter_key], person, gov, society.contentment_context(gov), rose)
    if key is None:
        return total
    return next((f["mult"] for f in factors if f["key"] == key), None)


class Base(unittest.TestCase):
    def setUp(self):
        self.e = new_engine()
        self.gov = self.e.government
        for p in self.e.players:
            p.inventory.load([])

    def start(self, name: str, task: str):
        p = become_actor(self.e, name)
        action = find(self.e, p, "work", task=task)
        self.assertIsNotNone(action, f"{name} cannot {task}: {self.e.work_problem(p, 'work', task)}")
        self.assertTrue(self.e.apply(p, action))
        return p

    def give_job(self, name: str, job: str):
        p = self.e.player(name)
        self.gov.occupations[job].append(p)
        return p

    def update(self, people, days: float = 0.5):
        society.update_satisfaction(people, self.gov, self.e.qualities, 60, days)


class WorkContentTest(Base):
    def test_work_rises_only_while_working_the_job(self):
        bob = self.give_job("Bob", "Gatherer")
        bob.satisfaction["work"] = 40
        self.update([bob])
        idle = bob.satisfaction["work"]
        self.assertLess(idle, 40)  # holding the job is not enough
        self.start("Bob", "forage")
        self.assertEqual(self.e.working_now("Bob"), "Gatherer")
        self.update([bob])
        self.assertGreater(bob.satisfaction["work"], idle)
        self.assertTrue(bob.content_detail["work"]["rising"])

    def test_holding_a_job_is_worth_little_and_no_job_less(self):
        bob, cleo = self.give_job("Bob", "Gatherer"), self.e.player("Cleo")
        ctx = society.contentment_context(self.gov)
        with_job = society.meter_target(METERS["work"], bob, self.gov, self.e.qualities, 60, ctx)
        without = society.meter_target(METERS["work"], cleo, self.gov, self.e.qualities, 60, ctx)
        self.assertEqual(with_job, VALUES["working"]["idle_with_job"])
        self.assertEqual(without, VALUES["working"]["idle_without_job"])
        self.assertLess(without, with_job)
        self.assertLess(with_job, society.SATISFACTION["start"])

    def test_chores_outside_ones_job_are_not_working_it(self):
        from core import work as WORK
        self.give_job("Bob", "Gatherer")
        task = WORK.TASKS["fetch_water"]
        saved = task.occupations
        task.occupations = []  # a task open to anyone (work.json lists none at the moment): not the job's work
        try:
            self.start("Bob", "fetch_water")
            self.assertIsNone(self.e.working_now("Bob"))
        finally:
            task.occupations = saved

    def test_the_right_tools_speed_the_rise_and_more_than_one_faster(self):
        self.gov.innovation_pool.discovered.update({"Hunting", "Toolmaking", "Archery"})
        bob = self.give_job("Bob", "Hunter")
        none = factor("work", bob, self.gov, key="tools")
        bob.inventory.add("wooden_spear", 1)
        one = factor("work", bob, self.gov, key="tools")
        bob.inventory.add("bow", 1)
        two = factor("work", bob, self.gov, key="tools")
        self.assertLess(none, one)
        self.assertLess(one, two)
        self.assertEqual(self.e.production.job_tools(bob), (2, True))

    def test_no_tool_is_missed_before_one_exists(self):
        bob = self.give_job("Bob", "Gatherer")  # a hand axe helps, but nobody can make one yet
        self.assertEqual(self.e.production.job_tools(bob), (0, False))
        before = factor("work", bob, self.gov, key="tools")
        self.assertEqual(before, METERS["work"].multipliers["tools"]["none_invented"])
        self.gov.innovation_pool.discovered.add("Toolmaking")
        self.assertLess(factor("work", bob, self.gov, key="tools"), before)

    def test_choice_of_work_is_relative_to_the_age(self):
        n_open, possible = society.job_variety(self.gov)
        self.assertEqual(possible, len(OCCUPATIONS))  # every occupation so far is of the Tribal Age
        self.assertLess(n_open, possible)
        bob = self.give_job("Bob", "Gatherer")
        few = factor("work", bob, self.gov, key="job_variety")
        for o in OCCUPATIONS.values():
            self.gov.innovation_pool.discovered.update(o.requires)
        self.assertEqual(society.job_variety(self.gov), (possible, possible))
        all_tribal = factor("work", bob, self.gov, key="job_variety")
        self.assertGreater(all_tribal, few)
        # A later age with many more kinds of work: the same open jobs are now little choice.
        later = {f"Later job {i}": Occupation(f"Later job {i}", "", "", None, [], False, ["strength"], None,
                                              requires=["Writing"], age_index=1) for i in range(15)}
        OCCUPATIONS.update(later)
        try:
            self.gov.age_index = 1
            self.assertEqual(society.job_variety(self.gov), (possible, possible + 15))
            self.assertLess(factor("work", bob, self.gov, key="job_variety"), 1.0)
        finally:
            for k in later:
                OCCUPATIONS.pop(k)
            self.gov.age_index = 0


class ComfortAndSafetyTest(Base):
    def test_fire_tended_untended_or_out(self):
        e = self.e
        self.assertEqual(e.fire_state(), "untended")  # it burns at the start, but nobody keeps it
        bob = self.give_job("Bob", "Firekeeper")
        e.production.last_worked["Bob"] = e.clock
        self.assertEqual(e.fire_state(), "tended")
        e.production.fire_until = e.clock
        self.assertEqual(e.fire_state(), "out")
        self.assertIsNotNone(bob)

    def test_the_fire_pleases_only_when_people_warm_up_at_it(self):
        e = self.e
        cleo = e.player("Cleo")
        level = society.compute_qualities(self.gov)["fire"]["value"]
        target = society.meter_target(METERS["comfort"], cleo, self.gov, society.compute_qualities(self.gov), 60)
        for state in ("tended", "untended", "out"):  # a fire merely burning (or not) changes nothing
            self.gov.fire_state = lambda s=state: s
            self.assertEqual(society.compute_qualities(self.gov)["fire"]["value"], level)
        e.production.fire_until = e.clock + 10 ** 5
        cleo.needs["warmth"] = 30
        p = become_actor(e, "Cleo")
        self.assertTrue(e.apply(p, find(e, p, "care", kind="warm_up")))
        q = society.compute_qualities(self.gov)
        self.assertEqual(q["fire"]["value"], level + society.QUALITIES["fire"].per_use)
        self.assertGreater(society.meter_target(METERS["comfort"], cleo, self.gov, q, 60), target)
        e._settle_qualities(1.0)  # with nobody warming up, it stays where it is
        self.assertEqual(society.compute_qualities(self.gov)["fire"]["value"], level + society.QUALITIES["fire"].per_use)

    def test_spirit_keeper_ritual_comforts_everyone_and_counts_toward_care(self):
        esi, cleo = self.e.player("Esi"), self.e.player("Cleo")
        seat(self.gov, "Spirit Keeper", esi)
        self.e.production.last_worked["Esi"] = self.e.clock
        care_before = society.compute_qualities(self.gov)["care"]["value"]
        before = factor("comfort", cleo, self.gov)
        self.start("Esi", "lead_ritual")
        self.assertEqual(self.e.working_now("Esi"), "office:Spirit Keeper")
        self.assertGreater(factor("comfort", cleo, self.gov), before)
        self.assertGreater(society.compute_qualities(self.gov)["care"]["value"], care_before)

    def test_an_idle_spirit_keeper_gives_no_care(self):
        esi = self.e.player("Esi")
        seat(self.gov, "Spirit Keeper", esi)
        self.e.production.last_worked["Esi"] = self.e.clock - 10 ** 7  # has not worked in ages
        self.assertEqual(society.compute_qualities(self.gov)["care"]["detail"]["supply"], 0)

    def test_warriors_on_patrol_raise_safety(self):
        self.gov.innovation_pool.discovered.update({"Toolmaking"})
        self.e.possessions.deliver([{"item": "wooden_spear", "count": 2}])
        bob, cleo = self.give_job("Bob", "Warrior"), self.e.player("Cleo")
        self.e.production.last_worked["Bob"] = self.e.clock
        safety_before = society.compute_qualities(self.gov)["safety"]["value"]
        before = factor("safety", cleo, self.gov, key="working_now:Warrior")
        self.start("Bob", "patrol")
        self.assertGreater(society.compute_qualities(self.gov)["safety"]["value"], safety_before)
        self.assertGreater(factor("safety", cleo, self.gov, key="working_now:Warrior"), before)
        self.assertIsNotNone(bob)

    def test_empty_positions_slow_safety(self):
        gov, people = self.gov, self.e.players
        for office, holders in (("Clan Leader", people[:1]), ("Elder", people[1:4]), ("Spirit Keeper", people[4:5])):
            for p in holders:
                seat(gov, office, p)
        self.give_job(people[5].name, "Gatherer")
        self.give_job(people[6].name, "Firekeeper")
        filled, total = society.positions_filled(gov)
        self.assertEqual(filled, total)
        cleo = people[7]
        full = factor("safety", cleo, gov, key="positions_filled")
        gov.remove_office("Elder", people[1], announce=False)  # two of three Elders
        self.assertEqual(society.positions_filled(gov), (filled - 1, total))
        self.assertLess(factor("safety", cleo, gov, key="positions_filled"), full)

    def test_a_job_nobody_can_take_up_is_not_an_empty_position(self):
        _, total = society.positions_filled(self.gov)
        self.gov.innovation_pool.discovered.add("Hunting")  # Hunters need a spear, and there is none
        self.assertEqual(society.positions_filled(self.gov)[1], total)
        self.e.possessions.deliver([{"item": "wooden_spear", "count": 1}])
        self.assertEqual(society.positions_filled(self.gov)[1], total + 1)


class LeadersContentTest(Base):
    def test_leaders_reflect_everything_else(self):
        cleo = self.e.player("Cleo")
        for k in METERS["leaders"].depends_on:
            cleo.satisfaction[k] = 90
        high = society.meter_target(METERS["leaders"], cleo, self.gov, self.e.qualities, 60)
        for k in METERS["leaders"].depends_on:
            cleo.satisfaction[k] = 20
        low = society.meter_target(METERS["leaders"], cleo, self.gov, self.e.qualities, 60)
        self.assertGreater(high, low + 30)
        self.assertGreater(factor("leaders", cleo, self.gov, rose={k: True for k in METERS["leaders"].depends_on}),
                           factor("leaders", cleo, self.gov, rose={}))

    def test_poorly_suited_appointees_warm_to_the_leaders_slowly(self):
        gov = self.gov
        alice, imani, bob = self.e.player("Alice"), self.e.player("Imani"), self.e.player("Bob")
        seat(gov, "Clan Leader", alice)
        gov.innovation_pool.discovered.update({"Tracking"})
        for a in ("dexterity", "wisdom"):
            imani.attributes[a] = 1
        imani.skills["scouting"] = 0
        self.assertTrue(gov.appoint(alice, "Scout", imani))
        self.assertEqual(gov.appointed_job(imani), "Scout")
        poor = factor("leaders", imani, gov, key="fit")
        self.assertLess(poor, 0.5)
        self.assertTrue(gov.take_occupation("Gatherer", bob))  # chose it themselves: no fit factor
        self.assertIsNone(factor("leaders", bob, gov, key="fit"))
        restored = GameEngine.from_dict(self.e.to_dict())
        self.assertEqual(restored.government.appointed_job(restored.player("Imani")), "Scout")


class OfficeWorkTest(Base):
    def test_office_holders_have_work_of_their_own(self):
        gov = self.gov
        seat(gov, "Elder", self.e.player("Bob"))
        seat(gov, "Clan Leader", self.e.player("Cleo"))
        seat(gov, "Spirit Keeper", self.e.player("Esi"))
        tasks = {name: {key for kind, key, _ in self.e.work_options(self.e.player(name)) if kind == "work"}
                 for name in ("Bob", "Cleo", "Esi", "Dmitri")}
        self.assertIn("hold_council", tasks["Bob"])
        self.assertIn("office_duties", tasks["Cleo"])
        self.assertIn("lead_ritual", tasks["Esi"])
        self.assertNotIn("office_duties", tasks["Esi"])  # their office has work of its own
        self.assertFalse(tasks["Dmitri"] & {"hold_council", "office_duties", "lead_ritual"})
        self.start("Cleo", "office_duties")
        self.assertEqual(self.e.working_now("Cleo"), "office:Clan Leader")

    def test_the_view_explains_what_moves_each_meter(self):
        bob = self.give_job("Bob", "Gatherer")
        self.update(self.e.players, 0.05)
        view = self.e.observe(bob)
        work = view["satisfaction"]["work"]
        self.assertIn("rising", work)
        self.assertEqual({f["key"] for f in work["factors"]}, {"tools", "job_variety", "fit"})
        self.assertIn("content_rising", view["players"][0])



class FoodShortageTest(Base):
    """Two things that let a tribe starve slowly: hungry food workers too distressed to go and get food,
    and a Food quality that read full while people went hungry (so leaders added no food workers)."""

    def test_a_hungry_gatherer_still_goes_foraging(self):
        from controllers.npc import NPCController
        bob = self.give_job("Bob", "Gatherer")
        bob.needs["food"] = 5  # starving, with nothing in the pack to eat
        self.e.production.last_worked["Bob"] = self.e.clock  # no "hasn't worked in a while" pull
        bob = become_actor(self.e, "Bob")
        bob.needs.update({"food": 5, "energy": 90})  # starving but not tired: no reason to sleep instead
        # (Queuing research takes a moment and may come first; this is about food work against everything else.)
        legal = [a for a in self.e.legal_actions(bob) if a.type != "research"]
        self.assertIsNotNone(find(self.e, bob, "work", task="forage"))
        npc = NPCController("Bob", random.Random(1))
        view = self.e.observe(bob)
        view["world"]["night"] = True  # at night, on a trip that may well come back empty: the worst case
        choice = npc.decide(view, legal)
        self.assertEqual((choice.action.type, choice.action.params.get("task")), ("work", "forage"), choice.reason)

    def test_food_quality_follows_what_the_tribe_holds(self):
        for name in ("Bob", "Cleo", "Dmitri", "Esi"):
            self.give_job(name, "Gatherer")
            self.e.production.last_worked[name] = self.e.clock
        for p in self.e.players:
            p.inventory.load([])
        self.e.possessions.ground.clear()
        hungry = society.compute_qualities(self.gov)["food"]
        self.e.possessions.deliver([{"item": "meat", "count": 60}, {"item": "roots", "count": 20}])
        fed = society.compute_qualities(self.gov)["food"]
        self.assertGreater(fed["value"], hungry["value"] + 20)
        # One more food worker is worth something while stocks are short, even with work enough on paper.
        self.assertGreater(society.supply_value(hungry["detail"], 1.0), hungry["value"])


class WaterTest(Base):
    def test_water_quality_follows_what_the_tribe_holds_and_gatherers(self):
        self.assertIn("water", society.quality_fed_by("Gatherer"))
        for p in self.e.players:
            p.inventory.load([])
        self.e.possessions.ground.clear()
        dry = society.compute_qualities(self.gov)["water"]
        self.e.possessions.deliver([{"item": "water", "count": 400}])
        wet = society.compute_qualities(self.gov)["water"]
        self.assertGreater(wet["value"], dry["value"] + 40)

    def test_an_overflowing_store_does_not_miss_one_worker(self):
        for name in ("Bob", "Cleo", "Dmitri", "Esi", "Farid", "Greta", "Hiro", "Imani", "Joao", "Kalani", "Leila"):
            # more than enough fetching water
            self.give_job(name, "Gatherer")
            self.e.production.last_worked[name] = self.e.clock
        self.e.possessions.deliver([{"item": "water", "count": 600}])  # and the store overflowing
        water = society.compute_qualities(self.gov)["water"]
        d = water["detail"]
        work_only = {k: v for k, v in d.items() if k != "on_hand"}
        drop = society.supply_value(d, -1.0) - water["value"]
        work_drop = (society.supply_value(work_only, -1.0) - society.supply_value(work_only)) * (1 - d["on_hand"]["share"])
        self.assertAlmostEqual(drop, work_drop, delta=1)  # the overflowing store part doesn't miss them

    def test_an_idle_fisher_brings_no_fish_to_the_table(self):
        self.gov.innovation_pool.discovered.update({"Toolmaking", "Fishing"})
        self.give_job("Bob", "Fisher")  # no spear: never fished
        self.e.production.last_worked["Bob"] = -10 ** 9
        food = society.compute_qualities(self.gov)["food"]
        self.assertNotIn("fish", food["detail"]["categories"])


class FairLeadershipTest(Base):
    """Leading should be fair: moving people between jobs is part of the work and costs little, an unhappy
    tribe gives its leaders time to put things right before it moves against them, and a Clan Leader who
    works the office gets better at leading."""

    def test_the_hierarchy_of_work_comes_from_the_data(self):
        rank = lambda job: society.job_rank(self.gov, job)
        self.assertEqual((rank(None), rank("Gatherer"), rank("Firekeeper")), (0, 0, 0))  # no research, no tools
        self.assertGreater(rank("Scout"), 0)                     # needs research
        self.assertGreater(rank("Hunter"), rank("Scout"))        # more research, and tools
        self.assertGreater(rank("office:Clan Leader"), rank("office:Elder"))
        occ = OCCUPATIONS["Gatherer"]
        occ.rank = 4  # occupations.json 'rank' overrides
        try:
            self.assertEqual(rank("Gatherer"), 4)
        finally:
            occ.rank = None

    def test_a_step_up_pleases_and_a_step_down_sours(self):
        gov = self.gov
        alice, bob, cleo = self.e.player("Alice"), self.e.player("Bob"), self.e.player("Cleo")
        seat(gov, "Clan Leader", alice)
        gov.innovation_pool.discovered.update({"Tracking"})
        start = bob.satisfaction["leaders"]
        self.assertTrue(gov.appoint(alice, "Gatherer", bob))  # no work -> unskilled work: neutral
        self.assertEqual(bob.satisfaction["leaders"], start)
        self.assertNotIn("leaders", bob.grievances)
        onlooker = cleo.satisfaction["leaders"]
        self.assertTrue(gov.appoint(alice, "Scout", bob))     # up the hierarchy
        self.assertGreater(bob.satisfaction["leaders"], start)
        self.assertLess(bob.grievances["leaders"], 0)          # lasting goodwill
        self.assertEqual(cleo.satisfaction["leaders"], onlooker)  # onlookers don't mind
        up = bob.satisfaction["leaders"]
        self.assertTrue(gov.appoint(alice, "Gatherer", bob))  # back down
        self.assertLess(bob.satisfaction["leaders"], up)
        self.assertTrue(gov.dismiss(alice, "Gatherer", bob))  # dismissing still hurts a lot
        self.assertLess(bob.satisfaction["leaders"], start - 15)

    def test_an_unhappy_tribe_gives_its_leaders_time(self):
        from controllers.npc import NPCController
        spec = society.PATIENCE["meters"]["leaders"]
        gov = self.gov
        seat(gov, "Clan Leader", self.e.player("Alice"))
        bob = self.e.player("Bob")
        npc = NPCController("Bob", random.Random(1))
        bob.satisfaction["leaders"] = 15
        self.assertEqual(npc._unrest(self.e.observe(bob), "leaders"), 0)  # unhappy, but patient for now
        days = (spec["grace_life_hours"] + spec["build_up_life_hours"] + 1) / 24
        steps = 40
        for _ in range(steps):
            bob.satisfaction["leaders"] = 15
            self.update([bob], days / steps)
        self.assertEqual(society.patience_left(bob, "leaders"), 0)
        self.assertGreater(npc._unrest(self.e.observe(bob), "leaders"), 0.5)
        restored = GameEngine.from_dict(self.e.to_dict())
        self.assertEqual(restored.player("Bob").unrest, bob.unrest)
        # Once things are better, patience comes back.
        for _ in range(steps):
            bob.satisfaction["leaders"] = 80
            self.update([bob], days / steps)
        self.assertEqual(society.restless(bob, "leaders"), 0)

    def test_running_out_of_patience_is_announced(self):
        bob = self.e.player("Bob")
        spec = society.PATIENCE["meters"]["leaders"]
        events = []
        for _ in range(60):
            bob.satisfaction["leaders"] = 10
            events += society.update_satisfaction([bob], self.gov, self.e.qualities, 60,
                                                  (spec["grace_life_hours"] + 2) / 24 / 60)
        kinds = [c.get("leaders") for _, c in events]
        self.assertEqual(kinds, ["thin", "out"])

    def test_a_clan_leader_who_works_the_office_learns_leadership(self):
        gov = self.gov
        cleo = self.e.player("Cleo")
        seat(gov, "Clan Leader", cleo)
        for p in self.e.players:
            p.satisfaction["society"] = 50  # a middling tribe: neither praises nor blames
        before = cleo.skills["leadership"]
        self.start("Cleo", "office_duties")
        self.e._event_work_done({"player": "Cleo", "kind": "work", "key": "office_duties"})
        self.assertGreater(cleo.skills["leadership"], before)
        trained = cleo.skills["leadership"]
        self.e._live_one_day()
        self.assertGreater(cleo.skills["leadership"], trained)  # working the office: daily practice too
        idle = cleo.skills["leadership"]
        self.e.production.last_worked["Cleo"] = -10 ** 9  # long since worked the office
        for p in self.e.players:
            p.satisfaction["society"] = 10
        self.e._live_one_day()
        self.assertLess(cleo.skills["leadership"], idle)  # neglecting it while the tribe suffers

    def test_fetching_water_is_not_working_your_job(self):
        cleo = self.e.player("Cleo")
        seat(self.gov, "Clan Leader", cleo)
        self.e.production.last_worked.pop("Cleo", None)
        self.e._event_work_done({"player": "Cleo", "kind": "work", "key": "fetch_water"})
        self.assertNotIn("Cleo", self.e.production.last_worked)

    def test_ability_is_explained(self):
        cleo = self.e.player("Cleo")
        seat(self.gov, "Clan Leader", cleo)
        cleo.needs["energy"] = 20
        ab = self.e.observe(cleo)["ability"]
        self.assertEqual((ab["job"], ab["skill"]), ("Clan Leader", "leadership"))
        self.assertGreater(ab["tired"], 0)
        self.assertAlmostEqual(ab["value"], ab["rested"] - ab["tired"] - ab["unwell"], delta=0.6)


if __name__ == "__main__":
    unittest.main()


class HungerAndStoreTest(Base):
    def test_a_starving_person_is_not_content_with_food(self):
        bob = self.e.player("Bob")
        bob.inventory.load([{"item": "berries", "count": 3}, {"item": "roots", "count": 3},
                            {"item": "meat", "count": 2}])  # a varied pack...
        bob.satisfaction["food"] = 90
        bob.needs["food"] = 5                               # ...but starving
        self.update([bob], 0.02)
        self.assertLessEqual(bob.satisfaction["food"], 5 + society.METERS["food"].hunger["cap_above_need"])
        self.assertIn("hunger", {f["key"] for f in bob.content_detail["food"]["factors"]})
        cleo = self.e.player("Cleo")  # same pack, well fed: still pleased
        cleo.inventory.load([{"item": "berries", "count": 3}, {"item": "roots", "count": 3}])
        cleo.satisfaction["food"], cleo.needs["food"] = 60, 90
        self.update([cleo], 0.05)
        self.assertGreater(cleo.satisfaction["food"], 60)

    def test_npcs_with_nothing_in_their_pack_take_from_the_store_each_day(self):
        bob = self.e.player("Bob")
        bob.inventory.load([])
        self.e.possessions.deliver([{"item": "berries", "count": 10}, {"item": "water", "count": 10}])
        self.e.last_action.pop("Bob", None)
        self.e._live_one_day()
        self.assertGreater(self.e.possessions._points(bob, "food"), 0)
        self.assertGreater(self.e.possessions._points(bob, "water"), 0)

    def test_the_top_bar_counts_what_the_store_holds(self):
        from ui.model import camp_line
        self.e.possessions.ground.clear()
        self.e.possessions.deliver([{"item": "berries", "count": 4}, {"item": "fish", "count": 2},
                                    {"item": "wood", "count": 7}, {"item": "wooden_spear", "count": 1},
                                    {"item": "hand_axe", "count": 2}, {"item": "herbs", "count": 3}])
        line = {g["label"]: g["count"] for g in camp_line(self.e.observe(self.e.player("Alice")))}
        # The groups are the age's (data/ages/tribal/age.json 'store_panel').
        self.assertEqual(line, {"wood": 7, "food": 6, "water": 0, "minerals": 0, "medicine": 3, "tools": 3})

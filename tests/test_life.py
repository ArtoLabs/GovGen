"""Life and death (core/life.py, data/life.json): ages of life, illness and healing, death and the dead,
pregnancy and birth, childhood, and playing on after your character dies."""
import random
import unittest
from unittest import mock

from core import life as LIFE
from core.calendar import HOURS_PER_DAY, HOURS_PER_YEAR, day_of_year
from core.engine import GameEngine
from core.game import Game
from controllers.npc import NPCController
from tests.helpers import new_engine, find, become_actor, advance_days, give_work, seat
from world.character import RULES as CHARACTER


def healer(e, name="Esi", herbs=3):
    e.government.innovation_pool.discovered.add("Herbalism")
    p = give_work(e, name, "Healer")
    p.inventory.add("herbs", herbs)
    return p


class RulesTest(unittest.TestCase):
    def test_overrides_layer_by_age_government_and_innovation(self):
        base = LIFE.rules_for(["tribal"], "tribal", set())
        self.assertEqual(base["work_age"], LIFE.BASE["work_age"])
        with mock.patch.dict(LIFE.AGE_OVERRIDES, {"stone": {"work_age": 12, "pregnancy": {"chance": 0.5}}}), \
                mock.patch.dict(LIFE.INNOVATION_OVERRIDES, {"Writing": {"politics_age": 16}}):
            r = LIFE.rules_for(["tribal", "stone"], "chiefdom", {"Writing"})
        self.assertEqual(r["work_age"], 12)
        self.assertEqual(r["politics_age"], 16)
        self.assertEqual(r["pregnancy"]["chance"], 0.5)
        self.assertEqual(r["pregnancy"]["term_days"], LIFE.BASE["pregnancy"]["term_days"])  # merged, not replaced

    def test_curves(self):
        self.assertEqual(LIFE.curve([[0, 0], [10, 1]], 5), 0.5)
        self.assertEqual(LIFE.curve([[0, 0], [10, 1]], 50), 1)
        self.assertEqual(LIFE.curve([[0, 0], [10, 1]], -5), 0)


class StartingTribeTest(unittest.TestCase):
    def test_a_young_tribe_with_children_and_genders(self):
        e = new_engine()
        self.assertTrue(all(p.gender in CHARACTER.genders for p in e.players))
        self.assertLessEqual(max(p.age for p in e.players), 45)
        kids = [p for p in e.players if e.life.is_child(p)]
        self.assertGreaterEqual(len(kids), 3)
        self.assertEqual(e.player("Tomas").mother, "Alice")

    def test_children_get_only_part_of_the_roll(self):
        e = GameEngine()
        e.roll_characters(random.Random(1))
        base = CHARACTER.new_characters.get("attribute_base", 5)
        self.assertTrue(all(v == base for v in e.player("Ravi").attributes.values()))  # a baby: nothing yet
        self.assertTrue(all(v == 0 for v in e.player("Ravi").skills.values()))


class ChildhoodTest(unittest.TestCase):
    def test_children_play_and_study_but_have_no_politics_or_work(self):
        e = new_engine()
        noor = become_actor(e, "Noor")
        types = {a.type for a in e.legal_actions(noor)}
        self.assertIn("activity", types)
        self.assertFalse(types & {"vote", "nominate", "appoint", "research", "take_occupation", "work", "persuade"})
        self.assertFalse(e.government.can_vote(noor))
        self.assertFalse(e.government.can_hold_office("Elder", noor)[0])
        self.assertFalse(e.government.can_take_occupation("Gatherer", noor)[0])
        alice = e.player("Alice")
        seat(e.government, "Clan Leader", alice)
        self.assertNotIn("Noor", [a.params["appointee"] for a in e._options(alice) if a.type == "appoint"])

    def test_play_shapes_attributes_until_work_age(self):
        e = new_engine()
        noor = e.player("Noor")
        before = noor.attributes["charisma"]
        for _ in range(3):
            e.life.finish_activity(noor, "play_friends")  # 0.45 charisma each
        self.assertEqual(noor.attributes["charisma"], before + 1)
        self.assertGreater(noor.skills["persuasion"], 0)
        noor.age = e.life.rules["work_age"]
        stats = dict(noor.attributes)
        e.life.finish_activity(noor, "play_friends")
        self.assertEqual(noor.attributes, stats)  # set for life once old enough to work

    def test_an_activity_takes_time_and_counts_as_a_childs_work(self):
        e = new_engine()
        noor = become_actor(e, "Noor")
        self.assertTrue(e.apply(noor, find(e, noor, "activity", activity="play_alone")))
        self.assertEqual(e.working_now("Noor"), "childhood")
        before = noor.attributes["wisdom"] + noor.growth.get("wisdom", 0)
        advance_days(e, 80)
        self.assertGreater(noor.attributes["wisdom"] + noor.growth.get("wisdom", 0), before)

    def test_babies_have_no_company_play_until_old_enough(self):
        e = new_engine()
        keys = [k for k, _ in e.life.activities_for(e.player("Ravi"))]  # aged 1
        self.assertEqual(keys, [])

    def test_birthdays_come_on_each_persons_own_day(self):
        e = new_engine()
        noor = e.player("Noor")
        e.game_state.clock = (noor.birth_day - 1) * HOURS_PER_DAY
        age = noor.age
        advance_days(e, 2)
        self.assertEqual(noor.age, age + 1)


class IllnessTest(unittest.TestCase):
    def test_illness_drains_health_and_stops_healing(self):
        e = new_engine()
        bob = e.player("Bob")
        bob.health = 80
        e.life.fall_ill(bob, "sickness")
        drain, fatal = e.life.health_drain(bob)
        self.assertGreater(drain, 0)
        self.assertTrue(fatal)
        bob.live(0.1, False, 20, 20, None, None, health_drain=drain, fatal=fatal)
        self.assertLess(bob.health, 80)

    def test_the_old_fall_ill_more_and_the_dead_make_it_worse(self):
        e = new_engine()
        ill = e.life.illnesses()["sickness"]
        self.assertGreater(LIFE.curve(ill["rate_per_year"], 48), 10 * LIFE.curve(ill["rate_per_year"], 20))
        self.assertGreater(LIFE.curve(ill["cure_chance"], 25), LIFE.curve(ill["cure_chance"], 48))
        self.assertEqual(LIFE.curve(ill["cure_chance"], 55), 0)
        self.assertEqual(e.life.body_factor(), 1.0)
        e.life.die(e.player("Greta"))
        self.assertGreater(e.life.body_factor(), 1.0)

    def test_hard_work_can_make_you_ill(self):
        e = new_engine()
        bob = give_work(e, "Bob")
        from core.work import TASKS
        with mock.patch("random.random", return_value=0.0):
            e.life.after_work(bob, TASKS["forage"], own_job=True)
        self.assertIsNotNone(bob.illness)
        cleo = e.player("Cleo")
        with mock.patch("random.random", return_value=0.0):
            e.life.after_work(cleo, TASKS["office_duties"], own_job=False)  # not her job: no risk
        self.assertIsNone(cleo.illness)

    def test_rest_heals_and_work_does_not(self):
        e = new_engine()
        bob = give_work(e, "Bob")
        f = CHARACTER.health["regen_factors"]
        bob.health = 50
        bob.live(0.05, False, 20, 20, None, None, regen_factor=f["work"])
        self.assertEqual(bob.health, 50)
        bob.live(0.05, False, 20, 20, None, None, regen_factor=f["rest"])
        self.assertGreater(bob.health, 50)

    def test_a_healer_with_herbs_treats_and_may_cure(self):
        e = new_engine()
        esi = healer(e)
        bob = e.player("Bob")
        self.assertIsNone(e.life.treatment_for(bob))  # healthy: nothing to treat
        e.life.fall_ill(bob, "sickness")
        bob.health = 30
        actor = become_actor(e, "Bob")
        act = find(e, actor, "treat")
        self.assertIsNotNone(act)
        with mock.patch("random.random", return_value=0.0):
            self.assertTrue(e.apply(actor, act))
        self.assertIsNone(bob.illness)
        self.assertGreater(bob.health, 30)
        self.assertEqual(esi.inventory.count("herbs"), 2)

    def test_no_herbs_no_healing(self):
        e = new_engine()
        healer(e, herbs=0)
        bob = e.player("Bob")
        e.life.fall_ill(bob, "sickness")
        self.assertIsNone(e.life.treatment_for(bob))

    def test_a_failed_cure_still_gives_some_health(self):
        e = new_engine()
        healer(e)
        bob = e.player("Bob")
        e.life.fall_ill(bob, "sickness")
        bob.health = 20
        with mock.patch("random.random", return_value=0.999):
            self.assertTrue(e.life.treat(bob))
        self.assertIsNotNone(bob.illness)
        self.assertGreater(bob.health, 20)


class DeathTest(unittest.TestCase):
    def test_dying_of_illness_leaves_a_body_and_frees_the_office(self):
        e = new_engine()
        bob = e.player("Bob")
        seat(e.government, "Clan Leader", bob)
        bob.inventory.add("stone", 3)
        e.life.fall_ill(bob, "sickness")
        bob.health = 0.1
        advance_days(e, 2)
        self.assertIsNone(e.player("Bob"))
        self.assertNotIn(bob, e.government.players)
        self.assertNotIn(bob, e.government.get_role_holders("Clan Leader"))
        self.assertEqual([b["name"] for b in e.life.bodies], ["Bob"])
        self.assertGreaterEqual(e.possessions.ground.get("stone", 0), 3)
        view = e.observe(e.player("Alice"))
        self.assertEqual(view["life"]["bodies"][0]["name"], "Bob")

    def test_starving_to_nothing_is_death_not_a_collapse(self):
        e = new_engine()
        bob = e.player("Bob")
        bob.health = 0.1
        bob.needs["food"] = 0
        advance_days(e, 3)
        self.assertIsNone(e.player("Bob"))
        self.assertEqual(e.life.bodies[0]["cause"], "starvation")

    def test_a_death_takes_a_chunk_out_of_care_that_comes_back(self):
        from core import society
        e = new_engine()
        before = society.compute_qualities(e.government)["care"]["value"]
        e.life.die(e.player("Greta"))
        after = e.qualities["care"]["value"]
        self.assertAlmostEqual(after, before + society.QUALITIES["care"].events["death"], delta=0.5)
        e._settle_qualities(2.0)  # two day-night cycles later
        self.assertGreater(society.compute_qualities(e.government)["care"]["value"], after)
        restored = GameEngine.from_dict(e.to_dict())
        self.assertEqual(restored.quality_shocks, e.quality_shocks)

    def test_someone_lays_the_dead_to_rest(self):
        e = new_engine()
        e.life.die(e.player("Greta"))
        alice = become_actor(e, "Alice")
        act = find(e, alice, "work", task="carry_off_dead")
        self.assertIsNotNone(act)
        self.assertTrue(e.apply(alice, act))
        self.assertEqual(e.life.bodies[0]["handler"], "Alice")
        bob = become_actor(e, "Bob")
        self.assertIsNone(find(e, bob, "work", task="carry_off_dead"))  # already being seen to
        advance_days(e, 80)
        self.assertEqual(e.life.bodies, [])

    def test_a_dead_candidate_drops_out_of_an_election(self):
        e = new_engine()
        vote = next(v for v in e.voting.elections() if v.role == "Clan Leader")
        vote.nominations += ["Bob", "Cleo"]
        e.life.die(e.player("Bob"))
        self.assertNotIn("Bob", vote.nominations)

    def test_you_play_on_as_your_eldest_child(self):
        e = new_engine()
        from controllers.hud import HUDController
        hud = HUDController("Alice")
        ctrl = {p.name: hud if p.name == "Alice" else NPCController(p.name, rng=random.Random(1)) for p in e.players}
        g = Game(e, ctrl)
        e.life.die(e.player("Alice"))
        g._sync_people()
        self.assertIs(g.controllers["Tomas"], hud)
        self.assertEqual(hud.name, "Tomas")
        self.assertEqual(e.player("Tomas").controller, "human")
        self.assertNotIn("Alice", g.controllers)
        self.assertEqual([n for n, _ in g.realtime], ["Tomas"])


class BirthTest(unittest.TestCase):
    def test_pregnancy_stops_work_late_and_ends_in_a_birth(self):
        e = new_engine()
        imani = give_work(e, "Imani")
        e.life.conceive(imani)
        pr = e.life.rules["pregnancy"]
        self.assertIsNone(e.life.cannot_work(imani))
        e.game_state.clock = imani.pregnancy["due"] - (pr["no_work_last_days"] - 1) * HOURS_PER_DAY
        self.assertIsNotNone(e.life.cannot_work(imani))
        self.assertIsNotNone(e.work_problem(imani, "work", "forage"))
        view = e.observe(imani)["character"]["life"]["pregnancy"]
        self.assertTrue(view["no_work"])
        e.game_state.clock = imani.pregnancy["due"]
        before = len(e.players)
        e.life.daily()
        self.assertEqual(len(e.players), before + 1)
        baby = e.players[-1]
        self.assertEqual((baby.age, baby.mother), (0, "Imani"))
        self.assertTrue(all(v == LIFE.BASE["birth"]["attribute_start"] for v in baby.attributes.values()))
        self.assertIsNone(imani.pregnancy)
        self.assertIn(baby.name, e.free_at)
        self.assertEqual(baby.birth_day, day_of_year(e.clock))

    def test_the_roll_picks_a_woman_who_can_bear_children(self):
        e = new_engine()
        e.game_state.clock = 28 * HOURS_PER_DAY * 3
        with mock.patch("random.random", return_value=0.0):
            e.life._pregnancy_roll()
        mothers = [p for p in e.players if p.pregnancy]
        self.assertEqual(len(mothers), 1)
        self.assertTrue(mothers[0].bears_children)
        self.assertGreater(e.life.can_conceive(e.player("Leila")) + e.life.can_conceive(e.player("Cleo")), 0)
        self.assertEqual(e.life.can_conceive(e.player("Bob")), 0)
        self.assertEqual(e.life.can_conceive(e.player("Noor")), 0)  # a child

    def test_a_newborn_gets_an_npc_and_survives_a_save(self):
        e = new_engine()
        ctrl = {p.name: NPCController(p.name, rng=random.Random(1)) for p in e.players}
        g = Game(e, ctrl)
        baby = e.life.give_birth(e.player("Leila"))
        e.life.die(e.player("Greta"))
        g._sync_people()
        self.assertIn(baby.name, g.controllers)
        self.assertNotIn("Greta", g.controllers)
        restored = GameEngine.from_dict(e.to_dict())
        self.assertEqual([p.name for p in restored.players], [p.name for p in e.players])
        self.assertEqual(restored.player(baby.name).mother, "Leila")
        self.assertEqual([b["name"] for b in restored.life.bodies], ["Greta"])
        self.assertIn(baby.name, restored.life.used_names)

    def test_names_are_never_given_twice(self):
        e = new_engine()
        names = {e.life.give_birth(e.player("Leila")).name for _ in range(30)}
        self.assertEqual(len(names), 30)


class ColdTest(unittest.TestCase):
    def test_winter_without_a_fire_chills_very_fast_and_freezing_hurts(self):
        from world.character import Character
        from world import environment
        lost = {}
        for no_fire in (False, True):
            c = Character(30)
            c.live(1 / 12, False, -2, environment.COMFORT, None, "Winter", no_fire=no_fire)  # one winter, outdoors
            lost[no_fire] = 100 - c.needs["warmth"]
        self.assertGreater(lost[False], 30)        # cold enough to send people to the fire
        self.assertGreater(lost[True], 2 * lost[False])
        self.assertGreater(lost[True], 80)          # with no fire, one winter nearly freezes you
        c = Character(30)
        c.needs["warmth"] = 0
        c.live(1 / 12, False, -2, environment.COMFORT, None, "Winter", fatal=True)
        self.assertLess(c.health, 85)               # freezing wears health down within a winter

    def test_freezing_to_death_names_the_cold(self):
        e = new_engine()
        bob = e.player("Bob")
        bob.needs["warmth"] = 0
        bob.health = 0.1
        advance_days(e, 2)
        self.assertEqual(e.life.bodies[0]["cause"], "cold")


class NPCResearchTest(unittest.TestCase):
    def test_npcs_queue_the_cheapest_research_first(self):
        from innovations.innovation import ALL_INNOVATIONS
        e = new_engine()
        actor = become_actor(e, "Bob")
        legal = e.legal_actions(actor)
        research = [a for a in legal if a.type == "research"]
        self.assertTrue(research)
        c = NPCController("Bob", rng=random.Random(1))
        view = e.observe(actor)
        c.decide(view, legal)
        c._researched_at = None  # (deciding may have queued something; look at the scores afresh)
        cheapest = min(ALL_INNOVATIONS[a.params["innovation"]].cost for a in research)
        for a in research:
            score, _ = c._score_research(view, a)
            if ALL_INNOVATIONS[a.params["innovation"]].cost > cheapest:
                self.assertEqual(score, 0.0, a.params["innovation"])
        self.assertTrue(any(c._score_research(view, a)[0] > 0 for a in research
                            if ALL_INNOVATIONS[a.params["innovation"]].cost == cheapest))

    def test_leaders_keep_the_only_firekeeper(self):
        e = new_engine()
        kalani = give_work(e, "Kalani", "Firekeeper")
        e.government.innovation_pool.discovered.add("Herbalism")
        actor = become_actor(e, "Bob")
        c = NPCController("Bob", rng=random.Random(1))
        gain, loss = c._move_worth(e.observe(actor), "Kalani", "Healer")
        self.assertGreaterEqual(loss, 40)  # taking away the only fire keeper costs the camp its fire
        self.assertIsNotNone(kalani)


class HardTimesTest(unittest.TestCase):
    def test_the_ill_and_the_weak_cannot_work(self):
        e = new_engine()
        bob = give_work(e, "Bob")
        self.assertIsNone(e.work_problem(bob, "work", "forage"))
        e.life.fall_ill(bob, "sickness")
        self.assertIn("ill", e.work_problem(bob, "work", "forage"))
        bob.illness = None
        bob.health = 20
        self.assertIn("weak", e.work_problem(bob, "work", "forage"))

    def test_hardship_drags_contentment_down_fast(self):
        from core import society
        e = new_engine()
        gov = e.government
        q = society.compute_qualities(gov)
        cold, warm = e.player("Bob"), e.player("Cleo")
        cold.needs["warmth"] = 5
        society.update_satisfaction([cold, warm], gov, q, 60, 1 / 12)  # one season
        self.assertLess(cold.satisfaction["comfort"], warm.satisfaction["comfort"] - 20)
        self.assertTrue(any(f["key"] == "hardship" for f in cold.content_detail["comfort"]["factors"]))

    def test_a_suffering_tribe_turns_on_its_leaders(self):
        from core import society
        e = new_engine()
        gov = e.government
        q = society.compute_qualities(gov)
        people = e.players
        for p in people[:8]:
            p.needs["food"] = 0  # half the tribe starving
        before = [p.satisfaction["leaders"] for p in people]
        society.update_satisfaction(people, gov, q, 60, 1 / 12)
        self.assertLess(sum(p.satisfaction["leaders"] for p in people), sum(before) - 10 * len(people))

    def test_a_dead_leaders_seat_opens_to_a_vote_at_once(self):
        e = new_engine()
        gov = e.government
        greta = e.player("Greta")
        seat(gov, "Spirit Keeper", greta)  # normally filled only by a yearly divine sign
        e.life.die(greta)
        vote = next((v for v in e.voting.elections() if v.role == "Spirit Keeper"), None)
        self.assertIsNotNone(vote)
        self.assertTrue(vote.is_nomination_open)
        self.assertLessEqual(vote.nominations_close_at - e.clock, LIFE.BASE["succession"]["nomination_days"] * HOURS_PER_DAY)


class ScoutAndHealerTest(unittest.TestCase):
    def test_a_scout_brings_nothing_back_but_finds_places_often(self):
        from core import work as WORK
        self.assertEqual(WORK.TASKS["scout_plants"].yields, [])
        self.assertGreater(WORK.site_find_chance(50), WORK.trip_chance(WORK.TASKS["forage"], 50, False))

    def test_a_found_place_makes_the_next_trip_certain_then_is_used_up(self):
        e = new_engine()
        give_work(e, "Bob")
        e._add_site("plants", "Cleo", 1, 10 ** 4)
        p = become_actor(e, "Bob")
        before = sum(p.inventory.count(x) for x in ("berries", "roots")) + \
            sum(e.possessions.ground.get(x, 0) for x in ("berries", "roots"))
        e.apply(p, find(e, p, "work", task="forage"))
        advance_days(e, 100)
        after = sum(p.inventory.count(x) for x in ("berries", "roots")) + \
            sum(e.possessions.ground.get(x, 0) for x in ("berries", "roots"))
        self.assertGreater(after, before)
        self.assertFalse(e.site_known("plants"))

    def test_a_healer_goes_to_the_sick(self):
        e = new_engine()
        esi = healer(e)
        bob = e.player("Bob")
        e.life.fall_ill(bob, "sickness")
        actor = become_actor(e, "Esi")
        act = find(e, actor, "heal", patient="Bob")
        self.assertIsNotNone(act)
        d = NPCController("Esi", rng=random.Random(1)).decide(e.observe(actor), e.legal_actions(actor))
        self.assertEqual((d.action.type, d.action.params.get("patient")), ("heal", "Bob"))
        with mock.patch("random.random", return_value=0.0):
            self.assertTrue(e.apply(actor, act))
        self.assertIsNone(bob.illness)
        self.assertEqual(esi.inventory.count("herbs"), 2)

    def test_herbs_are_not_food(self):
        from world.items import ITEMS
        self.assertEqual(ITEMS["herbs"].use, {})


class NPCLifeTest(unittest.TestCase):
    def test_an_ill_npc_goes_to_the_healer(self):
        e = new_engine()
        healer(e)
        bob = e.player("Bob")
        e.life.fall_ill(bob, "sickness")
        actor = become_actor(e, "Bob")
        d = NPCController("Bob", rng=random.Random(1)).decide(e.observe(actor), e.legal_actions(actor))
        self.assertEqual(d.action.type, "treat")

    def test_npcs_lay_the_dead_to_rest(self):
        e = new_engine()
        e.life.die(e.player("Greta"))
        actor = become_actor(e, "Cleo")
        c = NPCController("Cleo", rng=random.Random(1))
        act = find(e, actor, "work", task="carry_off_dead")
        score, _ = c._score(e.observe(actor), act)
        self.assertGreater(score, 3)


if __name__ == "__main__":
    unittest.main()

"""Characters (needs, health, aging, skills), the day-night cycle, and occupations."""
import unittest

from core.calendar import HOURS_PER_DAY, HOURS_PER_YEAR
from core.occupations import OCCUPATIONS
from tests.helpers import become_actor, find, new_engine, seat
from world import environment
from world.character import RULES, Character


class CharacterTest(unittest.TestCase):
    def test_defaults_come_from_data(self):
        c = Character(30)
        self.assertEqual(set(c.attributes), set(RULES.attributes))
        self.assertEqual(set(c.needs), set(RULES.needs))
        self.assertTrue(all(v == 100 for v in c.needs.values()))

    def test_needs_fall_and_care_restores(self):
        c = Character(30)
        c.live(0.5, night=False, temperature=environment.COMFORT, comfort=environment.COMFORT)
        self.assertLess(c.needs["food"], 100)
        before = c.needs["water"]
        c.care_now("drink")  # instant
        self.assertGreater(c.needs["water"], before)
        hungry = c.needs["food"]
        eating = RULES.care_actions["eat"].activity()
        c.live(1 / 24, False, environment.COMFORT, environment.COMFORT, eating)  # one hour of eating
        self.assertGreater(c.needs["food"], hungry)

    def test_sleep_slows_hunger_and_restores_energy(self):
        awake, asleep = Character(30), Character(30)
        awake.needs["energy"] = asleep.needs["energy"] = 30
        sleep = RULES.care_actions["sleep"].activity()
        awake.live(8 / 24, True, environment.COMFORT, environment.COMFORT)
        asleep.live(8 / 24, True, environment.COMFORT, environment.COMFORT, sleep)
        self.assertGreater(asleep.needs["food"], awake.needs["food"])
        self.assertGreater(asleep.needs["energy"], 90)
        self.assertLess(awake.needs["energy"], 30)

    def test_hunger_and_thirst_empty_within_a_day(self):
        self.assertGreaterEqual(RULES.needs["food"].decay_per_day, 100)
        self.assertGreaterEqual(RULES.needs["water"].decay_per_day, 100)
        c = Character(30)
        c.live(0.5, False, environment.COMFORT, environment.COMFORT)  # half a day awake
        self.assertLessEqual(c.needs["food"], 50)
        self.assertLessEqual(c.needs["water"], 50)

    def test_cold_makes_warmth_fall_faster(self):
        warm, cold = Character(30), Character(30)
        warm.live(0.2, False, environment.COMFORT - 1, environment.COMFORT)
        cold.live(0.2, False, environment.COMFORT - 25, environment.COMFORT)
        self.assertLess(cold.needs["warmth"], warm.needs["warmth"])

    def test_neglect_leads_to_collapse_not_death(self):
        c = Character(30)
        message = None
        for _ in range(100):
            message = c.live(0.1, False, environment.COMFORT, environment.COMFORT) or message
        self.assertIsNotNone(message)
        self.assertGreater(c.health, 0)

    def test_aging_changes_attributes(self):
        c = Character(54, {"strength": 8})
        for _ in range(7):
            c.birthday()
        self.assertEqual(c.age, 61)
        self.assertEqual(c.attributes["strength"], 7)

    def test_training_improves_a_skill(self):
        c = Character(30)
        c.train("hunting", 1.0)
        self.assertGreater(c.skills["hunting"], 0)


class EnvironmentTest(unittest.TestCase):
    def test_day_and_night_alternate_over_the_cycle(self):
        self.assertFalse(environment.is_night(0))  # the game starts at dawn
        hours = environment.CYCLE_HOURS
        states = {environment.is_night(hours * f) for f in (0.0, 0.2, 0.4, 0.6, 0.8)}
        self.assertEqual(states, {True, False})


class EngineLifeTest(unittest.TestCase):
    def test_sleep_takes_eight_hours_of_the_day_night_cycle(self):
        e = new_engine()
        alice = become_actor(e, "Alice")
        sleep = find(e, alice, "care", kind="sleep")
        self.assertEqual(e.duration(sleep), environment.life_hours_to_calendar(8))
        self.assertEqual(e.duration(sleep), 8 * environment.CYCLE_HOURS / 24)
        drink = find(e, alice, "care", kind="drink")
        self.assertLessEqual(e.duration(drink), 1)

    def test_the_fire_needs_wood(self):
        e = new_engine()
        alice = become_actor(e, "Alice")
        self.assertIsNotNone(find(e, alice, "care", kind="warm_up"))  # the fire burns at first...
        e.fire_until = e.clock  # ...until its wood is spent
        self.assertIsNone(find(e, alice, "care", kind="warm_up"))
        self.assertIsNone(e.fire_temperature())
        e.government.occupations["Firekeeper"].append(e.player("Kalani"))
        self.assertIsNone(e.fire_temperature())  # a Firekeeper alone is not a fire
        e.fire_until = e.clock + 100
        self.assertIsNotNone(e.fire_temperature())
        self.assertIsNotNone(find(e, alice, "care", kind="warm_up"))

    def test_a_sleeper_can_wake_up(self):
        e = new_engine()
        alice = become_actor(e, "Alice")
        e.apply(alice, find(e, alice, "care", kind="sleep"))
        self.assertEqual([a.type for a in e.legal_actions(alice)], ["stop"])
        self.assertTrue(e.act_now(alice, e.legal_actions(alice)[0]))
        self.assertEqual(e.free_at["Alice"], e.clock)

    def test_everyone_ages_each_year_and_needs_fall(self):
        e = new_engine()
        ages = {p.name: p.age for p in e.players}
        while e.clock < HOURS_PER_YEAR + HOURS_PER_DAY:
            actor = e.step()
            if actor is not None:
                e.apply(actor, find(e, actor, "wait", days=30))
        self.assertTrue(all(p.age == ages[p.name] + 1 for p in e.players))
        self.assertTrue(all(p.needs["food"] < 100 for p in e.players))

    def test_care_is_a_legal_action(self):
        e = new_engine()
        alice = become_actor(e, "Alice")
        self.assertIsNotNone(find(e, alice, "care", kind="eat"))

    def test_appointing_a_hunter(self):
        e = new_engine()
        gov = e.government
        seat(gov, "Clan Leader", e.player("Alice"))
        alice = become_actor(e, "Alice")
        self.assertIsNone(find(e, alice, "appoint", position="Hunter", appointee="Imani"))  # no Hunting yet
        gov.innovation_pool.discovered.add("Hunting")
        act = find(e, alice, "appoint", position="Hunter", appointee="Imani")  # no spear yet: they'll wait
        self.assertIsNotNone(act)
        self.assertTrue(e.apply(alice, act))
        self.assertIn("Hunter", gov.occupations_of(e.player("Imani")))
        # A hunter can't be drafted away into other appointed work...
        self.assertFalse(gov.can_take_occupation("Scout", e.player("Imani"), switching=True)[0])
        # ...and the job survives a change of government.
        self.assertIn("Hunter", OCCUPATIONS)

    def test_gathering_is_open_to_volunteers_but_hunting_is_appointed(self):
        e = new_engine()
        bob = become_actor(e, "Bob")
        self.assertIsNotNone(find(e, bob, "take_occupation", occupation="Gatherer"))
        self.assertIsNone(find(e, bob, "take_occupation", occupation="Hunter"))

    def test_character_state_is_saved(self):
        e = new_engine()
        e.player("Bob").needs["food"] = 12.5
        e.player("Bob").age = 77
        from core.engine import GameEngine
        restored = GameEngine.from_dict(e.to_dict())
        self.assertEqual(restored.player("Bob").needs["food"], 12.5)
        self.assertEqual(restored.player("Bob").age, 77)


if __name__ == "__main__":
    unittest.main()


class SeasonWarmthTest(unittest.TestCase):
    def test_warmth_falls_fast_in_winter_and_hardly_in_summer(self):
        from world.character import Character
        from world import environment
        out = {}
        for season in ("Winter", "Spring", "Summer"):
            c = Character(30)
            c.needs["warmth"] = 100
            c.live(0.2, False, environment.COMFORT - 6, environment.COMFORT, None, season)
            out[season] = 100 - c.needs["warmth"]
        self.assertGreater(out["Winter"], 2 * out["Spring"])
        self.assertGreater(out["Spring"], 2 * out["Summer"])

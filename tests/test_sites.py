"""Trips out are a gamble unless a Scout found a good place; Elders appoint only Healers; politics goes on
while people work."""
import random
import unittest

from core import work as WORK
from core.occupations import OCCUPATIONS
from tests.helpers import advance_until, become_actor, do, find, give_work, new_engine, seat


class TripTests(unittest.TestCase):
    def test_trips_rarely_pay_off_without_a_site(self):
        forage = WORK.TASKS["forage"]
        self.assertLess(WORK.trip_chance(forage, 50, site_known=False), 0.5)
        self.assertGreater(WORK.trip_chance(forage, 50, site_known=True), 0.85)
        self.assertEqual(WORK.trip_chance(WORK.TASKS["fetch_water"], 50, site_known=False), 1.0)

    def test_many_trips_without_a_site_often_come_back_empty(self):
        e = new_engine(5)
        bob = e.player("Bob")
        t = WORK.TASKS["forage"]
        random.seed(1)
        hits = sum(random.random() < WORK.trip_chance(t, e.work_quality(bob, t), False) for _ in range(400))
        self.assertLess(hits, 220)

    def test_a_scout_chooses_what_to_look_for(self):
        # One scouting task per kind of place; only kinds someone could use now can be looked for.
        self.assertEqual({t.scouts_for for t in WORK.TASKS.values() if t.scouts_for}, set(WORK.SITE_KINDS))
        e = new_engine(2)
        e.government.innovation_pool.discovered.add("Tracking")
        esi = e.player("Esi")
        e.government.occupations["Scout"].append(esi)
        self.assertIsNone(e.work_problem(esi, "work", "scout_plants"))
        self.assertIn("nobody could use", e.work_problem(esi, "work", "scout_game"))  # nobody hunts yet
        e.government.innovation_pool.discovered.add("Hunting")
        self.assertIsNone(e.work_problem(esi, "work", "scout_game"))

    def test_a_scout_finds_what_they_looked_for_with_plenty_there(self):
        from utils.messages import Messages
        e = new_engine(2)
        esi = e.player("Esi")
        self.assertGreaterEqual(WORK.site_find_chance(50), 0.8)
        for seed in range(20):
            random.seed(seed)
            e.production._scout_for_sites(esi, "stone", 60)
            if e.production.sites:
                break
        site = e.production.sites[0]
        self.assertEqual((site["kind"], site["by"]), ("stone", "Esi"))
        lo, hi = WORK.SITES["loads"]
        self.assertTrue(lo <= site["loads"] <= hi)  # several trips' worth
        self.assertTrue(any(m.category == "find" and "Esi found" in m.text for m in Messages._messages))
        self.assertEqual(e.observe(esi)["camp"]["sites"][0]["kind"], "stone")

    def test_a_found_place_is_shared_out_over_trips_then_the_next_one_is_used(self):
        e = new_engine(3)
        give_work(e, "Bob")
        first = e.production._add_site("plants", "Cleo", 3.5, 10 ** 4)
        second = e.production._add_site("plants", "Hiro", 4, 10 ** 4)
        take = WORK.SITES["take_per_trip"]

        def forage():
            p = become_actor(e, "Bob")
            self.assertTrue(e.apply(p, find(e, p, "work", task="forage")))
            advance_until(e, lambda: e.free_at["Bob"] <= e.clock)
        forage()
        self.assertAlmostEqual(first["loads"], 3.5 - take)  # a big haul, with some left for the next trip
        self.assertEqual(second["loads"], 4)
        forage()
        self.assertNotIn(first, e.production.sites)                     # the rest of it: used up
        self.assertEqual(e.production.spent_sites[-1]["how"], "used up")
        self.assertEqual(e.production.site_of("plants"), second)        # the next trip goes to the next place found
        view = e.observe(e.player("Bob"))["camp"]
        self.assertEqual([x["by"] for x in view["sites"]], ["Hiro"])
        self.assertEqual(view["spent_sites"][0]["by"], "Cleo")

    def test_an_unused_place_is_lost_in_time(self):
        e = new_engine()
        site = e.production._add_site("wood", "Esi", 3, 2)
        e.game_state.clock = site["until"] + 1
        e.production._expire_sites()
        self.assertFalse(e.production.site_known("wood"))
        self.assertEqual(e.production.spent_sites[-1]["how"], "lost")

    def test_scouts_only_find_sites_someone_can_use(self):
        e = new_engine()
        kinds = set(e.production.useful_site_kinds())
        self.assertIn("plants", kinds)        # Gatherers forage from the start
        self.assertNotIn("game", kinds)       # nobody can hunt before Hunting
        e.government.innovation_pool.discovered.add("Hunting")
        self.assertIn("game", e.production.useful_site_kinds())

    def test_npc_scouts_look_for_what_the_tribe_is_short_of(self):
        from controllers.npc import NPCController
        e = new_engine()
        e.government.innovation_pool.discovered.add("Tracking")
        esi = e.player("Esi")
        e.government.occupations["Scout"].append(esi)
        for p in e.players:  # no food anywhere; plenty of stone and wood
            for k in ("berries", "roots", "meat", "fish"):
                p.inventory.take(k, p.inventory.count(k))
        for k in list(e.possessions.ground):
            if k in ("berries", "roots", "meat", "fish"):
                e.possessions.ground[k] = 0
        e.possessions.ground.update({"stone": 500, "wood": 500, "flint": 50, "herbs": 50})
        view = e.observe(esi)
        work = {w["key"]: w for w in view["camp"]["work"]}
        npc = NPCController("Esi", rng=random.Random(1))
        plants, _ = npc._scout_need(view, work["scout_plants"])
        stone, _ = npc._scout_need(view, work["scout_stone"])
        self.assertGreater(plants, 2 * stone)
        e.production._add_site("plants", "Hiro", 5, 10 ** 4)  # already found, with plenty left: less need
        later, _ = npc._scout_need(e.observe(esi), work["scout_plants"])
        self.assertLess(later, plants)

    def test_sites_are_saved(self):
        from core.engine import GameEngine
        e = new_engine()
        e.production._add_site("stone", "Esi", 4, 10)
        e.production._spend_site(e.production._add_site("wood", "Esi", 1, 10), "used up")
        loaded = GameEngine.from_dict(e.to_dict())
        self.assertEqual((loaded.production.sites, loaded.production.spent_sites, loaded.production.next_site_id),
                         (e.production.sites, e.production.spent_sites, e.production.next_site_id))
        old = e.to_dict()  # a save from before core/production.py: the places at the top, one per kind
        old.update(old.pop("production"))
        old["sites"] = {"stone": {"until": e.clock + 500, "by": "Esi", "trips": 2}}
        self.assertEqual(GameEngine.from_dict(old).production.site_of("stone")["loads"], 2)


class ElderTests(unittest.TestCase):
    def test_every_tribal_office_appoints_to_every_job(self):
        for name, occ in OCCUPATIONS.items():
            for office in ("Clan Leader", "Elder", "Spirit Keeper"):
                self.assertIn(office, occ.appointed_by, name)
        e = new_engine()
        seat(e.government, "Elder", e.player("Greta"))
        e.government.innovation_pool.discovered.update({"Herbalism", "Toolmaking", "Hunting"})
        appointable = set(e.government.appointable(e.player("Greta"))) & set(OCCUPATIONS)
        self.assertTrue({"Healer", "Hunter", "Gatherer", "Toolmaker"} <= appointable)


class PoliticsWhileBusyTests(unittest.TestCase):
    def test_a_worker_can_vote_and_nominate_without_stopping(self):
        e = new_engine(1)
        give_work(e, "Alice")  # only Gatherers fetch water
        alice = become_actor(e, "Alice")
        self.assertTrue(e.apply(alice, find(e, alice, "work", task="fetch_water")))
        busy_until = e.free_at["Alice"]
        self.assertFalse(e.is_free(alice))
        nominate = find(e, alice, "nominate", ballot="elect:Clan Leader", candidate="Bob")
        self.assertIsNotNone(nominate)
        self.assertTrue(e.act_now(alice, nominate))
        self.assertIn("Bob", e.voting.ballot("elect:Clan Leader").nominations)
        self.assertEqual(e.free_at["Alice"], busy_until)  # still out fetching water
        self.assertEqual(e.last_action["Alice"]["type"], "work")

    def test_no_politics_in_ones_sleep(self):
        e = new_engine(1)
        alice = become_actor(e, "Alice")
        alice.needs["energy"] = 10
        self.assertTrue(e.apply(alice, find(e, alice, "care", kind="sleep")))
        self.assertFalse(e.can_act_aside(alice))
        self.assertEqual([a.type for a in e.legal_actions(alice)], ["stop"])

    def test_working_npcs_still_vote(self):
        from controllers.npc import NPCController
        from core.game import Game, Pacer
        e = new_engine(4)
        ctrls = {p.name: NPCController(p.name, rng=random.Random(i)) for i, p in enumerate(e.players)}
        g = Game(e, ctrls, pacer=Pacer(speed=0))
        done = []
        real = e.act_aside

        def counting(player, action, reason=None):
            ok = real(player, action, reason)
            if ok:
                done.append(action.type)
            return ok
        e.act_aside = counting
        g.run(max_years=0.5)
        self.assertTrue(set(done) & {"vote", "nominate", "research", "appoint"}, done)

if __name__ == "__main__":
    unittest.main()


class NewRulesTests(unittest.TestCase):
    def test_a_weak_speaker_still_persuades_a_little(self):
        e = new_engine(1)
        seat(e.government, "Clan Leader", e.player("Dmitri"))
        bob = e.player("Bob")
        bob.skills["persuasion"], bob.attributes["charisma"] = 0.1, 1
        b = become_actor(e, "Bob")
        e.apply(b, find(e, b, "persuade", office="Clan Leader", target="Dmitri"))
        c = e.contests.contests[0]
        for name in list(c.meters):
            before = c.meters[name]
            e.contests.canvass(bob, c.key, name)
            self.assertGreater(c.meters[name], before)

    def test_food_contentment_follows_variety_in_the_pack(self):
        from core import society
        e = new_engine()
        p = e.player("Bob")
        results = []
        for stacks in ([], [("berries", 3)], [("berries", 2), ("roots", 2)], [("berries", 1), ("roots", 1), ("meat", 1)]):
            p.inventory.load([])
            for k, n in stacks:
                p.inventory.add(k, n)
            p.satisfaction["food"] = 50
            society.update_satisfaction([p], e.government, e.qualities, 60, 0.2)
            results.append(p.satisfaction["food"])
        none, one, two, three = results
        for v in p.satisfaction.values():  # the other meters stay within 0-100
            self.assertTrue(0 <= v <= 100, p.satisfaction)
        self.assertLess(none, 40)               # nothing to eat: falls fast
        self.assertTrue(47 < one <= 50)         # one kind: barely moves
        self.assertGreater(two, 50)
        self.assertGreater(three, two)          # more variety, faster up

    def test_new_games_roll_characters(self):
        from core.engine import GameEngine
        e = GameEngine()
        e.roll_characters(random.Random(7))
        stats = [tuple(p.attributes.values()) for p in e.players]
        self.assertGreater(len(set(stats)), 6)
        self.assertGreaterEqual(min(min(st) for st in stats), 5)  # everyone starts at least average
        self.assertGreater(max(max(st) for st in stats), 5)       # and the dice add to that
        for p in e.players:
            self.assertEqual({s for s, v in p.skills.items() if v} - {"gathering", "firekeeping"}, set())


class TalkWhileWorkingTest(unittest.TestCase):
    def test_a_worker_can_run_a_campaign_one_talk_at_a_time(self):
        from tests.helpers import seat
        e = new_engine(1)
        seat(e.government, "Clan Leader", e.player("Dmitri"))
        give_work(e, "Alice")
        alice = become_actor(e, "Alice")
        self.assertTrue(e.apply(alice, find(e, alice, "work", task="fetch_water")))
        busy_until = e.free_at["Alice"]
        self.assertTrue(e.act_now(alice, find(e, alice, "persuade", office="Clan Leader", target="Dmitri")))
        talk = find(e, alice, "canvass")
        self.assertIsNotNone(talk)
        self.assertTrue(e.act_now(alice, talk))
        self.assertIsNone(find(e, alice, "canvass"))  # the talk takes its time
        e.game_state.clock = e.talk_free_at["Alice"]
        self.assertIsNotNone(find(e, alice, "canvass"))
        self.assertEqual(e.free_at["Alice"], busy_until)  # still out fetching water
        self.assertEqual(e.last_action["Alice"]["type"], "work")

    def test_a_worker_can_challenge(self):
        from tests.helpers import seat
        e = new_engine(1)
        seat(e.government, "Clan Leader", e.player("Dmitri"))
        give_work(e, "Alice")
        alice = become_actor(e, "Alice")
        e.apply(alice, find(e, alice, "work", task="fetch_water"))
        self.assertTrue(e.act_now(alice, find(e, alice, "challenge", office="Clan Leader", holder="Dmitri")))

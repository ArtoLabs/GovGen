"""Work that produces things: jobs opened by research and tools, tasks and crafting, meals that use up
food, the fire's wood, and jobs that count only while worked."""
import random
import unittest

from core.actions import Action
from core.calendar import HOURS_PER_DAY
from core import society
from tests.helpers import advance_days, become_actor, find, new_engine
from world.environment import life_hours_to_calendar
from world.items import ITEMS


class WorkTest(unittest.TestCase):
    def setUp(self):
        self.e = new_engine()
        self.gov = self.e.government
        self.store = self.e.possessions.ground
        for p in self.e.players:  # empty packs, so everything comes from the store unless a test says so
            p.inventory.load([])
        # The game starts with an empty store; these tests start with a stocked one.
        self.e.possessions.deliver([{"item": "berries", "count": 40}, {"item": "roots", "count": 20},
                                    {"item": "meat", "count": 6}, {"item": "water", "count": 40},
                                    {"item": "wood", "count": 16}, {"item": "stone", "count": 10}])

    def actor(self, name):
        return become_actor(self.e, name)

    def finish(self, name):
        """Let time pass until `name`'s work is done (everyone else waits)."""
        until = self.e.free_at[name]
        advance_days(self.e, (until - self.e.clock) / HOURS_PER_DAY + 0.01)

    def test_only_gatherer_and_firekeeper_are_open_at_the_start(self):
        bob = self.actor("Bob")
        jobs = {a.params["occupation"] for a in self.e.legal_actions(bob) if a.type == "take_occupation"}
        self.assertEqual(jobs, {"Gatherer", "Firekeeper"})
        self.assertNotIn("Toolmaking", self.gov.innovation_pool.discovered)

    def test_hunter_needs_research_but_not_yet_a_spear(self):
        bob = self.e.player("Bob")
        self.assertFalse(self.gov.can_take_occupation("Hunter", bob, switching=True)[0])
        self.gov.innovation_pool.discovered.add("Hunting")
        self.assertTrue(self.gov.can_take_occupation("Hunter", bob, switching=True)[0])  # a spear comes later

    def test_gathering_brings_food_back_to_the_camp_store(self):
        bob = self.actor("Bob")
        self.assertTrue(self.e.apply(bob, find(self.e, bob, "take_occupation", occupation="Gatherer")))
        bob = self.actor("Bob")
        before = self.store.get("berries", 0)
        self.e.production._add_site("plants", "Esi", 10, 10 ** 4)  # a found place: certain
        random.seed(3)
        self.assertTrue(self.e.apply(bob, find(self.e, bob, "work", task="forage")))
        self.assertEqual(self.store.get("berries", 0), before)  # nothing until the work is done
        self.finish("Bob")
        # An NPC keeps food for a few meals and shares only the rest.
        self.assertGreater(bob.inventory.count("berries") + bob.inventory.count("roots"), 0)
        self.assertEqual(self.e.work_activity("Bob"), 1.0)

    def test_only_gatherers_fetch_water(self):
        alice = self.actor("Alice")
        if alice in self.gov.occupations["Gatherer"]:
            self.gov.occupations["Gatherer"].remove(alice)
        self.assertIsNone(find(self.e, alice, "work", task="fetch_water"))
        self.gov.occupations["Gatherer"].append(alice)
        self.assertIsNotNone(find(self.e, alice, "work", task="fetch_water"))
        self.assertIsNotNone(find(self.e, alice, "work", task="forage"))

    def test_a_toolmaker_crafts_from_materials_and_a_hunter_takes_the_spear(self):
        self.gov.innovation_pool.discovered.update({"Toolmaking", "Hunting"})
        hiro, imani = self.e.player("Hiro"), self.e.player("Imani")
        self.gov.occupations["Toolmaker"].append(hiro)
        hiro = self.actor("Hiro")
        wood, stone = self.store["wood"], self.store["stone"]
        self.assertTrue(self.e.apply(hiro, find(self.e, hiro, "craft", recipe="wooden_spear")))
        self.assertEqual((self.store["wood"], self.store["stone"]), (wood - 2, stone))  # wood only, used at once
        self.finish("Hiro")
        self.assertEqual(self.store.get("wooden_spear"), 1)
        self.gov.occupations["Hunter"].append(imani)
        imani = self.actor("Imani")
        meat = self.store.get("meat", 0)
        self.assertTrue(self.e.apply(imani, find(self.e, imani, "work", task="hunt")))
        self.assertEqual(imani.inventory.count("wooden_spear"), 1)  # taken from the store to hunt with
        self.finish("Imani")
        self.assertGreaterEqual(self.store.get("meat", 0), meat)

    def test_no_hunting_without_a_spear(self):
        self.gov.innovation_pool.discovered.add("Hunting")
        imani = self.e.player("Imani")
        self.gov.occupations["Hunter"].append(imani)
        imani = self.actor("Imani")
        self.assertIsNone(find(self.e, imani, "work", task="hunt"))
        self.assertIn("Spear", self.e.work_problem(imani, "work", "hunt"))

    def test_meals_come_only_from_ones_own_pack(self):
        alice = self.actor("Alice")
        alice.needs["food"] = 20
        stored = dict(self.store)
        self.assertIsNone(find(self.e, alice, "care", kind="eat"))  # a full store, an empty pack: no meal
        self.assertIn("Sorry", "".join(m for m in [self._try_eat(alice)]))
        alice.inventory.add("berries", 3)
        self.assertTrue(self.e.apply(alice, find(self.e, alice, "care", kind="eat")))
        self.assertEqual(alice.inventory.count("berries"), 0)
        self.assertEqual(self.store, stored)  # the store is untouched

    def _try_eat(self, player) -> str:
        from utils.messages import Messages
        before = len(Messages._messages)
        self.assertFalse(self.e._do_care(player, {"kind": "eat"}, None))
        return " ".join(m.text for m in Messages._messages[before:])

    def test_no_food_no_meal_and_no_water_no_drink(self):
        for k in list(self.store):
            del self.store[k]
        alice = self.actor("Alice")
        alice.needs["food"] = alice.needs["water"] = 30
        self.assertIsNone(find(self.e, alice, "care", kind="eat"))
        self.assertIsNone(find(self.e, alice, "care", kind="drink"))

    def test_drinking_restores_only_what_was_drunk(self):
        alice = self.actor("Alice")
        for k in list(self.store):
            del self.store[k]
        alice.inventory.load([{"item": "water", "count": 1}])
        alice.needs["water"] = 10
        self.assertTrue(self.e.apply(alice, find(self.e, alice, "care", kind="drink")))
        self.assertAlmostEqual(alice.needs["water"], 40)  # one portion of water: +30
        self.assertEqual(alice.inventory.count("water"), 0)

    def test_a_collapse_does_not_feed_anyone(self):
        bob = self.e.player("Bob")
        bob.needs.update({"food": 0, "water": 0, "energy": 0})
        bob.health = 1
        self.assertTrue(bob.live(0.1, False, 20, 18))
        self.assertEqual((bob.needs["food"], bob.needs["water"]), (0, 0))
        self.assertGreater(bob.needs["energy"], 0)

    def test_tending_the_fire_burns_wood_and_keeps_it_lit(self):
        kalani = self.e.player("Kalani")
        self.gov.occupations["Firekeeper"].append(kalani)
        self.e.production.fire_until = self.e.clock + 10
        kalani = self.actor("Kalani")
        wood = self.store["wood"]
        self.assertTrue(self.e.apply(kalani, find(self.e, kalani, "work", task="tend_fire")))
        self.assertEqual(self.store["wood"], wood - 2)
        self.finish("Kalani")
        self.assertGreater(self.e.fire_hours_left(), 3)

    def test_a_job_counts_for_the_tribe_only_while_it_is_worked(self):
        bob = self.e.player("Bob")
        self.gov.occupations["Gatherer"].append(bob)
        fresh = society.compute_qualities(self.gov)["food"]["detail"]["supply"]
        self.e.game_state.clock += 3 * life_hours_to_calendar(18)
        self.assertEqual(self.e.work_activity("Bob"), 0.0)
        idle = society.compute_qualities(self.gov)["food"]["detail"]["supply"]
        self.assertLess(idle, fresh)

    def test_camp_state_survives_a_save(self):
        from core.engine import GameEngine
        import json
        self.e.production.last_worked["Bob"] = 1234
        self.e.production.fire_until = 999
        loaded = GameEngine.from_dict(json.loads(json.dumps(self.e.to_dict())))
        self.assertEqual(loaded.production.last_worked["Bob"], 1234)
        self.assertEqual(loaded.production.fire_until, 999)


if __name__ == "__main__":
    unittest.main()


class KeepingTest(unittest.TestCase):
    """What work brings back goes to the worker's pack; NPCs share only their excess."""

    def setUp(self):
        self.e = new_engine()
        self.store = self.e.possessions.ground
        for p in self.e.players:
            p.inventory.load([])

    def test_an_npc_keeps_a_few_meals_and_shares_the_rest(self):
        bob = self.e.player("Bob")
        kept, shared = self.e.possessions.bring_back(bob, [{"item": "berries", "count": 30}])
        self.assertTrue(kept and shared)
        portion = self.e.possessions._portion("food")
        from world.items import KEEPING
        self.assertGreaterEqual(bob.inventory.count("berries") * 12, KEEPING["meals"] * portion)
        self.assertEqual(self.store["berries"], shared[0]["count"])

    def test_an_npc_with_enough_food_shares_it_all(self):
        bob = self.e.player("Bob")
        bob.inventory.add("meat", 10)
        kept, shared = self.e.possessions.bring_back(bob, [{"item": "berries", "count": 5}])
        self.assertEqual(kept, [])
        self.assertEqual(self.store["berries"], 5)

    def test_a_human_player_keeps_everything(self):
        alice = self.e.player("Alice")
        self.assertEqual(alice.controller, "human")
        kept, shared = self.e.possessions.bring_back(alice, [{"item": "stone", "count": 4}])
        self.assertEqual((kept, shared), ([{"item": "stone", "count": 4}], []))

    def test_materials_nobody_in_ones_job_uses_go_to_the_store(self):
        bob = self.e.player("Bob")
        self.e.possessions.bring_back(bob, [{"item": "stone", "count": 4}])
        self.assertEqual(self.store.get("stone"), 4)

    def test_only_those_whose_job_burns_or_shapes_it_keep_wood_and_stone(self):
        from tests.helpers import give_work
        bob = self.e.player("Bob")
        self.e.possessions.bring_back(bob, [{"item": "wood", "count": 4}])
        self.assertEqual(bob.inventory.count("wood"), 0)  # laying the dead to rest takes wood from the store
        keeper = give_work(self.e, "Bob", "Firekeeper")
        self.e.possessions.bring_back(keeper, [{"item": "wood", "count": 4}])
        self.assertEqual(keeper.inventory.count("wood"), 4)

    def test_npcs_put_back_materials_their_work_does_not_use(self):
        bob = self.e.player("Bob")
        bob.inventory.add("wood", 5)
        bob.inventory.add("stone", 3)
        self.assertTrue(self.e.possessions.put_back(bob))
        self.assertEqual((bob.inventory.count("wood"), bob.inventory.count("stone")), (0, 0))
        self.assertEqual((self.store.get("wood"), self.store.get("stone")), (5, 3))
        self.assertFalse(self.e.possessions.put_back(bob))

    def test_npcs_take_only_the_next_meal_from_the_store(self):
        from world.items import KEEPING
        bob = self.e.player("Bob")
        self.e.possessions.deliver([{"item": "berries", "count": 40}])
        self.assertTrue(self.e.possessions.restock(bob))
        portion, per = self.e.possessions._portion("food"), ITEMS["berries"].use["food"]
        self.assertLess((bob.inventory.count("berries") - 1) * per, KEEPING["restock_meals"] * portion)

    def test_hungry_npcs_take_varied_food_from_the_store(self):
        bob = self.e.player("Bob")
        self.e.possessions.deliver([{"item": "berries", "count": 20}, {"item": "roots", "count": 20},
                                    {"item": "water", "count": 10}])
        self.assertTrue(self.e.possessions.restock(bob))
        self.assertGreater(bob.inventory.count("berries"), 0)
        self.assertGreater(bob.inventory.count("roots"), 0)
        self.assertGreater(bob.inventory.count("water"), 0)
        self.assertFalse(self.e.possessions.restock(bob))  # stocked up now


class ToolsAndResearchTest(WorkTest):
    """Research opens the work and the better tools; jobs can be filled before their tools exist, and the
    worker waits for one and takes it from the store the moment there is one."""

    def recipes_open_to(self, name):
        p = self.e.player(name)
        return {key for kind, key, _ in self.e.work_options(p) if kind == "craft"}

    def test_stone_tools_need_stone_cutting(self):
        hiro = self.e.player("Hiro")
        self.gov.occupations["Toolmaker"].append(hiro)
        self.e.possessions.deliver([{"item": "flint", "count": 4}])
        self.gov.innovation_pool.discovered.update({"Toolmaking", "Hunting", "Archery"})
        made = self.recipes_open_to("Hiro")
        self.assertTrue({"wooden_hand_axe", "wooden_knife", "wooden_spear", "bow", "arrows"} <= made)
        self.assertFalse({"hand_axe", "stone_knife", "flint_spear", "flint_arrows"} & made)
        self.gov.innovation_pool.discovered.add("Stone Cutting")
        self.assertTrue({"hand_axe", "stone_knife", "flint_spear", "flint_arrows"} <= self.recipes_open_to("Hiro"))

    def test_bows_and_arrows_need_only_wood_and_archery(self):
        from core import work as WORK
        from innovations.innovation import ALL_INNOVATIONS
        self.assertNotIn("Stone Cutting", ALL_INNOVATIONS["Archery"].prerequisites)
        for key in ("bow", "arrows", "wooden_spear", "wooden_hand_axe", "wooden_knife"):
            self.assertEqual({s["item"] for s in WORK.RECIPES[key].consumes}, {"wood"}, key)

    def test_warriors_need_research_of_their_own(self):
        bob = self.e.player("Bob")
        self.gov.innovation_pool.discovered.update({"Toolmaking"})
        self.assertFalse(self.gov.can_take_occupation("Warrior", bob, switching=True)[0])
        self.gov.innovation_pool.discovered.add("Camp Defense")
        self.assertTrue(self.gov.can_take_occupation("Warrior", bob, switching=True)[0])

    def test_an_appointed_hunter_waits_for_a_spear_then_takes_one(self):
        self.gov.innovation_pool.discovered.update({"Toolmaking", "Hunting"})
        imani = self.e.player("Imani")
        self.gov.occupations["Hunter"].append(imani)
        self.assertIn("wooden_spear", self.e.observe(imani)["camp"]["tools_waited_for"])
        self.e._live_one_day()
        self.assertEqual(imani.inventory.count("wooden_spear"), 0)  # nothing to take yet: waiting
        self.assertIsNotNone(self.e.work_problem(imani, "work", "hunt"))
        self.e.possessions.deliver([{"item": "wooden_spear", "count": 1}])
        self.e._live_one_day()
        self.assertEqual(imani.inventory.count("wooden_spear"), 1)  # fetched it at once
        self.assertNotIn("wooden_spear", self.store)
        self.assertIsNone(self.e.work_problem(imani, "work", "hunt"))
        self.assertEqual(self.e.observe(imani)["camp"]["tools_waited_for"], [])

    def test_a_better_tool_stands_in_for_a_lesser_one(self):
        self.gov.innovation_pool.discovered.update({"Toolmaking", "Camp Defense", "Stone Cutting"})
        bob = self.e.player("Bob")
        self.gov.occupations["Warrior"].append(bob)
        self.e.possessions.deliver([{"item": "flint_spear", "count": 1}])
        self.e._live_one_day()
        self.assertEqual(bob.inventory.count("flint_spear"), 1)
        self.assertIsNone(self.e.work_problem(bob, "work", "patrol"))
        # In the camp's stock, flint spears count toward the wooden spears it wants.
        from controllers.npc import NPCController
        self.e.possessions.deliver([{"item": "flint_spear", "count": 5}])
        self.assertEqual(NPCController._shortage(self.e.observe(bob), "wooden_spear"), 0)

    def test_flint_arrows_go_first_and_hunt_better(self):
        self.gov.innovation_pool.discovered.update({"Toolmaking", "Hunting", "Archery", "Stone Cutting"})
        imani = self.e.player("Imani")
        self.gov.occupations["Hunter"].append(imani)
        imani.inventory.add("bow", 1)
        self.e.possessions.deliver([{"item": "arrows", "count": 5}, {"item": "flint_arrows", "count": 5}])
        imani = self.actor("Imani")
        self.assertTrue(self.e.apply(imani, find(self.e, imani, "work", task="hunt")))
        self.assertEqual((self.store.get("flint_arrows"), self.store.get("arrows")), (4, 5))
        event = next(ev for ev in self.e.events if ev[2] == "work_done" and ev[3]["player"] == "Imani")
        self.assertEqual(event[3]["ammo"], ["flint_arrows"])
        from core import work as WORK
        self.assertGreater(self.e.production._tool_yield(WORK.TASKS["hunt"], "flint_arrows"), 1.0)

    def test_a_bow_without_arrows_falls_back_to_a_spear(self):
        self.gov.innovation_pool.discovered.update({"Toolmaking", "Hunting", "Archery"})
        imani = self.e.player("Imani")
        self.gov.occupations["Hunter"].append(imani)
        imani.inventory.add("bow", 1)
        self.assertIsNotNone(self.e.work_problem(imani, "work", "hunt"))  # a bow, no arrows, no spear
        self.e.possessions.deliver([{"item": "wooden_spear", "count": 1}])
        from core import work as WORK
        self.assertEqual(self.e.production._tool_for(imani, WORK.TASKS["hunt"]), "wooden_spear")
        self.assertIsNone(self.e.work_problem(imani, "work", "hunt"))


class SitesAndGardensTest(WorkTest):
    def test_a_known_site_makes_the_trip_certain(self):
        from core import work as WORK
        hunt, forage = WORK.TASKS["hunt"], WORK.TASKS["forage"]
        self.assertEqual(WORK.trip_chance(hunt, 0, True), 1.0)
        self.assertEqual(WORK.trip_chance(forage, 0, True), 1.0)
        self.assertLess(WORK.trip_chance(hunt, 50, False), WORK.trip_chance(forage, 50, False))

    def test_a_kill_feeds_far_more_than_a_forage(self):
        from core import work as WORK
        from world.items import ITEMS
        food = lambda t: sum(y["amount"] * y.get("chance", 1) * ITEMS[y["item"]].use.get("food", 0) for y in t.yields)
        self.assertGreaterEqual(food(WORK.TASKS["hunt"]), 3 * food(WORK.TASKS["forage"]))

    def test_a_sustenance_gardener_makes_plant_places_but_gathers_nothing(self):
        esi = self.e.player("Esi")
        self.gov.innovation_pool.discovered.add("Forest Gardening")
        self.assertFalse(self.gov.can_take_occupation("Sustenance Gardener", esi)[0])  # not yet
        self.gov.innovation_pool.discovered.add("Sustenance Gardening")
        self.assertTrue(self.gov.can_take_occupation("Sustenance Gardener", esi)[0])
        self.gov.occupations["Sustenance Gardener"].append(esi)
        self.e.production.sites.clear()
        from core import work as WORK
        self.assertEqual(WORK.TASKS["tend_garden"].yields, [])  # plants the place; Gatherers do the gathering
        esi = self.actor("Esi")
        self.assertTrue(self.e.apply(esi, find(self.e, esi, "work", task="tend_garden")))
        self.finish("Esi")
        self.assertEqual([(x["kind"] in ("plants", "herbs"), x["by"]) for x in self.e.production.sites], [(True, "Esi")])


class ToolmakingAndWearTest(unittest.TestCase):
    actor, finish = WorkTest.actor, WorkTest.finish

    def setUp(self):
        WorkTest.setUp(self)
        self.gov.innovation_pool.discovered.update({"Toolmaking", "Hunting", "Stone Cutting"})
        self.hiro = self.e.player("Hiro")
        self.gov.occupations["Toolmaker"].append(self.hiro)

    def test_it_takes_tools_to_make_tools_quickly(self):
        act = Action("craft", {"recipe": "wooden_spear"})
        bare = self.e.duration(act, self.hiro)
        self.hiro.inventory.add("stone_knife", 1)
        self.assertLess(self.e.duration(act, self.hiro) * 2.5, bare)  # three times as fast with a stone knife

    def test_a_toolmaker_fetches_a_knife_from_the_store_and_it_wears(self):
        self.e.possessions.deliver([{"item": "stone_knife", "count": 1}])
        hiro = self.actor("Hiro")
        self.assertTrue(self.e.apply(hiro, find(self.e, hiro, "craft", recipe="wooden_spear")))
        self.assertEqual(hiro.inventory.count("stone_knife"), 1)
        random.seed(5)
        from world.items import ITEMS
        ITEMS["stone_knife"].breaks, saved = 0.0, ITEMS["stone_knife"].breaks
        try:
            self.finish("Hiro")
        finally:
            ITEMS["stone_knife"].breaks = saved
        self.assertEqual(self.e.possessions.uses_left(hiro, "stone_knife"), ITEMS["stone_knife"].uses - 1)

    def test_a_tool_worn_all_the_way_down_breaks(self):
        from world.items import ITEMS
        imani = self.e.player("Imani")
        imani.inventory.add("wooden_spear", 1, uses=1)
        self.assertTrue(self.e.possessions.wear_tool(imani, "wooden_spear"))
        self.assertEqual(imani.inventory.count("wooden_spear"), 0)
        imani.inventory.add("wooden_spear", 1, uses=5)
        self.assertFalse(self.e.possessions.wear_tool(imani, "wooden_spear"))
        self.assertEqual(self.e.possessions.uses_left(imani, "wooden_spear"), 4)
        self.assertLess(ITEMS["wooden_spear"].uses, ITEMS["flint_spear"].uses)  # stone lasts longer

    def test_wear_goes_with_the_tool_into_the_store_and_saves(self):
        from core.engine import GameEngine
        imani = self.e.player("Imani")
        imani.inventory.add("wooden_spear", 1, uses=3)
        slot = imani.inventory.wear_slot("wooden_spear")
        self.assertTrue(self.e.act_now(imani, Action("drop_item", {"slot": slot})))
        self.assertEqual(self.e.possessions.wear["wooden_spear"], [3])
        restored = GameEngine.from_dict(self.e.to_dict())
        self.assertEqual(restored.possessions.wear["wooden_spear"], [3])
        bob = self.e.player("Bob")
        self.assertTrue(self.e.act_now(bob, Action("pick_up", {"item": "wooden_spear", "count": 1})))
        self.assertEqual(self.e.possessions.uses_left(bob, "wooden_spear"), 3)
        self.assertNotIn("wooden_spear", self.e.possessions.wear)

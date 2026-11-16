"""Inventories: slots and stacks, the camp ground, giving, trading, using items, and saving."""
import json
import unittest

from controllers.npc import NPCController
from core.actions import Action
from core.engine import GameEngine
from tests.helpers import new_engine
from world.items import ITEMS, SLOTS, Inventory


class InventoryModelTest(unittest.TestCase):
    def test_add_tops_up_stacks_then_uses_free_slots(self):
        inv = Inventory(3)
        cap = ITEMS["stone"].max_stack
        self.assertEqual(inv.add("stone", cap + 2), 0)
        self.assertEqual([s["count"] for s in inv.slots if s], [cap, 2])
        self.assertEqual(inv.add("stone", 2 * cap), 2)  # tops up the second stack, fills the third, 2 left over
        self.assertEqual(inv.free_slots(), 0)
        self.assertEqual(inv.room_for("stone"), 0)

    def test_move_split_merge_and_swap(self):
        inv = Inventory(4)
        inv.add("stone", 6)
        inv.add("wood", 2)
        self.assertTrue(inv.move(0, 2, 2))   # split two stones into an empty slot
        self.assertEqual((inv.slots[0]["count"], inv.slots[2]["count"]), (4, 2))
        self.assertTrue(inv.move(2, 0))      # merge them back
        self.assertEqual(inv.slots[0]["count"], 6)
        self.assertIsNone(inv.slots[2])
        self.assertTrue(inv.move(0, 1))      # swap with the wood
        self.assertEqual((inv.slots[0]["item"], inv.slots[1]["item"]), ("wood", "stone"))
        self.assertFalse(inv.move(1, 0, 3))  # part of a stack can't land on a different item
        self.assertFalse(inv.move(3, 0))     # nothing to move

    def test_sort_merges_and_packs(self):
        inv = Inventory(5)
        inv.slots = [None, {"item": "wood", "count": 1}, {"item": "stone", "count": 2}, None,
                     {"item": "wood", "count": 3}]
        inv.sort()
        self.assertEqual(inv.slots[:2], [{"item": "wood", "count": 4}, {"item": "stone", "count": 2}])  # items.json order
        self.assertEqual(inv.free_slots(), 3)


class PossessionsTest(unittest.TestCase):
    def setUp(self):
        self.e = new_engine()
        self.alice, self.imani = self.e.player("Alice"), self.e.player("Imani")
        self.alice.inventory.add("stone", 3)
        self.alice.inventory.add("wood", 2)

    def q(self, player, type_, **params) -> bool:
        return self.e.act_now(player, Action(type_, params))

    def test_everyone_starts_with_items_and_finite_slots(self):
        self.assertEqual(len(self.alice.inventory.slots), SLOTS)
        self.assertGreater(self.alice.inventory.count("stone"), 0)
        self.assertGreater(self.imani.inventory.count("meat"), 0)
        view = self.e.observe(self.alice)
        self.assertEqual(view["possessions"]["inventory"]["size"], SLOTS)
        self.assertEqual(view["possessions"]["ground"], [])  # the camp starts with nothing
        self.assertIn("inventory", view["players"][0])

    def test_drop_and_pick_up_need_no_moment_to_act(self):
        self.assertNotIn("Alice", self.e.idle)  # not her moment, yet she can handle items
        stones = self.alice.inventory.count("stone")
        ground = self.e.possessions.ground.get("stone", 0)
        slot = next(i for i, s in enumerate(self.alice.inventory.slots) if s and s["item"] == "stone")
        self.assertTrue(self.q(self.alice, "drop_item", slot=slot, count=2))
        self.assertEqual(self.alice.inventory.count("stone"), stones - 2)
        self.assertEqual(self.e.possessions.ground["stone"], ground + 2)
        self.assertTrue(self.q(self.alice, "pick_up", item="stone", count=ground + 2))
        self.assertEqual(self.alice.inventory.count("stone"), stones + ground)
        self.assertNotIn("stone", self.e.possessions.ground)
        self.assertFalse(self.q(self.alice, "pick_up", item="stone"))

    def test_pick_up_stops_when_the_pack_is_full(self):
        self.alice.inventory.slots = \
            [{"item": "wood", "count": ITEMS["wood"].max_stack} for _ in range(SLOTS)]
        self.assertFalse(self.q(self.alice, "pick_up", item="stone"))

    def test_give_puts_items_in_their_pack(self):
        slot = next(i for i, s in enumerate(self.alice.inventory.slots) if s and s["item"] == "wood")
        before = self.imani.inventory.count("wood")
        self.assertTrue(self.q(self.alice, "give_item", slot=slot, to="Imani", count=1))
        self.assertEqual(self.imani.inventory.count("wood"), before + 1)

    def test_use_restores_needs(self):
        self.alice.needs["water"] = 20
        slot = next(i for i, s in enumerate(self.alice.inventory.slots) if s and s["item"] == "water")
        n = self.alice.inventory.count("water")
        self.assertTrue(self.q(self.alice, "use_item", slot=slot))
        self.assertEqual(self.alice.needs["water"], 20 + ITEMS["water"].use["water"])
        self.assertEqual(self.alice.inventory.count("water"), n - 1)
        stone = next(i for i, s in enumerate(self.alice.inventory.slots) if s and s["item"] == "stone")
        self.assertFalse(self.q(self.alice, "use_item", slot=stone))

    def test_no_handling_items_while_asleep_but_sorting_is_fine(self):
        self.e.last_action["Alice"] = {"type": "care", "params": {"kind": "sleep"}}
        self.e.free_at["Alice"] = self.e.clock + 1000
        self.assertFalse(self.q(self.alice, "drop_item", slot=0))
        self.assertTrue(self.q(self.alice, "sort_items"))

    def test_barter_needs_research_but_asking_and_giving_do_not(self):
        self.e.government.innovation_pool.discovered.discard("Barter System")
        self.assertFalse(self.e.observe(self.alice)["possessions"]["barter"])
        self.assertFalse(self.q(self.alice, "offer_trade", to="Imani", give=[{"item": "stone", "count": 2}],
                                want=[{"item": "meat", "count": 1}]))  # a trade: not yet
        self.assertTrue(self.q(self.alice, "offer_trade", to="Imani", give=[],
                               want=[{"item": "meat", "count": 1}]))   # asking for a gift: always
        self.e.government.innovation_pool.discovered.add("Barter System")
        self.assertTrue(self.e.observe(self.alice)["possessions"]["barter"])

    def test_trade_offer_accepted_swaps_items(self):
        self.e.government.innovation_pool.discovered.add("Barter System")
        a0, i0 = self.alice.inventory.totals(), self.imani.inventory.totals()
        self.assertTrue(self.q(self.alice, "offer_trade", to="Imani", give=[{"item": "stone", "count": 2}],
                               want=[{"item": "meat", "count": 1}]))
        offer = self.e.possessions.offers[0]
        self.assertTrue(self.e.quick(self.imani, Action("answer_trade", {"offer": offer["id"], "accept": True})))
        self.assertEqual(self.alice.inventory.count("meat"), a0.get("meat", 0) + 1)
        self.assertEqual(self.imani.inventory.count("stone"), i0.get("stone", 0) + 2)
        self.assertFalse(self.e.possessions.offers)

    def test_offer_must_be_real_and_only_the_target_answers(self):
        self.assertFalse(self.q(self.alice, "offer_trade", to="Imani", give=[{"item": "meat", "count": 99}], want=[]))
        self.assertFalse(self.q(self.alice, "offer_trade", to="Alice", give=[{"item": "stone", "count": 1}], want=[]))
        self.assertTrue(self.q(self.alice, "offer_trade", to="Imani", give=[{"item": "stone", "count": 1}], want=[]))
        oid = self.e.possessions.offers[0]["id"]
        self.assertFalse(self.q(self.alice, "answer_trade", offer=oid, accept=True))  # not hers to answer
        self.assertTrue(self.q(self.alice, "cancel_trade", offer=oid))

    def test_npcs_take_fair_trades_and_refuse_bad_ones(self):
        npc = NPCController("Imani")
        view = self.e.observe(self.imani)
        bad = {"id": 1, "give": [{"item": "stone", "count": 1}], "want": [{"item": "meat", "count": 1}]}
        good = {"id": 2, "give": [{"item": "stone", "count": 3}, {"item": "wood", "count": 2}],
                "want": [{"item": "meat", "count": 1}]}
        self.assertFalse(npc.answer_offer(view, bad).action.params["accept"])
        self.assertTrue(npc.answer_offer(view, good).action.params["accept"])

    def test_inventories_ground_and_offers_survive_a_save(self):
        self.q(self.alice, "drop_item", slot=0, count=1)
        self.q(self.alice, "offer_trade", to="Imani", give=[{"item": "stone", "count": 1}], want=[])
        data = json.loads(json.dumps(self.e.to_dict()))
        loaded = GameEngine.from_dict(data)
        self.assertEqual(loaded.player("Alice").inventory.slots, self.alice.inventory.slots)
        self.assertEqual(loaded.possessions.ground, self.e.possessions.ground)
        self.assertEqual(loaded.possessions.offers, self.e.possessions.offers)


if __name__ == "__main__":
    unittest.main()

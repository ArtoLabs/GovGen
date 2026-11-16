"""Resigning from an office, a new holder's grace period, and an unhappy tribe blaming its top leader."""
import unittest

from core.engine import GameEngine
from tests.helpers import become_actor, find, new_engine, seat


class ResignTest(unittest.TestCase):
    def test_an_office_holder_can_resign(self):
        e = new_engine(1)
        seat(e.government, "Clan Leader", e.player("Alice"))
        alice = become_actor(e, "Alice")
        act = find(e, alice, "resign", office="Clan Leader")
        self.assertIsNotNone(act)
        self.assertTrue(e.apply(alice, act))
        self.assertNotIn("Clan Leader", e.government.offices_of(e.player("Alice")))
        self.assertTrue(any(b.key == "elect:Clan Leader" for b in e.voting.elections()))  # the seat is filled again

    def test_nobody_without_an_office_can_resign(self):
        e = new_engine(1)
        bob = become_actor(e, "Bob")
        self.assertIsNone(find(e, bob, "resign"))


class GraceTest(unittest.TestCase):
    def test_a_new_holder_cannot_be_challenged_persuaded_against_or_voted_out_at_once(self):
        e = new_engine(1)
        gov = e.government
        gov.assign_office("Clan Leader", e.player("Dmitri"))  # just now: in grace
        gov.assign_office("Elder", e.player("Greta"))
        self.assertTrue(gov.in_grace("Clan Leader", e.player("Dmitri")))
        bob = become_actor(e, "Bob")
        self.assertIsNone(find(e, bob, "persuade", office="Clan Leader", target="Dmitri"))
        self.assertIsNone(find(e, bob, "challenge", office="Clan Leader", holder="Dmitri"))
        greta = e.player("Greta")
        seat(gov, "Elder", e.player("Esi"))
        self.assertNotIn(("remove_office", "Clan Leader", e.player("Dmitri")), e.voting.available_motions(e.player("Esi")))
        self.assertTrue(greta)
        # Once the grace is over they can be.
        e.game_state.clock += gov.grace_hours_left("Clan Leader", e.player("Dmitri")) + 1
        self.assertFalse(gov.in_grace("Clan Leader", e.player("Dmitri")))
        self.assertIn(("Clan Leader", "Dmitri"), e.contests.persuasion_targets(bob))
        self.assertIn(("remove_office", "Clan Leader", e.player("Dmitri")), e.voting.available_motions(e.player("Esi")))

    def test_grace_is_saved(self):
        e = new_engine(1)
        e.government.assign_office("Clan Leader", e.player("Dmitri"))
        r = GameEngine.from_dict(e.to_dict())
        self.assertTrue(r.government.in_grace("Clan Leader", r.player("Dmitri")))


class BlameTest(unittest.TestCase):
    def test_the_top_office_carries_the_discontent(self):
        from controllers.npc import NPCController
        e = new_engine(1)
        seat(e.government, "Clan Leader", e.player("Dmitri"))
        seat(e.government, "Elder", e.player("Greta"))
        bob = e.player("Bob")
        bob.satisfaction["leaders"] = 15
        npc = NPCController("Bob")
        view = e.observe(bob)
        self.assertEqual(npc._blame(view, "Clan Leader"), 1.0)
        self.assertLess(npc._blame(view, "Elder"), 0.5)
        self.assertGreater(npc._grievance(view, "Clan Leader", "Dmitri"), npc._grievance(view, "Elder", "Greta"))


if __name__ == "__main__":
    unittest.main()


class CooldownTest(unittest.TestCase):
    def run_campaign(self, win: bool):
        e = new_engine(1)
        seat(e.government, "Clan Leader", e.player("Dmitri"))
        a = become_actor(e, "Alice")
        e.apply(a, find(e, a, "persuade", office="Clan Leader", target="Dmitri"))
        c = e.contests.contests[0]
        for n in c.meters:
            c.meters[n] = 100.0 if win else 0.0
        c.floor = {}
        while e.contests.contest(c.key):
            x = e.step()
            if x:
                e.apply(x, find(e, x, "wait", days=1) or e.legal_actions(x)[0])
        return e

    def test_a_winner_who_resigns_may_campaign_again_at_once(self):
        e = self.run_campaign(win=True)
        alice = e.player("Alice")
        self.assertIn("Clan Leader", e.government.offices_of(alice))
        e.government.resign("Clan Leader", alice)
        self.assertEqual(e.contests.cooldown_hours_left("Alice"), 0)
        self.assertTrue(e.contests.persuasion_targets(alice))

    def test_a_loser_waits_a_day_night_cycle(self):
        from world.environment import CYCLE_HOURS
        e = self.run_campaign(win=False)
        self.assertNotIn("Clan Leader", e.government.offices_of(e.player("Alice")))
        left = e.contests.cooldown_hours_left("Alice")
        self.assertTrue(0 < left <= CYCLE_HOURS)
        self.assertEqual(e.observe(e.player("Alice"))["contest_cooldown_hours"], left)


class OthersLossTest(unittest.TestCase):
    def test_someone_elses_failed_campaign_does_not_block_you(self):
        e = CooldownTest().run_campaign(win=False)  # Alice loses against Dmitri
        bob = e.player("Bob")
        self.assertEqual(e.contests.cooldown_hours_left("Bob"), 0)
        self.assertIn(("Clan Leader", "Dmitri"), e.contests.persuasion_targets(bob))
        self.assertEqual(e.observe(bob)["offices"]["Clan Leader"]["protected_hours"], {})

    def test_the_cooldown_is_half_a_day_night_cycle(self):
        from world.environment import CYCLE_HOURS
        e = CooldownTest().run_campaign(win=False)
        self.assertLessEqual(e.contests.cooldown_hours_left("Alice"), CYCLE_HOURS / 2)

    def test_a_new_holder_is_named_in_the_picker_note(self):
        from ui.model import protected_note
        e = new_engine(1)
        e.government.assign_office("Clan Leader", e.player("Dmitri"))
        self.assertIn("Dmitri as Clan Leader", protected_note(e.observe(e.player("Bob"))))

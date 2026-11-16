"""Taking an office by persuasion or by challenge."""
import random
import unittest

from core.contests import CHALLENGE_KINDS, power
from tests.helpers import become_actor, find, new_engine, seat
from utils.messages import Messages


def run_until_done(e, contest):
    """Advance time (everyone else just waits) until the contest has been resolved."""
    for _ in range(20000):
        if e.contests.contest(contest.key) is None:
            return
        actor = e.step()
        if actor is not None:
            e.apply(actor, find(e, actor, "wait", days=1) or e.legal_actions(actor)[0])
    raise AssertionError("contest never ended")


class PersuasionTest(unittest.TestCase):
    def setUp(self):
        self.e = new_engine(1)
        self.gov = self.e.government
        seat(self.gov, "Clan Leader", self.e.player("Dmitri"))

    def test_campaign_gives_everyone_a_meter_and_can_replace_the_holder(self):
        bob = become_actor(self.e, "Bob")
        act = find(self.e, bob, "persuade", office="Clan Leader", target="Dmitri")
        self.assertIsNotNone(act)
        self.assertTrue(self.e.apply(bob, act))
        c = self.e.contests.contests[0]
        self.assertNotIn("Bob", c.meters)
        self.assertNotIn("Dmitri", c.meters)  # the holder resists by rallying, not with a meter
        voters = [p for p in self.e.players if self.e.government.can_vote(p)]  # children don't take part
        self.assertEqual(len(c.meters), len(voters) - 2)
        for name in c.meters:  # a perfectly persuaded tribe
            c.meters[name] = 100.0
        run_until_done(self.e, c)
        self.assertIn("Clan Leader", self.gov.offices_of(self.e.player("Bob")))
        self.assertNotIn("Clan Leader", self.gov.offices_of(self.e.player("Dmitri")))

    def test_unpersuaded_tribe_keeps_the_holder(self):
        bob = become_actor(self.e, "Bob")
        self.e.apply(bob, find(self.e, bob, "persuade", office="Clan Leader", target="Dmitri"))
        c = self.e.contests.contests[0]
        for name in c.meters:
            c.meters[name] = 0.0
        self.e.contests.tick(0)  # no time passes
        c.ends = self.e.clock
        self.e.contests.process()
        self.assertIn("Clan Leader", self.gov.offices_of(self.e.player("Dmitri")))

    def test_canvassing_raises_a_meter_and_rallying_lowers_it(self):
        bob = become_actor(self.e, "Bob")
        self.e.apply(bob, find(self.e, bob, "persuade", office="Clan Leader", target="Dmitri"))
        c = self.e.contests.contests[0]
        before = c.meters["Esi"]
        self.assertTrue(self.e.contests.canvass(bob, c.key, "Esi"))
        self.assertGreater(c.meters["Esi"], before)
        raised = c.meters["Esi"]
        self.assertTrue(self.e.contests.rally(self.e.player("Dmitri"), c.key, "Esi"))
        self.assertLess(c.meters["Esi"], raised)

    def test_winning_a_vacant_seat_calls_off_its_election(self):
        e = new_engine(2)
        self.assertTrue(any(b.key == "elect:Clan Leader" for b in e.voting.active_votes))
        bob = e.player("Bob")
        self.assertTrue(e.government.seize_office("Clan Leader", bob, None))
        self.assertFalse(any(b.key == "elect:Clan Leader" for b in e.voting.active_votes))


class ChallengeTest(unittest.TestCase):
    def setUp(self):
        self.e = new_engine(1)
        self.gov = self.e.government
        seat(self.gov, "Clan Leader", self.e.player("Greta"))  # old and frail, but wise

    def challenge(self, who="Dmitri"):
        actor = become_actor(self.e, who)
        act = find(self.e, actor, "challenge", office="Clan Leader", holder="Greta")
        self.assertIsNotNone(act)
        self.assertEqual(act.params["kind"], "")  # the challenger only names whom they challenge
        self.assertTrue(self.e.apply(actor, act))
        return self.e.contests.contests[0]

    def answer(self, kind, c=None):
        c = c or self.challenge()
        greta = become_actor(self.e, "Greta")
        choice = find(self.e, greta, "answer_challenge", contest=c.key, kind=kind)
        self.assertIsNotNone(choice)
        self.assertTrue(self.e.apply(greta, choice))
        return c

    def test_the_defender_chooses_the_contest(self):
        c = self.challenge()
        self.assertTrue(c.awaiting_answer)
        self.assertEqual(set(c.allowed), {"oration", "fight"})  # a Clan Leader's work (leadership) has no contest
        c = self.answer("oration", c)
        self.assertEqual(c.kind, "oration")

    def test_contestants_in_an_oration_speak_eat_and_drink(self):
        c = self.answer("oration")
        self.assertLess(self.e.free_at["Dmitri"], c.ends)  # not held busy until it ends
        dmitri = become_actor(self.e, "Dmitri")
        self.assertIsNotNone(self.e.contests.running_challenge("Dmitri"))
        types = {(a.type, a.params.get("kind")) for a in self.e.legal_actions(dmitri)}
        self.assertIn(("care", "eat"), types)
        self.assertIn(("care", "drink"), types)
        self.assertNotIn(("care", "sleep"), types)
        self.assertFalse(any(t == "take_occupation" for t, _ in types))
        listener = next(n for n in c.meters if n != "Greta")
        before = c.meters[listener]
        speech = find(self.e, dmitri, "canvass", contest=c.key, listener=listener)
        self.assertIsNotNone(speech)
        self.assertTrue(self.e.apply(dmitri, speech))
        self.assertGreater(c.meters[listener], before)
        greta = become_actor(self.e, "Greta")
        back = find(self.e, greta, "rally", contest=c.key, listener=listener)
        self.assertIsNotNone(back)  # the defender speaks too, pulling listeners back
        mid = c.meters[listener]
        self.e.apply(greta, back)
        self.assertLess(c.meters[listener], mid)
        self.assertIsNotNone(self.e.observe(dmitri)["in_contest"])

    def test_a_ritual_fight_holds_both_until_it_ends(self):
        c = self.answer("fight")
        self.assertEqual(self.e.free_at["Dmitri"], c.ends)
        self.assertEqual(self.e.free_at["Greta"], c.ends)

    def test_skill_contest_is_in_the_defenders_work(self):
        esi = self.e.player("Esi")
        seat(self.gov, "Elder", esi)
        kinds = self.e.contests.challenge_kinds_for(esi, self.gov.government_type.offices["Elder"])
        self.assertIn("lore", kinds)  # an Elder's work is lore

    def test_no_answer_means_the_defenders_best_contest(self):
        c = self.challenge()
        self.e.game_state.clock = c.ends
        self.e.contests.process()
        self.assertFalse(c.awaiting_answer)
        self.assertNotEqual(c.kind, "fight")  # Greta (STR 3) would never pick a fight

    def test_fight_is_a_ritual_not_to_the_death(self):
        c = self.challenge()
        self.e.contests._begin(c, "fight")
        for name in (c.challenger, c.defender):
            self.e.free_at[name] = c.ends
        run_until_done(self.e, c)
        self.assertGreater(self.e.player("Greta").health, 0)
        self.assertGreater(self.e.player("Dmitri").skills["combat"], 4)  # practice, win or lose

    def test_oration_trains_persuasion_even_for_the_loser(self):
        c = self.challenge()
        before = {n: self.e.player(n).skills["persuasion"] for n in ("Dmitri", "Greta")}
        self.e.contests._begin(c, "oration")
        c.ends = self.e.clock
        self.e.contests.process()
        for n in before:
            self.assertGreater(self.e.player(n).skills["persuasion"], before[n])

    def test_elders_cannot_be_fought_for(self):
        seat(self.gov, "Elder", self.e.player("Esi"))
        c_kinds = self.e.contests.challenge_kinds_for(self.e.player("Esi"), self.gov.government_type.offices["Elder"])
        self.assertNotIn("fight", c_kinds)
        self.assertIn("oration", c_kinds)

    def test_power_rewards_attributes_and_skill(self):
        fight = CHALLENGE_KINDS["fight"]
        weak = power({"strength": 3, "dexterity": 3, "constitution": 3}, {}, fight.attributes, fight.skill)
        strong = power({"strength": 9, "dexterity": 7, "constitution": 8}, {"combat": 4}, fight.attributes, fight.skill)
        self.assertGreater(strong, weak)

    def test_contests_survive_a_save(self):
        c = self.challenge()
        self.e.contests._begin(c, "oration")
        from core.engine import GameEngine
        restored = GameEngine.from_dict(self.e.to_dict())
        self.assertEqual(len(restored.contests.contests), 1)
        self.assertEqual(restored.contests.contests[0].meters, c.meters)


class DefenderStandingTest(unittest.TestCase):
    def test_a_leader_the_tribe_is_fed_up_with_can_hardly_defend(self):
        from tests.helpers import new_engine
        e = new_engine()
        cm = e.contests
        for p in e.players:
            p.satisfaction["leaders"] = 70
        liked = cm.standing()
        for p in e.players:
            p.satisfaction["leaders"] = 20
        self.assertGreaterEqual(liked, 1.0)
        self.assertLessEqual(cm.standing(), 0.25)


if __name__ == "__main__":
    unittest.main()


class CampaignFairnessTest(unittest.TestCase):
    """Persuading never backfires, and failing leadership makes a campaign easier."""

    def campaign(self, unhappy: bool):
        e = new_engine(1)
        seat(e.government, "Clan Leader", e.player("Dmitri"))
        for p in e.players:
            p.satisfaction["leaders"] = 20 if unhappy else 70
        bob = e.player("Bob")
        bob.skills["persuasion"] = 0.0
        b = become_actor(e, "Bob")
        e.apply(b, find(e, b, "persuade", office="Clan Leader", target="Dmitri"))
        return e, e.contests.contests[0]

    def test_unhappy_tribes_start_more_persuaded(self):
        _, calm = self.campaign(unhappy=False)
        _, angry = self.campaign(unhappy=True)
        self.assertGreater(sum(angry.meters.values()), sum(calm.meters.values()) + 10 * len(calm.meters))

    def test_the_holder_cannot_push_anyone_below_their_start(self):
        e, c = self.campaign(unhappy=False)
        dmitri = e.player("Dmitri")
        name = next(iter(c.meters))
        start = c.meters[name]
        for _ in range(5):
            e.contests.rally(dmitri, c.key, name)
        self.assertGreaterEqual(c.meters[name], start)

    def test_a_speech_with_no_skill_still_helps(self):
        e, c = self.campaign(unhappy=False)
        bob = e.player("Bob")
        bob.attributes["charisma"] = 1
        for name in list(c.meters):
            before = c.meters[name]
            e.contests.canvass(bob, c.key, name)
            self.assertGreater(c.meters[name], before)

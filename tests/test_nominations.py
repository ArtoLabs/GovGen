"""Standing for office: one election at a time, candidates vote for themselves, nominations can be
declined, and an office is its holder's work."""
import unittest

from tests.helpers import advance_days, become_actor, do, find, new_engine, seat


class NominationTest(unittest.TestCase):
    def setUp(self):
        self.e = new_engine(1)
        self.vm = self.e.voting
        self.chief = self.vm.ballot("elect:Clan Leader")
        self.elder = self.vm.ballot("elect:Elder")

    def test_nobody_stands_in_two_elections(self):
        self.assertTrue(do(self.e, "Alice", "nominate", ballot="elect:Clan Leader", candidate="Bob"))
        cleo = become_actor(self.e, "Cleo")
        self.assertIsNone(find(self.e, cleo, "nominate", ballot="elect:Elder", candidate="Bob"))
        self.assertIsNotNone(find(self.e, cleo, "nominate", ballot="elect:Elder", candidate="Dmitri"))

    def test_a_nomination_can_be_declined_and_is_not_repeated(self):
        do(self.e, "Alice", "nominate", ballot="elect:Elder", candidate="Bob")
        self.assertTrue(do(self.e, "Bob", "decline_nomination", ballot="elect:Elder"))
        self.assertNotIn("Bob", self.elder.nominations)
        cleo = become_actor(self.e, "Cleo")
        self.assertIsNone(find(self.e, cleo, "nominate", ballot="elect:Elder", candidate="Bob"))
        # Bob is free to stand elsewhere.
        self.assertIsNotNone(find(self.e, cleo, "nominate", ballot="elect:Clan Leader", candidate="Bob"))

    def _to_voting(self, *names):
        for i, n in enumerate(names):
            nominator = ["Kalani", "Leila", "Joao"][i]
            self.assertTrue(do(self.e, nominator, "nominate", ballot="elect:Clan Leader", candidate=n))
        advance_days(self.e, 31)
        self.assertTrue(self.chief.is_voting_active())

    def test_candidates_vote_for_themselves_and_are_not_asked(self):
        self._to_voting("Bob", "Cleo")
        self.assertEqual(self.chief.votes["Bob"], ["Bob"])
        self.assertEqual(self.chief.votes["Cleo"], ["Cleo"])
        bob = become_actor(self.e, "Bob")
        self.assertIsNone(find(self.e, bob, "vote", ballot="elect:Clan Leader"))
        self.assertTrue(self.e.observe(bob)["ballots"][0]["you_stand"])

    def test_withdrawing_from_a_two_way_vote_hands_it_to_the_other(self):
        self._to_voting("Bob", "Cleo")
        self.chief.votes["Alice"] = ["Bob"]
        self.assertTrue(do(self.e, "Bob", "decline_nomination", ballot="elect:Clan Leader"))
        self.assertEqual([p.name for p in self.e.government.get_role_holders("Clan Leader")], ["Cleo"])

    def test_withdrawing_from_a_three_way_vote_frees_its_voters(self):
        self._to_voting("Bob", "Cleo", "Dmitri")
        self.chief.votes["Alice"] = ["Bob"]
        self.assertTrue(do(self.e, "Bob", "decline_nomination", ballot="elect:Clan Leader"))
        self.assertEqual(self.chief.choices(), ["Cleo", "Dmitri"])
        alice = become_actor(self.e, "Alice")
        self.assertIsNotNone(find(self.e, alice, "vote", ballot="elect:Clan Leader", choice="Cleo"))
        bob = become_actor(self.e, "Bob")
        self.assertIsNotNone(find(self.e, bob, "vote", ballot="elect:Clan Leader", choice="Dmitri"))


class OfficeIsWorkTest(unittest.TestCase):
    def setUp(self):
        self.e = new_engine(1)
        self.gov = self.e.government

    def test_taking_an_office_gives_up_ones_work(self):
        bob = self.e.player("Bob")
        self.assertTrue(self.gov.take_occupation("Gatherer", bob))
        self.assertTrue(seat(self.gov, "Elder", bob))
        self.assertEqual(self.gov.occupations_of(bob), [])

    def test_office_holders_take_no_occupation(self):
        bob, cleo = self.e.player("Bob"), self.e.player("Cleo")
        seat(self.gov, "Elder", bob)
        seat(self.gov, "Clan Leader", cleo)
        self.assertFalse(self.gov.can_take_occupation("Gatherer", bob)[0])
        self.assertNotIn("Gatherer", self.gov.volunteer_options(bob))
        cleo_turn = become_actor(self.e, "Cleo")
        self.assertFalse(any(a.params.get("appointee") == "Bob" for a in self.e.legal_actions(cleo_turn)
                             if a.type == "appoint"))


if __name__ == "__main__":
    unittest.main()


class CampaignOrNominationTest(unittest.TestCase):
    """Someone running a persuasion campaign can't be nominated, and a nominee can't start one."""

    def setUp(self):
        self.e = new_engine(1)
        seat(self.e.government, "Clan Leader", self.e.player("Dmitri"))

    def test_a_campaigner_cannot_be_nominated(self):
        bob = become_actor(self.e, "Bob")
        act = find(self.e, bob, "persuade", office="Clan Leader", target="Dmitri")
        self.assertIsNotNone(act)
        self.assertTrue(self.e.apply(bob, act))
        cleo = become_actor(self.e, "Cleo")
        self.assertIsNone(find(self.e, cleo, "nominate", ballot="elect:Elder", candidate="Bob"))
        self.assertIsNotNone(find(self.e, cleo, "nominate", ballot="elect:Elder", candidate="Esi"))
        # Not even by forcing the action through.
        from core.actions import Action
        self.assertFalse(self.e.apply(cleo, Action("nominate", {"ballot": "elect:Elder", "candidate": "Bob"})))
        self.assertNotIn("Bob", self.e.voting.ballot("elect:Elder").nominations)

    def test_a_nominee_cannot_start_a_campaign(self):
        bob = become_actor(self.e, "Bob")
        self.assertIsNotNone(find(self.e, bob, "persuade", office="Clan Leader", target="Dmitri"))
        self.assertTrue(do(self.e, "Alice", "nominate", ballot="elect:Elder", candidate="Bob"))
        bob = become_actor(self.e, "Bob")
        self.assertEqual(self.e.contests.persuasion_targets(bob), [])
        self.assertIsNone(find(self.e, bob, "persuade", office="Clan Leader", target="Dmitri"))
        # Declining the nomination frees them to campaign again.
        self.assertTrue(do(self.e, "Bob", "decline_nomination", ballot="elect:Elder"))
        bob = become_actor(self.e, "Bob")
        self.assertIsNotNone(find(self.e, bob, "persuade", office="Clan Leader", target="Dmitri"))

    def test_a_challenger_cannot_be_nominated(self):
        bob = become_actor(self.e, "Bob")
        act = find(self.e, bob, "challenge", office="Clan Leader", holder="Dmitri")
        self.assertIsNotNone(act)
        self.assertTrue(self.e.apply(bob, act))
        cleo = become_actor(self.e, "Cleo")
        self.assertIsNone(find(self.e, cleo, "nominate", ballot="elect:Elder", candidate="Bob"))
        from core.actions import Action
        self.assertFalse(self.e.apply(cleo, Action("nominate", {"ballot": "elect:Elder", "candidate": "Bob"})))

    def test_a_nominee_cannot_challenge(self):
        bob = become_actor(self.e, "Bob")
        self.assertIsNotNone(find(self.e, bob, "challenge", office="Clan Leader", holder="Dmitri"))
        self.assertTrue(do(self.e, "Alice", "nominate", ballot="elect:Elder", candidate="Bob"))
        bob = become_actor(self.e, "Bob")
        self.assertEqual(self.e.contests.challenge_options(bob), [])
        self.assertTrue(do(self.e, "Bob", "decline_nomination", ballot="elect:Elder"))
        bob = become_actor(self.e, "Bob")
        self.assertIsNotNone(find(self.e, bob, "challenge", office="Clan Leader", holder="Dmitri"))

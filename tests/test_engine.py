from innovations.innovation import ALL_INNOVATIONS
import json
import unittest

from core.actions import Action
from core.calendar import ACTION_HOURS, HOURS_PER_DAY, HOURS_PER_YEAR, REFORM_COOLDOWN_HOURS, VOTING_HOURS
from tests.helpers import new_engine, find, do, become_actor, advance_days, advance_until, vote_all, seat, immortal


class EngineBasics(unittest.TestCase):
    def setUp(self):
        self.e = new_engine()
        self.alice, self.bob = self.e.players[0], self.e.players[1]

    def test_only_the_free_player_may_act(self):
        self.assertIs(self.e.step(), self.alice)  # everyone is free at day 1; ties go to the first player
        self.assertTrue(self.e.legal_actions(self.alice))
        self.assertEqual(self.e.legal_actions(self.bob), [])
        self.assertFalse(self.e.apply(self.bob, Action("wait", {"days": 1})))

    def test_illegal_action_refused(self):
        self.e.step()
        self.assertFalse(self.e.apply(self.alice, Action("appoint", {"position": "Elder", "appointee": "Bob"})))
        self.assertEqual(self.e.action_log, [])

    def test_observation_is_plain_data(self):
        json.dumps(self.e.observe(self.alice))

    def test_start_of_game(self):
        view = self.e.observe(self.alice)
        self.assertEqual(view["date"], "Year 0, Spring day 1")
        self.assertEqual(view["age"]["key"], "tribal")
        self.assertEqual(sorted(b["label"] for b in view["ballots"]), ["Clan Leader", "Elder (Seat 1)"])
        self.assertEqual(view["your_interfaces"], ["infrastructure"])
        self.assertEqual(len(self.e.players), 16)
        self.assertEqual(sum(1 for p in self.e.players if self.e.life.is_child(p)), 4)

    def test_actions_take_time(self):
        do(self.e, "Alice", "nominate", ballot="elect:Clan Leader", candidate="Bob")
        self.assertEqual(self.e.free_at["Alice"], ACTION_HOURS["nominate"])
        self.assertIs(self.e.step(), self.bob)  # Bob is free before Alice is again
        self.e.apply(self.bob, find(self.e, self.bob, "wait", days=7))
        self.assertEqual(self.e.free_at["Bob"], 7 * HOURS_PER_DAY)
        self.assertEqual(self.e.action_log[0]["date"], "Year 0, Spring day 1")

    def test_years_pass_with_the_clock(self):
        advance_days(self.e, 360)
        self.assertEqual(self.e.year, 1)
        self.assertGreater(self.e.government.innovation_pool.points + self.e.government.research_progress, 0)


class Research(unittest.TestCase):
    def test_research_takes_time(self):
        e = new_engine()
        with immortal(e):  # this takes years: nobody may die meanwhile and take their points with them
            self._research_takes_time(e)

    def _research_takes_time(self, e):
        gov = e.government
        gov.innovation_pool.points = 0
        seat(gov, "Clan Leader", e.players[0])
        do(e, "Alice", "research", innovation="Chieftainship")
        income = gov.daily_income()
        days_needed = ALL_INNOVATIONS["Chieftainship"].cost / income
        advance_days(e, days_needed * 0.5)
        self.assertNotIn("Chieftainship", gov.innovation_pool.discovered)
        advance_days(e, days_needed * 0.6 + 1)
        self.assertIn("Chieftainship", gov.innovation_pool.discovered)


class Elections(unittest.TestCase):
    def setUp(self):
        self.e = new_engine()
        self.gov = self.e.government

    def test_nominations_then_vote_on_the_clock(self):
        do(self.e, "Alice", "nominate", ballot="elect:Clan Leader", candidate="Alice")
        do(self.e, "Alice", "nominate", ballot="elect:Elder", candidate="Dmitri")
        do(self.e, "Bob", "nominate", ballot="elect:Elder", candidate="Bob")
        elder = next(v for v in self.e.voting.elections() if v.role == "Elder")
        advance_days(self.e, (elder.nominations_close_at - self.e.clock) / HOURS_PER_DAY - 1)
        self.assertTrue(elder.is_nomination_open)
        advance_days(self.e, 1.5)
        self.assertEqual(self.gov.offices_of(self.e.players[0]), ["Clan Leader"])  # sole nominee
        self.assertTrue(elder.is_voting_active())
        vote_all(self.e, lambda name, b: "Dmitri")
        self.assertEqual([p.name for p in self.gov.get_role_holders("Elder")], ["Dmitri"])

    def test_voting_closes_at_deadline_even_if_not_everyone_voted(self):
        do(self.e, "Alice", "nominate", ballot="elect:Elder", candidate="Dmitri")
        do(self.e, "Alice", "nominate", ballot="elect:Elder", candidate="Bob")
        advance_days(self.e, 31)
        elder = next(v for v in self.e.voting.elections() if v.role == "Elder")
        do(self.e, "Cleo", "vote", ballot=elder.key, choice="Bob")
        advance_days(self.e, VOTING_HOURS / HOURS_PER_DAY + 1)
        self.assertEqual([p.name for p in self.gov.get_role_holders("Elder")], ["Bob"])

    def test_one_office_per_player(self):
        do(self.e, "Alice", "nominate", ballot="elect:Clan Leader", candidate="Alice")
        advance_until(self.e, lambda: self.gov.get_role_holders("Clan Leader"))
        elder = next(v for v in self.e.voting.elections() if v.role == "Elder")
        self.assertNotIn("Alice", [p.name for p in self.e.voting.nomination_candidates(elder)])


class Removal(unittest.TestCase):
    def setUp(self):
        self.e = new_engine()
        g, P = self.e.government, {p.name: p for p in self.e.players}
        seat(g, "Clan Leader", P["Alice"])
        for name in ("Bob", "Dmitri", "Greta"):
            seat(g, "Elder", P[name])
        self.e.voting.clear()
        self.g, self.P = g, P

    def test_elders_remove_clan_leader_then_choose_a_new_one(self):
        bob = become_actor(self.e, "Bob")
        self.assertIsNotNone(find(self.e, bob, "call_vote", kind="remove_office", target="Alice"))
        self.assertIsNone(find(self.e, bob, "dismiss"))
        self.e.apply(bob, find(self.e, bob, "call_vote", kind="remove_office", target="Alice"))
        motion = self.e.voting.ballot("remove_office:Clan Leader:Alice")
        self.assertEqual(set(motion.votes), {"Bob", "Dmitri", "Greta"})
        vote_all(self.e, lambda name, b: "Yes")
        self.assertEqual(self.g.get_role_holders("Clan Leader"), [])
        election = next(v for v in self.e.voting.elections() if v.role == "Clan Leader")
        self.assertEqual((election.method, election.council), ("council_vote", "Elder"))

    def test_motion_needs_majority_of_electorate(self):
        do(self.e, "Bob", "call_vote", kind="remove_office", subject="Clan Leader", target="Alice")
        vote_all(self.e, lambda name, b: "Yes" if name == "Bob" else "No")
        self.assertEqual([p.name for p in self.g.get_role_holders("Clan Leader")], ["Alice"])

    def test_outcast(self):
        self.g.innovation_pool.discovered.add("Ostracism")
        do(self.e, "Bob", "call_vote", kind="grant_status", subject="Outcast", target="Alice")
        vote_all(self.e, lambda name, b: "Yes")
        alice = self.P["Alice"]
        self.assertEqual(self.g.statuses_of(alice), ["Outcast"])
        self.assertEqual(self.g.offices_of(alice), [])
        self.assertFalse(self.g.can_vote(alice))
        self.assertEqual(self.g.get_player_interfaces(alice), [])


class Reform(unittest.TestCase):
    def setUp(self):
        self.e = new_engine()
        g, P = self.e.government, {p.name: p for p in self.e.players}
        seat(g, "Clan Leader", P["Alice"])
        seat(g, "Elder", P["Bob"])
        seat(g, "Spirit Keeper", P["Cleo"])
        self.e.voting.clear()
        self.g, self.P = g, P

    def reach(self, *names):
        self.g.innovation_pool.discovered.update(names)
        self.g.check_new_age()

    def test_a_new_age_changes_the_government_by_itself(self):
        alice = become_actor(self.e, "Alice")
        self.assertIsNone(find(self.e, alice, "reform"))
        self.reach("Sustenance Gardening", "Forest Gardening", "Gardens on the Move", "Chieftainship")
        self.assertEqual(self.g.age.key, "stone")
        self.assertEqual(self.g.government_type.key, "chiefdom")  # no vote, no decree
        self.assertFalse([b for b in self.e.voting.active_votes if getattr(b, "kind", "") == "reform"])
        self.assertEqual(self.g.offices_of(self.P["Alice"]), ["Chieftain"])  # holders carry over...
        self.assertEqual(self.g.offices_of(self.P["Cleo"]), ["Priest"])
        self.assertEqual(self.g.offices_of(self.P["Bob"]), ["Elder"])
        self.assertEqual(self.g.get_role_holders("War Leader"), [])         # ...new offices start empty
        self.assertTrue(all(g.age == "stone" for g in self.g.available_reforms()))  # reform only within the age

    def test_research_done_before_the_age_picks_the_government(self):
        self.reach("Tribal Council", "Sustenance Gardening", "Forest Gardening", "Gardens on the Move", "Chieftainship")
        self.assertEqual(self.g.government_type.key, "village_council")
        self.assertEqual(self.g.offices_of(self.P["Alice"]), ["Elder"])  # the Clan Leader joins the council

    def test_research_notes_say_which_government_it_leads_to(self):
        from core.interfaces import unlock_note
        self.assertIn("Village Council (the society becomes one on entering the Stone Age)", unlock_note("Tribal Council"))
        self.assertIn("a reform within the Stone Age", unlock_note("Divine Right"))
        self.assertIn("becomes a Chiefdom", unlock_note("Chieftainship"))

    def test_appointments_carry_over_with_their_office(self):
        self.g.innovation_pool.discovered.add("Toolmaking")
        self.assertTrue(self.g.appoint(self.P["Alice"], "Gatherer", self.P["Imani"]))
        self.reach("Sustenance Gardening", "Forest Gardening", "Gardens on the Move", "Chieftainship")
        self.assertEqual(self.g.binding(self.P["Imani"]), ("Gatherer", "Chieftain"))

    def test_monarch_decrees(self):
        from innovations.innovation import ALL_INNOVATIONS
        self.reach(*[n for n, i in ALL_INNOVATIONS.items() if i.age != "metal"], "Writing")
        self.g.reform("kingdom")
        self.g.last_reform_hour = None
        self.assertEqual(self.g.offices_of(self.P["Alice"]), ["Monarch"])
        self.assertEqual(self.g.reform_mode(self.P["Alice"]), "decree")
        self.assertIsNone(self.g.reform_mode(self.P["Bob"]))
        do(self.e, "Alice", "reform", government="city_state")
        self.assertEqual(self.g.government_type.key, "city_state")
        self.assertEqual(self.g.offices_of(self.P["Alice"]), ["Magistrate"])
        self.assertEqual(self.g.offices_of(self.P["Bob"]), ["Council Member"])


if __name__ == "__main__":
    unittest.main()

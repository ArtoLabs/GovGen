"""The view model behind the pick lists: every person you can nominate, vote for or appoint comes with
a profile (who they are, how well they'd do the job, the stats the job uses)."""
import unittest

from tests.helpers import advance_days, become_actor, do, new_engine
from ui.model import action_groups, build_menu, candidate_profile


class CandidateProfileTest(unittest.TestCase):
    def setUp(self):
        self.e = new_engine(0)

    def view(self, name="Alice"):
        p = become_actor(self.e, name)
        return self.e.observe(p), self.e.legal_actions(p)

    def test_office_profile_uses_the_office_recipe(self):
        view, _ = self.view()
        pr = candidate_profile(view, "Bob", "Clan Leader")
        office = view["offices"]["Clan Leader"]
        self.assertEqual([a["key"] for a in pr["attributes"]],
                         sorted(office["quality_attributes"], key=lambda k: -office["quality_attributes"][k]))
        self.assertEqual(pr["skill"]["key"], office["quality_skill"])
        bob = next(p for p in view["players"] if p["name"] == "Bob")
        self.assertEqual(pr["fit"], bob["office_quality"]["Clan Leader"])
        self.assertEqual(pr["description"], bob["description"])
        self.assertFalse(pr["you"])
        self.assertTrue(candidate_profile(view, "Alice", "Clan Leader")["you"])

    def test_occupation_profile_uses_the_occupation(self):
        view, _ = self.view()
        name = next(iter(view["occupations"]))
        occ = view["occupations"][name]
        pr = candidate_profile(view, "Cleo", name)
        self.assertEqual({a["key"] for a in pr["attributes"]}, set(occ["attributes"]))
        cleo = next(p for p in view["players"] if p["name"] == "Cleo")
        self.assertEqual(pr["fit"], cleo["occupation_quality"][name])

    def test_unknown_position_still_describes_the_person(self):
        view, _ = self.view()
        pr = candidate_profile(view, "Dmitri", None)
        self.assertIsNone(pr["fit"])
        self.assertEqual(pr["attributes"], [])
        self.assertIsNone(candidate_profile(view, "Nobody", "Elder"))

    def _menu(self, kind, view, legal):
        group = next(g for g in action_groups(view, legal) if g.kind.type == kind)
        return build_menu(group, view)

    def test_nominees_have_profiles(self):
        view, legal = self.view()
        menu = self._menu("nominate", view, legal)
        people = [i for item in menu.items for i in (item.submenu.items if item.submenu else [item])]
        self.assertTrue(people)
        for item in people:
            self.assertEqual(item.profile["name"], item.label)
            self.assertIn(item.profile["position"], ("Clan Leader", "Elder"))

    def test_election_choices_have_profiles(self):
        for nominator, n in zip(["Esi", "Farid", "Greta"], ["Bob", "Cleo", "Dmitri"]):
            self.assertTrue(do(self.e, nominator, "nominate", ballot="elect:Clan Leader", candidate=n))
        advance_days(self.e, 31)
        view, legal = self.view()
        menu = self._menu("vote", view, legal)
        self.assertEqual([i.label for i in menu.items], ["Bob", "Cleo", "Dmitri"])
        for item in menu.items:
            self.assertEqual(item.profile["position"], "Clan Leader")
            self.assertIsNotNone(item.profile["fit"])


if __name__ == "__main__":
    unittest.main()


class PanelColumnsTest(unittest.TestCase):
    def test_innovations_shown_are_this_age_only(self):
        from tests.helpers import new_engine
        from ui.model import current_age_innovations
        e = new_engine()
        age, rows = current_age_innovations(e.observe(e.players[0]))
        self.assertEqual(age, "Tribal Age")
        self.assertTrue(rows)
        self.assertEqual({r.age for r in rows}, {"Tribal Age"})

    def test_crafts_say_which_jobs_use_an_item(self):
        from tests.helpers import new_engine
        from ui.model import craft_catalog
        e = new_engine()
        rows = {r.item: r for r in craft_catalog(e.observe(e.players[0]))}
        self.assertEqual(rows["hand_axe"].used_for, "Gatherer, Firekeeper: gather wood x1.6")
        self.assertIn("Toolmaker: making", rows["stone"].used_for)
        self.assertEqual(rows["fish"].used_for, "everyone: eating")

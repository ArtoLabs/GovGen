"""Appointing and dismissing people from work: no waiting, no limits, but people resent it."""
import unittest

from core import society
from core.engine import GameEngine
from tests.helpers import become_actor, find, new_engine, seat

JOB_LOSS = society.JOB_LOSS


def leader_engine():
    """An engine where Alice is Clan Leader, Hunting and Hierarchy are known and there are spears."""
    e = new_engine()
    gov = e.government
    seat(gov, "Clan Leader", e.player("Alice"))
    gov.innovation_pool.discovered.update({"Hunting", "Hierarchy", "Toolmaking", "Tracking", "Camp Defense"})
    e.possessions.deliver([{"item": "wooden_spear", "count": 2}])
    return e


class AppointmentTests(unittest.TestCase):
    def test_no_waiting_after_a_dismissal(self):
        e = leader_engine()
        gov, alice, imani = e.government, e.player("Alice"), e.player("Imani")
        self.assertTrue(gov.appoint(alice, "Hunter", imani))
        self.assertTrue(gov.dismiss(alice, "Hunter", imani))
        # Straight back into work, a different job, at once.
        self.assertTrue(gov.appoint(alice, "Warrior", imani))
        self.assertTrue(gov.appoint(alice, "Scout", imani))  # and moved again
        self.assertEqual(gov.occupations_of(imani), ["Scout"])

    def test_no_limit_on_how_many_do_one_job(self):
        e = leader_engine()
        gov, alice = e.government, e.player("Alice")
        others = [p for p in e.players if p is not alice and not gov.offices_of(p) and gov.of_age(p, "work")]
        for p in others:
            self.assertTrue(gov.appoint(alice, "Warrior", p), p.name)
        self.assertEqual(len(gov.occupations["Warrior"]), len(others))
        # Nobody is turned away for want of a place; only someone already a Warrior isn't offered again.
        become_actor(e, "Alice")
        self.assertIsNone(find(e, alice, "appoint", position="Warrior", appointee=others[0].name))
        gov.dismiss(alice, "Warrior", others[0])
        self.assertIsNotNone(find(e, alice, "appoint", position="Warrior", appointee=others[0].name))

    def test_dismissal_hurts_work_and_leaders_contentment(self):
        e = leader_engine()
        gov, alice, imani, bob = e.government, e.player("Alice"), e.player("Imani"), e.player("Bob")
        gov.appoint(alice, "Hunter", imani)
        imani.satisfaction.update({"work": 70, "leaders": 70})
        bob.satisfaction.update({"leaders": 70})
        gov.dismiss(alice, "Hunter", imani)
        hit = JOB_LOSS["dismissed"]["hit"]
        self.assertAlmostEqual(imani.satisfaction["work"], 70 - hit["work"])
        self.assertAlmostEqual(imani.satisfaction["leaders"], 70 - hit["leaders"])
        self.assertAlmostEqual(bob.satisfaction["leaders"], 70 - JOB_LOSS["onlookers"]["hit"]["leaders"])
        self.assertGreater(imani.grievances["leaders"], 0)

    def test_moving_someone_to_other_work_is_resented_too(self):
        e = leader_engine()
        gov, alice, imani = e.government, e.player("Alice"), e.player("Imani")
        gov.appoint(alice, "Hunter", imani)
        imani.satisfaction["work"] = 70
        gov.appoint(alice, "Warrior", imani)
        self.assertAlmostEqual(imani.satisfaction["work"], 70 - JOB_LOSS["reassigned"]["hit"]["work"])

    def test_first_appointment_is_not_resented(self):
        e = leader_engine()
        gov, alice, imani = e.government, e.player("Alice"), e.player("Imani")
        gov.occupations["Gatherer"] = [p for p in gov.occupations["Gatherer"] if p is not imani]
        imani.satisfaction["work"] = 70
        gov.appoint(alice, "Hunter", imani)
        self.assertEqual(imani.satisfaction["work"], 70)
        self.assertLess(imani.grievances.get("leaders", 0), 0)  # a step up the hierarchy: goodwill, not grievance
        self.assertNotIn("work", imani.grievances)

    def test_grievances_add_up_and_fade(self):
        e = leader_engine()
        gov, alice, imani = e.government, e.player("Alice"), e.player("Imani")
        for _ in range(3):
            gov.appoint(alice, "Hunter", imani)
            gov.dismiss(alice, "Hunter", imani)
        g = imani.grievances["leaders"]
        self.assertGreater(g, JOB_LOSS["dismissed"]["grievance"]["leaders"] * 2)
        self.assertLessEqual(g, JOB_LOSS["max_grievance"])
        # The grievance holds the meter down while it lasts...
        society.update_satisfaction(e.players, gov, e.qualities, 70, 0.01)
        half = JOB_LOSS["grievance_half_life_life_hours"] / 24
        society.update_satisfaction(e.players, gov, e.qualities, 70, half)
        self.assertAlmostEqual(imani.grievances["leaders"], g * 0.5 ** ((half + 0.01) * 24 / (half * 24)), places=3)
        # ...and is saved.
        restored = GameEngine.from_dict(e.to_dict())
        self.assertAlmostEqual(restored.player("Imani").grievances["leaders"], imani.grievances["leaders"])

    def test_old_saves_with_rest_times_still_load(self):
        e = leader_engine()
        data = e.to_dict()
        data["government"]["rest_until"] = {"Imani": 10 ** 9}
        restored = GameEngine.from_dict(data)
        self.assertTrue(restored.government.appoint(restored.player("Alice"), "Hunter", restored.player("Imani")))


class CraftChartTests(unittest.TestCase):
    def test_chart_shows_what_it_takes(self):
        e = new_engine()
        c = e.observe(e.player("Alice"))["crafts"]
        spear = next(r for r in c["recipes"] if r["item"] == "wooden_spear")
        self.assertEqual(spear["occupations"], ["Toolmaker"])
        self.assertEqual(spear["status"], "research")
        self.assertEqual({s["item"] for s in spear["inputs"]}, {"wood"})  # a sharpened stick
        e.government.innovation_pool.discovered.add("Toolmaking")
        c = e.observe(e.player("Alice"))["crafts"]
        self.assertEqual(next(r for r in c["recipes"] if r["item"] == "wooden_spear")["status"], "no_worker")
        e.government.occupations["Toolmaker"].append(e.player("Hiro"))
        c = e.observe(e.player("Alice"))["crafts"]
        self.assertEqual(next(r for r in c["recipes"] if r["item"] == "wooden_spear")["status"], "short")  # empty store
        e.possessions.deliver([{"item": "wood", "count": 2}, {"item": "stone", "count": 1}])
        c = e.observe(e.player("Alice"))["crafts"]
        self.assertEqual(next(r for r in c["recipes"] if r["item"] == "wooden_spear")["status"], "ready")
        self.assertIn("a Hunter can't work without one", c["uses"]["wooden_spear"])
        self.assertIn("Warrior", c["used_by"]["wooden_spear"])
        self.assertEqual(c["used_by"]["meat"], {"everyone": ["eating"]})

    def test_scouting_brings_back_no_items(self):
        # A Scout finds places (work.json 'sites'), not items: scouting is no source in the crafting chart.
        e = new_engine()
        c = e.observe(e.player("Alice"))["crafts"]
        self.assertFalse(any(s["key"] == "scout" for s in c["sources"]))
        self.assertIn("Tracking", e.observe(e.player("Alice"))["occupations"]["Scout"]["requires"])

    def test_ui_rows_pick_the_easiest_way(self):
        from ui.model import craft_catalog, craft_detail
        e = new_engine()
        v = e.observe(e.player("Alice"))
        rows = {r.item: r for r in craft_catalog(v)}
        self.assertEqual(rows["berries"].research, [])   # a Gatherer finds them; no Tracking needed
        self.assertEqual(rows["bow"].status, "research")
        text = "".join(t for t, _ in craft_detail(v, rows["wooden_spear"]))
        self.assertIn("Gather wood", text)


if __name__ == "__main__":
    unittest.main()


class AppointmentHierarchyTests(unittest.TestCase):
    """Someone appointed keeps the work until the office that appointed them (or a higher one, by
    'authority') releases, moves or dismisses them; lower offices can't touch it."""

    def setUp(self):
        self.e = leader_engine()  # Alice is Clan Leader
        self.gov = self.e.government
        self.alice, self.bob, self.esi = self.e.player("Alice"), self.e.player("Bob"), self.e.player("Esi")
        seat(self.gov, "Elder", self.bob)
        seat(self.gov, "Spirit Keeper", self.esi)
        self.imani, self.joao = self.e.player("Imani"), self.e.player("Joao")
        for p in (self.imani, self.joao):
            for occ in self.gov.occupations_of(p):
                self.gov.occupations[occ].remove(p)

    def test_offices_rank_by_authority(self):
        self.assertGreater(self.gov.authority_of(self.alice), self.gov.authority_of(self.bob))
        self.assertGreater(self.gov.authority_of(self.bob), self.gov.authority_of(self.esi))

    def test_an_appointee_cannot_quit_or_take_other_work(self):
        self.assertTrue(self.gov.appoint(self.alice, "Gatherer", self.imani))
        self.assertEqual(self.gov.binding(self.imani), ("Gatherer", "Clan Leader"))
        self.assertFalse(self.gov.leave_occupation("Gatherer", self.imani))
        self.assertIsNone(find(self.e, become_actor(self.e, "Imani"), "leave_occupation", occupation="Gatherer"))
        self.assertFalse(self.gov.can_take_occupation("Firekeeper", self.imani)[0])

    def test_lower_offices_cannot_move_or_dismiss_a_higher_appointment(self):
        self.assertTrue(self.gov.appoint(self.alice, "Gatherer", self.imani))
        self.assertFalse(self.gov.appoint(self.bob, "Firekeeper", self.imani))   # an Elder can't
        self.assertFalse(self.gov.dismiss(self.esi, "Gatherer", self.imani))     # nor the Spirit Keeper
        self.assertFalse(self.gov.release(self.bob, self.imani))
        self.assertTrue(self.gov.appoint(self.bob, "Gatherer", self.joao))      # the Elder's own appointee...
        self.assertFalse(self.gov.release(self.esi, self.joao))                 # ...is above the Spirit Keeper
        self.assertTrue(self.gov.appoint(self.alice, "Firekeeper", self.joao))  # but not the Clan Leader
        self.assertEqual(self.gov.binding(self.joao), ("Firekeeper", "Clan Leader"))

    def test_release_frees_them_but_keeps_the_work(self):
        self.assertTrue(self.gov.appoint(self.bob, "Gatherer", self.imani))
        self.assertTrue(self.gov.release(self.alice, self.imani))  # the Clan Leader may release anyone's
        self.assertIsNone(self.gov.binding(self.imani))
        self.assertIn("Gatherer", self.gov.occupations_of(self.imani))
        self.assertTrue(self.gov.leave_occupation("Gatherer", self.imani))

    def test_release_is_offered_only_within_ones_authority_and_survives_a_save(self):
        self.assertTrue(self.gov.appoint(self.alice, "Gatherer", self.imani))
        self.assertTrue(self.gov.appoint(self.esi, "Firekeeper", self.joao))
        self.assertEqual({p.name for p in self.gov.releasable(self.esi)}, {"Joao"})
        self.assertEqual({p.name for p in self.gov.releasable(self.alice)}, {"Imani", "Joao"})
        restored = GameEngine.from_dict(self.e.to_dict())
        self.assertEqual(restored.government.binding(restored.player("Imani")), ("Gatherer", "Clan Leader"))

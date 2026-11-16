"""Data by age (utils/game_data.py, data/ages/<age>/): every age's folder is read, what an age calls
things and the rules it changes take effect when the age is reached, and an occupation's file holds its work."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import work as WORK
from core.engine import GameEngine
from core.government_types import GOVERNMENT_TYPES
from core.occupations import OCCUPATIONS
from innovations.innovation import AGES, ALL_INNOVATIONS
from utils import game_data
from utils.data_files import DataError


class AgeFolderTests(unittest.TestCase):
    def test_every_age_is_a_folder_in_order(self):
        self.assertEqual([a.key for a in AGES], game_data.AGE_KEYS)
        self.assertEqual(game_data.AGE_KEYS[0], "tribal")
        for folder in game_data.AGE_FOLDERS:
            self.assertTrue((folder.path / "age.json").exists())

    def test_an_innovation_costs_what_its_file_says(self):
        for folder in game_data.AGE_FOLDERS:
            data = json.loads((folder.path / "innovations.json").read_text(encoding="utf-8"))
            mult = folder.data.get("innovation_cost_multiplier", 1)
            for entry in data["innovations"]:
                self.assertEqual(ALL_INNOVATIONS[entry["name"]].cost, round(entry["cost"] * mult), entry["name"])
                self.assertEqual(ALL_INNOVATIONS[entry["name"]].age, folder.key)

    def test_a_government_belongs_to_the_age_of_its_folder(self):
        for folder, _where, data in game_data.age_folder_files("governments"):
            self.assertEqual(GOVERNMENT_TYPES[data["key"]].age, folder.key)

    def test_an_occupation_file_holds_its_own_work(self):
        self.assertEqual(WORK.TASKS["forage"].occupations, ["Gatherer"])
        self.assertEqual(WORK.TASKS["gather_wood"].occupations, ["Gatherer", "Firekeeper"])  # 'also_done_by'
        self.assertEqual(WORK.RECIPES["wooden_spear"].occupations, ["Toolmaker"])
        self.assertEqual(WORK.TASKS["carry_off_dead"].occupations, [])  # the age's work.json: open to anyone
        self.assertEqual(OCCUPATIONS["Gatherer"].contributes["food"]["category"], "plants")
        for name, occ in OCCUPATIONS.items():
            self.assertEqual(occ.age, "tribal", name)

    def test_what_a_job_adds_to_the_society_comes_from_its_file(self):
        from core import society
        self.assertIn("Hunter", society.QUALITIES["food"].sources)
        self.assertIn("office:Spirit Keeper", society.QUALITIES["care"].sources)  # the office, from tribal.json
        self.assertIn("working_now:Warrior", society.METERS["safety"].multipliers)

    def test_an_age_cannot_override_rules_that_do_not_switch(self):
        """The calendar is the engine's own: an age folder with a rules/time.json is refused, not ignored."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "rules").mkdir()
            (Path(tmp) / "rules" / "time.json").write_text("{}", encoding="utf-8")
            fake = game_data.AgeFolder("later", Path(tmp), {"order": 99, "name": "Later"})
            with mock.patch.object(game_data, "AGE_FOLDERS", [fake]):
                with self.assertRaises(DataError):
                    game_data.age_rules("time")


class RulesByAgeTests(unittest.TestCase):
    def test_terms_follow_the_age_and_the_government(self):
        e = GameEngine()
        self.assertEqual(e.terms()["members"], "Tribe")
        self.assertEqual(e.observe(e.players[0])["terms"]["store"], "Camp")
        e.government.age_index = 1
        self.assertEqual(e.terms()["members"], "Villagers")
        with mock.patch.object(e.government.government_type, "terms", {"members": "Subjects"}):
            self.assertEqual(e.terms()["members"], "Subjects")
            self.assertEqual(e.terms()["store"], "Village")  # the rest is still the age's

    def test_the_store_panel_is_the_ages(self):
        e = GameEngine()
        panel = e.observe(e.players[0])["store_panel"]
        self.assertEqual([g["label"] for g in panel], [g["label"] for g in game_data.AGE_FOLDERS[0].data["store_panel"]])
        e.government.age_index = 1  # the Stone Age sets none of its own: it keeps the Tribal Age's
        self.assertEqual(e.observe(e.players[0])["store_panel"], panel)

    def test_an_age_changes_the_work_rules_when_it_is_reached(self):
        base = WORK.BASE_RULES["trips"]["base_chance"]
        with mock.patch.object(game_data, "age_rules", lambda name: {"stone": {"trips": {"base_chance": 0.9}}}
                               if name == "work" else {}):
            old, new = GameEngine(), GameEngine()
            new.government.age_index = 1
            new.refresh_rules()
            self.assertEqual(WORK.TRIPS["base_chance"], 0.9)
            self.assertEqual(WORK.TRIPS["with_site_chance"], WORK.BASE_RULES["trips"]["with_site_chance"])
            old.rules.use()  # another game still in the first age keeps the first age's rules
            self.assertEqual(WORK.TRIPS["base_chance"], base)

    def test_a_government_changes_the_rules_while_it_is_in_place(self):
        e = GameEngine()
        key = e.government.government_type.key
        with mock.patch.dict(game_data.GOVERNMENT_RULES, {key: {"work": {"fire": {"max_life_hours": 99}}}}):
            e.refresh_rules()
            self.assertEqual(WORK.FIRE["max_life_hours"], 99)
        e.refresh_rules()
        self.assertEqual(WORK.FIRE["max_life_hours"], WORK.BASE_RULES["fire"]["max_life_hours"])

    def _in_the_stone_age(self, overrides):
        """(a game in the first age, a game that has reached the Stone Age) with the Stone Age folder
        changing these rule files: {'society': {...}, 'npc': {...}}."""
        patch = mock.patch.object(game_data, "age_rules", lambda name: {"stone": overrides[name]}
                                  if name in overrides else {})
        patch.start()
        self.addCleanup(patch.stop)
        old, new = GameEngine(), GameEngine()
        self.addCleanup(old.rules.use)  # leave the first age's rules in force for the tests that follow
        new.government.age_index = 1
        new.refresh_rules()
        return old, new

    def test_an_age_changes_society_rules_and_adds_a_quality_and_a_meter(self):
        from core import society
        start = society.BASE_RULES["satisfaction"]["start"]
        old, new = self._in_the_stone_age({"society": {
            "supply_curve": 0.5,
            "satisfaction": {"start": 77, "job_loss": {"max_grievance": 5},
                             "meters": {"trade": {"name": "Trade", "inputs": {"society": 1.0}}}},
            "qualities": {"trade": {"name": "Trade", "icon": "T", "weight": 1, "style": "supply", "per_person": 0.2}}}})
        self.assertEqual((society.SATISFACTION["start"], society.JOB_LOSS["max_grievance"], society.SUPPLY_CURVE),
                         (77, 5, 0.5))
        self.assertIn("trade", society.QUALITIES)
        self.assertIn("trade", society.UPDATE_ORDER)
        self.assertIn("office:Spirit Keeper", society.QUALITIES["care"].sources)  # offices still add theirs
        self.assertIn("Hunter", society.QUALITIES["food"].sources)
        self.assertTrue(all("trade" in p.satisfaction for p in new.players))  # everyone gets the new meter
        new.observe(new.players[0])
        new.step()
        old.rules.use()  # the other game is still in the first age
        self.assertEqual(society.SATISFACTION["start"], start)
        self.assertNotIn("trade", society.QUALITIES)
        self.assertNotIn("trade", society.METERS)
        self.assertIs(society.SATISFACTION["job_loss"], society.JOB_LOSS)

    def test_an_age_changes_npc_contest_world_and_character_rules(self):
        from controllers import npc
        from core import contests
        from world import environment
        from world.character import RULES as CHARACTER
        before = (npc.TUNING["nominate_chance"], contests.SKILL_WEIGHT, environment.COMFORT,
                  CHARACTER.training_per_year, CHARACTER.needs["food"].decay_per_day)
        old, new = self._in_the_stone_age({
            "npc": {"nominate_chance": 0.99},
            "contests": {"skill_weight": 0.9, "challenge": {"kinds": {"riddles": {
                "name": "Riddles", "style": "best", "attributes": {"intelligence": 1.0}}}}},
            "world": {"climate": {"comfort": 25}},
            "character": {"training_per_year": 0.9, "needs": {"food": {"decay_per_day": 50}}}})
        self.assertEqual((npc.TUNING["nominate_chance"], contests.SKILL_WEIGHT, environment.COMFORT,
                          CHARACTER.training_per_year, CHARACTER.needs["food"].decay_per_day),
                         (0.99, 0.9, 25, 0.9, 50))
        self.assertIn("riddles", contests.CHALLENGE_KINDS)
        self.assertIn("fight", contests.CHALLENGE_KINDS)  # what the age doesn't mention stays
        self.assertEqual(CHARACTER.needs["water"].decay_per_day,
                         game_data.rules("character")["needs"]["water"]["decay_per_day"])
        old.rules.use()
        self.assertEqual((npc.TUNING["nominate_chance"], contests.SKILL_WEIGHT, environment.COMFORT,
                          CHARACTER.training_per_year, CHARACTER.needs["food"].decay_per_day), before)
        self.assertNotIn("riddles", contests.CHALLENGE_KINDS)

    def test_a_game_with_nothing_overridden_shares_the_base_rules(self):
        from core import society
        e = GameEngine()
        self.assertIs(e.rules["society"], society.BASE_RULES)
        self.assertIs(e.rules["work"], WORK.BASE_RULES)


if __name__ == "__main__":
    unittest.main()

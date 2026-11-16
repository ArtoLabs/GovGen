import random
import tempfile
import unittest
from pathlib import Path

from controllers.npc import NPCController, Persona
from core.engine import GameEngine
from core.game import Game
from core.save import load_save, rng_state_from_json, save_game
from tests.helpers import immortal, new_engine, seat
from utils.messages import Messages


def npc_game(seed: int, saved=None) -> Game:
    """An all-NPC game at maximum speed, new or continued from a save."""
    Messages.clear()
    if saved:
        random.setstate(rng_state_from_json(saved["random_state"]))
        engine = GameEngine.from_dict(saved["engine"])
    else:
        random.seed(seed)
        engine = GameEngine()
    seeder = random.Random(seed)
    controllers = {p.name: NPCController(p.name, rng=random.Random(seeder.random())) for p in engine.players}
    if saved:
        for name, c in controllers.items():
            c.load_state(saved["controllers"][name])
    return Game(engine, controllers)


class NPCGames(unittest.TestCase):
    def test_npcs_play_through_the_ages_without_stalling(self):
        game = npc_game(seed=5)  # the Stone Age arrives in years ~45-60 for most seeds
        with immortal(game.engine):  # this is about NPCs not stalling, not about survival (see test_life.py)
            game.run(max_years=60)
        engine = game.engine
        self.assertEqual(engine.year, 59)
        # Research never stalls: the Stone Age is here or nearly so (cheapest-first research and hard times can
        # push it a little past year 60).
        gov = engine.government
        progress = gov.next_age_progress()
        self.assertTrue(gov.age.key == "stone" or sum(done for _, done in progress[1]) >= 1)
        self.assertGreaterEqual(len(gov.innovation_pool.discovered), 20)
        types = {e["type"] for e in engine.action_log}
        self.assertTrue({"nominate", "vote", "research", "wait", "care", "appoint", "take_occupation"} <= types)
        # Leaders put people to work (office holders' work is their office), and nobody starves.
        gov = engine.government
        working = sum(1 for p in engine.players if gov.occupations_of(p) or gov.offices_of(p))
        self.assertGreaterEqual(working, 10)
        self.assertFalse(any(gov.occupations_of(p) and gov.offices_of(p) for p in engine.players))
        self.assertTrue(all(p.health > 0 for p in engine.players))

    def test_ages_take_decades_and_npcs_are_not_all_selfish(self):
        game = npc_game(seed=3)
        game.run(max_years=20)
        engine = game.engine
        self.assertEqual(engine.government.age.key, "tribal")  # the Stone Age takes decades
        noms = [e for e in engine.action_log if e["type"] == "nominate"]
        self.assertTrue(noms)
        self.assertLess(sum(e["params"]["candidate"] == e["player"] for e in noms), len(noms) / 2)

    def test_same_seed_same_game(self):
        # Games share Python's global random generator, so build and run them one at a time.
        a = npc_game(seed=11)
        a.run(max_years=3)
        b = npc_game(seed=11)
        b.run(max_years=3)
        self.assertEqual(a.engine.action_log, b.engine.action_log)

    def test_save_and_continue_is_identical_to_playing_straight_through(self):
        straight = npc_game(seed=5)
        straight.run(max_years=6)
        straight_log, straight_state = straight.engine.action_log, straight.engine.government.to_dict()

        first = npc_game(seed=5)
        first.run(max_years=3)
        with tempfile.TemporaryDirectory() as tmp:
            path = save_game(first, Path(tmp) / "save.json")
            saved = load_save(path)
        second = npc_game(seed=5, saved=saved)
        second.run(max_years=6)

        self.assertEqual(first.engine.action_log + second.engine.action_log, straight_log)
        self.assertEqual(second.engine.government.to_dict(), straight_state)

    def test_npc_never_votes_to_remove_itself(self):
        e = new_engine()
        g, P = e.government, {p.name: p for p in e.players}
        seat(g, "Elder", P["Bob"])
        npc = NPCController("Bob", rng=random.Random(1))
        view = e.observe(P["Bob"])
        npc.persona = Persona(next(p for p in view["players"] if p["name"] == "Bob"))
        lean, reason = npc._motion_lean(view, {"key": "k", "kind": "remove_office", "subject": "Elder", "target": "Bob"})
        self.assertLess(lean, 0)
        self.assertIn("themselves", reason)


if __name__ == "__main__":
    unittest.main()


class ResearchEagernessTest(unittest.TestCase):
    def test_someone_who_can_queues_free_research_when_nothing_is_researched(self):
        import random
        from controllers.npc import NPCController
        from tests.helpers import immortal, new_engine, seat
        e = new_engine()
        gov = e.government
        bob = e.player("Bob")
        seat(gov, "Elder", bob)
        gov.research_queue.clear()
        view = e.observe(bob)
        self.assertIn("Elder", view["research_roles"]["legislative"])
        from core.actions import Action
        self.assertNotIn("Symbolism", gov.innovation_pool.discovered)
        act = Action("research", {"interface": "legislative", "innovation": "Symbolism"})
        from controllers.npc import Persona
        npc = NPCController("Bob", random.Random(1))
        npc.persona = Persona(npc._player(view, "Bob"))
        npc.persona.curiosity = 0.0  # even the least curious
        score, why = npc._score_research(view, act)
        self.assertGreater(score, 3.0)
        self.assertIn("nothing", why)

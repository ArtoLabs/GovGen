"""Real-time play: a parked player never holds up the clock and may act whenever they choose."""
import unittest

from controllers.base import Controller, Decision
from core.calendar import HOURS_PER_DAY
from core.game import Game, Pacer
from tests.helpers import new_engine, wait
from controllers.npc import NPCController
from utils.messages import Messages


class RealtimeEngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = new_engine()
        self.alice = self.engine.player("Alice")

    def park_alice(self):
        for _ in range(5000):
            actor = self.engine.step()
            if actor is self.alice:
                self.engine.park(actor)
                return
            if actor is not None:
                wait(self.engine, actor)
        self.fail("Alice never became free")

    def test_parked_player_does_not_stop_the_clock(self):
        self.park_alice()
        start = self.engine.clock
        for _ in range(2000):
            actor = self.engine.step()
            self.assertIsNot(actor, self.alice)
            if actor is not None:
                wait(self.engine, actor)
        self.assertGreater(self.engine.clock, start + 5 * HOURS_PER_DAY)
        self.assertTrue(self.engine.legal_actions(self.alice))
        self.assertTrue(self.engine.observe(self.alice)["free"])

    def test_act_now_then_busy_then_free_again(self):
        self.park_alice()
        research = next(a for a in self.engine.legal_actions(self.alice) if a.type in ("research", "role_command", "wait"))
        self.assertTrue(self.engine.act_now(self.alice, research.with_params(text="x")))
        self.assertEqual(self.engine.legal_actions(self.alice), [])
        view = self.engine.observe(self.alice)
        self.assertFalse(view["free"])
        self.assertIsNotNone(view["busy_until"])
        self.assertFalse(self.engine.act_now(self.alice, research))  # busy: refused
        self.park_alice()  # becomes free again later

    def test_advance_clock_never_skips_anything_due(self):
        self.park_alice()
        due = self.engine.peek_next_time()
        self.engine.advance_clock(10 ** 6)
        self.assertEqual(self.engine.clock, due)


class WakeAndAlertsTest(unittest.TestCase):
    def test_resting_players_come_back_for_a_new_ballot(self):
        engine = new_engine()
        bob = engine.player("Bob")
        for _ in range(5000):
            actor = engine.step()
            if actor is bob:
                engine.apply(bob, next(a for a in engine.legal_actions(bob) if a.type == "wait" and a.params["days"] == 90))
                break
            if actor is not None:
                wait(engine, actor)
        self.assertIn("Bob", engine.resting)
        far = engine.free_at["Bob"]
        engine.voting.active_votes.clear()
        engine._ballot_stages.clear()
        engine.government.assignments.clear()  # vacancies -> elections open on the next settle
        engine._settle()
        self.assertTrue(engine.voting.active_votes)
        self.assertLess(engine.free_at["Bob"], far)
        self.assertLessEqual(engine.free_at["Bob"], engine.clock + engine.WAKE_DAYS * HOURS_PER_DAY)

    def test_ballot_watcher_alerts(self):
        from ui.model import BallotWatcher
        engine = new_engine()
        alice = engine.player("Alice")
        watcher = BallotWatcher()
        alerts = watcher.update(engine.observe(alice), engine.legal_actions(alice), [])
        self.assertTrue(any("Nominations are open" in a.text for a in alerts))
        self.assertEqual(watcher.update(engine.observe(alice), engine.legal_actions(alice), []), [])


class ScriptedRealtime(Controller):
    """A real-time controller that does one research/order as soon as it may, then quits."""
    is_human = True
    realtime = True

    def __init__(self):
        self.queue, self.results, self.done = [], [], False

    def update(self, view, legal):
        if not self.done and view["free"] and legal:
            act = next((a for a in legal if a.type in ("research", "role_command")), None)
            if act:
                self.queue.append(Decision(act.with_params(text="x")))
                self.done = True
        elif self.done and not self.queue and self.results:
            self.queue.append(None)

    def take_decisions(self):
        out, self.queue = self.queue, []
        return out

    def has_decisions(self):
        return bool(self.queue)

    def action_result(self, decision, ok, why=""):
        self.results.append(ok)


class RealtimeGameLoopTest(unittest.TestCase):
    def test_loop_applies_realtime_decisions_and_quits(self):
        engine = new_engine()
        human = ScriptedRealtime()
        controllers = {p.name: (human if p.name == "Alice" else NPCController(p.name)) for p in engine.players}
        game = Game(engine, controllers, pacer=Pacer(speed=0))
        game.run(max_years=3)
        self.assertEqual(human.results[:1], [True])
        self.assertTrue(game.stopped)

    def test_pacer_pause_and_interrupt(self):
        pacer = Pacer(seconds_per_year=1, speed=1)
        pacer.paused = True
        calls = []
        self.assertEqual(pacer.wait(100, lambda: calls.append(1) or len(calls) > 2), 0)


class AutoModeTest(unittest.TestCase):
    """On auto, the person you play is played by the NPC rules; on manual you choose; switch any time."""

    def game(self, years: float):
        from controllers.hud import HUDController
        engine = new_engine()
        hud = HUDController("Alice")
        controllers = {p.name: (hud if p.name == "Alice" else NPCController(p.name)) for p in engine.players}
        game = Game(engine, controllers, pacer=Pacer(speed=0))
        return engine, hud, game

    def test_on_auto_you_are_played_like_an_npc(self):
        engine, hud, game = self.game(1)
        hud.set_auto(True)
        game.run(max_years=1)
        mine = [e for e in engine.action_log if e["player"] == "Alice"]
        self.assertTrue(mine)  # nobody pressed a key, yet Alice lived her life
        self.assertIn("work", {e["type"] for e in mine})
        self.assertNotIn("Alice", engine.possessions.keeps_all)  # keeps and shares like an NPC

    def test_switching_back_to_manual_parks_you_again(self):
        engine, hud, game = self.game(1)
        hud.set_auto(True)
        game.run(max_years=0.5)
        acted = len([e for e in engine.action_log if e["player"] == "Alice"])
        hud.set_auto(False)
        game.stopped = False
        game.run(max_years=1.5)
        later = [e for e in engine.action_log[:] if e["player"] == "Alice"]
        self.assertLessEqual(len(later) - acted, 1)  # at most the action she was in the middle of
        self.assertIn("Alice", engine.possessions.keeps_all)
        self.assertIn("Alice", engine.idle)  # free, waiting for you to choose

    def test_auto_is_saved(self):
        from controllers.hud import HUDController
        hud = HUDController("Alice")
        hud.set_auto(True)
        hud.npc()
        again = HUDController("Alice")
        again.load_state(hud.to_dict())
        self.assertTrue(again.auto)


if __name__ == "__main__":
    unittest.main()

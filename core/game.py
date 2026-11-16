"""Runs a game: moves the clock forward at a watchable pace, asks whoever is free to act for a
decision, and passes the resulting events to every controller."""
import random
import signal
import time
from typing import Callable, Dict, Iterable, Optional

from controllers.base import Controller
from core.calendar import DAYS_PER_SEASON, HOURS_PER_DAY, HOURS_PER_YEAR
from core.engine import GameEngine
from utils.logging_config import logger
from utils.messages import Messages

from utils.data_files import DATA_DIR, load_json
SPEEDS = list(load_json(DATA_DIR / "settings.json").get("playback_speeds", [1, 5, 20, 0]))  # 0 = as fast as possible


class Pacer:
    """Turns game time into real time: `seconds_per_year` real seconds per game year at speed 1.
    Can be paused; while paused no game time passes (real-time players may still act)."""

    TICK = 0.05  # real seconds between checks for stop / pause / a real-time decision

    def __init__(self, seconds_per_year: float = 300, speed: float = 1):
        self.seconds_per_year = seconds_per_year
        self.speed = speed
        self.paused = False
        self.stop_requested: Callable[[], bool] = lambda: False

    def describe(self) -> str:
        return "max" if not self.speed else f"{self.speed:g}x"

    def next_speed(self):
        self.speed = SPEEDS[(SPEEDS.index(self.speed) + 1) % len(SPEEDS)] if self.speed in SPEEDS else 1

    def toggle_pause(self):
        self.paused = not self.paused

    def wait(self, game_hours: float, interrupt: Optional[Callable[[], bool]] = None) -> float:
        """Let `game_hours` of game time pass in real time. Returns the game hours that actually
        passed: less than asked if stopped or if `interrupt()` became true."""
        game_hours = max(0.0, game_hours)
        elapsed = 0.0
        while not self.stop_requested():
            if interrupt is not None and interrupt():
                return elapsed
            if self.paused:
                time.sleep(self.TICK)
                continue
            if not self.speed or elapsed >= game_hours - 1e-9:
                return game_hours
            real_left = (game_hours - elapsed) / HOURS_PER_YEAR * self.seconds_per_year / self.speed
            chunk = min(self.TICK, real_left)
            time.sleep(chunk)
            elapsed += chunk * self.speed / self.seconds_per_year * HOURS_PER_YEAR
        return elapsed


class Game:
    def __init__(self, engine: GameEngine, controllers: Dict[str, Controller], observers: Iterable = (),
                 pacer: Optional[Pacer] = None, autosave: Optional[Callable[['Game'], None]] = None):
        missing = [p.name for p in engine.players if p.name not in controllers]
        if missing:
            raise ValueError(f"No controller for: {', '.join(missing)}")
        self.engine = engine
        self.controllers = controllers
        # Who plays themselves: they keep everything their work brings back (items.json 'keeping').
        engine.possessions.keeps_all = {name for name, c in controllers.items() if c.is_human and not self._auto(c)}
        self.listeners = list(dict.fromkeys([*controllers.values(), *observers]))
        self.pacer = pacer or Pacer(speed=0)
        self.autosave = autosave
        self.stopped = False
        self._interrupted = False
        self._busy = False
        self._last_publish = 0.0
        self.realtime = [(name, c) for name, c in controllers.items() if c.realtime]
        self.pacer.stop_requested = lambda: self._interrupted

    @staticmethod
    def _auto(controller) -> bool:
        """A human player who has switched to auto: played by the NPC rules (controllers/hud.py)."""
        return bool(getattr(controller, "auto", False))

    def _sync_auto(self):
        """You switched between manual and auto (from the display, any time): on auto you keep only what an NPC
        keeps (items.json 'keeping') and your moment comes round like an NPC's; on manual you choose again."""
        engine = self.engine
        engine.possessions.keeps_all = {n for n, c in self.controllers.items() if c.is_human and not self._auto(c)}
        for name, c in self.realtime:
            if self._auto(c) and name in engine.idle:
                engine.idle.discard(name)  # free and waiting for you: the NPC rules take this moment

    def request_stop(self):
        """Stop at the next safe moment (callable from another thread, e.g. the HUD)."""
        self._interrupted = True

    def _broadcast(self):
        messages = Messages.drain()
        if messages:
            for listener in self.listeners:
                listener.notify(messages)

    def _on_interrupt(self, signum, frame):
        # Ctrl+C: never stop halfway through an engine step; finish it, then stop cleanly.
        self._interrupted = True
        if not self._busy:
            raise KeyboardInterrupt

    def run(self, max_years: Optional[float] = None):
        """Play until a player quits, Ctrl+C, or `max_years` of game time have passed."""
        previous = signal.getsignal(signal.SIGINT)
        try:
            signal.signal(signal.SIGINT, self._on_interrupt)
        except ValueError:
            previous = None  # not the main thread (e.g. some test runners)
        try:
            self._loop(max_years)
        except KeyboardInterrupt:
            self.stopped = True
        finally:
            if previous is not None:
                signal.signal(signal.SIGINT, previous)

    # ------------------------------------------------------------------ #
    # Real-time controllers
    # ------------------------------------------------------------------ #
    def _decisions_waiting(self) -> bool:
        return any(c.has_decisions() for _, c in self.realtime)

    def _apply_realtime(self) -> bool:
        """Carry out what real-time players chose. Returns True if anything was applied."""
        applied = False
        for name, controller in self.realtime:
            for decision in controller.take_decisions():
                if decision is None:
                    self.stopped = True  # the player chose to save and exit
                    return applied
                self._busy = True
                before = len(Messages._messages)
                ok = self.engine.act_now(self.engine.player(name), decision.action, decision.reason)
                self._busy = False
                why = "" if ok else " ".join(m.text for m in Messages._messages[before:])
                controller.action_result(decision, ok, why)
                self._broadcast()
                applied = True
        return applied

    def _answer_offers(self) -> bool:
        """Trade offers to people played by turn-based controllers (NPCs) are answered as soon as the
        person can use their hands; real-time players answer from their display."""
        answered = False
        for offer in self.engine.possessions.awaiting_answer():
            controller = self.controllers.get(offer["to"])
            target = self.engine.player(offer["to"])
            if controller is None or (controller.realtime and not self._auto(controller)) or target is None or self.engine.possessions.hands_free(target):
                continue
            decision = controller.answer_offer(self.engine.observe(target), offer)
            if decision is not None:
                self.engine.quick(target, decision.action, decision.reason)
                answered = True
        if answered:
            self._broadcast()
        return answered

    def _restock(self) -> bool:
        """NPCs running out of food or water take some from the camp store into their packs (items.json
        'keeping'), and put back materials their work doesn't use; you do that yourself in your inventory window."""
        engine, took = self.engine, False
        for name, controller in self.controllers.items():
            p = engine.player(name)
            if controller.is_human or not engine.possessions.hands_free(p):
                continue
            took |= engine.possessions.restock(p)
            took |= engine.possessions.put_back(p)
        if took:
            self._broadcast()
        return took

    def _aside_decisions(self) -> bool:
        """NPCs busy with work, a meal or rest still take part in politics (time.json 'while_busy'): every
        few days each one may vote, nominate, appoint... without breaking off what they are doing."""
        engine = self.engine
        cfg = engine.WHILE_BUSY
        soon = cfg.get("npc_check_days", 5) * HOURS_PER_DAY            # a ballot or challenge waits on them
        later = cfg.get("npc_check_days_otherwise", 30) * HOURS_PER_DAY  # anything else (appointing, research...)
        urgent = {"vote", "nominate", "decline_nomination", "answer_challenge"}
        acted = False
        for name, controller in self.controllers.items():
            if controller.realtime and not self._auto(controller):
                continue
            p = engine.player(name)
            since = engine.clock - engine.aside_checked.get(name, -later)
            if engine.clock - engine.aside_looked.get(name, -soon) < soon or not engine.can_act_aside(p):
                continue
            engine.aside_looked[name] = engine.clock
            legal = engine.aside_actions(p)
            if not legal or (since < later and not any(a.type in urgent for a in legal)):
                continue
            engine.aside_checked[name] = engine.clock
            from core.actions import Action
            decision = controller.decide(engine.observe(p), legal + [Action("wait", {"days": 1}, "Carry on")])
            if decision is None or decision.action.type == "wait":
                continue
            self._busy = True
            acted |= engine.act_aside(p, decision.action, decision.reason)
            self._busy = False
        if acted:
            self._broadcast()
        return acted

    def _sync_people(self):
        """Births and deaths (core/life.py): a newborn gets an NPC controller, the dead lose theirs, and when the
        person you play dies you play on as someone else (life.json 'successor': your eldest child first)."""
        from controllers.npc import NPCController
        engine = self.engine
        living = {p.name for p in engine.players}
        changed = False
        for name in [n for n in self.controllers if n not in living]:
            c = self.controllers.pop(name)
            changed = True
            heir = engine.life.successor_for(name) if c.is_human else None
            if heir is None:
                if not c.is_human and c in self.listeners:
                    self.listeners.remove(c)
                continue
            old = self.controllers.get(heir.name)
            if old is not None and old in self.listeners:
                self.listeners.remove(old)
            c.name = heir.name
            self.controllers[heir.name] = c
            heir.controller = "human"
            Messages.add(f"You were {name}, and {name} is dead. You play on as {heir.name}, aged {heir.age} "
                         f"({engine.life.life_stage(heir).lower()})", category="vital")
        for p in engine.players:
            if p.name not in self.controllers:
                c = NPCController(p.name, rng=random.Random(f"{p.name}:{p.id}:{p.born}"))  # the same in every replay
                self.controllers[p.name] = c
                self.listeners.append(c)
                changed = True
        if changed:
            self.realtime = [(n, c) for n, c in self.controllers.items() if c.realtime]
            engine.possessions.keeps_all = {n for n, c in self.controllers.items() if c.is_human and not self._auto(c)}
            for p in engine.players:
                p.controller = "human" if self.controllers[p.name].is_human else "npc"
            self._broadcast()
        if not engine.players:
            Messages.add("The tribe is no more. Everyone has died.", category="vital")
            self._broadcast()
            self.stopped = True

    def _publish(self, force: bool = False):
        """Send real-time controllers the current view (at most ~10 times a real second unless forced)."""
        if not self.realtime:
            return
        now = time.monotonic()
        if not force and now - self._last_publish < 0.1:
            return
        self._last_publish = now
        for name, controller in self.realtime:
            player = self.engine.player(name)
            controller.update(self.engine.observe(player), self.engine.legal_actions(player))

    # ------------------------------------------------------------------ #
    def _loop(self, max_years: Optional[float]):
        engine = self.engine
        if not engine.started:
            engine.start()
            self._broadcast()
        self._publish(force=True)
        limit = None if max_years is None else max_years * HOURS_PER_YEAR
        failures = 0
        while not self.stopped and not self._interrupted:
            self._sync_auto()
            if self._apply_realtime() | self._answer_offers() | self._restock() | self._aside_decisions():
                self._publish(force=True)
            if self.stopped:
                break
            target = engine.peek_next_time()
            if limit is not None and target >= limit:
                break
            needed = target - engine.clock
            if needed > 0:
                self._publish(force=True)
            waited = self.pacer.wait(needed, self._decisions_waiting if self.realtime else None)
            if self._interrupted:
                break
            if waited < needed:
                engine.advance_clock(waited)  # a real-time player acted part way; act at this moment
                continue
            season_before = engine.clock // (DAYS_PER_SEASON * HOURS_PER_DAY)
            self._busy = True
            actor = engine.step()
            self._sync_people()
            self._busy = False
            self._broadcast()
            self._publish()
            if self.autosave and engine.clock // (DAYS_PER_SEASON * HOURS_PER_DAY) != season_before:
                self.autosave(self)
            if actor is None:
                continue

            controller = self.controllers[actor.name]
            if controller.realtime and not self._auto(controller):
                engine.park(actor)  # they act whenever they choose; time keeps moving
                self._publish(force=True)
                continue
            decision = controller.decide(engine.observe(actor), engine.legal_actions(actor))
            if decision is None:
                self.stopped = True  # the player chose to save and exit
                break
            self._busy = True
            ok = engine.apply(actor, decision.action, decision.reason)
            self._busy = False
            self._broadcast()
            failures = 0 if ok else failures + 1
            if failures >= 3 and (not controller.is_human or self._auto(controller)):
                # Safety net so a confused NPC can never stall the game: it waits a day.
                logger.error(f"{actor.name} chose invalid actions 3 times; making them wait")
                wait = next(a for a in engine.legal_actions(actor) if a.type == "wait")
                engine.apply(actor, wait)
                failures = 0
        self._publish(force=True)

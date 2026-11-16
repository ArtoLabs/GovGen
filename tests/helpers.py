import contextlib
import logging
import random
from unittest import mock

from core.actions import Action
from core.calendar import HOURS_PER_DAY
from core.engine import GameEngine
from utils.messages import Messages
from world.character import RULES as CHARACTER

logging.getLogger("govgen").setLevel(logging.CRITICAL)


def new_engine(seed: int = 0) -> GameEngine:
    random.seed(seed)
    Messages.clear()
    engine = GameEngine()
    engine.start()
    return engine


def no_illness(engine):
    """Nobody falls ill (or so dies) in this engine: for tests of something else that run for years."""
    engine.life.illnesses = lambda: {}


@contextlib.contextmanager
def immortal(engine):
    """Nobody dies (or is born) in this engine: no illness, no pregnancies, and health at 0 is a collapse again
    (character.json 'at_zero'). For tests of something else that run for years (research, NPCs not stalling), not
    of survival; the tribe stays as it started."""
    no_illness(engine)
    engine.life._pregnancy_roll = lambda: None
    with mock.patch.object(CHARACTER, "zero_health_kills", False):
        yield engine


def give_work(engine, name: str, occupation: str = "Gatherer"):
    """Make `name` hold this occupation (if they don't yet), e.g. so they may fetch water."""
    p = engine.player(name)
    if p not in engine.government.occupations[occupation]:
        engine.government.occupations[occupation].append(p)
    return p


def find(engine, player, type_, **params):
    """The legal action of this type whose params include `params` (None if not legal)."""
    for a in engine.legal_actions(player):
        if a.type == type_ and all(a.params.get(k) == v for k, v in params.items()):
            return a
    return None


def wait(engine, player, days: int = 1):
    engine.apply(player, find(engine, player, "wait", days=days))


def become_actor(engine, name: str, limit: int = 5000):
    """Move time forward, everyone else just waiting, until `name` is free to act."""
    for _ in range(limit):
        actor = engine.step()
        if actor is None:
            continue
        if actor.name == name:
            return actor
        wait(engine, actor)
    raise AssertionError(f"{name} never got to act")


def do(engine, name: str, type_, **params) -> bool:
    player = become_actor(engine, name)
    action = find(engine, player, type_, **params)
    assert action is not None, f"{name} cannot {type_} {params}; legal: {[str(a) for a in engine.legal_actions(player)][:20]}"
    return engine.apply(player, action)


def advance_days(engine, days: float):
    """Let time pass; whoever is free just waits a day."""
    target = engine.clock + days * HOURS_PER_DAY
    while engine.peek_next_time() <= target:
        actor = engine.step()
        if actor is not None:
            wait(engine, actor)
    engine.game_state.clock = max(engine.clock, int(target))


def advance_until(engine, condition, days: int = 400) -> bool:
    for _ in range(days):
        if condition():
            return True
        advance_days(engine, 1)
    return condition()


def vote_all(engine, choose, days: int = 60):
    """Everyone votes when free with choose(player_name, ballot_view) -> choice, until no ballot is pending."""
    end = engine.clock + days * HOURS_PER_DAY
    while engine.clock < end and any(engine.voting.pending_votes(p) for p in engine.players):
        actor = engine.step()
        if actor is None:
            continue
        pending = engine.voting.pending_votes(actor)
        if pending:
            b = pending[0]
            view = next(x for x in engine.observe(actor)["ballots"] if x["key"] == b.key)
            engine.apply(actor, Action("vote", {"ballot": b.key, "choice": choose(actor.name, view)}))
        else:
            wait(engine, actor)


def seat(gov, office: str, player):
    """Give someone an office as if they had held it for a long time (past the new holder's grace)."""
    ok = gov.assign_office(office, player)
    gov.took_office.get(player.name, {}).pop(office, None)
    return ok

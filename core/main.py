"""Start or continue a game.

    python -m core.main                         play on the real-time HUD; continues the saved game if there is one
    python -m core.main --classic               play with the old scrolling text menus (turn-based)
    python -m core.main --new                   start a new game (the save is replaced at the next autosave)
    python -m core.main --watch --years 50      every player is an NPC; watch them (never touches the save)
    python -m core.main --speed 20              playback speed multiplier ('max' = no waiting)
    python -m core.main --seed 7 --log game.jsonl --detail summary
"""
import argparse
import json
import random
import threading
from typing import Optional

from controllers import HUDController, NPCController, TerminalController, ConsolePrinter
from core.calendar import format_date
from core.engine import GameEngine
from core.game import Game, Pacer
from core.save import load_save, rng_state_from_json, save_game, save_summary, SAVE_FILE
from utils.logging_config import logger
from utils.settings import load_settings
from world.player import players as default_players


def build_game(settings, watch: bool = False, saved: Optional[dict] = None, pacer: Optional[Pacer] = None,
               hud: bool = False) -> Game:
    engine = GameEngine.from_dict(saved["engine"]) if saved else GameEngine()
    seeder = random.Random(settings["seed"]) if settings["seed"] is not None else random.Random()
    if not saved:
        engine.roll_characters(random.Random(seeder.random()))  # a new game: everyone rolled with dice
    controllers, observers = {}, []
    for player in engine.players:
        if player.controller == "human" and not watch and hud:
            controllers[player.name] = HUDController(player.name, settings["npc_detail"])
        elif player.controller == "human" and not watch:
            controllers[player.name] = TerminalController(player.name, settings["npc_detail"], pacer)
        else:
            controllers[player.name] = NPCController(player.name, rng=random.Random(seeder.random()))
        if saved:
            controllers[player.name].load_state(saved["controllers"].get(player.name, {}))
    if not any(c.is_human for c in controllers.values()):
        observers.append(ConsolePrinter(settings["npc_detail"]))
    return Game(engine, controllers, observers, pacer=pacer,
                autosave=None if watch else (lambda g: save_game(g) if g.engine.players else None))


def run_hud(game: Game, max_years: Optional[float]):
    """Run the game loop in a background thread and the HUD in this one."""
    import logging
    from ui.hud import GovGenHUD
    controller = next(c for c in game.controllers.values() if c.realtime)
    # Console logging would scribble over the HUD; errors still go to govgen.log.
    for handler in list(logger.handlers):
        if type(handler) is logging.StreamHandler:
            logger.removeHandler(handler)
    errors = []

    def play():
        try:
            game.run(max_years=max_years)
        except BaseException as e:  # shown after the HUD closes
            logger.exception("Game loop crashed")
            errors.append(e)

    thread = threading.Thread(target=play, name="game-loop", daemon=True)
    thread.start()
    try:
        GovGenHUD(controller, game.pacer, thread).run()
    finally:
        controller.quit()
        game.request_stop()
        thread.join(timeout=10)
    if errors:
        raise errors[0]


def parse_speed(text: str) -> float:
    return 0 if text.lower() == "max" else float(text)


def main():
    parser = argparse.ArgumentParser(description="GovGen government simulation")
    parser.add_argument("--watch", action="store_true", help="make every player an NPC and print what happens")
    parser.add_argument("--new", action="store_true", help="start a new game instead of continuing the save")
    parser.add_argument("--years", type=float, help="stop when the game clock reaches this year")
    parser.add_argument("--speed", type=parse_speed, help="playback speed multiplier, or 'max'")
    parser.add_argument("--seed", type=int, help="random seed, for repeatable new games")
    parser.add_argument("--detail", choices=["full", "summary"], help="how much NPC activity to show")
    parser.add_argument("--classic", action="store_true", help="old scrolling text menus; the game pauses for you")
    parser.add_argument("--log", help="write every action taken to this file (JSON lines)")
    args = parser.parse_args()

    settings = load_settings()
    if args.seed is not None:
        settings["seed"] = args.seed
    if args.detail:
        settings["npc_detail"] = args.detail
    pacer = Pacer(settings["real_seconds_per_game_year"],
                  args.speed if args.speed is not None else settings["playback_speed"])

    saved = None
    summary = None if (args.watch or args.new) else save_summary()
    if summary:
        answer = input(f"Continue your saved game from {summary}? [Y/n] ").strip().lower()
        if answer in ("", "y", "yes"):
            saved = load_save()
    if saved:
        random.setstate(rng_state_from_json(saved["random_state"]))
    elif settings["seed"] is not None:
        random.seed(settings["seed"])  # dice and tie-breaks use the global generator

    roster = saved["engine"].get("roster") if saved else None  # a saved game's tribe (births and deaths)
    humans = [e for e in roster if e.get("controller") == "human"] if roster else \
        [p for p in default_players if p.controller == "human"]
    use_hud = not args.watch and not args.classic and len(humans) == 1
    game = build_game(settings, watch=args.watch, saved=saved, pacer=pacer, hud=use_hud)
    if args.years is not None:
        max_years = args.years
    else:
        max_years = 50 if args.watch else None
    try:
        if use_hud:
            run_hud(game, max_years)
        else:
            game.run(max_years=max_years)
    except EOFError:
        print("\nInput ended.")
    finally:
        if not args.watch and game.engine.started and not game.engine.players:
            print(f"\nThe tribe is no more: everyone had died by {format_date(game.engine.clock)}. "
                  f"The save was left as it was; start again with --new.")
        elif not args.watch and game.engine.started:
            save_game(game)
            print(f"\nGame saved at {format_date(game.engine.clock)} ({SAVE_FILE}).")
        if args.log:
            with open(args.log, "w", encoding="utf-8") as f:
                for entry in game.engine.action_log:
                    f.write(json.dumps(entry) + "\n")
            print(f"Wrote {len(game.engine.action_log)} actions to {args.log}")
        print("Exiting simulation.")


if __name__ == "__main__":
    main()

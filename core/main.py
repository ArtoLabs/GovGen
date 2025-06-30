import os
import random
from typing import List, Tuple, Callable
from core.government import Government
from world.player import players, Player
from core.interfaces import initialize_interfaces
from core.commands import CommandHandler
from core.voting_manager import VotingManager
from core.prompt import PromptManager
from innovations.innovation_manager import InnovationManager
from utils.messages import Messages
from utils.logging_config import logger

class Simulation:
    def __init__(self):
        self.government = Government(self)
        self.current_year = 0
        self.current_player_index = 0
        self.players = players
        logger.debug(f"Players loaded: {[p.name for p in self.players]}")
        self.running = True
        self.active_interface = None
        self.command_handler = CommandHandler(self)
        self.voting_manager = VotingManager(self)
        self.innovation_manager = InnovationManager(self.government)
        for player in self.players:
            self.government.add_player(player)
        logger.debug(f"Players added to government: {len(self.players)}")
        self.government.initialize()
        logger.debug("Government initialized")
        initialize_interfaces(self.government)
        logger.debug(f"Initial discovered innovations: {self.government.innovation_pool.discovered}")
        logger.debug(f"Initial assignments: {self.government.assignments}")
        logger.debug(f"Government type: {self.government.government_type.name}")
        for player in self.players:
            logger.debug(f"{player.name}.assigned_roles: {player.assigned_roles}")

    def clear_screen(self):
        os.system('cls' if os.name == 'nt' else 'clear')

    def do_end_turn(self):
        """Advance the turn, process year-end events, and trigger managers."""
        current_player = self.players[self.current_player_index]
        logger.debug(f"Ending turn for {current_player.name}")
        for vote in self.voting_manager.active_votes:
            if vote.is_voting_active() and vote.force_vote and not vote.can_end_turn(current_player):
                Messages.add(f"You must vote for {vote.role} before ending your turn!")
                return
        self.active_interface = None
        roll, _ = self.government.dice_bag.roll("d20")
        logger.debug(f"Divine appointment roll: {roll}")
        if roll == 20:
            assigned_players = set()
            for holders in self.government.assignments.values():
                assigned_players.update(holders)
            unassigned_players = [p for p in self.players if p not in assigned_players]
            if unassigned_players:
                available_roles = [
                    role for role, reqs in self.government.government_type.title_requirements.items()
                    if reqs.get("selection_method") == "divine_appointment" and
                       len(self.government.assignments.get(role, [])) < reqs.get("max_holders", 1)
                ]
                if available_roles:
                    selected_player = random.choice(unassigned_players)
                    selected_role = random.choice(available_roles)
                    if self.government.assign_role(selected_role, selected_player):
                        Messages.add(f"{selected_player.name} has been divinely appointed as {selected_role}")
                        logger.debug(f"Divinely appointed {selected_player.name} as {selected_role}")
        self.voting_manager.process_votes()  # Process votes before year advances
        self.current_player_index = (self.current_player_index + 1) % len(self.players)
        if self.current_player_index == 0:
            self.current_year += 1
            self.government.generate_innovation_points()
            Messages.add(
                f"Year {self.current_year} begins. Innovation Points: {self.government.innovation_pool.points}"
            )
            logger.debug(f"New year {self.current_year}")
            self.voting_manager.process_votes()  # Process votes to close nominations and start voting
            self.innovation_manager.process_turn()
            self.voting_manager.initiate_votes()
        logger.debug("Exiting do_end_turn")

    def run(self):
        """Run the main game loop."""
        self.clear_screen()
        Messages.add("Welcome to Government Simulation!")
        Messages.add(f"Players: {[p.name for p in self.players]}")
        Messages.add(f"Initial Year: {self.current_year}")
        self.voting_manager.initiate_votes()
        while self.running:
            self.clear_screen()
            prompt, menu_items = self.command_handler.get_prompt()
            command = input(prompt).strip().lower()
            logger.debug(f"Received command: {command}")
            try:
                num = int(command)
                for number, action, key in menu_items:
                    if number == num:
                        action()
                        logger.debug(f"Executed action for command {key}")
                        break
                else:
                    print("\033[91mInvalid selection.\033[0m")
                    logger.info("Invalid selection entered")
                    input("Press Enter to continue...")
            except ValueError:
                for number, action, key in menu_items:
                    if command == key:
                        action()
                        logger.debug(f"Executed action for command {key}")
                        break
                else:
                    print("\033[91mUnknown command.\033[0m")
                    logger.info("Unknown command entered")
                    input("Press Enter to continue...")

if __name__ == "__main__":
    sim = Simulation()
    sim.run()
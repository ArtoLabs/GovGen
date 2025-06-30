from typing import List, Tuple, Callable, Set
from world.player import Player
from core.interfaces import get_interface
from core.government_types import get_available_government_types
from innovations.innovation import ALL_INNOVATIONS
from innovations.innovation_map import ROLE_INNOVATION_MAP
from utils.utils import choose_from_list
from utils.messages import Messages
from utils.logging_config import logger
from core.prompt import PromptManager

class CommandHandler:
    def __init__(self, simulation: 'core.main.Simulation'):
        self.sim = simulation
        self.prompt_manager = PromptManager(simulation)
        self.commands: List[Tuple[str, str, Callable[[], None]]] = [
            ("list_players", "Show all players and their roles", self.do_list_players),
            ("list_roles", "Show available roles", self.do_list_roles),
            ("list_innovations", "Show innovations by role", self.do_list_innovations),
            ("set_government_type", "Change the government type", self.do_set_government_type),
            ("end_turn", "End the current player's turn", self.do_end_turn),
            ("exit", "Exit the simulation", self.do_exit),
            ("open_role_interface", "Open a role interface", self.do_open_role_interface),
            ("nominate", "Nominate a candidate for a role", self.do_nominate),
            ("appoint_player_to_role", "Appoint a player to a role", self.do_appoint_player_to_role),
        ]

    def do_list_players(self):
        """Display all players and their roles."""
        for p in self.sim.players:
            print(p)
        input("Press Enter to continue...")

    def do_list_roles(self):
        """Display available roles."""
        titled_roles = list(self.sim.government.government_type.role_mappings.keys())
        print("Available Roles:", titled_roles or "None")
        input("Press Enter to continue...")

    def get_prereq_icon(self, innov_name: str) -> str:
        """Get the icon for an innovation's prerequisite."""
        logger.debug(f"Querying icon for innovation {innov_name}")
        for role, innovations in ROLE_INNOVATION_MAP.items():
            for innov in innovations:
                if innov.name == innov_name:
                    logger.debug(f"Found {innov_name} in role {role} with icon {innov.icon}")
                    return innov.icon
        innov = ALL_INNOVATIONS.get(innov_name)
        icon = innov.icon if innov else "?"
        logger.debug(f"Using fallback icon {icon} for {innov_name}")
        return icon

    def build_innovation_list(self, discovered: Set[str], role_key: str) -> List[str]:
        """Build a formatted list of innovations for a role."""
        role_innovations = ROLE_INNOVATION_MAP.get(role_key, [])
        logger.debug(f"Role {role_key} innovations: {[innov.name for innov in role_innovations]}")
        if not role_innovations:
            return [f"No innovations for role {role_key.capitalize()}."]
        lines = []
        for innov in sorted(role_innovations, key=lambda x: x.name):
            logger.debug(f"Processing innovation {innov.name}")
            status = "[X]" if innov.name in discovered else ""
            lines.append(f"{innov.icon} {innov.name} {status} - {innov.description} [Cost: {innov.cost}]")
            if innov.prerequisites:
                prereq_list = []
                for prereq in sorted(innov.prerequisites):
                    if prereq not in ALL_INNOVATIONS:
                        logger.debug(f"Prerequisite {prereq} not found in ALL_INNOVATIONS")
                        continue
                    prereq_icon = self.get_prereq_icon(prereq)
                    prereq_list.append(f"{prereq_icon}{prereq}")
                if prereq_list:
                    lines.append(f"    Prerequisites: {', '.join(prereq_list)}")
            lines.append("")
        return lines

    def do_list_innovations(self):
        """Display innovations for a selected role."""
        roles = sorted(ROLE_INNOVATION_MAP.keys())
        options = roles + [None]
        selected_role = choose_from_list(
            options,
            "Select role to view innovations:",
            lambda r: "Cancel" if r is None else r.capitalize()
        )
        if selected_role is None:
            Messages.add("Innovation list cancelled.")
            logger.info("Innovation list cancelled")
            return
        print(f"{selected_role.capitalize()} Innovations:")
        discovered = self.sim.government.innovation_pool.discovered
        list_lines = self.build_innovation_list(discovered, selected_role)
        for line in list_lines:
            print(line)
        input("Press Enter to continue...")

    def do_set_government_type(self):
        """Change the government type."""
        available_types = get_available_government_types(self.sim.government.innovation_pool.discovered)
        if not available_types:
            print("No available government types.")
            logger.info("No available government types")
            input("Press Enter to continue...")
            return
        selected = choose_from_list(available_types, "Select government type:", lambda t: t.name)
        if selected:
            if self.sim.government.set_government_type(selected.name.lower()):
                print(f"Government type changed to {selected.name}.")
                logger.info(f"Government type changed to {selected.name}")
            else:
                print("Failed to change government type.")
                logger.error("Failed to change government type")
        input("Press Enter to continue...")

    def do_end_turn(self):
        """Trigger end of turn."""
        self.sim.do_end_turn()

    def do_exit(self):
        """Exit the simulation."""
        print("Exiting simulation.")
        logger.info("Exiting simulation")
        self.sim.running = False

    def do_open_role_interface(self):
        """Open a role interface for the current player."""
        current_player = self.sim.players[self.sim.current_player_index]
        interfaces = self.sim.government.get_player_interfaces(current_player)
        if not interfaces:
            Messages.add("No role interfaces available.")
            logger.info("No role interfaces available")
            return
        selected = choose_from_list(
            interfaces,
            "Select role interface:",
            lambda i: i.role_key.capitalize()
        )
        if selected:
            self.sim.active_interface = selected
            self.sim.voting_manager.initiate_votes()

    def do_appoint_player_to_role(self):
        current_player = self.sim.players[self.sim.current_player_index]
        # Find roles the current player can appoint for
        appointable_roles = [
            role_id for role_id, reqs in self.sim.government.government_type.title_requirements.items()
            if reqs.get("selection_method") == "appointment"
               and current_player in self.sim.government.get_role_holders(reqs.get("appointer"))
        ]
        if not appointable_roles:
            Messages.add("No roles available to appoint.")
            logger.info("No roles available to appoint")
            return
        # Let the player choose a role and appointee
        role_id = choose_from_list(appointable_roles, "Select role to appoint to:")
        if role_id:
            appointee = choose_from_list(self.sim.government.players, "Select player:", lambda p: p.name)
            if appointee:
                self.sim.government.appoint_player_to_role(current_player, role_id, appointee)

    # In commands.py
    def do_nominate(self):
        current_player = self.sim.players[self.sim.current_player_index]
        eligible_votes = [
            vote for vote in self.sim.voting_manager.active_votes
            if vote.is_nomination_open and (
                    vote.nomination_method == "open" or
                    (vote.nomination_method == "self_appointed" and current_player.name not in vote.nominations[
                        vote.role]) or
                    (vote.nomination_method == "appointed" and vote.can_appoint(current_player, vote.role))
            )
        ]
        logger.debug(f"Eligible votes for {current_player.name}: {[v.role for v in eligible_votes]}")
        if not eligible_votes:
            Messages.add("No roles available for nomination.")
            logger.info("No roles available for nomination")
            return
        selected_vote = choose_from_list(
            eligible_votes,
            "Select role to nominate for:",
            lambda v: f"{v.role}{f' (Seat {v.seat_number})' if v.seat_number else ''}"
        )
        if not selected_vote:
            Messages.add("Nomination cancelled.")
            logger.info("Nomination cancelled")
            return
        selected_role = selected_vote.role
        candidates = []
        if selected_vote.nomination_method == "self_appointed":
            candidates = [current_player]
        else:
            candidates = [p for p in self.sim.players if
                          not self.sim.government.is_player_assigned(p.name, selected_role)]
        if not candidates:
            Messages.add("No eligible candidates available.")
            logger.info("No eligible candidates available")
            return
        selected_candidate = choose_from_list(
            candidates,
            f"Nominate a candidate for {selected_role}:",
            lambda p: p.name
        )
        if not selected_candidate:
            Messages.add("Nomination cancelled.")
            logger.info("Nomination cancelled")
            return
        try:
            selected_vote.nominate(current_player, selected_candidate.name)
            Messages.add(f"{current_player.name} nominated {selected_candidate.name} for {selected_role}")
            logger.debug(
                f"Nominated {selected_candidate.name} for {selected_role}. Current nominations: {selected_vote.nominations[selected_role]}")
        except ValueError as e:
            print(f"Error: {e}")
            logger.error(f"Nomination error: {e}")
            input("Press Enter to continue...")


    def get_prompt(self) -> Tuple[str, List[Tuple[int, Callable[[], None], str]]]:
        """Delegate prompt generation to PromptManager."""
        return self.prompt_manager.get_prompt()

    def execute(self, command: str):
        """Execute a command based on user input."""
        prompt, menu_items = self.get_prompt()
        try:
            num = int(command)
            for number, action, key in menu_items:
                if number == num:
                    action()
                    return
            Messages.add("Invalid selection.")
            logger.info("Invalid command selection")
        except ValueError:
            for number, action, key in menu_items:
                if command == key:
                    action()
                    return
            Messages.add("Unknown command.")
            logger.info("Unknown command entered")

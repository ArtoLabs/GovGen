from typing import List, Tuple, Callable
from world.player import Player
from utils.utils import choose_from_list
from utils.logging_config import logger
from utils.messages import Messages


class PromptManager:
    def __init__(self, simulation: 'core.main.Simulation'):
        self.sim = simulation

    def get_prompt(self) -> Tuple[str, List[Tuple[int, Callable[[], None], str]]]:
        """
        Generate the game prompt and menu items by combining state info, campaigns, messages, and commands.
        Returns a tuple of the prompt string and a list of menu items (number, action, key).
        """
        try:
            self.sim.voting_manager.initiate_votes()
            current_player = self.sim.players[self.sim.current_player_index]

            # Build prompt components
            state_info = self._build_state_info()
            campaign_info = self._build_campaign_info()
            messages = self._build_messages()
            general_menu, menu_items, next_number = self._build_general_menu(current_player)
            submenu, additional_menu_items = self._build_submenu(current_player, next_number)

            # Combine prompt
            prompt = f"\n{messages}\n{state_info}{campaign_info}{general_menu}{submenu}\n{current_player.name} ({', '.join(self._get_player_roles(current_player))}) > "
            menu_items.extend(additional_menu_items)

            logger.debug(f"Final menu items: {[(n, k) for n, _, k in menu_items]}")
            return prompt, menu_items
        except Exception as e:
            logger.error(f"Error generating prompt: {e}")
            return "Error generating prompt. Please report this bug.\n", []

    def _get_player_roles(self, player: Player) -> List[str]:
        """Get the roles assigned to the current player."""
        roles = [
            role_key for role_key, holders in self.sim.government.assignments.items()
            if player in holders
        ]
        return list(dict.fromkeys(roles)) or ["None"]

    def _build_state_info(self) -> str:
        """Build the state information section of the prompt."""
        discovered = [i.name for i in self.sim.government.innovation_pool.get_discovered()]
        return (
            "__________________________________\n"
            f"Year {self.sim.current_year} | Innovation Points: {self.sim.government.innovation_pool.points}\n"
            f"Government Type: {self.sim.government.government_type.name}\n"
            f"Discovered Innovations: {', '.join(discovered) or 'None'}\n"
            f"Research Queue: {', '.join(self.sim.government.research_queue) or 'Empty'}\n"
            "__________________________________\n"
        )

    def _build_campaign_info(self) -> str:
        """Build the election campaigns section of the prompt."""
        # Collect votes that are either in nomination or voting phase
        active_campaigns = [
            vote for vote in self.sim.voting_manager.active_votes
            if vote.is_nomination_open or vote.voting_active
        ]
        if not active_campaigns:
            return ""

        # Build the campaign box with ANSI color coding
        campaign_info = "\033[96m__________________________________\nElection Campaigns:\n"
        for vote in active_campaigns:
            # Get max_holders for the role to decide if seat number should be shown
            max_holders = self.sim.government.government_type.title_requirements.get(vote.role, {}).get("max_holders",
                                                                                                        1)
            role_str = vote.role
            if max_holders > 1 and vote.seat_number is not None:
                role_str += f" (Seat {vote.seat_number})"

            # Determine the phase and list of names
            if vote.is_nomination_open:
                phase_str = "Taking nominations for"
                list_str = ', '.join(vote.nominations.get(vote.role, []))
            elif vote.voting_active:
                phase_str = "Now voting on"
                list_str = ', '.join(vote.candidates)
            else:
                continue  # Skip if neither phase is active (shouldn’t happen)

            # Add the formatted line
            line = f"  {phase_str} {role_str}: {list_str}\n"
            campaign_info += line

        campaign_info += "__________________________________\n\n\033[0m"
        return campaign_info

    def _build_messages(self) -> str:
        """Build and clear the messages section."""
        msg_str = Messages.to_str()
        Messages.clear()
        return msg_str

    def _build_general_menu(self, current_player: Player) -> Tuple[str, List[Tuple[int, Callable[[], None], str]], int]:
        """Build the general commands menu, filtering unavailable commands. Returns menu string, items, and next number."""
        menu_items = []
        general_menu = "General Commands:\n"
        number = 1
        roles = self._get_player_roles(current_player)

        for key, desc, action in self.sim.command_handler.commands:
            if self._should_include_command(key, current_player, roles):
                general_menu += f"  {number}: {desc}\n"
                menu_items.append((number, action, key))
                number += 1

        return general_menu, menu_items, number

    def _should_include_command(self, key: str, player: Player, roles: List[str]) -> bool:
        """Determine if a command should be included in the menu."""
        if key == "open_role_interface" and not roles:
            return False
        if key == "nominate":
            return any(
                vote.is_nomination_open and (
                        vote.nomination_method == "open" or
                        (vote.nomination_method == "self_appointed" and player.name not in [
                            c.name if isinstance(c, Player) else c for c in vote.nominations[vote.role]
                        ]) or
                        (vote.nomination_method == "appointed" and vote.can_appoint(player, vote.role))
                )
                for vote in self.sim.voting_manager.active_votes
            )
        if key == "appoint_player_to_role":
            return any(
                reqs.get("selection_method") == "appointment" and
                player in self.sim.government.get_role_holders(reqs.get("appointer"))
                for role_id, reqs in self.sim.government.government_type.title_requirements.items()
            )
        return True

    def _build_submenu(self, current_player: Player, start_number: int) -> Tuple[
        str, List[Tuple[int, Callable[[], None], str]]]:
        """Build the voting and interface commands submenu, continuing the number sequence from start_number."""
        submenu = ""
        menu_items = []
        number = start_number

        # Voting Commands
        voting_active = any(vote.is_voting_active() for vote in self.sim.voting_manager.active_votes)
        logger.debug(
            f"Active votes: {[f'{vote.role} (seat {vote.seat_number}, active={vote.is_voting_active()})' for vote in self.sim.voting_manager.active_votes]}")
        logger.debug(f"Voting active: {voting_active}")

        if voting_active:
            submenu += "__________________________________\nVoting Commands:\n"
            for vote in self.sim.voting_manager.active_votes:
                if vote.is_voting_active() and current_player not in vote.votes:
                    interface = self.sim.voting_manager.vote_interfaces.get(vote.role)
                    logger.debug(
                        f"Vote {vote.role}: Interface={interface}, Player voted={current_player in vote.votes}")
                    if interface:
                        submenu += f"  {number}: {interface.display_vote_options()}\n"
                        menu_items.append(
                            (number, lambda r=vote.role: self.sim.voting_manager.handle_vote(r), vote.role)
                        )
                        number += 1

        # Interface Commands
        if self.sim.active_interface:
            submenu += "__________________________________\n"
            submenu += f"{self.sim.active_interface.role_key.capitalize()} Interface Commands:\n"
            role_commands = self.sim.active_interface.get_commands()
            logger.debug(f"Role commands: {role_commands}")
            for cmd_key, cmd_desc in role_commands.items():
                action = lambda key=cmd_key: self.sim.active_interface.execute_command(key, current_player)
                submenu += f"  {number}: {cmd_desc}\n"
                menu_items.append((number, action, cmd_key))
                logger.debug(f"Assigned {number} to {cmd_key}: {cmd_desc}")
                number += 1
            submenu += f"  {number}: Close interface\n"
            menu_items.append((number, lambda: setattr(self.sim, 'active_interface', None), "close_interface"))

        return submenu, menu_items
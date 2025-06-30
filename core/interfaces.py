from typing import Dict, Callable, List, Optional
from core.command_registry import CommandRegistry
from world.player import Player
from innovations.innovation_map import ROLE_INNOVATION_MAP
from innovations.innovation_manager import InnovationManager
from utils.utils import choose_from_list
from utils.logging_config import logger
from utils.messages import Messages

class RoleInterface:
    def __init__(self, government: 'core.government.Government', role_key: str):
        self.role_key = role_key
        self.government = government
        self.innovation_manager = InnovationManager(government)
        self.commands: Dict[str, Callable[[Player], None]] = {
            "research": self.research
        }
        self.all_commands: Dict[str, str] = {
            "research": "Research a specific innovation"
        }

    def get_commands(self) -> Dict[str, str]:
        discovered = self.government.innovation_pool.discovered
        return {
            cmd_key: desc for cmd_key, desc in self.all_commands.items()
            if CommandRegistry.is_command_available(cmd_key, discovered)
        }

    def execute_command(self, command_key: str, player: Player) -> bool:
        if command_key in self.get_commands():
            self.commands[command_key](player)
            return True
        Messages.add(f"Command '{command_key}' is not available yet.")
        logger.info(f"Command '{command_key}' not available")
        return False

    def get_role_innovations(self) -> List['core.innovation.Innovation']:
        return ROLE_INNOVATION_MAP.get(self.role_key, [])

    def research(self, player: Player) -> None:
        available_innovations = [
            innov for innov in self.get_role_innovations()
            if innov.name not in self.government.innovation_pool.discovered and
               innov.name not in self.government.research_queue and
               innov.is_discoverable(self.government.innovation_pool.discovered)
        ]
        if not available_innovations:
            Messages.add("No innovations available to research.")
            logger.info("No innovations available to research")
            return
        options = available_innovations + [None]
        selected = choose_from_list(
            options,
            "Select innovation to queue for research:",
            lambda i: "Cancel" if i is None else f"{i.name} (Cost: {i.cost})"
        )
        if selected is None:
            Messages.add("Research cancelled.")
            logger.info("Research cancelled")
            return
        if self.innovation_manager.add_to_research_queue(selected.name):
            Messages.add(f"{selected.name} added to research queue.")
            logger.info(f"{selected.name} added to research queue")
        else:
            Messages.add(f"Cannot queue {selected.name} for research.")
            logger.error(f"Cannot queue {selected.name} for research")


class LeadershipInterface(RoleInterface):
    def __init__(self, government: 'core.government.Government'):
        super().__init__(government, "leadership")
        self.all_commands.update({
           # "appoint_player_to_role": "Appoint a player to a role",
            "remove_role": "Remove a player from a role",
            "start_nominations": "Start nominations for a role",
            "close_nominations": "Close nominations for a role"
        })
        self.commands.update({
          #  "appoint_player_to_role": self.appoint_player_to_role,
            "remove_role": self.remove_role,
            "start_nominations": self.start_nominations,
            "close_nominations": self.close_nominations
        })

    def start_nominations(self, player: Player) -> None:
        eligible_votes = [
            vote for vote in self.government.sim.voting_manager.active_votes
            if vote.nomination_control == "command_based" and vote.can_start_nominations(player) and not vote.is_nomination_open
        ]
        if not eligible_votes:
            print("No roles available to start nominations for.")
            logger.info("No roles available to start nominations")
            input("Press Enter to continue...")
            return
        selected_vote = choose_from_list(
            eligible_votes,
            "Select role to start nominations for:",
            lambda v: v.role
        )
        if selected_vote:
            selected_vote.start_nominations(self.government.sim.current_year)
            Messages.add(f"Nominations started for {selected_vote.role}")
            logger.debug(f"{player.name} started nominations for {selected_vote.role}")
        input("Press Enter to continue...")

    def close_nominations(self, player: Player) -> None:
        eligible_votes = [
            vote for vote in self.government.sim.voting_manager.active_votes
            if vote.nomination_control == "command_based" and vote.can_close_nominations(player) and vote.is_nomination_open
        ]
        if not eligible_votes:
            print("No roles available to close nominations for.")
            logger.info("No roles available to close nominations")
            input("Press Enter to continue...")
            return
        selected_vote = choose_from_list(
            eligible_votes,
            "Select role to close nominations for:",
            lambda v: v.role
        )
        if selected_vote:
            selected_vote.close_nominations()
            Messages.add(f"Nominations closed for {selected_vote.role}")
            logger.debug(f"{player.name} closed nominations for {selected_vote.role}")
        input("Press Enter to continue...")

    def remove_role(self, player: Player) -> None:
        players = self.government.players
        selected_player = choose_from_list(players, "Select player to remove role from:", lambda p: p.name)
        if selected_player:
            titled_roles_held = [role for role, holders in self.government.assignments.items() if
                                 selected_player in holders]
            if not titled_roles_held:
                print(f"{selected_player.name} has no titled roles.")
                logger.info(f"{selected_player.name} has no titled roles")
                input("Press Enter to continue...")
                return
            selected_role = choose_from_list(titled_roles_held, "Select role to remove:")
            if selected_role:
                self.government.remove_role(selected_role, selected_player)
        input("Press Enter to continue...")

class LegislativeInterface(RoleInterface):
    def __init__(self, government: 'core.government.Government'):
        super().__init__(government, "legislative")
        self.all_commands.update({
            "propose_law": "Propose a new law"
        })
        self.commands.update({
            "propose_law": self.propose_law
        })

    def propose_law(self, player: Player) -> None:
        law_name = input("Enter the name of the law: ").strip()
        print(f"Proposed law: {law_name} (placeholder implementation).")
        logger.info(f"Proposed law: {law_name}")
        input("Press Enter to continue...")

class JudicialInterface(RoleInterface):
    def __init__(self, government: 'core.government.Government'):
        super().__init__(government, "judicial")
        self.all_commands.update({
            "interpret_law": "Interpret an existing law",
            "resolve_dispute": "Resolve a dispute between parties"
        })
        self.commands.update({
            "interpret_law": self.interpret_law,
            "resolve_dispute": self.resolve_dispute
        })

    def interpret_law(self, player: Player) -> None:
        law_name = input("Enter the name of the law to interpret: ").strip()
        print(f"Interpreted law: {law_name} (placeholder implementation).")
        logger.info(f"Interpreted law: {law_name}")
        input("Press Enter to continue...")

    def resolve_dispute(self, player: Player) -> None:
        dispute = input("Describe the dispute: ").strip()
        print(f"Resolved dispute: {dispute} (placeholder implementation).")
        logger.info(f"Resolved dispute: {dispute}")
        input("Press Enter to continue...")

class MilitaryInterface(RoleInterface):
    def __init__(self, government: 'core.government.Government'):
        super().__init__(government, "military")
        self.all_commands.update({
            "appoint_player_to_role": "Appoint a player to a role",
            "declare_war": "Declare war on another group"
        })
        self.commands.update({
            "appoint_player_to_role": self.appoint_player_to_role,
            "declare_war": self.declare_war
        })

    def appoint_player_to_role(self, player: Player) -> None:
        appointable_roles = [
            role_id for role_id, reqs in self.government.government_type.title_requirements.items()
            if reqs.get("selection_method") == "appointment" and player in self.government.get_role_holders(
                reqs.get("appointer"))
        ]
        if not appointable_roles:
            print("No roles available to appoint.")
            logger.info("No roles available to appoint")
            input("Press Enter to continue...")
            return
        role_id = choose_from_list(appointable_roles, "Select role to appoint to:")
        if role_id:
            appointee = choose_from_list(self.government.players, "Select player:", lambda p: p.name)
            if appointee:
                self.government.appoint_player_to_role(player, role_id, appointee)
        input("Press Enter to continue...")

    def declare_war(self, player: Player) -> None:
        print("Declared war (placeholder implementation).")
        logger.info("Declared war")
        input("Press Enter to continue...")

class IntelligenceInterface(RoleInterface):
    def __init__(self, government: 'core.government.Government'):
        super().__init__(government, "intelligence")
        self.all_commands.update({
            "gather_info": "Gather information on a target",
            "conduct_espionage": "Conduct covert espionage"
        })
        self.commands.update({
            "gather_info": self.gather_info,
            "conduct_espionage": self.conduct_espionage
        })

    def gather_info(self, player: Player) -> None:
        target = input("Enter target for information gathering: ").strip()
        print(f"Gathered info on {target} (placeholder implementation).")
        logger.info(f"Gathered info on {target}")
        input("Press Enter to continue...")

    def conduct_espionage(self, player: Player) -> None:
        target = input("Enter target for espionage: ").strip()
        print(f"Conducted espionage on {target} (placeholder implementation).")
        logger.info(f"Conducted espionage on {target}")
        input("Press Enter to continue...")

class EconomicInterface(RoleInterface):
    def __init__(self, government: 'core.government.Government'):
        super().__init__(government, "economic")
        self.all_commands.update({
            "levy_tax": "Levy a tax on the population",
            "promote_trade": "Promote trade with other groups"
        })
        self.commands.update({
            "levy_tax": self.levy_tax,
            "promote_trade": self.promote_trade
        })

    def levy_tax(self, player: Player) -> None:
        amount = input("Enter tax amount: ").strip()
        print(f"Levied tax of {amount}")
        logger.info(f". (placeholder implementation)")
        input("Press Enter to continue...")

    def promote_trade(self, player: Player) -> None:
        partner = input("Enter trade partner: ").strip()
        print(f"Promoted trade with {partner}")
        logger.info(f". (placeholder implementation)")
        input("Press Enter to continue...")

class InfrastructureInterface(RoleInterface):
    def __init__(self, government: 'core.government.Government'):
        super().__init__(government, "infrastructure")
        self.all_commands.update({
            "build_project": "Start a new infrastructure project"
        })
        self.commands.update({
            "build_project": self.build_project
        })

    def build_project(self, player: Player) -> None:
        project = input("Enter project name: ").strip()
        print(f"Started infrastructure project: {project}")
        logger.info(f". (placeholder implementation)")
        input("Press Enter to continue...")

class ReligiousInterface(RoleInterface):
    def __init__(self, government: 'core.government.Government'):
        super().__init__(government, "religious")
        self.all_commands.update({
            "hold_ceremony": "Conduct a religious ceremony"
        })
        self.commands.update({
            "hold_ceremony": self.hold_ceremony
        })

    def hold_ceremony(self, player: Player) -> None:
        ceremony = input("Enter ceremony name: ").strip()
        print(f"Conducted {ceremony}")
        logger.info(f". (placeholder implementation)")
        input("Press Enter to continue...")

class CivicRepresentationInterface(RoleInterface):
    def __init__(self, government: 'core.government.Government'):
        super().__init__(government, "civic_representation")
        self.all_commands.update({
            "represent_people": "Represent the people’s interests"
        })
        self.commands.update({
            "represent_people": "self.represent_people"
        })

    def represent_people(self, player: Player) -> None:
        issue = input("Enter the issue to represent: ").strip()
        print(f"Represented issue: {issue}")
        logger.info(f". (placeholder implementation)")
        input("Press Enter to continue...")

ROLE_INTERFACES: Dict[str, RoleInterface] = {}

def initialize_interfaces(government: 'core.government.Government') -> None:
    """Initialize the role interfaces registry with a Government instance."""
    from core.roles_config import ROLE_CONFIGS
    global ROLE_CONFIGS
    logger.debug("Initializing role interfaces")
    ROLE_INTERFACES.update({
        config.key: config.interface_class(government)
        for config in ROLE_CONFIGS.values()
            if config.interface_class
    })

def get_interface(role_key: str) -> Optional['RoleInterface']:
    return ROLE_INTERFACES.get(role_key)
from typing import Dict, Callable
from command_registry import CommandRegistry
from player import get_player_by_name
from utils import choose_from_list

class RoleInterface:
    def __init__(self, role_key: str, government: 'Government'):
        self.role_key = role_key
        self.government = government
        self.commands: Dict[str, Callable[[], None]] = {}
        self.all_commands: Dict[str, str] = {}

    def get_commands(self) -> Dict[str, str]:
        discovered = self.government.innovation_pool.discovered
        return {
            cmd_key: desc for cmd_key, desc in self.all_commands.items()
            if CommandRegistry.is_command_available(cmd_key, discovered)
        }

    def execute_command(self, command_key: str) -> bool:
        if command_key in self.get_commands():
            self.commands[command_key]()
            return True
        print(f"Command '{command_key}' is not available yet.")
        return False

class LeadershipInterface(RoleInterface):
    def __init__(self, government: 'Government'):
        super().__init__("leadership", government)
        self.all_commands = {
            "assign_role": "Assign a player to a role",
            "set_method": "Set selection method for a role",
            "remove_role": "Remove a player from a role"
        }
        self.commands = {
            "assign_role": self.assign_role,
            "set_method": self.set_method,
            "remove_role": self.remove_role,
        }

    def assign_role(self) -> None:
        role_id = choose_from_list(list(self.government.government_type.role_mappings.keys()), "Select role to assign:")
        if role_id:
            players = self.government.players
            selected_player = choose_from_list(players, "Select player:", lambda p: p.name)
            if selected_player:
                self.government.assign_role(role_id, selected_player)
        input("Press Enter to continue...")

    def set_method(self) -> None:
        role_id = choose_from_list(list(self.government.government_type.role_mappings.keys()), "Select role to set method for:")
        if role_id:
            methods = self.government.get_available_selection_methods(role_id)
            if not methods:
                print("No available selection methods.")
            else:
                selected_method = choose_from_list(methods, "Select selection method:", lambda m: m.name)
                if selected_method:
                    if self.government.set_selection_method(role_id, selected_method.key):
                        print(f"Set {selected_method.name} for {role_id}.")
                    else:
                        print("Failed to set selection method.")
        input("Press Enter to continue...")

    def remove_role(self) -> None:
        players = self.government.players
        selected_player = choose_from_list(players, "Select player to remove role from:", lambda p: p.name)
        if selected_player:
            titled_roles_held = [role for role, holders in self.government.assignments.items() if selected_player in holders]
            if not titled_roles_held:
                print(f"{selected_player.name} has no titled roles.")
            else:
                selected_role = choose_from_list(titled_roles_held, "Select role to remove:")
                if selected_role:
                    self.government.remove_role(selected_role, selected_player)
        input("Press Enter to continue...")

class LegislativeInterface(RoleInterface):
    def __init__(self, government: 'Government'):
        super().__init__("legislative", government)
        self.all_commands = {
            "propose_law": "Propose a new law"
        }
        self.commands = {
            "propose_law": self.propose_law
        }

    def propose_law(self) -> None:
        law_name = input("Enter the name of the law: ").strip()
        print(f"Proposed law: {law_name} (placeholder implementation).")
        input("Press Enter to continue...")

class JudicialInterface(RoleInterface):
    def __init__(self, government: 'Government'):
        super().__init__("judicial", government)
        self.all_commands = {
            "interpret_law": "Interpret an existing law",
            "resolve_dispute": "Resolve a dispute between parties"
        }
        self.commands = {
            "interpret_law": self.interpret_law,
            "resolve_dispute": self.resolve_dispute
        }

    def interpret_law(self) -> None:
        law_name = input("Enter the name of the law to interpret: ").strip()
        print(f"Interpreted law: {law_name} (placeholder implementation).")
        input("Press Enter to continue...")

    def resolve_dispute(self) -> None:
        dispute = input("Describe the dispute: ").strip()
        print(f"Resolved dispute: {dispute} (placeholder implementation).")
        input("Press Enter to continue...")

class MilitaryInterface(RoleInterface):
    def __init__(self, government: 'Government'):
        super().__init__("military", government)
        self.all_commands = {
            "declare_war": "Declare war on another group"
        }
        self.commands = {
            "declare_war": self.declare_war
        }

    def declare_war(self) -> None:
        print("Declared war (placeholder implementation).")
        input("Press Enter to continue...")

class IntelligenceInterface(RoleInterface):
    def __init__(self, government: 'Government'):
        super().__init__("intelligence", government)
        self.all_commands = {
            "gather_info": "Gather information on a target",
            "conduct_espionage": "Conduct covert espionage"
        }
        self.commands = {
            "gather_info": self.gather_info,
            "conduct_espionage": self.conduct_espionage
        }

    def gather_info(self) -> None:
        target = input("Enter target for information gathering: ").strip()
        print(f"Gathered info on {target} (placeholder implementation).")
        input("Press Enter to continue...")

    def conduct_espionage(self) -> None:
        target = input("Enter target for espionage: ").strip()
        print(f"Conducted espionage on {target} (placeholder implementation).")
        input("Press Enter to continue...")

class EconomicInterface(RoleInterface):
    def __init__(self, government: 'Government'):
        super().__init__("economic", government)
        self.all_commands = {
            "levy_tax": "Levy a tax on the population",
            "promote_trade": "Promote trade with other groups"
        }
        self.commands = {
            "levy_tax": self.levy_tax,
            "promote_trade": self.promote_trade
        }

    def levy_tax(self) -> None:
        amount = input("Enter tax amount: ").strip()
        print(f"Levied tax of {amount} (placeholder implementation).")
        input("Press Enter to continue...")

    def promote_trade(self) -> None:
        partner = input("Enter trade partner: ").strip()
        print(f"Promoted trade with {partner} (placeholder implementation).")
        input("Press Enter to continue...")

class InfrastructureInterface(RoleInterface):
    def __init__(self, government: 'Government'):
        super().__init__("infrastructure", government)
        self.all_commands = {
            "build_project": "Start a new infrastructure project"
        }
        self.commands = {
            "build_project": self.build_project
        }

    def build_project(self) -> None:
        project = input("Enter project name: ").strip()
        print(f"Started infrastructure project: {project} (placeholder implementation).")
        input("Press Enter to continue...")

class ReligiousInterface(RoleInterface):
    def __init__(self, government: 'Government'):
        super().__init__("religious", government)
        self.all_commands = {
            "hold_ceremony": "Conduct a religious ceremony"
        }
        self.commands = {
            "hold_ceremony": self.hold_ceremony
        }

    def hold_ceremony(self) -> None:
        ceremony = input("Enter ceremony name: ").strip()
        print(f"Conducted ceremony: {ceremony} (placeholder implementation).")
        input("Press Enter to continue...")

class CivicRepresentationInterface(RoleInterface):
    def __init__(self, government: 'Government'):
        super().__init__("civic_representation", government)
        self.all_commands = {
            "represent_people": "Represent the people’s interests"
        }
        self.commands = {
            "represent_people": self.represent_people
        }

    def represent_people(self) -> None:
        issue = input("Enter the issue to represent: ").strip()
        print(f"Represented the people on: {issue} (placeholder implementation).")
        input("Press Enter to continue...")

ROLE_INTERFACES: Dict[str, RoleInterface] = {}
def initialize_interfaces(government: 'Government') -> None:
    """Initialize the role interfaces registry with a Government instance."""
    from roles_config import ROLE_CONFIGS  # Import here to avoid circular import
    global ROLE_INTERFACES
    ROLE_INTERFACES.update({
        config.key: config.interface_class(government)
        for config in ROLE_CONFIGS.values()
        if config.interface_class
    })

def get_interface(role_key: str) -> 'RoleInterface':
    return ROLE_INTERFACES.get(role_key)
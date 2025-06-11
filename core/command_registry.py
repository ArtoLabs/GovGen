from typing import Dict, List, Set

class CommandRegistry:
    _registry: Dict[str, List[str]] = {}

    @classmethod
    def register(cls, command_key: str, required_innovations: List[str]):
        """Register a command with its required innovations."""
        cls._registry[command_key] = required_innovations

    @classmethod
    def get_required_innovations(cls, command_key: str) -> List[str]:
        """Get the list of innovations required for a command."""
        return cls._registry.get(command_key, [])

    @classmethod
    def is_command_available(cls, command_key: str, discovered: Set[str]) -> bool:
        """Check if a command is available based on discovered innovations."""
        required = cls.get_required_innovations(command_key)
        return all(req in discovered for req in required)

# Register all existing commands with their prerequisites
CommandRegistry.register("assign_role", ["Chieftainship"])
CommandRegistry.register("set_method", ["Chieftainship"])
CommandRegistry.register("remove_role", ["Chieftainship"])
CommandRegistry.register("propose_law", ["Law Code", "Writing"])  # LegislativeInterface example
# Future commands can be added here, e.g.:
# CommandRegistry.register("declare_war", ["Military Command"])  # MilitaryInterface
# CommandRegistry.register("levy_tax", ["Taxation"])  # EconomicInterface
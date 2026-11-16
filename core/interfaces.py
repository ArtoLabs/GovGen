"""Role interfaces: what each kind of role can research and do.

Interfaces never ask for input. They describe their options; the engine turns those into
actions and a controller (human menu, NPC, later a network client or Unreal agent) chooses.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional
from core.command_registry import CommandRegistry
from world.player import Player
from innovations.innovation_map import ROLE_INNOVATION_MAP
from utils.messages import Messages


def unlock_note(innovation_name: str) -> str:
    """'  * opens Stone Age, Sacred Chiefdom, Hunter' for innovations that unlock an age, a government, an
    occupation, a recipe or a task."""
    from innovations.innovation import AGES
    from core.government_types import GOVERNMENT_TYPES
    from innovations.innovation import ALL_INNOVATIONS, AGES_BY_KEY
    unlocks = []
    for a in AGES:
        if innovation_name in a.requires:
            forms = [GOVERNMENT_TYPES[k].name for k in a.government_on_arrival]
            unlocks.append(f"{a.name} (the government becomes a {forms[-1]}"
                           + (f", or a {' or '.join(forms[:-1])} if its research is done first" if forms[1:] else "")
                           + ")" if forms else a.name)
    innov = ALL_INNOVATIONS.get(innovation_name)
    for g in GOVERNMENT_TYPES.values():
        if innovation_name not in g.requires:
            continue
        age = AGES_BY_KEY[g.age]
        if innov and innov.age_index < age.index and g.key in age.government_on_arrival[:-1]:
            unlocks.append(f"{g.name} (the society becomes one on entering the {age.name})")
        else:
            unlocks.append(f"{g.name} (a reform within the {age.name})")
    from core.occupations import OCCUPATIONS
    from core.work import opened_by
    unlocks += [o.name for o in OCCUPATIONS.values() if innovation_name in o.requires]
    unlocks += opened_by(innovation_name)
    return f"  * opens {', '.join(unlocks)}" if unlocks else ""


@dataclass(frozen=True)
class RoleCommand:
    key: str
    description: str
    text_prompt: str   # what to ask the actor for (law name, target, ...)
    outcome: str       # message template with {player} and {text}


# Flavor commands. They have no game effect yet; each is a hook for future systems.
ROLE_COMMANDS: Dict[str, List[RoleCommand]] = {
    "legislative": [RoleCommand("propose_law", "Propose a new law", "Name of the law", "{player} proposes the law '{text}'.")],
    "judicial": [
        RoleCommand("interpret_law", "Interpret an existing law", "Law to interpret", "{player} interprets the law '{text}'."),
        RoleCommand("resolve_dispute", "Resolve a dispute between parties", "Describe the dispute", "{player} resolves a dispute: {text}."),
    ],
    "military": [RoleCommand("declare_war", "Declare war on another group", "Group to declare war on", "{player} declares war on {text}.")],
    "intelligence": [
        RoleCommand("gather_info", "Gather information on a target", "Target", "{player} gathers information on {text}."),
        RoleCommand("conduct_espionage", "Conduct covert espionage", "Target", "{player} conducts espionage against {text}."),
    ],
    "economic": [
        RoleCommand("levy_tax", "Levy a tax on the population", "Tax amount", "{player} levies a tax of {text}."),
        RoleCommand("promote_trade", "Promote trade with other groups", "Trade partner", "{player} promotes trade with {text}."),
    ],
    "infrastructure": [RoleCommand("build_project", "Start a new infrastructure project", "Project name", "{player} starts building {text}.")],
    "religious": [RoleCommand("hold_ceremony", "Conduct a religious ceremony", "Ceremony name", "{player} holds the ceremony '{text}'.")],
    "civic_representation": [RoleCommand("represent_people", "Represent the people's interests", "Issue", "{player} speaks for the people on: {text}.")],
}


class RoleInterface:
    def __init__(self, government: 'core.government.Government', role_key: str):
        self.role_key = role_key
        self.government = government

    @property
    def name(self) -> str:
        return self.role_key.replace("_", " ").capitalize()

    def available_commands(self) -> List[RoleCommand]:
        discovered = self.government.innovation_pool.discovered
        return [c for c in ROLE_COMMANDS.get(self.role_key, [])
                if CommandRegistry.is_command_available(c.key, discovered)]

    def command(self, key: str) -> Optional[RoleCommand]:
        return next((c for c in self.available_commands() if c.key == key), None)

    def research_options(self) -> List['innovations.innovation.Innovation']:
        discovered = self.government.innovation_pool.discovered
        return [i for i in ROLE_INNOVATION_MAP.get(self.role_key, [])
                if i.name not in discovered and i.name not in self.government.research_queue
                and i.is_discoverable(discovered)]

    def perform(self, command_key: str, player: Player, text: str, reason: str = None) -> bool:
        command = self.command(command_key)
        if command is None:
            Messages.add(f"Command '{command_key}' is not available.", important=False)
            return False
        Messages.add(command.outcome.format(player=player.name, text=text or "something") + " (no effect yet)",
                     important=False, reason=reason)
        return True


# One class per interface, kept so roles_config can name them.
class LeadershipInterface(RoleInterface):
    def __init__(self, government): super().__init__(government, "leadership")

class LegislativeInterface(RoleInterface):
    def __init__(self, government): super().__init__(government, "legislative")

class JudicialInterface(RoleInterface):
    def __init__(self, government): super().__init__(government, "judicial")

class MilitaryInterface(RoleInterface):
    def __init__(self, government): super().__init__(government, "military")

class IntelligenceInterface(RoleInterface):
    def __init__(self, government): super().__init__(government, "intelligence")

class EconomicInterface(RoleInterface):
    def __init__(self, government): super().__init__(government, "economic")

class InfrastructureInterface(RoleInterface):
    def __init__(self, government): super().__init__(government, "infrastructure")

class ReligiousInterface(RoleInterface):
    def __init__(self, government): super().__init__(government, "religious")

class CivicRepresentationInterface(RoleInterface):
    def __init__(self, government): super().__init__(government, "civic_representation")


ROLE_INTERFACES: Dict[str, RoleInterface] = {}


def initialize_interfaces(government: 'core.government.Government') -> None:
    """Create one interface per role for this government (replacing any from an earlier game)."""
    from core.roles_config import ROLE_CONFIGS
    ROLE_INTERFACES.clear()
    ROLE_INTERFACES.update({
        config.key: config.interface_class(government)
        for config in ROLE_CONFIGS.values()
        if config.interface_class
    })


def get_interface(role_key: str) -> Optional[RoleInterface]:
    return ROLE_INTERFACES.get(role_key)

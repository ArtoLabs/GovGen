from typing import Dict, List, Set
from role import Role
from interfaces import RoleInterface
from player import Player
from selection import SelectionMethod

class GovernmentType:
    def __init__(self, name: str, role_mappings: Dict[str, List[str]], required_innovations: Set[str], title_requirements: Dict[str, Dict[str, any]]):
        self.name = name
        self.role_mappings = role_mappings
        self.required_innovations = required_innovations
        self.title_requirements = title_requirements

    def is_available(self, discovered: Set[str]) -> bool:
        return all(req in discovered for req in self.required_innovations)

    def get_accessible_interfaces(self, player: Player, assignments: Dict[str, List[Player]]) -> List[RoleInterface]:
        from interfaces import get_interface
        interfaces = set()
        for titled_role, holders in assignments.items():
            if player in holders and titled_role in self.role_mappings:
                for base_role in self.role_mappings[titled_role]:
                    interface = get_interface(base_role)
                    if interface:
                        interfaces.add(interface)
        return list(interfaces)

    def is_valid_selection_method(self, role_id: str, method_key: str, discovered: Set[str]) -> bool:
        return role_id in self.role_mappings and method_key in {"divine_appointment", "election", "hereditary"}

    def get_titled_role(self, role_key: str) -> str:
        if role_key in self.role_mappings:
            return role_key
        raise KeyError(f"Titled role '{role_key}' not found in {self.name} government type")

GOVERNMENT_TYPES = {
    "tribal": GovernmentType(
        name="Tribal",
        role_mappings={
            "chieftain": ["leadership", "legislative", "judicial", "economic", "infrastructure"],
            "head_warrior": ["military", "intelligence"],
            "shaman": ["religious", "civic_representation"]
        },
        required_innovations={"Tribalism"},
        title_requirements={
            "chieftain": {"innovations": ["Chieftainship"], "max_holders": 1},
            "head_warrior": {"innovations": ["Hierarchy", "Military Command"], "max_holders": 2},
            "shaman": {"innovations": ["Divine Right"], "max_holders": 1}
        }
    ),
}

def get_government_type(name: str) -> 'GovernmentType':
    return GOVERNMENT_TYPES.get(name.lower())

def get_available_government_types(discovered: Set[str]) -> List[GovernmentType]:
    return [gov_type for gov_type in GOVERNMENT_TYPES.values() if gov_type.is_available(discovered)]
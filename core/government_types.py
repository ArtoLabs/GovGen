from typing import Dict, List, Set
from core.interfaces import RoleInterface
from world.player import Player

class GovernmentType:
    def __init__(self, name: str, role_mappings: Dict[str, List[str]], required_innovations: Set[str], title_requirements: Dict[str, Dict[str, any]]):
        self.name = name
        self.role_mappings = role_mappings
        self.required_innovations = required_innovations
        self.title_requirements = title_requirements

    def is_available(self, discovered: Set[str]) -> bool:
        return all(req in discovered for req in self.required_innovations)

    def get_accessible_interfaces(self, player: Player, assignments: Dict[str, List[Player]]) -> List[RoleInterface]:
        from core.interfaces import get_interface
        interfaces = set()
        for titled_role, holders in assignments.items():
            if player in holders and titled_role in self.role_mappings:
                for base_role in self.role_mappings[titled_role]:
                    interface = get_interface(base_role)
                    if interface:
                        interfaces.add(interface)
        return list(interfaces)

    def is_valid_selection_method(self, role_id: str, method_key: str, discovered: Set[str]) -> bool:
        return role_id in self.role_mappings and method_key == self.title_requirements.get(role_id, {}).get("selection_method")

GOVERNMENT_TYPES = {
    "tribal": GovernmentType(
        name="Tribal",
        role_mappings={
            "Elder": ["civic_representation", "judicial"],
            "Clan Leader": ["leadership", "legislative", "infrastructure"],
            "Chieftain": ["leadership", "legislative", "judicial", "economic", "infrastructure"],
            "Head Warrior": ["military", "intelligence"],
            "Shaman": ["religious", "civic_representation", "intelligence"],
            "Warrior": [],
            "Guardian-Enforcer": [],
            "Priest": ["religious", "civic_representation", "legislative"],
            "Initiate": [],
            "Steward": ["civic_representation", "economic"],
            "Grain Keeper": ["civic_representation", "infrastructure"],
            "Hereditary Chieftain": ["leadership", "legislative", "judicial", "economic", "infrastructure"],
            "Outcast": [],
        },
        required_innovations={"Tribalism"},
        title_requirements={
            "Elder": {
                "innovations": ["Tribalism"],
                "max_holders": 2,
                "selection_method": "voting",
                "voting_system": "first_past_the_post",
                "nomination_method": "appointed",
                "appointer": "anyone",
                "force_vote": True,
                "nomination_control": "time_based",
                "nomination_duration": 1
            },
            "Clan Leader": {
                "innovations": ["Tribalism"],
                "max_holders": 2,
                "selection_method": "appointment",
                "appointer": "Elder",
                "force_vote": True,
            },
            "Chieftain": {
                "innovations": ["Chieftainship"],
                "max_holders": 1,
                "selection_method": "voting",
                "voting_system": "first_past_the_post",
                "nomination_method": "appointed",
                "appointer": "Elder",
                "force_vote": True,
                "nomination_control": "command_based",
                "nomination_starter_role": "Elder",
                "nomination_closer_role": "Clan Leader",
            },
            "Head Warrior": {"innovations": ["Hierarchy", "Warrior Command"], "max_holders": 2, "selection_method": "appointment", "appointer": "Chieftain"},
            "Shaman": {"innovations": ["Divine Right"], "max_holders": 1, "selection_method": "appointment", "appointer": "Chieftain"},
            "Warrior": {"innovations": ["Warriors"], "max_holders": 500, "selection_method": "appointment", "appointer": "Head Warrior"},
            "Guardian-Enforcer": {"innovations": ["Chieftainship", "Centralized Authority", "Distribution"], "max_holders": 500, "selection_method": "appointment", "appointer": "Chieftain"},
            "Priest": {"innovations": ["Religion"], "max_holders": 10, "selection_method": "divine_appointment"},
            "Initiate": {"innovations": ["Religion"], "max_holders": 100, "selection_method": "appointment", "appointer": "Priest"},
            "Steward": {"innovations": ["Chieftainship", "Centralized Authority"], "max_holders": 1, "selection_method": "appointment", "appointer": "Chieftain"},
            "Grain Keeper": {"innovations": ["Chieftainship", "Centralized Authority"], "max_holders": 1, "selection_method": "appointment", "appointer": "Chieftain"},
            "Hereditary Chieftain": {"innovations": ["Hereditary Rule"], "max_holders": 1, "selection_method": "divine_appointment"},
            "Outcast": {"innovations": ["Ostracism"], "max_holders": 500, "selection_method": "appointment", "appointer": "Chieftain"},
        },
    ),
}

def get_government_type(name: str) -> 'GovernmentType':
    return GOVERNMENT_TYPES.get(name.lower())

def get_available_government_types(discovered: Set[str]) -> List[GovernmentType]:
    return [gov_type for gov_type in GOVERNMENT_TYPES.values() if gov_type.is_available(discovered)]
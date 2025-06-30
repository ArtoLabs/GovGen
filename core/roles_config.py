from typing import List, Optional
from dataclasses import dataclass, asdict
import json
from core.interfaces import (
    LeadershipInterface,
    LegislativeInterface,
    JudicialInterface,
    MilitaryInterface,
    IntelligenceInterface,
    EconomicInterface,
    InfrastructureInterface,
    ReligiousInterface,
    CivicRepresentationInterface
)

@dataclass
class RoleConfig:
    key: str
    name: str
    description: str
    interface_tag: str
    selection_required: bool
    max_holders: int
    innovation_points: int
    interface_class: Optional['type[core.interfaces.RoleInterface]']

def get_role_configs():
    """Define role configurations."""
    return {
        "leadership": RoleConfig(
            key="leadership",
            name="Leadership Role",
            description="Holds supreme executive power and authority over the government.",
            interface_tag="leadership_panel",
            selection_required=True,
            max_holders=1,
            innovation_points=5,
            interface_class=LeadershipInterface
        ),
        "legislative": RoleConfig(
            key="legislative",
            name="Legislative Role",
            description="Responsible for drafting and enacting laws.",
            interface_tag="legislative_panel",
            selection_required=True,
            max_holders=2,
            innovation_points=3,
            interface_class=LegislativeInterface
        ),
        "judicial": RoleConfig(
            key="judicial",
            name="Judicial Role",
            description="Interprets laws and resolves disputes.",
            interface_tag="judicial_panel",
            selection_required=True,
            max_holders=2,
            innovation_points=3,
            interface_class=JudicialInterface
        ),
        "military": RoleConfig(
            key="military",
            name="Military Role",
            description="Oversees defense and military operations.",
            interface_tag="military_panel",
            selection_required=True,
            max_holders=2,
            innovation_points=2,
            interface_class=MilitaryInterface
        ),
        "intelligence": RoleConfig(
            key="intelligence",
            name="Intelligence Role",
            description="Manages espionage and information gathering.",
            interface_tag="intelligence_panel",
            selection_required=True,
            max_holders=1,
            innovation_points=4,
            interface_class=IntelligenceInterface
        ),
        "economic": RoleConfig(
            key="economic",
            name="Economic Role",
            description="Manages trade, resources, and economic policy.",
            interface_tag="economic_panel",
            selection_required=True,
            max_holders=2,
            innovation_points=3,
            interface_class=EconomicInterface
        ),
        "infrastructure": RoleConfig(
            key="infrastructure",
            name="Infrastructure Role",
            description="Oversees public works and infrastructure development.",
            interface_tag="infrastructure_panel",
            selection_required=True,
            max_holders=2,
            innovation_points=2,
            interface_class=InfrastructureInterface
        ),
        "religious": RoleConfig(
            key="religious",
            name="Religious Role",
            description="Guides spiritual and religious affairs.",
            interface_tag="religious_panel",
            selection_required=True,
            max_holders=1,
            innovation_points=2,
            interface_class=ReligiousInterface
        ),
        "civic_representation": RoleConfig(
            key="civic_representation",
            name="Civic Representation Role",
            description="Represents the interests of the population.",
            interface_tag="civic_representation_panel",
            selection_required=True,
            max_holders=2,
            innovation_points=3,
            interface_class=CivicRepresentationInterface
        ),
    }

ROLE_CONFIGS = get_role_configs()

def validate_configs():
    """Validate role configurations for consistency."""
    for key, config in ROLE_CONFIGS.items():
        if config.max_holders < 1:
            raise ValueError(f"Invalid max_holders '{config.max_holders}' for role '{key}'")
        if config.innovation_points < 0:
            raise ValueError(f"Invalid innovation_points '{config.innovation_points}' for role '{key}'")

validate_configs()

def save_configs_to_json(filename: str):
    """Save ROLE_CONFIGS to a JSON file."""
    configs = {
        key: {
            k: v for k, v in asdict(config).items()
            if k != 'interface_class'
        }
        for key, config in ROLE_CONFIGS.items()
    }
    with open(filename, 'w') as f:
        json.dump(configs, f, indent=2)

def load_configs_from_json(filename: str):
    """Load ROLE_CONFIGS from a JSON file."""
    with open(filename, 'r') as f:
        data = json.load(f)
    interface_map = {
        'leadership': LeadershipInterface,
        'legislative': LegislativeInterface,
        'judicial': JudicialInterface,
        'military': MilitaryInterface,
        'intelligence': IntelligenceInterface,
        'economic': EconomicInterface,
        'infrastructure': InfrastructureInterface,
        'religious': ReligiousInterface,
        'civic_representation': CivicRepresentationInterface
    }
    configs = {}
    for key, config_data in data.items():
        configs[key] = RoleConfig(
            **config_data,
            interface_class=interface_map.get(config_data['key'])
        )
    return configs
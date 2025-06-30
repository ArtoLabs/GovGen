from typing import Optional, List
from core.roles_config import ROLE_CONFIGS

class Role:
    def __init__(
        self,
        key: str,
        name: str,
        description: str,
        interface_tag: str,
        title: str = None,
        selection_required: bool = True
    ):
        self.key = key
        self.name = name
        self.description = description
        self.interface_tag = interface_tag
        self.title = title or None
        self.selection_required = selection_required

    def __repr__(self):
        return f"<Role {self.name} (Key: {self.key})>"

def get_role(key: str) -> Optional[Role]:
    """Fetch a role by its key."""
    config = ROLE_CONFIGS.get(key)
    if not config:
        return None
    return Role(
        key=config.key,
        name=config.name,
        description=config.description,
        interface_tag=config.interface_tag,
        selection_required=config.selection_required
    )

def get_unlocked_roles(owned_innovations: set[str]) -> List[Role]:
    """Get all roles, as they have no innovation requirements."""
    return [get_role(key) for key in ROLE_CONFIGS if get_role(key)]
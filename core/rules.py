from typing import Dict, List, Set, Tuple
from role import get_role
from player import Player
from government_types import GovernmentType
from roles_config import ROLE_CONFIGS


def get_role_limits() -> Dict[str, int]:
    return {config.key: config.max_holders for config in ROLE_CONFIGS.values()}


def is_role_unlocked(role_id: str, discovered: Set[str]) -> Tuple[bool, List[str]]:
    role = get_role(role_id)
    if not role:
        return False, [f"Key '{role_id}' does not exist"]
    return True, []


def can_assign_role(role_id: str, player: Player, assignments: Dict[str, List[Player]], discovered: Set[str],
                    government_type: GovernmentType) -> Tuple[bool, List[str]]:
    reasons = []

    if role_id in government_type.role_mappings:
        title_reqs = government_type.title_requirements.get(role_id, {})
        missing = [req for req in title_reqs.get("innovations", []) if req not in discovered]
        if missing:
            reasons.append(f"Title '{role_id}' requires missing innovations: {', '.join(missing)}")
            return False, reasons
        max_holders = title_reqs.get("max_holders", 1)
        current_holders = len(assignments.get(role_id, []))
        if current_holders >= max_holders:
            reasons.append(f"Maximum holders ({max_holders}) for '{role_id}' already reached")
            return False, reasons
        any_valid = False
        for base_role in government_type.role_mappings[role_id]:
            unlocked, base_reasons = is_role_unlocked(base_role, discovered)
            if unlocked:
                any_valid = True
            else:
                reasons.extend(base_reasons)
        if not any_valid:
            reasons.append(f"No base roles for '{role_id}' are valid")
            return False, reasons
        return True, []

    unlocked, base_reasons = is_role_unlocked(role_id, discovered)
    if not unlocked:
        reasons.extend(base_reasons)
        return False, reasons
    role_limits = get_role_limits()
    max_holders = role_limits.get(role_id, 1)
    current_holders = len(assignments.get(role_id, []))
    if current_holders >= max_holders:
        reasons.append(f"Maximum holders ({max_holders}) for '{role_id}' already reached")
        return False, reasons
    return True, []
"""Eligibility rules shared by every way of filling an office."""
from typing import List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from core.government import Government
    from world.player import Player


def can_hold_office(government: 'Government', office_name: str, player: 'Player',
                    ignore_seat_limit: bool = False) -> Tuple[bool, List[str]]:
    gov_type = government.government_type
    office = gov_type.offices.get(office_name)
    if office is None:
        return False, [f"'{office_name}' is not an office in a {gov_type.name} government"]
    missing = [req for req in office.requires if req not in government.innovation_pool.discovered]
    if missing:
        return False, [f"'{office_name}' requires {', '.join(missing)}"]
    if government.has_effect(player, "cannot_hold_office"):
        return False, [f"{player.name} may not hold office"]
    if not government.of_age(player, "politics"):
        return False, [f"{player.name} is too young to hold office"]
    holders = government.get_role_holders(office_name)
    if player in holders:
        return False, [f"{player.name} already holds '{office_name}'"]
    if not ignore_seat_limit and len(holders) >= office.seats:
        return False, [f"all {office.seats} '{office_name}' seat(s) are filled"]
    held = government.offices_of(player)
    if len(held) >= gov_type.max_offices_per_player:
        return False, [f"{player.name} already holds {', '.join(held)} (limit {gov_type.max_offices_per_player})"]
    return True, []

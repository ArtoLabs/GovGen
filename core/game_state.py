from typing import List, Optional, TYPE_CHECKING
from world.player import Player

if TYPE_CHECKING:
    from core.government import Government
    from core.voting_manager import VotingManager

class GameState:
    """Shared state the managers read: the clock, players, government and voting manager."""

    def __init__(self, players: List[Player], government: Optional['Government'] = None,
                 voting_manager: Optional['VotingManager'] = None):
        self.clock = 0  # game hours since the start (see core/calendar.py)
        self.players = players
        self.government = government
        self.voting_manager = voting_manager

    @property
    def current_year(self) -> int:
        from core.calendar import year_of
        return year_of(self.clock)

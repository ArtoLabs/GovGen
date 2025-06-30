from abc import ABC, abstractmethod
from typing import Dict, List, Set, Optional
from world.player import Player
from core.government import Government
from utils.messages import Messages
import random
from collections import defaultdict

class VotingSystem(ABC):
    def __init__(
        self,
        role: str,
        force_vote: bool = True,
        nomination_control: str = "time_based",
        nomination_duration: int = 1,
        nomination_starter_role: Optional[str] = None,
        nomination_closer_role: Optional[str] = None,
        seat_number: Optional[int] = None,
    ):
        self.seat_number = seat_number
        self.role = role
        self.force_vote = force_vote
        self.nomination_control = nomination_control  # "time_based" or "command_based"
        self.nomination_duration = nomination_duration  # Years for time-based
        self.nomination_starter_role = nomination_starter_role
        self.nomination_closer_role = nomination_closer_role
        self.nomination_method = "open"
        self.government: Optional[Government] = None
        self.nominations: Dict[str, List[str]] = {role: []}
        self.votes: Dict[Player, str] = {}
        self.voting_active = False
        self.candidates: List[str] = []
        self.players: List[Player] = []
        self.is_nomination_open = False
        self.nomination_start_year: Optional[int] = None
        self.voting_start_year: Optional[int] = None  # Track when voting starts

    def set_nomination_method(self, method: str):
        self.nomination_method = method

    def start_nominations(self, current_year: int):
        """Start the nomination phase."""
        if self.is_nomination_open:
            raise ValueError(f"Nominations for {self.role} are already open")
        if self.nomination_control == "command_based" and not self.nomination_starter_role:
            raise ValueError(f"No starter role defined for {self.role}")
        self.is_nomination_open = True
        self.nomination_start_year = current_year
        self.nominations[self.role] = []

    def close_nominations(self):
        """Close the nomination phase and prepare for voting or direct assignment."""
        if not self.is_nomination_open:
            raise ValueError(f"Nominations for {self.role} are not open")
        self.is_nomination_open = False
        self.nomination_start_year = None

    def is_nomination_period_over(self, current_year: int) -> bool:
        """Check if the time-based nomination period has ended."""
        if self.nomination_control != "time_based" or not self.is_nomination_open:
            return False
        if self.nomination_start_year is None:
            return False
        return (current_year - self.nomination_start_year) >= self.nomination_duration

    def nominate(self, player: Player, candidate_name: str):
        if not self.is_nomination_open:
            raise ValueError(f"Nominations for {self.role} are not open")
        if self.voting_active:
            raise ValueError("Cannot nominate while voting is active")
        if self.nomination_method == "self_appointed" and player.name != candidate_name:
            raise ValueError("Only self-nomination is allowed")
        if self.nomination_method == "appointed" and not self.can_appoint(player, self.role):
            raise ValueError(f"{player.name} is not authorized to nominate for {self.role}")
        if candidate_name in self.nominations[self.role]:
            raise ValueError(f"{candidate_name} is already nominated for {self.role}")
        if candidate_name not in [p.name for p in self.government.players]:
            raise ValueError(f"{candidate_name} is not a valid player")
        if self.government.is_player_assigned(candidate_name, self.role):
            raise ValueError(f"{candidate_name} is already assigned to {self.role}")
        self.nominations[self.role].append(candidate_name)

    def can_start_nominations(self, player: Player) -> bool:
        """Check if a player can start nominations (for command-based)."""
        if self.nomination_control != "command_based" or not self.nomination_starter_role:
            return False
        return player in self.government.assignments.get(self.nomination_starter_role, [])

    def can_close_nominations(self, player: Player) -> bool:
        """Check if a player can close nominations (for command-based)."""
        if self.nomination_control != "command_based" or not self.nomination_closer_role:
            return False
        return player in self.government.assignments.get(self.nomination_closer_role, [])

    def can_appoint(self, player: Player, role: str) -> bool:
        """Check if a player can appoint nominees for a role."""
        if self.nomination_method != "appointed":
            return False
        appointer = self.government.government_type.title_requirements.get(role, {}).get("appointer")
        if appointer == "anyone":
            return True
        if not appointer:
            return False
        return player in self.government.assignments.get(appointer, [])

    def can_end_turn(self, player: Player) -> bool:
        return not self.force_vote or player in self.votes

    def start_vote(self, players: List[Player], candidates: List[str]):
        self.voting_active = True
        self.candidates = candidates
        self.players = players
        self.voting_start_year = self.government.sim.current_year  # Set voting start year

    def is_voting_active(self) -> bool:
        return self.voting_active

    @abstractmethod
    def vote(self, player: Player, vote_data: str):
        pass

    @abstractmethod
    def get_result(self) -> str:
        pass

    @abstractmethod
    def is_complete(self) -> bool:
        pass

class FirstPastThePost(VotingSystem):
    def __init__(
        self,
        role: str,
        force_vote: bool = True,
        nomination_control: str = "time_based",
        nomination_duration: int = 1,
        nomination_starter_role: Optional[str] = None,
        nomination_closer_role: Optional[str] = None,
        seat_number: Optional[int] = None,
    ):
        super().__init__(
            role,
            force_vote,
            nomination_control,
            nomination_duration,
            nomination_starter_role,
            nomination_closer_role,
            seat_number
        )

    def vote(self, player: Player, candidate: str):
        if not self.voting_active:
            raise ValueError("Voting is not active")
        if candidate not in self.candidates:
            raise ValueError(f"{candidate} is not a valid candidate")
        if player in self.votes:
            raise ValueError(f"{player.name} has already voted")
        self.votes[player] = candidate

    def is_complete(self, sim: 'core.main.Simulation') -> bool:
        # Voting completes when the year advances past the voting start year
        return self.voting_start_year is not None and sim.current_year > self.voting_start_year

    def get_result(self) -> str:
        if not self.votes:
            return random.choice(self.candidates)
        vote_counts = {}
        for candidate in self.candidates:
            vote_counts[candidate] = sum(1 for v in self.votes.values() if v == candidate)
        max_votes = max(vote_counts.values())
        winners = [c for c, v in vote_counts.items() if v == max_votes]
        return random.choice(winners)

class RankedChoiceVoting(VotingSystem):
    def __init__(
        self,
        role: str,
        force_vote: bool = True,
        nomination_control: str = "time_based",
        nomination_duration: int = 1,
        nomination_starter_role: Optional[str] = None,
        nomination_closer_role: Optional[str] = None,
        seat_number: Optional[int] = None,
    ):
        super().__init__(
            role,
            force_vote,
            nomination_control,
            nomination_duration,
            nomination_starter_role,
            nomination_closer_role,
            seat_number
        )
        self.votes: Dict[Player, str] = {}

    def vote(self, player: Player, preferences: List[str]):
        if not self.voting_active:
            raise ValueError("Voting is not active")
        if len(preferences) != len(self.candidates):
            raise ValueError("Invalid number of preferences")
        if sorted(preferences) != sorted(self.candidates):
            raise ValueError("Preferences must include all candidates")
        if player in self.votes:
            raise ValueError(f"{player.name} has already voted")
        self.votes[player] = ",".join(preferences)

    def is_complete(self) -> bool:
        return len(self.votes) == len(self.players) or (not self.force_vote and len(self.votes) > 0)

    def get_result(self) -> str:
        vote_counts = defaultdict(int)
        eliminated = set()
        preferences = {p: v.split(",") for p, v in self.votes.items()}
        while True:
            vote_counts.clear()
            for player, prefs in preferences.items():
                for candidate in prefs:
                    if candidate not in eliminated:
                        vote_counts[candidate] += 1
                        break
            if not vote_counts:
                return random.choice(self.candidates)
            max_votes = max(vote_counts.values())
            if max_votes > sum(vote_counts.values()) / 2:
                return max(vote_counts, key=vote_counts.get)
            min_votes = min(vote_counts.values())
            min_candidates = [c for c, v in vote_counts.items() if v == min_votes]
            eliminated.add(random.choice(min_candidates))

class TwoRoundRunoffVoting(VotingSystem):
    def __init__(
        self,
        role: str,
        force_vote: bool = True,
        nomination_control: str = "time_based",
        nomination_duration: int = 1,
        nomination_starter_role: Optional[str] = None,
        nomination_closer_role: Optional[str] = None,
        seat_number: Optional[int] = None,
    ):
        super().__init__(
            role,
            force_vote,
            nomination_control,
            nomination_duration,
            nomination_starter_role,
            nomination_closer_role,
            seat_number
        )
        self.finalists: List[str] = []
        self.first_round = True

    def vote(self, player: Player, candidate: str):
        if not self.voting_active:
            raise ValueError("Voting is not active")
        if candidate not in (self.finalists or self.candidates):
            raise ValueError(f"{candidate} is not a valid candidate")
        if player in self.votes:
            raise ValueError(f"{player.name} has already voted")
        self.votes[player] = candidate

    def is_complete(self) -> bool:
        return len(self.votes) == len(self.players) or (not self.force_vote and len(self.votes) > 0)

    def get_result(self) -> str:
        if not self.votes:
            return random.choice(self.finalists or self.candidates)
        vote_counts = {}
        for candidate in (self.finalists or self.candidates):
            vote_counts[candidate] = sum(1 for v in self.votes.values() if v == candidate)
        max_votes = max(vote_counts.values())
        if max_votes > sum(vote_counts.values()) / 2:
            return max(vote_counts, key=vote_counts.get)
        if not self.finalists:
            top_two = sorted(vote_counts, key=vote_counts.get, reverse=True)[:2]
            self.finalists = top_two
            self.first_round = False
            self.votes.clear()
            return "RUNOFF"
        winners = [c for c, v in vote_counts.items() if v == max_votes]
        return random.choice(winners)

class VotingInterface(ABC):
    def __init__(self, voting_system: VotingSystem):
        self.voting_system = voting_system

    @abstractmethod
    def display_vote_options(self) -> str:
        pass

    @abstractmethod
    def handle_vote(self, player: Player, vote_data: str):
        pass

class FirstPastThePostInterface(VotingInterface):
    def display_vote_options(self) -> str:
        return f"Vote for one: {', '.join(self.voting_system.candidates)}"

    def handle_vote(self, player: Player, vote_data: str):
        self.voting_system.vote(player, vote_data)

class RankedChoiceInterface(VotingInterface):
    def display_vote_options(self) -> str:
        return f"Rank candidates (comma-separated): {', '.join(self.voting_system.candidates)}"

    def handle_vote(self, player: Player, vote_data: str):
        preferences = [x.strip() for x in vote_data.split(",")]
        self.voting_system.vote(player, preferences)

class TwoRoundRunoffInterface(VotingInterface):
    def display_vote_options(self) -> str:
        candidates = self.voting_system.finalists or self.voting_system.candidates
        return f"Vote for one: {', '.join(candidates)}"

    def handle_vote(self, player: Player, vote_data: str):
        self.voting_system.vote(player, vote_data)
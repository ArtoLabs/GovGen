from typing import List, Dict
from core.voting import VotingSystem, FirstPastThePost, RankedChoiceVoting, TwoRoundRunoffVoting, VotingInterface, FirstPastThePostInterface, RankedChoiceInterface, TwoRoundRunoffInterface
from utils.messages import Messages
from utils.logging_config import logger

class VotingManager:
    def __init__(self, simulation: 'core.main.Simulation'):
        self.sim = simulation
        self.active_votes: List[VotingSystem] = []
        self.vote_interfaces: Dict[str, VotingInterface] = {}
        self.queued_seats: Dict[str, List[int]] = {}  # Role -> List of seat numbers to fill

    def initiate_votes(self):
        """Initialize votes for vacant roles, queuing seats sequentially."""
        logger.debug(f"Initiating votes. Current assignments: {self.sim.government.assignments}")
        VOTING_SYSTEMS = {
            "first_past_the_post": FirstPastThePost,
            "ranked_choice": RankedChoiceVoting,
            "two_round_runoff": TwoRoundRunoffVoting
        }
        discovered = self.sim.government.innovation_pool.discovered
        for role, reqs in self.sim.government.government_type.title_requirements.items():
            selection_method = reqs.get("selection_method")
            max_holders = reqs.get("max_holders", 1)
            current_holders = len(self.sim.government.assignments.get(role, []))
            active_votes_for_role = sum(1 for v in self.active_votes if v.role == role)
            vacant_seats = max_holders - current_holders - active_votes_for_role
            required_innovations = set(reqs.get("innovations", []))
            logger.debug(f"Checking role {role}: selection_method={selection_method}, "
                         f"current_holders={current_holders}, max_holders={max_holders}, "
                         f"active_votes={active_votes_for_role}, vacant_seats={vacant_seats}, "
                         f"innovations={required_innovations}, discovered={discovered}")
            if selection_method == "voting" and vacant_seats > 0 and required_innovations.issubset(discovered):
                # Queue all vacant seats
                self.queued_seats.setdefault(role, []).extend(
                    range(current_holders + active_votes_for_role + 1, max_holders + 1))
                # Start nominations for the first queued seat, if any
                if self.queued_seats[role] and not any(
                        v.role == role and v.is_nomination_open for v in self.active_votes):
                    seat = self.queued_seats[role].pop(0)
                    nomination_method = reqs.get("nomination_method", "open")
                    voting_system_name = reqs.get("voting_system", "first_past_the_post")
                    force_vote = reqs.get("force_vote", False)
                    nomination_control = reqs.get("nomination_control", "time_based")
                    nomination_duration = reqs.get("nomination_duration", 1)  # Added to define nomination_duration
                    nomination_starter_role = reqs.get("nomination_starter_role")
                    nomination_closer_role = reqs.get("nomination_closer_role")
                    vote = VOTING_SYSTEMS[voting_system_name](
                        role,
                        force_vote,
                        nomination_control,
                        nomination_duration,
                        nomination_starter_role,
                        nomination_closer_role,
                        seat_number=seat
                    )
                    vote.government = self.sim.government
                    vote.set_nomination_method(nomination_method)
                    self.active_votes.append(vote)
                    if nomination_control == "time_based":
                        vote.start_nominations(self.sim.current_year)
                        logger.debug(f"Started time-based nominations for {role} (seat {seat})")
                    else:
                        logger.debug(f"Queued command-based nominations for {role} (seat {seat})")
            else:
                if selection_method != "voting":
                    logger.debug(f"Skipping {role}: selection_method is {selection_method}")
                elif current_holders >= max_holders:
                    logger.debug(f"Skipping {role}: already has enough holders")
                elif not required_innovations.issubset(discovered):
                    logger.debug(f"Skipping {role}: required innovations not discovered")

    def start_vote(self, role: str, voting_system: VotingSystem):
        """Start the voting phase for a role."""
        self.vote_interfaces[role] = {
            FirstPastThePost: FirstPastThePostInterface,
            RankedChoiceVoting: RankedChoiceInterface,
            TwoRoundRunoffVoting: TwoRoundRunoffInterface
        }[type(voting_system)](voting_system)
        logger.debug(f"Started voting for {role} with candidates {voting_system.candidates}")
        Messages.add(f"Voting started for {role} with candidates {voting_system.candidates}")

    def process_votes(self):
        """Process active votes and nomination phases."""
        logger.debug(f"Processing votes in year {self.sim.current_year}, player index {self.sim.current_player_index}")
        for vote in self.active_votes[:]:
            if vote.is_nomination_open:
                if vote.nomination_control == "time_based" and vote.is_nomination_period_over(self.sim.current_year):
                    vote.close_nominations()
                    logger.debug(f"Closed time-based nominations for {vote.role} (seat {vote.seat_number})")
            if not vote.is_nomination_open and not vote.is_voting_active():
                candidates = vote.nominations[vote.role]
                if len(candidates) == 1:
                    winner_name = candidates[0]
                    winner = next(p for p in self.sim.players if p.name == winner_name)
                    if self.sim.government.assign_role(vote.role, winner):
                        Messages.add(
                            f"{winner.name} elected as {vote.role} (seat {vote.seat_number}, single candidate)")
                        logger.debug(
                            f"Elected {winner.name} as {vote.role} (seat {vote.seat_number}, single candidate)")
                    else:
                        Messages.add(
                            f"Failed to assign {winner.name} as {vote.role} (seat {vote.seat_number}); restarting nominations")
                        logger.warning(f"Assignment failed for {winner.name} as {vote.role} seat {vote.seat_number}")
                        self.queued_seats.setdefault(vote.role, []).insert(0, vote.seat_number)
                    self.active_votes.remove(vote)
                    if vote.role in self.vote_interfaces:
                        del self.vote_interfaces[vote.role]
                    if self.queued_seats.get(vote.role):
                        self.initiate_votes()
                elif len(candidates) > 1:
                    vote.start_vote(self.sim.players, candidates)
                    self.start_vote(vote.role, vote)
                    logger.debug(
                        f"Started voting for {vote.role} (seat {vote.seat_number}) with candidates {vote.candidates}")
                elif len(candidates) == 0:
                    self.active_votes.remove(vote)
                    if vote.role in self.vote_interfaces:
                        del self.vote_interfaces[vote.role]
                    self.queued_seats.setdefault(vote.role, []).insert(0, vote.seat_number)
                    self.initiate_votes()
                    logger.debug(f"No candidates for {vote.role} (seat {vote.seat_number}), restarting nominations")
            if vote.is_voting_active() and vote.is_complete(self.sim):
                if isinstance(vote, TwoRoundRunoffVoting) and vote.get_result() == "RUNOFF":
                    vote.start_vote(self.sim.players, vote.finalists)
                    Messages.add(
                        f"Runoff voting started for {vote.role} (seat {vote.seat_number}) between {', '.join(vote.finalists)}")
                    logger.debug(
                        f"Started runoff voting for {vote.role} (seat {vote.seat_number}) with finalists {vote.finalists}")
                    continue
                winner_name = vote.get_result()
                winner = next(p for p in self.sim.players if p.name == winner_name)
                if self.sim.government.assign_role(vote.role, winner):
                    Messages.add(f"{winner.name} has been elected as {vote.role} (seat {vote.seat_number})")
                    logger.debug(f"Elected {winner.name} as {vote.role} (seat {vote.seat_number})")
                else:
                    Messages.add(
                        f"Failed to assign {winner.name} as {vote.role} (seat {vote.seat_number}); restarting nominations")
                    logger.warning(f"Assignment failed for {winner.name} as {vote.role} seat {vote.seat_number}")
                    self.queued_seats.setdefault(vote.role, []).insert(0, vote.seat_number)
                self.active_votes.remove(vote)
                if vote.role in self.vote_interfaces:
                    del self.vote_interfaces[vote.role]
                if self.queued_seats.get(vote.role):
                    self.initiate_votes()

    def handle_vote(self, role: str):
        """Handle a player's vote for a role."""
        interface = self.vote_interfaces.get(role)
        if not interface:
            Messages.add(f"No active vote for {role}")
            logger.info(f"No active vote for {role}")
            input("Press Enter to continue...")
            return
        print(interface.display_vote_options())
        vote_data = input("Enter your vote (e.g., 'Bob' or 'Bob,Cleo' for ranked choice): ").strip()
        try:
            interface.handle_vote(self.sim.players[self.sim.current_player_index], vote_data)
            Messages.add(f"{self.sim.players[self.sim.current_player_index].name} voted for {vote_data} in {role} election")
            logger.debug(f"{self.sim.players[self.sim.current_player_index].name} voted for {vote_data} in {role} election")
        except ValueError as e:
            print(f"Error: {e}")
            logger.error(f"Vote error for {role}: {e}")
            input("Press Enter to continue...")
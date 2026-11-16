from typing import List, Dict, Optional, Tuple, TYPE_CHECKING
from core.voting import (Ballot, VotingSystem, Motion, FirstPastThePost, RankedChoiceVoting, TwoRoundRunoffVoting,
                         ballot_from_dict)
from core.calendar import NOMINATION_HOURS, VOTING_HOURS, MOTION_HOURS, HOURS_PER_DAY, format_date
from core.government_types import VOTE_METHODS
from utils.messages import Messages
from utils.logging_config import logger
from core.game_state import GameState

if TYPE_CHECKING:
    from world.player import Player

VOTING_SYSTEMS = {
    "first_past_the_post": FirstPastThePost,
    "ranked_choice": RankedChoiceVoting,
    "two_round_runoff": TwoRoundRunoffVoting,
}


class VotingManager:
    """Runs elections for vote-selected offices and yes/no motions (removals, statuses)."""

    def __init__(self, game_state: GameState):
        self.game_state = game_state
        self.active_votes: List[Ballot] = []

    @property
    def government(self):
        return self.game_state.government

    @property
    def now(self) -> int:
        return self.game_state.clock

    def next_deadline(self):
        """Earliest moment a ballot's nomination or voting period closes (None if none open)."""
        deadlines = [d for d in (b.next_deadline() for b in self.active_votes) if d is not None]
        return min(deadlines) if deadlines else None

    def to_dict(self):
        return {"active_votes": [b.to_dict() for b in self.active_votes]}

    def load_state(self, data, player):
        self.active_votes = [ballot_from_dict(d, player) for d in data["active_votes"]]
        for b in self.elections():
            b.government = self.government

    def clear(self):
        self.active_votes.clear()

    def ballot(self, key: str):
        return next((b for b in self.active_votes if b.key == key), None)

    def elections(self) -> List[VotingSystem]:
        return [v for v in self.active_votes if isinstance(v, VotingSystem)]

    # ------------------------------------------------------------------ #
    # Eligibility helpers (shared by the prompt menu and commands)
    # ------------------------------------------------------------------ #
    def nominatable_votes(self, player: 'Player') -> List[VotingSystem]:
        return [v for v in self.elections() if v.is_nomination_open and v.can_nominate(player)]

    def nomination_candidates(self, vote: VotingSystem) -> List['Player']:
        """Who may still be put forward: eligible, not already standing in this or any other election,
        not campaigning by persuasion for an office, and not someone who declined this one."""
        contests = getattr(self.game_state, "contests", None)
        return [p for p in self.game_state.players
                if p.name not in vote.nominations and p.name not in vote.declined
                and self.standing_in(p) is None and not (contests and contests.campaigning(p.name))
                and self.government.can_hold_office(vote.role, p)[0]]

    def standing_in(self, player: 'Player') -> Optional[VotingSystem]:
        """The election this player is a candidate in (nominated, or on the ballot), if any.
        Nobody stands in two elections at once."""
        for v in self.elections():
            if player.name in (v.nominations if v.is_nomination_open else v.choices()):
                return v
        return None

    def declinable(self, player: 'Player') -> List[VotingSystem]:
        """Elections this player may turn down: they are nominated, or on the ballot."""
        v = self.standing_in(player)
        return [v] if v is not None else []

    def decline(self, player: 'Player', key: str, reason: str = None) -> bool:
        """The player turns down their nomination (or withdraws from the vote). Votes already cast
        for them are void and those voters may vote again."""
        vote = self.ballot(key)
        if vote is None or vote not in self.declinable(player):
            Messages.add(f"{player.name} is not standing for that.", important=False)
            return False
        name = player.name
        vote.declined.append(name)
        if vote.is_nomination_open:
            vote.nominations.remove(name)
            vote.nominated_by.pop(name, None)
            Messages.add(f"{name} declines the nomination for {vote.label}", reason=reason)
            return True
        vote.candidates = [c for c in vote.candidates if c != name]
        if getattr(vote, "finalists", None):
            vote.finalists = [c for c in vote.finalists if c != name]
        for voter, ranking in vote.votes.items():
            vote.votes[voter] = [c for c in ranking if c != name]
        Messages.add(f"{name} withdraws from {vote.label}", reason=reason)
        remaining = vote.choices()
        if len(remaining) == 1:
            self._seat_winner(vote, remaining[0])
        elif not remaining:
            Messages.add(f"No candidates remain for {vote.label}; nominations will reopen.")
            self._remove(vote)
            self.initiate_votes()
        return True

    def forget(self, name: str):
        """Someone has died: they leave every electorate; a candidate drops out (votes for them are void, and
        a ballot left with one candidate seats them); a motion about them, or called by them, is called off."""
        for vote in list(self.active_votes):
            vote.votes.pop(name, None)
            if isinstance(vote, Motion):
                if (vote.target is not None and vote.target.name == name) or vote.proposer.name == name:
                    self._remove(vote)
                    Messages.add(f"The vote '{vote.label}' is called off: {name} has died")
                continue
            vote.nominated_by = {c: by for c, by in vote.nominated_by.items() if c != name}
            if vote.is_nomination_open:
                if name in vote.nominations:
                    vote.nominations.remove(name)
                continue
            if name not in vote.choices():
                continue
            vote.candidates = [c for c in vote.candidates if c != name]
            if getattr(vote, "finalists", None):
                vote.finalists = [c for c in vote.finalists if c != name]
            for voter, ranking in vote.votes.items():
                vote.votes[voter] = [c for c in ranking if c != name]
            remaining = vote.choices()
            if len(remaining) == 1:
                self._seat_winner(vote, remaining[0])
            elif not remaining:
                Messages.add(f"No candidates remain for {vote.label}; nominations will reopen.")
                self._remove(vote)
                self.initiate_votes()

    def _candidates_vote_for_themselves(self, vote: VotingSystem):
        """A candidate's own vote is for themselves; they aren't asked."""
        for name in vote.choices():
            if name in vote.votes:
                vote.votes[name] = [name]

    def pending_votes(self, player: 'Player') -> List[Ballot]:
        """Ballots in the voting phase where this player still has to vote."""
        return [v for v in self.active_votes
                if v.is_voting_active() and v.in_electorate(player) and not v.has_voted(player)]

    def available_motions(self, player: 'Player') -> List[Tuple[str, str, 'Player']]:
        """(kind, subject, target) motions this player may call."""
        gov = self.government
        if not gov.can_vote(player):
            return []
        open_keys = {v.key for v in self.active_votes}
        motions = []

        def may_call(spec, target) -> bool:
            if spec["method"] not in VOTE_METHODS:
                return False
            resolved = gov.resolve_vote_method(spec)
            return bool(resolved) and player in gov.electorate(*resolved, exclude=target)

        for office in gov.government_type.offices.values():
            for holder in gov.get_role_holders(office.name):
                if holder is not player and not gov.in_grace(office.name, holder) and may_call(office.removed_by, holder):
                    motions.append(("remove_office", office.name, holder))
        for status in gov.government_type.statuses.values():
            if not gov.is_unlocked(status.requires):
                continue
            for target in gov.players:
                if target is player:
                    continue
                has = target in gov.statuses.get(status.name, [])
                if not has and may_call(status.granted_by, target):
                    motions.append(("grant_status", status.name, target))
                elif has and may_call(status.revoked_by, target):
                    motions.append(("revoke_status", status.name, target))
        return [m for m in motions if f"{m[0]}:{m[1]}:{m[2].name}" not in open_keys]

    # ------------------------------------------------------------------ #
    # Elections
    # ------------------------------------------------------------------ #
    def _label(self, office_name: str, seat: int) -> str:
        office = self.government.government_type.offices.get(office_name)
        return f"{office_name} (Seat {seat})" if office and office.seats > 1 else office_name

    def initiate_votes(self):
        """Open an election for the next vacant seat of each vote-selected office (one seat at a time)."""
        gov = self.government
        if gov is None or self.game_state.players is None:
            raise ValueError("Invalid GameState: government or players are None")
        for office in gov.government_type.offices.values():
            spec = office.selected_by
            if spec["method"] not in VOTE_METHODS or not gov.is_unlocked(office.requires):
                continue
            holders = len(gov.get_role_holders(office.name))
            if holders >= office.seats or any(v.role == office.name for v in self.elections()):
                continue
            resolved = gov.resolve_vote_method(spec)
            if not resolved:
                continue
            method, council = resolved
            seat = holders + 1
            vote = VOTING_SYSTEMS[spec.get("voting_system", "first_past_the_post")](
                office.name, method, council,
                nomination_hours=int(spec.get("nomination_days", NOMINATION_HOURS / HOURS_PER_DAY) * HOURS_PER_DAY),
                voting_hours=int(spec.get("voting_days", VOTING_HOURS / HOURS_PER_DAY) * HOURS_PER_DAY),
                seat_number=seat, label=self._label(office.name, seat),
            )
            vote.government = gov
            vote.start_nominations(self.now)
            self.active_votes.append(vote)
            who = "all members" if method == "tribe_vote" else f"the {council}s"
            Messages.add(f"Nominations are open for {vote.label} until {format_date(vote.nominations_close_at)} "
                         f"(nominated and chosen by {who})")

    def snap_election(self, office_name: str, nomination_days: float, voting_days: float) -> bool:
        """A seat fell empty suddenly (its holder died): an election opens at once, short, whatever way the
        office is normally filled (a divine sign, a yearly roll...). Voters are those the office's own vote would
        have (else the whole tribe). False if one is already under way or nobody may vote."""
        gov = self.government
        office = gov.government_type.offices.get(office_name)
        if office is None or any(v.role == office_name for v in self.elections()):
            return False
        spec = office.selected_by
        resolved = gov.resolve_vote_method(spec) if spec["method"] in VOTE_METHODS else ("tribe_vote", None)
        if not resolved:
            resolved = ("tribe_vote", None)
        method, council = resolved
        seat = len(gov.get_role_holders(office_name)) + 1
        vote = VOTING_SYSTEMS[spec.get("voting_system", "first_past_the_post")](
            office_name, method, council, nomination_hours=max(1, int(nomination_days * HOURS_PER_DAY)),
            voting_hours=max(1, int(voting_days * HOURS_PER_DAY)), seat_number=seat,
            label=self._label(office_name, seat))
        vote.government = gov
        vote.start_nominations(self.now)
        self.active_votes.append(vote)
        who = "all members" if method == "tribe_vote" else f"the {council}s"
        Messages.add(f"The seat of {vote.label} stands empty: nominations are open at once, until "
                     f"{format_date(vote.nominations_close_at)} (chosen by {who})")
        return True

    def cancel_unneeded_elections(self):
        """End elections for offices whose seats were all filled some other way (e.g. by persuasion)."""
        gov = self.government
        for vote in self.elections():
            office = gov.government_type.offices.get(vote.role)
            if office is None or len(gov.get_role_holders(vote.role)) >= office.seats:
                self._remove(vote)
                Messages.add(f"The election for {vote.label} is called off: the seat has been filled")

    def _remove(self, ballot: Ballot):
        if ballot in self.active_votes:
            self.active_votes.remove(ballot)

    def _seat_winner(self, vote: VotingSystem, winner_name: str):
        winner = next((p for p in self.game_state.players if p.name == winner_name), None)
        if winner and self.government.assign_office(vote.role, winner, announce=False):
            Messages.add(f"{winner.name} has been chosen as {vote.label}")
        else:
            Messages.add(f"The election for {vote.label} produced no valid winner; it will be held again.")
        self._remove(vote)
        self.initiate_votes()

    def _process_election(self, vote: VotingSystem):
        if vote.is_nomination_open and vote.is_nomination_period_over(self.now):
            vote.close_nominations()
            # Candidates may have become ineligible since nomination (e.g. took another office).
            candidates = [n for n in vote.nominations
                          if any(p.name == n and self.government.can_hold_office(vote.role, p)[0]
                                 for p in self.game_state.players)]
            if len(candidates) == 1:
                self._seat_winner(vote, candidates[0])
            elif candidates:
                electorate = self.government.electorate(vote.method, vote.council)
                vote.start_vote(electorate, candidates, self.now, vote.voting_hours)
                self._candidates_vote_for_themselves(vote)
                Messages.add(f"Voting has begun for {vote.label} until {format_date(vote.voting_closes_at)}: "
                             f"{', '.join(candidates)}")
            else:
                Messages.add(f"No eligible nominations for {vote.label}; nominations will reopen.")
                self._remove(vote)
                self.initiate_votes()
            return
        if vote.is_complete(self.now):
            result = vote.get_result()
            if result == "RUNOFF":
                vote.start_vote(self.government.electorate(vote.method, vote.council), vote.candidates, self.now, vote.voting_hours)
                self._candidates_vote_for_themselves(vote)
                Messages.add(f"No majority for {vote.label}; runoff between {', '.join(vote.finalists)}")
                return
            self._seat_winner(vote, result)

    # ------------------------------------------------------------------ #
    # Motions
    # ------------------------------------------------------------------ #
    def propose_motion(self, proposer: 'Player', kind: str, subject: str, target: 'Player', reason: str = None) -> bool:
        if (kind, subject, target) not in self.available_motions(proposer):
            Messages.add("You cannot call that vote.")
            return False
        gov = self.government
        entry = gov.government_type.offices.get(subject) or gov.government_type.statuses.get(subject)
        spec = {"remove_office": getattr(entry, "removed_by", None),
                "grant_status": getattr(entry, "granted_by", None),
                "revoke_status": getattr(entry, "revoked_by", None)}[kind]
        method, council = gov.resolve_vote_method(spec)
        motion = Motion(kind, subject, target, proposer)
        motion.start_vote(gov.electorate(method, council, exclude=target), ["Yes", "No"], self.now, MOTION_HOURS)
        self.active_votes.append(motion)
        voters = "all members" if method == "tribe_vote" else f"the {council}s"
        Messages.add(f"{proposer.name} calls a vote of {voters}: {motion.label}", reason=reason)
        return True

    def propose_reform(self, proposer: 'Player', government_key: str, reason: str = None) -> bool:
        gov = self.government
        target = next((g for g in gov.available_reforms() if g.key == government_key), None)
        if gov.reform_mode(proposer) != "vote" or target is None:
            Messages.add("You cannot call a reform vote right now.")
            return False
        method, council = gov.reform_vote_method()
        motion = Motion("reform", target.key, None, proposer, subject_label=target.name)
        motion.start_vote(gov.electorate(method, council), ["Yes", "No"], self.now, MOTION_HOURS)
        self.active_votes.append(motion)
        voters = "all members" if method == "tribe_vote" else f"the {council}s"
        Messages.add(f"{proposer.name} calls a vote of {voters}: {motion.label}", reason=reason)
        return True

    def _process_motion(self, motion: Motion):
        if not motion.is_complete(self.now):
            return
        self._remove(motion)
        gov = self.government
        if not motion.passed():
            Messages.add(f"Vote failed: {motion.label}")
            return
        Messages.add(f"Vote passed: {motion.label}")
        if motion.kind == "reform":
            if not gov.reform(motion.subject):
                Messages.add("The reform could not take place (it is no longer possible).")
            return
        if motion.kind == "remove_office":
            gov.remove_office(motion.subject, motion.target)
        elif motion.kind == "grant_status":
            gov.grant_status(motion.subject, motion.target)
        else:
            gov.revoke_status(motion.subject, motion.target)
        self.initiate_votes()

    # ------------------------------------------------------------------ #
    # Turn processing
    # ------------------------------------------------------------------ #
    def process_votes(self):
        for ballot in self.active_votes[:]:
            if ballot not in self.active_votes:
                continue  # removed while processing another ballot
            if isinstance(ballot, Motion):
                self._process_motion(ballot)
            else:
                self._process_election(ballot)

    def cast_vote(self, player: 'Player', key: str, ranking: List[str], reason: str = None) -> bool:
        """Record a ballot. `ranking` is one choice, or several in order for ranked-choice elections."""
        ballot = self.ballot(key)
        if ballot is None or ballot not in self.pending_votes(player):
            Messages.add(f"{player.name} cannot vote on that.")
            return False
        valid = ballot.choices()
        if not ranking or any(c not in valid for c in ranking) or len(set(ranking)) != len(ranking) \
                or (not ballot.ranked and len(ranking) != 1):
            Messages.add(f"Vote not recorded: choose {'one or more' if ballot.ranked else 'one'} of {', '.join(valid)}")
            return False
        ballot.votes[player.name] = list(ranking)
        Messages.add(f"{player.name} voted {', '.join(ranking)} on: {ballot.label}", important=False, reason=reason)
        self.process_votes()  # resolve at once if everyone has now voted
        return True

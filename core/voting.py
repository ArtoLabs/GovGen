"""Ballots: elections to fill offices and yes/no motions. All periods run on the game clock (hours)."""
import random
from typing import Any, Callable, Dict, List, Optional
from world.player import Player
from utils.logging_config import logger


class Ballot:
    """State shared by elections and motions: who may vote, the votes cast, and when voting closes."""
    is_nomination_open = False
    ranked = False  # True if voters rank several choices instead of picking one

    def __init__(self, key: str, label: str):
        self.key = key
        self.label = label
        self.candidates: List[str] = []
        self.votes: Dict[str, List[str]] = {}
        self.voting_closes_at: Optional[int] = None

    def start_vote(self, electorate: List[Player], candidates: List[str], now: int, duration_hours: int):
        self.candidates = list(candidates)
        self.votes = {p.name: [] for p in electorate}
        self.voting_closes_at = now + duration_hours
        logger.debug(f"Voting started: {self.label} candidates={self.candidates} electorate={list(self.votes)}")

    def choices(self) -> List[str]:
        """What a voter may currently choose between."""
        return self.candidates

    def is_voting_active(self) -> bool:
        return bool(self.candidates and self.voting_closes_at is not None)

    def in_electorate(self, player: Player) -> bool:
        return player.name in self.votes

    def has_voted(self, player: Player) -> bool:
        return bool(self.votes.get(player.name))

    def is_complete(self, now: int) -> bool:
        """Everyone in the electorate has voted, or voting has closed. Non-voters abstain."""
        return self.is_voting_active() and (all(self.votes.values()) or now >= self.voting_closes_at)

    def next_deadline(self) -> Optional[int]:
        return self.voting_closes_at if self.is_voting_active() else None

    def get_result(self) -> str:
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        return {"class": type(self).__name__, "key": self.key, "label": self.label, "candidates": self.candidates,
                "votes": self.votes, "voting_closes_at": self.voting_closes_at}

    def _load(self, data: Dict[str, Any]):
        self.candidates = list(data["candidates"])
        self.votes = {k: list(v) for k, v in data["votes"].items()}
        self.voting_closes_at = data["voting_closes_at"]


# --------------------------------------------------------------------------- #
# Elections
# --------------------------------------------------------------------------- #
class VotingSystem(Ballot):
    """An election to fill one seat of an office: a nomination period, then a voting period."""

    def __init__(self, role: str, method: str, council: Optional[str] = None, nomination_hours: int = 720,
                 voting_hours: int = 720, seat_number: int = 1, label: Optional[str] = None):
        super().__init__(key=f"elect:{role}", label=label or role)
        self.role = role
        self.seat_number = seat_number
        self.method = method          # "tribe_vote" or "council_vote"
        self.council = council
        self.nomination_hours = nomination_hours
        self.voting_hours = voting_hours
        self.nominations: List[str] = []
        self.nominated_by: Dict[str, str] = {}   # candidate -> who put them forward
        self.declined: List[str] = []            # people who turned this election down; not nominated again
        self.nominations_close_at: Optional[int] = None
        self.is_nomination_open = False
        self.government = None  # set by VotingManager

    def start_nominations(self, now: int):
        self.is_nomination_open = True
        self.nominations_close_at = now + self.nomination_hours

    def is_nomination_period_over(self, now: int) -> bool:
        return self.nominations_close_at is not None and now >= self.nominations_close_at

    def close_nominations(self):
        self.is_nomination_open = False

    def next_deadline(self) -> Optional[int]:
        return self.nominations_close_at if self.is_nomination_open else super().next_deadline()

    def can_nominate(self, player: Player) -> bool:
        return bool(self.government) and player in self.government.electorate(self.method, self.council)

    def nominate(self, nominator: Player, candidate_name: str):
        if not self.is_nomination_open:
            raise ValueError("Nominations are not open")
        if not self.can_nominate(nominator):
            raise ValueError(f"{nominator.name} may not nominate for {self.role}")
        if candidate_name in self.nominations:
            raise ValueError(f"{candidate_name} is already nominated for {self.role}")
        if candidate_name in self.declined:
            raise ValueError(f"{candidate_name} has declined to stand for {self.role}")
        self.nominations.append(candidate_name)
        self.nominated_by[candidate_name] = nominator.name
        logger.debug(f"{nominator.name} nominated {candidate_name} for {self.label}")

    @staticmethod
    def _top(vote_counts: Dict[str, int]) -> str:
        if not vote_counts:
            return ""
        best = max(vote_counts.values())
        return random.choice([c for c, v in vote_counts.items() if v == best])  # ties broken by lot

    def to_dict(self) -> Dict[str, Any]:
        return {**super().to_dict(), "role": self.role, "seat_number": self.seat_number, "method": self.method,
                "council": self.council, "nomination_hours": self.nomination_hours, "voting_hours": self.voting_hours,
                "nominations": self.nominations, "nominations_close_at": self.nominations_close_at,
                "nominated_by": dict(self.nominated_by), "declined": list(self.declined),
                "is_nomination_open": self.is_nomination_open}

    def _load(self, data: Dict[str, Any]):
        super()._load(data)
        self.nominations = list(data["nominations"])
        self.nominated_by = dict(data.get("nominated_by", {}))
        self.declined = list(data.get("declined", []))
        self.nominations_close_at = data["nominations_close_at"]
        self.is_nomination_open = data["is_nomination_open"]


class FirstPastThePost(VotingSystem):
    def get_result(self) -> str:
        counts = {c: 0 for c in self.candidates}
        for ballot in self.votes.values():
            if ballot and ballot[0] in counts:
                counts[ballot[0]] += 1
        return self._top(counts)


class RankedChoiceVoting(VotingSystem):
    ranked = True

    def get_result(self) -> str:
        remaining = list(self.candidates)  # a list, not a set, so results never depend on hash order
        while remaining:
            counts = {c: 0 for c in remaining}
            for ballot in self.votes.values():
                for choice in ballot:
                    if choice in counts:
                        counts[choice] += 1
                        break
            total = sum(counts.values())
            leader = self._top(counts)
            if total == 0 or counts[leader] > total / 2 or len(remaining) == 1:
                return leader
            lowest = min(counts.values())
            remaining = [c for c in remaining if counts[c] > lowest] or [leader]
        return ""


class TwoRoundRunoffVoting(VotingSystem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.finalists: List[str] = []

    def choices(self) -> List[str]:
        return self.finalists or self.candidates

    def get_result(self) -> str:
        pool = self.finalists or self.candidates
        counts = {c: 0 for c in pool}
        for ballot in self.votes.values():
            if ballot and ballot[0] in counts:
                counts[ballot[0]] += 1
        if self.finalists:
            return self._top(counts)
        ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        if len(ranked) == 1 or ranked[0][1] > sum(counts.values()) / 2:
            return ranked[0][0]
        self.finalists = [ranked[0][0], ranked[1][0]]
        return "RUNOFF"

    def to_dict(self) -> Dict[str, Any]:
        return {**super().to_dict(), "finalists": self.finalists}

    def _load(self, data: Dict[str, Any]):
        super()._load(data)
        self.finalists = list(data.get("finalists", []))


# --------------------------------------------------------------------------- #
# Motions: yes/no votes on removing someone, a status, or a reform
# --------------------------------------------------------------------------- #
class Motion(Ballot):
    KINDS = {
        "remove_office": "Remove {target} as {subject}?",
        "grant_status": "Make {target} {subject}?",
        "revoke_status": "Lift {target}'s {subject} status?",
        "reform": "Reform the government into a {subject}?",
    }

    def __init__(self, kind: str, subject: str, target: Optional[Player], proposer: Player, subject_label: str = None):
        target_name = target.name if target else ""
        label = self.KINDS[kind].format(target=target_name, subject=subject_label or subject)
        super().__init__(key=f"{kind}:{subject}:{target_name}", label=label)
        self.kind = kind
        self.subject = subject
        self.subject_label = subject_label
        self.target = target
        self.proposer = proposer

    def passed(self) -> bool:
        """Passes with yes votes from a majority of the whole electorate (abstaining counts against)."""
        yes = sum(1 for ballot in self.votes.values() if ballot == ["Yes"])
        return yes > len(self.votes) / 2

    def get_result(self) -> str:
        return "Yes" if self.passed() else "No"

    def to_dict(self) -> Dict[str, Any]:
        return {**super().to_dict(), "kind": self.kind, "subject": self.subject, "subject_label": self.subject_label,
                "target": self.target.name if self.target else None, "proposer": self.proposer.name}


BALLOT_CLASSES = {c.__name__: c for c in (FirstPastThePost, RankedChoiceVoting, TwoRoundRunoffVoting, Motion)}


def ballot_from_dict(data: Dict[str, Any], player: Callable[[str], Player]) -> Ballot:
    cls = BALLOT_CLASSES[data["class"]]
    if cls is Motion:
        ballot = Motion(data["kind"], data["subject"], player(data["target"]) if data["target"] else None,
                        player(data["proposer"]), data.get("subject_label"))
    else:
        ballot = cls(data["role"], data["method"], data["council"], data["nomination_hours"], data["voting_hours"],
                     data["seat_number"], data["label"])
    ballot._load(data)
    return ballot

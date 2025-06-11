from typing import List, Dict, Optional

class SelectionMethod:
    def __init__(
        self,
        key: str,
        name: str,
        description: str,
        required_innovations: Optional[List[str]] = None,
        available_at_start: bool = False
    ):
        self.key = key
        self.name = name
        self.description = description
        self.required_innovations = required_innovations or []
        self.available_at_start = available_at_start  # Allow use at game start (e.g., tribal phase)

    def is_unlocked(self, owned_innovations: List[str]) -> bool:
        """Check if the selection method is unlocked based on innovations or initial availability."""
        if self.available_at_start:
            return True  # Available at game start (e.g., for tribal government)
        return all(req in owned_innovations for req in self.required_innovations)

    def __repr__(self):
        return f"<SelectionMethod {self.name} (Key: {self.key})>"

SELECTION_METHODS: Dict[str, SelectionMethod] = {
    "divine_appointment": SelectionMethod(
        key="divine_appointment",
        name="Divine Appointment",
        description="Chosen by spiritual or mystical signs.",
        required_innovations=["Divine Right"],
        available_at_start=True  # Available for tribal phase
    ),
    "hereditary_succession": SelectionMethod(
        key="hereditary_succession",
        name="Hereditary Succession",
        description="Passed through contemporaneous bloodlines or family ties.",
        required_innovations=["Hereditary Rule"]
    ),
    "appointment": SelectionMethod(
        key="appointment",
        name="Appointment",
        description="Selected by an existing authority figure.",
        required_innovations=["Hierarchy"]
    ),
    "lottery": SelectionMethod(
        key="lottery",
        name="Lottery",
        description="Randomly selected from eligible candidates.",
        required_innovations=["Record Keeping"]
    ),
    "election_direct": SelectionMethod(
        key="election_direct",
        name="Direct Election",
        description="Voted on directly by the eligible population.",
        required_innovations=["Voting", "Election"]
    ),
    "election_indirect": SelectionMethod(
        key="election_indirect",
        name="Indirect Election",
        description="Chosen by an intermediary electoral body.",
        required_innovations=["Representation", "Election"]
    ),
    "contest": SelectionMethod(
        key="contest",
        name="Contest / Trial by Skill",
        description="Decided by competition, combat, or trial.",
        required_innovations=["Military Command"]
    ),
    "rotation": SelectionMethod(
        key="rotation",
        name="Rotation",
        description="Chosen in turn from a predefined pool or order.",
        required_innovations=["Record Keeping"]
    ),
    "auction": SelectionMethod(
        key="auction",
        name="Auction / Purchase",
        description="Granted to the highest bidder or payer.",
        required_innovations=["Currency"]
    ),
    "seniority": SelectionMethod(
        key="seniority",
        name="Seniority",
        description="Given to the oldest or longest-serving candidate.",
        required_innovations=["Record Keeping"]
    ),
    "self_appointment": SelectionMethod(
        key="self_appointment",
        name="Self-Appointment",
        description="The person claims the position for themselves, often backed by force.",
        required_innovations=["Military Command"],
        available_at_start=True  # Available for tribal phase
    )
}

def get_unlocked_selection_methods(owned_innovations: List[str], government_type: Optional[str] = None) -> List[SelectionMethod]:
    """
    Get unlocked selection methods based on current innovations and optional government type.
    government_type is a placeholder for future integration with government_types.py.
    """
    unlocked_methods = [
        method for method in SELECTION_METHODS.values()
        if method.is_unlocked(owned_innovations)
    ]
    # Placeholder for government type filtering (to be expanded later)
    if government_type:
        # Example: Restrict methods based on government_type (e.g., Tribal allows only divine_appointment, self_appointment)
        pass
    return unlocked_methods

def get_selection_method(key: str) -> Optional[SelectionMethod]:
    """Fetch a selection method by its key."""
    return SELECTION_METHODS.get(key)
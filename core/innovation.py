from typing import List, Optional
import random

class Innovation:
    def __init__(self, name: str, description: str = "", icon: Optional[str] = None, 
                 prerequisites: Optional[List[str]] = None, tags: Optional[List[str]] = None, 
                 cost: int = 10):
        self.name = name
        self.description = description
        self.icon = icon
        self.prerequisites = prerequisites or []
        self.tags = tags or []
        self.cost = cost  # Innovation points required to unlock
        self.discovered = False

    def is_discoverable(self, discovered_names: set) -> bool:
        return all(prereq in discovered_names for prereq in self.prerequisites)

    def __repr__(self):
        return f"<Innovation {self.name} (Cost: {self.cost})>"

class InnovationPool:
    def __init__(self):
        self.discovered = set()
        self.points = 100  # Total accumulated innovation points

    def add_points(self, points: int):
        """Add innovation points to the pool."""
        self.points += points

    def spend_points(self, cost: int) -> bool:
        """Spend points if sufficient, return True if successful."""
        if self.points >= cost:
            self.points -= cost
            return True
        return False

    def discover(self, name: str) -> bool:
        """Attempt to discover a specific innovation (targeted research)."""
        if name not in INNOVATIONS:
            raise ValueError(f"Unknown innovation: {name}")
        innovation = INNOVATIONS[name]
        if innovation.is_discoverable(self.discovered) and self.points >= innovation.cost:
            self.discovered.add(name)
            self.points -= innovation.cost
            return True
        return False

    def discover_random(self) -> Optional[str]:
        """Attempt to discover a random innovation if enough points are available."""
        discoverable = self.get_discoverable()
        affordable = [i for i in discoverable if i.cost <= self.points]
        if not affordable:
            return None
        innovation = random.choice(affordable)
        self.discovered.add(innovation.name)
        self.points -= innovation.cost
        return innovation.name

    def get_discovered(self) -> List['Innovation']:
        return [INNOVATIONS[n] for n in self.discovered]

    def get_discoverable(self) -> List['Innovation']:
        return [i for i in INNOVATIONS.values() 
                if i.name not in self.discovered and i.is_discoverable(self.discovered)]

    def __repr__(self):
        return f"<InnovationPool Points: {self.points}, Discovered: {sorted(self.discovered)}>"

# Static innovation registry (updated with costs)
INNOVATIONS = {
    "Fire": Innovation("Fire", "Control of fire.", icon="🔥", cost=0),
    "Toolmaking": Innovation("Toolmaking", "Basic tools from stone.", icon="🪓", cost=0),
    "Language": Innovation("Language", "Spoken communication.", icon="🎤", cost=0),
    "Tribalism": Innovation("Tribalism", "Organized kinship groups.", prerequisites=["Language"], cost=0),
    "Writing": Innovation("Writing", "Symbolic written communication.", prerequisites=["Toolmaking", "Language"], icon="✍️", cost=20),
    "Record Keeping": Innovation("Record Keeping", "Maintaining structured logs.", prerequisites=["Writing"], cost=15),
    "Law Code": Innovation("Law Code", "Formalized rules.", prerequisites=["Writing"], icon="📜", cost=18),
    "Hierarchy": Innovation("Hierarchy", "Structured social ranks.", prerequisites=["Tribalism"], cost=15),
    "Chieftainship": Innovation("Chieftainship", "Basic tribal leadership.", prerequisites=["Tribalism"], cost=0),
    "Divine Right": Innovation("Divine Right", "Leader chosen by gods.", prerequisites=["Chieftainship"], cost=25),
    "Hereditary Rule": Innovation("Hereditary Rule", "Power passed by lineage.", prerequisites=["Chieftainship"], cost=25),
    "Law Interpretation": Innovation("Law Interpretation", "Judicial review of rules.", prerequisites=["Law Code"], cost=22),
    "Dispute Resolution": Innovation("Dispute Resolution", "Formal judging process.", prerequisites=["Law Interpretation"], cost=20),
    "Military Command": Innovation("Military Command", "Organized armed leadership.", prerequisites=["Hierarchy"], cost=25),
    "Standing Army": Innovation("Standing Army", "Permanent military body.", prerequisites=["Military Command"], cost=30),
    "Religious Authority": Innovation("Religious Authority", "Clergy or spiritual power.", prerequisites=["Language"], cost=15),
    "Organized Religion": Innovation("Organized Religion", "Systematized belief.", prerequisites=["Religious Authority"], cost=20),
    "Representation": Innovation("Representation", "Voices for people in decisions.", prerequisites=["Law Code"], cost=25),
    "Voting": Innovation("Voting", "Collective decision-making.", prerequisites=["Representation"], cost=20),
    "Election": Innovation("Election", "Formal process of selecting leaders.", prerequisites=["Voting"], cost=25),
    "Taxation": Innovation("Taxation", "Systematic resource extraction.", prerequisites=["Law Code"], cost=20),
    "Currency": Innovation("Currency", "Standardized medium of exchange.", prerequisites=["Taxation"], cost=25),
    "Infrastructure Planning": Innovation("Infrastructure Planning", "Organized resource development.", prerequisites=["Taxation"], cost=22),
    "Information Gathering": Innovation("Information Gathering", "Spying and reporting.", prerequisites=["Language"], cost=18),
    "Espionage": Innovation("Espionage", "Covert operations.", prerequisites=["Information Gathering"], cost=25),
}
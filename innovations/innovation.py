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
        self.cost = cost
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
        if name not in ALL_INNOVATIONS:
            raise ValueError(f"Unknown innovation: {name}")
        innovation = ALL_INNOVATIONS[name]
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
        return [ALL_INNOVATIONS[n] for n in self.discovered]

    def get_discoverable(self) -> List['Innovation']:
        return [i for i in ALL_INNOVATIONS.values()
                if i.name not in self.discovered and i.is_discoverable(self.discovered)]

    def __repr__(self):
        return f"<InnovationPool Points: {self.points}, Discovered: {sorted(self.discovered)}>"

# Role-specific innovation lists
LEADERSHIP_INNOVATIONS = [
    Innovation("Fire", "Control of fire for warmth and cooking.", icon="👑", cost=0, tags=["Tribal, Leadership"]),
    Innovation("Language", "Spoken communication for coordination.", icon="👑", cost=0, tags=["Tribal, Leadership"]),
    Innovation("Tribalism", "Organized kinship groups for social structure.", icon="👑", prerequisites=["Language"], cost=0, tags=["Tribal, Leadership"]),
    Innovation("Hierarchy", "Structured social ranks for authority.", icon="👑", prerequisites=["Tribalism"], cost=0, tags=["Tribal, Leadership"]),
    Innovation("Chieftainship", "Formalized tribal leadership.", icon="👑", prerequisites=["Tribalism"], cost=20, tags=["Tribal, Leadership"]),
    Innovation("Hereditary Rule", "Power passed through family lineage.", icon="👑", prerequisites=["Chieftainship"], cost=25, tags=["Tribal, Leadership"]),
    Innovation("Warrior Command", "Organized leadership for armed forces.", icon="👑", prerequisites=["Hierarchy"], cost=25, tags=["Tribal, Leadership"]),
    Innovation("Centralized Authority", "Unified control over tribal groups.", icon="👑", prerequisites=["Hierarchy"], cost=20, tags=["Tribal, Leadership"]),
    Innovation("Diplomacy", "Negotiation with external groups.", icon="👑", prerequisites=["Language"], cost=18, tags=["Tribal, Leadership"]),
    Innovation("Divine Right", "Leaders chosen by divine will.", icon="👑", prerequisites=["Chieftainship"], cost=25, tags=["Tribal, Leadership"]),
    Innovation("Distribution", "Leaders can distribute goods from storage to the tribe.", icon="👑", prerequisites=["Chieftainship", "Storage", "Oral History", "Token Exchange", "Forest Gardening"], cost=25, tags=["Tribal, Leadership"]),
    Innovation("Totemic Kinship Systems", "Clan leaders can be chosen.", icon="👑", prerequisites=["Chieftainship", "Hierarchy", "Hereditary Rule"], cost=25, tags=["Tribal, Leadership"]),
    Innovation("Personal Adornment", "Begins to create a separation of classes.", icon="👑", prerequisites=["Chieftainship", "Symbolism", "Ritual Ceremonies"], cost=25, tags=["Tribal, Leadership"]),
]

MILITARY_INNOVATIONS = [
    Innovation("Warriors", "Basic ability to appoint warriors within the tribe.", prerequisites=["Warrior Command"], cost=20, icon="⚔️", tags=["Tribal, Military"]),
    Innovation("Tactical Coordination", "Ability for warriors to perform more complex coordinated tactics.", prerequisites=["Warriors"], cost=15, icon="⚔️", tags=["Tribal, Military"]),
    Innovation("Weapon Crafting", "Advanced tools for combat.", prerequisites=["Toolmaking", "Warriors"], cost=15, icon="⚔️", tags=["Tribal, Military"]),
    Innovation("Fortifications", "Defensive structures like walls.", prerequisites=["Toolmaking", "Warriors", "Domestication"], cost=25, icon="⚔️", tags=["Tribal, Military"]),
    Innovation("Battle Formations", "Coordinated warrior maneuvers.", prerequisites=["Tactical Coordination"], cost=18, icon="⚔️", tags=["Tribal, Military"]),
]

LEGISLATIVE_INNOVATIONS = [
    Innovation("Symbolism", "Basic understanding of symbols.", prerequisites=[], cost=0, icon="📜", tags=["Tribal, Legislative"]),
    Innovation("Oral History", "Memorization of important tribal events and judgments.", prerequisites=["Symbolism", "Language"], cost=20, icon="📜", tags=["Tribal, Legislative"]),
    Innovation("Sacred Storytelling", "Retelling of sacred tribal history and beliefs.", prerequisites=["Oral History", "Spirituality", "Public Assemblies"], cost=20, icon="📜", tags=["Tribal, Legislative"]),
    Innovation("Oral Codes", "Memorization and retelling of tribal rules.", prerequisites=["Sacred Storytelling"], cost=20, icon="📜", tags=["Tribal, Legislative"]),
    Innovation("Oral Law", "Breaking tribal rules comes with consequences.", prerequisites=["Oral Codes", "Punishment"], cost=20, icon="📜", tags=["Tribal, Legislative"]),
    Innovation("Writing", "Symbolic written communication.", prerequisites=["Toolmaking", "Language"], cost=20, icon="📜", tags=["Tribal, Legislative"]),
    Innovation("Record Keeping", "Structured logs for governance.", prerequisites=["Writing"], cost=15, icon="📜", tags=["Tribal, Legislative"]),
]

JUDICIAL_INNOVATIONS = [
    Innovation("Dispute Resolution", "The chieftain's formal process for settling conflicts.", prerequisites=["Diplomacy"], cost=20, icon="⚖️", tags=["Tribal, Judicial"]),
    Innovation("Punishment", "Ability to inflict negative consequences.", prerequisites=["Dispute Resolution"], cost=25, icon="⚖️", tags=["Tribal, Judicial"]),
    Innovation("Ostracism", "Ability to exile a character.", prerequisites=["Punishment"], cost=25, icon="⚖️", tags=["Tribal, Judicial"]),
    Innovation("Tribal Arbitration", "Mediation by the entire tribe.", prerequisites=["Tribalism", "Punishment", "Oral Codes"], cost=15, icon="⚖️", tags=["Tribal, Judicial"]),
    Innovation("Trial by Elder Council", "Judgment by a group of elders.", prerequisites=["Punishment", "Hierarchy", "Tribal Council"], cost=25, icon="⚖️", tags=["Tribal, Judicial"]),
]

INTELLIGENCE_INNOVATIONS = [
    Innovation("Information Gathering", "Systematic spying and reporting.", prerequisites=["Language"], cost=18, icon="🕵️", tags=["Tribal, Intelligence"]),
    Innovation("Scouting Networks", "Organized reconnaissance teams.", prerequisites=["Information Gathering"], cost=20, icon="🕵️", tags=["Tribal, Intelligence"]),
]

ECONOMIC_INNOVATIONS = [
    Innovation("Domestication", "The taming of animals and plants.", prerequisites=["Tribalism", "Forest Gardening"], cost=10, icon="💰", tags=["Tribal, Economic"]),
    Innovation("Barter System", "Character-to-character trading.", prerequisites=["Tribalism"], cost=10, icon="💰", tags=["Tribal, Economic"]),
    Innovation("Trade", "Trade between tribes.", prerequisites=["Barter System", "Distribution"], cost=10, icon="💰", tags=["Tribal, Economic"]),
    Innovation("Token Exchange", "A precursor to money.", prerequisites=["Trade"], cost=10, icon="💰", tags=["Tribal, Economic"]),
    Innovation("Debt", "Ability to owe at a later time.", prerequisites=["Token Exchange"], cost=10, icon="💰", tags=["Tribal, Economic"]),
    Innovation("Division of Labor", "Ability to select tribal members for specific duties.", prerequisites=["Debt"], cost=10, icon="💰", tags=["Tribal, Economic"]),
    Innovation("Property", "Exclusive claim to objects.", prerequisites=["Domestication"], cost=10, icon="💰", tags=["Tribal, Economic"]),
    Innovation("Long-Distance Trade", "Increases the number of tribes to trade with.", prerequisites=["Trade", "The Wheel"], cost=10, icon="💰", tags=["Tribal, Economic"]),
    Innovation("Skill Specialization", "Increases the quality of production.", prerequisites=["Division of Labor"], cost=10, icon="💰", tags=["Tribal, Economic"]),
    Innovation("Taxation", "Systematic resource collection.", prerequisites=["Chieftainship", "Centralized Authority", "Property", "Oral Law", "Debt"], cost=20, icon="💰", tags=["Tribal, Economic"]),
    Innovation("Marketplaces", "Central locations for commerce.", prerequisites=["Trade", "Property"], cost=15, icon="💰", tags=["Tribal, Economic"]),
    Innovation("Trade Guilds", "Organized merchant associations.", prerequisites=["Skill Specialization"], cost=20, icon="💰", tags=["Tribal, Economic"]),
]

INFRASTRUCTURE_INNOVATIONS = [
    Innovation("Gardens on the Move", "Spreading seeds along nomadic routes.", cost=0, icon="🏗️", tags=["Tribal, Infrastructure"]),
    Innovation("Toolmaking", "Basic tools from stone or wood.", cost=0, icon="🏗️", tags=["Tribal, Infrastructure"]),
    Innovation("Stone Cutting", "Cutting and shaping stone for tools and structures.", cost=0, prerequisites=["Toolmaking"], icon="🏗️", tags=["Tribal, Infrastructure"]),
    Innovation("Traditional Sites", "Established locations for tribal activities.", prerequisites=["Gardens on the Move"], cost=20, icon="🏗️", tags=["Tribal, Infrastructure"]),
    Innovation("The Wheel", "A classic invention for transport.", prerequisites=["Toolmaking", "Domestication"], cost=20, icon="🏗️", tags=["Tribal, Infrastructure"]),
    Innovation("Forest Gardening", "Staying settled in one area long enough to plant a small garden.", prerequisites=["Gardens on the Move"], cost=20, icon="🏗️", tags=["Tribal, Infrastructure"]),
    Innovation("Sustenance Gardening", "Permanently settled and growing only enough food to survive.", prerequisites=["Forest Gardening"], cost=20, icon="🏗️", tags=["Tribal, Infrastructure"]),
    Innovation("Storage", "Keeps food longer.", prerequisites=["Toolmaking", "Domestication", "Sustenance Gardening"], cost=20, icon="🏗️", tags=["Tribal, Infrastructure"]),
    Innovation("Forestry", "Organized harvesting of timber.", prerequisites=["Toolmaking", "Forest Gardening"], cost=15, icon="🏗️", tags=["Tribal, Infrastructure"]),
    Innovation("Irrigation", "Water management for agriculture.", prerequisites=["Toolmaking", "Sustenance Gardening"], cost=20, icon="🏗️", tags=["Tribal, Infrastructure"]),
    Innovation("Agriculture", "The ability to produce more food than needed to survive.", prerequisites=["Toolmaking", "Irrigation"], cost=20, icon="🏗️", tags=["Tribal, Infrastructure"]),
    Innovation("Infrastructure Planning", "Coordinated resource allocation.", prerequisites=["Taxation"], cost=22, icon="🏗️", tags=["Tribal, Infrastructure"]),
    Innovation("Road Building", "Constructed paths for transport.", prerequisites=["Infrastructure Planning", "The Wheel"], cost=18, icon="🏗️", tags=["Tribal, Infrastructure"]),
    Innovation("Sacred Architecture", "Heightens powers of priest and chieftain.", prerequisites=["Infrastructure Planning", "Sacred Sites", "Stone Cutting"], cost=18, icon="🏗️", tags=["Tribal, Infrastructure"]),
    Innovation("Monumental Architecture", "Heightens powers of priest and chieftain.", prerequisites=["Sacred Architecture", "Stone Cutting"], cost=18, icon="🏗️", tags=["Tribal, Infrastructure"]),
]

RELIGIOUS_INNOVATIONS = [
    Innovation("Spirituality", "Finding existential meaning in abstract form.", prerequisites=["Language", "Symbolism"], cost=15, icon="🙏", tags=["Tribal, Religious"]),
    Innovation("Rituals", "Performing symbolic gestures to invoke mystery and power.", prerequisites=["Spirituality"], cost=15, icon="🙏", tags=["Tribal, Religious"]),
    Innovation("Burial", "Symbolic gestures to honor the deceased.", prerequisites=["Rituals", "Forest Gardening"], cost=15, icon="🙏", tags=["Tribal, Religious"]),
    Innovation("Burial Rituals", "Giving significance to lives lost.", prerequisites=["Rituals", "Forest Gardening"], cost=15, icon="🙏", tags=["Tribal, Religious"]),
    Innovation("Ritual Dances & Vision Quests", "Performing symbolic acts to seek spiritual insight.", prerequisites=["Spirituality"], cost=15, icon="🙏", tags=["Tribal, Religious"]),
    Innovation("Ceremonies", "Organized rituals for communal worship.", prerequisites=["Rituals"], cost=15, icon="🙏", tags=["Tribal, Religious"]),
    Innovation("Sacred Sites", "Dedicated places of worship.", prerequisites=["Ceremonies"], cost=22, icon="🙏", tags=["Tribal, Religious"]),
    Innovation("Religion", "Organized spiritual beliefs.", prerequisites=["Ceremonies", "Sacred Architecture"], cost=25, icon="🙏", tags=["Tribal, Religious"]),
    Innovation("Religious Authority", "Formal clergy or spiritual leaders.", prerequisites=["Religion"], cost=15, icon="🙏", tags=["Tribal, Religious"]),
]

CIVIC_REPRESENTATION_INNOVATIONS = [
    Innovation("Annual Traditions", "Beginning of holding group gatherings.", prerequisites=["Rituals", "Tribalism"], cost=15, icon="🏛️", tags=["Tribal, Civic Representation"]),
    Innovation("Ceremonial Feasting", "Brings the whole tribe together.", prerequisites=["Annual Traditions", "Sacred Sites"], cost=15, icon="🏛️", tags=["Tribal, Civic Representation"]),
    Innovation("Tribal Council", "Group representing community interests.", prerequisites=["Hierarchy", "Sacred Sites"], cost=15, icon="🏛️", tags=["Tribal, Civic Representation"]),
    Innovation("Public Assemblies", "Gatherings for civic input.", prerequisites=["Ceremonial Feasting"], cost=18, icon="🏛️", tags=["Tribal, Civic Representation"]),
]


# Global innovation registry
ALL_INNOVATIONS = {}
def register_innovations():
    for innovation_list in [
        LEADERSHIP_INNOVATIONS, MILITARY_INNOVATIONS, LEGISLATIVE_INNOVATIONS,
        JUDICIAL_INNOVATIONS, INTELLIGENCE_INNOVATIONS, ECONOMIC_INNOVATIONS,
        INFRASTRUCTURE_INNOVATIONS, RELIGIOUS_INNOVATIONS, CIVIC_REPRESENTATION_INNOVATIONS
    ]:
        for innovation in innovation_list:
            ALL_INNOVATIONS[innovation.name] = innovation
register_innovations()


class Player:
    def __init__(self, player_id, name, age, description, charisma, intelligence, strength, traits=None):
        self.id = player_id
        self.name = name
        self.age = age
        self.description = description
        self.charisma = charisma
        self.intelligence = intelligence
        self.strength = strength
        self.traits = traits or []
        self.assigned_roles = []

    def assign_role(self, role_name):
        if role_name not in self.assigned_roles:
            self.assigned_roles.append(role_name)

    def __str__(self):
        return (f"Player {self.name} (Age {self.age}) - {self.description} | "
                f"Stats: CHA {self.charisma}, INT {self.intelligence}, STR {self.strength} | "
                f"Roles: {', '.join(self.assigned_roles) or 'None'}")

# Static list of dummy test players
players = [
    Player(
        player_id=1,
        name="Alice",
        age=35,
        description="A strategic thinker with a calm demeanor.",
        charisma=7,
        intelligence=9,
        strength=5,
        traits=["rational", "diplomatic"]
    ),
    Player(
        player_id=2,
        name="Bob",
        age=42,
        description="A bold orator with a strong sense of justice.",
        charisma=9,
        intelligence=6,
        strength=6,
        traits=["passionate", "justice-driven"]
    ),
    Player(
        player_id=3,
        name="Cleo",
        age=28,
        description="A quiet tactician who prefers shadows over spotlight.",
        charisma=5,
        intelligence=8,
        strength=7,
        traits=["introverted", "calculating"]
    ),
    Player(
        player_id=4,
        name="Dmitri",
        age=50,
        description="An old warrior with deep roots in tradition.",
        charisma=6,
        intelligence=5,
        strength=9,
        traits=["conservative", "respected"]
    ),
]

# Helper to get player by name or ID
def get_player_by_name(name):
    for p in players:
        if p.name.lower() == name.lower():
            return p
    return None

def get_player_by_id(pid):
    for p in players:
        if p.id == pid:
            return p
    return None

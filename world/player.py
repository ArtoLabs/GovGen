

from world.character import Character, RULES
from world.items import STARTING_INVENTORY, Inventory


class Player(Character):
    """A member of the tribe: who they are (name, description, traits, who controls them) on top of a
    Character (attributes, skills, needs, health, age)."""

    def __init__(self, player_id, name, age, description="", attributes=None, skills=None, traits=None,
                 controller="npc", inventory=None, gender=None, birth_day=None, mother=None, born=None,
                 starting_items=True):
        super().__init__(age, attributes, skills)
        self.id = player_id
        self.controller = controller  # "human" or "npc"
        self.name = name
        self.description = description
        self.traits = traits or []
        # Life (core/life.py, data/rules/life.json): who they are born of, and what their body is going through.
        self.gender = gender if gender in RULES.genders else next(iter(RULES.genders), None)
        self.birth_day = int(birth_day if birth_day is not None else (17 + 53 * int(player_id)) % 300 + 30)  # day of the year
        self.mother = mother          # name of their mother, if known
        self.born = born              # game clock (hours) of their birth, None if born before the game
        self.illness = None           # {'key': illness key, 'since': clock} while ill
        self.pregnancy = None         # {'since': clock, 'due': clock} while pregnant
        self.last_birth = None        # clock of the last child she bore
        self.growth = {}              # childhood: attribute -> points gathered toward the next whole point
        self.satisfaction: dict = {}  # meters from data/rules/society.json, kept by core/society.py
        self.expectations: dict = {}  # what they have grown used to, per meter
        self.grievances: dict = {}    # meter -> points held against the tribe (being dismissed...), fading
        self.unrest: dict = {}        # meter -> cycle-hours it has been low (society.json 'patience')
        self.content_detail: dict = {}  # what moved each meter at the last update (for display only, not saved)
        self.inventory = Inventory()  # what they carry (world/items.py, data/rules/items.json)
        for stack in [*(STARTING_INVENTORY if starting_items else []), *(inventory or [])]:
            self.inventory.add(stack["item"], stack["count"])

    @property
    def bears_children(self) -> bool:
        return bool(RULES.genders.get(self.gender, {}).get("bears_children"))

    def roster_entry(self) -> dict:
        """Who this person is (saved, so a game keeps the people born and lost in it)."""
        return {"id": self.id, "name": self.name, "age": self.age, "description": self.description,
                "traits": list(self.traits), "controller": self.controller, "gender": self.gender,
                "birth_day": self.birth_day, "mother": self.mother, "born": self.born}

    @classmethod
    def from_roster(cls, e: dict) -> 'Player':
        return cls(player_id=e["id"], name=e["name"], age=e["age"], description=e.get("description", ""),
                   traits=e.get("traits", []), controller=e.get("controller", "npc"), gender=e.get("gender"),
                   birth_day=e.get("birth_day"), mother=e.get("mother"), born=e.get("born"), starting_items=False)

    # The three original stats, kept as names because older code and saves use them.
    @property
    def charisma(self) -> int:
        return self.attribute("charisma")

    @property
    def intelligence(self) -> int:
        return self.attribute("intelligence")

    @property
    def strength(self) -> int:
        return self.attribute("strength")

    def character_state(self):
        return {**super().character_state(), "satisfaction": dict(self.satisfaction),
                "expectations": dict(self.expectations), "grievances": dict(self.grievances),
                "unrest": dict(self.unrest), "inventory": self.inventory.to_list(),
                "illness": dict(self.illness) if self.illness else None,
                "pregnancy": dict(self.pregnancy) if self.pregnancy else None,
                "last_birth": self.last_birth, "growth": dict(self.growth)}

    def load_character_state(self, data):
        super().load_character_state(data)
        self.satisfaction.update(data.get("satisfaction", {}))
        self.expectations.update(data.get("expectations", {}))
        self.grievances.update(data.get("grievances", {}))
        self.unrest.update(data.get("unrest", {}))
        if "inventory" in data:  # older saves keep the starting inventory
            self.inventory.load(data["inventory"])
        self.illness = dict(data["illness"]) if data.get("illness") else None
        self.pregnancy = dict(data["pregnancy"]) if data.get("pregnancy") else None
        self.last_birth = data.get("last_birth")
        self.growth = dict(data.get("growth", {}))

    def __str__(self):
        stats = ", ".join(f"{RULES.attributes[k].abbr} {v}" for k, v in self.attributes.items())
        return f"Player {self.name} (Age {self.age}) - {self.description} | {stats}"

def load_players():
    """Players come from data/players.json; ids follow the order of the file."""
    from utils.data_files import DATA_DIR, load_json, require
    from world.items import check_stacks
    entries = load_json(DATA_DIR / "players.json").get("players", [])
    require(len(entries) >= 2, "players.json", "needs at least two players")
    names = [e.get("name") for e in entries]
    require(len(set(names)) == len(names), "players.json", "player names must be unique")
    loaded = []
    for i, e in enumerate(entries, 1):
        require(all(k in e for k in ("name", "age")), f"players.json player #{i}", "needs 'name' and 'age'")
        require(e.get("controller", "npc") in ("human", "npc"), f"players.json '{e['name']}'",
                "'controller' must be 'human' or 'npc'")
        require(e.get("gender") is None or e["gender"] in RULES.genders, f"players.json '{e['name']}'",
                f"'gender' must be one of {', '.join(RULES.genders)} (character.json 'genders')")
        require(e.get("mother") is None or e["mother"] in names, f"players.json '{e['name']}'",
                "'mother' must name another player")
        require(e.get("birthday") is None or 0 <= int(e["birthday"]) < 360, f"players.json '{e['name']}'",
                "'birthday' must be a day of the year, 0-359")
        attributes = dict(e.get("attributes", {}))
        for old in ("charisma", "intelligence", "strength"):  # older files listed these at the top level
            if old in e:
                attributes.setdefault(old, e[old])
        loaded.append(Player(
            player_id=i, name=e["name"], age=e["age"], description=e.get("description", ""),
            attributes=attributes, skills=e.get("skills", {}),
            traits=e.get("traits", []), controller=e.get("controller", "npc"),
            inventory=check_stacks(e.get("inventory", []), f"players.json '{e['name']}' inventory"),
            gender=e.get("gender"), birth_day=e.get("birthday"), mother=e.get("mother"),
        ))
    return loaded


players = load_players()  # data as loaded; each game builds its own fresh copies

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

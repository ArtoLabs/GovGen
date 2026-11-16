"""Items and inventories, defined by data/items.json.

Like world/character.py this knows nothing of governments, the engine or any display. An inventory is a
fixed number of slots; each slot is empty or holds a stack of one kind of item, up to that item's
'max_stack'. The camp ground is a simple pile (item -> count) with no limit.

Everything is plain data underneath (lists and dicts), so it saves as JSON and can later be mirrored by
an Unreal Engine inventory component.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.data_files import DATA_DIR, load_json, require

_data = load_json(DATA_DIR / "items.json")


@dataclass
class ItemDef:
    key: str
    name: str
    icon: str
    description: str
    max_stack: int = 1
    value: float = 1
    use: Dict[str, float] = field(default_factory=dict)  # need -> amount restored when used
    use_label: str = "Use"
    use_announce: str = "uses"
    kind: str = "material"   # food, water, material, tool, medicine
    breaks: float = 0.0      # tools: chance of breaking each time used for work
    counts_as: List[str] = field(default_factory=list)  # lesser items this one stands in for (a better version)
    uses: int = 0            # tools: how many times it can be used before it is worn out (0 = no wear)

    @property
    def is_tool(self) -> bool:
        return self.kind == "tool"


ITEMS: Dict[str, ItemDef] = {}
for _key, _d in _data.get("items", {}).items():
    require("name" in _d, f"items.json item '{_key}'", "needs a 'name'")
    require(int(_d.get("max_stack", 1)) >= 1, f"items.json item '{_key}'", "'max_stack' must be at least 1")
    ITEMS[_key] = ItemDef(_key, _d["name"], _d.get("icon", "•"), _d.get("description", ""),
                          int(_d.get("max_stack", 1)), float(_d.get("value", 1)), dict(_d.get("use", {})),
                          _d.get("use_label", "Use"), _d.get("use_announce", f"uses {_d['name'].lower()}"),
                          _d.get("kind", "material"), float(_d.get("tool", {}).get("breaks", 0)),
                          list(_d.get("counts_as", [])), int(_d.get("tool", {}).get("uses", 0)))
    require(not ITEMS[_key].uses or ITEMS[_key].max_stack == 1, f"items.json item '{_key}'",
            "a tool with 'uses' (wear) must have 'max_stack' 1")
    for _need in ITEMS[_key].use:
        require(_need == "health" or _need in __import__("world.character", fromlist=["RULES"]).RULES.needs,
                f"items.json item '{_key}'", f"'use' names unknown need '{_need}'")

for _key, _item in ITEMS.items():
    for _other in _item.counts_as:
        require(_other in ITEMS and _other != _key, f"items.json item '{_key}'",
                f"'counts_as' names unknown item '{_other}'")


def substitutes(item: str) -> List[str]:
    """`item` and the items that can stand in for it ('counts_as'), better versions first."""
    return [k for k, d in ITEMS.items() if item in d.counts_as] + [item]


BARTER_REQUIRES: List[str] = list(_data.get("barter_requires", []))
CAMP_SUMMARY: List[Dict[str, Any]] = list(_data.get("camp_summary", {}).get("groups", []))
for _g in CAMP_SUMMARY:
    for _k in _g.get("items", []):
        require(_k in ITEMS, "items.json camp_summary", f"unknown item '{_k}'")


def camp_summary(store: Dict[str, int]) -> List[Dict[str, Any]]:
    """The top bar's groups (items.json 'camp_summary') with how many of each the store holds."""
    out = []
    for g in CAMP_SUMMARY:
        keys = {k for k, d in ITEMS.items() if d.kind in g.get("kinds", [])} | set(g.get("items", []))
        out.append({"label": g["label"], "icon": g.get("icon", "•"), "count": sum(store.get(k, 0) for k in keys),
                    "empty_warning": bool(g.get("empty_warning", False))})
    return out


SLOTS: int = int(_data.get("inventory", {}).get("slots", 16))
COLUMNS: int = int(_data.get("inventory", {}).get("columns", 4))
OFFER_LIFE_HOURS: float = float(_data.get("trade_offer_life_hours", 2))
KEEPING: Dict[str, float] = _data.get("keeping", {})
require(SLOTS >= 1 and COLUMNS >= 1, "items.json", "'inventory' needs at least one slot and one column")


def _stacks(entries: List[Dict[str, Any]], where: str) -> List[Dict[str, Any]]:
    for e in entries:
        require(e.get("item") in ITEMS, where, f"unknown item '{e.get('item')}' (see items.json 'items')")
        require(int(e.get("count", 1)) >= 1, where, "'count' must be at least 1")
    return [{"item": e["item"], "count": int(e.get("count", 1))} for e in entries]


STARTING_INVENTORY = _stacks(_data.get("starting_inventory", []), "items.json 'starting_inventory'")
CAMP_STORE = _stacks(_data.get("camp_store", _data.get("camp_ground", [])), "items.json 'camp_store'")


def restoring(need: str) -> List[str]:
    """Items whose use restores `need` (what people eat for 'food', drink for 'water'), least valuable first."""
    return sorted((k for k, i in ITEMS.items() if i.use.get(need, 0) > 0), key=lambda k: ITEMS[k].value / ITEMS[k].use[need])


def food_variety(inventory: 'Inventory') -> int:
    """How many different kinds of food (items whose use restores food) someone carries."""
    return sum(1 for k, n in inventory.totals().items() if n > 0 and ITEMS[k].use.get("food", 0) > 0)


def check_stacks(entries: List[Dict[str, Any]], where: str) -> List[Dict[str, Any]]:
    """Validate a list of {item, count} from a data file (players.json 'inventory'...)."""
    return _stacks(entries, where)


def describe(stacks: List[Dict[str, Any]]) -> str:
    """'3 Stone and 1 Meat'."""
    parts = [f"{s['count']} {ITEMS[s['item']].name}" for s in stacks]
    return " and ".join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + " and " + parts[-1]


class Inventory:
    """A fixed row of slots. slots[i] is None or {'item': key, 'count': n}."""

    def __init__(self, size: int = SLOTS):
        self.slots: List[Optional[Dict[str, Any]]] = [None] * size

    # ------------------------------------------------------------------ #
    # Reading
    # ------------------------------------------------------------------ #
    def count(self, item: str) -> int:
        return sum(s["count"] for s in self.slots if s and s["item"] == item)

    def room_for(self, item: str) -> int:
        """How many more of `item` would fit."""
        cap = ITEMS[item].max_stack
        return sum(cap - s["count"] if s and s["item"] == item else cap if s is None else 0 for s in self.slots)

    def free_slots(self) -> int:
        return sum(1 for s in self.slots if s is None)

    def totals(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for s in self.slots:
            if s:
                out[s["item"]] = out.get(s["item"], 0) + s["count"]
        return out

    def valid_slot(self, i: Any) -> bool:
        return isinstance(i, int) and 0 <= i < len(self.slots)

    # ------------------------------------------------------------------ #
    # Changing
    # ------------------------------------------------------------------ #
    def add(self, item: str, count: int, uses: Optional[int] = None) -> int:
        """Put `count` of `item` in: topping up existing stacks first, then empty slots. Returns how many
        did not fit. A tool that wears out keeps its uses left on its slot ('uses': new if not given)."""
        cap = ITEMS[item].max_stack
        for s in self.slots:
            if count and s and s["item"] == item and s["count"] < cap:
                n = min(count, cap - s["count"])
                s["count"] += n
                count -= n
        for i, s in enumerate(self.slots):
            if count and s is None:
                n = min(count, cap)
                self.slots[i] = {"item": item, "count": n}
                if ITEMS[item].uses:
                    self.slots[i]["uses"] = ITEMS[item].uses if uses is None else int(uses)
                count -= n
        return count

    def pop_uses(self, item: str) -> Optional[int]:
        """Take one worn tool of `item` out (the most worn first); returns its uses left (None: none here)."""
        held = [i for i, s in enumerate(self.slots) if s and s["item"] == item]
        if not held:
            return None
        i = min(held, key=lambda j: self.slots[j].get("uses", ITEMS[item].uses))
        uses = self.slots[i].get("uses")
        self.take_from(i, 1)
        return uses

    def wear_slot(self, item: str) -> Optional[int]:
        """The slot of the `item` tool that gets used for work: the most worn one."""
        held = [i for i, s in enumerate(self.slots) if s and s["item"] == item]
        return min(held, key=lambda j: self.slots[j].get("uses", ITEMS[item].uses)) if held else None

    def take(self, item: str, count: int) -> bool:
        """Remove `count` of `item` from wherever it is (last slots first). False (and nothing taken) if
        there isn't that much."""
        if self.count(item) < count:
            return False
        for i in range(len(self.slots) - 1, -1, -1):
            s = self.slots[i]
            if count and s and s["item"] == item:
                n = min(count, s["count"])
                s["count"] -= n
                count -= n
                if s["count"] == 0:
                    self.slots[i] = None
        return True

    def take_from(self, slot: int, count: int) -> Optional[Dict[str, Any]]:
        """Remove up to `count` from one slot; returns what was removed, or None if the slot is empty."""
        s = self.slots[slot]
        if not s:
            return None
        n = max(1, min(count, s["count"]))
        s["count"] -= n
        if s["count"] == 0:
            self.slots[slot] = None
        out = {"item": s["item"], "count": n}
        if "uses" in s:
            out["uses"] = s["uses"]
        return out

    def move(self, src: int, dst: int, count: Optional[int] = None) -> bool:
        """Move a stack (or `count` of it) from one slot to another: into an empty slot, onto the same
        kind of item (as many as fit), or swapping places with a different item (whole stacks only)."""
        if src == dst or not self.slots[src]:
            return False
        a, b = self.slots[src], self.slots[dst]
        n = a["count"] if count is None else max(1, min(count, a["count"]))
        if b is None:
            self.slots[dst] = {**a, "count": n}
        elif b["item"] == a["item"]:
            n = min(n, ITEMS[a["item"]].max_stack - b["count"])
            if n <= 0:
                return False
            b["count"] += n
        else:
            if n != a["count"]:
                return False  # can't put part of a stack on a different item
            self.slots[src], self.slots[dst] = b, a
            return True
        a["count"] -= n
        if a["count"] == 0:
            self.slots[src] = None
        return True

    def sort(self):
        """Tidy up: merge stacks of the same item and pack them to the front, in items.json order."""
        worn = [s for s in self.slots if s and ITEMS[s["item"]].uses]  # tools keep their own wear
        totals = {k: n for k, n in self.totals().items() if not ITEMS[k].uses}
        self.slots = [None] * len(self.slots)
        order = list(ITEMS)
        for key in ITEMS:
            if key in totals:
                self.add(key, totals[key])
        for s in sorted(worn, key=lambda x: order.index(x["item"])):
            self.slots[self.slots.index(None)] = dict(s)
        tail = [s for s in self.slots if s]
        tail.sort(key=lambda x: order.index(x["item"]))
        self.slots = tail + [None] * (len(self.slots) - len(tail))

    # ------------------------------------------------------------------ #
    # Data
    # ------------------------------------------------------------------ #
    def copy(self) -> 'Inventory':
        inv = Inventory(len(self.slots))
        inv.slots = [dict(s) if s else None for s in self.slots]
        return inv

    def to_list(self) -> List[Optional[Dict[str, Any]]]:
        return [dict(s) if s else None for s in self.slots]

    def load(self, slots: List[Optional[Dict[str, Any]]]):
        self.slots = [None] * len(self.slots)
        for i, s in enumerate(slots[:len(self.slots)]):
            if s and s.get("item") in ITEMS and s.get("count", 0) > 0:
                self.slots[i] = {"item": s["item"], "count": int(s["count"])}
                if ITEMS[s["item"]].uses:
                    self.slots[i]["uses"] = int(s.get("uses", ITEMS[s["item"]].uses))

    def observe(self) -> Dict[str, Any]:
        return {"slots": self.to_list(), "size": len(self.slots), "columns": COLUMNS,
                "free": self.free_slots()}


def pile_add(pile: Dict[str, int], item: str, count: int):
    pile[item] = pile.get(item, 0) + count


def pile_list(pile: Dict[str, int]) -> List[Dict[str, Any]]:
    """The ground as a list of stacks, in items.json order."""
    return [{"item": k, "count": pile[k]} for k in ITEMS if pile.get(k, 0) > 0]

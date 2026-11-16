"""Where the game's data lives, and how the ages lay it out.

    data/settings.json            how the program runs (speed, seed...)
    data/players.json             the people a new game starts with
    data/rules/<name>.json        how things work in every age (character, time, society, work, life...)
    data/ages/<age>/              everything that belongs to one age:
        age.json                  its place in the order, what opens it, what it calls things, the store panel
        innovations.json          what can be researched in it, and what each costs
        items.json                its things
        occupations/<job>.json    one file per occupation: who may do it, and all of its work (tasks, recipes)
        work.json                 work that is nobody's occupation (offices' work, work open to anyone)
        governments/<key>.json    its forms of government, with their offices
        rules/<name>.json         this age's changes to data/rules/<name>.json

The engine asks this module for "every age's occupations", "the rules in force now" and so on; no other code
knows the folder layout. Adding an age is adding a folder.

Content (innovations, items, occupations, work, governments) adds up: a later age keeps what earlier ages had
and adds its own. Rules are layered: data/rules/<name>.json, then the 'rules/<name>.json' of every age reached,
in order, then the current government's "rules": {"<name>": {...}}. The rule files in SWITCHABLE change this
way while a game runs; the few others (time, items, occupations, interfaces) are read once, and an age that
tries to override one is refused with a clear message, so nothing is silently ignored.

How a rule file switches: the module that owns it (core/society.py for 'society', controllers/npc.py for
'npc'...) calls switchable(name, base, apply) once. A game keeps a RuleSet for its ages and government and
calls use() before it does or shows anything; use() hands each module the table now in force, and the module
puts it into its own tables in place, so every reader of those tables follows the age without knowing it.
"""
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.data_files import DATA_DIR, DataError, load_json, require

RULES_DIR = DATA_DIR / "rules"
AGES_DIR = DATA_DIR / "ages"
# Rule files an age or a government may change while the game runs.
SWITCHABLE = ("work", "life", "society", "npc", "contests", "character", "world")
DEFAULT_TERMS = {"society": "society", "members": "Members", "member": "Member", "store": "Store",
                 "store_name": "store", "home": "home"}


@dataclass
class AgeFolder:
    key: str
    path: Path
    data: Dict[str, Any]

    @property
    def order(self) -> float:
        return self.data.get("order", 0)


def public(d: Dict[str, Any]) -> Dict[str, Any]:
    """A data table without its '_comment' entries."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    """Lay `over` onto `base` (in place): objects merge key by key, anything else is replaced."""
    for k, v in over.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def _find_ages() -> List[AgeFolder]:
    if not AGES_DIR.is_dir():
        raise DataError(f"Missing data folder: {AGES_DIR}")
    found = []
    for folder in sorted(p for p in AGES_DIR.iterdir() if p.is_dir()):
        data = load_json(folder / "age.json")
        where = f"ages/{folder.name}/age.json"
        require("name" in data, where, "needs a 'name'")
        require(isinstance(data.get("order"), (int, float)), where, "needs an 'order' (a number: ages come in this order)")
        found.append(AgeFolder(folder.name, folder, data))
    require(bool(found), "data/ages", "needs at least one age folder with an age.json")
    found.sort(key=lambda a: (a.order, a.key))
    for a, b in zip(found, found[1:]):
        require(a.order != b.order, f"ages/{b.key}/age.json", f"has the same 'order' as '{a.key}'")
    return found


AGE_FOLDERS: List[AgeFolder] = _find_ages()
AGE_KEYS: List[str] = [a.key for a in AGE_FOLDERS]


def where(path: Path) -> str:
    """A file's place under data/, for messages ('ages/tribal/occupations/scout.json')."""
    try:
        return str(path.relative_to(DATA_DIR))
    except ValueError:
        return path.name


def rules(name: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """data/rules/<name>.json: the rules as they are in every age (before any age's changes)."""
    path = RULES_DIR / f"{name}.json"
    if not path.exists() and default is not None:
        return default
    return load_json(path)


def age_file(age: AgeFolder, name: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """(where, data) of one age's <name>.json, or None if the age has none."""
    path = age.path / f"{name}.json"
    return (where(path), load_json(path)) if path.exists() else None


def age_files(name: str) -> List[Tuple[AgeFolder, str, Dict[str, Any]]]:
    """Every age's <name>.json, in the order of the ages: (age, where, data)."""
    out = []
    for age in AGE_FOLDERS:
        found = age_file(age, name)
        if found:
            out.append((age, *found))
    return out


def age_folder_files(subfolder: str) -> List[Tuple[AgeFolder, str, Dict[str, Any]]]:
    """Every .json in every age's <subfolder>/ ('occupations', 'governments'): (age, where, data)."""
    out = []
    for age in AGE_FOLDERS:
        folder = age.path / subfolder
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            out.append((age, where(path), load_json(path)))
    return out


_age_rules_read: Dict[str, Dict[str, Dict[str, Any]]] = {}


def age_rules(name: str) -> Dict[str, Dict[str, Any]]:
    """Each age's changes to data/rules/<name>.json: {age key: overrides}."""
    if name in _age_rules_read:
        return _age_rules_read[name]
    out = _age_rules_read[name] = {}
    for age in AGE_FOLDERS:
        path = age.path / "rules" / f"{name}.json"
        if path.exists():
            require(name in SWITCHABLE, where(path),
                    f"an age can't change the '{name}' rules yet (it can change: {', '.join(SWITCHABLE)}); "
                    f"edit data/rules/{name}.json instead")
            out[age.key] = public(load_json(path))
    return out


for _age in AGE_FOLDERS:  # refuse rule files nothing would read
    for _path in sorted((_age.path / "rules").glob("*.json")) if (_age.path / "rules").is_dir() else []:
        age_rules(_path.stem)

GOVERNMENT_RULES: Dict[str, Dict[str, Dict[str, Any]]] = {}  # government key -> rule file -> overrides


def register_government_rules(key: str, overrides: Dict[str, Any], file: str):
    """A government file's "rules": {"work": {...}, "life": {...}} (core/government_types.py reports them)."""
    for name in public(overrides):
        require(name in SWITCHABLE, file, f"'rules' can't change '{name}' yet (it can change: {', '.join(SWITCHABLE)})")
    GOVERNMENT_RULES[key] = {k: public(v) for k, v in public(overrides).items()}


def rules_in_force(name: str, age_keys: List[str], government_key: Optional[str] = None,
                   base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The <name> rules as they stand now: the base, then each age reached (oldest first), then the government."""
    r = copy.deepcopy(base if base is not None else rules(name))
    by_age = age_rules(name)
    for key in age_keys:
        merge(r, by_age.get(key, {}))
    if government_key:
        merge(r, GOVERNMENT_RULES.get(government_key, {}).get(name, {}))
    return r


def inherited(field: str, age_keys: List[str], default: Any = None) -> Any:
    """An age.json value that later ages keep unless they set their own ('store_panel'): the latest one given."""
    by_key = {a.key: a.data for a in AGE_FOLDERS}
    for key in reversed(age_keys):
        if field in by_key.get(key, {}):
            return by_key[key][field]
    return default


def terms(age_keys: List[str], government_terms: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """What things are called now: the defaults, each age reached, then the government's own words."""
    out = dict(DEFAULT_TERMS)
    by_key = {a.key: a.data for a in AGE_FOLDERS}
    for key in age_keys:
        out.update(public(by_key.get(key, {}).get("terms", {})))
    out.update(public(government_terms or {}))
    return out


# --------------------------------------------------------------------------- #
# Rules that switch with the age and the government
# --------------------------------------------------------------------------- #
_switch: Dict[str, Tuple[Dict[str, Any], Callable[[Dict[str, Any]], None]]] = {}  # name -> (base, apply)
_in_force: Dict[str, Dict[str, Any]] = {}  # name -> the table its module is using now


def switchable(name: str, base: Dict[str, Any], apply: Callable[[Dict[str, Any]], None],
               check: Optional[Callable[[Dict[str, Any], str], None]] = None):
    """A module says: these are my rules as they are in every age (`base`, already in use), and `apply(table)`
    puts another table in force. Every age's version is tried once here (apply, and `check` if given), so a
    mistake in an age's override stops the program at startup, naming the file, not years into a game."""
    require(name in SWITCHABLE, f"rules '{name}'", "is not in game_data.SWITCHABLE")
    _switch[name] = (base, apply)
    _in_force[name] = base
    by_age = age_rules(name)
    try:
        for i, key in enumerate(AGE_KEYS):
            if key in by_age:
                table = rules_in_force(name, AGE_KEYS[:i + 1], None, base)
                if check:
                    check(table, f"ages/{key}/rules/{name}.json")
                apply(table)
        for gov_key, by_name in GOVERNMENT_RULES.items():
            if name in by_name:
                apply(rules_in_force(name, AGE_KEYS[:1], gov_key, base))
    finally:
        if by_age or any(name in by_name for by_name in GOVERNMENT_RULES.values()):
            apply(base)


def all_versions(name: str, base: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The <name> rules as they stand at each age, oldest first (for 'is this known in any age?' checks)."""
    by_age = age_rules(name)
    return [rules_in_force(name, AGE_KEYS[:i + 1], None, base) if any(k in by_age for k in AGE_KEYS[:i + 1]) else base
            for i in range(len(AGE_KEYS))]


class RuleSet:
    """The rules in force for one game: for every switchable rule file, the table for the ages it has reached
    and its government. Where nothing overrides a file the table IS the base table, so games in the same
    situation share it and nothing is rebuilt."""

    def __init__(self, age_keys: List[str], government_key: Optional[str] = None):
        self.age_keys, self.government_key = list(age_keys), government_key
        self.tables: Dict[str, Dict[str, Any]] = {}
        for name, (base, _apply) in _switch.items():
            by_age = age_rules(name)
            changed = any(k in by_age for k in age_keys) or name in GOVERNMENT_RULES.get(government_key or "", {})
            self.tables[name] = rules_in_force(name, age_keys, government_key, base) if changed else base

    def __getitem__(self, name: str) -> Dict[str, Any]:
        return self.tables[name]

    def use(self):
        """Make these the rules every module works with (cheap when they already are)."""
        for name, table in self.tables.items():
            if _in_force.get(name) is not table:
                _switch[name][1](table)
                _in_force[name] = table


def fill(table: Dict[str, Any], values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Replace a module table's contents in place (so everything holding the table sees the change)."""
    values = dict(values or {})
    table.clear()
    table.update(values)
    return table

"""A human playing at this terminal. All menus are built from the engine's legal actions.

While other players act, events print as they happen at the game's playback speed. When it is your
moment to act the game pauses until you choose; every action takes some game time, and "Wait" lets
time pass.
"""
from typing import Any, Callable, Dict, List, Optional, Tuple

from controllers.base import Controller, Decision
from core.actions import Action
from core.calendar import ACTION_HOURS, format_duration
from core.interfaces import ROLE_COMMANDS, unlock_note
from innovations.innovation import ALL_INNOVATIONS, AGES_BY_KEY, INTERFACE_ICONS
from innovations.innovation_map import ROLE_INNOVATION_MAP
from utils.messages import Message, Messages
from utils.utils import choose_from_list

QUIT = object()
RED, CYAN, BOLD, RESET = "\033[91m", "\033[96m", "\033[1m", "\033[0m"


def _with_cancel(options: list, prompt: str, display: Callable = str):
    return choose_from_list(list(options) + [None], prompt, lambda o: "Cancel" if o is None else display(o))


def _pause():
    input("Press Enter to continue...")


def _takes(action_type: str) -> str:
    return f" ({format_duration(ACTION_HOURS.get(action_type, 1))})"


class ConsolePrinter:
    """Prints game events as they happen (used when watching NPC-only games)."""

    def __init__(self, detail: str = "full"):
        self.detail = detail

    def notify(self, messages: List[Message]):
        text = Messages.format(messages, self.detail)
        if text:
            print(text, flush=True)


class TerminalController(Controller):
    is_human = True

    def __init__(self, name: str, detail: str = "full", pacer=None):
        self.name = name
        self.detail = detail
        self.pacer = pacer  # lets the player change playback speed from the menu
        self.open_interface: Optional[str] = None

    def notify(self, messages: List[Message]):
        text = Messages.format(messages, self.detail)
        if text:
            print(text, flush=True)

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": "human", "detail": self.detail}

    def load_state(self, data: Dict[str, Any]):
        if data and data.get("kind") == "human":
            self.detail = data.get("detail", self.detail)

    # ------------------------------------------------------------------ #
    def decide(self, view: Dict[str, Any], legal: List[Action]) -> Optional[Decision]:
        while True:
            print(self._status(view))
            items = self._menu(view, legal)
            for i, (key, desc, _) in enumerate(items, 1):
                print(f"  {i}: {desc}")
            positions = ", ".join(view["your_positions"]) or "Tribe member"
            raw = input(f"\n{BOLD}{view['date']}{RESET} - {view['you']} ({positions}) > ").strip().lower()
            if raw.isdigit() and 1 <= int(raw) <= len(items):
                handler = items[int(raw) - 1][2]
            else:
                handler = next((h for k, _, h in items if k == raw), None)
            if handler is None:
                print(f"{RED}Unknown command.{RESET}")
                continue
            result = handler()
            if result is QUIT:
                return None
            if isinstance(result, Decision):
                return result

    # ------------------------------------------------------------------ #
    # Screen
    # ------------------------------------------------------------------ #
    def _status(self, v: Dict[str, Any]) -> str:
        gov = v["government"]
        if v["next_age"]:
            needs = ", ".join(f"{n} {'[X]' if done else '[ ]'}" for n, done in v["next_age"]["needs"].items())
            next_line = f"Next age: {v['next_age']['name']} - needs {needs}"
        else:
            next_line = "Next age: none yet - this is the latest age in the game data"
        reforms = ", ".join(r["name"] for r in gov["available_reforms"]) or "none yet"
        if gov["available_reforms"] and gov["reform_cooldown_days"]:
            reforms += f" (no reform for {gov['reform_cooldown_days']} more days)"
        r = v["researching"]
        research = (f"{r['innovation']} {r['points']}/{r['cost']} points" if r else "nothing")
        if len(v["research_queue"]) > 1:
            research += f" (then {', '.join(v['research_queue'][1:])})"
        lines = [
            "\n__________________________________",
            f"{BOLD}{v['date']}{RESET} | {v['age']['name']} | Innovation points: {v['points']} (+{v['points_per_year']} a year)",
            f"Government: {gov['name']} | Possible governments: {reforms}",
            next_line,
            f"Researching: {research}",
            f"Discovered ({len(v['discovered'])}): {', '.join(v['discovered'])}",
            "__________________________________",
        ]
        ballots = []
        for b in v["ballots"]:
            if b["nominating"]:
                ballots.append(f"  Nominations for {b['label']} until {b['closes']}: {', '.join(b['nominations']) or 'none yet'}")
            elif b["voting"]:
                mine = " (you voted)" if b["you_voted"] else (" (you may vote)" if b["you_can_vote"] else "")
                ballots.append(f"  Voting on {b['label']} until {b['closes']} ({', '.join(b['choices'])}) - "
                               f"{b['votes_cast']}/{b['electorate_size']} voted{mine}")
        if ballots:
            lines += [f"{CYAN}Elections and Votes:", *ballots, f"__________________________________{RESET}"]
        return "\n".join(lines)

    def _menu(self, v: Dict[str, Any], legal: List[Action]) -> List[Tuple[str, str, Callable]]:
        by_type: Dict[str, List[Action]] = {}
        for a in legal:
            by_type.setdefault(a.type, []).append(a)
        items: List[Tuple[str, str, Callable]] = [
            ("list_players", "Show all players, their positions and stats", lambda: self._list_players(v)),
            ("list_roles", "Show this government's offices", lambda: self._list_roles(v)),
            ("list_innovations", "Show innovations by role", lambda: self._list_innovations(v)),
        ]
        if v["your_interfaces"]:
            items.append(("open_role_interface", "Open a role interface", lambda: self._open_interface(v)))

        seen = []
        for a in by_type.get("vote", []):
            if a.params["ballot"] not in seen:
                seen.append(a.params["ballot"])
                ballot = next(b for b in v["ballots"] if b["key"] == a.params["ballot"])
                acts = [x for x in by_type["vote"] if x.params["ballot"] == ballot["key"]]
                items.append((f"vote:{ballot['key']}",
                              f"Vote on {ballot['label']} ({', '.join(ballot['choices'])}){_takes('vote')}",
                              lambda b=ballot, acts=acts: self._vote(b, acts)))
        simple = [
            ("nominate", "Nominate a candidate for an office", "Nominate for which office?", "Nominate:"),
            ("decline_nomination", "Decline your nomination (or withdraw from a vote)", None, "Decline:"),
            ("appoint", "Appoint someone to a position you control", "Appoint to which position?", "Appoint:"),
            ("dismiss", "Remove someone from a position you control", "Remove from which position?", "Remove:"),
            ("call_vote", "Call a vote (remove an office holder, cast out a member...)", None, "Call a vote to:"),
        ]
        for key, desc, group_prompt, item_prompt in simple:
            if key in by_type:
                items.append((key, desc + _takes(key),
                              lambda acts=by_type[key], gp=group_prompt, ip=item_prompt: self._pick(acts, gp, ip)))
        if "reform" in by_type:
            decree = v["government"]["reform_mode"] == "decree"
            desc = "Reform the government by decree" if decree else "Call a vote to reform the government"
            items.append(("reform", desc + _takes("reform"), lambda: self._reform(v, by_type["reform"])))

        if self.open_interface and self.open_interface in v["your_interfaces"]:
            key = self.open_interface
            research = [a for a in by_type.get("research", []) if a.params["interface"] == key]
            if research:
                items.append(("research", f"[{key}] Research an innovation{_takes('research')}",
                              lambda acts=research: self._pick(acts, None, "Queue for research:")))
            for a in by_type.get("role_command", []):
                if a.params["interface"] == key:
                    items.append((a.params["command"], f"[{key}] {a.label}{_takes('role_command')}",
                                  lambda a=a: self._role_command(a)))
            items.append(("close_interface", f"[{key}] Close interface", self._close_interface))

        if "wait" in by_type:
            items.append(("wait", "Wait (let time pass)", lambda: self._pick(by_type["wait"], None, "Wait for:")))
        other = "summary" if self.detail == "full" else "full"
        items.append(("detail", f"Show NPC activity as: {other} (now: {self.detail})", self._toggle_detail))
        if self.pacer is not None:
            items.append(("speed", f"Playback speed: {self.pacer.describe()} (change)", self._change_speed))
        items.append(("exit", "Save and exit", lambda: QUIT))
        return items

    # ------------------------------------------------------------------ #
    # Choosing actions
    # ------------------------------------------------------------------ #
    def _pick(self, acts: List[Action], group_prompt: Optional[str], item_prompt: str) -> Optional[Decision]:
        groups = list(dict.fromkeys(a.group for a in acts))
        if group_prompt and len(groups) > 1:
            group = _with_cancel(groups, group_prompt)
            if group is None:
                return None
            acts = [a for a in acts if a.group == group]
        chosen = _with_cancel(acts, item_prompt, lambda a: a.label)
        return Decision(chosen) if chosen else None

    def _vote(self, ballot: Dict[str, Any], acts: List[Action]) -> Optional[Decision]:
        print(f"\n{ballot['label']} (voting closes {ballot['closes']})")
        if ballot["ranked"]:
            print("Candidates: " + ", ".join(ballot["choices"]))
            ranking = [c.strip() for c in input("Rank them, comma-separated: ").split(",") if c.strip()]
            first = next((a for a in acts if ranking and a.params["choice"] == ranking[0]), None)
            if first is None:
                print(f"{RED}Your first choice must be one of the candidates.{RESET}")
                return None
            return Decision(first.with_params(ranking=ranking))
        chosen = _with_cancel(acts, "Your vote:", lambda a: a.label)
        return Decision(chosen) if chosen else None

    def _reform(self, v: Dict[str, Any], acts: List[Action]) -> Optional[Decision]:
        gov = v["government"]
        print(f"Current government: {gov['name']} ({gov['age']}). Changed by {gov['reformed_by']}.")
        for r in gov["available_reforms"]:
            offices = ", ".join(f"{n} x{o['seats']}" if o["seats"] > 1 else n for n, o in r["offices"].items())
            print(f"  {r['name']} ({r['age']}): {r['description']}\n      Offices: {offices}\n"
                  f"      You would be: {r['outcome'].get(v['you']) or 'no office'}")
        prompt = "Reform by decree into:" if gov["reform_mode"] == "decree" else "Call a vote to reform into:"
        chosen = _with_cancel(acts, prompt, lambda a: a.label)
        return Decision(chosen) if chosen else None

    def _role_command(self, action: Action) -> Optional[Decision]:
        command = next(c for c in ROLE_COMMANDS[action.params["interface"]] if c.key == action.params["command"])
        text = input(f"{command.text_prompt}: ").strip()
        return Decision(action.with_params(text=text))

    def _open_interface(self, v: Dict[str, Any]):
        chosen = _with_cancel(v["your_interfaces"], "Open which interface?", lambda k: k.replace("_", " ").capitalize())
        if chosen:
            self.open_interface = chosen
        return None

    def _close_interface(self):
        self.open_interface = None
        return None

    def _toggle_detail(self):
        self.detail = "summary" if self.detail == "full" else "full"
        return None

    def _change_speed(self):
        self.pacer.next_speed()
        return None

    # ------------------------------------------------------------------ #
    # Information screens
    # ------------------------------------------------------------------ #
    def _list_players(self, v: Dict[str, Any]):
        for p in v["players"]:
            positions = ", ".join(p["offices"] + p["statuses"]) or "Tribe member"
            print(f"{p['name']} (Age {p['age']}) - {p['description']}\n"
                  f"    CHA {p['charisma']}, INT {p['intelligence']}, STR {p['strength']} | "
                  f"Traits: {', '.join(p['traits'])} | Positions: {positions}")
        _pause()

    def _list_roles(self, v: Dict[str, Any]):
        gov = v["government"]
        print(f"{gov['name']} ({gov['age']}) - {gov['description']}\nChanged by {gov['reformed_by']}.\n")
        for name, o in v["offices"].items():
            locked = "" if o["unlocked"] else f"  [needs {', '.join(o['requires'])}]"
            print(f"{name} ({len(o['holders'])}/{o['seats']}): {', '.join(o['holders']) or 'vacant'}{locked}")
            print(f"    {o['description']}\n    Chosen by {o['selected_by']}; removed by {o['removed_by']}")
            print(f"    Interfaces: {', '.join(o['interfaces'])}")
        for name, s in v["statuses"].items():
            locked = "" if s["unlocked"] else f"  [needs {', '.join(s['requires'])}]"
            print(f"{name} (status): {', '.join(s['holders']) or 'none'}{locked}")
            print(f"    {s['description']} Granted by {s['granted_by']}.")
        print(f"\nEvery member can use: {', '.join(gov['member_interfaces']) or 'nothing'}. "
              f"A player may hold {gov['max_offices_per_player']} office(s).")
        _pause()

    def _list_innovations(self, v: Dict[str, Any]):
        role = _with_cancel(sorted(INTERFACE_ICONS), "Select role to view innovations:", lambda r: r.capitalize())
        if role is None:
            return None
        discovered = set(v["discovered"])
        print(f"{role.capitalize()} Innovations:")
        for innov in sorted(ROLE_INNOVATION_MAP.get(role, []), key=lambda x: (x.age_index, x.name)):
            done = "[X]" if innov.name in discovered else ""
            age = AGES_BY_KEY[innov.age].name
            print(f"{innov.icon} {innov.name} {done} - {innov.description} [Cost: {innov.cost}, {age}]{unlock_note(innov.name)}")
            if innov.prerequisites:
                prereqs = ", ".join(f"{ALL_INNOVATIONS[p].icon}{p}" for p in sorted(innov.prerequisites))
                print(f"    Prerequisites: {prereqs}")
        _pause()
        return None

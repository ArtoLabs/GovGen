"""UI-neutral view model: turns the engine's observation and legal actions into things a screen shows.

Nothing here draws anything or reads input. The terminal HUD (ui/hud.py) uses it today; a graphical
client can use exactly the same functions later and only differ in how it paints them:

    action_groups(view, legal)   the action bar: one entry per kind of action, with its hotkey
                                 (ACTION_SECTIONS groups them: politics, leading, life)
    build_menu(group, view)      the picker tree behind one action (ballot -> choice, office -> person...)
    candidate_profile(view, ...) a person in a pick list: who they are and how well they'd do the job
    innovation_catalog(view)     every innovation in the game with its status for this tribe
    ballot_rows(view)            open nominations and votes, ready to list
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.actions import Action
from core.calendar import ACTION_HOURS, HOURS_PER_DAY
from world.environment import format_life_duration, life_hours_to_calendar
from core.interfaces import ROLE_COMMANDS, unlock_note
from innovations.innovation import ALL_INNOVATIONS, AGES, AGES_BY_KEY, INTERFACE_ICONS, reached_age_index
from world.character import RULES as CHARACTER
from world.items import ITEMS


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ActionKind:
    type: str      # engine action type
    hotkey: str    # one key, no Enter
    label: str     # short name for the action bar
    title: str     # longer name for the picker heading
    also: Tuple[str, ...] = ()  # other engine action types shown under the same key
    window: bool = False  # opens a window rather than a picker, so it is always available


# Order is the order on the action bar. "wait" is left out: in real time you simply don't act.
ACTION_KINDS: List[ActionKind] = [
    ActionKind("vote", "v", "Vote", "Vote"),
    ActionKind("nominate", "n", "Nominate", "Nominate a candidate", also=("decline_nomination",)),
    ActionKind("appoint", "a", "Appoint", "Appoint someone to a position you control"),
    ActionKind("dismiss", "d", "Dismiss", "Remove someone from a position, or release them from an appointment",
               also=("release",)),
    ActionKind("call_vote", "c", "Call vote", "Call a vote"),
    ActionKind("reform", "f", "Reform", "Reform the government"),
    ActionKind("research", "r", "Research", "Queue an innovation for research"),
    ActionKind("role_command", "o", "Orders", "Give an order from one of your roles"),
    ActionKind("care", "e", "Needs", "Look after yourself", also=("treat",)),
    ActionKind("take_occupation", "j", "Job", "Take up or give up a job", also=("leave_occupation",)),
    ActionKind("work", "w", "Work", "Do work: gather, hunt, craft... (children: play and study)",
               also=("craft", "activity", "heal")),
    ActionKind("stop", "x", "Wake/stop", "Stop what you are doing"),
    ActionKind("persuade", "p", "Persuade", "Persuade the tribe", also=("canvass", "rally")),
    ActionKind("challenge", "h", "Challenge", "Challenge an office holder", also=("answer_challenge",)),
    ActionKind("resign", "g", "Resign", "Give up an office you hold"),
    ActionKind("inventory", "i", "Inventory", "What you carry", window=True),
]
KIND_BY_TYPE = {k.type: k for k in ACTION_KINDS}

# How the action bar groups the kinds (each type appears once; every ACTION_KINDS type is listed).
ACTION_SECTIONS: List[Tuple[str, List[str]]] = [
    ("Politics", ["vote", "nominate", "call_vote", "reform", "persuade", "challenge", "resign"]),
    ("Leading", ["appoint", "dismiss", "role_command", "research"]),
    ("Life", ["care", "work", "take_occupation", "inventory", "stop"]),
]


@dataclass
class ActionGroup:
    kind: ActionKind
    actions: List[Action]

    @property
    def available(self) -> bool:
        return bool(self.actions) or self.kind.window

    @property
    def duration(self) -> str:
        """How long the action keeps you busy, in day-night time."""
        return format_life_duration(ACTION_HOURS.get(self.kind.type, 1))

    def duration_of(self, action: Action) -> str:
        if action.type in ("work", "craft"):
            from core.work import work
            t = work(action.type, action.params.get("task") or action.params.get("recipe"))
            return format_life_duration(life_hours_to_calendar(t.life_hours if t else 1))
        if action.type == "care":
            care = CHARACTER.care_actions[action.params["kind"]]
            return "a moment" if care.instant else format_life_duration(life_hours_to_calendar(care.life_hours))
        if action.type == "wait":
            return format_life_duration(action.params["days"] * HOURS_PER_DAY)
        if action.type in ("treat", "activity", "heal"):
            from core.life import BASE
            hours = BASE.get("treatment", {}).get("life_hours", 1) if action.type in ("treat", "heal") else \
                BASE.get("childhood", {}).get("activities", {}).get(action.params.get("activity"), {}).get("life_hours", 1.5)
            return format_life_duration(life_hours_to_calendar(hours))
        if action.type in ("persuade", "canvass", "rally", "challenge", "answer_challenge"):
            from core.contests import CHALLENGE_KINDS, PERSUASION
            kind = action.params.get("kind")
            from core.contests import DURING_CONTEST, SPEAK
            if action.type in ("challenge", "answer_challenge") and kind and \
                    DURING_CONTEST.get(CHALLENGE_KINDS[kind].style, {"locked": True}).get("locked"):
                hours = CHALLENGE_KINDS[kind].life_hours
            elif action.type in ("persuade", "challenge", "answer_challenge"):
                hours = PERSUASION.get("announce_life_hours", 0.25)
            elif action.params.get("speech"):
                hours = SPEAK.get("life_hours", 0.25)
            else:
                hours = PERSUASION.get(action.type, {}).get("life_hours", 0.5)
            return format_life_duration(life_hours_to_calendar(hours))
        return format_life_duration(ACTION_HOURS.get(action.type, 1))


def action_groups(view: Dict[str, Any], legal: List[Action]) -> List[ActionGroup]:
    """Every action kind, in action-bar order, with the legal actions of that kind (maybe none)."""
    by_type: Dict[str, List[Action]] = {}
    for a in legal:
        by_type.setdefault(a.type, []).append(a)
    return [ActionGroup(kind, [a for t in (kind.type, *kind.also) for a in by_type.get(t, [])]) for kind in ACTION_KINDS]


@dataclass
class MenuItem:
    label: str
    detail: str = ""                         # a second, dimmer line
    action: Optional[Action] = None          # choosing it takes this action...
    submenu: Optional['Menu'] = None         # ...or opens this menu
    text_prompt: Optional[str] = None        # the action needs free text first (a law's name...)
    ranked: Optional[List[str]] = None       # the action needs a ranking of these candidates first
    profile: Optional[Dict[str, Any]] = None  # the item is a person: candidate_profile() for the position
    profiles: Optional[Dict[str, Dict[str, Any]]] = None  # for `ranked`: each candidate's profile


@dataclass
class Menu:
    title: str
    items: List[MenuItem] = field(default_factory=list)
    note: str = ""


def candidate_profile(view: Dict[str, Any], name: str, position: Optional[str]) -> Optional[Dict[str, Any]]:
    """Who `name` is and how well they would do `position` (an office or an occupation), as plain data:
    a pick list shows it beside each person so you can compare candidates.

        fit          their work quality in the position (0-100), or None if it isn't a known position
        attributes   the attributes the position uses, most important first: abbr, name, value, weight
        skill        the skill the position uses: name, value (or None)
    """
    p = next((x for x in view["players"] if x["name"] == name), None)
    if p is None:
        return None
    if position in view["offices"]:
        o = view["offices"][position]
        weights = o.get("quality_attributes") or {}
        skill = o.get("quality_skill")
        fit = p.get("office_quality", {}).get(position)
        holds = name in o["holders"]
    elif position in view["occupations"]:
        occ = view["occupations"][position]
        weights = {a: 1.0 for a in occ["attributes"]}
        skill = occ["skill"]
        fit = p.get("occupation_quality", {}).get(position)
        holds = name in occ["holders"]
    else:
        weights, skill, fit, holds = {}, None, None, False
    # Where the position stands against their current work (society.json 'job_rank'): up pleases, down sours.
    ranks = [view["occupations"][o].get("rank", 0) for o in p["occupations"]] + \
            [view["offices"][o].get("rank", 0) for o in p.get("offices", []) if o in view["offices"]]
    new_rank = (view["offices"].get(position) or view["occupations"].get(position) or {}).get("rank")
    move = None if new_rank is None or holds else new_rank - max(ranks, default=0)
    attrs = [{"key": k, "abbr": CHARACTER.attributes[k].abbr, "name": CHARACTER.attributes[k].name,
              "value": p[k], "weight": w}
             for k, w in sorted(weights.items(), key=lambda kv: -kv[1]) if k in CHARACTER.attributes]
    return {
        "name": name, "you": name == view["you"], "age": p["age"], "life_stage": p["sheet"]["life_stage"],
        "description": p["description"], "traits": list(p["traits"]),
        "positions": positions_of(p), "occupations": list(p["occupations"]),
        "occupation_icons": occupation_icons(view, p), "doing": p.get("doing"),
        "position": position, "fit": fit, "holds_it": holds, "attributes": attrs,
        "skill": None if not skill else {"key": skill, "name": CHARACTER.skills[skill].name if skill in CHARACTER.skills
                                         else skill, "value": p["sheet"]["skills"].get(skill, 0.0)},
        "mood": p.get("mood"),
        "rank_move": move,  # >0 a step up (they'd welcome it), <0 a step down (they'd resent it), 0 the same
    }


def _ballot_office(view: Dict[str, Any], ballot_key: str) -> Optional[str]:
    """The office an election fills (None for a motion)."""
    b = next((b for b in view["ballots"] if b["key"] == ballot_key), {})
    return b.get("office") if b.get("kind") == "election" else None


def _grouped(title: str, actions: List[Action], make_item, note: str = "") -> Menu:
    """One level per action.group if there is more than one group, then one item per action."""
    groups = list(dict.fromkeys(a.group for a in actions))
    if len(groups) <= 1:
        return Menu(f"{title}: {groups[0]}" if groups and groups[0] else title, [make_item(a) for a in actions], note)
    return Menu(title, [MenuItem(g, submenu=Menu(g, [make_item(a) for a in actions if a.group == g], note))
                        for g in groups], note)


def build_menu(group: ActionGroup, view: Dict[str, Any]) -> Menu:
    """The picker tree for one action kind."""
    kind, acts = group.kind, group.actions
    note = f"Takes {group.duration}."
    if kind.type == "vote":
        ballots = {b["key"]: b for b in view["ballots"]}
        items = []
        for key in dict.fromkeys(a.params["ballot"] for a in acts):
            b = ballots[key]
            choices = [a for a in acts if a.params["ballot"] == key]
            detail = f"closes {b['closes']} ({b['days_left']} days) - {b['votes_cast']}/{b['electorate_size']} voted"
            office = _ballot_office(view, key)
            if b["ranked"]:
                profiles = {c: candidate_profile(view, c, office) for c in b["choices"]} if office else None
                items.append(MenuItem(b["label"], detail, action=choices[0], ranked=list(b["choices"]),
                                      profiles=profiles))
            else:
                items.append(MenuItem(b["label"], detail, submenu=Menu(
                    f"Vote: {b['label']}" if office else b["label"],
                    [MenuItem(a.label, action=a, profile=candidate_profile(view, a.label, office) if office else None)
                     for a in choices], note)))
        if len(items) == 1 and items[0].submenu:
            return items[0].submenu
        return Menu("Vote on which ballot?", items, note)
    if kind.type == "reform":
        reforms = {r["key"]: r for r in view["government"]["available_reforms"]}
        decree = view["government"]["reform_mode"] == "decree"

        def reform_item(a: Action) -> MenuItem:
            r = reforms.get(a.params["government"], {})
            offices = ", ".join(f"{n} x{o['seats']}" if o["seats"] > 1 else n for n, o in r.get("offices", {}).items())
            you = r.get("outcome", {}).get(view["you"]) or "no office"
            return MenuItem(a.label, f"{r.get('description', '')}\nOffices: {offices}. You would be: {you}", action=a)
        return Menu("Reform by decree into:" if decree else "Call a vote to reform into:",
                    [reform_item(a) for a in acts], note)
    if kind.type == "research":
        def research_item(a: Action) -> MenuItem:
            innov = ALL_INNOVATIONS.get(a.params["innovation"])
            detail = innov.description if innov else ""
            return MenuItem(a.label, detail, action=a)
        return _grouped(kind.title, acts, research_item, note)
    if kind.type == "role_command":
        def command_item(a: Action) -> MenuItem:
            cmd = next(c for c in ROLE_COMMANDS[a.params["interface"]] if c.key == a.params["command"])
            return MenuItem(f"[{a.group.replace('_', ' ')}] {a.label}", action=a, text_prompt=cmd.text_prompt)
        return Menu(kind.title, [command_item(a) for a in acts], note)
    if kind.type == "care":
        needs = view["character"]["needs"]

        def care_item(a: Action) -> MenuItem:
            if a.type == "treat":
                return MenuItem(a.label, treat_detail(view) + f" · takes {group.duration_of(a)}", action=a)
            care = CHARACTER.care_actions[a.params["kind"]]
            parts = [f"{CHARACTER.needs[n].name} +{amt:g} (now {needs[n]['label'].lower()})" for n, amt in care.restores.items()]
            bonus = "  (by the fire)" if care.needs_amenity == "fire" else ""
            if care.consumes:
                bonus += "  · uses food or water from your own inventory"
            return MenuItem(care.label, f"{'; '.join(parts)} · takes {group.duration_of(a)}{bonus}", action=a)
        camp = view.get("camp", {})
        missing = [w for w, k in (("food", "eat"), ("water", "drink"))
                   if k in CHARACTER.care_actions and not any(a.params["kind"] == k for a in acts)]
        note = ""
        if missing and camp:
            note = (f"Sorry, you can't {' or '.join('eat' if m == 'food' else 'drink' for m in missing)} right now: "
                    f"you have no {' or '.join(missing)} in your inventory. Take some from the camp store first "
                    f"(I opens your inventory, Tab switches to the store).")
        return Menu("Look after yourself", [care_item(a) for a in acts], note)
    if kind.type == "work":
        return _work_menu(group, view)
    if kind.type == "take_occupation":
        items = []
        for a in acts:
            name = a.params["occupation"]
            occ = view["occupations"][name]
            if a.type == "leave_occupation":
                items.append(MenuItem(a.label, f"Takes {group.duration_of(a)}.", action=a))
            else:
                skill = f"; trains {occ['skill']}" if occ["skill"] else ""
                items.append(MenuItem(f"{occ['icon']} Become a {name}", f"{occ['description']} (suits "
                                      f"{', '.join(occ['attributes'])}{skill}) · takes {group.duration_of(a)}", action=a))
        return Menu("Jobs", items, "Skilled work is given by appointment; you can volunteer for open work. "
                                   "Many jobs open only through research, and some need a tool to exist first.")
    if kind.type == "appoint":
        def appoint_item(a: Action) -> MenuItem:
            pos = a.params["position"]
            known = pos in view["occupations"] or pos in view["offices"]
            return MenuItem(a.label, action=a, profile=candidate_profile(view, a.label, pos) if known else None)

        def position_label(g: str) -> str:
            occ = view["occupations"].get(g)
            if not occ:
                return g
            seats = f"{len(occ['holders'])}/{occ['seats']}" if occ["seats"] else f"{len(occ['holders'])}"
            return f"{occ['icon']} {g} ({seats})"
        groups = list(dict.fromkeys(a.group for a in acts))
        if len(groups) == 1:
            return Menu(f"Appoint: {position_label(groups[0])}", [appoint_item(a) for a in acts], note)
        return Menu(kind.title, [MenuItem(position_label(g), view["occupations"].get(g, {}).get("description", ""),
                                          submenu=Menu(position_label(g), [appoint_item(a) for a in acts if a.group == g], note))
                                 for g in groups], note)
    if kind.type == "nominate":
        return _nominate_menu(group, view, note)
    if kind.type == "persuade":
        return _persuade_menu(group, view)
    if kind.type == "challenge":
        return _challenge_menu(group, view)
    if kind.type == "resign":
        return Menu("Resign", [MenuItem(a.label, f"Give up the office; the seat is filled as the government "
                                                 f"says (an election, seniority...). Takes {group.duration}.", action=a)
                               for a in acts], "")
    if kind.type == "call_vote":
        names = {"remove_office": "Remove an office holder", "grant_status": "Grant a status",
                 "revoke_status": "Lift a status"}
        acts = [Action(a.type, a.params, a.label, names.get(a.group, a.group)) for a in acts]
        return _grouped(kind.title, acts, lambda a: MenuItem(a.label, action=a), note)
    return _grouped(kind.title, acts, lambda a: MenuItem(a.label, action=a), note)


def work_detail(w: Dict[str, Any]) -> str:
    """'2 h · brings back ~4 Berries, ~2 Roots (sometimes) · uses 2 Wood · with a Wooden Spear'."""
    from world.items import ITEMS
    q = w.get("quality", 50)
    parts = [format_life_duration(life_hours_to_calendar(w["life_hours"]))]
    if w["yields"]:
        bits = []
        for y in w["yields"]:
            name = ITEMS[y["item"]].name
            if y.get("exact"):
                bits.append(f"{int(y['amount'])} {name}")
            else:
                n = y["amount"] * (0.5 + q / 100)
                bits.append(f"~{n:.0f} {name}" + (" (sometimes)" if y.get("chance", 1) < 0.95 else ""))
        parts.append(("makes " if w["kind"] == "craft" else "brings back ") + ", ".join(bits))
    if w.get("site"):
        parts.append("certain: goes to a place a Scout found" if w.get("site_known") else
                     f"{w.get('chance', 1):.0%} chance of anything (no place found)")
    if w.get("scouts_for"):
        parts.append(f"{w.get('find_chance', 0.85):.0%} chance to find a place holding several trips' worth; "
                     "brings nothing back itself")
    if w.get("fire_life_hours"):
        parts.append(f"keeps the fire burning ~{w['fire_life_hours']:g} h longer")
    if w["consumes"]:
        parts.append("uses " + ", ".join(f"{s['count']} {ITEMS[s['item']].name}" for s in w["consumes"]))
    if w["tools"]:
        parts.append("with a " + " or ".join(ITEMS[t].name for t in w["tools"]))
    if w.get("skill"):
        parts.append(f"trains {w['skill']}")
    return " · ".join(parts)


def _work_menu(group: ActionGroup, view: Dict[str, Any]) -> Menu:
    """Your job's tasks and what you can craft, with what each brings back; what you can't do yet is
    listed with the reason."""
    camp = view.get("camp", {})
    info = {(w["kind"], w["key"]): w for w in camp.get("work", [])}
    tasks, crafts, plays = [], [], []
    for a in group.actions:
        if a.type == "activity":
            plays.append(MenuItem(f"[{a.group}] {a.label}", activity_detail(a, view) + f" · takes {group.duration_of(a)}",
                                  action=a))
            continue
        if a.type == "heal":
            tasks.insert(0, MenuItem(f"🌿 {a.label}", "Go to them with medicine from your pack: may cure, and gives back "
                                     f"health · takes {group.duration_of(a)}", action=a))
            continue
        key = a.params.get("task") or a.params.get("recipe")
        w = info.get((a.type, key))
        item = MenuItem(a.label, work_detail(w) if w else "", action=a)
        (crafts if a.type == "craft" else tasks).append(item)
    life = view.get("character", {}).get("life", {})
    if plays or life.get("child"):
        years = life.get("years_to_work", 0)
        note = (f"Children don't work: they play and study, and what they choose shapes who they become. At "
                f"{life.get('work_age', 9):g} your attributes are set"
                + (f" ({years:g} more year{'' if years == 1 else 's'})." if years else "."))
        if tasks:
            note += " Not now: " + "; ".join(f"{w['label']} ({w['problem']})" for w in camp.get("work", []) if w["problem"]) + "."
        return Menu("Play and study", plays + tasks, note)
    items = tasks + ([MenuItem("Craft…", f"{len(crafts)} things you can make",
                               submenu=Menu("Craft", crafts, "Materials come from your pack, then the camp store."))]
                     if len(crafts) > 3 else crafts)
    blocked = [f"{w['label']} ({w['problem']})" for w in camp.get("work", []) if w["problem"]]
    note = "What you bring back goes to the camp store."
    if blocked:
        note += " Not now: " + "; ".join(blocked) + "."
    return Menu("Work", items, note)


def activity_detail(a: Action, view: Optional[Dict[str, Any]] = None) -> str:
    """'CHA +0.45, DEX +0.25 · persuasion +0.15': what a child's play or study adds to them."""
    from core.life import BASE
    spec = ((view or {}).get("character", {}).get("life", {}).get("activities") or
            BASE.get("childhood", {}).get("activities", {})).get(a.params.get("activity"), {})
    parts = [f"{CHARACTER.attributes[k].abbr} +{v:g}" for k, v in spec.get("attributes", {}).items()]
    parts += [f"{CHARACTER.skills[k].name.lower()} +{v:g}" for k, v in spec.get("skills", {}).items()]
    return ", ".join(parts) + (" · with other children" if spec.get("needs_company") else "")


def treat_detail(view: Dict[str, Any]) -> str:
    """What a visit to the healer would do for you now."""
    life = view.get("character", {}).get("life", {})
    ill = life.get("illness")
    if ill and ill.get("cure_chance") is not None:
        return (f"{ill['icon']} {ill['name']}: {ill['cure_chance']:.0%} chance this visit cures it; health back "
                f"either way (several visits for very low health), then rest")
    return "Health back faster than resting alone (uses one of the healer's medicines)"


def life_icons(p: Dict[str, Any]) -> str:
    """Icons for what someone's body is going through: ill, with child, a child or a baby."""
    life = p.get("life") or {}
    out = ""
    if life.get("illness"):
        out += life["illness"].get("icon", "🤒")
    if life.get("pregnancy"):
        out += life["pregnancy"].get("icon", "🤰")
    if life.get("child"):
        out += "👶" if p.get("age", 0) < 2 else "🧒"
    return out


def life_status(life: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """(kind, headline, detail) lines for the You box: illness, pregnancy, childhood."""
    out = []
    ill = life.get("illness")
    if ill:
        healer = (f"E: see {ill['healer']} ({ill['cure_chance']:.0%} cure)" if ill.get("healer")
                  else "no healer with medicine")
        out.append(("illness", f"{ill['icon']} {ill['name']}", f"{ill['days']} days · health draining · {healer}"))
    pr = life.get("pregnancy")
    if pr:
        when = "can't work until the birth" if pr["no_work"] else f"stops work in {pr['days_to_rest']} days"
        out.append(("pregnancy", f"{pr['icon']} With child", f"month {pr['months']:.0f} of {pr['term_months']:.0f} · "
                                                              f"due {pr['due']} · {when}"))
    if life.get("child"):
        years = life.get("years_to_work", 0)
        out.append(("child", "🧒 Child", f"play and study (W) shape you · attributes set at {life['work_age']:g}"
                                         + (f" (in {years:g} year{'' if years == 1 else 's'})" if years else "")))
    return out


def camp_line(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The camp store at a glance (items.json 'camp_summary'): {label, icon, count, empty_warning} per group,
    counted from the store itself, so it matches what the inventory window (I) shows."""
    from world.items import camp_summary
    poss = view.get("possessions")
    if not poss:
        return []
    return camp_summary({s["item"]: s["count"] for s in poss["ground"]})


def _contest_power(view: Dict[str, Any], name: str, kind: str) -> float:
    from core.contests import CHALLENGE_KINDS, persuasion_power, power
    p = next(x for x in view["players"] if x["name"] == name)
    if kind == "persuasion":
        return persuasion_power(p, p["sheet"]["skills"])
    ck = CHALLENGE_KINDS[kind]
    return power(p, p["sheet"]["skills"], ck.attributes, ck.skill)


def _nominate_menu(group: ActionGroup, view: Dict[str, Any], note: str) -> Menu:
    """Turning down your own nomination comes first; then whom to put forward, per election."""
    declines = [a for a in group.actions if a.type == "decline_nomination"]
    noms = [a for a in group.actions if a.type == "nominate"]
    items = []
    ballots = {b["key"]: b for b in view["ballots"]}
    for a in declines:
        b = ballots.get(a.params["ballot"], {})
        by = b.get("nominated_by", {}).get(view["you"])
        who = "you put yourself forward" if by == view["you"] else f"{by} put you forward" if by else "you are standing"
        items.append(MenuItem(f"✋ {a.label}", f"{who}. You won't be nominated for it again this time.", action=a))
    if noms:
        def nominee(a: Action) -> MenuItem:
            office = _ballot_office(view, a.params["ballot"])
            return MenuItem(a.label, action=a, profile=candidate_profile(view, a.label, office) if office else None)
        sub = _grouped("Nominate a candidate", noms, nominee, note)
        for it in sub.items:
            if it.submenu:
                it.submenu.title = f"Nominate a candidate for {it.label}"
        if not items:
            return sub
        items += sub.items if len(sub.items) and sub.items[0].submenu else \
            [MenuItem(sub.title, submenu=sub)]
    return Menu("Nominations", items, "You may stand in one election at a time; candidates vote for themselves.")


def _persuade_menu(group: ActionGroup, view: Dict[str, Any]) -> Menu:
    """Speeches in a running oration, running campaigns (win someone over / keep someone loyal), then
    new campaigns."""
    from core.contests import PERSUASION
    contests = {c["key"]: c for c in view.get("contests", [])}
    items = []
    for a in group.actions:
        c = contests.get(a.params.get("contest"), {})
        if a.type in ("canvass", "rally") and c.get("style") == "audience":
            m = c.get("meters", {}).get(a.label, 50)
            yours = m if a.type == "canvass" else 100 - m
            takes = group.duration_of(Action(a.type, {**a.params, "speech": True}, a.label, a.group))
            items.append(MenuItem(f"📢 Speak to {a.label}", f"now {yours:.0f}% for you · takes {takes}", action=a))
            continue
        if a.type == "canvass":
            c = contests.get(a.params["contest"], {})
            m = c.get("meters", {}).get(a.label, 0)
            items.append(MenuItem(f"Win over {a.label}", f"now {m:.0f}% persuaded · takes {group.duration_of(a)}",
                                  action=a))
        elif a.type == "rally":
            c = contests.get(a.params["contest"], {})
            m = c.get("meters", {}).get(a.label, 0)
            items.append(MenuItem(f"Keep {a.label} on your side", f"{m:.0f}% swayed by {c.get('challenger')} · "
                                  f"takes {group.duration_of(a)}", action=a))
    items.sort(key=lambda i: i.label)
    mine = _contest_power(view, view["you"], "persuasion")
    for a in group.actions:
        if a.type == "persuade":
            target = a.params["target"]
            items.append(MenuItem(f"Campaign to become {a.label}",
                                  f"{PERSUASION.get('life_hours', 6):g} h to win the tribe over; you need "
                                  f"{PERSUASION.get('success_at', 50)}% on average. Your persuasion {mine:.1f}"
                                  + (f" (charisma and the persuasion skill). {target} can rally against you." if target else "."),
                                  action=a))
    if view.get("in_contest") and view["in_contest"]["style"] == "audience":
        ic = view["in_contest"]
        return Menu(f"{ic['name']} against {ic['opponent']}: speak to whom?", items,
                    "Each speech sways one listener; the crowd's lean shows in the Tribe panel.")
    return Menu("Persuade", items, "Everyone's persuasion meter shows in the Tribe panel while a campaign runs."
                + protected_note(view))


def protected_note(view: Dict[str, Any]) -> str:
    """' Not yet: Bob as Clan Leader (new to the office, 3.0 h).' for holders nobody may contest yet."""
    bits = [f"{n} as {office} ({format_life_duration(h)})" for office, o in view.get("offices", {}).items()
            for n, h in o.get("protected_hours", {}).items()]
    return (" Can't be contested yet (new to the office): " + "; ".join(bits) + ".") if bits else ""


def _challenge_menu(group: ActionGroup, view: Dict[str, Any]) -> Menu:
    """Answering a challenge (pick the contest) comes first; then whom to challenge."""
    from core.contests import CHALLENGE, CHALLENGE_KINDS, kinds_allowed
    standing = 1 + CHALLENGE.get("defender_standing", 0)
    contests = {c["key"]: c for c in view.get("contests", [])}
    items = []
    for a in group.actions:
        if a.type != "answer_challenge":
            continue
        kind, c = a.params["kind"], contests.get(a.params["contest"], {})
        ck = CHALLENGE_KINDS[kind]
        mine = _contest_power(view, view["you"], kind) * standing
        theirs = _contest_power(view, c.get("challenger"), kind) if c.get("challenger") else 1.0
        items.append(MenuItem(f"{ck.icon} Answer with {ck.name.lower()}",
                              f"{ck.description} You {mine:.1f} (with your standing) vs {c.get('challenger')} "
                              f"{theirs:.1f} · takes {group.duration_of(a)}", action=a))
    if items:
        return Menu("You have been challenged: choose the contest", items,
                    "Pick the one you are strongest at. If you don't answer in time, it is picked for you.")
    for a in group.actions:
        holder, office = a.params["holder"], a.params["office"]
        if a.params.get("kind"):
            ck = CHALLENGE_KINDS[a.params["kind"]]
            mine = _contest_power(view, view["you"], ck.key)
            theirs = _contest_power(view, holder, ck.key) * standing
            items.append(MenuItem(f"{ck.icon} {ck.name}: {holder} ({office})", f"You {mine:.1f} vs {theirs:.1f}",
                                  action=a))
            continue
        holder_view = next(p for p in view["players"] if p["name"] == holder)
        kinds = kinds_allowed(view["offices"][office].get("challenges", []), holder_view.get("trades", []))
        odds = ", ".join(f"{CHALLENGE_KINDS[k].name.lower()} {_contest_power(view, view['you'], k):.1f} vs "
                         f"{_contest_power(view, holder, k) * standing:.1f}" for k in kinds)
        q = view["offices"][office]["holder_quality"].get(holder)
        items.append(MenuItem(f"Challenge {holder} for {office}",
                              f"{holder} does the job at {q:.0f}/100 and will choose the contest: {odds}", action=a))
    return Menu("Challenge whom?", items, "Win and the office is yours; lose and you must wait." + protected_note(view))


def contest_focus(view: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The contest whose meters the Tribe panel shows: one you are in, else the first with meters."""
    contests = [c for c in view.get("contests", []) if c["style"] in ("persuasion", "audience")]
    return next((c for c in contests if c["your_role"] in ("challenger", "defender")), contests[0] if contests else None)


# --------------------------------------------------------------------------- #
# Innovations
# --------------------------------------------------------------------------- #
STATUS_ORDER = ["researching", "queued", "available", "discovered", "locked"]


@dataclass
class InnovationRow:
    name: str
    icon: str
    interface: str
    age: str
    age_index: int
    cost: int
    status: str                 # one of STATUS_ORDER
    why_locked: str             # for locked ones: what's missing
    prerequisites: List[str]
    missing: List[str]
    unlocks: str
    description: str
    you_can_research: bool      # available and one of your roles may research it


def innovation_catalog(view: Dict[str, Any]) -> List[InnovationRow]:
    """All innovations in the game, each with its status for this tribe."""
    discovered = set(view["discovered"])
    queue = list(view["research_queue"])
    researching = view["researching"]["innovation"] if view["researching"] else None
    reached = reached_age_index(discovered)
    mine = set(view["your_interfaces"])
    rows = []
    for innov in ALL_INNOVATIONS.values():
        missing = [p for p in innov.prerequisites if p not in discovered]
        if innov.name in discovered:
            status, why = "discovered", ""
        elif innov.name == researching:
            status, why = "researching", ""
        elif innov.name in queue:
            status, why = "queued", ""
        elif innov.is_discoverable(discovered):
            status, why = "available", ""
        else:
            status = "locked"
            why = ", ".join(([f"needs {AGES_BY_KEY[innov.age].name}"] if innov.age_index > reached else []) +
                            ([f"needs {', '.join(missing)}"] if missing else []))
        rows.append(InnovationRow(
            name=innov.name, icon=innov.icon or "?", interface=innov.interface, age=AGES_BY_KEY[innov.age].name,
            age_index=innov.age_index, cost=innov.cost, status=status, why_locked=why,
            prerequisites=list(innov.prerequisites), missing=missing,
            unlocks=unlock_note(innov.name).replace("  * opens ", ""), description=innov.description,
            you_can_research=status == "available" and innov.interface in mine))
    rows.sort(key=lambda r: (r.age_index, STATUS_ORDER.index(r.status), r.interface, r.name))
    return rows


def current_age_innovations(view: Dict[str, Any]) -> Tuple[str, List[InnovationRow]]:
    """The age the tribe is in, and the innovations worth showing now: that age's, plus any from earlier
    ages still undiscovered. Later ages are left out until they are reached."""
    reached = reached_age_index(set(view["discovered"]))
    rows = [r for r in innovation_catalog(view)
            if r.age_index == reached or (r.age_index < reached and r.status != "discovered")]
    return AGES[reached].name, rows


INTERFACES = list(INTERFACE_ICONS)


# --------------------------------------------------------------------------- #
# Ballots and tribe
# --------------------------------------------------------------------------- #
@dataclass
class BallotRow:
    label: str
    stage: str          # "nominating" or "voting"
    closes: str
    days_left: Optional[int]
    detail: str         # candidates / choices
    tally: str          # "7/12 voted"
    you: str            # "you may vote", "you voted", "you may nominate", ""
    urgent: bool        # you can act on it now


def ballot_rows(view: Dict[str, Any], legal: List[Action]) -> List[BallotRow]:
    can_vote = {a.params["ballot"] for a in legal if a.type == "vote"}
    can_nominate = {a.params["ballot"] for a in legal if a.type == "nominate"}
    rows = []
    for b in view["ballots"]:
        if b.get("nominating"):
            you = "you may nominate" if b["key"] in can_nominate else ""
            rows.append(BallotRow(b["label"], "nominating", b["closes"] or "", b["days_left"],
                                  ", ".join(b["nominations"]) or "no nominations yet", "", you, b["key"] in can_nominate))
        elif b["voting"]:
            if b.get("you_stand"):
                you = "you are a candidate"
            elif b["you_voted"]:
                you = "you voted"
            elif b["key"] in can_vote:
                you = "you may vote"
            elif b["you_can_vote"]:
                you = "you may vote when free"
            else:
                you = ""
            rows.append(BallotRow(b["label"], "voting", b["closes"] or "", b["days_left"], " / ".join(b["choices"]),
                                  f"{b['votes_cast']}/{b['electorate_size']} voted", you, b["key"] in can_vote))
    return rows


def positions_of(p: Dict[str, Any]) -> str:
    return ", ".join(p["offices"] + p["statuses"])


def occupation_icons(view: Dict[str, Any], p: Dict[str, Any]) -> str:
    return "".join(view["occupations"][o]["icon"] for o in p.get("occupations", []))


def next_age_line(view: Dict[str, Any]) -> str:
    if not view["next_age"]:
        return "latest age reached"
    needs = "  ".join(f"{n} {'[X]' if done else '[ ]'}" for n, done in view["next_age"]["needs"].items())
    return f"{view['next_age']['name']}: {needs}"


def all_ages() -> List[str]:
    return [a.name for a in AGES]


# --------------------------------------------------------------------------- #
# Ballot alerts
# --------------------------------------------------------------------------- #
@dataclass
class Alert:
    date: str
    icon: str
    text: str
    level: str  # "info", "action" (you can do something), "urgent" (time is running out), "done"


REMIND_AT_DAYS = (10, 3)


class BallotWatcher:
    """Turns successive views into alerts: a ballot opened, moved to voting, is running out of time
    for you, or closed (with its result). Keeps no game state of its own beyond what it has seen."""

    def __init__(self):
        self.stages: Dict[str, str] = {}
        self.labels: Dict[str, str] = {}
        self.reminded: set = set()

    def update(self, view: Dict[str, Any], legal: List[Action], recent_texts: List[str]) -> List[Alert]:
        from core.calendar import format_date
        date = format_date(view["time"], short=True)
        can_vote = {a.params["ballot"] for a in legal if a.type == "vote"}
        can_nominate = {a.params["ballot"] for a in legal if a.type == "nominate"}
        alerts: List[Alert] = []
        now: Dict[str, str] = {}
        for b in view["ballots"]:
            stage = "nominating" if b.get("nominating") else "voting" if b["voting"] else "waiting"
            now[b["key"]] = stage
            self.labels[b["key"]] = b["label"]
            nominated = b.get("you_stand") and b.get("nominating")
            tag = (b["key"], b["closes"], "nominated")
            if nominated and tag not in self.reminded:
                self.reminded.add(tag)
                by = b.get("nominated_by", {}).get(view["you"])
                if by and by != view["you"]:
                    alerts.append(Alert(date, "🎖", f"{by} has nominated you for {b['label']}. "
                                                    "Press N to decline if you don't want it.", "action"))
            if self.stages.get(b["key"]) != stage:
                if stage == "nominating":
                    alerts.append(Alert(date, "📣", f"Nominations are open for {b['label']} "
                                                    f"({b['days_left']} days).", "info"))
                    if b["key"] in can_nominate or b["you_can_vote"]:
                        alerts.append(Alert(date, "👉", f"You can put someone forward for {b['label']}: press N.", "action"))
                elif stage == "voting":
                    alerts.append(Alert(date, "🔔", f"Voting has begun: {b['label']} "
                                                    f"({b['days_left']} days to vote).", "info"))
                    if b.get("you_stand"):
                        alerts.append(Alert(date, "🎖", f"You are a candidate for {b['label']}: your own vote is for "
                                                        "yourself. Now the tribe decides (N to withdraw).", "action"))
                    elif b["you_can_vote"] and not b["you_voted"]:
                        alerts.append(Alert(date, "👉", f"Your vote is needed on {b['label']}: press V.", "action"))
            if stage == "voting" and b["you_can_vote"] and not b["you_voted"] and b["days_left"] is not None:
                for limit in REMIND_AT_DAYS:
                    tag = (b["key"], b["closes"], limit)
                    if b["days_left"] <= limit and tag not in self.reminded:
                        self.reminded.add(tag)
                        alerts.append(Alert(date, "⏰", f"Only {b['days_left']} day{'s' if b['days_left'] != 1 else ''} "
                                                        f"left to vote on {b['label']}!", "urgent"))
                        break
        for c in view.get("contests", []):
            stage = f"contest:{c['style']}"
            now[c["key"]] = stage
            self.labels[c["key"]] = c["label"]
            if self.stages.get(c["key"]) == stage:
                continue
            role, office = c["your_role"], c["office"]
            if c["style"] == "persuasion":
                alerts.append(Alert(date, "💬", c["label"] + ".", "info"))
                if role == "defender":
                    alerts.append(Alert(date, "👉", f"{c['challenger']} wants your place as {office}: press P to "
                                                    "keep people on your side!", "urgent"))
                elif role == "challenger":
                    alerts.append(Alert(date, "👉", "Your campaign has begun: press P to win people over.", "action"))
            elif c["style"] == "pending":
                alerts.append(Alert(date, "⏳", f"{c['challenger']} challenges {c['defender']} for {office}!", "info"))
                if role == "defender":
                    alerts.append(Alert(date, "⚠", f"You have been challenged by {c['challenger']} for your place as "
                                                   f"{office}! Press H to choose the contest.", "urgent"))
            else:
                alerts.append(Alert(date, c["icon"], f"{c['challenger']} and {c['defender']} begin a "
                                                     f"{c['name'].lower()} for {office}.", "info"))
                if role in ("challenger", "defender"):
                    if c["style"] == "audience":
                        hint = "Press P to speak to the listeners and win them to your side!"
                    elif c["style"] == "duel":
                        hint = "You are fighting until someone yields."
                    else:
                        hint = "It runs on its own; you can still eat, drink and vote."
                    alerts.append(Alert(date, "⚠", f"Your {c['name'].lower()} for {office} has begun. {hint}",
                                        "urgent"))
        for key in set(self.stages) - set(now):
            if key.startswith("contest:"):
                who = self.labels.get(key, "").split(" ")[0]
                result = next((t for t in reversed(recent_texts) if t.startswith(who) or f"against {who}" in t
                               if any(w in t for w in ("won the tribe over", "failed to win", "wins the", "defends the"))),
                              None)
                alerts.append(Alert(date, "✅", f"Over: {result or self.labels.get(key, key)}", "done"))
                continue
            label = self.labels.get(key, key)
            outcome_words = ("chosen", "failed", "passed", "no valid", "elected", "won", "removed", "becomes",
                             "now ", "reformed", "carried", "called off")
            result = next((t for t in reversed(recent_texts) if label.split(" (")[0] in t
                           and any(w in t for w in outcome_words) and "cannot" not in t
                           and not t.startswith(("Nominations are open", "Voting has begun"))), None)
            alerts.append(Alert(date, "✅", f"Closed: {result or label}", "done"))
        self.stages = now
        return alerts


def ballot_status(b: Dict[str, Any], legal: List[Action], free: bool) -> Tuple[str, str]:
    """(tag, level) describing where you stand on a ballot: VOTE NOW, NOMINATE, VOTED, ..."""
    can_vote = any(a.type == "vote" and a.params["ballot"] == b["key"] for a in legal)
    can_nominate = any(a.type == "nominate" and a.params["ballot"] == b["key"] for a in legal)
    if b.get("you_stand"):
        return "CANDIDATE", "action"
    if b.get("nominating"):
        if can_nominate:
            return "NOMINATE", "action"
        return ("NOMINATING", "info") if b["you_can_vote"] else ("WATCHING", "info")
    if b["you_voted"]:
        return "VOTED ✓", "done"
    if can_vote:
        return "VOTE NOW", "urgent" if (b["days_left"] or 99) <= REMIND_AT_DAYS[0] else "action"
    if b["you_can_vote"]:
        return "VOTE WHEN FREE", "action"
    return "WATCHING", "info"


# --------------------------------------------------------------------------- #
# Inventories
# --------------------------------------------------------------------------- #
def inventory_of(view: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """A person's inventory as seen in `view`: {slots, size, columns, free}, or None."""
    if name == view["you"] and "possessions" in view:
        return view["possessions"]["inventory"]
    p = next((x for x in view["players"] if x["name"] == name), None)
    return p.get("inventory") if p else None


def count_choices(most: int) -> List[int]:
    """Sensible amounts to offer in a picker: 1, 2, 3, 5, 10... up to `most` (always included)."""
    out = [n for n in (1, 2, 3, 5, 10, 15, 20) if n < most]
    return out + [most] if most >= 1 else []


def stack_worth(stacks: List[Dict[str, Any]]) -> float:
    """The plain trade value of some stacks (NPCs also weigh what they need right now)."""
    from world.items import ITEMS
    return sum(ITEMS[s["item"]].value * s["count"] for s in stacks)


# --------------------------------------------------------------------------- #
# Crafting chart (F12): what the tribe can make or find, and what it takes
# --------------------------------------------------------------------------- #
CRAFT_STATUS_RANK = {"ready": 0, "short": 1, "no_tool": 2, "no_worker": 3, "research": 4}
CRAFT_FILTERS = ["all", "can be had now", "not yet"]
KIND_ORDER = ["food", "water", "material", "tool", "medicine"]


@dataclass
class CraftRow:
    item: str
    icon: str
    name: str
    kind: str
    made: List[Dict[str, Any]]      # recipes that make it (crafts 'recipes')
    found: List[Dict[str, Any]]     # tasks that bring it back (crafts 'sources')
    status: str                     # best of its ways: ready, short, no_tool, no_worker, research
    why: str
    uses: List[str]
    store: int
    used_by: Dict[str, List[str]] = field(default_factory=dict)  # job -> what for
    best: Optional[Dict[str, Any]] = None  # the way that gets it soonest


    @property
    def by(self) -> str:
        jobs = [o for w in self.made + self.found for o in (w["occupations"] or ["anyone"])]
        return ", ".join(dict.fromkeys(jobs))

    @property
    def research(self) -> List[Dict[str, Any]]:
        """The research the easiest way to get it needs."""
        return list(self.best["research"]) if self.best else []

    @property
    def used_for(self) -> str:
        """'Hunter: go hunting x1.2' and 'Warrior: patrol the camp', one line each ('—' if nothing uses it)."""
        groups: Dict[str, List[str]] = {}  # what for -> jobs, so jobs that use it alike share a line
        for job, whats in self.used_by.items():
            made = [w[len("to make "):] for w in whats if w.startswith("to make ")]
            rest = [w for w in whats if not w.startswith("to make ")]
            if len(made) > 3:  # the full list is in the detail below the table
                made = made[:2] + [f"{len(made) - 2} more"]
            what = ", ".join(rest + ([f"making {', '.join(made)}"] if made else []))
            groups.setdefault(what, []).append(job)
        return "\n".join(f"{', '.join(jobs)}: {what}" for what, jobs in groups.items()) or "—"

    @property
    def takes(self) -> str:
        if self.made:
            return " or ".join(" + ".join(f"{s['count']} {ITEMS[s['item']].name}" for s in r["inputs"]) for r in self.made)
        best = self.best if self.best in self.found else self.found[0]
        more = len(self.found) - 1
        return best["label"] + (f" (+{more} more)" if more else "")


def craft_catalog(view: Dict[str, Any]) -> List[CraftRow]:
    """One row per item the tribe can make or find in this age, best way first."""
    c = view.get("crafts")
    if not c:
        return []
    rows: Dict[str, CraftRow] = {}

    def row(key: str) -> CraftRow:
        if key not in rows:
            i = ITEMS[key]
            rows[key] = CraftRow(key, i.icon, i.name, i.kind, [], [], "research", "", c["uses"].get(key, []),
                                 c["store"].get(key, 0), used_by=c.get("used_by", {}).get(key, {}))
        return rows[key]

    def better(r: CraftRow, way: Dict[str, Any]):
        rank = (CRAFT_STATUS_RANK[way["status"]], sum(not x["done"] for x in way["research"]), len(way["research"]))
        if r.best is None or rank < (CRAFT_STATUS_RANK[r.status], sum(not x["done"] for x in r.best["research"]),
                                     len(r.best["research"])):
            r.status, r.why, r.best = way["status"], way["why"], way

    for rec in c["recipes"]:
        r = row(rec["item"])
        r.made.append(rec)
        better(r, rec)
    for src in c["sources"]:
        for y in src["yields"]:
            r = row(y["item"])
            r.found.append(src)
            better(r, src)
    order = list(ITEMS)
    return sorted(rows.values(), key=lambda r: (KIND_ORDER.index(r.kind) if r.kind in KIND_ORDER else 99,
                                                order.index(r.item)))


def craft_detail(view: Dict[str, Any], r: CraftRow) -> List[Tuple[str, str]]:
    """(text, style) lines describing how to get an item, where its materials come from, and its uses."""
    c = view["crafts"]
    lines: List[Tuple[str, str]] = [(f"{r.icon} {r.name}", "bold"), (f"  ({r.kind}; the store has {r.store})", "dim"),
                                    ("\n" + ITEMS[r.item].description + "\n", "")]

    def research_text(w) -> str:
        return ", ".join(f"{x['name']} {'✓' if x['done'] else '✗'}" for x in w["research"]) or "none"

    def who(w) -> str:
        if not w["occupations"]:
            return "anyone"
        names = [n for n in w["workers"]]
        return f"a {' or '.join(w['occupations'])}" + (f" (now: {', '.join(names)})" if names else " (nobody yet)")

    for rec in r.made:
        lines.append((f"Made by {who(rec)}, {format_life_duration(life_hours_to_calendar(rec['life_hours']))} of "
                      f"{rec['skill']}; research: {research_text(rec)}\n", "bold"))
        for s in rec["inputs"]:
            have = rec["have"].get(s["item"], 0)
            from_ = [src["label"] for src in c["sources"] if any(y["item"] == s["item"] for y in src["yields"])]
            from_ += [f"made by {' or '.join(x['occupations'])}" for x in c["recipes"] if x["item"] == s["item"]]
            lines.append((f"   {s['count']} {ITEMS[s['item']].icon} {ITEMS[s['item']].name}", "green" if have >= s["count"] else "yellow"))
            lines.append((f"  (store {have})  ← {'; '.join(from_) or 'nowhere yet'}\n", "dim"))
        lines.append((f"   → {rec['count']} {r.name}\n", ""))
    for src in r.found:
        y = next(y for y in src["yields"] if y["item"] == r.item)
        odds = f", {y['chance']:.0%} of trips" if y["chance"] < 1 else ""
        tools = f"; with a {' or '.join(ITEMS[x].name for x in src['tools'])}" if src["tools"] else ""
        uses = f"; uses up {', '.join(str(s['count']) + ' ' + ITEMS[s['item']].name for s in src['consumes'])}" if src["consumes"] else ""
        lines.append((f"Found by {who(src)}: {src['label']} ({format_life_duration(life_hours_to_calendar(src['life_hours']))}, "
                      f"about {y['amount']:g}{odds}{tools}{uses}); research: {research_text(src)}\n", "bold"))
    style = {"ready": "green", "short": "yellow", "no_tool": "yellow", "no_worker": "yellow", "research": "red"}[r.status]
    lines.append((f"Now: {r.why}\n", style))
    if r.uses:
        lines.append(("Used for: " + "; ".join(r.uses) + "\n", "cyan"))
    breaks = ITEMS[r.item].breaks
    if breaks:
        lines.append((f"Breaks on about {breaks:.0%} of uses (about {1 / breaks:.0f} uses on average).\n", "dim"))
    return lines

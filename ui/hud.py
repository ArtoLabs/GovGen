"""The command-center HUD: a fixed, non-scrolling terminal screen built with Textual.

    ┌ top bar: date, age, government, points, speed ───────────────────────────────┐
    │ CHRONICLE (what everyone  │ YOU: status, stats, roles,       │ TRIBE          │
    │ is doing, live)           │      your action keys            │ who holds what,│
    │                           │ GOVERNMENT AND VOTES: reforms,   │ who is doing   │
    │                           │      open nominations and votes  │ what           │
    │                           │ INNOVATION POOL: research, next  │                │
    │                           │      age, discoveries as icons   │                │
    ├───────────────────────────┴──────────────────────────────────┴────────────────┤
    │ F-key bar: information screens and game controls                              │
    └ status line ──────────────────────────────────────────────────────────────────┘

Letters act, F-keys look. Pressing an action key opens a small picker; numbers (or arrows and
Enter, or the mouse) choose, Esc goes back. The game keeps running the whole time.

All game data comes from HUDController (thread-safe) and ui/model.py (UI-neutral), so a graphical
client can replace this file without touching the game.
"""
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Input, Label, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from controllers.base import Decision
from controllers.hud import HUDController
from core.calendar import format_date, format_duration
from world.environment import HOURS_PER_LIFE_HOUR, format_life_duration
from world.character import RULES as CHARACTER
from innovations.innovation import INTERFACE_ICONS
from ui.model import (camp_line, occupation_icons, contest_focus, BallotWatcher, ballot_status, ACTION_SECTIONS, INTERFACES, Menu,
                      life_icons, life_status,
                      MenuItem, action_groups, build_menu, innovation_catalog, current_age_innovations, positions_of,
                      CRAFT_FILTERS, craft_catalog, craft_detail, protected_note)
from ui.inventory import InventoryScreen
from utils.messages import Message
from world.items import ITEMS

PICK_KEYS = "123456789abcdefghijklmnopqrstuvwxyz"
ALERT_STYLE = {"info": "", "action": "bold green", "urgent": "bold red", "done": "cyan"}
TAG_STYLE = {"info": "bold black on grey50", "action": "bold black on green", "urgent": "bold white on red",
             "done": "bold black on cyan"}


DETAIL_LEVELS = {"full": "everything everyone does, with reasons",
                 "politics": "everything except everyday life (eating, sleeping, resting)",
                 "summary": "important events only"}


def message_text(m: Message, detail: str) -> Optional[Text]:
    """One chronicle entry, or None if hidden at this detail level."""
    if detail == "summary" and not m.important:
        return None
    if detail == "politics" and m.category == "life":
        return None
    if m.header:
        return Text(m.text, style="bold cyan")
    t = Text()
    if m.time is not None:
        t.append(format_date(m.time, short=True) + " ", style="dim")
    t.append(m.text, style="bold yellow" if m.important else "green" if m.category == "life" else "")
    if m.reason and detail == "full":
        t.append(f"\n   ({m.reason})", style="dim italic")
    return t


def sat_style(value: float) -> str:
    """Colour for a satisfaction or quality value."""
    return "b green" if value >= 65 else "yellow" if value >= 45 else "b red"


def need_style(value: float, critical: bool) -> str:
    return "bold red" if critical else "red" if value < 25 else "yellow" if value < 50 else "green"


def bar(done: float, total: float, width: int = 12) -> str:
    filled = 0 if total <= 0 else max(0, min(width, round(width * done / total)))
    return "█" * filled + "░" * (width - filled)


# --------------------------------------------------------------------------- #
# Meters: coloured bars on a dark track, with eighth-cell resolution
# --------------------------------------------------------------------------- #
EIGHTHS = " ▏▎▍▌▋▊▉"
TRACK = "on grey23"
SKILL_COLOR, ATTRIBUTE_COLOR = "cyan", "medium_purple1"
HEALTH_ICON = "💗"


# Emoji that terminals and Textual agree are 2 cells wide. Icons written with the invisible "emoji
# style" selector (U+FE0F, as in 🏗️ ⚖️ ⚔️) are counted as 1 cell by Textual but drawn as 2, which
# shifts the rest of the screen row and breaks the box borders.
SAFE_ROLE_ICONS = {"judicial": "🔨", "military": "🏹", "intelligence": "🔍", "infrastructure": "🧱",
                   "civic_representation": "👥"}


def role_icon(key: str) -> str:
    icon = SAFE_ROLE_ICONS.get(key) or INTERFACE_ICONS.get(key, "•")
    return "•" if "️" in icon else icon


def level_color(value: float) -> str:
    """Colour for a 0-100 value where higher is better (satisfaction, quality, mood)."""
    return "green" if value >= 65 else "yellow" if value >= 45 else "red"


def need_color(value: float, critical: bool) -> str:
    return "red" if critical or value < 25 else "yellow" if value < 50 else "green"


def meter(value: float, total: float, width: int, color: str) -> Text:
    """A bar `width` cells wide, filled in `color` to value/total."""
    width = max(1, width)
    frac = 0.0 if total <= 0 else max(0.0, min(1.0, value / total))
    full, part = divmod(round(frac * width * 8), 8)
    t = Text("█" * full, style=color)
    if full < width:
        t.append(EIGHTHS[part], style=f"{color} {TRACK}")
        t.append(" " * (width - full - 1), style=TRACK)
    return t


def ability_note(ab) -> Text:
    """'leadership 3.2 · tired -8' under the Ability bar: what it rests on and what is dragging it down."""
    t = Text(style="dim", no_wrap=True, overflow="ellipsis")
    t.append("+".join(a[:3].upper() for a in ab["attributes"][:3]))
    if ab.get("skill_name"):
        t.append(f" · {ab['skill_name'].lower()} {ab['skill_level']:.1f}")
    for key, word in (("tired", "tired"), ("unwell", "ill")):
        if ab.get(key, 0) >= 1:
            t.append(f" · {word} ")
            t.append(f"-{ab[key]:.0f}", style="yellow")
    return t


def patience_cell(patience) -> tuple:
    """(text, style) for someone's patience with the leaders (or society, if worse)."""
    if not patience:
        return ("-", "dim")
    worst = min(patience.values(), key=lambda d: (d["left"], -d["restless"]))
    if worst["restless"] > 0 or worst["left"] <= 0:
        return ("● out", "bold red")
    if worst["unrest"] <= 0:
        return ("∙ fine", "green")
    left = worst["left"]
    return (("◔ thin" if left < 0.4 else "◑ wearing" if left < 0.75 else "◕ grumbling"),
            "yellow" if left < 0.4 else "dim yellow")


class MeterRow:
    """One line of a meter box: label, bar, note (a number or a word)."""
    __slots__ = ("label", "value", "total", "color", "note", "label_style", "note_style")

    def __init__(self, label: str, value: float, total: float = 100, color: str = "green", note: str = "",
                 label_style: str = "", note_style: str = ""):
        self.label, self.value, self.total, self.color, self.note = label, value, total, color, note
        self.label_style, self.note_style = label_style, note_style


def meter_rows(rows: List[Any], width: int, lines: int = 0, max_bar: int = 24, notes_right: bool = True) -> Text:
    """Rows of `label bar note` with the labels and notes in aligned columns; the bars take whatever
    width is left. Rows may also be plain Text (shown as is) . Padded with blank lines to `lines`."""
    meters = [r for r in rows if isinstance(r, MeterRow)]
    label_w = max((Text(r.label).cell_len for r in meters), default=0)
    note_w = max((len(r.note) for r in meters), default=0)
    room = width - label_w - (1 if label_w else 0) - (note_w + 1 if note_w else 0)
    if room < 6 and label_w > 6:  # narrow: shorten long labels ('Firekeeping') rather than lose the bars
        label_w = max(6, label_w - (6 - room))
        room = width - label_w - 1 - (note_w + 1 if note_w else 0)
    bar_w = max(3, min(max_bar, room))
    t = Text(no_wrap=True, overflow="ellipsis")
    for i, r in enumerate(rows):
        if i:
            t.append("\n")
        if not isinstance(r, MeterRow):
            t.append_text(r if isinstance(r, Text) else Text(str(r)))
            continue
        label = Text(r.label, style=r.label_style)
        label.truncate(label_w, overflow="ellipsis", pad=True)
        t.append_text(label)
        if label_w:
            t.append(" ")
        t.append_text(meter(r.value, r.total, bar_w, r.color))
        if note_w:
            t.append(" ")
            t.append(r.note.rjust(note_w) if notes_right else r.note, style=r.note_style)
    for _ in range(len(rows), lines):
        t.append("\n")
    return t


def body_rows(sheet: Dict[str, Any], words: bool = True) -> List[MeterRow]:
    """Health and every need, each with its word ('Full', 'Thirsty'), or with its number when the box
    is too narrow for words (`words=False`)."""
    hp = sheet["health"]
    rows = [MeterRow(HEALTH_ICON, hp, 100, "red" if hp < 50 else "green", f"Health {hp}" if words else str(hp),
                     note_style="bold red" if hp < 50 else "")]
    for k, n in CHARACTER.needs.items():
        need = sheet["needs"][k]
        rows.append(MeterRow(n.icon, need["value"], 100, need_color(need["value"], need["critical"]),
                             need["label"] if words else str(need["value"]),
                             note_style="bold red" if need["critical"] else ""))
    return rows


def content_rows(view: Dict[str, Any], satisfaction: Dict[str, float], mood: Optional[float] = None,
                 rising: Optional[Dict[str, Optional[bool]]] = None) -> List[MeterRow]:
    """The satisfaction meters (food, work, leaders, society, comfort, safety), then mood if given.
    A ▲ or ▼ after the number: the meter is rising or falling."""
    rows = []
    for key, m in view["satisfaction"].items():
        val = satisfaction.get(key, 50)
        up = (rising or {}).get(key, m.get("rising"))
        arrow = "" if up is None else "▲" if up else "▼"
        rows.append(MeterRow(m["name"], val, 100, level_color(val), f"{val:.0f}{arrow}"))
    if mood is not None:
        rows.append(MeterRow("Mood", mood, 100, level_color(mood), f"{mood:.0f}", label_style="bold"))
    return rows


def skill_rows(skills: Dict[str, float], limit: int) -> List[Any]:
    """The best `limit` skills (only those above zero)."""
    best = sorted(((v, k) for k, v in skills.items() if v > 0), reverse=True)[:limit]
    if not best:
        return [Text("no skills yet", style="dim")]
    return [MeterRow(CHARACTER.skills[k].name, v, CHARACTER.skill_max, SKILL_COLOR, f"{v:.1f}") for v, k in best]


def attribute_rows(p: Dict[str, Any]) -> List[MeterRow]:
    return [MeterRow(a.abbr, p[k], CHARACTER.attr_max, ATTRIBUTE_COLOR, str(p[k]), label_style="bold")
            for k, a in CHARACTER.attributes.items()]


class MeterBox(Static):
    """A bordered box of meter rows that redraws its bars to fit whenever its width changes."""

    def __init__(self, title: str = "", rows: Any = None, lines: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.border_title = title
        self.rows, self.lines = rows or [], lines

    def show(self, rows: Any, lines: Optional[int] = None):
        """`rows` is a list of rows, or a function of the box's width that returns them."""
        self.rows = rows
        if lines is not None:
            self.lines = lines
        self._render_rows()

    def on_mount(self):
        self._render_rows()

    def on_resize(self):
        self._render_rows()

    def _render_rows(self):
        width = self.content_size.width or 20
        rows = self.rows(width) if callable(self.rows) else self.rows
        self.update(meter_rows(rows, width, self.lines))


def actions_markup(groups: List[Any], width: int) -> str:
    """Your action keys as keycaps, one row per section (Politics, Leading, Life). Uses aligned columns
    and section names when they fit in `width`, and wraps when nothing else does."""
    by_type = {g.kind.type: g for g in groups}
    sections = [(name, [by_type[t] for t in types if t in by_type]) for name, types in ACTION_SECTIONS]
    listed = {t for _, types in ACTION_SECTIONS for t in types}
    rest = [g for g in groups if g.kind.type not in listed]
    if rest:
        sections.append(("Other", rest))

    def cell(g) -> Tuple[str, int]:
        k, label = g.kind.hotkey.upper(), g.kind.label
        if g.available:
            return f"[@click=screen.act('{g.kind.type}')][b black on green] {k} [/] [b]{escape(label)}[/][/]", 4 + len(label)
        return f"[dim][on #3a3a3a] {k} [/] {escape(label)}[/]", 4 + len(label)

    sections = [(name, [cell(g) for g in gs]) for name, gs in sections if gs]
    name_w = max(len(n) for n, _ in sections) + 2

    def layout(labeled: bool, per_row: int, gap: int) -> Tuple[List[str], int]:
        """Each section split into rows of at most `per_row` keys, all in aligned columns."""
        rows = [(name if i == 0 else "", cs[i:i + per_row]) for name, cs in sections
                for i in range(0, len(cs), per_row)]
        col_w = [max(cs[j][1] for _, cs in rows if j < len(cs)) for j in range(per_row)]
        widest = (name_w if labeled else 0) + sum(col_w) + gap * (per_row - 1)
        lines = []
        for name, cs in rows:
            parts = [markup + " " * (col_w[j] - w if j < len(cs) - 1 else 0) for j, (markup, w) in enumerate(cs)]
            lines.append((f"[dim]{name:<{name_w}}[/]" if labeled else "") + (" " * gap).join(parts))
        return lines, widest

    most = max(len(cs) for _, cs in sections)
    options = [layout(labeled, n, gap) for n in range(most, 0, -1) for labeled in (True, False) for gap in (2, 1)]
    fitting = [lines for lines, widest in options if widest <= width]
    if not fitting:
        return "\n".join(options[-1][0])
    return "\n".join(min(fitting, key=len))  # fewest rows; ties go to labels, then wider gaps (listed first)


class ActionBar(Static):
    """The Actions box: lays out its keycaps again whenever its width changes."""
    groups: List[Any] = []

    def show(self, groups: List[Any]):
        self.groups = groups
        self.update(actions_markup(groups, self.content_size.width or 80))

    def on_resize(self):
        if self.groups:
            self.update(actions_markup(self.groups, self.content_size.width or 80))


class FlowGrid(Grid):
    """A grid whose column count follows its width: the largest of `columns` that leaves every cell at
    least `min_cell` wide."""

    def __init__(self, *children, min_cell: int = 22, columns: Tuple[int, ...] = (4, 2, 1), **kwargs):
        super().__init__(*children, **kwargs)
        self.min_cell, self.columns = min_cell, columns

    def on_resize(self):
        width = self.size.width
        cols = next((c for c in self.columns if width >= c * self.min_cell), self.columns[-1])
        if self.styles.grid_size_columns != cols:
            self.styles.grid_size_columns = cols


# --------------------------------------------------------------------------- #
# Pop-ups
# --------------------------------------------------------------------------- #
class PickerScreen(ModalScreen):
    """Choose one item from a menu: its key, arrows + Enter, or a click. Esc goes back."""
    BINDINGS = [Binding("escape", "dismiss(None)", "Back")]

    def __init__(self, menu: Menu):
        super().__init__()
        self.menu = menu

    def compose(self) -> ComposeResult:
        options = []
        people = any(item.profile for item in self.menu.items)
        for i, item in enumerate(self.menu.items):
            key = PICK_KEYS[i] if i < len(PICK_KEYS) else " "
            if item.profile:
                prompt = profile_text(item.profile, key)
            else:
                prompt = Text.assemble((f" {key} ", "bold green"), item.label + (" ▸" if item.submenu else ""))
                if item.detail:
                    prompt.append("\n     " + item.detail.replace("\n", "\n     "), style="dim")
            options.append(Option(prompt))
            if people and i < len(self.menu.items) - 1:
                options.append(None)  # a separator line between people
        with Vertical(id="dialog", classes="people" if people else ""):
            yield Label(Text(self.menu.title, style="bold cyan"))
            if people:
                yield Static(profile_legend(self.menu.items), classes="legend")
            yield OptionList(*options, id="options")
            yield Label(Text(f"{self.menu.note}  Key or ↑↓ Enter to choose · Esc back".strip(), style="dim"))

    def on_key(self, event) -> None:
        if event.character and event.character in PICK_KEYS:
            i = PICK_KEYS.index(event.character)
            if i < len(self.menu.items):
                event.stop()
                self.dismiss(self.menu.items[i])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.menu.items[event.option_index])  # separators don't count as options


def profile_text(pr: Dict[str, Any], key: str = "", ranked: Optional[int] = None) -> Text:
    """A person in a pick list: who they are, how well they would do the job, the stats the job uses,
    and what kind of person they are."""
    t = Text()
    if ranked is not None:
        t.append(f" {ranked}.", style="bold green")
    else:
        t.append(f" {key} ", style="bold green")
    t.append(" ")
    t.append(f"{pr['name']:<8}", style="bold green" if pr["you"] else "bold")
    t.append(f" {pr['age']} {pr['life_stage'].lower()}", style="dim")
    t.append("  ·  ")
    t.append(pr["positions"] or "Tribe member", style="cyan")
    if pr["occupations"]:
        t.append(f"  ·  {pr['occupation_icons']} {', '.join(pr['occupations'])}", style="cyan")
    if pr["you"]:
        t.append("   (you)", style="bold green")
    if pr["holds_it"]:
        t.append(f"   holds it now", style="yellow")
    move = pr.get("rank_move")
    if move:
        t.append(f"   {'▲ a step up' if move > 0 else '▼ a step down'} ({move:+g} rank)",
                 style="green" if move > 0 else "red")
    if ranked is not None:
        t.append(f"   ← your {ordinal(ranked)} choice", style="bold green")
    t.append("\n     ")
    if pr["fit"] is not None:
        color = level_color(pr["fit"])
        t.append("Fit ", style="bold")
        t.append_text(meter(pr["fit"], 100, 12, color))
        t.append(f" {pr['fit']:3.0f}", style=f"bold {color}")
        t.append("  │", style="dim")
    for a in pr["attributes"]:
        t.append(f"  {a['abbr']} ", style="bold" if a["weight"] >= 0.8 else "")
        t.append_text(meter(a["value"], CHARACTER.attr_max, 5, ATTRIBUTE_COLOR))
        t.append(f" {a['value']:<2}")
    if pr["skill"]:
        s = pr["skill"]
        t.append(f"  {s['name']} ", style="bold")
        t.append_text(meter(s["value"], CHARACTER.skill_max, 5, SKILL_COLOR))
        t.append(f" {s['value']:.1f}")
    t.append("\n     ")
    t.append(pr["description"], style="italic")
    if pr["traits"]:
        t.append("  (" + ", ".join(pr["traits"]) + ")", style="dim")
    return t


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def profile_legend(items: List[Any]) -> Text:
    """One line explaining the candidate cards: what Fit means and which stats the job uses."""
    pr = next((i.profile for i in items if i.profile), None) or next(
        (p for i in items if i.profiles for p in i.profiles.values() if p), None)
    t = Text()
    if not pr or not pr["position"]:
        return t
    t.append(f"Fit = how well each would do the work of {pr['position']} today. "
             f"It draws on the stats shown, most important first", style="dim")
    used = [a["name"] for a in pr["attributes"]] + ([pr["skill"]["name"] + " skill"] if pr["skill"] else [])
    if used:
        t.append(f" ({', '.join(used)})", style="dim")
    t.append(".", style="dim")
    if any((i.profile or {}).get("rank_move") for i in items):
        t.append(" ▲/▼: higher or lower work than they have now; they warm to the leaders for a step up "
                 "and resent a step down.", style="dim")
    return t


class RankScreen(ModalScreen):
    """Rank candidates by pressing their keys in order of preference."""
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel"), Binding("backspace", "undo", "Undo"),
                Binding("enter", "done", "Done")]

    def __init__(self, title: str, candidates: List[str], profiles: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.title_text, self.candidates, self.ranking = title, candidates, []
        self.profiles = {c: p for c, p in (profiles or {}).items() if p}

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog", classes="people" if self.profiles else ""):
            yield Label(Text(self.title_text, style="bold cyan"))
            if self.profiles:
                yield Static(profile_legend([MenuItem("", profiles=self.profiles)]), classes="legend")
            with VerticalScroll(id="rank_scroll"):
                yield Static(id="rank")
            yield Label(Text("Press keys in order of preference · Backspace undo · Enter done · Esc cancel", style="dim"))

    def on_mount(self):
        self._draw()

    def _draw(self):
        t = Text()
        for i, c in enumerate(self.candidates):
            ranked = self.ranking.index(c) + 1 if c in self.ranking else None
            if c in self.profiles:
                t.append_text(profile_text(self.profiles[c], PICK_KEYS[i], ranked))
                t.append("\n\n")
            elif ranked is not None:
                t.append(f"  {ranked}. {c}\n", style="bold green")
            else:
                t.append(f" [{PICK_KEYS[i]}] {c}\n")
        self.query_one("#rank", Static).update(t)

    def on_key(self, event) -> None:
        if event.character and event.character in PICK_KEYS:
            i = PICK_KEYS.index(event.character)
            if i < len(self.candidates) and self.candidates[i] not in self.ranking:
                event.stop()
                self.ranking.append(self.candidates[i])
                if len(self.ranking) == len(self.candidates):
                    self.dismiss(self.ranking)
                else:
                    self._draw()

    def action_undo(self):
        if self.ranking:
            self.ranking.pop()
            self._draw()

    def action_done(self):
        if self.ranking:
            self.dismiss(self.ranking)


class TextScreen(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, prompt: str):
        super().__init__()
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(Text(self.prompt, style="bold cyan"))
            yield Input(id="text")
            yield Label(Text("Enter to confirm · Esc cancel", style="dim"))

    def on_input_submitted(self, event: Input.Submitted):
        self.dismiss(event.value.strip())


class InfoScreen(ModalScreen):
    """A full-size information page, closed by Esc or the F-key that opened it."""
    KEY = "f1"

    def __init__(self, view: Dict[str, Any]):
        super().__init__()
        self.view = view

    def on_key(self, event) -> None:
        if event.key in ("escape", self.KEY) and self.app.screen is self:
            event.stop()
            self.dismiss(None)

    def body(self) -> Text:
        return Text()

    def compose(self) -> ComposeResult:
        with Vertical(id="info"):
            with VerticalScroll():
                yield Static(self.body())
            yield Label(Text(f"Esc or {self.KEY.upper()} to close · ↑↓ PgUp PgDn to scroll", style="dim"))


class HelpScreen(InfoScreen):
    KEY = "f1"

    def body(self) -> Text:
        t = Text()
        t.append("How to play\n\n", style="bold cyan")
        t.append("The game runs in real time. The clock never waits for you: other members of the tribe act, "
                 "ballots open and close, and research advances while you think. Every action keeps you busy "
                 "for a while (shown in the picker). Politics runs on days and work on hours, so while you are out "
                 "working, crafting, resting or eating you can still vote, nominate, appoint, persuade or challenge "
                 "without stopping; only keys you can't use right now are greyed out.\n\n")
        t.append("Actions (letters)\n", style="bold")
        for key, text in [("v", "Vote on an open ballot"), ("n", "Nominate a candidate (one election at a time each), or decline your own nomination"),
                          ("a", "Appoint someone to a position you control"),
                          ("d", "Dismiss someone from a position you control"),
                          ("c", "Call a vote: remove an office holder, grant or lift a status"),
                          ("f", "Reform the government into another form of the same age (by decree or by calling a vote); a new "
                                "age changes the government by itself"),
                          ("r", "Queue an innovation for research (one of your roles must be able to)"),
                          ("o", "Give an order from one of your roles (propose a law, levy a tax...)"),
                          ("e", "Look after yourself: eat, drink, sleep, warm up by the fire"),
                          ("w", "Work: do your job's work (forage, hunt, tend the fire, patrol, lead a ritual, see to "
                                "your office...) or craft tools. Your Work contentment rises only while you work your "
                                "job: faster with the right tools (more than one, faster still) and the more jobs your "
                                "age has opened. What you bring back goes into your pack"),
                          ("j", "Job: volunteer for open work (Gatherer, Firekeeper...) or give up your job"),
                          ("x", "Wake up or stop resting / warming up early"),
                          ("p", "Persuade: campaign for an office, win people over, rally them against a rival, or speak in an oration"),
                          ("h", "Challenge an office holder (they choose the contest), or choose yours when challenged"),
                          ("g", "Resign from an office you hold (someone new to an office can't be challenged, "
                                "persuaded against or voted out for a while)"),
                          ("i", "Inventory: move, split, sort, use, drop and pick up items, give and trade. "
                                "Handling items takes no time, but not while asleep")]:
            t.append(f"  {key}  ", style="bold green")
            t.append(text + "\n")
        t.append("\nIn a picker: press the key shown, or use ↑↓ and Enter, or click. Esc goes back.\n\n")
        t.append("Living off the land\n", style="bold")
        t.append("Food and water come only from work. Gatherers forage and fetch water (only they do); what they bring "
                 "back goes to the camp store, and every meal and drink uses it up (your own pack first). With "
                 "nothing to eat or drink, people go hungry and thirsty and lose health; at no health they die. In "
                 "winter warmth falls fast (very fast with no fire in camp) and freezing drains health: resting by the "
                 "fire only keeps the cold off, so warm up by it (E). The fire burns "
                 "wood: the Firekeeper must keep feeding it. Most jobs open only through research (Toolmaking, "
                 "Hunting, Fishing, Tracking, Herbalism, Camp Defense...). Some work needs a tool: a Hunter or Warrior "
                 "a spear, a Fisher a fishing spear. You can be appointed before one exists: you wait, and take one "
                 "from the camp store the moment the Toolmaker makes one. Toolmaking gives tools of sharpened wood; "
                 "only Stone Cutting gives stone and flint ones, which do the same work better. The top bar counts what the camp store "
                 "holds: wood, food, water, stone, herbs and tools (the same as the store in your inventory, I). F12 (or K) shows everything that can be made or found and what "
                 "it takes.\n\n"
                 "Trips out (foraging, wood, stone, hunting, fishing, herbs) often come back empty: well under half "
                 "succeed, hunting least often, but a kill brings back far more food than a forage. A Scout brings "
                 "nothing back but chooses what to look for (berry grounds, deadwood, a stone bed, game trails, a "
                 "fishing pool, herbs) and usually finds it: a found place holds several trips' worth, and every trip "
                 "of that kind goes there and pays off for certain until it is used up (the Found places panel under "
                 "the tribe shows what is left). A Sustenance Gardener (Sustenance Gardening) tends plots of plants "
                 "for the Gatherers instead. Unused places are lost after a while. The W "
                 "menu says when a good place is known. Fetching water from the river always works.\n\n")
        t.append("Life and death\n", style="bold")
        t.append("People are born, grow up, fall ill and die (data/life.json). Anyone may fall ill, the old far more "
                 "often, and hard work makes it likelier. While ill (🤒 in your box) your health drains; at nothing "
                 "you die. Only a healer can cure it: press E, See the healer. The Healer (Herbalism) needs herbs (or "
                 "poultices) in their own pack; each visit uses one, may cure you (less likely the older you are) and "
                 "gives back some health. Health comes back otherwise only while you rest, not while you work. "
                 "The dead lie in camp (💀 in the tribe list) until someone carries them away, burns or buries them "
                 "(W); while they lie there, sickness spreads. Now and then a woman becomes pregnant (🤰, a bar shows "
                 "the nine months); she can't work for the last three, then a baby joins the tribe. Children (🧒) don't "
                 "work until 9: they play and study (W), and what they choose sets their attributes. They vote and "
                 "hold office from 14. If you die, you play on as your eldest child (or else the youngest adult).\n\n")
        t.append("Hiring and firing\n", style="bold")
        t.append("A leader may appoint and dismiss as often as they like, and any number of people may do the same "
                 "work. Moving someone to other work costs only a little of their contentment: it is part of "
                 "leading. Dismissing someone outright hurts: their Work and Leaders contentment drops at once and "
                 "stays low for a while, more with every dismissal, and the rest of the tribe is unsettled too.\n"
                 "An unhappy tribe gives its leaders time: people grumble first, and only when their patience runs "
                 "out (the chronicle warns you; F9 shows everyone's) do they campaign, challenge or vote them out.\n"
                 "Ability (under your Roles) is how well you do your job right now, not how content you are. Work "
                 "your office with W to grow its skill: a Clan Leader learns leadership.\n\n")
        t.append("Screens and controls (F-keys)\n", style="bold")
        t.append("When you nominate, vote for or appoint someone, each person shows how well they would do the job "
                 "(Fit), the stats and skill the job uses, and what kind of person they are.\n\n")
        for key, text in [("F1", "This help"), ("F2", "Tribe: everyone as a card of meters (stats, body, content, skills); "
                                                 "arrows choose a member, Enter opens their inventory"),
                          ("F3", "Government: offices, statuses and possible reforms"),
                          ("F4", "Innovations of the current age: status and what each needs; Enter queues research"),
                          ("F5", "Change playback speed"), ("Space", "Pause / resume (you can still act)"),
                          ("F6", "Chronicle detail: everything (everyday life in green) / no everyday life / important only"),
                          ("F7", "Full chronicle history"), ("F8", "Your character sheet: attributes, body, skills"),
                          ("F9", "Society: how well the tribe works and how content everyone is"),
                          ("F10", "Save and quit (also Ctrl+Q)"),
                          ("M", "Auto / manual: on auto the game plays your character exactly like an NPC (you can "
                                "still pause, look at everything and open your inventory); M again gives you back "
                                "full control"),
                          ("F12", "Crafting chart (also K): every item that can be made or found in this age, "
                                  "the job, research, tools and materials it takes, where those come from, and "
                                  "whether it can be had now")]:
            t.append(f"  {key:<6}", style="bold green")
            t.append(text + "\n")
        return t


def carried_text(inv: Optional[Dict[str, Any]]) -> Text:
    """'🎒 4/16  🪨 3  🪵 2  💧 2': what someone carries, in one line."""
    t = Text()
    if not inv:
        return t
    totals: Dict[str, int] = {}
    for s in inv["slots"]:
        if s:
            totals[s["item"]] = totals.get(s["item"], 0) + s["count"]
    t.append(f"🎒 {inv['size'] - inv['free']}/{inv['size']}", style="dim")
    for key in ITEMS:
        if key in totals:
            t.append(f"  {ITEMS[key].icon} {totals[key]}")
    if not totals:
        t.append("  carries nothing", style="dim")
    return t


class MemberCard(Vertical):
    """One member of the tribe on the F2 screen: who they are, then boxes of meters for their
    attributes, body, contentment and skills."""
    LINES = 6

    def __init__(self, p: Dict[str, Any], view: Dict[str, Any]):
        super().__init__(classes="card")
        self.p, self.view = p, view

    def compose(self) -> ComposeResult:
        yield Static(classes="card_head")
        with FlowGrid(classes="card_boxes", min_cell=21, columns=(4, 2, 1)):
            yield MeterBox("Stats", classes="cbox stats")
            yield MeterBox("Body", classes="cbox body")
            yield MeterBox("Content", classes="cbox content")
            yield MeterBox("Skills", classes="cbox skills")

    def on_mount(self):
        self.refresh_card(self.p, self.view)

    def on_click(self):
        self.screen.open_member(self.p["name"])  # type: ignore[attr-defined]

    def refresh_card(self, p: Dict[str, Any], view: Dict[str, Any]):
        self.p, self.view = p, view
        you = p["name"] == view["you"]
        self.set_class(you, "you")
        self.border_title = f"[b]{escape(p['name'])}[/]" + (" [b green](you)[/]" if you else "")
        self.border_subtitle = escape(p["doing"] or "free")
        head = Text()
        life = p.get("life") or {}
        head.append(f"{life.get('gender_icon', '')} age {p['age']} ({p['sheet']['life_stage']})", style="dim")
        icons = life_icons(p)
        if life.get("illness"):
            head.append(f"  {life['illness']['icon']} {life['illness']['name'].lower()}", style="bold red")
        if life.get("pregnancy"):
            pr = life["pregnancy"]
            head.append(f"  {pr['icon']} ", style="")
            head.append(bar(pr["share"], 1, 8), style="magenta")
            head.append(f" month {pr['months']:.0f}/{pr['term_months']:.0f}", style="magenta")
        elif icons and not life.get("illness"):
            head.append(f"  {icons}", style="")
        head.append("  ·  ")
        head.append(positions_of(p) or "Tribe member", style="bold cyan")
        if p["occupations"]:
            head.append(f"  ·  {occupation_icons(view, p)} {', '.join(p['occupations'])}", style="cyan")
        if p.get("work_quality") is not None:
            head.append("  ·  ability ", style="dim")
            head.append(f"{p['work_quality']:.0f}", style="bold " + level_color(p["work_quality"]))
        if not p["can_vote"] and life.get("of_age", True):
            head.append("  ·  cannot vote", style="red")
        if p.get("sheet", {}).get("body_temperature") is not None:
            head.append(f"  ·  {p['sheet']['body_temperature']:.1f}°C", style="dim")
        head.append("\n")
        head.append(p["description"], style="italic")
        if life.get("mother"):
            head.append(f"  (mother: {life['mother']})", style="dim")
        if p["traits"]:
            head.append("  " + ", ".join(p["traits"]), style="dim")
        head.append("\n")
        head.append_text(carried_text(p.get("inventory")))
        self.query_one(".card_head", Static).update(head)
        lines = max(self.LINES, len(view["satisfaction"]) + 1)  # every meter, then mood
        self.query_one(".stats", MeterBox).show(attribute_rows(p), lines)
        self.query_one(".body", MeterBox).show(lambda width: body_rows(p["sheet"], words=width >= 24), lines)
        self.query_one(".content", MeterBox).show(content_rows(view, p["satisfaction"], p.get("mood"),
                                                               p.get("content_rising")), lines)
        self.query_one(".skills", MeterBox).show(skill_rows(p["sheet"]["skills"], lines), lines)


class TribeScreen(InfoScreen):
    """Everyone in the tribe as a card of meters. Stays live while open. Arrows choose a member;
    Enter (or I, or a click) opens their inventory."""
    KEY = "f2"

    def __init__(self, view: Dict[str, Any]):
        super().__init__(view)
        names = [p["name"] for p in view["players"]]
        self.selected = names.index(view["you"]) if view["you"] in names else 0

    def on_key(self, event) -> None:
        if self.app.screen is not self:
            return
        cards = list(self.query(MemberCard))
        if event.key in ("left", "right", "up", "down") and cards:
            cols = self.query_one("#tribe_grid").styles.grid_size_columns or 1
            step = {"left": -1, "right": 1, "up": -cols, "down": cols}[event.key]
            if 0 <= self.selected + step < len(cards):
                self.selected += step
            self._mark(cards)
            cards[self.selected].scroll_visible()
            event.stop()
            event.prevent_default()
        elif event.key in ("enter", "i") and cards:
            event.stop()
            self.open_member(cards[self.selected].p["name"])
        else:
            super().on_key(event)

    def _mark(self, cards=None):
        for i, card in enumerate(cards or self.query(MemberCard)):
            card.set_class(i == self.selected, "selected")

    def open_member(self, name: str):
        names = [c.p["name"] for c in self.query(MemberCard)]
        if name in names:
            self.selected = names.index(name)
            self._mark()
        self.app.push_screen(InventoryScreen(name))

    def compose(self) -> ComposeResult:
        with Vertical(id="info"):
            yield Static(self._head(self.view), id="tribe_head")
            with VerticalScroll(id="tribe_scroll"):
                with FlowGrid(id="tribe_grid", min_cell=84, columns=(3, 2, 1)):
                    for p in self.view["players"]:
                        yield MemberCard(p, self.view)
            yield Label(Text("Arrows choose a member · Enter or click opens their inventory · PgUp PgDn scroll · "
                             "Esc or F2 to close · bars update live", style="dim"))

    def on_mount(self):
        self.query_one("#tribe_scroll").focus()
        self._mark()

    @staticmethod
    def _head(view: Dict[str, Any]) -> Text:
        t = Text()
        t.append("Tribe", style="bold cyan")
        t.append(f"   {len(view['players'])} members", style="dim")
        moods = [p.get("mood", 50) for p in view["players"]]
        if moods:
            avg = sum(moods) / len(moods)
            t.append("   ·   average mood ", style="dim")
            t.append(f"{avg:.0f}", style="bold " + level_color(avg))
        life = view.get("life", {})
        kids = sum(1 for p in view["players"] if (p.get("life") or {}).get("child"))
        if kids:
            t.append(f"   ·   {kids} children", style="dim")
        ill = [p["name"] for p in view["players"] if (p.get("life") or {}).get("illness")]
        if ill:
            t.append(f"   ·   ill: {', '.join(ill)}", style="bold red")
        if life.get("bodies"):
            t.append(f"   ·   {len(life['bodies'])} dead lying in camp: "
                     f"{', '.join(b['name'] for b in life['bodies'])} (sickness spreads ×{life.get('illness_factor', 1):g})",
                     style="bold red")
        t.append(f"   ·   born {life.get('births', 0)}, died {life.get('deaths', 0)}", style="dim")
        t.append("\nStats: attributes (1-10) · Body: health and needs · Content: how satisfied they are "
                 "(0-100) · Skills: their best (0-10)", style="dim")
        return t

    def refresh_view(self, view: Dict[str, Any]):
        self.view = view
        self.query_one("#tribe_head", Static).update(self._head(view))
        by_name = {p["name"]: p for p in view["players"]}
        cards = list(self.query(MemberCard))
        if [c.p["name"] for c in cards] != list(by_name):  # someone was born or has died
            grid = self.query_one("#tribe_grid")
            grid.remove_children()
            grid.mount(*[MemberCard(p, view) for p in view["players"]])
            self.selected = min(self.selected, len(by_name) - 1)
            self.call_after_refresh(self._mark)
            return
        for card in cards:
            if card.p["name"] in by_name:
                card.refresh_card(by_name[card.p["name"]], view)


class GovernmentScreen(InfoScreen):
    KEY = "f3"

    def body(self) -> Text:
        v, gov = self.view, self.view["government"]
        t = Text()
        t.append(f"{gov['name']}", style="bold cyan")
        t.append(f"  ({gov['age']})\n{gov['description']}\nChanged by {gov['reformed_by']}.\n\n")
        t.append("Offices\n", style="bold")
        for name, o in v["offices"].items():
            t.append(f"  {name} ({len(o['holders'])}/{o['seats']}): ", style="bold")
            t.append(", ".join(o["holders"]) or "vacant")
            if not o["unlocked"]:
                t.append(f"  [needs {', '.join(o['requires'])}]", style="red")
            ways = ["persuasion"] if o.get("persuadable") else []
            if o.get("challenges"):
                ways.append("challenge (" + ", ".join(o["challenges"]).replace("skill", "a contest in one's own work") + ")")
            also = f"    Can also be taken by {' or '.join(ways)}\n" if ways else ""
            t.append(f"\n    {o['description']}\n    Chosen by {o['selected_by']}; removed by {o['removed_by']}\n"
                     f"{also}    Interfaces: {', '.join(o['interfaces']) or 'none'}\n", style="dim")
        if v["statuses"]:
            t.append("\nStatuses\n", style="bold")
        for name, s in v["statuses"].items():
            t.append(f"  {name}: ", style="bold")
            t.append(", ".join(s["holders"]) or "none")
            if not s["unlocked"]:
                t.append(f"  [needs {', '.join(s['requires'])}]", style="red")
            t.append(f"\n    {s['description']} Granted by {s['granted_by']}.\n", style="dim")
        t.append(f"\nEvery member can use: {', '.join(gov['member_interfaces']) or 'nothing'}. "
                 f"A player may hold {gov['max_offices_per_player']} office(s).\n\n")
        t.append("Work (occupations)\n", style="bold")
        for name, o in v["occupations"].items():
            seats = f"{len(o['holders'])}/{o['seats']}" if o["seats"] else f"{len(o['holders'])}"
            t.append(f"  {o['icon']} {name} ({seats}): ", style="bold")
            t.append(", ".join(o["holders"]) or "nobody")
            if not o["unlocked"]:
                t.append(f"  [needs {', '.join(o['requires'])}]", style="red")
            how = ("anyone may volunteer" if o["open"] and not o["appointed_by"] else
                   f"appointed by the {' or '.join(o['appointed_by'])}" + ("; volunteers welcome" if o["open"] else ""))
            t.append(f"\n    {o['description']} {how.capitalize()}. Suits {', '.join(o['attributes'])}"
                     + (f"; trains {o['skill']}" if o["skill"] else "") + f"; +{o['points']} innovation pts/yr.\n",
                     style="dim")
        t.append("\nPossible reforms\n", style="bold")
        if not gov["available_reforms"]:
            t.append("  None yet. New forms of government open with new ages and innovations.\n", style="dim")
        if gov["available_reforms"] and gov["reform_cooldown_days"]:
            t.append(f"  No reform for {gov['reform_cooldown_days']} more days.\n", style="yellow")
        for r in gov["available_reforms"]:
            offices = ", ".join(f"{n} x{o['seats']}" if o["seats"] > 1 else n for n, o in r["offices"].items())
            t.append(f"  {r['name']}", style="bold")
            t.append(f" ({r['age']}): {r['description']}\n    Offices: {offices}\n"
                     f"    You would be: {r['outcome'].get(v['you']) or 'no office'}\n", style="dim")
        return t


class CharacterScreen(InfoScreen):
    """Your full character sheet."""
    KEY = "f8"

    def body(self) -> Text:
        v = self.view
        c = v["character"]
        me = next(p for p in v["players"] if p["name"] == v["you"])
        t = Text()
        t.append(f"{v['you']}", style="bold cyan")
        t.append(f"  age {c['age']} ({c['life_stage']})  ·  {', '.join(v['your_positions']) or 'Tribe member'}")
        if v["your_occupations"]:
            t.append(f"  ·  {occupation_icons(v, me)} {', '.join(v['your_occupations'])}", style="cyan")
        t.append(f"\n{me['description']}  ", style="italic")
        t.append(f"Traits: {', '.join(c['traits'])}\n\n", style="dim")
        t.append("Attributes\n", style="bold")
        for k, a in CHARACTER.attributes.items():
            val = c["attributes"][k]
            t.append(f"  {a.name:<13}", style="bold")
            t.append(f"{val:>2} {bar(val, CHARACTER.attr_max, 10)}  ")
            t.append(a.description + "\n", style="dim")
        t.append("\nBody\n", style="bold")
        t.append(f"  {'Health':<13}{c['health']:>3} {bar(c['health'], 100, 10)}\n",
                 style="bold red" if c["health"] < 50 else "")
        if c.get("body_temperature") is not None:
            w = v["world"]
            t.append(f"  {'Temperature':<13}{c['body_temperature']:.1f}°C  (air {w['temperature']:g}°C, "
                     f"comfortable at {w['comfort']}°C)\n")
        for k, n in CHARACTER.needs.items():
            need = c["needs"][k]
            t.append(f"  {n.icon} {n.name:<10}", style="bold")
            t.append(f"{need['value']:>3} {bar(need['value'], 100, 10)} {need['label']}\n",
                     style=need_style(need["value"], need["critical"]))
        t.append("  Press E to eat, drink, sleep or warm up. Needs fall over the day-night cycle; "
                 "an empty one wears down health. Health comes back only while you are not working (fastest resting or "
                 "asleep).\n", style="dim")
        life = c.get("life") or {}
        t.append("\nLife\n", style="bold")
        t.append(f"  {life.get('gender_icon', '')} {life.get('gender_name', '')}, {c['life_stage'].lower()}"
                 + (f", mother {life['mother']}" if life.get("mother") else "") + "\n")
        for kind, headline, detail in life_status(life):
            t.append(f"  {headline}: ", style="bold red" if kind == "illness" else "bold magenta" if kind == "pregnancy"
                     else "bold cyan")
            t.append(detail + "\n")
            if kind == "pregnancy":
                t.append(f"  {bar(life['pregnancy']['share'], 1, 30)}\n", style="magenta")
            if kind == "illness" and life["illness"].get("description"):
                t.append(f"  {life['illness']['description']}\n", style="dim")
        if life.get("child") and life.get("growth"):
            t.append("  Growing toward: " + ", ".join(f"{CHARACTER.attributes[k].abbr} {c['attributes'][k] + 1} "
                                                      f"({v:.0%})" for k, v in life["growth"].items()) + "\n", style="dim")
        t.append(f"  Work from age {life.get('work_age', 9):g}; vote and hold office from {life.get('politics_age', 14):g}. "
                 "The old fall ill more often and are cured less often.\n", style="dim")
        t.append_text(contentment_text(v))
        t.append("\nSkills\n", style="bold")
        for k, sdef in CHARACTER.skills.items():
            val = c["skills"][k]
            t.append(f"  {sdef.name:<13}", style="bold" if val else "dim")
            t.append(f"{val:>4.1f} {bar(val, CHARACTER.skill_max, 10)}  ", style="" if val else "dim")
            t.append(f"({CHARACTER.attributes[sdef.attribute].abbr}) {sdef.description}\n", style="dim")
        t.append("  Skills grow while you do the work that uses them; talent (the attribute) speeds learning.\n",
                 style="dim")
        return t


def contentment_text(v: Dict[str, Any]) -> Text:
    """Each of your contentment meters: where it is heading and what speeds or slows its rise."""
    t = Text()
    t.append("\nContent", style="bold")
    doing = v.get("working_now")
    t.append(f"  (working as {doing[7:] if doing.startswith('office:') else doing} now)\n" if doing else
             "  (not working your job right now: Work does not rise)\n", style="dim")
    for key, m in v["satisfaction"].items():
        val = m["value"]
        t.append(f"  {m['name']:<13}", style="bold")
        t.append(f"{val:>3.0f} {bar(val, 100, 10)} ", style=sat_style(val).replace("b ", "bold "))
        if m.get("rising") is None:
            t.append("\n")
            continue
        t.append("▲ rising" if m["rising"] else "▼ falling", style="green" if m["rising"] else "red")
        if m.get("target") is not None:
            t.append(f" toward {m['target']:.0f}", style="dim")
        factors = m.get("factors") or []
        if factors and m.get("multiplier") is not None:
            t.append(f"  rises ×{m['multiplier']:g} as fast: ", style="dim")
        elif factors:
            t.append("  ", style="dim")
        t.append(" · ".join(f"{f['label']}: {f['detail']}" + (f" ×{f['mult']:g}" if f.get("mult") is not None else "")
                            for f in factors), style="dim")
        t.append("\n")
    t.append("  Work rises only while you work your job (W): faster with the right tools (two or more, faster still), "
             "the more of your age's jobs are open, and the better you fit it. Safety rises with Warriors on patrol "
             "and every position filled; Comfort with the fire being used (people warming up), care, and the Spirit "
             "Keeper's rituals; Leaders "
             "with everything else going well.\n", style="dim")
    pat = v.get("patience") or {}
    if pat:
        t.append("\nPatience", style="bold")
        t.append("  (how long you'd put up with things before moving against those in charge; NPCs act only "
                 "once theirs runs out)\n", style="dim")
        for key, d in pat.items():
            name = v["satisfaction"].get(key, {}).get("name", key)
            text, style = patience_cell({key: d})
            t.append(f"  {name:<13}", style="bold")
            t.append(f"{text:<12}", style=style)
            t.append(f"unhappy {d['unrest']:g} of {d['grace']:g} hours allowed while {name} is below {d['below']:g}\n",
                     style="dim")
    ab = v.get("ability")
    if ab:
        t.append("\nAbility", style="bold")
        t.append(f"  {ab['value']:.0f}/100 as {ab['job']}", style="bold " + level_color(ab["value"]))
        t.append(f"  (not contentment: how well you do the job: {', '.join(ab['attributes'])}"
                 + (f" and {ab['skill_name'].lower()} {ab['skill_level']:.2f}" if ab.get("skill_name") else "")
                 + f" make {ab['rested']:.0f} rested and well"
                 + (f", tired -{ab['tired']:.0f}" if ab["tired"] >= 0.5 else "")
                 + (f", unwell -{ab['unwell']:.0f}" if ab["unwell"] >= 0.5 else "")
                 + ". Work your job (W) to practise the skill.)\n", style="dim")
    return t


class SocietyScreen(InfoScreen):
    """How well the society works (qualities, who feeds them) and how everyone feels."""
    KEY = "f9"

    def body(self) -> Text:
        v = self.view
        soc = v["society"]
        t = Text()
        t.append("Society ", style="bold cyan")
        t.append(f"{soc['score']:.0f}/100", style=sat_style(soc["score"]).replace("b ", "bold "))
        t.append("   how well the tribe works (weighted average of the qualities below)\n\n", style="dim")
        for q in soc["qualities"].values():
            t.append(f"  {q['icon']} {q['name']:<11}", style="bold" if q["active"] else "dim")
            if not q["active"]:
                t.append("not yet (needs an innovation)\n", style="dim")
                continue
            t.append(f"{q['value']:>4.0f} {bar(q['value'], 100, 12)}", style=sat_style(q["value"]).replace("b ", "bold "))
            d = q["detail"]
            shock = f" · {d['shock']:+.0f} from a death, coming back" if d.get("shock") else ""
            if "level" in d:  # raised only by use (people warming up at the fire)
                t.append(f"  +{d['per_use']:g} each time someone warms up at the fire"
                         + (f", -{d['fall_per_day']:g} a day-night otherwise" if d.get("fall_per_day") else
                            "; otherwise it stays the same") + f"{shock}\n", style="dim")
            elif "seats" in d:
                seats = ", ".join(f"{o}: {n or 'vacant'} {val:.0f}" for o, n, val in d["seats"])
                t.append(f"  {seats}{shock}\n", style="dim")
            else:
                who = ", ".join(f"{n} {wq:.0f}" for _, n, wq in d["workers"]) or "nobody"
                cats = f" · kinds covered: {', '.join(d['categories']) or 'none'} (of {', '.join(d['all_categories'])})" \
                    if d.get("all_categories") else ""
                held = d.get("on_hand")
                stock = f" · on hand {held['have']} of {held['want']} points" if held else ""
                sick = d.get("sick")
                ill = f" · {sick['count']} ill" if sick and sick.get("count") else ""
                t.append(f"  work {d['supply']:g} of {d['need']:g} needed · {who}{cats}{stock}{ill}{shock}\n", style="dim")
        t.append("\nHow content everyone is ", style="bold")
        t.append("(each meter moves toward what they experience, faster or slower by tools, choice of work, "
                 "Warriors on patrol, rituals...; F8 shows what moves yours)\n", style="dim")
        meters = list(v["satisfaction"].items())
        t.append(f"  {'':<8}" + "".join(f"{m['name'][:8]:>9}" for _, m in meters) + "     mood  ability  patience\n",
                 style="bold")
        for p in v["players"]:
            t.append(f"  {p['name']:<8}", style="bold green" if p["name"] == v["you"] else "bold")
            for key, _ in meters:
                val = p["satisfaction"].get(key, 50)
                t.append(f"{val:>9.0f}", style=sat_style(val).replace("b ", "bold "))
            t.append(f"{p['mood']:>9.0f}", style=sat_style(p["mood"]).replace("b ", "bold "))
            wq = p.get("work_quality")
            t.append(f"  {'-' if wq is None else f'{wq:.0f}':>7}",
                     style="dim" if wq is None else level_color(wq))
            t.append("  ")
            t.append(*patience_cell(p.get("patience", {})))
            t.append("\n")
        t.append("\nAbility is not contentment: it is how well someone does their best job or office right now "
                 "(attributes and skill, less when tired or unwell). It sets how much their work yields and how "
                 "much it adds to the society qualities above. It dips as they tire and recovers with sleep; it "
                 "grows as they practise.\n"
                 "Patience: unhappy people put up with it for a while before they act. While patience lasts (∙ to ◔) "
                 "they only grumble; once it runs out (●) they campaign, challenge, call for removal votes and "
                 "change. It comes back once their Leaders (and Society) contentment recovers.\n", style="dim")
        return t


class LogScreen(InfoScreen):
    KEY = "f7"

    def __init__(self, view, history: List[Message], detail: str):
        super().__init__(view)
        self.history, self.detail = history, detail

    def compose(self) -> ComposeResult:
        with Vertical(id="info"):
            yield RichLog(id="fulllog", wrap=True, markup=False, min_width=20)
            yield Label(Text("Esc or F7 to close · ↑↓ PgUp PgDn to scroll", style="dim"))

    def on_mount(self):
        log = self.query_one("#fulllog", RichLog)
        for m in self.history:
            line = message_text(m, self.detail)
            if line is not None:
                log.write(line)


STATUS_STYLE = {"discovered": ("✓", "green"), "researching": ("▶", "bold yellow"), "queued": ("…", "yellow"),
                "available": ("○", "cyan"), "locked": ("·", "dim")}
STATUS_FILTERS = ["all", "available", "in progress", "discovered", "locked"]


class InnovationScreen(InfoScreen):
    """Every innovation in the game with its status. Enter queues the highlighted one for research."""
    KEY = "f4"

    def __init__(self, view, legal, controller: HUDController, focus: Optional[str] = None):
        super().__init__(view)
        self.legal, self.controller, self.focus_name = legal, controller, focus
        self.age_name, self.rows = current_age_innovations(view)
        self.status_filter = 0
        self.role_filter = -1  # -1 = all roles
        self.shown = []

    def compose(self) -> ComposeResult:
        with Vertical(id="info"):
            yield Static(id="innov_head")
            yield DataTable(id="innov_table", cursor_type="row", zebra_stripes=True)
            yield Static(id="innov_detail")
            yield Label(Text("s status filter · i role filter · Enter research highlighted · Esc/F4 close", style="dim"))

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("", "", "Innovation", "Kind", "Who researches it", "Cost", "Needs", "Status")
        self._fill()
        table.focus()
        if self.focus_name:
            row = next((i for i, r in enumerate(self.shown) if r.name == self.focus_name), 0)
            table.move_cursor(row=row)
            self._detail(row)

    def _fill(self):
        status = STATUS_FILTERS[self.status_filter]
        role = None if self.role_filter < 0 else INTERFACES[self.role_filter]
        mine = set(self.view["your_interfaces"])

        def keep(r):
            if role and r.interface != role:
                return False
            if status == "in progress":
                return r.status in ("researching", "queued")
            return status == "all" or r.status == status
        self.shown = [r for r in self.rows if keep(r)]
        table = self.query_one(DataTable)
        table.clear()
        for r in self.shown:
            mark, style = STATUS_STYLE[r.status]
            label = r.status + (" (you can)" if r.you_can_research else "")
            table.add_row(Text(mark, style=style), r.icon, Text(r.name, style=style if r.status != "locked" else "dim"),
                          Text(r.interface.replace("_", " "), style="bold" if r.interface in mine else "dim"),
                          self._who(r), str(r.cost), self._needs(r), Text(label, style=style))
        counts = {s: sum(1 for r in self.rows if r.status == s) for s in STATUS_STYLE}
        head = Text()
        head.append(f"Innovations of the {self.age_name}  ", style="bold cyan")
        head.append(f"{counts['discovered']} discovered · {counts['researching'] + counts['queued']} in progress · "
                    f"{counts['available']} available · {counts['locked']} locked     ", style="dim")
        head.append(f"showing: {status}, {role.replace('_', ' ') if role else 'all roles'}", style="yellow")
        self.query_one("#innov_head", Static).update(head)
        self._detail(0)

    def _who(self, r) -> Text:
        """The roles of this government that research this kind of innovation (nobody: it can't be yet)."""
        who = self.view.get("research_roles", {}).get(r.interface, [])
        return Text(", ".join(who) if who else "nobody yet", style="cyan" if who else "red")

    @staticmethod
    def _needs(r) -> Text:
        """Prerequisites, green when discovered and red when still missing."""
        t = Text()
        for i, p in enumerate(r.prerequisites):
            t.append((", " if i else "") + p, style="red" if p in r.missing else "green")
        return t if r.prerequisites else Text("—", style="dim")

    def _detail(self, index: int):
        t = Text()
        if 0 <= index < len(self.shown):
            r = self.shown[index]
            t.append(f"{r.icon} {r.name}", style="bold")
            t.append(f"  ({r.interface.replace('_', ' ')}, {r.age}, cost {r.cost})\n{r.description}\n")
            who = self.view.get("research_roles", {}).get(r.interface, [])
            t.append("Researched by: " + (", ".join(who) if who else "no role in this government") + "\n",
                     style="cyan" if who else "red")
            if r.prerequisites:
                t.append("Needs: " + ", ".join(f"{p}{'' if p not in r.missing else ' (missing)'}"
                                               for p in r.prerequisites) + "\n", style="dim")
            if r.why_locked:
                t.append(f"Locked: {r.why_locked}\n", style="red")
            if r.unlocks:
                t.append(f"Opens: {r.unlocks}\n", style="green")
        self.query_one("#innov_detail", Static).update(t)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        self._detail(event.cursor_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        if not 0 <= event.cursor_row < len(self.shown):
            return
        r = self.shown[event.cursor_row]
        action = next((a for a in self.legal if a.type == "research" and a.params["innovation"] == r.name), None)
        if action is None:
            why = r.why_locked or ("it is already " + r.status if r.status != "available"
                                   else "none of your roles can research it, or you are busy")
            self.app.notify(f"Can't research {r.name}: {why}.", severity="warning")
            return
        self.controller.submit(Decision(action))
        self.app.notify(f"Queuing {r.name} for research.")
        self.dismiss(None)

    def on_key(self, event) -> None:
        if event.character == "s":
            event.stop()
            self.status_filter = (self.status_filter + 1) % len(STATUS_FILTERS)
            self._fill()
        elif event.character == "i":
            event.stop()
            self.role_filter = self.role_filter + 1 if self.role_filter + 1 < len(INTERFACES) else -1
            self._fill()


class CraftScreen(InfoScreen):
    """The crafting chart: every item the tribe can make or find in this age, who makes it, the research,
    tools and materials it takes, and whether it can be had now. Opened with F12 or K."""
    KEY = "f12"
    STATUS = {"ready": ("✓", "green"), "short": ("…", "yellow"), "no_tool": ("…", "yellow"),
              "no_worker": ("…", "yellow"), "research": ("✗", "red")}

    def __init__(self, view):
        super().__init__(view)
        self.rows = craft_catalog(view)
        self.filter = 0
        self.shown = []

    def compose(self) -> ComposeResult:
        with Vertical(id="info"):
            yield Static(id="craft_head")
            yield DataTable(id="craft_table", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="craft_detail_box"):
                yield Static(id="craft_detail")
            yield Label(Text("↑↓ choose an item · s show all / can be had now / not yet · Esc, F12 or K to close",
                             style="dim"))

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("", "", "Item", "Kind", "Made / found by", "Research", "Takes", "Store", "Now", "Used by")
        self._fill()
        table.focus()

    def _fill(self):
        which = CRAFT_FILTERS[self.filter]
        self.shown = [r for r in self.rows if which == "all" or (r.status == "ready") == (which == "can be had now")]
        table = self.query_one(DataTable)
        table.clear()
        for r in self.shown:
            mark, style = self.STATUS[r.status]
            research = Text()
            for i, x in enumerate(r.research):
                research.append((", " if i else "") + x["name"], style="green" if x["done"] else "red")
            table.add_row(Text(mark, style=style), r.icon, r.name, Text(r.kind, style="dim"),
                          r.by, research if r.research else Text("—", style="dim"), r.takes,
                          Text(str(r.store), style="dim" if not r.store else ""), Text(r.why, style=style),
                          Text(r.used_for, style="cyan" if r.used_by else "dim"), height=None)
        ready = sum(1 for r in self.rows if r.status == "ready")
        head = Text()
        head.append(f"Crafting and gathering — {self.view['crafts']['age']}  ", style="bold cyan")
        head.append(f"{len(self.rows)} items · {ready} can be had now · {len(self.rows) - ready} not yet     ", style="dim")
        head.append(f"showing: {which}", style="yellow")
        self.query_one("#craft_head", Static).update(head)
        self._detail(0)

    def _detail(self, index: int):
        t = Text()
        if 0 <= index < len(self.shown):
            for text, style in craft_detail(self.view, self.shown[index]):
                t.append(text, style=style)
        self.query_one("#craft_detail", Static).update(t)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        self._detail(event.cursor_row)

    def on_key(self, event) -> None:
        if event.character == "s":
            event.stop()
            self.filter = (self.filter + 1) % len(CRAFT_FILTERS)
            self._fill()
        elif event.character == "k" and self.app.screen is self:
            event.stop()
            self.dismiss(None)


class InnovationPool(Static):
    """The innovation pool box: clicking an icon opens that innovation in F4; clicking elsewhere opens F4."""

    def on_click(self) -> None:
        def open_if_nothing_else():
            if isinstance(self.app.screen, CommandCenter):
                self.app.screen.action_info("innovations")
        self.call_after_refresh(open_if_nothing_else)


# --------------------------------------------------------------------------- #
# Main screen
# --------------------------------------------------------------------------- #
class CommandCenter(Screen):
    BINDINGS = [
        Binding("f1", "info('help')", "Help"),
        Binding("f2", "info('tribe')", "Tribe"),
        Binding("f3", "info('government')", "Government"),
        Binding("f4", "info('innovations')", "Innovations"),
        Binding("f5", "speed", "Speed"),
        Binding("space", "pause", "Pause"),
        Binding("f6", "detail", "Detail"),
        Binding("f7", "info('log')", "Log"),
        Binding("f8", "info('character')", "Character"),
        Binding("f9", "info('society')", "Society"),
        Binding("f10", "app.save_quit", "Save and quit"),
        Binding("f12", "info('crafts')", "Crafts"),
        Binding("k", "info('crafts')", "Crafts", show=False),
        Binding("m", "toggle_auto", "Auto/manual"),
    ] + [Binding(k, f"act('{t}')", show=False) for k, t in
         [("v", "vote"), ("n", "nominate"), ("a", "appoint"), ("d", "dismiss"), ("c", "call_vote"),
          ("f", "reform"), ("r", "research"), ("o", "role_command"), ("e", "care"), ("j", "take_occupation"),
          ("x", "stop"), ("p", "persuade"), ("h", "challenge"), ("i", "inventory"), ("w", "work"), ("g", "resign")]]

    def compose(self) -> ComposeResult:
        yield Static(id="top")
        with Horizontal(id="main"):
            yield RichLog(id="chronicle", wrap=True, markup=False, max_lines=600, auto_scroll=True, min_width=20)
            with Vertical(id="center"):
                with Vertical(id="you"):
                    with Horizontal(id="you_head"):
                        yield Static(id="you_id")
                        yield MeterBox("Roles", id="you_roles", classes="box")
                    with FlowGrid(id="you_boxes", min_cell=22, columns=(3, 1)):
                        yield MeterBox("Body", id="you_body", classes="box")
                        yield MeterBox("Skills", id="you_skills", classes="box")
                        yield MeterBox("Content", id="you_content", classes="box")
                    yield ActionBar(id="you_actions", classes="box")
                yield VerticalScroll(Static(id="ballots_body"), id="ballots")
                yield InnovationPool(id="innovations")
            with Vertical(id="right"):
                yield VerticalScroll(Static(id="tribe_body"), id="tribe")
                yield VerticalScroll(Static(id="places_body"), id="places")
        yield Static(id="fkeys")
        yield Static(id="status")

    def on_mount(self):
        self.query_one("#chronicle").border_title = "Chronicle"
        self.query_one("#you").border_title = "You"
        self.query_one("#you_skills").border_subtitle = "F8 all"
        self.query_one("#you_actions").border_title = "Actions"
        self.query_one("#ballots").border_title = "Government and votes"
        self.query_one("#innovations").border_title = "Innovation pool"
        self.query_one("#innovations").border_subtitle = "click an icon, or F4"
        self.query_one("#tribe").border_title = "Tribe"
        self.query_one("#places").border_title = "Found places"
        self.query_one("#fkeys", Static).update(
            "[@click=screen.info('help')][b green]F1[/] help[/]  [@click=screen.info('tribe')][b green]F2[/] tribe[/]  "
            "[@click=screen.info('government')][b green]F3[/] government[/]  "
            "[@click=screen.info('innovations')][b green]F4[/] innovations[/]  "
            "[@click=screen.speed][b green]F5[/] speed[/]  [@click=screen.pause][b green]Space[/] pause[/]  "
            "[@click=screen.detail][b green]F6[/] detail[/]  [@click=screen.info('log')][b green]F7[/] log[/]  [@click=screen.info('character')][b green]F8[/] you[/]  [@click=screen.info('society')][b green]F9[/] society[/]  "
            "[@click=app.save_quit][b green]F10[/] save+quit[/]  [@click=screen.info('crafts')][b green]F12[/] crafts[/]  "
            "[@click=screen.toggle_auto][b green]M[/] auto/manual[/]")

    @property
    def hud(self) -> 'GovGenHUD':
        return self.app  # type: ignore

    # ------------------------------------------------------------------ #
    # Drawing
    # ------------------------------------------------------------------ #
    def draw(self, view: Dict[str, Any], legal: list):
        hud = self.hud
        gov = view["government"]
        pacer = hud.pacer
        speed = "[b red]❚❚ PAUSED[/]" if pacer.paused else f"▶ {pacer.describe()}"
        speed = ("[b black on magenta] AUTO [/] " if hud.controller.auto else "[b black on green] MANUAL [/] ") + speed
        self.query_one("#top", Static).update(
            f" [b]GovGen[/]  │  [b]{escape(view['date'])}[/]  │  {escape(view['age']['name'])}  │  "
            f"{escape(gov['name'])}  │  {self._sky(view['world'])}  │  {self._camp(view)}  │  {speed}")
        self._draw_you(view, legal)
        self._draw_ballots(view, legal)
        self._draw_tribe(view)
        self._draw_places(view)
        self._draw_innovations(view)
        self.set_status()

    @staticmethod
    def _camp(view) -> str:
        """What the camp store holds (items.json 'camp_summary'): plain counts, as in the inventory window."""
        parts = [f"{g['icon']} [b{' red' if g['empty_warning'] and not g['count'] else ''}]{g['count']}[/]"
                 for g in camp_line(view)]
        return "[dim]camp[/] " + "   ".join(parts) if parts else ""

    @staticmethod
    def _sky(w) -> str:
        icon = {"Night": "🌙", "Dawn": "🌅", "Dusk": "🌇"}.get(w["time_of_day"], "🌞")
        left = bar(1 - w["half_progress"], 1, 6)
        until = "dawn" if w["night"] else "dusk"
        fire = f"[b yellow]fire {w['fire_temperature']:g}°C[/]" if w.get("fire") else "[red]no fire[/]"
        return f"{icon} {w['time_of_day']} [dim]{left} to {until}[/]  air {w['temperature']:g}°C  {fire}"

    def _draw_you(self, v, legal):
        """Who you are and what you can do: a header (name, age, attributes, what you're doing), boxes of
        meters (body, skills, content, roles) and your action keys grouped by kind."""
        me = next(p for p in v["players"] if p["name"] == v["you"])
        c = v["character"]

        # Header: who you are and what you're doing on the left, your Roles box on the right.
        sep = "  " if self.query_one("#you_id").content_size.width >= 42 else " "
        life = c.get("life") or {}
        head = [f"[b]{escape(v['you'])}[/] {escape(life.get('gender_icon', ''))}  [dim]age[/] {c['age']} "
                f"[dim]({escape(c['life_stage'])})[/]",
                f"[i]{escape(me['description'])}[/]" + (f" [dim]({escape(', '.join(c['traits']))})[/]" if c.get("traits") else ""),
                sep.join(f"[dim]{a.abbr}[/] [b]{c['attributes'][k]}[/]" for k, a in CHARACTER.attributes.items())]
        if v["free"]:
            head.append("[b black on green] READY [/] [dim]free to act[/]")
        else:
            head.append(f"[b black on yellow] {escape(v['doing'] or 'busy')} [/] "
                        f"[dim]{format_life_duration(v['busy_hours_left'])} left[/]"
                        + ("  [@click=screen.act('stop')][b black on green] X [/] [green]stop[/][/]" if v.get("can_stop") else ""))
        side = v.get("side")
        if side and side["hours_left"] > 0:  # a second thing going on: a talk while working
            head.append(f"[b black on yellow] {escape(side['doing'])} [/] "
                        f"[dim]{format_life_duration(side['hours_left'])} left · on the side[/]")
        elif side and side.get("can_talk"):
            head.append("[b black on green] P [/] [green]ready to talk again[/] [dim](while you work)[/]")
        for kind, headline, detail in life_status(life):  # ill, with child, a child (data/life.json)
            if kind == "illness":
                head.append(f"[b white on red] {escape(headline)} [/] [red]{escape(detail)}[/]")
            elif kind == "pregnancy":
                pr = life["pregnancy"]
                head.append(f"[b black on magenta] {escape(headline)} [/] [magenta]{bar(pr['share'], 1, 12)}[/] "
                            f"[dim]{escape(detail)}[/]")
            else:
                head.append(f"[b black on cyan] {escape(headline)} [/] [dim]{escape(detail)}[/]")
        if v.get("contest_cooldown_hours"):
            head.append(f"[dim]after losing a contest: no new campaign or challenge for "
                        f"{format_life_duration(v['contest_cooldown_hours'])}[/]")
        ic = v.get("in_contest")
        if ic:
            hint = {"audience": "[b green]P[/] speak · eat, drink, vote",
                    "duel": "fighting until one yields"}.get(ic["style"], "can eat, drink, vote")
            head.append(f"[b white on dark_magenta] {escape(ic['name'])} vs {escape(ic['opponent'])} [/] {hint}")
        self.query_one("#you_id", Static).update("\n".join(head))
        self.query_one("#you_roles", MeterBox).show(lambda width: self._role_rows(v, me, width))

        # Meter boxes, all the same height (room for every contentment meter).
        lines = max(5, len(v["satisfaction"]))
        body = self.query_one("#you_body", MeterBox)
        body.border_subtitle = f"{c['body_temperature']:.1f}°C" if c.get("body_temperature") is not None else ""
        if life.get("illness"):
            body.border_subtitle = f"[b red]{escape(life['illness']['icon'])} ill[/]  " + body.border_subtitle
        body.show(lambda width: body_rows(c, words=width >= 24), lines)
        self.query_one("#you_skills", MeterBox).show(skill_rows(c["skills"], lines), lines)
        content = self.query_one("#you_content", MeterBox)
        content.border_subtitle = f"mood [{sat_style(v['mood'])}]{v['mood']:.0f}[/]"
        content.show(content_rows(v, {k: m["value"] for k, m in v["satisfaction"].items()}), lines)

        self.query_one("#you_actions", ActionBar).show(action_groups(v, legal))

    @staticmethod
    def _role_rows(v, me, width: int) -> List[Any]:
        """Your place in the tribe: offices and statuses, your work and how well you do it, and the roles
        (powers) they give you, wrapped to `width`."""
        rows: List[Any] = []
        t = Text()
        for i, pos in enumerate(me["offices"] + me["statuses"]):
            t.append(", " if i else "")
            t.append(pos, style="bold red" if pos in me["statuses"] and pos not in me["offices"] else "bold cyan")
        if not t.plain:
            t.append("Tribe member", style="bold cyan")
        if me["occupations"]:
            t.append("  ·  ", style="dim")
            t.append(f"{occupation_icons(v, me)} {', '.join(me['occupations'])}", style="cyan")
        elif not me["offices"] and (me.get("life") or {}).get("child"):
            t.append("  ·  ", style="dim")
            t.append("a child: plays and studies (W)", style="dim")
        elif not me["offices"]:
            t.append("  ·  ", style="dim")
            t.append("no work (J)", style="dim")
        if not me["can_vote"] and (me.get("life") or {}).get("of_age", True):
            t.append("  ·  cannot vote", style="red")
        elif not me["can_vote"]:
            t.append(f"  ·  votes from {(me.get('life') or {}).get('politics_age', 14):g}", style="dim")
        rows.append(t)
        ab = v.get("ability")
        if ab is not None:
            wq = ab["value"]
            rows.append(MeterRow("Ability", wq, 100, level_color(wq), f"{wq:.0f}",
                                 label_style="dim", note_style="bold " + level_color(wq)))
            rows.append(ability_note(ab))
        line = Text()
        for key in v["your_interfaces"]:
            item = f"{role_icon(key)} {key.replace('_', ' ')}"
            if line.plain and line.cell_len + 3 + Text(item).cell_len + 1 > width:
                rows.append(line)
                line = Text()
            line.append("   " if line.plain else "")
            line.append(item)
        rows.append(line if line.plain else Text("no roles yet", style="dim"))
        return rows

    def _draw_ballots(self, v, legal):
        """Government, recent alerts, then one spaced-out card per open ballot with a countdown."""
        gov = v["government"]
        t = Text()
        t.append(gov["name"], style="bold cyan")
        t.append(f"  changed by {gov['reformed_by']}", style="dim")
        t.append("\nReforms ", style="dim")
        t.append(", ".join(r["name"] for r in gov["available_reforms"]) or "none yet")
        if gov["available_reforms"] and gov["reform_cooldown_days"]:
            t.append(f" (not for {gov['reform_cooldown_days']} days)", style="dim")
        elif gov["available_reforms"] and gov["reform_mode"]:
            t.append(f" ({'by your decree' if gov['reform_mode'] == 'decree' else 'you may call a vote'}: F)", style="green")
        t.append("\n")
        soc = v.get("society", {})
        if soc:
            t.append("Society ", style="dim")
            t.append(f"{soc['score']:.0f}", style=sat_style(soc["score"]).replace("b ", "bold "))
            t.append("  ")
            for q in soc["qualities"].values():
                if q["active"]:
                    t.append(f"{q['icon']}{q['value']:.0f} ", style=sat_style(q["value"]).replace("b ", "bold "))
            t.append(" F9\n", style="dim")

        # Contests come first (yours at the top): they move fast and can cost you your office.
        needs_you = self._draw_contests(t, v)
        alerts = self.hud.alerts[-4 if v.get("contests") else -5:]
        if alerts:
            t.append("─" * 46 + "\n", style="dim")
            for i, a in enumerate(reversed(alerts)):
                newest = i == 0 and self.hud.alert_fresh()
                style = ALERT_STYLE[a.level] + (" reverse" if newest and a.level in ("action", "urgent") else "")
                t.append(f"{a.icon} ", style="")
                t.append(f"{a.date}  ", style="dim")
                t.append(a.text + "\n", style=style)
        t.append("─" * 46 + "\n", style="dim")

        if not v["ballots"] and not v.get("contests"):
            t.append("No open elections, votes or contests.", style="dim")
        for b in v["ballots"]:
            tag, level = ballot_status(b, legal, v["free"])
            needs_you |= level in ("action", "urgent")
            stage = "Nominations" if b.get("nominating") else "Voting"
            t.append("\n")
            t.append(f" {tag} ", style=TAG_STYLE[level])
            t.append(f"  {b['label']}\n", style="bold")
            if b.get("nominating"):
                t.append("   Nominated: ", style="dim")
                t.append((", ".join(b["nominations"]) or "nobody yet") + "\n")
            else:
                t.append("   Choices: ", style="dim")
                t.append(" / ".join(b["choices"]))
                t.append(f"     {b['votes_cast']}/{b['electorate_size']} voted\n", style="dim")
            left, total = b["days_left"] or 0, b.get("phase_days") or 30
            bar_style = "red" if left <= 3 else "yellow" if left <= 10 else "green"
            t.append("   " + bar(left, total, 20), style=bar_style)
            t.append(f"  {stage} close in {left} day{'s' if left != 1 else ''}", style=bar_style)
            t.append(f" ({b['closes']})\n", style="dim")
            if tag == "CANDIDATE":
                by = b.get("nominated_by", {}).get(v["you"])
                how = f"{by} put you forward" if by and by != v["you"] else "you are standing"
                t.append(f"   {how}{'' if b.get('nominating') else '; your vote is for yourself'}. "
                         "Press N to decline.\n", style=ALERT_STYLE[level])
            elif level in ("action", "urgent"):
                key = "N" if tag == "NOMINATE" else "V"
                hint = ("Busy now: you can vote when you are free." if tag == "VOTE WHEN FREE"
                        else f"Press {key} to {'nominate' if key == 'N' else 'vote'}.")
                t.append(f"   {hint}\n", style=ALERT_STYLE[level])
        self.query_one("#ballots_body", Static).update(t)
        self.query_one("#ballots").set_class(needs_you, "attention")

    def _draw_contests(self, t: Text, v) -> bool:
        """Cards for running persuasion campaigns and challenges. Returns True if one needs you."""
        needs_you = False
        mine_first = sorted(v.get("contests", []), key=lambda c: c["your_role"] not in ("challenger", "defender"))
        for c in mine_first:
            role = c["your_role"]
            mine = role in ("challenger", "defender")
            needs_you |= mine
            t.append("\n")
            tag = "PERSUASION" if c["style"] == "persuasion" else "CHALLENGE"
            t.append(f" {tag} ", style=TAG_STYLE["urgent" if mine else "info"])
            if c["style"] == "pending":
                t.append(f"  ⏳ {c['challenger']} challenges {c['defender']} for {c['office']}\n", style="bold")
                choices = ", ".join(a["name"].lower() for a in c["allowed"])
                t.append(f"   {c['defender']} chooses the contest: {choices}\n", style="")
                t.append(f"   {format_life_duration(c['hours_left'])} to choose\n", style="dim")
                if role == "defender":
                    t.append("   Press H to choose your contest!\n", style="bold red")
                continue
            if c["style"] == "persuasion":
                whom = f" (replacing {c['defender']})" if c["defender"] else ""
                t.append(f"  {c['icon']} {c['challenger']} → {c['office']}{whom}\n", style="bold")
                sup, need = c["support"], c["success_at"]
                style = "green" if sup >= need else "yellow"
                t.append(f"   Tribe persuaded {bar(sup, 100, 14)} {sup:.0f}%", style=style)
                t.append(f" (needs {need}%)\n", style="dim")
            else:
                t.append(f"  {c['icon']} {c['challenger']} vs {c['defender']} for {c['office']}: {c['name'].lower()}\n",
                         style="bold")
                if c["style"] == "audience":
                    t.append(f"   Crowd for {c['challenger']} {bar(c['support'], 100, 14)} {c['support']:.0f}%\n",
                             style="green" if c["support"] > 50 else "yellow")
                elif c["style"] == "duel":
                    m = c["meters"].get("momentum", 50)
                    t.append(f"   {c['defender']} {bar(m, 100, 14)} {c['challenger']}  ", style="")
                    t.append(f"{'gaining' if m > 50 else 'losing' if m < 50 else 'even'} for {c['challenger']}\n",
                             style="green" if m > 50 else "yellow")
                else:
                    sc = c["scores"]
                    t.append(f"   {c['challenger']} {sc.get(c['challenger'], 0):g} {c['unit']}  ·  "
                             f"{c['defender']} {sc.get(c['defender'], 0):g} {c['unit']}\n")
            left = c["hours_left"]
            t.append(f"   {bar(left, c['total_hours'], 14)} {format_life_duration(left)} left\n", style="dim")
            if role == "challenger" and c["style"] == "persuasion":
                t.append("   Press P to win people over.\n", style="bold green")
            elif role == "defender" and c["style"] == "persuasion":
                t.append("   Press P to keep people on your side!\n", style="bold red")
            elif role == "audience" and c["style"] == "persuasion":
                t.append(f"   You are {c['meters'].get(v['you'], 0):.0f}% persuaded.\n", style="dim")
            elif mine and c["style"] == "audience":
                t.append("   Press P to speak to the listeners!\n", style="bold red" if role == "defender" else "bold green")
            elif mine:
                t.append("   You are in this contest.\n", style="bold red" if role == "defender" else "bold green")
        return needs_you

    def _draw_tribe(self, v):
        # One line per member, cut to the panel's width with '…' (never wrapped: a wrapped line pushed the
        # rest of the row out of sight); the legend below wraps as usual.
        t = Text(no_wrap=True, overflow="ellipsis")
        focus = contest_focus(v)
        if focus:
            what = "persuaded by" if focus["style"] == "persuasion" else "for"
            t.append(f"Meters: how far each is {what} {focus['challenger']}\n", style="bold")
        for p in v["players"]:
            you = p["name"] == v["you"]
            t.append("●", style=sat_style(p.get("mood", 50)))
            t.append(f"{p['name']:<7}", style="bold green" if you else "bold")
            icons = occupation_icons(v, p)
            t.append(f"{icons or '  '}", style="")
            pos = positions_of(p) or "-"
            t.append(f" {pos[:10]:<10}", style="cyan" if pos != "-" else "dim")
            sick = [CHARACTER.needs[k].icon for k, n in p["sheet"]["needs"].items() if n["critical"]]
            if sick:
                t.append("".join(sick), style="red")
            body = life_icons(p)
            if body:
                t.append(body, style="")
            child = (p.get("life") or {}).get("child") or not (p.get("life") or {}).get("of_age", True)
            t.append("✗" if not p["can_vote"] and not child else " ", style="red")
            meter = focus["meters"].get(p["name"]) if focus else None
            if meter is not None:
                t.append(f" {bar(meter, 100, 6)} {meter:3.0f}%\n", style="green" if meter >= 50 else "yellow")
            elif focus and p["name"] in (focus["challenger"], focus["defender"]):
                t.append(f" {'campaigning' if p['name'] == focus['challenger'] else 'defending'}\n", style="bold")
            elif p["doing"] and not p["doing"].startswith("resting"):
                t.append(f" {p['doing']}\n", style="yellow")
            elif not p["doing"] and p.get("waiting_for"):
                t.append(f" needs {p['waiting_for'][2:]}\n", style="yellow")
            elif not p["doing"]:
                t.append(" free\n", style="green")
            else:
                t.append(f" {p.get('last_deed') or 'at home'}\n", style="dim")
        for b in v.get("life", {}).get("bodies", []):  # the dead, until someone lays them to rest
            t.append(f"{b['icon']}", style="")
            t.append(f"{b['name']:<7}", style="bold red")
            t.append(f" died at {b['age']} · ", style="red")
            t.append(f"{b['handler']} sees to it\n" if b["handler"] else f"unburied {b['days']}d (W)\n",
                     style="yellow" if b["handler"] else "bold red")
        legend = Text()
        legend.append("\nbusy now", style="yellow")
        legend.append(" · last deed, at home\n● mood (green content, red unhappy) · ✗ cannot vote\nred icon = in need · "
                      "🤒 ill · 🤰 with child · 🧒 child · 💀 dead, not yet laid to rest\nF2 details · F9 society",
                      style="dim")
        from rich.console import Group
        self.query_one("#tribe_body", Static).update(Group(t, legend))

    def _draw_places(self, v):
        """Places Scouts found (and gardeners' plots): what is left at each, oldest first (trips go there
        first), then the last few used up or lost, greyed."""
        camp = v.get("camp", {})
        t = Text(no_wrap=True, overflow="ellipsis")
        for x in camp.get("sites", []):
            t.append(f"{x['icon']} ", style="")
            t.append(f"{x['short']:<13}", style="bold")
            t.append(f" {bar(x['loads'], x['total'], 6)} ", style="green" if x["loads"] > x["total"] / 3 else "yellow")
            t.append(f"{x['loads']:g} trips\n", style="")
            t.append(f"   found by {x['by']} · gone in {format_life_duration(x['hours_left'] * HOURS_PER_LIFE_HOUR)}\n",
                     style="dim")
        for x in camp.get("spent_sites", []):
            t.append(f"{x['icon']} {x['short']:<13} {x['how']} ({x['by']})\n", style="dim")
        if not camp.get("sites") and not camp.get("spent_sites"):
            t.append("None yet: a Scout can look for berry grounds,\ngame trails, deadwood... (W)\n", style="dim")
        self.query_one("#places_body", Static).update(t)

    def _draw_innovations(self, v):
        """Icons only: what's being researched, what's queued, the next age, and everything discovered."""
        rows = {r.name: r for r in innovation_catalog(v)}
        names = list(rows)
        self.pool_names = names

        def icon(name: str, style: str = "") -> str:
            r = rows[name]
            mark = f"[{style}]{r.icon}[/]" if style else r.icon
            return f"[@click=screen.innovation({names.index(name)})]{mark}[/]"

        lines = []
        r = v["researching"]
        if r:
            row = rows[r["innovation"]]
            line = (f"[dim]Researching[/] {icon(row.name)} [b]{escape(row.name)}[/] "
                    f"{bar(r['points'], r['cost'], 10)} {r['points']}/{r['cost']}")
            if len(v["research_queue"]) > 1:
                line += "   [dim]then[/] " + " ".join(icon(n) for n in v["research_queue"][1:] if n in rows)
            lines.append(line)
        else:
            lines.append("[dim]Researching[/] [yellow]nothing - press R to queue an innovation[/]")
        lines.append(f"[dim]Points[/] {v['points']} [dim](+{v['points_per_year']}/yr)[/]   [dim]Next age[/] "
                     + (f"[b]{escape(v['next_age']['name'])}[/] needs " + "  ".join(
                         f"{icon(n) if n in rows else ''}{'[green]✓[/]' if done else '[dim]·[/]'}"
                         for n, done in v["next_age"]["needs"].items()) if v["next_age"] else "[dim]latest age reached[/]"))
        found = [n for n in rows if rows[n].status == "discovered"]
        lines.append(f"[dim]Discovered {len(found)}[/]  " + " ".join(icon(n) for n in found))
        available = [n for n in rows if rows[n].status == "available"]
        if available:
            lines.append(f"[dim]Available {len(available)}[/]   " + " ".join(icon(n) for n in available))
        self.query_one("#innovations", Static).update("\n".join(lines))

    def set_status(self, text: Optional[str] = None, style: str = ""):
        if text is None:
            text, style = getattr(self, "_status", ("", ""))
        self._status = (text, style)
        v = self.hud.last_view
        who = f"{v['you']} ({', '.join(v['your_positions']) or 'Tribe member'})" if v else ""
        t = Text(f" {who} ▸ ", style="bold")
        t.append(text, style=style)
        self.query_one("#status", Static).update(t)

    def chronicle(self) -> RichLog:
        return self.query_one("#chronicle", RichLog)

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def action_act(self, action_type: str):
        hud = self.hud
        view, legal = hud.last_view, hud.last_legal
        if view is None:
            return
        if action_type == "inventory":
            self.app.push_screen(InventoryScreen(view["you"]))
            return
        if hud.controller.auto:
            self.set_status("You are on AUTO: the game plays you like any other member. Press M to take over.",
                            "yellow")
            return
        group = next(g for g in action_groups(view, legal) if g.kind.type == action_type)
        if not group.available:
            if not view["free"]:
                self.set_status(f"You are busy ({view['doing']}) for {format_life_duration(view['busy_hours_left'])} more"
                                + (" (X to stop)." if view.get("can_stop") else "."), "yellow")
            elif group.kind.type in ("persuade", "challenge") and view.get("contest_cooldown_hours"):
                self.set_status(f"You lost your last contest: no new campaign or challenge for "
                                f"{format_life_duration(view['contest_cooldown_hours'])}.", "yellow")
            elif group.kind.type in ("persuade", "challenge") and protected_note(view):
                self.set_status(protected_note(view).strip(), "yellow")
            else:
                self.set_status(f"Nothing to {group.kind.label.lower()} right now.", "yellow")
            return
        self.choose(group, view)

    @work(exclusive=True)
    async def choose(self, group, view):
        if group.kind.type == "stop":
            self.hud.controller.submit(Decision(group.actions[0]))
            self.set_status("Getting up…", "dim")
            return
        item = await self._pick(build_menu(group, view))
        if item is None:
            self.set_status("Cancelled.", "dim")
            return
        action = item.action
        if item.ranked:
            ranking = await self.app.push_screen_wait(RankScreen(item.label, item.ranked, item.profiles))
            if not ranking:
                self.set_status("Cancelled.", "dim")
                return
            action = next(a for a in group.actions if a.params["ballot"] == action.params["ballot"]
                          and a.params["choice"] == ranking[0]).with_params(ranking=ranking)
        if item.text_prompt:
            text = await self.app.push_screen_wait(TextScreen(item.text_prompt))
            if text is None:
                self.set_status("Cancelled.", "dim")
                return
            action = action.with_params(text=text)
        self.hud.controller.submit(Decision(action))
        self.set_status(f"{group.kind.label}: {item.label}…", "dim")

    async def _pick(self, menu: Menu) -> Optional[MenuItem]:
        while True:
            item = await self.app.push_screen_wait(PickerScreen(menu))
            if item is None:
                return None
            if item.submenu is None:
                return item
            chosen = await self._pick(item.submenu)
            if chosen is not None:
                return chosen

    def action_info(self, which: str, focus: Optional[str] = None):
        hud = self.hud
        if hud.last_view is None:
            return
        v = hud.last_view
        screens = {"help": lambda: HelpScreen(v), "tribe": lambda: TribeScreen(v),
                   "government": lambda: GovernmentScreen(v),
                   "innovations": lambda: InnovationScreen(v, hud.last_legal, hud.controller, focus),
                   "log": lambda: LogScreen(v, hud.history, hud.controller.detail),
                   "character": lambda: CharacterScreen(v),
                   "society": lambda: SocietyScreen(v),
                   "crafts": lambda: CraftScreen(v)}
        self.app.push_screen(screens[which]())

    def action_innovation(self, index: int):
        names = getattr(self, "pool_names", [])
        if 0 <= index < len(names):
            self.action_info("innovations", names[index])

    def action_speed(self):
        self.hud.pacer.next_speed()
        self.hud.redraw()

    def action_toggle_auto(self):
        """Manual (you choose everything) or auto (you are played exactly like an NPC). Switch any time."""
        c = self.hud.controller
        c.set_auto(not c.auto)
        if c.auto:
            self.set_status("AUTO: you are played like any other member of the tribe. Space still pauses; "
                            "M takes you back to manual.", "magenta")
        else:
            self.set_status("MANUAL: you choose again. Whatever you were doing carries on until it is done.", "green")
        self.hud.redraw()

    def action_pause(self):
        self.hud.pacer.toggle_pause()
        self.set_status("Paused. You can still act." if self.hud.pacer.paused else "Resumed.", "yellow")
        self.hud.redraw()

    def action_detail(self):
        c = self.hud.controller
        levels = list(DETAIL_LEVELS)
        c.detail = levels[(levels.index(c.detail) + 1) % len(levels)] if c.detail in levels else "full"
        self.hud.rewrite_chronicle()
        self.set_status(f"Chronicle shows {DETAIL_LEVELS[c.detail]}.", "dim")


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
class GovGenHUD(App):
    TITLE = "GovGen"
    CSS = """
    Screen { layout: vertical; }
    #top { height: 1; background: $primary-darken-2; color: $text; }
    #main { height: 1fr; }
    #chronicle { width: 2fr; min-width: 30; border: round $accent; scrollbar-size-vertical: 1; }
    #center { width: 3fr; }
    #you { height: auto; border: round $accent; padding: 0 0; }
    #you_head { height: auto; }
    #you_id { width: 3fr; height: auto; padding: 0 1; link-style: none; link-style-hover: reverse; }
    #you_roles { width: 2fr; }
    #you_boxes { height: auto; grid-size: 3; grid-rows: auto; grid-gutter: 0 0; }
    .box { height: auto; border: round $primary-lighten-2; border-title-color: $text; padding: 0 1;
           text-wrap: nowrap; text-overflow: ellipsis; }
    #you_actions { link-style: none; link-style-hover: reverse; }
    #ballots { height: 1fr; border: round $accent; padding: 0 1; }
    #ballots.attention { border: heavy $success; }
    #innovations { height: auto; max-height: 12; border: round $accent; padding: 0 1;
                   link-style: none; link-style-hover: reverse; }
    #right { width: 42; }
    #tribe { height: 1fr; border: round $accent; padding: 0 1; }
    #places { height: auto; max-height: 14; border: round $accent; padding: 0 1; }
    #fkeys { height: 1; padding: 0 1; color: $text-muted; link-style: none; link-style-hover: reverse; }
    #status { height: 1; background: $primary-darken-3; }
    PickerScreen, RankScreen, TextScreen { align: center middle; }
    #dialog { width: 70; max-width: 90%; height: auto; max-height: 80%; border: thick $accent;
              background: $surface; padding: 0 1; }
    #dialog OptionList { height: auto; max-height: 24; border: none; }
    #dialog.people { width: 112; max-width: 96%; max-height: 90%; }
    #dialog.people OptionList { max-height: 40; }
    #rank_scroll { height: auto; max-height: 40; }
    #tribe_scroll { height: 1fr; }
    #tribe_grid { height: auto; grid-size: 2; grid-rows: auto; grid-gutter: 0 1; }
    .card { height: auto; border: round $accent; padding: 0 1; }
    .card.you { border: round $success; }
    .card.selected { border: heavy $warning; }
    InventoryScreen { align: center middle; }
    #inv { width: 124; max-width: 98%; height: auto; max-height: 96%; border: thick $accent; background: $surface;
           padding: 0 1; }
    #inv_title { height: 1; }
    #inv_main { height: auto; }
    #inv_grid { height: auto; grid-gutter: 0 0; grid-rows: 4; }
    .slot { height: 4; border: round $primary-darken-1; padding: 0 1; }
    .slot.empty { border: round $primary-darken-3; }
    .slot.selected { border: heavy $warning; }
    .slot.holding { border: double $success; background: $success 15%; }
    #inv_side { width: 1fr; height: auto; }
    .ibox { height: auto; border: round $primary-lighten-2; border-title-color: $text; padding: 0 1; }
    .ibox.focused { border: heavy $warning; }
    #inv_keys { height: auto; margin-top: 1; }
    #inv_status { height: 1; }
    .card_head { height: auto; }
    .card_boxes { height: auto; grid-size: 4; grid-rows: auto; }
    .cbox { height: auto; border: round $primary-lighten-2; border-title-color: $text; padding: 0 1;
            text-wrap: nowrap; text-overflow: ellipsis; }
    InfoScreen { align: center middle; }
    #info { width: 94%; height: 92%; border: thick $accent; background: $surface; padding: 0 1; }
    #innov_table { height: 1fr; }
    #innov_detail { height: auto; min-height: 4; border-top: solid $accent; }
    #craft_table { height: 1fr; }
    #craft_detail_box { height: auto; max-height: 14; min-height: 6; border-top: solid $accent; }
    """
    BINDINGS = [Binding("ctrl+q", "save_quit", "Save and quit", priority=True)]

    def __init__(self, controller: HUDController, pacer, game_thread: Optional[threading.Thread] = None):
        super().__init__()
        self.controller, self.pacer, self.game_thread = controller, pacer, game_thread
        self.version = -1
        self.last_view: Optional[Dict[str, Any]] = None
        self.last_legal: list = []
        self.history: List[Message] = []
        self.quitting = False
        self.watcher = BallotWatcher()
        self.alerts: list = []
        self._alert_time = 0.0

    def on_mount(self):
        self.push_screen(CommandCenter())
        self.set_interval(0.1, self.poll)

    @property
    def main(self) -> CommandCenter:
        return next(s for s in self.screen_stack if isinstance(s, CommandCenter))

    def poll(self):
        if not any(isinstance(s, CommandCenter) for s in self.screen_stack):
            return  # starting up or shutting down
        main = self.main
        messages = self.controller.drain_messages()
        if messages:
            self.history.extend(messages)
            del self.history[:-5000]
            log = main.chronicle()
            for m in messages:
                line = message_text(m, self.controller.detail)
                if line is not None:
                    log.write(line)
        for decision, ok, why in self.controller.drain_results():
            if ok:
                text, style = f"Done: {decision.action.label or decision.action.type.replace('_', ' ')}.", "green"
            else:
                if not why or "cannot do that right now" in why:
                    why = "it's no longer possible (a ballot may have closed, or things changed while you chose)."
                text, style = f"Couldn't do that: {why}", "red"
            main.set_status(text, style)
            if hasattr(self.screen, "show_result"):
                self.screen.show_result(text, style)  # e.g. the inventory window
        if messages and hasattr(self.screen, "hear"):
            self.screen.hear(messages)
        you = self.last_view["you"] if self.last_view else None
        for m in messages:  # deaths, births, the dead laid to rest; and you falling ill
            if m.category == "find":  # what a Scout found, and a found place used up
                self.notify(m.text, title="Scouting", severity="information", timeout=6)
            elif m.category == "vital" or (m.category == "illness" and you and m.text.find(f" {you} ") >= 0):
                self.notify(m.text, title="Life and death" if m.category == "vital" else "You are ill",
                            severity="error" if "died" in m.text or "fallen ill" in m.text else "information",
                            timeout=8)
        version, view, legal = self.controller.snapshot()
        if version != self.version and view is not None:
            first = self.last_view is None
            self.version, self.last_view, self.last_legal = version, view, legal
            self._watch_ballots(view, legal)
            main.draw(view, legal)
            if hasattr(self.screen, "refresh_view"):
                self.screen.refresh_view(view)  # e.g. the Tribe screen's meters stay live
            if first:
                main.set_status("Welcome. The clock is running. F1 for help; letters act, F-keys look.", "dim")
        if self.game_thread is not None and not self.game_thread.is_alive():
            self.exit()

    def _watch_ballots(self, view, legal):
        recent = [m.text for m in self.history[-80:] if m.important]
        new = self.watcher.update(view, legal, recent)
        if not new:
            return
        self.alerts.extend(new)
        del self.alerts[:-30]
        self._alert_time = time.monotonic()
        for a in new:
            if a.level in ("action", "urgent"):
                self.notify(f"{a.icon} {a.text}", title="Government", severity="warning" if a.level == "action" else "error",
                            timeout=6)
                if a.level == "urgent":
                    self.bell()

    def alert_fresh(self) -> bool:
        """True for a few seconds after a new alert, so it stands out."""
        return time.monotonic() - self._alert_time < 4

    def redraw(self):
        if self.last_view is not None:
            self.main.draw(self.last_view, self.last_legal)

    def rewrite_chronicle(self):
        log = self.main.chronicle()
        log.clear()
        for m in self.history[-600:]:
            line = message_text(m, self.controller.detail)
            if line is not None:
                log.write(line)

    def action_save_quit(self):
        if not self.quitting:
            self.quitting = True
            self.controller.quit()
            self.main.set_status("Saving…", "yellow")
        if self.game_thread is None:
            self.exit()

"""The inventory window: a grid of slots, the item under the cursor, the camp store and trade offers.

Your own inventory (I from the main screen):
    arrows      move the cursor            Enter/Space  pick up a stack to move, then place it
    s           pick up half a stack        o            sort and merge stacks
    u           use (eat, drink)            d            put in the camp store
    g           give to someone             t            offer someone a trade (needs Barter System)
    Tab         switch to the camp store (Enter takes)
    y / n       accept / decline an offer made to you      c  withdraw your offer

Someone else's (F2, choose a member, Enter): browse their slots; t asks for the item under the cursor (as a gift; once
the Barter System is known, in a trade); g gives them something of yours.

Every change goes to the game as a quick action (core/possessions.py) through the HUDController; the
window redraws from the next view, so it always shows what the game holds.
"""
from typing import Any, Dict, List, Optional

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from controllers.base import Decision
from core.actions import Action
from ui.model import Menu, MenuItem, count_choices, inventory_of, stack_worth
from world.items import ITEMS, describe


class SlotCell(Static):
    """One inventory slot."""

    def __init__(self, index: int):
        super().__init__(classes="slot")
        self.index = index

    def show(self, stack: Optional[Dict[str, Any]], selected: bool, holding: bool):
        self.set_class(selected, "selected")
        self.set_class(holding, "holding")
        self.set_class(stack is None, "empty")
        t = Text(no_wrap=True, overflow="ellipsis")
        if stack is None:
            t.append("\n  ·", style="dim")
        else:
            item = ITEMS[stack["item"]]
            t.append(f"{item.icon} ", style="")
            t.append(item.name, style="bold")
            t.append(f"\n  ×{stack['count']}", style="bold yellow" if stack["count"] > 1 else "dim")
            if stack["count"] >= item.max_stack:
                t.append(" full", style="dim")
        self.update(t)

    def on_click(self):
        self.screen.click_slot(self.index)  # type: ignore[attr-defined]


class InventoryScreen(ModalScreen):
    BINDINGS = [Binding("escape", "back", "Close")]

    def __init__(self, owner: str, close_key: str = "i"):
        super().__init__()
        self.owner = owner
        self.close_key = close_key
        self.cursor = 0
        self.ground_cursor = 0
        self.focus_ground = False
        self.holding: Optional[Dict[str, Any]] = None  # {"slot", "count" (None = whole stack)}
        self.view: Optional[Dict[str, Any]] = None
        self.busy_choosing = False

    # ------------------------------------------------------------------ #
    @property
    def hud(self):
        return self.app

    @property
    def own(self) -> bool:
        return self.view is not None and self.owner == self.view["you"]

    def inv(self) -> Dict[str, Any]:
        return inventory_of(self.view, self.owner) or {"slots": [], "size": 0, "columns": 4, "free": 0}

    def compose(self) -> ComposeResult:
        self.view = self.hud.last_view
        inv = self.inv()
        with Vertical(id="inv"):
            yield Static(id="inv_title")
            with Horizontal(id="inv_main"):
                grid = Grid(*[SlotCell(i) for i in range(inv["size"])], id="inv_grid")
                grid.styles.grid_size_columns = inv["columns"]
                grid.styles.width = inv["columns"] * 18
                yield grid
                with Vertical(id="inv_side"):
                    yield Static(id="inv_detail", classes="ibox")
                    yield Static(id="inv_ground", classes="ibox")
                    yield Static(id="inv_offers", classes="ibox")
            yield Static(id="inv_keys")
            yield Label(id="inv_status")

    def on_mount(self):
        self.query_one("#inv_detail").border_title = "Item"
        from ui.model import term
        self.query_one("#inv_ground").border_title = term("store_name").capitalize()
        self.query_one("#inv_offers").border_title = "Trade offers"
        if not self.own:
            self.query_one("#inv_ground").display = False
        self._draw()

    def refresh_view(self, view: Dict[str, Any]):
        self.view = view
        self._draw()

    def hear(self, messages):
        """New chronicle lines: say how your trades went (answered at once by NPCs, or ran out)."""
        you = self.view["you"] if self.view else ""
        for m in messages:
            if f"{you}'s trade" in m.text or f"between {you} and" in m.text:
                self.show_result(m.text + ".", "bold green" if " accepts " in m.text else "yellow")

    def show_result(self, text: str, style: str = ""):
        self.query_one("#inv_status", Label).update(Text(text, style=style))

    # ------------------------------------------------------------------ #
    # Drawing
    # ------------------------------------------------------------------ #
    def _draw(self):
        v = self.view
        if v is None:
            return
        inv = self.inv()
        slots = inv["slots"]
        self.cursor = min(self.cursor, max(0, len(slots) - 1))
        used = inv["size"] - inv["free"]
        title = Text()
        title.append("Your inventory" if self.own else f"{self.owner}'s inventory", style="bold cyan")
        title.append(f"   {used}/{inv['size']} slots used", style="dim")
        hands = v.get("possessions", {}).get("hands")
        if self.own and hands:
            title.append(f"   you can't handle items while {hands}", style="bold red")
        if self.holding is not None:
            s = slots[self.holding["slot"]] if self.holding["slot"] < len(slots) else None
            if s:
                n = self.holding["count"] or s["count"]
                title.append(f"   moving {describe([{'item': s['item'], 'count': n}])}: Enter to place, Esc to cancel",
                             style="bold yellow")
        self.query_one("#inv_title", Static).update(title)
        for cell in self.query(SlotCell):
            stack = slots[cell.index] if cell.index < len(slots) else None
            cell.show(stack, cell.index == self.cursor and not self.focus_ground,
                      self.holding is not None and self.holding["slot"] == cell.index)
        self._draw_detail(slots)
        if self.own:
            self._draw_ground(v)
        self._draw_offers(v)
        self._draw_keys()

    def _draw_detail(self, slots):
        t = Text()
        s = slots[self.cursor] if self.cursor < len(slots) and not self.focus_ground else None
        if self.focus_ground:
            ground = self.view.get("possessions", {}).get("ground", [])
            s = ground[self.ground_cursor] if self.ground_cursor < len(ground) else None
        if s is None:
            t.append("An empty slot." if not self.focus_ground else "Nothing here.", style="dim")
        else:
            item = ITEMS[s["item"]]
            t.append(f"{item.icon} {item.name}", style="bold")
            t.append(f"   ×{s['count']}", style="bold yellow")
            t.append(f"   (stacks to {item.max_stack})\n", style="dim")
            t.append(item.description + "\n", style="italic")
            t.append("Trade value ", style="dim")
            t.append(f"{item.value:g}", style="bold")
            t.append(" each", style="dim")
            if item.uses:
                left = s.get("uses", item.uses)
                t.append("\nWear ", style="dim")
                t.append(f"{left} of {item.uses} uses left", style="bold " + ("red" if left <= item.uses // 4 else "green"))
            if item.use:
                effects = ", ".join(f"{need} +{amount:g}" for need, amount in item.use.items())
                t.append(f"\n{item.use_label}: {effects}", style="green")
        self.query_one("#inv_detail", Static).update(t)

    def _draw_ground(self, v):
        ground = v.get("possessions", {}).get("ground", [])
        self.ground_cursor = min(self.ground_cursor, max(0, len(ground) - 1))
        box = self.query_one("#inv_ground", Static)
        box.set_class(self.focus_ground, "focused")
        t = Text()
        if not ground:
            t.append("The camp store is empty.", style="dim")
        for i, s in enumerate(ground):
            item = ITEMS[s["item"]]
            here = self.focus_ground and i == self.ground_cursor
            t.append("▶ " if here else "  ", style="bold green")
            t.append(f"{item.icon} {item.name}", style="bold reverse" if here else "bold")
            t.append(f"  ×{s['count']}\n", style="yellow")
        t.append("Tab: " + ("back to your pack" if self.focus_ground else "take things from the store"), style="dim")
        box.update(t)

    def _draw_offers(self, v):
        offers = v.get("possessions", {}).get("offers", [])
        if not self.own:
            offers = [o for o in offers if self.owner in (o["from"], o["to"])]
        t = Text()
        if not offers:
            t.append("No open offers.", style="dim")
        for o in offers:
            mine = o["from"] == v["you"]
            give = describe(o["give"]) or "nothing"
            want = describe(o["want"]) or "nothing"
            if mine:
                t.append(f"You → {o['to']}: ", style="bold")
                t.append(f"{give} for {want}", style="")
                t.append("  waiting for an answer (c withdraws)\n", style="dim")
            else:
                t.append(f"{o['from']} → you: ", style="bold green")
                t.append(f"{give} for your {want}")
                t.append("  y accept · n decline\n", style="bold green")
        self.query_one("#inv_offers", Static).update(t)

    def _draw_keys(self):
        t = Text()

        def key(k, label):
            t.append(f" {k} ", style="bold black on green")
            t.append(f" {label}  ")
        if self.own and self.focus_ground:
            key("↑↓", "choose"); key("Enter", "take all"); key("1", "take one"); key("Tab", "back to pack")
        elif self.own:
            key("←↑↓→", "move"); key("Enter", "move stack" if self.holding is None else "place")
            key("s", "split"); key("u", "use"); key("d", "to store"); key("g", "give")
            if self.view.get("possessions", {}).get("barter"):
                key("t", "trade")
            key("o", "sort"); key("Tab", "store")
        else:
            key("←↑↓→", "look")
            key("t", "ask for this or trade" if self.view.get("possessions", {}).get("barter") else "ask for this")
            key("g", "give them something")
        key("Esc", "close")
        self.query_one("#inv_keys", Static).update(t)

    # ------------------------------------------------------------------ #
    # Input
    # ------------------------------------------------------------------ #
    def submit(self, action: Action, text: str):
        self.hud.controller.submit(Decision(action))
        self.show_result(text + "…", "dim")

    def action_back(self):
        if self.holding is not None:
            self.holding = None
            self._draw()
            return
        self.dismiss(None)

    def click_slot(self, index: int):
        self.focus_ground = False
        self.cursor = index
        if self.own:
            self._enter()
        self._draw()

    def on_key(self, event) -> None:
        if self.view is None or self.app.screen is not self:
            return
        k = event.key
        handled = True
        if k == self.close_key and self.holding is None:
            self.dismiss(None)
        elif k == "tab" and self.own:
            self.focus_ground = not self.focus_ground
            self.holding = None
        elif self.focus_ground and self.own:
            handled = self._ground_key(k)
        elif k in ("left", "right", "up", "down"):
            cols, size = self.inv()["columns"], self.inv()["size"]
            step = {"left": -1, "right": 1, "up": -cols, "down": cols}[k]
            if 0 <= self.cursor + step < size:
                self.cursor += step
        elif not self.own:
            handled = self._other_key(k)
        else:
            handled = self._own_key(k)
        if handled:
            event.stop()
            event.prevent_default()
            self._draw()

    def _stack(self) -> Optional[Dict[str, Any]]:
        slots = self.inv()["slots"]
        return slots[self.cursor] if self.cursor < len(slots) else None

    def _enter(self):
        if self.holding is None:
            if self._stack():
                self.holding = {"slot": self.cursor, "count": None}
            return
        src, count = self.holding["slot"], self.holding["count"]
        self.holding = None
        if src != self.cursor:
            params = {"slot": src, "to": self.cursor}
            if count is not None:
                params["count"] = count
            self.submit(Action("move_item", params), "Moving")

    def _own_key(self, k: str) -> bool:
        s = self._stack()
        if k in ("enter", "space"):
            self._enter()
        elif k == "s":
            if s and s["count"] > 1:
                self.holding = {"slot": self.cursor, "count": s["count"] // 2}
        elif k == "o":
            self.submit(Action("sort_items"), "Sorting")
        elif k == "u" and s:
            if ITEMS[s["item"]].use:
                self.submit(Action("use_item", {"slot": self.cursor}), f"{ITEMS[s['item']].use_label}ing")
            else:
                self.show_result(f"{ITEMS[s['item']].name} can't be used like that.", "yellow")
        elif k == "d" and s:
            self.drop(self.cursor, s)
        elif k == "g" and s:
            self.give_own(self.cursor, s)
        elif k == "t" and self.view.get("possessions", {}).get("barter"):
            self.trade_from_own(self.cursor if s else None)
        elif k in ("y", "n", "c"):
            self.answer(k)
        else:
            return False
        return True

    def _ground_key(self, k: str) -> bool:
        ground = self.view.get("possessions", {}).get("ground", [])
        if k == "up":
            self.ground_cursor = max(0, self.ground_cursor - 1)
        elif k == "down":
            self.ground_cursor = min(max(0, len(ground) - 1), self.ground_cursor + 1)
        elif k in ("enter", "space", "p", "1") and ground:
            s = ground[self.ground_cursor]
            n = 1 if k == "1" else s["count"]
            self.submit(Action("pick_up", {"item": s["item"], "count": n}),
                        f"Picking up {describe([{'item': s['item'], 'count': n}])}")
        elif k in ("y", "n", "c"):
            self.answer(k)
        else:
            return False
        return True

    def _other_key(self, k: str) -> bool:
        if k == "t":
            self.ask_trade(self._stack())
        elif k == "g":
            self.give_to(self.owner)
        else:
            return False
        return True

    # ------------------------------------------------------------------ #
    # Pickers (count, person, item)
    # ------------------------------------------------------------------ #
    async def _pick(self, title: str, items: List[MenuItem], note: str = "") -> Optional[MenuItem]:
        from ui.hud import PickerScreen
        if not items:
            return None
        return await self.app.push_screen_wait(PickerScreen(Menu(title, items, note)))

    async def _count(self, item: str, most: int, verb: str) -> Optional[int]:
        if most <= 1:
            return most
        name = ITEMS[item].name
        chosen = await self._pick(f"{verb} how many {name}?",
                                  [MenuItem(f"{n}" + (" (all)" if n == most else ""), action=Action("n", {"n": n}))
                                   for n in count_choices(most)])
        return None if chosen is None else chosen.action.params["n"]

    async def _person(self, title: str) -> Optional[str]:
        names = [p for p in self.view["players"] if p["name"] != self.view["you"]]
        items = []
        for p in names:
            inv = p.get("inventory") or {}
            note = f"{inv.get('free', 0)} free slots"
            if p.get("doing"):
                note += f" · {p['doing']}"
            items.append(MenuItem(p["name"], note, action=Action("p", {"name": p["name"]})))
        chosen = await self._pick(title, items)
        return None if chosen is None else chosen.action.params["name"]

    def _own_stacks(self) -> List[Dict[str, Any]]:
        """Your items, merged by kind (for trade pickers)."""
        totals: Dict[str, int] = {}
        for s in (inventory_of(self.view, self.view["you"]) or {}).get("slots", []):
            if s:
                totals[s["item"]] = totals.get(s["item"], 0) + s["count"]
        return [{"item": k, "count": totals[k]} for k in ITEMS if k in totals]

    def _theirs(self, name: str) -> List[Dict[str, Any]]:
        totals: Dict[str, int] = {}
        for s in (inventory_of(self.view, name) or {}).get("slots", []):
            if s:
                totals[s["item"]] = totals.get(s["item"], 0) + s["count"]
        return [{"item": k, "count": totals[k]} for k in ITEMS if k in totals]

    async def _choose_stack(self, title: str, stacks: List[Dict[str, Any]], verb: str,
                            allow_nothing: str = "") -> Optional[List[Dict[str, Any]]]:
        """Pick one kind of item and an amount from `stacks`. [] means 'nothing' (if allowed)."""
        items = [MenuItem(f"{ITEMS[s['item']].icon} {ITEMS[s['item']].name}  ×{s['count']}",
                          f"worth {ITEMS[s['item']].value:g} each", action=Action("s", dict(s))) for s in stacks]
        if allow_nothing:
            items.append(MenuItem(allow_nothing, action=Action("s", {})))
        chosen = await self._pick(title, items)
        if chosen is None:
            return None
        if not chosen.action.params:
            return []
        s = chosen.action.params
        n = await self._count(s["item"], s["count"], verb)
        return None if not n else [{"item": s["item"], "count": n}]

    # ------------------------------------------------------------------ #
    # Things you do
    # ------------------------------------------------------------------ #
    @work(exclusive=True)
    async def drop(self, slot: int, s: Dict[str, Any]):
        n = await self._count(s["item"], s["count"], "Drop")
        if n:
            self.submit(Action("drop_item", {"slot": slot, "count": n}),
                        f"Dropping {describe([{'item': s['item'], 'count': n}])}")

    @work(exclusive=True)
    async def give_own(self, slot: int, s: Dict[str, Any]):
        to = await self._person(f"Give {ITEMS[s['item']].name} to whom?")
        if not to:
            return
        n = await self._count(s["item"], s["count"], "Give")
        if n:
            self.submit(Action("give_item", {"slot": slot, "to": to, "count": n}),
                        f"Giving {describe([{'item': s['item'], 'count': n}])} to {to}")

    @work(exclusive=True)
    async def give_to(self, to: str):
        mine = self._own_stacks()
        if not mine:
            self.show_result("You have nothing to give.", "yellow")
            return
        chosen = await self._choose_stack(f"Give {to} what?", mine, "Give")
        if not chosen:
            return
        s = chosen[0]
        slots = (inventory_of(self.view, self.view["you"]) or {}).get("slots", [])
        # Give from the fullest slots of that item first, one quick action per slot.
        left = s["count"]
        for i, st in sorted(enumerate(slots), key=lambda x: -(x[1]["count"] if x[1] else 0)):
            if left and st and st["item"] == s["item"]:
                n = min(left, st["count"])
                self.hud.controller.submit(Decision(Action("give_item", {"slot": i, "to": to, "count": n})))
                left -= n
        self.show_result(f"Giving {describe(chosen)} to {to}…", "dim")

    @work(exclusive=True)
    async def trade_from_own(self, slot: Optional[int]):
        to = await self._person("Trade with whom?")
        if to:
            await self._trade(to, None)

    @work(exclusive=True)
    async def ask_trade(self, s: Optional[Dict[str, Any]]):
        await self._trade(self.owner, s)

    async def _trade(self, to: str, wanted: Optional[Dict[str, Any]]):
        """Build an offer: what you want of theirs, then what you give for it."""
        if wanted is None:
            theirs = self._theirs(to)
            want = await self._choose_stack(f"What do you want from {to}?", theirs, "Ask for",
                                            allow_nothing="Nothing — just give them something")
        else:
            total = next((x["count"] for x in self._theirs(to) if x["item"] == wanted["item"]), wanted["count"])
            n = await self._count(wanted["item"], total, "Ask for")
            want = None if not n else [{"item": wanted["item"], "count": n}]
        if want is None:
            return
        if not self.view.get("possessions", {}).get("barter"):  # no Barter System yet: only ask as a gift
            if want:
                self.submit(Action("offer_trade", {"to": to, "give": [], "want": want}),
                            f"Asking {to} for {describe(want)}")
            return
        give = await self._choose_stack(
            f"What do you give {to}" + (f" for {describe(want)}" if want else "") + "?", self._own_stacks(), "Give",
            allow_nothing="Nothing — ask for it as a gift" if want else "")
        if give is None or not (give or want):
            return
        note = f"(worth {stack_worth(give):g} for {stack_worth(want):g}; they value food and water more when they need it)"
        self.submit(Action("offer_trade", {"to": to, "give": give, "want": want}),
                    f"Offering {to} {describe(give) or 'nothing'} for {describe(want) or 'nothing'} {note}")

    def answer(self, k: str):
        offers = self.view.get("possessions", {}).get("offers", [])
        you = self.view["you"]
        if k == "c":
            mine = [o for o in offers if o["from"] == you]
            if mine:
                self.submit(Action("cancel_trade", {"offer": mine[0]["id"]}), f"Withdrawing the offer to {mine[0]['to']}")
            return
        theirs = [o for o in offers if o["to"] == you]
        if theirs:
            o = theirs[0]
            self.submit(Action("answer_trade", {"offer": o["id"], "accept": k == "y"}),
                        ("Accepting" if k == "y" else "Declining") + f" {o['from']}'s offer")

"""What people carry, the tribe's shared camp store, and trades between people.

The camp store (`ground`) is where work delivers what it yields, and where people eat and drink from
when their own pack has nothing; anyone may put things in or take them out.

Handling items is a *quick action*: it takes no game time and doesn't need the player's moment, so a
real-time player can sort their pack, drop something or offer a trade while busy (resting, warming up,
campaigning...). Anything that needs your hands (dropping, picking up, giving, using, trading) is not
possible while asleep, collapsed or locked in a ritual fight; moving items between your own slots
always is.

Quick action types and their params (all plain data, like core/actions.py):
    move_item     {slot, to}            optional: count (split a stack)
    sort_items    {}
    drop_item     {slot}                optional: count; the items go into the camp store
    pick_up       {item}                optional: count; from the camp store
    use_item      {slot}                eat, drink... (items.json 'use')
    give_item     {slot, to}            optional: count; straight into their pack
    offer_trade   {to, give, want}      give/want: [{item, count}]; they accept or decline
    answer_trade  {offer, accept}
    cancel_trade  {offer}
"""
from typing import Any, Dict, List, Optional, Tuple

from utils.messages import Messages
from world import environment
from world.items import (CAMP_STORE, ITEMS, KEEPING, OFFER_LIFE_HOURS, describe, pile_add, pile_list,
                         substitutes)

QUICK_ACTIONS = {"move_item", "sort_items", "drop_item", "pick_up", "use_item", "give_item",
                 "offer_trade", "answer_trade", "cancel_trade"}
ALWAYS_ALLOWED = {"move_item", "sort_items", "cancel_trade"}


def _int(v: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class Possessions:
    def __init__(self, engine):
        self.engine = engine
        self.ground: Dict[str, int] = {}
        for s in CAMP_STORE:
            pile_add(self.ground, s["item"], s["count"])
        self.offers: List[Dict[str, Any]] = []  # open trade offers
        self._next_offer = 1
        self.wear: Dict[str, List[int]] = {}  # uses left of worn tools in the store (tools not listed are new)

    # ------------------------------------------------------------------ #
    # Tool wear (items.json tool 'uses'): kept on the slot in a pack, and listed here for the store
    # ------------------------------------------------------------------ #
    def _store_take(self, item: str) -> Optional[int]:
        """Take one `item` out of the store; returns its uses left if it is a worn tool (None: as new)."""
        self.ground[item] -= 1
        if not self.ground[item]:
            del self.ground[item]
        worn = self.wear.pop(item, [])
        uses = worn.pop(0) if worn else None
        worn = worn[:self.ground.get(item, 0)]  # never more worn tools than tools
        if worn:
            self.wear[item] = worn
        return uses

    def _store_put(self, item: str, count: int, uses: Optional[int] = None):
        pile_add(self.ground, item, count)
        if ITEMS[item].uses and uses is not None and uses < ITEMS[item].uses:
            self.wear.setdefault(item, []).append(int(uses))

    def _move_between_packs(self, giver, taker, item: str, count: int):
        for _ in range(count if ITEMS[item].uses else 0):
            taker.inventory.add(item, 1, giver.inventory.pop_uses(item))
        if not ITEMS[item].uses:
            giver.inventory.take(item, count)
            taker.inventory.add(item, count)

    def uses_left(self, player, item: str) -> Optional[int]:
        i = player.inventory.wear_slot(item)
        return player.inventory.slots[i].get("uses") if i is not None else None

    def wear_tool(self, player, item: str) -> bool:
        """One use of the player's `item` tool: it wears down a use. True if that wore it out (it is gone)."""
        if not ITEMS[item].uses:
            return False
        i = player.inventory.wear_slot(item)
        if i is None:
            return False
        slot = player.inventory.slots[i]
        slot["uses"] = slot.get("uses", ITEMS[item].uses) - 1
        if slot["uses"] <= 0:
            player.inventory.take_from(i, 1)
            return True
        return False

    # ------------------------------------------------------------------ #
    # Who can handle items
    # ------------------------------------------------------------------ #
    def hands_free(self, player) -> Optional[str]:
        """None if the player can use their hands, else why not ('asleep')."""
        e = self.engine
        last = e.last_action.get(player.name, {})
        busy = not e.is_free(player) and e.free_at[player.name] > e.clock
        if busy and last.get("type") == "collapse":
            return "collapsed"
        if busy and last.get("type") == "care" and last.get("params", {}).get("kind") == "sleep":
            return "asleep"
        rule = e.contests.restriction(player.name)
        if rule is not None and rule["locked"]:
            return "in a ritual fight"
        return None

    # ------------------------------------------------------------------ #
    # Doing
    # ------------------------------------------------------------------ #
    def act(self, player, action, reason: Optional[str] = None) -> bool:
        if action.type not in QUICK_ACTIONS:
            return False
        self.expire()
        if action.type not in ALWAYS_ALLOWED:
            why = self.hands_free(player)
            if why:
                Messages.add(f"{player.name} can't handle items while {why}.", important=False)
                return False
        return bool(getattr(self, f"_{action.type}")(player, action.params, reason))

    def _slot(self, player, params, key: str = "slot") -> Optional[int]:
        i = _int(params.get(key))
        if i is None or not player.inventory.valid_slot(i):
            Messages.add("There is no such slot.", important=False)
            return None
        return i

    def _move_item(self, player, params, reason) -> bool:
        src, dst = self._slot(player, params), self._slot(player, params, "to")
        if src is None or dst is None:
            return False
        if not player.inventory.move(src, dst, _int(params.get("count"))):
            Messages.add("That can't go there.", important=False)
            return False
        return True

    def _sort_items(self, player, params, reason) -> bool:
        player.inventory.sort()
        return True

    def _drop_item(self, player, params, reason) -> bool:
        i = self._slot(player, params)
        if i is None:
            return False
        taken = player.inventory.take_from(i, _int(params.get("count"), 10 ** 9))
        if not taken:
            Messages.add("That slot is empty.", important=False)
            return False
        self._store_put(taken["item"], taken["count"], taken.get("uses"))
        Messages.add(f"{player.name} puts {describe([taken])} in the camp store", important=False, reason=reason,
                     category="life")
        return True

    def _pick_up(self, player, params, reason) -> bool:
        item = params.get("item")
        have = self.ground.get(item, 0)
        if not have:
            Messages.add("There is none of that in the camp store.", important=False)
            return False
        want = min(have, _int(params.get("count"), have) or have)
        n = min(want, player.inventory.room_for(item))
        if n <= 0:
            Messages.add(f"{player.name} has no room for {ITEMS[item].name}.", important=False)
            return False
        if ITEMS[item].uses:
            for _ in range(n):
                player.inventory.add(item, 1, self._store_take(item))
        else:
            player.inventory.add(item, n)
            self.ground[item] -= n
            if not self.ground[item]:
                del self.ground[item]
        Messages.add(f"{player.name} takes {describe([{'item': item, 'count': n}])} from the camp store", important=False,
                     reason=reason, category="life")
        return True

    def _use_item(self, player, params, reason) -> bool:
        i = self._slot(player, params)
        if i is None:
            return False
        s = player.inventory.slots[i]
        if not s or not ITEMS[s["item"]].use:
            Messages.add("That can't be used.", important=False)
            return False
        item = ITEMS[s["item"]]
        player.inventory.take_from(i, 1)
        for need, amount in item.use.items():
            if need == "health":
                player.health = max(0.0, min(100.0, player.health + amount))
            elif need in player.needs:
                player.needs[need] = max(0.0, min(100.0, player.needs[need] + amount))
        Messages.add(f"{player.name} {item.use_announce}", important=False, reason=reason, category="life")
        return True

    def _give_item(self, player, params, reason) -> bool:
        i = self._slot(player, params)
        other = self.engine.player(params.get("to", ""))
        if i is None or other is None or other is player:
            Messages.add("Give it to whom?", important=False)
            return False
        s = player.inventory.slots[i]
        if not s:
            Messages.add("That slot is empty.", important=False)
            return False
        n = max(1, min(_int(params.get("count"), s["count"]) or s["count"], s["count"]))
        if other.inventory.room_for(s["item"]) < n:
            Messages.add(f"{other.name} has no room for {describe([{'item': s['item'], 'count': n}])}.", important=False)
            return False
        given = player.inventory.take_from(i, n)
        other.inventory.add(given["item"], given["count"], given.get("uses"))
        Messages.add(f"{player.name} gives {describe([given])} to {other.name}", important=False, reason=reason,
                     category="life")
        return True

    # ------------------------------------------------------------------ #
    # The camp store, for work and meals
    # ------------------------------------------------------------------ #
    def available(self, player, item: str) -> int:
        """How many of `item` the player can lay hands on: their own pack plus the camp store, counting
        better items that stand in for it (items.json 'counts_as')."""
        return sum(player.inventory.count(k) + self.ground.get(k, 0) for k in substitutes(item))

    def has_all(self, player, stacks: List[Dict[str, Any]]) -> bool:
        return all(self.available(player, s["item"]) >= s["count"] for s in stacks)

    def consume(self, player, stacks: List[Dict[str, Any]]) -> bool:
        """Use up items: from the player's pack first, then the camp store. All or nothing."""
        return self.consume_used(player, stacks) is not None

    def consume_used(self, player, stacks: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """Use up items (pack first, then the camp store; a better item that 'counts_as' the one asked for
        goes first). Returns what was actually used, or None (and nothing used) if something is missing."""
        if not self.has_all(player, stacks):
            return None
        used: List[Dict[str, Any]] = []
        for s in stacks:
            left = s["count"]
            for from_pack in (True, False):
                for k in substitutes(s["item"]):
                    if not left:
                        break
                    n = min(left, player.inventory.count(k) if from_pack else self.ground.get(k, 0))
                    if not n:
                        continue
                    if from_pack:
                        player.inventory.take(k, n)
                    else:
                        self.ground[k] -= n
                        if not self.ground[k]:
                            del self.ground[k]
                    used.append({"item": k, "count": n})
                    left -= n
        return used

    def deliver(self, stacks: List[Dict[str, Any]]):
        """Put items straight into the camp store."""
        for s in stacks:
            pile_add(self.ground, s["item"], s["count"])

    # ------------------------------------------------------------------ #
    # Bringing work home, and NPCs keeping what they need (items.json 'keeping')
    # ------------------------------------------------------------------ #
    @staticmethod
    def _points(player, need: str) -> float:
        return sum(ITEMS[k].use.get(need, 0) * n for k, n in player.inventory.totals().items())

    @staticmethod
    def _portion(need: str) -> float:
        """Points of `need` one meal or drink restores (character.json care actions)."""
        from world.character import RULES
        return next((c.restores[need] for c in RULES.care_actions.values() if c.consumes and need in c.restores), 70)

    def _own_work_uses(self, player) -> Dict[str, set]:
        """Items the player's own work uses: {'tools': ..., 'materials': ...}. Materials only for their own
        job's work (a Fire Tender's wood, a Toolmaker's stone): work open to anyone draws on the store."""
        from core import work as WORK
        gov = self.engine.government
        occupations, offices = gov.occupations_of(player), gov.offices_of(player)
        tools, materials = set(), set()
        for t in [*WORK.TASKS.values(), *WORK.RECIPES.values()]:
            own = WORK.job_for(t, occupations, offices) is not None
            if not own and not t.open_to_anyone:
                continue
            tools.update(self.tool_options(t.tools))
            tools.update(t.boost)
            if not own:
                continue  # work anyone may do (laying the dead to rest...) takes its wood from the store
            for stacks in t.tool_consumes.values():
                materials.update(k for s in stacks for k in substitutes(s["item"]))
            materials.update(s["item"] for s in t.consumes)
        return {"tools": tools, "materials": materials}

    keeps_all: Optional[set] = None  # names of human players (set by core/game.py); None: by players.json

    def _keeps_all(self, player) -> bool:
        return player.name in self.keeps_all if self.keeps_all is not None else player.controller == "human"

    def wants_to_keep(self, player, item: str) -> int:
        """How many more of `item` an NPC keeps for themselves before sharing with the camp store."""
        k, info = KEEPING, ITEMS[item]
        for need, key in (("food", "meals"), ("water", "drinks")):
            if info.use.get(need, 0) > 0:
                want = k.get(key, 3) * self._portion(need) - self._points(player, need)
                return max(0, int(-(-want // info.use[need])))  # round up
        have = player.inventory.count(item)
        if info.use.get("health", 0) > 0:
            return max(0, int(k.get("medicine", 1)) - have)
        uses = self._own_work_uses(player)
        if item in uses["tools"]:
            return max(0, int(k.get("own_tools", 1)) - have)
        if item in uses["materials"]:
            return max(0, int(k.get("own_materials", 6)) - have)
        return 0

    def bring_back(self, player, stacks: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """What work brought back goes into the worker's pack. A human player keeps it all; an NPC keeps
        what it needs and shares the rest. Whatever doesn't fit goes to the camp store. Returns (kept, shared)."""
        kept, shared = [], []
        for s in stacks:
            n = s["count"] if self._keeps_all(player) else min(s["count"], self.wants_to_keep(player, s["item"]))
            left = player.inventory.add(s["item"], n) if n else 0
            if n - left:
                kept.append({"item": s["item"], "count": n - left})
            rest = s["count"] - (n - left)
            if rest:
                pile_add(self.ground, s["item"], rest)
                shared.append({"item": s["item"], "count": rest})
        return kept, shared

    def restock(self, player) -> bool:
        """An NPC low on food or water takes some from the camp store into their pack (food as varied as
        it can: a varied pack makes people content). Returns True if they took anything."""
        from world.items import restoring
        took = False
        for need, key in (("food", "meals"), ("water", "drinks")):
            portion = self._portion(need)
            if self._points(player, need) >= KEEPING.get("restock_below_meals", 1) * portion:
                continue
            short = KEEPING.get("restock_" + key, KEEPING.get(key, 3)) * portion - self._points(player, need)
            plan: Dict[str, int] = {}
            kinds = [k for k in restoring(need) if self.ground.get(k, 0)]
            while kinds and short > 0:
                for k in list(kinds):  # one of each kind in turn
                    if short <= 0:
                        break
                    if plan.get(k, 0) >= min(self.ground.get(k, 0), player.inventory.room_for(k)):
                        kinds.remove(k)
                        continue
                    plan[k] = plan.get(k, 0) + 1
                    short -= ITEMS[k].use[need]
            for k, n in plan.items():
                took |= self._pick_up(player, {"item": k, "count": n}, f"is running out of {need}")
        return took

    def put_back(self, player) -> bool:
        """An NPC puts materials into the camp store that their own job doesn't use up (wood and stone are
        for the Fire Tender and the Toolmaker), and own-job materials beyond 'own_materials'. Food, water,
        medicine and tools stay. Returns True if they put anything back."""
        from core import work as WORK
        materials = {s["item"] for t in [*WORK.TASKS.values(), *WORK.RECIPES.values()] for s in t.consumes} | \
                    {k for t in [*WORK.TASKS.values(), *WORK.RECIPES.values()]
                     for stacks in t.tool_consumes.values() for s in stacks for k in substitutes(s["item"])}
        mine = self._own_work_uses(player)
        done = False
        for item, have in player.inventory.totals().items():
            info = ITEMS[item]
            if item not in materials or info.uses or item in mine["tools"] or \
                    any(info.use.get(n, 0) > 0 for n in ("food", "water", "health")):
                continue
            spare = have - (int(KEEPING.get("own_materials", 6)) if item in mine["materials"] else 0)
            if spare > 0:
                player.inventory.take(item, spare)
                pile_add(self.ground, item, spare)
                done = True
                Messages.add(f"{player.name} puts {describe([{'item': item, 'count': spare}])} in the camp store",
                             important=False, category="life", reason="their work doesn't use it")
        return done

    @staticmethod
    def tool_options(options: List[str]) -> List[str]:
        """`options` in order, each preceded by the better tools that stand in for it ('counts_as')."""
        out: List[str] = []
        for key in options:
            out += [k for k in substitutes(key) if k not in out]
        return out

    def find_tool(self, player, options: List[str], usable=None) -> Optional[str]:
        """The first of `options` (or a better tool standing in for one) the player has in their pack, else
        in the camp store. `usable(tool)`: skip tools that can't be used now (a bow with no arrows)."""
        options = self.tool_options(options)
        for where in (player.inventory.count, lambda k: self.ground.get(k, 0)):
            for key in options:
                if where(key) and (usable is None or usable(key)):
                    return key
        return None

    def tools_missing(self, player) -> List[Tuple[str, Any]]:
        """(job, task) for each piece of this player's job work that needs a tool they don't carry."""
        from core import work as WORK
        gov = self.engine.government
        out = []
        for job in gov.jobs_of(player):
            for t in WORK.tasks_of_job(job):
                if t.tools and gov.is_unlocked(t.requires) and \
                        not any(player.inventory.count(k) for k in self.tool_options(t.tools)):
                    out.append((job, t))
        return out

    def take_tools_for_work(self):
        """Whoever's job needs a tool they don't carry takes one from the camp store as soon as there is one
        (work.json 'auto_take_tools'): appointed before any tool existed, they wait for one, then get to work.
        The best tool first, one whose ammunition is in the store too if there is one."""
        from core import work as WORK
        if not WORK.AUTO_TAKE_TOOLS:
            return
        e = self.engine
        for p in e.players:
            if self.hands_free(p):
                continue  # asleep, collapsed...: later
            for job, t in self.tools_missing(p):
                if any(p.inventory.count(k) for k in self.tool_options(t.tools)):
                    continue  # took one for another task of the same job just now
                stored = [k for k in self.tool_options(t.tools) if self.ground.get(k, 0) and p.inventory.room_for(k)]
                key = next((k for k in stored if self.has_all(p, e.production._tool_consumes(t, k))), stored[0] if stored else None)
                if key:
                    name = job[7:] if job.startswith("office:") else job
                    self._pick_up(p, {"item": key, "count": 1}, f"needs it for their work as {name}")

    def tools_waited_for(self) -> List[str]:
        """Tools someone is waiting for: their job needs one, and there is none in their pack or the store."""
        wanted: List[str] = []
        for p in self.engine.players:
            for _, t in self.tools_missing(p):
                if not any(self.ground.get(k, 0) for k in self.tool_options(t.tools)):
                    wanted += [k for k in t.tools if k not in wanted]
        return wanted

    def take_tool(self, player, key: str) -> bool:
        """Make sure the tool is in the player's pack (taking it from the store if need be)."""
        if player.inventory.count(key):
            return True
        if self.ground.get(key, 0) and player.inventory.room_for(key) >= 1:
            player.inventory.add(key, 1, self._store_take(key))
            return True
        return False

    def break_tool(self, player, key: str):
        if player.inventory.count(key):
            player.inventory.pop_uses(key)
        elif self.ground.get(key, 0):
            self._store_take(key)

    def pick_meal(self, player, need: str, wanted: float) -> List[Dict[str, Any]]:
        """Items to eat or drink to restore about `wanted` of `need`: the plainest first, from the person's
        own pack only (food in the camp store must be taken into the pack first). Empty if there is nothing."""
        from world.items import restoring
        out, got = [], 0.0
        for key in restoring(need):
            per = ITEMS[key].use[need]
            have = player.inventory.count(key)
            n = 0
            while n < have and got < wanted - per / 2:
                n += 1
                got += per
            if n:
                out.append({"item": key, "count": n})
        if not out:  # too little wanted to bother, but something is there: take one of the plainest
            key = next((k for k in restoring(need) if player.inventory.count(k)), None)
            if key:
                out.append({"item": key, "count": 1})
        return out

    def store_supply(self, need: str) -> float:
        """Food or water points in the camp store alone (what people without any can take)."""
        return sum(ITEMS[k].use.get(need, 0) * n for k, n in self.ground.items())

    def supply(self, need: str) -> float:
        """How much of `need` (food or water points) everything in the camp store and everyone's packs holds."""
        total = 0.0
        for key, n in self.ground.items():
            total += ITEMS[key].use.get(need, 0) * n
        for p in self.engine.players:
            for key, n in p.inventory.totals().items():
                total += ITEMS[key].use.get(need, 0) * n
        return total

    # ------------------------------------------------------------------ #
    # Trades
    # ------------------------------------------------------------------ #
    @staticmethod
    def _clean(stacks: Any) -> Optional[List[Dict[str, Any]]]:
        if not isinstance(stacks, list):
            return None
        out: Dict[str, int] = {}
        for s in stacks:
            if not isinstance(s, dict) or s.get("item") not in ITEMS or (_int(s.get("count")) or 0) < 1:
                return None
            out[s["item"]] = out.get(s["item"], 0) + int(s["count"])
        return [{"item": k, "count": v} for k, v in out.items()]

    @staticmethod
    def _fits(giver, receiver, give: List[Dict[str, Any]], get: List[Dict[str, Any]]) -> bool:
        """Would `receiver` have room for `give` once `get` has left their pack?"""
        inv = receiver.inventory.copy()
        for s in get:
            if not inv.take(s["item"], s["count"]):
                return False
        return all(inv.add(s["item"], s["count"]) == 0 for s in give)

    def _has(self, player, stacks) -> bool:
        return all(player.inventory.count(s["item"]) >= s["count"] for s in stacks)

    def offer(self, key: Any) -> Optional[Dict[str, Any]]:
        return next((o for o in self.offers if o["id"] == _int(key)), None)

    def _offer_trade(self, player, params, reason) -> bool:
        other = self.engine.player(params.get("to", ""))
        give, want = self._clean(params.get("give", [])), self._clean(params.get("want", []))
        if other is None or other is player or give is None or want is None or not (give or want):
            Messages.add("That isn't a trade.", important=False)
            return False
        if give and want and not self.can_barter():
            Messages.add("Trading one thing for another needs the Barter System; for now you can only give "
                         "things or ask for them.", important=False)
            return False
        if not self._has(player, give):
            Messages.add(f"{player.name} doesn't have {describe(give)}.", important=False)
            return False
        if not self._has(other, want):
            Messages.add(f"{other.name} doesn't have {describe(want)}.", important=False)
            return False
        if any(o["from"] == player.name and o["to"] == other.name for o in self.offers):
            Messages.add(f"{player.name} is already waiting for {other.name}'s answer.", important=False)
            return False
        e = self.engine
        o = {"id": self._next_offer, "from": player.name, "to": other.name, "give": give, "want": want,
             "made": e.clock, "expires": e.clock + max(1, environment.life_hours_to_calendar(OFFER_LIFE_HOURS))}
        self._next_offer += 1
        self.offers.append(o)
        what = describe(give) if give else "nothing"
        Messages.add(f"{player.name} offers {other.name} {what} for {describe(want) if want else 'nothing'}",
                     important=False, reason=reason, category="life")
        return True

    def _answer_trade(self, player, params, reason) -> bool:
        o = self.offer(params.get("offer"))
        if o is None or o["to"] != player.name:
            Messages.add("There is no such offer.", important=False)
            return False
        self.offers.remove(o)
        giver = self.engine.player(o["from"])
        if not params.get("accept"):
            Messages.add(f"{player.name} turns down {giver.name}'s trade", important=False, reason=reason,
                         category="life")
            return True
        if not self._has(giver, o["give"]) or not self._has(player, o["want"]):
            Messages.add(f"The trade between {giver.name} and {player.name} falls through: the items are gone.",
                         important=False)
            return True
        if not self._fits(giver, player, o["give"], o["want"]) or not self._fits(player, giver, o["want"], o["give"]):
            Messages.add(f"The trade between {giver.name} and {player.name} falls through: no room to carry it.",
                         important=False)
            return True
        for s in o["give"]:
            self._move_between_packs(giver, player, s["item"], s["count"])
        for s in o["want"]:
            self._move_between_packs(player, giver, s["item"], s["count"])
        Messages.add(f"{player.name} accepts {giver.name}'s trade: "
                     f"{describe(o['give']) or 'nothing'} for {describe(o['want']) or 'nothing'}",
                     important=False, reason=reason, category="life")
        return True

    def _cancel_trade(self, player, params, reason) -> bool:
        o = self.offer(params.get("offer"))
        if o is None or o["from"] != player.name:
            Messages.add("There is no such offer.", important=False)
            return False
        self.offers.remove(o)
        Messages.add(f"{player.name} withdraws the offer to {o['to']}", important=False, category="life")
        return True

    def forget(self, player):
        """Someone has died: what they carried goes to the camp store (worn tools keep their wear), and trade
        offers to or from them lapse."""
        for slot in player.inventory.to_list():
            if slot:
                for _ in range(slot["count"]) if ITEMS[slot["item"]].uses else [None]:
                    self._store_put(slot["item"], 1 if ITEMS[slot["item"]].uses else slot["count"], slot.get("uses"))
        player.inventory.load([])
        self.offers = [o for o in self.offers if player.name not in (o["from"], o["to"])]
        if self.keeps_all is not None:
            self.keeps_all.discard(player.name)

    def expire(self):
        now = self.engine.clock
        for o in [o for o in self.offers if o["expires"] <= now]:
            self.offers.remove(o)
            Messages.add(f"{o['to']} never answered {o['from']}'s trade offer", important=False, category="life")

    def awaiting_answer(self) -> List[Dict[str, Any]]:
        self.expire()
        return list(self.offers)

    # ------------------------------------------------------------------ #
    # Observation and saving
    # ------------------------------------------------------------------ #
    def can_barter(self) -> bool:
        """Two-sided trades need research (items.json 'barter_requires'); asking and giving never do."""
        from world.items import BARTER_REQUIRES
        return self.engine.government.is_unlocked(BARTER_REQUIRES)

    def observe(self, player) -> Dict[str, Any]:
        e = self.engine
        return {
            "barter": self.can_barter(),
            "inventory": player.inventory.observe(),
            "ground": pile_list(self.ground),
            "hands": self.hands_free(player),
            "offers": [{**o, "hours_left": max(0, o["expires"] - e.clock)} for o in self.offers
                       if player.name in (o["from"], o["to"])],
        }

    def to_dict(self) -> Dict[str, Any]:
        return {"ground": dict(self.ground), "offers": [dict(o) for o in self.offers], "next_offer": self._next_offer,
                "wear": {k: list(v) for k, v in self.wear.items()}}

    def load_state(self, data: Dict[str, Any]):
        if not data:
            return  # an older save: the camp ground starts as in items.json
        self.ground = {k: int(v) for k, v in data.get("ground", {}).items() if k in ITEMS and v > 0}
        self.offers = [dict(o) for o in data.get("offers", [])]
        self.wear = {k: [int(x) for x in v] for k, v in data.get("wear", {}).items() if k in ITEMS}
        self._next_offer = data.get("next_offer", 1)

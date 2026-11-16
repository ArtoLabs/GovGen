# GovGen
Algorithm for building in-game government architecture

## Running

From this folder:

```bash
../venv/bin/pip install -r requirements.txt                       # once: installs Textual (the HUD)
../venv/bin/python -m core.main                                   # play on the HUD; offers to continue your saved game
../venv/bin/python -m core.main --classic                         # old scrolling text menus (the game pauses for you)
../venv/bin/python -m core.main --new                             # start over (the save is replaced at the next autosave)
../venv/bin/python -m core.main --watch --years 20 --speed 20     # all 12 players are NPCs, 20x speed
../venv/bin/python -m core.main --seed 7 --log game.jsonl         # repeatable game, every action saved
../venv/bin/python -m unittest discover -s tests -t .             # tests
```

**Time.** The game runs on a 360-day calendar. Every action takes game time (voting 2 hours,
nominating 4, a reform 3 days...). Nobody takes turns: whoever becomes free next acts next. At normal
speed a game year takes about five real minutes. Change speed in game (F5) or with `--speed`
(`max` = no waiting). Members of the tribe act only now and then (they spend
weeks at a time going about their lives) but come back within a few days when an election or vote
opens that they can take part in. Progress is slow on purpose: reaching the Stone Age takes decades
(tune `innovation_cost_multiplier` in `data/time.json`).

**New characters.** Every new game starts everyone's attributes at 5 (average) and rolls dice for a bonus on top (5–9; only illness, age and the like later take one below 5); skills start at 0 except
those of jobs open from the start (gathering, firekeeping). Children get only the part of the roll their
childhood so far would have given them, and babies born in the game start at 5 in everything. Saved games
keep their characters, including everyone born and lost.

**Life and death.** People are born, grow up, fall ill and die (`data/life.json`). The tribe starts young,
from a baby to a 42-year-old, because in the Tribal Age few live past about 45 and anyone reaching 50 is
the oldest alive. Anyone can fall ill, the old far more often, and each piece of work done adds to the
risk. While ill (🤒 in your box) health drains, nothing heals, and at nothing you die. Only a healer can
cure it: press `e`, See the healer. The Healer (Herbalism) needs herbs or poultices in their own pack; each
visit uses one, may cure you (the older you are, the less likely; by about 52 never) and gives back some
health, so very low health needs several visits, or rest. Health otherwise comes back only while not
working, fastest resting or asleep. The dead lie in camp (💀 in the tribe list) until someone carries them
away, burns them on a pyre or (with Burial Rites) buries them (`w`); while they lie there, everyone falls
ill more easily. Then they are gone from the tribe. Every 28 days there is a small chance one of the women
becomes pregnant (🤰, a bar shows the nine months); she can't work for the last three, then a baby joins
the tribe. Children don't work until 9: they play and study (`w`), alone or with friends, stories, plants,
fire, tracks..., and what they choose shapes their attributes (everyone is born with 5 in each) until 9,
when they are set. From 14 they vote and may hold office. If your character dies, you play on as your
eldest child, else the youngest adult. Every number, including the working age, lifespans and illnesses,
can change by age, government or discovery in `data/life.json`.

**Society and satisfaction.** Everyone does their work with a quality (attributes, skill, health).
Together that makes the society's qualities (food, water, leadership, safety, fire, care, tools, culture,
shelter) and each person's contentment meters (food, work, leaders, society, comfort, safety), which
partly measure life against what people have grown used to:
- **Work** rises only while someone is working their job (`w`); just holding a job is worth very little,
  and an unworked job lets it sink. It rises faster with the right tool for the job (two or more, faster
  still; no tool is missed before one has been invented) and with a wide choice of work *for the age*:
  every Tribal job open is a big boost, but the same jobs out of a later age's many more are not.
- **Comfort** follows the tribe's Fire quality, care from Healers and the Spirit Keeper, and shelter. Fire
  rises only when people use the fire: every time someone warms up by it (`e`) it goes up; a fire merely
  burning adds nothing, and otherwise it stays where it is. While the Spirit Keeper leads a ritual (their
  `w` work) everyone's Comfort rises faster and care counts double. Every death takes one chunk (10) out of
  the tribe's Care, which comes back slowly by itself.
- **Safety** follows Warriors and Scouts watching over the camp and every position being filled (office
  seats and jobs): each Warrior on patrol right now speeds it up (and counts double), while empty seats
  slow it, or stop it.
- **Leaders** reflects everything: how well the offices are run and every other meter, faster while most
  of them rise. Someone appointed to work they are poorly suited for warms to the leaders only slowly.

Every office has work too: Elders hold council, the Spirit Keeper leads rituals, other offices attend to
their duties. F8 shows what is moving each of your meters and by how much. NPCs look after their bodies as always but act
far less than you, and turn to politics only when unhappy; leaders appoint where something is lacking.
A leader may appoint and dismiss at will, with no waiting and no limit per job. Being appointed doesn't
by itself sour anyone: what counts is where the new work stands in the **hierarchy of work**. Work that
needs no research and no tools (Gatherer, Firekeeper) is the bottom rung; each research step behind a job,
and needing tools, puts it higher; offices rank by their points. Moving someone up (from no work to Scout,
or Gatherer to Hunter) warms them to the leaders; moving them down sours them; moving them across, or giving
someone with no work an unskilled job, changes nothing (leaving work they had got into still costs a little
Work contentment). The pick list marks each candidate ▲ a step up or ▼ a step down. Dismissing someone
outright hits them hard (and everyone else a little), and the grievance fades only slowly. All of it comes
from the data, so new ages and governments get their own hierarchy just by adding jobs and offices.

**Hard times.** Suffering drags contentment down fast, on top of the usual drift (`society.json` meters'
`hardship`): freezing sinks Comfort, being weak or starving sinks Food and Work, and a tribe with many
people ill, starving or freezing sinks everyone's Society and Leaders contentment. The ill, and anyone
below 35 health, can't work at all (`life.json` `no_work`), so their Work contentment sinks too. Patience
is shorter than it was, so an unhappy tribe moves against its leaders well before it dies out. When an
office holder dies, the seat doesn't wait: an election opens at once (a short one, even for offices
normally filled by a divine sign), and anyone may campaign for the empty seat by persuasion straight away.

**Patience.** An unhappy tribe does not turn on its leaders at once. Each person counts how long their
Leaders (or Society) contentment has been low; only once that passes their patience (10 cycle-hours for
Leaders by default, then building up over 6 more) do NPCs campaign, challenge, call removal votes, outcast
or reform. The chronicle warns when patience is wearing thin and when it runs out; F9 shows everyone's
patience and F8 your own. Patience comes back, faster than it went, once contentment recovers.

**Ability** (the bar under your Roles, the "ability" column in F9) is not contentment: it is how well you
do your best job or office right now, from its attributes and skill, less while tired or unwell. It sets
how much your work yields and adds to the society's qualities; it dips as you tire, recovers with sleep and
grows as you practise. Working your office (`w`) trains its skill: a Clan Leader attending to their duties
learns leadership, more while the tribe is content; a leader who neglects the office while the tribe
suffers loses it.
F9 shows it all. Every rate and multiplier is in `data/society.json` (and NPC eagerness in `data/npc.json`).

**New ages and governments.** Nobody votes a tribe into a chiefdom. When research brings the next age,
the government changes by itself into the age's form (`ages.json` `government_on_arrival`): the first one
whose research is already done, else the last. Tribal Council researched before the Stone Age means a
Village Council; otherwise a Chiefdom. Office holders carry over (the Clan Leader becomes Chieftain, the
Spirit Keeper Priest, Elders stay Elders), and so do their appointments. The new offices (War Leader,
Steward...) start empty, to be won by election, persuasion, challenge or appointment. The research
picker and F4 say which government an innovation leads to. Changing to another form of the same age
(a Sacred Chiefdom once Divine Right is known) is a reform (`f`); there is no reform to another age.

**Taking an office.** Besides elections, tribal offices can be taken by persuasion (a campaign of a
few day-night hours: win people over one by one while the holder rallies them back; everyone's
persuasion meter shows in the Tribe panel) or by challenge (the one challenged picks: oration before the tribe, a ritual fight,
or a contest in their own work such as hunting or gathering). In an oration both contestants speak to
listeners one at a time (`p`) and can still eat, drink and vote; a ritual fight holds both until someone
yields. Persuading never backfires: each talk wins a listener over at least a little, and the holder's
rallies can stall a campaign but never push anyone below where they started; people unhappy with their
leaders, and a holder doing the job badly, make a campaign start much further along. Someone who has just
taken an office can't be persuaded against, challenged or voted out for one day-night cycle; anyone may
resign an office (`g`). An unhappy tribe blames its top leader most: NPCs go after the Clan Leader first. Contests and elections don't mix: someone campaigning by persuasion or challenging for an office
can't be nominated, and someone nominated (or on a ballot) can't start a campaign or a challenge until
they decline. See
`data/contests.json`.

**Standing for office.** You can stand in one election at a time. Candidates' own votes go to
themselves automatically, so they are never asked to vote. Anyone nominated may decline (`n`), or withdraw
once voting has begun; votes already cast for them are void. An office is its holder's work: taking one
means giving up your occupation, and office holders take no other work.

**Living off the land.** Food and water come only from work. Every job has work to do (`w`):
Gatherers forage for berries and roots, gather wood and stone and fetch water (only they do), Hunters
hunt, Fishers fish, the Toolmaker crafts tools from wood, stone and flint, the Firekeeper feeds the
fire with wood. What work brings back goes into the worker's own pack: you keep it all and decide what
to put in the shared camp store; NPCs keep about two meals' worth (and the tools and materials their own
job uses) and share the rest. You eat and drink only from your own pack: to eat from the store, take the
food into your inventory first (I, then Tab). NPCs running low do that themselves. How content you are
with food depends on the variety you carry: nothing falls fast, one kind barely holds, two or more
kinds raise it, faster the more kinds. The tribe's Food quality counts the food it actually holds as well
as the work being done, so it drops when people go hungry and leaders put more people on food. With none left, people go hungry and
thirsty and lose health, and at no health they die: of starvation, thirst or cold as much as of illness.
There is no collapsing. The fire burns only while it has wood. Winter is bitter: out and about, your
warmth (🔥 in your Body box) falls fast, and with no fire in camp it falls very fast; frozen, your health
drains. Sleeping or resting at camp by a burning fire only keeps the cold off; to get warm you sit by the
fire (`e`, Warm up), which is also what makes the tribe content with its fire. The tribe's Water quality
fills slowly: it takes a good store of water and Gatherers fetching it.
The camp starts empty and everyone carries only a mouthful. Trips out (foraging, wood, stone, hunting,
fishing, herbs) are a gamble: foraging succeeds about 3 times in 10, hunting about 1 in 4, unless a
good place of that kind is known (berry grounds, deadwood, a stone bed, game trails, a fishing pool, an
herb patch). A kill is worth far more than a forage: about 13 meat (3–4 times a forage's food) plus hide
and bone. A Scout brings nothing back, but chooses what to look for, as a Gatherer chooses what to gather: berry grounds, deadwood, a stone bed, game trails, a fishing pool or an herb patch (only kinds someone could use yet). They find it far more often than a Gatherer's trip succeeds (85% at average skill). A found place holds an abundance, 3 to 5 ordinary hauls: every trip of that kind, by anyone, goes there, is certain to pay off and takes up to 2 hauls, leaving the rest for the next trip until it is used up; then trips go to the next place found. Finds pop up on screen and in the Chronicle, and the Found places panel under the tribe list shows what is left at each place (and the last few used up or lost). NPC Scouts look for what the tribe is shortest of (no food: berry grounds, game trails, a fishing pool). A Sustenance Gardener tends plots that work the same way. A Healer also goes to the sick themselves (W, Heal): NPC healers put that before any other work, and don't turn herbs into poultices while anyone is ill. Herbs are medicine only: nobody eats them. Fetching water from the river always works.

**The hierarchy of appointments.** Every Tribal office can appoint anyone to any job (never to an office).
Someone who takes up work on their own may quit it; someone appointed must keep it until released. Offices
rank by `authority` (data/governments: Clan Leader 3, Elder 2, Spirit Keeper 1): only the office that made
an appointment, or a higher one, may move that person to other work, dismiss them or release them (D:
"release" lets them keep the work as their own choice, free to quit). An Elder can't touch the Clan
Leader's appointments, and the Spirit Keeper can't touch either's.
A job counts for the tribe (its society qualities and skill practice) only while it is actually worked.
At the start only Gatherer and Firekeeper are open (plus the offices); the other jobs open through
research (Toolmaking, Hunting, Fishing, Tracking, Herbalism, Camp Defense for the Warrior...).

**Tools.** Toolmaking gives sharpened-wood tools: a wooden hand axe, knife and spear (and, with Fishing,
a fishing spear; with Archery, a bow and wooden arrows), all made from wood alone. Only Stone Cutting
opens stone tools: a stone hand axe and knife, a flint spear and flint-tipped arrows. A better tool stands
in for the lesser one (`counts_as` in `data/items.json`): a flint spear does anything a wooden spear does,
flint arrows are used before wooden ones and hunt better, and the camp's stock counts them together.
Someone can be appointed a Hunter, Fisher or Warrior as soon as the research is done, but can't work until
there is a tool for it: they wait (the Tribe panel says what they need), the Toolmaker makes what someone
is waiting for first, and the moment one is in the camp store they take it into their pack and get to work.
A bow with no arrows is put aside for a spear. Making a tool takes three times as long with bare hands:
a stone knife (or a hand axe, or a wooden knife, less so) makes it go faster, and the Toolmaker takes the
best one from the store. Every tool wears: it has a number of uses (wood fewer than stone) and loses one
each time it is used, and may break outright by chance; worn all the way down it breaks for certain. Its
wear stays with it in packs and in the camp store (the inventory window shows uses left), and the worker
must fetch a new one from the store before carrying on. The
top bar counts what the camp store holds (wood, food, water, stone, herbs, tools; `items.json`
`camp_summary`), the same numbers as the store in the inventory window. NPCs whose pack runs out of food
or water take some from the store at once, before anything else. Tasks,
recipes and yields live in `data/work.json`, items in `data/items.json`.

**Inventory.** Everyone carries a pack with a fixed number of slots (16); each slot holds a stack of
one kind of item, up to that item's stack size. Press `i` for your inventory window: arrows move the
cursor, Enter picks up a stack and Enter again places it (onto an empty slot, onto the same item, or
swapping), `s` splits a stack, `o` sorts, `u` uses (eat, drink, apply a poultice), `d` puts it in the camp
store, `g` gives to someone, `t` offers someone a trade (only once the Barter System is researched,
`items.json` `barter_requires`), and Tab switches to the camp store to take things out. On F2, arrows
choose a member and Enter (or a click) opens their inventory, where `t` asks for the item under the cursor
(as a gift; with the Barter System, in a trade) and `g` gives them something. Handling items takes no game time
and works while you are busy, but not while asleep, collapsed or in a ritual fight (sorting always
works). NPCs answer a trade as soon as they are awake: they accept if what they get is worth at least
what they give, and value food and water more when hungry or thirsty. Items are defined in
`data/items.json`.

**The HUD.** By default you play in real time on a fixed "command center" screen: the clock never
waits for you. The Chronicle (left) shows what everyone does as it happens. The middle shows You
(who you are and what you're doing, a Roles box with your office, work and powers, boxes of bars for
your Body, Skills and Content, and your action keys grouped by kind), Government and votes (reforms, open elections and motions) and
the Innovation pool (research, next age, and every discovery as an icon; click one for details).
The right shows the tribe. Letters act (`v` vote, `n` nominate,
`a` appoint, `d` dismiss, `c` call a vote, `f` reform, `r` research, `o` orders, `e` eat, drink,
sleep or warm up, `w` work (gather, hunt, craft...), `j` take up or give up a job, `x` wake or stop, `p` persuade, `h` challenge, `g` resign from an office, `i` inventory); each opens a small
picker where one key chooses and Esc goes back. Pickers that list people (nominate, vote, appoint) show
each person's Fit for the job, the stats and skill it uses, and a line about who they are. F-keys look: F1 help,
F2 tribe (a live card of meters per member, with what they carry; Enter opens a member's inventory), F3 government,
F4 innovations (the current age's innovations with their status and what each needs; Enter queues research), F5 speed, Space pause,
F6 chronicle detail, F7 full log, F8 your character sheet, F9 society, F10 save and quit, F12 (or `k`)
the crafting chart: every item that can be made or found in this age, the job, research, tools and
materials it takes, where those come from, which jobs use it and for what, and whether it can be had now. The mouse works too. Politics runs on days and work
on hours of the day-night cycle, so while you are out working, crafting, resting or eating you can still
vote, nominate, appoint, persuade or challenge without stopping (NPCs do the same); only what you can't
do right now is greyed out.

**Auto and manual.** Press `m` to switch the person you play to auto: from then on the game plays them
exactly like any NPC (same decisions, same keeping and sharing of what they bring back), so you can sit
back and watch the whole tribe run itself. Space still pauses, every screen still works, and your
inventory still opens; `m` again gives you back full control (whatever they were in the middle of finishes
first). The top bar shows AUTO or MANUAL, and the choice is saved with the game.

**Saving.** There is one save, `saves/savegame.json`. The game autosaves at the start of every season
and when you exit (F10 or Ctrl+Q on the HUD; "Save and exit" or Ctrl+C in classic mode). Watch mode never touches it.

Settings live in `data/settings.json`; the calendar and action durations in `data/time.json`.

## How it fits together

```
data/*.json  ──►  GameEngine (core/engine.py)  ◄──►  Controllers (controllers/)
 ages, innovations,   rules and state; no input or        TerminalController  a human at this keyboard
 governments,         printing. Three calls:              NPCController       utility-scoring NPC
 players, settings      observe(player)   -> plain data   (future) network client, Unreal agent
                        legal_actions(player)
                        apply(player, action)
```

**Modules.** `world/` holds the people and the natural world, with no knowledge of governments:
`world/character.py` (attributes, skills, needs, health, aging), `world/environment.py` (day-night
cycle, temperature), `world/player.py` (a Character plus name, gender, mother, traits, controller and inventory), `world/items.py` (item
definitions, inventory slots and stacks). `core/work.py` loads tasks and recipes and rolls what work yields; the engine runs them as `work` and
`craft` actions and delivers the yield when the work is done (a `work_done` event).
`core/life.py` holds life and death (illness and healing, the dead, pregnancy and birth, childhood): the
engine calls it each day and after work, and it adds the `treat` and `activity` actions; births and deaths
add and remove players, and the game loop gives newborns an NPC controller (or hands yours to your heir).
`core/possessions.py` holds the camp store and trade offers
and carries out *quick actions* (moving, dropping, picking up, using, giving and trading items): they
take no game time and don't need the player's moment, so the engine runs them through `quick()` rather
than `apply()`; NPC controllers answer trade offers through `answer_offer()`. `core/` holds
the society's rules: `core/government.py` (offices, statuses, occupations, reform), `core/occupations.py`,
`core/voting*.py`, and `core/engine.py`, which ties them to the clock and exposes observe /
legal_actions / apply. Each maps naturally onto an Unreal component or subsystem later.

Real-time players (the HUD) plug in the same way: `HUDController` (controllers/hud.py) passes views
and decisions between the game loop, which runs in its own thread, and the display. `ui/model.py`
turns observations and legal actions into display-neutral pieces (action keys, picker menus,
innovation catalog, ballot rows); `ui/hud.py` paints them with Textual. A graphical client only
needs to replace `ui/hud.py`.

`core/game.py` runs the loop: move the game clock to the next thing that happens (a scheduled event,
a ballot deadline, or a player becoming free), waiting in real time according to the playback
speed; ask that player's controller for a decision; apply it; and pass the resulting events to every
controller. `core/save.py` writes the whole state (engine, NPC memories, random number generators)
as one JSON file. Actions (`core/actions.py`) and observations are
plain data, so they can be logged, replayed, and sent over a network unchanged. Game content goes
in `data/` (see `data/README.md`).

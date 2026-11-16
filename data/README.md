# Game data

Everything about ages, innovations and governments lives here. The engine validates these files at
startup and stops with a message naming the file and field if something is wrong. Every number that
tunes the game sits in one of these files; the code only holds fallbacks equal to them.

## Where to tweak what

| To change... | Look in |
|---|---|
| How long people live: how often each age falls ill, how fast an illness drains health, how likely a healer's visit cures it | `life.json` → `illnesses` (curves by age) |
| Who heals, with what medicine, how much a visit gives back, when the not-ill may go | `life.json` → `treatment` |
| How fast health comes back while resting, asleep, awake or working (not at all) | `character.json` → `health.regen_factors` |
| How much the unburied dead spread sickness | `life.json` → `remains` |
| How the dead are laid to rest (carry away, pyre, burial) and how long it takes | `work.json` → tasks with `disposes_of_dead` |
| How risky each kind of work is for falling ill | `life.json` → `illnesses.<illness>.work_chance`; `work.json` → a task's `illness_risk` |
| How often women become pregnant, who can, how long it lasts, when they stop working | `life.json` → `pregnancy` |
| Newborns: names, genders, traits, starting attributes | `life.json` → `birth` |
| The age to work and the age for politics (voting, office, research) | `life.json` → `work_age`, `politics_age` |
| Children's play and study and what each does for them | `life.json` → `childhood.activities` |
| How much less children eat and drink | `life.json` → `need_factors` |
| Life stages and aging (attributes changing with age) | `life.json` → `life_stages`, `aging` |
| Any of the above for a later age, a government, or after a discovery | `life.json` → `ages`, `governments`, `innovations` |
| Whom you play on as when your character dies | `life.json` → `successor` |
| How much people lying ill lower the Care quality (so leaders appoint a Healer) | `society.json` → `qualities.care.sick` |
| How NPCs look after their health, lay the dead to rest, and how NPC children choose play and study | `npc.json` → `health`, `remains`, `childhood` |
| Genders, and who can bear children | `character.json` → `genders` |
| How long eating, drinking, sleeping or warming up takes (`life_hours`; eating is 0.5 = 30 minutes of the day-night cycle) and how much it restores | `character.json` → `care_actions` |
| How fast hunger, thirst, tiredness and cold set in; health | `character.json` → `needs`, `health` |
| Whether health at 0 is death (now) or a collapse (the old rule), and what each need kills of | `character.json` → `health.at_zero`; `needs.<need>.death_cause` |
| How hard winter bites, and how much worse with no fire in camp | `character.json` → `needs.warmth.season_factors`, `no_fire_factors` |
| How fast freezing (or any need) drains health | `character.json` → `needs.<need>.health_loss_per_day` (else `health.loss_per_day_per_critical_need`) |
| How warm resting by the fire keeps you (0: it only keeps the cold off) | `world.json` → `fire.resting_warmth` |
| How much a death takes out of Care, and how fast it comes back | `society.json` → `qualities.care.events.death`; `quality_events.recover_half_life_life_hours` |
| How much each warm-up at the fire raises the Fire quality (and whether it fades) | `society.json` → `qualities.fire` (`per_use`, `fall_per_day`, `start`) |
| How hard the Water quality is to fill | `society.json` → `qualities.water` (`per_person`, `sources.Gatherer.amount`, `on_hand.per_member`) |
| Whether NPCs research the cheapest innovation first | `npc.json` → `research.cheapest_first` |
| What keeping the only fire is worth to NPC leaders | `npc.json` → `appoint.sole_provider_worth` |
| How fast skills grow, and how much talent helps | `character.json` → `training_per_year`, `mastery_slowdown`, `talent` |
| How long political actions take (appoint, dismiss, vote, research...) | `time.json` → `action_hours` |
| Research speed, the length of a year and of a day-night cycle | `time.json` |
| What work and crafting take and produce, how lucky a trip is, how far the fire burns | `work.json` |
| Items, stack sizes, what food restores, tool breakage, slots in a pack | `items.json` |
| What the top bar counts of the camp store | `items.json` → `camp_summary` |
| How much going hungry pulls down Food contentment | `society.json` → `satisfaction.meters.food.hunger` |
| How fast tools wear out (uses before they break) and their chance to break | `items.json` → `items.<tool>.tool` (`uses`, `breaks`) |
| How long making a tool takes, and how much tools speed it up | `work.json` → `recipes.<recipe>.life_hours`, `craft_speed_tools` (or a recipe's own `speed_tools`) |
| How eagerly NPCs queue research | `npc.json` → `research` |
| Which tools are better versions of others (stone of wood, flint arrows of wooden) | `items.json` → `counts_as` |
| Which research opens which tools; what tools are made of | `work.json` → `recipes` (`requires`, `inputs`) |
| Who may fetch water (or do any task) | `work.json` → `tasks.<task>.occupations` |
| Jobs: who appoints, what they need, caps (none by default) | `occupations.json` |
| Which government a new age brings (automatically, by what has been researched) | `ages.json` → `government_on_arrival` |
| The hierarchy of appointments (who may move, dismiss or release whose appointees) | `governments/*.json` → `offices.<office>.authority` (default: its points) |
| What being dismissed or moved costs in contentment | `society.json` → `satisfaction.job_loss` |
| The hierarchy of work, and how a step up or down feels | `society.json` → `satisfaction.job_rank`; `rank` on an occupation or office overrides |
| How long an unhappy tribe waits before moving against its leaders | `society.json` → `satisfaction.patience` |
| How fast office holders learn leadership (and their office's skill) | `society.json` → `leadership_training`; `work.json` → `practice_days_per_task` |
| How contentment and society scores are worked out | `society.json` |
| How fast each contentment meter rises and falls, and what speeds it up (tools, choice of work, fit, Warriors on patrol, the Spirit Keeper's rituals, filled positions) | `society.json` → `satisfaction.meters.<meter>`: `rise_per_day`, `fall_per_day`, `multipliers` |
| What working, not working, or having no job is worth to Work; what a tended, untended or dead fire is worth to Comfort | `society.json` → `satisfaction.input_values` |
| Which positions count as "filled" for Safety | `society.json` → `satisfaction.positions` |
| How much more a Warrior on patrol or the Spirit Keeper at a ritual counts toward safety, care and culture | `society.json` → `qualities.<quality>.sources.<job>.while_working` |
| Which age an occupation belongs to (for the choice of work) | `occupations.json` → `age` (default: the latest age of what it requires) |
| How much of the Food (or Water) quality comes from what is actually held (store and packs) rather than work being done | `society.json` → `qualities.food.on_hand`, `qualities.water.on_hand` |
| How much water a trip to the river brings back | `work.json` → `tasks.fetch_water.yields` |
| How much hunger, thirst or tiredness keeps NPCs from everything else, and how much their own hunger sends them to food work | `npc.json` → `distress_damping`, `work.own_need_weight` |
| How eager NPCs are (voting, appointing, dismissing, volunteering) | `npc.json` |
| Persuasion and challenges, and the role of chance in them | `contests.json` |
| How much a leader the tribe is unhappy with loses the power to defend their office (rallies, orations) | `contests.json` → `defender_contentment` |
| Playback speeds, seconds per year | `settings.json` |

## `players.json`
The players, in turn order. Add or remove entries to change the player count (at least two).

Each player has a `gender` (`character.json` `genders`) and may name a `mother` (another player: used
when you play on as your child after you die) and a `birthday` (0-359, the day of the year they age;
otherwise one is picked). Children (below `life.json` `work_age`) start with only part of the dice
roll: the part their childhood so far would have given them.

Each player may list an `inventory` of items (`[{"item": "meat", "count": 2}]`) they carry at the
start, on top of everyone's `starting_inventory` in `items.json`.

## `work.json`
What work produces. `trips`: tasks with a `site` succeed only with `base_chance`, adjusted by work
quality; a task's own `chance` replaces `base_chance` (hunting is rarer than foraging). While a found
place of that kind has something left, the trip goes there instead and succeeds with `with_site_chance`
(1 = always). `sites`: a task with `finds_sites` (the Scout's) becomes one task per kind
(`scout_plants`, `scout_game`...; its label's `{name}`/`{short}` filled in), so the Scout chooses what to
look for; kinds nobody could use yet can't be chosen. The trip finds the place with `find_chance` (plus
`find_quality_effect` by work quality). A place holds `loads` ordinary hauls (a `[min, max]` range, or a
kind's own `loads`); each trip takes up to `take_per_trip` of them (all, if less than `least_left` would
be left), from the oldest place first; then the next place found is used. `life_hours`: an unused place
is lost after this long. `spent_shown`: how many used-up or lost places the Found places panel keeps
listing. `kinds`: name, short, icon, weight (for gardeners' plots). A task with `makes_sites`
(`{"kinds": {kind: weight}, "life_hours": n, "loads": n}`, the Sustenance Gardener's `tend_garden`) tends
a place instead of finding one, topping up their own plot. `tasks`: the work of each job (`occupations`, and/or `offices` for office holders' work such as
the Spirit Keeper's ritual; `any_office` is the work of every office with no task of its own; with none
of them, anyone may do it): `life_hours`, the `skill` it trains, `requires` (innovations), `tools` (one is needed: taken
from the worker's pack, else the camp store; tools may break, see `items.json`), `consumes` (items used
up), `yields` (items brought back to the camp store: `amount` for an average worker, more for better
ones; `chance` that a trip finds it at all), `boost` (tools that multiply the yield), `tool_yields` and
`tool_consumes` (per tool: a bow uses arrows; a tool with nothing left to use up is passed over for the
next), `fire_life_hours` (feeds the fire). A better item standing in for a listed one (`items.json`
`counts_as`) works too, and is used first; `tool_yields` may name ammunition as well (flint arrows).
`disposes_of_dead` (a task open to anyone old enough to work): lays one of the dead to rest (`done_text`
for the chronicle); `illness_risk`: times `life.json` `work_chance` of falling ill when the work is done
(default 1 for a job's own work, none for other work). `auto_take_tools`: whoever's job needs a tool they don't carry takes one from the camp store as soon as
there is one (not while asleep). `recipes`: what is
crafted from `inputs` into an `output`. `fire`: how long the fire burns at the start and at most.
`work_counts_life_hours`: a job counts for the society and for skill practice only if worked within
this long, then fades to nothing over `work_fades_life_hours`. `practice_days_per_task`: how much skill
practice one piece of work is worth. `yield_roll`: yields go from `at_quality_0` to `at_quality_100` x
`amount` with work quality, times a luck factor of 1 ± `luck`. `anyone_attributes`: what makes someone
good at work open to anyone. `fire.feed_at_quality_0`/`feed_at_quality_100`: how far a Firekeeper's
wood goes, by their work quality. `stock_targets`: what NPCs think is enough in the camp store (`food`/`water` per member in
food or water points; items as counts); they work harder for what is short, and only stock items some
unlocked task or recipe uses.

## `items.json`
Items people carry. `inventory`: how many `slots` everyone has and how many `columns` the window shows.
Each entry in `items`: `name`, `icon`, `description`, `max_stack` (how many fit in one slot), `value`
(trade worth; NPCs compare what they get with what they give, and value an item more when it restores
a need they are short of), and optionally `use` (needs restored at once when used, e.g. `{"food": 30}`),
`use_label` and `use_announce`; `kind` (food, water, material, tool, medicine); `tool`
(`{"breaks": chance per use}`); `counts_as` (items this one is a better version of: a flint spear
counts as a wooden spear wherever work needs or uses one, is used first, and counts toward its stock).
Meals eat items whose `use` restores food, drinks use items restoring
water. `starting_inventory` is what everyone begins with; `camp_store` is what the tribe's shared store
holds at the start (empty by default: the tribe gathers everything itself); `keeping`: work's yield goes
to the worker's pack; NPCs keep `meals`/`drinks` worth of food and water, `own_tools`/`own_materials` of
what their job uses and `medicine`, and share the rest with the store; NPCs below `restock_below_meals`
take food (varied) and water from the store. Meals come only from one's own pack; `trade_offer_life_hours` is how long (in day-night hours)
a trade offer stays open. Add an entry and it appears everywhere.

## `life.json`
Life and death. Everything sits under `base`; `ages.<age key>` (each age reached, in order),
`governments.<key>` (the government in place) and `innovations.<name>` (once discovered) lay overrides
on top: objects merge key by key, numbers, lists and curves are replaced. So a later age can let people
live longer, a discovery can add a new illness or change who is fertile, all without code. Curves are
`[x, value]` points joined by straight lines (flat past the ends); x is usually age in years.
- `work_age` (9): children below it don't work, can't be appointed or volunteer, and play and study
  instead. `politics_age` (14): from it people vote, nominate, stand, hold office, campaign, challenge,
  appoint, research, and count toward innovation points.
- `life_stages`, `need_factors` (children eat and drink less), `aging` (replaces `character.json`
  `aging`).
- `illnesses`: each has `name`, `icon`, `rate_per_year` (by age: how many times a year someone falls ill,
  rolled daily), `work_chance` (by age: the chance per piece of their own job's work), `health_loss_per_day`
  (per day-night cycle; nothing heals while ill), `fatal` (health at 0 while ill is death, not a collapse),
  `cure_chance` (by the patient's age, per healer visit), `weight`, `requires`. One illness at a time.
- `treatment`: `See the healer` (under E): anyone ill, or below `below_health`, may visit a holder of one
  of the `healers` occupations who carries `medicine` in their own pack (best `power` first; `count` used
  up). A visit takes `life_hours`, cures with the illness's `cure_chance` x the healer's factor
  (`healer_factor` by their work quality) x the medicine's power, and gives back `health_gain` health (x the
  same) either way. It counts as the healer's work. `self`: healers may treat themselves. NPC healers keep
  `healer_keeps` medicine in their pack, from the camp store.
- `remains`: the dead lie in camp (with `icon`) and stay in the tribe list until someone lays them to rest
  (`work.json` tasks with `disposes_of_dead`); each body multiplies everyone's illness rates by
  1 + `illness_factor_per_body` + `illness_factor_per_year` x years lying there. What the dead carried
  goes to the camp store.
- `pregnancy`: every `roll_every_days` there is `chance` that one woman (`character.json` genders
  `bears_children`) becomes pregnant, drawn by `fertility` (by age); not while pregnant, ill
  (`not_while_ill`) or within `rest_after_birth_days` of a birth. The father is unknown in the Tribal Age
  (`father`). She can't work for the last `no_work_last_days` of `term_days`; then the child is born.
- `birth`: `genders` (weights), `names` per gender (never reused in a game; numerals once all are used),
  `traits` drawn from `trait_pool`, `attribute_start` for every attribute, and a `description`.
- `childhood.activities`: play and study (under W for children): `group`, `label`, `life_hours`,
  `min_age`, `requires`, `needs_company` (another child to play with), and what each adds: `attributes`
  (points; each whole point raises the attribute) and `skills`. At `work_age` attributes are set.
- `successor`: whom you play on as when your character dies (`children`, `youngest_adult`, `anyone`).

## `time.json`
`office_grace_life_days`: a new office holder can't be persuaded against, challenged or voted out for
this many day-night cycles. `while_busy`: which `actions` (vote, nominate, appoint, persuade, challenge...) someone may take at once,
without breaking off, while busy with one of `during` (work, craft, wait, `care:eat`...); busy NPCs
consider it every `npc_check_days` when a ballot or challenge waits on them, else every
`npc_check_days_otherwise`.

The calendar and how long things take, in game time: `days_per_year` (360) and `seasons`;
`action_hours` (how long each kind of action keeps a player busy); `wait_days` (the waiting options);
how long nominations, election voting and yes/no motions stay open (`nomination_days`, `voting_days`,
`motion_days`); `reform_cooldown_years`; and `innovation_cost_multiplier`, which scales every
innovation's `cost` (6 = the Stone Age takes roughly 35-80 game years). Raise it for a slower climb
through the ages, lower it for a faster one. Innovation points flow in daily (1/360 of each office's
yearly `points` per day) and go into whatever is being researched.

`news_travel_days`: someone resting at home hears that an election or vote opened within this many
days. `start_after_dawn`: where in the day-night cycle the game begins.

`day_night_cycle_days` (1080 = one day and night lasts about 15 real minutes at normal speed), `dawn` and
`dusk` (where day starts and ends in that cycle, 0-1) set the slower clock people live by.

## `character.json`
What a person is made of. Every list here can grow and the engine, NPCs and HUD pick the additions up:
- `attributes` (STR, DEX, CON, INT, WIS, CHA...): `name`, `abbr`, `default`, `description`; `attribute_range`.
- `skills`: `name`, the `attribute` that speeds learning it, `description`; `skill_range`. Skills grow
  while someone holds an occupation that trains them (`training_per_year`); any office trains `office_skill`.
- `needs` (hunger, thirst, energy, warmth): a level from 100 (satisfied) to 0. `decay_per_day` is per
  day-night cycle; `night_factor`, `cold_factor_per_degree` and `warm_gain_per_degree` adjust it, and
  `season_factors` scales how fast it falls by season (Warmth: full in winter, slow in spring and autumn,
  hardly at all in summer); `levels`
  name the bands; below `critical` the need wears down health. Constitution slows decay (`constitution_resists`).
- `health`: loss per critical need (a need's own `health_loss_per_day` overrides it: freezing drains
  faster), regeneration (`regen_factors`: not while working), and `at_zero`: `death` (health at 0 kills,
  whatever the cause: the emptiest need's `death_cause`, or the illness) or `collapse` (the old rule: the
  person rests `collapse_rest_days` and gets back `collapse_restores_needs`, energy and warmth, never food or
  water). Warmth: `season_factors` (a season is a twelfth of a day-night cycle, so winter is x5) and
  `no_fire_factors` (x2.5 more in winter with no fire in camp).
- `care_actions` (eat, drink, sleep, warm up): `life_hours` they take on the day-night cycle (0 = instant;
  sleep is 8), the needs they `restore` (gradually, over that time), `factors` that slow other needs
  meanwhile (sleep slows hunger and thirst), `at_camp` (warmed by the fire if there is one),
  `interruptible` (you can wake or get up early), `requires` (innovations), `needs_amenity` (e.g. `fire`,
  which exists only while the fire has wood: see `work.json`), `consumes` (eats or drinks items from the pack,
  then the camp store, restoring only what was eaten; impossible with nothing there; `max_share` caps one
  sitting, 1.5 = a feast), `scaled_by_quality` with `quality_floor`, and `announce` (chronicle text).
- `new_characters`: how a new game rolls attributes (`attribute_base` 5, plus a dice bonus that is never below 0) and the few starting skills (only those of
  jobs open from the start); `random: false` uses the stats in `players.json` instead.
- `talent`: each point of a skill's attribute above `average` speeds learning it by `per_point`.
- `resting`: how needs change while someone rests at home between other things.
- `life_stages` and `aging` rules (attribute changes from an age, every N years).

## `society.json`
How well the tribe works and how people feel, all 0-100:
- `work_quality`: how well one person does one job or office: weighted attributes (`attribute_share`)
  and skill (`skill_share`), lowered when they are unwell (`condition`). Offices use
  `office_quality_default` unless the office in `governments/*.json` has its own `quality`
  (`attributes`, `skill`).
- `qualities`: society factors (food, water, leadership, safety, fire, care, tools, culture, shelter...). Style
  `supply`: the `sources` (occupations, or `office:Name`) each give `amount` x work quality / 50 against
  `per_person` x members; `variety` is the share that depends on covering every `category` (plants,
  meat, fish). Style `offices`: average quality of every office seat (vacant = 0), weighted by points.
  `weight` sets importance in the overall society score; `requires` delays a quality until an innovation.
  `on_hand` (Food, Water): `share` of the value comes from the points of that `need` the tribe actually
  holds (camp store and packs) against `per_member` each, so it can't read full while people go hungry or
  thirsty, and leaders see that another worker would help (and that one fewer won't hurt while the store
  overflows). Water is fed by Gatherers, the only ones who fetch it (each counts half, since they forage
  too); it needs about 21 water per member on hand to read full. `sick` (Care): `share` of the value is
  100 less `per_sick` for each person ill with nobody seeing to them; healing work worth `cover_supply`
  (about one working Healer) sees to them all. So leaders see the need for a Healer while people lie ill.
- Style `use` (Fire): the quality rises `per_use` each time one of its `uses` happens (`care:warm_up`:
  someone warming up at the fire) and otherwise loses `fall_per_day` (0: it stays the same); it starts at
  `start`. It doesn't care whether the fire merely burns. `sources` only names whose work it rests on.
- `events` (Care): points an event takes out at once (`death`: -10). Not a constant drain: the chunk comes
  back by itself, halving every `quality_events.recover_half_life_life_hours`.
- `satisfaction.meters`: each person's meters (food, work, leaders, society, comfort, safety...). Each
  moves toward a target built from `inputs` plus `bonus` (`holds_office`), closing `rise_per_day` of the
  gap per day-night cycle while below it and `fall_per_day` while above it (both default to
  `drift_per_day`). Inputs: `quality:<name>`, `society`, `need:<name>`, `needs`, `own_work`,
  `meter:<key>` (another meter, e.g. Leaders takes Food, Work, Safety, Comfort and Society), `working`
  (`input_values.working`: doing their own job's work right now / holding a job but idle / no job),
  `fire` (`input_values.fire`: tended / untended / out) and `positions_filled`. `expectations.share`
  of a meter compares life with what the person has grown used to, so decline breeds discontent even in
  a good tribe (`"expectations": false` turns that off, as for Work).
- `satisfaction.meters.<meter>.multipliers`: what makes a meter rise faster or slower. Each has a
  `curve` of `[x, multiplier]` points (a straight line between them, flat past the ends), all multiplied
  together: `tools` (x = how many different tools for their job the person carries; `none_invented` while
  no such tool can be made or exists), `job_variety` (x = share of the occupations of the ages reached
  that are open: relative to the age), `fit` (x = how well they do their job, 0-100; with
  `appointed_only`, only for work a leader appointed them to), `positions_filled` (x = share filled, see
  `satisfaction.positions`), `meters_rising` (x = share of its `meter:` inputs rising) and
  `working_now:<job>` (x = how many are doing that job's work right now; offices as `office:<name>`).
- `qualities.<quality>.sources.<job>.while_working`: that job counts this many times over while its work
  is being done right now (a Warrior on patrol, the Spirit Keeper's ritual). Jobs and offices with work of
  their own count toward qualities only while worked lately (`work.json` `work_counts_life_hours`).
- `satisfaction.meters.food.variety_rates`: the Food meter moves by these points per day-night cycle
  by how many kinds of food the person carries (0, 1, 2, 3, 4+) instead of drifting toward a target.
- `satisfaction.job_loss`: anyone can be dismissed or moved to other work at any time, as often as the
  appointer likes, but it costs. `dismissed` (taken off their work) and `reassigned` (moved straight to
  other work): `hit` drops their meters at once (Work and Leaders by default); `grievance` keeps those
  meters' targets lowered, fading by half every `grievance_half_life_life_hours`; repeated dismissals
  add up to `max_grievance`. `onlookers`: what everyone else feels each time; a kind may set its own
  (`reassigned` sets none: moving people about is a normal part of leading). Unhappy members are
  restless: NPCs whose Leaders meter is low vote and challenge against the leaders, once their patience runs out.
- `satisfaction.job_rank`: being appointed pleases or sours by where the new work stands against the old
  (no work is rank 0). An occupation's rank is `research_step` x the longest chain of researched
  innovations behind it (ages' starting innovations don't count) + `tools` if it has `needs_tools`; an
  office's is `office_per_point` x its points; a `rank` key on the occupation (occupations.json) or office
  (governments/*.json) sets it outright. Per rank moved, `up` adds `hit` points to the person's `meter`
  (Leaders) and leaves `goodwill` (a grievance in reverse, fading the same way); `down` takes `hit` and
  leaves `grievance`. At most `max_points` per appointment. Same rank: nothing. NPC appointers like a
  step up (`npc.json` `appoint.rank_weight` per rank) and avoid a step down (`appoint.demote_weight`).
- `satisfaction.patience`: for each meter listed (`leaders`, `society`), a person's unrest counts the
  cycle-hours that meter has been below `below`, draining `recover` times as fast once it is back up (at
  most `max_life_hours`). Their discontent with it counts toward NPC politics only after
  `grace_life_hours`, reaching full over `build_up_life_hours`. The chronicle warns at `warn_at` of the
  grace used and again when it runs out. Unrest is saved with each person.
- `supply_curve`: how a supply-style quality grows with supply (below 1, the first workers count most).
- `leadership_training`: the office skill (leadership) of anyone holding an office changes each day by
  practice x (`while_working` x how recently they worked the office with `w`, 1 fading to 0, + `tribe_share`
  x the tribe's mood, (average `meter` - `neutral_at`) / `span` between -1 and 1). Other office skills (an
  Elder's lore) grow only while the office is worked. Office work (`work.json` tasks with `offices` or
  `any_office` and no `skill`) also trains the office's skill each time, like any other task.

## `npc.json`
How eager NPCs are. They always look after their bodies; everything else they do far less than the
player, and politics (campaigns, challenges, removal votes, reform) only when a satisfaction meter falls
below `discontent.starts_below`, and only once their patience has run out (`society.json`
`satisfaction.patience`; voting turnout doesn't wait). `turnout` sets how likely an NPC is to bother voting; `nominate_chance`
likewise for nominating; leaders appoint only where a quality the job feeds is below `appoint.gap_below`,
at most every `appoint.days_between` days, and are reluctant (`appoint.reassign_reluctance`) to move
someone who already works, since they resent it; they dismiss only workers below `dismiss.poor_below`.
`politics.blame_exponent`: the top office carries all
the tribe's discontent with its leaders, lesser offices (points / top points) ^ exponent of it. A hungry, thirsty or
exhausted NPC is `distress_damping` less keen on everything except looking after themselves and work
that brings back what they lack; their own hunger makes food work more attractive (`work.own_need_weight`).
Since Work contentment rises only while working, an NPC whose Work meter is below `work.content_wanted` is keener to
do their job's work (`work.content_weight`).
`health`: ill NPCs work and play `work_when_ill` as keenly and go to the healer first (`treat_when_ill`);
below `rest_below` health, `work_when_hurt`. `remains`: how keen NPCs are to lay the dead to rest (one goes
per body, preferring the safer way). `childhood`: how NPC children choose play and study (each child has
its own lasting tastes, which is what makes them grow up different).
`volunteer`: open work is more attractive when the tribe is short of what it provides (`need`) and
less when many already do it (`crowding`, x the share of the tribe in that job), so with no limit per job
people still spread out.

## `contests.json`
`luck`: the role of chance (random factors for speeches, orations and fights, how far listeners lean at
the start, and the size of finds in skill contests); `persuasion.unrest`: listeners unhappy with the leaders (and a holder doing the office badly) start a campaign more persuaded, the holder's rallies work less on unhappy listeners and never push anyone below their starting level, and `persuasion.canvass.min_gain` is the least a talk moves someone; `persuasion.resistance.min`/`max` bound how open
a listener can be.

Ways to take an office other than an election. Each office in `governments/*.json` opts in with
`"contested_by": {"persuasion": true, "challenge": ["oration", "fight", "skill"]}` (`skill` = a contest
in the defender's own line of work: an occupation's skill, or the skill of the office they hold, so an
Elder (lore) may answer with a storytelling contest). In the tribe: Clan
Leader allows persuasion, oration, ritual fight and skill contests; Elder persuasion, oration and skill
contests; Spirit Keeper persuasion and oration.
- `persuasion`: a campaign of `life_hours` (day-night hours). Every member gets a persuasion meter
  (0-100) for its duration, starting at `start_meter` (+`start_per_charisma` per charisma point above 5).
  It rises slowly on its own (`passive_per_day`), jumps when the campaigner speaks to someone
  (`canvass`), and falls when the threatened holder does (`rally`). Wise people and fellow office
  holders are harder to sway (`resistance`). At the end the average meter ± `randomness` must reach
  `success_at`.
- `challenge.chosen_by`: `defender` (the one challenged picks the contest within `answer_life_hours`, or
  the one they are strongest at is picked for them) or `challenger`. Each kind's `practice` is the skill
  both contestants gain, win or lose (oration trains persuasion).
- `challenge.during_contest`: what the two contestants may still do, by style. `locked` holds them
  until it ends (the ritual fight); `may` lists action types, `care:<kind>` for one care action, and
  `speak`: in an audience contest both sides speak to one listener at a time (`speak.life_hours` each;
  the listener moves about `speak.gain` x the speaker's contest strength, the challenger drawing them
  in, the defender pulling them back). Short waits are always allowed.
- `challenge.kinds`: each has a `style`: `audience` (both speak; listeners' meters swing), `duel`
  (momentum swings until someone yields at `yield_at`; `injury` hurts but never kills), `best` (largest
  single find, e.g. biggest animal in `unit` kg) or `total` (most found, e.g. baskets of food).
  `attributes` and `skill` give each side's power; `defender_standing` gives the holder an edge.
- Cooldowns: a challenger waits `cooldown_life_days` day-night cycles before another contest; a holder
  can't be contested again for `defender_rest_life_days`.

The winner takes the office; the holder loses it; the winner gives up any other office if they may hold
only one; an election for a seat that is no longer vacant is called off.

## `occupations.json`
The work people do (`max_per_player` occupations each). Occupations belong to the society, not a
government, so they last through reforms. With `office_is_work: true`, an office is its holder's work:
taking one gives up any occupation, and office holders may not take or be appointed to one. A leader
may move someone from work they themselves control to other work (NPC leaders do so only when the
tribe gains more than it loses, weighing each quality's `weight`).

| Field | Meaning |
|---|---|
| `icon`, `description` | For display |
| `seats` | Optional cap on how many may hold it; leave it out (the default) for no limit |
| `appointed_by` | Offices, from any government, whose holders appoint to it and dismiss from it |
| `volunteer` | Members may take it up themselves (also true when the government has none of the appointing offices) |
| `attributes`, `skill` | What makes someone good at it; the skill it trains |
| `points` | Innovation points a year per holder |
| `requires`, `interfaces` | Innovations needed; role interfaces it grants |
| `needs_tools` | The work can't be done without one of these items (a Hunter needs a spear). Anyone may still be appointed once the research is done: they wait for one, then take it from the store (`work.json` `auto_take_tools`) |
| `provides` | Amenities the group has while anyone holds it (`fire` from the Firekeeper, while the fire has wood) |
| `also_trains` | Other skills the work improves, as a share of the main skill's practice (only while the job is worked) |

There is no waiting after a dismissal and no limit per job: a leader may make everyone a Warrior and
everyone a Gatherer again the next moment. The cost is contentment (`society.json` `job_loss`).

Appointment can take someone from volunteer work (a Gatherer becomes a Hunter) but not from work they
were appointed to; they must be released first.

## `world.json`
`climate`: each season's average temperature, the day-night swing, and the `comfort` temperature.
Cold air drains warmth faster; warm air restores it. `fire`: the temperature by the communal fire (plus a little per point of the
Firekeeper's skill). People sleeping, eating, resting or warming up at camp feel the fire, but only up to `resting_warmth` degrees above comfort (0: it keeps the cold off and no more; to get warm, warm up); without a
Firekeeper there is no fire, and cold nights drain warmth with nothing to restore it.

## `settings.json`
Not game rules but how you play: `npc_detail` (`full` or `summary`), `seed`,
`real_seconds_per_game_year` (300 = five minutes per game year at normal speed), `playback_speed` and
the `playback_speeds` F5 cycles through.

## `ages.json`
Ordered list of ages. An age is reached when every innovation in its `requires` is discovered (and all
earlier ages are reached). The first age lists `starting_innovations`. An age's `requires` must come
from earlier ages, otherwise it could never be reached.

## `innovations/<age>.json`
One file per age; `age` must match a key in `ages.json`.

| Field | Meaning |
|---|---|
| `name` | Unique name |
| `interface` | Which role interface can research it (`leadership`, `legislative`, `judicial`, `military`, `intelligence`, `economic`, `infrastructure`, `religious`, `civic_representation`) |
| `cost` | Innovation points needed |
| `prerequisites` | Innovations that must be discovered first (same age or earlier) |
| `description` | Shown in the innovation list |
| `icon` | Optional; defaults to the interface's icon |

## `governments/<key>.json`
One government type per file.

| Field | Meaning |
|---|---|
| `key`, `name`, `description` | Identity |
| `age` | Age in which this government becomes available |
| `requires` | Extra innovations needed beyond reaching the age |
| `reformed_by` | How this government can be changed into another: `appointment` (the `appointer` decrees it alone; if that seat is empty, members vote), `tribe_vote` or `council_vote` (a yes/no vote anyone in the electorate can call) |
| `max_offices_per_player` | How many offices one player may hold at once |
| `member_interfaces` | Interfaces every member gets, office or not |
| `member_points` | Innovation points each member adds per year |
| `carry_over` | `{"Old Office": "New Office"}` – who keeps a position when the society reforms into this government. Offices with the same name carry over automatically. Keys may come from any government |
| `offices` | See below |
| `statuses` | See below |

### Offices
| Field | Meaning |
|---|---|
| `seats` | Number of holders |
| `requires` | Innovations needed before the office exists |
| `interfaces` | Role interfaces the holder can open |
| `points` | Innovation points per holder per year |
| `selected_by` | How holders are chosen (methods below) |
| `removed_by` | How holders are removed (`tribe_vote`, `council_vote`, `appointment`, or `none`) |

### Statuses
Standing in society rather than a job: unlimited holders, no seats. `granted_by` / `revoked_by` use the
same methods as offices. `effects` may include `loses_office`, `cannot_hold_office`, `cannot_vote`,
`no_member_interfaces`.

### Selection methods
| Method | Extra fields | Behaviour |
|---|---|---|
| `tribe_vote` | `voting_system`, `nomination_days`, `voting_days` | Any member may nominate; every member votes |
| `council_vote` | `council`, `fallback`, `voting_system`, `nomination_days`, `voting_days` | Holders of `council` nominate and vote. If the council is empty, `fallback` is used instead |
| `appointment` | `appointer` | The holder of `appointer` chooses. Appointing to a full one-seat office replaces the holder |
| `divine_sign` | `chance` | At the start of each year there is a `chance` (0–1) that an eligible member is chosen at random |
| `seniority` | – | The oldest eligible member takes the seat |

Elections take nominations for `nomination_days` (default from `time.json`), then vote for
`voting_days`; voting ends early once everyone has voted, and anyone who hasn't voted by the deadline
abstains. When used for removal or for granting a status, `tribe_vote` and `council_vote` become a
yes/no motion that any voter may call; it passes with yes votes from a majority of the electorate
(the person in question does not vote).

Nobody stands in two elections at once. When voting begins, each candidate's vote is cast for
themselves. A nominee may decline (and is not nominated again for that election), or withdraw during
voting: votes for them are void and those voters may vote again; if one candidate is left they win.

`voting_system` is `first_past_the_post` (default), `ranked_choice` or `two_round_runoff`.

### Reforming
A society may adopt any government whose age it has reached and whose `requires` it has discovered,
but never one from an older age than its current government. After a reform, another cannot be
proposed for `reform_cooldown_years` (in `time.json`).

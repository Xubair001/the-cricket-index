# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Three independently-runnable components, each with its own venv-relative or npm-relative commands.

**Setup** (once):
```bash
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
cd frontend && npm install
```

**Run** (each in its own terminal, in this order):
```bash
temporal server start-dev                                              # Web UI: localhost:8233
cd ingestion && source ../venv/bin/activate && python worker.py
cd backend && source ../venv/bin/activate && python -m uvicorn main:app --port 8001
cd frontend && npm run dev                                             # localhost:5173
```

**Trigger ingestion** (worker must be running):
```bash
cd ingestion && python starter.py tests   # or: odis, t20is, psl
cd ingestion && python starter.py icc      # ICC rankings
cd ingestion && python starter.py fixtures # ICC schedule: results + upcoming
cd ingestion && python starter.py daily    # both of the above (what the schedule runs)
cd ingestion && python starter.py enrich   # cricinfo crosswalk + Wikidata bios/names/photos
```
Re-running match ingestion is cheap — each match is content-hashed; unchanged
matches are skipped, not re-parsed.

**Register the daily ICC sync** (rankings + fixtures; re-running updates it):
```bash
cd ingestion && python schedule.py        # --delete to remove
```

**Frontend lint/build** (this is what CI runs — no test suite exists in this repo):
```bash
cd frontend && npm run lint && npm run build
```

**Backend sanity check** (this is what CI runs in lieu of tests):
```bash
cd backend && python -m compileall -q . && python -c "from main import app"
```

**Git workflow**: see `CONTRIBUTING.md` — never commit directly to `dev`/`main`; branch from `dev` as `feature/*`, `fix/*`, or `chore/*`.

## Architecture

### Three components, one SQLite file

`ingestion/` (writes) and `backend/` (reads) both talk to the same `cricket.db`
at the repo root, independently. Neither imports from the other. Both resolve
its path the same way — via a `PROJECT_ROOT` computed from `__file__`
(`ingestion/shared.py`, `backend/app/database.py`) — so everything works
regardless of the process's cwd or the repo's absolute location. Follow this
convention for any new script; don't hardcode paths.

### Gender separation is a schema property, not a query filter

Men's and women's cricket share no identity below the API layer. `teams` are
keyed by `(name, gender, team_type)` — men's and women's "India" are
different rows with different `team_id`s. `competitions` are keyed by
`(key, gender)` — "Test" has a separate row per gender. `players.gender` is
set once, from the gender of the first match they're seen in (a real person
never plays both). Every list/browse endpoint (`dashboard`, `rankings`,
`teams`, `players` search, `matches` list) takes a required `gender` query
param; detail endpoints (`teams/{team_id}`, `players/{identifier}`,
`matches/{match_id}`) don't need one because the ID already disambiguates.

The frontend mirrors this with a `/:gender/*` path prefix (`men`/`women`,
mapped to the API's `male`/`female` via `frontend/src/gender/useGender.ts`).
`Layout.tsx`'s gender switcher deliberately drops to the current section's
*list* page rather than trying to preserve a specific team/player/match ID
when switching — an ID from one gender is meaningless in the other's context.

### International vs franchise is the same kind of split as gender

Adding the PSL needed no migration — `teams.team_type` and `competitions.type`
already carried the vocabulary. The rule the code enforces is that the two
never merge into one number:
- `teams` are keyed by `(name, gender, team_type)`, and `GET /api/teams` takes
  an optional `team_type` so a list is national sides *or* franchises, never
  both interleaved. The frontend Teams page defaults to `international`.
- Rankings are confined to one competition type at a time
  (`queries._ranking_scope`). An unscoped request is **not** "everything" — it
  falls back to `international`, and franchise cricket must be asked for via
  `competition=psl` or `competition_type=domestic_league`. Blending a player's
  Test/ODI/T20I runs with their PSL runs would produce a figure no cricket
  source publishes.
- `team_type` is derived from the competition
  (`shared.TEAM_TYPE_BY_COMPETITION_TYPE`), **not** from the source data:
  Cricsheet's own `info.team_type` says `"club"` for franchise leagues, which
  isn't in the schema's CHECK vocabulary. That raw value is still stored on
  `matches.team_type` as a display-only column.

Competition keys and types are validated against the `competitions` table
(`app/validation.py`), not a regex, so ingesting a new league stays a data
change rather than an API code change.

### Ingestion: Temporal workflow, not child-workflow-per-match

`CricsheetIngestionWorkflow` (`ingestion/ingestion_workflow.py`) downloads a
Cricsheet archive, then fans out to concurrent **activities** (not child
workflows) for each match — ingesting one match is a single unit of work
(hash-check → parse → upsert), not a multi-step process, so activities are
the right granularity. It processes matches in batches of
`BATCH_SIZE_PER_GENERATION` and calls `workflow.continue_as_new` between
batches so history stays bounded across the ~9,000+ match archives.

Idempotency: `ingest_match` (`activities.py`) SHA-256-hashes each match's raw
JSON and compares against the stored `matches.content_hash` before doing any
parsing or writes — an unchanged match is a no-op. This is also how a
periodic re-sync (re-running `starter.py` against a refreshed Cricsheet
archive) would stay cheap.

### No ball-by-ball data is stored — only derived aggregates

`ingestion/parsing.py` walks each match's `innings/overs/deliveries`
structure purely to accumulate per-player totals (`PlayerMatchStat`), then
discards the balls. The scoring rules encoded there are real cricket domain
logic, not incidental:
- `BOWLER_CREDITED_KINDS` / `NOT_OUT_KINDS` — which wicket kinds count against
  a bowler's figures, and which don't count as a batting dismissal (e.g.
  "retired hurt" isn't out; "run out" isn't the bowler's wicket).
- Wides don't count as a ball faced; wides and no-balls don't count as a
  legal ball bowled but do count as runs conceded; byes/leg-byes count as a
  legal ball but never count against the bowler.
- `dismissals` is a count, not a boolean — a Test can have two innings per
  side, so a player can be dismissed twice in one match. This matters for
  batting average (`runs / dismissals`), computed in
  `backend/app/queries.py`.

Don't "simplify" any of this without checking real figures against known
career stats first — these rules were reverse-engineered from actual
Cricsheet delivery records, not assumed.

### Three data sources, kept visibly separate

Cricsheet is still the only source of match data, and it is the reason every
derived figure exists — the per-player aggregates come from its ball-by-ball
records. Two others feed non-match facts, and neither is allowed to blur into
the first:

- **ICC rankings** (`icc_player_rankings`, `icc_team_rankings`) come from
  ICC's own JSON feed — the one their site consumes. They live behind
  `/api/icc/*` and a separate "ICC" nav section, deliberately not merged with
  `/api/rankings`, which this project *computes* from ball-by-ball data.
  Conflating a derived figure with an official rating is the one mistake the
  split exists to prevent.
  - `IccRankingsWorkflow` runs daily via a Temporal Schedule (`schedule.py`).
    ICC republishes roughly weekly, but `rank_date` is part of the key, so a
    daily run that finds nothing new just rewrites the same snapshot.
  - ICC marks ties with `'='` in the position column; `parse_icc_rankings`
    carries the previous position forward. Treating `'='` as unparseable
    silently drops every tied player (6 of the top 100 Test batters).
    Because ties share a position, `player_name` is part of the primary key
    **and must stay `primary_key=True` on the SQLAlchemy model** — omit it
    there and tied rows collapse into one ORM identity, which the session then
    emits twice.
  - ICC names people "Travis Head" where Cricsheet says "TM Head", and
    publishes no ID we share. `enrichment.resolve_player` matches on
    (surname, first initial) with country as a tiebreak, and returns None
    whenever more than one player fits — "Moeen Ali" will not be guessed at
    between `M Ali` and `MM Ali`. Unlinked entries still display; they just
    aren't links. ~72% link cleanly.

- **ICC fixtures** (`fixtures`) come from the same ICC feed's schedule
  endpoint. Deliberately NOT merged into `matches`: `matches` holds Cricsheet
  records with per-player figures derived from ball-by-ball, whereas a fixture
  is a calendar entry and an upcoming one has no result at all. Merging would
  put resultless rows into the table every aggregate query reads.
  - The feed paginates on **`page_number`**, not `page`. `page` is accepted and
    silently ignored, so a loop using it returns page one every time — which
    looks exactly like a working paginated fetch that collected 24 copies of
    the same 500 rows. It also needs `from_date`/`to_date` (YYYYMMDD); without
    them no upcoming fixtures come back at all.
  - Each fixture is SHA-256-hashed from its raw feed object, the same
    idempotency contract `ingest_match` uses, so a daily run rewrites only
    genuinely-changed rows (a scoreline landing, a start time moving).
  - Dates arrive as US `M/D/YYYY` and are converted to ISO on ingest. Gender
    comes from the `- m` / `- w` suffix on `comp_type`.
  - `queries.list_fixtures`'s "results" window is date-bounded, not just
    `is_upcoming = 0`: a **cancelled future** fixture carries `is_upcoming=0`
    and `match_result='Match Cancelled'`, so without the bound it sorts to the
    top of "results" as a match two months away that never happened.

- **Wikidata** fills player bio fields, joined on `players.cricinfo_id`. That
  column is populated from Cricsheet's own people register
  (`https://cricsheet.org/register/people.csv`, `key_cricinfo`, 99.8%
  coverage), so the join is exact and involves no name matching at all.
  Run via `python starter.py enrich`; not scheduled, since bios rarely change.
  - The public SPARQL endpoint burst-throttles with 429 and no `Retry-After`.
    `_wikidata_get` backs off exponentially, and `enrich_from_wikidata` **fails
    the activity** when more than half the batches fail — a throttled run
    otherwise returns "0 matched" and is indistinguishable from Wikidata
    genuinely knowing nobody.

### Names: `JE Root` is correct, `Joe Root` is for reading

Cricsheet's `players.name` uses the standard scorecard convention — every
initial, then surname (`JE Root` = Joseph Edward Root). That is what Wisden,
CricketArchive and ESPNcricinfo's own scorecard guidelines use; it is **not**
stale or wrong data, and it is not to be "fixed" by replacing the source.

`players.display_name` holds the Wikidata label alongside it, and the API
returns the preferred form as `name` with the scorecard form as
`scorecard_name`. Coverage is ~4,100 of 9,442, so the fallback is load-bearing:
a player Wikidata doesn't know keeps their scorecard name rather than getting a
fabricated full name.

**Preferring the Wikidata label unconditionally is wrong**, and `app/names.py`
owns the rule that replaced it. Wikidata stores a *formal* name, so where the
scorecard form is already natural the label makes it less recognisable, not
more — `Babar Azam` → `Mohammad Babar Azam`, `Imran Khan` →
`Mohammad Imran Khan`, `Liton Das` → `Litton Das`. The label is therefore used
only when the scorecard name needs expanding, i.e. its first token is an
initials cluster (`JE Root` → `Joe Root`, `HMRKB Herath` → `Rangana Herath`).
That pattern allows up to eight letters: Sri Lankan initials run long
(`CBRLS Kumara`, `PADLR Sandakan`), and a narrower bound leaves them displayed
as initials. 3,103 of the 4,119 labelled players take the label; of the 1,016
that keep their scorecard name, 102 would otherwise have been renamed wrongly.
Known limit: players best known *by* their initials (`MS Dhoni`) get expanded,
because nothing distinguishes them from `JE Root` — the sourced label wins over
a guess.

Search matches **both** columns. Matching only `players.name` meant a player
could not be found by the name the product itself displayed: "Joe Root"
returned nothing while "JE Root" worked.

`players.image_url` is a Wikimedia Commons photo (P18), for ~1,000 players.
Two non-obvious details:
- P18 points at the **original** upload — Joe Root's is 2568x1794 / 4.8 MB,
  enough to time out a page load. The stored URL is a thumbnail.
- Wikimedia no longer renders arbitrary widths; an unlisted size returns
  `400 Use thumbnail sizes listed on ...`. Probing the handler, the sizes it
  serves are **120, 250, 500, 960, 1280** — `enrichment.COMMONS_ALLOWED_THUMB_WIDTHS`.
  The thumb path is computed from the MD5 of the underscored filename
  (`/thumb/<md5[0]>/<md5[:2]>/<file>/250px-<file>`) rather than costing an API
  round trip per player.

### Playing status is derived, and "retired" is never guessed

`queries.player_status` returns `active` / `inactive` / `retired`. The word
**retired only appears when a source says so** — Wikidata's P2032 or a date of
death. It is never inferred from a gap in appearances, because a gap covers
retirement, injury, being dropped, and cricket this dataset doesn't cover, and
nothing here distinguishes them. Those render as "Last played 2019".

Be aware how thin the sourced signal is: **P2032 exists for 21 of ~31,700
cricketers in Wikidata**, so exactly 2 players in this database have a
retirement date (plus 41 with a date of death). MS Dhoni shows as *inactive*,
not retired. That is correct behaviour, not a bug to "fix" by lowering the bar.

`active` is measured against the newest match **in the dataset**, not today —
anchoring to now would silently reclassify every current player the moment the
Cricsheet archive went stale.

### Forward-looking schema, not yet populated

Two things exist in `schema.sql` for a future phase and currently do
nothing — don't treat them as dead code:
- `matches.data_granularity` (`'full'` vs `'result_only'`) anticipates a
  coarser-grained future data source (e.g. pre-2001 results without
  per-player breakdowns). Everything ingested today is `'full'`.
- `player_career_totals` would hold aggregate-only figures for players whose
  stats can't be decomposed per-match. Unused until that source exists.
- `players.date_of_birth` / `birth_place` / `nationality` / `cricinfo_id` /
  `bio_source` are nullable and currently always `null`. The API and UI both
  render this as "Not available" — never infer or guess a value for these.

### A "four" is a boundary, not four runs off the bat

`ingestion/parsing.py` counts `fours`/`sixes` only when Cricsheet does NOT set
`runs.non_boundary`. That flag exists precisely to mark all-run fours and
overthrow-assisted ones, and ignoring it overstates boundaries. Found by
validating against a published source rather than by reading the code: Joe Root
came out at 1,523 Test fours against ESPNcricinfo's 1,515. After the fix he
matches exactly, along with matches (166), runs (14,114) and sixes (46).

`runs_scored` is unaffected — a non-boundary four is still four runs. What
changes is `fours`, `sixes` and anything derived from them, notably the batting
explorer's boundary %.

### Fixing the parser does nothing until PARSER_VERSION is bumped

Idempotency is a SHA-256 of the raw match JSON, and Cricsheet's bytes do not
change when our parser does. `shared.PARSER_VERSION` is mixed into that hash for
exactly this reason: without it, a parser fix plus a re-run skips all 10,040
matches and **reports success**. This is the trap §5 names, and it is not
hypothetical — the first attempt at the boundary fix returned "357 unchanged
(skipped)".

Two things are needed to land a parser change: bump `PARSER_VERSION`, **and
restart the Temporal worker** — it holds the old module in memory and will
happily keep using it.

### Venue normalisation: comma-collapse is safe, substring merging is not

`backend/app/venues.py` takes 593 raw venue strings to ~400 grounds. Three rules,
and the reasoning behind the last two is the load-bearing part:

- **Comma-collapse** (automatic, safe): the text before the first comma is the
  ground. "Arnos Vale Ground, Kingstown, St Vincent" -> "Arnos Vale Ground".
- **Curated aliases only.** The tempting rule — merge when one name contains the
  other — is wrong invisibly. Dubai has "ICC Academy" *and* "ICC Academy Ground
  No 2" (different pitches); Pakistan has "Arbab Niaz Stadium" in Peshawar and
  "Niaz Stadium" in Hyderabad, 1,000km apart. Substring similarity is used only
  to **report** candidates for review, never to merge.
- **City qualifies only the names that actually collide** (`CITY_QUALIFIED`).
  "County Ground" is EIGHT English grounds; "National Stadium" is Karachi *and*
  Hamilton, Bermuda. But city cannot be part of the key generally, because the
  column is itself inconsistent — the same ground appears under Bridgetown and
  Barbados, Kingston and Jamaica, Port Elizabeth and Gqeberha, Dhaka and Mirpur.
  Of 28 same-name-different-city cases, most are one ground written two ways.

### The Performance Index pools percentiles by discipline, or it rates discipline

`backend/app/analytics/performance_index.py`. Two decisions that look like
detail and are correctness:

- **Percentiles are pooled within (scope x discipline).** Measured over this
  dataset a bowler's mean opposition-adjusted impact is **1.08 par units against
  a batter's 0.64** — a 69% gap that is an artefact of the impact model (a
  four-wicket haul converts to ~120 runs-equivalent where a good innings is 45),
  not a statement about quality. Pooled together the first cut returned eleven
  bowlers in a top twelve. The form board never exposed this because form is
  self-relative and the offset cancels; a rating compares players to each other,
  so it does not.
- **"Recent performance" is the absolute standard of the window, not the form
  delta.** §14 words that component as "recent window versus the player's own
  baseline", which is literally the form figure — but scored that way the Index
  inherits form's self-relativity, a journeyman improving from poor to ordinary
  out-rates a great player playing normally, and the Index becomes a reweighted
  copy of a board we already ship (violating §15's requirement that the three
  rankings stay distinct). The deviation is deliberate and documented in the
  module.

Consistency is **downside deviation**, not variance: plain variance punishes a
match-winning 150 as hard as a duck, so the most "consistent" player is the
reliably mediocre one. Only shortfalls below par count.

Absent components (role, situation, availability — 25% of §14's weighting) are
dropped and the rest renormalised, never scored as zero. The API returns every
component with both its specified and applied weight, and the UI states the
shortfall.

### A volume floor does not keep specialists out of the wrong leaderboard

The explorers (`backend/app/analytics/explorer.py`) gate on minimum balls, and
that is **not** sufficient to keep a batter off a bowling board. Over a long
career a top-order batter's occasional overs clear any sane minimum: Kohli has
bowled 989 balls, Tendulkar 2,812, Root 8,120 — all past a 300-ball gate. The
mirror held too, with Muralitharan, Bumrah and Anderson all clearing a 200-ball
batting gate.

`discipline()` infers a crude role from `balls_bowled / (balls_faced +
balls_bowled)`, which §5 sanctions explicitly (it is *wicketkeeper* and *opener*
that are unreachable, not the batter/bowler/all-rounder split). `ELIGIBLE` maps
it: batting admits batters and all-rounders, bowling admits bowlers and
all-rounders, all-round admits only all-rounders.

The two cuts (0.25 / 0.78) are read off the observed distribution over the 1,782
men's internationals with 20+ matches, and classify every well-known player
correctly — Kohli .03, Root .19 (batters); Maxwell .50, Shakib .62, Afridi .76
(all-rounders); Ashwin .83, Bumrah .94, Muralitharan .96 (bowlers). The middle
band is deliberately wide: excluding a genuine all-rounder from a list they
belong on is the expensive error; admitting a marginal one is cheap.

The role is **inferred and labelled as such on every row**. It is never a
sourced fact about a player.

### Opposition strength is fitted, and two obvious versions of it are wrong

`backend/app/analytics/opposition.py` scales every performance by how hard the
side it came against actually is. Without it the form board ranked by *weakness*
of opposition — players whose recent cricket was against Norway, Portugal and
Malta outranked Virat Kohli.

Two measures were tried and rejected **against data**, so don't reach for them:

- **Mean impact conceded to opponents.** Ranked Indonesia the strongest side and
  Pakistan among the weakest. Impact is not zero-sum within a match and a
  competition slice is too coarse a control: associate matches are low-scoring
  for *both* sides, so a side that only plays them looks miserly. What was
  measured was the run-scoring environment, not the side.
- **Opponents' raw share of match impact.** Cancels the environment (it is a
  ratio within one match) and fixed the above, but still put UAE, Uganda and
  Japan above Australia — a share measures dominance over *whoever you played*.

What works is fitting those shares with **Bradley-Terry**, which makes strength
transitive, and referencing the fitted powers against the opposition in an
**average match** rather than the average team. That last part matters: there
are ~110 men's international sides and most play rarely, so a team-count
reference puts "par opposition" at roughly Malta and pins every Test nation to
the multiplier clamp. Validated against ICC team ratings at Spearman ρ ≈ +0.81
to +0.83 across all three formats — ICC is the *check*, never an input (it ranks
only ~10-20 sides, is a current snapshot against 25 years of data, and §6 keeps
official ratings out of derived figures).

Conventional figures — average, strike rate, economy — are deliberately **not**
adjusted, because they have to match what a scorecard source publishes. Only
this project's own impact measures carry the adjustment.

**Fitted per era, referenced against a stable core.** Team strength moves over 25
years: on own-share of match output Bangladesh runs 0.387 in the early 2000s to
0.505 in the mid-2020s, Australia 0.570 down to 0.488 — Bangladesh's swing alone
is wider than the gap between many pairs of sides, so one career rating credits a
2003 century against them exactly as much as a 2025 one. `opposition.multiplier`
therefore takes the match date (§14's "opponent standing at the time").

The era reference is taken over a **stable core** of sides present in most eras,
not over each era's whole population, and this is load-bearing. In 2019 the ICC
granted T20I status to every member, so the 2020s pool holds dozens of associates
that played no international cricket in the 2000s; referenced against its own
era's average, *every* established side inflated in the 2020s and Australia came
out harder to face in 2020 than in 2000. Anchored to the core, the curves match
cricket history instead — Australia 1.240 → 1.038, Bangladesh 0.796 → 0.964,
Sri Lanka declining after the Murali era, Zimbabwe dipping in 2005.

### Form boards rank on par units, not on the percentage

`FormLeader.rank_score` is `delta_absolute × confidence`, not
`delta_ratio × confidence`. A percentage is a ratio against the player's own
baseline, so a player who was dreadful and is now merely below average posts a
huge one — Sharvin Muniandy reached the in-form board at +97% while producing
**0.70 par units**, below what an average appearance is worth. Every leaderboard
row carries `recent_mean` so the absolute standard is visible beside the change.

### Rankings are computed in Python, not SQL, after a GROUP BY

`backend/app/queries.py`'s `_batting_aggregate_rows` / `_bowling_aggregate_rows`
run one SQL `GROUP BY` per call, then compute averages/strike-rate/economy
and sort in Python across the full result set before slicing for pagination.

They group by `player_identifier`, **not** `player_name` — 78 names in this
dataset map to more than one real person (two distinct "SR Taylor"s, two
"Shahid Afridi"s), and grouping by name silently summed their careers into a
single ranking row. `max(player_name)` just picks a stable display spelling.
Both helpers also take an optional `team_id`, which is what makes a team page
show a player's figures *for that team* rather than their gender-wide career
totals — without it a franchise page credits Babar Azam with his Test runs.
This is intentional (average requires a divide-by-zero guard that's awkward
in SQLite SQL) but means an unfiltered all-players query is O(total players)
in Python — acceptable at this dataset's size (~9,300 players), worth
revisiting with a materialized summary table if that ever changes.

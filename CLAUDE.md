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
cd backend && source ../venv/bin/activate && python -m uvicorn main:app --port 8001 --env-file ../.env
cd frontend && npm run dev                                             # localhost:5173
```

**Which database** is chosen by `DATABASE_URL` in `.env` (gitignored). With no
`.env`, or no such variable, everything uses the local `cricket.db` exactly as
before - so `--env-file` is harmless when the file is absent. A Neon connection
string goes in as-is; `postgres://` and `postgresql://` are both normalised to
the psycopg driver, because managed providers hand out the short form and
SQLAlchemy 2 rejects it.

**Trigger ingestion** (worker must be running):
```bash
cd ingestion && python starter.py tests   # or: odis, t20is, psl
cd ingestion && python starter.py icc      # ICC rankings
cd ingestion && python starter.py fixtures # ICC schedule: results + upcoming
cd ingestion && python starter.py daily    # both of the above (what the schedule runs)
cd ingestion && python starter.py enrich   # cricinfo crosswalk + Wikidata bios/names/photos
```
Re-running match ingestion is cheap - each match is content-hashed; unchanged
matches are skipped, not re-parsed.

**Migrate to Postgres** (idempotent; safe to re-run, resumes where it stopped):
```bash
cd backend && python -m scripts.migrate_to_postgres --url "$DATABASE_URL" --create-schema
cd backend && python -m scripts.migrate_to_postgres --url "$DATABASE_URL" --skip deliveries
cd backend && python -m scripts.migrate_to_postgres --url "$DATABASE_URL" --verify-only
```
Use the DIRECT endpoint rather than the pooled one for the load: it is one long
`COPY` per chunk, which is what a transaction pooler is not for.

**Register the daily ICC sync** (rankings + fixtures; re-running updates it):
```bash
cd ingestion && python schedule.py        # --delete to remove
```

**Keep it running** (what makes the schedule actually daily):
```bash
./deploy/install-systemd.sh              # --uninstall to remove
```
The 06:00 schedule only fires while the Temporal server AND the worker are both
up. Started by hand they die with the terminal session, and a missed run leaves
no error anywhere - the schedule fired on 13 and 14 Aug 2026 and silently
skipped the 15th and 16th for exactly that reason. The units set
`Restart=always`, and the worker `Requires=` the server so it restarts with it.

Note `loginctl enable-linger` is still needed for the units to survive logout;
the installer prints the command rather than running it, since it changes the
login session rather than the repo.

**Frontend lint/build** (this is what CI runs - no test suite exists in this repo):
```bash
cd frontend && npm run lint && npm run build
```

**Backend sanity check** (this is what CI runs in lieu of tests):
```bash
cd backend && python -m compileall -q . && python -c "from main import app"
```

**Git workflow**: see `CONTRIBUTING.md` - never commit directly to `dev`/`main`; branch from `dev` as `feature/*`, `fix/*`, or `chore/*`.

## Writing style

**Never use an em dash (U+2014).** Not in UI copy, not in code comments, not
in docstrings, not in this file, not in commit messages. Use a plain hyphen
`-`, or restructure the sentence. The repo was swept clean of 318 of them; do
not reintroduce one.

The same applies to the em dash used as a "no value" marker in a table cell:
`format.ts`'s `rate`/`percent`/`count` helpers default to `'-'`, and any new
placeholder should match.

The character is written here as a code point rather than literally, so that
the repo contains none at all and the check below is exact rather than always
matching this paragraph:

```bash
# -I skips binaries: the Cricsheet archives under data/ contain the byte
# sequence and are not ours to edit.
grep -rnI "$(printf '\u2014')" . --exclude-dir=node_modules --exclude-dir=venv \
  --exclude-dir=.git --exclude-dir=dist --exclude-dir=__pycache__ --exclude-dir=data --exclude='*.log'
```

## Architecture

### Three components, one SQLite file

`ingestion/` (writes) and `backend/` (reads) both talk to the same `cricket.db`
at the repo root, independently. Neither imports from the other. Both resolve
its path the same way - via a `PROJECT_ROOT` computed from `__file__`
(`ingestion/shared.py`, `backend/app/database.py`) - so everything works
regardless of the process's cwd or the repo's absolute location. Follow this
convention for any new script; don't hardcode paths.

### Gender separation is a schema property, not a query filter

Men's and women's cricket share no identity below the API layer. `teams` are
keyed by `(name, gender, team_type)` - men's and women's "India" are
different rows with different `team_id`s. `competitions` are keyed by
`(key, gender)` - "Test" has a separate row per gender. `players.gender` is
set once, from the gender of the first match they're seen in (a real person
never plays both). Every list/browse endpoint (`dashboard`, `rankings`,
`teams`, `players` search, `matches` list) takes a required `gender` query
param; detail endpoints (`teams/{team_id}`, `players/{identifier}`,
`matches/{match_id}`) don't need one because the ID already disambiguates.

The frontend mirrors this with a `/:gender/*` path prefix (`men`/`women`,
mapped to the API's `male`/`female` via `frontend/src/gender/useGender.ts`).
`Layout.tsx`'s gender switcher deliberately drops to the current section's
*list* page rather than trying to preserve a specific team/player/match ID
when switching - an ID from one gender is meaningless in the other's context.

### International vs franchise is the same kind of split as gender

Adding the PSL needed no migration - `teams.team_type` and `competitions.type`
already carried the vocabulary. The rule the code enforces is that the two
never merge into one number:
- `teams` are keyed by `(name, gender, team_type)`, and `GET /api/teams` takes
  an optional `team_type` so a list is national sides *or* franchises, never
  both interleaved. The frontend Teams page defaults to `international`.
- Rankings are confined to one competition type at a time
  (`queries._ranking_scope`). An unscoped request is **not** "everything" - it
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
workflows) for each match - ingesting one match is a single unit of work
(hash-check → parse → upsert), not a multi-step process, so activities are
the right granularity. It processes matches in batches of
`BATCH_SIZE_PER_GENERATION` and calls `workflow.continue_as_new` between
batches so history stays bounded across the ~9,000+ match archives.

Idempotency: `ingest_match` (`activities.py`) SHA-256-hashes each match's raw
JSON and compares against the stored `matches.content_hash` before doing any
parsing or writes - an unchanged match is a no-op. This is also how a
periodic re-sync (re-running `starter.py` against a refreshed Cricsheet
archive) would stay cheap.

### The scoring rules in the parser are cricket, not bookkeeping

(For where the balls themselves live, see "Deliveries are stored" below - this
section is about how each ball is *counted*, which is the part that has been
wrong before.)

`ingestion/parsing.py` walks each match's `innings/overs/deliveries` structure
and accumulates per-player totals (`PlayerMatchStat`). The scoring rules
encoded there are real cricket domain logic, not incidental:
- `BOWLER_CREDITED_KINDS` / `NOT_OUT_KINDS` - which wicket kinds count against
  a bowler's figures, and which don't count as a batting dismissal (e.g.
  "retired hurt" isn't out; "run out" isn't the bowler's wicket).
- Wides don't count as a ball faced; wides and no-balls don't count as a
  legal ball bowled but do count as runs conceded; byes/leg-byes count as a
  legal ball but never count against the bowler.
- `dismissals` is a count, not a boolean - a Test can have two innings per
  side, so a player can be dismissed twice in one match. This matters for
  batting average (`runs / dismissals`), computed in
  `backend/app/queries.py`.

Don't "simplify" any of this without checking real figures against known
career stats first - these rules were reverse-engineered from actual
Cricsheet delivery records, not assumed.

### Three data sources, kept visibly separate

Cricsheet is still the only source of match data, and it is the reason every
derived figure exists - the per-player aggregates come from its ball-by-ball
records. Two others feed non-match facts, and neither is allowed to blur into
the first:

- **ICC rankings** (`icc_player_rankings`, `icc_team_rankings`) come from
  ICC's own JSON feed - the one their site consumes. They live behind
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
    **and must stay `primary_key=True` on the SQLAlchemy model** - omit it
    there and tied rows collapse into one ORM identity, which the session then
    emits twice.
  - ICC names people "Travis Head" where Cricsheet says "TM Head", and
    publishes no ID we share. `enrichment.resolve_player` matches on
    (surname, first initial) with country as a tiebreak, and returns None
    whenever more than one player fits - "Moeen Ali" will not be guessed at
    between `M Ali` and `MM Ali`. Unlinked entries still display; they just
    aren't links. ~72% link cleanly.

- **ICC fixtures** (`fixtures`) come from the same ICC feed's schedule
  endpoint. Deliberately NOT merged into `matches`: `matches` holds Cricsheet
  records with per-player figures derived from ball-by-ball, whereas a fixture
  is a calendar entry and an upcoming one has no result at all. Merging would
  put resultless rows into the table every aggregate query reads.
  - The feed paginates on **`page_number`**, not `page`. `page` is accepted and
    silently ignored, so a loop using it returns page one every time - which
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
    the activity** when more than half the batches fail - a throttled run
    otherwise returns "0 matched" and is indistinguishable from Wikidata
    genuinely knowing nobody.

### Names: `JE Root` is correct, `Joe Root` is for reading

Cricsheet's `players.name` uses the standard scorecard convention - every
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
more - `Babar Azam` → `Mohammad Babar Azam`, `Imran Khan` →
`Mohammad Imran Khan`, `Liton Das` → `Litton Das`. The label is therefore used
only when the scorecard name needs expanding, i.e. its first token is an
initials cluster (`JE Root` → `Joe Root`, `HMRKB Herath` → `Rangana Herath`).
That pattern allows up to eight letters: Sri Lankan initials run long
(`CBRLS Kumara`, `PADLR Sandakan`), and a narrower bound leaves them displayed
as initials. 3,103 of the 4,119 labelled players take the label; of the 1,016
that keep their scorecard name, 102 would otherwise have been renamed wrongly.
Known limit: players best known *by* their initials (`MS Dhoni`) get expanded,
because nothing distinguishes them from `JE Root` - the sourced label wins over
a guess.

Search matches **both** columns. Matching only `players.name` meant a player
could not be found by the name the product itself displayed: "Joe Root"
returned nothing while "JE Root" worked.

`players.image_url` is a Wikimedia Commons photo (P18), for ~1,000 players.
Two non-obvious details:
- P18 points at the **original** upload - Joe Root's is 2568x1794 / 4.8 MB,
  enough to time out a page load. The stored URL is a thumbnail.
- Wikimedia no longer renders arbitrary widths; an unlisted size returns
  `400 Use thumbnail sizes listed on ...`. Probing the handler, the sizes it
  serves are **120, 250, 500, 960, 1280** - `enrichment.COMMONS_ALLOWED_THUMB_WIDTHS`.
  The thumb path is computed from the MD5 of the underscored filename
  (`/thumb/<md5[0]>/<md5[:2]>/<file>/250px-<file>`) rather than costing an API
  round trip per player.

### Playing status is derived, and "retired" is never guessed

`queries.player_status` returns `active` / `inactive` / `retired`. The word
**retired only appears when a source says so** - Wikidata's P2032 or a date of
death. It is never inferred from a gap in appearances, because a gap covers
retirement, injury, being dropped, and cricket this dataset doesn't cover, and
nothing here distinguishes them. Those render as "Last played 2019".

Be aware how thin the sourced signal is: **P2032 exists for 21 of ~31,700
cricketers in Wikidata**, so exactly 2 players in this database have a
retirement date (plus 41 with a date of death). MS Dhoni shows as *inactive*,
not retired. That is correct behaviour, not a bug to "fix" by lowering the bar.

`active` is measured against the newest match **in the dataset**, not today -
anchoring to now would silently reclassify every current player the moment the
Cricsheet archive went stale.

### Deliveries are stored, and the aggregates are NOT derived from them at read time

Phase 1.5 landed: `deliveries` holds ~4.9M ball-by-ball rows beside the 221k
`player_match_stats` rows. Both are written by the same parse, and that
duplication is deliberate - §28 forbids a page request touching raw
ball-by-ball data, so an average still comes from the aggregate table while
phase splits, dot-ball rates, batting position and chasing come from
`deliveries`.

Measured, not estimated (§34 #4 asked for a sizing estimate):
**64 bytes per delivery, ~0.31 GB for the full backfill.** That is affordable
because of two schema choices - `WITHOUT ROWID` with a `(match_id, innings, seq)`
key, and extras stored as four small integers rather than a repeated kind
string. Don't "tidy" either without re-measuring.

`seq` is the 0-based position within the innings and is what makes the key work.
Ball-within-over cannot: a wide or no-ball adds a delivery to the over, so
`(over, ball)` is not unique.

Deliveries are DELETEd and re-inserted per match rather than upserted, because
the key is positional - a re-parse that changes the ball count would otherwise
strand tail rows from the previous version.

**The two tables must reconcile.** After the backfill, summing deliveries back
up to per-player figures matches `player_match_stats` on 100% of 168,458 batting
and 119,730 bowling rows. Re-run that check after any parser change; a
disagreement means every Tier B figure will contradict the boards the product
already ships.

When re-running it, apply the parser's *own* rules or the check will report a
false failure. A first pass showed one disagreeing row and the fault was the
query: the parser skips wides entirely for a batter, and Cricsheet has a
delivery flagged as a wide that also credits the batter a run. The parser is
right - nobody scores off the bat on a wide - so the reconciliation must exclude
wides from batter runs, not just from balls faced.

### Forward-looking schema, not yet populated

Two things exist in `schema.sql` for a future phase and currently do
nothing - don't treat them as dead code:
- `matches.data_granularity` (`'full'` vs `'result_only'`) anticipates a
  coarser-grained future data source (e.g. pre-2001 results without
  per-player breakdowns). Everything ingested today is `'full'`.
- `player_career_totals` would hold aggregate-only figures for players whose
  stats can't be decomposed per-match. Unused until that source exists.
`players.date_of_birth` / `birth_place` / `nationality` / `cricinfo_id` /
`bio_source` used to be listed here as "always `null`". They are not - the
Wikidata enrichment pass populates them, `nationality` for 3,098 of 9,442. They
remain *partial*, so the API and UI still render an absent value as "Not
available", and nothing is ever inferred to fill a gap.

`nationality` in particular is not a safe field to build on. It is a Wikidata
citizenship claim, not a cricketing one, and it is wrong often enough to
matter - it records **Chris Gayle as Australian**, and 2,554 West Indies
appearance-rows carry a nationality that is not a Caribbean territory. See the
player-flag section below for what to use instead.

### A "four" is a boundary, not four runs off the bat

`ingestion/parsing.py` counts `fours`/`sixes` only when Cricsheet does NOT set
`runs.non_boundary`. That flag exists precisely to mark all-run fours and
overthrow-assisted ones, and ignoring it overstates boundaries. Found by
validating against a published source rather than by reading the code: Joe Root
came out at 1,523 Test fours against ESPNcricinfo's 1,515. After the fix he
matches exactly, along with matches (166), runs (14,114) and sixes (46).

`runs_scored` is unaffected - a non-boundary four is still four runs. What
changes is `fours`, `sixes` and anything derived from them, notably the batting
explorer's boundary %.

### Fixing the parser does nothing until PARSER_VERSION is bumped

Idempotency is a SHA-256 of the raw match JSON, and Cricsheet's bytes do not
change when our parser does. `shared.PARSER_VERSION` is mixed into that hash for
exactly this reason: without it, a parser fix plus a re-run skips all 10,040
matches and **reports success**. This is the trap §5 names, and it is not
hypothetical - the first attempt at the boundary fix returned "357 unchanged
(skipped)".

Two things are needed to land a parser change: bump `PARSER_VERSION`, **and
restart the Temporal worker** - it holds the old module in memory and will
happily keep using it.

### Venue normalisation: comma-collapse is safe, substring merging is not

`backend/app/venues.py` takes 593 raw venue strings to ~400 grounds. Three rules,
and the reasoning behind the last two is the load-bearing part:

- **Comma-collapse** (automatic, safe): the text before the first comma is the
  ground. "Arnos Vale Ground, Kingstown, St Vincent" -> "Arnos Vale Ground".
- **Curated aliases only.** The tempting rule - merge when one name contains the
  other - is wrong invisibly. Dubai has "ICC Academy" *and* "ICC Academy Ground
  No 2" (different pitches); Pakistan has "Arbab Niaz Stadium" in Peshawar and
  "Niaz Stadium" in Hyderabad, 1,000km apart. Substring similarity is used only
  to **report** candidates for review, never to merge.
- **City qualifies only the names that actually collide** (`CITY_QUALIFIED`).
  "County Ground" is EIGHT English grounds; "National Stadium" is Karachi *and*
  Hamilton, Bermuda. But city cannot be part of the key generally, because the
  column is itself inconsistent - the same ground appears under Bridgetown and
  Barbados, Kingston and Jamaica, Port Elizabeth and Gqeberha, Dhaka and Mirpur.
  Of 28 same-name-different-city cases, most are one ground written two ways.

### Venue intelligence: the toss makes "chasing success" Tier A

`backend/app/analytics/venue.py`. §20 marks "average score, average winning
score, chasing success rate" as Tier B, assuming knowing who chased needs the
innings sequence that only stored deliveries provide. It does not - **the toss
gives it exactly**. `toss_winner_team_id` and `toss_decision` are populated for
100% of the 10,040 matches, and together they name the side that batted first:
the toss winner if they chose to bat, otherwise their opponent.

That makes the most useful thing a venue page can say available today. Sharjah
PSL: batting first wins 30.6% and captains choose to bat 15.8% of the time -
outcome and behaviour agree. Sharjah ODIs: captains bat 87.9% of the time and
win 45.5% doing it - they do not.

Two things the module is careful about:
- **"Runs off the bat", never "average score".** `player_match_stats` has no
  extras - a wide is charged to the bowler, byes and leg-byes to nobody - so
  summing a side's batters understates a true total by roughly 5%. The figure is
  named for what it is. The par indices are unaffected, since both sides of the
  ratio are measured the same way, which is why they carry the interpretation.
- **Every rate is per competition.** A ground hosting Tests and T20Is has two
  different characters and one average describes neither.

### The ICC scorecard endpoint carries squads - and role, hand and bowling type

The single most valuable finding in this project. §34 lists "source for role,
handedness and bowling type" (#1) and "source for squad lists" (#2) as open
decisions gating most of the differentiated product. **Both are answered by a
feed this repo already consumes.**

`ICC_SCORECARD_ENDPOINT` was being used only for completed matches. Called with
an *upcoming* `game_id` it returns a full announced squad, and every player
carries:

    Role          Batter | Bowler | All-Rounder | Wicket Keeper
    Batting.Style RHB | LHB
    Bowling.Style RM, RFM, RF, LM, OB, SLO, LB ...
    status        ICC's own availability wording
    Iscaptain, Position, Matches, career Batting/Bowling summary

Measured on the first pull: 927 squad rows across 35 fixtures, 79% resolving to
one of our players through the same (surname, initial) index the ICC rankings
use. That gives sourced roles including 125 wicketkeepers, 720 RHB against 207
LHB, and a bowling style good enough to split pace from spin.

§5's claim that fixtures "carry team names only, no player lists" is true of the
*schedule* endpoint and false of the *scorecard* one. Check the second before
declaring anything Tier C on squad data again.

### Squad attributes come from COMPLETED fixtures too, and that is the whole difference

The first squad sync fetched only upcoming fixtures, because the feature it fed
was availability and a played match cannot be a commitment. That left sourced
role, hand and bowling style on **343 of 9,472 players (3.6%)** - a filter that
silently excludes almost everyone, which is precisely what §17 warns against.

The same payload for a *completed* fixture still carries every player's Role,
Batting.Style and Bowling.Style. Fetching those as well (`sync_fixture_squads`
takes `include_completed`) took the register to **16,996 squad rows over 757
fixtures, 2,295 players with a sourced role and hand, 1,981 with a bowling
style** - 42% of players active in the last three years. Availability still
reads only upcoming fixtures; the widened pull is for the attributes.

Two details that bite:
- The feed spells the same role two ways. 74 players carry `"Batsman"` against
  the majority's `"Batter"`, so an unnormalised filter for one drops the other.
  `scout.normalise_role` owns the mapping.
- **`func.max()` per column is not "the latest row".** It returns the
  alphabetically-largest value of each column *independently*, so it can report
  a player's newest batting hand beside a role they were given years earlier,
  and it ranks `"Wicket Keeper"` over `"All-Rounder"` purely on the letter W.
  `_sourced_attributes` walks rows ordered oldest-first instead, letting later
  rows overwrite earlier ones only where they actually carry a value.

### A bowling style is a NOMINAL attribute, and filtering on it alone puts batters on a bowling brief

The mirror of the volume-floor trap, and it bit in exactly the same way. The
feed records a bowling style for anyone who has ever turned an arm over, so
asking the PSL for spin returned **Babar Azam, Tim David and Abdullah Shafique**
- all recorded `OB`, none of them spinners.

So a style filter (`analytics/scout.py`) additionally requires the player to be
picked to bowl at all: role Bowler or All-Rounder, sourced or inferred. The same
brief then returns Mohammad Nabi, Sikandar Raza, Abrar Ahmed and Liam Dawson.

The display rule follows from the same fact: `BestXI` renders a bowling type
only on a bowling slot, because "spin" beside Ben Duckett's name is true and
useless.

### The Scout page declares what it could not do, and that is the feature

`backend/app/analytics/scout.py` serves §17, whose own warning is that shipping
it early means "a filter that quietly ignores half the brief". Every response
therefore carries `applied` and `ignored` maps, and the page renders both, so a
constraint the data cannot honour is named on screen with its reason rather than
dropped.

Three honesty devices, all load-bearing:
- **Coverage above the results.** `with_sourced_attributes / candidates_considered`
  (659 of 1,806 internationally, 16 of 120 for the PSL) sits above the table,
  because a hand or style filter can only ever match inside that subset and a
  reader would otherwise take "no left-handers" for a fact about cricket.
- **Age is a SOFT bound.** Date of birth covers about 42% of the register, so
  players of unknown age are kept and counted in `unknown_age`, never dropped.
  A hard bound would silently discard the majority.
- **The franchise caveat is stated, not implied.** The squad feed is ICC's, so a
  franchise brief only knows attributes for players who also appear for their
  country. That goes in `ignored` rather than being left to be guessed from a
  short result list.

Validated by asking for left-handed keepers: Rishabh Pant, Devon Conway, Ishan
Kishan, Tom Latham. All four are exactly that.

### Availability: committed is sourced, available is not

`backend/app/analytics/availability.py`. The asymmetry governs the whole
feature and the UI is built around it.

A player named in a squad is a fact. A player **absent** from every squad is
evidence of nothing, because squads are announced a few weeks out: of 160
fixtures in a 60-day window, 33 had a squad. So the API never returns a list
called "available players" - it returns commitments plus
`fixtures_with_squads / fixtures_in_window`, and the page puts that coverage
figure ABOVE the results. A scout reading "142 free players" off an unannounced
squad table would be badly misled.

Franchise leagues are absent from the feed entirely (§34 #3), so a player free
of international duty may still be contracted elsewhere. That is stated in the
response, not left to be discovered.

### Best XI is buildable, and a stumping is what unlocked it

§5 puts Best XI behind two Tier C blockers. Both were true of
`player_match_stats` and neither is true of the ball record:

- **Wicketkeeper.** Cricsheet carries a `fielders` list on 65% of wickets; it
  simply was not being stored. `deliveries.fielder` now keeps it, and **a
  stumping identifies a keeper outright** because nobody else can take one.
- **Batting position.** The two batters on the first ball of an innings are the
  openers, straight from `seq = 0`.
- **Role** was already inferrable from balls faced versus bowled.

**A squad naming somebody a keeper now beats the stumping inference.** 291
players carry a sourced `Wicket Keeper` role, and that reaches the one case the
stumping rule was known to miss: a keeper who simply never stumped in the scope.
`Pick.keeper_source` records which route identified them (`squad` or
`stumping`), and the stumping rule below remains the fallback, unchanged.

**Catches are NOT a fallback for identifying a keeper.** They cannot be told
apart from outfield catches, so any long-serving fielder clears a catch
threshold - at 25 catches the selector named Mohammad Hafeez, an off-spinning
all-rounder, as a PSL wicketkeeper, with Babar Azam close behind on 58 catches
and zero stumpings. A stumping is now required; catches only rank keepers
already confirmed by one. The cost is missing a keeper who never stumped in the
scope, and that is the right way round: a side with no keeper is flagged and
visible, a wrong keeper is not.

### Selection scores career standing, not just the Performance Index

`analytics/selection.py` fills a **role shape** rather than taking the top
eleven by rating, because the latter reliably returns six openers and no keeper.

The weighting matters more than it looks. The Performance Index measures a
player's **last 15 matches**, so scoring on Index-plus-form is recency counted
twice and career record counted not at all - which picked a PSL XI containing
neither Mohammad Rizwan (102 PSL matches, index 41 on a poor recent window) nor
Babar Azam. Career standing over the whole scope now carries 55%, the Index 30%,
form 15%. "Best XI" has to mean more than "hottest XI" while still moving for a
player out of touch.

**Balance is reported, never selected for.** Handedness and bowling type left
Tier C when the squad feed was read for them, but only partly: they are known
for most current internationals and few historical or franchise-only players.
Filling a seam/spin quota on that would systematically prefer players who happen
to have squad data over better players who do not, which is a selection bias
dressed up as balance. So the side is picked on the role shape as before and the
split is stated underneath.

The note is also thresholded, for the same reason the flag rules are. An
all-time PSL XI is mostly players who retired before the feed's window, so 5 of
6 bowling picks have no style on record - and saying "no spinner in this attack"
of a side containing **Rashid Khan and Sunil Narine** would be a conclusion drawn
from a blank sample. Counts are always reported; the interpretation is only added
when the known picks outnumber the unknown ones. Availability genuinely does stay
out of selection, and `unavailable` still says so.

### Match intelligence: partnerships key on the pair, spells group by bowler

`backend/app/analytics/match_intel.py` (§22). Two algorithms with a trap each:

- **A partnership is keyed on the PAIR at the crease, not on the wicket count.**
  Counting wickets breaks on the cases that matter: a retired-hurt batter
  returning resumes with a different partner, and a run out can remove the
  non-striker without the incoming batter facing a ball. Comparing the unordered
  pair between deliveries handles both, and strike rotation does not register as
  a change because the pair is a set. Partnership runs include extras, as any
  scorecard does.

- **A spell must be grouped BY BOWLER first.** Walking the innings in over order
  and breaking whenever the bowler changes closes every spell after one over -
  a bowler cannot bowl consecutive overs, so their overs are never adjacent in
  the sequence. Group by bowler, then split where their own overs are more than
  `MAX_SPELL_GAP` (2) apart, since bowlers alternate ends.

  This is the whole value of the feature: Jomel Warrican's 6/112 in one Test
  innings is three spells - 1/69 off 22, 2/34 off 17, then **3/9 off 7** when he
  ran through the tail. Match figures hide that.

**Win probability is NOT built**, and that is deliberate: §22 defers it, and an
unfitted, unvalidated curve is confidently wrong exactly at the moments people
look at it. The endpoint returns a `deferred` map naming it and tactical events
with reasons, so a reader can tell a missing feature from a missing figure.

### Splits are format-aware, or they invent cricket that isn't played

`backend/app/analytics/splits.py` serves §12 with the split type as a parameter,
not a family of endpoints. Phase and situation come off the stored deliveries;
venue, opposition and competition come off the match.

Two refusals are the point of the module:
- **Phases don't exist in a Test.** A T20 powerplay is six overs and an ODI's is
  ten, so the bands live in `config.PHASE_BANDS` per competition - and Tests get
  no entry at all. Slicing overs 0-5 off a Test innings would produce a number
  that looks like the T20 one and means something else. The split reports that
  it does not apply.
- **Batting first vs chasing doesn't describe a Test either.** Four innings, and
  only the fourth is a chase in any sense.

`home_away` and `bowling_type` are returned in an `unavailable` map with reasons
rather than omitted, so a caller can tell "no data for this player" from "this
cut is not computable at all".

Validated against a published figure: Kohli's ODI situation split gives 65.46
chasing against 52.69 batting first, versus ESPNcricinfo's 65.5 and 51.7 - the
"Chase Master" statistic reproduced from the innings sequence alone.

### The Index's situation component is a RATIO, and needs both a floor and shrinkage

`performance_index` scores situation as chasing average over the same player's
batting-first average, never as a raw chasing figure: an opener chases far more
often than a finisher, so a raw number would rank opportunity.

Both guards are load-bearing and were set from the distribution. At a
5-dismissal floor with no shrinkage the ratio reached **14.19** and the p10-p90
spread was 0.55-1.77 - that is sample size, not a situational edge. At 10
dismissals each side, shrunk towards 1.0 on the thinner side, the spread is
0.65-1.50 with 1,004 players still qualifying.

### The Performance Index pools percentiles by discipline, or it rates discipline

`backend/app/analytics/performance_index.py`. Two decisions that look like
detail and are correctness:

- **Percentiles are pooled within (scope x discipline).** Measured over this
  dataset a bowler's mean opposition-adjusted impact is **1.08 par units against
  a batter's 0.64** - a 69% gap that is an artefact of the impact model (a
  four-wicket haul converts to ~120 runs-equivalent where a good innings is 45),
  not a statement about quality. Pooled together the first cut returned eleven
  bowlers in a top twelve. The form board never exposed this because form is
  self-relative and the offset cancels; a rating compares players to each other,
  so it does not.
- **"Recent performance" is the absolute standard of the window, not the form
  delta.** §14 words that component as "recent window versus the player's own
  baseline", which is literally the form figure - but scored that way the Index
  inherits form's self-relativity, a journeyman improving from poor to ordinary
  out-rates a great player playing normally, and the Index becomes a reweighted
  copy of a board we already ship (violating §15's requirement that the three
  rankings stay distinct). The deviation is deliberate and documented in the
  module.

Consistency is **downside deviation**, not variance: plain variance punishes a
match-winning 150 as hard as a duck, so the most "consistent" player is the
reliably mediocre one. Only shortfalls below par count.

Absent components (role, situation, availability - 25% of §14's weighting) are
dropped and the rest renormalised, never scored as zero. The API returns every
component with both its specified and applied weight, and the UI states the
shortfall.

### A volume floor does not keep specialists out of the wrong leaderboard

The explorers (`backend/app/analytics/explorer.py`) gate on minimum balls, and
that is **not** sufficient to keep a batter off a bowling board. Over a long
career a top-order batter's occasional overs clear any sane minimum: Kohli has
bowled 989 balls, Tendulkar 2,812, Root 8,120 - all past a 300-ball gate. The
mirror held too, with Muralitharan, Bumrah and Anderson all clearing a 200-ball
batting gate.

`discipline()` infers a crude role from `balls_bowled / (balls_faced +
balls_bowled)`, which §5 sanctions explicitly (it is *wicketkeeper* and *opener*
that are unreachable, not the batter/bowler/all-rounder split). `ELIGIBLE` maps
it: batting admits batters and all-rounders, bowling admits bowlers and
all-rounders, all-round admits only all-rounders.

The two cuts (0.25 / 0.78) are read off the observed distribution over the 1,782
men's internationals with 20+ matches, and classify every well-known player
correctly - Kohli .03, Root .19 (batters); Maxwell .50, Shakib .62, Afridi .76
(all-rounders); Ashwin .83, Bumrah .94, Muralitharan .96 (bowlers). The middle
band is deliberately wide: excluding a genuine all-rounder from a list they
belong on is the expensive error; admitting a marginal one is cheap.

The role is **inferred and labelled as such on every row**. It is never a
sourced fact about a player.

### Opposition strength is fitted, and two obvious versions of it are wrong

`backend/app/analytics/opposition.py` scales every performance by how hard the
side it came against actually is. Without it the form board ranked by *weakness*
of opposition - players whose recent cricket was against Norway, Portugal and
Malta outranked Virat Kohli.

Two measures were tried and rejected **against data**, so don't reach for them:

- **Mean impact conceded to opponents.** Ranked Indonesia the strongest side and
  Pakistan among the weakest. Impact is not zero-sum within a match and a
  competition slice is too coarse a control: associate matches are low-scoring
  for *both* sides, so a side that only plays them looks miserly. What was
  measured was the run-scoring environment, not the side.
- **Opponents' raw share of match impact.** Cancels the environment (it is a
  ratio within one match) and fixed the above, but still put UAE, Uganda and
  Japan above Australia - a share measures dominance over *whoever you played*.

What works is fitting those shares with **Bradley-Terry**, which makes strength
transitive, and referencing the fitted powers against the opposition in an
**average match** rather than the average team. That last part matters: there
are ~110 men's international sides and most play rarely, so a team-count
reference puts "par opposition" at roughly Malta and pins every Test nation to
the multiplier clamp. Validated against ICC team ratings at Spearman ρ ≈ +0.81
to +0.83 across all three formats - ICC is the *check*, never an input (it ranks
only ~10-20 sides, is a current snapshot against 25 years of data, and §6 keeps
official ratings out of derived figures).

Conventional figures - average, strike rate, economy - are deliberately **not**
adjusted, because they have to match what a scorecard source publishes. Only
this project's own impact measures carry the adjustment.

**Fitted per era, referenced against a stable core.** Team strength moves over 25
years: on own-share of match output Bangladesh runs 0.387 in the early 2000s to
0.505 in the mid-2020s, Australia 0.570 down to 0.488 - Bangladesh's swing alone
is wider than the gap between many pairs of sides, so one career rating credits a
2003 century against them exactly as much as a 2025 one. `opposition.multiplier`
therefore takes the match date (§14's "opponent standing at the time").

The era reference is taken over a **stable core** of sides present in most eras,
not over each era's whole population, and this is load-bearing. In 2019 the ICC
granted T20I status to every member, so the 2020s pool holds dozens of associates
that played no international cricket in the 2000s; referenced against its own
era's average, *every* established side inflated in the 2020s and Australia came
out harder to face in 2020 than in 2000. Anchored to the core, the curves match
cricket history instead - Australia 1.240 → 1.038, Bangladesh 0.796 → 0.964,
Sri Lanka declining after the Murali era, Zimbabwe dipping in 2005.

### `opposition.index()` falls back; `era_index()` does not - and display needs the second

`index(team, era)` deliberately falls back to a side's long-run figure when an
era has no fit, which is right for *scoring*: a match in an unfitted era should
still be adjusted by something. It is wrong for *display*, and silently so - the
fallback returns the side's whole-career index **and its whole-career match
count**, so an era a side never played renders as if they played their entire
career in it. Ireland's curve showed "2000: from 301 matches" before this was
caught. `era_index()` returns None instead, and every display path uses it.

The Opposition Analytics page is also where the model's qualifications live, on
the page rather than in a tooltip: it is a difficulty rating, it merges batting
and bowling strength into one figure, and it is not an official rating. An era
with under 15 matches is drawn hollow, and where the most recent era is that thin
no current figure is stated at all.

### Form boards rank on par units, not on the percentage

`FormLeader.rank_score` is `delta_absolute × confidence`, not
`delta_ratio × confidence`. A percentage is a ratio against the player's own
baseline, so a player who was dreadful and is now merely below average posts a
huge one - Sharvin Muniandy reached the in-form board at +97% while producing
**0.70 par units**, below what an average appearance is worth. Every leaderboard
row carries `recent_mean` so the absolute standard is visible beside the change.

### Caching: `data_version` alone is NOT a data-change signal

`backend/app/cache.py`. Several figures are derived from the whole dataset rather
than from the rows a request returns - the par table, the fitted opposition
strengths, the appearance-derived flag map, the two ranking aggregates. Computing
them per request was the largest cost on the read path, and caching them needs an
invalidation signal because `ingestion/` writes the same file while the API is up.

Three things about the signal, each found by measuring rather than reasoning:

- **`PRAGMA data_version` is per-connection and NOT comparable across
  connections.** SQLite documents this, and the obvious implementation - probe
  whichever pooled session the request holds, compare to one global - was
  observed reporting **2 and 3 for an unchanged database from two live sessions**,
  with a plain *read* appearing to bump the counter. A single dedicated
  connection is used for the probe so every comparison is same-connection.
- **A WAL checkpoint bumps the counter with no data change**, verified directly:
  `baseline 2 -> read 2 -> commit 3 -> wal_checkpoint(TRUNCATE) 4`. With the
  worker up and reader connections coming and going, that was **11 counter
  changes in 12 seconds of an idle database**, every row count unchanged. The
  cache threw away good work several times a minute.
- So the counter only means *look closer*. When it moves, a cheap content
  signature decides: row counts over `matches`, `player_match_stats`, `players`,
  `fixture_squads` plus `max(matches.content_hash)` (so a re-parse of existing
  matches is caught, not just new ones). Sub-10 ms, and it runs only when the
  counter has already moved. `deliveries` is deliberately excluded - counting
  4.8M rows costs 50 ms and nothing writes deliveries without writing
  `player_match_stats` in the same ingest.

Entries are tagged with the **signature**, not the counter, and `MAX_ENTRIES`
(512, LRU) is a **security control rather than tidiness**: keys include
caller-controlled values (`team_id` is any 64-bit int, an explorer's filter set is
effectively open), so an unbounded store lets an anonymous caller mint an entry
per request until the process dies.

`compute` runs OUTSIDE the lock - holding it across a multi-second aggregate would
serialise every request behind the first. An earlier version instead *discarded* a
value if anything committed while it was being computed, which starved exactly the
cases that needed caching: the all-round board takes ~3 s to build, the worker
commits inside that window, and the result was thrown away every single time.

`impact`, `opposition`, `performance_index` and `leaderboard` keep their own dicts
but compare against `cache.generation()`, which applies the same confirmed rule.
Before this they had **no invalidation at all** - an ingest mid-session was served
stale figures until someone restarted the process.

### The N+1s were in the analytics, not the ORM

Measured, with query counts:

- **Best XI: 3,159 queries, 9.0 s.** `form.assess` issues a query per player when
  called without a prefetched timeline, and `selection.py` was calling it in a
  loop over 3,145 candidates - while already holding the whole timeline map it
  needed, and throwing it away. `all_timelines` had existed for exactly this.
- **Scout: 1,814 queries, 5.9 s**, same cause.
- **`_hydrate_match_summary`: two queries per match**, so a 25-row match list was
  51 round trips and the 100-row page the API allows was 201. Individually cheap
  enough to hide - both tables are small and the identity map absorbs repeats -
  which is why it survived. `_hydrate_match_summaries` does a page in two.

Batching alone took Best XI to 14 queries but only 13.8 s -> 9.7 s, because the
cost had never been the round trips: it was building **154,400 MatchImpact objects,
107 MB, per scope, twice**. `form.scope_summary` reduces that map to the ~5,400
per-player facts its consumers actually want (one verdict, career mean, ball
counts) and caches *those*. Caching the timelines themselves was measured and
rejected at 107 MB per scope across ~14 scopes.

`MatchImpact` gained `slots=True` while investigating this. It is worth keeping and
it is not the win: 731 -> 691 bytes per object. The nested `Impact` dominates.

### SQLite is tuned for an analytical read replica, not for OLTP

`backend/app/database.py`. The defaults are wrong for a 645 MB file whose every
board is a GROUP BY over a large scan: `cache_size` was 2 MB, `mmap_size` 0, and
`temp_store` spilled sorts to disk files. Now 128 MB, 256 MB and MEMORY. These are
ceilings rather than allocations, so a process serving small queries pays nothing.

**Indexes were measured and mostly not added.** A composite `matches(gender,
competition_id)` removed an `AUTOMATIC PARTIAL COVERING INDEX` from two hot plans
and changed wall time by nothing (1.74 s vs 1.74 s; 0.29 s vs 0.28 s) - the
planner does not choose it for a full aggregate, which is correct. It was dropped
rather than kept for the write cost. The existing note in `schema.sql` about
gender-prefixed indexes on `matches` stands and was honoured: re-measure before
adding one.

### A warmup has to warm the keys REQUESTS use

`backend/main.py`. Cold, the Performance Index board is 6.7 s, the form boards
3.3 s, the all-round explorer 1.8 s; warm, all three are under 5 ms. Without a
warmup the first visitor after every restart pays the cold number, so the default
scopes are built in a daemon thread at startup (`CRICKET_INDEX_WARM_CACHE=0` to
skip).

Two failed attempts are worth not repeating:

- Warming with `competition_type="international"` where the routers pass **None**
  (and vice versa) populates keys nothing reads. The routers resolve the default
  further down, so the cache key is whatever the *request path* produces - which
  is `international` for rankings and the Index, and the router's per-discipline
  `min_balls` for the explorers, not `ExplorerFilters`' own default of 0. Verified
  by diffing cache keys after a warmup against keys created by real requests.
- Driving the real routes with `TestClient` from the warmup thread **deadlocked
  the server on startup** - it runs the ASGI app in its own event-loop portal, and
  doing that inside a process already serving the same app hung it before it
  answered anything. A warmup must never be able to take the server down.

### Rankings are computed in Python, not SQL, after a GROUP BY

`backend/app/queries.py`'s `_batting_aggregate_rows` / `_bowling_aggregate_rows`
run one SQL `GROUP BY` per call, then compute averages/strike-rate/economy
and sort in Python across the full result set before slicing for pagination.

They group by `player_identifier`, **not** `player_name` - 78 names in this
dataset map to more than one real person (two distinct "SR Taylor"s, two
"Shahid Afridi"s), and grouping by name silently summed their careers into a
single ranking row. `max(player_name)` just picks a stable display spelling.
Both helpers also take an optional `team_id`, which is what makes a team page
show a player's figures *for that team* rather than their gender-wide career
totals - without it a franchise page credits Babar Azam with his Test runs.
This is intentional (average requires a divide-by-zero guard that's awkward
in SQLite SQL) but means an unfiltered all-players query is O(total players)
in Python - acceptable at this dataset's size (~9,300 players), worth
revisiting with a materialized summary table if that ever changes.

### A squad window is the side's own last N matches, not a date range

`backend/app/analytics/squad.py`. The obvious implementation - "everyone who
played in the last 12 months" - reports most of this dataset as having no squad
at all. There are ~110 international sides here and the great majority play a
handful of matches a year and then nothing for a long stretch; a calendar
window makes that a statement about the fixture list rather than about the
side. Anchoring to the team's own most recent matches means "current squad"
means the same thing for Australia and for Malta.

The window is read through `player_match_stats`, not `matches.team1_id/team2_id`,
so the window and the appearances that fill it come from the same rows.

Role is `explorer.discipline` applied to **this window, for this team** - never
a career role. A career role is wrong twice over: a player bowls a different
share for their country than for a franchise, and a different share in Tests
than in T20Is. Axar Patel comes out a *bowler* for India over these 20 matches
at a 0.784 share, just past the 0.78 cut, and that is the honest reading of
what he was picked to do in that window rather than of what he is. The raw
share travels with every row so the inference stays checkable.

Roles read off very few deliveries are marked uncertain rather than withheld -
below `ROLE_MIN_BALLS` (60) they carry the same dotted rule the form verdicts
use. On a franchise squad that is typically a third of the list.

The endpoint returns an `unavailable` list naming what cannot be derived
(wicketkeeper, batting position, handedness, availability) and the page renders
it verbatim, so a partial picture cannot quietly present itself as a whole one.

### A player's flag is who they represent, never who Wikidata says they are

`queries._player_country_map` resolves the flag beside a player name from their
own **appearances**, so it means exactly what the flag beside a team means. It
does not read `players.nationality`: that answers a different question
(citizenship) and gets it wrong often - Wikidata has Chris Gayle as Australian,
and it stores values like "United Kingdom" and "Guyana" that name no cricketing
side. 8,194 of 9,442 players resolve.

Four cases the data forces, none of which may be "simplified" away:

- **Invitational XIs are not a nationality.** `flags.INVITATIONAL` (Africa XI,
  Asia XI, ICC World XI) is deliberately *narrower* than `flags.NO_NATION`,
  which also contains the West Indies. Use `flags.is_national_side` for this
  question and `flags.country_code` for drawing. Without the split, the 146
  players with more than one "international" side look dual-national - Dravid
  becomes India/ICC World XI and Tikolo Kenya/Africa XI.
- **The West Indies is a real side with no ISO code.** It resolves to a name
  with `country_code = None` - neutral mark, side named on hover, 227 players.
  Dropping code-less sides entirely would erase them.
- **Franchise-only players (1,247, mostly PSL) get no flag at all.** Nothing is
  inferred from where the league is played, so a PSL board shows Rilee Rossouw
  as South Africa and domestic-only players with the neutral mark.
- **Switchers take their most recent side**, tie-broken on appearances. Checked
  against every real case in the data and correct in all of them. The one that
  looks like a bug is not: Asif Ali shows **Bahrain**, because he played 75
  times for Pakistan to 2023 and 56 times for Bahrain since.

`/api/icc/*` rows derive their flag from ICC's own `country` column instead,
because that table is ICC's claim about ICC's list - resolving it from our
appearance data would mix a derived figure into a published one (§6). That path
needs `flags.ALIASES`, since feeds spell nations differently ("USA" against the
team table's "United States of America"). Afghanistan was missing from
`COUNTRY_CODES` altogether until this shipped: it has no side in the Cricsheet
archive, so only the ICC feed ever referenced it.

### Security posture: what was fixed, and what is deliberately absent

Audited by probing the running API, not by reading it. The full probe set lives in
the history; what matters is which findings were real.

**SQL injection is not reachable.** Every query goes through SQLAlchemy with bound
parameters, and `competition` / `competition_type` / `team_type` are validated
against the `competitions` and `teams` tables rather than interpolated. Injection
strings in `search`, `competition`, the venue `:path` route, `match_id` and
`identifier` all returned clean 200/404/422. Path traversal on the `:path` route
(`../../../etc/passwd` and its encodings) 404s: the value is a lookup key, never a
filesystem path, and nothing in the API opens a file from a request.

**Three real findings, all fixed:**

- **Two anonymous 500s.** `GET /api/teams/999999999999999999999` raised
  `OverflowError: Python int too large to convert to SQLite INTEGER`, and a
  100k-character `search` raised `OperationalError: LIKE or GLOB pattern too
  complex`. A 500 is an unhandled path, and both were one request from any
  caller. Int ids are now bounded by `validation.MAX_DB_INT` (SQLite's signed
  64-bit ceiling) and search strings by `MAX_SEARCH_LENGTH`; both now 422.
- **Error messages were a 1:1 reflector.** Naming the bad value is what makes a
  422 useful, but the value was echoed in full - 100 KB of junk in `competition`
  produced a **100,086-byte response**. `validation.echo` clips to 60 characters
  (now 164 bytes), and a real typo still gets the helpful message.
- **The cache was an unbounded store keyed partly on caller input.** See the
  caching section: `MAX_ENTRIES` with LRU eviction is the fix.

**Hardening added:** `nosniff`, `X-Frame-Options: DENY` and `Referrer-Policy:
no-referrer` on every response, and a catch-all handler that returns a generic
500 body so no query, path or driver message can leak regardless of Starlette's
`debug` setting. No CSP: it governs what a *document* may load and this API
returns no documents - the SPA's CSP belongs wherever the built frontend is served.

**Ingestion:** there is no `extractall` anywhere, so zip-slip does not apply, but
`z.read` decompressed without a bound - a crafted entry expanding to gigabytes
would OOM the worker rather than error. `MAX_MATCH_JSON_BYTES` (16 MB) is checked
against the declared size first; that is ~18x the largest real match (a Test at
892 kB, ODIs near 217 kB) so it cannot reject genuine data. Defence in depth,
since the archive is Cricsheet's over HTTPS. No `pickle`, `eval`, `exec` or shell
execution exists in either component, and every outbound URL is a hardcoded
constant, so there is no SSRF surface.

**`ICC_CLIENT_ID` is not a secret** despite matching every secret-scanner pattern.
It is the public client id ICC's own site sends from browser JavaScript to a public
CDN. It is documented as such in place so nobody "fixes" it by adding a config step
that protects nothing. `pip-audit` and `npm audit` both report zero known
vulnerabilities.

**Deliberately absent, and why:** there is no authentication and no rate limiting.
Everything binds `127.0.0.1` - the API, Vite, and Temporal's dev server - so
nothing is network-reachable, CORS is restricted to the Vite origin, and
`allow_methods=["GET"]` means POST and DELETE return 405. The data is public
cricket records and the API is read-only. **Both assumptions break the moment
anything is bound to a public interface**, and the cold-path costs documented above
(seconds of CPU on an unwarmed scope) are what a rate limiter would exist to
protect. `/docs`, `/redoc` and `/openapi.json` are open for the same reason and
should be reconsidered together with the above, not separately.

### Filter state lives in the URL, and `useFilters` is the only thing that writes it

Sixteen pages carry filters. Nine held them in the URL through a hand-rolled copy
of the same fifteen lines, and seven held them in `useState`, which is invisible
state: narrow a board to Test bowling with a 20-match floor, follow a player
link, come back, and you are on the unfiltered default with nothing saying what
changed. That URL also cannot be shared or reloaded, and the browser's back
button becomes a page-level navigation rather than an undo. The split was not a
decision anybody made, which is why `frontend/src/state/useFilters.ts` now owns
it and nothing else calls `useSearchParams`.

Four things there are load-bearing:

- **Two writers, not one with a boolean.** `set` means *a filter changed*, so
  paging resets - holding an offset across a filter change lands the reader on
  page four of a three-page result, which reads as an empty board. `keep` is
  everything else: the pager itself, and disclosures like the Performance Index's
  per-row "How?", which are UI state and must not throw away the reader's place.
  A `keepOffset` flag at the call site did not say which was meant.
- **Zero is written for a filter and dropped for paging.** `0` is falsy, and the
  first version dropped it everywhere - so a reader who deliberately set a
  minimum of nought silently got the control's default of ten back. A floor of
  zero is a real choice; page one is genuinely the absence of an offset.
- **The writers are referentially STABLE**, via the functional form of
  `setSearchParams` rather than closing over `params`. This is not tidiness: an
  effect that lists a writer whose identity changed with the query string would
  re-run - and refetch - every time any unrelated parameter moved, such as a
  disclosure opening.
- **A URL naming a value wins over a stored preference**, the same rule the scope
  switch already follows. `Teams.tsx` follows the app-wide family switch only
  when it actually MOVES, tracked through a ref: writing on mount as well would
  overwrite a shared `?type=franchise` with the family default.

Two pages validate rather than cast, because a hand-typed value reaches the API
otherwise: `Fixtures` checks the window against `WINDOWS` (three values, not the
two an earlier narrowing assumed - `live` was silently unreachable), and
`Underrated` checks the format against the **current gender's** list, since
men's and women's rank types share no vocabulary and `test` has no women's
equivalent.

Removing the per-page "reset the offset on a gender switch" effects left a real
gap, because a gender switch is a path change that keeps the query string. The
fix is at the point the answer lands rather than a guess up front: an empty page
at a non-zero offset clears the offset, which also covers a list shrinking after
an ingest. `clear()` exists for the stronger case - Compare and Squad Analysis
drop every filter, because an identifier from one gender names nothing in the
other.

`npm run check:filters` asserts the ten merge rules. The repo has no test suite
and this is not the start of one; it is the one piece of the filter layer that is
pure logic and was got wrong twice.

### Postgres works, and §24's "a connection change, not a rewrite" was 90% true

`DATABASE_URL` selects the store and its absence means the local SQLite file, so
nothing about running this repo changed. The read path was genuinely portable:
every query goes through SQLAlchemy with bound parameters, and the window
functions the period work added are standard SQL. But "no SQLite-specific SQL"
was not quite the case, and the gaps only appear when something actually runs
the queries on Postgres:

- **`func.iif` is SQLite's**, and 22 call sites across five analytics modules
  used it. Postgres has no such function at all. `sqlfun.iif` emits `CASE WHEN`,
  which both accept, so this is a translation rather than a dialect branch.
- **`TEXT + INTEGER` concatenation.** `Delivery.match_id + "-" + Delivery.innings`
  in the splits counter. SQLite coerces silently; Postgres refuses with "operator
  does not exist". The innings is now `cast(..., String)`.
- **Postgres is stricter about GROUP BY**, and four queries selected a bare
  column that SQLite allowed: impact, opposition, venue and the news list. The
  fix is to group by the joined tables' PRIMARY KEYS, because that is how
  Postgres infers functional dependency - and `news_article_images` has a
  COMPOSITE key, so two of its three columns infers nothing.
- **`group_concat` had no business being there.** It was the only
  dialect-specific function in the read path. Removed rather than branched:
  `/api/competitions` groups by (key, gender) and folds in Python, the same call
  `queries.py` already makes for the ranking aggregates.
- **The same expression must be built ONCE** when it appears in both the select
  list and the GROUP BY. Calling `_era_expr()` twice looks equivalent and is not:
  each call mints its own bind parameters, so Postgres could not match the
  grouped expression and rejected the all-round explorer outright.

`schema.sql` stays the single definition and is translated at load time
(`scripts/postgres_schema.py`): `INTEGER PRIMARY KEY AUTOINCREMENT` becomes an
identity column, `WITHOUT ROWID` is dropped. A hand-maintained second schema file
would be the copy that drifts.

#### `PRAGMA data_version` has no Postgres equivalent, and the fix is not a translation

`cache.py`'s two-tier invalidation exists because the pragma is a memory read and
the content signature is a real query. On Postgres that asymmetry disappears -
there is no pragma, and every candidate (`pg_current_xact_id`, `pg_stat_database`)
is a round trip exactly like the signature.

What matters instead is **not probing on every lookup**. `data_version` is called
inside `get_or_compute`, so on SQLite every warm cache hit pays nothing; over a
network it would pay a full round trip, which is the entire warm-path budget for
boards that are meant to be under 5 ms. So on Postgres the signature is polled at
most once per `PROBE_INTERVAL_SECONDS` (5) and the last answer is reused. The cost
is stated rather than hidden: a figure can be up to five seconds stale after an
ingest commits, which is nothing against a daily ingestion schedule.

#### Tie-breaks are not tidiness, and SQLite hid a dozen missing ones

Comparing 46 endpoints between the two engines found 9 disagreeing. Almost none
were value corruption: they were **the same rows in a different order**, because
an `ORDER BY` or a `.sort()` left ties to the engine. `queries.py` had used a
final key from the start ("otherwise paging through a ranking can repeat or skip
a row"); a dozen other places had not.

Fixed with one rule applied everywhere - fixtures (dozens share a start date),
match performers, tournaments, underrated, form leaders, scout candidates,
selection candidates, venue formats and grounds, opposition rows, splits buckets,
bowling spells. **This was a live defect on SQLite too**, not a portability
detail: any of those lists paged with an arbitrary tie order can repeat or skip.

Two of the nine were a different problem: the same ground reported a different
city on each engine. `matches.city` genuinely holds two spellings for one ground
(Dhaka/Mirpur, Chittagong/Chattogram, Port Elizabeth/Gqeberha), and both the
venue profile and the venue listing picked one arbitrarily - the profile through a
bare `LIMIT 1` with no `ORDER BY`. They now pick the spelling **most of the
cricket was filed under**, alphabetical when level: deterministic, and a better
answer than a coin flip.

After all of it: **43 of 46 endpoints byte-identical**, 2 differing only in the
last bits of one float (`recent_mean`, largest relative difference 1.11e-15
against a float64 epsilon of 2.2e-16 - summation order, rendered at 2dp), and 0
errors. Float sums are not made bit-identical across engines and should not be.

#### Latency is geographic, and no amount of batching fixes it

Measured against a Neon project in `us-east-2` from Pakistan: **median round-trip
617 ms**. That single number explains every reading, and none of it is cold start:

    player profile   22 round trips x 617ms = 13.6s   (observed 14.7s warm)
    dashboard         9 round trips x 617ms =  5.6s   (observed  6.8s warm)

Query *execution* is fine - the same 22 queries run in 266 ms against local
Postgres, and several aggregates are faster there than on SQLite. The cost is
distance multiplied by round-trip count, so the two levers are the region and the
number of queries per request.

`_player_competition_totals` is the second lever applied: the profile looped the
competitions calling both aggregate builders per competition, which is 14 queries
for seven competitions. Grouped by competition key instead, it is 2 - the profile
went from 22 round trips to 16. **This is the N+1 lesson CLAUDE.md already
records for Best XI and Scout, resurfacing the moment the database stopped being
a local file**: on SQLite the loop was 26 ms and invisible.

The region is the larger lever and it is a one-time decision, because Neon cannot
move a project after creation. A region near the reader takes the RTT from 617 ms
to roughly 40-120 ms.

#### Ball-by-ball data is 2.7x larger in Postgres, which decides what fits

Measured, not estimated: the 24 other tables are **79 MB** and `deliveries` is
**842 MB**, against ~310 MB in SQLite. The gap is exactly the `WITHOUT ROWID`
that CLAUDE.md's "64 bytes per delivery" depended on - Postgres has no
equivalent, so every row carries a tuple header and the primary key becomes a
separate index. Total 922 MB against 661 MB of SQLite.

That matters because a plan's storage limit decides whether the product is whole.
Neon's free plan reports `neon.max_cluster_size = 512MB`, so the ball record does
not fit and `capabilities.has_deliveries` exists for exactly that deployment:
every figure derived from deliveries reports **"this deployment does not hold
ball-by-ball data"** rather than returning an empty result. An empty phase split
reads as "this player never batted in the powerplay", which is a claim about
cricket; this is a fact about the deployment, and §17 and §30 are about not
conflating those.

#### The migration is resumable, because a remote load is interrupted

`scripts/migrate_to_postgres.py`. One `COPY` per table inside one transaction is
faster and wrong for a metered link: a dropped connection at four million rows
rolls back the lot and spends a gigabyte of transfer for nothing. So:

- **Committed per chunk**, capping the loss at one chunk.
- **Resumable by counting the target** and skipping that many source rows in the
  same deterministic order. Verified by deleting 40,000 rows mid-table: the
  re-run loaded exactly those 40,000 and reported "(resumed)", and a third run
  was a no-op reporting "(complete)". This is also what makes the script safe to
  run twice by accident.
- **Keyset pagination, not OFFSET.** `LIMIT n OFFSET m` per chunk makes a 4.8M
  row load quadratic - the last chunk re-scans the whole index to find its start.
- **Retried with reconnect** on connection errors only; a constraint violation is
  raised at once, because retrying it just fails again more slowly.
- **Load order from Postgres's own FK catalog**, topologically sorted, rather
  than a hand-written list or `session_replication_role = replica` - the latter
  needs superuser, which a managed Postgres does not give you.

Verification compares row counts **and** a per-table integer checksum, because
equal counts over mangled values is the failure a count-only check cannot see.

### The period vocabulary existed with no consumers, and two window kinds are not one

`analytics/periods.py` was written early, fully documented, and **wired to
nothing**: `parse`, `to_date_bounds` and `is_count_bounded` had zero callers and
the only export was `/api/analytics/periods` returning a list of options no page
requested. So the audit finding was not "the UI is missing a control" - no
endpoint accepted a window at all, and Principle 3's "first-class everywhere"
was unmet everywhere.

Rankings and all three explorers now take `period`. The implementation turns on
one distinction that is easy to miss and expensive to get wrong:

- **A date-bounded window pushes into SQL.** "Last 12 months", a season, a
  custom range: one predicate, applied to every player in the same query.
- **A count-bounded window cannot.** Each player's tenth-most-recent match falls
  on a different day, so there is no date range that expresses "last 10
  matches". It is a per-player cut, done with
  `ROW_NUMBER() OVER (PARTITION BY player_identifier ORDER BY match_date DESC)`
  and joined as a subquery. **The pair is the unit, not the match id**: a match
  inside one player's last ten is outside another's, so filtering on match id
  would admit every player who happened to appear in somebody else's recent
  match. Standard SQL rather than a SQLite extension, per §24's portability rule.

Four things that are load-bearing:

- **The anchor is the newest match IN THE SCOPE**, not in the database and not
  today. Not today, for the reason `player_status` already documents. Not the
  database, for the reason `selection.py` already documents: the PSL season ends
  in May while the newest match overall is an August Test, so a database-wide
  anchor would silently cost a PSL board three and a half months of its own
  season. Measured: the men's Test scope anchors to 2026-08-15 where the whole
  database is 2026-08-04.
- **The count-bounded cut is ranked over the SAME slice the board draws.** On the
  explorer that means "last 10 matches at the SCG" is their last ten *there*, not
  their last ten anywhere filtered down to the SCG - which would return one or
  two rows per player and describe nothing. `_last_matches_window` re-applies
  every filter except the window itself.
- **The period is part of the cache key, built from the window's FIELDS rather
  than its label.** Career and last-12-months are different aggregates over one
  scope, and sharing an entry would serve whichever was asked for first. Verified:
  each returns its own leader, and repeats are 2 to 3 ms.
- **A period and an explicit date range INTERSECT** rather than one overriding
  the other, the same rule `_competition_scoped` follows for a key and a type
  given together. `period=last12m&date_to=2026-01-01` resolves to
  2025-08-15..2026-01-01. This is what let the explorer's two raw date inputs be
  replaced by one window control without breaking a single shared link.

#### The window reaches six surfaces, and the profile is where it reads hardest

Rankings, all three explorers, the player directory, Compare and the player
profile all take `period`. Two of those are worth knowing about:

- **Compare** is §13's explicit requirement ("period adjustable within the
  comparison"), and it turns the page from "who has scored more" into "who is
  scoring more now": Kohli against Rohit in ODIs is 14,819 to 11,532 over a
  career and **760 to 584 over the last twelve months**, off twelve matches each.
- **The profile drops formats it has no cricket in.** Kohli's career page shows
  Test, ODI and T20I; narrowed to twelve months it shows ODI alone, because that
  is the only format he has played in the window. That is the honest answer, so
  the empty state says "no cricket in this window - widen it" rather than looking
  like a data failure.

The profile's window is anchored on gender only, not on a competition: a profile
spans every format the player has played, so there is no single competition to
count a relative window back from.

Form is **not** narrowed with the aggregates on the directory. Form has its own
baseline and answers a different question (Principle 3), so a `period=last30d`
board shows thirty-day run tallies beside standard form verdicts, and the note
says which is which.

#### A career-scale volume floor emptied a narrowed WINDOW too

Exactly the defect `explorer.derive_min_balls` already fixed, in a new place. The
directory applies a default floor of 200 balls faced (300 bowled) whenever the
sort is a volume field, and that floor was fixed regardless of the window - so it
was measuring a career qualification against a month of cricket. Measured on
men's Tests sorted by runs:

    window        fixed floor        derived floor
    career        693 of 1,063       693 of 1,063  (200, unchanged)
    last 12m       88 of 197         115 of 197    (floor 99)
    last 6m        43 of 146          88 of 146    (floor 59)
    last 30d       12 of 71           52 of 71     (floor 35)
    last 5 matches 552 of 1,063      769 of 1,063  (floor 98)

At thirty days the fixed floor hid **83% of the players who actually batted**, and
the page said only "12 players in tests". The floor is now derived from the slice
when a window narrows it and left fixed for a career board, and the response
carries `total_before_volume_floor` so the page leads with "52 of 71".

One copy defect fell out of the same line: the header read "sorted on a rate, so
a minimum of 200 balls faced applies" for **runs** and **wickets**, which are
totals. `QUALIFIED` now holds the unit only and the threshold comes from the API,
since it is no longer a constant the client can know.

#### A count-bounded board puts a retired player beside a current one, and says so

"Last 10 matches" on a leaderboard reads as *recent form*, and it is not: it is
each player's own last ten, so the men's Test board returns Mahela Jayawardene
second and Kumar Sangakkara sixth beside Shubman Gill and Devon Conway. That is
the honest answer to the question asked and it is genuinely useful, so it is not
"fixed" by adding a recency filter. `periods.applied` relabels it **"Each
player's last 10 matches"** and carries the caveat, and the page prints both
above the first row.

The same function resolves a relative window to real dates for display, because
"617 runs" means nothing without knowing over what (§30).

#### A season is the source's own label, so it is not offered as a control

`season:<label>` parses and a URL naming one resolves, but `describe()` omits
seasons deliberately. Cricsheet labels men's Tests **`2024` (13 matches) and
`2024/25` (29)**, so an option reading "2024" returns a third of the year's
cricket and looks like missing data. A reader wanting a calendar year gets an
exact answer from a custom range instead, which is why the custom control is a
pair of date inputs rather than an entry in the preset list.

#### Validated against published tables, which is how the date path was checked

Calendar 2024 men's Tests reproduce exactly - the ordering and every figure:

    batting   Root 1,556 (17)   Jaiswal 1,478 (15)   Duckett 1,149 (17)
              Brook 1,100 (12)  K Mendis 1,049 (9)
    bowling   Bumrah 71 at 14.93 (published 14.92)   Atkinson 52
              Bashir 49   Henry 48   Jadeja 48   Ashwin 47

`validation.check_period` bounds the spec at 64 characters and turns a parse
failure into a 422 naming the valid set, the same treatment competition keys get.
Swept: 55 (period x surface) combinations return 200, and six malformed specs all
422 rather than 500.

### A thin rate is marked, and each rate is gated on ITS OWN denominator

The splits panel shipped every rate at the same weight, which the venue split
punishes hardest: a Test career spans ~79 grounds and around one in seven is a
single innings, so an average of 146.50 from two visits sat beside one from
eight with nothing to separate them. Thin rates now carry the `.uncertain`
dotted rule - marked rather than withheld, because the runs were scored and it is
the *rate* that cannot be trusted.

Two refinements, both found by reading real output rather than the code:

- **Per discipline, not per row.** A single flag marked Kohli's Wankhede
  **batting** (6 innings, 433 runs) unreliable because he had also bowled a few
  balls there. That is the same conflation the explorers guard against when they
  keep batters off a bowling board.
- **Per rate, because the denominators are different quantities.** Gating
  everything on innings marked the wrong figures. A batting average is runs /
  **dismissals**: Kohli's JSCA return of 192.00 comes off 4 innings and **2
  dismissals** and is exactly the unstable case, yet it passed an innings test
  comfortably - while the strike rate over those same 4 innings rests on 200-odd
  balls and is perfectly sound. Measured over his 103 ODI venues, **21 rows are
  sound on strike rate and meaningless on average**, and the innings-only gate
  missed every one. `RELIABLE_MIN_DISMISSALS` and `RELIABLE_MIN_WICKETS` (4 each)
  gate those two; balls faced and balls bowled gate the rest.

The tooltip names the denominator it actually rested on ("Divides by 2
dismissals - too few for an average"), because "too few innings" is the wrong
explanation for a figure that does not divide by innings.

The split selector and the row-expansion moved into the URL with everything else,
so "look at their venue splits" is a link somebody can send.

### An error message is reader-facing copy, and this one named a dev port

`ErrorMessage` appended "check the API is running on port 8001, then reload" to
every failure, above the raw thrown string. Three things wrong with it, and the
third is the one that matters:

- **The port is a developer's detail** and was already wrong: a reviewer running
  a second instance on 8009 was told to check 8001.
- **A JSON envelope is not a sentence.** A mistyped player id rendered as
  `Error: 404 Not Found: {"detail":"player 'x' not found"}`.
- **"The API is down" is the wrong diagnosis for the commonest case.** A 404 or
  422 means the address names something this dataset does not hold, and telling
  the reader to reload sends them round the same failure again.

The status code now chooses the wording and the server's own `detail` - which
this project writes as a readable sentence on every 404 and its own 422s - is the
explanation. Two details worth keeping:

- **The body is found from the first brace, not the first colon.** Callers pass
  either `error.message` or `String(error)`, and the second carries an `Error: `
  prefix that claims the first colon - which silently sent every error to the
  generic fallback.
- **A 422 is never told to reload**, because the address itself carries the bad
  value and the same request fails identically. FastAPI's own field-level shape
  (`detail` as a list) is not prose, so it falls back to naming the cause rather
  than printing `Input should be less than or equal to 9223372036854775807`.

`format.plural` fixes the matching copy defect: five headings read "1 players"
or "1 matches" exactly when a filter had narrowed to the single row a reader is
most likely looking straight at.

### Navigation is a button, and an arrow is not a word

Inline "Compare with another player ->" links were replaced by
`components/ActionLink.tsx` (three weights: primary, secondary, quiet) drawing
`components/Icon.tsx` SVGs. Three reasons, and the third is the one that is easy
to miss: underlined-blue-plus-glyph is the convention for a link *inside prose*
and these are not in prose, a text arrow sits on the body baseline so it never
aligns with its label, and a four-word link is a four-word hit target.

The distinction that has to survive: **navigation marks are icons, data-direction
marks are text.** A rise/fall glyph in an ICC movement row, a trend arrow on a
form verdict, `12 -> 8` between two positions - those are content, and a sweep
that replaced every arrow with a component corrupted them into JSX-as-text. They
stay as escaped literals (`'\u2197'`, not the raw character), because JSX resolves
named entities through Babel's table, which carries `&rarr;` but not `&nearr;` -
that one rendered as the literal string on the page.

Links genuinely inside a sentence stay underlined text links. There are twelve of
them, all naming another page in the middle of an explanation, and turning those
into buttons would put a control in the middle of a paragraph.

### International and Leagues is a switch, and the client used to leak across it

Competition type is a hard partition in this schema, exactly as gender is, and
the backend has enforced it from the start (`queries._ranking_scope`). The
client did not. Five pages each carried their own copy of

    All Internationals | Tests | ODIs | T20Is | PSL

which crosses the partition inside one dropdown, and whose blank default
silently meant internationals - so a reader who picked PSL had changed family
without being told, and a reader who picked nothing did not know which family
they were in.

`frontend/src/scope/scope.ts` now owns it: a family switch in the chrome beside
Men's/Women's, and `useScopedCompetition` which gives a page the options for the
current family and the `competition_type` to send when no specific competition
is chosen.

Three things worth keeping:

- **The list comes from `GET /api/competitions`, not from the client.**
  `app/validation.py` already refuses to hardcode competition keys, precisely so
  that ingesting a new league stays a data change. Five hardcoded copies in the
  client put that code change straight back, and were the reason the families
  got mixed in the first place.
- **A URL naming a competition WINS over the stored preference**, and moves the
  switch to match. The only way to hold an out-of-family competition is for a
  URL to name one, since a page's dropdown offers only the current family - and
  a shared link to a PSL board should show the PSL board with the switch visibly
  on Leagues, not a notice explaining why it will not. An earlier version
  dropped the competition and explained itself instead; the notice component was
  removed once the adoption rule made it unreachable.
- **Not a path prefix, unlike gender.** Gender is in the URL because a player
  identifier is meaningless without it. A competition family is a lens over the
  same rows, every scope-sensitive page already carries its competition in its
  own query string, and a prefix would have meant editing 48 link sites across
  24 files to gain nothing a reader can see.

**The switch is gendered, and it has to be.** `/api/competitions` groups by key,
so PSL looked like a competition both genders have - and the switch offered
"Leagues" in a women's scope where every board behind it returned nothing,
because the only league here is men-only. The endpoint now reports which
genders hold each competition, the provider filters to the current one, and the
control is **absent** rather than shown dead when a gender has only one family.
It also falls back rather than stranding the app in a family the current gender
cannot fill. This disappears the moment a women's league is ingested; until
then, offering the switch would have been a promise the data cannot keep.

`Teams.tsx` seeds its `team_type` tabs from the switch, because `team_type` and
competition type are the same partition from two sides - the ingestion side maps
one to the other in `shared.TEAM_TYPE_BY_COMPETITION_TYPE`.

### Best XI answers two different questions, and says which one it answered

`pool='all_time'` (the default, so existing links are unchanged) picks from
everyone who has played enough in the scope. For Tests that returns Kumar
Sangakkara, Shane Warne and Ryan Harris - correct for "the best there has been",
useless for "who do we pick next".

`pool='current'` restricts the candidates to players still in the picture:

- last appearance **in this scope** within `config.SELECTION_CURRENT_WINDOW_DAYS`;
- and no sourced retirement date or date of death. That excludes almost nobody
  (43 in the whole register) because this project never infers retirement from a
  gap, but where a source does say so it is the strongest signal there is.

Two details that are easy to get wrong:

- **The window is anchored to the newest match IN THE SCOPE**, not to today and
  not to the newest match in the database. Anchoring to today would empty the
  pool the moment the Cricsheet archive went stale - the trap `player_status`
  already documents - and anchoring to the whole database would be worse for a
  league, since the PSL season ends in May while the newest match overall is an
  August Test, so a PSL pool would silently lose three and a half months of its
  own season.
- **The window is `queries.ACTIVE_WINDOW_DAYS` (365), reused rather than
  reinvented.** "Current" here has to mean what the active/inactive badge on a
  player's profile means, or a side would list someone the rest of the product
  calls inactive. Measured pools: 132 Test players, 121 PSL, 1,532 across all
  men's internationals.

The weighting also changes, to `SELECTION_WEIGHTS_CURRENT` (career 0.40, index
0.35, form 0.25 against 0.55/0.30/0.15). Career is still the largest single
term, because one poor series does not stop someone being the best available -
but inside a pool already restricted to current players it is the component that
discriminates least, since everyone left has been picked recently. Deliberately
not "form only": form is self-relative, so leaning on it would prefer a
journeyman having a good month over a great player having an ordinary one, which
is the trap `FormLeader.rank_score` documents for the boards.

Both the pool size and the applied weights are returned and rendered, because
the same heading means two different things depending on them. The page's
provenance footnote deliberately does **not** repeat the percentages: it used to
hardcode 55/30/15 and sat directly under a line stating 40/35/25, contradicting
it.

### Team weakness is a decline against the side itself, not a league position

Section 19 calls this "the differentiator" on a team page and gives the answer's
exact shape: *"death bowling performance has declined over the last 10
matches"*. `backend/app/analytics/team_weakness.py` implements that sentence
literally - a named PHASE rather than a total, compared against the side's OWN
previous window rather than against a table, over the side's own last ten
matches rather than a date range (the rule `squad.py` already follows, because
most international sides play in bursts).

Being below the peer figure is reported but deliberately does **not** make
something a weakness. A side can sit below the median for its whole history
with nothing having gone wrong, and a page that called that a weakness would
tell every below-average side the same thing.

#### The decline threshold is 20%, and the first guess was 8%

Measured over 536 facet comparisons across 97 men's T20I sides, the spread of
|change against own baseline| is median 10.5%, p75 18.2%, p90 29.4%. At 8% it
flagged **62% of all phases** as declining, which is a horoscope.

Worth checking before blaming the window: widening the recent window from 10
matches to 30 moves the median only from 10.5% to 9.0%, so that spread is
genuine era-to-era movement rather than small-sample noise. The window stays at
Section 19's own ten matches and the threshold sits in the tail of real
variation instead - 20% is about p80 and flags roughly one phase per side.

#### The peer reference took three attempts, and the first two failed silently

This is the same trap `opposition.py` documents - a team-count reference puts
par opposition at roughly Malta - and it had to be rediscovered here:

1. **Median of every side's rate** put powerplay batting at 6.82 an over while
   every Test nation sat between 8.9 and 9.7. There are ~110 men's
   international sides and most play rarely, so the median side is an associate.
2. **Pooled over every delivery** barely moved it, to 6.77: volume-weighting
   does not help when more than half the men's T20Is here genuinely are between
   sides outside the full members.
3. **The most active sides in a recent window** was the worst, and the only one
   with a visible tell. In 2019 the ICC granted T20I status to every member, so
   the 600 most recent men's T20Is are mostly associate cricket and the "core"
   it selected was **Austria, Indonesia, Sweden, Brazil and Romania**. The
   symptom was that every side came out above the reference on batting and
   below it on bowling simultaneously, which cannot happen against a real peer
   group - the reference was a single number applied to both sides.

What works is the twelve sides with the most **all-time** cricket in the scope,
pooled over matches **between two of them**. Full members have played T20Is
since 2005 and most associates only since 2019, so career volume separates them
where a recent window inverts them. The resulting reference - 8.3-8.6 powerplay,
~9.6 at the death - is what top-level T20I actually looks like.

`_peer_rates` also filters on gender, which the first version did not: a men's
team page was being measured against a pool containing women's matches.

### Underrated Players compares two ratings without correcting either

Section 15 calls the gap between the ICC's published position and the computed
Performance Index a product in its own right, and in the same breath forbids the
thing that would ruin it: **"the platform must never imply its rating replaces
or corrects the ICC's."** `backend/app/analytics/underrated.py` is built around
that sentence. Nothing is worded as an ICC error, ICC's own position is shown
unmodified, and the two are described as measuring different things - a points
system over a rolling window of results against a percentile blend over
ball-by-ball contribution.

**Both sides are re-ranked inside the players who appear in BOTH lists.** The
obvious comparison, ICC position against Index position, compares two different
populations: ICC ranks about 100 players per discipline, the Index rates every
player in the scope. A player 3rd on ours and 45th on ICC's may simply be 3rd of
a far larger pool. So the comparison is confined to the intersection and both
orderings are compressed to 1..N over exactly it.

**Absence is not a position.** A player ICC does not list is excluded, never
treated as ranked last: it may mean 101st, it may mean ICC does not rate them at
all, and this dataset cannot tell those apart. Roughly 12% of each ICC list
cannot be matched to a player here either (the same refusal
`icc_player_rankings.player_identifier` already makes), and a further chunk have
too little cricket for the Index. All three exclusions are counted and reported
above the table.

#### The threshold is a PROPORTION of the comparable set, not a number of places

Measured over 442 comparisons the pooled gap distribution is median 0, p75 10,
p90 20. The median being zero is the reassuring part: the two ratings broadly
agree, which is what makes a disagreement worth reading.

A fixed threshold looked right and was not. Comparable sets run from 37 to 67
players by discipline, so a gap of 20 is a 54% move in one board and 30% in
another - and at a fixed 20, **Test bowling flagged nobody at all**, because its
widest disagreement is 17 places. That board would have been permanently empty
for a reason that says nothing about either rating. A quarter of the comparable
set (floor 8) yields 4 to 14 players per board instead of 0 to 13.

#### The associate skew is measured and stated, because it is not a finding

Players from outside the twelve full members are **1.33x over-represented**
among those flagged: 35% of flagged against 26% of the comparable pool, over 276
comparisons. Neither rating is wrong. ICC's points weight a result by the
opposition's own rating and associate sides rarely meet the highest-rated teams,
while the Index is opposition-adjusted but still credits associate cricket at
its adjusted value. Left unsaid, a board showing four Dutch and Irish names
reads as "the ICC underrates associates" when much of it is a structural
difference in what the two measure.

### Batting position is a Tier B constraint that deliveries already answered

Section 33's definition-of-success query lists seven constraints and says two
were answerable when it was written. Six are now, and "opener" was the one still
derivable-but-unexposed: `explorer.openers` reads the opening pair straight off
`seq = 0`, the selector had used it since Best XI shipped, and Scout simply had
no filter for it. `?opens=true` now applies it.

It moved from `selection` to `explorer` to get there. Scout cannot import
`selection`, because `selection` imports `scout` - and both openers and
`discipline` are facts read off the ball record, which is what `explorer`
already holds. Unlike hand and bowling style it is a **hard** filter with full
coverage, because it is derived rather than sourced from the ICC squad feed.

The seventh, "strong against pace", stays in `ignored` with its reason: it needs
each delivery's bowler type, and bowling style is known only for players in the
squad feed while the ball record spans 25 years.

### Tournaments are a normalisation problem before they are a feature

`matches.event_name` is free text from Cricsheet and names 1,276 distinct
events. Two things have to be true before a tournaments page means anything.

**1. Most of those are not tournaments.** 1,013 of them are bilateral tours -
"Pakistan tour of England" is two sides playing a series. A tournament here is
an event at least `tournaments.MIN_SIDES` (3) different sides played in, which
is read off the data. A name-based rule would both admit tours called Trophy
and miss tournaments not called anything of the kind. 266 events qualify,
holding 5,424 matches.

**2. One tournament appears under several names, and the editions confirm it.**
The men's 50-over World Cup is "ICC World Cup" (2003, 2007), "ICC Cricket World
Cup" (2011, 2015, 2023) and "World Cup" (2019). Grouping the raw column files
it as three tournaments with a third of its history each.

Worse, Cricsheet is inconsistent *within* an edition, not only between them:
the 2014 men's T20 World Cup is 31 matches under "World T20" and 1 under "ICC
Men's T20 World Cup", and 2016 is 26 under "World T20" and 1 under "ICC World
Twenty20". So aliasing is not tidying that could be skipped - without it an
edition page is short by whatever landed under the other spelling.

`backend/app/events.py` follows `venues.py` exactly: **curated aliases only,
never a substring rule.** The tempting rule is catastrophic here, because all
of these are different tournaments:

    ICC Cricket World Cup
    ICC Cricket World Cup Qualifier
    ICC Men's Cricket World Cup League 2          (234 matches on its own)
    ICC Men's T20 World Cup Africa Region Qualifier

Similarity is used only to REPORT pairs for review (`merge_candidates`), and
the report earns its keep: it flagged "Asia Cup" against "Afro-Asia Cup" and
"East Asia Cup", and "Pakistan tour of England" against "Pakistan tour of
England and Scotland" - all genuinely different, all correctly left alone.
Alias keys are (gender, competition, name), because two bilateral series in
this data already carry one name across both genders.

**Containment alone was not enough, and the miss was expensive.** A first pass
only reported pairs where one name is a substring of the other, which cannot
see a REORDERING: "Women's World T20" against "ICC Women's T20 World Cup".
That is a fourth spelling of the women's T20 World Cup carrying its **2014 and
2016 editions, 46 matches**, and the tournament page simply had no 2014 or 2016
until it was found. `merge_candidates` now also compares order-independent
token sets.

That second rule needs its own guard, or it drowns the report: "England tour of
India" and "India tour of England" have the same token set and are opposite
tours. `_DIRECTIONAL` excludes them, which took the report from 261 pairs back
to 11.

**Typographic variants are normalised automatically, not curated.** Two names
here differ from a twin only by a curly apostrophe (`Men\u2019s` against
`Men's`), 8 matches. Merging those is not a judgement that two tournaments are
one - it is the same string - so `_TYPOGRAPHIC` handles it in
`canonical_event` rather than in the alias table.

#### A champion needs `event.stage`, and a tied final needs `outcome.eliminator`

Both were added to the parser (v5) for this, and both are load-bearing:

- **`event_stage`** names the Final. A winner is never inferred from "the last
  match of the event", which is wrong wherever a third-place play-off follows
  the final or coverage of an edition is partial - and partial coverage is
  normal here, the 2019 men's World Cup being 48 matches of which this database
  holds 36. Where the final is absent the page says "final not held here"
  rather than leaving an empty cell that reads as "nobody won".
- **`eliminator_team_id`** is who took a TIED match on a super over, boundary
  count or bowl-out. Cricsheet records it as `outcome.eliminator` and **not**
  as `outcome.winner`, so the 2019 World Cup final parses as
  `{"result": "tie", "eliminator": "England"}` with `winner_team_id` NULL.
  England won that World Cup. Reading only `winner_team_id` shows the most
  famous final of the decade as won by nobody. It is kept as a separate column
  rather than folded into `winner_team_id`, because every aggregate that counts
  match wins is right to keep excluding a tie.

Validated against the honours lists: the men's World Cup returns Australia 4,
England 1 (2019, marked as a tiebreak), India 1; the men's T20 World Cup all
ten editions with the right finalists; the Champions Trophy all six; the
women's T20 World Cup Australia 6, New Zealand 1.

#### What this dataset actually holds of the global events

Verified rather than assumed: Cricsheet publishes a **dedicated** archive per
ICC tournament, and `icc_mens_cricket_world_cup_json.zip` contains exactly 265
matches across exactly the six editions we hold, with identical per-edition
counts. So the ingestion is complete against the source; the gaps below are
Cricsheet's, not ours.

* **Nothing before ~2002.** Earliest data is 2001-12-19 (Tests), 2002-06-27
  (men's ODIs), 2005 (men's T20Is), 2007 (women's ODIs), 2009 (women's T20Is).
  So World Cups 1975-1999, Champions Trophies 1998-2002 and every women's World
  Cup to 2005 are absent entirely, and always will be from this source.
* **Afghanistan is withdrawn in full.** Zero Afghanistan matches come from
  Cricsheet - the four in the database arrive through the ICC scorecard
  fallback. Not just recent matches: the whole record, retroactively. This is
  why the 2019 and 2023 World Cups show **nine** sides rather than ten, and it
  is the single largest systematic gap. `tournaments._notes` says so on any
  flagship tournament missing them.
* **Editions are usually short by a few matches.** Only 2011 (CWC), 2009 (men's
  T20 WC), 2006/2009/2013/2017 (Champions Trophy), 2022 (women's CWC) and
  2016/2023/2024 (women's T20 WC) are complete. The rest run 1 to 12 matches
  under the real tournament.
* **No Under-19 World Cups.** Cricsheet publishes no U19 archive at all, so
  that is not an ingestion decision either.

The product states this rather than implying completeness: an edition reports
the matches held, `has_final` distinguishes "we do not hold the final" from
"nobody won", and the coverage notes name the causes.

#### Cross-source duplicates were real, and the key was the reason

`ingest_match` drops an ICC stand-in when the Cricsheet version of the same
match is written, keyed on `natural_key`. Two things defeated it and 33
fixtures were stored twice:

- **The cleanup only fires when a Cricsheet match is parsed.** An ICC row that
  arrives after the Cricsheet match is already stored is never revisited,
  because that match then hash-skips.
- **The key used raw team names.** ICC writes "Turkiye", "France Cricket" and
  "Hong Kong, China" where Cricsheet writes "Turkey", "France" and "Hong Kong",
  so the keys differed and both rows survived.

`icc_scorecard.natural_key` now lower-cases and maps through a small curated
`_TEAM_SPELLINGS`, which fixes new inserts. Existing rows keep the key computed
at insert time, so `backend/scripts/dedupe_matches.py` recomputes and repairs
them (`--apply`). It deliberately touches only cricsheet/icc pairs: two
Cricsheet rows sharing a key are a **double-header**, two real T20Is between
the same sides on one day, and deleting one would delete real cricket.

#### The deliveries reconciliation is 99.999%, not 100%, and here is the case

Re-checked after the v5 re-parse, Cricsheet-only: **0 of 169,111 batting rows
disagree**, and **1 of 120,217 bowling rows** does. The one is real and
pre-existing. A single delivery can dismiss two batters - match 1534056 has a
ball that is both a "retired out" and a "stumped" off DJ Hall - and
`deliveries.wicket_kind` is one column, so only one of the two survives.
`player_match_stats` is the correct side of that disagreement. Fixing it means
changing the key of a 4.9M-row table for one known instance, which is why it is
documented rather than done.

The 252 batting and 118 bowling rows that disagree across ALL sources are
ICC-sourced matches, which carry per-player figures and no ball-by-ball at all
by design. Scope the check to `source='cricsheet'` or it reports a false
failure.

### The frontend is light-first with dark as a peer, and semantic colour has two tiers

`frontend/src/index.css` defines both palettes as `--color-*` tokens, so every
Tailwind utility re-themes at once. Dark is declared under both
`prefers-color-scheme` **and** `[data-theme]`, because the in-app toggle
(`theme/useTheme.ts`, a three-way System/Light/Dark control) has to win in both
directions. Preference is applied by an inline script in `index.html` before
first paint; doing it from the bundle is the flash of wrong theme.

Three things here are load-bearing:

- **Semantic colour ships as a mark tier and an `-ink` tier.** A colour dark
  enough to read as 12px text is too dark to hold its hue as a 6px dot, so
  `--color-positive` fills and `--color-positive-ink` labels. Using the mark
  tier for text fails AA.
- **Amber and red cannot be told apart, so uncertainty is not a colour.** Six
  candidate pairs were measured across both themes; every one landed ΔE 11.5–12.8
  for *normal* vision against a floor of 15, and as low as ΔE 0.6 under
  deuteranopia. Since amber means *uncertainty* and red means *below par*, and
  the two sit in adjacent columns of a form row, uncertainty moved to the
  `.uncertain` dotted rule plus a marker. **Do not "fix" this by picking a
  better amber** - there isn't one. Amber survives only where it is isolated,
  such as the "soon" nav tag.
- **Charts read tokens at runtime** (`theme/useChartTheme.tsx`). Recharts takes
  literal colours, so hardcoding hex pins every chart to one theme - which is
  exactly what happened when a light theme was added to a dark-only palette.
  Legend text wears ink tokens, never the series colour.

The categorical series order is fixed and validated as a set
(`--color-series-1..4`): worst adjacent CVD ΔE 10.2, normal-vision ΔE 19.1, all
≥ 3:1 on their own surface. Slots 2 and 4 collide when every pair is on screen
at once, so all-pairs forms (scatter, bubble, small multiples) cap at three
series.

The signature device is the **par datum** (`.par-track`, `components/ParMeter.tsx`):
a hairline at 1.00 with the bar growing away from it. Its scale tops out at
**3.0, not 2.0** - the in-form board routinely returns 2.0–3.0 par units, and at
a ceiling of 2 every one of those rows drew an identical full bar, which is the
one thing the meter exists to prevent.

### News is a fourth source family, and the extraction route is per publisher

`ingestion/news_sources.py` (pure) and `ingestion/news_activities.py` (I/O and
writes), the same split `enrichment.py`/`activities.py` already uses. Four
publishers, each read through the most structured mechanism that actually
works for it, established by probing rather than by assumption:

- **The Guardian** has a real content API (`content.guardianapis.com`). It
  names the hero image explicitly as the element with `relation="main"` and
  ships altText, caption, credit, photographer, source and pixel dimensions
  with it, so "which image is the primary one" needs no heuristic at all. It
  also ships `wordcount`, which is the only independent check that a body
  arrived whole rather than truncated. Measured limits on their open `test`
  key: 720/min, 50,000/day.
- **The ICC** has no RSS. It publishes a Google News sitemap
  (`sitemap-article.xml`, reachable from robots.txt) with an exact
  `news:publication_date`, and its article pages embed a schema.org
  `NewsArticle` with the full `articleBody`.
- **Sky Sports** is RSS for discovery, JSON-LD for the article.
- **ESPNcricinfo** is feed-only, and not by preference. Its article pages, its
  internal `hs-consumer-api`, and `robots.txt` itself all return an Akamai 403
  to a non-browser client. Rather than defeat that with a headless browser it
  is read from the RSS it publishes for the purpose, and `content_policy` says
  `metadata_only` so nothing downstream expects a body.

**Two publishers are registered and disabled**, which is the point of
registering them. `bbcsport` is off because bbc.co.uk/robots.txt says in plain
English "No scraping, crawling, or systematic extraction" and "No creating
datasets from BBC content"; the adapter parses their feed fine, and the
exclusion is a policy decision that should be visible and reversible by
someone holding a licence, not a silent absence. `cricbuzz` is off because
their edge 403s every non-browser client on every path including RSS.
`/api/news/sources` returns the disabled ones with their reasons for the same
reason.

#### Fixing the extractor does nothing until EXTRACTOR_VERSION is bumped

`news_sources.EXTRACTOR_VERSION` plays exactly the role `PARSER_VERSION` plays
for Cricsheet, and for the same reason: idempotency is a hash of what we
extracted, and a publisher's bytes do not change when our extractor is fixed.
It is mixed into `content_hash`, and the ledger re-queues any URL stored at an
older version. **The worker must also be restarted** - it holds the old module
in memory. This is not hypothetical: the first attempt at the image-rendition
fix below reported "60 stored" while writing v1 rows, because the old worker
was still up.

#### Canonicalisation keys on the publisher's article id, not on the URL

Sky's RSS links `/cricket/news/12040/13574220/...` and their own
`rel=canonical` says `/cricket/news/12175/13574220/...`. The five-digit segment
is a section id and varies; the eight-digit article id does not. A
URL-keyed pipeline files that article twice, so `news_articles` is UNIQUE on
`(publisher_id, source_article_id)` as well as on `url_fingerprint`, and the
canonical URL is read from the page rather than trusted from the feed.
ESPNcricinfo needs the same treatment for a different reason: one story is
reachable as `/story/<slug>-1550496`, as `/ci/content/story/1550496.html`, and
on both `espncricinfo.com` and `cricinfo.com`, all three of which appear in
one `<item>` of their own feed.

#### Syndication is not the same question as coverage

`text_simhash` detects the same body republished elsewhere. It is deliberately
NOT used to collapse different articles about one event: on the day this was
built the Guardian, Sky and the ICC each wrote their own piece about Jake
Weatherald being dropped, and merging those would delete two mastheads' work
and misreport how widely a story ran.

The threshold was measured, not taken from convention. Over 120 real bodies
(median 574 words):

    syndication, 2% to 20% of words edited      p90 distance 2 to 7, max 11
    truncated republication, 90% of body kept   median 6, p90 10
    DIFFERENT articles, 7,140 pairs             min 12, p1 23, median 32
    same event, three publishers                min 22

The conventional 3-of-64 cut misses a republication with ordinary house-style
edits. `SYNDICATION_MAX_DISTANCE = 8` sits in the gap with a 4-bit margin
below the negative class's observed floor, deliberately nearer the syndication
side: a false positive suppresses a real article.

#### Images are referenced, never re-hosted, and the asset id is not the URL

Every hero on these four sources is licensed agency photography (Getty, Alamy,
PA, Reuters). The RSS and API grants cover reading the metadata, not making
and serving a copy - the same call already made for `players.image_url`, where
the asset was freely licensed Wikimedia and the argument was therefore weaker.

Each CDN encodes a stable asset id separately from the rendition, and
`image_identity` recovers it so one photograph is one row across articles and
sizes:

    imgci       p.imgci.com/db/PICTURES/CMS/<bucket>/<id>[.<variant>].jpg
                bucket = id // 100 * 100; variants probed live:
                (none) 1400x933  .1 160x107  .2 310x207  .3 900x600
                .4 900x506  .5 365x205  .6 1296x729  .9 800x800
    365dm       e{N}.365dm.com/{yy}/{mm}/{W}x{H}/{slug}_{assetId}.jpg
                host shard and size both vary for one asset; the id does not
    cloudinary  images.icc-cricket.com/image/upload/<t_named>/[v<n>/]prd/<publicId>
    guim        media.guim.co.uk/<mediaId>/<crop>/<width>.jpg

**The ICC's Cloudinary account has strict transformations enabled.** Named
transforms serve (`t_ratio16_9-size50-webp` is 94 KB against `size20`'s 21 KB
for the same asset); an arbitrary `w_1600,c_fill` returns **HTTP 401**. So a
rendition may only ever be requested from `ICC_NAMED_TRANSFORMS`, never
constructed. Directly analogous to the Wikimedia thumbnail rule above.

Caption, credit and alt text live on `news_article_images`, not on
`news_images`: the same photograph is reused across articles with a different
caption each time, and storing them on the asset has the last article
ingested overwrite every earlier one's caption.

**Two renditions are stored, and the list must use the smaller one.** Storing
only the largest was right for "what is the best available" and wrong for a
64px row: measured on the stored assets, one dashboard row was pulling a
**461 KB** original from ESPNcricinfo and **308 KB** from Sky.
`news_images.thumb_url` holds a list-sized rendition
(`news_sources.thumb_rendition`) and the API returns it as `image.thumb_url`,
with `cdn_url` kept for the article hero. Per CDN: imgci `.2` (48 KB), 365dm
`384x216` (24 KB), Cloudinary `t_ratio16_9-size20-webp` (16 KB), guim
`/500.jpg` (25 KB).

**A second CDN whitelists its widths, and it is the Guardian's.**
`media.guim.co.uk` serves `/140.jpg` and `/500.jpg` and returns **HTTP 403**
for `/300.jpg`. So the thumbnail width is a verified constant, not arithmetic
on the stored width - the same rule the ICC's Cloudinary account and Wikimedia
already impose. `thumb_rendition` returns **None** for an unrecognised CDN
rather than the original, so a caller knows to fall back rather than silently
reintroducing the weight.

**The upsert keeps the largest rendition, not the latest.** The Guardian ships
one `mediaId` as both the main element (140/500/1000px) and the thumbnail
element (500px). A plain last-write-wins stored *every* hero at 500x400 with a
1000px rendition available. `validate_news` checks for the regression.

#### Scope and robots are different refusals and are recorded differently

`is_discoverable` enforces robots.txt (the ICC names eight integrity-desk
articles it does not want crawled). `is_in_scope` enforces the source's own
`article_path`. Both land in the ledger as `skipped` with a reason, never as
`failed`, because neither is a failure and mixing them in buries real
extraction breakage.

Both patterns were set from measurement and both were wrong first time:

- Sky's feed `12040` is their **all-sport** news feed, not cricket - 2 of 20
  items were cricket and the rest football, F1, tennis and racing. `12123`
  (cricket news) and `12175` (cricket, Australia desk) are the right ones.
- The ICC's first pattern allowed only `/news/`, which is the smallest of
  their three article families. Over the current 520 ICC articles it would
  keep 86 and discard 434: their per-tournament sitemaps publish under
  `/tournaments/<slug>/news/<article>` (417) and their disciplinary and
  qualifier announcements under `/media-releases/` (17), both 300-700 word
  cricket articles.
- Sky needed the same correction from the other direction. Their feeds only
  ever emit `/cricket/news/<section>/<id>/<slug>`, so a pattern fitted to the
  feed looks right and then rejects articles *after* they are stored, because
  their own `rel=canonical` redirects some into `/cricket/news/<id>/<slug>`
  (no section segment) and The Hundred into its own top-level section. Fit
  the pattern to the CANONICAL forms, not to the feed.

#### The ledger is keyed on the URL, so a failed scrape cannot look stored

`news_ingestions` is keyed on `url_fingerprint`, **not** on `article_id`. A URL
that failed to extract has a row there and no article row anywhere, which is
what makes "failed and partial scrapes are not marked as successfully
processed" structural rather than a convention. It is also the retry state
(`next_attempt_after`, exponential over 0.25h/1h/6h/24h/72h then abandoned),
the conditional-request cache (`etag`, `last_modified`) and the input to the
per-source circuit breaker in one place.

`invalid` and `failed` are different statuses on purpose. An `invalid` row was
served and parsed and simply was not an article, so refetching it in fifteen
minutes produces the same non-article; it becomes eligible again only when
`EXTRACTOR_VERSION` changes, which is the one event that could change the
answer.

**Conditional requests are worth far less than they look, and `content_hash`
is what actually does the work.** Measured across the four sources: the ICC
serves an ETag on both its sitemaps and its article pages, and **nobody serves
`Last-Modified` at all** - not the Guardian's API, not Sky's RSS, not
ESPNcricinfo's. So `If-None-Match` saves a body only for the ICC, and for
everyone else a re-run refetches the page and is saved from rewriting by the
extracted-content hash instead. That is not a shortfall, it is where the
saving really comes from: a forced re-queue of 32 Sky articles returned **30
unchanged, 1 stored, 1 invalid**, with 30 full page writes avoided by the hash
and none by a 304.

#### Entity linking uses the publisher's own tags, never a name in the body

The ICC tags people as `"Matt Renshaw 03/28/1996"` - a name **with a date of
birth**. `players.date_of_birth` is already populated from Wikidata, so that
match is effectively exact and needs no disambiguation. Name-only tags go
through `enrichment.resolve_player`, the same (surname, initial) index the ICC
rankings use, which refuses when more than one player fits.

Player names are NOT scanned for in body prose. "Root", "Khan" and "Ali"
appear constantly, the index is built for scorecard-form names, and a wrong
link attaches an article to the wrong person's profile with nothing on the
page to reveal it. A tag is the publisher's own assertion about who a piece is
about, which is a different quality of evidence from a substring match.

Team links carry the gender problem this schema always has: men's and women's
"Australia" are different `team_id`s and an article declares neither. The
gender is inferred from explicit markers and the `confidence` column records
which happened - `body_name` when the text established it, `body_name_men_default`
when nothing did and the men's side was taken. Recording the default as a
distinct value rather than folding it into `body_name` is the point.

**The inference reads the TITLE first, and that ordering is load-bearing.** A
body-only scan filed two men's Hundred finals as women's cricket, because a
report of the men's final mentions the women's final in the same sentence
("Rockets miss out on a clean sweep of men's and women's titles"). The headline
is what an article is *about*; the body is what it *mentions*. Within either
scope a marker counts only when the opposite marker is absent, so a piece
naming both returns None rather than picking.

Measured over 1,082 articles, title-first took women's classifications from 283
to 238 (removing the false positives) and positively identified 254 as men's
that had previously only defaulted - `body_name` rose from 1,006 to 1,901 and
`body_name_men_default` fell from 1,788 to 898.

`\bmen` cannot match inside "women" because the 'o' before 'm' is a word
character and the boundary fails, which is the only reason the two patterns are
safe to test independently.

#### The news gender filter is asymmetric, because the inference is

`/api/news?gender=` does not mirror the browse endpoints. Publishers never tag
an article with a gender; `link_news_entities` reads one from explicit markers
("women's", "WBBL", "Women's T20 World Cup") and returns nothing when there are
none. So the filter means:

* `female` - the article links to a women's side. A positive fact.
* `male` - the article links to **no** women's side. An absence.

Filtering men's news the way women's is filtered would be wrong twice over: it
would drop every article that could not be linked to any side at all (about
40% of the ESPNcricinfo headlines, which carry no tags and no body), and it
would present a default as a finding. Both the News page and the dashboard
strip state which rule applied. This is the same distinction
`body_name_men_default` already records on the entity row.

#### News sits at the FOOT of the dashboard, and the "no news feed" rule was reversed deliberately

`Home.tsx` used to carry "Every section is a computed entry point into the
product. Deliberately not a news feed (section 6)." It now carries a four-story strip,
and the reasoning was rewritten rather than left contradicting the code.

What that rule was protecting against is still real: a feed at the top would
make the landing page read as a scores-and-headlines site, which is the one
thing it exists to say it is not. So the strip sits **below** the form boards
and the dataset counts, is capped at four stories, uses thumbnail-sized images,
and every headline is an external link. It is a way out to the sources, not the
product. It is also fetched in its own `useEffect` rather than in the
`Promise.all` that loads the boards, so a publisher outage cannot blank them.

#### Content policy is enforced on the way out, not on the way in

`news_publishers.content_policy` is `full`, `extract` or `metadata_only`, and
`backend/app/news.py::_body_for` applies it when serving. The full body is
stored regardless, because entity linking, search and syndication detection
all need the whole text and truncating at ingest would degrade them
permanently - and because a policy can be corrected without a re-scrape if a
licence is obtained or withdrawn, which is not true of text thrown away on the
way in. `body_truncated` is returned on every article, not only capped ones,
so a client can always tell a short article from a trimmed one.

#### Rate limiting is per source and per worker process

`news_activities._SourceLimiter` holds a minimum interval and a concurrency
cap per source. Two separate controls because they answer different questions:
the semaphore bounds open sockets, the interval bounds request rate, and a
semaphore alone lets N requests fire in the same millisecond and then idle.

Its scope is **the worker process**. Two workers on one task queue would each
hold their own limiter and together exceed the floor, which is why the
intervals are set an order of magnitude below what each source advertises
rather than at the line. A cross-worker limiter needs shared state this
project's single-SQLite-file architecture has no good home for, and pretending
otherwise would be worse than saying so.

#### Tournament data needs no job of its own, but staying CORRECT does

`event_name`, `event_stage` and `eliminator_team_id` are written by
`ingest_match`, so the Cricsheet legs of `icc-daily-sync` already refresh
tournaments every day - a new World Cup match arrives with its stage and its
tiebreak winner attached, and nothing extra has to run. Yesterday's scheduled
run ingested 37 new matches and 304'd the rest, which is the mechanism working
as intended.

What the daily sync does NOT do on its own is keep tournaments *correct*, and
`activities.audit_tournaments` runs last in `IccDailySyncWorkflow` for the two
ways they break silently:

- **A renamed event splits a tournament, with no error anywhere.** Cricsheet
  renames events between editions - the men's 50-over World Cup has three
  names, the women's T20 World Cup four. An unaliased spelling does not fail;
  it quietly becomes a separate one-edition tournament and the real one loses
  those matches. This is not hypothetical: "Women's World T20" hid the 2014 and
  2016 editions, 46 matches, until it was found by hand. The audit reports any
  multi-team event whose first match falls inside `NEW_EVENT_WINDOW_DAYS`, so a
  rename surfaces in the workflow result the day it appears. It **reports**
  rather than fixes, because the alias table lives in `backend/app/events.py`
  and deciding two names are one tournament is a judgement, not a rule.
- **A duplicate match can outlive the cleanup meant to remove it.** The ICC
  scorecard leg writes stand-ins daily; `ingest_match` drops one when Cricsheet
  publishes the same match, but only if that match is parsed and only if the
  natural keys agree. The audit re-runs the check over everything and removes
  what is left.

**Removing duplicates is not enough on its own, and the first version of this
churned.** `ingest_icc_scorecards` decides whether Cricsheet already holds a
match by comparing its freshly-computed `natural_key` against the **stored**
key on Cricsheet rows. Those stored keys were written at insert time, so once
`natural_key` started normalising team spellings they stopped matching: the ICC
leg stored 22 stand-ins it should have skipped, the audit deleted them, and the
same 22 came back the next day. Measured before and after re-deriving the
stored keys:

    before   22 stored, 0 already in Cricsheet  ->  22 deleted by the audit
    after     0 stored, 95 already in Cricsheet ->   0 deleted

So the audit also **writes the re-derived key back** (10,104 rows on the first
pass). Deleting the row is cleaning up; fixing the key is what stops the work
being redone every morning.

The audit is in `ingestion/` and does **not** import `backend/app/events.py`,
because CLAUDE.md's rule is that neither side imports from the other. That is
why it flags new *names* rather than running the similarity report: the
similarity logic belongs with the alias table it serves, and the ingestion side
only needs to say "something new appeared, go and look".

#### Two Temporal schedules, both daily

`schedule.py` registers `icc-daily-sync` at 06:00 and `news-sync` at 06:30.
Separate schedules rather than one job with two legs, because they must fail
independently: a publisher blocking us should not put a red mark on the
workflow that ingests match data.

The half-hour offset is not cosmetic. Both write to the one SQLite file and the
ICC job includes a Cricsheet archive ingest, which is the heaviest write in
this project; starting news on the same minute would have it queue behind that
for no reason.

**The daily cadence has a real cost, and it is worth knowing before someone
"fixes" a gap.** RSS feeds are windows, not archives: Sky's two cricket feeds
hold 20 items each and ESPNcricinfo's hold 100. On a day when a publisher files
more than its window holds, a once-daily pass never sees the overflow, and
those articles are missed permanently rather than late. The ICC is unaffected,
since its sitemap plus the per-tournament ones reach far beyond a day. If gaps
start appearing, the fix is more runs per day, not a bigger fetch - and the
ledger makes it visible, because a run that returns a full feed of unseen
articles is a sign the window was full when we looked.

`NewsSyncWorkflow` runs its sources **concurrently**, unlike
`IccDailySyncWorkflow`'s Cricsheet leg which runs sequentially. The difference
is what each is bounded by: a bulk archive ingest is bounded by writes to the
one SQLite file and is worth not overlapping, whereas news fetching is bounded
by four independent publishers' politeness delays, and serialising them spends
the whole run waiting on the slowest while the other three idle.

### A percentage with no ceiling is a broken column, and form had one

`FormLeader.rank_score` documents why the boards are *ordered* on par units
rather than on the percentage. What that left behind was a board ordered on one
quantity and labelled with another, and the two do not agree. Measured over the
711 men's international verdicts:

    delta_percent |change|   p50 21.4  p75 36.9  p90 52.7  p99 131.2  MAX 306.1
    over 100%                22 of 711 (3.1%)

So the top row read **+197.6%** and the sixth read **+47.5%**, with rows in
between higher than rows above them. There is no reading of that column which is
not either "the sort is wrong" or "this number means something I cannot see".
And +306.1% was Daniel Jackiel at 1.67 par units off a 0.28 baseline, printed
above Virat Kohli's 2.63 par units.

`form.stamp_form_scores` adds **`form_score`, a 0-100 percentile of
`rank_score`** - the same device `performance_index` uses, for the same reason:
it bounds a quantity with no natural ceiling without inventing a cap, and
because it percentiles the *same* value the board sorts on, the column can no
longer contradict the order. `delta_percent` stays in the payload for
traceability (§30) and is no longer the headline anywhere.

Four things about it that are load-bearing:

- **One population, computed once.** The score is stamped inside
  `_build_scope_summary`, which is the cached reduction that the boards, the
  directory, Scout and Best XI all read their verdicts from. Percentiling per
  consumer gave the same player a different score on the board than in the
  directory - `form.leaderboard` therefore *looks up* its scores rather than
  computing its own, and only falls back to stamping if a player is somehow
  absent.
- **A thin verdict scores None, not 50.** Below `LEADERBOARD_MIN_CONFIDENCE` the
  verdict is excluded from the population and left unscored; 50 would read as
  "exactly median" for a player nobody could place.
- **`score_against_scope` exists for the single-player endpoint**, which assesses
  one verdict outside any population. It percentiles the *value* against the
  cached distribution rather than copying a precomputed score, so it stays
  correct when the caller asks for a non-default window.
- **The wording changes past a doubling, and nothing is clipped.**
  `delta_display` says "3.0x their baseline" above +100% and "+16% against their
  baseline" below it - so §11's required sentence still reads the way §11 writes
  it, and no percentage over 100 is ever rendered.

`scout.py` and `selection.py` now score form on `form_score` too, replacing a
local clamp of the ratio to +/-1 that handed every player past a doubling an
identical form term. And `queries.PLAYER_SORTS["form"]` sorts on the score, not
on `form_delta`: ordering the directory by the raw ratio put whoever had the
worst baseline on top, which is the defect the boards had already fixed.

**Team weakness had the same latent bug and a men's-only measurement missed it.**
An initial check over men's T20I sides found a maximum of 78.9% and concluded the
facet deltas were naturally bounded. Swept across every competition and gender
that is false: 3 of 2,340 exceed 100%, topping out at Turkey's women's T20I
middle-over batting at **128.6%**. `Facet.delta_display` carries the wording.

`backend/scripts/validate_percentages.py` is the guard. It sweeps 33 read paths
and fails on any field the UI renders as a percentage or a 0-100 score that
falls outside its range - and separately on any *raw* ratio that ships without a
bounded companion, so a new board cannot reintroduce the problem. Two things
about it: it treats an unreachable endpoint as a failure, so a stopped server
cannot look like a clean run; and its own logic is tested against synthetic
payloads, because the first version of this check never called its own walk
function and passed everything.

### A tournament edition is where the drill-down actually lives

`tournaments.py` answers "which tournaments exist and who won them".
`analytics/tournament_edition.py` answers everything a reader wants next: the
table, every fixture, the leading run-scorers and wicket-takers of that edition,
and who took the most player-of-the-match awards. The split follows §32 - the
event-name folding stays in `tournaments.py` and never happens twice, so an
edition can never be assembled from a raw Cricsheet spelling the alias table
would have merged.

Validated against published sources rather than by reading the code, which is
how both of the bugs below were found.

**The 2017 Champions Trophy reproduces exactly.** Both groups, every points
total, England's +0.866 net run rate, Shikhar Dhawan's 338 runs and Hasan Ali's
13 wickets. That edition is complete in this dataset (15 of 15 matches), so it
is the clean end-to-end check. 2023's men's World Cup gives Mohammed Shami 24
wickets, also exact.

#### Two bugs the validation caught, both of which looked right

- **A super over inflates every total it touches.** Cricsheet stores it as
  further innings on the same match with no flag of its own, so summing innings
  gave the 2019 World Cup final as **England 256/10 against New Zealand 256/9** -
  each side's real 241 plus their 15-run super over. The innings number is the
  only signal there is, so `_team_innings` drops anything past the second **when
  the match has an overs limit**; a Test's third and fourth innings are the
  match, not a tiebreak.
- **A knockout match does not belong in a group table.** Counted in, the tied
  2019 final gave England 10 played and 13 points against a published 9 and 12.
  `KNOCKOUT_STAGES` enumerates all 35 values `matches.event_stage` actually
  holds rather than pattern-matching "Final", the same call `venues.py` and
  `events.py` make. An unrecognised spelling falls back to a small hint list and
  is **reported in `standings_caveats`** either way, so the guess is visible.

#### The table is honest about not being the published table

Net run rate applies the **all-out rule** - a side bowled out is charged its full
overs quota, not the overs it used - and excludes abandoned matches entirely.
Skipping the first inflates every collapse; including the second rates a match
with no result.

Coverage is *detected*, not asserted. A round-robin gives every side the same
number of matches, so an uneven `played` column is proof that matches are
missing: the 2019 World Cup comes out with sides on 6 to 8 where all ten played
9, and the note says so in those terms. Points are the near-universal 2-for-a-win
convention and are labelled as a convention, with a caveat on any edition whose
stages imply carry-over points.

The Afghanistan withdrawal matters more here than anywhere else in the product,
because on an edition page it changes the *leaderboard* rather than a total: the
2024 men's T20 World Cup loses its actual leading run-scorer (Rahmanullah
Gurbaz, 281) and a joint leading wicket-taker (Fazalhaq Farooqi, 17). Without
the note that reads as this dataset disagreeing with every published source.

#### The season is a `:path`, and percent-encoding does not help

More than half the editions here are labelled `2023/24`. Starlette matches on
the *decoded* path, so `2023%2F24` still arrives as two segments and misses the
route - the same reason `/analytics/venues/{venue_name:path}` is a path. The
frontend route is a splat and the client deliberately does **not** encode the
season.

### Compare is 2 to 5 players, and `a`/`b` could not express it

§13 asks for 2-5 and §25 names the extension. The shape is now `sides: [...]`
with `values: [...]` per metric and a `best_index`, because `better: 'a' | 'b'`
has nowhere to put a third player and a client should not have to re-derive
"best of five".

Three details:

- **The volume gate is per player, not per row.** MS Dhoni's 36 balls bowled give
  him an ODI bowling average of 31.00 which is true, unmeaningful, and must not
  win the row - while Rohit Sharma's 610 balls in the same row are perfectly
  comparable. `qualified[]` marks the first without blanking the second, and
  `gate_field`/`gate_min` travel so the UI can say *why* a figure is greyed.
- **`best_index` is null on a tie.** Highlighting one of two equal figures
  asserts a difference that is not there.
- **`?a=&b=` is still accepted.** §27 makes every filter state a shareable URL,
  so two-player links already sent have to keep resolving; they map onto the
  front of `players`, and the page rewrites itself to the canonical
  `?players=x,y` form.

**The UI caps at four, and the limit is the design system's, not the data's.**
`index.css` defines and CVD-validates exactly four categorical series, and
identity on this page rests on colour across three charts. A fifth player would
mean either an unvalidated hue or two players sharing one, and a comparison where
two columns are the same colour is worse than a comparison of four. The cap is
stated on the page rather than only enforced.

### Best XI answers an objective, and says what that objective cost

`selection.OBJECTIVES` implements §18's seven optimisation targets through the
two levers that actually decide a side - the **role shape** it is filled to and
the **weighting** candidates are scored on. There is no second algorithm; it is
the same shape-fill either way, which is what keeps every objective explainable
in the same terms. `youth` and `experience` add a preference term carrying
`OBJECTIVE_BONUS_WEIGHT` (0.20) on top of quality rather than replacing it, so a
youth side is still the best *young* side and not the youngest eleven who have
played eight matches. Youth is soft, and players of unknown age are counted and
reported rather than dropped - date of birth covers ~42% of the register.

**§18's trade-off requirement is now met literally.** `_fill_shape` is the only
place that knows why a better player is missing - by the time a caller sees the
eleven, the reason has been discarded - so it tags each candidate passed over
with the quota that was full when their turn came. Asking for bowling strength in
Tests reports David Warner at 86.01 against Kumar Sangakkara's 85.13, out
because the three batter places were already filled. Only players who out-score
somebody actually picked appear: a candidate below every pick was not traded off,
they were not good enough, and listing them buries the real trade.

### The team page has both halves of §19, and one scope control

`analytics/team_strength.py` is the strength profile beside the weakness
analysis. Every dimension is a **depth** question rather than a quality one,
because that is what §19 asks and what a squad page can answer that a
leaderboard cannot: a side with one great batter and nine poor ones has excellent
batting and no batting depth, and it is the second that decides a series.

- Batting and bowling depth are the share of output from **outside the top
  three** - the complement of the reliance figure `squad.py` already computes,
  and scale-free, so a 3,000-run side and a 900-run side compare.
- Experience is mean appearances **in this scope**. A player's 120 Test caps are
  not experience of a T20 side.
- Bench usage is **deliberately unscored**. A high number can mean healthy
  rotation or an unsettled side and this data cannot tell them apart, so scoring
  it would assert something unknown.

Peers are the twelve sides with the most all-time cricket in the scope, and this
is the third module to need that lesson - see `team_weakness._peer_rates` and
`opposition.py` for the references that failed. Where fewer than three peers can
be measured the score is **None**, never 50, which would read as "exactly
typical" for a side nobody could place.

**One competition selector drives both panels.** Each owning its own put two
dropdowns on the team page and let them disagree: a reader saw depth over all
international cricket beside a decline measured in T20Is, with nothing saying
the two figures described different scopes.

### ICC ranking movement is buildable; ranking history is not, yet

§7 and §10 both list a ranking history, and `icc_player_rankings` is keyed on
`rank_date`, so the schema has always supported one. The data does not: there are
**six distinct snapshot dates spanning 2026-07-28 to 2026-08-17**, because the
daily sync started recently and the ICC republishes roughly weekly. A trend chart
over three weeks presents three weeks as a career, so `analytics/icc_movement.py`
computes movement between the two most recent published lists instead - which is
what §8 asks for under "Latest ICC Movements" - and reports `snapshots` so the
page can say how deep the record is.

Three traps, all found in the data:

- **Each rank type has its OWN snapshot dates.** `test-batting` was last captured
  2026-08-11 while `odiw-batting` was captured 2026-08-17. Resolving "the two
  most recent dates" globally and applying them to every type returns nothing for
  most of them, because it compares a men's Test list against a date only the
  women's lists have.
- **A player absent from the earlier list is a NEW ENTRY, not a riser.** Treating
  them as having moved from 101st manufactures a position the ICC never
  published. Same refusal `underrated.py` makes about absence from a ranked list.
- **A negative position delta is an improvement.** `places_gained` is signed so
  positive always means better, because a board where the best mover shows the
  most negative number gets misread every time.

`§8`'s **Available Talent section is deliberately still absent**, and that is not
an oversight. `availability.py` exists precisely to refuse the claim that heading
makes: 25 of 274 upcoming fixtures have an announced squad, so a list of
"available players" would be an absence of evidence presented as a finding.

### Two Performance Index components are off for coverage, not for absence

The reasons in `performance_index.COMPONENTS` were stale and the table is served
to explain itself, so a reader was being told something untrue:

- **role** said "no playing role exists in any current source". A sourced role
  exists for 2,295 of 9,511 players via the ICC squad feed. It stays off because
  a role-peer percentile over a quarter of the register would rate only those
  players and would systematically prefer whoever appears in the feed - the same
  selection bias `selection.py` refuses when it reports balance instead of
  selecting for it.
- **availability** said "no available feed carries squad lists". 16,996 rows over
  757 fixtures do. It stays off because only 25 of 274 upcoming fixtures have one
  announced, so the component would score an absence of evidence for most
  players.

### Home/away stays unavailable, and the measurement is the reason

`splits.UNAVAILABLE["home_away"]` now carries what was measured rather than a
general statement. Over all **636 distinct (venue, city) pairs, only 15 carry a
segment that resolves to a country - 2.4%**. Cricsheet gives a ground and a city
(270 of them) and never a country, so this is a data decision - a sourced
ground-to-country list - not a code one.

It is deliberately **not** inferred from which side plays somewhere most often.
That resolves Sharjah and Dubai to Pakistan and India, which is exactly backwards
for the neutral venues where the question matters most.

### The Vite dev proxy target is configurable

`VITE_API_TARGET` overrides `http://127.0.0.1:8001`. More than one API can be up
on this machine at once - a second checkout, or a reviewer running on a spare
port to compare against the instance already serving 8001 - and a hardcoded
target silently proxies to whichever process got there first:

    VITE_API_TARGET=http://127.0.0.1:8009 npm run dev -- --port 5174

### Best XI was ranking sample size, and three separate things caused it

Found by reading the all-time men's Test XI rather than the code. It contained
**Ben Duckett, Axar Patel (15 matches) and Pragyan Ojha**, and it *traded off*
Muttiah Muralitharan. The PSL side took Saqib Mahmood on 8 matches and left out
Mohammad Rizwan on 102 - the exact failure `SELECTION_WEIGHTS` was written to
prevent. The women's ODI XI took Holly Colvin on 11 matches beside players on 40
to 120.

The aggregates underneath were verified correct first, against published career
records, so the defect had to be in the weighting:

    Stuart Broad   ours 167 Tests / 604 wkts / avg 27.68   published identical
    Alastair Cook  ours 161 Tests / 12,472 runs / 45.35    published identical
    James Anderson ours 682 wkts / avg 26.41               published 704 / 26.45
    R Ashwin       ours 532 wkts / avg 24.12               published 537 / 24.00

One figure needs its column read carefully. The **bowling** board's `Mat` is
matches in which the player BOWLED - `_build_bowling_aggregate_rows` filters
`balls_bowled > 0` - so Broad shows 166 there against 167 on the batting board
and on his profile. The missing one is the Antigua Test of February 2009,
abandoned after ten balls, where he is named and bowled nothing. Both numbers are
right for what they count; only a reader comparing the bowling board directly
against a published Test-match count will notice.

Broad's and Cook's whole careers fall inside the window, and both reproduce
exactly; Anderson and Ashwin differ only by the matches Cricsheet is missing.

**1. `_career_standing` percentiled an unshrunk mean.** So sample size bought
the top of the board: Steve Waugh scored 98.1 on **8 matches** and Brian Lara
100.0 on **17**, while Rahul Dravid sat at 56.3 on 80 and James Anderson at 72.6
on 182. Correlation of standing with match count was r = 0.43, i.e. a long career
earned almost nothing.

Each mean is now shrunk toward its pool's mean, the empirical-Bayes device
`assess` already uses on the form window. The constant is **fitted per (scope x
discipline), not chosen**: K = within-player variance / between-player variance,
which is the number of matches at which a player's own mean and the pool's carry
equal weight. Measured on men's Tests that is **15.4 for batters, 9.3 for
all-rounders, 7.5 for bowlers**. Worth knowing: the values that *looked* right
when eyeballing the board were 45 to 60, four times too aggressive, which is
exactly why it is fitted rather than tuned until the output pleases.

The between-player term must be corrected for sampling noise -
`var(observed means) = var(true) + within/n` - because skipping that overstates
the spread between players and so understates the shrinkage, which is the
direction that leaves the bug in.

**2. `MIN_MATCHES = 8` is too low for an all-time side, and a fixed floor breaks
a scope.** The obvious fix, a floor of 20, silently empties one: **no player has
more than 14 women's Tests here**, because the dataset holds 24 of them. At 20
that XI returns nobody - and it is one of the best sides this product produces
(Perry, Knight, Healy, Ecclestone, Sciver-Brunt), precisely because when everyone
has 8 to 14 matches the comparison is level.

So the all-time floor is **a third of what a long career in this scope looks
like**, taken as the p90 of match counts: 18 for men's Tests, 26 for men's ODIs,
14 for men's T20Is, 15 for the PSL, 5 for women's Tests. `pool='current'` keeps
the absolute floor of 8, because it asks "who do we pick next", the pool is
already restricted to players active within a year, and a newcomer with eight
caps is a legitimate answer to that and not to "the best there has ever been".
The floor is returned as `eligibility_floor` and stated on the page.

**3. A retired player was scored 50 for form, which is a penalty for having
retired.** `form_score` is None for anyone without a current verdict, and the
neutral 50 was substituted. Measured: **55% of the all-time Test pool and 58% of
the PSL pool have no form verdict**, and form carries 15%, so an active player on
95 gained 6.8 points over a retired one purely for still playing - inside a side
explicitly picked across all time. That is more than the gap between several
picks.

Each player is now scored on the components they actually have, renormalised over
them, which is what `performance_index` already does for absent components. A
retired player carries career and index at 0.65/0.35; an active one carries all
three. `applied_weights` reports the shape per pick.

After all three: the all-time Test XI is Sangakkara, Head, Pietersen, Smith,
Williamson, Vettori, Jansen, Cummins, Warne, Muralitharan, Ajmal, and the PSL
side has Fakhar Zaman, Rashid Khan and Shaheen Afridi in it.

**Two smaller fixes found while checking.** `shape` reported the unscaled XI
shape, so a XV page stated a shape summing to ten above fifteen names; it now
reports the scaled shape `_fill_shape` actually filled. And a role quota the pool
cannot fill was silent - a women's Test XV asked for four bowlers, fielded two,
and said nothing - so `_notes` now names it.

**The page defaults to `pool='current'`; the API still defaults to `all_time`.**
Two different requirements. A reader opening "Best XI" is almost always asking
who to pick next, and a side containing Warne and Muralitharan reads as the
product ignoring that they retired. But the API default has to stay `all_time`,
because links already shared carry no `pool` and must keep resolving to the side
they returned before. So the page sends its intent explicitly.

### The venue city qualification was defeated at the query

`CITY_QUALIFIED` exists because "County Ground" is several English grounds and
"National Stadium" is Karachi and Hamilton. `canonical_key` honours it. The
queries did not: `explorer.raw_venues_for` resolved the raw spellings using the
city and then **returned the venue strings alone**, under a comment stating that
"the city is part of their identity". Every caller then filtered
`Match.venue IN (...)`, which matches a bare name wherever it appears.

Measured before the fix: **14 ground profiles over-counted and 405 match-rows
were attributed to the wrong ground.** County Ground (Bristol) served Taunton,
Hove, Derby, Chelmsford and Northampton as well; National Stadium (Karachi)
included two Bermuda matches.

`raw_venue_pairs` now returns (venue, city) pairs and `venue_condition` builds
the WHERE clause, shared by the venue profile and the explorers so the two cannot
drift. `city IS NULL` needs `IS` rather than `=`, so it cannot be a tuple-valued
`IN`.

The same flaw existed in the **venue split**, which grouped on the raw column, so
six County Grounds collapsed into one row for players with up to 37 appearances
across them. It now groups on the pair and labels through `canonical(venue,
city)`, which qualifies the name.

Verified after: 591 venue profiles across both genders, zero anomalies, and every
profile's match count equals its listing's. 408 canonical grounds from 636 raw
(venue, city) pairs, and the API's per-ground totals sum to all 10,105 matches
that carry a venue, so nothing is lost in normalisation.

### What the verification pass confirmed was already right

Worth recording so it is not re-litigated:

- **Form verdicts are correct.** Kohli's last ten internationals are 74, 65, 5,
  124, 23, 93, 65, 102, 135, 74 - 760 runs at 76.0 against England, New Zealand,
  South Africa and Australia. "In form, 99.9, 3.0x baseline" is right.
- **The opposition adjustment works.** Full members are 35% of the qualifying
  population and 52% of the top 25, so the board favours harder opposition by
  1.48x rather than ranking by weakness. Multipliers order sensibly: India 1.179,
  England 1.084, Australia 1.035, Bangladesh 0.967, Bhutan 0.758, Malta 0.645.
- **Associates on the in-form board are not a bug.** Namgay Thinley's 100 off 47
  plus wickets is a genuine purple patch, already discounted by a ~0.76
  multiplier, and the par-units column beside it carries the absolute standard.
  Form means *changed*; the Index means *best*.
- **`pool='current'` leaks nobody.** Checked against the database across four
  scopes: zero picks with a last appearance before the cutoff, a retirement date
  or a date of death.
- **Every team survives every team endpoint.** 212 teams x 3 endpoints = 636
  requests, zero non-404 errors and zero out-of-range figures.

### The homepage leads with what it can answer, not with three boards

The landing page was a hero, one par explainer, three form boards and a news
list, all at the same visual weight. Two concrete problems: five identically
styled pills gave a reader nowhere to start, and Scout, Best XI, venue
intelligence, tournaments and availability were reachable only from a collapsed
sidebar group, so a first-time reader could not tell they existed.

Now: one primary action against quieter secondaries; the dataset's scale in the
hero where it is actually read rather than at the foot; a **"What you can ask
it"** grid whose six cards lead with the *question* each surface answers, which
is §2's first rule applied to navigation; and real section headings so the page
has a rhythm instead of a stack of equal cards.

The news strip keeps §8's constraint and stops keeping it ugly. It still sits
below every computed board, still holds four stories, still links out - but four
64px thumbnails in an undifferentiated list read as filler, so it is now one lead
story with room to be legible plus three rows. The header still says nothing
there feeds any figure on the page.

One implementation note: JSX resolves named entities through Babel's table,
which has `&rarr;` but **not** `&nearr;` - that one rendered as literal text on
the page. Use an escape for anything outside the common set.

### The venue alias report could not see the aliases that mattered

`venues.unresolved_candidates` compares names by CONTAINMENT, so it reports
"Grange Cricket Club" against "Grange Cricket Club Ground" and misses every
rename, sponsorship name, acronym and word-order swap - which is most of them,
because those share no substring with the name they belong to.

Sweeping same-city pairs by distinctive token and by acronym instead found
**700+ matches filed on a duplicate ground record**, and the largest were the
best-known grounds in the dataset:

    Sheikh Zayed Stadium        120 + Zayed Cricket Stadium              35
    Shere Bangla National       225 + Sher-e-Bangla National              1
    Gahanga International       104 + "Gahanga International ... . Rwanda" 77
    R Premadasa Stadium         148 + R.Premadasa Stadium                25
    The Wanderers Stadium        41 + New Wanderers Stadium              57
    UKM-YSD Cricket Oval         40 + YSD-UKM Cricket Oval               37
    WA Cricket Association Gd    38 + W.A.C.A. Ground                    12

Kigali's is not a rename at all: one row has a **full stop where every other has
a comma**, so ", Rwanda" is never stripped. It cannot be fixed by splitting on a
full stop, because that breaks "R.Premadasa" and "W.A.C.A." - so it is an alias.

Two generic fixes rather than a longer list of aliases:

- **The lookup key is punctuation-insensitive.** Case, full stops, hyphens and
  apostrophes are stripped for comparison, because a ground written with or
  without full stops is not two grounds and the variants are a class rather than
  a list. Only eight raw spellings here contain a full stop and every one is
  initials, so the DISPLAY name is normalised the same way - "R.Premadasa
  Stadium" becomes "R Premadasa Stadium", matching how this product already
  writes initials. Normalising the key alone would have merged the group and then
  labelled it two different ways, putting two rows in the list with one key.
- **"Niaz Stadium" and "Arbab Niaz Stadium" still differ** under that rule, which
  is the property that keeps two grounds 1,000km apart separate. The
  normalisation only removes characters that carry no identity; it is not fuzzy.

**Two merges were rejected because a source contradicted the instinct**, and both
are now pinned in `DISTINCT_DESPITE_SIMILARITY`:

- Darwin's **Marrara Cricket Ground and Marrara Stadium (TIO)** are two grounds
  inside one sporting complex. Wikipedia says so explicitly.
- Townsville's **Tony Ireland Stadium and Riverway Stadium** are separate venues,
  both used for cricket in the same series.

Also pinned: Nagpur's Civil Lines **Ground** against the Jamtha **Stadium**,
Potchefstroom's Senwes Park against the university's No 1 ground, and
Queenstown's Davies Park against John Davies Oval, where nothing was found either
way and one match is not enough to merge on.

**And one wrong merge already in the data: "Nehru Stadium".** India has several,
and this dataset holds four - Kochi, Guwahati, Pune and Margao - pooled into one
ground of eleven matches across four cities. Found by the cross-city check, not
by reading names, and fixed by adding it to `CITY_QUALIFIED` alongside County
Ground and National Stadium.

Result: **636 raw (venue, city) pairs to 394 canonical grounds**, all 10,105
matches with a venue accounted for, and 572 venue profiles across both genders
with zero anomalies.

`backend/scripts/validate_venues.py` makes this repeatable, which §29 asks for.
Four checks, each of which caught something real: cross-city merges (found Nehru
Stadium), same-city rename and acronym candidates (found the 700 matches),
no-match-lost, and a regression check that the pinned-apart grounds still
resolve separately - because two of those entries exist only because a source
overruled a guess.

#### Australian grounds are the sharpest case, and the handover is the proof

Sponsorship renaming is constant there. The WACA merged from three spellings to
50 matches ending **2017-12**, and Perth Stadium begins **2018-01** - a clean
handover with no overlap, which is strong evidence the two are correctly kept
apart rather than one ground written two ways. Cairns' "Bundaberg Rum Stadium"
was Cazaly's Stadium under a naming-rights deal from 2001 to 2003, which is
exactly when its two matches were played.

The figures then read as cricket: the MCG's T20I bat-first win rate is 36.8%
against the SCG's 63.6%, and the SCG's Test runs-per-wicket is 36.04 against the
MCG's 29.75.

### Ground character is the question a single ground page cannot answer

`/api/analytics/ground-character` puts every ground in ONE competition on two
axes at once, because "how does this ground compare with the others we will play
on" needs the population and a ground page only has one row of it.

Both axes are indices against the competition's **own** par, with the datum at
1.00 - the same device the par meter uses everywhere else. A raw runs-per-wicket
of 31 is a low Test figure and a very high T20I one, so only the index is
comparable. `competition` is therefore **required**, not optional: a ground
hosting Tests and T20Is has two characters and one figure describes neither, and
defaulting silently would be the "unscoped means everything" mistake §6 exists
to prevent.

It produces real cricket. Men's Tests: the WACA at 1.096 scoring and 0.959
wickets (fast scoring, wickets fall), Edgbaston 1.092 and 0.90, against Dubai at
0.882 and 1.13 and Sheikh Zayed at 0.926 and 1.119 with batting first winning
88.9% - a slow surface where the toss decides a great deal.

Colour on the chart carries the bat-first record and uses the **semantic**
positive/negative pair rather than a categorical one, because unlike role or team
"batting first wins more often" has a direction. Grounds below the reliability
threshold are drawn faded rather than dropped, so a thin ground is visible as
thin.

### The scatter is the chart a leaderboard cannot replace

`ExplorerScatter` plots average against strike rate for batting, and average
against economy for bowling. A column sorted by average says who scores most per
dismissal; it cannot say that two batters averaging 45 are different cricketers
if one strikes at 75 and the other at 140, which is the first thing a selector
wants.

Three things it gets right that a naive version would not:

- **It fetches its OWN field, ordered by matches.** Plotting the table's page
  would put the reference lines at the median of the top 25 by whatever column
  the reader sorted on - sorted by runs, every one of those is a high-volume
  player and the "median strike rate" is the median of the heaviest scorers. It
  asks for 100 rows under the same filters ordered by participation, which is the
  one ordering that biases neither axis.
- **Axis padding is proportional, not absolute.** A flat +/-5 is reasonable on
  strike rate, which spans 119 to 179, and absurd on economy, which spans 2.5 to
  4.5: it produced an axis running -2.61 to 9.11 with every point squashed into
  the middle third, so the chart showed no separation in the dimension it exists
  to show.
- **The good quadrant is derived, not written.** Bowling inverts - low is better
  on both axes - so the caption is generated from the metric. Hardcoding
  "top-right" would have praised the worst bowlers on screen.

Colour carries the inferred role, which is three values: the maximum the design
system allows on an all-pairs form where every series can sit beside every other.

### The type scale was missing its middle, so every page invented one

There were tokens for the hero and the page title and nothing between, so panel
headings appeared as `text-sm font-semibold`, `text-base font-semibold` and
`text-[15px] font-semibold` on three surfaces sitting next to each other. A
reader got no consistent signal about what level of the page they were on.

`--text-section` and `--text-panel` fill the gap, and each rung now has one
utility that sets family, size, weight and colour together - the ad-hoc classes
set size and weight only, which is how display-face titles ended up beside
body-face ones. `u-note` is the explanatory line under a heading, one size and
colour everywhere, because those lines carry this product's honesty devices and
must not look like a caption on one page and an afterthought on another.

Applied through `Panel`, `PageHeader` and a new `SectionHeading` rather than page
by page, so it propagates. Fixed rather than fluid below the title: a heading
inside a card must not resize while the table under it does not.

One JSX note found while building: named entities resolve through Babel's table,
which has `&rarr;` but **not** `&nearr;` - that one rendered as literal text.

### A career-scale volume floor emptied every narrowed slice

Reported as "at Sydney against Australia we have 0 stats or one player", and
reproduced exactly. The explorers defaulted to **5 matches and 200 balls**, which
is a fair qualification for an all-time board and unreachable in a single-ground,
single-opposition cut. Measured:

    slice                              shown   actually played
    Bellerive Oval v Australia             0               148
    Perth Stadium v Australia              0                82
    Adelaide Oval v Pakistan               0                39
    Sydney Cricket Ground v NZ             1                42
    Sydney Cricket Ground v Australia     26               261

Nothing on the page distinguished that from a ground with no cricket at it, which
is the "filter that silently stops filtering" failure in a new disguise. The
innings floor did the larger share of the damage: it alone cut Sydney against
Australia from 261 to 35 before the ball floor was reached.

**Both floors are now derived from the slice**, a quarter of what an established
player in THAT cut has, taken as the 75th percentile. Self-calibrating in the
same way `selection._all_time_floor` is, and it lands where it should at both
ends: the career batting board derives **202 balls**, almost exactly the old
fixed 200, while Bellerive against Australia derives 23 and returns 97 of 148.
An explicit `min_balls` or `min_innings` from the caller is honoured exactly.

Three structural changes made that possible:

- **The floors moved out of the builders into `page()`**, so the rows they remove
  can be COUNTED. Applied in the builder they never existed, which is why the
  page could not tell the reader anything.
- **The response carries `total_before_volume_floor` and both applied floors**,
  and the page leads with "97 of 148 players shown". Those two numbers differing
  is the whole story on a narrowed slice.
- **The cache key drops the floors**, since they are applied after the build, so
  two requests differing only in `min_balls` now share one build.

One bug fell out of this: the all-round builder emitted no ball counts, so the
new floor measured zero for every row and removed the entire board. It now emits
`balls_faced` and `balls_bowled`, which the role inference was already using
internally.

### Best XI can be tilted to a ground, and a tilt is not a re-scope

The obvious reading of "pick a side for this ground" is to run the selection over
matches at that ground. It does not work, for the reason above: at a single
ground the median player has one or two matches, so a side picked on that is a
side picked on noise - and it would silently exclude every good player who has
not been there.

So the side is still picked over the whole scope and a venue record moves a
candidate within it. `selection._venue_records` scores each player's at-ground
mean impact in par units and **shrinks it toward that player's own level in the
scope** - not toward the population, because the question is "are they better
here than they usually are", so their own norm is the right prior.
`VENUE_SHRINKAGE_MATCHES` is 8, higher than the career constant, because an
at-venue sample is smaller and noisier.

Three things reported rather than implied:

- **Every pick shows its sample.** "1.17x par from 13 matches" for Steve Smith at
  the SCG, and "1.92x par from 3 matches - too few to move them much" for Rishabh
  Pant. A venue figure without its count invites being read as a record.
- **Coverage sits above the side.** 186 of 328 candidates have any record at the
  SCG; 48 of 328 at R Premadasa. A venue term over 48 candidates is a different
  claim from one over 186.
- **The term is absent, not neutral, for a player who has never been there.** The
  weights renormalise over what a player has, the same rule form follows: a
  middling 50 for "never played at this ground" would penalise a great player for
  the fixture list.

Validated: at the SCG the tilt brings in Rishabh Pant, who made 159 not out
there, and drops Kevin Pietersen.

### Interface corrections

Several of these are small and all of them were visible:

- **Table cells had no edge inset.** `px-3` put the first and last columns 12px
  from the card border and they read as clipped. The inset is declared once in
  `tableClass` rather than on every page's cells.
- **`Provenance` is now a disclosure.** Several ran past 700 characters, and a
  wall of small grey text at the foot of a page is read by nobody - which defeats
  writing it. Collapsed, a page ends on one clear line; open, the whole
  explanation is there. `<details>` rather than a React toggle, so it is keyboard
  accessible and findable by the browser's own search. It was also `max-w-3xl`,
  ending short of the table above it and reading as a stray paragraph.
- **Five nav entries pointed at a screen that already had one.** Players, Teams,
  Best XI, Compare and Matches each appeared twice, so the same destination was
  reachable from two labels - which reads as having moved section when nothing
  has. 22 items, no duplicates.
- **The type scale was missing its middle**, so panel headings appeared at three
  different sizes on adjacent cards. `--text-section` and `--text-panel` fill it,
  applied through `Panel`, `PageHeader` and `SectionHeading` so it propagates.
- **Text arrows became SVG.** `&rarr;` and friends inherit the body face, so
  weight and baseline never matched the label beside them, and they announce as
  content to a screen reader. `components/Icon.tsx` holds three marks, sized in
  `em` and `aria-hidden`. Note the distinction kept deliberately: NAVIGATION
  affordances are icons; the trend glyphs in a data column stay as marks, because
  there they carry meaning rather than direction of travel.
- **Chart domains are clamped at zero.** Proportional padding pushed a batting
  average axis to -8.96, which is not a value any batter can hold.
- **Filters that were component state moved into the URL** - the ground-character
  competition and the team-intelligence competition. §27 makes every filter state
  a shareable link, and component state is also lost on a back-navigation.

### The footer is the product's mark, and the attribution moved rather than went

The footer carried the data provenance on every screen, which read as a
disclaimer stapled to the product. It could not simply be deleted: the match
records are ODC-BY 1.0 and **that licence requires attribution**. So the footer
is now the product's own name and copyright with a link, and the attribution
lives on `/about` alongside contact details.

Also removed from every reader-facing surface: the per-publisher `policy_note`,
which discussed access mechanics and crawling rules. That is an internal
compliance record, it belongs in the codebase, and on screen it read as an
admission rather than as information. The column stays so the decision remains
auditable; `app/news.py` no longer returns it and the News page no longer renders
it.

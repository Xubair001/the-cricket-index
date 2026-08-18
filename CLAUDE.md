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
Re-running match ingestion is cheap - each match is content-hashed; unchanged
matches are skipped, not re-parsed.

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

#### Two Temporal schedules, not one

`schedule.py` registers `icc-daily-sync` at 06:00 and `news-sync` every three
hours. Separate because the cadences genuinely differ - news moves hourly
where Cricsheet republishes every few days - and because they must fail
independently: a publisher blocking us should not put a red mark on the
workflow that ingests match data.

`NewsSyncWorkflow` runs its sources **concurrently**, unlike
`IccDailySyncWorkflow`'s Cricsheet leg which runs sequentially. The difference
is what each is bounded by: a bulk archive ingest is bounded by writes to the
one SQLite file and is worth not overlapping, whereas news fetching is bounded
by four independent publishers' politeness delays, and serialising them spends
the whole run waiting on the slowest while the other three idle.

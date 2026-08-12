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
```
Re-running is cheap — each match is content-hashed; unchanged matches are skipped, not re-parsed.

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

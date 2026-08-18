# The Cricket Index

A cricket data platform for exploring players, teams, matches, and statistics
across international cricket - with men's and women's cricket kept
structurally separate throughout, not just filtered in the UI.

## What's here

Three components, each independently runnable:

| Component | Stack | Role |
| --- | --- | --- |
| `ingestion/` | Python, [Temporal](https://temporal.io) | Downloads [Cricsheet](https://cricsheet.org) match data, parses it, and loads it into SQLite |
| `backend/` | Python, FastAPI, SQLAlchemy | Read-only REST API over the ingested data |
| `frontend/` | React, TypeScript, Vite, Tailwind | The dashboard - rankings, team/player/match profiles, search |

## Data model, in brief

- **Teams, competitions, and players are gender-scoped at the schema level.**
  Men's and women's "India" are different rows with different IDs - there is
  no shared team identity to accidentally leak across genders.
- **Competitions and seasons are first-class tables**, not string columns, so
  a new competition (a domestic league, say) is a new row, not a schema
  change. Adding the PSL required no migration.
- **International and franchise cricket never blend into one figure.** Teams
  are keyed by `team_type` as well as gender, and rankings are scoped to one
  competition type at a time - an unqualified ranking means internationals,
  and franchise cricket has to be asked for explicitly. Summing a player's
  Test, ODI, T20I and PSL runs into a single "career runs" number is not a
  statistic any cricket source reports.
- **A `data_granularity` flag on matches** (`full` vs `result_only`)
  anticipates a future, coarser-grained data source (e.g. historical
  pre-2001 results) without requiring another migration when it lands.
- **Missing data stays missing.** Player bio fields are `null` until a real
  source backs them - the API and UI both say "Not available," never a guess.
  The same rule governs playing status: a player is only labelled **Retired**
  when Wikidata carries a retirement or death date. A long gap in appearances
  shows as "Last played 2019" instead, because a gap equally means injury,
  being dropped, or cricket outside this dataset. In practice that means very
  few retirement labels - Wikidata records a retirement date for just 21 of
  ~31,700 cricketers - and showing fewer honest labels is the intended
  trade-off.
- **Official ICC rankings are kept apart from computed ones.** `/api/icc/*`
  serves ICC's published ratings, refreshed daily; `/api/rankings` serves
  figures this project derives from ball-by-ball data. They are never merged.
- **Fixtures are not matches.** `/api/fixtures` serves ICC's schedule -
  upcoming, live and recent - while `/api/matches` serves Cricsheet records
  with per-player figures. An upcoming fixture has no result and no stats, so
  the two stay in separate tables and separate endpoints.
- **Names appear both ways.** Cricsheet uses the scorecard convention
  (`JE Root` = Joseph Edward Root), which is what Wisden and ESPNcricinfo's own
  scorecards use. The UI shows the readable form (`Joe Root`) from Wikidata
  where available and keeps the scorecard form beside it, falling back to the
  scorecard name for the ~56% of players Wikidata doesn't cover.

See `ingestion/schema.sql` for the full schema.

## Data source & scope

All current data comes from [Cricsheet](https://cricsheet.org), licensed
under [ODC-BY 1.0](https://opendatacommons.org/licenses/by/1.0/) (reuse
permitted with attribution). This is an important scope boundary:
**Cricsheet's coverage starts in 2001 (men's) / 2003 (women's)** - players
whose careers ended before then aren't in this dataset. The platform doesn't
claim otherwise.

Currently ingested: Test, ODI, and T20I internationals (both genders), plus
the Pakistan Super League (men's only - there is no women's PSL).

## Prerequisites

- Python 3.12+
- Node 20+
- [Temporal CLI](https://docs.temporal.io/cli) (`temporal server start-dev`)

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cd frontend && npm install && cd ..
```

## Running it

Four processes, each in its own terminal:

```bash
# 1. Temporal dev server (workflow orchestration + Web UI at localhost:8233)
temporal server start-dev

# 2. Ingestion worker
cd ingestion && source ../venv/bin/activate && python worker.py

# 3. Backend API (localhost:8001)
cd backend && source ../venv/bin/activate && python -m uvicorn main:app --port 8001

# 4. Frontend (localhost:5173)
cd frontend && npm run dev
```

With the worker running, trigger ingestion per competition:

```bash
cd ingestion
python starter.py tests   # or: odis, t20is, psl
python starter.py icc     # ICC's official rankings
python starter.py enrich  # player bios from Wikidata
python starter.py news    # sports news from every enabled publisher
python starter.py news:guardian   # one publisher (guardian|icc|skysports|espncricinfo)
python schedule.py        # register the daily ICC refresh and the 3-hourly news sync
```

Re-running is cheap: each match is content-hashed, so unchanged matches are
skipped rather than re-parsed. News works the same way, keyed on a hash of
what was extracted rather than of the page.

### News sources

Four publishers, each read through the most structured mechanism that works
for it: the Guardian Open Platform API, the ICC's Google News sitemap plus
JSON-LD, Sky Sports RSS plus JSON-LD, and ESPNcricinfo's RSS alone (their
article pages return an Akamai 403 to any non-browser client). The BBC and
Cricbuzz are registered and **disabled** on publisher policy, with the reason
recorded and served from `/api/news/sources`.

Set `GUARDIAN_API_KEY` for your own key; it falls back to their open `test`
key, which is rate limited to 720/min and 50,000/day.

Check the archive against what should be true of it:

```bash
cd backend && python -m scripts.validate_news          # add --strict to gate a deploy
cd ingestion && python test_news_sources.py            # extraction unit tests
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branching model and
pre-push checklist.

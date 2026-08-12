# The Cricket Index

A cricket data platform for exploring players, teams, matches, and statistics
across international cricket — with men's and women's cricket kept
structurally separate throughout, not just filtered in the UI.

## What's here

Three components, each independently runnable:

| Component | Stack | Role |
| --- | --- | --- |
| `ingestion/` | Python, [Temporal](https://temporal.io) | Downloads [Cricsheet](https://cricsheet.org) match data, parses it, and loads it into SQLite |
| `backend/` | Python, FastAPI, SQLAlchemy | Read-only REST API over the ingested data |
| `frontend/` | React, TypeScript, Vite, Tailwind | The dashboard — rankings, team/player/match profiles, search |

## Data model, in brief

- **Teams, competitions, and players are gender-scoped at the schema level.**
  Men's and women's "India" are different rows with different IDs — there is
  no shared team identity to accidentally leak across genders.
- **Competitions and seasons are first-class tables**, not string columns, so
  a new competition (a domestic league, say) is a new row, not a schema
  change.
- **A `data_granularity` flag on matches** (`full` vs `result_only`)
  anticipates a future, coarser-grained data source (e.g. historical
  pre-2001 results) without requiring another migration when it lands.
- **Missing data stays missing.** Player bio fields (date of birth,
  birthplace, nationality) exist in the schema but are `null` until a real
  source backs them — the API and UI both say "Not available," never a
  guess.

See `ingestion/schema.sql` for the full schema.

## Data source & scope

All current data comes from [Cricsheet](https://cricsheet.org), licensed
under [ODC-BY 1.0](https://opendatacommons.org/licenses/by/1.0/) (reuse
permitted with attribution). This is an important scope boundary:
**Cricsheet's coverage starts in 2001 (men's) / 2003 (women's)** — players
whose careers ended before then aren't in this dataset. The platform doesn't
claim otherwise.

Currently ingested: Test, ODI, and T20I internationals, both genders.

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
python starter.py tests   # or: odis, t20is
```

Re-running is cheap: each match is content-hashed, so unchanged matches are
skipped rather than re-parsed.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branching model and
pre-push checklist.

# Contributing

## Branching model

Work flows in one direction only - never commit directly to `dev` or `main`.

```
feature/my-change ──PR──> dev ──PR──> main
```

| Branch | Purpose | Who writes to it |
| --- | --- | --- |
| `main` | Production. Always deployable. | Only a PR from `dev`. |
| `dev` | Integration. Everything lands here first. | Only a PR from a feature branch. |
| `feature/*`, `fix/*`, `chore/*` | Your work. Short-lived. | You, directly. |

## Day-to-day

Start every branch from an up-to-date `dev`:

```bash
git checkout dev
git pull
git checkout -b feature/player-search
```

Commit, push, and open a PR **into `dev`**:

```bash
git push -u origin feature/player-search
```

CI runs on the PR (frontend lint + build, backend compile + import). Once it's
green and reviewed, merge into `dev` and delete the branch.

## Releasing to `main`

When `dev` is in a state worth shipping, open a PR from `dev` into `main`.
This is the only way commits reach `main`. Don't squash it - a merge commit
keeps `dev` and `main` sharing history, so the next release PR shows only what's
actually new.

## Naming

- `feature/` - new capability (`feature/bowling-averages`)
- `fix/` - bug fix (`fix/nrr-rounding`)
- `chore/` - tooling, deps, docs (`chore/bump-vite`)

## Before you push

```bash
cd frontend && npm run lint && npm run build
cd ../backend && python -c "from main import app"
```

## What never gets committed

`.gitignore` covers these, but worth knowing why:

- `cricket.db`, `temporal.db` - rebuilt by the ingestion workflow
- `data/*.zip` - re-downloadable from [cricsheet.org](https://cricsheet.org)
- `venv/`, `node_modules/`, `*.log`

Together these are ~470 MB. The tracked source is under 500 KB - keep it that way.

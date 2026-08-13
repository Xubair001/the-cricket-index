"""The analytics layer.

Three process-lifetime caches sit behind this package, and they are *dependent*
rather than independent:

    impact.par_table  ->  opposition.table  ->  form (per verdict)  ->  leaderboard

`opposition` measures itself against par, and every form verdict is scored using
both. Clearing one and leaving the others is therefore not a partial refresh but
an inconsistent one -- a leaderboard rebuilt against a stale par table produces
figures that reconcile with nothing. Use `invalidate_all()` after an ingest
rather than reaching for a single module's `invalidate()`.
"""

from __future__ import annotations

from . import impact, leaderboard, opposition


def invalidate_all() -> None:
    """Drop every cached aggregate, in dependency order."""
    impact.invalidate()
    opposition.invalidate()
    leaderboard.invalidate()


__all__ = ["invalidate_all"]

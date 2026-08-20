"""Cached, paginated form boards.

Computing a board means scoring every player-match row in scope and running a
verdict per player -- about three seconds over men's internationals. That is far
too slow to do per request (§26: never recompute an expensive aggregate on the
request path), and it is also completely deterministic between ingests, so the
result is cached per scope for the process lifetime.

`invalidate()` exists for the same reason `impact.invalidate()` does: the cache
is only correct until the ingester writes new matches.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import cache

from ..models import Player
from ..names import preferred_name
from . import config, form

_cache: dict[tuple, list[dict]] = {}
_cache_version: tuple | None = None


def _cache_stale(db: Session) -> bool:
    """True when the ingester has committed since this module last built."""
    global _cache_version
    # `cache.generation` and not `cache.data_version`: the raw counter also moves
    # on a WAL checkpoint, which would drop this cache several times a minute
    # while the ingestion worker is up and nothing had actually changed.
    current = cache.generation(db)
    if _cache_version != current:
        _cache_version = current
        return True
    return False


def invalidate() -> None:
    _cache.clear()


def scope_label(competition_key: str | None, competition_type: str | None) -> str:
    """Human-readable description of what a board covers.

    Boards carry their scope because an unqualified one is not "all cricket" --
    it is internationals, and a franchise board has to be asked for. Saying so
    on the response is what stops the omission reading as a blend.
    """
    if competition_key:
        return competition_key
    return competition_type or config_default_scope()


def config_default_scope() -> str:
    # Mirrors queries.DEFAULT_RANKING_COMPETITION_TYPE without importing the
    # query layer into the analytics layer (§29 -- the dependency runs one way).
    return "international"


def _build(
    db: Session,
    *,
    gender: str,
    competition_key: str | None,
    competition_type: str | None,
) -> list[dict]:
    board = form.leaderboard(
        db,
        gender=gender,
        competition_key=competition_key,
        competition_type=competition_type,
    )
    names = {
        p.identifier: (preferred_name(p.name, p.display_name), p.name)
        for p in db.execute(select(Player)).scalars()
    }

    rows: list[dict] = []
    for leader in board:
        display, scorecard = names.get(leader.player_identifier, (None, None))
        v = leader.verdict
        rows.append(
            {
                "player_identifier": leader.player_identifier,
                "player_name": display or leader.player_identifier,
                "scorecard_name": scorecard,
                "state": v.state,
                "label": v.label,
                "delta_percent": round(v.delta_ratio * 100, 1) if v.delta_ratio is not None else None,
                "trend": v.trend,
                "confidence": round(v.confidence, 3),
                "recent_matches": v.recent_matches,
                "baseline_matches": v.baseline_matches,
                # The absolute standard, in par units where 1.0 is an average
                # appearance. Travels with every row because a percentage alone
                # cannot distinguish "improved to excellent" from "improved to
                # still below average" -- and both appear on a form board.
                "recent_mean": round(v.recent_mean, 2) if v.recent_mean is not None else None,
                "baseline_mean": round(v.baseline_mean, 2) if v.baseline_mean is not None else None,
                "explanation": v.explanation,
            }
        )
    return rows


def leaderboard_page(
    db: Session,
    *,
    gender: str,
    competition_key: str | None = None,
    competition_type: str | None = None,
    state: str | None = None,
    trend: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """One page of a form board, plus the total after filtering."""
    scope = competition_type
    if not competition_key and not competition_type:
        scope = config_default_scope()

    key = (gender, competition_key, scope)
    # Drop every board when the ingester commits: a form verdict built from the
    # old snapshot would otherwise be served until the process restarts.
    if _cache_stale(db):
        _cache.clear()
    if key not in _cache:
        _cache[key] = _build(
            db,
            gender=gender,
            competition_key=competition_key,
            competition_type=scope,
        )

    rows = _cache[key]
    if state:
        rows = [r for r in rows if r["state"] == state]
    if trend:
        rows = [r for r in rows if r["trend"] == trend]

    # "Out of form" reads best worst-first; every other view is best-first. The
    # cached list is already ordered best-first, so this is a reversal, not a
    # re-sort, and the evidence weighting behind the order is preserved.
    if state == "out_of_form":
        rows = list(reversed(rows))

    return rows[offset : offset + limit], len(rows)


__all__ = ["leaderboard_page", "invalidate", "scope_label", "config"]

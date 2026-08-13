"""Fixtures: upcoming schedule, live matches, and recent results.

Separate from /api/matches, which serves Cricsheet records with per-player
figures. A fixture is a calendar entry — an upcoming one has no result and no
player stats at all — so merging the two would put resultless rows into the
endpoint every aggregate depends on.
"""
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import queries, schemas
from ..database import get_db

router = APIRouter(prefix="/api/fixtures", tags=["fixtures"])


@router.get("", response_model=schemas.PaginatedFixtures)
def list_fixtures(
    # gender is optional here, unlike the browse endpoints: a fixtures calendar
    # is a legitimate cross-gender view, and ICC publishes them in one feed.
    gender: str | None = Query(default=None, pattern="^(male|female)$"),
    window: Literal["upcoming", "live", "results"] = "upcoming",
    match_type: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.PaginatedFixtures:
    items, total = queries.list_fixtures(db, gender, window, match_type, limit, offset)
    return schemas.PaginatedFixtures(
        total=total,
        limit=limit,
        offset=offset,
        window=window,
        last_synced=queries.fixtures_last_synced(db),
        items=items,
    )


@router.get("/match-types")
def match_types(
    gender: str | None = Query(default=None, pattern="^(male|female)$"),
    db: Session = Depends(get_db),
) -> dict:
    """Read from the data, so a new format ICC starts publishing just appears."""
    return {"match_types": queries.fixture_match_types(db, gender)}

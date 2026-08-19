"""What competitions this dataset actually holds.

Exists because the frontend had the list hardcoded in five separate files, each
a copy of the same four entries, and each mixing internationals and franchise
cricket into one flat dropdown whose blank option silently meant "all
internationals". That is the same coupling `app/validation.py` already refuses
on the backend: competition keys are validated against the `competitions` table
rather than a regex, precisely so that ingesting a new league stays a data
change. A hardcoded list in the client puts that code change straight back.

`type` is what makes the two families separable, and it is the API's own
vocabulary ('international' | 'domestic_league') rather than a UI label, so a
client can pass it straight back as `competition_type`.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..models import Competition, Match

router = APIRouter(prefix="/api/competitions", tags=["competitions"])


@router.get("", response_model=list[schemas.CompetitionInfo])
def list_competitions(
    # Optional, unlike the browse endpoints. A client building a scope switcher
    # wants to know what exists before it has a gender to ask about, and
    # competitions are keyed by (key, gender) so the same key appears for both.
    gender: str | None = Query(default=None, pattern="^(male|female)$"),
    db: Session = Depends(get_db),
) -> list[schemas.CompetitionInfo]:
    """Every competition, with how many matches it holds in this scope.

    Grouped by key rather than returned per row: `competitions` is keyed by
    (key, gender), so an ungendered request would otherwise list "Test" twice
    and a switcher built from it would show duplicates.
    """
    stmt = (
        select(
            Competition.key,
            func.min(Competition.display_name),
            func.min(Competition.type),
            func.count(Match.match_id),
        )
        .outerjoin(Match, Match.competition_id == Competition.competition_id)
        .group_by(Competition.key)
        .order_by(func.min(Competition.type), func.count(Match.match_id).desc())
    )
    if gender is not None:
        stmt = stmt.where(Competition.gender == gender)

    return [
        schemas.CompetitionInfo(
            key=key, display_name=display_name, type=ctype, matches=matches
        )
        for key, display_name, ctype, matches in db.execute(stmt).all()
    ]

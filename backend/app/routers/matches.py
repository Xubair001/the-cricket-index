from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import queries, schemas
from ..database import get_db

router = APIRouter(prefix="/api/matches", tags=["matches"])


@router.get("", response_model=schemas.PaginatedMatches)
def list_matches(
    gender: str = Query(pattern="^(male|female)$"),
    competition: str | None = Query(default=None, pattern="^(tests|odis|t20is)$"),
    team_id: int | None = Query(default=None),
    season: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.PaginatedMatches:
    items, total = queries.list_matches(
        db, gender, competition, team_id, season, search, limit, offset
    )
    return schemas.PaginatedMatches(total=total, limit=limit, offset=offset, items=items)


@router.get("/{match_id}", response_model=schemas.MatchDetail)
def match_detail(match_id: str, db: Session = Depends(get_db)) -> schemas.MatchDetail:
    # No gender param needed: match_id is already globally unique.
    detail = queries.get_match_detail(db, match_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"match '{match_id}' not found")
    return detail

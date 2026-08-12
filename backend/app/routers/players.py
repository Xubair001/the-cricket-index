from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import queries, schemas
from ..database import get_db

router = APIRouter(prefix="/api/players", tags=["players"])


@router.get("", response_model=schemas.PaginatedPlayers)
def list_players(
    gender: str = Query(pattern="^(male|female)$"),
    search: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.PaginatedPlayers:
    items, total = queries.search_players(db, gender, search, limit, offset)
    return schemas.PaginatedPlayers(total=total, limit=limit, offset=offset, items=items)


@router.get("/{identifier}", response_model=schemas.PlayerDetail)
def player_detail(identifier: str, db: Session = Depends(get_db)) -> schemas.PlayerDetail:
    # No gender param needed: a player's identifier already uniquely
    # determines them (and their gender) -- no cross-gender ambiguity to
    # resolve, unlike team names.
    detail = queries.get_player_detail(db, identifier)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"player '{identifier}' not found")
    return detail

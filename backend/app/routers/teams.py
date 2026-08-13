from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import queries, schemas, validation
from ..database import get_db

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("", response_model=schemas.PaginatedTeams)
def list_teams(
    gender: str = Query(pattern="^(male|female)$"),
    team_type: str | None = Query(default=None),
    # The ceiling is higher than other lists because this endpoint also backs
    # the team filter on the Matches page, which needs every side at once to
    # populate a select. A browsing page still asks for a page.
    limit: int = Query(default=25, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.PaginatedTeams:
    items, total = queries.get_teams_summary(
        db, gender, validation.check_team_type(db, team_type), limit, offset
    )
    return schemas.PaginatedTeams(total=total, limit=limit, offset=offset, items=items)


@router.get("/{team_id}", response_model=schemas.TeamDetail)
def team_detail(team_id: int, db: Session = Depends(get_db)) -> schemas.TeamDetail:
    detail = queries.get_team_detail(db, team_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"team '{team_id}' not found")
    return detail


@router.get("/{team_a_id}/head-to-head/{team_b_id}", response_model=schemas.HeadToHead)
def head_to_head(team_a_id: int, team_b_id: int, db: Session = Depends(get_db)) -> schemas.HeadToHead:
    result = queries.get_head_to_head(db, team_a_id, team_b_id)
    if result is None:
        raise HTTPException(status_code=404, detail="one or both teams not found")
    return result

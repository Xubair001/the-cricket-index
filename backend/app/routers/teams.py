from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import queries, schemas
from ..database import get_db

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("", response_model=list[schemas.TeamSummary])
def list_teams(
    gender: str = Query(pattern="^(male|female)$"),
    db: Session = Depends(get_db),
) -> list[schemas.TeamSummary]:
    return queries.get_teams_summary(db, gender)


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

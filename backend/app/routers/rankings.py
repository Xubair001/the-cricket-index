from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import queries, schemas, validation
from ..analytics import leaderboard as form_board
from ..database import get_db

router = APIRouter(prefix="/api/rankings", tags=["rankings"])

# Both endpoints take `competition` (one competition, e.g. 'tests' or 'psl') and
# `competition_type` ('international' | 'domestic_league'). They are two
# granularities of the same scope, never a blend: with neither set, rankings
# fall back to internationals rather than summing every format together. See
# queries._ranking_scope.


@router.get("/batting")
def batting_rankings(
    gender: str = Query(pattern="^(male|female)$"),
    competition: str | None = Query(default=None),
    competition_type: str | None = Query(default=None),
    min_matches: int = Query(default=10, ge=1),
    sort_by: Literal["runs", "average", "strike_rate", "matches"] = "runs",
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    competition = validation.check_competition_key(db, competition)
    competition_type = validation.check_competition_type(db, competition_type)
    rows, total = queries.get_batting_rankings(
        db, gender, competition, min_matches, sort_by, limit, offset, competition_type
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [schemas.BattingRankingRow(**r) for r in rows],
    }


@router.get("/bowling")
def bowling_rankings(
    gender: str = Query(pattern="^(male|female)$"),
    competition: str | None = Query(default=None),
    competition_type: str | None = Query(default=None),
    min_matches: int = Query(default=10, ge=1),
    sort_by: Literal["wickets", "average", "economy", "matches"] = "wickets",
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    competition = validation.check_competition_key(db, competition)
    competition_type = validation.check_competition_type(db, competition_type)
    rows, total = queries.get_bowling_rankings(
        db, gender, competition, min_matches, sort_by, limit, offset, competition_type
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [schemas.BowlingRankingRow(**r) for r in rows],
    }


@router.get("/form", response_model=schemas.FormLeaderboard)
def form_leaderboard(
    gender: str = Query(pattern="^(male|female)$"),
    state: str | None = Query(
        default=None,
        description="Filter to one form state, e.g. in_form or out_of_form",
    ),
    trend: str | None = Query(default=None, pattern="^(rising|flat|falling|unknown)$"),
    competition: str | None = Query(default=None),
    competition_type: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.FormLeaderboard:
    """Players ranked by how far their current form sits above their own baseline.

    This is not a "best players" list and must not be presented as one: it ranks
    *change*, so a modest player having a good run outranks a great player
    playing normally. That is the point -- who to look at now -- and it is why
    this lives beside the batting/bowling rankings rather than replacing them.
    """
    comp_key = validation.check_competition_key(db, competition)
    comp_type = validation.check_competition_type(db, competition_type)
    rows, total = form_board.leaderboard_page(
        db,
        gender=gender,
        competition_key=comp_key,
        competition_type=comp_type,
        state=state,
        trend=trend,
        limit=limit,
        offset=offset,
    )
    return schemas.FormLeaderboard(
        total=total,
        limit=limit,
        offset=offset,
        scope=form_board.scope_label(comp_key, comp_type),
        items=[schemas.FormLeaderRow(**r) for r in rows],
    )

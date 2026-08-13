"""ICC's official published rankings.

Deliberately a separate router from /api/rankings: those are computed from
Cricsheet ball-by-ball data by this project, these are ICC's own ratings
fetched from their feed. Presenting them under one path would invite reading a
number this app derived as an official one, or vice versa.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import queries, schemas
from ..database import get_db

router = APIRouter(prefix="/api/icc", tags=["icc"])


@router.get("/rank-types")
def rank_types(db: Session = Depends(get_db)) -> dict:
    """What's available, read from the data rather than hardcoded."""
    return {
        "players": queries.icc_player_rank_types(db),
        "teams": queries.icc_team_rank_types(db),
    }


@router.get("/players/{rank_type}", response_model=schemas.IccRankingTable)
def player_ranking(rank_type: str, db: Session = Depends(get_db)) -> schemas.IccRankingTable:
    table = queries.get_icc_player_ranking(db, rank_type)
    if table is None:
        raise HTTPException(
            status_code=404,
            detail=f"no ICC player ranking stored for '{rank_type}'; "
                   f"available: {queries.icc_player_rank_types(db)}",
        )
    return table


@router.get("/teams/{rank_type}", response_model=schemas.IccTeamRankingTable)
def team_ranking(rank_type: str, db: Session = Depends(get_db)) -> schemas.IccTeamRankingTable:
    table = queries.get_icc_team_ranking(db, rank_type)
    if table is None:
        raise HTTPException(
            status_code=404,
            detail=f"no ICC team ranking stored for '{rank_type}'; "
                   f"available: {queries.icc_team_rank_types(db)}",
        )
    return table

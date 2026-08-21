"""ICC's official published rankings.

Deliberately a separate router from /api/rankings: those are computed from
Cricsheet ball-by-ball data by this project, these are ICC's own ratings
fetched from their feed. Presenting them under one path would invite reading a
number this app derived as an official one, or vice versa.
"""
import dataclasses

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import queries, schemas, validation
from ..analytics import icc_movement as movement_mod
from ..database import get_db
from ..models import IccPlayerRanking

router = APIRouter(prefix="/api/icc", tags=["icc"])


@router.get("/rank-types")
def rank_types(db: Session = Depends(get_db)) -> dict:
    """What's available, read from the data rather than hardcoded."""
    return {
        "players": queries.icc_player_rank_types(db),
        "teams": queries.icc_team_rank_types(db),
    }


@router.get("/players/{rank_type}", response_model=schemas.IccRankingTable)
def player_ranking(
    rank_type: str,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.IccRankingTable:
    table = queries.get_icc_player_ranking(db, rank_type, limit, offset)
    if table is None:
        raise HTTPException(
            status_code=404,
            detail=f"no ICC player ranking stored for '{validation.echo(rank_type)}'; "
                   f"available: {queries.icc_player_rank_types(db)}",
        )
    return table


@router.get("/teams/{rank_type}", response_model=schemas.IccTeamRankingTable)
def team_ranking(
    rank_type: str,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.IccTeamRankingTable:
    table = queries.get_icc_team_ranking(db, rank_type, limit, offset)
    if table is None:
        raise HTTPException(
            status_code=404,
            detail=f"no ICC team ranking stored for '{validation.echo(rank_type)}'; "
                   f"available: {queries.icc_team_rank_types(db)}",
        )
    return table

@router.get("/movement/{rank_type}", response_model=schemas.IccMovementReport)
def player_movement(
    rank_type: str,
    db: Session = Depends(get_db),
) -> schemas.IccMovementReport:
    """Who moved in one ICC ranking since the previous published list (§8).

    Deliberately movement rather than a trend. `icc_player_rankings` is keyed on
    `rank_date` so a history is storable, but only a handful of dated lists are
    held so far - the daily sync began recently and the ICC republishes about
    weekly - and `snapshots` says how many. A chart over that would present a
    few weeks as a career.

    The comparison pair is resolved PER RANK TYPE, because each type has its own
    capture dates: taking the two most recent dates globally compares a men's
    Test list against a date only the women's lists have, and returns nothing.
    """
    valid = {r for (r,) in db.execute(
        select(IccPlayerRanking.rank_type).distinct()
    ).all()}
    if rank_type not in valid:
        raise HTTPException(
            status_code=404,
            detail=(
                f"unknown rank type '{validation.echo(rank_type)}'; "
                f"available: {sorted(valid)}"
            ),
        )
    result = movement_mod.movement(db, rank_type)
    payload = dataclasses.asdict(result)
    return schemas.IccMovementReport(**payload)


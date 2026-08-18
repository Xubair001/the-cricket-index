from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import queries, schemas, validation
from ..analytics import match_intel
from ..database import get_db

router = APIRouter(prefix="/api/matches", tags=["matches"])


@router.get("", response_model=schemas.PaginatedMatches)
def list_matches(
    gender: str = Query(pattern="^(male|female)$"),
    competition: str | None = Query(default=None),
    team_id: int | None = Query(default=None, ge=1, le=validation.MAX_DB_INT),
    season: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=validation.MAX_SEARCH_LENGTH),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.PaginatedMatches:
    items, total = queries.list_matches(
        db,
        gender,
        validation.check_competition_key(db, competition),
        team_id,
        season,
        search,
        limit,
        offset,
    )
    return schemas.PaginatedMatches(total=total, limit=limit, offset=offset, items=items)


@router.get("/{match_id}/intelligence", response_model=schemas.MatchIntelligence)
def match_intelligence(match_id: str, db: Session = Depends(get_db)) -> schemas.MatchIntelligence:
    """What happened in a match and why it mattered (§22).

    Partnerships, bowling spells and the over-by-over shape of each innings, all
    read off the stored deliveries. Descriptive only: win probability and
    tactical events are deferred by §22 and are reported in `deferred` with the
    reason rather than approximated.
    """
    result = match_intel.compute(db, match_id)
    if result is None:
        # Distinguish "no such match" from "this match exists but its figures
        # came from a source with no deliveries". A bare 404 reads as the first
        # and hides the second, which is the difference between a broken link
        # and a real limit of the data.
        match = queries.get_match_detail(db, match_id)
        if match is None:
            raise HTTPException(status_code=404, detail=f"match '{validation.echo(match_id)}' not found")
        raise HTTPException(
            status_code=422 if match.source != "cricsheet" else 404,
            detail=(
                f"match '{match_id}' has no ball-by-ball data: its figures come from "
                f"the {match.source} scorecard feed, which publishes totals but not "
                f"deliveries. Partnerships, spells and the over-by-over shape are "
                f"therefore unavailable for it, not merely empty."
                if match.source != "cricsheet"
                else f"no ball-by-ball data stored for match '{match_id}'"
            ),
        )
    drop = lambda o: {k: v for k, v in vars(o).items() if k != "innings"}
    return schemas.MatchIntelligence(
        match_id=result.match_id,
        deferred=result.deferred,
        innings=[
            schemas.InningsIntelligence(
                innings=i.innings,
                batting_team=i.batting_team,
                runs=i.runs,
                wickets=i.wickets,
                balls=i.balls,
                run_rate=i.run_rate,
                partnerships=[schemas.PartnershipRow(**drop(x)) for x in i.partnerships],
                spells=[schemas.SpellRow(**drop(x)) for x in i.spells],
                overs=[schemas.OverPointRow(**drop(x)) for x in i.overs],
            )
            for i in result.innings
        ],
    )


@router.get("/{match_id}", response_model=schemas.MatchDetail)
def match_detail(match_id: str, db: Session = Depends(get_db)) -> schemas.MatchDetail:
    # No gender param needed: match_id is already globally unique.
    detail = queries.get_match_detail(db, match_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"match '{validation.echo(match_id)}' not found")
    return detail

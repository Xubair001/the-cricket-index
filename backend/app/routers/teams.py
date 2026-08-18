from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from sqlalchemy import select

from .. import flags, queries, schemas, validation
from ..analytics import squad as squad_mod
from ..database import get_db
from ..models import Team

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
def team_detail(
    team_id: int = Path(ge=1, le=validation.MAX_DB_INT),
    db: Session = Depends(get_db),
) -> schemas.TeamDetail:
    detail = queries.get_team_detail(db, team_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"team '{team_id}' not found")
    return detail


@router.get("/{team_id}/squad", response_model=schemas.SquadAnalysis)
def team_squad(
    team_id: int = Path(ge=1, le=validation.MAX_DB_INT),
    window_matches: int = Query(
        default=squad_mod.DEFAULT_WINDOW_MATCHES,
        ge=5,
        le=100,
        description="How many of the side's most recent matches count as current.",
    ),
    db: Session = Depends(get_db),
) -> schemas.SquadAnalysis:
    """Who a side is currently picking, and what that group is made of (§8).

    The window is the team's own last N matches rather than a calendar period:
    most of the ~110 international sides here play a handful of matches a year,
    and a date window would report them as having no squad at all.

    Roles are inferred from deliveries in this window, for this team. That is
    the only role signal the dataset carries, it is labelled as inferred on
    every row, and it deliberately stops short of wicketkeeper and opener,
    which no amount of thresholding can recover from these records.
    """
    result = squad_mod.squad(db, team_id, window_matches=window_matches)
    if result is None:
        raise HTTPException(status_code=404, detail=f"team '{team_id}' not found")

    team = db.execute(select(Team).where(Team.team_id == team_id)).scalar_one()
    countries = queries._player_country_map(db, team.gender)
    return schemas.SquadAnalysis(
        team_id=result.team_id,
        team_name=result.team_name,
        country_code=flags.country_code(team.name, team.team_type),
        gender=team.gender,
        team_type=team.team_type,
        window_matches=result.window_matches,
        matches_in_window=result.matches_in_window,
        first_match=result.first_match,
        last_match=result.last_match,
        members=[
            schemas.SquadMember(
                **vars(m),
                country=countries.get(m.player_identifier, (None, None))[0],
                country_code=countries.get(m.player_identifier, (None, None))[1],
            )
            for m in result.members
        ],
        role_counts=result.role_counts,
        runs_by_role=result.runs_by_role,
        wickets_by_role=result.wickets_by_role,
        top_run_share=result.top_run_share,
        top_wicket_share=result.top_wicket_share,
        reliance_top_n=squad_mod.RELIANCE_TOP_N,
        unavailable=[
            "Wicketkeeper - no source in this dataset states who kept",
            "Batting position and openers - ball-by-ball order is not retained",
            "Handedness - not carried by Cricsheet or the enrichment sources",
            "Availability and injury - no squad-list feed covers it",
        ],
    )


@router.get("/{team_a_id}/head-to-head/{team_b_id}", response_model=schemas.HeadToHead)
def head_to_head(
    team_a_id: int = Path(ge=1, le=validation.MAX_DB_INT),
    team_b_id: int = Path(ge=1, le=validation.MAX_DB_INT),
    db: Session = Depends(get_db),
) -> schemas.HeadToHead:
    result = queries.get_head_to_head(db, team_a_id, team_b_id)
    if result is None:
        raise HTTPException(status_code=404, detail="one or both teams not found")
    return result

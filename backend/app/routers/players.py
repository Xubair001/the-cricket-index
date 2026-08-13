from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import queries, schemas, validation
from ..analytics import config, form
from ..analytics import leaderboard as form_board
from ..database import get_db

router = APIRouter(prefix="/api/players", tags=["players"])


@router.get("/compare", response_model=schemas.PlayerComparison)
def compare_players(
    a: str = Query(description="player identifier"),
    b: str = Query(description="player identifier"),
    competition: str | None = Query(default=None),
    competition_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.PlayerComparison:
    """Head-to-head between two players within one competition scope.

    Declared before /{identifier} so 'compare' isn't captured as an identifier.
    """
    result = queries.get_player_comparison(
        db,
        a,
        b,
        validation.check_competition_key(db, competition),
        validation.check_competition_type(db, competition_type),
    )
    if isinstance(result, str):
        # 404 for a missing player, 422 for a pairing that can't be compared.
        raise HTTPException(status_code=404 if "not found" in result else 422, detail=result)
    return result


@router.get("/directory", response_model=schemas.PlayerDirectory)
def player_directory(
    gender: str = Query(pattern="^(male|female)$"),
    search: str | None = Query(default=None),
    competition: str | None = Query(default=None),
    competition_type: str | None = Query(default=None),
    team_id: int | None = Query(default=None),
    min_matches: int = Query(default=1, ge=1, le=500),
    min_balls_faced: int = Query(default=0, ge=0),
    min_balls_bowled: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, pattern="^(active|inactive|retired)$"),
    form_state: str | None = Query(default=None),
    sort_by: str = Query(default="matches"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.PlayerDirectory:
    """The discovery surface: aggregates, playing status and current form together.

    Declared before /{identifier} so 'directory' isn't captured as an identifier.
    """
    if sort_by not in queries.PLAYER_SORTS:
        raise HTTPException(
            status_code=422,
            detail=f"sort_by must be one of {sorted(queries.PLAYER_SORTS)}",
        )
    comp_key = validation.check_competition_key(db, competition)
    comp_type = validation.check_competition_type(db, competition_type)
    rows, total = queries.browse_players(
        db,
        gender,
        search=search,
        competition_key=comp_key,
        competition_type=comp_type,
        team_id=team_id,
        min_matches=min_matches,
        min_balls_faced=min_balls_faced,
        min_balls_bowled=min_balls_bowled,
        status=status,
        form_state=form_state,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    return schemas.PlayerDirectory(
        total=total,
        limit=limit,
        offset=offset,
        scope=form_board.scope_label(comp_key, comp_type),
        items=[schemas.DirectoryPlayer(**r) for r in rows],
    )


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


@router.get("/{identifier}/form", response_model=schemas.FormVerdict)
def player_form(
    identifier: str,
    recent: int = Query(default=None, ge=3, le=50, description="matches in the recent window"),
    baseline_days: int = Query(default=None, ge=30, le=3650),
    competition: str | None = Query(default=None),
    competition_type: str | None = Query(
        default=None,
        description=(
            "Scope the verdict to one competition type. Internationals and "
            "franchise cricket are not blended into a single form figure."
        ),
    ),
    db: Session = Depends(get_db),
) -> schemas.FormVerdict:
    """How this player is going, measured against their own recent baseline.

    Declared before /{identifier} would otherwise be reached, and separate from
    the profile endpoint because form is a different question from career
    record -- Rule 3 -- and is the expensive half.
    """
    if queries.get_player_detail(db, identifier) is None:
        raise HTTPException(status_code=404, detail=f"player '{identifier}' not found")

    verdict = form.assess(
        db,
        identifier,
        recent_matches=recent or config.DEFAULT_RECENT_MATCHES,
        baseline_days=baseline_days or config.DEFAULT_BASELINE_DAYS,
        competition_key=validation.check_competition_key(db, competition),
        competition_type=validation.check_competition_type(db, competition_type),
    )
    return schemas.FormVerdict(**verdict.as_dict())


@router.get("/{identifier}", response_model=schemas.PlayerDetail)
def player_detail(identifier: str, db: Session = Depends(get_db)) -> schemas.PlayerDetail:
    # No gender param needed: a player's identifier already uniquely
    # determines them (and their gender) -- no cross-gender ambiguity to
    # resolve, unlike team names.
    detail = queries.get_player_detail(db, identifier)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"player '{identifier}' not found")
    return detail

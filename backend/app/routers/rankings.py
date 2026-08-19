from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import queries, schemas, validation
from ..analytics import config as analytics_config, selection, leaderboard as form_board, performance_index as performance_index_mod
from ..models import Team
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
        items=[
            schemas.FormLeaderRow(**r)
            for r in queries._attach_country(rows, queries._player_country_map(db, gender))
        ],
    )


@router.get("/performance", response_model=schemas.PerformanceIndexPage)
def performance_index(
    gender: str = Query(pattern="^(male|female)$"),
    competition: str | None = Query(default=None),
    competition_type: str | None = Query(default=None),
    role: str | None = Query(default=None, pattern="^(batter|bowler|allrounder)$"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.PerformanceIndexPage:
    """The Performance Index (§14).

    Scoped, decomposed, and explicit about what it cannot yet include. An
    unscoped request is international cricket -- never "everything" -- for the
    same reason every other aggregate here refuses to blend competition types.
    """
    key = validation.check_competition_key(db, competition)
    ctype = validation.check_competition_type(db, competition_type)
    if not key and not ctype:
        ctype = queries.DEFAULT_RANKING_COMPETITION_TYPE

    items, total = performance_index_mod.page(
        db,
        gender=gender,
        competition_key=key,
        competition_type=ctype,
        role=role,
        limit=limit,
        offset=offset,
    )
    countries = queries._player_country_map(db, gender)
    return schemas.PerformanceIndexPage(
        scope=key or ctype or "international",
        gender=gender,
        total=total,
        limit=limit,
        offset=offset,
        window_matches=analytics_config.INDEX_WINDOW_MATCHES,
        min_matches=analytics_config.INDEX_MIN_MATCHES,
        components=[schemas.IndexComponent(**c) for c in performance_index_mod.describe_components()],
        items=[
            schemas.IndexRow(
                player_identifier=r.player_identifier,
                player_name=r.player_name,
                role=r.role,
                matches=r.matches,
                index=r.index,
                scores=r.scores,
                raw=r.raw,
                country=countries.get(r.player_identifier, (None, None))[0],
                country_code=countries.get(r.player_identifier, (None, None))[1],
            )
            for r in items
        ],
    )


@router.get("/best-xi", response_model=schemas.SelectedSide)
def best_side(
    gender: str = Query(pattern="^(male|female)$"),
    size: int = Query(default=11, ge=11, le=15),
    competition: str | None = Query(default=None),
    competition_type: str | None = Query(default=None),
    team_id: int | None = Query(default=None, ge=1, le=validation.MAX_DB_INT),
    # 'all_time' stays the default so an existing link returns the side it
    # always did. 'current' answers a different question and says so in the
    # response rather than quietly changing what the same heading means.
    pool: str = Query(default="all_time", pattern="^(all_time|current)$"),
    db: Session = Depends(get_db),
) -> schemas.SelectedSide:
    """Best XI or XV for a scope (§18).

    Works identically for internationals and for a franchise league -- picking a
    PSL side is the same question as picking a Test side, asked of a different
    scope, which is what makes this usable for a league draft.

    `size` runs 11 to 15: a XV is a XI plus cover, so the same role shape is
    scaled rather than a different side being picked.

    `pool` chooses the question. 'all_time' picks from everyone who has played
    enough in the scope, including players who retired years ago. 'current'
    restricts it to players still in the picture - last appearance in this
    scope within a year of the scope's most recent match, and no sourced
    retirement or date of death - and leans the weighting towards recent
    evidence. The response reports the pool size, the anchor date and the
    weights, so which question was answered is visible on the page.
    """
    key = validation.check_competition_key(db, competition)
    ctype = validation.check_competition_type(db, competition_type)
    if not key and not ctype:
        ctype = queries.DEFAULT_RANKING_COMPETITION_TYPE

    result = selection.select_side(
        db,
        gender=gender,
        size=size,
        competition_key=key,
        competition_type=ctype,
        team_id=team_id,
        pool=pool,
    )
    team_name = None
    if team_id is not None:
        team = db.get(Team, team_id)
        team_name = team.name if team else None

    return schemas.SelectedSide(
        scope=result.scope,
        gender=result.gender,
        size=result.size,
        team_id=result.team_id,
        team_name=team_name,
        picks=[schemas.SelectionPick(**vars(p)) for p in result.picks],
        shape=result.shape,
        unavailable=result.unavailable,
        notes=result.notes,
        pool=result.pool,
        pool_size=result.pool_size,
        pool_considered=result.pool_considered,
        reference_date=result.reference_date,
        cutoff_date=result.cutoff_date,
        weights=result.weights,
    )

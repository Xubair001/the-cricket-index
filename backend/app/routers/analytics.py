"""Analytics endpoints -- the vocabulary and the workings, not one screen's data.

These are deliberately domain-shaped rather than component-shaped. `/periods`
exists so the UI renders whatever windows the analytics layer actually supports
instead of keeping a second copy of that list that drifts; `/par` exists because
§30 requires that a derived figure can be traced to the numbers behind it, and
every impact score in the product is computed against these.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import queries, schemas, validation
from sqlalchemy import func, select

from ..models import Match
from .. import venues
from ..analytics import explorer as explorer_mod, impact, periods
from ..database import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/periods", response_model=list[schemas.PeriodOption])
def list_periods() -> list[schemas.PeriodOption]:
    """The period windows the analytics layer supports."""
    return [schemas.PeriodOption(**p) for p in periods.describe()]


@router.get("/par", response_model=list[schemas.ParFigures])
def par_figures(db: Session = Depends(get_db)) -> list[schemas.ParFigures]:
    """Measured par performance per competition and gender.

    Every one of these is computed from this dataset, not configured. They are
    what "a typical performance" means everywhere else in the product, so
    exposing them is what lets a user check an impact figure rather than take it
    on trust.
    """
    table = impact.par_table(db)
    return [
        schemas.ParFigures(
            competition_key=key,
            gender=gender,
            scoring_rate=round(par.scoring_rate, 2),
            economy=round(par.economy, 2),
            runs_per_wicket=round(par.runs_per_wicket, 2),
            mean_impact=round(par.mean_impact, 2),
            balls=par.balls,
        )
        for (key, gender), par in sorted(table.slices().items())
    ]


@router.get("/venues", response_model=list[schemas.VenueOption])
def list_venues(
    gender: str | None = Query(default=None, pattern="^(male|female)$"),
    db: Session = Depends(get_db),
) -> list[schemas.VenueOption]:
    """Canonical grounds, with how many matches each actually has.

    The count is the point: it is the normalised figure, so a ground Cricsheet
    spells six different ways appears once with its whole history.
    """
    stmt = select(Match.venue, Match.city, func.count()).where(Match.venue.is_not(None))
    if gender:
        stmt = stmt.where(Match.gender == gender)
    stmt = stmt.group_by(Match.venue, Match.city)

    grouped: dict[str, dict] = {}
    for raw, city, count in db.execute(stmt).all():
        name = venues.canonical(raw, city)
        if not name:
            continue
        entry = grouped.setdefault(name, {"venue": name, "city": city, "matches": 0, "raw_spellings": 0})
        entry["matches"] += count
        entry["raw_spellings"] += 1
        if not entry["city"]:
            entry["city"] = city
    out = sorted(grouped.values(), key=lambda e: (-e["matches"], e["venue"]))
    return [schemas.VenueOption(**e) for e in out]


# ---------------------------------------------------------------------------
# Explorers (§21)
# ---------------------------------------------------------------------------
#
# Three views over one filter model. Each explorer admits only the disciplines
# that belong in it -- batters and all-rounders on the batting board, bowlers
# and all-rounders on the bowling one, all-rounders alone on the all-round view
# -- because a volume floor alone lets specialists leak into the wrong list.
#
# The venue filter matches on the CANONICAL ground (app/venues.py), not the raw
# string. Cricsheet files one ground under several spellings -- 593 strings for
# 396 grounds -- so a filter on the raw column would return a third of a
# ground's matches while appearing to return all of them.


@router.get("/{explorer}", response_model=schemas.ExplorerPage)
def explore(
    explorer: str,
    gender: str = Query(pattern="^(male|female)$"),
    competition: str | None = Query(default=None),
    competition_type: str | None = Query(default=None),
    team_id: int | None = Query(default=None),
    opposition_team_id: int | None = Query(default=None),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    min_innings: int = Query(default=explorer_mod.DEFAULT_MIN_INNINGS, ge=1, le=500),
    min_balls: int | None = Query(default=None, ge=0, le=100_000),
    # Narrows *within* an explorer's eligible set. Each explorer already
    # excludes the opposite specialism, so this is for asking a batting board
    # for all-rounders only, not for putting a bowler on it.
    role: str | None = Query(default=None, pattern="^(batter|bowler|allrounder)$"),
    # Canonical ground name. Now a real filter rather than an absent one: see
    # app/venues.py for why it could not ship until venues were normalised.
    venue: str | None = Query(default=None, max_length=120),
    sort_by: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.ExplorerPage:
    if explorer not in explorer_mod.BUILDERS:
        raise HTTPException(
            status_code=404,
            detail=f"unknown explorer '{explorer}'; available: {sorted(explorer_mod.BUILDERS)}",
        )

    sorts = explorer_mod.SORTS[explorer]
    if sort_by is None:
        sort_by = next(iter(sorts))
    if sort_by not in sorts:
        raise HTTPException(
            status_code=422,
            detail=f"cannot sort '{explorer}' by '{sort_by}'; available: {sorted(sorts)}",
        )

    # The qualification that makes a rate leaderboard mean anything differs by
    # discipline -- balls faced for batting, balls bowled for bowling -- so the
    # default depends on which explorer was asked for.
    if min_balls is None:
        min_balls = {
            "batting": explorer_mod.DEFAULT_MIN_BALLS_FACED,
            "bowling": explorer_mod.DEFAULT_MIN_BALLS_BOWLED,
        }.get(explorer, 0)

    filters = explorer_mod.ExplorerFilters(
        gender=gender,
        competition_key=validation.check_competition_key(db, competition),
        competition_type=validation.check_competition_type(db, competition_type),
        team_id=team_id,
        opposition_team_id=opposition_team_id,
        date_from=date_from,
        date_to=date_to,
        min_innings=min_innings,
        min_balls=min_balls,
        venue=venue,
        role=role,
    )
    items, total = explorer_mod.page(db, explorer, filters, sort_by, limit, offset)
    return schemas.ExplorerPage(
        explorer=explorer,
        total=total,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        filters=filters.describe(explorer),
        sorts=sorted(sorts),
        # ExplorerRow allows extra fields, so country/country_code ride along
        # without the model having to know about them.
        items=[
            schemas.ExplorerRow(**row)
            for row in queries._attach_country(
                items, queries._player_country_map(db, filters.gender)
            )
        ],
    )

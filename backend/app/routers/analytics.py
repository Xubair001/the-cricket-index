"""Analytics endpoints -- the vocabulary and the workings, not one screen's data.

These are deliberately domain-shaped rather than component-shaped. `/periods`
exists so the UI renders whatever windows the analytics layer actually supports
instead of keeping a second copy of that list that drifts; `/par` exists because
§30 requires that a derived figure can be traced to the numbers behind it, and
every impact score in the product is computed against these.
"""

import dataclasses

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import queries, schemas, validation
from sqlalchemy import func, select

from ..models import Match, Team
from .. import flags, venues
from ..analytics import (
    explorer as explorer_mod,
    impact,
    opposition as opposition_mod,
    periods,
    venue as venue_mod,
)
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


@router.get("/ground-character", response_model=list[schemas.GroundCharacter])
def ground_character(
    gender: str = Query(pattern="^(male|female)$"),
    competition: str = Query(description="one competition key; required"),
    min_matches: int = Query(default=1, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[schemas.GroundCharacter]:
    """Every ground in one competition, on the two axes that describe a pitch.

    Declared before `/venues/{venue_name:path}`, which would otherwise swallow
    the path.

    `competition` is REQUIRED rather than optional. A ground hosting Tests and
    T20Is has two characters and one figure describes neither, so there is no
    sensible unscoped answer to give - and defaulting to one silently would be
    the "unscoped means everything" mistake §6 exists to prevent.
    """
    key = validation.check_competition_key(db, competition)
    if not key:
        raise HTTPException(
            status_code=422,
            detail=f"unknown competition '{validation.echo(competition)}'",
        )
    rows = venue_mod.character(db, gender=gender, competition_key=key)
    return [
        schemas.GroundCharacter(**dataclasses.asdict(g))
        for g in rows
        if g.matches >= min_matches
    ]


@router.get("/venues/{venue_name:path}", response_model=schemas.VenueProfile)
def venue_profile(
    venue_name: str,
    gender: str = Query(pattern="^(male|female)$"),
    competition: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.VenueProfile:
    """One ground's character (§20).

    Keyed on the canonical ground, so every spelling of it contributes. The
    path is `:path` because canonical names carry commas, apostrophes and
    parenthesised cities ("County Ground (Bristol)").
    """
    result = venue_mod.profile(
        db,
        venue_name,
        gender=gender,
        competition_key=validation.check_competition_key(db, competition),
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"no ground matching '{validation.echo(venue_name)}'")
    return schemas.VenueProfile(
        venue=result.venue,
        city=result.city,
        matches=result.matches,
        first_match=result.first_match,
        last_match=result.last_match,
        raw_spellings=result.raw_spellings,
        formats=[schemas.VenueFormatStats(**vars(f)) for f in result.formats],
    )


@router.get("/opposition", response_model=schemas.TeamStrengthTable)
def team_strength(
    gender: str = Query(pattern="^(male|female)$"),
    competition_type: str = Query(default="international"),
    min_matches: int = Query(default=20, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> schemas.TeamStrengthTable:
    """Fitted difficulty per side, hardest first, with its era curve.

    This is the model the form boards and the Performance Index already use to
    scale every performance; exposing it is what lets a reader check the
    adjustment rather than take it on trust (§30).
    """
    ctype = validation.check_competition_type(db, competition_type) or "international"
    MIN_MATCHES_PER_ERA = 15
    table = opposition_mod.table(db)

    teams = {
        t.team_id: t
        for t in db.execute(
            select(Team).where(Team.gender == gender, Team.team_type == ctype)
        ).scalars()
    }
    eras = sorted({e for (_t, e) in table.era_keys() if e != "unknown"})

    rows: list[schemas.TeamStrengthRow] = []
    for team_id, team in teams.items():
        long_run, n = table.index(team_id)
        if n < min_matches:
            continue
        # `era_index`, not `index`: the latter falls back to the long-run figure
        # for an era the side never played, which would draw a flat line where
        # there is no cricket at all.
        series = []
        for era in eras:
            found = table.era_index(team_id, era)
            if not found:
                continue
            idx, count = found
            series.append(
                schemas.TeamStrengthEra(
                    era=era,
                    difficulty=round(1 / idx, 3) if idx else 1.0,
                    matches=count,
                    reliable=count >= MIN_MATCHES_PER_ERA,
                )
            )
        rows.append(
            schemas.TeamStrengthRow(
                team_id=team_id,
                name=team.name,
                country_code=flags.country_code(team.name, team.team_type),
                matches=n,
                difficulty=round(1 / long_run, 3) if long_run else 1.0,
                # Only from an era with enough cricket behind it. Spain's five
                # matches in the 2020s produced a "now" of 1.14 -- above
                # Australia -- which is sample size, not strength.
                current_difficulty=(
                    series[-1].difficulty if series and series[-1].reliable else None
                ),
                eras=series,
            )
        )
    rows.sort(key=lambda r: -r.difficulty)
    return schemas.TeamStrengthTable(
        gender=gender,
        competition_type=ctype,
        total=len(rows),
        validated_against_icc="Spearman rho +0.81 to +0.83 across Test, ODI and T20I",
        items=rows,
    )


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
    team_id: int | None = Query(default=None, ge=1, le=validation.MAX_DB_INT),
    opposition_team_id: int | None = Query(default=None, ge=1, le=validation.MAX_DB_INT),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    # None means DERIVE from the slice, the same as `min_balls`. A fixed default
    # of 5 matches is fair on a career board and unreachable at one ground
    # against one side, and it was the larger half of the empty-slice bug.
    min_innings: int | None = Query(default=None, ge=1, le=500),
    min_balls: int | None = Query(default=None, ge=0, le=100_000),
    # Narrows *within* an explorer's eligible set. Each explorer already
    # excludes the opposite specialism, so this is for asking a batting board
    # for all-rounders only, not for putting a bowler on it.
    role: str | None = Query(default=None, pattern="^(batter|bowler|allrounder)$"),
    # Canonical ground name. Now a real filter rather than an absent one: see
    # app/venues.py for why it could not ship until venues were normalised.
    venue: str | None = Query(default=None, max_length=120),
    # A window over this slice. A date-bounded one resolves into date_from and
    # date_to below, so `period=last12m` and an explicit range are the same
    # mechanism and links already carrying raw dates keep resolving. Only a
    # count-bounded window needs its own path.
    period: str | None = Query(default=None),
    sort_by: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.ExplorerPage:
    if explorer not in explorer_mod.BUILDERS:
        raise HTTPException(
            status_code=404,
            detail=f"unknown explorer '{validation.echo(explorer)}'; available: {sorted(explorer_mod.BUILDERS)}",
        )

    sorts = explorer_mod.SORTS[explorer]
    if sort_by is None:
        sort_by = next(iter(sorts))
    if sort_by not in sorts:
        raise HTTPException(
            status_code=422,
            detail=f"cannot sort '{validation.echo(explorer)}' by '{validation.echo(sort_by)}'; available: {sorted(sorts)}",
        )

    # `min_balls` is passed through as None when the caller did not name one, and
    # the analytics layer derives it FROM THE SLICE. The old behaviour -
    # substituting a fixed per-discipline default here - is what made a narrowed
    # view look empty: 200 balls faced is a fair qualification for an all-time
    # batting board and unreachable at one ground against one side, so
    # "Bellerive Oval against Australia" returned 0 players of 148.

    competition_key = validation.check_competition_key(db, competition)
    competition_type = validation.check_competition_type(db, competition_type)
    window = validation.check_period(period)

    # A date-bounded window becomes a date range, INTERSECTED with any explicit
    # one rather than overriding it: two ways of narrowing the same axis should
    # compose, which is the rule `_competition_scoped` already follows for a key
    # and a type given together.
    last_matches = None
    if window is not None:
        if window.is_count_bounded:
            last_matches = window.matches
        else:
            anchor = queries.applied_period(
                db, gender, competition_key, competition_type, window
            )["anchor"]
            bounds = window.to_date_bounds(anchor)
            if bounds:
                start, end = bounds
                date_from = max(x for x in (date_from, start) if x) if (date_from or start) else None
                date_to = min(x for x in (date_to, end) if x) if (date_to or end) else None

    filters = explorer_mod.ExplorerFilters(
        gender=gender,
        competition_key=competition_key,
        competition_type=competition_type,
        team_id=team_id,
        opposition_team_id=opposition_team_id,
        date_from=date_from,
        date_to=date_to,
        min_innings=min_innings,
        min_balls=min_balls,
        venue=venue,
        role=role,
        last_matches=last_matches,
    )
    items, total, before_floor, applied_balls, applied_innings = explorer_mod.page(
        db, explorer, filters, sort_by, limit, offset
    )
    return schemas.ExplorerPage(
        explorer=explorer,
        total=total,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        filters=filters.describe(explorer),
        sorts=sorted(sorts),
        period=periods.applied(
            window,
            queries.applied_period(db, gender, competition_key, competition_type, window)["anchor"],
        ),
        # Both counts, because their being different IS the story on a narrowed
        # slice. Without the "before" figure a reader cannot tell "no cricket
        # here" from "the volume floor removed all of it".
        total_before_volume_floor=before_floor,
        applied_min_balls=applied_balls,
        applied_min_innings=applied_innings,
        # ExplorerRow allows extra fields, so country/country_code ride along
        # without the model having to know about them.
        items=[
            schemas.ExplorerRow(**row)
            for row in queries._attach_country(
                items, queries._player_country_map(db, filters.gender)
            )
        ],
    )

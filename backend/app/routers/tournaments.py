"""Tournaments: World Cups, Champions Trophy, Asia Cup and the rest.

Separate from `/api/matches`, which lists individual matches, and from
`/api/competitions`, which lists formats. A tournament sits between them: it is
a named event inside one competition, run over several editions.

Only multi-team events are served. `matches.event_name` names 1,276 distinct
events and 1,013 of them are bilateral tours; a list including those would bury
the World Cup under a thousand two-team series. See app/tournaments.py for why
that test is the number of sides rather than anything in the name.
"""
import dataclasses

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import schemas, tournaments, validation
from ..database import get_db

router = APIRouter(prefix="/api/tournaments", tags=["tournaments"])


@router.get("", response_model=list[schemas.TournamentSummary])
def list_tournaments(
    gender: str = Query(pattern="^(male|female)$"),
    competition_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[schemas.TournamentSummary]:
    """Every multi-team event in the scope, flagship ICC tournaments first.

    The ordering is presentation only. Nothing is hidden for not being a
    flagship, and the full list is returned so the tail is visibly there.
    """
    rows = tournaments.list_tournaments(
        db, gender, validation.check_competition_type(db, competition_type)
    )
    return [schemas.TournamentSummary(**vars(t)) for t in rows]


@router.get("/{slug}", response_model=schemas.TournamentDetail)
def tournament_detail(
    slug: str,
    gender: str = Query(pattern="^(male|female)$"),
    competition_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.TournamentDetail:
    """One tournament: editions and champions, plus its leading players.

    `notes` carries what the page cannot tell you - editions whose final this
    dataset does not hold, finals decided on a tiebreak, and the raw Cricsheet
    spellings that were merged to form this tournament.
    """
    result = tournaments.get_tournament(
        db, slug, gender, validation.check_competition_type(db, competition_type)
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"no tournament '{validation.echo(slug)}' in this scope",
        )
    detail = vars(result).copy()
    detail["editions_detail"] = [
        schemas.TournamentEdition(**vars(e)) for e in result.editions_detail
    ]
    return schemas.TournamentDetail(**detail)

@router.get("/{slug}/editions/{season:path}", response_model=schemas.TournamentEditionDetail)
def tournament_edition(
    slug: str,
    season: str,
    gender: str = Query(pattern="^(male|female)$"),
    competition_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.TournamentEditionDetail:
    """One edition: its table, every fixture it holds, and who led it.

    `season` is a `:path` because Cricsheet's own season labels contain a slash
    for a tournament spanning a new year - "2023/24", "2014/15" - and more than
    half the editions here are labelled that way. Percent-encoding it does not
    help: Starlette matches on the decoded path, so `2023%2F24` still arrives as
    two segments and misses the route entirely. Same reason `/analytics/venues/
    {venue_name:path}` is a path.

    Declared after `/{slug}` so the two-segment path is unambiguous, and it
    reuses the same event folding, so an edition can never be assembled from a
    raw Cricsheet spelling the alias table would have merged - which is how the
    2014 and 2016 women's T20 World Cups went missing before the aliases landed.

    `standings` is a table of the matches this dataset holds, not the published
    one, and `standings_caveats` plus `notes` say where and why they differ.
    """
    result = tournaments.get_edition(
        db,
        slug,
        season,
        gender,
        validation.check_competition_type(db, competition_type),
    )
    if result is None:
        available = tournaments.edition_seasons(db, slug, gender)
        detail = (
            f"no edition '{validation.echo(season)}' of "
            f"'{validation.echo(slug)}' in this scope"
        )
        if available:
            # Naming the seasons held turns a dead end into a usable answer, and
            # they are public facts about this dataset rather than anything the
            # caller supplied.
            detail += f"; seasons held: {', '.join(available[:12])}"
        raise HTTPException(status_code=404, detail=detail)

    # `asdict` rather than `vars`: these dataclasses are slots=True, so they
    # have no __dict__, and it recurses into the nested rows so pydantic can
    # build the whole tree in one pass.
    return schemas.TournamentEditionDetail(**dataclasses.asdict(result))


"""Tournaments: World Cups, Champions Trophy, Asia Cup and the rest.

Separate from `/api/matches`, which lists individual matches, and from
`/api/competitions`, which lists formats. A tournament sits between them: it is
a named event inside one competition, run over several editions.

Only multi-team events are served. `matches.event_name` names 1,276 distinct
events and 1,013 of them are bilateral tours; a list including those would bury
the World Cup under a thousand two-team series. See app/tournaments.py for why
that test is the number of sides rather than anything in the name.
"""
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

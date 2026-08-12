"""Query-param validation for values whose valid set lives in the database.

`gender` stays a regex on the route signature -- it's a closed set fixed by the
schema's CHECK constraint. Competition keys and types are not: the whole point
of `competitions` being a table is that a new league is a new row, so validating
them against a hardcoded pattern would put an API code change back in the way of
every future competition. These check against the data instead, and still return
422-style rejections for garbage input rather than silently returning [].
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import queries


def check_competition_key(db: Session, competition: str | None) -> str | None:
    if competition is None:
        return None
    valid = queries.valid_competition_keys(db)
    if competition not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"unknown competition '{competition}'; expected one of {sorted(valid)}",
        )
    return competition


def check_competition_type(db: Session, competition_type: str | None) -> str | None:
    if competition_type is None:
        return None
    valid = queries.valid_competition_types(db)
    if competition_type not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"unknown competition_type '{competition_type}'; expected one of {sorted(valid)}",
        )
    return competition_type


def check_team_type(db: Session, team_type: str | None) -> str | None:
    if team_type is None:
        return None
    valid = queries.valid_team_types(db)
    if team_type not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"unknown team_type '{team_type}'; expected one of {sorted(valid)}",
        )
    return team_type

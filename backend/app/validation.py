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

# How much of a rejected value to quote back. Naming the bad value is what makes
# a 422 useful, but echoing it in full turns every validation error into a
# reflector: 100 KB of junk in the `competition` param produced a 100 KB response
# body, so an attacker got the server to amplify their own payload back at
# whatever they aimed it at. Enough to identify a typo, not enough to carry a
# payload.
MAX_ECHO_LENGTH = 60


def echo(value) -> str:
    """A rejected value, clipped so an error cannot be used as an amplifier."""
    text = str(value)
    if len(text) <= MAX_ECHO_LENGTH:
        return text
    return text[:MAX_ECHO_LENGTH] + f"... ({len(text)} chars)"


def check_competition_key(db: Session, competition: str | None) -> str | None:
    if competition is None:
        return None
    valid = queries.valid_competition_keys(db)
    if competition not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"unknown competition '{echo(competition)}'; expected one of {sorted(valid)}",
        )
    return competition


def check_competition_type(db: Session, competition_type: str | None) -> str | None:
    if competition_type is None:
        return None
    valid = queries.valid_competition_types(db)
    if competition_type not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"unknown competition_type '{echo(competition_type)}'; expected one of {sorted(valid)}",
        )
    return competition_type


def check_team_type(db: Session, team_type: str | None) -> str | None:
    if team_type is None:
        return None
    valid = queries.valid_team_types(db)
    if team_type not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"unknown team_type '{echo(team_type)}'; expected one of {sorted(valid)}",
        )
    return team_type


# SQLite stores integers as signed 64-bit, and binding anything larger raises
# OverflowError from the driver - which surfaces as a 500, not a 422. Any id that
# reaches a query needs this bound: `GET /api/teams/999999999999999999999` was an
# anonymous, one-request internal error.
MAX_DB_INT = 2**63 - 1

# LIKE patterns are built from the caller's search string, and SQLite refuses a
# pattern past a complexity limit with "LIKE or GLOB pattern too complex" - again
# a 500 rather than a rejection. 200 characters is far past any real player or
# venue name, and the shape of the failure (an unbounded string reaching a query
# planner) is the part worth closing rather than the exact bound.
MAX_SEARCH_LENGTH = 200

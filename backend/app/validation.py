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
from .analytics import periods

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

# A period spec is caller-controlled text with its own grammar (a preset key,
# `season:<label>` or `custom:<start>:<end>`), so it is bounded and parsed here
# rather than at each call site. `periods.parse` raises PeriodError for anything
# it does not recognise; that becomes a 422 naming the valid set, the same
# treatment competition keys get, and for the same reason: the vocabulary lives
# with the data rather than in a regex the API has to be redeployed to change.
MAX_PERIOD_LENGTH = 64


def check_period(db: Session | None, spec: str | None):
    """Parsed Period, or None for an unset (career-wide) request.

    Two checks beyond parsing, and both exist for the reason every validation
    here does: a filter the data cannot honour must SAY so rather than return an
    empty board.

    * **A season label is checked against the seasons that exist.** `season:2024`
      is one of 50 real labels; `season:2024xyz` parsed happily and returned
      `total: 0`, which reads as "nobody scored a run that season". An unknown
      competition has always returned a 422 naming the valid set, and a season is
      the same kind of value - the source's own vocabulary, held in the data.
    * **A custom range must overlap the data.** A window of 1990 is not an empty
      board, it is a window before this dataset begins (2001-12-19), and saying
      which years exist is more useful than showing nothing.

    The second check also narrows a real amplification surface. Every distinct
    window is a distinct cache key and therefore a full aggregate build - the
    all-round explorer measures 833 ms for a fresh window against 5 ms warm - and
    a caller choosing arbitrary dates never hits a warm key. Bounding the range
    to the span the data covers does not close that (the span is ~9,000 days) but
    it rejects the trivially-generated payloads before any aggregate runs.

    `db` is optional so the parse-only path stays usable without a session.
    """
    if spec is None or not spec.strip():
        return None
    if len(spec) > MAX_PERIOD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"period is too long ({len(spec)} chars, max {MAX_PERIOD_LENGTH})",
        )
    try:
        period = periods.parse(spec)
    except periods.PeriodError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if db is None:
        return period

    if period.kind == periods.SEASON:
        known = queries.known_seasons(db)
        if period.season_label not in known:
            recent = ", ".join(sorted(known, reverse=True)[:4])
            raise HTTPException(
                status_code=422,
                detail=(
                    f"unknown season '{echo(period.season_label)}'. This dataset "
                    f"holds {len(known)} seasons, most recently {recent}."
                ),
            )

    if period.kind == periods.CUSTOM:
        first, last = queries.dataset_span(db)
        if first and last and (period.end < first or period.start > last):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"the window {echo(period.start)} to {echo(period.end)} falls "
                    f"outside this dataset, which covers {first} to {last}."
                ),
            )
    return period

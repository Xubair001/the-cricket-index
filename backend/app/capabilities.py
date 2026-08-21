"""What this deployment can actually answer.

A deployment is not always the full dataset. The ball-by-ball table is 842 MB in
Postgres against 79 MB for the other twenty-four tables put together, so a
storage-limited target can hold everything except the deliveries - and every
figure this project derives from them then has nothing to read.

The point of this module is that such a deployment must **say so** rather than
return an empty result. Those are different claims and the product already
distinguishes them everywhere else: `splits.UNAVAILABLE` names the cuts that
cannot be computed at all, `match_intel` returns a `deferred` map with reasons,
Scout separates `applied` from `ignored`. An empty phase split reads as "this
player never batted in the powerplay", which is a statement about cricket. "This
deployment holds no ball-by-ball data" is a statement about the deployment, and
conflating them is exactly the failure §17 and §30 exist to prevent.

The check is one `SELECT 1 ... LIMIT 1`, cached against the same generation
signal every other derived figure uses - so it costs one query per data change
rather than one per request, and it starts reporting True the moment deliveries
are loaded, with no redeploy.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from . import cache
from .models import Competition, Delivery, Match, PlayerMatchStat

# The wording every surface uses, so a reader meets the same sentence wherever
# they hit the limit rather than four paraphrases of it.
NO_DELIVERIES = (
    "This deployment does not hold ball-by-ball data, which this figure is "
    "derived from. Career and per-match records are unaffected."
)

_state: dict[tuple, bool] = {}


def has_deliveries(db: Session) -> bool:
    """True when ball-by-ball rows exist to read.

    `LIMIT 1` rather than `count(*)`: the question is existence, and counting
    4.8M rows to answer it would cost more than most of the queries it guards.
    """
    global _state
    generation = cache.generation(db)
    hit = _state.get(generation)
    if hit is not None:
        return hit
    found = db.execute(select(Delivery.match_id).limit(1)).first() is not None
    # Replaced in one assignment rather than cleared then written. Uvicorn serves
    # requests from a thread pool, so between a `.clear()` and the write another
    # thread can observe an empty dict and repeat the probe. Harmless - the probe
    # is a LIMIT 1 and the answer is the same - but the window does not need to
    # exist, and rebinding the name closes it without a lock.
    _state = {generation: found}
    return found


# --------------------------------------------------------------------------
# Partial coverage, which is more dangerous than none
# --------------------------------------------------------------------------
#
# `has_deliveries` is a BINARY, deployment-level answer, and that was sufficient
# while the ball record was either whole or absent. It stopped being sufficient
# the moment a deployment held ball-by-ball data for *some* matches: a player
# who appeared in both covered and uncovered matches then gets a figure computed
# from part of their cricket and rendered exactly like a complete one.
#
# That is worse than holding nothing. An empty split reads as an absence and
# invites the question; a partial split reads as a fact. §17 and §30 are both
# about not letting those two look alike, so a surface built on deliveries has to
# be able to say "computed from 14 of your 31 matches" and mean it.


@dataclass(frozen=True)
class Coverage:
    """How much of a slice the ball record actually covers."""

    matches_with_deliveries: int
    matches_total: int

    @property
    def complete(self) -> bool:
        return self.matches_total == 0 or self.matches_with_deliveries >= self.matches_total

    @property
    def empty(self) -> bool:
        return self.matches_with_deliveries == 0

    def note(self) -> str | None:
        """The sentence a surface prints, or None when there is nothing to say."""
        if self.complete:
            return None
        if self.empty:
            return (
                f"None of the {self.matches_total} matches in this scope have "
                "ball-by-ball data here, so this cannot be computed."
            )
        return (
            f"Computed from {self.matches_with_deliveries} of "
            f"{self.matches_total} matches - the rest have no ball-by-ball "
            "record in this deployment, so treat this as a partial picture."
        )


def delivery_coverage(
    db: Session,
    *,
    gender: str,
    competition_key: str | None = None,
    player_identifier: str | None = None,
) -> Coverage:
    """Matches with a ball record against matches in the slice.

    Counted over `player_match_stats` rather than `matches`, so the denominator
    is "matches this player actually appeared in" rather than "matches that
    exist" - which is what makes the ratio mean anything on a player page.

    Cached on the same generation signal as everything else, keyed by the slice,
    because a profile asks this once per split and the answer only moves on an
    ingest.
    """
    key = ("delivery_coverage", gender, competition_key, player_identifier)

    def build() -> Coverage:
        stmt = (
            select(
                func.count(distinct(PlayerMatchStat.match_id)),
                func.count(distinct(Delivery.match_id)),
            )
            .select_from(PlayerMatchStat)
            .join(Match, Match.match_id == PlayerMatchStat.match_id)
            .outerjoin(Delivery, Delivery.match_id == PlayerMatchStat.match_id)
            .where(Match.gender == gender)
        )
        if competition_key:
            stmt = stmt.join(
                Competition, Competition.competition_id == Match.competition_id
            ).where(Competition.key == competition_key)
        if player_identifier:
            stmt = stmt.where(PlayerMatchStat.player_identifier == player_identifier)
        total, covered = db.execute(stmt).one()
        return Coverage(int(covered or 0), int(total or 0))

    return cache.get_or_compute(db, key, build)

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

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import cache
from .models import Delivery

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

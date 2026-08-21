"""Process-level caching for derived tables, invalidated by the ingester.

Several figures this API serves are derived from the whole dataset rather than
from the rows a request returns: the par table, the fitted opposition strengths,
the player-to-country map behind every flag. Recomputing them per request is the
single largest avoidable cost on the read path - the country map alone is a
GROUP BY over 220k appearance rows, and a rankings page that returns 25 players
was paying it in full.

Caching them is only safe with an invalidation signal, and that is the part this
module exists for. `ingestion/` writes to the same file while the API is up, so
a plain module-level dict serves figures from before the last ingest until
someone restarts the process - silently, and for exactly as long as the server
stays up.

**Two tiers: `PRAGMA data_version` to detect *maybe*, a content signature to
confirm.** The pragma alone is not a data-change signal - a WAL checkpoint bumps
it with no data change whatsoever, verified directly:

    baseline 2 -> read only 2 -> real commit 3 -> wal_checkpoint(TRUNCATE) 4

In this deployment the ingestion worker runs alongside the API and short-lived
reader connections come and go, so checkpoints are frequent: 11 counter changes
were observed in 12 seconds of an otherwise idle database, with every row count
unchanged. Invalidating on the pragma alone therefore threw away good cached work
several times a minute for no reason.

So a pragma change only means *look closer*. When it moves, a cheap content
signature decides: row counts over the tables every derived figure is built from,
plus the largest `matches.content_hash` so a re-parse of existing matches is
caught as well as new ones. Measured at under 10 ms, and it runs only when the
pragma has already moved - never on the hot path.

**`PRAGMA data_version` is read on ONE DEDICATED CONNECTION.** The
pragma reports whether another connection has committed since *this* connection
last looked, and SQLite's contract is explicitly per-connection: two values from
different connections are not comparable. That matters here because the API
serves requests from a thread pool over a connection pool, so the obvious
implementation - probe whichever session the request happens to hold - compares
numbers from different connections against one global.

That was measured doing exactly the wrong thing: two live sessions reported 2 and
3 for an unchanged database, and a *read* appeared to bump the counter. The cache
invalidated itself constantly and cached almost nothing. Probing a single
long-lived connection makes every comparison same-connection, which is the case
the pragma is actually specified for.

The probe connection is read-only and stays in autocommit, so each pragma is its
own short read and does observe commits made meanwhile. Holding a transaction
open would pin it to one snapshot and it would never see a change at all.

The alternative signals are all worse. A TTL is wrong in both directions: stale
for its whole window after an ingest, and throwing away good work when nothing
has changed. A file mtime misses WAL writes, since commits land in the `-wal`
sidecar and may not touch the main file for a long time.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import DB_PATH, IS_SQLITE, engine

# Hard ceiling on entries, with least-recently-used eviction.
#
# This bound is a SECURITY control, not tidiness. Keys include values a caller
# controls - `team_id` is any 64-bit integer, and an explorer's filter set is
# effectively open - so an unbounded store lets an anonymous caller mint a new
# cache entry per request and grow the process until it is killed. The cache was
# added to make reads cheap; without a bound it would have added a way to
# exhaust memory instead.
#
# 512 is comfortably above the working set (a few dozen real scopes) and far
# below anything that matters for memory, so a legitimate user never evicts and
# an abusive one just gets cache misses.
MAX_ENTRIES = 512

# Guards the store. Uvicorn serves requests from a thread pool, so two requests
# can miss the same key at once; without the lock they would both compute and
# race to write. The lock is NOT held across the computation - see below.
_lock = threading.Lock()
_store: "OrderedDict[Any, Any]" = OrderedDict()
_version: int | None = None
_signature_value: tuple | None = None


# The dedicated probe connection. Created lazily, then reused for the life of
# the process so every reading is comparable with the last. `_probe_lock` is
# separate from `_lock` because `data_version` is called while `_lock` is already
# held; reusing it would deadlock.
_probe: sqlite3.Connection | None = None
_probe_lock = threading.Lock()

# --------------------------------------------------------------------------
# The Postgres path: no cheap gate exists, so the signature IS the gate
# --------------------------------------------------------------------------
#
# The two-tier design above is worth having on SQLite because the tiers cost
# wildly different amounts: `PRAGMA data_version` is a memory read and the
# signature is a real query. On Postgres that asymmetry disappears - there is no
# pragma, and every candidate for one (`pg_current_xact_id`, `pg_stat_database`
# counters) is a round trip exactly like the signature. A two-tier scheme would
# pay the same cost for less information.
#
# **What matters instead is not probing on every lookup.** `data_version` is
# called inside `get_or_compute`, so on SQLite every warm cache hit pays one
# memory read - nothing. Over a network to a managed Postgres it would pay a
# round trip, which is the whole warm-path budget: the boards this cache exists
# to protect are under 5 ms warm, and a probe per hit would multiply that by the
# link latency. So the signature is checked at most once per interval and the
# last answer is reused in between.
#
# The cost is stated rather than hidden: **a figure can be up to
# `PROBE_INTERVAL_SECONDS` stale after an ingest commits.** That is acceptable
# here and would not be everywhere - ingestion is a daily scheduled job, so the
# window is a few seconds inside a 24-hour cycle. It is not acceptable to make it
# much larger, because the whole reason this module exists is that a long-running
# API otherwise serves pre-ingest figures indefinitely.
PROBE_INTERVAL_SECONDS = 5.0
_last_probe_at: float = 0.0
_last_probe_value: int = 0


def data_version(db: Session | None = None) -> int:
    """A counter that moves when the data MIGHT have changed.

    The `db` argument is accepted and ignored, so callers can keep passing the
    session they already hold. On SQLite, probing *that* session would
    reintroduce the cross-connection comparison this function exists to avoid;
    on Postgres a `count(*)` is comparable from any connection, so the hazard is
    SQLite's alone.
    """
    global _probe, _last_probe_at, _last_probe_value
    if not IS_SQLITE:
        with _probe_lock:
            now = time.monotonic()
            if now - _last_probe_at < PROBE_INTERVAL_SECONDS:
                return _last_probe_value
            _last_probe_at = now
            # The signature itself, hashed to an int so it slots into the
            # counter's contract. `_sweep_locked` then compares the real
            # signature and only discards entries when it genuinely differs, so
            # a hash collision costs a wasted re-check and never a stale serve.
            _last_probe_value = hash(_query_signature())
            return _last_probe_value
    with _probe_lock:
        if _probe is None:
            _probe = sqlite3.connect(DB_PATH, check_same_thread=False)
        # Serialised on `_probe_lock`: one sqlite3 connection is not safe for
        # concurrent use, and `check_same_thread=False` disables the driver's own
        # guard rather than making it safe.
        return int(_probe.execute("PRAGMA data_version").fetchone()[0])


# Tables every derived figure is built from. `deliveries` is deliberately absent:
# counting 4.8M rows costs 50 ms against the whole probe's sub-10 ms, and nothing
# writes deliveries without writing `player_match_stats` in the same ingest.
_SIGNATURE_SQL = """
    SELECT (SELECT count(*) FROM matches),
           (SELECT count(*) FROM player_match_stats),
           (SELECT count(*) FROM players),
           (SELECT count(*) FROM fixture_squads),
           (SELECT max(content_hash) FROM matches)
"""


def _query_signature() -> tuple:
    """Run the signature query on whichever engine is configured.

    The SQL is unchanged between the two: `count(*)` and `max()` over four small
    tables is as portable as SQL gets, which is why the signature tier survived
    the move intact while the pragma tier did not.
    """
    with engine.connect() as conn:
        return tuple(conn.execute(text(_SIGNATURE_SQL)).one())


def _signature() -> tuple:
    """A cheap fingerprint of the data the caches are built from."""
    global _probe
    if not IS_SQLITE:
        return _query_signature()
    with _probe_lock:
        if _probe is None:
            _probe = sqlite3.connect(DB_PATH, check_same_thread=False)
        return tuple(_probe.execute(_SIGNATURE_SQL).fetchone())


def _sweep_locked(current: int) -> None:
    """Drop entries if the DATA changed. Caller holds the lock.

    A moved `data_version` is only a hint - it also moves on a WAL checkpoint. So
    confirm against the content signature before discarding anything, and
    re-baseline the counter either way so the next call takes the fast path.
    """
    global _version, _signature_value
    if _version == current:
        return
    _version = current
    signature = _signature()
    if _signature_value is not None and signature == _signature_value:
        return          # checkpoint, not an ingest: the cache is still valid
    _signature_value = signature
    _store.clear()


def get_or_compute(db: Session, key: Any, compute: Callable[[], Any]) -> Any:
    """Return the cached value for `key`, computing it once if absent.

    Each entry is TAGGED with the `data_version` it was computed against, and
    served only while that tag still matches. The first version of this stored
    values only if nothing had committed during the computation, and that starved
    the cache exactly where it was needed most: the all-round board takes ~3
    seconds to build, the ingestion worker commits during that window, and the
    result was discarded every single time - so a 3-second endpoint stayed a
    3-second endpoint while the cheap ones cached fine. Tagging keeps the same
    freshness guarantee (nothing built before a commit is served after it)
    without making long computations permanently uncacheable.

    `compute` runs OUTSIDE the lock. Holding a lock across a multi-second
    aggregate would serialise every request behind the first one, turning a cache
    into a global bottleneck - the opposite of the point. The cost is that two
    simultaneous misses may both compute; they produce the same value from the
    same snapshot, so the duplicate work is wasted but never wrong.
    """
    with _lock:
        current = data_version(db)
        _sweep_locked(current)
        hit = _store.get(key)
        if hit is not None and hit[0] == _signature_value:
            _store.move_to_end(key)   # touched: it is now the most recent
            return hit[1]

    value = compute()

    with _lock:
        # Tagged with the version observed AFTER computing, which is the snapshot
        # the value actually describes.
        _sweep_locked(data_version(db))
        # Tagged with the SIGNATURE, not the counter: a checkpoint changes the
        # counter without invalidating anything, and an entry tagged with a
        # counter would then be unreachable even though it is still correct.
        _store[key] = (_signature_value, value)
        _store.move_to_end(key)
        while len(_store) > MAX_ENTRIES:
            _store.popitem(last=False)   # drop the least recently used
    return value


def generation(db: Session | None = None) -> tuple | None:
    """A token that changes ONLY when the data changes.

    For module-level caches that keep their own dict but need the same
    invalidation rule. Comparing against `data_version` directly is wrong for
    them for the same reason it is wrong here: a WAL checkpoint moves the counter
    without changing a row. This runs the two-tier check and hands back the
    confirmed content signature.
    """
    with _lock:
        _sweep_locked(data_version(db))
        return _signature_value


def clear() -> None:
    """Forget everything. For tests and for an explicit refresh."""
    global _version, _signature_value
    with _lock:
        _store.clear()
        _version = None
        _signature_value = None


def stats() -> dict:
    """What is currently held, for the health endpoint."""
    with _lock:
        return {
            "entries": len(_store),
            "max_entries": MAX_ENTRIES,
            "data_version": _version,
            "signature": list(_signature_value) if _signature_value else None,
        }

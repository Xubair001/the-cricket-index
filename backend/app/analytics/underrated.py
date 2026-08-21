r"""Underrated players (Section 15).

The scope calls the gap between two of its three rankings a product in its own
right: "Underrated Players surfaces those whose computed performance materially
exceeds their official position." The two rankings already exist and are already
kept apart - `/api/icc/*` serves ICC's published positions, `/api/rankings/*`
and the Performance Index serve figures computed here - and Section 6 forbids
ever merging them. This does not merge them. It measures where they disagree.

The one line that governs the whole module
-------------------------------------------
Section 15: **"The platform must never imply its rating replaces or corrects the
ICC's."** So nothing here is worded as an error on ICC's part. A gap is a
disagreement between two ratings built from different evidence for different
purposes, and the interesting direction is simply the one a selector might act
on. ICC's rating is a points system over a rolling window of results; this one
is a percentile blend over ball-by-ball contribution. Neither is the other's
approximation.

Why both ranks are re-ranked inside a shared set
--------------------------------------------------
The obvious comparison - ICC position against Performance Index position -
compares two different populations and is meaningless. ICC ranks about 100
players per discipline; the Index rates every player in the scope, thousands of
them, including associates and the long-retired that ICC does not rank at all.
A player sitting 3rd on ours and 45th on ICC's may simply be 3rd of a far larger
pool.

So the comparison is confined to the players who appear in BOTH, and both sides
are re-ranked 1..N within exactly that set. ICC's 1st, 4th, 9th become 1, 2, 3.
The question then asked is precise: *among the players ICC ranks in this
discipline that we can also identify, where do the two orderings disagree?*

What is deliberately not counted
----------------------------------
A player absent from ICC's list is **not** treated as "ranked last and therefore
underrated". Absence is not a position: it may mean 101st, it may mean ICC does
not rate that player at all, and this dataset cannot tell the two apart. The
same rule `icc_player_rankings.player_identifier` already follows - an entry
that cannot be matched to a player stays unlinked rather than being attached to
the wrong one - means roughly 15% of each ICC list is unidentifiable here. Both
exclusions are counted and reported above the table rather than quietly applied.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import IccPlayerRanking
from . import performance_index as pi

# ICC's rank_type prefix -> the scope it describes here. ICC publishes no
# women's Test ranking, which is why there is no 'testw'.
ICC_SCOPE = {
    "test": ("male", "tests"),
    "odi": ("male", "odis"),
    "t20": ("male", "t20is"),
    "odiw": ("female", "odis"),
    "t20w": ("female", "t20is"),
}

# ICC's discipline suffix -> the Index's role vocabulary.
ICC_ROLE = {
    "batting": "batter",
    "bowling": "bowler",
    "allrounder": "allrounder",
}

# How far apart the two orderings must be before the disagreement is worth
# showing. A PROPORTION of the comparable set, not an absolute number of
# places, and that distinction is not cosmetic: the comparable sets run from
# 37 to 67 players depending on discipline, so a fixed gap of 20 is a 54% move
# in one board and a 30% move in another. Measured with a fixed 20, Test
# bowling flagged nobody at all - its widest disagreement is 17 places - so
# that board would have been permanently empty for a reason that says nothing
# about the ratings.
#
# From the pooled distribution over 442 comparisons: median 0, p75 10, p90 20.
# The median being zero is the reassuring part - the two ratings broadly agree,
# which is what makes a disagreement worth reading. A quarter of the list is
# comfortably past p75 in every discipline and yields 4 to 14 players per
# board rather than 0 to 13.
MIN_GAP_FRACTION = 0.25

# Floor, so a discipline with an unusually small comparable set cannot flag a
# handful of places as "material".
MIN_GAP_FLOOR = 8


def _min_gap(comparable: int) -> int:
    return max(MIN_GAP_FLOOR, round(comparable * MIN_GAP_FRACTION))


@dataclass
class UnderratedPlayer:
    player_identifier: str
    player_name: str
    country: str | None
    country_code: str | None
    # ICC's own published position, unmodified. Shown because it is the number
    # a reader will recognise, and because re-ranking is a comparison device
    # rather than a restatement of ICC's list.
    icc_position: int
    icc_points: int | None
    # Both sides re-ranked 1..N within the comparable set. These are what the
    # gap is computed from; comparing raw positions across two different
    # populations would not mean anything.
    icc_rank_in_set: int
    index_rank_in_set: int
    gap: int
    index: float
    matches: int


@dataclass
class UnderratedTable:
    rank_type: str
    gender: str
    competition_key: str
    role: str
    rank_date: str | None
    # Coverage, above the results, because a reader cannot weigh a gap without
    # knowing how much of ICC's list it was measured over.
    icc_listed: int
    icc_linked: int
    comparable: int
    # The threshold actually applied, which depends on how large the
    # comparable set turned out to be. Reported so a reader can see what
    # "materially" meant for this board rather than assuming a fixed number.
    min_gap: int
    items: list[UnderratedPlayer] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def decode(rank_type: str) -> tuple[str, str, str] | None:
    """'odiw-bowling' -> ('female', 'odis', 'bowler'), or None if unknown."""
    if "-" not in rank_type:
        return None
    prefix, _, suffix = rank_type.rpartition("-")
    scope = ICC_SCOPE.get(prefix)
    role = ICC_ROLE.get(suffix)
    if not scope or not role:
        return None
    return scope[0], scope[1], role


def _dense_ranks(ordered_ids: list[str]) -> dict[str, int]:
    """1-based position within a list already in the right order."""
    return {pid: i + 1 for i, pid in enumerate(ordered_ids)}


def compute(db: Session, rank_type: str, limit: int = 25) -> UnderratedTable | None:
    decoded = decode(rank_type)
    if decoded is None:
        return None
    gender, competition_key, role = decoded

    # ICC's most recent publication only. Comparing against an older snapshot
    # would report disagreements that ICC has since resolved.
    latest = db.execute(
        select(IccPlayerRanking.rank_date)
        .where(IccPlayerRanking.rank_type == rank_type)
        .order_by(IccPlayerRanking.rank_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is None:
        return None

    icc_rows = db.execute(
        select(IccPlayerRanking)
        .where(
            IccPlayerRanking.rank_type == rank_type,
            IccPlayerRanking.rank_date == latest,
        )
        # `player_name` closes the ordering. ICC marks ties with '=' and the
        # parser carries the previous position forward, so several rows genuinely
        # share a position - and which of them comes first then decides both
        # re-ranked positions below. Left to the engine that differed between
        # SQLite and Postgres, which moved players on and off the board.
        # `player_name` is part of this table's primary key precisely because
        # ties exist, so it is the natural final key.
        .order_by(IccPlayerRanking.position, IccPlayerRanking.player_name)
    ).scalars().all()

    icc_listed = len(icc_rows)
    linked = [r for r in icc_rows if r.player_identifier]

    rated, _total = pi.page(
        db,
        gender=gender,
        competition_key=competition_key,
        role=role,
        limit=10**9,
        offset=0,
    )
    index_of = {r.player_identifier: r for r in rated}

    # The comparable set: ICC-listed, identified here, and rated by the Index.
    # An ICC-listed player the Index has no rating for is excluded rather than
    # given a default, for the same reason absence is not treated as a rank.
    shared = [r for r in linked if r.player_identifier in index_of]
    if not shared:
        return UnderratedTable(
            rank_type=rank_type, gender=gender, competition_key=competition_key,
            role=role, rank_date=latest, icc_listed=icc_listed,
            icc_linked=len(linked), comparable=0, min_gap=0,
            notes=[_coverage_note(icc_listed, len(linked), 0)],
        )

    # ICC's own order, compressed to 1..N over the shared set. ICC ties share a
    # position, and `icc_rows` is already ordered by it, so walking in order
    # preserves their ordering exactly.
    icc_rank = _dense_ranks([r.player_identifier for r in shared])
    index_rank = _dense_ranks([
        r.player_identifier
        for r in sorted(
            shared,
            # Identifier closes it: two players can hold the same Index to the
            # decimal, and a stable sort would otherwise inherit whatever order
            # the ICC query produced.
            key=lambda r: (-index_of[r.player_identifier].index, r.player_identifier),
        )
    ])

    from .. import queries as _queries

    countries = _queries._player_country_map(db, gender)

    threshold = _min_gap(len(shared))
    items = []
    for row in shared:
        pid = row.player_identifier
        gap = icc_rank[pid] - index_rank[pid]
        if gap < threshold:
            continue
        rating = index_of[pid]
        country, code = countries.get(pid, (None, None))
        items.append(UnderratedPlayer(
            player_identifier=pid,
            player_name=rating.player_name,
            country=country,
            country_code=code,
            icc_position=row.position,
            icc_points=row.points,
            icc_rank_in_set=icc_rank[pid],
            index_rank_in_set=index_rank[pid],
            gap=gap,
            index=rating.index,
            matches=rating.matches,
        ))

    # Identifier last: players tie on both gap and index often enough that
    # without it the board's order is the engine's, not ours.
    items.sort(key=lambda p: (-p.gap, -p.index, p.player_identifier or ""))
    return UnderratedTable(
        rank_type=rank_type, gender=gender, competition_key=competition_key,
        role=role, rank_date=latest, icc_listed=icc_listed,
        icc_linked=len(linked), comparable=len(shared), min_gap=threshold,
        items=items[:limit],
        notes=[
            _coverage_note(icc_listed, len(linked), len(shared)),
            f"A player is listed when the two orderings disagree by at least "
            f"{threshold} places - a quarter of the {len(shared)} compared. "
            f"Across all disciplines the median disagreement is zero, which is "
            f"why a large one is worth reading.",
            ASSOCIATE_SKEW_NOTE,
        ],
    )


# A structural property of the comparison, measured rather than suspected:
# over 276 comparisons, players from outside the twelve full members are
# 1.33x over-represented among those flagged (35% of flagged against 26% of
# the comparable pool). Neither rating is wrong. ICC's points system weights a
# result by the opposition's rating and associates rarely meet the top sides,
# while the Index is opposition-adjusted but still credits associate cricket at
# its adjusted value. Stated because a board showing four Dutch and Irish names
# reads as "ICC underrates associates" if the reason is left out.
ASSOCIATE_SKEW_NOTE = (
    "Players from outside the twelve full members appear here about a third "
    "more often than their share of the comparable pool (35% against 26%, "
    "measured over 276 comparisons). That is a difference in what the two "
    "ratings measure, not a finding about either: ICC's points weight a result "
    "by the opposition's own rating, and associate sides rarely meet the "
    "highest-rated teams."
)


def _coverage_note(listed: int, linked: int, comparable: int) -> str:
    return (
        f"Measured over {comparable} of the {listed} players ICC ranks here. "
        f"{listed - linked} could not be matched to a player in this dataset "
        f"and {linked - comparable} have too little cricket in this scope for "
        f"the Index to rate. Both are excluded rather than assumed: a player "
        f"absent from a ranking has no position, not a low one."
    )


def gap_distribution(db: Session, rank_type: str) -> list[int]:
    """Every gap for one discipline, for calibrating MIN_GAP against data."""
    table = compute(db, rank_type, limit=10**9)
    if table is None:
        return []
    saved = globals()["MIN_GAP_FLOOR"], globals()["MIN_GAP_FRACTION"]
    globals()["MIN_GAP_FLOOR"], globals()["MIN_GAP_FRACTION"] = -10**9, 0.0
    try:
        return sorted(p.gap for p in compute(db, rank_type, limit=10**9).items)
    finally:
        globals()["MIN_GAP_FLOOR"], globals()["MIN_GAP_FRACTION"] = saved

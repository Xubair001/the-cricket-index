r"""Movement in the ICC's published rankings between two snapshots (§8, §15).

Why movement and not a ranking history
--------------------------------------
§7 lists "Ranking History" and §10 lists "ICC Ranking History" as a profile
section, and `icc_player_rankings` is keyed on `rank_date`, so the schema has
always supported one. The DATA does not yet: measured here there are six
distinct snapshot dates spanning 2026-07-28 to 2026-08-17, because the daily ICC
sync only started recently and ICC republishes roughly weekly.

A trend chart over three weeks is not a history, and drawing one would present
three weeks as though it were a career. What three weeks of weekly snapshots
DOES support is movement - who went up, who came down, since the last published
list - which is exactly what §8 asks for under "Latest ICC Movements" and
"Biggest Movers". So that is what this computes, and `snapshots` reports how
deep the record actually is so the page can say it.

Three traps, all of them found in the data
------------------------------------------
**Each rank type has its OWN snapshot dates.** `test-batting` was last captured
on 2026-08-11 while `odiw-batting` was captured on 2026-08-17. Taking "the two
most recent dates" globally and applying them to every rank type finds no rows
at all for most of them - it compares a men's Test list against a date only the
women's lists have. So the pair of dates is resolved per rank type.

**A player absent from the earlier snapshot is a NEW ENTRY, not a riser.**
Treating them as having moved from 101st manufactures a position ICC never
published. They are returned in a separate list, which is the same refusal
`underrated.py` makes about absence from a ranked list.

**A negative position delta is an IMPROVEMENT.** Position 1 is the top, so
moving from 8th to 3rd is -5. Every figure here is signed so that POSITIVE means
improvement, because a board where the best mover shows the most negative number
gets misread every time.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from ..models import IccPlayerRanking

# Rows per direction. Enough to see the shape of a week's movement.
TOP_N = 10


@dataclass(slots=True)
class Mover:
    rank_type: str
    player_name: str
    player_identifier: str | None
    country: str | None
    country_code: str | None
    position: int
    previous_position: int
    # Signed so POSITIVE is an improvement, despite position 1 being the top.
    places_gained: int
    points: int | None
    previous_points: int | None
    points_gained: int | None


@dataclass(slots=True)
class NewEntry:
    rank_type: str
    player_name: str
    player_identifier: str | None
    country: str | None
    country_code: str | None
    position: int
    points: int | None


@dataclass(slots=True)
class MovementReport:
    rank_type: str
    current_date: str | None
    previous_date: str | None
    # How many snapshots exist for THIS rank type. The honest answer to "how
    # far back does this go", and the reason there is no trend chart.
    snapshots: int
    compared: int = 0
    risers: list[Mover] = field(default_factory=list)
    fallers: list[Mover] = field(default_factory=list)
    new_entries: list[NewEntry] = field(default_factory=list)
    dropped_out: int = 0
    notes: list[str] = field(default_factory=list)


def snapshot_dates(db: Session, rank_type: str) -> list[str]:
    """Every date this rank type was captured on, newest first.

    Per rank type, not global - see the module docstring for why taking the
    global pair finds nothing for most types.
    """
    rows = db.execute(
        select(distinct(IccPlayerRanking.rank_date))
        .where(IccPlayerRanking.rank_type == rank_type)
        .order_by(IccPlayerRanking.rank_date.desc())
    ).all()
    return [r[0] for r in rows if r[0]]


def _key(row: IccPlayerRanking) -> str:
    """What identifies the same person across two snapshots.

    ICC's own player id where present, else the name. The name is a safe
    fallback here rather than a guess: it is part of this table's primary key
    already, because ICC marks ties with '=' and tied players share a position.
    """
    return row.icc_player_id or f"name:{row.player_name}"


def movement(db: Session, rank_type: str) -> MovementReport:
    """Who moved in this ranking since the previous published list."""
    from .. import flags

    dates = snapshot_dates(db, rank_type)
    report = MovementReport(
        rank_type=rank_type,
        current_date=dates[0] if dates else None,
        previous_date=dates[1] if len(dates) > 1 else None,
        snapshots=len(dates),
    )
    if len(dates) < 2:
        report.notes.append(
            "Only one published list is held for this ranking, so there is "
            "nothing to compare it against yet. The ICC republishes roughly "
            "weekly and each sync stores a dated snapshot, so this fills in "
            "over time rather than being a gap in the source."
        )
        return report

    def rows_for(rank_date: str) -> dict[str, IccPlayerRanking]:
        found = db.execute(
            select(IccPlayerRanking).where(
                IccPlayerRanking.rank_type == rank_type,
                IccPlayerRanking.rank_date == rank_date,
            )
        ).scalars()
        return {_key(row): row for row in found}

    now = rows_for(dates[0])
    before = rows_for(dates[1])

    movers: list[Mover] = []
    for key, row in now.items():
        earlier = before.get(key)
        if earlier is None:
            report.new_entries.append(
                NewEntry(
                    rank_type=rank_type,
                    player_name=row.player_name,
                    player_identifier=row.player_identifier,
                    country=row.country,
                    country_code=flags.country_code(row.country) if row.country else None,
                    position=row.position,
                    points=row.points,
                )
            )
            continue
        if row.position == earlier.position:
            report.compared += 1
            continue
        report.compared += 1
        movers.append(
            Mover(
                rank_type=rank_type,
                player_name=row.player_name,
                player_identifier=row.player_identifier,
                country=row.country,
                country_code=flags.country_code(row.country) if row.country else None,
                position=row.position,
                previous_position=earlier.position,
                # Position 1 is the top, so going from 8th to 3rd is a gain of
                # five. Signed here rather than in the client, so no consumer
                # has to remember which direction is good.
                places_gained=earlier.position - row.position,
                points=row.points,
                previous_points=earlier.points,
                points_gained=(
                    row.points - earlier.points
                    if row.points is not None and earlier.points is not None
                    else None
                ),
            )
        )

    report.dropped_out = sum(1 for key in before if key not in now)
    movers.sort(key=lambda m: (-m.places_gained, m.player_name))
    report.risers = [m for m in movers if m.places_gained > 0][:TOP_N]
    report.fallers = sorted(
        (m for m in movers if m.places_gained < 0),
        key=lambda m: (m.places_gained, m.player_name),
    )[:TOP_N]

    report.new_entries.sort(key=lambda e: e.position)
    report.new_entries = report.new_entries[:TOP_N]

    report.notes.append(
        f"Comparing the list published {dates[0]} against {dates[1]}. "
        f"{report.snapshots} snapshot{'s' if report.snapshots != 1 else ''} of "
        f"this ranking are held in total, which is why this page shows movement "
        f"rather than a trend: the daily sync began recently and the ICC "
        f"republishes about weekly."
    )
    if report.new_entries or report.dropped_out:
        report.notes.append(
            f"{len(report.new_entries)} player(s) appear who were not in the "
            f"previous list and {report.dropped_out} who were. These are listed "
            f"separately rather than counted as movement: a player absent from a "
            f"list has no published position, and inventing one to subtract from "
            f"would attribute a move the ICC never published."
        )
    return report


__all__ = ["movement", "snapshot_dates", "MovementReport", "Mover", "NewEntry"]

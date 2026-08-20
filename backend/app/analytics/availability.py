r"""Player availability (§16) -- who is committed, and what that does not mean.

What this can now answer, and why it could not before
------------------------------------------------------
§5 lists "squad lists per fixture" as the core blocker for availability, on the
grounds that fixtures "carry team names only, no player lists". That is true of
the ICC *schedule* endpoint. It is not true of the *scorecard* endpoint, which
returns a full announced squad for a fixture that has not been played -- with
each player's role, batting hand, bowling style and an availability status.

So availability is now sourced rather than inferred. A player named in a squad
for a fixture inside a window is **committed** for that window, and that is a
fact from ICC's own feed rather than a guess from recent appearances.

The asymmetry that governs this whole module
----------------------------------------------
**Committed is sourced. Available is not.**

A player appearing in a squad is positive evidence. A player *absent* from every
squad is not evidence of anything, because squads are announced a few weeks out:
of 207 upcoming fixtures in the current window, only 35 have a squad published.
So the overwhelming majority of "not committed" players are simply players whose
squad has not been named yet.

Every response therefore carries `fixtures_with_squads` against
`fixtures_in_window`, and the API never returns a list called "available
players". It returns commitments, and a coverage figure that says how much of
the window is actually known. §5's rule -- availability must never imply it
accounts for injury or contract -- is preserved exactly: ICC's `status` field is
passed through verbatim and nothing is inferred from silence.

Franchise cricket is absent from the feed entirely
----------------------------------------------------
The ICC feed carries internationals and youth internationals only. A player free
of international duty in a window may still be contracted to a franchise league
that this feed has never heard of, which is §34 #3 and is unresolved. That is
stated in the response rather than left for a reader to discover.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Fixture, FixtureSquad, Player
from ..names import preferred_name

# What the caller must be told alongside any availability answer.
CAVEATS = {
    "absence_is_not_availability": (
        "A player not named in any squad is not known to be free: squads are "
        "announced a few weeks before a series, so most fixtures in a forward "
        "window have none published yet. Only commitments are sourced."
    ),
    "no_franchise_fixtures": (
        "The ICC feed carries internationals and youth internationals only. A "
        "player with no international commitment may still be contracted to a "
        "franchise league this feed does not cover."
    ),
    "no_injury_or_contract": (
        "Nothing here accounts for injury, contract disputes or personal "
        "availability. ICC's own status wording is passed through unchanged."
    ),
}


@dataclass
class Commitment:
    icc_match_id: str
    team_name: str | None
    opponent: str | None
    start_date: str | None
    end_date: str | None
    match_type: str | None
    series_name: str | None
    role: str | None
    batting_style: str | None
    bowling_style: str | None
    is_captain: bool
    status: str | None


@dataclass
class PlayerAvailability:
    player_identifier: str | None
    player_name: str
    committed: bool
    commitments: list[Commitment] = field(default_factory=list)
    # Sourced attributes, carried because they come from the same rows and are
    # the answer to §34 #1 -- role, hand and bowling type.
    role: str | None = None
    batting_style: str | None = None
    bowling_style: str | None = None


@dataclass
class AvailabilityWindow:
    date_from: str
    date_to: str
    fixtures_in_window: int
    fixtures_with_squads: int
    players: list[PlayerAvailability] = field(default_factory=list)
    caveats: dict = field(default_factory=lambda: dict(CAVEATS))


def _window_fixtures(db: Session, date_from: str, date_to: str):
    """Fixtures overlapping the window, and how many have a squad."""
    in_window = (
        select(Fixture)
        .where(
            Fixture.start_date.is_not(None),
            Fixture.start_date <= date_to,
            func.coalesce(Fixture.end_date, Fixture.start_date) >= date_from,
        )
    )
    fixtures = db.execute(in_window).scalars().all()
    ids = [f.icc_match_id for f in fixtures]
    with_squads = set()
    if ids:
        with_squads = {
            r[0]
            for r in db.execute(
                select(FixtureSquad.icc_match_id)
                .where(FixtureSquad.icc_match_id.in_(ids))
                .distinct()
            ).all()
        }
    return fixtures, with_squads


def window(
    db: Session,
    *,
    date_from: str,
    date_to: str,
    player_identifier: str | None = None,
    role: str | None = None,
    batting_style: str | None = None,
    limit: int = 100,
) -> AvailabilityWindow:
    """Who is committed between two dates.

    Filters on the SOURCED attributes -- role, batting hand -- because those are
    now facts from the feed rather than inferences, which is what makes a query
    like "left-handed openers committed in September" answerable at all.
    """
    fixtures, with_squads = _window_fixtures(db, date_from, date_to)
    by_id = {f.icc_match_id: f for f in fixtures}

    stmt = select(FixtureSquad).where(
        FixtureSquad.icc_match_id.in_(list(by_id) or [""])
    )
    if player_identifier:
        stmt = stmt.where(FixtureSquad.player_identifier == player_identifier)
    if role:
        stmt = stmt.where(FixtureSquad.role == role)
    if batting_style:
        stmt = stmt.where(FixtureSquad.batting_style == batting_style)

    names = {
        p.identifier: preferred_name(p.name, p.display_name)
        for p in db.execute(select(Player)).scalars()
    }

    grouped: dict[str, PlayerAvailability] = {}
    for row in db.execute(stmt).scalars().all():
        f = by_id.get(row.icc_match_id)
        if f is None:
            continue
        # Key on the identifier where we have one, else the ICC name -- an
        # unlinked player is still a real commitment and should not vanish.
        key = row.player_identifier or f"icc:{row.player_name}"
        entry = grouped.get(key)
        if entry is None:
            entry = PlayerAvailability(
                player_identifier=row.player_identifier,
                player_name=names.get(row.player_identifier or "", row.player_name),
                committed=True,
                role=row.role,
                batting_style=row.batting_style,
                bowling_style=row.bowling_style,
            )
            grouped[key] = entry

        opponent = (
            f.team_b_name if (row.team_name or "") == (f.team_a_name or "") else f.team_a_name
        )
        entry.commitments.append(
            Commitment(
                icc_match_id=row.icc_match_id,
                team_name=row.team_name,
                opponent=opponent,
                start_date=f.start_date,
                end_date=f.end_date,
                match_type=f.match_type,
                series_name=f.series_name,
                role=row.role,
                batting_style=row.batting_style,
                bowling_style=row.bowling_style,
                is_captain=bool(row.is_captain),
                status=row.status,
            )
        )

    players = sorted(
        grouped.values(), key=lambda p: (-len(p.commitments), p.player_name)
    )[:limit]
    for p in players:
        p.commitments.sort(key=lambda c: c.start_date or "")

    return AvailabilityWindow(
        date_from=date_from,
        date_to=date_to,
        fixtures_in_window=len(fixtures),
        fixtures_with_squads=len(with_squads),
        players=players,
    )


__all__ = ["window", "AvailabilityWindow", "PlayerAvailability", "Commitment", "CAVEATS"]

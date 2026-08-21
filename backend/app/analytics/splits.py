r"""Performance splits (§12) -- the same player, cut by circumstance.

One endpoint, split type as a parameter
----------------------------------------
§25 is explicit that the split type is a parameter rather than a family of
endpoints, and this module mirrors that: every split produces the same
`SplitBucket` shape, so the UI renders one table however the cut was made and
two splits can never drift into disagreeing about what "strike rate" means.

What each split needs, and what it now has
-------------------------------------------
§12 lists seven splits across three tiers. Four are live here:

* **opposition** and **competition** were always Tier A -- they need only the
  match, not the ball.
* **phase** and **situation** were Tier B and are live because `deliveries`
  now exists. Phase needs the over number; situation needs the innings
  sequence. Both come straight off the ball.
* **venue** was Tier B on venue normalisation, which `app/venues.py` did.

Two remain absent and are reported as such rather than approximated:

* **home / away** needs a venue-to-country mapping. `venues.py` canonicalises a
  ground's *name*, which is a different problem from knowing which country it
  is in, and the `city` column is too inconsistent to infer from.
* **bowling type faced** (pace vs spin) needs a bowler-type source that does
  not exist in Cricsheet or Wikidata (Tier C).

Phases are a property of the format, not of cricket
----------------------------------------------------
A T20 powerplay is six overs and an ODI's is ten, so the bands live in `config`
per competition. Tests get **no bands at all**: there is no powerplay in a Test
and no death overs, and slicing overs 0-5 off a Test innings would produce a
figure that looks like the T20 one and means something else entirely. The split
reports that it does not apply rather than inventing it.

The same honesty applies to situation. In a limited-overs match "batting first"
and "chasing" are the whole story. A Test has four innings and only the fourth
is a chase in any meaningful sense, so a Test is split by innings number and
labelled that way instead of being forced into a two-way cut it does not have.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from ..models import Competition, Delivery, Match, Team
from ..venues import canonical
from . import config

# Split types this module can actually compute.
AVAILABLE = ("phase", "situation", "venue", "opposition", "competition")

# Packs (venue, city) into one GROUP BY key. A character that cannot occur in
# either column, so unpacking is unambiguous.
_VENUE_CITY_SEPARATOR = "\x1f"

# Below this a bucket's RATES are not a record of anything, and the venue split
# is where it bites: a Test career spans ~79 grounds and around one in seven of
# them is a single innings, so an average of 146.50 from two visits was being
# shown at the same weight as one from eight. The bucket is still returned -
# the runs were scored - it is the rates that carry a warning.
#
# **Each rate is gated on its OWN denominator**, which the first version was not.
# Gating everything on innings marked the wrong figures: a batting average is
# runs / DISMISSALS, so 192.00 off four innings and two dismissals is the
# unstable case and passed an innings test comfortably, while a strike rate off
# the same four innings rests on 200-odd balls and is perfectly sound. The
# denominators are different quantities and one threshold cannot describe both.
RELIABLE_MIN_INNINGS = 3
RELIABLE_MIN_BALLS = 60
# An average divides by dismissals, so that is what has to be counted. Four is
# where the figure stops swinging by tens of runs on one more innings.
RELIABLE_MIN_DISMISSALS = 4
# A bowling average divides by wickets, and the same reasoning applies.
RELIABLE_MIN_WICKETS = 4

# Declared so the API can report them as absent-with-a-reason rather than
# silently offering a shorter list than §12 promises.
UNAVAILABLE = {
    "home_away": "Needs a venue-to-country mapping, and this dataset has no "
                 "country to read. Measured over all 636 distinct "
                 "(venue, city) pairs, only 15 carry a segment that resolves to "
                 "a country - 2.4%. Cricsheet gives a ground and a city (270 of "
                 "them), never a country, so canonicalising a ground's name is a "
                 "different problem from knowing which country it is in. "
                 "Unblocking this is a data decision: a sourced ground-to-country "
                 "list. It is deliberately not inferred from which side plays "
                 "somewhere most often, because that resolves Sharjah and Dubai "
                 "to Pakistan and India, which is exactly backwards for the "
                 "neutral venues where the question matters most.",
    "bowling_type": "Needs a pace/spin source for each bowler, which exists in "
                    "neither Cricsheet nor Wikidata (Tier C).",
}


@dataclass
class SplitBucket:
    """One slice of a player's cricket. Batting and bowling side by side."""

    key: str
    label: str
    innings: int = 0
    # Batting
    runs: int = 0
    balls_faced: int = 0
    dismissals: int = 0
    fours: int = 0
    sixes: int = 0
    dots: int = 0
    average: float | None = None
    strike_rate: float | None = None
    dot_pct: float | None = None
    boundary_pct: float | None = None
    # Bowling
    wickets: int = 0
    balls_bowled: int = 0
    runs_conceded: int = 0
    economy: float | None = None
    bowling_average: float | None = None
    bowling_dot_pct: float | None = None
    # False where this bucket rests on too little cricket for THAT SIDE's rates
    # to describe anything. Per discipline, because a batter who bowled two overs
    # at a ground must not have their batting average flagged on the strength of
    # the bowling sample - which is the same conflation the explorers guard
    # against when they keep batters off a bowling board.
    #
    # Marked rather than withheld: the runs were scored, so the row stays and it
    # is the rates that carry the warning. Matters most on the venue split, where
    # a Test career spans ~79 grounds and around one in seven is a single innings.
    batting_reliable: bool = True
    bowling_reliable: bool = True
    # Narrower still, for the two rates whose denominator is not balls. See
    # RELIABLE_MIN_DISMISSALS: a strike rate off four innings is sound and the
    # average over the same four is not, because they divide by different things.
    average_reliable: bool = True
    bowling_average_reliable: bool = True


@dataclass
class SplitResult:
    split: str
    label: str
    applies: bool = True
    # Populated when `applies` is False -- e.g. phases in a Test.
    not_applicable_because: str | None = None
    buckets: list[SplitBucket] = field(default_factory=list)


def _rate(n: float, d: float, places: int = 2) -> float | None:
    return round(n / d, places) if d else None


def _finish(b: SplitBucket) -> SplitBucket:
    """Derive every rate once, so no two splits compute them differently."""
    b.average = _rate(b.runs, b.dismissals)
    b.strike_rate = _rate(b.runs * 100.0, b.balls_faced)
    b.dot_pct = _rate(b.dots * 100.0, b.balls_faced)
    b.boundary_pct = _rate((b.fours + b.sixes) * 100.0, b.balls_faced)
    b.economy = _rate(b.runs_conceded * 6.0, b.balls_bowled)
    b.bowling_average = _rate(b.runs_conceded, b.wickets)
    # Per discipline. A single flag marked Kohli's Wankhede batting (6 innings,
    # 433 runs) unreliable because he had also bowled a few balls there.
    b.batting_reliable = (
        b.innings >= RELIABLE_MIN_INNINGS and b.balls_faced >= RELIABLE_MIN_BALLS
    )
    b.bowling_reliable = (
        b.innings >= RELIABLE_MIN_INNINGS and b.balls_bowled >= RELIABLE_MIN_BALLS
    )
    # ...and then per rate, on the denominator that rate actually divides by.
    b.average_reliable = b.batting_reliable and b.dismissals >= RELIABLE_MIN_DISMISSALS
    b.bowling_average_reliable = b.bowling_reliable and b.wickets >= RELIABLE_MIN_WICKETS
    return b


def _scoped(stmt: Select, gender: str, competition_key: str | None) -> Select:
    stmt = stmt.where(Match.gender == gender)
    if competition_key:
        stmt = stmt.where(Competition.key == competition_key)
    return stmt


# --- batting and bowling aggregates off the ball ---------------------------
#
# Two queries rather than one: a delivery has exactly one batter and one bowler,
# so a single grouped query would have to pick which role it was aggregating and
# would double-count a player who did both in the same bucket.

def _batting_rows(db: Session, pid: str, group, gender, competition_key):
    stmt = (
        select(
            group.label("bucket"),
            func.sum(Delivery.runs_batter),
            # A wide is not a ball faced -- the same rule the aggregate parser
            # applies, so a split and a career figure agree.
            func.sum(func.iif(Delivery.wides == 0, 1, 0)),
            func.sum(func.iif(Delivery.runs_total == 0, 1, 0)),
            func.sum(func.iif((Delivery.runs_batter == 4) & (Delivery.non_boundary == 0), 1, 0)),
            func.sum(func.iif((Delivery.runs_batter == 6) & (Delivery.non_boundary == 0), 1, 0)),
            func.sum(func.iif(Delivery.player_out == pid, 1, 0)),
            func.count(func.distinct(Delivery.match_id + "-" + Delivery.innings)),
        )
        .join(Match, Match.match_id == Delivery.match_id)
        .join(Competition, Competition.competition_id == Match.competition_id)
        .where(Delivery.batter == pid)
        .group_by(group)
    )
    return db.execute(_scoped(stmt, gender, competition_key)).all()


def _bowling_rows(db: Session, pid: str, group, gender, competition_key):
    stmt = (
        select(
            group.label("bucket"),
            # Wides and no-balls are not legal deliveries, but their runs are
            # charged to the bowler; byes and leg-byes are neither.
            func.sum(func.iif((Delivery.wides == 0) & (Delivery.noballs == 0), 1, 0)),
            func.sum(Delivery.runs_batter + Delivery.wides + Delivery.noballs),
            func.sum(func.iif(Delivery.runs_total == 0, 1, 0)),
            func.sum(
                func.iif(
                    Delivery.wicket_kind.in_(tuple(BOWLER_CREDITED_KINDS)), 1, 0
                )
            ),
        )
        .join(Match, Match.match_id == Delivery.match_id)
        .join(Competition, Competition.competition_id == Match.competition_id)
        .where(Delivery.bowler == pid)
        .group_by(group)
    )
    return db.execute(_scoped(stmt, gender, competition_key)).all()


# Mirrors ingestion/parsing.py. A run out is not the bowler's wicket.
BOWLER_CREDITED_KINDS = {
    "bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket",
}


def _group_expression(split: str, competition_key: str | None):
    """The SQL expression a split groups on, and how to label a bucket."""
    if split == "phase":
        bands = config.PHASE_BANDS.get(competition_key or "")
        expr = None
        for key, _label, lo, hi in bands:
            branch = func.iif((Delivery.over >= lo) & (Delivery.over <= hi), key, None)
            expr = branch if expr is None else func.coalesce(expr, branch)
        labels = {k: lbl for k, lbl, _lo, _hi in bands}
        order = [k for k, _l, _lo, _hi in bands]
        return expr, labels, order

    if split == "situation":
        # Innings number IS the situation in limited-overs cricket: the side
        # batting in innings 1 set a target, the side in innings 2 chased it.
        expr = func.iif(Delivery.innings == 1, "batting_first", "chasing")
        return expr, {"batting_first": "Batting first", "chasing": "Chasing"}, [
            "batting_first", "chasing",
        ]

    if split == "venue":
        # Grouped on venue AND city, not the venue alone. Six different English
        # grounds are all called "County Ground" and two are "National Stadium",
        # so grouping on the raw column merges them: players here have up to 37
        # appearances spread across six County Grounds, reported as one row.
        # The pair is packed into one expression because this is a GROUP BY key,
        # and unpacked when the label is resolved.
        return (
            Match.venue + _VENUE_CITY_SEPARATOR + func.coalesce(Match.city, ""),
            None,
            None,
        )
    if split == "opposition":
        return func.iif(
            Delivery.batting_team_id == Match.team1_id, Match.team2_id, Match.team1_id
        ), None, None
    if split == "competition":
        return Competition.key, None, None
    raise ValueError(split)


def compute(
    db: Session,
    player_identifier: str,
    *,
    split: str,
    gender: str,
    competition_key: str | None = None,
) -> SplitResult:
    """One split for one player."""
    if split not in AVAILABLE:
        raise ValueError(f"unknown split '{split}'")

    label = split.replace("_", " ").title()

    # Phase needs a format, and Tests have none.
    if split == "phase":
        if not competition_key:
            return SplitResult(
                split, label, applies=False,
                not_applicable_because=(
                    "Phases differ by format - a T20 powerplay is six overs and an "
                    "ODI's is ten - so a competition must be chosen."
                ),
            )
        if competition_key not in config.PHASE_BANDS:
            return SplitResult(
                split, label, applies=False,
                not_applicable_because=(
                    "There is no powerplay or death overs in this format, so the "
                    "phases other formats use do not exist here."
                ),
            )

    if split == "situation" and competition_key == "tests":
        return SplitResult(
            split, label, applies=False,
            not_applicable_because=(
                "A Test has four innings and only the fourth is a chase in any "
                "meaningful sense, so batting-first versus chasing does not "
                "describe it."
            ),
        )

    group, labels, order = _group_expression(split, competition_key)

    buckets: dict[str, SplitBucket] = {}

    def bucket_for(raw) -> SplitBucket | None:
        if raw is None:
            return None
        key = str(raw)
        if key not in buckets:
            buckets[key] = SplitBucket(key=key, label=(labels or {}).get(key, key))
        return buckets[key]

    for raw, runs, balls, dots, fours, sixes, outs, inns in _batting_rows(
        db, player_identifier, group, gender, competition_key
    ):
        b = bucket_for(raw)
        if b is None:
            continue
        b.runs, b.balls_faced, b.dots = runs or 0, balls or 0, dots or 0
        b.fours, b.sixes, b.dismissals = fours or 0, sixes or 0, outs or 0
        b.innings = inns or 0

    for raw, balls, conceded, dots, wickets in _bowling_rows(
        db, player_identifier, group, gender, competition_key
    ):
        b = bucket_for(raw)
        if b is None:
            continue
        b.balls_bowled, b.runs_conceded = balls or 0, conceded or 0
        b.wickets = wickets or 0
        b.bowling_dot_pct = _rate((dots or 0) * 100.0, balls or 0)

    rows = [_finish(b) for b in buckets.values()]

    # Names for the splits whose bucket key is an id or a raw string.
    if split == "venue":
        for b in rows:
            venue, _, city = b.key.partition(_VENUE_CITY_SEPARATOR)
            # `canonical` takes the city so a shared ground name is qualified -
            # "County Ground (Bristol)" rather than six rows all reading
            # "County Ground".
            b.label = canonical(venue, city or None) or venue
    elif split == "opposition":
        names = dict(db.execute(select(Team.team_id, Team.name)).all())
        for b in rows:
            b.label = names.get(int(b.key), b.key)

    if order:
        rows.sort(key=lambda b: order.index(b.key) if b.key in order else 99)
    else:
        rows.sort(key=lambda b: -(b.balls_faced + b.balls_bowled))

    return SplitResult(split, label, buckets=rows)


__all__ = ["compute", "SplitResult", "SplitBucket", "AVAILABLE", "UNAVAILABLE"]

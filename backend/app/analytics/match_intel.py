r"""Match intelligence (§22) -- what happened, and why it mattered.

§22 opens by saying match pages "do not compete with live-score products", and
that is the design constraint, not a disclaimer. A scorecard says Kohli made 82.
This module says the innings turned on a 118-run stand that took the required
rate from 9.4 to 6.1, and that the bowler who broke it had figures of 2 for 11
in a four-over spell. Same match, different question.

Everything here was Tier B until the deliveries backfill; all of it now comes
straight off the ball sequence.

What is deliberately NOT here
------------------------------
§22 lists win probability, tactical events and match-changing moments under
"Later", and they stay there. A win-probability model needs to be fitted and
validated against outcomes before it is shown to anybody -- an unvalidated one
would produce a confident curve that is simply wrong at the moments people care
about most, which is worse than no curve. What this module offers instead is
*descriptive*: the over-by-over shape of an innings, and the partnerships and
spells that produced it. Every figure is something that demonstrably happened.

Partnerships are keyed on the PAIR, not on the wicket count
------------------------------------------------------------
A partnership runs while the same two batters are together, so the pair itself
is the key. Counting wickets instead breaks on the cases that matter: a retired
hurt returning later resumes with a different partner, and a run out can remove
the non-striker, which changes the pair without the incoming batter having faced
a ball. Comparing the unordered pair from one delivery to the next handles all
of it, and strike rotation -- which swaps batter and non_striker every over --
does not register as a change because the pair is compared as a set.

Partnership runs include extras, as they do on any scorecard: a stand is what
the scoreboard moved by while two batters were together, not the sum of their
individual scores.

A spell is consecutive overs, not "all the overs a bowler bowled"
-----------------------------------------------------------------
Bowling in cricket comes in spells, and a bowler's match figures hide them: 4 for
60 could be one destructive burst and two expensive ones. A spell here is a run
of overs by the same bowler with no over of theirs missing in between, which is
exactly how the term is used.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Competition, Delivery, Match, Player, Team
from ..names import preferred_name
from . import impact as impact_mod

# A stand below this is not a partnership anyone discusses; it is two batters
# briefly at the crease. Kept off the highlights, still counted in the totals.
NOTABLE_PARTNERSHIP_RUNS = 30

# Overs apart at which a bowler's overs still count as one spell. Bowlers
# alternate ends so a continuous spell steps by two; more than that means they
# were rested and came back.
MAX_SPELL_GAP = 2


@dataclass
class Partnership:
    innings: int
    wicket: int                 # which wicket this stand was for (1 = opening)
    batter_a: str
    batter_b: str
    runs: int
    balls: int
    run_rate: float | None
    unbroken: bool              # ended the innings rather than a wicket
    ended_by: str | None        # dismissal kind that broke it
    start_over: int
    end_over: int


@dataclass
class Spell:
    innings: int
    bowler: str
    overs: int
    balls: int
    runs_conceded: int
    wickets: int
    economy: float | None
    start_over: int
    end_over: int


@dataclass
class OverPoint:
    """One over of an innings -- the momentum series."""

    innings: int
    over: int
    runs: int
    wickets: int
    cumulative_runs: int
    cumulative_wickets: int


@dataclass
class InningsIntel:
    innings: int
    batting_team: str | None
    runs: int
    wickets: int
    balls: int
    run_rate: float | None
    partnerships: list[Partnership] = field(default_factory=list)
    spells: list[Spell] = field(default_factory=list)
    overs: list[OverPoint] = field(default_factory=list)


@dataclass
class MatchIntel:
    match_id: str
    innings: list[InningsIntel] = field(default_factory=list)
    # Named so the API can state what is descriptive and what is absent.
    deferred: dict[str, str] = field(default_factory=dict)


DEFERRED = {
    "win_probability": (
        "§22 defers this. A win-probability curve has to be fitted and validated "
        "against outcomes first; an unvalidated one is confidently wrong exactly "
        "at the moments people look at it."
    ),
    "tactical_events": (
        "Field settings, bowling changes as decisions, and match-ups are not in "
        "Cricsheet's ball record."
    ),
}

# Mirrors the parser. A run out is not the bowler's wicket.
BOWLER_CREDITED_KINDS = {
    "bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket",
}
# A retirement is not a dismissal, so it does not end a partnership by wicket.
NOT_OUT_KINDS = {"retired hurt", "retired not out"}


def _rate(n: float, d: float, places: int = 2) -> float | None:
    return round(n / d, places) if d else None


def compute(db: Session, match_id: str) -> MatchIntel | None:
    """Everything §22 supports for one match, from its deliveries."""
    rows = db.execute(
        select(Delivery).where(Delivery.match_id == match_id).order_by(
            Delivery.innings, Delivery.seq
        )
    ).scalars().all()
    if not rows:
        return None

    names = {
        p.identifier: preferred_name(p.name, p.display_name)
        for p in db.execute(select(Player)).scalars()
    }
    teams = dict(db.execute(select(Team.team_id, Team.name)).all())

    def who(pid: str | None) -> str:
        return names.get(pid or "", pid or "unknown")

    out = MatchIntel(match_id=match_id, deferred=dict(DEFERRED))

    by_innings: dict[int, list[Delivery]] = {}
    for d in rows:
        by_innings.setdefault(d.innings, []).append(d)

    for innings, balls in sorted(by_innings.items()):
        intel = InningsIntel(
            innings=innings,
            batting_team=teams.get(balls[0].batting_team_id or -1),
            runs=sum(b.runs_total for b in balls),
            # A wicket that is a retirement is not a dismissal.
            wickets=sum(
                1 for b in balls if b.wicket_kind and b.wicket_kind not in NOT_OUT_KINDS
            ),
            balls=sum(1 for b in balls if not b.wides and not b.noballs),
            run_rate=None,
        )
        intel.run_rate = _rate(
            sum(b.runs_total for b in balls) * 6.0,
            sum(1 for b in balls if not b.wides and not b.noballs),
        )
        intel.partnerships = _partnerships(balls, who)
        intel.spells = _spells(balls, who)
        intel.overs = _overs(balls, innings)
        out.innings.append(intel)

    return out


def _partnerships(balls: list[Delivery], who) -> list[Partnership]:
    """Stands, keyed on the pair at the crease."""
    stands: list[Partnership] = []
    current: dict | None = None
    wicket_no = 0

    for b in balls:
        pair = frozenset(x for x in (b.batter, b.non_striker) if x)
        if current is None or current["pair"] != pair:
            if current is not None:
                stands.append(_close(current, who, unbroken=False, kind=None))
            wicket_no += 1
            current = {
                "pair": pair, "runs": 0, "balls": 0,
                "start_over": b.over, "end_over": b.over, "wicket": wicket_no,
            }
        current["runs"] += b.runs_total
        if not b.wides:
            current["balls"] += 1
        current["end_over"] = b.over
        if b.wicket_kind and b.wicket_kind not in NOT_OUT_KINDS:
            stands.append(_close(current, who, unbroken=False, kind=b.wicket_kind))
            current = None

    if current is not None:
        # Still together when the innings ended: all out at the other end, or
        # overs exhausted, or a declaration.
        stands.append(_close(current, who, unbroken=True, kind=None))
    return stands


def _close(c: dict, who, *, unbroken: bool, kind: str | None) -> Partnership:
    pair = sorted(c["pair"])
    return Partnership(
        innings=0,
        wicket=c["wicket"],
        batter_a=who(pair[0] if pair else None),
        batter_b=who(pair[1] if len(pair) > 1 else None),
        runs=c["runs"],
        balls=c["balls"],
        run_rate=_rate(c["runs"] * 6.0, c["balls"]),
        unbroken=unbroken,
        ended_by=kind,
        start_over=c["start_over"],
        end_over=c["end_over"],
    )


def _spells(balls: list[Delivery], who) -> list[Spell]:
    """Runs of consecutive overs by the same bowler."""
    # over -> bowler, plus that over's figures
    overs: dict[int, dict] = {}
    for b in balls:
        o = overs.setdefault(
            b.over, {"bowler": b.bowler, "runs": 0, "balls": 0, "wickets": 0}
        )
        o["runs"] += b.runs_batter + b.wides + b.noballs
        if not b.wides and not b.noballs:
            o["balls"] += 1
        if b.wicket_kind in BOWLER_CREDITED_KINDS:
            o["wickets"] += 1

    # Grouped BY BOWLER first. Walking the innings in over order instead closes
    # every spell after one over, because the bowler changes at the end of each
    # -- a bowler cannot bowl consecutive overs, so their overs are never
    # adjacent in the innings sequence.
    by_bowler: dict[str, list[int]] = {}
    for over, o in overs.items():
        if o["bowler"]:
            by_bowler.setdefault(o["bowler"], []).append(over)

    spells: list[Spell] = []
    for bowler, their_overs in by_bowler.items():
        current: dict | None = None
        for over in sorted(their_overs):
            # Bowlers alternate ends, so consecutive overs in a spell are two
            # apart. A larger gap means they were taken off and brought back,
            # which is a second spell -- and telling those apart is the whole
            # point, since match figures hide it.
            if current and over - current["end_over"] > MAX_SPELL_GAP:
                spells.append(_close_spell(current, who))
                current = None
            if current is None:
                current = {
                    "bowler": bowler, "runs": 0, "balls": 0, "wickets": 0,
                    "overs": 0, "start_over": over, "end_over": over,
                }
            o = overs[over]
            current["runs"] += o["runs"]
            current["balls"] += o["balls"]
            current["wickets"] += o["wickets"]
            current["overs"] += 1
            current["end_over"] = over
        if current:
            spells.append(_close_spell(current, who))

    spells.sort(key=lambda s: (s.start_over, s.bowler))
    return spells


def _close_spell(c: dict, who) -> Spell:
    return Spell(
        innings=0,
        bowler=who(c["bowler"]),
        overs=c["overs"],
        balls=c["balls"],
        runs_conceded=c["runs"],
        wickets=c["wickets"],
        economy=_rate(c["runs"] * 6.0, c["balls"]),
        start_over=c["start_over"],
        end_over=c["end_over"],
    )


def _overs(balls: list[Delivery], innings: int) -> list[OverPoint]:
    """The momentum series: what each over produced, and the running total."""
    per: dict[int, list[int]] = {}
    for b in balls:
        e = per.setdefault(b.over, [0, 0])
        e[0] += b.runs_total
        if b.wicket_kind and b.wicket_kind not in NOT_OUT_KINDS:
            e[1] += 1

    points, runs, wkts = [], 0, 0
    for over in sorted(per):
        r, w = per[over]
        runs += r
        wkts += w
        points.append(
            OverPoint(
                innings=innings, over=over, runs=r, wickets=w,
                cumulative_runs=runs, cumulative_wickets=wkts,
            )
        )
    return points


__all__ = ["compute", "MatchIntel", "InningsIntel", "Partnership", "Spell",
           "OverPoint", "DEFERRED", "NOTABLE_PARTNERSHIP_RUNS"]

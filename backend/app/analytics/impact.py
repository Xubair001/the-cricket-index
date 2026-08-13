r"""Per-match impact -- one comparable number for what a player did in a match.

Why this exists
---------------
Form cannot be measured on runs, because runs answer a different question in
every format: 45 off 30 wins a T20 and 45 off 140 saves a Test. Ranking form by
runs also silently ranks batters above bowlers, and openers above finishers,
because it measures opportunity as much as performance.

So each performance is converted into **runs-equivalent value**: how many runs
the player's contribution was worth compared with what a par performer would
have produced from the same opportunity. Batting and bowling both land in runs,
which is what makes them addable into a single figure for an all-rounder.

    batting = runs + (runs - par_scoring_rate x balls_faced)
              \___/   \_________________________________/
              volume    efficiency: runs above the going rate

    bowling = wickets x cost_of_a_wicket + (par_economy - economy) x overs
              \_______________________/   \______________________________/
                   wickets in runs                   runs saved

Par is measured, not assumed
----------------------------
Every par figure comes from the dataset, grouped by (competition, gender). A
women's T20I has a different par scoring rate from a men's Test, and both differ
from the PSL; hardcoding any of them would bake in whichever format happened to
be in mind. Thin competitions fall back to their gender's global par rather than
producing a wild par from a handful of matches.

Comparing across formats
------------------------
Runs-equivalent is only comparable *within* a competition. Measured over this
dataset, a men's Test appearance is worth a mean 91.1 runs-equivalent against
23.7 for a men's T20I -- nearly four times as much, because a Test innings has
far more balls in it. Left uncorrected, a player who stops playing Tests and
plays only T20Is registers a collapse in form having done nothing differently.

So every impact also carries `normalized`: the figure divided by the mean
appearance in its own (competition, gender) slice. Par is 1.0 in every format,
and the form engine works entirely in these units. The raw runs-equivalent is
kept alongside because it is the readable one when the scope is a single
competition.

What this is not
----------------
It is not a substitute for the ball-by-ball model. Without deliveries there is
no phase, no situation, and no notion of whether a chase was under pressure --
so a match-winning 40 in a collapse and a dead-rubber 40 score the same. That
gap is Tier B in the scope document; this model is the honest ceiling on
match-level data, and it is built so those terms can be added without changing
its shape.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Competition, Match, PlayerMatchStat
from . import config

GLOBAL = "__all__"


@dataclass(frozen=True)
class Par:
    """Reference performance for one (competition, gender) slice."""

    scoring_rate: float       # runs per 100 balls faced
    economy: float            # runs conceded per over
    runs_per_wicket: float    # what one wicket is worth, in runs
    mean_impact: float        # runs-equivalent value of a typical appearance here
    balls: int                # sample size behind these figures
    measured: bool            # False when this is a fallback, not its own slice

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Impact:
    """A single performance, decomposed.

    Every component is kept rather than just the total, because Rule 5 applies
    to intermediate figures too: "impact 62" is only useful if the UI can show
    that it was 50 runs plus 12 for scoring them quickly.

    `total` is in runs-equivalent and is only comparable *within* a competition.
    `normalized` divides it by what a typical appearance in that competition is
    worth, so 1.0 means par everywhere -- see the note on cross-format
    comparison in the module docstring.
    """

    total: float
    normalized: float
    batting: float
    bowling: float
    batting_volume: float
    batting_efficiency: float
    bowling_wickets: float
    bowling_economy: float

    def as_dict(self) -> dict:
        return {k: round(v, 3) for k, v in asdict(self).items()}


ZERO = Impact(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


class ParTable:
    """Par figures for every (competition, gender) slice in the dataset."""

    def __init__(self, slices: dict[tuple[str, str], Par], globals_: dict[str, Par]):
        self._slices = slices
        self._globals = globals_

    def lookup(self, competition_key: str | None, gender: str) -> Par:
        if competition_key:
            found = self._slices.get((competition_key, gender))
            if found is not None:
                return found
        fallback = self._globals.get(gender)
        if fallback is not None:
            return fallback
        # An empty database. Par of zero makes impact collapse to raw runs,
        # which is wrong but inert -- better than dividing by nothing.
        return Par(0.0, 0.0, 0.0, 0.0, 0, measured=False)

    def slices(self) -> dict[tuple[str, str], Par]:
        return dict(self._slices)


_cache: ParTable | None = None


def par_table(db: Session, *, refresh: bool = False) -> ParTable:
    """Measure (and cache) par figures for the whole dataset.

    One aggregate over player_match_stats, held for the process lifetime. The
    underlying data only changes when the ingester runs, and §26 is explicit
    that expensive aggregates must not be recomputed per request.
    """
    global _cache
    if _cache is not None and not refresh:
        return _cache

    stmt = (
        select(
            Competition.key,
            Match.gender,
            func.sum(PlayerMatchStat.runs_scored),
            func.sum(PlayerMatchStat.balls_faced),
            func.sum(PlayerMatchStat.runs_conceded),
            func.sum(PlayerMatchStat.balls_bowled),
            func.sum(PlayerMatchStat.wickets_taken),
            func.count(),
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .join(Competition, Competition.competition_id == Match.competition_id)
        .group_by(Competition.key, Match.gender)
    )

    slices: dict[tuple[str, str], Par] = {}
    totals: dict[str, list[int]] = {}

    for key, gender, runs, balls, conceded, bowled, wickets, rows in db.execute(stmt).all():
        runs, balls = runs or 0, balls or 0
        conceded, bowled, wickets = conceded or 0, bowled or 0, wickets or 0
        rows = rows or 0

        acc = totals.setdefault(gender, [0, 0, 0, 0, 0, 0])
        for i, v in enumerate((runs, balls, conceded, bowled, wickets, rows)):
            acc[i] += v

        if balls >= config.MIN_BALLS_FOR_PAR:
            slices[(key, gender)] = _par_from(runs, balls, conceded, bowled, wickets, rows, True)

    # Competitions thinner than MIN_BALLS_FOR_PAR get no slice of their own and
    # resolve to their gender's global par via ParTable.lookup.
    globals_ = {gender: _par_from(*acc, True) for gender, acc in totals.items()}

    _cache = ParTable(slices, globals_)
    return _cache


def _par_from(runs, balls, conceded, bowled, wickets, rows, measured: bool) -> Par:
    # Mean impact has a closed form. Within a slice both efficiency terms sum to
    # exactly zero by the definition of par -- par_scoring_rate/100 x total_balls
    # IS total_runs, and par_economy x total_overs IS total_runs_conceded -- so
    # the sum of impact reduces to runs scored plus runs conceded. That saves a
    # second pass over every player-match row purely to compute a mean.
    return Par(
        scoring_rate=(runs * 100.0 / balls) if balls else 0.0,
        economy=(conceded * 6.0 / bowled) if bowled else 0.0,
        runs_per_wicket=(conceded / wickets) if wickets else 0.0,
        mean_impact=((runs + conceded) / rows) if rows else 0.0,
        balls=balls,
        measured=measured,
    )


_team_totals: dict[tuple[str, int], float] | None = None


def team_match_totals(db: Session, *, refresh: bool = False) -> dict[tuple[str, int], float]:
    """(match_id, team_id) -> that side's total runs-equivalent impact.

    Needed by anything asking "how much of this was the player's doing" -- a
    share of the side's effort, which is what makes a contribution comparable
    between a low-scoring match and a run fest.

    Impact is linear in the aggregates, so one GROUP BY down to (match, side)
    gives every total without a per-row pass.
    """
    global _team_totals
    if _team_totals is not None and not refresh:
        return _team_totals

    par = par_table(db)
    stmt = (
        select(
            PlayerMatchStat.match_id,
            PlayerMatchStat.team_id,
            Competition.key,
            Match.gender,
            func.sum(PlayerMatchStat.runs_scored),
            func.sum(PlayerMatchStat.balls_faced),
            func.sum(PlayerMatchStat.wickets_taken),
            func.sum(PlayerMatchStat.balls_bowled),
            func.sum(PlayerMatchStat.runs_conceded),
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .join(Competition, Competition.competition_id == Match.competition_id)
        .where(PlayerMatchStat.team_id.is_not(None))
        .group_by(PlayerMatchStat.match_id, PlayerMatchStat.team_id)
    )
    out: dict[tuple[str, int], float] = {}
    for match_id, team_id, key, gender, runs, bf, wkts, bb, conceded in db.execute(stmt).all():
        p = par_table(db).lookup(key, gender)
        out[(match_id, team_id)] = (
            2.0 * (runs or 0)
            - (p.scoring_rate / 100.0) * (bf or 0)
            + p.runs_per_wicket * (wkts or 0)
            + (p.economy / 6.0) * (bb or 0)
            - (conceded or 0)
        )
    _team_totals = out
    return out


def invalidate() -> None:
    """Drop the cached par table -- call after an ingest changes the dataset."""
    global _cache, _team_totals
    _cache = None
    _team_totals = None


def score(
    *,
    runs_scored: int,
    balls_faced: int,
    wickets_taken: int,
    balls_bowled: int,
    runs_conceded: int,
    par: Par,
) -> Impact:
    """Convert one player-match row into runs-equivalent impact."""
    batting_volume = float(runs_scored) * config.BATTING_VOLUME_WEIGHT
    batting_efficiency = 0.0
    if balls_faced:
        expected = par.scoring_rate / 100.0 * balls_faced
        batting_efficiency = (runs_scored - expected) * config.BATTING_EFFICIENCY_WEIGHT

    bowling_wickets = 0.0
    bowling_economy = 0.0
    if balls_bowled:
        overs = balls_bowled / 6.0
        bowling_wickets = wickets_taken * par.runs_per_wicket * config.BOWLING_WICKET_WEIGHT
        economy = runs_conceded * 6.0 / balls_bowled
        bowling_economy = (par.economy - economy) * overs * config.BOWLING_ECONOMY_WEIGHT

    batting = batting_volume + batting_efficiency
    bowling = bowling_wickets + bowling_economy
    total = batting + bowling
    return Impact(
        total=total,
        normalized=(total / par.mean_impact) if par.mean_impact else 0.0,
        batting=batting,
        bowling=bowling,
        batting_volume=batting_volume,
        batting_efficiency=batting_efficiency,
        bowling_wickets=bowling_wickets,
        bowling_economy=bowling_economy,
    )

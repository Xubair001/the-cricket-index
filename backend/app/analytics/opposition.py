r"""Opposition strength -- how hard the cricket was, not just how big the number.

The problem this solves
-----------------------
`impact.py` measures every performance against a par drawn from its
(competition, gender) slice. That makes a T20I innings comparable with a Test
innings, but it still treats every T20I as the same cricket: par for "T20I men"
is one figure covering India v Australia and Malta v Luxembourg alike.

The consequence was visible on the form board. Players whose recent cricket was
against Norway, Portugal and Malta ranked above Virat Kohli, because scoring
heavily against a weak attack produces the same normalized impact as scoring
heavily against a strong one. A decision-support tool that answers "who should I
look at" with a list sorted by weakness of opposition is worse than useless to a
selector -- it is confidently wrong.

How strength is measured
------------------------
Not from reputation, and not from win/loss records, which answer a different
question and are circular for this purpose. It is measured as a side's
opponents' **share of the impact generated inside their own matches**:

    concession[T] = mean over T's matches of  opp_impact / (opp_impact + T_impact)

normalized so that an even split (0.5) is an index of 1.0. Above 1.0 means
opponents take more than half the cricket played against T -- a weak side. Below
means T takes the larger share -- a strong one.

A performance against T is then scaled by the reciprocal:

    multiplier[T] = 1 / concession[T]

so runs against a weak attack are discounted and runs against a strong one are
credited.

Why the share is then fitted, and not used directly
---------------------------------------------------
A raw share measures dominance over *whoever a side happened to play*, which is
not the same as strength. Measured directly, UAE, Uganda and Japan came out
above Australia: they take a large share of their own matches because those
matches are against other associate sides. Using that, a player facing Japan
would have their figures marked *up*.

Strength has to be transitive, so the shares are fitted with a Bradley-Terry
model: each side gets a power `p`, and the share a side is expected to take
against an opponent is `p_self / (p_self + p_opponent)`. Fitting `p` to the
observed shares propagates difficulty through the fixture list -- beating a side
that beats strong sides counts; beating Malta does not. The fit runs by the
standard MM iteration, which is monotonic and needs no learning rate.

Pools are fitted separately per (competition type, gender), because men's and
women's sides never meet and franchise sides never play international ones. A
single fit across disconnected components would produce ratings on incomparable
scales that only look like one ladder.

The fitted powers are referenced against the opposition in an **average match**,
not the average team. There are ~110 men's international sides in this dataset
and most of them play a handful of matches, so a team-count reference puts "par
opposition" at roughly Malta -- which marked every Test nation up to the clamp
and made Australia and the West Indies indistinguishable. Weighting by matches
played puts the reference where the cricket actually is, and matches the
population `par.mean_impact` is itself measured over.

Why a *share*, and not the raw figure
-------------------------------------
The obvious measure -- mean normalized impact conceded to opponents -- is
invalid, and measurably so. It was tried first and ranked Indonesia the
strongest side in the dataset and Pakistan, West Indies and Sri Lanka among the
weakest, which is plainly backwards.

The reason is that impact is **not zero-sum within a match**, and a competition
slice is too coarse a control. "T20I men" covers India v Australia and Indonesia
v Mongolia alike. Associate matches are low-scoring for *both* sides, so every
player in them posts a below-par normalized impact -- and a side that only plays
such cricket therefore looks miserly, when all that has been measured is the
run-scoring environment. Test-playing nations, whose matches are long and
high-scoring, looked generous for the mirror-image reason.

Taking the share instead cancels the environment exactly: it is a ratio of two
quantities drawn from the same match, so how much cricket the match contained
divides out. A side is strong when it takes the larger share of what happened,
whoever it played and however low-scoring the game.

Two guards, both necessary
--------------------------
* **Shrinkage.** A side with 40 player-rows against them has a wildly unstable
  index, and inverting an unstable index produces a wilder multiplier. Each
  index is shrunk towards 1.0 (par, i.e. no adjustment) as though the side had
  `OPPOSITION_SHRINKAGE_ROWS` additional rows at exactly par. A side with
  thousands of rows keeps nearly all of its measured index; a side with a
  handful keeps almost none, which is the correct default -- absent evidence,
  assume average opposition rather than invent an adjustment.
* **Clamping.** Even shrunk, the tails are not to be trusted to the point of
  doubling or erasing a performance, so the multiplier is bounded.

What this deliberately is NOT
-----------------------------
It is not an Elo rating and not a ladder. It says nothing about which side would
win, and it must not be presented as a team ranking -- `concession` conflates
bowling strength with batting strength, since a single index covers both halves
of the game. Splitting it needs the per-innings data that Tier B unlocks.

It is also measured *including* the rated player's own rows. Excluding them per
player would mean a separate index per player; at thousands of rows per side the
self-contribution is immaterial, and shrinkage absorbs the rest. For a side with
few rows the index is shrunk almost to 1.0 anyway, so the circularity cannot
produce a meaningful self-boost.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Competition, Match, PlayerMatchStat
from . import config
from .impact import GLOBAL, ParTable, par_table


class OppositionTable:
    """Per-side concession indices, and the multipliers derived from them."""

    def __init__(
        self,
        indices: dict[tuple[int, str], tuple[float, int]],
        overall: dict[int, tuple[float, int]],
    ):
        # (team_id, competition_key) -> (shrunk index, rows behind it)
        self._indices = indices
        # team_id -> (shrunk index, rows) across every competition
        self._overall = overall

    def index(self, team_id: int | None, competition_key: str | None) -> tuple[float, int]:
        """The concession index for a side, most specific slice first."""
        if team_id is None:
            return 1.0, 0
        if competition_key:
            found = self._indices.get((team_id, competition_key))
            if found is not None:
                return found
        return self._overall.get(team_id, (1.0, 0))

    def multiplier(self, team_id: int | None, competition_key: str | None) -> float:
        """How much a performance against this side is worth, versus par."""
        if not config.OPPOSITION_ADJUSTMENT_ENABLED:
            return 1.0
        idx, _rows = self.index(team_id, competition_key)
        if idx <= 0:
            return 1.0
        low, high = config.OPPOSITION_MULTIPLIER_BOUNDS
        return max(low, min(high, 1.0 / idx))

    def as_rows(self) -> list[dict]:
        """Every measured side, strongest first -- for inspection and the API."""
        rows = [
            {
                "team_id": team_id,
                "competition_key": None,
                "concession_index": round(idx, 4),
                "multiplier": round(self.multiplier(team_id, None), 4),
                "rows": n,
            }
            for team_id, (idx, n) in self._overall.items()
        ]
        rows.sort(key=lambda r: r["concession_index"])
        return rows


_cache: OppositionTable | None = None


def invalidate() -> None:
    """Drop the cached table -- call after an ingest changes the dataset."""
    global _cache
    _cache = None


def _shrink(index: float, rows: int) -> float:
    """Pull a measured index towards 1.0 in proportion to how thin it is."""
    k = config.OPPOSITION_SHRINKAGE_ROWS
    return (rows * index + k * 1.0) / (rows + k) if (rows + k) else 1.0


def table(db: Session, *, refresh: bool = False) -> OppositionTable:
    """Measure (and cache) concession indices for every side in the dataset.

    One GROUP BY down to (match, side) -- roughly 20,000 groups over 10,040
    matches, not a per-row pass over all 221k player-match rows. Impact is
    linear in the aggregates, so a side's total for a match needs only that
    group's summed runs, balls, wickets and concessions:

        sum(impact) = 2*runs - (par_sr/100)*balls_faced
                      + par_rpw*wickets + (par_econ/6)*balls_bowled - conceded

    The two sides of each match are then paired up in Python to form the share.
    """
    global _cache
    if _cache is not None and not refresh:
        return _cache

    par: ParTable = par_table(db)

    stmt = (
        select(
            PlayerMatchStat.match_id,
            PlayerMatchStat.team_id,
            Competition.key,
            Competition.type,
            Match.gender,
            func.sum(PlayerMatchStat.runs_scored),
            func.sum(PlayerMatchStat.balls_faced),
            func.sum(PlayerMatchStat.wickets_taken),
            func.sum(PlayerMatchStat.balls_bowled),
            func.sum(PlayerMatchStat.runs_conceded),
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .join(Competition, Competition.competition_id == Match.competition_id)
        .where(
            PlayerMatchStat.player_identifier.is_not(None),
            PlayerMatchStat.team_id.is_not(None),
            Match.team1_id.is_not(None),
            Match.team2_id.is_not(None),
        )
        .group_by(PlayerMatchStat.match_id, PlayerMatchStat.team_id)
    )

    # match_id -> the per-side impact totals within it, plus its fitting pool
    sides: dict[str, list[tuple[int, float]]] = {}
    pool_of: dict[str, tuple[str, str]] = {}

    for match_id, team_id, comp_key, comp_type, gender, runs, bf, wkts, bb, conceded in db.execute(stmt).all():
        p = par.lookup(comp_key, gender)
        if not p.mean_impact:
            continue
        impact_sum = (
            2.0 * (runs or 0)
            - (p.scoring_rate / 100.0) * (bf or 0)
            + p.runs_per_wicket * (wkts or 0)
            + (p.economy / 6.0) * (bb or 0)
            - (conceded or 0)
        )
        sides.setdefault(match_id, []).append((team_id, impact_sum))
        pool_of[match_id] = (comp_type or "unknown", gender or "unknown")

    # One Bradley-Terry pool per (competition type, gender): disconnected sets
    # of sides must not be fitted onto a single scale.
    pools: dict[tuple[str, str], list[tuple[int, int, float, float]]] = {}
    played: dict[int, int] = {}

    for match_id, entries in sides.items():
        if len(entries) != 2:
            # A match with only one side's rows says nothing about a split.
            continue
        (team_a, impact_a), (team_b, impact_b) = entries
        total = impact_a + impact_b
        if total <= 0:
            # Both sides negative-or-zero: a washout or a freak low-scorer.
            # There is no meaningful share to take.
            continue
        pools.setdefault(pool_of[match_id], []).append(
            (team_a, team_b, impact_a / total, impact_b / total)
        )
        played[team_a] = played.get(team_a, 0) + 1
        played[team_b] = played.get(team_b, 0) + 1

    overall: dict[int, tuple[float, int]] = {}
    for matches in pools.values():
        powers = _fit_bradley_terry(matches)
        if not powers:
            continue
        # The reference is the opposition in an AVERAGE MATCH, not the average
        # team. Most international sides are associates who play rarely, so a
        # team-count mean puts "par opposition" at roughly Malta and marks every
        # Test nation up to the clamp. Weighting by matches played puts it where
        # the cricket actually is, which is also the population `par.mean_impact`
        # is measured over -- so the two normalizations agree.
        weight_total = sum(played.get(t, 0) for t in powers)
        reference = (
            sum(p * played.get(t, 0) for t, p in powers.items()) / weight_total
            if weight_total
            else 1.0
        ) or 1.0
        for team, power in powers.items():
            # Expected share the reference side takes against this one, divided
            # by an even split so average opposition reads as an index of 1.0.
            index = (reference / (reference + power)) / 0.5
            n = played.get(team, 0)
            overall[team] = (_shrink(index, n), n)

    # Per-competition slices are left empty: a side's power is fitted across its
    # whole pool, and re-fitting per competition splits already-thin fixture
    # lists into components too sparse to rate. `index()` falls through to the
    # pool figure, which is the honest resolution rather than a noisier one.
    _cache = OppositionTable({}, overall)
    return _cache


def _fit_bradley_terry(
    matches: list[tuple[int, int, float, float]],
    iterations: int = config.OPPOSITION_FIT_ITERATIONS,
) -> dict[int, float]:
    """Fit a power per side from observed impact shares.

    The standard MM update for Bradley-Terry, which is monotonic in the
    likelihood and needs no step size:

        p[T] <- (total share T took) / (sum over T's matches of 1/(p[T] + p[O]))

    Fractional outcomes are admissible here for the same reason partial credit is
    in a weighted logistic fit -- the update only ever uses summed shares.
    Powers are renormalised to a mean of 1.0 each round, which fixes the scale
    that Bradley-Terry leaves free and keeps "average side" at exactly 1.0.
    """
    teams = {t for m in matches for t in (m[0], m[1])}
    if not teams:
        return {}

    power = {t: 1.0 for t in teams}
    taken: dict[int, float] = {t: 0.0 for t in teams}
    for a, b, share_a, share_b in matches:
        taken[a] += share_a
        taken[b] += share_b

    for _ in range(iterations):
        denom: dict[int, float] = {t: 0.0 for t in teams}
        for a, b, _sa, _sb in matches:
            pair = power[a] + power[b]
            if pair <= 0:
                continue
            denom[a] += 1.0 / pair
            denom[b] += 1.0 / pair

        for t in teams:
            if denom[t] > 0 and taken[t] > 0:
                power[t] = taken[t] / denom[t]

        mean = sum(power.values()) / len(power)
        if mean > 0:
            for t in teams:
                power[t] /= mean

    return power


__all__ = ["table", "invalidate", "OppositionTable", "GLOBAL"]

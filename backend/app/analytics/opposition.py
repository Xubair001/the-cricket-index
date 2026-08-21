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

What this is, and what it is not
---------------------------------
It is a **difficulty rating**: how hard a side is to play against, fitted from
results and validated against ICC team ratings at Spearman rho +0.81 to +0.83
across all three formats. That correlation is a check, never an input -- §6
keeps official ratings out of derived figures.

It is NOT a prediction of who would win a given match, and it is NOT an official
rating. It also **conflates batting and bowling strength**: a single index covers
both halves of the game, so a side with a fearsome attack and a brittle top order
reads the same as a balanced one of equal overall difficulty. Splitting it needs
the per-innings data that Tier B unlocks.

Presented as a ladder it must carry all three of those qualifications, which is
why the surface that shows it says so on the page rather than in a tooltip.

It is also measured *including* the rated player's own rows. Excluding them per
player would mean a separate index per player; at thousands of rows per side the
self-contribution is immaterial, and shrinkage absorbs the rest. For a side with
few rows the index is shrunk almost to 1.0 anyway, so the circularity cannot
produce a meaningful self-boost.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import cache

from ..models import Competition, Match, PlayerMatchStat
from . import config
from .impact import GLOBAL, ParTable, par_table


class OppositionTable:
    """Per-side concession indices, and the multipliers derived from them."""

    def __init__(
        self,
        by_era: dict[tuple[int, str], tuple[float, int]],
        overall: dict[int, tuple[float, int]],
    ):
        # (team_id, era) -> (shrunk index, matches in that era)
        self._by_era = by_era
        # team_id -> (shrunk index, matches) across every era
        self._overall = overall

    def index(
        self, team_id: int | None, era: str | None = None
    ) -> tuple[float, int]:
        """The concession index for a side, in an era if one is given."""
        if team_id is None:
            return 1.0, 0
        if era:
            found = self._by_era.get((team_id, era))
            if found is not None:
                return found
        return self._overall.get(team_id, (1.0, 0))

    def era_index(self, team_id: int | None, era: str) -> tuple[float, int] | None:
        """This era's own fit, or None if the side played no cricket in it.

        Distinct from `index()`, which deliberately FALLS BACK to the long-run
        figure -- correct when scoring a match, because an unfitted era should
        still be adjusted by something. It is wrong for display: the fallback
        returns the side's whole-career index and match count, so an era a side
        never played reads as if they played their entire career in it.
        """
        return self._by_era.get((team_id, era)) if team_id is not None else None

    def multiplier_for_era(self, team_id: int | None, era: str | None) -> float:
        """As `multiplier`, for callers that already grouped by era in SQL."""
        if not config.OPPOSITION_ADJUSTMENT_ENABLED:
            return 1.0
        idx, _n = self.index(team_id, era)
        if idx <= 0:
            return 1.0
        low, high = config.OPPOSITION_MULTIPLIER_BOUNDS
        return max(low, min(high, 1.0 / idx))

    def multiplier(self, team_id: int | None, match_date: str | None = None) -> float:
        """How much a performance against this side, at that time, is worth.

        Passing the date is what makes this "standing at the time" rather than a
        career average -- see the era note in `config`.
        """
        if not config.OPPOSITION_ADJUSTMENT_ENABLED:
            return 1.0
        idx, _n = self.index(team_id, era_of(match_date) if match_date else None)
        if idx <= 0:
            return 1.0
        low, high = config.OPPOSITION_MULTIPLIER_BOUNDS
        return max(low, min(high, 1.0 / idx))

    def era_keys(self) -> list[tuple[int, str]]:
        """Every (team, era) pair that has a fitted index."""
        return list(self._by_era.keys())

    def as_rows(self) -> list[dict]:
        """Every measured side, strongest first -- for inspection and the API."""
        rows = [
            {
                "team_id": team_id,
                "era": None,
                "concession_index": round(idx, 4),
                "multiplier": round(self.multiplier(team_id), 4),
                "rows": n,
            }
            for team_id, (idx, n) in self._overall.items()
        ]
        rows.sort(key=lambda r: (r["concession_index"], r.get("team_name") or ""))
        return rows


_cache: OppositionTable | None = None
_cache_version: tuple | None = None


def _cache_stale(db: Session) -> bool:
    """True when the ingester has committed since this module last fitted."""
    global _cache_version
    # `cache.generation` and not `cache.data_version`: the raw counter also moves
    # on a WAL checkpoint, which would drop this cache several times a minute
    # while the ingestion worker is up and nothing had actually changed.
    current = cache.generation(db)
    if _cache_version != current:
        _cache_version = current
        return True
    return False


def invalidate() -> None:
    """Drop the cached table -- call after an ingest changes the dataset."""
    global _cache
    _cache = None


def era_of(match_date: str | None) -> str:
    """The era bucket a match falls in. Unknown dates get their own bucket.

    Bucketing by fixed span rather than a rolling window keeps one fit per
    (pool, era) instead of one per match, which is what makes this affordable.
    """
    if not match_date or len(match_date) < 4 or not match_date[:4].isdigit():
        return "unknown"
    year = int(match_date[:4])
    span = config.OPPOSITION_ERA_YEARS
    return str((year // span) * span)


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
    if refresh or _cache_stale(db):
        _cache = None
    if _cache is not None:
        return _cache

    par: ParTable = par_table(db)

    stmt = (
        select(
            PlayerMatchStat.match_id,
            PlayerMatchStat.team_id,
            Competition.key,
            Competition.type,
            Match.gender,
            Match.match_date_start,
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
        # The four match-level columns are in the GROUP BY although they are
        # constant within each (match, team) group: SQLite allows a bare column
        # here and Postgres does not, and Postgres infers functional dependency
        # only through a grouped primary key. Listing them changes no grouping.
        .group_by(
            PlayerMatchStat.match_id,
            PlayerMatchStat.team_id,
            Competition.key,
            Competition.type,
            Match.gender,
            Match.match_date_start,
        )
    )

    # match_id -> the per-side impact totals within it, plus its fitting pool
    sides: dict[str, list[tuple[int, float]]] = {}
    pool_of: dict[str, tuple[str, str]] = {}

    dates: dict[str, str | None] = {}
    for match_id, team_id, comp_key, comp_type, gender, match_date, runs, bf, wkts, bb, conceded in db.execute(stmt).all():
        dates[match_id] = match_date
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

    # One Bradley-Terry pool per (competition type, gender, era). Disconnected
    # sets of sides must not share a scale, and neither must different decades.
    pools: dict[tuple, list[tuple[int, int, float, float]]] = {}
    played: dict[int, int] = {}
    played_era: dict[tuple[int, str], int] = {}

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
        era = era_of(dates.get(match_id))
        pools.setdefault(pool_of[match_id] + (era,), []).append(
            (team_a, team_b, impact_a / total, impact_b / total)
        )
        for t in (team_a, team_b):
            played[t] = played.get(t, 0) + 1
            played_era[(t, era)] = played_era.get((t, era), 0) + 1

    # Fitted per (pool, era), then also pooled across eras so a thin era can be
    # shrunk towards the side's own long-run figure rather than towards 1.0.
    era_index: dict[tuple[int, str], float] = {}
    all_era_pools: dict[tuple, list] = {}
    for key, matches in pools.items():
        all_era_pools.setdefault(key[:-1], []).extend(matches)

    # The era reference is taken over a STABLE CORE, not over each era's whole
    # population, and this is not a detail.
    #
    # In 2019 the ICC granted T20I status to all its members, so the 2020s pool
    # contains dozens of associate sides that played no international cricket in
    # the 2000s. Referenced against its own era's average, every established
    # side therefore *inflates* in the 2020s -- Australia came out harder to face
    # in 2020 than in 2000, which is not true, it is only that the average
    # opponent got weaker. That breaks the one thing the multiplier exists for:
    # making performances comparable across time.
    #
    # Sides appearing with real volume in most eras give a yardstick that means
    # the same thing in every era, so an era index is measured against cricket's
    # persistent core rather than against whoever happened to hold status.
    eras_present: dict[int, set[str]] = {}
    for (team, era), n in played_era.items():
        if n >= config.OPPOSITION_CORE_MIN_MATCHES_PER_ERA:
            eras_present.setdefault(team, set()).add(era)
    core = {
        t
        for t, eras in eras_present.items()
        if len(eras) >= config.OPPOSITION_CORE_MIN_ERAS
    }

    for key, matches in pools.items():
        era = key[-1]
        powers = _fit_bradley_terry(matches)
        if not powers:
            continue
        anchors = {t: p for t, p in powers.items() if t in core} or powers
        weight_total = sum(played_era.get((t, era), 0) for t in anchors)
        reference = (
            sum(p * played_era.get((t, era), 0) for t, p in anchors.items()) / weight_total
            if weight_total else 1.0
        ) or 1.0
        for team, power in powers.items():
            era_index[(team, era)] = (reference / (reference + power)) / 0.5

    overall: dict[int, tuple[float, int]] = {}
    for matches in all_era_pools.values():
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

    # Each era's own fit, pulled towards the side's all-era figure in proportion
    # to how little cricket that era holds for them.
    by_era: dict[tuple[int, str], tuple[float, int]] = {}
    k = config.OPPOSITION_ERA_SHRINKAGE_MATCHES
    for (team, era), idx in era_index.items():
        n = played_era.get((team, era), 0)
        long_run = overall.get(team, (1.0, 0))[0]
        by_era[(team, era)] = ((n * idx + k * long_run) / (n + k), n)

    _cache = OppositionTable(by_era, overall)
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

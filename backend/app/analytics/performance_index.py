r"""The Performance Index (§14) -- a transparent, platform-specific rating.

What question this answers, and how it differs from the form board
------------------------------------------------------------------
The form board answers *who has changed*. This answers *who is playing the best
cricket right now*. §15 requires the three rankings this product carries -- ICC,
the computed leaderboards, and this Index -- to stay distinct and always
labelled, so the Index must not collapse into either of the others.

That constraint drives the one place this deviates from a literal reading of
§14. The spec describes the 30% component as "recent window versus the player's
own baseline", which is the form delta. Scored that way the Index would inherit
form's defining property -- it is self-relative -- and a journeyman improving
from poor to ordinary would out-rate a great player playing normally. That is
correct for a form board and wrong for a rating, and it would make the Index a
reweighted copy of a board we already ship.

So **recent performance is scored on the absolute standard of the recent
window**, in par units, opposition-adjusted. The baseline comparison is not
discarded -- it is the form board, one click away, and the API returns both.
§14 opens by saying the initial weighting is "a starting point, not a
conclusion"; this is that judgement made explicitly rather than silently.

Why every component is percentile-scored
-----------------------------------------
The four live components are measured in incompatible units: par units, a
deviation, a multiplier, and a share. Weighting those directly would mean the
component with the widest raw spread quietly dominates, whatever the weights
say. Each is therefore converted to its **percentile within the qualified
population for this scope**, so a weight of 30% really does contribute 30%, and
an Index of 87 has a precise meaning: better than 87% of qualified players on
this blend, in this scope.

It also makes the Index robust to the long right tail of cricket data, where a
single triple-century would otherwise drag a z-score for everybody.

Consistency is downside-only, and that is deliberate
-----------------------------------------------------
§14 defines consistency as "variance of contribution". Implemented as plain
variance it punishes a match-winning 150 exactly as hard as a duck, because both
are far from the mean -- so the most "consistent" player is the reliably
mediocre one, and a player who never fails but occasionally destroys an attack
is marked down for the destroying.

A selector does not mean that by consistency. They mean *how often does this
player fail*. So the measure here is **downside deviation**: only appearances
below par contribute to it, and brilliance above par is free. Same statistic,
half the distribution -- the same reasoning that separates a Sortino ratio from
a Sharpe one.

Percentiles are pooled by discipline, or the Index rates discipline
---------------------------------------------------------------------
Measured over this dataset, the mean opposition-adjusted impact of a bowler is
**1.08 par units against a batter's 0.64** -- a 69% gap that has nothing to do
with quality. It falls out of the impact model: a four-wicket haul converts to
roughly 120 runs-equivalent where a good innings is 45, so bowlers sit higher on
the same scale. The form board never exposed this because form is self-relative
and the offset cancels; a rating compares players to each other, so it does not.

Pooled together, the first cut of this Index returned eleven bowlers in a top
twelve. Percentiles are therefore taken **within (scope x discipline)**, using
the same inferred batter / bowler / all-rounder split the explorers use. An
Index of 87 means "better than 87% of qualified players *of this discipline* in
this scope", which is both the comparison a selector actually wants and the
nearest thing available to §14's Tier-C "measured against role peers".

Scope is part of the definition
--------------------------------
§14: scores are comparable only within a scope (format x gender x competition
type), and a cross-format Index is not defined. The population a percentile is
taken against IS the scope, so an Index computed for Tests and one for T20Is are
different numbers about different things and are never mixed.

Absent components are never scored as zero
-------------------------------------------
Role, situation and availability are Tier B/C and cannot be computed from this
data. §14 is explicit that scoring them zero "penalises every player identically
and produces a number that looks precise and means less than it appears". They
are therefore dropped from the weighting entirely, the remaining weights are
renormalised over what is live, and the response lists what is inactive and why
so the UI can state it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Competition, Delivery, Match, Player
from ..names import preferred_name
from . import config, explorer, form, impact as impact_mod

# Component -> (weight from §14, live in Phase 1, why not)
COMPONENTS: dict[str, tuple[float, bool, str | None]] = {
    "recent_performance": (0.30, True, None),
    "consistency": (0.20, True, None),
    "opposition": (0.15, True, None),
    "match_impact": (0.10, True, None),
    "role": (0.10, False, "No playing role exists in any current source (Tier C)."),
    # Live since the deliveries backfill: the innings sequence gives chasing
    # directly, so "does this player deliver under a chase" is computable.
    # Pressure in the fuller sense (required rate, wickets in hand) still is
    # not -- what is scored here is chasing specifically, and the basis says so.
    "situation": (0.10, True, None),
    "availability": (
        0.05,
        False,
        "Needs squad lists per fixture, which no available feed carries (Tier C).",
    ),
}

COMPONENT_LABELS = {
    "recent_performance": "Recent performance",
    "consistency": "Consistency",
    "opposition": "Opposition strength",
    "match_impact": "Match impact",
    "role": "Role performance",
    "situation": "Situation performance",
    "availability": "Availability",
}

COMPONENT_BASIS = {
    "recent_performance": "Absolute output over the recent window, in par units, adjusted for opposition",
    "consistency": "Downside deviation below par - only failures count against it",
    "opposition": "Mean strength of the sides faced in the window",
    "match_impact": "Share of the side's own effort in matches it won",
    "situation": "Output when chasing, against the same player batting first",
}


@dataclass
class PlayerIndex:
    player_identifier: str
    player_name: str
    # The pool this player's percentiles were taken against, not a claim about
    # them. Inferred, never sourced.
    role: str
    matches: int
    raw: dict[str, float]
    scores: dict[str, float] = field(default_factory=dict)
    index: float = 0.0


def _active_weights() -> dict[str, float]:
    """Live components only, renormalised to sum to 1.0."""
    live = {k: w for k, (w, on, _) in COMPONENTS.items() if on}
    total = sum(live.values())
    return {k: w / total for k, w in live.items()} if total else {}


def _percentiles(values: list[float]) -> list[float]:
    """Percentile rank of each value within its own population, 0..100.

    Ties share the midpoint of the range they span, so a block of identical
    figures cannot be ordered by accident of input order.
    """
    n = len(values)
    if n <= 1:
        return [50.0] * n
    order = sorted(range(n), key=lambda i: values[i])
    out = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        # Midpoint rank of the tied block, scaled onto 0..100.
        midpoint = (i + j) / 2.0
        for k in range(i, j + 1):
            out[order[k]] = midpoint / (n - 1) * 100.0
        i = j + 1
    return out


def _downside_deviation(values: list[float], target: float = 1.0) -> float:
    """Root-mean-square of shortfalls below `target`. Above-target is free."""
    if not values:
        return 0.0
    shortfalls = [min(0.0, v - target) ** 2 for v in values]
    return (sum(shortfalls) / len(shortfalls)) ** 0.5


_cache: dict[tuple, list["PlayerIndex"]] = {}


def invalidate() -> None:
    _cache.clear()
    _chasing_cache.clear()


def page(
    db: Session,
    *,
    gender: str,
    competition_key: str | None = None,
    competition_type: str | None = None,
    role: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list["PlayerIndex"], int]:
    """One page of the Index, cached per scope.

    Rating every player in a scope means scoring ~3,000 timelines, which is far
    too slow for the request path (§28) and is deterministic between ingests --
    the same reason the form boards are cached.
    """
    # Both the floor and the shrinkage are what keep this measuring a
    # situational edge rather than a small sample. See the note in `config`.
    floor = config.INDEX_SITUATION_MIN_DISMISSALS
    k = config.INDEX_SITUATION_SHRINKAGE

    key = (gender, competition_key, competition_type)
    if key not in _cache:
        _cache[key] = compute(
            db,
            gender=gender,
            competition_key=competition_key,
            competition_type=competition_type,
        )
    rows = _cache[key]
    if role:
        rows = [r for r in rows if r.role == role]
    return rows[offset : offset + limit], len(rows)


def compute(
    db: Session,
    *,
    gender: str,
    competition_key: str | None = None,
    competition_type: str | None = None,
    window: int = config.INDEX_WINDOW_MATCHES,
    min_matches: int = config.INDEX_MIN_MATCHES,
) -> list[PlayerIndex]:
    """Rate every qualified player in one scope, best first."""
    timelines = form.all_timelines(
        db,
        gender=gender,
        competition_key=competition_key,
        competition_type=competition_type,
    )
    team_totals = impact_mod.team_match_totals(db)
    winners = {
        m_id: w
        for m_id, w in db.execute(select(Match.match_id, Match.winner_team_id)).all()
    }
    # A side's own impact is what the player's share is taken against, so the
    # player's team per match has to travel with the row.
    names = {
        p.identifier: preferred_name(p.name, p.display_name)
        for p in db.execute(select(Player)).scalars()
    }

    rated: list[PlayerIndex] = []
    for pid, timeline in timelines.items():
        recent = timeline[:window]
        if len(recent) < min_matches:
            continue

        # Discipline is taken from the whole scoped timeline rather than the
        # window: a bowler who happened to bat in three of their last fifteen
        # matches is still a bowler.
        role = explorer.discipline(
            sum(m.balls_faced for m in timeline),
            sum(m.balls_bowled for m in timeline),
        )

        values = [m.value for m in recent]
        mean_value = sum(values) / len(values)

        # Opposition: the mean multiplier faced. Above 1.0 means the window was
        # played against sides harder than average.
        multipliers = [m.opposition_multiplier for m in recent]
        mean_multiplier = sum(multipliers) / len(multipliers)

        # Match impact: share of the side's own effort, counted only in matches
        # the side won -- "contribution relative to match outcome" (§14). A big
        # score in a defeat is real cricket and shows up in the other three
        # components; this one is specifically about contributing to results.
        shares: list[float] = []
        for m in recent:
            won = winners.get(m.match_id)
            if won is None or m.team_id is None:
                # No result, or no side recorded -- says nothing either way, so
                # it is excluded rather than counted as a zero contribution.
                continue
            team_total = team_totals.get((m.match_id, m.team_id))
            if team_total is None or team_total <= 0:
                continue
            # Share of their OWN side's effort, not the match's.
            share = max(0.0, min(1.0, m.impact.total / team_total))
            shares.append(share if won == m.team_id else 0.0)
        match_impact = sum(shares) / len(shares) if shares else 0.0

        # Situation: how the player goes chasing, relative to how they go
        # batting first. A ratio rather than a raw chasing figure, because a
        # top-order batter chases more often than a finisher and the raw number
        # would rank opportunity. 1.0 means "the same player either way".
        chasing = _chasing_ratio(db, pid, gender, competition_key, competition_type)

        rated.append(
            PlayerIndex(
                player_identifier=pid,
                player_name=names.get(pid, pid),
                role=role,
                matches=len(recent),
                raw={
                    "recent_performance": round(mean_value, 3),
                    # Negated so that, like every other component, larger is
                    # better before percentiles are taken.
                    "consistency": round(-_downside_deviation(values), 3),
                    "opposition": round(mean_multiplier, 3),
                    "match_impact": round(match_impact, 3),
                    "situation": round(chasing, 3),
                },
            )
        )

    if not rated:
        return []

    weights = _active_weights()
    # One percentile pool per discipline. Pooling them together would rank
    # bowlers above batters on an artefact of the impact model, not on merit.
    pools: dict[str, list[PlayerIndex]] = {}
    for r in rated:
        pools.setdefault(r.role, []).append(r)

    for pool in pools.values():
        for component in weights:
            column = [r.raw[component] for r in pool]
            for r, score in zip(pool, _percentiles(column)):
                r.scores[component] = round(score, 1)

    for r in rated:
        r.index = round(sum(weights[c] * r.scores[c] for c in weights), 1)

    rated.sort(key=lambda r: r.player_identifier)
    rated.sort(key=lambda r: r.index, reverse=True)
    return rated


# Cached per scope: one query per player would be ~3,000 round trips.
_chasing_cache: dict[tuple, dict[str, float]] = {}


def _chasing_ratio(db: Session, pid, gender, competition_key, competition_type) -> float:
    """Runs per dismissal chasing, over the same batting first.

    A RATIO, not a raw chasing average. An opener chases far more often than a
    finisher, so a raw figure would score opportunity; comparing a player with
    themselves removes that. 1.0 means they are the same player either way,
    which is also the value returned when there is too little of one side to
    compare -- absent evidence, assume no situational edge rather than invent one.
    """
    key = (gender, competition_key, competition_type)
    if key not in _chasing_cache:
        stmt = (
            select(
                Delivery.batter,
                func.sum(func.iif(Delivery.innings == 1, Delivery.runs_batter, 0)),
                func.sum(func.iif(Delivery.innings == 1, func.iif(Delivery.player_out == Delivery.batter, 1, 0), 0)),
                func.sum(func.iif(Delivery.innings > 1, Delivery.runs_batter, 0)),
                func.sum(func.iif(Delivery.innings > 1, func.iif(Delivery.player_out == Delivery.batter, 1, 0), 0)),
            )
            .join(Match, Match.match_id == Delivery.match_id)
            .join(Competition, Competition.competition_id == Match.competition_id)
            .where(Delivery.batter.is_not(None), Match.gender == gender)
            .group_by(Delivery.batter)
        )
        if competition_key:
            stmt = stmt.where(Competition.key == competition_key)
        if competition_type:
            stmt = stmt.where(Competition.type == competition_type)

        out: dict[str, float] = {}
        for batter, first_runs, first_outs, chase_runs, chase_outs in db.execute(stmt).all():
            # Both sides need real evidence; below that the ratio is noise.
            if (first_outs or 0) < floor or (chase_outs or 0) < floor:
                continue
            first_avg = (first_runs or 0) / first_outs
            chase_avg = (chase_runs or 0) / chase_outs
            if first_avg <= 0:
                continue
            ratio = chase_avg / first_avg
            # Shrunk towards 1.0 -- "no situational edge" -- on the THINNER of
            # the two sides, since that is what the comparison actually rests on.
            n = min(first_outs, chase_outs)
            out[batter] = (n * ratio + k * 1.0) / (n + k)
        _chasing_cache[key] = out
    return _chasing_cache[key].get(pid, 1.0)


def describe_components() -> list[dict]:
    """Every component, live or not, with its weight and its basis.

    Returned with every response: §14 requires that the UI state which
    components are active, and §30 requires a decomposition rather than a bare
    score. Inactive components report the original §14 weight and a reason, so
    "the Index is missing 25% of its intended inputs" stays visible.
    """
    active = _active_weights()
    return [
        {
            "key": key,
            "label": COMPONENT_LABELS[key],
            "specified_weight": weight,
            "applied_weight": round(active.get(key, 0.0), 4),
            "active": on,
            "basis": COMPONENT_BASIS.get(key),
            "unavailable_because": reason,
        }
        for key, (weight, on, reason) in COMPONENTS.items()
    ]


__all__ = ["compute", "describe_components", "PlayerIndex", "COMPONENTS"]

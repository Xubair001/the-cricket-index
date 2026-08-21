r"""A side's strength profile (§19): where they are deep, and where they are thin.

§19 lists six dimensions - batting, bowling, all-round depth, experience,
current form, bench depth - and pairs them with the weakness analysis as the two
halves of a team page. `team_weakness.py` shipped first because it is §19's
stated differentiator; this is the other half.

What each dimension is, and why that measure
--------------------------------------------
Every dimension is a **depth** question, not a quality one, because that is what
§19 asks and it is the thing a squad page can answer that a leaderboard cannot.
A side with one great batter and nine poor ones has excellent batting and no
batting depth, and it is the second that decides a series.

- **Batting / bowling depth** is the share of the window's output that came from
  OUTSIDE the top three contributors. `squad.py` already computes the top-three
  share for reliance; depth is its complement, and it is the right measure
  because it is scale-free: it compares a side that scored 3,000 runs with one
  that scored 900 without either looking better for the total.
- **All-round depth** is how many players the ball record puts in the
  all-rounder band with enough deliveries to be confident about. Inferred, and
  labelled as inferred, like every role in this project.
- **Experience** is the squad's mean appearances IN THIS SCOPE, not career
  appearances. A side's experience is what they have done together in this
  format; a player's 120 Tests are not experience of a T20 side.
- **Current form** is the mean bounded form score across the squad, which is
  already a scope percentile, so a squad mean of 60 means "this side's players
  are collectively in the 60th percentile of movers in this scope".
- **Bench depth** is how many players a side used beyond a settled eleven over
  the window. High is ambiguous on its own - it can mean rotation OR churn - so
  it is reported with the raw count and never scored as simply good.

Every dimension is scored against the SAME core, and that matters
------------------------------------------------------------------
`team_weakness._peer_rates` documents three peer references that failed, and the
failure mode is identical here: there are ~110 men's international sides and most
play rarely, so any measure taken against "the average side" tells every full
member they are exceptional and every associate that they are hopeless. The core
is the twelve sides with the most all-time cricket in the scope, which is the set
that actually contests it. The page says "the core sides of this competition",
never "average".

Where a dimension has no peer figure - too few core sides with a window, a scope
with almost no cricket - the raw figure is returned and the score is None. It is
never defaulted to 50, which would read as "exactly typical" for a side nobody
could measure.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Competition, Match, PlayerMatchStat, Team
from . import config, form as form_mod, squad as squad_mod

# The peer group, on all-time volume in the scope. Deliberately the same number
# `team_weakness` uses, for the same reason: these are the sides that contest the
# competition regularly, and a reference taken over every side puts par at
# roughly Malta.
PEER_CORE_SIDES = 12

# A settled side is eleven players. Anything past that over a window is either
# rotation or churn, and the count is what "bench depth" measures.
SETTLED_XI = 11

# Below this a player did not contribute enough in the window to count towards a
# depth figure. Without it, a batter who faced four balls counts as depth.
DEPTH_MIN_BALLS = 30


@dataclass(slots=True)
class Dimension:
    key: str
    label: str
    # The measured figure, in its own units.
    value: float | None
    unit: str
    # 0-100 against the core sides of this scope. None where no peer figure
    # could be built - never 50, which would read as "typical".
    score: float | None
    # The core's own figure, so the comparison is visible rather than implied.
    peer_value: float | None
    peer_sides: int
    basis: str
    # False where the window is too thin for the figure to describe the side.
    reliable: bool = True


@dataclass(slots=True)
class TeamStrength:
    team_id: int
    team_name: str
    gender: str
    team_type: str
    competition_key: str | None
    window_matches: int
    matches_in_window: int
    squad_size: int
    first_match: str | None = None
    last_match: str | None = None
    dimensions: list[Dimension] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unavailable: dict[str, str] = field(default_factory=dict)


UNAVAILABLE = {
    "bench_quality": (
        "Bench depth counts how many players a side used beyond a settled "
        "eleven. It cannot say whether those players are good enough to come "
        "in, because a player who has not played for this side has no record "
        "for it - and their record elsewhere is a different question."
    ),
    "fielding": (
        "No fielding strength. The ball record credits the fielder on a "
        "dismissal, which identifies a wicketkeeper, but a catch taken cannot "
        "be told from a catch dropped and nothing records the second."
    ),
    "conditions": (
        "Not adjusted for where the window was played. A side whose last "
        "twenty matches were at home will look stronger than the same side "
        "away, and this dataset carries no ground-to-country mapping to "
        "correct it - see the home/away split."
    ),
}


def _scope_matches(db: Session, gender: str, competition_key: str | None):
    stmt = select(Match.match_id, Match.team1_id, Match.team2_id).join(
        Competition, Competition.competition_id == Match.competition_id
    ).where(Match.gender == gender)
    if competition_key:
        stmt = stmt.where(Competition.key == competition_key)
    return db.execute(stmt).all()


def _core_sides(db: Session, gender: str, competition_key: str | None) -> list[int]:
    """The sides with the most all-time cricket in this scope.

    All-time rather than recent, the lesson `team_weakness._peer_rates` records:
    full members have played T20Is since 2005 and most associates only since the
    2019 status expansion, so a recent window selects an associate core and
    inverts every comparison built on it.
    """
    played: dict[int, int] = {}
    for _match_id, team1, team2 in _scope_matches(db, gender, competition_key):
        for team in (team1, team2):
            if team:
                played[team] = played.get(team, 0) + 1
    return [
        team_id
        for team_id, _count in sorted(played.items(), key=lambda kv: -kv[1])[:PEER_CORE_SIDES]
    ]


def _scope_appearances(
    db: Session, gender: str, competition_key: str | None
) -> dict[str, int]:
    """Matches per player IN THIS SCOPE, which is what experience means here."""
    stmt = (
        select(
            PlayerMatchStat.player_identifier,
            func.count(func.distinct(PlayerMatchStat.match_id)),
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .join(Competition, Competition.competition_id == Match.competition_id)
        .where(
            Match.gender == gender,
            PlayerMatchStat.player_identifier.is_not(None),
        )
        .group_by(PlayerMatchStat.player_identifier)
    )
    if competition_key:
        stmt = stmt.where(Competition.key == competition_key)
    return {pid: n for pid, n in db.execute(stmt).all()}


def _measure(
    result: squad_mod.SquadResult,
    appearances: dict[str, int],
    verdicts: dict[str, object],
) -> dict[str, float | None]:
    """The six figures for one side, in their own units."""
    members = result.members
    if not members:
        return {}

    contributors = [m for m in members if m.balls_faced >= DEPTH_MIN_BALLS]
    bowlers = [m for m in members if m.balls_bowled >= DEPTH_MIN_BALLS]

    # Depth is the complement of reliance: the share of output from outside the
    # top three. Scale-free, so a 3,000-run side and a 900-run side compare.
    batting_depth = (
        round(100.0 - result.top_run_share, 1) if result.top_run_share is not None else None
    )
    bowling_depth = (
        round(100.0 - result.top_wicket_share, 1)
        if result.top_wicket_share is not None
        else None
    )

    allrounders = sum(
        1 for m in members if m.role == "allrounder" and m.role_confident
    )

    in_scope = [appearances.get(m.player_identifier, 0) for m in members]
    experience = round(sum(in_scope) / len(in_scope), 1) if in_scope else None

    scores = [
        getattr(verdicts.get(m.player_identifier), "form_score", None) for m in members
    ]
    placed = [s for s in scores if s is not None]
    current_form = round(sum(placed) / len(placed), 1) if placed else None

    bench = max(0, len(members) - SETTLED_XI)

    return {
        "batting_depth": batting_depth,
        "bowling_depth": bowling_depth,
        "allround_depth": float(allrounders),
        "experience": experience,
        "current_form": current_form,
        "bench_depth": float(bench),
        "_contributors": float(len(contributors)),
        "_bowlers": float(len(bowlers)),
    }


DIMENSIONS = [
    (
        "batting_depth",
        "Batting depth",
        "% of runs",
        "Share of the window's runs scored OUTSIDE the top three contributors. "
        "High means the runs are spread; low means the side leans on a few.",
    ),
    (
        "bowling_depth",
        "Bowling depth",
        "% of wickets",
        "Share of the window's wickets taken OUTSIDE the top three. Read the "
        "same way as batting depth.",
    ),
    (
        "allround_depth",
        "All-round depth",
        "players",
        "Players the ball record places in the all-rounder band with enough "
        "deliveries to be confident. Role is inferred from balls faced versus "
        "bowled, never sourced.",
    ),
    (
        "experience",
        "Experience",
        "mean appearances",
        "Mean appearances IN THIS SCOPE across the squad. A player's Test caps "
        "are not experience of a T20 side, so career totals are not used.",
    ),
    (
        "current_form",
        "Current form",
        "mean form score",
        "Mean form score across the squad. Each is already a percentile within "
        "this scope, so 60 means the side's players are collectively above the "
        "median mover here.",
    ),
    (
        "bench_depth",
        "Bench usage",
        "players beyond XI",
        "Players used beyond a settled eleven over the window. Deliberately not "
        "scored as good: a high number can mean healthy rotation or an unsettled "
        "side, and this figure cannot tell them apart.",
    ),
]

# Bench usage is genuinely ambiguous, so it is reported without a peer score.
# Scoring it would assert that more rotation is better, which is not known.
UNSCORED = {"bench_depth"}


def analyse(
    db: Session,
    team_id: int,
    competition_key: str | None = None,
    window_matches: int = squad_mod.DEFAULT_WINDOW_MATCHES,
) -> TeamStrength | None:
    """A side's strength profile against the core sides of its scope."""
    team = db.get(Team, team_id)
    if team is None:
        return None

    own = squad_mod.squad(db, team_id, window_matches=window_matches)
    if own is None:
        return None

    appearances = _scope_appearances(db, team.gender, competition_key)
    verdicts = form_mod.scope_summary(
        db,
        gender=team.gender,
        competition_key=competition_key,
        competition_type=None if competition_key else team_type_to_competition_type(team.team_type),
    ).verdicts

    mine = _measure(own, appearances, verdicts)

    # The peer figure, over the core sides of this scope excluding this one.
    core = [t for t in _core_sides(db, team.gender, competition_key) if t != team_id]
    peer_values: dict[str, list[float]] = {}
    measured_peers = 0
    for other_id in core:
        other = squad_mod.squad(db, other_id, window_matches=window_matches)
        if other is None or not other.members:
            continue
        measured_peers += 1
        for key, value in _measure(other, appearances, verdicts).items():
            if value is not None and not key.startswith("_"):
                peer_values.setdefault(key, []).append(value)

    result = TeamStrength(
        team_id=team_id,
        team_name=team.name,
        gender=team.gender,
        team_type=team.team_type,
        competition_key=competition_key,
        window_matches=window_matches,
        matches_in_window=own.matches_in_window,
        squad_size=len(own.members),
        first_match=own.first_match,
        last_match=own.last_match,
        unavailable=dict(UNAVAILABLE),
    )

    thin = own.matches_in_window < max(5, window_matches // 3)
    for key, label, unit, basis in DIMENSIONS:
        value = mine.get(key)
        others = sorted(peer_values.get(key, []))
        peer_value = (
            round(others[len(others) // 2], 1) if others else None
        )
        score = None
        if key not in UNSCORED and value is not None and len(others) >= 3:
            # Percentile against the core, the same device the Index and the
            # form score use, so a 0-100 here means what it means elsewhere.
            at_or_below = sum(1 for other in others if other <= value)
            score = round(100.0 * at_or_below / len(others), 1)
        result.dimensions.append(
            Dimension(
                key=key,
                label=label,
                value=value,
                unit=unit,
                score=score,
                peer_value=peer_value,
                peer_sides=len(others),
                basis=basis,
                reliable=not thin,
            )
        )

    if thin:
        result.notes.append(
            f"{team.name} has {own.matches_in_window} matches in this window, "
            f"against a requested {window_matches}. Every figure here rests on "
            f"that, and is marked unreliable rather than withheld."
        )
    if measured_peers < 3:
        result.notes.append(
            f"Only {measured_peers} peer side{'s' if measured_peers != 1 else ''} "
            f"in this scope could be measured, so most dimensions carry no score "
            f"against them. The raw figures are still shown."
        )
    else:
        result.notes.append(
            f"Scored against the {measured_peers} sides with the most cricket in "
            f"this scope, not against the average side. There are far more "
            f"international teams than there are teams that play regularly, so "
            f"an average-based reference tells every established side it is "
            f"exceptional - the trap the weakness analysis documents."
        )
    return result


def team_type_to_competition_type(team_type: str) -> str | None:
    """The competition family a side belongs to.

    Needed because a strength profile taken without a competition must not blend
    a franchise season into an international record - the partition this schema
    enforces everywhere else. Returns None for a team type with no obvious
    family rather than guessing one.
    """
    return {
        "international": "international",
        "franchise": "domestic_league",
    }.get(team_type)


__all__ = ["analyse", "TeamStrength", "Dimension", "DIMENSIONS", "UNAVAILABLE"]

"""Squad analysis - who a side is currently picking, and what that XI is made of.

Three decisions here look like detail and are correctness:

**The window is the team's own last N matches, not a calendar period.** A
calendar window ("the last 12 months") empties the page for every associate
side, because most of the ~110 international teams in this dataset play a
handful of matches a year and then nothing for eighteen months. Their squad
still exists. Anchoring to the side's own fixtures means "current squad" means
the same thing for Australia and for Malta.

**Role is inferred from this window, for this team - not from a career.** A
player's career role is the wrong answer twice over: Jadeja bowls a far larger
share for India in Tests than in T20Is, and a franchise picks players into
different jobs than their country does. `explorer.discipline` is reused so the
cuts stay in one place (§21 sanctions the batter/bowler/all-rounder split as
inferred; wicketkeeper and opener remain unreachable).

**A role read off very few deliveries is reported as uncertain rather than
withheld.** Someone who faced four balls in one appearance would otherwise be
filed as a "bowler" with the same confidence as Bumrah. The figure is shown
with the ball counts it came from, and flagged below `ROLE_MIN_BALLS`, which is
the same contract the form verdicts use.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Match, Player, PlayerMatchStat, Team
from ..names import preferred_name
from .explorer import discipline

# How many of the side's most recent matches count as "current".
DEFAULT_WINDOW_MATCHES = 20

# Below this many deliveries in the window, the inferred role is reported but
# marked uncertain. Roughly two overs bowled or half an innings faced - enough
# to be a signal, not enough to be a claim.
ROLE_MIN_BALLS = 60

# How many players the reliance figures are measured over. Three is the number
# a selector actually worries about: "if these three fail, does the side score?"
RELIANCE_TOP_N = 3

ROLES = ("batter", "allrounder", "bowler", "unknown")


@dataclass
class SquadMember:
    player_identifier: str
    player_name: str
    matches: int
    runs: int
    balls_faced: int
    dismissals: int
    wickets: int
    balls_bowled: int
    runs_conceded: int
    batting_average: float | None
    strike_rate: float | None
    bowling_average: float | None
    economy: float | None
    role: str
    # The ratio `discipline` was read off, so the inference is checkable rather
    # than something the reader has to take on trust.
    bowling_share: float | None
    role_confident: bool
    last_played: str | None


@dataclass
class SquadResult:
    team_id: int
    team_name: str
    window_matches: int
    matches_in_window: int
    first_match: str | None
    last_match: str | None
    members: list[SquadMember] = field(default_factory=list)
    role_counts: dict[str, int] = field(default_factory=dict)
    runs_by_role: dict[str, int] = field(default_factory=dict)
    wickets_by_role: dict[str, int] = field(default_factory=dict)
    top_run_share: float | None = None
    top_wicket_share: float | None = None


def _safe(numerator: float, denominator: float, places: int = 2) -> float | None:
    return round(numerator / denominator, places) if denominator else None


def _window_match_ids(db: Session, team_id: int, window_matches: int) -> list[str]:
    """The team's most recent match ids, newest first.

    Read through `player_match_stats` rather than `matches.team1_id/team2_id`:
    the squad is defined by who actually took the field, and this keeps the
    window and the appearances that fill it derived from the same rows.
    """
    stmt = (
        select(PlayerMatchStat.match_id, func.max(Match.match_date_start).label("played"))
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .where(PlayerMatchStat.team_id == team_id)
        .group_by(PlayerMatchStat.match_id)
        .order_by(func.max(Match.match_date_start).desc())
        .limit(window_matches)
    )
    return [match_id for match_id, _ in db.execute(stmt).all()]


def squad(db: Session, team_id: int, window_matches: int = DEFAULT_WINDOW_MATCHES) -> SquadResult | None:
    team = db.execute(select(Team).where(Team.team_id == team_id)).scalar_one_or_none()
    if team is None:
        return None

    match_ids = _window_match_ids(db, team_id, window_matches)
    if not match_ids:
        return SquadResult(
            team_id=team.team_id,
            team_name=team.name,
            window_matches=window_matches,
            matches_in_window=0,
            first_match=None,
            last_match=None,
        )

    span = db.execute(
        select(func.min(Match.match_date_start), func.max(Match.match_date_start)).where(
            Match.match_id.in_(match_ids)
        )
    ).one()

    stmt = (
        select(
            PlayerMatchStat.player_identifier.label("pid"),
            func.coalesce(
                func.max(Player.name), func.max(PlayerMatchStat.player_name)
            ).label("scorecard_name"),
            func.max(Player.display_name).label("wikidata_name"),
            func.count(func.distinct(PlayerMatchStat.match_id)).label("matches"),
            func.sum(PlayerMatchStat.runs_scored).label("runs"),
            func.sum(PlayerMatchStat.balls_faced).label("balls_faced"),
            func.sum(PlayerMatchStat.dismissals).label("dismissals"),
            func.sum(PlayerMatchStat.wickets_taken).label("wickets"),
            func.sum(PlayerMatchStat.balls_bowled).label("balls_bowled"),
            func.sum(PlayerMatchStat.runs_conceded).label("runs_conceded"),
            func.max(Match.match_date_start).label("last_played"),
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .outerjoin(Player, Player.identifier == PlayerMatchStat.player_identifier)
        .where(PlayerMatchStat.team_id == team_id)
        .where(PlayerMatchStat.match_id.in_(match_ids))
        .where(PlayerMatchStat.player_identifier.is_not(None))
        # Grouped by identifier, never by name -- names collide across people.
        .group_by(PlayerMatchStat.player_identifier)
    )

    members: list[SquadMember] = []
    for r in db.execute(stmt).all():
        balls_faced = r.balls_faced or 0
        balls_bowled = r.balls_bowled or 0
        total_balls = balls_faced + balls_bowled
        runs = r.runs or 0
        wickets = r.wickets or 0
        conceded = r.runs_conceded or 0
        members.append(
            SquadMember(
                player_identifier=r.pid,
                player_name=preferred_name(r.scorecard_name, r.wikidata_name),
                matches=r.matches,
                runs=runs,
                balls_faced=balls_faced,
                dismissals=r.dismissals or 0,
                wickets=wickets,
                balls_bowled=balls_bowled,
                runs_conceded=conceded,
                batting_average=_safe(runs, r.dismissals or 0),
                strike_rate=_safe(runs * 100, balls_faced),
                bowling_average=_safe(conceded, wickets),
                economy=_safe(conceded * 6, balls_bowled),
                role=discipline(balls_faced, balls_bowled),
                bowling_share=round(balls_bowled / total_balls, 3) if total_balls else None,
                role_confident=total_balls >= ROLE_MIN_BALLS,
                last_played=r.last_played,
            )
        )

    # Most-used first: a squad list ordered by appearances reads as the pecking
    # order, which is the question the page is actually asked.
    members.sort(key=lambda m: (-m.matches, -(m.runs + m.wickets * 20), m.player_name))

    role_counts = {role: 0 for role in ROLES}
    runs_by_role = {role: 0 for role in ROLES}
    wickets_by_role = {role: 0 for role in ROLES}
    for m in members:
        role_counts[m.role] += 1
        runs_by_role[m.role] += m.runs
        wickets_by_role[m.role] += m.wickets

    total_runs = sum(m.runs for m in members)
    total_wickets = sum(m.wickets for m in members)
    top_runs = sorted((m.runs for m in members), reverse=True)[:RELIANCE_TOP_N]
    top_wickets = sorted((m.wickets for m in members), reverse=True)[:RELIANCE_TOP_N]

    return SquadResult(
        team_id=team.team_id,
        team_name=team.name,
        window_matches=window_matches,
        matches_in_window=len(match_ids),
        first_match=span[0],
        last_match=span[1],
        members=members,
        role_counts=role_counts,
        runs_by_role=runs_by_role,
        wickets_by_role=wickets_by_role,
        top_run_share=_safe(sum(top_runs) * 100, total_runs),
        top_wicket_share=_safe(sum(top_wickets) * 100, total_wickets),
    )

r"""Venue intelligence (§20) -- what kind of cricket does this ground produce?

Why this could not be built before
-----------------------------------
§20's stated prerequisite is "a venues table with canonical names ... 593 raw
strings must collapse to a real ground list before any venue figure is
trustworthy". That is now `app/venues.py`, and it is genuinely load-bearing
here: the St Lucia ground alone was filed under six spellings, so a page keyed
on the raw column would have shown a quarter of its history and looked complete.
Every figure below groups on the canonical ground.

What is Tier A here, and one thing §20 marked Tier B that is not
-----------------------------------------------------------------
§20 marks "average score, average winning score, chasing success rate" as Tier
B, on the reasonable assumption that knowing who chased needs the innings
sequence that only stored deliveries provide.

It does not. **The toss gives it exactly.** `toss_winner_team_id` and
`toss_decision` are populated for 100% of the 10,040 matches, and together they
name the side that batted first: the toss winner if they chose to bat, otherwise
their opponent. Chasing success is therefore Tier A, and it is the single most
useful thing a venue page can say -- a ground where sides batting first win 65%
of the time is a different proposition from one where they win 35%, and that is
precisely the question a captain at the toss is asking.

What genuinely is not available: phase scoring, dot-ball rates and pace-vs-spin
(Tier B/C), and true innings totals -- see the note on extras below.

Runs off the bat, not "average score"
--------------------------------------
`player_match_stats` holds what each batter scored. It does not hold extras: a
wide is charged to the bowler's `runs_conceded`, and byes and leg-byes are
charged to nobody, because they are not the bowler's fault. Summing a side's
batters therefore gives **runs off the bat**, which is a well-defined figure and
roughly 5% short of the true team total.

So this module reports "runs off the bat" and says so, rather than labelling an
understated number "average score". The comparison against par is unaffected --
both sides of it are measured the same way -- which is why the interpretive
figure (how this ground compares with its format) is the one given prominence.

Every figure is compared with its own format
----------------------------------------------
A raw "31 runs per wicket" says nothing without knowing whether the ground hosts
Tests or T20Is. Each ground is therefore measured per competition and expressed
as a ratio against that competition's own par, so "12% higher scoring than a
typical T20I" is the headline and the raw figure sits behind it (§2: context
beats raw statistics).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Competition, Match, PlayerMatchStat
from ..venues import canonical, canonical_key
from . import config

# Below this a ground's rates are noise; they are returned but flagged so the UI
# can mark them rather than presenting four matches as a ground's character.
MIN_MATCHES_FOR_CHARACTER = 10


@dataclass
class VenueFormat:
    """One ground's cricket within one competition."""

    competition_key: str
    competition_name: str
    matches: int
    runs_off_bat_per_match: float | None
    runs_per_wicket: float | None
    balls_per_wicket: float | None
    boundary_rate: float | None       # boundaries per 100 balls faced
    # Ratios against this competition's own par. 1.0 = typical for the format.
    scoring_index: float | None
    wicket_index: float | None
    bat_first_wins: int
    bat_first_losses: int
    bat_first_win_pct: float | None
    toss_win_pct: float | None        # how often the toss winner wins
    chose_to_bat_pct: float | None    # what captains actually decide here
    decided_matches: int
    reliable: bool


@dataclass
class VenueProfile:
    venue: str
    city: str | None
    matches: int
    first_match: str | None
    last_match: str | None
    raw_spellings: list[str] = field(default_factory=list)
    formats: list[VenueFormat] = field(default_factory=list)


def _safe(n: float, d: float, places: int = 2) -> float | None:
    return round(n / d, places) if d else None


def _raw_strings(db: Session, wanted_key: str) -> list[str]:
    rows = db.execute(
        select(Match.venue, Match.city).distinct().where(Match.venue.is_not(None))
    ).all()
    return sorted({v for v, c in rows if canonical_key(v, c) == wanted_key})


def profile(
    db: Session,
    venue_name: str,
    *,
    gender: str,
    competition_key: str | None = None,
) -> VenueProfile | None:
    """One ground's character, per competition.

    Grouped on the canonical ground, so every spelling of it contributes.
    """
    wanted = canonical_key(venue_name)
    if not wanted:
        return None
    raws = _raw_strings(db, wanted)
    if not raws:
        return None

    # Per-competition batting aggregates at this ground.
    stmt = (
        select(
            Competition.key,
            Competition.display_name,
            func.count(func.distinct(PlayerMatchStat.match_id)).label("matches"),
            func.sum(PlayerMatchStat.runs_scored),
            func.sum(PlayerMatchStat.balls_faced),
            func.sum(PlayerMatchStat.dismissals),
            func.sum(PlayerMatchStat.fours),
            func.sum(PlayerMatchStat.sixes),
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .join(Competition, Competition.competition_id == Match.competition_id)
        .where(Match.venue.in_(raws), Match.gender == gender)
        .group_by(Competition.key)
    )
    if competition_key:
        stmt = stmt.where(Competition.key == competition_key)

    # Par for the same slices, so a ground can be expressed against its format.
    from . import impact as impact_mod

    par = impact_mod.par_table(db)

    formats: list[VenueFormat] = []
    for key, display, n, runs, balls, dismissals, fours, sixes in db.execute(stmt).all():
        runs, balls = runs or 0, balls or 0
        dismissals = dismissals or 0
        p = par.lookup(key, gender)

        rpw = _safe(runs, dismissals)
        # Par's scoring_rate is runs per 100 balls for the whole competition, so
        # the ground's own rate against it is a like-for-like ratio.
        ground_rate = _safe(runs * 100.0, balls, 4)
        scoring_index = (
            round(ground_rate / p.scoring_rate, 3)
            if ground_rate and p.scoring_rate else None
        )
        # Balls per wicket against the competition's own: above 1.0 means wickets
        # are harder to take here than the format's norm.
        ground_bpw = _safe(balls, dismissals, 4)
        par_bpw = (
            (p.scoring_rate and p.runs_per_wicket)
            and (p.runs_per_wicket / (p.scoring_rate / 100.0))
            or None
        )
        wicket_index = round(ground_bpw / par_bpw, 3) if ground_bpw and par_bpw else None

        toss = _toss_record(db, raws, gender, key)
        formats.append(
            VenueFormat(
                competition_key=key,
                competition_name=display,
                matches=n,
                runs_off_bat_per_match=_safe(runs, n),
                runs_per_wicket=rpw,
                balls_per_wicket=_safe(balls, dismissals),
                boundary_rate=_safe((fours or 0) + (sixes or 0), balls / 100.0 if balls else 0),
                scoring_index=scoring_index,
                wicket_index=wicket_index,
                reliable=n >= MIN_MATCHES_FOR_CHARACTER,
                **toss,
            )
        )

    formats.sort(key=lambda f: -f.matches)

    span = db.execute(
        select(func.min(Match.match_date_start), func.max(Match.match_date_start)).where(
            Match.venue.in_(raws), Match.gender == gender
        )
    ).one()
    total = db.execute(
        select(func.count()).select_from(Match).where(
            Match.venue.in_(raws), Match.gender == gender
        )
    ).scalar_one()
    city = db.execute(
        select(Match.city).where(Match.venue.in_(raws), Match.city.is_not(None)).limit(1)
    ).scalar_one_or_none()

    return VenueProfile(
        venue=canonical(venue_name) or venue_name,
        city=city,
        matches=total,
        first_match=span[0],
        last_match=span[1],
        raw_spellings=raws,
        formats=formats,
    )


def _toss_record(db: Session, raws: list[str], gender: str, competition_key: str) -> dict:
    """Bat-first and toss outcomes at a ground.

    Who batted first is derived from the toss, which is what makes this Tier A:
    the toss winner bats first if they chose to bat, otherwise their opponent
    does. Matches without a result are excluded from win rates rather than
    counted as losses -- a washout says nothing about the ground's character.
    """
    rows = db.execute(
        select(
            Match.toss_winner_team_id,
            Match.toss_decision,
            Match.team1_id,
            Match.team2_id,
            Match.winner_team_id,
        )
        .join(Competition, Competition.competition_id == Match.competition_id)
        .where(
            Match.venue.in_(raws),
            Match.gender == gender,
            Competition.key == competition_key,
        )
    ).all()

    bat_first_wins = bat_first_losses = toss_wins = decided = chose_bat = tossed = 0
    for toss_winner, decision, t1, t2, winner in rows:
        if toss_winner and decision:
            tossed += 1
            if decision == "bat":
                chose_bat += 1
        if not (toss_winner and decision and winner and t1 and t2):
            continue
        bat_first = toss_winner if decision == "bat" else (t2 if toss_winner == t1 else t1)
        decided += 1
        if winner == bat_first:
            bat_first_wins += 1
        else:
            bat_first_losses += 1
        if winner == toss_winner:
            toss_wins += 1

    return {
        "bat_first_wins": bat_first_wins,
        "bat_first_losses": bat_first_losses,
        "bat_first_win_pct": _safe(bat_first_wins * 100.0, decided),
        "toss_win_pct": _safe(toss_wins * 100.0, decided),
        "chose_to_bat_pct": _safe(chose_bat * 100.0, tossed),
        "decided_matches": decided,
    }


__all__ = ["profile", "VenueProfile", "VenueFormat", "MIN_MATCHES_FOR_CHARACTER"]

r"""Scout -- find a player (§17).

A brief, not a filter
----------------------
§17 asks for "a dedicated workflow, not a filtered list": the user states a
need and the system returns ranked, explained candidates. The difference that
matters is accountability. A filter silently returns whatever survived; a brief
has to say which of its constraints were actually applied.

That is not decoration here -- §17 ends with the exact warning this module is
built around: scheduling Scout early "means shipping a filter that quietly
ignores half the brief". So every response carries `applied` and `ignored`, and
a constraint that cannot be honoured is named with the reason rather than
dropped.

What changed, and what did not
--------------------------------
§17 marks three of its seven constraints Tier C: role, availability and
pace/spin performance. Two of those are now sourced, from the ICC squad feed
(`fixture_squads`) -- role, batting hand and bowling style all come from
announced squads, and availability is a commitment rather than a guess.

**Coverage is the catch, and it is severe.** Squads exist only for fixtures the
feed carries, so a sourced attribute is known for a small fraction of the 9,400
players in the register. A brief that filters on batting hand therefore narrows
to players we have squad data for -- which is a real answer, but a different one
from "every left-hander in cricket". The response reports `candidates_considered`
against `with_sourced_attributes` so the caller can see the difference.

Age is a soft filter, deliberately
-----------------------------------
§4 requires it: date of birth covers about 42% of the register, so a hard age
filter would silently exclude the majority. An age bound therefore keeps players
of unknown age in a separate bucket rather than discarding them, and the
response says how many that was.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Competition, FixtureSquad, Match, Player, PlayerMatchStat
from ..names import preferred_name
from . import config, explorer, form as form_mod, performance_index as pi

# Bowling styles the ICC feed uses, split into the two families a scout asks
# about. Anything not spin is treated as pace; the feed's vocabulary is small
# and every unseen code has been a seam variant.
SPIN_STYLES = {"OB", "SLO", "LB", "LBG", "OS", "SLA", "LWS", "RLB"}

# Constraints §17's brief names that still cannot be honoured at all.
CANNOT_APPLY = {
    "strong_against_pace": (
        "Needs each delivery's bowler type. Bowling style is known for players "
        "in the squad feed, but the ball record spans 25 years while squads "
        "cover a recent window, so a pace/spin split would rest on a fraction "
        "of a career and read as if it covered all of it."
    ),
}


@dataclass
class Candidate:
    player_identifier: str
    player_name: str
    country: str | None
    country_code: str | None
    matches: int
    # Sourced where the squad feed knows them, inferred otherwise -- and the
    # response says which, because a scout filtering on hand needs to know.
    role: str | None
    role_sourced: bool
    batting_style: str | None
    bowling_style: str | None
    bowling_family: str | None
    age: int | None
    index: float | None
    # Raw ratio against the player's own baseline, in percent. Unbounded, kept
    # for traceability. `form_score` is the bounded figure to display.
    form_delta: float | None
    form_score: float | None
    form_display: str | None
    form_state: str | None
    recent_mean: float | None
    committed_in_window: bool | None
    score: float
    reason: str


@dataclass
class ScoutResult:
    scope: str
    gender: str
    candidates_considered: int
    with_sourced_attributes: int
    unknown_age: int
    applied: dict = field(default_factory=dict)
    ignored: dict = field(default_factory=dict)
    candidates: list[Candidate] = field(default_factory=list)


# The feed spells the same role two ways ("Batsman" is the older wording, 74
# players still carry it). Normalising is not cosmetic: an unnormalised filter
# for "Batter" silently drops them.
ROLE_ALIASES = {
    "batsman": "Batter",
    "batter": "Batter",
    "bowler": "Bowler",
    "all-rounder": "All-Rounder",
    "allrounder": "All-Rounder",
    "wicket keeper": "Wicket Keeper",
    "wicketkeeper": "Wicket Keeper",
    "wicket-keeper": "Wicket Keeper",
}


def normalise_role(raw: str | None) -> str | None:
    """Map the feed's role wording onto one vocabulary, or None if unrecognised."""
    if not raw:
        return None
    return ROLE_ALIASES.get(raw.strip().lower())


def _sourced_attributes(db: Session) -> dict[str, dict]:
    """Latest squad row per player: role, hand, bowling style.

    Latest rather than merged, because a role is a fact about a fixture - a
    player named as keeper in one squad and a batter in another is not a
    contradiction, and the most recent naming is the current one.

    Resolved in Python over rows ordered oldest-first, NOT with `func.max()` per
    column. `max()` returns the alphabetically-largest value of each column
    independently, which is neither the latest row nor even a single coherent
    row: it would report a player's newest hand beside a role they were given
    years earlier, and rank "Wicket Keeper" over "All-Rounder" purely on the
    letter W. The table is ~17k rows, so a single ordered pass is cheap.
    """
    stmt = (
        select(
            FixtureSquad.player_identifier,
            FixtureSquad.role,
            FixtureSquad.batting_style,
            FixtureSquad.bowling_style,
        )
        .where(FixtureSquad.player_identifier.is_not(None))
        .order_by(FixtureSquad.fetched_at.asc())
    )
    out: dict[str, dict] = {}
    for pid, role, bat, bowl in db.execute(stmt).all():
        entry = out.setdefault(pid, {})
        # Later rows overwrite earlier ones, but only where they carry a value:
        # a squad row missing a bowling style should not erase one we have.
        if role:
            entry["role"] = normalise_role(role)
        if bat:
            entry["batting_style"] = bat
        if bowl:
            entry["bowling_style"] = bowl
            entry["bowling_family"] = "spin" if bowl in SPIN_STYLES else "pace"
    for entry in out.values():
        entry.setdefault("role", None)
        entry.setdefault("batting_style", None)
        entry.setdefault("bowling_style", None)
        entry.setdefault("bowling_family", None)
    return out


def _committed(db: Session, date_from: str | None, date_to: str | None) -> set[str]:
    """Players named in a squad overlapping the window."""
    if not (date_from and date_to):
        return set()
    from ..models import Fixture

    stmt = (
        select(FixtureSquad.player_identifier)
        .join(Fixture, Fixture.icc_match_id == FixtureSquad.icc_match_id)
        .where(
            FixtureSquad.player_identifier.is_not(None),
            Fixture.start_date.is_not(None),
            Fixture.start_date <= date_to,
            func.coalesce(Fixture.end_date, Fixture.start_date) >= date_from,
        )
        .distinct()
    )
    return {r[0] for r in db.execute(stmt).all()}


def _age_on(dob: str | None, when: date) -> int | None:
    if not dob or len(dob) < 10:
        return None
    try:
        born = date.fromisoformat(dob[:10])
    except ValueError:
        return None
    return when.year - born.year - ((when.month, when.day) < (born.month, born.day))


def search(
    db: Session,
    *,
    gender: str,
    competition_key: str | None = None,
    competition_type: str | None = "international",
    role: str | None = None,
    batting_style: str | None = None,
    bowling_family: str | None = None,
    # Batting position, derived from who faces the first ball of an innings.
    # Section 33 lists "opener" as the one Tier B constraint in its
    # definition-of-success query, and stored deliveries answered it - the
    # selector has used it since Best XI shipped. This exposes the same
    # derivation to a brief.
    opens: bool = False,
    max_age: int | None = None,
    min_matches: int = 10,
    form_state: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    exclude_committed: bool = False,
    limit: int = 25,
) -> ScoutResult:
    """Run a brief and return ranked, explained candidates."""
    applied: dict[str, str] = {}
    ignored: dict[str, str] = dict(CANNOT_APPLY)

    # One reduced, cached view of the scope for every candidate's form. Called
    # without it, `assess` issues a query per candidate - 1,808 round trips on
    # an international brief.
    summary = form_mod.scope_summary(
        db, gender=gender, competition_key=competition_key,
        competition_type=competition_type,
    )
    # `pi.page` is cached per scope; `pi.compute` is not.
    _rated, _n = pi.page(
        db, gender=gender, competition_key=competition_key,
        competition_type=competition_type, limit=10**9, offset=0,
    )
    rated = {r.player_identifier: r for r in _rated}
    sourced = _sourced_attributes(db)
    committed = _committed(db, date_from, date_to)
    # Reuses the selector's derivation rather than a second copy of it: an
    # opener is a batter seen on the first ball of an innings at least
    # `config.OPENER_MIN_INNINGS` times.
    openers = explorer.openers(db, gender, competition_key, competition_type) if opens else {}

    stmt = (
        select(
            PlayerMatchStat.player_identifier,
            func.count(func.distinct(PlayerMatchStat.match_id)),
            func.sum(PlayerMatchStat.balls_faced),
            func.sum(PlayerMatchStat.balls_bowled),
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .join(Competition, Competition.competition_id == Match.competition_id)
        .where(PlayerMatchStat.player_identifier.is_not(None), Match.gender == gender)
        .group_by(PlayerMatchStat.player_identifier)
    )
    if competition_key:
        stmt = stmt.where(Competition.key == competition_key)
    if competition_type:
        stmt = stmt.where(Competition.type == competition_type)
    applied["format"] = competition_key or competition_type or "international"

    people = {p.identifier: p for p in db.execute(select(Player)).scalars()}
    from .. import queries as _queries

    countries = _queries._player_country_map(db, gender)
    today = date.today()

    if opens:
        applied["position"] = (
            f"opener - faced the first ball of an innings at least "
            f"{config.OPENER_MIN_INNINGS} times in this scope"
        )

    considered = with_attrs = unknown_age = 0
    out: list[Candidate] = []

    for pid, matches, bf, bb in db.execute(stmt).all():
        if matches < min_matches:
            continue
        rating = rated.get(pid)
        if rating is None:
            continue
        considered += 1

        attrs = sourced.get(pid)
        if attrs:
            with_attrs += 1

        # Role is sourced where the squad feed names it, inferred otherwise.
        role_value = (attrs or {}).get("role")
        role_sourced = bool(role_value)
        if not role_value:
            inferred = explorer.discipline(bf or 0, bb or 0)
            role_value = {
                "batter": "Batter", "bowler": "Bowler",
                "allrounder": "All-Rounder", "unknown": None,
            }.get(inferred)

        if role and (role_value or "").lower() != role.lower():
            continue
        # Batting position, unlike hand and bowling style, is DERIVED from the
        # ball record rather than sourced from a squad announcement - so it is
        # a hard filter with full coverage, not one bounded by who happens to
        # appear in the ICC feed.
        if opens and openers.get(pid, 0) < config.OPENER_MIN_INNINGS:
            continue
        if batting_style and (attrs or {}).get("batting_style") != batting_style:
            continue
        if bowling_family:
            if (attrs or {}).get("bowling_family") != bowling_family:
                continue
            # A bowling style is a NOMINAL attribute: the feed records one for
            # anyone who has ever turned an arm over, so filtering on style
            # alone puts batters on a bowling brief. Asking the PSL for spin
            # returned Babar Azam, Tim David and Abdullah Shafique - all
            # recorded "OB", none of them spinners. This is the same trap the
            # explorers hit with a volume floor: Root has bowled 8,120 balls
            # and clears any sane minimum without being a bowler.
            #
            # So a style filter additionally requires the player to be picked
            # to bowl - role Bowler or All-Rounder, sourced or inferred.
            if role_value not in ("Bowler", "All-Rounder"):
                continue

        person = people.get(pid)
        age = _age_on(getattr(person, "date_of_birth", None), today)
        if age is None:
            unknown_age += 1
        # SOFT: a player of unknown age is kept, because date of birth covers
        # about 42% of the register and a hard bound would drop the majority.
        if max_age is not None and age is not None and age > max_age:
            continue

        verdict = summary.verdicts.get(pid)
        if verdict is None:
            continue
        if form_state and verdict.state != form_state:
            continue

        is_committed = pid in committed if (date_from and date_to) else None
        if exclude_committed and is_committed:
            continue

        # Standard first, current touch second -- the same blend selection uses,
        # so a scout and a selector cannot disagree about who is better.
        #
        # `form_score` is the verdict's percentile within this scope: already
        # 0-100, already confidence-filtered, and calibrated against the
        # population rather than by an arbitrary transform. It replaced a local
        # clamp of the ratio to +/-1, which gave every player past a doubling
        # the same form term and so could not separate the strongest movers from
        # each other. 50 is the neutral fallback where a verdict is too thin to
        # place, which is the same thing the clamp did with no delta at all.
        form_pct = verdict.form_score if verdict.form_score is not None else 50.0
        score = 0.7 * rating.index + 0.3 * form_pct

        bits = [f"index {rating.index:.0f}"]
        if verdict.form_score is not None:
            # One decimal, because 0dp rounds 99.9 to "100/100" and reads as a
            # perfect score on a scale where 100 means "top of this scope".
            bits.append(f"form {verdict.form_score:.1f}/100")
        elif verdict.delta_display:
            # Too thin to score, so say the move instead of implying a rank.
            bits.append(f"form {verdict.delta_display}")
        if role_value:
            bits.append(f"{role_value.lower()}{'' if role_sourced else ' (inferred)'}")
        if is_committed:
            bits.append("committed in window")

        out.append(
            Candidate(
                player_identifier=pid,
                player_name=preferred_name(
                    getattr(person, "name", pid), getattr(person, "display_name", None)
                ),
                country=countries.get(pid, (None, None))[0],
                country_code=countries.get(pid, (None, None))[1],
                matches=matches,
                role=role_value,
                role_sourced=role_sourced,
                batting_style=(attrs or {}).get("batting_style"),
                bowling_style=(attrs or {}).get("bowling_style"),
                bowling_family=(attrs or {}).get("bowling_family"),
                age=age,
                index=rating.index,
                form_delta=round(verdict.delta_ratio * 100, 1) if verdict.delta_ratio is not None else None,
                form_score=verdict.form_score,
                form_display=verdict.delta_display,
                form_state=verdict.state,
                recent_mean=verdict.recent_mean,
                committed_in_window=is_committed,
                score=round(score, 1),
                reason=", ".join(bits),
            )
        )

    if role:
        applied["role"] = f"{role} (sourced where the squad feed knows it, else inferred)"
    if batting_style:
        applied["batting_hand"] = f"{batting_style} - only players with squad data can match"
    if bowling_family:
        applied["bowling_type"] = (
            f"{bowling_family} - restricted to bowlers and all-rounders, since the "
            "feed records a style for any occasional bowler; only players with "
            "squad data can match"
        )
    if max_age is not None:
        applied["age"] = f"under {max_age + 1}, soft - players of unknown age are kept"
    if form_state:
        applied["form"] = form_state
    if date_from and date_to:
        applied["period"] = f"{date_from} to {date_to}"
    applied["minimum"] = f"{min_matches} matches in scope"

    # The squad feed is ICC's, so it covers international cricket only. On a
    # franchise brief the sourced attributes come from whatever international
    # cricket those players also play, which is a small and uneven slice - 16
    # of 120 qualifying PSL players. Said here rather than left to be inferred
    # from a short result list.
    if (competition_type or "international") != "international":
        ignored["franchise_squad_data"] = (
            "Role, batting hand and bowling style come from ICC squad "
            "announcements, which cover international cricket only. For a "
            "franchise brief they are known only for players who also appear "
            "for their country, so an attribute filter here reaches a small "
            "and uneven slice of the league."
        )

    out.sort(key=lambda c: -c.score)
    return ScoutResult(
        scope=competition_key or competition_type or "international",
        gender=gender,
        candidates_considered=considered,
        with_sourced_attributes=with_attrs,
        unknown_age=unknown_age,
        applied=applied,
        ignored=ignored,
        candidates=out[:limit],
    )


__all__ = ["search", "ScoutResult", "Candidate", "SPIN_STYLES", "CANNOT_APPLY"]

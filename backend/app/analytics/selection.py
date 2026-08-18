r"""Best XI / XV (§18) -- pick a side, and show why each name is on it.

Why this exists now, when §5 said it could not
------------------------------------------------
§5 puts Best XI behind two Tier C blockers: playing role, and wicketkeeper
identification. Both were true statements about `player_match_stats`, which has
no fielding columns and no batting order. They are not true of the ball record
this project now stores:

* **Role** comes from balls faced versus balls bowled (`explorer.discipline`),
  which §5 sanctions explicitly.
* **Batting position** comes from the order batters first appear in an innings.
  §5 lists it as Tier B on "delivery order within an innings", which exists.
* **Wicketkeeper** comes from who is credited with dismissals. Only a keeper can
  effect a stumping, and a keeper takes far more catches than any other fielder.
  Cricsheet carries a `fielders` list on 65% of wickets; it was simply not being
  stored until the schema kept it.

So the side is picked on inferred roles, and every one of them is labelled as
inferred. What remains genuinely unavailable is **handedness** and **bowling
type** -- a balanced attack here means seam-and-spin balance cannot be checked,
and a left-right opening pair cannot be requested. Those stay Tier C, and the
response says so rather than quietly picking as if they were considered.

How the side is picked
-----------------------
Not "the eleven highest-rated players", which reliably returns six openers and
no keeper. Selection fills a **shape**: a required number of each role, taking
the best available for each slot, then filling any remaining places with the
best players left regardless of role.

Within a slot, players are ranked on a blend of what they have done and what
they are doing now -- the Performance Index for standard, the form engine for
current touch. §18 asks for both, and neither alone picks a side a selector
would recognise: standard alone ignores that a great player is out of nick, and
form alone promotes whoever is having a hot fortnight.

Scope is part of the answer
----------------------------
A side is picked within one scope -- a competition and a gender -- for the same
reason every other figure here is scoped. Picking a "best XI" across Tests and
T20Is would blend formats that ask for different players, and picking across
international and franchise cricket would put a PSL season beside a Test career.
Franchise selection works exactly the same way and is what makes this usable for
a league draft, which is §3's scout use case.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Competition, Delivery, Match, PlayerMatchStat, Team
from ..names import preferred_name
from ..models import Player
from . import config, scout, explorer, form as form_mod, performance_index as pi

# The shape a side is picked to. Deliberately a *minimum* per role with the
# remainder open, rather than a rigid quota: a side with three genuine
# all-rounders should be allowed to field them.
XI_SHAPE = {
    "wicketkeeper": 1,
    "batter": 4,
    "allrounder": 2,
    "bowler": 3,
}
# The eleventh place is open -- best available, whatever the role.

# Openers are picked from the batters already selected rather than as an extra
# role, because an opener IS a batter; the position only says where they bat.
OPENERS_WANTED = 2

# Below this a player has not played enough in the scope to be picked on it.
MIN_MATCHES = 8

# What the selector still cannot guarantee. Handedness and bowling type moved
# OFF this list when the ICC squad feed was read for them, but only partly:
# they are known for the players who appear in a squad announcement, which is
# most current internationals and few historical or franchise-only players.
# They are therefore REPORTED per pick and summarised as a balance note, and
# deliberately NOT enforced as a quota - filling a seam/spin shape on partial
# coverage would systematically prefer players who happen to have squad data
# over better players who do not, which is a selection bias dressed as balance.
UNAVAILABLE = {
    "handedness": "Batting hand is sourced from ICC squad announcements, so it "
                  "is known for most current internationals and unknown for "
                  "much of the rest. A left-right opening pair is reported "
                  "where both hands are known, never enforced.",
    "bowling_type": "Bowling style has the same partial coverage, so the "
                    "seam/spin split of the attack is reported rather than "
                    "selected for.",
    "availability": "No squad lists per fixture, so nobody here is checked "
                    "against injury, contract or selection (Tier C).",
}


@dataclass
class Pick:
    player_identifier: str
    player_name: str
    role: str                    # inferred
    slot: str                    # what they were picked as
    is_wicketkeeper: bool
    # How the keeper was identified: 'squad' (ICC named them one), 'stumping'
    # (they took one, which nobody else can), or None for a non-keeper. A
    # sourced role beats our inference and is preferred where both exist.
    keeper_source: str | None
    opens: bool
    matches: int
    index: float | None          # Performance Index within the scope
    form_delta: float | None     # % against their own baseline
    form_state: str | None
    recent_mean: float | None    # absolute standard, par units
    selection_score: float
    reason: str
    # Sourced from ICC squad announcements where the player appears in one,
    # else None. Never inferred: there is no way to guess a batting hand.
    batting_style: str | None = None
    bowling_family: str | None = None
    # The national side they represent, resolved from appearances exactly as
    # every other surface does - never from players.nationality.
    country: str | None = None
    country_code: str | None = None


@dataclass
class Selection:
    scope: str
    gender: str
    size: int
    team_id: int | None
    team_name: str | None
    picks: list[Pick] = field(default_factory=list)
    shape: dict = field(default_factory=dict)
    unavailable: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _keepers(db: Session, gender: str, competition_key, competition_type) -> dict[str, int]:
    """Keeper evidence per player: stumpings weighted, catches counted.

    A stumping can only be taken by the keeper, so one is REQUIRED. Catches are
    not a substitute: they cannot be distinguished from outfield catches, and
    using them as a fallback picked Mohammad Hafeez as a PSL keeper. They are
    used only to rank keepers who have already been confirmed by a stumping.

    The cost is a keeper who genuinely never stumped in the scope, who will be
    missed. That is the right way round: leaving a side without a keeper is
    visible and flagged, whereas naming the wrong player as one is not.
    """
    stmt = (
        select(
            Delivery.fielder,
            func.sum(func.iif(Delivery.wicket_kind == "stumped", 1, 0)),
            func.sum(func.iif(Delivery.wicket_kind == "caught", 1, 0)),
        )
        .join(Match, Match.match_id == Delivery.match_id)
        .join(Competition, Competition.competition_id == Match.competition_id)
        .where(Delivery.fielder.is_not(None), Match.gender == gender)
        .group_by(Delivery.fielder)
    )
    if competition_key:
        stmt = stmt.where(Competition.key == competition_key)
    if competition_type:
        stmt = stmt.where(Competition.type == competition_type)

    out: dict[str, int] = {}
    for pid, stumpings, catches in db.execute(stmt).all():
        score = (stumpings or 0) * config.KEEPER_STUMPING_WEIGHT + (catches or 0)
        # A stumping is required, not merely weighted. Catches alone identify a
        # good fielder, not a keeper -- see the note in `config`.
        if (stumpings or 0) >= config.KEEPER_MIN_STUMPINGS:
            out[pid] = score
    return out


def _openers(db: Session, gender: str, competition_key, competition_type) -> dict[str, int]:
    """How often a player was among the first two batters of an innings.

    The opening pair is exactly the two batters on strike and at the other end
    for the first delivery, which the ball record gives directly.
    """
    first_balls = (
        select(Delivery.match_id, Delivery.innings, Delivery.batter, Delivery.non_striker)
        .join(Match, Match.match_id == Delivery.match_id)
        .join(Competition, Competition.competition_id == Match.competition_id)
        .where(Delivery.seq == 0, Match.gender == gender)
    )
    if competition_key:
        first_balls = first_balls.where(Competition.key == competition_key)
    if competition_type:
        first_balls = first_balls.where(Competition.type == competition_type)

    counts: dict[str, int] = {}
    for _m, _i, batter, non_striker in db.execute(first_balls).all():
        for pid in (batter, non_striker):
            if pid:
                counts[pid] = counts.get(pid, 0) + 1
    return counts


def _career_standing(
    db: Session, gender, competition_key, competition_type, summary=None
) -> dict[str, float]:
    """Percentile of a player's whole record in the scope, within their discipline.

    Deliberately the FULL timeline, not the Index's 15-match window: this is the
    term that says "good player", against which the Index and form say "playing
    well now". Pooled by discipline for the same reason the Index is -- a
    bowler's mean impact is 1.08 par units against a batter's 0.64, so a single
    pool would rank discipline rather than merit.
    """
    if summary is None:
        summary = form_mod.scope_summary(
            db, gender=gender, competition_key=competition_key,
            competition_type=competition_type,
        )
    pools: dict[str, list[tuple[str, float]]] = {}
    for pid, n in summary.match_count.items():
        if n < MIN_MATCHES:
            continue
        faced, bowled = summary.balls[pid]
        role = explorer.discipline(faced, bowled)
        pools.setdefault(role, []).append((pid, summary.career_mean[pid]))

    out: dict[str, float] = {}
    for rows in pools.values():
        scores = pi._percentiles([v for _p, v in rows])
        for (pid, _v), pct in zip(rows, scores):
            out[pid] = pct
    return out


def select_side(
    db: Session,
    *,
    gender: str,
    size: int = 11,
    competition_key: str | None = None,
    competition_type: str | None = None,
    team_id: int | None = None,
) -> Selection:
    """Pick a side of `size` within one scope."""
    # One reduced, cached view of the scope, shared by career standing and every
    # per-player form verdict below. Calling `assess` per candidate without a
    # prefetched timeline issued a query each - 3,145 round trips and about nine
    # seconds on an international XI - and the timeline map it needs is 107 MB,
    # so `scope_summary` reduces it to per-player facts and caches those.
    summary = form_mod.scope_summary(
        db, gender=gender, competition_key=competition_key,
        competition_type=competition_type,
    )
    # `pi.page` is cached per scope; `pi.compute` is not.
    rated, _total = pi.page(
        db,
        gender=gender,
        competition_key=competition_key,
        competition_type=competition_type,
        limit=10**9,
        offset=0,
    )
    index_of = {r.player_identifier: r for r in rated}
    career = _career_standing(db, gender, competition_key, competition_type, summary)
    keepers = _keepers(db, gender, competition_key, competition_type)
    sourced = scout._sourced_attributes(db)
    openers = _openers(db, gender, competition_key, competition_type)

    # Who is eligible, and their volume in this scope.
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
    if team_id is not None:
        stmt = stmt.where(PlayerMatchStat.team_id == team_id)

    names = {
        p.identifier: preferred_name(p.name, p.display_name)
        for p in db.execute(select(Player)).scalars()
    }
    from .. import queries as _queries

    countries = _queries._player_country_map(db, gender)

    candidates: list[Pick] = []
    for pid, matches, bf, bb in db.execute(stmt).all():
        if matches < MIN_MATCHES:
            continue
        rating = index_of.get(pid)
        if rating is None:
            continue
        role = explorer.discipline(bf or 0, bb or 0)
        if role == "unknown":
            continue
        attrs = sourced.get(pid) or {}
        # A sourced keeper role beats our stumping inference, and reaches
        # keepers who simply never stumped in this scope - the one case the
        # stumping rule was known to miss.
        if attrs.get("role") == "Wicket Keeper":
            is_keeper, keeper_source = True, "squad"
        elif pid in keepers:
            is_keeper, keeper_source = True, "stumping"
        else:
            is_keeper, keeper_source = False, None
        verdict = summary.verdicts.get(pid)
        if verdict is None:
            continue
        # Career standing, recent quality and current touch. §18 asks for a best
        # side that accounts for form; all three on a 0-100 scale so the weights
        # in `config` mean what they say.
        form_pct = 50.0
        if verdict.delta_ratio is not None:
            # A delta of +/-100% maps to the ends of the scale, damped by how
            # much cricket the verdict rests on.
            moved = max(-1.0, min(1.0, verdict.delta_ratio)) * verdict.confidence
            form_pct = 50.0 + moved * 50.0
        w = config.SELECTION_WEIGHTS
        score = (
            w["career"] * career.get(pid, 50.0)
            + w["index"] * rating.index
            + w["form"] * form_pct
        )

        candidates.append(
            Pick(
                player_identifier=pid,
                player_name=names.get(pid, pid),
                role=role,
                slot="",
                is_wicketkeeper=is_keeper,
                keeper_source=keeper_source,
                opens=openers.get(pid, 0) >= config.OPENER_MIN_INNINGS,
                matches=matches,
                index=rating.index,
                form_delta=round(verdict.delta_ratio * 100, 1) if verdict.delta_ratio is not None else None,
                form_state=verdict.state,
                recent_mean=verdict.recent_mean,
                selection_score=round(score, 2),
                reason="",
                batting_style=attrs.get("batting_style"),
                bowling_family=attrs.get("bowling_family"),
                country=countries.get(pid, (None, None))[0],
                country_code=countries.get(pid, (None, None))[1],
            )
        )

    candidates.sort(key=lambda p: -p.selection_score)
    picks = _fill_shape(candidates, size)
    return Selection(
        scope=competition_key or competition_type or "international",
        gender=gender,
        size=size,
        team_id=team_id,
        team_name=None,
        picks=picks,
        shape=dict(XI_SHAPE),
        unavailable=UNAVAILABLE,
        notes=_notes(picks, size),
    )


def _fill_shape(candidates: list[Pick], size: int) -> list[Pick]:
    """Fill the required roles first, then the remaining places on merit.

    Taking the top `size` by score instead reliably returns a side with six
    openers and no keeper -- which is why selection is a shape and not a
    leaderboard.
    """
    chosen: list[Pick] = []
    taken: set[str] = set()

    # Scale the shape with the squad: a XV is a XI plus cover, not a different
    # side, so the same proportions apply.
    scale = size / 11.0
    wanted = {role: max(1, round(n * scale)) for role, n in XI_SHAPE.items()}

    # Keeper first. Without one the side is invalid, and the best keeper is
    # rarely the best batter, so picking on merit alone would never take them.
    for c in candidates:
        if len(chosen) >= size:
            break
        if c.is_wicketkeeper and sum(1 for p in chosen if p.slot == "wicketkeeper") < wanted["wicketkeeper"]:
            c.slot = "wicketkeeper"
            c.reason = (
                "Best available keeper - named one in an ICC squad."
                if c.keeper_source == "squad"
                else "Best available keeper - only a keeper can stump, which is how they are identified."
            )
            chosen.append(c)
            taken.add(c.player_identifier)

    for role in ("batter", "allrounder", "bowler"):
        for c in candidates:
            if len(chosen) >= size:
                break
            if c.player_identifier in taken or c.role != role:
                continue
            if sum(1 for p in chosen if p.slot == role) >= wanted[role]:
                break
            c.slot = role
            c.reason = f"Best available {role} on standard and current form."
            chosen.append(c)
            taken.add(c.player_identifier)

    # Remaining places on merit, whatever the role.
    for c in candidates:
        if len(chosen) >= size:
            break
        if c.player_identifier in taken:
            continue
        c.slot = c.role
        c.reason = "Picked on merit for an open place."
        chosen.append(c)
        taken.add(c.player_identifier)

    # Openers are marked among the batters already chosen, not picked separately.
    opening = [p for p in chosen if p.opens][:OPENERS_WANTED]
    for p in opening:
        p.reason += " Opens."
    return chosen


def _notes(picks: list[Pick], size: int) -> list[str]:
    """What the selector could not guarantee about this side."""
    notes = []
    if not any(p.is_wicketkeeper for p in picks):
        notes.append(
            "No wicketkeeper could be identified in this scope, so this side has none. "
            "A keeper is taken from an ICC squad naming them one, or failing that from "
            "having taken a stumping; a scope with too little cricket carries neither."
        )
    if sum(1 for p in picks if p.opens) < OPENERS_WANTED:
        notes.append(
            "Fewer than two players in this side have regularly opened, so the top order "
            "is not settled by the data."
        )
    if len(picks) < size:
        notes.append(
            f"Only {len(picks)} players clear the minimum of {MIN_MATCHES} matches in this scope."
        )

    # Balance is REPORTED, never selected for. Coverage of hand and bowling
    # style is partial, so a quota would prefer players with squad data over
    # better players without it. Stating the shortfall lets a selector apply
    # judgement the data cannot.
    bowlers = [p for p in picks if p.slot in ("bowler", "allrounder")]
    known_type = [p for p in bowlers if p.bowling_family]
    if known_type:
        seam = sum(1 for p in known_type if p.bowling_family == "pace")
        spin = len(known_type) - seam
        unknown = len(bowlers) - len(known_type)
        note = f"Attack: {seam} seam, {spin} spin of {len(bowlers)} bowling picks"
        note += f", {unknown} with no style on record." if unknown else "."
        # Only interpret the split when most of it is actually known. An
        # all-time PSL side is largely players who retired before the squad
        # feed's window, so "no spinner" would be said of a side containing
        # Rashid Khan and Sunil Narine. Counts are reported either way; the
        # conclusion is not drawn from a mostly-blank sample.
        if spin == 0 and len(known_type) > unknown and len(known_type) >= 2:
            note += " No spinner among them, which a turning surface would want."
        notes.append(note)

    top = [p for p in picks if p.opens or p.slot in ("opener", "batter")]
    known_hand = [p for p in top if p.batting_style]
    unknown_hand = len(top) - len(known_hand)
    if (
        len(known_hand) >= 2
        and len(known_hand) > unknown_hand
        and not any(p.batting_style == "LHB" for p in known_hand)
    ):
        notes.append(
            f"Top order is right-handed across the {len(known_hand)} of {len(top)} picks whose hand "
            "is on record, so there may be no left-right pair to unsettle a bowler's line."
        )
    return notes


__all__ = ["select_side", "Selection", "Pick", "XI_SHAPE", "UNAVAILABLE", "MIN_MATCHES"]

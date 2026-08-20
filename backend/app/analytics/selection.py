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
from datetime import date, timedelta

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

# §18's optimisation objectives. Each changes the side through the two levers
# that actually decide it: the ROLE SHAPE the eleven is filled to, and the
# WEIGHTING candidates are scored on. Nothing here is a separate algorithm - the
# selector is the same shape-fill either way, which is what keeps every
# objective explainable in the same terms.
#
# `bonus` names a preference term added on top of quality rather than replacing
# it. It carries OBJECTIVE_BONUS_WEIGHT and the base weights are renormalised to
# the remainder, so "youngest XI" still means "the best young side" and not "the
# youngest eleven who have played eight matches".
#
# Youth is a SOFT preference for the reason every age filter here is soft: date
# of birth covers about 42% of the register, so a hard one would discard the
# majority. A player of unknown age scores the neutral 50 and is reported.
OBJECTIVES: dict[str, dict] = {
    "overall": {
        "label": "Overall quality",
        "detail": "Career standing, rating and current form, on the default weighting.",
    },
    "form": {
        "label": "Current form",
        "detail": "Leans hard on the recent window while keeping career standing in the mix.",
        "weights": {"career": 0.25, "index": 0.30, "form": 0.45},
    },
    "batting": {
        "label": "Batting strength",
        "detail": "Six specialist batters instead of four, at the cost of a bowler.",
        "shape": {"wicketkeeper": 1, "batter": 6, "allrounder": 2, "bowler": 2},
    },
    "bowling": {
        "label": "Bowling strength",
        "detail": "Five specialist bowlers instead of three, at the cost of a batter.",
        "shape": {"wicketkeeper": 1, "batter": 3, "allrounder": 2, "bowler": 5},
    },
    "balance": {
        "label": "Balance",
        "detail": "An extra all-rounder, so the side has more ways to change a match.",
        "shape": {"wicketkeeper": 1, "batter": 4, "allrounder": 3, "bowler": 3},
    },
    "youth": {
        "label": "Youth",
        "detail": (
            "Prefers younger players among those of comparable standing. A soft "
            "preference: date of birth is known for about 42% of the register, "
            "and a player of unknown age is kept rather than dropped."
        ),
        "bonus": "youth",
    },
    "experience": {
        "label": "Experience",
        "detail": "Prefers the deepest records in this scope among comparable players.",
        "bonus": "experience",
    },
}

# How much of the score an objective's preference term takes. Deliberately a
# minority share: at 0.5 a "youth" side stopped being a good side, and §18 asks
# for the best XI *for an objective*, not the extreme of that objective.
OBJECTIVE_BONUS_WEIGHT = 0.20

# The age band the youth preference is measured across. A 19-year-old scores
# 100, a 38-year-old scores 0, and it is linear between - chosen from the
# observed range of ages in this register rather than as round numbers.
YOUTH_BEST_AGE = 19
YOUTH_WORST_AGE = 38

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
    form_delta: float | None     # % against their own baseline; unbounded
    form_score: float | None     # 0-100 percentile of the move; the display figure
    form_display: str | None     # the move in words, never a percentage over 100
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
class TradeOff:
    """A player good enough to be picked who was not, and the reason.

    §18 requires this outright: "Show what was traded off - the highest-rated
    player omitted, and the constraint that omitted them." Without it a side is
    an assertion; with it a selector can see the decision they are being asked
    to accept, which is what §2's rule 5 means by explainable.

    Only players who out-score somebody actually picked appear here. A candidate
    who scored below every pick was not traded off - they simply were not good
    enough, and listing them would bury the real trade in noise.
    """

    player_identifier: str
    player_name: str
    role: str
    selection_score: float
    index: float | None
    matches: int
    country: str | None = None
    country_code: str | None = None
    # The constraint that kept them out, in the terms the selector applies it.
    reason: str = ""
    # Who holds the place they would have taken, and by how much less.
    displaced: str | None = None
    displaced_score: float | None = None


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
    # Which pool was picked from, and what that came to. Reported rather than
    # implied: a side is only readable if you know who could have been in it.
    pool: str = "all_time"
    pool_size: int = 0
    pool_considered: int = 0
    # The scope's most recent match, and the cutoff derived from it. Both null
    # for an all-time pool, where no window applies.
    reference_date: str | None = None
    cutoff_date: str | None = None
    # The weights actually applied, so the blend is checkable on the page.
    weights: dict = field(default_factory=dict)
    # Which of §18's objectives this side answers, and what that changed.
    objective: str = "overall"
    objective_label: str = ""
    objective_detail: str = ""
    # The best players left out, with the constraint that left them out (§18).
    tradeoffs: list[TradeOff] = field(default_factory=list)
    # Players whose age is unknown, where the objective depends on age. Reported
    # for the same reason Scout reports it: date of birth covers ~42% of the
    # register and a hard bound would discard the majority silently.
    unknown_age: int = 0


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


# What `pool` may be. 'all_time' is the original behaviour and stays the
# default, so an existing link keeps returning the side it used to.
POOLS = ("all_time", "current")


def _current_pool(
    db: Session, gender: str, competition_key, competition_type
) -> tuple[set[str], str | None, str | None]:
    """Players still in the picture for this scope: (identifiers, anchor, cutoff).

    Two rules, and the second is the one that matters:

    * A **sourced** retirement date or date of death excludes a player
      outright. That is almost nobody - 43 in the whole register - because
      this project never infers retirement from a gap in appearances. It is
      applied anyway, since where a source does say so it is the strongest
      signal available.
    * Otherwise, last appearance IN THIS SCOPE within
      `config.SELECTION_CURRENT_WINDOW_DAYS`.

    The window is anchored to the newest match in the SCOPE, not to today and
    not to the newest match in the database. Anchoring to today would empty
    the pool the moment the Cricsheet archive went stale, which is the trap
    `player_status` already documents. Anchoring to the whole database would
    be worse for a league: the PSL season ends in May and the newest match
    overall is an August Test, so a PSL pool measured against the database
    would silently lose three and a half months of its own season.

    Returns the anchor and cutoff so the caller can state what "current"
    meant rather than leaving the reader to assume it means "today".
    """
    stmt = (
        select(
            PlayerMatchStat.player_identifier,
            func.max(Match.match_date_start),
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

    last_played = {pid: last for pid, last in db.execute(stmt).all() if last}
    if not last_played:
        return set(), None, None

    anchor = max(last_played.values())
    try:
        cutoff = (
            date.fromisoformat(anchor[:10])
            - timedelta(days=config.SELECTION_CURRENT_WINDOW_DAYS)
        ).isoformat()
    except ValueError:
        return set(last_played), anchor, None

    gone = {
        pid
        for pid, in db.execute(
            select(Player.identifier).where(
                (Player.retirement_date.is_not(None))
                | (Player.date_of_death.is_not(None))
            )
        ).all()
    }
    return (
        {pid for pid, last in last_played.items() if last >= cutoff and pid not in gone},
        anchor,
        cutoff,
    )


def select_side(
    db: Session,
    *,
    gender: str,
    size: int = 11,
    competition_key: str | None = None,
    competition_type: str | None = None,
    team_id: int | None = None,
    pool: str = "all_time",
    objective: str = "overall",
) -> Selection:
    """Pick a side of `size` within one scope.

    `pool='current'` restricts the candidates to players still in the picture
    for this scope and shifts the weighting towards recent evidence. It answers
    a different question from the default: "who should we pick next", rather
    than "who was the best there has ever been".

    `objective` is §18's optimisation target. It changes the role shape, the
    weighting, or both - see OBJECTIVES - and the response reports which, because
    the same heading means a different side depending on it.
    """
    if pool not in POOLS:
        pool = "all_time"
    if objective not in OBJECTIVES:
        objective = "overall"
    spec = OBJECTIVES[objective]
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
    openers = explorer.openers(db, gender, competition_key, competition_type)

    eligible_now: set[str] | None = None
    anchor = cutoff = None
    if pool == "current":
        eligible_now, anchor, cutoff = _current_pool(
            db, gender, competition_key, competition_type
        )

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

    people = list(db.execute(select(Player)).scalars())
    names = {p.identifier: preferred_name(p.name, p.display_name) for p in people}
    from .. import queries as _queries

    countries = _queries._player_country_map(db, gender)

    # The objective's two levers, resolved before the loop so every candidate is
    # scored the same way.
    weights = spec.get("weights") or (
        config.SELECTION_WEIGHTS_CURRENT if pool == "current"
        else config.SELECTION_WEIGHTS
    )
    shape = spec.get("shape") or XI_SHAPE
    bonus_kind = spec.get("bonus")

    # Ages, for the youth objective only. Measured against the newest match in
    # the DATASET rather than today, the same anchor `player_status` uses: a
    # stale archive must not silently age every player out of a youth side.
    ages: dict[str, int] = {}
    unknown_age = 0
    if bonus_kind == "youth":
        as_of = _queries.dataset_latest_date(db)
        reference = None
        if as_of:
            try:
                reference = date.fromisoformat(as_of[:10])
            except ValueError:
                reference = None
        if reference is not None:
            for person in people:
                if not person.date_of_birth:
                    continue
                try:
                    born = date.fromisoformat(person.date_of_birth[:10])
                except ValueError:
                    continue
                ages[person.identifier] = (reference - born).days // 365

    rows = db.execute(stmt).all()
    # The experience term is relative to the deepest record available in this
    # scope, so it needs the maximum before any candidate is scored.
    max_matches = max((m for _, m, _, _ in rows), default=0) if bonus_kind == "experience" else 0

    candidates: list[Pick] = []
    considered = 0
    for pid, matches, bf, bb in rows:
        if matches < MIN_MATCHES:
            continue
        considered += 1
        if eligible_now is not None and pid not in eligible_now:
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
        # `form_score` is the verdict's percentile within this scope: bounded
        # 0-100 by construction and calibrated against the population. It
        # replaced a local clamp of the ratio to +/-100%, which handed every
        # player past a doubling an identical form term and so could not tell
        # the strongest movers apart. 50 is neutral, used where the verdict is
        # too thin to place.
        form_pct = verdict.form_score if verdict.form_score is not None else 50.0
        quality = (
            weights["career"] * career.get(pid, 50.0)
            + weights["index"] * rating.index
            + weights["form"] * form_pct
        )
        # An objective's preference term rides on top of quality rather than
        # replacing it, so "youngest XI" still means the best young side. 50 is
        # neutral, which is what an unknown age scores.
        if bonus_kind is None:
            score = quality
        else:
            preference = 50.0
            if bonus_kind == "youth":
                player_age = ages.get(pid)
                if player_age is None:
                    unknown_age += 1
                else:
                    span = YOUTH_WORST_AGE - YOUTH_BEST_AGE
                    ratio = (YOUTH_WORST_AGE - player_age) / span
                    preference = 100.0 * max(0.0, min(1.0, ratio))
            elif bonus_kind == "experience":
                # Against the deepest record in this scope, so the term means
                # "experienced relative to who is available" rather than against
                # an arbitrary match count.
                preference = 100.0 * min(1.0, matches / max_matches) if max_matches else 50.0
            score = (1.0 - OBJECTIVE_BONUS_WEIGHT) * quality + OBJECTIVE_BONUS_WEIGHT * preference

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
                form_score=verdict.form_score,
                form_display=verdict.delta_display,
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
    picks, tradeoffs = _fill_shape(candidates, size, shape)
    return Selection(
        scope=competition_key or competition_type or "international",
        gender=gender,
        size=size,
        team_id=team_id,
        team_name=None,
        picks=picks,
        shape=dict(shape),
        unavailable=UNAVAILABLE,
        notes=_notes(picks, size),
        pool=pool,
        pool_size=len(candidates),
        pool_considered=considered,
        reference_date=anchor,
        cutoff_date=cutoff,
        weights=dict(weights),
        objective=objective,
        objective_label=spec["label"],
        objective_detail=spec["detail"],
        tradeoffs=tradeoffs,
        unknown_age=unknown_age,
    )



def _fill_shape(
    candidates: list[Pick], size: int, shape: dict[str, int]
) -> tuple[list[Pick], list[TradeOff]]:
    """Fill the required roles first, then the remaining places on merit.

    Taking the top `size` by score instead reliably returns a side with six
    openers and no keeper -- which is why selection is a shape and not a
    leaderboard.

    Also records what that cost. §18 requires the highest-rated omitted player
    and the constraint that omitted them, and the shape-fill is the only place
    that knows: by the time a caller sees the eleven, the reason a better player
    is missing has been discarded. So each candidate passed over is tagged with
    the quota that was full when their turn came.
    """
    chosen: list[Pick] = []
    taken: set[str] = set()
    # player_identifier -> the constraint that passed over them.
    blocked: dict[str, str] = {}

    # Scale the shape with the squad: a XV is a XI plus cover, not a different
    # side, so the same proportions apply.
    scale = size / 11.0
    wanted = {role: max(1, round(n * scale)) for role, n in shape.items()}

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
        quota = wanted.get(role, 0)
        for c in candidates:
            if len(chosen) >= size:
                break
            if c.player_identifier in taken or c.role != role:
                continue
            if sum(1 for p in chosen if p.slot == role) >= quota:
                # Every remaining candidate in this role is blocked by the same
                # full quota, so record it and stop walking the role.
                for later in candidates:
                    if later.player_identifier in taken or later.role != role:
                        continue
                    blocked.setdefault(
                        later.player_identifier,
                        f"the {quota} {role} place{'s' if quota != 1 else ''} were already filled",
                    )
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

    return chosen, _tradeoffs(candidates, chosen, taken, blocked, size)


# How many omitted players to report. Enough to see the shape of the decision
# rather than only its single sharpest instance.
MAX_TRADEOFFS = 5


def _tradeoffs(
    candidates: list[Pick],
    chosen: list[Pick],
    taken: set[str],
    blocked: dict[str, str],
    size: int,
) -> list[TradeOff]:
    """The best players left out, and what left them out.

    Only players who out-score somebody actually picked qualify. A candidate
    below every pick was not traded off - they were not good enough - and
    including them would bury the real trade in a list of also-rans.
    """
    if not chosen:
        return []
    weakest = min(chosen, key=lambda p: p.selection_score)
    out: list[TradeOff] = []
    for c in candidates:
        if len(out) >= MAX_TRADEOFFS:
            break
        if c.player_identifier in taken:
            continue
        if c.selection_score <= weakest.selection_score:
            # Candidates are score-ordered, so nobody after this one qualifies.
            break
        reason = blocked.get(
            c.player_identifier,
            f"the side was complete at {size} before their place came up",
        )
        out.append(
            TradeOff(
                player_identifier=c.player_identifier,
                player_name=c.player_name,
                role=c.role,
                selection_score=c.selection_score,
                index=c.index,
                matches=c.matches,
                country=c.country,
                country_code=c.country_code,
                reason=reason,
                displaced=weakest.player_name,
                displaced_score=weakest.selection_score,
            )
        )
    return out


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

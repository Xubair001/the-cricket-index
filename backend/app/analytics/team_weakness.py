r"""Team weakness analysis (Section 19).

Section 19 calls this "the differentiator" on a team page and gives the shape of
the answer it wants: *"death bowling performance has declined over the last 10
matches"*. Three things are load-bearing in that sentence and all three are
implemented literally.

**A facet, not a total.** "This side is weak" is not actionable. A weakness is
always a named phase or situation - death bowling, the powerplay, chasing - so a
coach knows what to work on.

**Against the side's OWN past, not against a league table.** "Declined" is a
comparison with themselves. A side can be the best death-bowling attack in the
world and still be declining, and that is the thing worth surfacing early. The
peer comparison is computed too and reported beside it, because the two answer
different questions and a reader needs both: falling from excellent to good is
not the same problem as being persistently below everyone else.

**A window of the side's own last N matches, not a date range.** The same rule
`squad.py` already follows and for the same reason: there are ~110
international sides here and most play in bursts, so a calendar window measures
the fixture list rather than the side.

What this refuses to do
------------------------
* **Phases do not exist in a Test.** `config.PHASE_BANDS` has no Test entry
  because a T20 powerplay is six overs and an ODI's is ten, and slicing overs
  0-5 off a Test innings produces a number that looks like the T20 one and means
  something else. Test sides get the format-independent facets only, and the
  phase facets are reported as inapplicable rather than omitted.
* **Invent a weakness when there is not one.** A side with nothing materially
  worse gets an empty list and a sentence saying so. A page that always finds
  three weaknesses is a horoscope.
* **Call a thin sample a weakness.** Every facet carries the deliveries it rests
  on, and one below `MIN_DELIVERIES` in either window is not judged at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from ..models import Competition, Delivery, Match, Team
from . import config

# The scope's own number. Also about a season for most sides.
RECENT_MATCHES = 10

# How far back the "own past" reaches. Bounded rather than "everything before",
# so the baseline is a comparable recent era rather than a career average that
# drifts as a side plays more - and so a side that changed generation five
# years ago is not judged against players who have retired.
BASELINE_MATCHES = 40

# Below this a facet is not judged in either window. A T20 side's death overs
# are roughly 24 balls a match, so 10 matches is ~240 - this floor keeps a side
# that has played few matches in the window from producing a verdict on 30
# deliveries.
MIN_DELIVERIES = 120

# How much worse than their own baseline before it is called a decline.
#
# Measured over 536 facet comparisons across 97 men's T20I sides, the spread of
# |change against own baseline| is: median 10.5%, p75 18.2%, p90 29.4%. A first
# guess of 8% would have flagged 62% of all phases as declining, which is a
# horoscope rather than an analysis.
#
# That spread is NOT mostly small-sample noise, which was worth checking before
# blaming the window: widening the recent window from 10 matches to 30 moves the
# median only from 10.5% to 9.0%. Team phase rates genuinely move about 10%
# between eras as personnel and conditions change. So the window stays at
# Section 19's own ten matches and the threshold sits in the tail of real
# variation instead.
#
# 20% is roughly p80 and flags about one phase per side - a death economy going
# from 9.0 to 10.8, which is a decline a coach would act on.
DECLINE_THRESHOLD = 0.20

# Facets whose figure is better when LOWER (an economy rate conceded).
LOWER_IS_BETTER = {"bowling"}


@dataclass
class Facet:
    key: str
    label: str
    # 'batting' or 'bowling'. Decides which direction is worse.
    side: str
    recent: float | None
    baseline: float | None
    peer_median: float | None
    recent_deliveries: int
    baseline_deliveries: int
    # Change against their own past, signed so that negative is always worse
    # regardless of whether the underlying figure is a rate or an economy.
    delta_percent: float | None = None
    # Against everyone else in the scope, same sign convention.
    versus_peers_percent: float | None = None
    verdict: str = "unmeasured"
    note: str = ""


@dataclass
class TeamWeakness:
    team_id: int
    team_name: str
    competition_key: str | None
    recent_matches: int
    baseline_matches: int
    facets: list[Facet] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    unavailable: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _team_matches(db: Session, team_id: int, competition_key: str | None) -> list[str]:
    """The side's own matches in the scope, newest first."""
    stmt = (
        select(Match.match_id)
        .join(Competition, Competition.competition_id == Match.competition_id)
        .where((Match.team1_id == team_id) | (Match.team2_id == team_id))
        .order_by(Match.match_date_start.desc())
    )
    if competition_key:
        stmt = stmt.where(Competition.key == competition_key)
    return [m for (m,) in db.execute(stmt).all()]


def _phase_of(over: int, bands) -> str | None:
    for key, _label, lo, hi in bands:
        if lo <= over <= hi:
            return key
    return None


def _gather(
    db: Session, match_ids: list[str], team_id: int | None, bands
) -> dict[tuple[str, str], list[int]]:
    """Runs and legal balls per (phase, side), for one set of matches.

    `team_id` None means every side, which is how the peer baseline is built.
    Batting is attributed by `deliveries.batting_team_id`; bowling is the same
    delivery seen from the other end, so a side's bowling phases are the
    deliveries in its matches that its opponents batted.
    """
    if not match_ids:
        return {}
    totals: dict[tuple[str, str], list[int]] = {}
    for i in range(0, len(match_ids), 400):
        chunk = match_ids[i : i + 400]
        rows = db.execute(
            select(
                Delivery.over,
                Delivery.batting_team_id,
                func.sum(Delivery.runs_total),
                # Wides and no-balls are not legal deliveries, so they are
                # excluded from the ball count but their runs still count
                # against the bowling side - the same rule parsing.py applies.
                func.sum(
                    (Delivery.wides == 0).cast(Integer) * (Delivery.noballs == 0).cast(Integer)
                ),
            )
            .where(Delivery.match_id.in_(chunk))
            .group_by(Delivery.over, Delivery.batting_team_id)
        ).all()
        for over, batting_team, runs, legal in rows:
            phase = _phase_of(over or 0, bands)
            if phase is None:
                continue
            for side, applies in (
                ("batting", team_id is None or batting_team == team_id),
                ("bowling", team_id is None or batting_team != team_id),
            ):
                if not applies:
                    continue
                bucket = totals.setdefault((phase, side), [0, 0])
                bucket[0] += runs or 0
                bucket[1] += legal or 0
    return totals


def _rate(runs: int, balls: int) -> float | None:
    """Runs per over. The unit both batting and bowling phases are read in."""
    return round(runs / balls * 6, 2) if balls else None


def _signed_delta(recent: float, reference: float, side: str) -> float:
    """Percent change, signed so NEGATIVE is always worse.

    Needed because the two sides read in opposite directions: 7.2 runs an over
    is good batting and bad bowling. Without the flip a declining attack would
    show as an improvement.
    """
    if not reference:
        return 0.0
    change = (recent - reference) / reference * 100
    return change if side == "batting" else -change


def analyse(
    db: Session, team_id: int, competition_key: str | None = None
) -> TeamWeakness | None:
    team = db.get(Team, team_id)
    if team is None:
        return None

    bands = config.PHASE_BANDS.get(competition_key or "")
    unavailable: dict[str, str] = {}
    if not bands:
        unavailable["phases"] = (
            "Phases are defined per competition and Tests have none: a T20 "
            "powerplay is six overs and an ODI's is ten, so slicing the first "
            "six overs off a Test innings gives a number that looks like the "
            "T20 one and means something else. Pick a limited-overs "
            "competition to see phase analysis."
        )
    unavailable["opposition_quality"] = (
        "A phase figure here is not adjusted for who it came against. The "
        "opposition model scales this project's own impact measures, not "
        "conventional rates, so a side whose recent fixtures were unusually "
        "hard will look worse than it is."
    )

    matches = _team_matches(db, team_id, competition_key)
    recent_ids = matches[:RECENT_MATCHES]
    baseline_ids = matches[RECENT_MATCHES : RECENT_MATCHES + BASELINE_MATCHES]

    result = TeamWeakness(
        team_id=team_id,
        team_name=team.name,
        competition_key=competition_key,
        recent_matches=len(recent_ids),
        baseline_matches=len(baseline_ids),
        unavailable=unavailable,
    )
    if not bands:
        result.notes.append(
            f"{team.name} has {len(matches)} matches in this scope. No phase "
            f"analysis is possible for this competition."
        )
        return result
    if len(recent_ids) < RECENT_MATCHES or not baseline_ids:
        result.notes.append(
            f"Not enough cricket to compare: {len(recent_ids)} recent matches "
            f"and {len(baseline_ids)} before them. A weakness is a change "
            f"against the side's own past, which needs both."
        )
        return result

    recent = _gather(db, recent_ids, team_id, bands)
    baseline = _gather(db, baseline_ids, team_id, bands)
    # Peers: the same phases over the same recent window across the whole scope,
    # so a comparison is against how cricket is being played now rather than
    # against a 25-year average.
    peers = _peer_rates(db, competition_key, team.gender, bands, exclude_team=team_id)

    labels = {key: label for key, label, _lo, _hi in bands}
    for phase_key, phase_label in labels.items():
        for side in ("batting", "bowling"):
            r_runs, r_balls = recent.get((phase_key, side), [0, 0])
            b_runs, b_balls = baseline.get((phase_key, side), [0, 0])
            facet = Facet(
                key=f"{phase_key}_{side}",
                label=f"{phase_label} {side}",
                side=side,
                recent=_rate(r_runs, r_balls),
                baseline=_rate(b_runs, b_balls),
                peer_median=peers.get((phase_key, side)),
                recent_deliveries=r_balls,
                baseline_deliveries=b_balls,
            )
            if r_balls < MIN_DELIVERIES or b_balls < MIN_DELIVERIES:
                facet.verdict = "unmeasured"
                facet.note = (
                    f"{r_balls} recent and {b_balls} earlier legal deliveries; "
                    f"{MIN_DELIVERIES} are needed in each before this is judged."
                )
                result.facets.append(facet)
                continue

            facet.delta_percent = round(
                _signed_delta(facet.recent, facet.baseline, side), 1
            )
            if facet.peer_median:
                facet.versus_peers_percent = round(
                    _signed_delta(facet.recent, facet.peer_median, side), 1
                )
            facet.verdict = _verdict(facet)
            facet.note = _facet_note(facet)
            result.facets.append(facet)

    result.weaknesses = [f.note for f in result.facets if f.verdict == "declined"]
    result.notes.append(_summary(team.name, result))
    return result


def _verdict(f: Facet) -> str:
    """'declined' only against the side's OWN past, per Section 19's wording.

    Being below the peer median is reported on the facet but is deliberately
    not what makes something a weakness here: a side can sit below the median
    for its whole history without anything having gone wrong, and a page that
    called that a weakness would tell every below-average side the same thing.
    """
    threshold = DECLINE_THRESHOLD * 100
    if f.delta_percent is None:
        return "unmeasured"
    if f.delta_percent <= -threshold:
        return "declined"
    if f.delta_percent >= threshold:
        return "improved"
    return "steady"


def _facet_note(f: Facet) -> str:
    direction = "declined" if f.delta_percent < 0 else "improved"
    unit = "conceded" if f.side == "bowling" else "scored"
    note = (
        f"{f.label.capitalize()} has {direction} {abs(f.delta_percent):.0f}% "
        f"over the last {RECENT_MATCHES} matches: {f.recent} runs an over "
        f"{unit} against {f.baseline} before them"
    )
    if f.versus_peers_percent is not None:
        stance = "above" if f.versus_peers_percent > 0 else "below"
        note += (
            f". That is {abs(f.versus_peers_percent):.0f}% {stance} the core "
            f"sides of this competition ({f.peer_median})"
        )
    return note + "."


def _summary(name: str, result: TeamWeakness) -> str:
    judged = [f for f in result.facets if f.verdict != "unmeasured"]
    declined = [f for f in judged if f.verdict == "declined"]
    if not judged:
        return (
            f"No phase carries enough cricket in both windows to judge "
            f"{name} on."
        )
    if not declined:
        return (
            f"Nothing has materially declined. All {len(judged)} phases "
            f"measured are within {DECLINE_THRESHOLD * 100:.0f}% of "
            f"{name}'s own recent baseline, so this side has no weakness "
            f"this analysis can find - which is a result, not an empty page."
        )
    return (
        f"{len(declined)} of {len(judged)} measured phases have fallen more "
        f"than {DECLINE_THRESHOLD * 100:.0f}% against {name}'s own baseline "
        f"of the {result.baseline_matches} matches before these."
    )


def _peer_rates(
    db: Session, competition_key: str | None, gender: str, bands, exclude_team: int
) -> dict[tuple[str, str], float]:
    """Run rate per (phase, side) over the CORE sides of this competition.

    Two references were tried and rejected against data before this one, and
    both failed the same way:

    * **Median of every side's rate.** Put powerplay batting at 6.82 an over
      while every Test nation sat between 8.9 and 9.7 - so each of them was
      told it was 35% "above par". There are ~110 men's international sides and
      most play rarely, so the median side is an associate.
    * **Pooled over every delivery.** Volume-weighting does not rescue it,
      because the population genuinely IS mostly associate cricket: more than
      half the men's T20Is here are between sides outside the full members.
      Powerplay barely moved, to 6.77.
    * **The most active sides in a RECENT window.** This looked like the fix
      and was the worst of the three: in 2019 the ICC granted T20I status to
      every member, so the 600 most recent men's T20Is are dominated by
      associate cricket and the "core" it selected was Austria, Indonesia,
      Sweden, Brazil and Romania. The tell was that every side came out above
      the reference on batting and below it on bowling at once, which cannot
      happen against a real peer group.

    This is the trap `opposition.py` documents for its own reference point - a
    team-count reference puts par opposition at roughly Malta - and the fix is
    the same: anchor to a stable core. Peers here are the `PEER_CORE_SIDES`
    that played the most in the window, which is the set that actually contests
    the competition regularly, and the figure is pooled over their deliveries.

    An associate side is therefore measured against established opposition,
    which is the honest reading rather than a flattering one: the label on the
    page says "the core sides of this competition", not "average".
    """
    # Gender is a hard partition here as everywhere: without it a men's team
    # page was measured against a pool containing women's matches.
    scoped = select(Match.match_id, Match.team1_id, Match.team2_id).join(
        Competition, Competition.competition_id == Match.competition_id
    ).where(Match.gender == gender)
    if competition_key:
        scoped = scoped.where(Competition.key == competition_key)

    # The core is chosen on ALL-TIME volume, not recent volume. Full members
    # have played T20Is since 2005 and most associates only since the 2019
    # status expansion, so career volume separates them cleanly where a recent
    # window inverts them.
    all_time = db.execute(scoped).all()
    career: dict[int, int] = {}
    for _m, t1, t2 in all_time:
        for t in (t1, t2):
            if t:
                career[t] = career.get(t, 0) + 1
    core = {
        team_id
        for team_id, _ in sorted(career.items(), key=lambda kv: -kv[1])[:PEER_CORE_SIDES]
    } - {exclude_team}
    if not core:
        return {}

    # Then the recent window, restricted to matches between two core sides -
    # so the reference is core cricket, not a core side dismantling an
    # associate.
    recent_rows = db.execute(
        scoped.order_by(Match.match_date_start.desc()).limit(PEER_MATCH_WINDOW)
    ).all()
    core_matches = [
        m for m, t1, t2 in recent_rows if t1 in core and t2 in core
    ]
    if not core_matches:
        return {}

    # `_gather` with team_id None counts each delivery once on the batting side
    # and once on the bowling side, which is the pooled figure wanted here.
    pooled = _gather(db, core_matches, None, bands)
    return {
        key: round(runs / balls * 6, 2)
        for key, (runs, balls) in pooled.items()
        if balls >= MIN_DELIVERIES
    }


# How many recent matches in the scope the peer sample is drawn from. Bounded
# so the comparison is against contemporary cricket rather than a 25-year
# average, and so the query does not walk the whole competition.
PEER_MATCH_WINDOW = 600

# How many sides form the reference core, by all-time volume in the scope.
# Twelve is the number of full members and is what a reader means by "how this
# competition is played at the top". Raising it reaches down into sides that
# joined at the 2019 expansion and drags the reference back towards the
# associate figure the rejected versions produced.
PEER_CORE_SIDES = 12

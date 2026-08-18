"""The form engine -- is this player playing better or worse than they usually do?

Method
------
1. Every match in scope becomes an impact figure (`impact.py`), normalized so
   that 1.0 is a par appearance in that competition. Batting and bowling become
   comparable, and so do formats -- without that second step a player who moves
   from Tests to T20Is shows a collapse in form having changed nothing, because
   a Test appearance is worth nearly four times a T20I one in raw runs.
2. The **recent window** is the player's last N matches (default 10).
3. The **baseline** is the same player over the preceding 12 months, with the
   recent window removed. Form is measured against the player's own normal
   level, never against other players -- that is what makes "in form" mean
   *changed*, rather than *good*.
4. The verdict is the change in mean impact per match, banded by `config`.
5. A trend is taken *within* the recent window by comparing its older half with
   its newer half, so "improving" and "declining" describe direction rather than
   just position against the baseline.

Every step is reported, not just the verdict. `FormVerdict` carries the two
means, the sample sizes, the delta, the trend and a confidence figure, because a
classification drawn from four innings and one drawn from forty must not look
identical in the UI.

Deliberate limits
-----------------
Self-relative comparison means an ordinary player having a good month and a
great player having a good month both read "in form". That is correct for this
question -- "who has changed" is not "who is best", and conflating them is how
form tables end up just re-listing the best players. Ranking by standard is the
Performance Index's job, and the two are shown side by side rather than merged.

A player whose baseline is near zero (a tail-ender, or someone who has barely
batted or bowled) cannot produce a meaningful percentage change; below
`MIN_MEANINGFUL_BASELINE` the delta is reported in absolute impact units and
confidence is capped.

**Opposition is adjusted for**, via `opposition.py`. Par is measured per
competition, so a T20I is judged against T20I norms -- but every T20I shares one
par, whether it was played against Australia or Indonesia. Left there, the board
ranked by weakness of opposition: players whose recent cricket was against
Norway, Portugal and Malta outranked Virat Kohli, having done nothing harder.
Each performance is therefore scaled by how much resistance the opposing side
actually offers, measured from what every other player scores against them. The
displayed figure is still what the player did; only the comparison is adjusted.

What remains unadjusted is *situation*: a match-winning 40 in a collapse and a
dead-rubber 40 still score alike, because that needs the per-delivery data Tier B
unlocks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import cache
from ..models import Competition, Match, PlayerMatchStat
from . import config, impact as impact_mod, opposition as opposition_mod


# slots=True: a form board or a Best XI materialises every impact in a scope -
# 154,400 objects for men's internationals - and a plain dataclass carries a
# per-instance __dict__ that dominates the cost at that count. Measured at 731
# bytes and 113 MB held per scope before, which is what kept these maps off the
# cache. Nothing here needs a dynamic attribute, and the `value` property works
# unchanged under slots.
@dataclass(slots=True)
class MatchImpact:
    """One match in a player's timeline, with its impact decomposed."""

    match_id: str
    match_date: str | None
    competition_key: str
    gender: str
    # Both sides are carried: the opponent rates the difficulty, and the
    # player's own side is what a contribution share is taken against. Deriving
    # one from the other at the call site is how a player ends up measured as a
    # share of the opposition's effort.
    team_id: int | None
    opponent_team_id: int | None
    runs_scored: int
    balls_faced: int
    wickets_taken: int
    balls_bowled: int
    runs_conceded: int
    impact: impact_mod.Impact
    # How much this performance is worth given who it came against (1.0 = an
    # average side, so no adjustment). See `opposition.py`.
    opposition_multiplier: float = 1.0

    @property
    def value(self) -> float:
        """Impact in par units, adjusted for the strength of the opposition.

        This -- not `impact.normalized` -- is what the form engine measures. The
        raw figure stays on `impact` so the UI can still show what the player
        actually did; only the comparison is adjusted.
        """
        return self.impact.normalized * self.opposition_multiplier

    def as_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "match_date": self.match_date,
            "competition_key": self.competition_key,
            "runs_scored": self.runs_scored,
            "balls_faced": self.balls_faced,
            "wickets_taken": self.wickets_taken,
            "balls_bowled": self.balls_bowled,
            "runs_conceded": self.runs_conceded,
            "impact": round(self.impact.total, 2),
            "impact_normalized": round(self.impact.normalized, 3),
            "opposition_multiplier": round(self.opposition_multiplier, 3),
            "adjusted_value": round(self.value, 3),
        }


@dataclass
class FormVerdict:
    state: str
    label: str
    recent_mean: float | None
    baseline_mean: float | None
    recent_matches: int
    baseline_matches: int
    delta_ratio: float | None      # None when the baseline is too small to divide by
    delta_absolute: float | None
    trend: str                     # rising | flat | falling | unknown
    confidence: float              # 0..1
    explanation: str
    recent_window_label: str
    baseline_window_label: str
    timeline: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "label": self.label,
            "recent_mean": _round(self.recent_mean),
            "baseline_mean": _round(self.baseline_mean),
            "recent_matches": self.recent_matches,
            "baseline_matches": self.baseline_matches,
            "delta_ratio": _round(self.delta_ratio, 4),
            "delta_absolute": _round(self.delta_absolute),
            "delta_percent": _round(self.delta_ratio * 100) if self.delta_ratio is not None else None,
            "trend": self.trend,
            "confidence": _round(self.confidence, 3),
            "explanation": self.explanation,
            "recent_window": self.recent_window_label,
            "baseline_window": self.baseline_window_label,
            "timeline": self.timeline,
        }


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


def player_timeline(
    db: Session,
    player_identifier: str,
    *,
    competition_key: str | None = None,
    competition_type: str | None = None,
    limit: int | None = None,
) -> list[MatchImpact]:
    """Every match this player appears in, newest first, scored for impact.

    Ordered by date descending with match_id as a tiebreak so that two matches
    on the same date -- common in a tournament -- always order the same way.
    Without it, "last 10 matches" can quietly return a different ten between
    two requests and the form verdict flickers.
    """
    par = impact_mod.par_table(db)
    opp = opposition_mod.table(db)

    stmt = (
        select(
            PlayerMatchStat.match_id,
            Match.match_date_start,
            Competition.key,
            Match.gender,
            Match.team1_id,
            Match.team2_id,
            PlayerMatchStat.team_id,
            PlayerMatchStat.runs_scored,
            PlayerMatchStat.balls_faced,
            PlayerMatchStat.wickets_taken,
            PlayerMatchStat.balls_bowled,
            PlayerMatchStat.runs_conceded,
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .join(Competition, Competition.competition_id == Match.competition_id)
        .where(PlayerMatchStat.player_identifier == player_identifier)
        .order_by(Match.match_date_start.desc(), PlayerMatchStat.match_id.desc())
    )
    if competition_key:
        stmt = stmt.where(Competition.key == competition_key)
    if competition_type:
        stmt = stmt.where(Competition.type == competition_type)
    if limit:
        stmt = stmt.limit(limit)

    out: list[MatchImpact] = []
    for row in db.execute(stmt).all():
        (
            match_id, match_date, comp_key, gender,
            team1_id, team2_id, team_id,
            runs, balls_faced, wickets, balls_bowled, conceded,
        ) = row
        opponent = team2_id if team_id == team1_id else team1_id
        out.append(
            MatchImpact(
                opposition_multiplier=opp.multiplier(opponent, match_date),
                match_id=match_id,
                match_date=match_date,
                competition_key=comp_key,
                gender=gender,
                team_id=team_id,
                opponent_team_id=opponent,
                runs_scored=runs or 0,
                balls_faced=balls_faced or 0,
                wickets_taken=wickets or 0,
                balls_bowled=balls_bowled or 0,
                runs_conceded=conceded or 0,
                impact=impact_mod.score(
                    runs_scored=runs or 0,
                    balls_faced=balls_faced or 0,
                    wickets_taken=wickets or 0,
                    balls_bowled=balls_bowled or 0,
                    runs_conceded=conceded or 0,
                    par=par.lookup(comp_key, gender),
                ),
            )
        )
    return out


def all_timelines(
    db: Session,
    *,
    gender: str,
    competition_key: str | None = None,
    competition_type: str | None = None,
) -> dict[str, list[MatchImpact]]:
    """Every player's scored timeline, in one query.

    `player_timeline` is fine for one profile but issues a query per player,
    which makes a leaderboard over ~2,600 players 2,600 round trips. This pulls
    the whole scope once and groups in Python; the per-player verdict is then
    computed by the same `assess` used on a profile page, so a leaderboard row
    and a profile can never disagree about a player's form.
    """
    par = impact_mod.par_table(db)
    opp = opposition_mod.table(db)

    stmt = (
        select(
            PlayerMatchStat.player_identifier,
            PlayerMatchStat.match_id,
            Match.match_date_start,
            Competition.key,
            Match.gender,
            Match.team1_id,
            Match.team2_id,
            PlayerMatchStat.team_id,
            PlayerMatchStat.runs_scored,
            PlayerMatchStat.balls_faced,
            PlayerMatchStat.wickets_taken,
            PlayerMatchStat.balls_bowled,
            PlayerMatchStat.runs_conceded,
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .join(Competition, Competition.competition_id == Match.competition_id)
        .where(
            PlayerMatchStat.player_identifier.is_not(None),
            Match.gender == gender,
        )
        .order_by(
            PlayerMatchStat.player_identifier,
            Match.match_date_start.desc(),
            PlayerMatchStat.match_id.desc(),
        )
    )
    if competition_key:
        stmt = stmt.where(Competition.key == competition_key)
    if competition_type:
        stmt = stmt.where(Competition.type == competition_type)

    out: dict[str, list[MatchImpact]] = {}
    for row in db.execute(stmt).all():
        (
            pid, match_id, match_date, comp_key, row_gender,
            team1_id, team2_id, team_id,
            runs, balls_faced, wickets, balls_bowled, conceded,
        ) = row
        opponent = team2_id if team_id == team1_id else team1_id
        out.setdefault(pid, []).append(
            MatchImpact(
                opposition_multiplier=opp.multiplier(opponent, match_date),
                match_id=match_id,
                match_date=match_date,
                competition_key=comp_key,
                gender=row_gender,
                team_id=team_id,
                opponent_team_id=opponent,
                runs_scored=runs or 0,
                balls_faced=balls_faced or 0,
                wickets_taken=wickets or 0,
                balls_bowled=balls_bowled or 0,
                runs_conceded=conceded or 0,
                impact=impact_mod.score(
                    runs_scored=runs or 0,
                    balls_faced=balls_faced or 0,
                    wickets_taken=wickets or 0,
                    balls_bowled=balls_bowled or 0,
                    runs_conceded=conceded or 0,
                    par=par.lookup(comp_key, row_gender),
                ),
            )
        )
    return out


@dataclass
class FormLeader:
    player_identifier: str
    verdict: FormVerdict

    @property
    def rank_score(self) -> float:
        """Evidence-weighted move in par units, used for ordering only.

        Two corrections to "sort by the percentage", both of which were visibly
        wrong on the board before they were made:

        1. **Weight by confidence.** The largest percentage swings belong to the
           players with the shortest baselines, because that is where the noise
           is. This is the same empirical-Bayes reasoning as the shrinkage
           inside `assess`, extended to sample size.

        2. **Measure the move in par units, not as a percentage.** A percentage
           is a ratio against the player's own baseline, so a player who was
           dreadful and is now merely below average posts a huge one. Sharvin
           Muniandy reached the in-form board at +97% while producing 0.70 par
           units -- below what an average appearance is worth -- because he had
           improved from 0.27. Meanwhile Virat Kohli at 2.94 par units scored a
           smaller percentage off a higher base. Ranking on `delta_absolute`
           (par units gained against their own norm) puts them in the order a
           selector would: it takes real cricket to gain a par unit, and no
           amount of arithmetic off a tiny base manufactures one.

        The displayed figure stays the percentage, because that is what the
        player actually produced; this only decides position. `recent_mean`
        travels with every row so the absolute standard is visible next to it.
        """
        return (self.verdict.delta_absolute or 0.0) * self.verdict.confidence


def scope_summary(
    db: Session,
    *,
    gender: str,
    competition_key: str | None = None,
    competition_type: str | None = None,
) -> "ScopeSummary":
    """Every player's form verdict and career aggregates for one scope, cached.

    Cached at THIS level rather than at `all_timelines`, and the distinction is
    the whole point. The timeline map is ~154,400 MatchImpact objects and 107 MB
    for men's internationals - too much to hold per scope. What its consumers
    actually want is one verdict and a few totals per player, which is ~5,400
    small objects. So the expensive map is built once, reduced, and dropped.

    Best XI and Scout both needed the same three things from it (the Index,
    career standing, and a form verdict each) and were each rebuilding it, which
    is what made them the two slowest endpoints in the API.
    """
    return cache.get_or_compute(
        db,
        ("form_scope_summary", gender, competition_key, competition_type),
        lambda: _build_scope_summary(
            db, gender=gender, competition_key=competition_key,
            competition_type=competition_type,
        ),
    )


@dataclass(slots=True)
class ScopeSummary:
    """Reduced per-player facts for one scope. Small enough to cache."""

    verdicts: dict[str, FormVerdict]
    # Mean par-unit value over the player's whole record in this scope, which is
    # the "good player" term selection weights against the Index's "playing well
    # now". Kept here so it comes from the same pass as the verdicts.
    career_mean: dict[str, float]
    balls: dict[str, tuple[int, int]]   # (faced, bowled), for role inference
    match_count: dict[str, int]


def _build_scope_summary(
    db: Session,
    *,
    gender: str,
    competition_key: str | None = None,
    competition_type: str | None = None,
) -> ScopeSummary:
    timelines = all_timelines(
        db, gender=gender, competition_key=competition_key,
        competition_type=competition_type,
    )
    verdicts: dict[str, FormVerdict] = {}
    career_mean: dict[str, float] = {}
    balls: dict[str, tuple[int, int]] = {}
    match_count: dict[str, int] = {}
    for pid, timeline in timelines.items():
        if not timeline:
            continue
        verdicts[pid] = assess(db, pid, timeline=timeline)
        career_mean[pid] = sum(m.value for m in timeline) / len(timeline)
        balls[pid] = (
            sum(m.balls_faced for m in timeline),
            sum(m.balls_bowled for m in timeline),
        )
        match_count[pid] = len(timeline)
    return ScopeSummary(
        verdicts=verdicts, career_mean=career_mean, balls=balls, match_count=match_count
    )


def leaderboard(
    db: Session,
    *,
    gender: str,
    competition_key: str | None = None,
    competition_type: str | None = None,
    recent_matches: int = config.DEFAULT_RECENT_MATCHES,
    baseline_days: int = config.DEFAULT_BASELINE_DAYS,
    active_within_days: int = config.LEADERBOARD_ACTIVE_WINDOW_DAYS,
    min_confidence: float = config.LEADERBOARD_MIN_CONFIDENCE,
) -> list[FormLeader]:
    """Form verdicts for every currently-active player in scope.

    Two filters keep the board honest rather than merely long:

    * `active_within_days` drops players who aren't playing. A retired player's
      last ten matches are still "recent" to a naive window, and a form table
      that opens with someone who stopped playing in 2019 is wrong in the way
      that matters most to a selector.
    * `min_confidence` drops verdicts resting on too little cricket. Without it
      the extremes of the board are exactly the players with the fewest matches,
      because that is where the noise is.

    Anchored to the newest match in the dataset, not today -- same reason as
    everywhere else: a stale archive must not silently retire everyone.
    """
    anchor = db.execute(select(func.max(Match.match_date_start))).scalar_one_or_none()
    cutoff: str | None = None
    if anchor:
        try:
            cutoff = (
                date.fromisoformat(anchor[:10]) - timedelta(days=active_within_days)
            ).isoformat()
        except ValueError:
            cutoff = None

    timelines = all_timelines(
        db,
        gender=gender,
        competition_key=competition_key,
        competition_type=competition_type,
    )

    leaders: list[FormLeader] = []
    for pid, timeline in timelines.items():
        if not timeline:
            continue
        newest = timeline[0].match_date
        if cutoff and (not newest or newest[:10] < cutoff):
            continue
        verdict = assess(
            db,
            pid,
            recent_matches=recent_matches,
            baseline_days=baseline_days,
            timeline=timeline,
        )
        if verdict.state == "insufficient_data" or verdict.confidence < min_confidence:
            continue
        leaders.append(FormLeader(player_identifier=pid, verdict=verdict))

    # Best-first, with identifier as a stable tiebreak so paging can't repeat or
    # skip a row when two players share a delta.
    leaders.sort(key=lambda l: l.player_identifier)
    leaders.sort(key=lambda l: l.rank_score, reverse=True)
    return leaders


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _trend(recent: list[MatchImpact]) -> str:
    """Direction within the recent window: older half versus newer half."""
    if len(recent) < 4:
        return "unknown"
    # `recent` is newest-first; split so `newer` really is the later cricket.
    half = len(recent) // 2
    newer = _mean([m.value for m in recent[:half]])
    older = _mean([m.value for m in recent[half:]])
    if newer is None or older is None:
        return "unknown"
    spread = max(abs(older), 1.0)
    change = (newer - older) / spread
    if change > 0.15:
        return "rising"
    if change < -0.15:
        return "falling"
    return "flat"


def _confidence(recent_n: int, baseline_n: int, low_baseline: bool) -> float:
    recent_factor = min(1.0, recent_n / config.CONFIDENCE_FULL_RECENT)
    baseline_factor = min(1.0, baseline_n / config.CONFIDENCE_FULL_BASELINE)
    value = recent_factor * baseline_factor
    if low_baseline:
        value = min(value, config.LOW_BASELINE_CONFIDENCE_CAP)
    return round(value, 3)


def _band(delta_ratio: float) -> str:
    for state, threshold in config.FORM_BANDS:
        if delta_ratio >= threshold:
            return state
    return "out_of_form"


def assess(
    db: Session,
    player_identifier: str,
    *,
    recent_matches: int = config.DEFAULT_RECENT_MATCHES,
    baseline_days: int = config.DEFAULT_BASELINE_DAYS,
    competition_key: str | None = None,
    competition_type: str | None = None,
    timeline: list[MatchImpact] | None = None,
) -> FormVerdict:
    """Classify a player's current form against their own recent baseline."""
    matches = timeline if timeline is not None else player_timeline(
        db,
        player_identifier,
        competition_key=competition_key,
        competition_type=competition_type,
    )

    recent_window_label = f"last {recent_matches} matches"
    baseline_window_label = f"preceding {baseline_days // 30} months"

    recent = matches[:recent_matches]
    if len(recent) < config.MIN_RECENT_MATCHES:
        return FormVerdict(
            state="insufficient_data",
            label=config.FORM_LABELS["insufficient_data"],
            recent_mean=None, baseline_mean=None,
            recent_matches=len(recent), baseline_matches=0,
            delta_ratio=None, delta_absolute=None,
            trend="unknown", confidence=0.0,
            explanation=(
                f"Only {len(recent)} match{'' if len(recent) == 1 else 'es'} on record "
                f"in this scope - too few to judge form against a baseline."
            ),
            recent_window_label=recent_window_label,
            baseline_window_label=baseline_window_label,
            timeline=[m.as_dict() for m in recent],
        )

    # The baseline runs back from the oldest match of the recent window, so the
    # two sets never overlap (config.BASELINE_EXCLUDES_RECENT).
    anchor = recent[-1].match_date
    cutoff: str | None = None
    if anchor:
        try:
            cutoff = (date.fromisoformat(anchor[:10]) - timedelta(days=baseline_days)).isoformat()
        except ValueError:
            cutoff = None

    older = matches[recent_matches:] if config.BASELINE_EXCLUDES_RECENT else matches
    baseline = [
        m for m in older
        if cutoff is None or (m.match_date and m.match_date[:10] >= cutoff)
    ]
    # A player whose whole career predates the baseline window would otherwise
    # get no baseline at all; fall back to everything before the recent window.
    if len(baseline) < config.MIN_BASELINE_MATCHES:
        baseline = older
        baseline_window_label = "career before this run"

    recent_mean = _mean([m.value for m in recent]) or 0.0
    trend = _trend(recent)

    if len(baseline) < config.MIN_BASELINE_MATCHES:
        return FormVerdict(
            state="insufficient_data",
            label=config.FORM_LABELS["insufficient_data"],
            recent_mean=recent_mean, baseline_mean=None,
            recent_matches=len(recent), baseline_matches=len(baseline),
            delta_ratio=None, delta_absolute=None,
            trend=trend, confidence=0.0,
            explanation=(
                f"{len(recent)} recent matches, but only {len(baseline)} earlier "
                "ones to compare against - not enough history for a baseline."
            ),
            recent_window_label=recent_window_label,
            baseline_window_label=baseline_window_label,
            timeline=[m.as_dict() for m in recent],
        )

    baseline_mean = _mean([m.value for m in baseline]) or 0.0

    # Shrink the recent mean towards the baseline in proportion to how little
    # cricket it rests on -- equivalent to crediting the player with
    # FORM_SHRINKAGE_MATCHES extra matches at their established level. Without
    # this, a three-innings purple patch and a thirty-match rise look alike.
    k = config.FORM_SHRINKAGE_MATCHES
    n = len(recent)
    adjusted_recent = (n * recent_mean + k * baseline_mean) / (n + k)
    delta_absolute = adjusted_recent - baseline_mean

    low_baseline = abs(baseline_mean) < config.MIN_MEANINGFUL_BASELINE
    delta_ratio: float | None
    if low_baseline:
        # Dividing by a near-zero baseline manufactures huge percentages from
        # trivial changes. Band on the absolute move instead, scaled against the
        # threshold below which we don't trust ratios at all.
        delta_ratio = delta_absolute / config.MIN_MEANINGFUL_BASELINE
    else:
        delta_ratio = delta_absolute / abs(baseline_mean)

    state = _band(delta_ratio)
    confidence = _confidence(len(recent), len(baseline), low_baseline)

    direction = "above" if delta_absolute >= 0 else "below"
    if low_baseline:
        detail = (
            f"{abs(delta_absolute):.2f} of a par performance per match {direction} "
            f"their {baseline_window_label} baseline"
        )
    else:
        detail = (
            f"{abs(delta_ratio) * 100:.0f}% {direction} their "
            f"{baseline_window_label} baseline"
        )
    explanation = (
        f"Performance over the {recent_window_label} is {detail} "
        f"({recent_mean:.2f} vs {baseline_mean:.2f} times a par performance, "
        f"from {len(recent)} recent and {len(baseline)} earlier matches)."
    )

    return FormVerdict(
        state=state,
        label=config.FORM_LABELS[state],
        recent_mean=recent_mean,
        baseline_mean=baseline_mean,
        recent_matches=len(recent),
        baseline_matches=len(baseline),
        delta_ratio=delta_ratio,
        delta_absolute=delta_absolute,
        trend=trend,
        confidence=confidence,
        explanation=explanation,
        recent_window_label=recent_window_label,
        baseline_window_label=baseline_window_label,
        timeline=[m.as_dict() for m in recent],
    )

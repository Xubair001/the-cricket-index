from datetime import date

from sqlalchemy import and_, case, func, or_, select, union_all
from sqlalchemy.orm import Session

from . import cache, schemas, flags
from .analytics import explorer as explorer_mod, periods
from .names import preferred_name
from .models import (
    Competition,
    Fixture,
    IccPlayerRanking,
    IccTeamRanking,
    Match,
    Player,
    PlayerMatchStat,
    Team,
)

RECENT_MATCHES_LIMIT = 10

# Rankings are confined to one competition type at a time (see _ranking_scope).
# Internationals are the default scope because that's what an unqualified
# cricket record means; franchise cricket is opt-in.
DEFAULT_RANKING_COMPETITION_TYPE = "international"


def valid_competition_keys(db: Session) -> set[str]:
    """The competition keys currently present in the database.

    Read from `competitions` rather than hardcoded in the routers so that
    ingesting a new league is a data change, not an API code change --  the
    same property the schema already gives competitions and seasons.
    """
    return {k for (k,) in db.execute(select(Competition.key).distinct()).all()}


def valid_competition_types(db: Session) -> set[str]:
    return {t for (t,) in db.execute(select(Competition.type).distinct()).all()}


def valid_team_types(db: Session) -> set[str]:
    return {t for (t,) in db.execute(select(Team.team_type).distinct()).all()}


# A player counts as active if they appeared within this window -- measured
# against the newest match in the dataset, NOT today. Anchoring to "now" would
# quietly reclassify every active player as inactive whenever the Cricsheet
# archive goes stale, turning a data-freshness problem into a wrong claim about
# thousands of careers.
ACTIVE_WINDOW_DAYS = 365


def dataset_latest_date(db: Session) -> str | None:
    return db.execute(select(func.max(Match.match_date_start))).scalar_one_or_none()


def dataset_span(db: Session) -> tuple[str | None, str | None]:
    """(earliest, latest) match date. Cached: it changes only on an ingest."""
    return cache.get_or_compute(
        db,
        ("dataset_span",),
        lambda: tuple(
            db.execute(
                select(func.min(Match.match_date_start), func.max(Match.match_date_start))
            ).one()
        ),
    )


def known_seasons(db: Session) -> set[str]:
    """Every season label the data actually holds.

    A season is the SOURCE's own label rather than a calendar year, so the valid
    set is a property of the data and belongs here rather than in a pattern - the
    same reason competition keys are checked against the `competitions` table.
    """
    return cache.get_or_compute(
        db,
        ("known_seasons",),
        lambda: {
            label
            for (label,) in db.execute(
                select(Match.season_label).where(Match.season_label.is_not(None)).distinct()
            ).all()
        },
    )


def player_status(
    player: Player, last_played: str | None, reference_date: str | None
) -> schemas.PlayerStatus:
    """Playing status, keeping sourced facts and observations distinct.

    'retired' requires a source -- Wikidata's work-period-end (P2032) or a date
    of death. It is never inferred from a gap in appearances: 'no matches since
    2023' covers retirement, injury, being dropped, and unrecorded domestic
    cricket alike, and this dataset cannot distinguish them. Those return
    'inactive' plus the last date actually observed, so the UI can state what
    is known instead of asserting what isn't.
    """
    if player.retirement_date:
        return schemas.PlayerStatus(
            state="retired",
            last_played=last_played,
            retired_on=player.retirement_date,
            deceased_on=player.date_of_death,
            source=player.bio_source,
        )
    if player.date_of_death:
        return schemas.PlayerStatus(
            state="retired",
            last_played=last_played,
            retired_on=None,
            deceased_on=player.date_of_death,
            source=player.bio_source,
        )

    state = "inactive"
    if last_played and reference_date:
        try:
            gap = date.fromisoformat(reference_date[:10]) - date.fromisoformat(last_played[:10])
            if gap.days <= ACTIVE_WINDOW_DAYS:
                state = "active"
        except ValueError:
            pass
    return schemas.PlayerStatus(
        state=state,
        last_played=last_played,
        retired_on=None,
        deceased_on=None,
        source=None,
    )


def _last_played_map(db: Session, gender: str | None = None) -> dict[str, str]:
    stmt = (
        select(PlayerMatchStat.player_identifier, func.max(Match.match_date_start))
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .where(PlayerMatchStat.player_identifier.is_not(None))
        .group_by(PlayerMatchStat.player_identifier)
    )
    if gender:
        stmt = stmt.where(Match.gender == gender)
    return {ident: last for ident, last in db.execute(stmt).all() if last}


def _build_player_country_map(
    db: Session, gender: str | None = None
) -> dict[str, tuple[str, str | None]]:
    """player_identifier -> (national side represented, ISO code or None).

    The flag beside a player means the same thing as the flag beside a team:
    the nation they turn out for. It is read from their appearances, which is
    Cricsheet-derived and exact, and deliberately *not* from
    `players.nationality` - that is a Wikidata citizenship claim answering a
    different question. A Guyanese passport does not make a West Indies player
    Guyanese in cricketing terms, and the dataset carries values like "United
    Kingdom" that name no cricketing side at all.

    Three cases the shape of the data forces:

    * **Franchise-only players** (1,247 of 9,442, mostly PSL) represent no
      nation here and get no entry. They render as the neutral mark, exactly
      as a franchise team does.
    * **Invitational appearances** are skipped, so the 146 players with more
      than one "international" side collapse to their real one - an ICC World
      XI cap does not make Dravid dual-national.
    * **Genuine switchers** remain (van der Merwe: South Africa then
      Netherlands; Garth: Australia then Ireland). The most recent side wins,
      tie-broken on appearances. That is a sourced fact - who they last played
      for - rather than a guess at allegiance, and the side's name travels with
      the code so the UI can say which on hover.
    """
    # Request-scoped memo, INSIDE the process-scoped one in `_player_country_map`.
    # Both earn their place: building this scans every international appearance
    # and groups ~5,400 players, and the batting and bowling aggregate helpers
    # each call it on every invocation - so a player profile rebuilt it once per
    # competition, and a two-player comparison twice that again. Measured cost of
    # not caching: 6.9s for /players/compare and 2.8s for a profile, against
    # 0.06s and 0.04s before flags were added.
    #
    # Session.info is exactly request-scoped (get_db opens and closes a Session
    # per request), so this tier cannot go stale within a response. It is kept
    # because a caller reaching the builder directly still wants it.
    #
    # Named `request_memo`, not `cache`: the module-level `cache` import is what
    # the outer tier uses, and shadowing it here would be a trap for the next
    # edit rather than a bug today.
    request_memo = db.info.setdefault("_player_country_map", {})
    if gender in request_memo:
        return request_memo[gender]

    stmt = (
        select(
            PlayerMatchStat.player_identifier,
            Team.name,
            Team.team_type,
            func.max(Match.match_date_start),
            func.count(),
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .join(Team, Team.team_id == PlayerMatchStat.team_id)
        .where(PlayerMatchStat.player_identifier.is_not(None))
        .where(Team.team_type == "international")
        .group_by(PlayerMatchStat.player_identifier, Team.team_id)
    )
    if gender:
        stmt = stmt.where(Match.gender == gender)

    best: dict[str, tuple[str, int, str, str | None]] = {}
    for identifier, name, team_type, last_played, appearances in db.execute(stmt).all():
        if not flags.is_national_side(name, team_type):
            continue
        candidate = (last_played or "", appearances, name, flags.country_code(name, team_type))
        current = best.get(identifier)
        if current is None or candidate[:2] > current[:2]:
            best[identifier] = candidate
    resolved = {ident: (name, code) for ident, (_, _, name, code) in best.items()}
    request_memo[gender] = resolved
    return resolved


def _player_country_map(
    db: Session, gender: str | None = None
) -> dict[str, tuple[str, str | None]]:
    """Cached view of the appearance-derived flag map.

    Every board that shows a player name needs this, and it is a GROUP BY over
    all 220k appearance rows regardless of how many rows the page returns - a
    25-row rankings page was paying roughly 200 ms for it. It changes only when
    matches are ingested, which `app.cache` detects.
    """
    return cache.get_or_compute(
        db, ("player_country_map", gender), lambda: _build_player_country_map(db, gender)
    )


def _team_record_map(db: Session) -> dict[int, tuple[int, int, int]]:
    """Cached view of every team's played/won/decided counts."""
    return cache.get_or_compute(db, ("team_record_map",), lambda: _build_team_record_map(db))


def _attach_country(
    rows: list[dict], countries: dict[str, tuple[str, str | None]], key: str = "player_identifier"
) -> list[dict]:
    """Stamp `country` / `country_code` onto already-built row dicts.

    Applied after the fact rather than joined into each aggregate query: the
    ranking helpers already group and sort in Python, and a join would have to
    be repeated identically in seven places with the invitational rule in each.
    """
    for row in rows:
        name, code = countries.get(row.get(key) or "", (None, None))
        row["country"] = name
        row["country_code"] = code
    return rows


def _safe_div(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator, 2)


def _team_ref(team: Team | None) -> schemas.TeamRef | None:
    if team is None:
        return None
    return schemas.TeamRef(
        team_id=team.team_id,
        name=team.name,
        country_code=flags.country_code(team.name, team.team_type),
    )


def _match_summary(m: Match, comp: Competition, team1: Team | None, team2: Team | None, winner: Team | None) -> schemas.MatchSummary:
    return schemas.MatchSummary(
        match_id=m.match_id,
        source=m.source,
        has_ball_by_ball=(m.source == "cricsheet"),
        competition_key=comp.key,
        competition_name=comp.display_name,
        gender=m.gender,
        match_type=m.match_type,
        season_label=m.season_label,
        venue=m.venue,
        city=m.city,
        match_date_start=m.match_date_start,
        team1=_team_ref(team1),
        team2=_team_ref(team2),
        winner=_team_ref(winner),
        outcome_result=m.outcome_result,
        win_by_runs=m.win_by_runs,
        win_by_wickets=m.win_by_wickets,
    )


def _competition_scoped(stmt, competition_key: str | None, competition_type: str | None):
    """Applies competition filtering, joining `competitions` at most once.

    `competition_key` and `competition_type` are two granularities of the same
    scope (one competition vs. every competition of a kind); a caller passing
    both gets the intersection, which is only ever used defensively.
    """
    if not competition_key and not competition_type:
        return stmt
    stmt = stmt.join(Competition, Competition.competition_id == Match.competition_id)
    if competition_key:
        stmt = stmt.where(Competition.key == competition_key)
    if competition_type:
        stmt = stmt.where(Competition.type == competition_type)
    return stmt


def _scope_anchor(
    db: Session,
    gender: str,
    competition_key: str | None,
    competition_type: str | None,
) -> str | None:
    """The newest match date within THIS scope, which is what a relative window
    like "last 12 months" is measured back from.

    `periods.py` establishes that a relative window is anchored to the newest
    match in the data rather than to today, because anchoring to now means the
    day the archive goes stale every current player silently drops out of the
    window and the product reports a data-freshness problem as a fact about
    cricket.

    The anchor is taken **within the scope** rather than over the whole
    database, which is the same call `selection.py` makes for its current-player
    pool and for the same reason: the PSL season ends in May while the newest
    match overall is an August Test, so a database-wide anchor would silently
    cost a PSL board three and a half months of its own season.
    """
    stmt = select(func.max(Match.match_date_start)).where(Match.gender == gender)
    stmt = _competition_scoped(stmt, competition_key, competition_type)
    return db.execute(stmt).scalar()


def _period_scoped(
    stmt,
    period: "periods.Period | None",
    anchor: str | None,
):
    """Applies a DATE-BOUNDED window to a statement.

    Count-bounded windows ("last 10 matches") are not expressible here: each
    player's tenth-most-recent match falls on a different date, so the cut is
    per player and happens in `_count_bounded_match_ids`. Callers branch on
    `period.is_count_bounded` rather than guessing.
    """
    if period is None:
        return stmt
    bounds = period.to_date_bounds(anchor)
    if bounds is None:  # count-bounded; handled by the caller
        return stmt
    start, end = bounds
    if start:
        stmt = stmt.where(Match.match_date_start >= start)
    if end:
        stmt = stmt.where(Match.match_date_start <= end)
    if period.season_label:
        stmt = stmt.where(Match.season_label == period.season_label)
    return stmt


def _count_bounded_window(
    gender: str,
    competition_key: str | None,
    competition_type: str | None,
    matches: int,
    team_id: int | None = None,
):
    """A joinable subquery of the (player, match) pairs inside each player's
    last N appearances.

    A count-bounded window has to be cut per player: each player's tenth-most
    recent match falls on a different date, so there is no single date range
    that expresses it. Filtering on match id alone is wrong for the same reason
    - a match inside one player's last ten is outside another's, so it would
    admit every player who happened to appear in somebody else's recent match.
    The pair is therefore the unit, and it is joined rather than collected in
    Python so the aggregate stays one query.

    A plain window function, not a SQLite extension: §24 requires the analytics
    layer to stay portable, and `ROW_NUMBER() OVER (PARTITION BY ...)` is
    standard SQL that Postgres runs unchanged.
    """
    ranked = (
        select(
            PlayerMatchStat.player_identifier.label("pid"),
            PlayerMatchStat.match_id.label("mid"),
            func.row_number()
            .over(
                partition_by=PlayerMatchStat.player_identifier,
                order_by=(
                    Match.match_date_start.desc(),
                    # Two matches can share a date (a double-header), so the id
                    # breaks the tie and keeps the cut deterministic across runs.
                    PlayerMatchStat.match_id.desc(),
                ),
            )
            .label("rn"),
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .where(Match.gender == gender)
        .where(PlayerMatchStat.player_identifier.is_not(None))
    )
    ranked = _competition_scoped(ranked, competition_key, competition_type)
    if team_id is not None:
        ranked = ranked.where(PlayerMatchStat.team_id == team_id)
    sub = ranked.subquery()
    return select(sub.c.pid, sub.c.mid).where(sub.c.rn <= matches).subquery()


def _build_batting_aggregate_rows(
    db: Session,
    gender: str,
    competition_key: str | None = None,
    competition_type: str | None = None,
    player_identifier: str | None = None,
    team_id: int | None = None,
    period: "periods.Period | None" = None,
) -> list[dict]:
    stmt = (
        select(
            # Grouped by identifier, not name: 78 names in this dataset map to
            # more than one real person (e.g. two "Iftikhar Ahmed"s in the PSL
            # squads alone), and grouping by name silently merged their careers
            # into a single ranking row. player_match_stats.player_identifier is
            # populated for every Cricsheet-sourced row.
            #
            # Both name forms are selected and resolved by names.preferred_name
            # in Python: which one to show depends on whether the scorecard name
            # is initials, which no SQL dialect expresses cleanly, and keeping
            # the rule in one module is what stops rankings and profiles
            # disagreeing about what a player is called. max() wrappers keep
            # these valid under GROUP BY -- the join is 1:1 on the group key.
            func.coalesce(
                func.max(Player.name), func.max(PlayerMatchStat.player_name)
            ).label("scorecard_name"),
            func.max(Player.display_name).label("wikidata_name"),
            PlayerMatchStat.player_identifier,
            func.count(func.distinct(PlayerMatchStat.match_id)).label("matches"),
            func.sum(PlayerMatchStat.runs_scored).label("runs"),
            func.sum(PlayerMatchStat.dismissals).label("dismissals"),
            func.sum(PlayerMatchStat.balls_faced).label("balls_faced"),
            func.sum(PlayerMatchStat.fours).label("fours"),
            func.sum(PlayerMatchStat.sixes).label("sixes"),
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .outerjoin(Player, Player.identifier == PlayerMatchStat.player_identifier)
        .where(Match.gender == gender)
        .group_by(PlayerMatchStat.player_identifier)
    )
    stmt = _competition_scoped(stmt, competition_key, competition_type)
    if player_identifier:
        stmt = stmt.where(PlayerMatchStat.player_identifier == player_identifier)
    if team_id is not None:
        stmt = stmt.where(PlayerMatchStat.team_id == team_id)
    # Two different mechanisms, because the two kinds of window are not the
    # same shape: a date range pushes straight into the WHERE clause, while
    # "last 10 matches" is a per-player cut and joins a ranked subquery.
    if period is not None:
        if period.is_count_bounded:
            window = _count_bounded_window(
                gender, competition_key, competition_type,
                period.matches or 0, team_id,
            )
            stmt = stmt.join(
                window,
                and_(
                    window.c.pid == PlayerMatchStat.player_identifier,
                    window.c.mid == PlayerMatchStat.match_id,
                ),
            )
        else:
            anchor = _scope_anchor(db, gender, competition_key, competition_type)
            stmt = _period_scoped(stmt, period, anchor)

    rows = db.execute(stmt).all()
    results = []
    for r in rows:
        runs = r.runs or 0
        dismissals = r.dismissals or 0
        balls_faced = r.balls_faced or 0
        results.append(
            {
                "player_name": preferred_name(r.scorecard_name, r.wikidata_name),
                "player_identifier": r.player_identifier,
                "matches": r.matches,
                "runs": runs,
                "dismissals": dismissals,
                "balls_faced": balls_faced,
                "fours": r.fours or 0,
                "sixes": r.sixes or 0,
                "average": _safe_div(runs, dismissals),
                "strike_rate": _safe_div(runs * 100, balls_faced),
            }
        )
    # Stamped here rather than in each caller so rankings, the dashboard's top
    # tens and a team page's leaders all carry the flag without three copies of
    # the rule. Note the country is the player's own nation even on a team page
    # scoped to a franchise -- Babar Azam is Pakistan on a Peshawar Zalmi list.
    return _attach_country(results, _player_country_map(db, gender))


def _build_bowling_aggregate_rows(
    db: Session,
    gender: str,
    competition_key: str | None = None,
    competition_type: str | None = None,
    player_identifier: str | None = None,
    team_id: int | None = None,
    period: "periods.Period | None" = None,
) -> list[dict]:
    stmt = (
        select(
            # Grouped by identifier, not name -- see _batting_aggregate_rows.
            func.coalesce(
                func.max(Player.name), func.max(PlayerMatchStat.player_name)
            ).label("scorecard_name"),
            func.max(Player.display_name).label("wikidata_name"),
            PlayerMatchStat.player_identifier,
            func.count(func.distinct(PlayerMatchStat.match_id)).label("matches"),
            func.sum(PlayerMatchStat.wickets_taken).label("wickets"),
            func.sum(PlayerMatchStat.runs_conceded).label("runs_conceded"),
            func.sum(PlayerMatchStat.balls_bowled).label("balls_bowled"),
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .outerjoin(Player, Player.identifier == PlayerMatchStat.player_identifier)
        .where(Match.gender == gender, PlayerMatchStat.balls_bowled > 0)
        .group_by(PlayerMatchStat.player_identifier)
    )
    stmt = _competition_scoped(stmt, competition_key, competition_type)
    if player_identifier:
        stmt = stmt.where(PlayerMatchStat.player_identifier == player_identifier)
    if team_id is not None:
        stmt = stmt.where(PlayerMatchStat.team_id == team_id)
    # Two different mechanisms, because the two kinds of window are not the
    # same shape: a date range pushes straight into the WHERE clause, while
    # "last 10 matches" is a per-player cut and joins a ranked subquery.
    if period is not None:
        if period.is_count_bounded:
            window = _count_bounded_window(
                gender, competition_key, competition_type,
                period.matches or 0, team_id,
            )
            stmt = stmt.join(
                window,
                and_(
                    window.c.pid == PlayerMatchStat.player_identifier,
                    window.c.mid == PlayerMatchStat.match_id,
                ),
            )
        else:
            anchor = _scope_anchor(db, gender, competition_key, competition_type)
            stmt = _period_scoped(stmt, period, anchor)

    rows = db.execute(stmt).all()
    results = []
    for r in rows:
        wickets = r.wickets or 0
        runs_conceded = r.runs_conceded or 0
        balls_bowled = r.balls_bowled or 0
        results.append(
            {
                "player_name": preferred_name(r.scorecard_name, r.wikidata_name),
                "player_identifier": r.player_identifier,
                "matches": r.matches,
                "wickets": wickets,
                "runs_conceded": runs_conceded,
                "balls_bowled": balls_bowled,
                "average": _safe_div(runs_conceded, wickets),
                "economy": _safe_div(runs_conceded * 6, balls_bowled),
            }
        )
    return _attach_country(results, _player_country_map(db, gender))


def _period_key(period: "periods.Period | None") -> str | None:
    """A stable cache key for a window.

    Built from the fields that change the rows rather than from the label, so
    two specs that mean the same window share one cache entry and a relabelled
    preset does not silently orphan its own entry.
    """
    if period is None:
        return None
    return "|".join(
        str(x) for x in (
            period.kind, period.matches, period.days,
            period.season_label, period.start, period.end,
        )
    )


def _cached_aggregate_rows(build, db, key_prefix, *args) -> list[dict]:
    """Cache a scope-wide aggregate, pass a single-player one straight through.

    These two GROUP BYs are the hot spot of the whole read path: a rankings page,
    an explorer board, the player directory, a team page and the dashboard all
    start here, and each one paid the full 220k-row aggregate to return 25 rows.

    Only the scope-wide form is cached. `player_identifier` is the last argument
    and, when set, the query is an indexed lookup of one player's rows - already
    fast, and caching it would key the store by 9,500 identifiers per scope for
    no gain.
    """
    gender, competition_key, competition_type, player_identifier, team_id, period = args
    if player_identifier is not None:
        return build(
            db, gender, competition_key, competition_type, player_identifier, team_id, period
        )
    # The period is part of the key, not of the value: "last 12 months" and
    # career are different aggregates over the same scope, and sharing one entry
    # between them would serve whichever was asked for first.
    period_key = _period_key(period)
    return cache.get_or_compute(
        db,
        (key_prefix, gender, competition_key, competition_type, team_id, period_key),
        lambda: build(db, gender, competition_key, competition_type, None, team_id, period),
    )


def _batting_aggregate_rows(
    db: Session,
    gender: str,
    competition_key: str | None = None,
    competition_type: str | None = None,
    player_identifier: str | None = None,
    team_id: int | None = None,
    period: "periods.Period | None" = None,
) -> list[dict]:
    return _cached_aggregate_rows(
        _build_batting_aggregate_rows, db, "batting_rows",
        gender, competition_key, competition_type, player_identifier, team_id, period,
    )


def _bowling_aggregate_rows(
    db: Session,
    gender: str,
    competition_key: str | None = None,
    competition_type: str | None = None,
    player_identifier: str | None = None,
    team_id: int | None = None,
    period: "periods.Period | None" = None,
) -> list[dict]:
    return _cached_aggregate_rows(
        _build_bowling_aggregate_rows, db, "bowling_rows",
        gender, competition_key, competition_type, player_identifier, team_id, period,
    )


def _ranking_scope(competition_key: str | None, competition_type: str | None) -> str | None:
    """Resolves the competition_type a ranking should be confined to.

    A ranking must never sum across competition types: a "runs" figure that
    blends Test/ODI/T20I with franchise-league cricket is a number no cricket
    source reports. So an unscoped request is not "everything" -- it falls back
    to internationals, and franchise cricket has to be asked for explicitly.
    A specific competition_key is already narrower than any type, so it wins.
    """
    if competition_key:
        return None
    return competition_type or DEFAULT_RANKING_COMPETITION_TYPE


def applied_period(
    db: Session,
    gender: str,
    competition_key: str | None,
    competition_type: str | None,
    period: "periods.Period | None",
) -> dict:
    """What window a scoped request actually used, for the response to state.

    Resolving the anchor needs the database and the scope, which is why this
    lives here rather than in `periods`: that module owns the vocabulary and the
    arithmetic, this owns "the newest match in THIS scope".
    """
    if period is None or period.kind == periods.CAREER:
        return periods.applied(None, None)
    anchor_date = _scope_anchor(
        db, gender, competition_key,
        _ranking_scope(competition_key, competition_type),
    )
    return periods.applied(period, anchor_date)


def get_batting_rankings(
    db: Session,
    gender: str,
    competition_key: str | None,
    min_matches: int,
    sort_by: str,
    limit: int,
    offset: int,
    competition_type: str | None = None,
    period: "periods.Period | None" = None,
) -> tuple[list[dict], int]:
    rows = _batting_aggregate_rows(
        db,
        gender,
        competition_key=competition_key,
        competition_type=_ranking_scope(competition_key, competition_type),
        period=period,
    )
    rows = [r for r in rows if r["matches"] >= min_matches]
    # Identifier as the final key so equal figures always land in the same
    # order -- otherwise paging through a ranking can repeat or skip a row.
    rows.sort(key=lambda r: (r["player_identifier"] or ""))
    rows.sort(key=lambda r: (r[sort_by] if r[sort_by] is not None else -1), reverse=True)
    total = len(rows)
    return rows[offset : offset + limit], total


def get_bowling_rankings(
    db: Session,
    gender: str,
    competition_key: str | None,
    min_matches: int,
    sort_by: str,
    limit: int,
    offset: int,
    competition_type: str | None = None,
    period: "periods.Period | None" = None,
) -> tuple[list[dict], int]:
    rows = _bowling_aggregate_rows(
        db,
        gender,
        competition_key=competition_key,
        competition_type=_ranking_scope(competition_key, competition_type),
        period=period,
    )
    rows = [r for r in rows if r["matches"] >= min_matches]
    reverse = sort_by not in ("average", "economy")  # lower is better for both
    rows.sort(key=lambda r: (r["player_identifier"] or ""))
    rows.sort(key=lambda r: (r[sort_by] if r[sort_by] is not None else (10**9)), reverse=reverse)
    total = len(rows)
    return rows[offset : offset + limit], total


def _top_by_plain_sum(db: Session, gender: str, discipline: str, limit: int) -> list[dict]:
    """Top N players by total runs / wickets, ordered and limited in SQL.

    The general ranking helpers build a dict for every player in the dataset
    (~6,000 rows) and sort in Python, because average and strike rate need a
    divide-with-guard that's awkward in SQLite. Runs and wickets need no such
    thing -- they're plain SUMs -- so the dashboard's "top 5" can be answered
    with ORDER BY ... LIMIT and never materialise the other 5,995 rows.
    """
    is_batting = discipline == "batting"
    total = func.sum(
        PlayerMatchStat.runs_scored if is_batting else PlayerMatchStat.wickets_taken
    ).label("total")

    # No join to `players` here. Resolving display names inside the aggregate
    # costs a lookup for every one of ~6,000 groups to label the 5 that survive
    # the LIMIT -- measured 245ms against 137ms. The names are fetched for the
    # handful of winners afterwards instead.
    columns = [
        func.max(PlayerMatchStat.player_name).label("fallback_name"),
        PlayerMatchStat.player_identifier,
        func.count(func.distinct(PlayerMatchStat.match_id)).label("matches"),
        total,
    ]
    if is_batting:
        columns += [
            func.sum(PlayerMatchStat.dismissals).label("dismissals"),
            func.sum(PlayerMatchStat.balls_faced).label("balls_faced"),
            func.sum(PlayerMatchStat.fours).label("fours"),
            func.sum(PlayerMatchStat.sixes).label("sixes"),
        ]
    else:
        columns += [
            func.sum(PlayerMatchStat.runs_conceded).label("runs_conceded"),
            func.sum(PlayerMatchStat.balls_bowled).label("balls_bowled"),
        ]

    stmt = (
        select(*columns)
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .where(Match.gender == gender)
        .group_by(PlayerMatchStat.player_identifier)
        # player_identifier breaks ties deterministically. Two bowlers on
        # exactly 335 wickets is not hypothetical -- it's the women's ODI list
        # today -- and an unspecified order there makes paginated results
        # unstable, repeating or skipping a row between pages.
        .order_by(total.desc(), PlayerMatchStat.player_identifier)
        .limit(limit)
    )
    # Same scope rule as the rankings endpoints: never blend competition types.
    stmt = _competition_scoped(stmt, None, DEFAULT_RANKING_COMPETITION_TYPE)
    if not is_batting:
        stmt = stmt.where(PlayerMatchStat.balls_bowled > 0)

    results = db.execute(stmt).all()
    names = {
        p.identifier: p.display_name or p.name
        for p in db.execute(
            select(Player).where(
                Player.identifier.in_([r.player_identifier for r in results])
            )
        ).scalars()
    }

    rows = []
    for r in results:
        display = names.get(r.player_identifier) or r.fallback_name
        if is_batting:
            rows.append({
                "player_name": display, "player_identifier": r.player_identifier,
                "matches": r.matches, "runs": r.total or 0,
                "dismissals": r.dismissals or 0, "balls_faced": r.balls_faced or 0,
                "fours": r.fours or 0, "sixes": r.sixes or 0,
                "average": _safe_div(r.total or 0, r.dismissals or 0),
                "strike_rate": _safe_div((r.total or 0) * 100, r.balls_faced or 0),
            })
        else:
            rows.append({
                "player_name": display, "player_identifier": r.player_identifier,
                "matches": r.matches, "wickets": r.total or 0,
                "runs_conceded": r.runs_conceded or 0, "balls_bowled": r.balls_bowled or 0,
                "average": _safe_div(r.runs_conceded or 0, r.total or 0),
                "economy": _safe_div((r.runs_conceded or 0) * 6, r.balls_bowled or 0),
            })
    return rows


def get_dashboard_stats(db: Session, gender: str) -> schemas.DashboardStats:
    total_matches = db.execute(
        select(func.count(Match.match_id)).where(Match.gender == gender)
    ).scalar_one()
    total_players = db.execute(
        select(func.count(Player.identifier)).where(Player.gender == gender)
    ).scalar_one()
    total_teams = db.execute(
        select(func.count(Team.team_id)).where(Team.gender == gender)
    ).scalar_one()

    by_competition = [
        schemas.CompetitionCount(competition_key=key, display_name=name, count=n)
        for key, name, n in db.execute(
            select(Competition.key, Competition.display_name, func.count(Match.match_id))
            .join(Match, Match.competition_id == Competition.competition_id)
            .where(Competition.gender == gender)
            .group_by(Competition.key, Competition.display_name)
        ).all()
    ]

    matches_by_season = [
        schemas.SeasonCount(season=s, count=n)
        for s, n in db.execute(
            select(Match.season_label, func.count(Match.match_id))
            .where(Match.gender == gender, Match.season_label.is_not(None))
            .group_by(Match.season_label)
            .order_by(Match.season_label)
        ).all()
    ]

    batting_rows = _top_by_plain_sum(db, gender, "batting", limit=5)
    bowling_rows = _top_by_plain_sum(db, gender, "bowling", limit=5)

    return schemas.DashboardStats(
        gender=gender,
        total_matches=total_matches,
        total_players=total_players,
        total_teams=total_teams,
        by_competition=by_competition,
        matches_by_season=matches_by_season,
        top_run_scorers=batting_rows,
        top_wicket_takers=bowling_rows,
    )


def _team_summary(db: Session, team: Team) -> schemas.TeamSummary:
    matches = db.execute(
        select(func.count(Match.match_id)).where(
            (Match.team1_id == team.team_id) | (Match.team2_id == team.team_id)
        )
    ).scalar_one()
    wins = db.execute(
        select(func.count(Match.match_id)).where(Match.winner_team_id == team.team_id)
    ).scalar_one()
    losses = db.execute(
        select(func.count(Match.match_id)).where(
            ((Match.team1_id == team.team_id) | (Match.team2_id == team.team_id))
            & Match.winner_team_id.is_not(None)
            & (Match.winner_team_id != team.team_id)
        )
    ).scalar_one()
    ties_or_nr = matches - wins - losses
    return schemas.TeamSummary(
        team_id=team.team_id,
        name=team.name,
        country_code=flags.country_code(team.name, team.team_type),
        gender=team.gender,
        team_type=team.team_type,
        matches=matches,
        wins=wins,
        losses=losses,
        ties_or_no_result=ties_or_nr,
        win_pct=_safe_div(wins * 100, matches),
    )


def _build_team_record_map(db: Session) -> dict[int, tuple[int, int, int]]:
    """team_id -> (played, wins, decided), for every team in one query.

    Each match contributes a row per side, so a team's appearances are just the
    rows carrying its id. Built as a single grouped scan because the per-team
    version ran three COUNTs for each team -- 330 queries to render one teams
    page, one of which had no index and scanned `matches` end to end each time.
    """
    appearances = union_all(
        select(
            Match.team1_id.label("tid"), Match.winner_team_id.label("winner")
        ).where(Match.team1_id.is_not(None)),
        select(
            Match.team2_id.label("tid"), Match.winner_team_id.label("winner")
        ).where(Match.team2_id.is_not(None)),
    ).subquery()

    rows = db.execute(
        select(
            appearances.c.tid,
            func.count().label("played"),
            func.sum(
                case((appearances.c.winner == appearances.c.tid, 1), else_=0)
            ).label("wins"),
            func.sum(
                case((appearances.c.winner.is_not(None), 1), else_=0)
            ).label("decided"),
        ).group_by(appearances.c.tid)
    ).all()
    return {r.tid: (r.played, r.wins or 0, r.decided or 0) for r in rows}


def get_teams_summary(
    db: Session,
    gender: str,
    team_type: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[schemas.TeamSummary], int]:
    """One page of team records, plus the total after filtering.

    The win/loss record has to be assembled before a side can be ranked or even
    included -- sides with no completed matches are dropped -- so the slice is
    taken after that work rather than in SQL. At ~119 sides that is immaterial,
    and it keeps `total` honest: it counts sides that actually appear, not rows
    in the table.
    """
    # Without a team_type filter this lists Karachi Kings next to Australia --
    # they're both male teams, but they aren't comparable entities. The caller
    # picks a side; the API doesn't blend them by default.
    stmt = select(Team).where(Team.gender == gender)
    if team_type:
        stmt = stmt.where(Team.team_type == team_type)
    teams = db.execute(stmt).scalars().all()

    records = _team_record_map(db)
    summaries = []
    for team in teams:
        played, wins, decided = records.get(team.team_id, (0, 0, 0))
        if not played:
            continue
        # losses = decided matches this team didn't win; the rest are ties or
        # no-results. Same definitions the per-team version used.
        summaries.append(
            schemas.TeamSummary(
                team_id=team.team_id,
                name=team.name,
                country_code=flags.country_code(team.name, team.team_type),
                gender=team.gender,
                team_type=team.team_type,
                matches=played,
                wins=wins,
                losses=decided - wins,
                ties_or_no_result=played - decided,
                win_pct=_safe_div(wins * 100, played),
            )
        )
    summaries.sort(key=lambda s: s.matches, reverse=True)
    total = len(summaries)
    if limit is not None:
        summaries = summaries[offset : offset + limit]
    return summaries, total


def get_team_detail(db: Session, team_id: int) -> schemas.TeamDetail | None:
    team = db.execute(select(Team).where(Team.team_id == team_id)).scalar_one_or_none()
    if team is None:
        return None

    summary = _team_summary(db, team)

    # Scoped to this team's matches, not merely to players who have appeared
    # for it. Filtering gender-wide career totals down to the team's squad
    # meant a franchise page credited a player with every run of their
    # international career too -- e.g. Karachi Kings showing Babar Azam's Test
    # runs. team_id lives on player_match_stats, so the aggregate can do it.
    batting_rows = _batting_aggregate_rows(db, team.gender, team_id=team_id)
    batting_rows.sort(key=lambda r: r["runs"], reverse=True)

    bowling_rows = _bowling_aggregate_rows(db, team.gender, team_id=team_id)
    bowling_rows.sort(key=lambda r: r["wickets"], reverse=True)

    recent = db.execute(
        select(Match)
        .where((Match.team1_id == team_id) | (Match.team2_id == team_id))
        .order_by(Match.match_date_start.desc())
        .limit(RECENT_MATCHES_LIMIT)
    ).scalars().all()
    recent_matches = _hydrate_match_summaries(db, list(recent))

    return schemas.TeamDetail(
        **summary.model_dump(),
        top_run_scorers=[schemas.BattingRankingRow(**r) for r in batting_rows[:10]],
        top_wicket_takers=[schemas.BowlingRankingRow(**r) for r in bowling_rows[:10]],
        recent_matches=recent_matches,
    )


def get_head_to_head(db: Session, team_a_id: int, team_b_id: int) -> schemas.HeadToHead | None:
    team_a = db.execute(select(Team).where(Team.team_id == team_a_id)).scalar_one_or_none()
    team_b = db.execute(select(Team).where(Team.team_id == team_b_id)).scalar_one_or_none()
    if team_a is None or team_b is None:
        return None

    matches = db.execute(
        select(Match).where(
            ((Match.team1_id == team_a_id) & (Match.team2_id == team_b_id))
            | ((Match.team1_id == team_b_id) & (Match.team2_id == team_a_id))
        )
    ).scalars().all()
    a_wins = sum(1 for m in matches if m.winner_team_id == team_a_id)
    b_wins = sum(1 for m in matches if m.winner_team_id == team_b_id)
    return schemas.HeadToHead(
        team_a=_team_ref(team_a),
        team_b=_team_ref(team_b),
        matches=len(matches),
        team_a_wins=a_wins,
        team_b_wins=b_wins,
        ties_or_no_result=len(matches) - a_wins - b_wins,
    )


def search_players(
    db: Session, gender: str, search: str | None, limit: int, offset: int
) -> tuple[list[schemas.PlayerSummary], int]:
    stmt = (
        select(
            Player.identifier,
            Player.name,
            Player.gender,
            func.count(func.distinct(PlayerMatchStat.match_id)).label("matches"),
        )
        .outerjoin(PlayerMatchStat, PlayerMatchStat.player_identifier == Player.identifier)
        .where(Player.gender == gender)
        .group_by(Player.identifier, Player.name, Player.gender)
        .having(func.count(func.distinct(PlayerMatchStat.match_id)) > 0)
    )
    if search:
        # Both name forms are searched. Matching only the scorecard name means a
        # player cannot be found by the name the product itself displays --
        # "Joe Root" returned nothing while "JE Root" worked.
        stmt = stmt.where(
            or_(
                Player.name.ilike(f"%{search}%"),
                Player.display_name.ilike(f"%{search}%"),
            )
        )

    all_rows = db.execute(stmt).all()
    all_rows = sorted(all_rows, key=lambda r: r.matches, reverse=True)
    total = len(all_rows)
    page = all_rows[offset : offset + limit]

    # Status only for the page being returned -- the two lookups it needs are
    # cheap, but building them for all ~9,400 players to serve 25 would not be.
    reference = dataset_latest_date(db)
    last_played = _last_played_map(db, gender)
    countries = _player_country_map(db, gender)
    page_players = {
        p.identifier: p
        for p in db.execute(
            select(Player).where(Player.identifier.in_([r.identifier for r in page]))
        ).scalars()
    }

    items = [
        schemas.PlayerSummary(
            identifier=r.identifier,
            name=preferred_name(
                r.name,
                page_players[r.identifier].display_name
                if r.identifier in page_players
                else None,
            ),
            scorecard_name=r.name,
            gender=r.gender,
            matches=r.matches,
            country=countries.get(r.identifier, (None, None))[0],
            country_code=countries.get(r.identifier, (None, None))[1],
            status=(
                player_status(page_players[r.identifier], last_played.get(r.identifier), reference)
                if r.identifier in page_players
                else None
            ),
        )
        for r in page
    ]
    return items, total


def _player_competition_totals(
    db: Session,
    identifier: str,
    gender: str,
    period: "periods.Period | None" = None,
) -> dict[str, dict]:
    """Every competition's figures for ONE player, in two queries rather than 2N.

    The profile used to loop the competitions and call the two aggregate builders
    per competition: seven competitions, fourteen queries, on top of the eight
    the rest of the page needs. On a local SQLite file that is 26 ms and invisible.
    Against a managed Postgres it is fourteen network round trips, and at the
    617 ms median measured from here that alone was 8.6 of the profile's 14.7
    seconds - the same N+1 lesson CLAUDE.md records for Best XI and Scout,
    surfacing again the moment the database stopped being a local file.

    Grouped by competition key in SQL instead. Two round trips, any number of
    competitions.
    """
    def rows(discipline: str) -> dict[str, dict]:
        if discipline == "batting":
            columns = [
                func.count(func.distinct(PlayerMatchStat.match_id)).label("matches"),
                func.sum(PlayerMatchStat.runs_scored).label("runs"),
                func.sum(PlayerMatchStat.dismissals).label("dismissals"),
                func.sum(PlayerMatchStat.balls_faced).label("balls_faced"),
                func.sum(PlayerMatchStat.fours).label("fours"),
                func.sum(PlayerMatchStat.sixes).label("sixes"),
            ]
        else:
            columns = [
                func.count(func.distinct(PlayerMatchStat.match_id)).label("matches"),
                func.sum(PlayerMatchStat.wickets_taken).label("wickets"),
                func.sum(PlayerMatchStat.runs_conceded).label("runs_conceded"),
                func.sum(PlayerMatchStat.balls_bowled).label("balls_bowled"),
            ]
        stmt = (
            select(Competition.key, Competition.display_name, *columns)
            .join(Match, Match.match_id == PlayerMatchStat.match_id)
            .join(Competition, Competition.competition_id == Match.competition_id)
            .where(
                PlayerMatchStat.player_identifier == identifier,
                Match.gender == gender,
            )
            # `display_name` is grouped with the key it depends on: Postgres
            # requires every non-aggregate column in the GROUP BY.
            .group_by(Competition.key, Competition.display_name)
        )
        if period is not None:
            if period.is_count_bounded:
                window = _count_bounded_window(
                    gender, None, None, period.matches or 0, None
                )
                stmt = stmt.join(
                    window,
                    and_(
                        window.c.pid == PlayerMatchStat.player_identifier,
                        window.c.mid == PlayerMatchStat.match_id,
                    ),
                )
            else:
                stmt = _period_scoped(
                    stmt, period, _scope_anchor(db, gender, None, None)
                )
        out: dict[str, dict] = {}
        for row in db.execute(stmt).all():
            data = dict(row._mapping)
            out[data.pop("key")] = data
        return out

    batting = rows("batting")
    bowling = rows("bowling")
    merged: dict[str, dict] = {}
    for key in set(batting) | set(bowling):
        b = batting.get(key, {})
        bo = bowling.get(key, {})
        merged[key] = {
            "display_name": b.get("display_name") or bo.get("display_name") or key,
            "matches": max(b.get("matches") or 0, bo.get("matches") or 0),
            "runs": b.get("runs") or 0,
            "dismissals": b.get("dismissals") or 0,
            "balls_faced": b.get("balls_faced") or 0,
            "fours": b.get("fours") or 0,
            "sixes": b.get("sixes") or 0,
            "wickets": bo.get("wickets") or 0,
            "runs_conceded": bo.get("runs_conceded") or 0,
            "balls_bowled": bo.get("balls_bowled") or 0,
        }
    return merged


def get_player_detail(
    db: Session, identifier: str, period: "periods.Period | None" = None
) -> schemas.PlayerDetail | None:
    player = db.execute(select(Player).where(Player.identifier == identifier)).scalar_one_or_none()
    if player is None:
        return None

    team_ids = [
        tid
        for (tid,) in db.execute(
            select(PlayerMatchStat.team_id)
            .where(PlayerMatchStat.player_identifier == identifier)
            .distinct()
        ).all()
    ]
    teams = db.execute(select(Team).where(Team.team_id.in_(team_ids))).scalars().all()

    by_competition = []
    competitions = db.execute(
        select(Competition).where(Competition.gender == player.gender)
    ).scalars().all()
    # Two queries for every competition, not two per competition. See
    # `_player_competition_totals`: on a local file the loop was invisible, and
    # against a remote database it was 14 of this page's 22 round trips.
    totals = _player_competition_totals(db, identifier, player.gender, period)
    for comp in competitions:
        row = totals.get(comp.key)
        if row is None:
            continue
        by_competition.append(
            schemas.PlayerFormatStats(
                competition_key=comp.key,
                display_name=comp.display_name,
                matches=row["matches"],
                runs=row["runs"],
                dismissals=row["dismissals"],
                balls_faced=row["balls_faced"],
                fours=row["fours"],
                sixes=row["sixes"],
                batting_average=_safe_div(row["runs"], row["dismissals"]),
                strike_rate=_safe_div(row["runs"] * 100.0, row["balls_faced"]),
                wickets=row["wickets"],
                runs_conceded=row["runs_conceded"],
                balls_bowled=row["balls_bowled"],
                bowling_average=_safe_div(row["runs_conceded"], row["wickets"]),
                economy=_safe_div(row["runs_conceded"] * 6.0, row["balls_bowled"]),
            )
        )

    recent = db.execute(
        select(Match)
        .join(PlayerMatchStat, PlayerMatchStat.match_id == Match.match_id)
        .where(PlayerMatchStat.player_identifier == identifier)
        .order_by(Match.match_date_start.desc())
        .limit(RECENT_MATCHES_LIMIT)
    ).scalars().all()
    recent_matches = _hydrate_match_summaries(db, list(recent))

    country, country_code = _player_country_map(db, player.gender).get(
        player.identifier, (None, None)
    )
    return schemas.PlayerDetail(
        identifier=player.identifier,
        name=player.display_name or player.name,
        scorecard_name=player.name,
        gender=player.gender,
        country=country,
        country_code=country_code,
        teams=[_team_ref(t) for t in teams],
        bio=schemas.PlayerBio(
            date_of_birth=player.date_of_birth,
            birth_place=player.birth_place,
            nationality=player.nationality,
            bio_source=player.bio_source,
            image_url=player.image_url,
        ),
        status=player_status(
            player,
            db.execute(
                select(func.max(Match.match_date_start))
                .join(PlayerMatchStat, PlayerMatchStat.match_id == Match.match_id)
                .where(PlayerMatchStat.player_identifier == identifier)
            ).scalar_one_or_none(),
            dataset_latest_date(db),
        ),
        icc_rankings=current_icc_ranks_for_player(db, identifier),
        by_competition=by_competition,
        recent_matches=recent_matches,
    )


def _fixture_row(f: Fixture) -> schemas.FixtureRow:
    return schemas.FixtureRow(
        icc_match_id=f.icc_match_id,
        series_name=f.series_name,
        tour_name=f.tour_name,
        match_type=f.match_type,
        match_number=f.match_number,
        gender=f.gender,
        match_status=f.match_status,
        is_upcoming=bool(f.is_upcoming),
        is_live=bool(f.is_live),
        start_date=f.start_date,
        end_date=f.end_date,
        start_time_gmt=f.start_time_gmt,
        venue=f.venue,
        country=f.country,
        team_a_name=f.team_a_name,
        team_a_short=f.team_a_short,
        team_a_id=f.team_a_id,
        team_b_name=f.team_b_name,
        team_b_short=f.team_b_short,
        team_b_id=f.team_b_id,
        match_result=f.match_result,
        winning_team_name=f.winning_team_name,
        toss_won_by=f.toss_won_by,
        toss_elected_to=f.toss_elected_to,
    )


def list_fixtures(
    db: Session,
    gender: str | None,
    window: str,
    match_type: str | None,
    limit: int,
    offset: int,
) -> tuple[list[schemas.FixtureRow], int]:
    """Fixtures in one of three windows: upcoming, live, or results.

    Ordering differs by window on purpose -- upcoming reads soonest-first,
    results read most-recent-first. A single ordering would bury whichever half
    the reader came for.
    """
    stmt = select(Fixture)
    if gender:
        stmt = stmt.where(Fixture.gender == gender)
    if match_type:
        stmt = stmt.where(Fixture.match_type == match_type)

    # `icc_match_id` closes every ordering below. Dozens of fixtures share a
    # start date, so date alone leaves their order to the engine - which means
    # paging can repeat or skip a row, and it made a SQLite result and a Postgres
    # result of the same query disagree. Same discipline as the ranking
    # aggregates, which have used a final key from the start.
    if window == "upcoming":
        stmt = stmt.where(Fixture.is_upcoming == 1).order_by(
            Fixture.start_date.asc(),
            Fixture.start_time_gmt.asc(),
            Fixture.icc_match_id.asc(),
        )
    elif window == "live":
        stmt = stmt.where(Fixture.is_live == 1).order_by(
            Fixture.start_date.asc(), Fixture.icc_match_id.asc()
        )
    else:  # results
        # Date-bounded, not just `is_upcoming == 0`. A cancelled *future*
        # fixture carries is_upcoming=0 and match_result="Match Cancelled", so
        # without this it sorts to the top of "results" and the most recent
        # result on the page is a match two months away that never happened.
        stmt = stmt.where(
            Fixture.is_upcoming == 0,
            Fixture.match_result.is_not(None),
            Fixture.start_date <= date.today().isoformat(),
        ).order_by(Fixture.start_date.desc(), Fixture.icc_match_id.desc())

    rows = db.execute(stmt).scalars().all()
    total = len(rows)
    return [_fixture_row(f) for f in rows[offset : offset + limit]], total


def fixture_match_types(db: Session, gender: str | None = None) -> list[str]:
    stmt = select(Fixture.match_type).distinct().where(Fixture.match_type.is_not(None))
    if gender:
        stmt = stmt.where(Fixture.gender == gender)
    return sorted(t for (t,) in db.execute(stmt).all())


def fixtures_last_synced(db: Session) -> str | None:
    return db.execute(select(func.max(Fixture.fetched_at))).scalar_one_or_none()


def _latest_rank_dates(db: Session, model) -> dict[str, str]:
    """Newest published rank_date per rank_type.

    Snapshots accumulate (that history is the point), so every read of "the
    current table" has to pin the latest date rather than mixing publications.
    """
    return {
        rank_type: rank_date
        for rank_type, rank_date in db.execute(
            select(model.rank_type, func.max(model.rank_date)).group_by(model.rank_type)
        ).all()
    }


def current_icc_ranks_for_player(db: Session, identifier: str) -> list[schemas.IccRankEntry]:
    latest = _latest_rank_dates(db, IccPlayerRanking)
    if not latest:
        return []
    rows = db.execute(
        select(IccPlayerRanking).where(IccPlayerRanking.player_identifier == identifier)
    ).scalars().all()
    entries = [
        schemas.IccRankEntry(
            rank_type=r.rank_type,
            rank_date=r.rank_date,
            position=r.position,
            points=r.points,
            career_best=r.career_best,
        )
        for r in rows
        if latest.get(r.rank_type) == r.rank_date
    ]
    entries.sort(key=lambda e: (e.rank_type, e.position))
    return entries


def icc_player_rank_types(db: Session) -> list[str]:
    return sorted(t for (t,) in db.execute(select(IccPlayerRanking.rank_type).distinct()))


def icc_team_rank_types(db: Session) -> list[str]:
    return sorted(t for (t,) in db.execute(select(IccTeamRanking.rank_type).distinct()))


def get_icc_player_ranking(
    db: Session, rank_type: str, limit: int | None = None, offset: int = 0
) -> schemas.IccRankingTable | None:
    rank_date = db.execute(
        select(func.max(IccPlayerRanking.rank_date)).where(
            IccPlayerRanking.rank_type == rank_type
        )
    ).scalar_one_or_none()
    if not rank_date:
        return None
    scoped = (
        IccPlayerRanking.rank_type == rank_type,
        IccPlayerRanking.rank_date == rank_date,
    )
    total = db.execute(
        select(func.count()).select_from(IccPlayerRanking).where(*scoped)
    ).scalar_one()
    stmt = select(IccPlayerRanking).where(*scoped).order_by(IccPlayerRanking.position)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    rows = db.execute(stmt).scalars().all()
    return schemas.IccRankingTable(
        rank_type=rank_type,
        rank_date=rank_date,
        fetched_at=rows[0].fetched_at if rows else None,
        total=total,
        limit=limit if limit is not None else total,
        offset=offset,
        rows=[
            schemas.IccRankingRow(
                position=r.position,
                player_name=r.player_name,
                country=r.country,
                country_code=flags.country_code(r.country, "international"),
                points=r.points,
                career_best=r.career_best,
                player_identifier=r.player_identifier,
            )
            for r in rows
        ],
    )


def get_icc_team_ranking(
    db: Session, rank_type: str, limit: int | None = None, offset: int = 0
) -> schemas.IccTeamRankingTable | None:
    rank_date = db.execute(
        select(func.max(IccTeamRanking.rank_date)).where(IccTeamRanking.rank_type == rank_type)
    ).scalar_one_or_none()
    if not rank_date:
        return None
    scoped = (
        IccTeamRanking.rank_type == rank_type,
        IccTeamRanking.rank_date == rank_date,
    )
    total = db.execute(
        select(func.count()).select_from(IccTeamRanking).where(*scoped)
    ).scalar_one()
    stmt = select(IccTeamRanking).where(*scoped).order_by(IccTeamRanking.position)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    rows = db.execute(stmt).scalars().all()
    return schemas.IccTeamRankingTable(
        rank_type=rank_type,
        rank_date=rank_date,
        fetched_at=rows[0].fetched_at if rows else None,
        total=total,
        limit=limit if limit is not None else total,
        offset=offset,
        rows=[
            schemas.IccTeamRankingRow(
                position=r.position, team_name=r.team_name, points=r.points, team_id=r.team_id
            )
            for r in rows
        ],
    )


# Metric definitions for a head-to-head:
#   (key, label, lower_is_better, format, gate_field, gate_minimum)
#
# `lower_is_better` matters -- a bowling average of 22 beats one of 30, so a
# naive "bigger wins" comparison awards the wrong side on two of these.
#
# The gate matters just as much. Rate metrics are meaningless at low volume:
# Kohli's Test economy of 2.88 comes off 175 balls against Root's 3.37 off
# 6,332, and calling that a win for Kohli would be true arithmetic and a false
# claim about cricket. Below the gate the numbers are still shown -- both are
# real -- but no winner is declared.
COMPARISON_METRICS = [
    ("matches", "Matches", False, "int", None, 0),
    ("runs", "Runs", False, "int", None, 0),
    ("batting_average", "Batting Average", False, "float", "dismissals", 10),
    ("strike_rate", "Strike Rate", False, "float", "balls_faced", 200),
    ("fours", "Fours", False, "int", None, 0),
    ("sixes", "Sixes", False, "int", None, 0),
    ("wickets", "Wickets", False, "int", None, 0),
    ("bowling_average", "Bowling Average", True, "float", "balls_bowled", 600),
    ("economy", "Economy", True, "float", "balls_bowled", 600),
    ("balls_bowled", "Balls Bowled", False, "int", None, 0),
]


def _scoped_totals(
    db: Session, identifier: str, gender: str, competition_key: str | None,
    competition_type: str | None, period: "periods.Period | None" = None,
) -> schemas.PlayerFormatStats | None:
    batting = _batting_aggregate_rows(
        db, gender, competition_key=competition_key,
        competition_type=competition_type, player_identifier=identifier,
        period=period,
    )
    bowling = _bowling_aggregate_rows(
        db, gender, competition_key=competition_key,
        competition_type=competition_type, player_identifier=identifier,
        period=period,
    )
    if not batting and not bowling:
        return None
    b = batting[0] if batting else None
    bo = bowling[0] if bowling else None
    return schemas.PlayerFormatStats(
        competition_key=competition_key or (competition_type or "all"),
        display_name="",
        matches=(b or bo)["matches"],
        runs=b["runs"] if b else 0,
        dismissals=b["dismissals"] if b else 0,
        balls_faced=b["balls_faced"] if b else 0,
        fours=b["fours"] if b else 0,
        sixes=b["sixes"] if b else 0,
        batting_average=b["average"] if b else None,
        strike_rate=b["strike_rate"] if b else None,
        wickets=bo["wickets"] if bo else 0,
        runs_conceded=bo["runs_conceded"] if bo else 0,
        balls_bowled=bo["balls_bowled"] if bo else 0,
        bowling_average=bo["average"] if bo else None,
        economy=bo["economy"] if bo else None,
    )


def _season_series(
    db: Session, identifier: str, gender: str, competition_key: str | None,
    competition_type: str | None,
) -> list[tuple[str, int, int]]:
    """(season, runs, wickets) per season within scope, chronological."""
    stmt = (
        select(
            Match.season_label,
            func.sum(PlayerMatchStat.runs_scored),
            func.sum(PlayerMatchStat.wickets_taken),
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .where(
            PlayerMatchStat.player_identifier == identifier,
            Match.gender == gender,
            Match.season_label.is_not(None),
        )
        .group_by(Match.season_label)
    )
    stmt = _competition_scoped(stmt, competition_key, competition_type)
    rows = db.execute(stmt).all()
    return sorted(((s, r or 0, w or 0) for s, r, w in rows), key=lambda t: t[0])


def _career_span(db: Session, identifier: str) -> list[str | None]:
    row = db.execute(
        select(func.min(Match.match_date_start), func.max(Match.match_date_start))
        .join(PlayerMatchStat, PlayerMatchStat.match_id == Match.match_id)
        .where(PlayerMatchStat.player_identifier == identifier)
    ).one()
    return [row[0][:4] if row[0] else None, row[1][:4] if row[1] else None]


def _comparison_side(
    db: Session, player: Player, competition_key: str | None, competition_type: str | None,
    reference: str | None, period: "periods.Period | None" = None,
) -> schemas.ComparisonSide:
    identifier = player.identifier
    team_ids = [
        tid for (tid,) in db.execute(
            select(PlayerMatchStat.team_id)
            .where(PlayerMatchStat.player_identifier == identifier)
            .distinct()
        ).all()
    ]
    teams = db.execute(select(Team).where(Team.team_id.in_(team_ids))).scalars().all()
    last_played = db.execute(
        select(func.max(Match.match_date_start))
        .join(PlayerMatchStat, PlayerMatchStat.match_id == Match.match_id)
        .where(PlayerMatchStat.player_identifier == identifier)
    ).scalar_one_or_none()

    by_competition = []
    for comp in db.execute(
        select(Competition).where(Competition.gender == player.gender)
    ).scalars().all():
        totals = _scoped_totals(db, identifier, player.gender, comp.key, None, period)
        if totals is None:
            continue
        totals.competition_key = comp.key
        totals.display_name = comp.display_name
        by_competition.append(totals)

    country, country_code = _player_country_map(db, player.gender).get(
        identifier, (None, None)
    )
    return schemas.ComparisonSide(
        identifier=identifier,
        name=player.display_name or player.name,
        scorecard_name=player.name,
        country=country,
        country_code=country_code,
        status=player_status(player, last_played, reference),
        teams=[_team_ref(t) for t in teams],
        bio=schemas.PlayerBio(
            date_of_birth=player.date_of_birth,
            birth_place=player.birth_place,
            nationality=player.nationality,
            bio_source=player.bio_source,
            image_url=player.image_url,
        ),
        totals=_scoped_totals(
            db, identifier, player.gender, competition_key, competition_type, period
        ),
        by_competition=by_competition,
        icc_rankings=current_icc_ranks_for_player(db, identifier),
        career_span=_career_span(db, identifier),
    )


# 2 to 5, per §13. The upper bound is a readability limit rather than a
# computational one: the comparison is a table with one column per player, and
# past five the columns are too narrow to read on any realistic screen.
MAX_COMPARISON_PLAYERS = 5


def get_player_comparison(
    db: Session, identifiers: list[str],
    competition_key: str | None, competition_type: str | None,
    period: "periods.Period | None" = None,
) -> schemas.PlayerComparison | str:
    """Compare 2 to 5 players. Returns an error string if the set is invalid.

    §13 asks for 2-5 and §25 names the extension explicitly. The shape is a list
    of sides with a list of values per metric, rather than the `a`/`b` pair it
    replaced: a two-player special case cannot express "who is best of five"
    without the client re-deriving it, and `better: 'a' | 'b'` has nowhere to put
    a third player.

    Three rules are enforced here rather than left to the caller:
      * same gender - men's and women's cricket share no identity anywhere else
        in this app, and a cross-gender "who scored more" is not a comparison
        anyone makes;
      * one competition scope - an unscoped career total would sum international
        and franchise runs, the exact blend Phase 2 removed;
      * no duplicates - the same player twice is a column of itself, and
        silently de-duplicating would return fewer players than were asked for
        without saying so.
    """
    if len(identifiers) < 2:
        return "need at least two players to compare"
    if len(identifiers) > MAX_COMPARISON_PLAYERS:
        return (
            f"cannot compare more than {MAX_COMPARISON_PLAYERS} players at once "
            f"({len(identifiers)} requested)"
        )
    seen: set[str] = set()
    for identifier in identifiers:
        if identifier in seen:
            return f"player '{identifier}' is listed twice"
        seen.add(identifier)

    players: list[Player] = []
    for identifier in identifiers:
        player = db.execute(
            select(Player).where(Player.identifier == identifier)
        ).scalar_one_or_none()
        if player is None:
            return f"player '{identifier}' not found"
        players.append(player)

    genders = {p.gender for p in players}
    if len(genders) > 1:
        detail = ", ".join(f"'{p.name}' is {p.gender}" for p in players)
        return f"cannot compare across genders ({detail})"
    gender = players[0].gender

    if not competition_key and not competition_type:
        competition_type = DEFAULT_RANKING_COMPETITION_TYPE
    if competition_key:
        competition_type = None

    reference = dataset_latest_date(db)
    sides = [
        _comparison_side(db, p, competition_key, competition_type, reference, period)
        for p in players
    ]

    metrics = []
    for key, label, lower_better, fmt, gate_field, gate_min in COMPARISON_METRICS:
        values = [
            getattr(side.totals, key, None) if side.totals else None for side in sides
        ]
        # A rate needs a sample before it means anything, and the gate applies
        # per player rather than to the set: one player short of the threshold
        # makes THEIR figure incomparable, not the whole row. Their value is
        # still returned - it is a fact about them - but it cannot win the row.
        qualified = [True] * len(sides)
        if gate_field:
            for i, side in enumerate(sides):
                have = getattr(side.totals, gate_field, 0) if side.totals else 0
                qualified[i] = (have or 0) >= gate_min

        contenders = [
            (i, v) for i, v in enumerate(values) if v is not None and qualified[i]
        ]
        best_index = None
        if len(contenders) > 1:
            picker = min if lower_better else max
            best_value = picker(v for _, v in contenders)
            leaders = [i for i, v in contenders if v == best_value]
            # A tie has no winner. Highlighting one of two equal figures would
            # assert a difference that is not there.
            if len(leaders) == 1:
                best_index = leaders[0]

        metrics.append(
            schemas.ComparisonMetric(
                key=key,
                label=label,
                values=values,
                qualified=qualified,
                best_index=best_index,
                lower_is_better=lower_better,
                format=fmt,
                gate_field=gate_field,
                gate_min=gate_min if gate_field else None,
            )
        )

    series = [
        dict((season, (runs, wickets)) for season, runs, wickets in _season_series(
            db, p.identifier, gender, competition_key, competition_type))
        for p in players
    ]
    seasons = sorted({season for one in series for season in one})

    scope_label = competition_key or competition_type or "all"
    if competition_key:
        comp = db.execute(
            select(Competition).where(
                Competition.key == competition_key, Competition.gender == gender
            )
        ).scalar_one_or_none()
        if comp:
            scope_label = comp.display_name
    elif competition_type == "international":
        scope_label = "All Internationals"
    elif competition_type == "domestic_league":
        scope_label = "Franchise Cricket"

    return schemas.PlayerComparison(
        scope=competition_key or competition_type or "all",
        scope_label=scope_label,
        gender=gender,
        sides=sides,
        metrics=metrics,
        season_runs=[
            {"season": season, "values": [one.get(season, (0, 0))[0] for one in series]}
            for season in seasons
        ],
        season_wickets=[
            {"season": season, "values": [one.get(season, (0, 0))[1] for one in series]}
            for season in seasons
        ],
    )


def _hydrate_match_summaries(db: Session, matches: list[Match]) -> list[schemas.MatchSummary]:
    """Hydrate a whole page of matches in two queries, not two per match.

    The per-match version issued one query for the competition and one for the
    sides, so a 25-row match list was 51 round trips and a 100-row one was 201.
    Each was individually cheap - both tables are small and SQLAlchemy's identity
    map absorbs the repeats within a session - which is exactly why it survived:
    the cost is per row, so it only becomes visible at the page sizes the API
    already allows.
    """
    if not matches:
        return []
    comp_ids = {m.competition_id for m in matches}
    comps = {
        c.competition_id: c
        for c in db.execute(
            select(Competition).where(Competition.competition_id.in_(comp_ids))
        ).scalars().all()
    }
    team_ids = {
        tid
        for m in matches
        for tid in (m.team1_id, m.team2_id, m.winner_team_id)
        if tid is not None
    }
    teams = {
        t.team_id: t
        for t in db.execute(select(Team).where(Team.team_id.in_(team_ids))).scalars().all()
    } if team_ids else {}
    return [
        _match_summary(
            m,
            comps[m.competition_id],
            teams.get(m.team1_id),
            teams.get(m.team2_id),
            teams.get(m.winner_team_id),
        )
        for m in matches
    ]


def _hydrate_match_summary(db: Session, m: Match) -> schemas.MatchSummary:
    """One match. Prefer `_hydrate_match_summaries` for a list."""
    return _hydrate_match_summaries(db, [m])[0]


def list_matches(
    db: Session,
    gender: str,
    competition_key: str | None,
    team_id: int | None,
    season: str | None,
    search: str | None,
    limit: int,
    offset: int,
    competition_type: str | None = None,
) -> tuple[list[schemas.MatchSummary], int]:
    """A match list, optionally confined to one competition or one type.

    Unlike the aggregate queries, an unscoped call here really does mean every
    competition: a match list is a list of events, not a summed figure, so
    mixing internationals and franchise cricket corrupts nothing. The type
    filter exists so a client that has put itself into one family can keep the
    list consistent with the rest of what it is showing, not because the
    figures would otherwise be wrong.
    """
    stmt = select(Match).where(Match.gender == gender)
    # A specific key is already narrower than any type, so it wins.
    if competition_key:
        stmt = stmt.join(Competition, Competition.competition_id == Match.competition_id).where(
            Competition.key == competition_key
        )
    elif competition_type:
        stmt = stmt.join(Competition, Competition.competition_id == Match.competition_id).where(
            Competition.type == competition_type
        )
    if team_id:
        stmt = stmt.where((Match.team1_id == team_id) | (Match.team2_id == team_id))
    if season:
        stmt = stmt.where(Match.season_label == season)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            Match.venue.ilike(like) | Match.city.ilike(like) | Match.event_name.ilike(like)
        )

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(Match.match_date_start.desc()).limit(limit).offset(offset)
    items = db.execute(stmt).scalars().all()
    return _hydrate_match_summaries(db, list(items)), total


def get_match_detail(db: Session, match_id: str) -> schemas.MatchDetail | None:
    match = db.execute(select(Match).where(Match.match_id == match_id)).scalar_one_or_none()
    if match is None:
        return None

    summary = _hydrate_match_summary(db, match)
    toss_winner = (
        db.execute(select(Team).where(Team.team_id == match.toss_winner_team_id)).scalar_one_or_none()
        if match.toss_winner_team_id
        else None
    )

    performers = db.execute(
        select(PlayerMatchStat)
        .where(PlayerMatchStat.match_id == match_id)
        # Player identifier last, so two performers on the same runs always land
        # in the same order rather than the engine's arbitrary one.
        .order_by(
            PlayerMatchStat.team_id,
            PlayerMatchStat.runs_scored.desc(),
            PlayerMatchStat.player_identifier.asc(),
        )
    ).scalars().all()

    # The flag earns its place most on a franchise scorecard, where one XI holds
    # several nationalities; on an international it agrees with the team header,
    # which is the point -- it is the same fact, not a second one.
    countries = _player_country_map(db, match.gender)

    return schemas.MatchDetail(
        **summary.model_dump(),
        toss_winner=_team_ref(toss_winner),
        toss_decision=match.toss_decision,
        player_of_match=match.player_of_match,
        event_name=match.event_name,
        performers=[
            schemas.MatchPerformer(
                player_name=p.player_name,
                player_identifier=p.player_identifier,
                country=countries.get(p.player_identifier or "", (None, None))[0],
                country_code=countries.get(p.player_identifier or "", (None, None))[1],
                team_id=p.team_id,
                runs_scored=p.runs_scored,
                balls_faced=p.balls_faced,
                fours=p.fours,
                sixes=p.sixes,
                dismissals=p.dismissals,
                wickets_taken=p.wickets_taken,
                balls_bowled=p.balls_bowled,
                runs_conceded=p.runs_conceded,
            )
            for p in performers
        ],
    )


# ---------------------------------------------------------------------------
# Player directory
# ---------------------------------------------------------------------------

# What a directory row can be ordered by. Kept as a mapping rather than accepting
# an arbitrary column name so the API can validate against it and the UI can
# render exactly the options that exist.
PLAYER_SORTS = {
    "matches": "matches",
    "runs": "runs",
    "batting_average": "batting_average",
    "strike_rate": "strike_rate",
    "wickets": "wickets",
    "bowling_average": "bowling_average",
    "economy": "economy",
    # Sorts on the bounded score, not on `form_delta`. The raw ratio is a
    # percentage against the player's own baseline, so ordering by it puts
    # whoever had the worst baseline on top -- the same defect the form boards
    # fixed by ranking on par units. The score is a percentile of that same
    # evidence-weighted move, so this ordering now matches the boards'.
    "form": "form_score",
}

# Ascending is right for these: a lower bowling average or economy is better.
PLAYER_SORTS_ASCENDING = {"bowling_average", "economy"}

# You cannot rank a player on a discipline they didn't perform. Sorting by
# economy without this puts batters who bowled six balls and conceded nothing at
# the top with an economy of 0.00, which is not the best bowling in the dataset
# -- it is the absence of bowling. Each sort declares what participation it
# requires, and rows without it are excluded from that ordering rather than
# being ranked as though a missing figure were a perfect one.
# ...and merely requiring "more than zero" is not enough: two balls bowled for
# no run is still an economy of 0.00 at the top of the table. A rate needs a
# sample before it means anything, so a sort on one applies a default
# qualification the caller can raise or explicitly lower.
DEFAULT_QUALIFY_BALLS_FACED = 200
DEFAULT_QUALIFY_BALLS_BOWLED = 300

SORT_REQUIRES = {
    "runs": "balls_faced",
    "batting_average": "balls_faced",
    "strike_rate": "balls_faced",
    "wickets": "balls_bowled",
    "bowling_average": "balls_bowled",
    "economy": "balls_bowled",
}


def browse_players(
    db: Session,
    gender: str,
    *,
    search: str | None = None,
    competition_key: str | None = None,
    competition_type: str | None = None,
    team_id: int | None = None,
    min_matches: int = 1,
    min_balls_faced: int = 0,
    min_balls_bowled: int = 0,
    status: str | None = None,
    form_state: str | None = None,
    sort_by: str = "matches",
    limit: int = 25,
    offset: int = 0,
    period: "periods.Period | None" = None,
) -> tuple[list[dict], int, int, int]:
    """The player directory: aggregates, status and form in one row per player.

    Scoped like every other aggregate -- an unqualified request is
    internationals, not "everything summed together" (see _ranking_scope).

    Sorting and filtering happen after the GROUP BY, in Python, for the same
    reason the rankings do: batting average needs a divide-by-zero guard that is
    awkward in SQL. That makes this O(players in scope) per call, which is fine
    at this dataset's size and is the first thing to revisit if it grows.
    """
    from .analytics import leaderboard as form_board

    scope_type = _ranking_scope(competition_key, competition_type)

    batting = {
        r["player_identifier"]: r
        for r in _batting_aggregate_rows(
            db, gender, competition_key, scope_type, team_id=team_id, period=period
        )
    }
    bowling = {
        r["player_identifier"]: r
        for r in _bowling_aggregate_rows(
            db, gender, competition_key, scope_type, team_id=team_id, period=period
        )
    }

    # Form comes from the cached board so the directory and the leaderboards
    # can't disagree, and so the directory doesn't pay to recompute it.
    form_rows, _ = form_board.leaderboard_page(
        db,
        gender=gender,
        competition_key=competition_key,
        competition_type=scope_type,
        limit=100_000,
        offset=0,
    )
    form_by_player = {r["player_identifier"]: r for r in form_rows}

    reference = dataset_latest_date(db)
    last_played = _last_played_map(db, gender)
    players = {
        p.identifier: p
        for p in db.execute(select(Player).where(Player.gender == gender)).scalars()
    }

    needle = (search or "").strip().lower()
    rows: list[dict] = []
    for identifier, bat in batting.items():
        player = players.get(identifier)
        if player is None:
            continue

        bowl = bowling.get(identifier, {})
        matches = bat["matches"]
        if matches < min_matches:
            continue

        display = preferred_name(player.name, player.display_name)
        if needle and needle not in (display or "").lower() and needle not in (player.name or "").lower():
            continue

        state = player_status(player, last_played.get(identifier), reference)
        if status and state.state != status:
            continue

        form_row = form_by_player.get(identifier)
        if form_state and (not form_row or form_row["state"] != form_state):
            continue

        rows.append(
            {
                "identifier": identifier,
                "name": display,
                "scorecard_name": player.name,
                "image_url": player.image_url,
                "nationality": player.nationality,
                "date_of_birth": player.date_of_birth,
                "matches": matches,
                "balls_faced": bat["balls_faced"],
                "balls_bowled": bowl.get("balls_bowled", 0),
                "runs": bat["runs"],
                "batting_average": bat["average"],
                "strike_rate": bat["strike_rate"],
                "wickets": bowl.get("wickets", 0),
                "bowling_average": bowl.get("average"),
                "economy": bowl.get("economy"),
                "status": state,
                "form_state": form_row["state"] if form_row else None,
                "form_label": form_row["label"] if form_row else None,
                "form_delta": form_row["delta_percent"] if form_row else None,
                # Bounded 0-100 and the figure the card shows. `form_delta`
                # above is the raw ratio and has no ceiling.
                "form_score": form_row["form_score"] if form_row else None,
                "form_display": form_row["delta_display"] if form_row else None,
                "form_confidence": form_row["confidence"] if form_row else None,
            }
        )

    # Qualification, applied after the rows are built so the thresholds can read
    # the aggregated figures.
    #
    # **The default floor is DERIVED when a window narrows the slice**, which is
    # the same defect `explorer.derive_min_balls` fixed and for the same reason:
    # 200 balls faced is a fair qualification for a career board and most of a
    # season's worth of batting inside a 30-day window. Measured on men's Tests,
    # the fixed floor showed 12 players of the 71 who actually batted in the last
    # 30 days, and 43 of 146 over six months - with nothing on the page saying so.
    required = SORT_REQUIRES.get(sort_by)
    faced_floor, bowled_floor = min_balls_faced, min_balls_bowled
    narrowed = period is not None and period.kind != periods.CAREER
    if required == "balls_faced" and min_balls_faced == 0:
        faced_floor = (
            explorer_mod.derive_min_balls(rows, "batting")
            if narrowed
            else DEFAULT_QUALIFY_BALLS_FACED
        )
    if required == "balls_bowled" and min_balls_bowled == 0:
        bowled_floor = (
            explorer_mod.derive_min_balls(rows, "bowling")
            if narrowed
            else DEFAULT_QUALIFY_BALLS_BOWLED
        )
    # Counted before the floor, because the two being different is the whole
    # story on a narrowed window - without it a reader cannot tell "nobody played"
    # from "the floor removed them".
    total_before_floor = len(rows)
    rows = [
        r
        for r in rows
        if r["balls_faced"] >= faced_floor and r["balls_bowled"] >= bowled_floor
    ]

    field = PLAYER_SORTS.get(sort_by, "matches")
    ascending = field in PLAYER_SORTS_ASCENDING
    # Identifier first as a stable tiebreak, so paging never repeats or skips a
    # row when two players share a figure. Missing values sort last in both
    # directions -- a player with no bowling average is not the best bowler.
    rows.sort(key=lambda r: r["identifier"])
    if ascending:
        rows.sort(key=lambda r: (r[field] is None, r[field] if r[field] is not None else 0))
    else:
        # The "is not None" flag has to invert with the sort direction. Reusing
        # the ascending key under reverse=True would sort missing values to the
        # TOP -- a form-sorted directory would open with the players who have no
        # form verdict at all.
        rows.sort(
            key=lambda r: (r[field] is not None, r[field] if r[field] is not None else 0),
            reverse=True,
        )

    return (
        rows[offset : offset + limit],
        len(rows),
        total_before_floor,
        faced_floor if required == "balls_faced" else bowled_floor,
    )

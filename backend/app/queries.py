from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import schemas
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


def _safe_div(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator, 2)


def _team_ref(team: Team | None) -> schemas.TeamRef | None:
    if team is None:
        return None
    return schemas.TeamRef(team_id=team.team_id, name=team.name)


def _match_summary(m: Match, comp: Competition, team1: Team | None, team2: Team | None, winner: Team | None) -> schemas.MatchSummary:
    return schemas.MatchSummary(
        match_id=m.match_id,
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


def _batting_aggregate_rows(
    db: Session,
    gender: str,
    competition_key: str | None = None,
    competition_type: str | None = None,
    player_identifier: str | None = None,
    team_id: int | None = None,
) -> list[dict]:
    stmt = (
        select(
            # Grouped by identifier, not name: 78 names in this dataset map to
            # more than one real person (e.g. two "Iftikhar Ahmed"s in the PSL
            # squads alone), and grouping by name silently merged their careers
            # into a single ranking row. player_match_stats.player_identifier is
            # populated for every Cricsheet-sourced row.
            #
            # Display uses the Wikidata label ("Joe Root") where we have one and
            # the scorecard name ("JE Root") otherwise -- max() wrappers keep it
            # valid under GROUP BY even though the join is 1:1 on the group key.
            func.coalesce(
                func.max(Player.display_name),
                func.max(Player.name),
                func.max(PlayerMatchStat.player_name),
            ).label("player_name"),
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

    rows = db.execute(stmt).all()
    results = []
    for r in rows:
        runs = r.runs or 0
        dismissals = r.dismissals or 0
        balls_faced = r.balls_faced or 0
        results.append(
            {
                "player_name": r.player_name,
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
    return results


def _bowling_aggregate_rows(
    db: Session,
    gender: str,
    competition_key: str | None = None,
    competition_type: str | None = None,
    player_identifier: str | None = None,
    team_id: int | None = None,
) -> list[dict]:
    stmt = (
        select(
            # Grouped by identifier, not name -- see _batting_aggregate_rows.
            func.coalesce(
                func.max(Player.display_name),
                func.max(Player.name),
                func.max(PlayerMatchStat.player_name),
            ).label("player_name"),
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

    rows = db.execute(stmt).all()
    results = []
    for r in rows:
        wickets = r.wickets or 0
        runs_conceded = r.runs_conceded or 0
        balls_bowled = r.balls_bowled or 0
        results.append(
            {
                "player_name": r.player_name,
                "player_identifier": r.player_identifier,
                "matches": r.matches,
                "wickets": wickets,
                "runs_conceded": runs_conceded,
                "balls_bowled": balls_bowled,
                "average": _safe_div(runs_conceded, wickets),
                "economy": _safe_div(runs_conceded * 6, balls_bowled),
            }
        )
    return results


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


def get_batting_rankings(
    db: Session,
    gender: str,
    competition_key: str | None,
    min_matches: int,
    sort_by: str,
    limit: int,
    offset: int,
    competition_type: str | None = None,
) -> tuple[list[dict], int]:
    rows = _batting_aggregate_rows(
        db,
        gender,
        competition_key=competition_key,
        competition_type=_ranking_scope(competition_key, competition_type),
    )
    rows = [r for r in rows if r["matches"] >= min_matches]
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
) -> tuple[list[dict], int]:
    rows = _bowling_aggregate_rows(
        db,
        gender,
        competition_key=competition_key,
        competition_type=_ranking_scope(competition_key, competition_type),
    )
    rows = [r for r in rows if r["matches"] >= min_matches]
    reverse = sort_by not in ("average", "economy")  # lower is better for both
    rows.sort(key=lambda r: (r[sort_by] if r[sort_by] is not None else (10**9)), reverse=reverse)
    total = len(rows)
    return rows[offset : offset + limit], total


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

    batting_rows, _ = get_batting_rankings(
        db, gender, competition_key=None, min_matches=1, sort_by="runs", limit=5, offset=0
    )
    bowling_rows, _ = get_bowling_rankings(
        db, gender, competition_key=None, min_matches=1, sort_by="wickets", limit=5, offset=0
    )

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
        gender=team.gender,
        team_type=team.team_type,
        matches=matches,
        wins=wins,
        losses=losses,
        ties_or_no_result=ties_or_nr,
        win_pct=_safe_div(wins * 100, matches),
    )


def get_teams_summary(
    db: Session, gender: str, team_type: str | None = None
) -> list[schemas.TeamSummary]:
    # Without a team_type filter this lists Karachi Kings next to Australia --
    # they're both male teams, but they aren't comparable entities. The caller
    # picks a side; the API doesn't blend them by default.
    stmt = select(Team).where(Team.gender == gender)
    if team_type:
        stmt = stmt.where(Team.team_type == team_type)
    teams = db.execute(stmt).scalars().all()
    summaries = [_team_summary(db, t) for t in teams]
    summaries = [s for s in summaries if s.matches > 0]
    summaries.sort(key=lambda s: s.matches, reverse=True)
    return summaries


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
    recent_matches = [_hydrate_match_summary(db, m) for m in recent]

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
        stmt = stmt.where(Player.name.ilike(f"%{search}%"))

    all_rows = db.execute(stmt).all()
    all_rows = sorted(all_rows, key=lambda r: r.matches, reverse=True)
    total = len(all_rows)
    page = all_rows[offset : offset + limit]

    # Status only for the page being returned -- the two lookups it needs are
    # cheap, but building them for all ~9,400 players to serve 25 would not be.
    reference = dataset_latest_date(db)
    last_played = _last_played_map(db, gender)
    page_players = {
        p.identifier: p
        for p in db.execute(
            select(Player).where(Player.identifier.in_([r.identifier for r in page]))
        ).scalars()
    }

    items = [
        schemas.PlayerSummary(
            identifier=r.identifier,
            name=(page_players[r.identifier].display_name if r.identifier in page_players
                  and page_players[r.identifier].display_name else r.name),
            scorecard_name=r.name,
            gender=r.gender,
            matches=r.matches,
            status=(
                player_status(page_players[r.identifier], last_played.get(r.identifier), reference)
                if r.identifier in page_players
                else None
            ),
        )
        for r in page
    ]
    return items, total


def get_player_detail(db: Session, identifier: str) -> schemas.PlayerDetail | None:
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
    for comp in competitions:
        batting = _batting_aggregate_rows(
            db, player.gender, competition_key=comp.key, player_identifier=identifier
        )
        bowling = _bowling_aggregate_rows(
            db, player.gender, competition_key=comp.key, player_identifier=identifier
        )
        if not batting and not bowling:
            continue
        b = batting[0] if batting else None
        bo = bowling[0] if bowling else None
        by_competition.append(
            schemas.PlayerFormatStats(
                competition_key=comp.key,
                display_name=comp.display_name,
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
        )

    recent = db.execute(
        select(Match)
        .join(PlayerMatchStat, PlayerMatchStat.match_id == Match.match_id)
        .where(PlayerMatchStat.player_identifier == identifier)
        .order_by(Match.match_date_start.desc())
        .limit(RECENT_MATCHES_LIMIT)
    ).scalars().all()
    recent_matches = [_hydrate_match_summary(db, m) for m in recent]

    return schemas.PlayerDetail(
        identifier=player.identifier,
        name=player.display_name or player.name,
        scorecard_name=player.name,
        gender=player.gender,
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

    if window == "upcoming":
        stmt = stmt.where(Fixture.is_upcoming == 1).order_by(
            Fixture.start_date.asc(), Fixture.start_time_gmt.asc()
        )
    elif window == "live":
        stmt = stmt.where(Fixture.is_live == 1).order_by(Fixture.start_date.asc())
    else:  # results
        # Date-bounded, not just `is_upcoming == 0`. A cancelled *future*
        # fixture carries is_upcoming=0 and match_result="Match Cancelled", so
        # without this it sorts to the top of "results" and the most recent
        # result on the page is a match two months away that never happened.
        stmt = stmt.where(
            Fixture.is_upcoming == 0,
            Fixture.match_result.is_not(None),
            Fixture.start_date <= date.today().isoformat(),
        ).order_by(Fixture.start_date.desc())

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


def get_icc_player_ranking(db: Session, rank_type: str) -> schemas.IccRankingTable | None:
    rank_date = db.execute(
        select(func.max(IccPlayerRanking.rank_date)).where(
            IccPlayerRanking.rank_type == rank_type
        )
    ).scalar_one_or_none()
    if not rank_date:
        return None
    rows = db.execute(
        select(IccPlayerRanking)
        .where(IccPlayerRanking.rank_type == rank_type, IccPlayerRanking.rank_date == rank_date)
        .order_by(IccPlayerRanking.position)
    ).scalars().all()
    return schemas.IccRankingTable(
        rank_type=rank_type,
        rank_date=rank_date,
        fetched_at=rows[0].fetched_at if rows else None,
        rows=[
            schemas.IccRankingRow(
                position=r.position,
                player_name=r.player_name,
                country=r.country,
                points=r.points,
                career_best=r.career_best,
                player_identifier=r.player_identifier,
            )
            for r in rows
        ],
    )


def get_icc_team_ranking(db: Session, rank_type: str) -> schemas.IccTeamRankingTable | None:
    rank_date = db.execute(
        select(func.max(IccTeamRanking.rank_date)).where(IccTeamRanking.rank_type == rank_type)
    ).scalar_one_or_none()
    if not rank_date:
        return None
    rows = db.execute(
        select(IccTeamRanking)
        .where(IccTeamRanking.rank_type == rank_type, IccTeamRanking.rank_date == rank_date)
        .order_by(IccTeamRanking.position)
    ).scalars().all()
    return schemas.IccTeamRankingTable(
        rank_type=rank_type,
        rank_date=rank_date,
        fetched_at=rows[0].fetched_at if rows else None,
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
    competition_type: str | None,
) -> schemas.PlayerFormatStats | None:
    batting = _batting_aggregate_rows(
        db, gender, competition_key=competition_key,
        competition_type=competition_type, player_identifier=identifier,
    )
    bowling = _bowling_aggregate_rows(
        db, gender, competition_key=competition_key,
        competition_type=competition_type, player_identifier=identifier,
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
    reference: str | None,
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
        totals = _scoped_totals(db, identifier, player.gender, comp.key, None)
        if totals is None:
            continue
        totals.competition_key = comp.key
        totals.display_name = comp.display_name
        by_competition.append(totals)

    return schemas.ComparisonSide(
        identifier=identifier,
        name=player.display_name or player.name,
        scorecard_name=player.name,
        status=player_status(player, last_played, reference),
        teams=[_team_ref(t) for t in teams],
        bio=schemas.PlayerBio(
            date_of_birth=player.date_of_birth,
            birth_place=player.birth_place,
            nationality=player.nationality,
            bio_source=player.bio_source,
            image_url=player.image_url,
        ),
        totals=_scoped_totals(db, identifier, player.gender, competition_key, competition_type),
        by_competition=by_competition,
        icc_rankings=current_icc_ranks_for_player(db, identifier),
        career_span=_career_span(db, identifier),
    )


def get_player_comparison(
    db: Session, identifier_a: str, identifier_b: str,
    competition_key: str | None, competition_type: str | None,
) -> schemas.PlayerComparison | str:
    """Head-to-head between two players. Returns an error string if invalid.

    Two rules are enforced rather than left to the caller:
      * same gender -- men's and women's cricket share no identity anywhere
        else in this app, and a cross-gender "who scored more" is not a
        comparison anyone makes;
      * one competition scope -- comparing an unscoped career total would sum
        international and franchise runs, the exact blend Phase 2 removed.
    """
    a = db.execute(select(Player).where(Player.identifier == identifier_a)).scalar_one_or_none()
    b = db.execute(select(Player).where(Player.identifier == identifier_b)).scalar_one_or_none()
    if a is None:
        return f"player '{identifier_a}' not found"
    if b is None:
        return f"player '{identifier_b}' not found"
    if a.identifier == b.identifier:
        return "cannot compare a player with themselves"
    if a.gender != b.gender:
        return (
            f"cannot compare across genders ('{a.name}' is {a.gender}, "
            f"'{b.name}' is {b.gender})"
        )

    if not competition_key and not competition_type:
        competition_type = DEFAULT_RANKING_COMPETITION_TYPE
    if competition_key:
        competition_type = None

    reference = dataset_latest_date(db)
    side_a = _comparison_side(db, a, competition_key, competition_type, reference)
    side_b = _comparison_side(db, b, competition_key, competition_type, reference)

    metrics = []
    for key, label, lower_better, fmt, gate_field, gate_min in COMPARISON_METRICS:
        va = getattr(side_a.totals, key, None) if side_a.totals else None
        vb = getattr(side_b.totals, key, None) if side_b.totals else None
        comparable = True
        if gate_field:
            ga = getattr(side_a.totals, gate_field, 0) if side_a.totals else 0
            gb = getattr(side_b.totals, gate_field, 0) if side_b.totals else 0
            comparable = (ga or 0) >= gate_min and (gb or 0) >= gate_min
        better = None
        if comparable and va is not None and vb is not None and va != vb:
            a_wins = va < vb if lower_better else va > vb
            better = "a" if a_wins else "b"
        metrics.append(
            schemas.ComparisonMetric(
                key=key, label=label, a=va, b=vb,
                better=better, lower_is_better=lower_better, format=fmt,
            )
        )

    series_a = dict((s, (r, w)) for s, r, w in _season_series(
        db, a.identifier, a.gender, competition_key, competition_type))
    series_b = dict((s, (r, w)) for s, r, w in _season_series(
        db, b.identifier, b.gender, competition_key, competition_type))
    seasons = sorted(set(series_a) | set(series_b))

    scope_label = competition_key or competition_type or "all"
    if competition_key:
        comp = db.execute(
            select(Competition).where(
                Competition.key == competition_key, Competition.gender == a.gender
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
        gender=a.gender,
        a=side_a,
        b=side_b,
        metrics=metrics,
        season_runs=[
            {"season": s, "a": series_a.get(s, (0, 0))[0], "b": series_b.get(s, (0, 0))[0]}
            for s in seasons
        ],
        season_wickets=[
            {"season": s, "a": series_a.get(s, (0, 0))[1], "b": series_b.get(s, (0, 0))[1]}
            for s in seasons
        ],
    )


def _hydrate_match_summary(db: Session, m: Match) -> schemas.MatchSummary:
    comp = db.execute(
        select(Competition).where(Competition.competition_id == m.competition_id)
    ).scalar_one()
    team_ids = [tid for tid in (m.team1_id, m.team2_id, m.winner_team_id) if tid is not None]
    teams_by_id = {
        t.team_id: t
        for t in db.execute(select(Team).where(Team.team_id.in_(team_ids))).scalars().all()
    } if team_ids else {}
    return _match_summary(
        m,
        comp,
        teams_by_id.get(m.team1_id),
        teams_by_id.get(m.team2_id),
        teams_by_id.get(m.winner_team_id),
    )


def list_matches(
    db: Session,
    gender: str,
    competition_key: str | None,
    team_id: int | None,
    season: str | None,
    search: str | None,
    limit: int,
    offset: int,
) -> tuple[list[schemas.MatchSummary], int]:
    stmt = select(Match).where(Match.gender == gender)
    if competition_key:
        stmt = stmt.join(Competition, Competition.competition_id == Match.competition_id).where(
            Competition.key == competition_key
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
    return [_hydrate_match_summary(db, m) for m in items], total


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
        .order_by(PlayerMatchStat.team_id, PlayerMatchStat.runs_scored.desc())
    ).scalars().all()

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

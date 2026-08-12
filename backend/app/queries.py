from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import schemas
from .models import Competition, Match, Player, PlayerMatchStat, Team

RECENT_MATCHES_LIMIT = 10


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


def _batting_aggregate_rows(
    db: Session,
    gender: str,
    competition_key: str | None = None,
    player_identifier: str | None = None,
) -> list[dict]:
    stmt = (
        select(
            PlayerMatchStat.player_name,
            func.max(PlayerMatchStat.player_identifier).label("player_identifier"),
            func.count(func.distinct(PlayerMatchStat.match_id)).label("matches"),
            func.sum(PlayerMatchStat.runs_scored).label("runs"),
            func.sum(PlayerMatchStat.dismissals).label("dismissals"),
            func.sum(PlayerMatchStat.balls_faced).label("balls_faced"),
            func.sum(PlayerMatchStat.fours).label("fours"),
            func.sum(PlayerMatchStat.sixes).label("sixes"),
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .where(Match.gender == gender)
        .group_by(PlayerMatchStat.player_name)
    )
    if competition_key:
        stmt = stmt.join(Competition, Competition.competition_id == Match.competition_id).where(
            Competition.key == competition_key
        )
    if player_identifier:
        stmt = stmt.where(PlayerMatchStat.player_identifier == player_identifier)

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
    player_identifier: str | None = None,
) -> list[dict]:
    stmt = (
        select(
            PlayerMatchStat.player_name,
            func.max(PlayerMatchStat.player_identifier).label("player_identifier"),
            func.count(func.distinct(PlayerMatchStat.match_id)).label("matches"),
            func.sum(PlayerMatchStat.wickets_taken).label("wickets"),
            func.sum(PlayerMatchStat.runs_conceded).label("runs_conceded"),
            func.sum(PlayerMatchStat.balls_bowled).label("balls_bowled"),
        )
        .join(Match, Match.match_id == PlayerMatchStat.match_id)
        .where(Match.gender == gender, PlayerMatchStat.balls_bowled > 0)
        .group_by(PlayerMatchStat.player_name)
    )
    if competition_key:
        stmt = stmt.join(Competition, Competition.competition_id == Match.competition_id).where(
            Competition.key == competition_key
        )
    if player_identifier:
        stmt = stmt.where(PlayerMatchStat.player_identifier == player_identifier)

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


def get_batting_rankings(
    db: Session,
    gender: str,
    competition_key: str | None,
    min_matches: int,
    sort_by: str,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    rows = _batting_aggregate_rows(db, gender, competition_key=competition_key)
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
) -> tuple[list[dict], int]:
    rows = _bowling_aggregate_rows(db, gender, competition_key=competition_key)
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


def get_teams_summary(db: Session, gender: str) -> list[schemas.TeamSummary]:
    teams = db.execute(select(Team).where(Team.gender == gender)).scalars().all()
    summaries = [_team_summary(db, t) for t in teams]
    summaries = [s for s in summaries if s.matches > 0]
    summaries.sort(key=lambda s: s.matches, reverse=True)
    return summaries


def get_team_detail(db: Session, team_id: int) -> schemas.TeamDetail | None:
    team = db.execute(select(Team).where(Team.team_id == team_id)).scalar_one_or_none()
    if team is None:
        return None

    summary = _team_summary(db, team)

    team_player_names = {
        n
        for (n,) in db.execute(
            select(PlayerMatchStat.player_name)
            .where(PlayerMatchStat.team_id == team_id)
            .distinct()
        ).all()
    }

    batting_rows = [
        r for r in _batting_aggregate_rows(db, team.gender) if r["player_name"] in team_player_names
    ]
    batting_rows.sort(key=lambda r: r["runs"], reverse=True)

    bowling_rows = [
        r for r in _bowling_aggregate_rows(db, team.gender) if r["player_name"] in team_player_names
    ]
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
    items = [
        schemas.PlayerSummary(identifier=r.identifier, name=r.name, gender=r.gender, matches=r.matches)
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
        name=player.name,
        gender=player.gender,
        teams=[_team_ref(t) for t in teams],
        bio=schemas.PlayerBio(
            date_of_birth=player.date_of_birth,
            birth_place=player.birth_place,
            nationality=player.nationality,
            bio_source=player.bio_source,
        ),
        by_competition=by_competition,
        recent_matches=recent_matches,
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

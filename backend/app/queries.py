from datetime import date

from sqlalchemy import case, func, or_, select, union_all
from sqlalchemy.orm import Session

from . import schemas, flags
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


def _player_country_map(
    db: Session, gender: str | None = None
) -> dict[str, tuple[str, str | None]]:
    """player_identifier -> (national side represented, ISO code or None).

    The flag beside a player means the same thing as the flag beside a team:
    the nation they turn out for. It is read from their appearances, which is
    Cricsheet-derived and exact, and deliberately *not* from
    `players.nationality` — that is a Wikidata citizenship claim answering a
    different question. A Guyanese passport does not make a West Indies player
    Guyanese in cricketing terms, and the dataset carries values like "United
    Kingdom" that name no cricketing side at all.

    Three cases the shape of the data forces:

    * **Franchise-only players** (1,247 of 9,442, mostly PSL) represent no
      nation here and get no entry. They render as the neutral mark, exactly
      as a franchise team does.
    * **Invitational appearances** are skipped, so the 146 players with more
      than one "international" side collapse to their real one — an ICC World
      XI cap does not make Dravid dual-national.
    * **Genuine switchers** remain (van der Merwe: South Africa then
      Netherlands; Garth: Australia then Ireland). The most recent side wins,
      tie-broken on appearances. That is a sourced fact — who they last played
      for — rather than a guess at allegiance, and the side's name travels with
      the code so the UI can say which on hover.
    """
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
    return {ident: (name, code) for ident, (_, _, name, code) in best.items()}


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
) -> tuple[list[dict], int]:
    rows = _bowling_aggregate_rows(
        db,
        gender,
        competition_key=competition_key,
        competition_type=_ranking_scope(competition_key, competition_type),
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


def _team_record_map(db: Session) -> dict[int, tuple[int, int, int]]:
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
    "form": "form_delta",
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
) -> tuple[list[dict], int]:
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
            db, gender, competition_key, scope_type, team_id=team_id
        )
    }
    bowling = {
        r["player_identifier"]: r
        for r in _bowling_aggregate_rows(
            db, gender, competition_key, scope_type, team_id=team_id
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
                "form_confidence": form_row["confidence"] if form_row else None,
            }
        )

    # Qualification, applied after the rows are built so the thresholds can read
    # the aggregated figures.
    required = SORT_REQUIRES.get(sort_by)
    faced_floor, bowled_floor = min_balls_faced, min_balls_bowled
    if required == "balls_faced" and min_balls_faced == 0:
        faced_floor = DEFAULT_QUALIFY_BALLS_FACED
    if required == "balls_bowled" and min_balls_bowled == 0:
        bowled_floor = DEFAULT_QUALIFY_BALLS_BOWLED
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

    return rows[offset : offset + limit], len(rows)

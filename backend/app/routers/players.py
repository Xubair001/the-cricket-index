from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import queries, schemas, validation
from ..analytics import availability as availability_mod, scout as scout_mod, splits as splits_mod, config, form
from ..analytics import leaderboard as form_board
from ..database import get_db

router = APIRouter(prefix="/api/players", tags=["players"])


@router.get("/compare", response_model=schemas.PlayerComparison)
def compare_players(
    players: list[str] | None = Query(
        default=None,
        description=(
            "2 to 5 player identifiers. Repeat the parameter "
            "(?players=x&players=y) or pass one comma-separated value."
        ),
    ),
    a: str | None = Query(default=None, description="legacy: first player", deprecated=True),
    b: str | None = Query(default=None, description="legacy: second player", deprecated=True),
    competition: str | None = Query(default=None),
    competition_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.PlayerComparison:
    """Compare 2 to 5 players within one competition scope (§13).

    Declared before /{identifier} so 'compare' isn't captured as an identifier.

    `a` and `b` are still accepted, and that is not tidiness: §27 makes every
    filter state a URL a scout can send to a colleague, so two-player links
    already shared have to keep resolving. They map onto the front of `players`.
    """
    identifiers: list[str] = []
    for value in players or []:
        # Accept both ?players=x&players=y and ?players=x,y. The second is what
        # a hand-written or shared URL tends to look like.
        identifiers += [part.strip() for part in value.split(",") if part.strip()]
    if not identifiers:
        identifiers = [x for x in (a, b) if x]

    if len(identifiers) > queries.MAX_COMPARISON_PLAYERS:
        # Bounded before any query runs: identifiers are caller-controlled and
        # each one costs several aggregates.
        raise HTTPException(
            status_code=422,
            detail=(
                f"cannot compare more than {queries.MAX_COMPARISON_PLAYERS} "
                f"players at once ({len(identifiers)} requested)"
            ),
        )
    for identifier in identifiers:
        if len(identifier) > validation.MAX_SEARCH_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"player identifier too long: '{validation.echo(identifier)}'",
            )

    result = queries.get_player_comparison(
        db,
        identifiers,
        validation.check_competition_key(db, competition),
        validation.check_competition_type(db, competition_type),
    )
    if isinstance(result, str):
        # 404 for a missing player, 422 for a set that can't be compared.
        raise HTTPException(status_code=404 if "not found" in result else 422, detail=result)
    return result


@router.get("/directory", response_model=schemas.PlayerDirectory)
def player_directory(
    gender: str = Query(pattern="^(male|female)$"),
    search: str | None = Query(default=None, max_length=validation.MAX_SEARCH_LENGTH),
    competition: str | None = Query(default=None),
    competition_type: str | None = Query(default=None),
    team_id: int | None = Query(default=None, ge=1, le=validation.MAX_DB_INT),
    min_matches: int = Query(default=1, ge=1, le=500),
    min_balls_faced: int = Query(default=0, ge=0),
    min_balls_bowled: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, pattern="^(active|inactive|retired)$"),
    form_state: str | None = Query(default=None),
    sort_by: str = Query(default="matches"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.PlayerDirectory:
    """The discovery surface: aggregates, playing status and current form together.

    Declared before /{identifier} so 'directory' isn't captured as an identifier.
    """
    if sort_by not in queries.PLAYER_SORTS:
        raise HTTPException(
            status_code=422,
            detail=f"sort_by must be one of {sorted(queries.PLAYER_SORTS)}",
        )
    comp_key = validation.check_competition_key(db, competition)
    comp_type = validation.check_competition_type(db, competition_type)
    rows, total = queries.browse_players(
        db,
        gender,
        search=search,
        competition_key=comp_key,
        competition_type=comp_type,
        team_id=team_id,
        min_matches=min_matches,
        min_balls_faced=min_balls_faced,
        min_balls_bowled=min_balls_bowled,
        status=status,
        form_state=form_state,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    return schemas.PlayerDirectory(
        total=total,
        limit=limit,
        offset=offset,
        scope=form_board.scope_label(comp_key, comp_type),
        items=[
            schemas.DirectoryPlayer(**r)
            for r in queries._attach_country(
                rows, queries._player_country_map(db, gender), key="identifier"
            )
        ],
    )


@router.get("", response_model=schemas.PaginatedPlayers)
def list_players(
    gender: str = Query(pattern="^(male|female)$"),
    search: str | None = Query(default=None, max_length=validation.MAX_SEARCH_LENGTH),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> schemas.PaginatedPlayers:
    items, total = queries.search_players(db, gender, search, limit, offset)
    return schemas.PaginatedPlayers(total=total, limit=limit, offset=offset, items=items)


@router.get("/{identifier}/form", response_model=schemas.FormVerdict)
def player_form(
    identifier: str,
    recent: int = Query(default=None, ge=3, le=50, description="matches in the recent window"),
    baseline_days: int = Query(default=None, ge=30, le=3650),
    competition: str | None = Query(default=None),
    competition_type: str | None = Query(
        default=None,
        description=(
            "Scope the verdict to one competition type. Internationals and "
            "franchise cricket are not blended into a single form figure."
        ),
    ),
    db: Session = Depends(get_db),
) -> schemas.FormVerdict:
    """How this player is going, measured against their own recent baseline.

    Declared before /{identifier} would otherwise be reached, and separate from
    the profile endpoint because form is a different question from career
    record -- Rule 3 -- and is the expensive half.
    """
    player = queries.get_player_detail(db, identifier)
    if player is None:
        raise HTTPException(status_code=404, detail=f"player '{validation.echo(identifier)}' not found")

    comp_key = validation.check_competition_key(db, competition)
    comp_type = validation.check_competition_type(db, competition_type)
    verdict = form.assess(
        db,
        identifier,
        recent_matches=recent or config.DEFAULT_RECENT_MATCHES,
        baseline_days=baseline_days or config.DEFAULT_BASELINE_DAYS,
        competition_key=comp_key,
        competition_type=comp_type,
    )
    # `assess` has no population to place the verdict against, so the bounded
    # 0-100 score has to be computed here. Without this the profile page shows
    # the unbounded percentage while every board shows the score.
    verdict.form_score = form.score_against_scope(
        db,
        verdict,
        gender=player.gender,
        competition_key=comp_key,
        competition_type=comp_type,
    )
    return schemas.FormVerdict(**verdict.as_dict())


@router.get("/scout", response_model=schemas.ScoutResult)
def scout_search(
    gender: str = Query(pattern="^(male|female)$"),
    competition: str | None = Query(default=None),
    competition_type: str | None = Query(default="international"),
    role: str | None = Query(default=None),
    batting_style: str | None = Query(default=None, pattern="^(RHB|LHB)$"),
    bowling_family: str | None = Query(default=None, pattern="^(pace|spin)$"),
    # Batting position. Derived from the ball record, so unlike hand and
    # bowling style this one has full coverage rather than being bounded by
    # who happens to appear in the ICC squad feed.
    opens: bool = Query(default=False),
    max_age: int | None = Query(default=None, ge=15, le=60),
    min_matches: int = Query(default=10, ge=1, le=500),
    form_state: str | None = Query(default=None),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    exclude_committed: bool = Query(default=False),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
) -> schemas.ScoutResult:
    """Run a scouting brief and return ranked, explained candidates (§17).

    The response declares `applied` and `ignored` because §17's own warning is
    that shipping this early means "a filter that quietly ignores half the
    brief". A constraint that cannot be honoured is named with its reason.

    Age is a SOFT bound: date of birth covers about 42% of the register, so
    players of unknown age are kept and counted rather than dropped.
    """
    result = scout_mod.search(
        db,
        gender=gender,
        competition_key=validation.check_competition_key(db, competition),
        competition_type=validation.check_competition_type(db, competition_type),
        role=role,
        batting_style=batting_style,
        bowling_family=bowling_family,
        opens=opens,
        max_age=max_age,
        min_matches=min_matches,
        form_state=form_state,
        date_from=date_from,
        date_to=date_to,
        exclude_committed=exclude_committed,
        limit=limit,
    )
    return schemas.ScoutResult(
        scope=result.scope,
        gender=result.gender,
        candidates_considered=result.candidates_considered,
        with_sourced_attributes=result.with_sourced_attributes,
        unknown_age=result.unknown_age,
        applied=result.applied,
        ignored=result.ignored,
        candidates=[schemas.ScoutCandidate(**vars(c)) for c in result.candidates],
    )


@router.get("/availability", response_model=schemas.AvailabilityWindow)
def availability(
    date_from: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    role: str | None = Query(default=None),
    batting_style: str | None = Query(default=None, pattern="^(RHB|LHB)$"),
    player: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> schemas.AvailabilityWindow:
    """Who is COMMITTED between two dates (§16).

    Deliberately not "who is available": a player named in a squad is sourced
    fact, a player absent from every squad is not evidence of anything, because
    most fixtures in a forward window have no squad announced yet. The response
    carries `fixtures_with_squads` against `fixtures_in_window` so the caller can
    see how much of the window is known, plus the caveats verbatim.
    """
    result = availability_mod.window(
        db,
        date_from=date_from,
        date_to=date_to,
        player_identifier=player,
        role=role,
        batting_style=batting_style,
        limit=limit,
    )
    return schemas.AvailabilityWindow(
        date_from=result.date_from,
        date_to=result.date_to,
        fixtures_in_window=result.fixtures_in_window,
        fixtures_with_squads=result.fixtures_with_squads,
        caveats=result.caveats,
        players=[
            schemas.PlayerAvailabilityRow(
                player_identifier=p.player_identifier,
                player_name=p.player_name,
                committed=p.committed,
                role=p.role,
                batting_style=p.batting_style,
                bowling_style=p.bowling_style,
                commitments=[schemas.CommitmentRow(**vars(c)) for c in p.commitments],
            )
            for p in result.players
        ],
    )


@router.get("/{identifier}/splits", response_model=schemas.PlayerSplits)
def player_splits(
    identifier: str,
    split: str = Query(default="phase"),
    gender: str = Query(pattern="^(male|female)$"),
    competition: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> schemas.PlayerSplits:
    """One split for one player (§12), split type as a parameter (§25).

    Phase and situation come off the stored deliveries; venue, opposition and
    competition come off the match. Splits §12 lists but no source supports are
    returned in `unavailable` with a reason rather than omitted, so the caller
    can see the difference between "no data for this player" and "this cut is
    not computable at all".
    """
    if split not in splits_mod.AVAILABLE:
        raise HTTPException(
            status_code=422,
            detail=f"unknown split '{validation.echo(split)}'; available: {sorted(splits_mod.AVAILABLE)}",
        )
    key = validation.check_competition_key(db, competition)
    result = splits_mod.compute(
        db, identifier, split=split, gender=gender, competition_key=key
    )
    return schemas.PlayerSplits(
        player_identifier=identifier,
        split=result.split,
        label=result.label,
        gender=gender,
        competition_key=key,
        applies=result.applies,
        not_applicable_because=result.not_applicable_because,
        available=sorted(splits_mod.AVAILABLE),
        unavailable=splits_mod.UNAVAILABLE,
        buckets=[schemas.SplitBucket(**vars(b)) for b in result.buckets],
    )


@router.get("/{identifier}", response_model=schemas.PlayerDetail)
def player_detail(identifier: str, db: Session = Depends(get_db)) -> schemas.PlayerDetail:
    # No gender param needed: a player's identifier already uniquely
    # determines them (and their gender) -- no cross-gender ambiguity to
    # resolve, unlike team names.
    detail = queries.get_player_detail(db, identifier)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"player '{validation.echo(identifier)}' not found")
    return detail

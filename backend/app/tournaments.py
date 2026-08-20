"""Tournaments: World Cups, Champions Trophy and the rest.

What counts as a tournament
----------------------------
`matches.event_name` names 1,276 distinct events after aliasing, and **1,013 of
them are bilateral tours** - "Pakistan tour of England" is two sides playing a
series, not a tournament. Listing them all would bury the World Cup under a
thousand tours.

So a tournament here is an event that at least `MIN_SIDES` teams played in.
That is a fact read off the data, not a guess from the name: a name-based rule
("contains Cup", "starts with ICC") would both admit tours called Trophy and
miss tournaments that are not called anything of the kind. 266 events qualify,
holding 5,424 matches.

Where a winner comes from
--------------------------
`matches.event_stage = 'Final'`, sourced from Cricsheet's `event.stage`. It is
never inferred from "the last match of the event", which is wrong wherever a
third-place play-off is played after the final or coverage of an edition is
partial - and partial coverage is common here (see below).

The final's winner is `winner_team_id` **or** `eliminator_team_id`. Both are
needed and the second is the interesting one: Cricsheet records a tied match as
`{"result": "tie", "eliminator": "England"}` with no winner at all, so the 2019
World Cup final has `winner_team_id` NULL. England won that World Cup. Reading
only `winner_team_id` would show the most famous final of the decade as won by
nobody.

Coverage is stated, never implied
----------------------------------
Cricsheet does not hold every match of every edition. The 2019 men's World Cup
was 48 matches; this database has 36. An edition therefore reports the matches
held rather than a total, and `has_final` says whether the deciding match is
among them - so "winner unknown" reads as "we do not hold that match", which is
true, instead of as "nobody won it", which is not.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import events as events_mod
from .models import Competition, Match, Player, PlayerMatchStat, Team
from .names import preferred_name

# How many distinct sides make an event a tournament rather than a tour.
# Three, not four: a triangular series is a genuine tournament and several in
# this data (the old Asia Cups, the Kwibuka group stages) have exactly three.
MIN_SIDES = 3

# Afghanistan have been a regular participant in global events since gaining
# full membership. A tournament whose most recent edition predates this could
# legitimately have no Afghanistan matches, so the coverage note is not shown
# for it.
AFGHANISTAN_QUALIFIED_FROM = "2015-01-01"

# Rows returned for the per-tournament leaderboards. Enough to be a story,
# short enough that the page stays readable.
TOP_N = 10


@dataclass
class Edition:
    season: str | None
    matches: int
    sides: int
    first_date: str | None
    last_date: str | None
    winner_team_id: int | None = None
    winner_name: str | None = None
    runner_up_name: str | None = None
    # False when the deciding match is not in this dataset, which is why a
    # winner may be absent. Distinguishes "we do not hold it" from "nobody won".
    has_final: bool = False
    # True when the final was tied and settled on a super over, boundary count
    # or bowl-out. The winner then comes from `eliminator_team_id`.
    decided_by_tiebreak: bool = False
    venues: list[str] = field(default_factory=list)


@dataclass
class TournamentSummary:
    name: str
    slug: str
    gender: str
    competition_key: str
    competition_name: str
    competition_type: str
    is_icc: bool
    is_flagship: bool
    matches: int
    sides: int
    editions: int
    first_date: str | None
    last_date: str | None
    latest_season: str | None
    latest_winner: str | None


@dataclass
class TournamentDetail(TournamentSummary):
    editions_detail: list[Edition] = field(default_factory=list)
    top_run_scorers: list[dict] = field(default_factory=list)
    top_wicket_takers: list[dict] = field(default_factory=list)
    most_titles: list[dict] = field(default_factory=list)
    # Raw Cricsheet spellings folded into this tournament. Shown because an
    # alias is a judgement, and a reader who disagrees can see what was merged.
    source_names: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _event_rows(db: Session, gender: str, competition_type: str | None):
    stmt = (
        select(
            Match.event_name,
            Match.gender,
            Competition.key,
            Competition.display_name,
            Competition.type,
            Match.season_label,
            Match.match_id,
            Match.team1_id,
            Match.team2_id,
            Match.match_date_start,
            Match.event_stage,
            Match.winner_team_id,
            Match.eliminator_team_id,
            Match.venue,
        )
        .join(Competition, Competition.competition_id == Match.competition_id)
        .where(Match.event_name.is_not(None), Match.gender == gender)
    )
    if competition_type:
        stmt = stmt.where(Competition.type == competition_type)
    return db.execute(stmt).all()


def _group(rows) -> dict:
    """Fold raw event names into canonical tournaments.

    Grouping happens in Python rather than SQL because the alias map is a dict
    lookup, the same reason `queries._batting_aggregate_rows` computes averages
    in Python after a GROUP BY. The row count here is one per match, so this is
    a scan over ~10k tuples.
    """
    out: dict = defaultdict(lambda: {
        "matches": set(), "sides": set(), "editions": defaultdict(lambda: {
            "matches": set(), "sides": set(), "dates": [], "final": None,
            "venues": set(),
        }),
        "dates": [], "raw_names": set(), "competition": None,
        "side_ids": set(),
    })
    for (name, gender, ckey, cname, ctype, season, match_id, t1, t2,
         date, stage, winner, eliminator, venue) in rows:
        canonical = events_mod.canonical_event(name, gender, ckey)
        if not canonical:
            continue
        key = (canonical, gender, ckey)
        bucket = out[key]
        bucket["competition"] = (cname, ctype)
        bucket["raw_names"].add(name)
        bucket["matches"].add(match_id)
        bucket["sides"].update(x for x in (t1, t2) if x)
        if date:
            bucket["dates"].append(date)

        bucket["side_ids"].update(x for x in (t1, t2) if x)
        ed = bucket["editions"][season]
        ed["matches"].add(match_id)
        ed["sides"].update(x for x in (t1, t2) if x)
        if date:
            ed["dates"].append(date)
        if venue:
            ed["venues"].add(venue)
        # Only a match Cricsheet marks as the Final decides an edition.
        if stage == "Final":
            ed["final"] = (winner, eliminator, t1, t2)
    return out


def _edition(season, data, team_names) -> Edition:
    dates = sorted(data["dates"])
    winner_id = runner_up = None
    tiebreak = False
    if data["final"]:
        winner, eliminator, t1, t2 = data["final"]
        # A tied final has no `winner`; the side that took the tiebreak is in
        # `eliminator`. Without this the 2019 World Cup shows no champion.
        winner_id = winner or eliminator
        tiebreak = winner is None and eliminator is not None
        if winner_id:
            other = t2 if winner_id == t1 else t1
            runner_up = team_names.get(other)
    return Edition(
        season=season,
        matches=len(data["matches"]),
        sides=len(data["sides"]),
        first_date=dates[0] if dates else None,
        last_date=dates[-1] if dates else None,
        winner_team_id=winner_id,
        winner_name=team_names.get(winner_id) if winner_id else None,
        runner_up_name=runner_up,
        has_final=data["final"] is not None,
        decided_by_tiebreak=tiebreak,
        venues=sorted(data["venues"]),
    )


def list_tournaments(
    db: Session, gender: str, competition_type: str | None = None
) -> list[TournamentSummary]:
    """Multi-team events only, flagship ICC tournaments first."""
    grouped = _group(_event_rows(db, gender, competition_type))
    team_names = {t.team_id: t.name for t in db.execute(select(Team)).scalars()}

    out: list[TournamentSummary] = []
    for (name, g, ckey), data in grouped.items():
        if len(data["sides"]) < MIN_SIDES:
            continue
        cname, ctype = data["competition"]
        editions = {
            season: _edition(season, ed, team_names)
            for season, ed in data["editions"].items()
        }
        latest = max(
            editions.values(),
            key=lambda e: (e.last_date or "", e.season or ""),
            default=None,
        )
        dates = sorted(data["dates"])
        out.append(TournamentSummary(
            name=name,
            slug=events_mod.slug(name),
            gender=g,
            competition_key=ckey,
            competition_name=cname,
            competition_type=ctype,
            is_icc=name in events_mod.ICC_EVENTS,
            is_flagship=name in events_mod.FLAGSHIP,
            matches=len(data["matches"]),
            sides=len(data["sides"]),
            editions=len(editions),
            first_date=dates[0] if dates else None,
            last_date=dates[-1] if dates else None,
            latest_season=latest.season if latest else None,
            latest_winner=latest.winner_name if latest else None,
        ))

    # Flagship events first, then by how much cricket they hold. Ordering only:
    # nothing is hidden for not being a flagship, and the list says how many
    # tournaments it holds so the tail is visibly there.
    out.sort(key=lambda t: (not t.is_flagship, not t.is_icc, -t.matches))
    return out


def get_tournament(
    db: Session, slug: str, gender: str, competition_type: str | None = None
) -> TournamentDetail | None:
    """One tournament: its editions, its champions, and who scored the runs."""
    grouped = _group(_event_rows(db, gender, competition_type))
    team_names = {t.team_id: t.name for t in db.execute(select(Team)).scalars()}

    match = None
    for key, data in grouped.items():
        if events_mod.slug(key[0]) == slug and len(data["sides"]) >= MIN_SIDES:
            # Ties broken on volume: a slug is lossy, and if two canonical
            # names ever collided the larger is the one a reader meant.
            if match is None or len(data["matches"]) > len(grouped[match]["matches"]):
                match = key
    if match is None:
        return None

    data = grouped[match]
    name, g, ckey = match
    cname, ctype = data["competition"]
    editions = sorted(
        (_edition(season, ed, team_names) for season, ed in data["editions"].items()),
        key=lambda e: (e.first_date or "", e.season or ""),
        reverse=True,
    )

    # Titles per side, counted only from editions whose final we hold.
    titles: dict[str, int] = defaultdict(int)
    for e in editions:
        if e.winner_name:
            titles[e.winner_name] += 1

    match_ids = data["matches"]
    scorers, takers = _leaderboards(db, match_ids)

    latest = editions[0] if editions else None
    dates = sorted(data["dates"])
    notes = _notes(name, g, editions, data, team_names)

    return TournamentDetail(
        name=name,
        slug=events_mod.slug(name),
        gender=g,
        competition_key=ckey,
        competition_name=cname,
        competition_type=ctype,
        is_icc=name in events_mod.ICC_EVENTS,
        is_flagship=name in events_mod.FLAGSHIP,
        matches=len(match_ids),
        sides=len(data["sides"]),
        editions=len(editions),
        first_date=dates[0] if dates else None,
        last_date=dates[-1] if dates else None,
        latest_season=latest.season if latest else None,
        latest_winner=latest.winner_name if latest else None,
        editions_detail=editions,
        top_run_scorers=scorers,
        top_wicket_takers=takers,
        most_titles=[
            {"team": team, "titles": n}
            for team, n in sorted(titles.items(), key=lambda x: (-x[1], x[0]))
        ],
        source_names=sorted(data["raw_names"]),
        notes=notes,
    )


def _leaderboards(db: Session, match_ids: set[str]) -> tuple[list[dict], list[dict]]:
    """Runs and wickets across every edition of one tournament.

    Career totals within the tournament, deliberately unadjusted for opposition
    strength. Every other board in this product carries that adjustment, and
    this one does not for the same reason conventional averages do not: a
    tournament's leading run-scorer is a published, checkable figure, and a
    version of it weighted by a fitted model would not match any source.
    """
    if not match_ids:
        return [], []
    ids = list(match_ids)

    def totals_by_player():
        # SQLite caps a statement's variables, and a big tournament is 357
        # matches, so the IN list is chunked rather than assumed to fit.
        totals: dict[str, list] = defaultdict(lambda: [0, 0, 0, 0])
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            stmt = (
                select(
                    PlayerMatchStat.player_identifier,
                    func.sum(PlayerMatchStat.runs_scored),
                    func.sum(PlayerMatchStat.wickets_taken),
                    func.count(func.distinct(PlayerMatchStat.match_id)),
                    func.sum(PlayerMatchStat.dismissals),
                )
                .where(
                    PlayerMatchStat.match_id.in_(chunk),
                    PlayerMatchStat.player_identifier.is_not(None),
                )
                .group_by(PlayerMatchStat.player_identifier)
            )
            for pid, runs, wkts, matches, outs in db.execute(stmt).all():
                t = totals[pid]
                t[0] += runs or 0
                t[1] += wkts or 0
                t[2] += matches or 0
                t[3] += outs or 0
        return totals

    totals = totals_by_player()
    names = {
        p.identifier: preferred_name(p.name, p.display_name)
        for p in db.execute(select(Player)).scalars()
    }

    scorers = sorted(totals.items(), key=lambda x: -x[1][0])[:TOP_N]
    takers = sorted(totals.items(), key=lambda x: -x[1][1])[:TOP_N]
    return (
        [
            {
                "player_identifier": pid,
                "player_name": names.get(pid, pid),
                "matches": t[2],
                "runs": t[0],
                # Average is runs / dismissals, not runs / innings: a Test can
                # dismiss a player twice, which is why `dismissals` is a count.
                "average": round(t[0] / t[3], 2) if t[3] else None,
            }
            for pid, t in scorers if t[0] > 0
        ],
        [
            {
                "player_identifier": pid,
                "player_name": names.get(pid, pid),
                "matches": t[2],
                "wickets": t[1],
            }
            for pid, t in takers if t[1] > 0
        ],
    )


def _notes(
    name: str, gender: str, editions: list[Edition], data: dict, team_names: dict
) -> list[str]:
    """What this page cannot tell you, stated rather than left to be assumed."""
    notes: list[str] = []

    # The single largest coverage gap in this dataset, and it is explainable
    # rather than random. Cricsheet has withdrawn ALL Afghanistan ball-by-ball
    # data - not just recent matches, the whole record - in protest at the
    # ICC's treatment of Afghan women's cricket. Zero Afghanistan matches come
    # from Cricsheet here; the handful in the database arrive through the ICC
    # scorecard fallback. So a global event Afghanistan competed in is short by
    # every one of their matches, and the side simply does not appear.
    sides = {team_names.get(i) for i in data.get("side_ids", set())}
    last = max((e.last_date or "" for e in editions), default="")
    # Men's only. Afghanistan have never played women's international cricket -
    # the Taliban banned it - so saying they "competed in recent editions" of a
    # women's tournament would be a straightforwardly false statement, and this
    # note was making exactly that claim on the women's T20 World Cup page.
    if (
        gender == "male"
        and name in events_mod.FLAGSHIP
        and "Afghanistan" not in sides
        and last >= AFGHANISTAN_QUALIFIED_FROM
    ):
        notes.append(
            "Afghanistan does not appear in this tournament even though they "
            "competed in its recent editions. Cricsheet has withdrawn their "
            "entire ball-by-ball record in protest at the ICC's treatment of "
            "Afghan women's cricket, so their matches are absent from the "
            "source rather than missing from this ingestion. Editions they "
            "played in are short by roughly one side's worth of matches."
        )

    missing = [e for e in editions if not e.has_final]
    if missing:
        seasons = ", ".join(e.season or "?" for e in missing[:6])
        more = f" and {len(missing) - 6} more" if len(missing) > 6 else ""
        notes.append(
            f"No final is held for {len(missing)} of {len(editions)} editions "
            f"({seasons}{more}), so their champion is not shown. Cricsheet does "
            f"not carry every match of every edition, and a winner is only ever "
            f"read from the match it marks as the Final - never guessed from "
            f"whichever match happens to be last."
        )

    tiebreaks = [e for e in editions if e.decided_by_tiebreak]
    if tiebreaks:
        notes.append(
            "Decided on a tiebreak rather than a result: "
            + ", ".join(f"{e.season} ({e.winner_name})" for e in tiebreaks)
            + ". Cricsheet records these as a tie with no winner, so the "
            "champion comes from the eliminator instead."
        )

    if len(data["raw_names"]) > 1:
        notes.append(
            f"Cricsheet spells this tournament {len(data['raw_names'])} ways "
            f"across its editions, and they are merged here: "
            + ", ".join(f'"{n}"' for n in sorted(data["raw_names"]))
            + ". Editions are disjoint in time and the finalists match the "
            "tournament's honours, which is what the merge was checked against."
        )

    return notes

"""Pure parsing for ICC's per-match scorecard feed.

Why this exists: Cricsheet publishes its archives in bulk every few days, so
`matches` runs days-to-weeks behind real cricket. ICC's own match centre serves
a completed scorecard within hours, which closes that gap.

What it is NOT: a replacement for Cricsheet. These are ICC's *computed* figures,
not ones this project derived from ball-by-ball, and they arrive with no
deliveries at all. Everything parsed here is marked `source='icc'` on the match
so a reader (and every future query) can tell the two apart, and Cricsheet
supersedes an ICC row for the same real-world match when it eventually lands.

Three shapes in the feed that will silently corrupt figures if mishandled:

* **Every numeric field is a string.** `Runs: '21'`, `Balls_Bowled: '54'`.
* **`Dismissal` has three states, not two.** A real dismissal ('caught',
  'bowled', 'lbw', ...), the literal `'not out'`, and **empty**, which means
  *did not bat* in that innings. Counting 'not out' or empty as a dismissal
  wrecks every batting average; a Test scorecard here carries 8 empties.
* **A player appears once per innings.** In a Test that means the same batter
  has two rows, so figures must be summed across innings and `dismissals` is a
  count (0-2), exactly as Cricsheet's parser treats it.
"""
import re
from dataclasses import dataclass, field

from enrichment import match_key, normalize

# Dismissal strings that mean the batter was not dismissed. Anything else that
# is non-empty is a genuine dismissal and counts toward the batting average.
NOT_DISMISSED = {"not out", "notout", "retired hurt", "retired not out"}


def _int(value, default: int = 0) -> int:
    """The feed ships every number as a string, and '' for did-not-bat."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _text(value) -> str | None:
    text = (str(value).strip() if value is not None else "")
    return text or None


@dataclass
class IccPlayerStat:
    icc_player_id: str
    name_full: str
    name_short: str | None
    team_icc_id: str
    runs_scored: int = 0
    balls_faced: int = 0
    fours: int = 0
    sixes: int = 0
    dismissals: int = 0
    wickets_taken: int = 0
    balls_bowled: int = 0
    runs_conceded: int = 0
    # Facts Cricsheet does not carry. Recorded because the feed states them
    # outright, rather than inferred -- squad.py currently lists all three as
    # underivable.
    is_keeper: bool = False
    is_captain: bool = False
    batting_position: int | None = None
    stated_role: str | None = None


@dataclass
class IccParsedMatch:
    icc_match_id: str
    match_type: str | None
    gender: str | None
    series_name: str | None
    match_number: str | None
    match_date: str | None
    venue: str | None
    city: str | None
    team_a_icc_id: str | None
    team_a_name: str | None
    team_b_icc_id: str | None
    team_b_name: str | None
    result_text: str | None
    status: str | None
    is_complete: bool = False
    players: list[IccPlayerStat] = field(default_factory=list)


def us_date_to_iso(value: str | None) -> str | None:
    """'8/13/2026' -> '2026-08-13'. Same US format the schedule feed uses."""
    if not value:
        return None
    parts = str(value).split("T")[0].split("/")
    if len(parts) != 3:
        return None
    month, day, year = parts
    if not (month.isdigit() and day.isdigit() and year.isdigit()):
        return None
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


# ICC's own league ids. 10 is the women's international league; 1 and 9 are the
# men's ones the site requests together (`league_ids=1,9,10`).
WOMENS_LEAGUE_IDS = {"10"}
MENS_LEAGUE_IDS = {"1", "9"}


def scorecard_gender(league: str | None, league_id: str | None = None) -> str | None:
    """Gender of a scorecard, from whichever field actually carries it.

    `League` is NOT reliable: a women's ODI reads 'womens_international', but
    the Australia-Bangladesh Test reads plain 'icc', which names no gender at
    all. `League_Id` is the field that always distinguishes them, so it is
    checked first and the string only used as a fallback.

    Returns None rather than guessing. Callers ingesting from our own fixtures
    table should pass that row's gender instead, since it is already derived
    from the schedule feed's explicit '- m' / '- w' suffix.
    """
    lid = (str(league_id).strip() if league_id is not None else "")
    if lid in WOMENS_LEAGUE_IDS:
        return "female"
    if lid in MENS_LEAGUE_IDS:
        return "male"

    text = (league or "").lower()
    # Order matters: "women" contains "men".
    if "women" in text or text.rstrip().endswith("- w"):
        return "female"
    if "men" in text or text.rstrip().endswith("- m"):
        return "male"
    return None


def build_register_index(register_rows: list[dict]) -> dict:
    """Index Cricsheet's people register for ICC-name lookup.

    This is the load-bearing choice in the whole ICC path. Cricsheet withholds
    Afghanistan *match* data but still publishes the people register, so an
    Afghan player resolves to their real Cricsheet identifier rather than a
    synthetic one. Two things follow:

    * when Cricsheet restores those matches, they land on the SAME player rows
      and career totals merge with no reconciliation step;
    * the register carries key_cricinfo, so Wikidata bios, photos and display
      names work for these players immediately.

    Minting `icc-<id>` identifiers instead would create a parallel player
    universe that could never be merged back.
    """
    index = {"name": {}, "key": {}, "meta": {}}
    for row in register_rows:
        identifier = (row.get("identifier") or "").strip()
        if not identifier:
            continue
        index["meta"][identifier] = {
            "name": (row.get("name") or "").strip(),
            "cricinfo_id": (row.get("key_cricinfo") or "").strip() or None,
        }
        for field in ("name", "unique_name"):
            value = (row.get(field) or "").strip()
            if not value:
                continue
            index["name"].setdefault(normalize(value), set()).add(identifier)
            k = match_key(value)
            if k:
                index["key"].setdefault(k, set()).add(identifier)
    return index


def resolve_register_player(index: dict, name_full: str) -> str | None:
    """Cricsheet identifier for an ICC scorecard name, or None when unsure.

    Exact name first, then (surname, first initial) to absorb transliteration
    drift. Anything matching more than one person stays unresolved: the
    register genuinely contains two different players called "Ziaur Rahman",
    and guessing between them would attribute a career to the wrong human.
    """
    if not name_full:
        return None
    hit = index["name"].get(normalize(name_full), set())
    if len(hit) == 1:
        return next(iter(hit))
    k = match_key(name_full)
    if k:
        hit = index["key"].get(k, set())
        if len(hit) == 1:
            return next(iter(hit))
    return None


# Sides the two feeds spell differently. Curated, not fuzzy-matched, for the
# reason `venues.py` and `events.py` both give: a name is not evidence, and an
# automatic rule would eventually merge two real sides.
#
# Measured: after the cross-source cleanup ran over every match, 9 duplicate
# fixtures remained and every one of them was a spelling difference in this
# list. ICC writes the country's current official name where Cricsheet uses
# the older English one, and appends "Cricket" to some association names.
_TEAM_SPELLINGS = {
    "turkiye": "turkey",
    "france cricket": "france",
    "czechia": "czech republic",
    "hong kong, china": "hong kong",
    "usa": "united states of america",
}


def _match_side(name: str | None) -> str:
    """One side's name, reduced to a form both feeds agree on."""
    cleaned = re.sub(r"\s+", " ", (name or "")).strip().lower()
    return _TEAM_SPELLINGS.get(cleaned, cleaned)


def natural_key(gender: str | None, competition: str | None, date: str | None,
                team_a: str | None, team_b: str | None) -> str:
    """Identity of a real-world match, independent of which source described it.

    Team names are sorted because the two feeds disagree about which side is
    listed first, and a key that flipped with the listing order would fail to
    match the very rows it exists to deduplicate.

    They are also lower-cased and run through `_TEAM_SPELLINGS`, because
    sorting alone was not enough: 9 fixtures survived deduplication as
    Cricsheet/ICC pairs purely because one feed said "Turkiye" or "France
    Cricket" where the other said "Turkey" or "France". Those pairs counted
    twice in every aggregate that reads `matches`.

    Note this changes the key for EVERY match, so an existing database keeps
    its old keys until each match is next parsed. That is why the cleanup also
    runs from the Cricsheet side on every ingest rather than only at insert.
    """
    sides = sorted(filter(None, [_match_side(team_a), _match_side(team_b)]))
    return "|".join([gender or "", competition or "", date or "", *sides])


def build_player_index(rows: list[tuple]) -> dict:
    """Index our players for ICC-name lookup.

    `rows` is (identifier, name, display_name, gender). Two tiers, because the
    two sources agree on spelling more often than on format:

    * exact Wikidata display name -- "Steve Smith" is stored verbatim, so 20 of
      22 players in a Test squad hit this outright;
    * (surname, first initial), which survives the transliteration differences
      that break exact matching: ICC's "Mehidy Hasan Miraz" against Cricsheet's
      "Meh**e**di", "Ebad**o**t Hossain" against "Ebad**a**t".

    Identifiers are deduped per key: a player whose `name` and `display_name`
    reduce to the same key would otherwise look like two candidates and be
    thrown away as ambiguous.
    """
    index = {"display": {}, "key": {}}
    for identifier, name, display_name, gender in rows:
        if display_name:
            index["display"].setdefault((gender, normalize(display_name)), set()).add(identifier)
        for candidate in (name, display_name):
            k = match_key(candidate or "")
            if k:
                index["key"].setdefault((gender, k[0], k[1]), set()).add(identifier)
    return index


def resolve_icc_player(index: dict, name_full: str, gender: str | None) -> str | None:
    """Our identifier for an ICC scorecard player, or None when unsure.

    Matches on Name_Full only. Name_Short is deliberately NOT used as a fallback:
    it is not a consistent convention -- "E Hossain" looks like initials but
    "Hasan Miraz" is a shortened given name, and keying off it silently produces
    the wrong initial and therefore no match (or worse, someone else's).
    """
    if not name_full:
        return None
    hit = index["display"].get((gender, normalize(name_full)), set())
    if len(hit) == 1:
        return next(iter(hit))

    k = match_key(name_full)
    if k:
        hit = index["key"].get((gender, k[0], k[1]), set())
        if len(hit) == 1:
            return next(iter(hit))
    return None


def parse_scorecard(
    game_id: str, payload: dict, gender_hint: str | None = None
) -> IccParsedMatch | None:
    """ICC scorecard JSON -> one match with per-player totals summed over innings.

    `gender_hint` comes from our `fixtures` row when ingesting, which is the
    authoritative signal: it is derived from the schedule feed's explicit
    '- m' / '- w' comp_type suffix rather than inferred from the scorecard.
    """
    data = (payload or {}).get("data") or {}
    detail = data.get("Matchdetail") or {}
    match = detail.get("Match") or {}
    if not match:
        return None

    teams = data.get("Teams") or {}
    series = detail.get("Series") or {}
    venue = detail.get("Venue") or {}

    # Seed every named squad member, so a player who did not bat or bowl still
    # registers as having played -- the same rule the Cricsheet parser follows.
    stats: dict[str, IccPlayerStat] = {}
    for team_id, team in teams.items():
        for pid, p in (team.get("Players") or {}).items():
            stats[pid] = IccPlayerStat(
                icc_player_id=pid,
                name_full=_text(p.get("Name_Full")) or _text(p.get("Name_Short")) or pid,
                name_short=_text(p.get("Name_Short")),
                team_icc_id=team_id,
                is_keeper=bool(p.get("Iskeeper")),
                is_captain=bool(p.get("Iscaptain")),
                batting_position=_int(p.get("Position"), 0) or None,
                stated_role=_text(p.get("Role")) or _text(p.get("Skill_Name")),
            )

    for innings in data.get("Innings") or []:
        for b in innings.get("Batsmen") or []:
            pid = _text(b.get("Batsman"))
            if pid is None:
                continue
            s = stats.get(pid)
            if s is None:
                # A player in the scorecard but not the squad block. Keep them
                # rather than dropping runs on the floor.
                s = stats[pid] = IccPlayerStat(
                    icc_player_id=pid, name_full=pid, name_short=None,
                    team_icc_id=_text(innings.get("Battingteam")) or "",
                )
            s.runs_scored += _int(b.get("Runs"))
            s.balls_faced += _int(b.get("Balls"))
            s.fours += _int(b.get("Fours"))
            s.sixes += _int(b.get("Sixes"))
            dismissal = (_text(b.get("Dismissal")) or "").lower()
            if dismissal and dismissal not in NOT_DISMISSED:
                s.dismissals += 1

        for w in innings.get("Bowlers") or []:
            pid = _text(w.get("Bowler"))
            if pid is None:
                continue
            s = stats.get(pid)
            if s is None:
                s = stats[pid] = IccPlayerStat(
                    icc_player_id=pid, name_full=pid, name_short=None,
                    team_icc_id=_text(innings.get("Bowlingteam")) or "",
                )
            s.wickets_taken += _int(w.get("Wickets"))
            s.balls_bowled += _int(w.get("Balls_Bowled"))
            s.runs_conceded += _int(w.get("Runs"))

    team_ids = list(teams)
    home = _text(detail.get("Team_Home")) or (team_ids[0] if team_ids else None)
    away = _text(detail.get("Team_Away")) or (team_ids[1] if len(team_ids) > 1 else None)
    status = _text(detail.get("Status")) or _text(match.get("Status"))

    return IccParsedMatch(
        icc_match_id=str(game_id),
        match_type=_text(match.get("Type")),
        gender=gender_hint or scorecard_gender(match.get("League"), match.get("League_Id")),
        series_name=_text(series.get("Name")),
        match_number=_text(match.get("Number")),
        match_date=us_date_to_iso(match.get("Date")),
        venue=_text(venue.get("Name")),
        city=_text(venue.get("City")),
        team_a_icc_id=home,
        team_a_name=_text((teams.get(home) or {}).get("Name_Full")) if home else None,
        team_b_icc_id=away,
        team_b_name=_text((teams.get(away) or {}).get("Name_Full")) if away else None,
        result_text=_text(detail.get("Result")) or _text(series.get("Status")),
        status=status,
        # Only a finished match is worth storing: an in-progress one would be
        # ingested with half a scorecard and then read as a completed record.
        is_complete=(status or "").lower() in {"match ended", "completed", "result"},
        players=list(stats.values()),
    )

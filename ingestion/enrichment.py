"""Pure logic for enriching players and matching external ranking entries.

Kept free of I/O (like parsing.py) so the matching rules -- which are the part
that can silently corrupt data -- are directly testable.

The central problem here is that three sources name the same human three ways:

    Cricsheet   "TM Head"        (initials + surname)
    ICC         "Travis Head"    (given name + surname)
    Wikidata    "Travis Head"    (label)

Wikidata is joined on the ESPNcricinfo ID from Cricsheet's own people register,
so that link is exact and needs no name logic at all. ICC publishes no such ID,
so its entries are matched by name -- conservatively, and left unlinked when
ambiguous, because a wrong link is indistinguishable from a right one in the UI.
"""
import hashlib
import re
import unicodedata
from urllib.parse import quote, unquote

# Wikidata properties. P2697 is the ESPNcricinfo player ID, which is what makes
# the join exact -- Cricsheet's register supplies it for 99.8% of people.
WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
CRICSHEET_PEOPLE_REGISTER = "https://cricsheet.org/register/people.csv"

# ICC's own JSON feed, the one its rankings pages consume. comp_type carries a
# 'w' suffix for women's ('odiw'); there is no women's Test ranking, which is
# why (testw, *) is absent rather than merely empty.
ICC_RANKING_ENDPOINT = "https://assets-icc.sportz.io/cricket/v1/ranking"
ICC_CLIENT_ID = "tPZJbRgIub3Vua93/DWtyQ=="

ICC_COMP_TYPES = {
    "test": ("male", "tests"),
    "odi": ("male", "odis"),
    "t20": ("male", "t20is"),
    "odiw": ("female", "odis"),
    "t20w": ("female", "t20is"),
}
ICC_PLAYER_TYPES = ("bat", "bowl", "allrounder")
ICC_TEAM_TYPE = "team"


def icc_feeds() -> list[tuple[str, str]]:
    """Every (comp_type, type) pair ICC actually publishes."""
    return [
        (comp, typ)
        for comp in ICC_COMP_TYPES
        for typ in (*ICC_PLAYER_TYPES, ICC_TEAM_TYPE)
    ]


def normalize(text: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^\w\s]", " ", stripped)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def match_key(name: str) -> tuple[str, str] | None:
    """Reduce a personal name to (surname, first-initial).

    This is the one shape both conventions collapse to:

        "TM Head"     -> ("head", "t")
        "Travis Head" -> ("head", "t")
        "Babar Azam"  -> ("azam", "b")     # no initials in either source

    Returns None for single-token names, which carry too little to match on.
    """
    parts = normalize(name).split()
    if len(parts) < 2:
        return None
    surname = parts[-1]
    lead = parts[0]
    if not lead or not surname:
        return None
    return surname, lead[0]


def build_name_index(players: list[tuple[str, str, str | None]]) -> dict:
    """Index Cricsheet players by (gender, surname, initial) -> [identifiers].

    `players` is (identifier, name, gender). Keys landing on more than one
    identifier are the ambiguous ones; resolve_player refuses those.
    """
    index: dict[tuple[str, str, str], list[str]] = {}
    for identifier, name, gender in players:
        key = match_key(name)
        if key is None:
            continue
        index.setdefault((gender or "", key[0], key[1]), []).append(identifier)
    return index


def resolve_player(
    index: dict,
    icc_name: str,
    gender: str,
    country_lookup: dict[str, set[str]] | None = None,
    icc_country: str | None = None,
) -> str | None:
    """Best-effort Cricsheet identifier for an ICC ranking entry.

    Returns None unless exactly one player matches -- or, when several do, the
    country breaks the tie unambiguously. Everything else stays unlinked: with
    "M Ali" and "MM Ali" both reducing to ("ali", "m"), guessing would attach
    one player's ICC rank to another's profile with no way for a reader to tell.
    """
    key = match_key(icc_name)
    if key is None:
        return None
    candidates = index.get((gender, key[0], key[1]), [])
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1 and country_lookup and icc_country:
        wanted = normalize(icc_country)
        narrowed = [
            ident
            for ident in candidates
            if any(wanted == normalize(t) for t in country_lookup.get(ident, ()))
        ]
        if len(narrowed) == 1:
            return narrowed[0]
    return None


def parse_people_register(csv_text: str) -> dict[str, str]:
    """identifier -> ESPNcricinfo key, from Cricsheet's people register."""
    import csv
    import io

    out: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        identifier = (row.get("identifier") or "").strip()
        cricinfo = (row.get("key_cricinfo") or "").strip()
        if identifier and cricinfo:
            out[identifier] = cricinfo
    return out


def wikidata_query(cricinfo_ids: list[str]) -> str:
    """SPARQL for one batch of ESPNcricinfo IDs.

    Only fields a source actually backs are selected. P2032 (work period end)
    is included even though barely 21 cricketers have it -- when it IS present
    it's the only thing that licenses the word "retired" anywhere in this app.
    """
    values = " ".join(f'"{cid}"' for cid in cricinfo_ids if cid.isdigit())
    return f"""SELECT ?cricinfo ?personLabel ?img ?dob ?dod ?workEnd ?birthPlaceLabel ?nationalityLabel WHERE {{
  VALUES ?cricinfo {{ {values} }}
  ?person wdt:P2697 ?cricinfo .
  OPTIONAL {{ ?person wdt:P18 ?img }}
  OPTIONAL {{ ?person wdt:P569 ?dob }}
  OPTIONAL {{ ?person wdt:P570 ?dod }}
  OPTIONAL {{ ?person wdt:P2032 ?workEnd }}
  OPTIONAL {{ ?person wdt:P19 ?birthPlace }}
  OPTIONAL {{ ?person wdt:P27 ?nationality }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}"""


# Wikimedia no longer renders arbitrary thumbnail widths -- an unlisted size
# returns "400 Use thumbnail sizes listed on https://w.wiki/GHai". Probing the
# handler directly, these are the ones it serves:
COMMONS_ALLOWED_THUMB_WIDTHS = (120, 250, 500, 960, 1280)

# 250px for an 80px avatar at 2x. It matters: P18 points at the ORIGINAL
# upload, and Joe Root's is 2568x1794 / 4.8 MB -- large enough to time out a
# page load on its own. The 250px rendition is 18.7 KB, ~256x smaller.
COMMONS_THUMB_WIDTH = 250


def commons_thumb_url(url: str | None, width: int = COMMONS_THUMB_WIDTH) -> str | None:
    """Turn a Wikidata P18 value into a small, directly-fetchable image URL.

    P18 gives `http://commons.wikimedia.org/wiki/Special:FilePath/<file>`, which
    is unhelpful twice over: it's http (blocked as mixed content on an https
    page) and it redirects to the full-size original.

    Wikimedia's real file layout is derivable rather than lookup-only -- the
    path segments are the first one and two hex digits of the MD5 of the
    underscored filename -- so the thumbnail URL is computed here instead of
    costing an API round trip per player.
    """
    if not url or "Special:FilePath/" not in url:
        return _https(url)

    filename = unquote(url.split("Special:FilePath/", 1)[1]).split("?")[0]
    filename = filename.replace(" ", "_")
    if not filename:
        return None

    if width not in COMMONS_ALLOWED_THUMB_WIDTHS:
        width = min(COMMONS_ALLOWED_THUMB_WIDTHS, key=lambda w: abs(w - width))

    digest = hashlib.md5(filename.encode("utf-8")).hexdigest()
    encoded = quote(filename)
    # Vector and multi-page sources are rasterised, so the rendition carries an
    # extra extension (Foo.svg -> 250px-Foo.svg.png).
    suffix = ".png" if filename.lower().endswith((".svg", ".pdf", ".tif", ".tiff")) else ""
    return (
        "https://upload.wikimedia.org/wikipedia/commons/thumb/"
        f"{digest[0]}/{digest[:2]}/{encoded}/{width}px-{encoded}{suffix}"
    )


def _https(url: str | None) -> str | None:
    if not url:
        return None
    return "https://" + url[len("http://") :] if url.startswith("http://") else url


# Kept as the old name so callers/tests referring to it keep working.
normalize_commons_url = commons_thumb_url


def clean_label(label: str | None) -> str | None:
    """Wikidata's label service falls back to the Q-id when no English label
    exists. A bare 'Q12345' is not a name, so it's dropped and the player keeps
    their scorecard name."""
    if not label:
        return None
    label = label.strip()
    if re.fullmatch(r"Q\d+", label):
        return None
    return label or None


def _date_only(value: str | None) -> str | None:
    """Wikidata returns full xsd:dateTime; keep the date, drop the time."""
    if not value:
        return None
    return value[:10] if len(value) >= 10 else None


def parse_wikidata_rows(payload: dict) -> dict[str, dict]:
    """SPARQL JSON -> {cricinfo_id: {bio fields}}, empty values dropped."""
    out: dict[str, dict] = {}
    for row in payload.get("results", {}).get("bindings", []):
        cricinfo = row.get("cricinfo", {}).get("value")
        if not cricinfo:
            continue
        record = {
            "display_name": clean_label(row.get("personLabel", {}).get("value")),
            "image_url": normalize_commons_url(row.get("img", {}).get("value")),
            "date_of_birth": _date_only(row.get("dob", {}).get("value")),
            "date_of_death": _date_only(row.get("dod", {}).get("value")),
            "retirement_date": _date_only(row.get("workEnd", {}).get("value")),
            "birth_place": row.get("birthPlaceLabel", {}).get("value") or None,
            "nationality": row.get("nationalityLabel", {}).get("value") or None,
        }
        if any(record.values()):
            out[cricinfo] = record
    return out


ICC_SCHEDULE_ENDPOINT = "https://assets-icc.sportz.io/cricket/v1/schedule"
# The feed paginates on `page_number`, NOT `page`. Passing `page` is silently
# ignored and every request returns the same first page -- which looks like a
# working paginated fetch while collecting one page 24 times.
ICC_SCHEDULE_PAGE_SIZE = 500


def us_date_to_iso(value: str | None) -> str | None:
    """'8/12/2026' -> '2026-08-12'. The feed ships US M/D/YYYY throughout."""
    if not value:
        return None
    parts = value.split("T")[0].split("/")
    if len(parts) != 3:
        return None
    month, day, year = parts
    if not (month.isdigit() and day.isdigit() and year.isdigit()):
        return None
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def fixture_gender(comp_type: str | None, league: str | None) -> str | None:
    """ICC suffixes comp_type with '- m' / '- w' ('ODI International - w')."""
    haystack = f"{comp_type or ''} {league or ''}".lower()
    if haystack.rstrip().endswith("- w") or "- w " in haystack or "women" in haystack:
        return "female"
    if "- m" in haystack or "men" in haystack:
        return "male"
    return None


def parse_fixture(raw: dict) -> dict | None:
    """One schedule entry -> a flat fixtures row (no result for upcoming ones)."""
    match_id = str(raw.get("match_id") or "").strip()
    if not match_id:
        return None
    comp_type = (raw.get("comp_type") or "").strip() or None
    return {
        "icc_match_id": match_id,
        "series_id": (raw.get("series_id") or "").strip() or None,
        "series_name": (raw.get("series_name") or "").strip() or None,
        "tour_name": (raw.get("tour_name") or "").strip() or None,
        "comp_type": comp_type,
        "match_type": (raw.get("match_type") or "").strip() or None,
        "gender": fixture_gender(comp_type, raw.get("league")),
        "match_number": (raw.get("match_number") or "").strip() or None,
        "match_status": (raw.get("match_status") or "").strip() or None,
        "is_upcoming": 1 if raw.get("upcoming") else 0,
        "is_live": 1 if raw.get("live") else 0,
        "start_date": us_date_to_iso(raw.get("match_date_gmt")),
        "end_date": us_date_to_iso(raw.get("end_match_date_gmt")),
        "start_time_gmt": (raw.get("match_time_gmt") or "").strip() or None,
        "venue": (raw.get("venue") or "").strip() or None,
        "country": (raw.get("country") or "").strip() or None,
        "team_a_name": (raw.get("teama") or "").strip() or None,
        "team_a_short": (raw.get("teama_short") or "").strip() or None,
        "team_b_name": (raw.get("teamb") or "").strip() or None,
        "team_b_short": (raw.get("teamb_short") or "").strip() or None,
        "match_result": (raw.get("match_result") or "").strip() or None,
        "winning_team_name": _winning_team_name(raw),
        "toss_won_by": _team_name_for_id(raw, raw.get("toss_won_by")),
        "toss_elected_to": (raw.get("toss_elected_to") or "").strip() or None,
    }


def _team_name_for_id(raw: dict, team_id) -> str | None:
    """The feed gives toss/winner as team IDs; resolve against this fixture."""
    team_id = str(team_id or "").strip()
    if not team_id:
        return None
    if team_id == str(raw.get("teama_id") or ""):
        return (raw.get("teama") or "").strip() or None
    if team_id == str(raw.get("teamb_id") or ""):
        return (raw.get("teamb") or "").strip() or None
    return None


def _winning_team_name(raw: dict) -> str | None:
    return _team_name_for_id(raw, raw.get("winning_team_id"))


def parse_icc_rankings(payload: dict) -> tuple[str, str, list[dict]]:
    """ICC feed -> (rank_type, rank_date, entries).

    The feed nests everything under a 'bat-rank' key regardless of what was
    requested -- bowling, all-rounder and team responses all arrive under that
    same name -- so the authoritative descriptor is the inner 'rank-type'.
    """
    data = (payload or {}).get("data") or {}
    if not data:
        return "", "", []
    block = data[next(iter(data))] or {}
    rank_type = block.get("rank-type") or ""
    rank_date = block.get("rank_date") or ""
    entries = []
    # ICC writes '=' in the position column for a player tied with the one
    # above, so position has to carry forward. Treating '=' as unparseable
    # silently drops every tied player -- 6 of the top 100 Test batters.
    last_position = 0
    for row in block.get("rank") or []:
        raw_position = str(row.get("no", "")).strip()
        if raw_position.isdigit():
            position = int(raw_position)
            last_position = position
        elif raw_position in ("=", "") and last_position:
            position = last_position
        else:
            continue
        points_raw = str(row.get("Points", "")).strip()
        entries.append(
            {
                "position": position,
                "icc_player_id": (row.get("Player_id") or "").strip() or None,
                "player_name": (row.get("Player-name") or "").strip(),
                "country": (row.get("Country_name") or row.get("Country") or "").strip() or None,
                "team_id": (row.get("team_id") or "").strip() or None,
                "team_name": (row.get("team_name") or "").strip(),
                "points": int(points_raw) if points_raw.isdigit() else None,
                "career_best": (row.get("careerbest") or "").strip() or None,
            }
        )
    return rank_type, rank_date, entries

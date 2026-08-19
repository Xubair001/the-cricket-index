r"""Tournament identity.

The problem
-----------
`matches.event_name` is free text from Cricsheet: 1,025 distinct strings, and
one tournament routinely appears under several of them because Cricsheet's own
naming convention changed over the years. The men's 50-over World Cup is the
clearest case, and the finalists confirm each edition is the same tournament:

    ICC World Cup           2003 (Australia beat India), 2007 (Australia)
    ICC Cricket World Cup   2011 (India), 2015 (Australia), 2023 (Australia)
    World Cup               2019 (the tied final)

Grouping the raw column would file that tournament as three, each with a third
of its history. This is the same failure `venues.py` exists to prevent, and the
same two rules apply.

Worse than renaming: SPLIT EDITIONS
------------------------------------
Cricsheet is inconsistent *within* a single edition, not only between them. The
2014 men's T20 World Cup is 31 matches under "World T20" and 1 under "ICC Men's
T20 World Cup"; the 2016 edition is 26 under "World T20" and 1 under "ICC World
Twenty20". So this is not cosmetic tidying that could be skipped - without it,
an edition page is short by however many matches landed under the other spelling.

Why aliasing is NOT automated
------------------------------
The tempting rule - merge names that share "World Cup" - is wrong, and wrong
invisibly. All of these are DIFFERENT tournaments:

    ICC Cricket World Cup                     the tournament itself
    ICC Cricket World Cup Qualifier           a separate qualifying event
    ICC Men's Cricket World Cup League 2      a separate league competition
    ICC Men's T20 World Cup Africa Region Qualifier   ... and a dozen more

"ICC Men's Cricket World Cup League 2" alone is 234 matches, more than the World
Cup proper has here. A substring rule would pour all of it into one page.

So merges are curated only, and every entry below was checked against the
edition's finalists and dates before being added. Substring similarity is used
only to REPORT candidates (`merge_candidates`), never to act on.

Scoped by gender and competition
---------------------------------
An alias key is (gender, competition key, lower-cased name), not a bare name.
Two bilateral series in this data already carry one name across both genders
("India in New Zealand ODI Series"), so an ungendered key would be wrong the
moment a tournament name were ever reused. Every alias below was verified to
be single-gender and single-competition in the current data; keying it this way
means that stays true rather than being assumed.
"""

from __future__ import annotations

import re

# Verified same-tournament aliases, keyed by (gender, competition key, raw name
# lower-cased) -> canonical display name.
#
# Each entry was confirmed by checking that the editions are disjoint in time
# and that the finalists match the real tournament's honours list. Do not add
# on the strength of the names alone.
ALIASES: dict[tuple[str, str, str], str] = {
    # Men's 50-over World Cup. Three Cricsheet spellings across six editions,
    # verified 2003 AUS, 2007 AUS, 2011 IND, 2015 AUS, 2019 ENG, 2023 AUS.
    ("male", "odis", "icc world cup"): "ICC Cricket World Cup",
    ("male", "odis", "world cup"): "ICC Cricket World Cup",
    # Men's T20 World Cup. Renamed twice, and the 2014 and 2016 editions are
    # each split across two of these spellings.
    ("male", "t20is", "icc world twenty20"): "ICC Men's T20 World Cup",
    ("male", "t20is", "world t20"): "ICC Men's T20 World Cup",
    # Women's T20 World Cup: "World Twenty20" through 2012/13, current name
    # from 2018/19.
    ("female", "t20is", "icc women's world twenty20"): "ICC Women's T20 World Cup",
    ("female", "t20is", "women's t20 world cup"): "ICC Women's T20 World Cup",
    # The women's qualifier lost its "ICC" prefix in the 2025/26 data.
    # Verified disjoint: ICC-prefixed 2019/2022/2024, bare 2025/26.
    ("female", "t20is", "women's t20 world cup qualifier"):
        "ICC Women's T20 World Cup Qualifier",
    # Women's Asia Cup under three spellings across disjoint editions:
    # ACC-prefixed 2012/13 and 2016/17, "Twenty20" 2018, bare 2008/2022/2024.
    ("female", "t20is", "women's twenty20 asia cup"): "Women's Asia Cup",
    ("female", "t20is", "asian cricket council women's twenty20 asia cup"):
        "Women's Asia Cup",
    # A FOURTH spelling of the women's T20 World Cup, and the one that hurt:
    # "Women's World T20" carries the 2014 and 2016 editions, 46 matches, and
    # without this the tournament page simply had no 2014 or 2016. Missed by
    # the substring reporter because the words are REORDERED rather than
    # extended - which is why `merge_candidates` now also compares token sets.
    ("female", "t20is", "women's world t20"): "ICC Women's T20 World Cup",
    ("female", "odis", "icc women's cricket world cup qualifier"):
        "ICC Women's World Cup Qualifier",
    # Word-order variants of the same qualifier, disjoint seasons.
    ("male", "t20is", "icc men's t20 world cup asia a qualifier"):
        "ICC Men's T20 World Cup Asia Qualifier A",
    ("male", "t20is", "icc men's t20 world cup asia b qualifier"):
        "ICC Men's T20 World Cup Asia Qualifier B",
}

# NOT aliased, and the reason is worth keeping: "ECA Men's European Cup" and
# "ECA Men's European Cup, 2026" look like the same tournament renamed, and are
# not. They are 13 Cricsheet matches and 13 ICC-sourced copies of the SAME
# fixtures, which survived cross-source deduplication because the two feeds
# spell sides differently ("Turkey" against "Turkiye", "France" against "France
# Cricket"). Merging them would present 13 real matches as 26.

# Tournaments run by the ICC, so the list can lead with them without guessing
# from the string "ICC" - which would also catch every regional qualifier and,
# on the other side, miss the Asia Cup's ACC events.
#
# Membership is about who runs the event, NOT how important it is: the World
# Cup Qualifier and the regional qualifiers are ICC events and belong here.
ICC_EVENTS = {
    "ICC Cricket World Cup",
    "ICC Men's T20 World Cup",
    "ICC Women's World Cup",
    "ICC Women's T20 World Cup",
    "ICC Champions Trophy",
    "ICC World Test Championship",
}

# Events that are a global final rather than a qualifying or development
# competition. Used only to order the list so the tournaments most people came
# looking for are at the top; nothing is hidden on the strength of it.
FLAGSHIP = ICC_EVENTS | {"Asia Cup"}


# Typographic variants that are the SAME STRING differently encoded. Applied
# automatically, unlike ALIASES: merging "Men\u2019s" with "Men's" is not a
# judgement about two tournaments being one, it is the same name written with a
# curly apostrophe. Two names in this data differ only this way, 8 matches, and
# both have a straight-apostrophe twin - so left alone they split an event in
# half for no reason a reader could ever guess at.
_TYPOGRAPHIC = {
    "\u2018": "'", "\u2019": "'",      # single quotes
    "\u201c": '"', "\u201d": '"',      # double quotes
    "\u2013": "-", "\u2014": "-",      # en/em dash
    "\u00a0": " ",                     # non-breaking space
}


def _typographic(text: str) -> str:
    for bad, good in _TYPOGRAPHIC.items():
        text = text.replace(bad, good)
    return text


def canonical_event(name: str | None, gender: str | None, competition: str | None) -> str | None:
    """The tournament this match belongs to, or None when it names no event.

    Typographically normalised, whitespace-normalised and alias-resolved.
    Nothing else: no title-casing, no stripping of "ICC", no attempt to
    shorten. The stored name is a publisher's name for a tournament and the
    only safe transformations are the ones above.
    """
    if not name:
        return None
    cleaned = re.sub(r"\s+", " ", _typographic(name)).strip()
    if not cleaned:
        return None
    key = ((gender or "").lower(), (competition or "").lower(), cleaned.lower())
    return ALIASES.get(key, cleaned)


def slug(name: str) -> str:
    """A URL-safe id for a tournament name.

    Lossy by design - "ICC Men's T20 World Cup" and a hypothetical "ICC Mens
    T20 World Cup" would collide - so the API resolves a slug by matching it
    against the canonical names actually present rather than by reversing this.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# Words that make one tournament a DIFFERENT tournament from another whose name
# it otherwise contains. `merge_candidates` uses these to keep genuine pairs out
# of the report, so the list a human reviews is short enough to actually review.
_DISTINGUISHING = (
    # Suffixes that mark a separate competition feeding the main one.
    "qualifier", "qualifying", "league", "division", "regional", "region",
    "sub regional", "sub-regional", "play-off", "playoff", "warm-up",
    "challenge", "under-19", "under 19", "u19", "youth", "development",
    "rising stars", "emerging",
    # Prefixes that make a different tournament of the same base name. All of
    # these are real pairs in this data: "Asia Cup" against "Afro-Asia Cup" and
    # "East Asia Cup", "Continental Cup" against "Africa Continental Cup".
    "afro", "east", "west", "south", "north", "africa", "asia ", "european",
    "continental", "commonwealth",
    # A tour that visited a second country is a different tour, not the same
    # one renamed: "Pakistan tour of England" against "Pakistan tour of England
    # and Scotland".
    " and ",
)


# Words that mean the same thing written two ways, folded before comparing
# token sets. Only spelling, never meaning.
_EQUIVALENT = {"twenty20": "t20", "cricket": "", "icc": "", "the": "", "of": ""}


# A name whose word ORDER carries meaning. "England tour of India" and "India
# tour of England" are opposite tours, not one tournament written two ways, so
# the reordering rule must not touch them - it fired on 250 such pairs and
# buried the handful that mattered.
_DIRECTIONAL = re.compile(r"\b(tour of|in .+ series| v | vs )\b", re.I)


def _signature(name: str) -> frozenset:
    """Order-independent token set, for catching REORDERED names."""
    text = re.sub(r"[^a-z0-9 ]", " ", _typographic(name).lower())
    words = [_EQUIVALENT.get(w, w) for w in text.split()]
    return frozenset(w for w in words if w)


def merge_candidates(names: list[str]) -> list[tuple[str, str]]:
    """Name pairs that MIGHT be one tournament, for a human to check.

    Reports, never merges. Two rules, and the second exists because the first
    was not enough:

    1. **Containment.** One name is a substring of the other. Suppressed when
       the extra text carries a `_DISTINGUISHING` word, which is what separates
       "ICC Cricket World Cup" from "... Qualifier" - the case that makes
       automatic merging unsafe.
    2. **Reordering.** The two names reduce to the same token set. Containment
       alone missed "Women's World T20" against "ICC Women's T20 World Cup",
       and that miss cost the women's T20 World Cup its 2014 and 2016 editions
       - 46 matches that were in the database the whole time.
    """
    out: list[tuple[str, str]] = []
    ordered = sorted(set(names), key=len)
    seen: set[tuple[str, str]] = set()

    for i, short in enumerate(ordered):
        low_short = short.lower()
        for long in ordered[i + 1:]:
            low_long = long.lower()
            if low_short == low_long:
                continue
            pair = (short, long)
            if low_short in low_long:
                extra = low_long.replace(low_short, " ")
                if any(word in extra for word in _DISTINGUISHING):
                    continue
                if pair not in seen:
                    seen.add(pair)
                    out.append(pair)
            elif (
                not _DIRECTIONAL.search(short)
                and not _DIRECTIONAL.search(long)
                and _signature(short) == _signature(long)
                and pair not in seen
            ):
                seen.add(pair)
                out.append(pair)
    return out

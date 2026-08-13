r"""Venue normalisation.

The problem
-----------
`matches.venue` is free text straight from Cricsheet: 593 distinct strings for
407 actual grounds. The same ground turns up as "Allan Border Field", "Allan
Border Field, Brisbane", and sometimes "Ground, City, Country". Any analytics
computed over the raw column splits one ground's history across several rows,
which is why §5 lists this as one of two traps blocking venue work, and why the
explorers shipped without a venue filter rather than with one that quietly
narrowed to a third of a ground's matches.

Two mechanisms, and the second is deliberately small
-----------------------------------------------------
1. **Comma-collapse** -- the safe, automatic rule. The text before the first
   comma is the ground; the rest is a location that `matches.city` already
   holds. This alone takes 593 strings to 407 and is the bulk of the win. It is
   safe because it only ever merges strings that share a base name.

2. **Curated aliases** -- for grounds that appear under genuinely different
   names, which no string rule can catch. §5 names the case: "Sharjah Cricket
   Stadium" and "Sharjah Cricket Association Stadium" are one ground. Sponsor
   names are the other common source ("Boland Bank Park" / "Boland Park").

Why aliasing is NOT automated
------------------------------
The obvious rule -- merge when one name contains the other -- is wrong, and
wrong in a way that would be invisible. Dubai has both "ICC Academy" and "ICC
Academy Ground No 2": one contains the other and they are *different pitches*.
Merging them would silently pool two grounds' records forever.

So substring similarity is used only to *report* candidates
(`unresolved_candidates`), never to merge them. Anything merged here was checked
against a source first. That is the same rule the rest of the product follows:
a name is not evidence, and an unverifiable match resolves to "leave them
apart" rather than to a guess.
"""

from __future__ import annotations

import re

# Verified same-ground aliases. Key and value are both post-comma-collapse base
# names, compared case-insensitively. Each entry was checked against a source
# before being added -- do not add on the strength of the names alone.
ALIASES: dict[str, str] = {
    # §5 names this pair explicitly as one ground.
    "sharjah cricket association stadium": "Sharjah Cricket Stadium",
    # Club grounds routinely written with and without the word "Ground".
    "sinhalese sports club": "Sinhalese Sports Club Ground",
    "nondescripts cricket club": "Nondescripts Cricket Club Ground",
    "colombo cricket club": "Colombo Cricket Club Ground",
    "wanderers": "Wanderers Cricket Ground",
    # Sponsor names for the same ground.
    "boland bank park": "Boland Park",
    "de beers diamond oval": "Diamond Oval",
    "the royal & sun alliance county ground": "County Ground",
    "the cooper associates county ground": "County Ground",
    # Local shorthand.
    "sylhet stadium": "Sylhet International Cricket Stadium",
    "bermuda national stadium": "National Stadium",
    "bready": "Bready Cricket Club",
    # A misspelling, not a second ground: the St Lucia venue is named for
    # Darren Sammy. 35 matches are filed under the single-R spelling and 5
    # under the correct one, so without this the ground's own records are the
    # minority of its history.
    "daren sammy national cricket stadium": "Darren Sammy National Cricket Stadium",
}

# Ground names that genuinely exist in more than one place. For these ONLY, the
# city is part of the identity and the canonical name is qualified with it.
#
# Found by scanning the data, then read rather than trusted: of 28 base names
# whose rows span cities with no shared word, most are the SAME ground with the
# place written differently -- Kensington Oval as Bridgetown or Barbados, Sabina
# Park as Kingston or Jamaica, St George's Park under Port Elizabeth and its
# current name Gqeberha, Shere Bangla under Dhaka and its Mirpur district. Those
# must still merge, so "different city" cannot be the rule.
#
# These three are the real collisions. "County Ground" is the sharpest: it is
# the name of EIGHT distinct English county grounds (Bristol, Chelmsford, Derby,
# Hove, Northampton, Taunton, Brighton, Worcester), and merging them would pool
# eight teams' home records into one.
CITY_QUALIFIED = {
    "county ground",
    "national stadium",      # Karachi and Hamilton, Bermuda
    "gymkhana club ground",  # Nairobi and Dar-es-Salaam
}

# Names that LOOK like aliases of a shorter name but are separate grounds.
# Listed explicitly so a future tidy-up cannot "simplify" them into a merge.
DISTINCT_DESPITE_SIMILARITY = {
    "icc academy ground no 2",   # a different pitch from "ICC Academy"
    "icc global cricket academy",
    # Arbab Niaz Stadium is in Peshawar; Niaz Stadium is in Hyderabad, Sindh.
    # One name contains the other and they are 1,000km apart -- the single
    # clearest reason substring similarity is reported and never applied.
    "arbab niaz stadium",
    "niaz stadium",
}

_WHITESPACE = re.compile(r"\s+")


def base_name(venue: str | None) -> str | None:
    """The ground, with any trailing location dropped.

    "Arnos Vale Ground, Kingstown, St Vincent" -> "Arnos Vale Ground".
    """
    if not venue:
        return None
    head = venue.split(",")[0]
    head = _WHITESPACE.sub(" ", head).strip()
    return head or None


def canonical(venue: str | None, city: str | None = None) -> str | None:
    """The canonical display name for a raw venue string.

    `city` is only consulted for the handful of names in `CITY_QUALIFIED`, which
    exist in more than one place. Everywhere else it is ignored on purpose: the
    city column is itself inconsistent (the same ground appears under Bridgetown
    and Barbados, Kingston and Jamaica), so using it generally would re-split
    the very grounds this module exists to join.
    """
    name = base_name(venue)
    if not name:
        return None
    key = name.lower()
    if key not in DISTINCT_DESPITE_SIMILARITY:
        name = ALIASES.get(key, name)
        key = name.lower()
    if key in CITY_QUALIFIED and city:
        return f"{name} ({city.strip()})"
    return name


def canonical_key(venue: str | None, city: str | None = None) -> str | None:
    """A stable grouping key -- what analytics should GROUP BY."""
    name = canonical(venue, city)
    return name.lower() if name else None


def unresolved_candidates(venues: list[str]) -> list[tuple[str, str]]:
    """Pairs that look like the same ground but have not been verified.

    Reported rather than merged (§29 makes data quality a monitored layer, not
    an ad-hoc script). A pair appearing here means "someone should check this",
    never "these are the same".
    """
    names = sorted({c for c in (canonical(v) for v in venues) if c})
    out: list[tuple[str, str]] = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            al, bl = a.lower(), b.lower()
            if al in DISTINCT_DESPITE_SIMILARITY or bl in DISTINCT_DESPITE_SIMILARITY:
                continue
            aw, bw = set(al.split()), set(bl.split())
            if aw < bw or bw < aw:
                out.append((a, b))
    return out


__all__ = [
    "canonical", "canonical_key", "base_name",
    "unresolved_candidates", "ALIASES", "DISTINCT_DESPITE_SIMILARITY",
]

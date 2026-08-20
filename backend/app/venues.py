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

    # ---- Added after a same-city sweep, each checked against a source -------
    #
    # The containment report cannot see any of these: they are renames,
    # abbreviations and word-order swaps, which share no substring with the name
    # they belong to. Between them 700+ matches were filed on a duplicate ground.
    #
    # Sponsorship and rebranding. Verified: the Abu Dhabi ground is published as
    # both "Sheikh Zayed Stadium" and "Zayed Cricket Stadium" (155 matches split
    # 120/35), and Johannesburg's is "New Wanderers Stadium" precisely to
    # distinguish it from the historical Old Wanderers, which this dataset does
    # not hold (98 split 57/41).
    "zayed cricket stadium": "Sheikh Zayed Stadium",
    "new wanderers stadium": "The Wanderers Stadium",
    # Cairns: "Bundaberg Rum Stadium" was Cazaly's Stadium under a naming-rights
    # deal from 2001 to 2003, which is exactly when these two matches were
    # played.
    "bundaberg rum stadium": "Cazaly's Stadium",
    # Pearland, Texas: Moosa Stadium under a sponsored name.
    "choice moosa stadium": "Moosa Cricket Stadium",

    # Acronyms and expansions of the same body's name. The WACA takes its name
    # from the initials of the Western Australian Cricket Association, so these
    # are one ground written two ways - 50 matches split 38/12.
    "w a c a ground": "Western Australia Cricket Association Ground",
    "waca ground": "Western Australia Cricket Association Ground",
    "vra cricket ground": "VRA Ground",
    # Nagpur's OLD ground, in Civil Lines. Deliberately NOT merged with
    # "Vidarbha Cricket Association Stadium, Jamtha", which is the newer ground
    # a few kilometres away - see the note in DISTINCT_DESPITE_SIMILARITY.
    "vidarbha c a ground": "Vidarbha Cricket Association Ground",

    # Fuller and shorter forms of one name.
    "sher e bangla national cricket stadium": "Shere Bangla National Stadium",
    "sardar patel (gujarat) stadium": "Sardar Patel Stadium",
    "punjab cricket association is bindra stadium": "Punjab Cricket Association Stadium",
    "grange cricket club": "Grange Cricket Club Ground",
    "vassil levski national sports academy": "National Sports Academy",
    "tafawa balewa square (tbs) cricket oval": "Tafawa Balewa Square Cricket Oval",

    # Bangi, Malaysia: the same sponsor pair written in both orders, splitting
    # the ground 40/37.
    "ysd ukm cricket oval": "UKM-YSD Cricket Oval",

    # Kigali: a FULL STOP where every other row has a comma, so the trailing
    # ", Rwanda" is not stripped and 181 matches split 104/77. Not a rename at
    # all - a typo in the source that comma-collapse cannot reach, because
    # splitting on a full stop would break "R.Premadasa" and "W.A.C.A.".
    "gahanga international cricket stadium. rwanda": "Gahanga International Cricket Stadium",
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
    # Found by the cross-city check below, not by reading names: India has
    # several Nehru Stadiums and this dataset holds four of them - Kochi,
    # Guwahati, Pune and Margao. Merged they were one ground with eleven matches
    # in four cities, which is the same failure "County Ground" describes.
    "nehru stadium",
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

    # ---- Checked and deliberately NOT merged --------------------------------
    #
    # Every one of these looked like an alias and is not. They are listed so a
    # future sweep cannot quietly fold them together, and because two of them
    # were caught only by checking a source against an instinct that said merge.
    #
    # Darwin: Wikipedia is explicit that Marrara Cricket Ground "should not be
    # confused with the nearby Marrara Oval (TIO Stadium)". Two grounds inside
    # one sporting complex.
    "marrara stadium",
    "marrara cricket ground",
    # Townsville: Tony Ireland Stadium and Riverway Stadium are separate venues,
    # both used for cricket in the same series.
    "riverway stadium",
    "tony ireland stadium",
    # Nagpur: the Jamtha STADIUM is the newer ground, several kilometres from the
    # Civil Lines GROUND. "Stadium" and "Ground" is the only thing telling them
    # apart, which is why the abbreviation alias above points at the Ground and
    # this one is pinned.
    "vidarbha cricket association stadium",
    # Potchefstroom: Senwes Park and the university's own No 1 ground.
    "north west cricket stadium",
    "north-west university no1 ground",
    # Queenstown: too little to go on. One match under "Davies Park" against ten
    # under "John Davies Oval", and nothing found that says they are the same
    # ground, so they stay apart. Reported by the sweep rather than merged.
    "davies park",
    "john davies oval",
}

_WHITESPACE = re.compile(r"\s+")
# Characters that carry no identity in a ground name. Used only for the
# comparison key, never for display.
_PUNCTUATION = re.compile(r"[.\-'\u2019&]")


# The three tables above are written in readable lower case with spaces, because
# that is how a human checks them. Matching happens on the punctuation-stripped
# key, so each is reindexed once here rather than normalised at every lookup.
def _key_of(name: str) -> str:
    return _PUNCTUATION.sub("", name.lower()).replace(" ", "")


_ALIAS_BY_KEY = {_key_of(k): v for k, v in ALIASES.items()}
_CITY_QUALIFIED_KEYS = {_key_of(k) for k in CITY_QUALIFIED}
_DISTINCT_KEYS = {_key_of(k) for k in DISTINCT_DESPITE_SIMILARITY}


def base_name(venue: str | None) -> str | None:
    """The ground, with any trailing location dropped.

    "Arnos Vale Ground, Kingstown, St Vincent" -> "Arnos Vale Ground".
    """
    if not venue:
        return None
    head = venue.split(",")[0]
    head = _WHITESPACE.sub(" ", head).strip()
    return head or None


def _lookup_key(name: str) -> str:
    r"""The form two spellings of one ground are compared on.

    Case, internal punctuation and spacing are stripped, because a ground being
    written with or without full stops is not two grounds. This is a
    normalisation rather than an alias, and it has to be, because the variants
    are a CLASS rather than a list. Measured over this dataset it merges:

        R Premadasa Stadium (148) with R.Premadasa Stadium (25)
        M Chinnaswamy Stadium (14) with M.Chinnaswamy Stadium (5)
        Vidarbha C.A. Ground with Vidarbha CA Ground

    Colombo's ground was the sharpest: a sixth of its history sat under the
    spelling with full stops, so a venue page keyed on the raw column showed 148
    of its 173 matches and looked complete.

    Deliberately NOT a substring or fuzzy rule - it only removes characters that
    carry no identity. "Niaz Stadium" and "Arbab Niaz Stadium" still differ here,
    which is the property that keeps two grounds 1,000km apart separate.
    """
    return _PUNCTUATION.sub("", name.lower()).replace(" ", "")


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
    # Normalise the DISPLAY form as well as the lookup, or a punctuation variant
    # resolves to the same ground and then labels it differently, putting two
    # rows in the ground list with one key between them. Only eight raw
    # spellings here contain a full stop and every one is initials, so turning
    # "R.Premadasa Stadium" into "R Premadasa Stadium" is safe - and it matches
    # how this product already writes initials elsewhere ("JE Root").
    name = _WHITESPACE.sub(" ", name.replace(".", " ")).strip()
    # Punctuation-insensitive throughout, so a spelling that differs only by a
    # full stop resolves to the same ground and to the same alias entry.
    key = _lookup_key(name)
    if key not in _DISTINCT_KEYS:
        name = _ALIAS_BY_KEY.get(key, name)
        key = _lookup_key(name)
    if key in _CITY_QUALIFIED_KEYS and city:
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

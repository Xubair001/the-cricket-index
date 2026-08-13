"""Which name to show a player by.

Two names exist for each player and neither is wrong:

* `players.name` is Cricsheet's scorecard form -- every initial, then surname
  (`JE Root` = Joseph Edward Root). This is the Wisden/CricketArchive
  convention, not stale data.
* `players.display_name` is the Wikidata label, present for 4,119 of 9,442.

The obvious rule -- prefer the Wikidata label whenever there is one -- is wrong,
and produces names no cricket source uses:

    Babar Azam    -> Mohammad Babar Azam
    Imran Khan    -> Mohammad Imran Khan
    Liton Das     -> Litton Das

Wikidata holds a *formal* name. Where the scorecard form is already a natural
name, the label adds a legal forename or a transliteration variant and makes the
name less recognisable, not more. Where the scorecard form is initials, the
label is exactly what's needed:

    JE Root         -> Joe Root
    HMRKB Herath    -> Rangana Herath
    PADLR Sandakan  -> Lakshan Sandakan

So the label is used only when the scorecard name actually needs expanding --
when its first token is initials. Measured over this dataset that is 3,103 of
the 4,119 players who have a label; the other 1,016 keep their scorecard name,
and 102 of those would otherwise have been renamed to something wrong.

Known limit: a handful of players are best known *by* their initials
(`MS Dhoni`, `AB de Villiers`). This rule expands those to the Wikidata label.
Nothing in the data distinguishes them from `JE Root`, where expanding is
clearly right, so the sourced label is preferred over guessing.
"""

from __future__ import annotations

import re

# Cricsheet initials run longer than two letters for Sri Lankan names in
# particular -- `CBRLS Kumara`, `HMRKB Herath`, `PADLR Sandakan` -- so this
# deliberately allows up to eight. A narrower bound silently classifies those as
# natural names and leaves them displayed as initials.
_INITIALS = re.compile(r"^[A-Z]{1,8}$")


def is_scorecard_initials(scorecard_name: str | None) -> bool:
    """True when the name's first token is an initials cluster, not a word."""
    if not scorecard_name:
        return False
    head = scorecard_name.split()
    return bool(head) and bool(_INITIALS.match(head[0]))


def preferred_name(scorecard_name: str | None, display_name: str | None) -> str | None:
    """The name to show, given both forms.

    Falls back through display -> scorecard so a player missing either one still
    gets a name rather than nothing.
    """
    if scorecard_name and display_name:
        return display_name if is_scorecard_initials(scorecard_name) else scorecard_name
    return display_name or scorecard_name

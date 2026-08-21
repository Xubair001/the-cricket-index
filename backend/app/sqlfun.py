"""Portable spellings of SQL constructs the analytics layer needs.

§24 requires no SQLite-specific SQL in the analytics layer, so that a move to
Postgres is a connection change. That held for everything except one function:
`iif(condition, then, else)`, which is SQLite's and which twenty-odd aggregate
expressions across six analytics modules were built on. Postgres has no `iif`
at all, so every one of those queries failed with

    UndefinedFunction: function iif(boolean, integer, integer) does not exist

`CASE WHEN` is the standard spelling and runs unchanged on both, which is why
this is a translation rather than a dialect branch: there is no version of this
that needs to know which database it is talking to.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import case


def iif(condition: Any, then: Any, otherwise: Any = None):
    """`CASE WHEN condition THEN then ELSE otherwise END`.

    Keeps the argument order of the SQLite function it replaces, so the call
    sites read the same as before and the swap is reviewable line by line.
    """
    return case((condition, then), else_=otherwise)

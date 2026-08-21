"""Period windows -- the vocabulary for "when".

Rule 3 of the product philosophy is that career performance and current form are
different things, so a period is a first-class argument everywhere in the
analytics layer rather than an optional filter bolted on at the end.

Two kinds of window exist and they are not interchangeable:

* **Date-bounded** ("last 6 months", a season, a custom range) can be pushed
  down into SQL and applied to every player in one query.
* **Count-bounded** ("last 10 matches") cannot. Each player's tenth-most-recent
  match is a different date, so the window has to be cut per player after their
  matches are ordered.

`to_date_bounds()` returns None for the count-bounded kinds; callers use that to
decide which path they're on rather than guessing from the spec string.

Anchoring
---------
Relative windows are measured from the newest match **in the dataset**, not from
today. This matches how `queries.player_status` already decides who is active,
and for the same reason: anchoring to now means the day the Cricsheet archive
goes stale, every current player silently drops out of "last 30 days" and the
product starts reporting a data-freshness problem as though it were a fact about
cricket.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

CAREER = "career"
LAST_MATCHES = "last_matches"
LAST_DAYS = "last_days"
SEASON = "season"
CUSTOM = "custom"


@dataclass(frozen=True)
class Period:
    kind: str
    label: str
    matches: int | None = None
    days: int | None = None
    season_label: str | None = None
    start: str | None = None
    end: str | None = None

    @property
    def is_count_bounded(self) -> bool:
        return self.kind == LAST_MATCHES

    def to_date_bounds(self, anchor: str | None) -> tuple[str | None, str | None] | None:
        """(start, end) ISO dates, or None when the window can't be expressed as dates.

        `anchor` is the dataset's newest match date; a relative window is
        meaningless without it, so those degrade to career rather than silently
        measuring from an arbitrary point.
        """
        if self.kind == CAREER:
            return (None, None)
        if self.kind == CUSTOM:
            return (self.start, self.end)
        if self.kind == SEASON:
            return (None, None)  # applied as a season_label filter, not a date range
        if self.kind == LAST_DAYS:
            if not anchor:
                return (None, None)
            try:
                end = date.fromisoformat(anchor[:10])
            except ValueError:
                return (None, None)
            return ((end - timedelta(days=self.days or 0)).isoformat(), end.isoformat())
        return None


# The windows the product offers by default. Exposed over the API so the UI
# renders whatever the analytics layer actually supports instead of keeping its
# own copy of this list that can drift out of step.
PRESETS: dict[str, Period] = {
    "career": Period(CAREER, "Career"),
    "last5": Period(LAST_MATCHES, "Last 5 matches", matches=5),
    "last10": Period(LAST_MATCHES, "Last 10 matches", matches=10),
    "last20": Period(LAST_MATCHES, "Last 20 matches", matches=20),
    "last30d": Period(LAST_DAYS, "Last 30 days", days=30),
    "last3m": Period(LAST_DAYS, "Last 3 months", days=91),
    "last6m": Period(LAST_DAYS, "Last 6 months", days=182),
    "last12m": Period(LAST_DAYS, "Last 12 months", days=365),
}


class PeriodError(ValueError):
    """Raised for a period spec that cannot be parsed."""


def parse(spec: str | None) -> Period:
    """Parse a URL-safe period spec.

    Accepts a preset key, `season:<label>`, or `custom:<start>:<end>`. Keeping
    the whole window in one string is what lets an analysis URL be copied to a
    colleague and land on exactly the same numbers.
    """
    if not spec:
        return PRESETS["career"]

    spec = spec.strip()
    if spec in PRESETS:
        return PRESETS[spec]

    if spec.startswith("season:"):
        label = spec[len("season:"):].strip()
        if not label:
            raise PeriodError("season period needs a label, e.g. season:2024")
        return Period(SEASON, f"Season {label}", season_label=label)

    if spec.startswith("custom:"):
        parts = spec.split(":")
        if len(parts) != 3:
            raise PeriodError("custom period must be custom:<start>:<end> in ISO dates")
        _, start, end = parts
        for value in (start, end):
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise PeriodError(f"'{value}' is not an ISO date (YYYY-MM-DD)") from exc
        if start > end:
            raise PeriodError("custom period start is after its end")
        return Period(CUSTOM, f"{start} to {end}", start=start, end=end)

    raise PeriodError(
        f"unknown period '{spec}'. Expected one of {sorted(PRESETS)}, "
        "season:<label>, or custom:<start>:<end>"
    )


def describe() -> list[dict]:
    """The preset windows, for the UI to render as options.

    Seasons are deliberately absent. A season here is Cricsheet's own label, not
    a calendar year, and men's Tests split across `2024` (13 matches) and
    `2024/25` (29) - so offering "2024" as an option would return a third of the
    year's cricket and look like missing data. `season:<label>` stays parseable
    so a URL naming one still resolves, and a reader who wants a calendar year
    gets an exact answer from a custom range instead.
    """
    return [
        {"key": key, "label": period.label, "kind": period.kind}
        for key, period in PRESETS.items()
    ]


def applied(period: "Period | None", anchor: str | None) -> dict:
    """What window was actually used, for the response to state.

    §30 requires a figure to be traceable to how it was produced, and a window
    is half of that: "617 runs" means nothing without knowing over what. Two
    parts of this are not cosmetic:

    * **A count-bounded window is each player's OWN last N**, so it puts a
      player's final ten Tests beside a current player's most recent ten. That
      is the honest reading of the question and it is genuinely useful, but a
      board headed "last 10 matches" reads as "recent form" - so the label says
      whose ten it is rather than leaving the reader to infer it.
    * **The resolved dates travel with a relative window.** "Last 12 months"
      is measured from the newest match in the scope, not from today, so the
      reader has to be able to see which twelve months they are looking at.
    """
    if period is None:
        return {
            "spec": None,
            "label": "Career",
            "kind": CAREER,
            "start": None,
            "end": None,
            "anchor": None,
            "note": None,
        }
    bounds = period.to_date_bounds(anchor)
    start, end = bounds if bounds else (None, None)
    note = None
    label = period.label
    if period.is_count_bounded:
        label = f"Each player's last {period.matches} matches"
        note = (
            "Counted per player, so a retired player's final matches sit "
            "beside a current player's most recent ones."
        )
    elif period.kind == LAST_DAYS:
        note = (
            "Measured back from the newest match in this scope, not from today, "
            "so the window does not move when the data goes stale."
        )
    elif period.kind == SEASON:
        note = (
            "A season is the source's own label rather than a calendar year, "
            "and a format's cricket can span two of them."
        )
    return {
        "spec": spec_of(period),
        "label": label,
        "kind": period.kind,
        "start": start,
        "end": end,
        "anchor": anchor,
        "note": note,
    }


def spec_of(period: "Period") -> str | None:
    """The URL-safe spec that would reproduce this window."""
    for key, preset in PRESETS.items():
        if preset == period:
            return key
    if period.kind == SEASON:
        return f"season:{period.season_label}"
    if period.kind == CUSTOM:
        return f"custom:{period.start}:{period.end}"
    return None

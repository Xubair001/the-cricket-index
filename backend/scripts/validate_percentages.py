r"""Assert that no figure the UI renders as a percentage can exceed 100.

Why this exists
---------------
A percentage reads as a share of something, so a reader takes anything past 100
as either a bug or a scale they have lost track of. Several figures here are
ratios against a player's own baseline and have no natural ceiling: measured
over the 711 men's international form verdicts, 22 exceeded 100% and the largest
was +306.1%. Worse, the form boards *order* on par units gained while they used
to *display* that ratio, so the column was not monotonic with its own sort - the
top row read +197.6% and the sixth read +47.5%.

`analytics/form.stamp_form_scores` fixed that by adding a bounded 0-100
`form_score`, and this script is the guard that keeps it fixed. It is a
validator rather than a unit test because the repo has no test suite; it follows
`validate_news.py`, which exists for the same reason.

Two classes of field, deliberately treated differently
------------------------------------------------------
BOUNDED   Anything the UI prints with a '%' or as a 0-100 score. Must be in
          range. A violation here is a bug.
RAW       `delta_percent`, `delta_ratio`, `form_delta` - the true unbounded
          ratio, kept so a figure stays traceable to its inputs (§30). These are
          EXPECTED to exceed 100 and are checked for the opposite thing: that a
          worded, bounded companion field travels with them, so no client is
          forced to render the raw ratio to say anything at all.

Usage
-----
    cd backend && python -m scripts.validate_percentages          # live DB
    cd backend && python -m scripts.validate_percentages --json   # for CI

Exits non-zero on any violation.
"""
from __future__ import annotations

import argparse
import json
import sys

# Fields the UI renders with a '%' sign or as an index out of 100. Bounded.
BOUNDED_SUFFIXES = ("_pct", "_percentage")
BOUNDED_NAMES = {
    "form_score",
    "confidence",
    "percentile",
    "boundary_pct",
    "dot_pct",
    "bowling_dot_pct",
    "win_pct",
    "bat_first_win_pct",
    "toss_win_pct",
    "chose_to_bat_pct",
    "versus_peers_percent",
    "index",
    "selection_score",
    "score",
}
# Confidence is a 0..1 proportion rather than a 0..100 one.
UNIT_SCALE = {"confidence"}

# Unbounded by design. Each must be accompanied by one of its companions.
RAW_COMPANIONS = {
    "delta_percent": ("form_score", "delta_display"),
    "delta_ratio": ("form_score", "delta_display"),
    "form_delta": ("form_score", "form_display"),
}


def _violations(payload, path: str = "") -> list[str]:
    """Walk a decoded JSON body and report every out-of-range display figure."""
    out: list[str] = []
    if isinstance(payload, dict):
        for name, raw in RAW_COMPANIONS.items():
            if name in payload and payload[name] is not None:
                if not any(c in payload for c in raw):
                    out.append(
                        f"{path}/{name} is an unbounded ratio and carries none of "
                        f"{raw}; a client could only render it as a percentage"
                    )
        for key, value in payload.items():
            out += _violations(value, f"{path}/{key}")
    elif isinstance(payload, list):
        # Index only the first few paths so a 500-row board reports the field
        # once rather than five hundred times.
        for i, value in enumerate(payload):
            out += _violations(value, f"{path}[{i}]" if i < 3 else f"{path}[]")
    elif isinstance(payload, (int, float)) and not isinstance(payload, bool):
        name = path.rsplit("/", 1)[-1].split("[")[0]
        bounded = name in BOUNDED_NAMES or name.endswith(BOUNDED_SUFFIXES)
        if bounded:
            ceiling = 1.0 if name in UNIT_SCALE else 100.0
            if payload > ceiling or payload < -ceiling:
                out.append(f"{path} = {payload}, outside +/-{ceiling:g}")
    return out


def _endpoints() -> list[str]:
    """The read paths that carry a rate, a score or a form figure."""
    return [
        "/api/rankings/form?gender=male&limit=100",
        "/api/rankings/form?gender=male&state=out_of_form&limit=100",
        "/api/rankings/form?gender=female&limit=100",
        "/api/rankings/form?gender=male&competition=psl&limit=100",
        "/api/rankings/performance?gender=male&limit=100",
        "/api/rankings/best-xi?gender=male&pool=current",
        "/api/rankings/best-xi?gender=male&pool=all_time",
        "/api/rankings/best-xi?gender=male&competition=psl",
        "/api/rankings/underrated?rank_type=test-batting&limit=100",
        "/api/rankings/underrated?rank_type=odi-bowling&limit=100",
        "/api/players/directory?gender=male&sort_by=form&limit=100",
        "/api/players/directory?gender=female&sort_by=form&limit=100",
        "/api/players/scout?gender=male&limit=100",
        "/api/players/scout?gender=male&competition=psl&limit=100",
        "/api/analytics/batting?gender=male&limit=100",
        "/api/analytics/bowling?gender=male&limit=100",
        "/api/analytics/allround?gender=male&limit=100",
        "/api/analytics/opposition?gender=male",
        "/api/teams?gender=male&limit=100",
        "/api/dashboard?gender=male",
        # Added with each feature below, so a new board cannot reintroduce an
        # unbounded display figure without this failing.
        "/api/rankings/best-xi?gender=male&competition=tests&objective=youth",
        "/api/rankings/best-xi?gender=male&competition=tests&objective=bowling",
        "/api/rankings/best-xi?gender=male&competition=tests&objective=experience",
        "/api/teams/22/strength?competition=t20is",
        "/api/teams/22/weakness?competition=t20is",
        "/api/icc/movement/test-batting",
        "/api/icc/movement/odiw-batting",
        "/api/tournaments/icc-cricket-world-cup/editions/2019?gender=male",
        "/api/tournaments/icc-champions-trophy/editions/2017?gender=male",
        "/api/players/ba607b88/splits?split=situation&gender=male&competition=odis",
        "/api/players/ba607b88/splits?split=phase&gender=male&competition=odis",
        "/api/players/ba607b88/form",
        "/api/players/compare?players=ba607b88,6b71e6cf,740742ef&competition=odis",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # The port CLAUDE.md documents for the API. It used to default to 8009,
    # which was a scratch port from a review session - so the script's own
    # exit code was correct (it fails on an unreachable endpoint) while its
    # summary line still read "OK", and a clean-looking run had checked nothing.
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    import urllib.error
    import urllib.request

    findings: dict[str, list[str]] = {}
    unreachable: list[str] = []
    for path in _endpoints():
        try:
            with urllib.request.urlopen(args.base + path, timeout=120) as resp:
                body = json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            unreachable.append(f"{path}: {exc}")
            continue
        found = _violations(body)
        if found:
            findings[path] = found

    if args.json:
        print(json.dumps({"violations": findings, "unreachable": unreachable}, indent=2))
    else:
        for path, found in findings.items():
            print(f"FAIL {path}")
            for line in found[:10]:
                print(f"     {line}")
        for line in unreachable:
            print(f"SKIP {line}")
        checked = len(_endpoints()) - len(unreachable)
        if findings:
            print(f"\n{len(findings)} of {checked} endpoints carry an out-of-range display figure.")
        elif unreachable:
            # Never "OK" when something could not be reached. The exit code was
            # always right; the summary line was not, and the summary is what a
            # person reads. A run that checked nothing is the case this guard
            # exists for.
            print(
                f"\nFAIL {len(unreachable)} of {len(_endpoints())} endpoints were "
                f"unreachable, so {checked} were actually checked. Is the API "
                f"running on {args.base}?"
            )
        else:
            print(f"OK  {checked} endpoints checked, no display figure outside its range.")

    # An unreachable endpoint is not a pass. Report it as a failure so a stopped
    # server cannot look like a clean run.
    return 1 if findings or unreachable else 0


if __name__ == "__main__":
    sys.exit(main())

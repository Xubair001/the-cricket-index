r"""Venue normalisation checks, as a monitored layer rather than an ad-hoc script.

§29 makes data quality something that is measured on a schedule, not something
someone remembers to look at. Venue normalisation is the part of this dataset
most likely to drift, because every new ingest can introduce a new spelling of a
ground that already exists, and nothing fails when it does - the ground simply
splits in two and both halves look complete.

Four checks, and the reason each exists is a bug it actually caught:

1. **Cross-city merge.** A canonical ground whose rows span cities sharing no
   word is either one ground written two ways (Kensington Oval as Bridgetown and
   Barbados) or two grounds wrongly merged. This is how "Nehru Stadium" was
   found spanning Kochi, Guwahati, Pune and Margao - four different Indian
   grounds pooled into one.

2. **Same-city rename and acronym candidates.** `venues.unresolved_candidates`
   compares names by containment, which cannot see a rename or an abbreviation:
   "W.A.C.A. Ground" shares no substring with "Western Australia Cricket
   Association Ground", and "Zayed Cricket Stadium" shares none with "Sheikh
   Zayed Stadium". Grouping by city and comparing distinctive tokens finds them.
   That sweep recovered 700+ matches filed on a duplicate ground record.

3. **No match is lost.** Every match carrying a venue must land in exactly one
   canonical ground. A normalisation rule that drops rows would otherwise be
   invisible.

4. **The do-not-merge list still holds.** Grounds pinned apart in
   `DISTINCT_DESPITE_SIMILARITY` must still resolve to different keys. Two of
   those entries exist because a source contradicted an instinct that said
   merge - Marrara Cricket Ground against Marrara Stadium, and Tony Ireland
   against Riverway - so a regression here is a regression to a wrong answer.

Usage
-----
    cd backend && python -m scripts.validate_venues
    cd backend && python -m scripts.validate_venues --json

Exits non-zero when a check fails. Candidates are reported, never merged: a pair
appearing under check 2 means "someone should look", never "these are the same".
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from collections import defaultdict

# Words carrying no identity: nearly every ground name has some of them, so they
# cannot be what makes two names look alike.
GENERIC = {
    "ground", "grounds", "stadium", "cricket", "oval", "club", "association",
    "park", "field", "sports", "complex", "centre", "center", "international",
    "national", "the", "no", "a", "b", "academy", "university", "arena", "city",
    "county", "and", "of", "st", "new",
}


def _words(text: str | None) -> set[str]:
    return set(re.findall(r"[a-z]+", (text or "").lower()))


def _tokens(name: str, base) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (base(name) or name).lower())
    return {w for w in words if w not in GENERIC}


def _initials(name: str, base) -> str:
    words = re.findall(r"[A-Za-z]+", base(name) or name)
    return "".join(w[0].lower() for w in words if w.lower() not in GENERIC)


def _compact(name: str, base) -> str:
    return re.sub(r"[^a-z]", "", (base(name) or name).lower())


def run() -> dict:
    sys.path.insert(0, ".")
    from sqlalchemy import text

    from app import venues
    from app.database import SessionLocal

    db = SessionLocal()
    rows = db.execute(
        text(
            "select venue, city, count(*) n from matches "
            "where venue is not null group by 1, 2"
        )
    ).all()
    total_matches = sum(n for _v, _c, n in rows)

    groups: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for venue, city, n in rows:
        key = venues.canonical_key(venue, city)
        if key is None:
            continue
        groups[key][city or "?"] += n
    accounted = sum(sum(c.values()) for c in groups.values())

    # 1. cross-city merges
    cross_city = []
    for key, cities in sorted(groups.items()):
        if len(cities) < 2:
            continue
        shared = set.intersection(*[_words(c) for c in cities])
        if shared:
            continue
        cross_city.append(
            {
                "ground": key,
                "cities": sorted(cities.items(), key=lambda kv: -kv[1]),
            }
        )

    # 2. same-city rename / acronym candidates
    by_city: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for venue, city, n in rows:
        by_city[(city or "").lower()].append((venue, n))
    candidates = []
    for city, entries in sorted(by_city.items()):
        if not city or len(entries) < 2:
            continue
        for (a, na), (b, nb) in itertools.combinations(entries, 2):
            if venues.canonical_key(a, city) == venues.canonical_key(b, city):
                continue
            ta, tb = _tokens(a, venues.base_name), _tokens(b, venues.base_name)
            shared = ta & tb
            nested = bool(shared) and (ta <= tb or tb <= ta)
            acronym = (
                _initials(a, venues.base_name) == _compact(b, venues.base_name)
                or _initials(b, venues.base_name) == _compact(a, venues.base_name)
            )
            if nested or acronym:
                candidates.append(
                    {
                        "city": city,
                        "a": a,
                        "a_matches": na,
                        "b": b,
                        "b_matches": nb,
                        "why": "acronym" if acronym else "shares " + ",".join(sorted(shared)),
                    }
                )

    # 4. the do-not-merge list still holds
    pinned_broken = []
    pinned = sorted(venues.DISTINCT_DESPITE_SIMILARITY)
    for a, b in itertools.combinations(pinned, 2):
        if venues.canonical_key(a) == venues.canonical_key(b):
            pinned_broken.append({"a": a, "b": b})

    return {
        "raw_pairs": len(rows),
        "canonical_grounds": len(groups),
        "matches_with_venue": total_matches,
        "matches_accounted": accounted,
        "cross_city": cross_city,
        "candidates": candidates,
        "pinned_broken": pinned_broken,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run()

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"{result['raw_pairs']} raw (venue, city) pairs -> "
            f"{result['canonical_grounds']} canonical grounds"
        )
        print(
            f"matches with a venue: {result['matches_with_venue']}, "
            f"accounted for: {result['matches_accounted']}"
        )
        print()
        if result["candidates"]:
            print(f"REVIEW  {len(result['candidates'])} same-city candidate pair(s):")
            for c in result["candidates"]:
                print(
                    f"     {c['city'][:14]:<14} {c['a'][:38]:<38}({c['a_matches']:>3})"
                    f"  <>  {c['b'][:38]:<38}({c['b_matches']:>3})  {c['why']}"
                )
            print("     Reported, never merged. Check a source before adding an alias.")
            print()
        print(f"INFO    {len(result['cross_city'])} ground(s) span cities with no shared word.")
        print("        Each must be ONE ground written two ways. Read them:")
        for g in result["cross_city"][:40]:
            cities = ", ".join(f"{c}({n})" for c, n in g["cities"])
            print(f"     {g['ground'][:44]:<44} {cities}")
        print()

    failures = []
    if result["matches_accounted"] != result["matches_with_venue"]:
        failures.append(
            f"{result['matches_with_venue'] - result['matches_accounted']} matches "
            f"with a venue did not land in any canonical ground"
        )
    for p in result["pinned_broken"]:
        failures.append(f"pinned-apart grounds now merge: {p['a']!r} and {p['b']!r}")

    for f in failures:
        print(f"FAIL    {f}")
    if not failures:
        print("OK      no match lost, and every pinned-apart ground is still separate.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

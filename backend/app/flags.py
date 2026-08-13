"""Team -> country code, for flags.

Why this is backend data and not a UI lookup
--------------------------------------------
Which nation a side represents is a fact about the domain, not a presentation
detail, and §32 keeps domain knowledge out of components. The API therefore
returns an ISO 3166-1 alpha-2 code and the UI decides only how to draw it.

Three categories of side get **no** code, deliberately:

* **Franchises.** Karachi Kings play in Pakistan, but a franchise is not a
  national side, and the whole schema exists to stop the two blurring into one
  figure. Flying a Pakistan flag on a PSL team invites exactly that reading, so
  franchises get a neutral mark instead.
* **Invitational sides.** Africa XI, Asia XI and ICC World XI represent no
  country and never have.
* **West Indies.** A federation of fifteen territories with its own flag and no
  ISO code. Barbados appears separately in this dataset (it has played as its
  own side), and *that* has a code; the West Indies does not.

Anything unmapped returns None and renders as the neutral mark rather than
guessing, which is the same rule the bio fields follow.

England, Scotland and Wales are not ISO countries either, but they are the
recognised cricketing nations and Unicode gives them subdivision flags, so they
carry their GB subdivision tags.
"""

from __future__ import annotations

# Cricketing nations that are UK subdivisions rather than ISO countries.
SUBDIVISIONS = {
    "England": "gb-eng",
    "Scotland": "gb-sct",
    "Wales": "gb-wls",
}

# Name as it appears in `teams.name` -> ISO 3166-1 alpha-2.
COUNTRY_CODES: dict[str, str] = {
    "Argentina": "AR", "Australia": "AU", "Austria": "AT", "Bahamas": "BS",
    "Bahrain": "BH", "Bangladesh": "BD", "Barbados": "BB", "Belgium": "BE",
    "Belize": "BZ", "Bermuda": "BM", "Bhutan": "BT", "Botswana": "BW",
    "Brazil": "BR", "Bulgaria": "BG", "Cambodia": "KH", "Cameroon": "CM",
    "Canada": "CA", "Cayman Islands": "KY", "Chile": "CL", "China": "CN",
    "Cook Islands": "CK", "Costa Rica": "CR", "Croatia": "HR", "Cyprus": "CY",
    "Czech Republic": "CZ", "Denmark": "DK", "Estonia": "EE",
    # Eswatini renamed from Swaziland in 2018; the dataset carries both, and
    # they are the same side, so they resolve to the same flag.
    "Eswatini": "SZ", "Swaziland": "SZ",
    "Fiji": "FJ", "Finland": "FI", "France": "FR", "Gambia": "GM",
    "Germany": "DE", "Ghana": "GH", "Gibraltar": "GI", "Greece": "GR",
    "Guernsey": "GG", "Hong Kong": "HK", "Hungary": "HU", "India": "IN",
    "Indonesia": "ID", "Iran": "IR", "Ireland": "IE", "Isle of Man": "IM",
    "Israel": "IL", "Italy": "IT", "Ivory Coast": "CI", "Japan": "JP",
    "Jersey": "JE", "Kenya": "KE", "Kuwait": "KW", "Lesotho": "LS",
    "Luxembourg": "LU", "Malawi": "MW", "Malaysia": "MY", "Maldives": "MV",
    "Mali": "ML", "Malta": "MT", "Mexico": "MX", "Mongolia": "MN",
    "Mozambique": "MZ", "Myanmar": "MM", "Namibia": "NA", "Nepal": "NP",
    "Netherlands": "NL", "New Zealand": "NZ", "Nigeria": "NG", "Norway": "NO",
    "Oman": "OM", "Pakistan": "PK", "Panama": "PA", "Papua New Guinea": "PG",
    "Philippines": "PH", "Portugal": "PT", "Qatar": "QA", "Romania": "RO",
    "Rwanda": "RW", "Samoa": "WS", "Saudi Arabia": "SA", "Serbia": "RS",
    "Seychelles": "SC", "Sierra Leone": "SL", "Singapore": "SG",
    "Slovenia": "SI", "South Africa": "ZA", "South Korea": "KR", "Spain": "ES",
    "Sri Lanka": "LK", "St Helena": "SH", "Suriname": "SR", "Sweden": "SE",
    "Switzerland": "CH", "Tanzania": "TZ", "Thailand": "TH",
    "Timor-Leste": "TL", "Turkey": "TR", "Turks and Caicos Island": "TC",
    "Uganda": "UG", "United Arab Emirates": "AE",
    "United States of America": "US", "Uzbekistan": "UZ", "Vanuatu": "VU",
    "Zambia": "ZM", "Zimbabwe": "ZW",
}

# Sides that represent no nation. Listed explicitly rather than left to fall
# through, so that a genuine mapping gap stays distinguishable from a side that
# is correctly flagless.
NO_NATION = {"Africa XI", "Asia XI", "ICC World XI", "West Indies"}


def country_code(team_name: str | None, team_type: str | None = None) -> str | None:
    """ISO alpha-2 (or a GB subdivision tag) for a side, or None.

    `team_type` is honoured over the name: a franchise never resolves to a
    country even when its city sits plainly inside one.
    """
    if not team_name:
        return None
    if team_type and team_type != "international":
        return None
    if team_name in NO_NATION:
        return None
    if team_name in SUBDIVISIONS:
        return SUBDIVISIONS[team_name]
    return COUNTRY_CODES.get(team_name)


__all__ = ["country_code", "COUNTRY_CODES", "SUBDIVISIONS", "NO_NATION"]

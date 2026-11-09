"""
Helpers for matching US place names written in different ways.

The fuel price file, the Census town list and user input all spell towns
slightly differently ("St. Louis" vs "Saint Louis", "McCalla" vs "Mc Calla").
`normalize_place_name` turns all of them into one comparable form.
"""

import re
import unicodedata

US_STATES: dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}

_STATE_CODES_BY_NAME = {name.lower(): code for code, name in US_STATES.items()}

_ABBREVIATIONS = {"st": "saint", "ste": "sainte", "ft": "fort", "mt": "mount"}
_ABBREVIATION_PATTERN = re.compile(r"\b(st|ste|ft|mt)\b\.?")
_JOINED_PREFIX_PATTERN = re.compile(r"\b(mc|de|la|le) (?=\w)")


def normalize_place_name(name: str) -> str:
    """Return a lowercase, punctuation-free form of a place name for matching."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(char for char in text if not unicodedata.combining(char))  # ñ -> n
    text = text.lower()
    text = re.sub(r"\(.*?\)", " ", text)  # "Nashville (balance)" -> "Nashville"
    text = re.sub(r"[-/]", " ", text)  # "Winston-Salem" -> "Winston Salem"
    text = _ABBREVIATION_PATTERN.sub(lambda match: _ABBREVIATIONS[match.group(1)] + " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = _JOINED_PREFIX_PATTERN.sub(r"\1", text)  # "mc calla" -> "mccalla"
    text = re.sub(r"[^a-z0-9 ]", "", text)  # "o'fallon" -> "ofallon"
    return re.sub(r"\s+", " ", text).strip()


def state_code(text: str) -> str | None:
    """Return the two-letter code for a US state given as a code or full name."""
    cleaned = text.strip().replace(".", "")  # "D.C." -> "DC"
    if cleaned.upper() in US_STATES:
        return cleaned.upper()
    return _STATE_CODES_BY_NAME.get(cleaned.lower())

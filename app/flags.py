"""Länder -> Flaggen-Datei unter static/flags/<code>.svg"""

from pathlib import Path

COUNTRY_CODES = {
    "Argentina": "ar", "Australia": "au", "Austria": "at", "Bahrain": "bh", "Belgium": "be",
    "Brazil": "br", "Bulgaria": "bg", "Canada": "ca", "China": "cn", "Croatia": "hr",
    "Czech Republic": "cz", "Czechia": "cz", "Denmark": "dk", "England": "gb-eng", "Estonia": "ee",
    "Finland": "fi", "France": "fr", "Germany": "de", "Gibraltar": "gi", "Greece": "gr",
    "Hong Kong": "hk", "Hungary": "hu", "Iceland": "is", "India": "in", "Ireland": "ie",
    "Israel": "il", "Italy": "it", "Japan": "jp", "Kenya": "ke", "Latvia": "lv",
    "Lithuania": "lt", "Luxembourg": "lu", "Malaysia": "my", "Mexico": "mx", "Netherlands": "nl",
    "New Zealand": "nz", "Northern Ireland": "gb-nir", "Norway": "no", "Philippines": "ph",
    "Poland": "pl", "Portugal": "pt", "Romania": "ro", "Russia": "ru", "Scotland": "gb-sct",
    "Serbia": "rs", "Singapore": "sg", "Slovakia": "sk", "Slovenia": "si", "South Africa": "za",
    "South Korea": "kr", "Spain": "es", "Sweden": "se", "Switzerland": "ch", "Taiwan": "tw",
    "Thailand": "th", "Turkey": "tr", "Ukraine": "ua", "USA": "us", "United States": "us",
    "Wales": "gb-wls",
}

_FLAG_DIR = Path(__file__).resolve().parent / "static" / "flags"
_AVAILABLE = {p.stem for p in _FLAG_DIR.glob("*.svg")}


def flag_code(nation: str | None) -> str | None:
    code = COUNTRY_CODES.get((nation or "").strip())
    return code if code in _AVAILABLE else None

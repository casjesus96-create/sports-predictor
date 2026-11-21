"""Season-aware NHL team abbreviation to statistical franchise registry.

The registry records source abbreviations by season and resolves them to a
stable statistical-history key. It does not fetch data, write to Supabase,
or authorize any upstream data reuse.
"""
from __future__ import annotations

import re
from typing import Any

REGISTRY_VERSION = "2026-11-21.1"

_NHL_HISTORY = "https://www.nhl.com/news/nhl-expansion-history-281005106"
_NHL_RECORDS = "https://records.nhl.com/history"
_NHL_ABBREVIATIONS = "https://media.nhl.com/site/asset/public/ext/2026-27/2026GlobalSeriesFinland.pdf"
_JETS_CONSOLIDATION = (
    "https://www.nhl.com/jets/news/jets-and-nhl-announce-consolidation-of-winnipeg-jets-history"
)

# valid_from/to are season labels, inclusive. Current codes are not accepted
# before the season in which that abbreviation/team entered the NHL.
_ENTRIES: tuple[dict[str, Any], ...] = (
    # Current team abbreviations and their first NHL seasons.
    {"abbreviation": "ANA", "valid_from": "1993-1994", "valid_to": None, "canonical_key": "ANA", "source_url": _NHL_HISTORY},
    {"abbreviation": "BOS", "valid_from": "1924-1925", "valid_to": None, "canonical_key": "BOS", "source_url": _NHL_RECORDS},
    {"abbreviation": "BUF", "valid_from": "1970-1971", "valid_to": None, "canonical_key": "BUF", "source_url": _NHL_HISTORY},
    {"abbreviation": "CGY", "valid_from": "1980-1981", "valid_to": None, "canonical_key": "CGY", "source_url": _NHL_RECORDS},
    {"abbreviation": "CAR", "valid_from": "1997-1998", "valid_to": None, "canonical_key": "CAR", "source_url": _NHL_HISTORY},
    {"abbreviation": "CHI", "valid_from": "1926-1927", "valid_to": None, "canonical_key": "CHI", "source_url": _NHL_RECORDS},
    {"abbreviation": "COL", "valid_from": "1995-1996", "valid_to": None, "canonical_key": "COL", "source_url": _NHL_HISTORY},
    {"abbreviation": "CBJ", "valid_from": "2000-2001", "valid_to": None, "canonical_key": "CBJ", "source_url": _NHL_HISTORY},
    {"abbreviation": "DAL", "valid_from": "1993-1994", "valid_to": None, "canonical_key": "DAL", "source_url": _NHL_HISTORY},
    {"abbreviation": "DET", "valid_from": "1926-1927", "valid_to": None, "canonical_key": "DET", "source_url": _NHL_RECORDS},
    {"abbreviation": "EDM", "valid_from": "1979-1980", "valid_to": None, "canonical_key": "EDM", "source_url": _NHL_HISTORY},
    {"abbreviation": "FLA", "valid_from": "1993-1994", "valid_to": None, "canonical_key": "FLA", "source_url": _NHL_HISTORY},
    {"abbreviation": "LAK", "valid_from": "1967-1968", "valid_to": None, "canonical_key": "LAK", "source_url": _NHL_HISTORY},
    {"abbreviation": "MIN", "valid_from": "2000-2001", "valid_to": None, "canonical_key": "MIN", "source_url": _NHL_HISTORY},
    {"abbreviation": "MTL", "valid_from": "1917-1918", "valid_to": None, "canonical_key": "MTL", "source_url": _NHL_RECORDS},
    {"abbreviation": "NSH", "valid_from": "1998-1999", "valid_to": None, "canonical_key": "NSH", "source_url": _NHL_HISTORY},
    {"abbreviation": "NJD", "valid_from": "1982-1983", "valid_to": None, "canonical_key": "NJD", "source_url": _NHL_RECORDS},
    {"abbreviation": "NYI", "valid_from": "1972-1973", "valid_to": None, "canonical_key": "NYI", "source_url": _NHL_HISTORY},
    {"abbreviation": "NYR", "valid_from": "1926-1927", "valid_to": None, "canonical_key": "NYR", "source_url": _NHL_RECORDS},
    {"abbreviation": "OTT", "valid_from": "1992-1993", "valid_to": None, "canonical_key": "OTT", "source_url": _NHL_HISTORY},
    {"abbreviation": "PHI", "valid_from": "1967-1968", "valid_to": None, "canonical_key": "PHI", "source_url": _NHL_HISTORY},
    {"abbreviation": "PIT", "valid_from": "1967-1968", "valid_to": None, "canonical_key": "PIT", "source_url": _NHL_HISTORY},
    {"abbreviation": "SJS", "valid_from": "1991-1992", "valid_to": None, "canonical_key": "SJS", "source_url": _NHL_HISTORY},
    {"abbreviation": "SEA", "valid_from": "2021-2022", "valid_to": None, "canonical_key": "SEA", "source_url": _NHL_HISTORY},
    {"abbreviation": "STL", "valid_from": "1967-1968", "valid_to": None, "canonical_key": "STL", "source_url": _NHL_HISTORY},
    {"abbreviation": "TBL", "valid_from": "1992-1993", "valid_to": None, "canonical_key": "TBL", "source_url": _NHL_HISTORY},
    {"abbreviation": "TOR", "valid_from": "1917-1918", "valid_to": None, "canonical_key": "TOR", "source_url": _NHL_RECORDS},
    {"abbreviation": "UTA", "valid_from": "2024-2025", "valid_to": None, "canonical_key": "UTA", "source_url": _NHL_ABBREVIATIONS},
    {"abbreviation": "VAN", "valid_from": "1970-1971", "valid_to": None, "canonical_key": "VAN", "source_url": _NHL_HISTORY},
    {"abbreviation": "VGK", "valid_from": "2017-2018", "valid_to": None, "canonical_key": "VGK", "source_url": _NHL_HISTORY},
    {"abbreviation": "WPG", "valid_from": "2011-2012", "valid_to": None, "canonical_key": "WPG", "source_url": _JETS_CONSOLIDATION},
    {"abbreviation": "WSH", "valid_from": "1974-1975", "valid_to": None, "canonical_key": "WSH", "source_url": _NHL_HISTORY},
    # Historical abbreviations. Statistical lineage follows NHL's published
    # history; it is not a claim that the clubs shared the same legal entity.
    {"abbreviation": "AFM", "valid_from": "1972-1973", "valid_to": "1979-1980", "canonical_key": "CGY", "source_url": _NHL_ABBREVIATIONS},
    {"abbreviation": "HFD", "valid_from": "1979-1980", "valid_to": "1996-1997", "canonical_key": "CAR", "source_url": _NHL_HISTORY},
    {"abbreviation": "QUE", "valid_from": "1979-1980", "valid_to": "1994-1995", "canonical_key": "COL", "source_url": _NHL_HISTORY},
    {"abbreviation": "MNS", "valid_from": "1967-1968", "valid_to": "1992-1993", "canonical_key": "DAL", "source_url": _NHL_HISTORY},
    {"abbreviation": "WIN", "valid_from": "1979-1980", "valid_to": "1995-1996", "canonical_key": "WPG", "source_url": _JETS_CONSOLIDATION},
    {"abbreviation": "PHX", "valid_from": "1996-1997", "valid_to": "2013-2014", "canonical_key": "ARI", "source_url": _NHL_ABBREVIATIONS},
    {"abbreviation": "ARI", "valid_from": "2014-2015", "valid_to": "2023-2024", "canonical_key": "ARI", "source_url": _NHL_ABBREVIATIONS},
    {"abbreviation": "ATL", "valid_from": "1999-2000", "valid_to": "2010-2011", "canonical_key": "WPG", "source_url": _JETS_CONSOLIDATION},
)

def _season_key(value: Any) -> str:
    season = str(value or "").strip()
    match = re.fullmatch(r"(\d{4})-(\d{4})", season)
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        raise ValueError("season debe usar el formato YYYY-YYYY con años consecutivos.")
    return season


def _validate_registry() -> None:
    by_abbreviation: dict[str, list[tuple[str, str]]] = {}
    for entry in _ENTRIES:
        abbreviation = entry["abbreviation"]
        start = _season_key(entry["valid_from"])
        end = _season_key(entry["valid_to"]) if entry["valid_to"] else "9999-10000"
        if not re.fullmatch(r"[A-Z]{2,3}", abbreviation):
            raise ValueError(f"Abreviatura NHL inválida: {abbreviation}")
        if entry["canonical_key"] not in {item["abbreviation"] for item in _ENTRIES}:
            raise ValueError(f"Clave canónica no registrada: {entry['canonical_key']}")
        if not entry["source_url"].startswith("https://"):
            raise ValueError(f"Fuente inválida para {abbreviation}")
        by_abbreviation.setdefault(abbreviation, []).append((start, end))
    for abbreviation, ranges in by_abbreviation.items():
        ordered = sorted(ranges)
        for previous, current in zip(ordered, ordered[1:]):
            if current[0] <= previous[1]:
                raise ValueError(f"Rangos de temporada solapados para {abbreviation}")


def resolve_team_identity(season: str, abbreviation: str) -> str | None:
    """Return the reviewed statistical-history key, or None if unresolved."""
    selected = _season_key(season)
    code = str(abbreviation or "").strip().upper()
    if not code:
        return None
    for entry in _ENTRIES:
        if entry["abbreviation"] != code:
            continue
        if selected < entry["valid_from"]:
            continue
        if entry["valid_to"] and selected > entry["valid_to"]:
            continue
        return entry["canonical_key"]
    return None


def build_season_team_identity_map(
    season: str,
    abbreviations: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, str]:
    """Build an explicit season-valid map suitable for nhl_archive.py.

    If abbreviations are supplied, only those codes are returned. Unknown or
    out-of-period codes are omitted and therefore remain training-ineligible.
    """
    selected = _season_key(season)
    if abbreviations is None:
        requested = sorted({entry["abbreviation"] for entry in _ENTRIES})
    else:
        if not isinstance(abbreviations, (list, tuple, set)):
            raise TypeError("abbreviations debe ser una lista, tupla o conjunto.")
        requested = sorted({str(code or "").strip().upper() for code in abbreviations if str(code or "").strip()})
    resolved: dict[str, str] = {}
    for code in requested:
        canonical = resolve_team_identity(selected, code)
        if canonical:
            resolved[code] = canonical
    return resolved


def get_registry_entries(season: str | None = None) -> list[dict[str, Any]]:
    """Return a defensive copy of registry rows, optionally filtered by season."""
    selected = _season_key(season) if season is not None else None
    result = []
    for entry in _ENTRIES:
        if selected and resolve_team_identity(selected, entry["abbreviation"]) is None:
            continue
        result.append(dict(entry))
    return result


_validate_registry()

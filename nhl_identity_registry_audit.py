"""Read-only, source-independent audit of the season-aware NHL identity registry.

This reports what the local registry currently knows. It does not claim the
registry is historically complete and does not fetch schedules or write data.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from typing import Any

from nhl_team_identity_registry import (
    REGISTRY_VERSION,
    get_registry_entries,
    resolve_team_identity,
)


def _season_label(start_year: int) -> str:
    if isinstance(start_year, bool) or not isinstance(start_year, int):
        raise TypeError("start_year debe ser un entero.")
    if start_year < 1917 or start_year > 9998:
        raise ValueError("start_year debe estar entre 1917 y 9998.")
    return f"{start_year}-{start_year + 1}"


def build_identity_registry_audit(
    start_year: int = 1917,
    end_year: int = 2026,
    observed_abbreviations_by_season: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Summarize registry coverage by season and optionally flag unknown codes.

    observed_abbreviations_by_season is caller-supplied data only. This module
    never fetches it. Unknown codes are reported, never auto-mapped.
    """
    if isinstance(end_year, bool) or not isinstance(end_year, int):
        raise TypeError("end_year debe ser un entero.")
    if end_year < start_year:
        raise ValueError("end_year no puede ser menor que start_year.")
    if end_year > 9998:
        raise ValueError("end_year debe ser como máximo 9998.")

    seasons: list[dict[str, Any]] = []
    unknown_observed: list[dict[str, str]] = []
    all_entries = get_registry_entries()
    for year in range(start_year, end_year + 1):
        season = _season_label(year)
        entries = get_registry_entries(season)
        abbreviations = sorted({str(row["abbreviation"]) for row in entries})
        canonical_groups: dict[str, list[str]] = defaultdict(list)
        for code in abbreviations:
            canonical = resolve_team_identity(season, code)
            if canonical is not None:
                canonical_groups[canonical].append(code)
        observed = (observed_abbreviations_by_season or {}).get(season, [])
        observed_codes = sorted({str(code or "").strip().upper() for code in observed if str(code or "").strip()})
        unknown = sorted(set(observed_codes) - set(abbreviations))
        for code in unknown:
            unknown_observed.append({"season": season, "abbreviation": code})
        seasons.append({
            "season": season,
            "registered_abbreviation_count": len(abbreviations),
            "registered_abbreviations": abbreviations,
            "statistical_group_count": len(canonical_groups),
            "statistical_groups": {
                key: sorted(codes) for key, codes in sorted(canonical_groups.items())
            },
            "observed_abbreviation_count": len(observed_codes),
            "unknown_observed_abbreviations": unknown,
        })

    historical_codes = sum(
        1 for row in all_entries
        if row.get("valid_to") is not None
    )
    current_open_ended_codes = sum(
        1 for row in all_entries
        if row.get("valid_to") is None
    )
    return {
        "success": not unknown_observed,
        "registry_version": REGISTRY_VERSION,
        "scope": "local_registry_only_no_network_no_database_writes",
        "historical_seasons_included": len(seasons),
        "start_season": seasons[0]["season"] if seasons else None,
        "end_season": seasons[-1]["season"] if seasons else None,
        "registry_entry_count": len(all_entries),
        "historical_bounded_entry_count": historical_codes,
        "open_ended_entry_count": current_open_ended_codes,
        "unknown_observed_abbreviations": unknown_observed,
        "seasons": seasons,
        "limitations": [
            "El registro describe identidades y periodos conocidos; no demuestra que cada temporada esté completa.",
            "Las claves canónicas agrupan historia estadística y no afirman continuidad de entidad legal.",
            "No se consultaron calendarios ni fuentes externas y no se importaron partidos.",
        ],
    }


def render_markdown_summary(report: dict[str, Any]) -> str:
    lines = [
        f"## NHL identity registry audit — {report.get('registry_version', 'unknown')}",
        f"**Scope:** {report.get('scope', 'unknown')}",
        f"**Seasons reviewed:** {report.get('historical_seasons_included', 0)}",
        f"**Registry entries:** {report.get('registry_entry_count', 0)}",
        "",
        "| Season | Registered abbreviations | Statistical groups | Unknown observed codes |",
        "|---|---:|---:|---:|",
    ]
    for item in report.get("seasons", []):
        lines.append(
            f"| {item['season']} | {item['registered_abbreviation_count']} | "
            f"{item['statistical_group_count']} | {len(item['unknown_observed_abbreviations'])} |"
        )
    lines.extend(["", "### Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    unknown = report.get("unknown_observed_abbreviations") or []
    if unknown:
        lines.extend(["", "### Unknown observed abbreviations", "", json.dumps(unknown, ensure_ascii=False, indent=2)])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audita el registro NHL por temporada sin red ni escrituras."
    )
    parser.add_argument("--start-year", type=int, default=1917)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--output", default="nhl-identity-registry-audit.json")
    args = parser.parse_args()
    report = build_identity_registry_audit(args.start_year, args.end_year)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    with open(args.output, "w", encoding="utf-8") as output_file:
        output_file.write(rendered)
    print(rendered)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

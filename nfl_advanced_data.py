"""Read-only schema inspection for public nflverse datasets."""
import csv
import gzip
import io
from datetime import datetime, timezone

import requests

from nfl_data_coverage import ADVANCED_SOURCES, NFLVERSE_RELEASES

TIMEOUT_SECONDS = 20


def _scan_csv_gzip(content):
    with gzip.GzipFile(fileobj=io.BytesIO(content), mode="rb") as zipped:
        reader = csv.DictReader(
            io.TextIOWrapper(zipped, encoding="utf-8-sig", errors="replace")
        )
        columns = list(reader.fieldnames or [])
        rows = 0
        seasons, weeks, teams, games = set(), set(), set(), set()
        for row in reader:
            rows += 1
            if row.get("season"):
                seasons.add(str(row["season"]).strip())
            if row.get("week"):
                weeks.add(str(row["week"]).strip())
            for field in ("team", "posteam", "defteam", "recent_team"):
                if row.get(field):
                    teams.add(str(row[field]).strip())
                    break
            for field in ("game_id", "old_game_id", "gsis_id"):
                if row.get(field):
                    games.add(str(row[field]).strip())
                    break
    return {
        "columns": columns,
        "column_count": len(columns),
        "rows_scanned": rows,
        "seasons": sorted(seasons),
        "weeks": sorted(weeks),
        "distinct_teams": len(teams),
        "distinct_games": len(games),
    }


def inspect_nfl_advanced_sources(season=2026, session=requests):
    results = []
    for source in ADVANCED_SOURCES:
        asset = source["asset_template"].format(season=season)
        url = f"{NFLVERSE_RELEASES}/{source['tag']}/{asset}"
        item = {
            "key": source["key"], "label": source["label"], "asset": asset,
            "available": False, "http_status": None, "url": None,
            "schema": None, "error": None,
        }
        try:
            response = session.get(url, timeout=TIMEOUT_SECONDS)
            item["http_status"] = response.status_code
            response.raise_for_status()
            item["schema"] = _scan_csv_gzip(response.content)
            item["available"] = True
            item["url"] = url
        except (requests.RequestException, OSError, EOFError, csv.Error, UnicodeError, ValueError) as exc:
            item["error"] = f"Fuente no inspeccionable: {type(exc).__name__}."
        results.append(item)
    return {
        "success": True,
        "sport": "NFL",
        "season": int(season),
        "model_version": "NFL-1.0.0",
        "read_only": True,
        "model_impact": "none",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources_checked": len(results),
        "sources_inspected": sum(1 for source in results if source["available"]),
        "sources": results,
        "next_step": "Evaluar cobertura de variables pregame con corte estricto anterior al kickoff.",
    }

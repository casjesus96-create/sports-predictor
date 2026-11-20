"""Read-only audit of NHL team-season schedule coverage.

This tool deliberately does not persist data. It measures source coverage and
cross-team consistency before any historical archive migration is considered.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from typing import Any

from nhl_client import NHLDataError, get_team_season_schedule

# Current franchise abbreviations. Historical seasons may require a different
# franchise map; do not silently assume today's abbreviations cover all eras.
CURRENT_TEAM_ABBREVIATIONS = (
    "ANA", "BOS", "BUF", "CGY", "CAR", "CHI", "COL", "CBJ",
    "DAL", "DET", "EDM", "FLA", "LAK", "MIN", "MTL", "NSH",
    "NJD", "NYI", "NYR", "OTT", "PHI", "PIT", "SJS", "SEA",
    "STL", "TBL", "TOR", "UTA", "VAN", "VGK", "WSH", "WPG",
)


def _signature(game: dict[str, Any]) -> tuple[Any, ...]:
    return (
        game.get("game_date"),
        (game.get("home") or {}).get("abbreviation"),
        (game.get("away") or {}).get("abbreviation"),
        (game.get("home") or {}).get("score"),
        (game.get("away") or {}).get("score"),
        game.get("game_state"),
        game.get("game_type"),
    )


def build_season_coverage_report(
    season: str,
    teams: list[str],
    schedule_by_team: dict[str, dict[str, Any]],
    failures: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Aggregate team schedules by game ID and expose gaps/conflicts."""
    failures = failures or {}
    observations: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    invalid_membership: list[dict[str, str]] = []

    for team in teams:
        payload = schedule_by_team.get(team) or {}
        for game in payload.get("games", []):
            game_id = str(game.get("game_id") or "").strip()
            if not game_id:
                continue
            home = (game.get("home") or {}).get("abbreviation")
            away = (game.get("away") or {}).get("abbreviation")
            if team not in {home, away}:
                invalid_membership.append({"requested_team": team, "game_id": game_id})
                continue
            observations[game_id].append((team, game))

    conflicts = []
    completed_missing_score = []
    games_missing_game_type = []
    game_type_counts: Counter[str] = Counter()
    game_state_counts: Counter[str] = Counter()
    team_observation_counts: Counter[str] = Counter()
    games_without_cross_team_confirmation: list[dict[str, Any]] = []
    non_completed_games: list[dict[str, Any]] = []
    for game_id, entries in observations.items():
        signatures = {_signature(game) for _, game in entries}
        if len(signatures) > 1:
            conflicts.append({"game_id": game_id, "teams": sorted({team for team, _ in entries})})
        canonical = entries[0][1]
        home = canonical.get("home") or {}
        away = canonical.get("away") or {}
        game_state = str(canonical.get("game_state") or "UNKNOWN")
        game_detail = {
            "game_id": game_id,
            "game_date": canonical.get("game_date"),
            "home_team": home.get("abbreviation"),
            "away_team": away.get("abbreviation"),
            "home_score": home.get("score"),
            "away_score": away.get("score"),
            "game_state": game_state,
            "game_type": canonical.get("game_type"),
        }
        observed_teams = sorted({team for team, _ in entries})
        if len(observed_teams) < 2:
            games_without_cross_team_confirmation.append({
                **game_detail,
                "observed_teams": observed_teams,
                "missing_team": away.get("abbreviation") if home.get("abbreviation") in observed_teams else home.get("abbreviation"),
            })
        if not canonical.get("completed"):
            non_completed_games.append(game_detail)
        game_type = canonical.get("game_type")
        if game_type is None:
            games_missing_game_type.append(game_id)
        else:
            game_type_counts[str(game_type)] += 1
        game_state_counts[str(canonical.get("game_state") or "UNKNOWN")] += 1
        if canonical.get("completed") and (
            (canonical.get("home") or {}).get("score") is None
            or (canonical.get("away") or {}).get("score") is None
        ):
            completed_missing_score.append(game_id)
        for team, _ in entries:
            team_observation_counts[team] += 1

    unique_games = len(observations)
    double_confirmed = sum(1 for entries in observations.values() if len({team for team, _ in entries}) >= 2)
    completed_games = sum(
        1 for entries in observations.values() if entries[0][1].get("completed")
    )
    missing_team_responses = sorted(set(teams) - set(schedule_by_team) - set(failures))
    return {
        "success": not failures and not missing_team_responses and not conflicts and not completed_missing_score and not games_missing_game_type and not invalid_membership,
        "season": season,
        "source": "NHL public club season schedule",
        "persistence": "read_only_no_database_writes",
        "teams_requested": len(teams),
        "teams_succeeded": len(schedule_by_team),
        "teams_failed": len(failures),
        "missing_team_responses": missing_team_responses,
        "team_failures": failures,
        "schedule_observations": sum(len(items) for items in observations.values()),
        "unique_games": unique_games,
        "duplicate_observations": sum(max(0, len(items) - 1) for items in observations.values()),
        "games_seen_from_multiple_team_schedules": double_confirmed,
        "cross_team_confirmation_rate": round(double_confirmed / unique_games, 4) if unique_games else None,
        "completed_games": completed_games,
        "games_without_cross_team_confirmation": games_without_cross_team_confirmation,
        "non_completed_games": non_completed_games,
        "review_required": bool(games_without_cross_team_confirmation or non_completed_games),
        "game_type_counts": dict(sorted(game_type_counts.items())),
        "game_state_counts": dict(sorted(game_state_counts.items())),
        "games_missing_game_type": games_missing_game_type,
        "completed_games_missing_score": completed_missing_score,
        "identity_conflicts": conflicts,
        "invalid_team_membership": invalid_membership,
        "team_observation_counts": dict(sorted(team_observation_counts.items())),
        "coverage_note": "Current franchise abbreviations only; historical relocations and inactive franchises require an explicit season-specific mapping.",
    }


def audit_nhl_season(season: str, teams: list[str] | None = None) -> dict[str, Any]:
    selected = list(dict.fromkeys(str(team).strip().upper() for team in (teams or CURRENT_TEAM_ABBREVIATIONS)))
    if not selected or any(not team for team in selected):
        raise ValueError("Se requiere al menos una abreviatura de equipo.")
    schedules: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    for team in selected:
        try:
            schedules[team] = get_team_season_schedule(team, season)
        except (NHLDataError, ValueError) as exc:
            failures[team] = str(exc)[:200]
    return build_season_coverage_report(season, selected, schedules, failures)


def render_markdown_summary(report: dict[str, Any]) -> str:
    """Render a compact GitHub Actions summary without hiding audit failures."""
    status = "PASS" if report.get("success") else "REVIEW REQUIRED"
    rate = report.get("cross_team_confirmation_rate")
    rate_text = f"{rate:.1%}" if isinstance(rate, (int, float)) else "N/A"
    lines = [
        f"## NHL historical coverage — {report.get('season', 'unknown season')}",
        f"**Result:** {status}",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Teams requested / successful / failed | {report.get('teams_requested', 0)} / {report.get('teams_succeeded', 0)} / {report.get('teams_failed', 0)} |",
        f"| Unique games | {report.get('unique_games', 0)} |",
        f"| Completed games | {report.get('completed_games', 0)} |",
        f"| Games without cross-team confirmation | {len(report.get('games_without_cross_team_confirmation', []))} |",
        f"| Non-completed games requiring review | {len(report.get('non_completed_games', []))} |",
        f"| Review required | {'YES' if report.get('review_required') else 'NO'} |",
        f"| Game types (raw NHL codes) | {json.dumps(report.get('game_type_counts', {}), sort_keys=True)} |",
        f"| Game states | {json.dumps(report.get('game_state_counts', {}), sort_keys=True)} |",
        f"| Games missing game type | {len(report.get('games_missing_game_type', []))} |",
        f"| Duplicate observations | {report.get('duplicate_observations', 0)} |",
        f"| Games confirmed by multiple team schedules | {report.get('games_seen_from_multiple_team_schedules', 0)} |",
        f"| Cross-team confirmation rate | {rate_text} |",
        f"| Identity conflicts | {len(report.get('identity_conflicts', []))} |",
        f"| Completed games missing score | {len(report.get('completed_games_missing_score', []))} |",
        f"| Invalid team membership | {len(report.get('invalid_team_membership', []))} |",
        "",
        "**Coverage limitation:** " + str(report.get("coverage_note", "Not specified.")),
        "",
        "The report is read-only; it does not write to Supabase or affect predictions.",
    ]
    for key, label in (
        ("team_failures", "Team source failures"),
        ("missing_team_responses", "Missing team responses"),
        ("identity_conflicts", "Identity conflicts"),
        ("completed_games_missing_score", "Completed games missing score"),
        ("games_missing_game_type", "Games missing game type"),
        ("invalid_team_membership", "Invalid team membership"),
        ("games_without_cross_team_confirmation", "Games without cross-team confirmation"),
        ("non_completed_games", "Non-completed games requiring review"),
    ):
        values = report.get(key) or []
        if values:
            lines.extend(["", f"### {label}", "", json.dumps(values, ensure_ascii=False, indent=2)])
    return chr(10).join(lines) + chr(10)

def main() -> int:
    parser = argparse.ArgumentParser(description="Audita cobertura histórica NHL sin escribir en Supabase.")
    parser.add_argument("--season", required=True, help="Temporada en formato YYYYYYYY, por ejemplo 20252026.")
    parser.add_argument("--teams", default=",".join(CURRENT_TEAM_ABBREVIATIONS), help="Abreviaturas separadas por coma.")
    parser.add_argument("--output", default="nhl-season-coverage-report.json", help="Ruta del informe JSON descargable.")
    args = parser.parse_args()
    teams = [item.strip().upper() for item in args.teams.split(",") if item.strip()]
    report = audit_nhl_season(args.season, teams)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + chr(10)
    with open(args.output, "w", encoding="utf-8") as output_file:
        output_file.write(rendered)
    print(rendered)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

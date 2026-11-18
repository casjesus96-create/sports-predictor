"""CLI entry point for the Valuebetennis ATP/WTA archive sync."""
import os
from datetime import datetime, timezone

from tennis_archive import MIN_YEAR, sync_tennis_archive


def resolve_year_range(start_year=None, end_year=None, current_year=None):
    """Default to current and previous years; allow explicit full backfill."""
    current = int(current_year or datetime.now(timezone.utc).year)
    end = int(end_year) if str(end_year or "").strip() else current
    start = (
        int(start_year)
        if str(start_year or "").strip()
        else max(MIN_YEAR, end - 1 if str(end_year or "").strip() else current - 1)
    )
    return start, end


if __name__ == "__main__":
    start, end = resolve_year_range(
        os.getenv("TENNIS_ARCHIVE_START_YEAR"),
        os.getenv("TENNIS_ARCHIVE_END_YEAR"),
    )
    result = sync_tennis_archive(start_year=start, end_year=end)
    print(result)
    if not result["success"]:
        raise SystemExit(1)

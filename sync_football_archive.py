"""CLI entry point for the owned football historical archive import."""
import os
from datetime import datetime, timezone

from football_archive import sync_football_archive


def resolve_year_range(start_year=None, end_year=None, current_year=None):
    """Use the current and previous season by default; honor explicit manual ranges."""
    year = int(current_year or datetime.now(timezone.utc).year)
    start = int(start_year) if str(start_year or "").strip() else max(2000, year - 1)
    end = int(end_year) if str(end_year or "").strip() else year
    return start, end


if __name__ == "__main__":
    start_year, end_year = resolve_year_range(
        os.getenv("FOOTBALL_ARCHIVE_START_YEAR"),
        os.getenv("FOOTBALL_ARCHIVE_END_YEAR"),
    )
    result = sync_football_archive(start_year=start_year, end_year=end_year)
    print(result)
    if not result["success"]:
        raise SystemExit(1)

"""CLI entry point for the owned football historical archive import."""
import os

from football_archive import sync_football_archive


if __name__ == "__main__":
    start_year = int(os.getenv("FOOTBALL_ARCHIVE_START_YEAR", "2000"))
    end_year = int(os.getenv("FOOTBALL_ARCHIVE_END_YEAR", "2026"))
    result = sync_football_archive(start_year=start_year, end_year=end_year)
    print(result)
    if not result["success"]:
        raise SystemExit(1)

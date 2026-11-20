"""Manual CLI entry point for the NHL historical results archive."""
import argparse
import json

from nhl_archive import sync_nhl_archive


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Importa resultados históricos NHL validados a Supabase."
    )
    parser.add_argument("--start-season", required=True, help="Ej. 20242025")
    parser.add_argument("--end-season", required=True, help="Ej. 20252026")
    args = parser.parse_args()
    result = sync_nhl_archive(args.start_season, args.end_season)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

from historical_data import sync_historical_games


if __name__ == "__main__":
    result = sync_historical_games(
        start_date="2026-03-25",
        end_date="2026-09-22",
        chunk_days=7,
    )

    print()
    print("RESULTADO:")
    print(result)

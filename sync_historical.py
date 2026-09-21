from historical_data import sync_historical_games


def main():
    result = sync_historical_games(
        days=30
    )

    print(
        "Resultado de sincronización:"
    )

    print(result)


if __name__ == "__main__":
    main()

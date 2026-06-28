from sqlalchemy import Engine, inspect, text


MARKET_CANDLE_LOOKUP_INDEX = "ix_market_candles_lookup"
MARKET_CANDLE_UNIQUE_INDEX = "uq_market_candles_exchange_symbol_timeframe_timestamp"


def apply_schema_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    table_columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in {"ai_analyses", "orders"}
        if inspector.has_table(table)
    }
    statements: list[str] = []
    if inspector.has_table("market_candles"):
        _migrate_market_candles(engine, inspector)

    if "orders" in table_columns and "correlation_id" not in table_columns["orders"]:
        statements.append("ALTER TABLE orders ADD COLUMN correlation_id VARCHAR(64) NULL")
        statements.append("CREATE INDEX ix_orders_correlation_id ON orders (correlation_id)")
    if "orders" in table_columns and "exchange" not in table_columns["orders"]:
        statements.append("ALTER TABLE orders ADD COLUMN exchange VARCHAR(32) NOT NULL DEFAULT 'binance'")
        statements.append("CREATE INDEX ix_orders_exchange ON orders (exchange)")
    if "ai_analyses" in table_columns:
        columns = table_columns["ai_analyses"]
        if "correlation_id" not in columns:
            statements.append("ALTER TABLE ai_analyses ADD COLUMN correlation_id VARCHAR(64) NULL")
            statements.append("CREATE INDEX ix_ai_analyses_correlation_id ON ai_analyses (correlation_id)")
        if "event_risk" not in columns:
            statements.append("ALTER TABLE ai_analyses ADD COLUMN event_risk INT NOT NULL DEFAULT 0")
        if "rationale" not in columns:
            statements.append("ALTER TABLE ai_analyses ADD COLUMN rationale JSON NULL")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _migrate_market_candles(engine: Engine, inspector) -> None:
    indexes = {index["name"] for index in inspector.get_indexes("market_candles")}
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("market_candles")
        if constraint.get("name")
    }
    if (
        MARKET_CANDLE_LOOKUP_INDEX in indexes
        and MARKET_CANDLE_UNIQUE_INDEX in unique_constraints | indexes
    ):
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE market_candles
                FROM market_candles
                JOIN (
                    SELECT
                        exchange,
                        symbol,
                        timeframe,
                        timestamp,
                        MAX(id) AS keep_id
                    FROM market_candles
                    GROUP BY exchange, symbol, timeframe, timestamp
                    HAVING COUNT(*) > 1
                ) duplicates
                    ON market_candles.exchange = duplicates.exchange
                    AND market_candles.symbol = duplicates.symbol
                    AND market_candles.timeframe = duplicates.timeframe
                    AND market_candles.timestamp = duplicates.timestamp
                    AND market_candles.id <> duplicates.keep_id
                """,
            ),
        )
        if MARKET_CANDLE_LOOKUP_INDEX not in indexes:
            connection.execute(
                text(
                    """
                    CREATE INDEX ix_market_candles_lookup
                    ON market_candles (exchange, symbol, timeframe, timestamp)
                    """,
                ),
            )
        if MARKET_CANDLE_UNIQUE_INDEX not in unique_constraints | indexes:
            connection.execute(
                text(
                    """
                    CREATE UNIQUE INDEX uq_market_candles_exchange_symbol_timeframe_timestamp
                    ON market_candles (exchange, symbol, timeframe, timestamp)
                    """,
                ),
            )

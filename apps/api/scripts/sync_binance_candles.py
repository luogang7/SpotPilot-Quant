import argparse
import json
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from sqlalchemy import select

from app.core.config import get_settings
from app.infrastructure.persistence.models import MarketCandleRecord
from app.infrastructure.persistence.session import create_mysql_session_factory


BINANCE_INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d"}
FALLBACK_BASE_URLS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
    "https://data-api.binance.vision",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Binance spot candles into MySQL.")
    parser.add_argument("--symbol", default=None, help="Symbol like BTC/USDT.")
    parser.add_argument("--timeframe", default=None, choices=sorted(BINANCE_INTERVALS))
    parser.add_argument("--limit", type=int, default=1000, help="Number of latest candles, max 1000.")
    parser.add_argument("--base-url", default=None, help="Override Binance public base URL.")
    return parser.parse_args()


def to_exchange_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace("-", "").upper()


def candidate_base_urls(primary: str) -> list[str]:
    urls = [primary.rstrip("/")]
    urls.extend(FALLBACK_BASE_URLS)
    return list(dict.fromkeys(url.rstrip("/") for url in urls if url))


def fetch_klines(
    *,
    base_urls: list[str],
    symbol: str,
    timeframe: str,
    limit: int,
    timeout_seconds: int,
) -> tuple[str, list[list[object]]]:
    params = urlencode(
        {
            "symbol": to_exchange_symbol(symbol),
            "interval": timeframe,
            "limit": max(1, min(limit, 1000)),
        },
    )
    errors: list[str] = []
    for base_url in base_urls:
        url = f"{base_url}/api/v3/klines?{params}"
        try:
            with urlopen(url, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, URLError, OSError) as exc:
            errors.append(f"{base_url}: {exc}")
            continue

        if isinstance(payload, dict) and "code" in payload:
            errors.append(f"{base_url}: {payload}")
            continue
        if not isinstance(payload, list):
            errors.append(f"{base_url}: unexpected payload type {type(payload).__name__}")
            continue
        return base_url, payload

    raise RuntimeError("All Binance endpoints failed: " + " | ".join(errors))


def to_record(exchange: str, symbol: str, timeframe: str, row: list[object]) -> MarketCandleRecord:
    return MarketCandleRecord(
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        timestamp=datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc).replace(tzinfo=None),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
    )


def main() -> None:
    args = parse_args()
    settings = get_settings()
    symbol = args.symbol or settings.default_symbol
    timeframe = args.timeframe or settings.default_timeframe
    base_url = args.base_url or settings.binance_spot_base_url

    source_url, rows = fetch_klines(
        base_urls=candidate_base_urls(base_url),
        symbol=symbol,
        timeframe=timeframe,
        limit=args.limit,
        timeout_seconds=settings.exchange_api_timeout_seconds,
    )
    records = [to_record("binance", symbol, timeframe, row) for row in rows]

    session_factory = create_mysql_session_factory(settings)
    session = session_factory()
    try:
        timestamps = [record.timestamp for record in records]
        existing = set(
            session.scalars(
                select(MarketCandleRecord.timestamp).where(
                    MarketCandleRecord.exchange == "binance",
                    MarketCandleRecord.symbol == symbol,
                    MarketCandleRecord.timeframe == timeframe,
                    MarketCandleRecord.timestamp.in_(timestamps),
                ),
            ).all(),
        )
        new_records = [record for record in records if record.timestamp not in existing]
        session.add_all(new_records)
        session.commit()
    finally:
        session.close()

    first_ts = records[0].timestamp.isoformat() if records else "n/a"
    last_ts = records[-1].timestamp.isoformat() if records else "n/a"
    print(
        "synced binance candles "
        f"symbol={symbol} timeframe={timeframe} source={source_url} "
        f"fetched={len(records)} inserted={len(new_records)} skipped={len(records) - len(new_records)} "
        f"range={first_ts}..{last_ts}",
    )


if __name__ == "__main__":
    main()

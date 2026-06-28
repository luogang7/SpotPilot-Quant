from datetime import datetime, timezone

import httpx

from app.domain.models import Candle, ExchangeId
from app.infrastructure.exchanges.base import (
    ExchangeMarketDataError,
    MarketDataSnapshot,
    MarketTicker,
)

BINANCE_INTERVALS = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}
BINANCE_FALLBACK_BASE_URLS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
    "https://data-api.binance.vision",
]
BINANCE_MAX_MARKET_PAGE_ATTEMPTS = 2


class BinanceSpotMarketClient:
    exchange = ExchangeId.BINANCE

    def __init__(self, base_url: str, timeout_seconds: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def candidate_base_urls(primary: str) -> list[str]:
        urls = [primary.rstrip("/")]
        urls.extend(BINANCE_FALLBACK_BASE_URLS)
        return list(dict.fromkeys(url.rstrip("/") for url in urls if url))

    @staticmethod
    def to_exchange_symbol(symbol: str) -> str:
        return symbol.replace("/", "").replace("-", "").upper()

    @staticmethod
    def to_exchange_interval(timeframe: str) -> str:
        try:
            return BINANCE_INTERVALS[timeframe]
        except KeyError as exc:
            raise ExchangeMarketDataError(f"Unsupported Binance interval: {timeframe}") from exc

    def get_market_data(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
    ) -> MarketDataSnapshot:
        exchange_symbol = self.to_exchange_symbol(symbol)
        interval = self.to_exchange_interval(timeframe)
        limit = max(1, min(limit, 1000))

        errors: list[str] = []
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(self.timeout_seconds, 2))
        for base_url in self.candidate_base_urls(self.base_url)[:BINANCE_MAX_MARKET_PAGE_ATTEMPTS]:
            try:
                with httpx.Client(base_url=base_url, timeout=timeout) as client:
                    ticker_response = client.get("/api/v3/ticker/24hr", params={"symbol": exchange_symbol})
                    kline_response = client.get(
                        "/api/v3/klines",
                        params={"symbol": exchange_symbol, "interval": interval, "limit": limit},
                    )

                self._raise_for_exchange_error(ticker_response, "ticker")
                self._raise_for_exchange_error(kline_response, "klines")
                break
            except (ExchangeMarketDataError, httpx.RequestError) as exc:
                errors.append(f"{base_url}: {exc}")
        else:
            raise ExchangeMarketDataError(
                "Binance public market request failed for all endpoints: " + " | ".join(errors),
            )

        ticker_payload = ticker_response.json()
        kline_payload = kline_response.json()

        return MarketDataSnapshot(
            exchange=self.exchange,
            symbol=symbol,
            timeframe=timeframe,
            ticker=MarketTicker(
                symbol=symbol,
                last_price=float(ticker_payload["lastPrice"]),
                change_24h_percent=float(ticker_payload["priceChangePercent"]),
                volume_24h=float(ticker_payload["volume"]),
                received_at=datetime.now(timezone.utc),
            ),
            candles=[
                Candle(
                    timestamp=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in kline_payload
            ],
        )

    @staticmethod
    def _raise_for_exchange_error(response: httpx.Response, name: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ExchangeMarketDataError(f"Binance {name} request failed: {exc}") from exc

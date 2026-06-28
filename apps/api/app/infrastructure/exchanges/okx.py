from datetime import datetime, timezone

import httpx

from app.domain.models import Candle, ExchangeId
from app.infrastructure.exchanges.base import (
    ExchangeMarketDataError,
    MarketDataSnapshot,
    MarketTicker,
)

OKX_INTERVALS = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
}
OKX_MAX_CANDLE_LIMIT = 1000
OKX_CANDLE_MIN_COLUMNS = 6


class OkxSpotMarketClient:
    exchange = ExchangeId.OKX

    def __init__(self, base_url: str, timeout_seconds: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def to_exchange_symbol(symbol: str) -> str:
        return symbol.replace("/", "-").upper()

    @staticmethod
    def to_exchange_interval(timeframe: str) -> str:
        try:
            return OKX_INTERVALS[timeframe]
        except KeyError as exc:
            raise ExchangeMarketDataError(f"Unsupported OKX interval: {timeframe}") from exc

    def get_market_data(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
    ) -> MarketDataSnapshot:
        exchange_symbol = self.to_exchange_symbol(symbol)
        interval = self.to_exchange_interval(timeframe)
        limit = max(1, min(limit, OKX_MAX_CANDLE_LIMIT))
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(self.timeout_seconds, 2))

        try:
            with httpx.Client(base_url=self.base_url, timeout=timeout) as client:
                ticker_response = client.get("/api/v5/market/ticker", params={"instId": exchange_symbol})
                candle_response = client.get(
                    "/api/v5/market/candles",
                    params={"instId": exchange_symbol, "bar": interval, "limit": limit},
                )
        except httpx.RequestError as exc:
            raise ExchangeMarketDataError(f"OKX public market request failed: {exc}") from exc

        self._raise_for_exchange_error(ticker_response, "ticker")
        self._raise_for_exchange_error(candle_response, "candles")

        ticker_payload = self._extract_data(ticker_response.json(), "ticker")[0]
        candle_payload = self._extract_data(candle_response.json(), "candles")
        open_24h = float(ticker_payload.get("open24h") or 0)
        last_price = float(ticker_payload["last"])
        change_24h = ((last_price - open_24h) / open_24h * 100) if open_24h else 0

        candles = [self._parse_candle(row, symbol=symbol) for row in reversed(candle_payload)]

        return MarketDataSnapshot(
            exchange=self.exchange,
            symbol=symbol,
            timeframe=timeframe,
            ticker=MarketTicker(
                symbol=symbol,
                last_price=last_price,
                change_24h_percent=change_24h,
                volume_24h=float(ticker_payload.get("volCcy24h") or ticker_payload.get("vol24h") or 0),
                received_at=datetime.now(timezone.utc),
            ),
            candles=candles,
        )

    @staticmethod
    def _raise_for_exchange_error(response: httpx.Response, name: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ExchangeMarketDataError(f"OKX {name} request failed: {exc}") from exc

    @staticmethod
    def _extract_data(payload: dict[str, object], name: str) -> list:
        if payload.get("code") != "0":
            raise ExchangeMarketDataError(f"OKX {name} response error: {payload}")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ExchangeMarketDataError(f"OKX {name} response missing data")
        return data

    @staticmethod
    def _parse_candle(row: object, symbol: str) -> Candle:
        if not isinstance(row, list) or len(row) < OKX_CANDLE_MIN_COLUMNS:
            raise ExchangeMarketDataError(f"OKX candles response has invalid row for {symbol}: {row}")

        try:
            timestamp = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
            open_price = float(row[1])
            high = float(row[2])
            low = float(row[3])
            close = float(row[4])
            volume = float(row[5])
        except (TypeError, ValueError) as exc:
            raise ExchangeMarketDataError(f"OKX candles response has invalid numeric row for {symbol}: {row}") from exc

        if high < low:
            raise ExchangeMarketDataError(f"OKX candles response has high below low for {symbol}: {row}")

        return Candle(
            timestamp=timestamp,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )

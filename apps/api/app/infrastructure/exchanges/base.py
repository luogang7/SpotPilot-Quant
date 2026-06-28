from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.models import Balance, Candle, ExchangeId, Order


class ExchangeMarketDataError(RuntimeError):
    """Raised when a public exchange market data request fails."""


class ExchangeTradingNotConfiguredError(RuntimeError):
    """Raised when private trading APIs are used without an explicit safe setup."""


class ExchangeTradingError(RuntimeError):
    """Raised when a private exchange trading request fails."""


@dataclass(frozen=True)
class MarketTicker:
    symbol: str
    last_price: float
    change_24h_percent: float
    volume_24h: float
    received_at: datetime


@dataclass(frozen=True)
class MarketDataSnapshot:
    exchange: ExchangeId
    symbol: str
    timeframe: str
    ticker: MarketTicker
    candles: list[Candle]


@dataclass(frozen=True)
class SpotOrderRequest:
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: float | None = None
    client_order_id: str | None = None


class SpotMarketDataClient(Protocol):
    exchange: ExchangeId

    def get_market_data(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
    ) -> MarketDataSnapshot:
        """Fetch public ticker and candle data for a spot symbol."""


class SpotTradingClient(Protocol):
    exchange: ExchangeId

    def get_balances(self) -> list[Balance]:
        """Fetch private account balances after API key and permission checks."""

    def create_order(self, request: SpotOrderRequest) -> Order:
        """Create a spot-only order after risk checks."""

    def cancel_order(self, symbol: str, order_id: str) -> Order:
        """Cancel a spot order."""


class NotConfiguredSpotTradingClient:
    def __init__(self, exchange: ExchangeId) -> None:
        self.exchange = exchange

    def get_balances(self) -> list[Balance]:
        raise ExchangeTradingNotConfiguredError(
            f"{self.exchange.value} private API is not configured",
        )

    def create_order(self, request: SpotOrderRequest) -> Order:
        raise ExchangeTradingNotConfiguredError(
            f"{self.exchange.value} private API is not configured for spot order {request.symbol}",
        )

    def cancel_order(self, symbol: str, order_id: str) -> Order:
        raise ExchangeTradingNotConfiguredError(
            f"{self.exchange.value} private API is not configured for order {order_id} on {symbol}",
        )

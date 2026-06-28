from app.core.config import Settings
from app.domain.models import ExchangeId
from app.infrastructure.exchanges.base import (
    ExchangeMarketDataError,
    ExchangeTradingNotConfiguredError,
    NotConfiguredSpotTradingClient,
    SpotMarketDataClient,
    SpotTradingClient,
)
from app.infrastructure.exchanges.binance import BinanceSpotMarketClient
from app.infrastructure.exchanges.ccxt_spot import CcxtSpotTradingClient
from app.infrastructure.exchanges.okx import OkxSpotMarketClient


def get_spot_market_client(exchange: ExchangeId, settings: Settings) -> SpotMarketDataClient:
    if exchange == ExchangeId.BINANCE:
        return BinanceSpotMarketClient(
            base_url=settings.binance_spot_base_url,
            timeout_seconds=settings.exchange_api_timeout_seconds,
        )
    if exchange == ExchangeId.OKX:
        return OkxSpotMarketClient(
            base_url=settings.okx_rest_base_url,
            timeout_seconds=settings.exchange_api_timeout_seconds,
        )
    raise ExchangeMarketDataError(f"Unsupported exchange: {exchange}")


def get_spot_trading_client(exchange: ExchangeId, settings: Settings) -> SpotTradingClient:
    if exchange == ExchangeId.BINANCE:
        if not settings.binance_spot_trading_enabled:
            return NotConfiguredSpotTradingClient(exchange)
        if not settings.binance_api_key or not settings.binance_api_secret:
            raise ExchangeTradingNotConfiguredError("binance API key and secret are required")
        return CcxtSpotTradingClient(
            exchange=exchange,
            exchange_id="binance",
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            sandbox=settings.binance_sandbox,
            timeout_seconds=settings.exchange_api_timeout_seconds,
        )
    if exchange == ExchangeId.OKX:
        if not settings.okx_spot_trading_enabled:
            return NotConfiguredSpotTradingClient(exchange)
        if not settings.okx_api_key or not settings.okx_api_secret or not settings.okx_api_passphrase:
            raise ExchangeTradingNotConfiguredError("okx API key, secret and passphrase are required")
        return CcxtSpotTradingClient(
            exchange=exchange,
            exchange_id="okx",
            api_key=settings.okx_api_key,
            api_secret=settings.okx_api_secret,
            password=settings.okx_api_passphrase,
            sandbox=settings.okx_sandbox,
            timeout_seconds=settings.exchange_api_timeout_seconds,
        )
    raise ExchangeTradingNotConfiguredError(f"Unsupported exchange: {exchange}")

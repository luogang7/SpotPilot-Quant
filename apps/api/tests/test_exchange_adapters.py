import httpx
import pytest

from app.domain.models import ExchangeId
from app.infrastructure.exchanges.base import ExchangeMarketDataError, SpotOrderRequest
from app.infrastructure.exchanges.binance import BinanceSpotMarketClient
from app.infrastructure.exchanges.ccxt_spot import CcxtSpotTradingClient
from app.infrastructure.exchanges.okx import OKX_MAX_CANDLE_LIMIT, OkxSpotMarketClient


def test_binance_symbol_and_interval_mapping() -> None:
    assert BinanceSpotMarketClient.to_exchange_symbol("BTC/USDT") == "BTCUSDT"
    assert BinanceSpotMarketClient.to_exchange_symbol("eth-usdt") == "ETHUSDT"
    assert BinanceSpotMarketClient.to_exchange_interval("1h") == "1h"


def test_binance_base_url_candidates_prefer_configured_endpoint() -> None:
    assert BinanceSpotMarketClient.candidate_base_urls("https://api1.binance.com/")[:2] == [
        "https://api1.binance.com",
        "https://api.binance.com",
    ]


def test_binance_retries_fallback_endpoint_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_base_urls: list[str] = []

    class StubResponse:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self._payload

    class StubHttpClient:
        def __init__(self, base_url: str, *args: object, **kwargs: object) -> None:
            self.base_url = base_url
            seen_base_urls.append(base_url)

        def __enter__(self) -> "StubHttpClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, path: str, params: dict[str, object]) -> StubResponse:
            if self.base_url == "https://primary.test":
                raise httpx.TimeoutException("timed out")

            if path.endswith("/klines"):
                return StubResponse(
                    [[1710000000000, "100", "104", "99", "102", "10"]],
                )
            return StubResponse(
                {"lastPrice": "102", "priceChangePercent": "2", "volume": "1000"},
            )

    monkeypatch.setattr("app.infrastructure.exchanges.binance.httpx.Client", StubHttpClient)

    snapshot = BinanceSpotMarketClient("https://primary.test").get_market_data("BTC/USDT", "1h")

    assert seen_base_urls[:2] == ["https://primary.test", "https://api.binance.com"]
    assert snapshot.ticker.last_price == 102
    assert snapshot.candles[0].close == 102


def test_okx_symbol_and_interval_mapping() -> None:
    assert OkxSpotMarketClient.to_exchange_symbol("BTC/USDT") == "BTC-USDT"
    assert OkxSpotMarketClient.to_exchange_symbol("eth-usdt") == "ETH-USDT"
    assert OkxSpotMarketClient.to_exchange_interval("1h") == "1H"


def test_rejects_unsupported_intervals() -> None:
    with pytest.raises(ExchangeMarketDataError):
        BinanceSpotMarketClient.to_exchange_interval("2h")
    with pytest.raises(ExchangeMarketDataError):
        OkxSpotMarketClient.to_exchange_interval("2h")


def test_okx_parses_candle_rows_and_preserves_oldest_first_order() -> None:
    rows = [
        ["1710003600000", "102", "106", "101", "105", "12", "1200", "1200", "1"],
        ["1710000000000", "100", "104", "99", "102", "10", "1000", "1000", "1"],
    ]

    candles = [OkxSpotMarketClient._parse_candle(row, "BTC/USDT") for row in reversed(rows)]

    assert [candle.close for candle in candles] == [102, 105]
    assert candles[0].timestamp.isoformat() == "2024-03-09T16:00:00+00:00"
    assert candles[1].volume == 12


def test_okx_rejects_invalid_candle_rows() -> None:
    with pytest.raises(ExchangeMarketDataError, match="invalid row"):
        OkxSpotMarketClient._parse_candle(["1710000000000", "100"], "BTC/USDT")

    with pytest.raises(ExchangeMarketDataError, match="high below low"):
        OkxSpotMarketClient._parse_candle(
            ["1710000000000", "100", "98", "99", "102", "10"],
            "BTC/USDT",
        )


def test_okx_candle_limit_supports_market_page_request_size(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    client = OkxSpotMarketClient("https://example.test")

    class StubResponse:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self._payload

    class StubHttpClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> "StubHttpClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, path: str, params: dict[str, object]) -> StubResponse:
            if path.endswith("/candles"):
                seen["candle_params"] = params
                return StubResponse(
                    {
                        "code": "0",
                        "data": [["1710000000000", "100", "104", "99", "102", "10"]],
                    },
                )
            return StubResponse(
                {
                    "code": "0",
                    "data": [{"last": "102", "open24h": "100", "volCcy24h": "1000"}],
                },
            )

    monkeypatch.setattr("app.infrastructure.exchanges.okx.httpx.Client", StubHttpClient)

    snapshot = client.get_market_data("BTC/USDT", "1h", 1000)

    assert seen["candle_params"] == {"instId": "BTC-USDT", "bar": "1H", "limit": OKX_MAX_CANDLE_LIMIT}
    assert snapshot.candles[0].close == 102


def test_ccxt_spot_client_maps_private_balances_and_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class FakeExchange:
        def __init__(self, config: dict[str, object]) -> None:
            seen["config"] = config

        def privateGetAccount(self, params: dict[str, object]) -> dict[str, object]:
            seen["account_params"] = params
            return {
                "balances": [
                    {"asset": "USDT", "free": "100", "locked": "2"},
                    {"asset": "BTC", "free": "0.01", "locked": "0"},
                    {"asset": "ZERO", "free": "0", "locked": "0"},
                ],
            }

        def fetch_balance(self, params: dict[str, object]) -> dict[str, object]:
            seen["balance_params"] = params
            return {
                "free": {"USDT": 100, "BTC": 0.01, "ZERO": 0},
                "used": {"USDT": 2, "BTC": 0, "ZERO": 0},
                "total": {"USDT": 102, "BTC": 0.01, "ZERO": 0},
            }

        def create_order(
            self,
            symbol: str,
            type: str,
            side: str,
            amount: float,
            price: float | None,
            params: dict[str, object],
        ) -> dict[str, object]:
            seen["order"] = {
                "symbol": symbol,
                "type": type,
                "side": side,
                "amount": amount,
                "price": price,
                "params": params,
            }
            return {
                "id": "EX-1",
                "symbol": symbol,
                "side": side,
                "type": type,
                "amount": amount,
                "price": price,
                "status": "open",
                "timestamp": 1710000000000,
            }

        def cancel_order(self, order_id: str, symbol: str, params: dict[str, object]) -> dict[str, object]:
            seen["cancel"] = {"order_id": order_id, "symbol": symbol, "params": params}
            return {"id": order_id, "symbol": symbol, "status": "canceled"}

    class FakeCcxt:
        binance = FakeExchange

    monkeypatch.setitem(__import__("sys").modules, "ccxt", FakeCcxt)

    client = CcxtSpotTradingClient(
        exchange=ExchangeId.BINANCE,
        exchange_id="binance",
        api_key="key",
        api_secret="secret",
        timeout_seconds=3,
    )

    balances = client.get_balances()
    order = client.create_order(
        SpotOrderRequest(
            symbol="BTC/USDT",
            side="buy",
            order_type="limit",
            quantity=0.01,
            price=50_000,
            client_order_id="cid-1",
        ),
    )
    canceled = client.cancel_order("BTC/USDT", "EX-1")

    assert seen["account_params"] == {"recvWindow": 10000}
    assert "balance_params" not in seen
    assert [balance.asset for balance in balances] == ["BTC", "USDT"]
    assert seen["order"] == {
        "symbol": "BTC/USDT",
        "type": "limit",
        "side": "buy",
        "amount": 0.01,
        "price": 50_000,
        "params": {"newClientOrderId": "cid-1"},
    }
    assert order.order_id == "EX-1"
    assert order.exchange == ExchangeId.BINANCE
    assert canceled.status == "canceled"
    assert seen["cancel"] == {"order_id": "EX-1", "symbol": "BTC/USDT", "params": {"type": "spot"}}

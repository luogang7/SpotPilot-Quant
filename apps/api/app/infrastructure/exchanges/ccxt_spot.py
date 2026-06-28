from datetime import datetime, timezone
from typing import Any

from app.domain.models import Balance, ExchangeId, Order
from app.infrastructure.exchanges.base import (
    ExchangeTradingError,
    SpotOrderRequest,
)


class CcxtSpotTradingClient:
    """Small spot-only wrapper around CCXT private trading APIs."""

    def __init__(
        self,
        exchange: ExchangeId,
        exchange_id: str,
        api_key: str,
        api_secret: str,
        password: str | None = None,
        sandbox: bool = False,
        timeout_seconds: int = 10,
    ) -> None:
        self.exchange = exchange
        self._client = self._build_client(
            exchange_id=exchange_id,
            api_key=api_key,
            api_secret=api_secret,
            password=password,
            sandbox=sandbox,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _build_client(
        exchange_id: str,
        api_key: str,
        api_secret: str,
        password: str | None,
        sandbox: bool,
        timeout_seconds: int,
    ) -> Any:
        try:
            import ccxt  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ExchangeTradingError(
                "ccxt integration dependency is not installed; install apps/api[integrations]",
            ) from exc

        exchange_class = getattr(ccxt, exchange_id)
        config: dict[str, Any] = {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "timeout": max(1, timeout_seconds) * 1000,
            "options": {
                "defaultType": "spot",
            },
        }
        if password:
            config["password"] = password

        client = exchange_class(config)
        if sandbox and hasattr(client, "set_sandbox_mode"):
            client.set_sandbox_mode(True)
        return client

    def get_balances(self) -> list[Balance]:
        if self.exchange == ExchangeId.BINANCE and hasattr(self._client, "privateGetAccount"):
            return self._get_binance_spot_account_balances()

        return self._get_ccxt_balances()

    def _get_ccxt_balances(self) -> list[Balance]:
        try:
            payload = self._client.fetch_balance({"type": "spot"})
        except Exception as exc:  # noqa: BLE001 - normalize third-party exceptions.
            raise ExchangeTradingError(f"{self.exchange.value} fetch_balance failed: {exc}") from exc

        balances: list[Balance] = []
        totals = payload.get("total") or {}
        free = payload.get("free") or {}
        used = payload.get("used") or {}
        assets = sorted(set(totals) | set(free) | set(used))
        for asset in assets:
            total_value = self._float_or_zero(totals.get(asset))
            free_value = self._float_or_zero(free.get(asset))
            locked_value = self._float_or_zero(used.get(asset))
            if total_value <= 0 and free_value <= 0 and locked_value <= 0:
                continue
            balances.append(
                Balance(
                    asset=asset,
                    free=free_value,
                    locked=locked_value,
                    total=total_value or free_value + locked_value,
                ),
            )
        return balances

    def _get_binance_spot_account_balances(self) -> list[Balance]:
        try:
            payload = self._client.privateGetAccount({"recvWindow": 10000})
        except Exception as exc:  # noqa: BLE001 - normalize third-party exceptions.
            raise ExchangeTradingError(
                f"{self.exchange.value} spot account balance fetch failed: {exc}",
            ) from exc

        entries = payload.get("balances") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise ExchangeTradingError(f"{self.exchange.value} spot account response missing balances")

        balances: list[Balance] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            asset = str(entry.get("asset") or "").upper()
            if not asset:
                continue
            free_value = self._float_or_zero(entry.get("free"))
            locked_value = self._float_or_zero(entry.get("locked"))
            total_value = free_value + locked_value
            if total_value <= 0:
                continue
            balances.append(
                Balance(
                    asset=asset,
                    free=free_value,
                    locked=locked_value,
                    total=total_value,
                ),
            )
        return sorted(balances, key=lambda balance: balance.asset)

    def create_order(self, request: SpotOrderRequest) -> Order:
        exchange_symbol = self._to_exchange_symbol(request.symbol)
        order_type = request.order_type.lower()
        side = request.side.lower()
        price = request.price if order_type == "limit" else None
        params: dict[str, object] = {}
        if request.client_order_id:
            if self.exchange == ExchangeId.BINANCE:
                params["newClientOrderId"] = request.client_order_id
            elif self.exchange == ExchangeId.OKX:
                params["clOrdId"] = request.client_order_id
            else:
                params["clientOrderId"] = request.client_order_id

        try:
            payload = self._client.create_order(
                symbol=exchange_symbol,
                type=order_type,
                side=side,
                amount=request.quantity,
                price=price,
                params=params,
            )
        except Exception as exc:  # noqa: BLE001 - normalize third-party exceptions.
            raise ExchangeTradingError(
                f"{self.exchange.value} create_order failed for {request.symbol}: {exc}",
            ) from exc

        return self._to_order(payload, fallback_symbol=request.symbol, fallback_side=side, fallback_type=order_type)

    def cancel_order(self, symbol: str, order_id: str) -> Order:
        exchange_symbol = self._to_exchange_symbol(symbol)
        try:
            payload = self._client.cancel_order(order_id, exchange_symbol, params={"type": "spot"})
        except Exception as exc:  # noqa: BLE001 - normalize third-party exceptions.
            raise ExchangeTradingError(
                f"{self.exchange.value} cancel_order failed for {order_id} on {symbol}: {exc}",
            ) from exc

        return self._to_order(payload, fallback_symbol=symbol, fallback_side="cancel_order", fallback_type="cancel")

    def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        try:
            exchange_symbol = self._to_exchange_symbol(symbol) if symbol else None
            payload = self._client.fetch_open_orders(exchange_symbol, None, None, {"type": "spot"})
        except Exception as exc:  # noqa: BLE001 - normalize third-party exceptions.
            raise ExchangeTradingError(
                f"{self.exchange.value} fetch_open_orders failed: {exc}",
            ) from exc

        orders: list[Order] = []
        for entry in payload or []:
            if not isinstance(entry, dict):
                continue
            orders.append(
                self._to_order(
                    entry,
                    fallback_symbol=symbol or "",
                    fallback_side=str(entry.get("side") or "buy"),
                    fallback_type=str(entry.get("type") or "limit"),
                ),
            )
        return orders

    def get_last_price(self, symbol: str) -> float | None:
        exchange_symbol = self._to_exchange_symbol(symbol)
        try:
            ticker = self._client.fetch_ticker(exchange_symbol)
        except Exception:  # noqa: BLE001 - normalize third-party exceptions.
            return None

        last = self._optional_float(ticker.get("last") if isinstance(ticker, dict) else None)
        if last is not None:
            return last
        return self._optional_float(ticker.get("close") if isinstance(ticker, dict) else None)

    def _to_exchange_symbol(self, symbol: str) -> str:
        return symbol.replace("-", "/").upper()

    def _to_local_symbol(self, symbol: str | None, fallback: str) -> str:
        if not symbol:
            return fallback
        return symbol.replace("-", "/").upper()

    def _to_order(
        self,
        payload: dict[str, Any],
        fallback_symbol: str,
        fallback_side: str,
        fallback_type: str,
    ) -> Order:
        fee_payload = payload.get("fee")
        fee = None
        if isinstance(fee_payload, dict):
            fee = self._optional_float(fee_payload.get("cost"))

        timestamp = payload.get("timestamp")
        created_at = (
            datetime.fromtimestamp(int(timestamp) / 1000, tz=timezone.utc)
            if timestamp
            else datetime.now(timezone.utc)
        )
        amount = self._optional_float(payload.get("amount"))
        filled = self._optional_float(payload.get("filled"))
        price = self._optional_float(payload.get("price"))
        average = self._optional_float(payload.get("average"))

        return Order(
            exchange=self.exchange,
            order_id=str(payload.get("id") or payload.get("clientOrderId") or ""),
            symbol=self._to_local_symbol(payload.get("symbol"), fallback_symbol),
            side=str(payload.get("side") or fallback_side),
            order_type=str(payload.get("type") or fallback_type),
            price=price or average or 0,
            quantity=amount or filled or 0,
            fee=fee,
            status=str(payload.get("status") or "submitted"),
            created_at=created_at,
        )

    @staticmethod
    def _optional_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _float_or_zero(cls, value: object) -> float:
        return cls._optional_float(value) or 0

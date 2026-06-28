from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeVar

from app.domain.models import BacktestRequest, BacktestResult, BacktestTrade, Candle

BacktestParameters = TypeVar("BacktestParameters")


class Backtester(Protocol[BacktestParameters]):
    def run(
        self,
        request: BacktestRequest,
        candles: list[Candle],
        parameters: BacktestParameters | None = None,
    ) -> BacktestResult:
        """Run one spot-only backtest implementation."""


@dataclass(frozen=True)
class MovingAverageCrossParameters:
    fast_window: int = 12
    slow_window: int = 48


@dataclass(frozen=True)
class RsiMeanReversionParameters:
    period: int = 14
    buy_below: float = 30
    sell_above: float = 70


@dataclass(frozen=True)
class GridParameters:
    lower_price: float = 45_000
    upper_price: float = 70_000
    grid_count: int = 8
    order_size_percent: float = 10

    @property
    def grid_step(self) -> float:
        return (self.upper_price - self.lower_price) / self.grid_count


@dataclass(frozen=True)
class BreakoutParameters:
    lookback: int = 20
    volume_multiplier: float = 1.5


@dataclass(frozen=True)
class BollingerBandsParameters:
    period: int = 20
    deviation_multiplier: float = 2
    exit_on_middle: bool = True


@dataclass(frozen=True)
class MacdTrendParameters:
    fast_window: int = 12
    slow_window: int = 26
    signal_window: int = 9


@dataclass(frozen=True)
class TrendPullbackParameters:
    short_window: int = 20
    long_window: int = 60


@dataclass(frozen=True)
class DcaParameters:
    interval_candles: int = 24
    order_size_percent: float = 10


@dataclass
class SpotBacktestState:
    cash: float
    quantity: float = 0.0
    entry_price: float = 0.0
    entry_capital: float = 0.0
    entry_fee: float = 0.0
    entry_time: datetime | None = None


@dataclass
class GridLot:
    quantity: float
    entry_price: float
    entry_capital: float
    entry_fee: float
    entry_time: datetime


class SpotBacktestMath:
    @staticmethod
    def buy_all_cash(state: SpotBacktestState, request: BacktestRequest, candle: Candle) -> None:
        execution_price = candle.close * (1 + request.slippage_rate)
        state.entry_capital = state.cash
        state.entry_fee = state.entry_capital * request.fee_rate
        state.quantity = max((state.entry_capital - state.entry_fee) / execution_price, 0)
        state.cash = 0
        state.entry_price = execution_price
        state.entry_time = candle.timestamp

    @staticmethod
    def sell_existing(
        state: SpotBacktestState,
        request: BacktestRequest,
        candle: Candle,
        exit_reason: str,
    ) -> BacktestTrade:
        if state.entry_time is None:
            raise ValueError("Cannot close a spot backtest position before it is opened")
        execution_price = candle.close * (1 - request.slippage_rate)
        gross = state.quantity * execution_price
        exit_fee = gross * request.fee_rate
        state.cash = gross - exit_fee
        trade = BacktestTrade(
            opened_at=state.entry_time,
            closed_at=candle.timestamp,
            symbol=request.symbol,
            side="long",
            entry_price=state.entry_price,
            exit_price=execution_price,
            pnl=state.cash - state.entry_capital,
            fee=state.entry_fee + exit_fee,
            exit_reason=exit_reason,
        )
        state.quantity = 0
        state.entry_price = 0
        state.entry_capital = 0
        state.entry_fee = 0
        state.entry_time = None
        return trade

    @staticmethod
    def sma(values: list[float], window: int) -> list[float | None]:
        output: list[float | None] = []
        rolling = 0.0
        for index, value in enumerate(values):
            rolling += value
            if index >= window:
                rolling -= values[index - window]
            output.append(rolling / window if index >= window - 1 else None)
        return output

    @staticmethod
    def rolling_std(values: list[float], window: int) -> list[float | None]:
        output: list[float | None] = []
        for index in range(len(values)):
            if index < window - 1:
                output.append(None)
                continue
            window_values = values[index - window + 1 : index + 1]
            mean = sum(window_values) / window
            variance = sum((value - mean) ** 2 for value in window_values) / window
            output.append(math.sqrt(variance))
        return output

    @staticmethod
    def ema(values: list[float], window: int) -> list[float | None]:
        if window <= 0:
            return [None] * len(values)
        output: list[float | None] = [None] * len(values)
        if len(values) < window:
            return output

        previous = sum(values[:window]) / window
        output[window - 1] = previous
        multiplier = 2 / (window + 1)
        for index in range(window, len(values)):
            previous = ((values[index] - previous) * multiplier) + previous
            output[index] = previous
        return output

    @staticmethod
    def ema_optional(values: list[float | None], window: int) -> list[float | None]:
        if window <= 0:
            return [None] * len(values)

        output: list[float | None] = [None] * len(values)
        seed: list[float] = []
        previous: float | None = None
        multiplier = 2 / (window + 1)
        for index, value in enumerate(values):
            if value is None:
                continue
            if previous is None:
                seed.append(value)
                if len(seed) == window:
                    previous = sum(seed) / window
                    output[index] = previous
                continue
            previous = ((value - previous) * multiplier) + previous
            output[index] = previous
        return output

    @staticmethod
    def macd(
        values: list[float],
        fast_window: int,
        slow_window: int,
        signal_window: int,
    ) -> tuple[list[float | None], list[float | None]]:
        fast_ema = SpotBacktestMath.ema(values, fast_window)
        slow_ema = SpotBacktestMath.ema(values, slow_window)
        macd_line = [
            fast - slow if fast is not None and slow is not None else None
            for fast, slow in zip(fast_ema, slow_ema, strict=False)
        ]
        signal_line = SpotBacktestMath.ema_optional(macd_line, signal_window)
        return macd_line, signal_line

    @staticmethod
    def bollinger_bands(
        values: list[float],
        period: int,
        deviation_multiplier: float,
    ) -> tuple[list[float | None], list[float | None], list[float | None]]:
        middle = SpotBacktestMath.sma(values, period)
        deviation = SpotBacktestMath.rolling_std(values, period)
        upper = [
            mean + (std * deviation_multiplier)
            if mean is not None and std is not None
            else None
            for mean, std in zip(middle, deviation, strict=False)
        ]
        lower = [
            mean - (std * deviation_multiplier)
            if mean is not None and std is not None
            else None
            for mean, std in zip(middle, deviation, strict=False)
        ]
        return lower, middle, upper

    @staticmethod
    def rsi(values: list[float], period: int) -> list[float | None]:
        output: list[float | None] = [None] * len(values)
        if len(values) <= period:
            return output

        gains: list[float] = []
        losses: list[float] = []
        for index in range(1, period + 1):
            change = values[index] - values[index - 1]
            gains.append(max(change, 0))
            losses.append(abs(min(change, 0)))

        average_gain = sum(gains) / period
        average_loss = sum(losses) / period
        output[period] = SpotBacktestMath._rsi_value(average_gain, average_loss)

        for index in range(period + 1, len(values)):
            change = values[index] - values[index - 1]
            gain = max(change, 0)
            loss = abs(min(change, 0))
            average_gain = ((average_gain * (period - 1)) + gain) / period
            average_loss = ((average_loss * (period - 1)) + loss) / period
            output[index] = SpotBacktestMath._rsi_value(average_gain, average_loss)
        return output

    @staticmethod
    def _rsi_value(average_gain: float, average_loss: float) -> float:
        if average_loss == 0:
            return 100
        relative_strength = average_gain / average_loss
        return 100 - (100 / (1 + relative_strength))

    @staticmethod
    def finish(
        request: BacktestRequest,
        candles: list[Candle],
        trades: list[BacktestTrade],
        equity_curve: list[float],
        final_equity: float,
        message: str,
    ) -> BacktestResult:
        if equity_curve:
            equity_curve[-1] = final_equity
        return BacktestResult(
            request=request,
            status="completed",
            message=message,
            total_return_percent=SpotBacktestMath.percent_return(
                request.initial_capital,
                final_equity,
            ),
            annual_return_percent=SpotBacktestMath.annual_return(
                request.initial_capital,
                final_equity,
                candles,
            ),
            max_drawdown_percent=SpotBacktestMath.max_drawdown(equity_curve),
            win_rate_percent=SpotBacktestMath.win_rate(trades),
            profit_factor=SpotBacktestMath.profit_factor(trades),
            trade_count=len(trades),
            equity_curve=[round(value, 4) for value in equity_curve],
            trades=trades,
        )

    @staticmethod
    def percent_return(initial: float, final: float) -> float:
        if initial <= 0:
            return 0
        return round(((final - initial) / initial) * 100, 4)

    @classmethod
    def annual_return(cls, initial: float, final: float, candles: list[Candle]) -> float:
        if initial <= 0 or final <= 0 or len(candles) < 2:
            return cls.percent_return(initial, final)
        days = max((candles[-1].timestamp - candles[0].timestamp).total_seconds() / 86_400, 1)
        return round(((final / initial) ** (365 / days) - 1) * 100, 4)

    @staticmethod
    def max_drawdown(equity_curve: list[float]) -> float:
        if not equity_curve:
            return 0
        peak = equity_curve[0]
        max_drawdown = 0.0
        for equity in equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak)
        return round(max_drawdown * 100, 4)

    @staticmethod
    def win_rate(trades: list[BacktestTrade]) -> float:
        if not trades:
            return 0
        winners = sum(1 for trade in trades if trade.pnl > 0)
        return round((winners / len(trades)) * 100, 4)

    @staticmethod
    def profit_factor(trades: list[BacktestTrade]) -> float:
        gross_profit = sum(trade.pnl for trade in trades if trade.pnl > 0)
        gross_loss = abs(sum(trade.pnl for trade in trades if trade.pnl < 0))
        if gross_profit == 0 and gross_loss == 0:
            return 0
        if gross_loss == 0:
            return round(gross_profit, 4)
        return round(gross_profit / gross_loss, 4)

    @staticmethod
    def empty_result(request: BacktestRequest, status: str, message: str) -> BacktestResult:
        return BacktestResult(
            request=request,
            status=status,
            message=message,
            total_return_percent=0,
            annual_return_percent=0,
            max_drawdown_percent=0,
            win_rate_percent=0,
            profit_factor=0,
            trade_count=0,
            equity_curve=[],
            trades=[],
        )


class MovingAverageCrossBacktester:
    """Long-only spot MA Cross backtester."""

    def run(
        self,
        request: BacktestRequest,
        candles: list[Candle],
        parameters: MovingAverageCrossParameters | None = None,
    ) -> BacktestResult:
        params = parameters or MovingAverageCrossParameters()
        required = params.slow_window + 2
        if len(candles) < required:
            return SpotBacktestMath.empty_result(
                request=request,
                status="data_unavailable",
                message=f"MA Cross requires at least {required} candles, got {len(candles)}",
            )

        state = SpotBacktestState(cash=request.initial_capital)
        trades: list[BacktestTrade] = []
        equity_curve: list[float] = []
        closes = [candle.close for candle in candles]
        fast_ma = SpotBacktestMath.sma(closes, params.fast_window)
        slow_ma = SpotBacktestMath.sma(closes, params.slow_window)

        for index, candle in enumerate(candles):
            equity_curve.append(state.cash + state.quantity * candle.close)
            if index == 0 or fast_ma[index] is None or slow_ma[index] is None:
                continue
            previous_fast = fast_ma[index - 1]
            previous_slow = slow_ma[index - 1]
            if previous_fast is None or previous_slow is None:
                continue

            crosses_up = previous_fast <= previous_slow and fast_ma[index] > slow_ma[index]
            crosses_down = previous_fast >= previous_slow and fast_ma[index] < slow_ma[index]
            if crosses_up and state.quantity == 0 and state.cash > 0:
                SpotBacktestMath.buy_all_cash(state, request, candle)
                continue
            if crosses_down and state.quantity > 0:
                trades.append(
                    SpotBacktestMath.sell_existing(state, request, candle, "ma_cross_down"),
                )

        if state.quantity > 0:
            trades.append(
                SpotBacktestMath.sell_existing(state, request, candles[-1], "end_of_data"),
            )

        return SpotBacktestMath.finish(
            request=request,
            candles=candles,
            trades=trades,
            equity_curve=equity_curve,
            final_equity=state.cash + (state.quantity * candles[-1].close),
            message="MA Cross completed with spot long-only rules",
        )


class RsiMeanReversionBacktester:
    """Long-only spot RSI mean reversion backtester."""

    def run(
        self,
        request: BacktestRequest,
        candles: list[Candle],
        parameters: RsiMeanReversionParameters | None = None,
    ) -> BacktestResult:
        params = parameters or RsiMeanReversionParameters()
        required = params.period + 2
        if len(candles) < required:
            return SpotBacktestMath.empty_result(
                request=request,
                status="data_unavailable",
                message=(
                    f"RSI Mean Reversion requires at least {required} candles, "
                    f"got {len(candles)}"
                ),
            )

        state = SpotBacktestState(cash=request.initial_capital)
        trades: list[BacktestTrade] = []
        equity_curve: list[float] = []
        rsi_values = SpotBacktestMath.rsi([candle.close for candle in candles], params.period)

        for index, candle in enumerate(candles):
            equity_curve.append(state.cash + state.quantity * candle.close)
            current_rsi = rsi_values[index]
            if current_rsi is None:
                continue
            if current_rsi <= params.buy_below and state.quantity == 0 and state.cash > 0:
                SpotBacktestMath.buy_all_cash(state, request, candle)
                continue
            if current_rsi >= params.sell_above and state.quantity > 0:
                trades.append(SpotBacktestMath.sell_existing(state, request, candle, "rsi_exit"))

        if state.quantity > 0:
            trades.append(
                SpotBacktestMath.sell_existing(state, request, candles[-1], "end_of_data"),
            )

        return SpotBacktestMath.finish(
            request=request,
            candles=candles,
            trades=trades,
            equity_curve=equity_curve,
            final_equity=state.cash + (state.quantity * candles[-1].close),
            message="RSI Mean Reversion completed with spot long-only rules",
        )


class GridBacktester:
    """Long-only spot grid backtester with fixed-size buy lots."""

    def run(
        self,
        request: BacktestRequest,
        candles: list[Candle],
        parameters: GridParameters | None = None,
    ) -> BacktestResult:
        params = parameters or GridParameters()
        if len(candles) < 2:
            return SpotBacktestMath.empty_result(
                request=request,
                status="data_unavailable",
                message=f"Grid Trading requires at least 2 candles, got {len(candles)}",
            )
        if not self._valid_parameters(params):
            return SpotBacktestMath.empty_result(
                request=request,
                status="invalid_parameters",
                message=(
                    "Grid Trading requires 0 < lower_price < upper_price, "
                    "grid_count >= 2 and 0 < order_size_percent <= 100"
                ),
            )

        cash = request.initial_capital
        lots: list[GridLot] = []
        trades: list[BacktestTrade] = []
        equity_curve: list[float] = []
        order_budget = request.initial_capital * (params.order_size_percent / 100)

        for index, candle in enumerate(candles):
            equity_curve.append(cash + sum(lot.quantity * candle.close for lot in lots))
            if index == 0:
                continue

            previous_level = self._grid_level(candles[index - 1].close, params)
            current_level = self._grid_level(candle.close, params)

            if current_level < previous_level and cash > 0:
                budget = min(cash, order_budget)
                if budget > 0:
                    cash -= budget
                    lots.append(self._buy_lot(request=request, candle=candle, budget=budget))
                continue

            if current_level > previous_level and lots:
                lot = lots.pop(0)
                trade, proceeds = self._sell_lot(
                    request=request,
                    candle=candle,
                    lot=lot,
                    exit_reason="grid_level_up",
                )
                cash += proceeds
                trades.append(trade)

        for lot in lots:
            trade, proceeds = self._sell_lot(
                request=request,
                candle=candles[-1],
                lot=lot,
                exit_reason="end_of_data",
            )
            cash += proceeds
            trades.append(trade)

        return SpotBacktestMath.finish(
            request=request,
            candles=candles,
            trades=trades,
            equity_curve=equity_curve,
            final_equity=cash,
            message="Grid Trading completed with spot long-only fixed-lot rules",
        )

    @staticmethod
    def _valid_parameters(params: GridParameters) -> bool:
        return (
            params.lower_price > 0
            and params.upper_price > params.lower_price
            and params.grid_count >= 2
            and 0 < params.order_size_percent <= 100
        )

    @staticmethod
    def _grid_level(price: float, params: GridParameters) -> int:
        if price <= params.lower_price:
            return 0
        if price >= params.upper_price:
            return params.grid_count
        return int((price - params.lower_price) / params.grid_step)

    @staticmethod
    def _buy_lot(request: BacktestRequest, candle: Candle, budget: float) -> GridLot:
        execution_price = candle.close * (1 + request.slippage_rate)
        entry_fee = budget * request.fee_rate
        quantity = max((budget - entry_fee) / execution_price, 0)
        return GridLot(
            quantity=quantity,
            entry_price=execution_price,
            entry_capital=budget,
            entry_fee=entry_fee,
            entry_time=candle.timestamp,
        )

    @staticmethod
    def _sell_lot(
        request: BacktestRequest,
        candle: Candle,
        lot: GridLot,
        exit_reason: str,
    ) -> tuple[BacktestTrade, float]:
        execution_price = candle.close * (1 - request.slippage_rate)
        gross = lot.quantity * execution_price
        exit_fee = gross * request.fee_rate
        proceeds = gross - exit_fee
        return (
            BacktestTrade(
                opened_at=lot.entry_time,
                closed_at=candle.timestamp,
                symbol=request.symbol,
                side="long",
                entry_price=lot.entry_price,
                exit_price=execution_price,
                pnl=proceeds - lot.entry_capital,
                fee=lot.entry_fee + exit_fee,
                exit_reason=exit_reason,
            ),
            proceeds,
        )


class BreakoutBacktester:
    """Long-only spot breakout backtester with volume confirmation."""

    def run(
        self,
        request: BacktestRequest,
        candles: list[Candle],
        parameters: BreakoutParameters | None = None,
    ) -> BacktestResult:
        params = parameters or BreakoutParameters()
        required = params.lookback + 2
        if len(candles) < required:
            return SpotBacktestMath.empty_result(
                request=request,
                status="data_unavailable",
                message=f"Breakout requires at least {required} candles, got {len(candles)}",
            )

        state = SpotBacktestState(cash=request.initial_capital)
        trades: list[BacktestTrade] = []
        equity_curve: list[float] = []

        for index, candle in enumerate(candles):
            equity_curve.append(state.cash + state.quantity * candle.close)
            if index < params.lookback:
                continue

            previous_window = candles[index - params.lookback : index]
            resistance = max(item.high for item in previous_window)
            support = min(item.low for item in previous_window)
            average_volume = sum(item.volume for item in previous_window) / params.lookback
            volume_confirmed = candle.volume >= average_volume * params.volume_multiplier
            if (
                candle.close > resistance
                and volume_confirmed
                and state.quantity == 0
                and state.cash > 0
            ):
                SpotBacktestMath.buy_all_cash(state, request, candle)
                continue
            if candle.close < support and state.quantity > 0:
                trades.append(
                    SpotBacktestMath.sell_existing(state, request, candle, "breakout_failed"),
                )

        if state.quantity > 0:
            trades.append(
                SpotBacktestMath.sell_existing(state, request, candles[-1], "end_of_data"),
            )

        return SpotBacktestMath.finish(
            request=request,
            candles=candles,
            trades=trades,
            equity_curve=equity_curve,
            final_equity=state.cash + (state.quantity * candles[-1].close),
            message="Breakout completed with spot long-only rules",
        )


class BollingerBandsBacktester:
    """Long-only spot Bollinger Bands mean-reversion backtester."""

    def run(
        self,
        request: BacktestRequest,
        candles: list[Candle],
        parameters: BollingerBandsParameters | None = None,
    ) -> BacktestResult:
        params = parameters or BollingerBandsParameters()
        required = params.period + 1
        if len(candles) < required:
            return SpotBacktestMath.empty_result(
                request=request,
                status="data_unavailable",
                message=f"Bollinger Bands requires at least {required} candles, got {len(candles)}",
            )

        state = SpotBacktestState(cash=request.initial_capital)
        trades: list[BacktestTrade] = []
        equity_curve: list[float] = []
        closes = [candle.close for candle in candles]
        lower, middle, upper = SpotBacktestMath.bollinger_bands(
            closes,
            params.period,
            params.deviation_multiplier,
        )

        for index, candle in enumerate(candles):
            equity_curve.append(state.cash + state.quantity * candle.close)
            lower_band = lower[index]
            middle_band = middle[index]
            upper_band = upper[index]
            if lower_band is None or middle_band is None or upper_band is None:
                continue
            if candle.close <= lower_band and state.quantity == 0 and state.cash > 0:
                SpotBacktestMath.buy_all_cash(state, request, candle)
                continue
            exit_band = middle_band if params.exit_on_middle else upper_band
            if candle.close >= exit_band and state.quantity > 0:
                trades.append(
                    SpotBacktestMath.sell_existing(state, request, candle, "bollinger_exit"),
                )

        if state.quantity > 0:
            trades.append(
                SpotBacktestMath.sell_existing(state, request, candles[-1], "end_of_data"),
            )

        return SpotBacktestMath.finish(
            request=request,
            candles=candles,
            trades=trades,
            equity_curve=equity_curve,
            final_equity=state.cash + (state.quantity * candles[-1].close),
            message="Bollinger Bands completed with spot long-only rules",
        )


class MacdTrendBacktester:
    """Long-only spot MACD trend-following backtester."""

    def run(
        self,
        request: BacktestRequest,
        candles: list[Candle],
        parameters: MacdTrendParameters | None = None,
    ) -> BacktestResult:
        params = parameters or MacdTrendParameters()
        required = params.slow_window + params.signal_window + 1
        if len(candles) < required:
            return SpotBacktestMath.empty_result(
                request=request,
                status="data_unavailable",
                message=f"MACD Trend requires at least {required} candles, got {len(candles)}",
            )

        state = SpotBacktestState(cash=request.initial_capital)
        trades: list[BacktestTrade] = []
        equity_curve: list[float] = []
        macd_line, signal_line = SpotBacktestMath.macd(
            [candle.close for candle in candles],
            params.fast_window,
            params.slow_window,
            params.signal_window,
        )

        for index, candle in enumerate(candles):
            equity_curve.append(state.cash + state.quantity * candle.close)
            if index == 0:
                continue
            previous_macd = macd_line[index - 1]
            previous_signal = signal_line[index - 1]
            current_macd = macd_line[index]
            current_signal = signal_line[index]
            if None in {previous_macd, previous_signal, current_macd, current_signal}:
                continue
            crosses_up = previous_macd <= previous_signal and current_macd > current_signal
            crosses_down = previous_macd >= previous_signal and current_macd < current_signal
            if crosses_up and state.quantity == 0 and state.cash > 0:
                SpotBacktestMath.buy_all_cash(state, request, candle)
                continue
            if crosses_down and state.quantity > 0:
                trades.append(
                    SpotBacktestMath.sell_existing(state, request, candle, "macd_cross_down"),
                )

        if state.quantity > 0:
            trades.append(
                SpotBacktestMath.sell_existing(state, request, candles[-1], "end_of_data"),
            )

        return SpotBacktestMath.finish(
            request=request,
            candles=candles,
            trades=trades,
            equity_curve=equity_curve,
            final_equity=state.cash + (state.quantity * candles[-1].close),
            message="MACD Trend completed with spot long-only rules",
        )


class TrendPullbackBacktester:
    """Long-only spot trend pullback backtester using short and long moving averages."""

    def run(
        self,
        request: BacktestRequest,
        candles: list[Candle],
        parameters: TrendPullbackParameters | None = None,
    ) -> BacktestResult:
        params = parameters or TrendPullbackParameters()
        required = params.long_window + 1
        if len(candles) < required:
            return SpotBacktestMath.empty_result(
                request=request,
                status="data_unavailable",
                message=f"Trend Pullback requires at least {required} candles, got {len(candles)}",
            )

        state = SpotBacktestState(cash=request.initial_capital)
        trades: list[BacktestTrade] = []
        equity_curve: list[float] = []
        closes = [candle.close for candle in candles]
        short_ma = SpotBacktestMath.sma(closes, params.short_window)
        long_ma = SpotBacktestMath.sma(closes, params.long_window)

        for index, candle in enumerate(candles):
            equity_curve.append(state.cash + state.quantity * candle.close)
            if index == 0:
                continue
            previous_short = short_ma[index - 1]
            current_short = short_ma[index]
            current_long = long_ma[index]
            if None in {previous_short, current_short, current_long}:
                continue

            trend_up = current_short > current_long and candle.close > current_long
            reclaimed_short = (
                candles[index - 1].close <= previous_short
                and candle.close > current_short
            )
            trend_failed = candle.close < current_long or current_short < current_long
            if trend_up and reclaimed_short and state.quantity == 0 and state.cash > 0:
                SpotBacktestMath.buy_all_cash(state, request, candle)
                continue
            if trend_failed and state.quantity > 0:
                trades.append(
                    SpotBacktestMath.sell_existing(state, request, candle, "trend_failed"),
                )

        if state.quantity > 0:
            trades.append(
                SpotBacktestMath.sell_existing(state, request, candles[-1], "end_of_data"),
            )

        return SpotBacktestMath.finish(
            request=request,
            candles=candles,
            trades=trades,
            equity_curve=equity_curve,
            final_equity=state.cash + (state.quantity * candles[-1].close),
            message="Trend Pullback completed with spot long-only rules",
        )


class DcaBacktester:
    """Long-only spot dollar-cost averaging backtester with fixed periodic buys."""

    def run(
        self,
        request: BacktestRequest,
        candles: list[Candle],
        parameters: DcaParameters | None = None,
    ) -> BacktestResult:
        params = parameters or DcaParameters()
        if not candles:
            return SpotBacktestMath.empty_result(
                request=request,
                status="data_unavailable",
                message="DCA requires at least 1 candle, got 0",
            )

        cash = request.initial_capital
        lots: list[GridLot] = []
        trades: list[BacktestTrade] = []
        equity_curve: list[float] = []
        order_budget = request.initial_capital * (params.order_size_percent / 100)

        for index, candle in enumerate(candles):
            equity_curve.append(cash + sum(lot.quantity * candle.close for lot in lots))
            if index % params.interval_candles != 0 or cash <= 0:
                continue
            budget = min(cash, order_budget)
            if budget > 0:
                cash -= budget
                lots.append(
                    GridBacktester._buy_lot(request=request, candle=candle, budget=budget),
                )

        for lot in lots:
            trade, proceeds = GridBacktester._sell_lot(
                request=request,
                candle=candles[-1],
                lot=lot,
                exit_reason="end_of_data",
            )
            cash += proceeds
            trades.append(trade)

        return SpotBacktestMath.finish(
            request=request,
            candles=candles,
            trades=trades,
            equity_curve=equity_curve,
            final_equity=cash,
            message="DCA completed with spot long-only fixed-interval rules",
        )


def export_backtest_result(result: BacktestResult, export_format: str) -> tuple[str, str, str]:
    if export_format == "json":
        return (
            "application/json",
            "json",
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        )
    if export_format != "csv":
        raise ValueError(f"Unsupported backtest export format: {export_format}")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["metric", "value"])
    writer.writerow(["status", result.status])
    writer.writerow(["message", result.message])
    writer.writerow(["strategy_id", result.request.strategy_id])
    writer.writerow(["symbol", result.request.symbol])
    writer.writerow(["exchange", result.request.exchange.value])
    writer.writerow(["timeframe", result.request.timeframe])
    writer.writerow(["start_date", result.request.start_date])
    writer.writerow(["end_date", result.request.end_date])
    writer.writerow(["initial_capital", result.request.initial_capital])
    writer.writerow(["total_return_percent", result.total_return_percent])
    writer.writerow(["annual_return_percent", result.annual_return_percent])
    writer.writerow(["max_drawdown_percent", result.max_drawdown_percent])
    writer.writerow(["win_rate_percent", result.win_rate_percent])
    writer.writerow(["profit_factor", result.profit_factor])
    writer.writerow(["trade_count", result.trade_count])
    writer.writerow([])
    writer.writerow(
        [
            "opened_at",
            "closed_at",
            "symbol",
            "side",
            "entry_price",
            "exit_price",
            "pnl",
            "fee",
            "exit_reason",
        ],
    )
    for trade in result.trades:
        writer.writerow(
            [
                trade.opened_at.isoformat(),
                trade.closed_at.isoformat(),
                trade.symbol,
                trade.side,
                trade.entry_price,
                trade.exit_price,
                trade.pnl,
                trade.fee,
                trade.exit_reason,
            ],
        )
    return ("text/csv; charset=utf-8", "csv", output.getvalue())

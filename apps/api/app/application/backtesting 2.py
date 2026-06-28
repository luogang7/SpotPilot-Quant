from dataclasses import dataclass

from app.domain.models import BacktestRequest, BacktestResult, BacktestTrade, Candle


@dataclass(frozen=True)
class MovingAverageCrossParameters:
    fast_window: int = 12
    slow_window: int = 48


class MovingAverageCrossBacktester:
    """Long-only spot MA Cross backtester.

    The engine buys spot with available cash on a fast-over-slow cross and sells the
    existing spot position on a fast-under-slow cross. It never shorts or uses leverage.
    """

    def run(
        self,
        request: BacktestRequest,
        candles: list[Candle],
        parameters: MovingAverageCrossParameters | None = None,
    ) -> BacktestResult:
        params = parameters or MovingAverageCrossParameters()
        required = params.slow_window + 2
        if len(candles) < required:
            return self._empty_result(
                request=request,
                status="data_unavailable",
                message=f"MA Cross requires at least {required} candles, got {len(candles)}",
            )

        cash = request.initial_capital
        quantity = 0.0
        entry_price = 0.0
        entry_capital = 0.0
        entry_fee = 0.0
        entry_time = None
        trades: list[BacktestTrade] = []
        equity_curve: list[float] = []
        closes = [candle.close for candle in candles]
        fast_ma = self._sma(closes, params.fast_window)
        slow_ma = self._sma(closes, params.slow_window)

        for index, candle in enumerate(candles):
            equity_curve.append(cash + quantity * candle.close)
            if index == 0 or fast_ma[index] is None or slow_ma[index] is None:
                continue
            previous_fast = fast_ma[index - 1]
            previous_slow = slow_ma[index - 1]
            if previous_fast is None or previous_slow is None:
                continue

            crosses_up = previous_fast <= previous_slow and fast_ma[index] > slow_ma[index]
            crosses_down = previous_fast >= previous_slow and fast_ma[index] < slow_ma[index]

            if crosses_up and quantity == 0 and cash > 0:
                execution_price = candle.close * (1 + request.slippage_rate)
                entry_capital = cash
                entry_fee = entry_capital * request.fee_rate
                quantity = max((entry_capital - entry_fee) / execution_price, 0)
                cash = 0
                entry_price = execution_price
                entry_time = candle.timestamp
                continue

            if crosses_down and quantity > 0 and entry_time is not None:
                execution_price = candle.close * (1 - request.slippage_rate)
                gross = quantity * execution_price
                exit_fee = gross * request.fee_rate
                cash = gross - exit_fee
                trades.append(
                    BacktestTrade(
                        opened_at=entry_time,
                        closed_at=candle.timestamp,
                        symbol=request.symbol,
                        side="long",
                        entry_price=entry_price,
                        exit_price=execution_price,
                        pnl=cash - entry_capital,
                        fee=entry_fee + exit_fee,
                        exit_reason="ma_cross_down",
                    ),
                )
                quantity = 0
                entry_price = 0
                entry_capital = 0
                entry_fee = 0
                entry_time = None

        if quantity > 0 and entry_time is not None:
            final_candle = candles[-1]
            execution_price = final_candle.close * (1 - request.slippage_rate)
            gross = quantity * execution_price
            exit_fee = gross * request.fee_rate
            cash = gross - exit_fee
            trades.append(
                BacktestTrade(
                    opened_at=entry_time,
                    closed_at=final_candle.timestamp,
                    symbol=request.symbol,
                    side="long",
                    entry_price=entry_price,
                    exit_price=execution_price,
                    pnl=cash - entry_capital,
                    fee=entry_fee + exit_fee,
                    exit_reason="end_of_data",
                ),
            )
            quantity = 0

        final_equity = cash + (quantity * candles[-1].close)
        if equity_curve:
            equity_curve[-1] = final_equity
        return BacktestResult(
            request=request,
            status="completed",
            message="MA Cross completed with spot long-only rules",
            total_return_percent=self._percent_return(request.initial_capital, final_equity),
            annual_return_percent=self._annual_return(request.initial_capital, final_equity, candles),
            max_drawdown_percent=self._max_drawdown(equity_curve),
            win_rate_percent=self._win_rate(trades),
            profit_factor=self._profit_factor(trades),
            trade_count=len(trades),
            equity_curve=[round(value, 4) for value in equity_curve],
            trades=trades,
        )

    @staticmethod
    def _sma(values: list[float], window: int) -> list[float | None]:
        output: list[float | None] = []
        rolling = 0.0
        for index, value in enumerate(values):
            rolling += value
            if index >= window:
                rolling -= values[index - window]
            output.append(rolling / window if index >= window - 1 else None)
        return output

    @staticmethod
    def _percent_return(initial: float, final: float) -> float:
        if initial <= 0:
            return 0
        return round(((final - initial) / initial) * 100, 4)

    @classmethod
    def _annual_return(cls, initial: float, final: float, candles: list[Candle]) -> float:
        if initial <= 0 or final <= 0 or len(candles) < 2:
            return cls._percent_return(initial, final)
        days = max((candles[-1].timestamp - candles[0].timestamp).total_seconds() / 86_400, 1)
        return round(((final / initial) ** (365 / days) - 1) * 100, 4)

    @staticmethod
    def _max_drawdown(equity_curve: list[float]) -> float:
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
    def _win_rate(trades: list[BacktestTrade]) -> float:
        if not trades:
            return 0
        winners = sum(1 for trade in trades if trade.pnl > 0)
        return round((winners / len(trades)) * 100, 4)

    @staticmethod
    def _profit_factor(trades: list[BacktestTrade]) -> float:
        gross_profit = sum(trade.pnl for trade in trades if trade.pnl > 0)
        gross_loss = abs(sum(trade.pnl for trade in trades if trade.pnl < 0))
        if gross_profit == 0 and gross_loss == 0:
            return 0
        if gross_loss == 0:
            return round(gross_profit, 4)
        return round(gross_profit / gross_loss, 4)

    @staticmethod
    def _empty_result(request: BacktestRequest, status: str, message: str) -> BacktestResult:
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

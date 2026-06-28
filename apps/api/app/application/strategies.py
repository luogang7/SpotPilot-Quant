from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.application.backtesting import (
    Backtester,
    BollingerBandsBacktester,
    BollingerBandsParameters,
    BreakoutBacktester,
    BreakoutParameters,
    DcaBacktester,
    DcaParameters,
    GridBacktester,
    GridParameters,
    MacdTrendBacktester,
    MacdTrendParameters,
    MovingAverageCrossBacktester,
    MovingAverageCrossParameters,
    RsiMeanReversionBacktester,
    RsiMeanReversionParameters,
    SpotBacktestMath,
    TrendPullbackBacktester,
    TrendPullbackParameters,
)
from app.domain.models import (
    BacktestRequest,
    BacktestResult,
    Candle,
    SpotSignalAction,
    StrategyConfig,
    StrategySignal,
)

StrategyParameter = float | int | str | bool


class StrategyAdapter(Protocol):
    definition: StrategyDefinition

    def build_signal(
        self,
        *,
        config: StrategyConfig,
        candles: list[Candle],
        symbol: str,
        correlation_id: str,
    ) -> StrategySignal | None:
        """Return the latest signal for this strategy, or None when data is insufficient."""

    def run_backtest(
        self,
        *,
        request: BacktestRequest,
        config: StrategyConfig,
        candles: list[Candle],
    ) -> BacktestResult:
        """Run a spot-only historical simulation for this strategy."""


@dataclass(frozen=True)
class StrategyDefinition:
    id: str
    name: str
    family: str
    description: str
    default_enabled: bool
    default_mode: str
    default_status: str
    default_parameters: dict[str, StrategyParameter]
    default_risk_controls: dict[str, StrategyParameter]
    supports_signals: bool = True
    supports_backtest: bool = True
    supports_live: bool = False

    def to_config(self) -> StrategyConfig:
        return StrategyConfig(
            id=self.id,
            name=self.name,
            enabled=self.default_enabled,
            mode=self.default_mode,
            status=self.default_status,
            parameters=dict(self.default_parameters),
            risk_controls=dict(self.default_risk_controls),
            recent_signals=[],
            family=self.family,
            description=self.description,
            supports_signals=self.supports_signals,
            supports_backtest=self.supports_backtest,
            supports_live=self.supports_live,
        )


class StrategyValidationError(ValueError):
    """Raised when a strategy configuration cannot be converted into runtime parameters."""


class StrategyRegistry:
    def __init__(self, adapters: list[StrategyAdapter]) -> None:
        self._adapters = {adapter.definition.id: adapter for adapter in adapters}

    def list_definitions(self) -> list[StrategyDefinition]:
        return [adapter.definition for adapter in self._adapters.values()]

    def list_default_configs(self) -> list[StrategyConfig]:
        return [definition.to_config() for definition in self.list_definitions()]

    def get_definition(self, strategy_id: str) -> StrategyDefinition | None:
        adapter = self._adapters.get(strategy_id)
        return adapter.definition if adapter is not None else None

    def get_default_config(self, strategy_id: str) -> StrategyConfig | None:
        definition = self.get_definition(strategy_id)
        return definition.to_config() if definition is not None else None

    def get_adapter(self, strategy_id: str) -> StrategyAdapter | None:
        return self._adapters.get(strategy_id)


class SignalEngine:
    def __init__(self, registry: StrategyRegistry) -> None:
        self.registry = registry

    def generate(
        self,
        *,
        strategy: StrategyConfig,
        candles: list[Candle],
        symbol: str,
        correlation_id: str,
    ) -> StrategySignal | None:
        adapter = self.registry.get_adapter(strategy.id)
        if adapter is None or not adapter.definition.supports_signals:
            return None
        try:
            return adapter.build_signal(
                config=strategy,
                candles=candles,
                symbol=symbol,
                correlation_id=correlation_id,
            )
        except StrategyValidationError:
            return None


class BacktestEngine:
    def __init__(self, registry: StrategyRegistry) -> None:
        self.registry = registry

    def run(
        self,
        *,
        request: BacktestRequest,
        strategy: StrategyConfig,
        candles: list[Candle],
    ) -> BacktestResult:
        adapter = self.registry.get_adapter(request.strategy_id)
        if adapter is None or not adapter.definition.supports_backtest:
            return SpotBacktestMath.empty_result(
                request=request,
                status="unsupported_strategy",
                message=f"Unsupported backtesting strategy: {request.strategy_id}",
            )
        try:
            return adapter.run_backtest(request=request, config=strategy, candles=candles)
        except StrategyValidationError:
            return SpotBacktestMath.empty_result(
                request=request,
                status="invalid_parameters",
                message=f"Invalid backtest parameters for {request.strategy_id}",
            )


class MovingAverageCrossStrategy:
    definition = StrategyDefinition(
        id="ma_cross",
        name="MA Cross",
        family="trend_following",
        description="快慢均线交叉产生现货买入或卖出现有持仓信号。",
        default_enabled=True,
        default_mode="dry_run",
        default_status="ready",
        default_parameters={"fast_window": 12, "slow_window": 48},
        default_risk_controls={
            "max_position_percent": 30,
            "stop_loss_percent": 3,
            "take_profit_percent": 6,
        },
        supports_live=True,
    )

    def __init__(self) -> None:
        self.backtester: Backtester[MovingAverageCrossParameters] = MovingAverageCrossBacktester()

    def build_signal(
        self,
        *,
        config: StrategyConfig,
        candles: list[Candle],
        symbol: str,
        correlation_id: str,
    ) -> StrategySignal | None:
        params = self._parameters(config)
        required = params.slow_window + 1
        if len(candles) < required:
            return None

        closes = [candle.close for candle in candles]
        fast_ma = SpotBacktestMath.sma(closes, params.fast_window)
        slow_ma = SpotBacktestMath.sma(closes, params.slow_window)
        index = len(candles) - 1
        previous_fast = fast_ma[index - 1]
        previous_slow = slow_ma[index - 1]
        current_fast = fast_ma[index]
        current_slow = slow_ma[index]
        if None in {previous_fast, previous_slow, current_fast, current_slow}:
            return None

        candle = candles[-1]
        if previous_fast <= previous_slow and current_fast > current_slow:
            return _strategy_signal(
                symbol=symbol,
                strategy=config.id,
                action=SpotSignalAction.BUY,
                price=candle.close,
                reason=(
                    f"fast_ma({params.fast_window}) crossed above "
                    f"slow_ma({params.slow_window})"
                ),
                correlation_id=correlation_id,
            )
        if previous_fast >= previous_slow and current_fast < current_slow:
            return _strategy_signal(
                symbol=symbol,
                strategy=config.id,
                action=SpotSignalAction.SELL_EXISTING,
                price=candle.close,
                reason=(
                    f"fast_ma({params.fast_window}) crossed below "
                    f"slow_ma({params.slow_window})"
                ),
                correlation_id=correlation_id,
            )
        return _hold_signal(
            symbol=symbol,
            strategy=config.id,
            price=candle.close,
            reason="MA trend has no fresh crossover",
            correlation_id=correlation_id,
        )

    def run_backtest(
        self,
        *,
        request: BacktestRequest,
        config: StrategyConfig,
        candles: list[Candle],
    ) -> BacktestResult:
        return self.backtester.run(
            request=request,
            candles=candles,
            parameters=self._parameters(config),
        )

    @staticmethod
    def _parameters(config: StrategyConfig) -> MovingAverageCrossParameters:
        try:
            fast_window = int(config.parameters["fast_window"])
            slow_window = int(config.parameters["slow_window"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StrategyValidationError(
                "MA Cross requires numeric fast_window and slow_window",
            ) from exc
        if fast_window <= 0 or slow_window <= 0 or fast_window >= slow_window:
            raise StrategyValidationError(
                "MA Cross requires positive fast_window < slow_window parameters",
            )
        return MovingAverageCrossParameters(fast_window=fast_window, slow_window=slow_window)


class RsiMeanReversionStrategy:
    definition = StrategyDefinition(
        id="rsi_mean_reversion",
        name="RSI Mean Reversion",
        family="mean_reversion",
        description="RSI 进入超卖区买入，进入超买区卖出现有现货。",
        default_enabled=True,
        default_mode="dry_run",
        default_status="ready",
        default_parameters={"period": 14, "buy_below": 30, "sell_above": 70},
        default_risk_controls={
            "max_position_percent": 20,
            "stop_loss_percent": 4,
            "take_profit_percent": 5,
            "spot_only": True,
        },
        supports_live=True,
    )

    def __init__(self) -> None:
        self.backtester: Backtester[RsiMeanReversionParameters] = RsiMeanReversionBacktester()

    def build_signal(
        self,
        *,
        config: StrategyConfig,
        candles: list[Candle],
        symbol: str,
        correlation_id: str,
    ) -> StrategySignal | None:
        params = self._parameters(config)
        if len(candles) < params.period + 1:
            return None
        rsi_values = SpotBacktestMath.rsi([candle.close for candle in candles], params.period)
        current_rsi = rsi_values[-1]
        if current_rsi is None:
            return None

        candle = candles[-1]
        if current_rsi <= params.buy_below:
            return _strategy_signal(
                symbol=symbol,
                strategy=config.id,
                action=SpotSignalAction.BUY,
                price=candle.close,
                reason=f"RSI({params.period})={current_rsi:.2f} <= buy_below={params.buy_below:g}",
                correlation_id=correlation_id,
            )
        if current_rsi >= params.sell_above:
            return _strategy_signal(
                symbol=symbol,
                strategy=config.id,
                action=SpotSignalAction.SELL_EXISTING,
                price=candle.close,
                reason=(
                    f"RSI({params.period})={current_rsi:.2f} >= "
                    f"sell_above={params.sell_above:g}"
                ),
                correlation_id=correlation_id,
            )
        return _hold_signal(
            symbol=symbol,
            strategy=config.id,
            price=candle.close,
            reason=f"RSI({params.period})={current_rsi:.2f} remains inside neutral band",
            correlation_id=correlation_id,
        )

    def run_backtest(
        self,
        *,
        request: BacktestRequest,
        config: StrategyConfig,
        candles: list[Candle],
    ) -> BacktestResult:
        return self.backtester.run(
            request=request,
            candles=candles,
            parameters=self._parameters(config),
        )

    @staticmethod
    def _parameters(config: StrategyConfig) -> RsiMeanReversionParameters:
        try:
            period = int(config.parameters["period"])
            buy_below = float(config.parameters["buy_below"])
            sell_above = float(config.parameters["sell_above"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StrategyValidationError(
                "RSI requires numeric period, buy_below and sell_above",
            ) from exc
        if period <= 1 or not (0 <= buy_below < sell_above <= 100):
            raise StrategyValidationError(
                "RSI requires period > 1 and 0 <= buy_below < sell_above <= 100",
            )
        return RsiMeanReversionParameters(period=period, buy_below=buy_below, sell_above=sell_above)


class GridTradingStrategy:
    definition = StrategyDefinition(
        id="grid",
        name="Grid Trading",
        family="range",
        description="在价格区间内按网格层级低买高卖，适合震荡行情的现货验证。",
        default_enabled=True,
        default_mode="dry_run",
        default_status="ready",
        default_parameters={
            "lower_price": 45000,
            "upper_price": 70000,
            "grid_count": 8,
            "order_size_percent": 10,
        },
        default_risk_controls={
            "max_position_percent": 25,
            "stop_loss_percent": 8,
            "take_profit_percent": 10,
            "spot_only": True,
        },
        supports_live=True,
    )

    def __init__(self) -> None:
        self.backtester: Backtester[GridParameters] = GridBacktester()

    def build_signal(
        self,
        *,
        config: StrategyConfig,
        candles: list[Candle],
        symbol: str,
        correlation_id: str,
    ) -> StrategySignal | None:
        params = self._parameters(config)
        if len(candles) < 2:
            return None

        previous = candles[-2]
        current = candles[-1]
        if current.close < params.lower_price or current.close > params.upper_price:
            return _hold_signal(
                symbol=symbol,
                strategy=config.id,
                price=current.close,
                reason="price is outside configured grid range",
                correlation_id=correlation_id,
            )

        previous_level = self._grid_level(previous.close, params)
        current_level = self._grid_level(current.close, params)
        if current_level < previous_level:
            return _strategy_signal(
                symbol=symbol,
                strategy=config.id,
                action=SpotSignalAction.BUY,
                price=current.close,
                reason=f"price moved down into grid level {current_level}",
                correlation_id=correlation_id,
            )
        if current_level > previous_level:
            return _strategy_signal(
                symbol=symbol,
                strategy=config.id,
                action=SpotSignalAction.SELL_EXISTING,
                price=current.close,
                reason=f"price moved up into grid level {current_level}",
                correlation_id=correlation_id,
            )
        return _hold_signal(
            symbol=symbol,
            strategy=config.id,
            price=current.close,
            reason=f"price remains in grid level {current_level}",
            correlation_id=correlation_id,
        )

    def run_backtest(
        self,
        *,
        request: BacktestRequest,
        config: StrategyConfig,
        candles: list[Candle],
    ) -> BacktestResult:
        return self.backtester.run(
            request=request,
            candles=candles,
            parameters=self._parameters(config),
        )

    @staticmethod
    def _parameters(config: StrategyConfig) -> GridParameters:
        try:
            lower_price = float(config.parameters["lower_price"])
            upper_price = float(config.parameters["upper_price"])
            grid_count = int(config.parameters["grid_count"])
            order_size_percent = float(config.parameters["order_size_percent"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StrategyValidationError(
                "Grid requires lower_price, upper_price, grid_count and order_size_percent",
            ) from exc
        if lower_price <= 0 or upper_price <= lower_price or grid_count < 2:
            raise StrategyValidationError(
                "Grid requires 0 < lower_price < upper_price and grid_count >= 2",
            )
        if not 0 < order_size_percent <= 100:
            raise StrategyValidationError("Grid requires 0 < order_size_percent <= 100")
        return GridParameters(
            lower_price=lower_price,
            upper_price=upper_price,
            grid_count=grid_count,
            order_size_percent=order_size_percent,
        )

    @staticmethod
    def _grid_level(price: float, params: GridParameters) -> int:
        if price <= params.lower_price:
            return 0
        if price >= params.upper_price:
            return params.grid_count
        return int((price - params.lower_price) / params.grid_step)


class BreakoutStrategy:
    definition = StrategyDefinition(
        id="breakout",
        name="Breakout",
        family="trend_following",
        description="价格突破近期高点并获得成交量确认时买入，跌破近期低点时卖出现货。",
        default_enabled=True,
        default_mode="dry_run",
        default_status="ready",
        default_parameters={"lookback": 20, "volume_multiplier": 1.5},
        default_risk_controls={
            "max_position_percent": 25,
            "stop_loss_percent": 5,
            "take_profit_percent": 10,
            "spot_only": True,
        },
        supports_live=True,
    )

    def __init__(self) -> None:
        self.backtester: Backtester[BreakoutParameters] = BreakoutBacktester()

    def build_signal(
        self,
        *,
        config: StrategyConfig,
        candles: list[Candle],
        symbol: str,
        correlation_id: str,
    ) -> StrategySignal | None:
        params = self._parameters(config)
        required = params.lookback + 1
        if len(candles) < required:
            return None

        current = candles[-1]
        previous_window = candles[-params.lookback - 1 : -1]
        resistance = max(candle.high for candle in previous_window)
        support = min(candle.low for candle in previous_window)
        average_volume = sum(candle.volume for candle in previous_window) / params.lookback
        volume_confirmed = current.volume >= average_volume * params.volume_multiplier
        if current.close > resistance and volume_confirmed:
            return _strategy_signal(
                symbol=symbol,
                strategy=config.id,
                action=SpotSignalAction.BUY,
                price=current.close,
                reason=(
                    f"close broke resistance={resistance:.4f} with volume "
                    f">= {params.volume_multiplier:g}x average"
                ),
                correlation_id=correlation_id,
            )
        if current.close < support:
            return _strategy_signal(
                symbol=symbol,
                strategy=config.id,
                action=SpotSignalAction.SELL_EXISTING,
                price=current.close,
                reason=f"close fell below support={support:.4f}",
                correlation_id=correlation_id,
            )
        return _hold_signal(
            symbol=symbol,
            strategy=config.id,
            price=current.close,
            reason="price has no confirmed breakout",
            correlation_id=correlation_id,
        )

    def run_backtest(
        self,
        *,
        request: BacktestRequest,
        config: StrategyConfig,
        candles: list[Candle],
    ) -> BacktestResult:
        return self.backtester.run(
            request=request,
            candles=candles,
            parameters=self._parameters(config),
        )

    @staticmethod
    def _parameters(config: StrategyConfig) -> BreakoutParameters:
        try:
            lookback = int(config.parameters["lookback"])
            volume_multiplier = float(config.parameters["volume_multiplier"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StrategyValidationError(
                "Breakout requires numeric lookback and volume_multiplier",
            ) from exc
        if lookback < 2 or volume_multiplier <= 0:
            raise StrategyValidationError(
                "Breakout requires lookback >= 2 and volume_multiplier > 0",
            )
        return BreakoutParameters(lookback=lookback, volume_multiplier=volume_multiplier)


class BollingerBandsStrategy:
    definition = StrategyDefinition(
        id="bollinger_bands",
        name="Bollinger Bands",
        family="mean_reversion",
        description="价格触及布林带下轨时分批买入，回到中轨或上轨时卖出现货。",
        default_enabled=True,
        default_mode="dry_run",
        default_status="ready",
        default_parameters={"period": 20, "deviation_multiplier": 2, "exit_on_middle": True},
        default_risk_controls={
            "max_position_percent": 20,
            "stop_loss_percent": 5,
            "take_profit_percent": 8,
            "spot_only": True,
        },
        supports_live=True,
    )

    def __init__(self) -> None:
        self.backtester: Backtester[BollingerBandsParameters] = BollingerBandsBacktester()

    def build_signal(
        self,
        *,
        config: StrategyConfig,
        candles: list[Candle],
        symbol: str,
        correlation_id: str,
    ) -> StrategySignal | None:
        params = self._parameters(config)
        if len(candles) < params.period:
            return None

        closes = [candle.close for candle in candles]
        lower, middle, upper = SpotBacktestMath.bollinger_bands(
            closes,
            params.period,
            params.deviation_multiplier,
        )
        current_lower = lower[-1]
        current_middle = middle[-1]
        current_upper = upper[-1]
        if None in {current_lower, current_middle, current_upper}:
            return None

        candle = candles[-1]
        if candle.close <= current_lower:
            return _strategy_signal(
                symbol=symbol,
                strategy=config.id,
                action=SpotSignalAction.BUY,
                price=candle.close,
                reason=f"close={candle.close:.4f} touched lower band={current_lower:.4f}",
                correlation_id=correlation_id,
            )

        exit_band = current_middle if params.exit_on_middle else current_upper
        exit_name = "middle" if params.exit_on_middle else "upper"
        if candle.close >= exit_band:
            return _strategy_signal(
                symbol=symbol,
                strategy=config.id,
                action=SpotSignalAction.SELL_EXISTING,
                price=candle.close,
                reason=f"close={candle.close:.4f} reached {exit_name} band={exit_band:.4f}",
                correlation_id=correlation_id,
            )
        return _hold_signal(
            symbol=symbol,
            strategy=config.id,
            price=candle.close,
            reason="price remains inside Bollinger band range",
            correlation_id=correlation_id,
        )

    def run_backtest(
        self,
        *,
        request: BacktestRequest,
        config: StrategyConfig,
        candles: list[Candle],
    ) -> BacktestResult:
        return self.backtester.run(
            request=request,
            candles=candles,
            parameters=self._parameters(config),
        )

    @staticmethod
    def _parameters(config: StrategyConfig) -> BollingerBandsParameters:
        try:
            period = int(config.parameters["period"])
            deviation_multiplier = float(config.parameters["deviation_multiplier"])
            exit_on_middle = _coerce_bool(config.parameters.get("exit_on_middle", True))
        except (KeyError, TypeError, ValueError) as exc:
            raise StrategyValidationError(
                "Bollinger Bands requires numeric period and deviation_multiplier",
            ) from exc
        if period <= 1 or deviation_multiplier <= 0:
            raise StrategyValidationError(
                "Bollinger Bands requires period > 1 and deviation_multiplier > 0",
            )
        return BollingerBandsParameters(
            period=period,
            deviation_multiplier=deviation_multiplier,
            exit_on_middle=exit_on_middle,
        )


class MacdTrendStrategy:
    definition = StrategyDefinition(
        id="macd_trend",
        name="MACD Trend",
        family="trend_following",
        description="MACD 快慢线金叉时买入，死叉时卖出现有现货，适合趋势行情验证。",
        default_enabled=True,
        default_mode="dry_run",
        default_status="ready",
        default_parameters={"fast_window": 12, "slow_window": 26, "signal_window": 9},
        default_risk_controls={
            "max_position_percent": 30,
            "stop_loss_percent": 4,
            "take_profit_percent": 8,
            "spot_only": True,
        },
        supports_live=True,
    )

    def __init__(self) -> None:
        self.backtester: Backtester[MacdTrendParameters] = MacdTrendBacktester()

    def build_signal(
        self,
        *,
        config: StrategyConfig,
        candles: list[Candle],
        symbol: str,
        correlation_id: str,
    ) -> StrategySignal | None:
        params = self._parameters(config)
        required = params.slow_window + params.signal_window + 1
        if len(candles) < required:
            return None

        macd_line, signal_line = SpotBacktestMath.macd(
            [candle.close for candle in candles],
            params.fast_window,
            params.slow_window,
            params.signal_window,
        )
        previous_macd = macd_line[-2]
        previous_signal = signal_line[-2]
        current_macd = macd_line[-1]
        current_signal = signal_line[-1]
        if None in {previous_macd, previous_signal, current_macd, current_signal}:
            return None

        candle = candles[-1]
        if previous_macd <= previous_signal and current_macd > current_signal:
            return _strategy_signal(
                symbol=symbol,
                strategy=config.id,
                action=SpotSignalAction.BUY,
                price=candle.close,
                reason=f"MACD crossed above signal: {current_macd:.4f} > {current_signal:.4f}",
                correlation_id=correlation_id,
            )
        if previous_macd >= previous_signal and current_macd < current_signal:
            return _strategy_signal(
                symbol=symbol,
                strategy=config.id,
                action=SpotSignalAction.SELL_EXISTING,
                price=candle.close,
                reason=f"MACD crossed below signal: {current_macd:.4f} < {current_signal:.4f}",
                correlation_id=correlation_id,
            )
        return _hold_signal(
            symbol=symbol,
            strategy=config.id,
            price=candle.close,
            reason="MACD has no fresh crossover",
            correlation_id=correlation_id,
        )

    def run_backtest(
        self,
        *,
        request: BacktestRequest,
        config: StrategyConfig,
        candles: list[Candle],
    ) -> BacktestResult:
        return self.backtester.run(
            request=request,
            candles=candles,
            parameters=self._parameters(config),
        )

    @staticmethod
    def _parameters(config: StrategyConfig) -> MacdTrendParameters:
        try:
            fast_window = int(config.parameters["fast_window"])
            slow_window = int(config.parameters["slow_window"])
            signal_window = int(config.parameters["signal_window"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StrategyValidationError(
                "MACD Trend requires numeric fast_window, slow_window and signal_window",
            ) from exc
        if (
            fast_window <= 0
            or slow_window <= 0
            or signal_window <= 0
            or fast_window >= slow_window
        ):
            raise StrategyValidationError(
                "MACD Trend requires positive fast_window < slow_window and signal_window > 0",
            )
        return MacdTrendParameters(
            fast_window=fast_window,
            slow_window=slow_window,
            signal_window=signal_window,
        )


class TrendPullbackStrategy:
    definition = StrategyDefinition(
        id="trend_pullback",
        name="Trend Pullback",
        family="trend_following",
        description="长均线保持上行时等待价格回踩短均线后重新站上，用于趋势中的低吸验证。",
        default_enabled=True,
        default_mode="dry_run",
        default_status="ready",
        default_parameters={"short_window": 20, "long_window": 60},
        default_risk_controls={
            "max_position_percent": 25,
            "stop_loss_percent": 4,
            "take_profit_percent": 10,
            "spot_only": True,
        },
        supports_live=True,
    )

    def __init__(self) -> None:
        self.backtester: Backtester[TrendPullbackParameters] = TrendPullbackBacktester()

    def build_signal(
        self,
        *,
        config: StrategyConfig,
        candles: list[Candle],
        symbol: str,
        correlation_id: str,
    ) -> StrategySignal | None:
        params = self._parameters(config)
        required = params.long_window + 1
        if len(candles) < required:
            return None

        closes = [candle.close for candle in candles]
        short_ma = SpotBacktestMath.sma(closes, params.short_window)
        long_ma = SpotBacktestMath.sma(closes, params.long_window)
        previous_short = short_ma[-2]
        current_short = short_ma[-1]
        current_long = long_ma[-1]
        if None in {previous_short, current_short, current_long}:
            return None

        current = candles[-1]
        previous = candles[-2]
        trend_up = current_short > current_long and current.close > current_long
        reclaimed_short = previous.close <= previous_short and current.close > current_short
        trend_failed = current.close < current_long or current_short < current_long
        if trend_up and reclaimed_short:
            return _strategy_signal(
                symbol=symbol,
                strategy=config.id,
                action=SpotSignalAction.BUY,
                price=current.close,
                reason="uptrend pullback reclaimed the short moving average",
                correlation_id=correlation_id,
            )
        if trend_failed:
            return _strategy_signal(
                symbol=symbol,
                strategy=config.id,
                action=SpotSignalAction.SELL_EXISTING,
                price=current.close,
                reason="trend failed below the long moving average",
                correlation_id=correlation_id,
            )
        return _hold_signal(
            symbol=symbol,
            strategy=config.id,
            price=current.close,
            reason="trend pullback setup is not confirmed",
            correlation_id=correlation_id,
        )

    def run_backtest(
        self,
        *,
        request: BacktestRequest,
        config: StrategyConfig,
        candles: list[Candle],
    ) -> BacktestResult:
        return self.backtester.run(
            request=request,
            candles=candles,
            parameters=self._parameters(config),
        )

    @staticmethod
    def _parameters(config: StrategyConfig) -> TrendPullbackParameters:
        try:
            short_window = int(config.parameters["short_window"])
            long_window = int(config.parameters["long_window"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StrategyValidationError(
                "Trend Pullback requires numeric short_window and long_window",
            ) from exc
        if short_window <= 0 or long_window <= 0 or short_window >= long_window:
            raise StrategyValidationError(
                "Trend Pullback requires positive short_window < long_window",
            )
        return TrendPullbackParameters(short_window=short_window, long_window=long_window)


class DcaStrategy:
    definition = StrategyDefinition(
        id="dca",
        name="DCA",
        family="position_building",
        description="按固定 K 线间隔用固定资金比例买入，适合长期分批建仓回测。",
        default_enabled=True,
        default_mode="backtest_only",
        default_status="ready",
        default_parameters={"interval_candles": 24, "order_size_percent": 10},
        default_risk_controls={
            "max_position_percent": 50,
            "stop_loss_percent": 15,
            "take_profit_percent": 30,
            "spot_only": True,
        },
        supports_signals=False,
        supports_live=False,
    )

    def __init__(self) -> None:
        self.backtester: Backtester[DcaParameters] = DcaBacktester()

    def build_signal(
        self,
        *,
        config: StrategyConfig,
        candles: list[Candle],
        symbol: str,
        correlation_id: str,
    ) -> StrategySignal | None:
        return None

    def run_backtest(
        self,
        *,
        request: BacktestRequest,
        config: StrategyConfig,
        candles: list[Candle],
    ) -> BacktestResult:
        return self.backtester.run(
            request=request,
            candles=candles,
            parameters=self._parameters(config),
        )

    @staticmethod
    def _parameters(config: StrategyConfig) -> DcaParameters:
        try:
            interval_candles = int(config.parameters["interval_candles"])
            order_size_percent = float(config.parameters["order_size_percent"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StrategyValidationError(
                "DCA requires numeric interval_candles and order_size_percent",
            ) from exc
        if interval_candles <= 0 or not 0 < order_size_percent <= 100:
            raise StrategyValidationError(
                "DCA requires interval_candles > 0 and 0 < order_size_percent <= 100",
            )
        return DcaParameters(
            interval_candles=interval_candles,
            order_size_percent=order_size_percent,
        )


class FundingRateGuardStrategy:
    definition = StrategyDefinition(
        id="funding_rate_guard",
        name="Funding Rate Guard",
        family="risk_filter",
        description="记录资金费率和合约溢价过滤阈值，用于后续风控接入，不直接产生订单。",
        default_enabled=True,
        default_mode="risk_filter",
        default_status="planned_p1",
        default_parameters={
            "max_funding_rate_percent": 0.05,
            "premium_threshold_percent": 1,
            "lookback_hours": 8,
        },
        default_risk_controls={"cannot_place_orders": True, "spot_only": True},
        supports_signals=False,
        supports_backtest=False,
        supports_live=False,
    )

    def build_signal(
        self,
        *,
        config: StrategyConfig,
        candles: list[Candle],
        symbol: str,
        correlation_id: str,
    ) -> StrategySignal | None:
        return None

    def run_backtest(
        self,
        *,
        request: BacktestRequest,
        config: StrategyConfig,
        candles: list[Candle],
    ) -> BacktestResult:
        return SpotBacktestMath.empty_result(
            request=request,
            status="unsupported_strategy",
            message=f"Unsupported backtesting strategy: {request.strategy_id}",
        )


class AiFilterStrategy:
    definition = StrategyDefinition(
        id="ai_filter",
        name="AI Filter",
        family="risk_filter",
        description="只校验 AI 结构化分析结果，不直接生成交易订单。",
        default_enabled=True,
        default_mode="risk_filter",
        default_status="schema_validator_only",
        default_parameters={"provider": "local_ai_mock", "requires_json_schema": True},
        default_risk_controls={"cannot_place_orders": True},
        supports_signals=False,
        supports_backtest=False,
        supports_live=False,
    )

    def build_signal(
        self,
        *,
        config: StrategyConfig,
        candles: list[Candle],
        symbol: str,
        correlation_id: str,
    ) -> StrategySignal | None:
        return None

    def run_backtest(
        self,
        *,
        request: BacktestRequest,
        config: StrategyConfig,
        candles: list[Candle],
    ) -> BacktestResult:
        return SpotBacktestMath.empty_result(
            request=request,
            status="unsupported_strategy",
            message=f"Unsupported backtesting strategy: {request.strategy_id}",
        )


def default_strategy_registry() -> StrategyRegistry:
    return StrategyRegistry(
        [
            MovingAverageCrossStrategy(),
            RsiMeanReversionStrategy(),
            GridTradingStrategy(),
            BreakoutStrategy(),
            BollingerBandsStrategy(),
            MacdTrendStrategy(),
            TrendPullbackStrategy(),
            DcaStrategy(),
            FundingRateGuardStrategy(),
            AiFilterStrategy(),
        ],
    )


def _coerce_bool(value: StrategyParameter) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _strategy_signal(
    *,
    symbol: str,
    strategy: str,
    action: SpotSignalAction,
    price: float,
    reason: str,
    correlation_id: str,
) -> StrategySignal:
    return StrategySignal(
        symbol=symbol,
        strategy=strategy,
        action=action,
        price=price,
        reason=reason,
        correlation_id=correlation_id,
    )


def _hold_signal(
    *,
    symbol: str,
    strategy: str,
    price: float,
    reason: str,
    correlation_id: str,
) -> StrategySignal:
    return _strategy_signal(
        symbol=symbol,
        strategy=strategy,
        action=SpotSignalAction.HOLD,
        price=price,
        reason=reason,
        correlation_id=correlation_id,
    )

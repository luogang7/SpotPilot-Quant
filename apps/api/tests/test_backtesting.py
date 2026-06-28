from datetime import datetime, timedelta, timezone

from app.application.backtesting import (
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
    TrendPullbackBacktester,
    TrendPullbackParameters,
    export_backtest_result,
)
from app.domain.models import BacktestRequest, Candle


def make_candles(closes: list[float]) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Candle(
            timestamp=start + timedelta(hours=index),
            open=close,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            volume=1000 + index,
        )
        for index, close in enumerate(closes)
    ]


def test_ma_cross_backtest_generates_only_long_spot_trades() -> None:
    backtester = MovingAverageCrossBacktester()
    request = BacktestRequest(initial_capital=10_000, fee_rate=0.001, slippage_rate=0.0005)
    candles = make_candles([10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 7])

    result = backtester.run(
        request=request,
        candles=candles,
        parameters=MovingAverageCrossParameters(fast_window=2, slow_window=3),
    )

    assert result.status == "completed"
    assert result.trade_count >= 1
    assert len(result.equity_curve) == len(candles)
    assert {trade.side for trade in result.trades} == {"long"}
    assert all(trade.fee > 0 for trade in result.trades)


def test_ma_cross_returns_data_unavailable_when_candles_are_insufficient() -> None:
    result = MovingAverageCrossBacktester().run(
        request=BacktestRequest(),
        candles=make_candles([10, 11, 12]),
        parameters=MovingAverageCrossParameters(fast_window=2, slow_window=5),
    )

    assert result.status == "data_unavailable"
    assert result.trade_count == 0
    assert result.trades == []


def test_rsi_mean_reversion_generates_long_only_spot_trades() -> None:
    request = BacktestRequest(initial_capital=10_000, fee_rate=0.001, slippage_rate=0.0005)
    candles = make_candles([100, 96, 92, 88, 84, 80, 82, 84, 88, 92, 96, 100, 104, 108])

    result = RsiMeanReversionBacktester().run(
        request=request,
        candles=candles,
        parameters=RsiMeanReversionParameters(period=3, buy_below=25, sell_above=65),
    )

    assert result.status == "completed"
    assert result.trade_count >= 1
    assert {trade.side for trade in result.trades} == {"long"}
    assert all(trade.exit_reason in {"rsi_exit", "end_of_data"} for trade in result.trades)


def test_breakout_generates_long_only_spot_trades_with_volume_confirmation() -> None:
    request = BacktestRequest(initial_capital=10_000, fee_rate=0.001, slippage_rate=0.0005)
    candles = make_candles([10, 10.2, 10.1, 10.3, 10.2, 11.5, 11.8, 9.6, 9.4])
    candles[5] = candles[5].model_copy(update={"volume": 5000, "high": 11.6})

    result = BreakoutBacktester().run(
        request=request,
        candles=candles,
        parameters=BreakoutParameters(lookback=3, volume_multiplier=1.2),
    )

    assert result.status == "completed"
    assert result.trade_count >= 1
    assert {trade.side for trade in result.trades} == {"long"}
    assert all(trade.exit_reason in {"breakout_failed", "end_of_data"} for trade in result.trades)


def test_bollinger_bands_generates_long_only_spot_trades() -> None:
    request = BacktestRequest(initial_capital=10_000, fee_rate=0.001, slippage_rate=0.0005)
    candles = make_candles([10, 10, 10, 8, 9, 10, 11])

    result = BollingerBandsBacktester().run(
        request=request,
        candles=candles,
        parameters=BollingerBandsParameters(period=3, deviation_multiplier=1, exit_on_middle=True),
    )

    assert result.status == "completed"
    assert result.trade_count >= 1
    assert {trade.side for trade in result.trades} == {"long"}
    assert all(trade.exit_reason in {"bollinger_exit", "end_of_data"} for trade in result.trades)


def test_macd_trend_generates_long_only_spot_trades() -> None:
    request = BacktestRequest(initial_capital=10_000, fee_rate=0.001, slippage_rate=0.0005)
    candles = make_candles([10, 9, 8, 7, 6, 7, 8, 9, 10, 11, 12, 11, 10, 9])

    result = MacdTrendBacktester().run(
        request=request,
        candles=candles,
        parameters=MacdTrendParameters(fast_window=2, slow_window=4, signal_window=2),
    )

    assert result.status == "completed"
    assert result.trade_count >= 1
    assert {trade.side for trade in result.trades} == {"long"}
    assert all(trade.exit_reason in {"macd_cross_down", "end_of_data"} for trade in result.trades)


def test_trend_pullback_generates_long_only_spot_trades() -> None:
    request = BacktestRequest(initial_capital=10_000, fee_rate=0.001, slippage_rate=0.0005)
    candles = make_candles([10, 11, 12, 13, 12, 14, 15])

    result = TrendPullbackBacktester().run(
        request=request,
        candles=candles,
        parameters=TrendPullbackParameters(short_window=2, long_window=4),
    )

    assert result.status == "completed"
    assert result.trade_count >= 1
    assert {trade.side for trade in result.trades} == {"long"}
    assert all(trade.exit_reason in {"trend_failed", "end_of_data"} for trade in result.trades)


def test_dca_generates_long_only_fixed_interval_trades() -> None:
    request = BacktestRequest(initial_capital=10_000, fee_rate=0.001, slippage_rate=0.0005)
    candles = make_candles([10, 11, 12, 13, 14])

    result = DcaBacktester().run(
        request=request,
        candles=candles,
        parameters=DcaParameters(interval_candles=2, order_size_percent=20),
    )

    assert result.status == "completed"
    assert result.trade_count == 3
    assert {trade.side for trade in result.trades} == {"long"}
    assert all(trade.exit_reason == "end_of_data" for trade in result.trades)


def test_grid_backtester_generates_long_only_fixed_lot_trades() -> None:
    request = BacktestRequest(
        initial_capital=10_000,
        fee_rate=0.001,
        slippage_rate=0.0005,
        strategy_id="grid",
    )
    candles = make_candles([100, 95, 90, 95, 100, 105, 100])

    result = GridBacktester().run(
        request=request,
        candles=candles,
        parameters=GridParameters(
            lower_price=80,
            upper_price=120,
            grid_count=4,
            order_size_percent=25,
        ),
    )

    assert result.status == "completed"
    assert result.trade_count >= 1
    assert {trade.side for trade in result.trades} == {"long"}
    assert all(trade.exit_reason in {"grid_level_up", "end_of_data"} for trade in result.trades)


def test_backtest_result_exports_json_and_csv() -> None:
    result = MovingAverageCrossBacktester().run(
        request=BacktestRequest(initial_capital=10_000, fee_rate=0.001, slippage_rate=0.0005),
        candles=make_candles([10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 7]),
        parameters=MovingAverageCrossParameters(fast_window=2, slow_window=3),
    )

    json_media_type, json_extension, json_content = export_backtest_result(result, "json")
    csv_media_type, csv_extension, csv_content = export_backtest_result(result, "csv")

    assert json_media_type == "application/json"
    assert json_extension == "json"
    assert '"trade_count"' in json_content
    assert csv_media_type == "text/csv; charset=utf-8"
    assert csv_extension == "csv"
    assert "opened_at,closed_at,symbol,side" in csv_content

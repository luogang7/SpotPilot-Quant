from app.application.ai import AiMockValidationService
from app.application.risk import RiskEngine
from app.domain.models import AiAnalysis, AllowedDirection, Balance, Position, RiskLevel


def test_high_ai_risk_blocks_new_positions() -> None:
    ai = AiMockValidationService().analyze_empty_context()
    result = RiskEngine().evaluate(
        balances=[Balance(asset="USDT", free=100, locked=0, total=100)],
        positions=[],
        ai=ai,
        persisted_rules=[],
    )

    assert result.status.value == "no_new_positions"
    assert "禁止新开仓" in result.summary


def test_missing_balance_source_pauses_even_when_ai_risk_is_low() -> None:
    ai = AiAnalysis(
        market_regime="trend",
        sentiment_score=0,
        risk_level=RiskLevel.LOW,
        event_risk=False,
        allowed_direction=AllowedDirection.LONG_ONLY,
        confidence=0.8,
        provider="test",
        model="schema",
        rationale=[],
        structured_payload={},
    )
    result = RiskEngine().evaluate(balances=[], positions=[], ai=ai, persisted_rules=[])

    assert result.status.value == "paused"
    assert "未配置账户余额来源" in result.summary


def test_stale_market_data_blocks_new_positions() -> None:
    ai = AiAnalysis(
        market_regime="trend",
        sentiment_score=0,
        risk_level=RiskLevel.LOW,
        event_risk=False,
        allowed_direction=AllowedDirection.LONG_ONLY,
        confidence=0.8,
        provider="test",
        model="schema",
        rationale=[],
        structured_payload={},
    )

    result = RiskEngine().evaluate(
        balances=[Balance(asset="USDT", free=1000, locked=0, total=1000)],
        positions=[],
        ai=ai,
        persisted_rules=[],
        data_latency_seconds=999,
        data_integrity="local_cache",
    )

    assert result.status.value == "no_new_positions"
    assert any(event.rule == "数据延迟" for event in result.events)


def test_position_limit_requires_reduce_only() -> None:
    ai = AiAnalysis(
        market_regime="trend",
        sentiment_score=0,
        risk_level=RiskLevel.LOW,
        event_risk=False,
        allowed_direction=AllowedDirection.LONG_ONLY,
        confidence=0.8,
        provider="test",
        model="schema",
        rationale=[],
        structured_payload={},
    )

    result = RiskEngine().evaluate(
        balances=[Balance(asset="USDT", free=100, locked=0, total=100)],
        positions=[
            Position(
                symbol="BTC/USDT",
                quantity=1,
                average_price=1000,
                current_price=1000,
                unrealized_pnl=0,
            ),
        ],
        ai=ai,
        persisted_rules=[],
        data_latency_seconds=0,
        data_integrity="live_public",
    )

    assert result.status.value == "no_new_positions"
    assert any(event.rule == "单币最大仓位" for event in result.events)
    assert any(event.rule == "总仓位上限" for event in result.events)

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.domain.models import (
    AiAnalysis,
    AiDecisionSignal,
    AiDecisionSignalAction,
    AiDecisionSignalHorizon,
    AiDecisionSignalPlanQuality,
    AiDecisionSignalStatus,
    AllowedDirection,
    ExchangeId,
    NewsSentimentSummary,
    RiskLevel,
)
from app.application.ai_providers import ai_provider_requires_api_key


class AiStructuredPayload(BaseModel):
    market_regime: str
    sentiment_score: float = Field(ge=-1, le=1)
    risk_level: RiskLevel
    event_risk: bool
    allowed_direction: AllowedDirection
    confidence: float = Field(ge=0, le=1)


class AiServiceUnavailable(RuntimeError):
    """Raised when the configured AI proxy cannot return usable structured output."""


ACTION_LABELS: dict[AiDecisionSignalAction, str] = {
    AiDecisionSignalAction.BUY: "买入",
    AiDecisionSignalAction.ADD: "加仓",
    AiDecisionSignalAction.HOLD: "持有",
    AiDecisionSignalAction.REDUCE: "减仓",
    AiDecisionSignalAction.SELL: "卖出",
    AiDecisionSignalAction.WATCH: "观察",
    AiDecisionSignalAction.AVOID: "回避",
    AiDecisionSignalAction.ALERT: "警报",
}

RISK_PENALTY: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 10,
    RiskLevel.HIGH: 25,
    RiskLevel.EXTREME: 40,
}


def attach_ai_decision_signal(
    analysis: AiAnalysis,
    *,
    scope: str = "symbol",
    symbol: str | None = None,
    exchange: ExchangeId | None = None,
    news: NewsSentimentSummary | None = None,
    market_context: dict[str, Any] | None = None,
) -> AiAnalysis:
    """Attach a DecisionSignal-style summary without adding a persistence dependency."""

    signal = build_ai_decision_signal(
        analysis,
        scope=scope,
        symbol=symbol,
        exchange=exchange,
        news=news,
        market_context=market_context,
    )
    structured_payload = {
        **analysis.structured_payload,
        "decision_signal": signal.model_dump(mode="json"),
    }
    return analysis.model_copy(
        update={
            "decision_signal": signal,
            "structured_payload": structured_payload,
        },
        deep=True,
    )


def build_ai_decision_signal(
    analysis: AiAnalysis,
    *,
    scope: str = "symbol",
    symbol: str | None = None,
    exchange: ExchangeId | None = None,
    news: NewsSentimentSummary | None = None,
    market_context: dict[str, Any] | None = None,
) -> AiDecisionSignal:
    resolved_scope = "market" if scope == "market" else "symbol"
    resolved_symbol = "MARKET" if resolved_scope == "market" else symbol or analysis.symbol or "BTC/USDT"
    created_at = analysis.updated_at
    action = _signal_action(analysis)
    horizon = _signal_horizon(analysis)
    snapshot = _primary_market_snapshot(market_context, resolved_symbol)
    price_plan = _price_plan(snapshot, action)
    score = _signal_score(analysis)
    expires_at = _signal_expiry(created_at, horizon)
    data_quality = _data_quality_summary(market_context, news, price_plan)
    metadata = {
        "decision_type": action.value,
        "holding_state": "unknown",
        "market_regime": analysis.market_regime,
        "risk_level": analysis.risk_level.value,
        "event_risk": analysis.event_risk,
        "allowed_direction": analysis.allowed_direction.value,
        "provider": analysis.provider,
        "model": analysis.model,
        "report_type": "ai_analysis",
    }
    if market_context is not None:
        metadata["market_phase_summary"] = {
            "phase": "crypto_24x7",
            "scope": resolved_scope,
            "timeframe": market_context.get("timeframe"),
        }

    return AiDecisionSignal(
        signal_id=_signal_id(created_at, resolved_scope, resolved_symbol, exchange),
        analysis_scope=resolved_scope,
        symbol=resolved_symbol,
        exchange=exchange,
        trace_id=analysis.correlation_id,
        action=action,
        action_label=ACTION_LABELS[action],
        score=score,
        confidence=analysis.confidence,
        horizon=horizon,
        plan_quality=_plan_quality(price_plan, data_quality),
        market_phase="crypto_24x7",
        created_at=created_at,
        expires_at=expires_at,
        reason=_signal_reason(analysis, resolved_symbol, snapshot),
        catalyst_summary=_catalyst_summary(news),
        watch_conditions=_watch_conditions(analysis, snapshot),
        risk_summary=_risk_summary(analysis, snapshot),
        invalidation=_invalidation_text(analysis, price_plan),
        evidence=_signal_evidence(analysis, news, snapshot),
        data_quality_summary=data_quality,
        metadata=metadata,
        **price_plan,
    )


def _signal_action(analysis: AiAnalysis) -> AiDecisionSignalAction:
    if analysis.event_risk and analysis.risk_level in {RiskLevel.HIGH, RiskLevel.EXTREME}:
        return AiDecisionSignalAction.ALERT
    if analysis.risk_level == RiskLevel.EXTREME:
        return AiDecisionSignalAction.AVOID
    if analysis.allowed_direction == AllowedDirection.NONE:
        return AiDecisionSignalAction.AVOID
    if analysis.allowed_direction == AllowedDirection.REDUCE_ONLY:
        return AiDecisionSignalAction.REDUCE
    if analysis.risk_level == RiskLevel.HIGH:
        return AiDecisionSignalAction.REDUCE
    if analysis.allowed_direction == AllowedDirection.LONG_ONLY:
        if analysis.risk_level == RiskLevel.LOW and analysis.sentiment_score >= 0.15:
            return AiDecisionSignalAction.BUY
        return AiDecisionSignalAction.WATCH
    if analysis.risk_level == RiskLevel.LOW and analysis.sentiment_score >= 0.35:
        return AiDecisionSignalAction.ADD
    if analysis.risk_level == RiskLevel.MEDIUM:
        return AiDecisionSignalAction.WATCH
    return AiDecisionSignalAction.HOLD


def _signal_horizon(analysis: AiAnalysis) -> AiDecisionSignalHorizon:
    if analysis.event_risk or analysis.risk_level in {RiskLevel.HIGH, RiskLevel.EXTREME}:
        return AiDecisionSignalHorizon.INTRADAY
    if analysis.risk_level == RiskLevel.MEDIUM:
        return AiDecisionSignalHorizon.ONE_DAY
    return AiDecisionSignalHorizon.THREE_DAYS


def _signal_expiry(created_at: datetime, horizon: AiDecisionSignalHorizon) -> datetime | None:
    days_by_horizon = {
        AiDecisionSignalHorizon.INTRADAY: 1,
        AiDecisionSignalHorizon.ONE_DAY: 1,
        AiDecisionSignalHorizon.THREE_DAYS: 3,
        AiDecisionSignalHorizon.FIVE_DAYS: 5,
        AiDecisionSignalHorizon.TEN_DAYS: 10,
    }
    days = days_by_horizon.get(horizon)
    if days is None:
        return None
    base = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=timezone.utc)
    return base + timedelta(days=days)


def _signal_score(analysis: AiAnalysis) -> int:
    raw = (
        50
        + analysis.sentiment_score * 25
        + (analysis.confidence - 0.5) * 20
        - RISK_PENALTY[analysis.risk_level]
    )
    if analysis.event_risk:
        raw -= 12
    return int(max(0, min(100, round(raw))))


def _primary_market_snapshot(
    market_context: dict[str, Any] | None,
    symbol: str,
) -> dict[str, Any] | None:
    snapshots = market_context.get("snapshots") if isinstance(market_context, dict) else None
    if not isinstance(snapshots, list):
        return None
    for snapshot in snapshots:
        if isinstance(snapshot, dict) and snapshot.get("symbol") == symbol:
            return snapshot
    first = snapshots[0] if snapshots else None
    return first if isinstance(first, dict) else None


def _price_plan(
    snapshot: dict[str, Any] | None,
    action: AiDecisionSignalAction,
) -> dict[str, float | None]:
    last_price = _number(snapshot.get("last_price")) if snapshot else None
    volatility = _number(snapshot.get("volatility")) if snapshot else None
    if last_price is None or last_price <= 0:
        return {
            "entry_low": None,
            "entry_high": None,
            "stop_loss": None,
            "target_price": None,
        }

    volatility = volatility if volatility is not None and volatility > 0 else 0.025
    stop_factor = max(0.015, min(0.08, volatility * 1.4))
    target_factor = max(0.025, min(0.14, volatility * 2.3))
    entry_actions = {
        AiDecisionSignalAction.BUY,
        AiDecisionSignalAction.ADD,
        AiDecisionSignalAction.HOLD,
        AiDecisionSignalAction.WATCH,
    }
    has_entry = action in entry_actions
    return {
        "entry_low": round(last_price * 0.985, 8) if has_entry else None,
        "entry_high": round(last_price * 1.005, 8) if has_entry else None,
        "stop_loss": round(last_price * (1 - stop_factor), 8),
        "target_price": round(last_price * (1 + target_factor), 8) if has_entry else None,
    }


def _plan_quality(
    price_plan: dict[str, float | None],
    data_quality: dict[str, Any],
) -> AiDecisionSignalPlanQuality:
    has_stop = price_plan.get("stop_loss") is not None
    has_target = price_plan.get("target_price") is not None
    level = data_quality.get("level")
    if has_stop and has_target and level == "good":
        return AiDecisionSignalPlanQuality.COMPLETE
    if has_stop or level in {"good", "partial"}:
        return AiDecisionSignalPlanQuality.PARTIAL
    if level == "minimal":
        return AiDecisionSignalPlanQuality.MINIMAL
    return AiDecisionSignalPlanQuality.UNKNOWN


def _data_quality_summary(
    market_context: dict[str, Any] | None,
    news: NewsSentimentSummary | None,
    price_plan: dict[str, float | None],
) -> dict[str, Any]:
    snapshots = market_context.get("snapshots") if isinstance(market_context, dict) else None
    snapshot_count = len(snapshots) if isinstance(snapshots, list) else 0
    snapshot_scores = [
        snapshot.get("data_integrity")
        for snapshot in snapshots
        if isinstance(snapshot, dict) and isinstance(snapshot.get("data_integrity"), str)
    ] if isinstance(snapshots, list) else []
    degraded = any(value not in {"live_public", "local_cache", "normal"} for value in snapshot_scores)
    limitations: list[str] = []
    if snapshot_count == 0:
        limitations.append("market_snapshot_missing")
    if degraded:
        limitations.append("market_data_degraded")
    if news is None or news.article_count == 0:
        limitations.append("news_context_empty")
    if price_plan.get("stop_loss") is None:
        limitations.append("price_plan_without_quote")

    if snapshot_count and not degraded and news is not None and news.article_count > 0:
        level = "good"
    elif snapshot_count:
        level = "partial"
    elif news is not None and news.article_count > 0:
        level = "minimal"
    else:
        level = "unknown"

    return {
        "level": level,
        "scores": {
            "market_snapshot": 100 if snapshot_count and not degraded else 65 if snapshot_count else 0,
            "news": min(100, 40 + (news.article_count if news else 0) * 8),
            "quote": 100 if price_plan.get("stop_loss") is not None else 0,
            "technical": 75 if snapshot_count else 0,
        },
        "limitations": limitations,
        "snapshot_count": snapshot_count,
        "news_article_count": news.article_count if news else 0,
        "news_source_count": news.source_count if news else 0,
    }


def _signal_reason(
    analysis: AiAnalysis,
    symbol: str,
    snapshot: dict[str, Any] | None,
) -> str:
    parts = [
        f"{symbol} 当前 AI 判定为 {analysis.market_regime}",
        f"风险等级 {analysis.risk_level.value}",
        f"允许方向 {analysis.allowed_direction.value}",
        f"置信度 {analysis.confidence:.0%}",
    ]
    change = _number(snapshot.get("change_24h_percent")) if snapshot else None
    rsi = _number(snapshot.get("rsi")) if snapshot else None
    if change is not None:
        parts.append(f"24h 涨跌 {change:.2f}%")
    if rsi is not None:
        parts.append(f"RSI {rsi:.1f}")
    if analysis.rationale:
        parts.append(analysis.rationale[0])
    return "，".join(parts) + "。"


def _catalyst_summary(news: NewsSentimentSummary | None) -> str:
    if news is None or news.article_count == 0:
        return "暂无明确新闻催化，主要依据行情快照和结构化风险字段。"
    headlines = [article.title for article in news.articles[:3]]
    return "；".join(headlines) if headlines else "新闻情绪已纳入，但缺少可展示标题。"


def _watch_conditions(analysis: AiAnalysis, snapshot: dict[str, Any] | None) -> str:
    conditions = [
        "观察 AI 风险等级是否继续上调",
        "观察新闻事件风险是否解除",
    ]
    last_price = _number(snapshot.get("last_price")) if snapshot else None
    rsi = _number(snapshot.get("rsi")) if snapshot else None
    if last_price is not None:
        conditions.append(f"观察价格能否稳定在 {last_price:g} 附近")
    if rsi is not None:
        if rsi >= 70:
            conditions.append("RSI 偏热，等待回落确认")
        elif rsi <= 30:
            conditions.append("RSI 偏冷，等待止跌确认")
        else:
            conditions.append("RSI 处于中性区间，等待方向选择")
    if analysis.allowed_direction == AllowedDirection.REDUCE_ONLY:
        conditions.append("仅减仓模式下不新增仓位")
    return "；".join(conditions) + "。"


def _risk_summary(analysis: AiAnalysis, snapshot: dict[str, Any] | None) -> str:
    risk_text = f"风险提示：当前为 {analysis.risk_level.value} 风险"
    if analysis.event_risk:
        risk_text += "，存在重大事件风险"
    volatility = _number(snapshot.get("volatility")) if snapshot else None
    if volatility is not None:
        risk_text += f"，波动率约 {volatility:.2%}"
    if analysis.allowed_direction in {AllowedDirection.NONE, AllowedDirection.REDUCE_ONLY}:
        risk_text += "，系统建议收紧交易权限"
    return risk_text + "。本报告仅供参考，不构成投资建议。"


def _invalidation_text(
    analysis: AiAnalysis,
    price_plan: dict[str, float | None],
) -> str:
    stop_loss = price_plan.get("stop_loss")
    if stop_loss is not None:
        return f"若价格跌破 {stop_loss:g} 或事件风险升级，当前信号失效并重新评估。"
    if analysis.risk_level in {RiskLevel.HIGH, RiskLevel.EXTREME}:
        return "若高风险事件持续发酵，保持回避或减仓；待风险解除后重新评估。"
    return "若情绪、风险等级或行情快照发生明显变化，当前信号失效并重新评估。"


def _signal_evidence(
    analysis: AiAnalysis,
    news: NewsSentimentSummary | None,
    snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "analysis": {
            "market_regime": analysis.market_regime,
            "sentiment_score": analysis.sentiment_score,
            "risk_level": analysis.risk_level.value,
            "event_risk": analysis.event_risk,
            "allowed_direction": analysis.allowed_direction.value,
            "confidence": analysis.confidence,
        },
        "market_snapshot": snapshot or {},
        "news": {
            "status": news.status if news else "empty",
            "sentiment_score": news.sentiment_score if news else 0,
            "sentiment_label": news.sentiment_label.value if news else "neutral",
            "article_count": news.article_count if news else 0,
            "source_count": news.source_count if news else 0,
            "headlines": [article.title for article in news.articles[:5]] if news else [],
        },
        "rationale": analysis.rationale[:8],
    }


def _signal_id(
    created_at: datetime,
    scope: str,
    symbol: str,
    exchange: ExchangeId | None,
) -> str:
    timestamp = int(created_at.timestamp())
    exchange_part = exchange.value if exchange else "default"
    symbol_part = symbol.lower().replace("/", "-").replace(" ", "-")
    return f"ai-{scope}-{exchange_part}-{symbol_part}-{timestamp}"


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


class AiMockValidationService:
    """Deterministic AI proxy substitute for P0 schema validation."""

    provider = "local_ai_mock"
    model = "schema-validator"

    def analyze_empty_context(
        self,
        scope: str = "symbol",
        symbol: str = "BTC/USDT",
        market_context: dict[str, Any] | None = None,
    ) -> AiAnalysis:
        return self.analyze_market_context(
            scope=scope,
            symbol=symbol,
            market_context=market_context,
        )

    def analyze_market_context(
        self,
        news: NewsSentimentSummary | None = None,
        scope: str = "symbol",
        symbol: str = "BTC/USDT",
        market_context: dict[str, Any] | None = None,
    ) -> AiAnalysis:
        if news is not None and news.article_count > 0:
            target = self._target_payload(scope=scope, symbol=news.symbol)
            payload = AiStructuredPayload(
                market_regime=f"news_{news.sentiment_label.value}",
                sentiment_score=news.sentiment_score,
                risk_level=news.risk_level,
                event_risk=news.event_risk,
                allowed_direction=self._allowed_direction_from_news(news),
                confidence=min(0.85, 0.45 + news.article_count * 0.03 + news.source_count * 0.02),
            )
            rationale = news.rationale or ["News sentiment context analyzed locally."]
            if market_context is not None:
                rationale = [
                    self._market_context_rationale(market_context),
                    *rationale,
                ]
            analysis = self.to_analysis(
                payload,
                rationale=rationale,
            )
            structured_payload = {
                **analysis.structured_payload,
                **target,
                "news": {
                    "status": news.status,
                    "article_count": news.article_count,
                    "source_count": news.source_count,
                    "top_headlines": [article.title for article in news.articles[:5]],
                },
            }
            if market_context is not None:
                structured_payload["market_context"] = market_context
            analysis = analysis.model_copy(
                update={
                    "analysis_scope": target["analysis_scope"],
                    "symbol": target["symbol"],
                    "structured_payload": structured_payload,
                },
                deep=True,
            )
            return attach_ai_decision_signal(
                analysis,
                scope=scope,
                symbol=target["symbol"],
                news=news,
                market_context=market_context,
            )

        target = self._target_payload(scope=scope, symbol=symbol)
        market_payload = self._payload_from_market_context(market_context)
        payload = AiStructuredPayload(
            market_regime=market_payload["market_regime"],
            sentiment_score=0,
            risk_level=market_payload["risk_level"],
            event_risk=False,
            allowed_direction=market_payload["allowed_direction"],
            confidence=market_payload["confidence"],
        )
        rationale = (
            [self._market_context_rationale(market_context)]
            if market_context is not None
            else ["No AI proxy or enriched market context is configured."]
        )
        analysis = self.to_analysis(
            payload,
            rationale=rationale,
        )
        structured_payload = {**analysis.structured_payload, **target}
        if market_context is not None:
            structured_payload["market_context"] = market_context
        analysis = analysis.model_copy(
            update={
                "analysis_scope": target["analysis_scope"],
                "symbol": target["symbol"],
                "structured_payload": structured_payload,
            },
            deep=True,
        )
        return attach_ai_decision_signal(
            analysis,
            scope=scope,
            symbol=target["symbol"],
            market_context=market_context,
        )

    @staticmethod
    def _allowed_direction_from_news(news: NewsSentimentSummary) -> AllowedDirection:
        if news.risk_level in {RiskLevel.HIGH, RiskLevel.EXTREME}:
            return AllowedDirection.NONE
        if news.event_risk or news.sentiment_score <= -0.2:
            return AllowedDirection.REDUCE_ONLY
        if news.sentiment_score >= 0.2:
            return AllowedDirection.LONG_ONLY
        return AllowedDirection.BOTH

    def validate_payload(self, payload: dict[str, object]) -> AiAnalysis:
        try:
            structured = AiStructuredPayload.model_validate(payload)
        except ValidationError as exc:
            fallback = AiStructuredPayload(
                market_regime="invalid_payload",
                sentiment_score=0,
                risk_level=RiskLevel.HIGH,
                event_risk=True,
                allowed_direction=AllowedDirection.NONE,
                confidence=0,
            )
            analysis = self.to_analysis(
                fallback,
                rationale=[f"AI structured JSON validation failed: {exc.errors()}"],
            )
            return attach_ai_decision_signal(analysis)
        analysis = self.to_analysis(structured, rationale=["AI structured JSON validation passed."])
        return attach_ai_decision_signal(analysis)

    @staticmethod
    def _target_payload(scope: str, symbol: str) -> dict[str, str]:
        analysis_scope = "market" if scope == "market" else "symbol"
        return {
            "analysis_scope": analysis_scope,
            "symbol": "MARKET" if analysis_scope == "market" else symbol,
        }

    @staticmethod
    def _market_context_rationale(market_context: dict[str, Any]) -> str:
        snapshots = market_context.get("snapshots")
        count = len(snapshots) if isinstance(snapshots, list) else 0
        return f"Market data context included {count} symbol snapshot(s)."

    @staticmethod
    def _payload_from_market_context(market_context: dict[str, Any] | None) -> dict[str, object]:
        if market_context is None:
            return {
                "market_regime": "not_configured",
                "risk_level": RiskLevel.HIGH,
                "allowed_direction": AllowedDirection.NONE,
                "confidence": 0,
            }

        snapshots = market_context.get("snapshots")
        if not isinstance(snapshots, list) or not snapshots:
            return {
                "market_regime": "market_data_empty",
                "risk_level": RiskLevel.MEDIUM,
                "allowed_direction": AllowedDirection.REDUCE_ONLY,
                "confidence": 0.25,
            }

        changes = [
            float(item["change_24h_percent"])
            for item in snapshots
            if isinstance(item, dict) and isinstance(item.get("change_24h_percent"), (int, float))
        ]
        volatilities = [
            float(item["volatility"])
            for item in snapshots
            if isinstance(item, dict) and isinstance(item.get("volatility"), (int, float))
        ]
        integrity_values = [
            item.get("data_integrity")
            for item in snapshots
            if isinstance(item, dict) and isinstance(item.get("data_integrity"), str)
        ]
        degraded = any(value != "normal" for value in integrity_values)
        avg_change = sum(changes) / len(changes) if changes else 0
        max_volatility = max(volatilities) if volatilities else 0
        confidence = min(0.75, 0.35 + len(snapshots) * 0.08)

        if degraded:
            return {
                "market_regime": "market_data_degraded",
                "risk_level": RiskLevel.MEDIUM,
                "allowed_direction": AllowedDirection.REDUCE_ONLY,
                "confidence": confidence,
            }
        if avg_change <= -3 or max_volatility >= 0.08:
            return {
                "market_regime": "risk_off_bearish",
                "risk_level": RiskLevel.HIGH,
                "allowed_direction": AllowedDirection.REDUCE_ONLY,
                "confidence": confidence,
            }
        if max_volatility >= 0.045:
            return {
                "market_regime": "high_volatility",
                "risk_level": RiskLevel.MEDIUM,
                "allowed_direction": AllowedDirection.REDUCE_ONLY,
                "confidence": confidence,
            }
        if avg_change >= 2:
            return {
                "market_regime": "risk_on_bullish",
                "risk_level": RiskLevel.LOW,
                "allowed_direction": AllowedDirection.LONG_ONLY,
                "confidence": confidence,
            }
        return {
            "market_regime": "range",
            "risk_level": RiskLevel.LOW,
            "allowed_direction": AllowedDirection.BOTH,
            "confidence": confidence,
        }

    def to_analysis(self, payload: AiStructuredPayload, rationale: list[str]) -> AiAnalysis:
        return AiAnalysis(
            market_regime=payload.market_regime,
            sentiment_score=payload.sentiment_score,
            risk_level=payload.risk_level,
            event_risk=payload.event_risk,
            allowed_direction=payload.allowed_direction,
            confidence=payload.confidence,
            provider=self.provider,
            model=self.model,
            rationale=rationale,
            structured_payload=payload.model_dump(mode="json"),
        )


@dataclass(frozen=True)
class AiProxyConfig:
    provider: str
    base_url: str
    api_key: str | None
    model: str
    priority: int
    api_format: str = "chat_completions"


class OpenAiCompatibleAiService:
    """OpenAI-compatible client that validates model output as strict JSON."""

    def __init__(
        self,
        proxy: AiProxyConfig,
        timeout_seconds: int,
        client: httpx.Client | None = None,
    ) -> None:
        self.proxy = proxy
        self.provider = proxy.provider
        self.model = proxy.model
        self.timeout_seconds = timeout_seconds
        self.client = client
        self.validator = AiMockValidationService()

    def analyze_empty_context(
        self,
        scope: str = "symbol",
        symbol: str = "BTC/USDT",
        market_context: dict[str, Any] | None = None,
    ) -> AiAnalysis:
        return self.analyze_market_context(
            scope=scope,
            symbol=symbol,
            market_context=market_context,
        )

    def analyze_market_context(
        self,
        news: NewsSentimentSummary | None = None,
        scope: str = "symbol",
        symbol: str = "BTC/USDT",
        market_context: dict[str, Any] | None = None,
    ) -> AiAnalysis:
        prompt = self._analysis_prompt(
            news=news,
            scope=scope,
            symbol=symbol,
            market_context=market_context,
        )
        try:
            response = self._request(prompt)
            payload = self._extract_structured_payload(response)
            analysis = self._strict_analysis(payload)
        except (httpx.HTTPError, ValueError, TypeError, ValidationError) as exc:
            raise AiServiceUnavailable(f"{self.provider} AI call failed: {exc}") from exc

        rationale = [f"{self.provider} returned valid structured JSON."]
        if news is not None and news.article_count > 0:
            rationale.insert(
                0,
                (
                    "News sentiment context included "
                    f"{news.article_count} article(s) from {news.source_count} source(s)."
                ),
            )
        if market_context is not None:
            rationale.insert(0, AiMockValidationService._market_context_rationale(market_context))
        target = AiMockValidationService._target_payload(
            scope=scope,
            symbol=news.symbol if news is not None else symbol,
        )
        structured_payload = {
            **analysis.structured_payload,
            **target,
        }
        if market_context is not None:
            structured_payload["market_context"] = market_context
        analysis = analysis.model_copy(
            update={
                "analysis_scope": target["analysis_scope"],
                "symbol": target["symbol"],
                "provider": self.provider,
                "model": self.model,
                "rationale": rationale,
                "structured_payload": structured_payload,
            },
            deep=True,
        )
        return attach_ai_decision_signal(
            analysis,
            scope=scope,
            symbol=target["symbol"],
            news=news,
            market_context=market_context,
        )

    @staticmethod
    def _analysis_prompt(
        news: NewsSentimentSummary | None = None,
        scope: str = "symbol",
        symbol: str = "BTC/USDT",
        market_context: dict[str, Any] | None = None,
    ) -> str:
        analysis_scope = "market" if scope == "market" else "symbol"
        target_symbol = "MARKET" if analysis_scope == "market" else symbol
        schema_instruction = (
            "JSON key 和枚举值必须使用英文原文，不要翻译。"
            "必须包含：market_regime(string), sentiment_score(number -1 到 1), "
            "risk_level(low/medium/high/extreme), event_risk(boolean), "
            "allowed_direction(long_only/reduce_only/both/none), confidence(number 0 到 1)。"
        )
        if news is None or news.article_count == 0:
            market_context_instruction = (
                f"行情上下文 JSON：{json.dumps(market_context, ensure_ascii=False)}"
                if market_context is not None
                else "当前没有账户资产、仓位、新闻或链上增强上下文，"
            )
            return (
                "你是本地现货量化风控系统的 AI 分析模块。"
                f"当前分析目标为 {target_symbol}，分析范围为 {analysis_scope}。"
                f"{market_context_instruction}"
                "请给出保守的结构化 JSON。只返回 JSON 对象，不要 Markdown。"
                f"{schema_instruction}"
            )

        news_payload = {
            "analysis_scope": analysis_scope,
            "symbol": news.symbol,
            "market_context": market_context,
            "sentiment_score": news.sentiment_score,
            "sentiment_label": news.sentiment_label.value,
            "risk_level": news.risk_level.value,
            "event_risk": news.event_risk,
            "article_count": news.article_count,
            "source_count": news.source_count,
            "headlines": [
                {
                    "source": article.source,
                    "title": article.title,
                    "sentiment_score": article.sentiment_score,
                    "event_risk": article.event_risk,
                    "matched_keywords": article.matched_keywords,
                }
                for article in news.articles[:10]
            ],
        }
        return (
            "你是本地现货量化风控系统的 AI 分析模块。"
            f"当前分析目标为 {news.symbol}，分析范围为 {analysis_scope}。"
            "market 表示全市场风险偏好、大盘监管与系统性事件；symbol 表示单一交易对过滤判断。"
            "请根据新闻情绪上下文给出保守的现货交易过滤判断。"
            "只返回 JSON 对象，不要 Markdown。"
            f"{schema_instruction}"
            "第一版仅支持现货，不允许 short_only；如果存在黑客、监管、交易所事故、"
            "重大清算或稳定币脱锚等事件风险，应提高 risk_level 并收紧 allowed_direction。"
            f"新闻上下文 JSON：{json.dumps(news_payload, ensure_ascii=False)}"
        )

    def validate_payload(self, payload: dict[str, object]) -> AiAnalysis:
        analysis = self.validator.validate_payload(payload)
        return analysis.model_copy(
            update={"provider": self.provider, "model": self.model},
            deep=True,
        )

    def to_analysis(self, payload: AiStructuredPayload, rationale: list[str]) -> AiAnalysis:
        analysis = self.validator.to_analysis(payload, rationale=rationale)
        return analysis.model_copy(
            update={"provider": self.provider, "model": self.model},
            deep=True,
        )

    def _strict_analysis(self, payload: dict[str, object]) -> AiAnalysis:
        structured = AiStructuredPayload.model_validate(payload)
        return self.to_analysis(
            structured,
            rationale=[f"{self.provider} structured JSON validation passed."],
        )

    def _request(self, prompt: str) -> dict[str, Any]:
        api_format = self.proxy.api_format.strip().lower().replace("-", "_")
        if api_format in {"responses", "response"}:
            return self._request_responses(prompt)
        if api_format in {"chat_completions", "chat_completion", "chat"}:
            return self._request_chat_completions(prompt)
        raise ValueError(f"unsupported AI API format: {self.proxy.api_format}")

    def _request_responses(self, prompt: str) -> dict[str, Any]:
        request = {
            "model": self.model,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                },
            ],
            "stream": False,
        }
        return self._post(f"{self.proxy.base_url.rstrip('/')}/responses", request)

    def _request_chat_completions(self, prompt: str) -> dict[str, Any]:
        request = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是本地现货量化风控系统的 AI 分析模块。"
                        "只能返回一个 JSON 对象，不要返回 Markdown 或额外说明。"
                        "JSON key 和枚举值必须使用英文原文，不要翻译。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
            "max_tokens": 512,
        }
        return self._post(f"{self.proxy.base_url.rstrip('/')}/chat/completions", request)

    def _post(self, endpoint: str, request: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
        }
        if self.proxy.api_key:
            headers["Authorization"] = f"Bearer {self.proxy.api_key}"
        if self.client is not None:
            response = self.client.post(endpoint, headers=headers, json=request)
            response.raise_for_status()
            return response.json()

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(endpoint, headers=headers, json=request)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _extract_structured_payload(response: dict[str, Any]) -> dict[str, object]:
        text = response.get("output_text")
        if not isinstance(text, str):
            text = OpenAiCompatibleAiService._extract_text_from_output(response.get("output"))
        if not text:
            text = OpenAiCompatibleAiService._extract_text_from_chat_choices(
                response.get("choices"),
            )
        if not text:
            raise ValueError("AI response did not include output text")

        stripped = text.strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("AI response did not include a JSON object") from None
            parsed = json.loads(stripped[start : end + 1])

        if not isinstance(parsed, dict):
            raise ValueError("AI structured response must be a JSON object")
        return parsed

    @staticmethod
    def _extract_text_from_output(output: object) -> str | None:
        if not isinstance(output, list):
            return None
        chunks: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if not isinstance(content, dict):
                    continue
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks) if chunks else None

    @staticmethod
    def _extract_text_from_chat_choices(choices: object) -> str | None:
        if not isinstance(choices, list):
            return None
        chunks: list[str] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str):
                chunks.append(content)
                continue
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks) if chunks else None


class RightCodeAiService(OpenAiCompatibleAiService):
    """Backward-compatible Responses API client for the primary right code proxy."""

    provider = "right_code"

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        client: httpx.Client | None = None,
    ) -> "RightCodeAiService | None":
        if not settings.ai_proxy_a_enabled or not settings.ai_proxy_a_api_key:
            return None
        return cls(
            proxy=AiProxyConfig(
                provider=settings.ai_proxy_a_provider,
                base_url=settings.ai_proxy_a_base_url,
                api_key=settings.ai_proxy_a_api_key,
                model=settings.ai_proxy_a_model,
                priority=settings.ai_proxy_a_priority,
                api_format=settings.ai_proxy_a_api_format,
            ),
            timeout_seconds=settings.ai_request_timeout_seconds,
            client=client,
        )


class AiRelayService:
    """Call configured AI proxies by priority and fail over on unusable responses."""

    def __init__(
        self,
        proxies: list[AiProxyConfig],
        timeout_seconds: int,
        client: httpx.Client | None = None,
    ) -> None:
        if not proxies:
            raise ValueError("AiRelayService requires at least one enabled proxy")
        self.proxies = sorted(proxies, key=lambda proxy: (proxy.priority, proxy.provider))
        self.timeout_seconds = timeout_seconds
        self.client = client
        self.validator = AiMockValidationService()
        self.last_successful_proxy: AiProxyConfig | None = None
        self.last_failures: list[str] = []
        self.provider = self.current_proxy.provider
        self.model = self.current_proxy.model

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        client: httpx.Client | None = None,
    ) -> "AiRelayService | None":
        proxies = [
            proxy
            for proxy in [
                _proxy_config(
                    provider=settings.ai_proxy_a_provider,
                    base_url=settings.ai_proxy_a_base_url,
                    api_key=settings.ai_proxy_a_api_key,
                    model=settings.ai_proxy_a_model,
                    priority=settings.ai_proxy_a_priority,
                    enabled=settings.ai_proxy_a_enabled,
                    api_format=settings.ai_proxy_a_api_format,
                ),
                _proxy_config(
                    provider=settings.ai_proxy_b_provider,
                    base_url=settings.ai_proxy_b_base_url,
                    api_key=settings.ai_proxy_b_api_key,
                    model=settings.ai_proxy_b_model,
                    priority=settings.ai_proxy_b_priority,
                    enabled=settings.ai_proxy_b_enabled,
                    api_format=settings.ai_proxy_b_api_format,
                ),
                _proxy_config(
                    provider=settings.ai_proxy_c_provider,
                    base_url=settings.ai_proxy_c_base_url,
                    api_key=settings.ai_proxy_c_api_key,
                    model=settings.ai_proxy_c_model,
                    priority=settings.ai_proxy_c_priority,
                    enabled=settings.ai_proxy_c_enabled,
                    api_format=settings.ai_proxy_c_api_format,
                ),
            ]
            if proxy is not None
        ]
        if not proxies:
            return None
        return cls(
            proxies=proxies,
            timeout_seconds=settings.ai_request_timeout_seconds,
            client=client,
        )

    @property
    def current_proxy(self) -> AiProxyConfig:
        return self.last_successful_proxy or self.proxies[0]

    @property
    def failover_ready(self) -> bool:
        return len(self.proxies) > 1

    def analyze_empty_context(
        self,
        scope: str = "symbol",
        symbol: str = "BTC/USDT",
        market_context: dict[str, Any] | None = None,
    ) -> AiAnalysis:
        return self.analyze_market_context(
            scope=scope,
            symbol=symbol,
            market_context=market_context,
        )

    def analyze_market_context(
        self,
        news: NewsSentimentSummary | None = None,
        scope: str = "symbol",
        symbol: str = "BTC/USDT",
        market_context: dict[str, Any] | None = None,
    ) -> AiAnalysis:
        failures: list[str] = []
        failed_providers: list[str] = []
        for proxy in self.proxies:
            service = OpenAiCompatibleAiService(
                proxy=proxy,
                timeout_seconds=self.timeout_seconds,
                client=self.client,
            )
            try:
                analysis = service.analyze_market_context(
                    news=news,
                    scope=scope,
                    symbol=symbol,
                    market_context=market_context,
                )
            except AiServiceUnavailable as exc:
                failed_providers.append(proxy.provider)
                failures.append(f"{proxy.provider}: {self._public_error(exc)}")
                continue

            self.last_successful_proxy = proxy
            self.last_failures = failures
            self.provider = proxy.provider
            self.model = proxy.model
            if not failures:
                return analysis

            return analysis.model_copy(
                update={
                    "rationale": [
                        (
                            f"AI failover used {proxy.provider} after "
                            f"{len(failed_providers)} failed provider(s): "
                            f"{', '.join(failed_providers)}."
                        ),
                        *analysis.rationale,
                    ],
                },
                deep=True,
            )

        self.last_failures = failures
        joined = "; ".join(failures) if failures else "no enabled AI proxies"
        raise AiServiceUnavailable(f"all AI proxies unavailable: {joined}")

    def validate_payload(self, payload: dict[str, object]) -> AiAnalysis:
        analysis = self.validator.validate_payload(payload)
        proxy = self.current_proxy
        self.provider = proxy.provider
        self.model = proxy.model
        return analysis.model_copy(
            update={"provider": proxy.provider, "model": proxy.model},
            deep=True,
        )

    @staticmethod
    def _public_error(exc: Exception) -> str:
        text = str(exc).replace("\n", " ").strip()
        return text[:240] + ("..." if len(text) > 240 else "")


def _proxy_config(
    *,
    provider: str,
    base_url: str | None,
    api_key: str | None,
    model: str,
    priority: int,
    enabled: bool,
    api_format: str,
) -> AiProxyConfig | None:
    if not enabled or not base_url:
        return None
    if ai_provider_requires_api_key(provider) and not api_key:
        return None
    return AiProxyConfig(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        priority=priority,
        api_format=api_format,
    )

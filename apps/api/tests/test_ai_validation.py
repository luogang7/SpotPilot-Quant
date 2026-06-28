import httpx
import pytest

from app.application.ai import (
    AiMockValidationService,
    AiProxyConfig,
    AiRelayService,
    AiServiceUnavailable,
    OpenAiCompatibleAiService,
    RightCodeAiService,
)


def test_ai_payload_validation_accepts_valid_structured_json() -> None:
    analysis = AiMockValidationService().validate_payload(
        {
            "market_regime": "trend",
            "sentiment_score": 0.2,
            "risk_level": "low",
            "event_risk": False,
            "allowed_direction": "long_only",
            "confidence": 0.75,
        },
    )

    assert analysis.provider == "local_ai_mock"
    assert analysis.risk_level.value == "low"
    assert analysis.allowed_direction.value == "long_only"
    assert analysis.structured_payload["market_regime"] == "trend"
    assert analysis.decision_signal is not None
    assert analysis.decision_signal.action.value == "buy"
    assert analysis.structured_payload["decision_signal"]["action"] == "buy"


def test_ai_payload_validation_falls_back_to_high_risk_for_invalid_json() -> None:
    analysis = AiMockValidationService().validate_payload(
        {
            "market_regime": "trend",
            "risk_level": "low",
        },
    )

    assert analysis.market_regime == "invalid_payload"
    assert analysis.risk_level.value == "high"
    assert analysis.event_risk is True
    assert analysis.allowed_direction.value == "none"
    assert analysis.decision_signal is not None
    assert analysis.decision_signal.action.value == "alert"


def test_ai_mock_empty_context_marks_market_scope() -> None:
    analysis = AiMockValidationService().analyze_empty_context(scope="market", symbol="MARKET")

    assert analysis.analysis_scope == "market"
    assert analysis.symbol == "MARKET"
    assert analysis.market_regime == "not_configured"
    assert analysis.structured_payload["analysis_scope"] == "market"
    assert analysis.structured_payload["symbol"] == "MARKET"
    assert analysis.decision_signal is not None
    assert analysis.decision_signal.symbol == "MARKET"
    assert analysis.decision_signal.status.value == "active"


def test_ai_mock_empty_context_uses_market_data_context() -> None:
    analysis = AiMockValidationService().analyze_empty_context(
        scope="symbol",
        symbol="ETH/USDT",
        market_context={
            "scope": "symbol",
            "symbol": "ETH/USDT",
            "snapshots": [
                {
                    "symbol": "ETH/USDT",
                    "last_price": 3280,
                    "change_24h_percent": 2.8,
                    "volatility": 0.02,
                    "data_integrity": "normal",
                },
            ],
        },
    )

    assert analysis.analysis_scope == "symbol"
    assert analysis.symbol == "ETH/USDT"
    assert analysis.market_regime == "risk_on_bullish"
    assert analysis.allowed_direction.value == "long_only"
    assert analysis.structured_payload["market_context"]["snapshots"][0]["symbol"] == "ETH/USDT"
    assert analysis.decision_signal is not None
    assert analysis.decision_signal.symbol == "ETH/USDT"
    assert analysis.decision_signal.entry_low is not None


def test_right_code_ai_service_calls_responses_api_and_validates_json() -> None:
    seen_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_request["url"] = str(request.url)
        seen_request["authorization"] = request.headers.get("Authorization")
        seen_request["body"] = request.read()
        return httpx.Response(
            200,
            json={
                "output_text": (
                    '{"market_regime":"range","sentiment_score":0.1,'
                    '"risk_level":"medium","event_risk":false,'
                    '"allowed_direction":"both","confidence":0.64}'
                ),
            },
        )

    service = RightCodeAiService(
        proxy=AiProxyConfig(
            provider="right_code",
            base_url="https://www.right.codes/codex/v1",
            api_key="test-key",
            model="gpt-5.5",
            priority=1,
            api_format="responses",
        ),
        timeout_seconds=20,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    analysis = service.analyze_empty_context()

    assert seen_request["url"] == "https://www.right.codes/codex/v1/responses"
    assert seen_request["authorization"] == "Bearer test-key"
    assert b'"model":"gpt-5.5"' in seen_request["body"]
    assert analysis.provider == "right_code"
    assert analysis.model == "gpt-5.5"
    assert analysis.risk_level.value == "medium"
    assert analysis.allowed_direction.value == "both"
    assert analysis.decision_signal is not None
    assert analysis.decision_signal.plan_quality.value in {"minimal", "unknown"}


def test_right_code_ai_service_raises_when_proxy_is_unavailable() -> None:
    service = RightCodeAiService(
        proxy=AiProxyConfig(
            provider="right_code",
            base_url="https://www.right.codes/codex/v1",
            api_key="test-key",
            model="gpt-5.5",
            priority=1,
            api_format="responses",
        ),
        timeout_seconds=20,
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))),
    )

    with pytest.raises(AiServiceUnavailable, match="right_code AI call failed"):
        service.analyze_empty_context()


def test_deepseek_ai_service_calls_chat_completions_and_validates_json() -> None:
    seen_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_request["url"] = str(request.url)
        seen_request["authorization"] = request.headers.get("Authorization")
        seen_request["body"] = request.read()
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"market_regime":"range","sentiment_score":0.1,'
                                '"risk_level":"medium","event_risk":false,'
                                '"allowed_direction":"both","confidence":0.64}'
                            ),
                        },
                    },
                ],
            },
        )

    service = OpenAiCompatibleAiService(
        proxy=AiProxyConfig(
            provider="deepseek",
            base_url="https://api.deepseek.com",
            api_key="deepseek-key",
            model="deepseek-v4-pro",
            priority=2,
            api_format="chat_completions",
        ),
        timeout_seconds=20,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    analysis = service.analyze_empty_context()

    assert seen_request["url"] == "https://api.deepseek.com/chat/completions"
    assert seen_request["authorization"] == "Bearer deepseek-key"
    assert b'"model":"deepseek-v4-pro"' in seen_request["body"]
    assert b'"response_format":{"type":"json_object"}' in seen_request["body"]
    assert analysis.provider == "deepseek"
    assert analysis.model == "deepseek-v4-pro"
    assert analysis.risk_level.value == "medium"
    assert analysis.decision_signal is not None


def test_ollama_ai_service_allows_local_channel_without_api_key() -> None:
    seen_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_request["url"] = str(request.url)
        seen_request["authorization"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"market_regime":"range","sentiment_score":0,'
                                '"risk_level":"low","event_risk":false,'
                                '"allowed_direction":"both","confidence":0.6}'
                            ),
                        },
                    },
                ],
            },
        )

    relay = AiRelayService(
        proxies=[
            AiProxyConfig(
                provider="ollama",
                base_url="http://127.0.0.1:11434/v1",
                api_key=None,
                model="qwen3.6",
                priority=1,
                api_format="chat_completions",
            ),
        ],
        timeout_seconds=20,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    analysis = relay.analyze_empty_context()

    assert seen_request["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert seen_request["authorization"] is None
    assert analysis.provider == "ollama"
    assert analysis.model == "qwen3.6"
    assert analysis.decision_signal is not None


def test_ai_relay_fails_over_to_deepseek_when_primary_fails() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if str(request.url).endswith("/responses"):
            return httpx.Response(500)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"market_regime":"range","sentiment_score":0.1,'
                                '"risk_level":"low","event_risk":false,'
                                '"allowed_direction":"long_only","confidence":0.8}'
                            ),
                        },
                    },
                ],
            },
        )

    relay = AiRelayService(
        proxies=[
            AiProxyConfig(
                provider="right_code",
                base_url="https://www.right.codes/codex/v1",
                api_key="primary-key",
                model="gpt-5.5",
                priority=1,
                api_format="responses",
            ),
            AiProxyConfig(
                provider="deepseek",
                base_url="https://api.deepseek.com",
                api_key="deepseek-key",
                model="deepseek-v4-pro",
                priority=2,
                api_format="chat_completions",
            ),
        ],
        timeout_seconds=20,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    analysis = relay.analyze_empty_context()

    assert seen_urls == [
        "https://www.right.codes/codex/v1/responses",
        "https://api.deepseek.com/chat/completions",
    ]
    assert analysis.provider == "deepseek"
    assert analysis.model == "deepseek-v4-pro"
    assert relay.current_proxy.provider == "deepseek"
    assert "failover used deepseek" in analysis.rationale[0]


def test_ai_relay_fails_over_when_primary_returns_invalid_structured_json() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if str(request.url).endswith("/responses"):
            return httpx.Response(200, json={"output_text": '{"risk_level":"low"}'})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"market_regime":"trend","sentiment_score":0.4,'
                                '"risk_level":"medium","event_risk":false,'
                                '"allowed_direction":"both","confidence":0.7}'
                            ),
                        },
                    },
                ],
            },
        )

    relay = AiRelayService(
        proxies=[
            AiProxyConfig(
                provider="right_code",
                base_url="https://www.right.codes/codex/v1",
                api_key="primary-key",
                model="gpt-5.5",
                priority=1,
                api_format="responses",
            ),
            AiProxyConfig(
                provider="deepseek",
                base_url="https://api.deepseek.com",
                api_key="deepseek-key",
                model="deepseek-v4-pro",
                priority=2,
                api_format="chat_completions",
            ),
        ],
        timeout_seconds=20,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    analysis = relay.analyze_empty_context()

    assert seen_urls == [
        "https://www.right.codes/codex/v1/responses",
        "https://api.deepseek.com/chat/completions",
    ]
    assert analysis.provider == "deepseek"
    assert analysis.allowed_direction.value == "both"

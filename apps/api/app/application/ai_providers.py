from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AiProviderTemplate:
    id: str
    name: str
    base_url: str
    default_model: str
    api_format: str = "chat_completions"
    requires_api_key: bool = True
    description: str = ""


AI_PROVIDER_TEMPLATES: tuple[AiProviderTemplate, ...] = (
    AiProviderTemplate(
        id="right_code",
        name="Right Code",
        base_url="https://www.right.codes/codex/v1",
        default_model="gpt-5.5",
        api_format="responses",
        description="当前兼容保留的主通道，使用 Responses API。",
    ),
    AiProviderTemplate(
        id="openai_compatible",
        name="OpenAI 兼容",
        base_url="https://api.example.com/v1",
        default_model="gpt-5.5",
        description="适用于自建网关、聚合平台或其他 OpenAI-compatible endpoint；实际模型名以网关支持为准。",
    ),
    AiProviderTemplate(
        id="openai",
        name="OpenAI 官方",
        base_url="https://api.openai.com/v1",
        default_model="gpt-5.5",
        description="OpenAI 官方 Chat Completions 兼容入口。",
    ),
    AiProviderTemplate(
        id="deepseek",
        name="DeepSeek 官方",
        base_url="https://api.deepseek.com",
        default_model="deepseek-v4-pro",
        description="DeepSeek 官方 OpenAI 兼容入口。",
    ),
    AiProviderTemplate(
        id="dashscope",
        name="通义千问（DashScope）",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen3.7-max",
        description=(
            "阿里云百炼 DashScope OpenAI 兼容模式；可按账号区域替换为工作空间专属域名。"
        ),
    ),
    AiProviderTemplate(
        id="moonshot",
        name="Kimi（月之暗面）",
        base_url="https://api.moonshot.ai/v1",
        default_model="kimi-k2.7-code",
        description="Moonshot/Kimi OpenAI 兼容入口。",
    ),
    AiProviderTemplate(
        id="zhipu",
        name="Z.AI / 智谱 GLM",
        base_url="https://api.z.ai/api/paas/v4",
        default_model="glm-5.2",
        description="Z.AI / 智谱 GLM OpenAI 兼容入口。",
    ),
    AiProviderTemplate(
        id="minimax",
        name="MiniMax 官方",
        base_url="https://api.minimax.io/v1",
        default_model="MiniMax-M3",
        description="MiniMax OpenAI 兼容入口。",
    ),
    AiProviderTemplate(
        id="ollama",
        name="Ollama（本地）",
        base_url="http://127.0.0.1:11434/v1",
        default_model="qwen3.6",
        requires_api_key=False,
        description="本机或局域网 Ollama OpenAI 兼容入口，通常不需要 API Key。",
    ),
    AiProviderTemplate(
        id="aihubmix",
        name="AIHubMix（聚合平台）",
        base_url="https://aihubmix.com/v1",
        default_model="gpt-5.5",
        description="一 Key 多模型聚合平台，按账号可用模型填写。",
    ),
    AiProviderTemplate(
        id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="~openai/gpt-latest",
        description="OpenRouter 聚合平台，模型 ID 按平台模型列表填写。",
    ),
    AiProviderTemplate(
        id="siliconflow",
        name="硅基流动（SiliconFlow）",
        base_url="https://api.siliconflow.cn/v1",
        default_model="Qwen/Qwen3.6-35B-A3B",
        description="SiliconFlow OpenAI 兼容入口。",
    ),
)


AI_PROVIDER_TEMPLATE_BY_ID = {template.id: template for template in AI_PROVIDER_TEMPLATES}


def get_ai_provider_template(provider: str) -> AiProviderTemplate | None:
    return AI_PROVIDER_TEMPLATE_BY_ID.get(provider.strip().lower())


def ai_provider_requires_api_key(provider: str) -> bool:
    template = get_ai_provider_template(provider)
    return True if template is None else template.requires_api_key

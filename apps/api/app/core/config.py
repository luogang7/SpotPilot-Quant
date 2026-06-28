from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"

DEFAULT_NEWS_FEED_URLS: tuple[str, ...] = (
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://www.theblock.co/rss.xml",
    "https://blockworks.com/feed",
    "https://cryptoslate.com/feed/",
    "https://beincrypto.com/feed/",
    "https://www.newsbtc.com/feed/",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")

    app_env: str = Field(default="local", validation_alias="APP_ENV")
    api_host: str = Field(default="0.0.0.0", validation_alias="API_HOST")
    api_port: int = Field(default=8001, validation_alias="API_PORT")
    web_origin: str = Field(default="http://localhost:5173", validation_alias="WEB_ORIGIN")

    default_exchange: str = Field(default="binance", validation_alias="DEFAULT_EXCHANGE")
    default_symbol: str = Field(default="BTC/USDT", validation_alias="DEFAULT_SYMBOL")
    default_timeframe: str = Field(default="1h", validation_alias="DEFAULT_TIMEFRAME")
    trading_mode: str = Field(default="dry_run", validation_alias="TRADING_MODE")
    live_trading_enabled: bool = Field(default=False, validation_alias="LIVE_TRADING_ENABLED")
    enable_public_exchange_data: bool = Field(
        default=True,
        validation_alias="ENABLE_PUBLIC_EXCHANGE_DATA",
    )
    exchange_api_timeout_seconds: int = Field(
        default=3,
        validation_alias="EXCHANGE_API_TIMEOUT_SECONDS",
    )
    public_market_cache_ttl_seconds: int = Field(
        default=15,
        validation_alias="PUBLIC_MARKET_CACHE_TTL_SECONDS",
    )
    max_data_latency_seconds: int = Field(
        default=300,
        validation_alias="MAX_DATA_LATENCY_SECONDS",
    )
    external_failure_cooldown_seconds: int = Field(
        default=30,
        validation_alias="EXTERNAL_FAILURE_COOLDOWN_SECONDS",
    )
    binance_spot_base_url: str = Field(
        default="https://api.binance.com",
        validation_alias="BINANCE_SPOT_BASE_URL",
    )
    binance_api_key: str | None = Field(default=None, validation_alias="BINANCE_API_KEY")
    binance_api_secret: str | None = Field(default=None, validation_alias="BINANCE_API_SECRET")
    binance_spot_trading_enabled: bool = Field(
        default=False,
        validation_alias="BINANCE_SPOT_TRADING_ENABLED",
    )
    binance_sandbox: bool = Field(default=False, validation_alias="BINANCE_SANDBOX")
    okx_rest_base_url: str = Field(
        default="https://www.okx.com",
        validation_alias="OKX_REST_BASE_URL",
    )
    okx_api_key: str | None = Field(default=None, validation_alias="OKX_API_KEY")
    okx_api_secret: str | None = Field(default=None, validation_alias="OKX_API_SECRET")
    okx_api_passphrase: str | None = Field(default=None, validation_alias="OKX_API_PASSPHRASE")
    okx_spot_trading_enabled: bool = Field(
        default=False,
        validation_alias="OKX_SPOT_TRADING_ENABLED",
    )
    okx_sandbox: bool = Field(default=False, validation_alias="OKX_SANDBOX")

    mysql_host: str = Field(default="127.0.0.1", validation_alias="MYSQL_HOST")
    mysql_port: int = Field(default=3306, validation_alias="MYSQL_PORT")
    mysql_database: str = Field(default="spotpilot_quant", validation_alias="MYSQL_DATABASE")
    mysql_user: str = Field(default="spotpilot", validation_alias="MYSQL_USER")
    mysql_password: str = Field(default="spotpilot_local", validation_alias="MYSQL_PASSWORD")
    repository_backend: str = Field(default="mysql", validation_alias="REPOSITORY_BACKEND")

    ai_request_timeout_seconds: int = Field(
        default=8,
        validation_alias="AI_REQUEST_TIMEOUT_SECONDS",
    )
    ai_analysis_cache_ttl_seconds: int = Field(
        default=60,
        validation_alias="AI_ANALYSIS_CACHE_TTL_SECONDS",
    )
    enable_news_sentiment: bool = Field(default=False, validation_alias="ENABLE_NEWS_SENTIMENT")
    news_feed_urls: str = Field(
        default=",".join(DEFAULT_NEWS_FEED_URLS),
        validation_alias="NEWS_FEED_URLS",
    )
    news_fetch_timeout_seconds: int = Field(default=5, validation_alias="NEWS_FETCH_TIMEOUT_SECONDS")
    news_cache_ttl_seconds: int = Field(default=300, validation_alias="NEWS_CACHE_TTL_SECONDS")
    news_max_articles_per_feed: int = Field(default=20, validation_alias="NEWS_MAX_ARTICLES_PER_FEED")
    news_default_limit: int = Field(default=20, validation_alias="NEWS_DEFAULT_LIMIT")
    ai_proxy_a_base_url: str = Field(
        default="https://www.right.codes/codex/v1",
        validation_alias="AI_PROXY_A_BASE_URL",
    )
    ai_proxy_a_provider: str = Field(default="right_code", validation_alias="AI_PROXY_A_PROVIDER")
    ai_proxy_a_api_key: str | None = Field(default=None, validation_alias="AI_PROXY_A_API_KEY")
    ai_proxy_a_model: str = Field(default="gpt-5.5", validation_alias="AI_PROXY_A_MODEL")
    ai_proxy_a_priority: int = Field(default=1, validation_alias="AI_PROXY_A_PRIORITY")
    ai_proxy_a_enabled: bool = Field(default=True, validation_alias="AI_PROXY_A_ENABLED")
    ai_proxy_a_api_format: str = Field(
        default="responses",
        validation_alias="AI_PROXY_A_API_FORMAT",
    )

    ai_proxy_b_base_url: str | None = Field(
        default="https://api.deepseek.com",
        validation_alias="AI_PROXY_B_BASE_URL",
    )
    ai_proxy_b_provider: str = Field(default="deepseek", validation_alias="AI_PROXY_B_PROVIDER")
    ai_proxy_b_api_key: str | None = Field(default=None, validation_alias="AI_PROXY_B_API_KEY")
    ai_proxy_b_model: str = Field(default="deepseek-v4-pro", validation_alias="AI_PROXY_B_MODEL")
    ai_proxy_b_priority: int = Field(default=2, validation_alias="AI_PROXY_B_PRIORITY")
    ai_proxy_b_enabled: bool = Field(default=False, validation_alias="AI_PROXY_B_ENABLED")
    ai_proxy_b_api_format: str = Field(
        default="chat_completions",
        validation_alias="AI_PROXY_B_API_FORMAT",
    )

    ai_proxy_c_base_url: str | None = Field(default=None, validation_alias="AI_PROXY_C_BASE_URL")
    ai_proxy_c_provider: str = Field(
        default="openai_compatible",
        validation_alias="AI_PROXY_C_PROVIDER",
    )
    ai_proxy_c_api_key: str | None = Field(default=None, validation_alias="AI_PROXY_C_API_KEY")
    ai_proxy_c_model: str = Field(default="gpt-5.5", validation_alias="AI_PROXY_C_MODEL")
    ai_proxy_c_priority: int = Field(default=3, validation_alias="AI_PROXY_C_PRIORITY")
    ai_proxy_c_enabled: bool = Field(default=False, validation_alias="AI_PROXY_C_ENABLED")
    ai_proxy_c_api_format: str = Field(
        default="chat_completions",
        validation_alias="AI_PROXY_C_API_FORMAT",
    )
    feishu_webhook_url: str | None = Field(default=None, validation_alias="FEISHU_WEBHOOK_URL")
    wecom_webhook_url: str | None = Field(default=None, validation_alias="WECOM_WEBHOOK_URL")
    telegram_bot_token: str | None = Field(default=None, validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = Field(default=None, validation_alias="TELEGRAM_CHAT_ID")
    email_smtp_host: str | None = Field(default=None, validation_alias="EMAIL_SMTP_HOST")
    email_smtp_port: int = Field(default=587, validation_alias="EMAIL_SMTP_PORT")
    email_smtp_username: str | None = Field(default=None, validation_alias="EMAIL_SMTP_USERNAME")
    email_smtp_password: str | None = Field(default=None, validation_alias="EMAIL_SMTP_PASSWORD")
    email_from: str | None = Field(default=None, validation_alias="EMAIL_FROM")
    email_to: str | None = Field(default=None, validation_alias="EMAIL_TO")
    email_use_tls: bool = Field(default=True, validation_alias="EMAIL_USE_TLS")
    slack_webhook_url: str | None = Field(default=None, validation_alias="SLACK_WEBHOOK_URL")
    discord_webhook_url: str | None = Field(default=None, validation_alias="DISCORD_WEBHOOK_URL")
    schedule_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("SCHEDULE_ENABLED", "DAILY_PUSH_ENABLED"),
    )
    schedule_time: str = Field(
        default="18:00",
        validation_alias=AliasChoices("SCHEDULE_TIME", "DAILY_PUSH_TIME"),
    )
    schedule_times: str = Field(
        default="",
        validation_alias=AliasChoices("SCHEDULE_TIMES", "DAILY_PUSH_TIMES"),
    )
    schedule_run_immediately: bool = Field(
        default=False,
        validation_alias=AliasChoices("SCHEDULE_RUN_IMMEDIATELY", "DAILY_PUSH_RUN_IMMEDIATELY"),
    )
    schedule_poll_interval_seconds: int = Field(
        default=30,
        validation_alias=AliasChoices(
            "SCHEDULE_POLL_INTERVAL_SECONDS",
            "DAILY_PUSH_POLL_INTERVAL_SECONDS",
        ),
    )

    @property
    def mysql_dsn(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

# SpotPilot Quant

<p align="right">
  <a href="README.md">Chinese</a> | <strong>English</strong>
</p>

SpotPilot Quant is a local crypto spot quant workbench for personal research, strategy validation, and end-to-end trading workflow rehearsal. It brings market data, strategy signals, AI analysis, backtesting, risk control, execution, and audit logs into one runnable full-stack system so you can validate the chain before touching live capital.

The first version is strictly limited to Spot trading. Strategies can only produce buy, sell-existing-position, wait, and cancel-related signals. AI is used for analysis, explanation, and filtering only; it does not place orders directly. Every execution action must pass risk checks and explicit runtime switches. By default, the project is centered on local dry-run, backtesting, and traceable logs, while live trading is disabled.

> Risk notice: This project is for technical research, strategy validation, and personal learning only. It is not investment advice. Crypto trading is high-risk. Before enabling live trading, complete your own testing, permission isolation, capital isolation, and risk review.

## Why This Project

Many quant demos stop at strategy formulas or backtest charts. A real trading workflow also has to deal with market data quality, exchange differences, AI uncertainty, risk blocks, API key permissions, audit trails, and failure fallback. SpotPilot Quant aims to put these pieces into a minimal local loop that actually runs:

- Use real public exchange data instead of static mock prices.
- Manage signal generation and backtesting through one strategy registry.
- Use AI as an analysis assistant, not an automated decision-maker that bypasses risk control.
- Protect execution with risk rules, a kill switch, trading-mode gates, and audit logs.
- Provide one workbench for market data, strategies, backtests, AI analysis, trading, risk, and settings.

## Features

- **Market workbench**: Binance / OKX Spot public market data, ticker, candlesticks, and market overview.
- **Strategy center**: Built-in adapters for MA Cross, RSI Mean Reversion, Grid Trading, and other spot strategies.
- **Backtesting engine**: Reuses the strategy registry for historical validation, including returns, drawdown, win rate, and trade details.
- **AI analysis**: Supports multiple model proxy channels for market explanation, strategy filtering, and structured risk notes.
- **Trading execution**: Connects to Binance / OKX private Spot trading APIs through CCXT. Live mode is disabled by default.
- **Risk control**: Checks mode, permissions, data integrity, and risk rules before opening, closing, or cancelling orders.
- **Daily push**: Sends daily quant reports to Feishu, WeCom, Telegram, Email, Slack, or Discord.
- **Audit logs**: Keeps strategy signals, AI filters, risk decisions, and order actions traceable.
- **Local-first storage**: Uses a local MySQL repository by default and does not return demo assets, demo positions, or fake orders.

## Screenshots

> Screenshots are captured from the local Chinese UI and show the workbench structure, market charts, strategy management, and risk pages. Real account assets, API keys, and private order details should not be included in public repository screenshots.

### Market Workbench

![Market Workbench](docs/screenshots/market.jpg)

### Strategy Lab

![Strategy Lab](docs/screenshots/strategy.jpg)

### Risk Center

![Risk Center](docs/screenshots/risk.jpg)

### Daily Push

The Feishu bot can receive daily quant reports with the analyzed symbol, market state, AI filtering result, risk action, and highlighted news summary.

<img src="docs/screenshots/daily-push-feishu.jpg" alt="Feishu daily quant report" width="420">

More pages:

- [Backtest page](docs/screenshots/backtest.jpg)
- [Project settings](docs/screenshots/settings.jpg)

## Tech Stack

- **Frontend**: Vue 3, Vite, TypeScript, Pinia, Vue Router, Element Plus, ECharts, Lightweight Charts.
- **Backend**: FastAPI, Pydantic, SQLAlchemy, PyMySQL, HTTPX, CCXT.
- **Infrastructure**: MySQL, Docker Compose, local `.env` configuration.
- **Testing / Quality**: Pytest, Ruff configuration, Vue type checking, ESLint.

## Project Layout

```text
apps/
  api/      FastAPI backend for market data, strategies, backtests, AI, trading, risk, and logs
  web/      Vue 3 + Vite frontend workbench
docs/       Architecture, module boundaries, and implementation notes
infra/      Local MySQL and infrastructure configuration
```

## Current Status

This project is currently a local MVP / research workbench. It is suitable for learning, secondary development, and validating Spot quant trading workflows. It is not recommended to connect large capital directly. If you need live trading, read the Safety Boundary first and start with small capital, human supervision, and rollback-ready configuration.

## Local Startup

1. Copy environment variables:

```bash
cp .env.example .env
```

2. Start MySQL:

```bash
docker compose -f infra/docker-compose.yml up -d
```

3. Start the backend:

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Initialize the MySQL repository:

```bash
python apps/api/scripts/init_db.py
```

Public Spot market data uses official exchange REST endpoints by default:

- Binance: `GET /api/v3/ticker/24hr`, `GET /api/v3/klines`
- OKX: `GET /api/v5/market/ticker`, `GET /api/v5/market/candles`

If the local machine cannot reach the exchange, the API returns a clear `data_integrity=exchange_error...` state instead of fake market data or an unhandled 500 error.

Spot live order placement, cancellation, and manual close actions use CCXT private APIs. Both the global live gate and the target exchange gate must be enabled:

```bash
TRADING_MODE=live
LIVE_TRADING_ENABLED=true

BINANCE_API_KEY=your Binance API Key
BINANCE_API_SECRET=your Binance API Secret
BINANCE_SPOT_TRADING_ENABLED=true
BINANCE_SANDBOX=false

OKX_API_KEY=your OKX API Key
OKX_API_SECRET=your OKX API Secret
OKX_API_PASSPHRASE=your OKX API Passphrase
OKX_SPOT_TRADING_ENABLED=true
OKX_SANDBOX=false
```

If you only need one exchange, enable only its corresponding `*_SPOT_TRADING_ENABLED` switch. API keys should only have Spot trading permissions. Do not enable withdrawal permissions.

4. Start the frontend:

```bash
npm --prefix apps/web install
npm --prefix apps/web run dev
```

The default frontend URL is `http://localhost:5173`, and the backend health check is `http://localhost:8001/api/v1/health`.

### Daily Push

The backend includes a daily push scheduler, disabled by default. When enabled, it generates a daily quant report according to the local machine time and sends it to configured Feishu, WeCom, Telegram, Email, Slack, or Discord channels.

```bash
SCHEDULE_ENABLED=true
SCHEDULE_TIME=18:00
SCHEDULE_TIMES=09:00,18:00
SCHEDULE_RUN_IMMEDIATELY=false
```

When `SCHEDULE_TIMES` is empty, the system falls back to `SCHEDULE_TIME`. You can also trigger one run manually:

```bash
curl -X POST http://localhost:8001/api/v1/settings/notifications/daily-push/run
```

### AI Model Configuration

AI model settings live in the root `.env`. Do not write real secrets into `.env.example` or commit them to Git.

The system keeps three channels: `AI_PROXY_A/B/C`. Each channel can be configured for Right Code, OpenAI-compatible services, DeepSeek, Tongyi Qianwen, Kimi, GLM, MiniMax, local Ollama models, and other common providers. Channel A remains compatible with Right Code Responses API by default, channel B is prefilled for DeepSeek, and channel C is reserved for any OpenAI-compatible service.

Common provider templates:

| Provider | `AI_PROXY_*_PROVIDER` | `AI_PROXY_*_BASE_URL` | `AI_PROXY_*_MODEL` example | `AI_PROXY_*_API_FORMAT` |
| --- | --- | --- | --- | --- |
| Right Code | `right_code` | `https://www.right.codes/codex/v1` | `gpt-5.5` | `responses` |
| OpenAI-compatible | `openai_compatible` | `https://api.example.com/v1` | `gpt-5.5` | `chat_completions` |
| OpenAI official | `openai` | `https://api.openai.com/v1` | `gpt-5.5` | `chat_completions` |
| DeepSeek official | `deepseek` | `https://api.deepseek.com` | `deepseek-v4-pro` | `chat_completions` |
| Tongyi Qianwen | `dashscope` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen3.7-max` | `chat_completions` |
| Kimi / Moonshot | `moonshot` | `https://api.moonshot.ai/v1` | `kimi-k2.7-code` | `chat_completions` |
| Z.AI / Zhipu GLM | `zhipu` | `https://api.z.ai/api/paas/v4` | `glm-5.2` | `chat_completions` |
| MiniMax official | `minimax` | `https://api.minimax.io/v1` | `MiniMax-M3` | `chat_completions` |
| Local Ollama | `ollama` | `http://127.0.0.1:11434/v1` | `qwen3.6` | `chat_completions` |
| AIHubMix | `aihubmix` | `https://aihubmix.com/v1` | `gpt-5.5` | `chat_completions` |
| OpenRouter | `openrouter` | `https://openrouter.ai/api/v1` | `~openai/gpt-latest` | `chat_completions` |
| SiliconFlow | `siliconflow` | `https://api.siliconflow.cn/v1` | `Qwen/Qwen3.6-35B-A3B` | `chat_completions` |

DashScope also provides newer workspace-specific compatible URLs. The settings page keeps the older `dashscope.aliyuncs.com` compatible domain by default for easier setup. If your account requires a workspace-specific endpoint, replace the Base URL there.

Example: enable DeepSeek as the B fallback channel:

```bash
AI_PROXY_B_BASE_URL=https://api.deepseek.com
AI_PROXY_B_PROVIDER=deepseek
AI_PROXY_B_API_KEY=your DeepSeek API Key
AI_PROXY_B_MODEL=deepseek-v4-pro
AI_PROXY_B_PRIORITY=2
AI_PROXY_B_ENABLED=true
AI_PROXY_B_API_FORMAT=chat_completions
```

Example: enable local Ollama:

```bash
AI_PROXY_C_BASE_URL=http://127.0.0.1:11434/v1
AI_PROXY_C_PROVIDER=ollama
AI_PROXY_C_API_KEY=
AI_PROXY_C_MODEL=qwen3.6
AI_PROXY_C_PRIORITY=3
AI_PROXY_C_ENABLED=true
AI_PROXY_C_API_FORMAT=chat_completions
```

Local Ollama usually does not require an API key. Cloud providers require the corresponding key. The settings page can test a single channel by sending a lightweight model call with the current provider, Base URL, API format, model, and API key, then validating whether a structured JSON response is returned.

The system calls channels by ascending `AI_PROXY_*_PRIORITY`. If one channel times out, returns an HTTP error, returns non-JSON content, or fails structured-field validation, the system automatically tries the next available channel. If all channels fail, the AI analysis API returns 503 and the trading workflow will not open new positions.

For local testing, you can start or restart both services with:

```bash
npm run test:dev:start
npm run test:dev:restart
```

These commands use backend port `8001` and frontend port `5173` by default. Logs are written to `logs/api-dev.log` and `logs/web-dev.log`. You can pass `API_PORT` or `WEB_PORT` to temporarily change ports.

The system does not return demo assets, positions, or orders by default. With `REPOSITORY_BACKEND=mysql`, it reads real configuration, orders, positions, risk state, and logs from MySQL. If explicitly switched to `memory`, it uses an empty in-memory repository and data is lost after restart. Market APIs return only real public market data or explicit exchange error states.

## Development Commands

```bash
npm run build:web
npm run lint:web
npm run typecheck:web
npm run test:api
npm run check:api
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for details. The overall workflow is:

```text
Market Data -> Strategy Signal -> AI Filter -> Risk Engine -> Execution Engine -> Audit Logs
                     |                               |
                     +---------- Backtesting --------+
```

Backend layers:

- `api/v1/routes`: HTTP routes and protocol conversion.
- `application`: Application orchestration for strategies, AI, backtesting, trading, and risk.
- `domain`: Pydantic contracts, domain models, and enums.
- `infrastructure`: Exchange adapters, MySQL schema, repositories, and external service adapters.

Frontend modules:

- Dashboard, Market, Strategy, Backtest, AI Analysis, Trading, Risk, Settings.
- `shared` contains the API client, base components, formatting helpers, and type definitions.

## Safety Boundary

- Live mode is disabled by default and must be enabled through environment variables and a secondary confirmation flow.
- Futures, perpetuals, leverage, margin, and naked shorting are not allowed in the first execution path.
- New positions must be blocked when data is stale, AI channels are unavailable, exchanges fail, or risk rules trigger.
- Every strategy signal, AI filter, risk decision, and order action must be traceable.

## Roadmap

- More complete strategy parameter management and visual backtest reports.
- Stricter live trading acceptance checks, paper trading mode, and capital protection policies.
- More exchange market data adapters and finer-grained data integrity checks.
- Better audit log search, export, and daily report templates.
- CI workflows for frontend build, backend tests, type checks, and basic security scanning.

## Disclaimer

This project does not guarantee returns, strategy effectiveness, third-party exchange stability, AI provider stability, or network availability. Any live trading decision and financial loss are the user's own responsibility.

## License

This project is open-sourced under the MIT License. When modifying, distributing, or using it commercially, please keep the copyright notice and license text:

```text
Copyright (c) 2026 Kairo
```

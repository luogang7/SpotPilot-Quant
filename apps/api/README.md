# API Service

FastAPI 后端采用分层结构：路由层只处理 HTTP 协议，应用服务层编排 PRD 业务流程，领域契约层定义前后端共享数据形状，基础设施层后续接入 MySQL、CCXT、AI 中转站和飞书。

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

初始化 MySQL repository：

```bash
python scripts/init_db.py
```

## Exchange Adapters

当前已实现 Binance / OKX 公共现货行情 adapter：

- Binance Spot ticker: `/api/v3/ticker/24hr`
- Binance Spot candles: `/api/v3/klines`
- OKX Spot ticker: `/api/v5/market/ticker`
- OKX Spot candles: `/api/v5/market/candles`

私有现货交易通过 CCXT 接入 Binance / OKX，已提供：

- `POST /api/v1/trading/live/orders`
- `POST /api/v1/trading/live/orders/cancel`
- `POST /api/v1/trading/live/positions/close`

Live 交易必须同时配置 `TRADING_MODE=live`、`LIVE_TRADING_ENABLED=true` 和目标交易所的 `*_SPOT_TRADING_ENABLED=true`。Binance 需要 `BINANCE_API_KEY` / `BINANCE_API_SECRET`，OKX 需要 `OKX_API_KEY` / `OKX_API_SECRET` / `OKX_API_PASSPHRASE`。第一版不开放合约、永续、杠杆、保证金或裸空接口。

## Backend Layers

```text
app/application              应用服务和 Repository 端口
app/domain                   API 契约和领域枚举
app/infrastructure/exchanges Binance / OKX 公共现货行情 adapter
app/infrastructure/persistence SQLAlchemy MySQL schema
app/infrastructure/repositories memory / SQLAlchemy repository
app/api/v1/routes            HTTP 路由，只做协议转换
```

Swagger: `http://localhost:8001/docs`

## Daily Push

后端会在启动时创建一个轻量定时器，但默认不发送日报。配置下面的环境变量后，系统会按北京时间所在运行环境的本地时间生成「每日量化日报」，复用已配置的飞书、企业微信、Telegram、Email、Slack 或 Discord 渠道推送。

```bash
SCHEDULE_ENABLED=true
SCHEDULE_TIME=18:00
# 多个时间点可用英文逗号分隔；为空时回退到 SCHEDULE_TIME
SCHEDULE_TIMES=09:00,18:00
SCHEDULE_RUN_IMMEDIATELY=false
```

也可以手动触发一次：

```bash
curl -X POST http://localhost:8001/api/v1/settings/notifications/daily-push/run
```

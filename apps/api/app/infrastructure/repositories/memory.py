from app.application.ports import (
    AiAnalysisRepository,
    AuditLogRepository,
    PortfolioRepository,
    RiskRepository,
    StrategyRepository,
    SystemStateRepository,
)
from app.domain.models import (
    AiAnalysis,
    AuditLog,
    Balance,
    Order,
    Position,
    RiskEvent,
    RiskRule,
    StrategyConfig,
    StrategySignal,
    SystemControlState,
)


class InMemoryPortfolioRepository(PortfolioRepository):
    def __init__(self) -> None:
        self.orders: list[Order] = []

    def list_balances(self) -> list[Balance]:
        return []

    def list_positions(self) -> list[Position]:
        return []

    def list_open_orders(self) -> list[Order]:
        return [
            order
            for order in self.orders
            if order.status in {"open", "partially_filled"}
        ]

    def list_historical_orders(self, limit: int = 100) -> list[Order]:
        return sorted(self.orders, key=lambda order: order.created_at, reverse=True)[:limit]

    def get_order_by_correlation_id(self, correlation_id: str) -> Order | None:
        return next((order for order in self.orders if order.correlation_id == correlation_id), None)

    def save_order(self, order: Order) -> Order:
        self.orders.append(order)
        return order


class InMemoryStrategyRepository(StrategyRepository):
    def __init__(self) -> None:
        self.strategies: dict[str, StrategyConfig] = {}
        self.signals: list[StrategySignal] = []

    def list_strategies(self) -> list[StrategyConfig]:
        return list(self.strategies.values())

    def get_strategy(self, strategy_id: str) -> StrategyConfig | None:
        return self.strategies.get(strategy_id)

    def save_strategy(self, strategy: StrategyConfig) -> StrategyConfig:
        self.strategies[strategy.id] = strategy
        return strategy

    def list_signals(self, limit: int = 100) -> list[StrategySignal]:
        return sorted(self.signals, key=lambda signal: signal.occurred_at, reverse=True)[:limit]

    def get_signal_by_correlation_id(self, correlation_id: str) -> StrategySignal | None:
        return next((signal for signal in self.signals if signal.correlation_id == correlation_id), None)

    def append_signal(self, signal: StrategySignal) -> StrategySignal:
        self.signals.append(signal)
        return signal


class InMemoryAuditLogRepository(AuditLogRepository):
    def __init__(self) -> None:
        self.logs: list[AuditLog] = []

    def list_logs(self, limit: int = 20) -> list[AuditLog]:
        return sorted(self.logs, key=lambda log: log.occurred_at, reverse=True)[:limit]

    def list_logs_by_correlation_id(self, correlation_id: str, limit: int = 100) -> list[AuditLog]:
        logs = [log for log in self.logs if log.correlation_id == correlation_id]
        return sorted(logs, key=lambda log: log.occurred_at)[:limit]

    def append_log(self, log: AuditLog) -> AuditLog:
        self.logs.append(log)
        return log


class InMemoryRiskRepository(RiskRepository):
    def __init__(self) -> None:
        self.events: list[RiskEvent] = []

    def list_rules(self) -> list[RiskRule]:
        return []

    def list_events(self, limit: int = 100) -> list[RiskEvent]:
        return sorted(self.events, key=lambda event: event.occurred_at, reverse=True)[:limit]

    def append_events(self, events: list[RiskEvent]) -> list[RiskEvent]:
        self.events.extend(events)
        return events

    def list_events_by_correlation_id(self, correlation_id: str, limit: int = 100) -> list[RiskEvent]:
        events = [event for event in self.events if event.correlation_id == correlation_id]
        return sorted(events, key=lambda event: event.occurred_at)[:limit]


class InMemoryAiAnalysisRepository(AiAnalysisRepository):
    def __init__(self) -> None:
        self.analyses: list[AiAnalysis] = []

    def save_analysis(self, analysis: AiAnalysis) -> AiAnalysis:
        self.analyses.append(analysis)
        return analysis

    def get_latest_analysis(self) -> AiAnalysis | None:
        return max(self.analyses, key=lambda analysis: analysis.updated_at, default=None)

    def get_analysis_by_correlation_id(self, correlation_id: str) -> AiAnalysis | None:
        return next(
            (analysis for analysis in self.analyses if analysis.correlation_id == correlation_id),
            None,
        )


class InMemorySystemStateRepository(SystemStateRepository):
    def __init__(self) -> None:
        self.state = SystemControlState()

    def get_state(self) -> SystemControlState:
        return self.state

    def save_state(self, state: SystemControlState) -> SystemControlState:
        self.state = state
        return state


EmptyPortfolioRepository = InMemoryPortfolioRepository
EmptyStrategyRepository = InMemoryStrategyRepository
EmptyAuditLogRepository = InMemoryAuditLogRepository
EmptyRiskRepository = InMemoryRiskRepository
EmptyAiAnalysisRepository = InMemoryAiAnalysisRepository
EmptySystemStateRepository = InMemorySystemStateRepository

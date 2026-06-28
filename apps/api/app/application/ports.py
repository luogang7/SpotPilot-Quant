from typing import Protocol

from app.domain.models import (
    AuditLog,
    AiAnalysis,
    Balance,
    Order,
    Position,
    RiskEvent,
    RiskRule,
    StrategyConfig,
    StrategySignal,
    SystemControlState,
)


class PortfolioRepository(Protocol):
    def list_balances(self) -> list[Balance]:
        """Return account balances from persistence or a private exchange adapter."""

    def list_positions(self) -> list[Position]:
        """Return spot positions only."""

    def list_open_orders(self) -> list[Order]:
        """Return open spot orders only."""

    def list_historical_orders(self, limit: int = 100) -> list[Order]:
        """Return historical spot orders."""

    def get_order_by_correlation_id(self, correlation_id: str) -> Order | None:
        """Return one order linked to a strategy/AI/risk decision chain."""

    def save_order(self, order: Order) -> Order:
        """Persist a user-initiated dry-run/live spot order record."""


class StrategyRepository(Protocol):
    def list_strategies(self) -> list[StrategyConfig]:
        """Return persisted strategy configurations."""

    def get_strategy(self, strategy_id: str) -> StrategyConfig | None:
        """Return one strategy configuration if it exists."""

    def save_strategy(self, strategy: StrategyConfig) -> StrategyConfig:
        """Persist a strategy configuration update."""

    def list_signals(self, limit: int = 100) -> list[StrategySignal]:
        """Return persisted strategy signals sorted newest first."""

    def get_signal_by_correlation_id(self, correlation_id: str) -> StrategySignal | None:
        """Return the signal that started one decision chain."""

    def append_signal(self, signal: StrategySignal) -> StrategySignal:
        """Persist one strategy signal for traceability."""


class AuditLogRepository(Protocol):
    def list_logs(self, limit: int = 20) -> list[AuditLog]:
        """Return audit logs sorted newest first."""

    def list_logs_by_correlation_id(self, correlation_id: str, limit: int = 100) -> list[AuditLog]:
        """Return audit logs for one decision chain sorted oldest first."""

    def append_log(self, log: AuditLog) -> AuditLog:
        """Persist an audit log entry for traceability."""


class RiskRepository(Protocol):
    def list_rules(self) -> list[RiskRule]:
        """Return persisted risk rules."""

    def list_events(self, limit: int = 100) -> list[RiskEvent]:
        """Return risk events sorted newest first."""

    def append_events(self, events: list[RiskEvent]) -> list[RiskEvent]:
        """Persist risk events produced by a rejected or restricted action."""

    def list_events_by_correlation_id(self, correlation_id: str, limit: int = 100) -> list[RiskEvent]:
        """Return risk events for one decision chain sorted oldest first."""


class AiAnalysisRepository(Protocol):
    def save_analysis(self, analysis: AiAnalysis) -> AiAnalysis:
        """Persist an AI analysis snapshot used in a decision chain."""

    def get_latest_analysis(self) -> AiAnalysis | None:
        """Return the newest persisted AI analysis snapshot."""

    def get_analysis_by_correlation_id(self, correlation_id: str) -> AiAnalysis | None:
        """Return the AI analysis snapshot for one decision chain."""


class SystemStateRepository(Protocol):
    def get_state(self) -> SystemControlState:
        """Return the current local safety state."""

    def save_state(self, state: SystemControlState) -> SystemControlState:
        """Persist the local safety state."""

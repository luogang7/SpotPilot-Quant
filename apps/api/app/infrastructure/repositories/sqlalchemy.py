from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

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
    AllowedDirection,
    Balance,
    ExchangeId,
    Order,
    Position,
    RiskEvent,
    RiskLevel,
    RiskRule,
    Severity,
    StrategyConfig,
    StrategySignal,
    SpotSignalAction,
    SystemControlState,
)
from app.infrastructure.persistence.models import (
    AiAnalysisRecord,
    AuditLogRecord,
    BalanceRecord,
    OrderRecord,
    PositionRecord,
    RiskEventRecord,
    RiskRuleRecord,
    StrategyConfigRecord,
    StrategySignalRecord,
    SystemStateRecord,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class SqlAlchemyPortfolioRepository(PortfolioRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_balances(self) -> list[Balance]:
        records = self.session.scalars(select(BalanceRecord)).all()
        return [
            Balance(asset=row.asset, free=row.free, locked=row.locked, total=row.total)
            for row in records
        ]

    def list_positions(self) -> list[Position]:
        records = self.session.scalars(select(PositionRecord)).all()
        return [
            Position(
                symbol=row.symbol,
                side=row.side,
                quantity=row.quantity,
                average_price=row.average_price,
                current_price=row.current_price,
                unrealized_pnl=row.unrealized_pnl,
                stop_loss=row.stop_loss,
                take_profit=row.take_profit,
            )
            for row in records
        ]

    def list_open_orders(self) -> list[Order]:
        records = self.session.scalars(
            select(OrderRecord).where(OrderRecord.status.in_(["open", "partially_filled"])),
        ).all()
        return [self._to_order(row) for row in records]

    def list_historical_orders(self, limit: int = 100) -> list[Order]:
        records = self.session.scalars(
            select(OrderRecord).order_by(desc(OrderRecord.created_at)).limit(limit),
        ).all()
        return [self._to_order(row) for row in records]

    def get_order_by_correlation_id(self, correlation_id: str) -> Order | None:
        record = self.session.scalars(
            select(OrderRecord).where(OrderRecord.correlation_id == correlation_id).limit(1),
        ).first()
        return self._to_order(record) if record else None

    def save_order(self, order: Order) -> Order:
        record = OrderRecord(
            order_id=order.order_id,
            correlation_id=order.correlation_id,
            exchange=order.exchange.value,
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            price=order.price,
            quantity=order.quantity,
            fee=order.fee,
            status=order.status,
            created_at=order.created_at,
        )
        self.session.merge(record)
        self.session.commit()
        return order

    @staticmethod
    def _to_order(row: OrderRecord) -> Order:
        return Order(
            order_id=row.order_id,
            correlation_id=row.correlation_id,
            exchange=ExchangeId(row.exchange),
            symbol=row.symbol,
            side=row.side,
            order_type=row.order_type,
            price=row.price,
            quantity=row.quantity,
            fee=row.fee,
            status=row.status,
            created_at=_as_utc(row.created_at),
        )


class SqlAlchemyStrategyRepository(StrategyRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_strategies(self) -> list[StrategyConfig]:
        records = self.session.scalars(select(StrategyConfigRecord)).all()
        return [
            self._to_strategy(row)
            for row in records
        ]

    def get_strategy(self, strategy_id: str) -> StrategyConfig | None:
        record = self.session.get(StrategyConfigRecord, strategy_id)
        return self._to_strategy(record) if record else None

    def save_strategy(self, strategy: StrategyConfig) -> StrategyConfig:
        record = self.session.get(StrategyConfigRecord, strategy.id)
        if record is None:
            record = StrategyConfigRecord(id=strategy.id)
            self.session.add(record)
        record.name = strategy.name
        record.enabled = int(strategy.enabled)
        record.mode = strategy.mode
        record.status = strategy.status
        record.parameters = strategy.parameters
        record.risk_controls = strategy.risk_controls
        self.session.commit()
        return strategy

    def list_signals(self, limit: int = 100) -> list[StrategySignal]:
        records = self.session.scalars(
            select(StrategySignalRecord).order_by(desc(StrategySignalRecord.created_at)).limit(limit),
        ).all()
        return [self._to_signal(row) for row in records]

    def get_signal_by_correlation_id(self, correlation_id: str) -> StrategySignal | None:
        record = self.session.scalars(
            select(StrategySignalRecord)
            .where(StrategySignalRecord.correlation_id == correlation_id)
            .limit(1),
        ).first()
        return self._to_signal(record) if record else None

    def append_signal(self, signal: StrategySignal) -> StrategySignal:
        self.session.add(
            StrategySignalRecord(
                correlation_id=signal.correlation_id,
                symbol=signal.symbol,
                strategy=signal.strategy,
                action=signal.action.value,
                price=signal.price,
                reason=signal.reason,
                blocked_by=signal.blocked_by,
                created_at=signal.occurred_at,
            ),
        )
        self.session.commit()
        return signal

    @staticmethod
    def _to_strategy(row: StrategyConfigRecord) -> StrategyConfig:
        return StrategyConfig(
            id=row.id,
            name=row.name,
            enabled=bool(row.enabled),
            mode=row.mode,
            status=row.status,
            parameters=row.parameters,
            risk_controls=row.risk_controls,
            recent_signals=[],
        )

    @staticmethod
    def _to_signal(row: StrategySignalRecord) -> StrategySignal:
        return StrategySignal(
            occurred_at=_as_utc(row.created_at),
            symbol=row.symbol,
            strategy=row.strategy,
            action=SpotSignalAction(row.action),
            price=row.price,
            reason=row.reason,
            blocked_by=row.blocked_by,
            correlation_id=row.correlation_id,
        )


class SqlAlchemyAuditLogRepository(AuditLogRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_logs(self, limit: int = 20) -> list[AuditLog]:
        records = self.session.scalars(
            select(AuditLogRecord).order_by(desc(AuditLogRecord.created_at)).limit(limit),
        ).all()
        return [self._to_log(row) for row in records]

    def list_logs_by_correlation_id(self, correlation_id: str, limit: int = 100) -> list[AuditLog]:
        records = self.session.scalars(
            select(AuditLogRecord)
            .where(AuditLogRecord.correlation_id == correlation_id)
            .order_by(AuditLogRecord.created_at)
            .limit(limit),
        ).all()
        return [self._to_log(row) for row in records]

    def append_log(self, log: AuditLog) -> AuditLog:
        record = AuditLogRecord(
            correlation_id=log.correlation_id,
            level=log.level.value,
            module=log.module,
            symbol=log.symbol,
            strategy=log.strategy,
            message=log.message,
            created_at=log.occurred_at,
        )
        self.session.add(record)
        self.session.commit()
        return log

    @staticmethod
    def _to_log(row: AuditLogRecord) -> AuditLog:
        return AuditLog(
            occurred_at=_as_utc(row.created_at),
            level=Severity(row.level),
            module=row.module,
            symbol=row.symbol,
            strategy=row.strategy,
            message=row.message,
            correlation_id=row.correlation_id,
        )


class SqlAlchemyRiskRepository(RiskRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_rules(self) -> list[RiskRule]:
        records = self.session.scalars(select(RiskRuleRecord)).all()
        return [
            RiskRule(
                name=row.name,
                current_value=row.current_value,
                threshold=row.threshold,
                status=Severity(row.status),
                action=row.action,
            )
            for row in records
        ]

    def list_events(self, limit: int = 100) -> list[RiskEvent]:
        records = self.session.scalars(
            select(RiskEventRecord).order_by(desc(RiskEventRecord.created_at)).limit(limit),
        ).all()
        return [self._to_event(row) for row in records]

    def append_events(self, events: list[RiskEvent]) -> list[RiskEvent]:
        for event in events:
            self.session.add(
                RiskEventRecord(
                    correlation_id=event.correlation_id,
                    rule=event.rule,
                    symbol=event.symbol,
                    trigger_value=event.trigger_value,
                    action=event.action,
                    reason=event.reason,
                    created_at=event.occurred_at,
                ),
            )
        self.session.commit()
        return events

    def list_events_by_correlation_id(self, correlation_id: str, limit: int = 100) -> list[RiskEvent]:
        records = self.session.scalars(
            select(RiskEventRecord)
            .where(RiskEventRecord.correlation_id == correlation_id)
            .order_by(RiskEventRecord.created_at)
            .limit(limit),
        ).all()
        return [self._to_event(row) for row in records]

    @staticmethod
    def _to_event(row: RiskEventRecord) -> RiskEvent:
        return RiskEvent(
            occurred_at=_as_utc(row.created_at),
            rule=row.rule,
            symbol=row.symbol,
            trigger_value=row.trigger_value,
            action=row.action,
            reason=row.reason,
            correlation_id=row.correlation_id,
        )


class SqlAlchemyAiAnalysisRepository(AiAnalysisRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_analysis(self, analysis: AiAnalysis) -> AiAnalysis:
        self.session.add(
            AiAnalysisRecord(
                correlation_id=analysis.correlation_id,
                provider=analysis.provider,
                model=analysis.model,
                market_regime=analysis.market_regime,
                sentiment_score=analysis.sentiment_score,
                risk_level=analysis.risk_level.value,
                event_risk=int(analysis.event_risk),
                allowed_direction=analysis.allowed_direction.value,
                confidence=analysis.confidence,
                rationale=analysis.rationale,
                structured_payload=analysis.structured_payload,
                created_at=analysis.updated_at,
            ),
        )
        self.session.commit()
        return analysis

    def get_latest_analysis(self) -> AiAnalysis | None:
        record = self.session.scalars(
            select(AiAnalysisRecord)
            .order_by(desc(AiAnalysisRecord.created_at))
            .limit(1),
        ).first()
        return self._to_analysis(record) if record else None

    def get_analysis_by_correlation_id(self, correlation_id: str) -> AiAnalysis | None:
        record = self.session.scalars(
            select(AiAnalysisRecord)
            .where(AiAnalysisRecord.correlation_id == correlation_id)
            .order_by(desc(AiAnalysisRecord.created_at))
            .limit(1),
        ).first()
        return self._to_analysis(record) if record else None

    @staticmethod
    def _to_analysis(record: AiAnalysisRecord) -> AiAnalysis:
        return AiAnalysis(
            correlation_id=record.correlation_id,
            market_regime=record.market_regime,
            sentiment_score=record.sentiment_score,
            risk_level=RiskLevel(record.risk_level),
            event_risk=bool(record.event_risk),
            allowed_direction=AllowedDirection(record.allowed_direction),
            confidence=record.confidence,
            provider=record.provider,
            model=record.model,
            rationale=record.rationale or [],
            structured_payload=record.structured_payload,
            updated_at=_as_utc(record.created_at),
        )


class SqlAlchemySystemStateRepository(SystemStateRepository):
    STATE_ID = "global"

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_state(self) -> SystemControlState:
        record = self.session.get(SystemStateRecord, self.STATE_ID)
        if record is None:
            return SystemControlState()
        return SystemControlState(
            paused=bool(record.paused),
            kill_switch_armed=bool(record.kill_switch_armed),
            updated_at=_as_utc(record.updated_at),
            reason=record.reason,
        )

    def save_state(self, state: SystemControlState) -> SystemControlState:
        record = self.session.get(SystemStateRecord, self.STATE_ID)
        if record is None:
            record = SystemStateRecord(id=self.STATE_ID)
            self.session.add(record)
        record.paused = int(state.paused)
        record.kill_switch_armed = int(state.kill_switch_armed)
        record.reason = state.reason
        record.updated_at = state.updated_at
        self.session.commit()
        return state

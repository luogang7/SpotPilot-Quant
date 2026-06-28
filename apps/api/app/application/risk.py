from dataclasses import dataclass

from app.domain.models import (
    AiAnalysis,
    Balance,
    Order,
    Position,
    RiskEvent,
    RiskRule,
    RiskStatus,
    RiskStatusResponse,
    Severity,
)


@dataclass(frozen=True)
class RiskThresholds:
    max_single_trade_loss_percent: float = 1.0
    max_daily_loss_percent: float = 3.0
    max_drawdown_percent: float = 10.0
    max_symbol_position_percent: float = 20.0
    max_total_position_percent: float = 60.0
    max_consecutive_losses: int = 5
    max_data_latency_seconds: int = 300


@dataclass(frozen=True)
class RuleEvaluation:
    rule: RiskRule
    event: RiskEvent | None = None


class RiskEngine:
    def evaluate(
        self,
        balances: list[Balance],
        positions: list[Position],
        ai: AiAnalysis,
        persisted_rules: list[RiskRule],
        historical_orders: list[Order] | None = None,
        data_latency_seconds: int = 0,
        data_integrity: str = "unknown",
        paused: bool = False,
        kill_switch_armed: bool = False,
        thresholds: RiskThresholds | None = None,
        correlation_id: str = "risk-evaluation",
    ) -> RiskStatusResponse:
        limits = thresholds or RiskThresholds()
        evaluations = self._evaluate_rules(
            balances=balances,
            positions=positions,
            ai=ai,
            historical_orders=historical_orders or [],
            data_latency_seconds=data_latency_seconds,
            data_integrity=data_integrity,
            paused=paused,
            kill_switch_armed=kill_switch_armed,
            thresholds=limits,
            correlation_id=correlation_id,
        )
        rules = persisted_rules or [evaluation.rule for evaluation in evaluations]
        events = [evaluation.event for evaluation in evaluations if evaluation.event is not None]

        critical_actions = {event.action for event in events}
        kill_switch_event = next((event for event in events if event.rule == "Kill Switch"), None)
        if kill_switch_event is not None:
            return RiskStatusResponse(
                status=RiskStatus.PAUSED,
                summary=f"风控触发暂停：{kill_switch_event.reason} 仅允许人工检查和管理已有现货仓位。",
                rules=rules,
                events=events,
            )
        if "no_new_positions" in critical_actions:
            return RiskStatusResponse(
                status=RiskStatus.NO_NEW_POSITIONS,
                summary="风控禁止新开仓：允许撤单、持有或卖出现有现货仓位。",
                rules=rules,
                events=events,
            )
        if "pause" in critical_actions:
            primary_reason = events[0].reason if events else "禁止新开仓。"
            return RiskStatusResponse(
                status=RiskStatus.PAUSED,
                summary=f"风控触发暂停：{primary_reason} 仅允许人工检查和管理已有现货仓位。",
                rules=rules,
                events=events,
            )
        if "reduce_only" in critical_actions:
            return RiskStatusResponse(
                status=RiskStatus.REDUCE_ONLY,
                summary="风控要求降低仓位：仅允许减仓、撤单和风险处置。",
                rules=rules,
                events=events,
            )
        return RiskStatusResponse(
            status=RiskStatus.ALLOW_TRADING,
            summary="P0 风控检查通过，仅允许现货 dry-run 或已确认的 Spot Live 动作。",
            rules=rules,
            events=events,
        )

    def _evaluate_rules(
        self,
        balances: list[Balance],
        positions: list[Position],
        ai: AiAnalysis,
        historical_orders: list[Order],
        data_latency_seconds: int,
        data_integrity: str,
        paused: bool,
        kill_switch_armed: bool,
        thresholds: RiskThresholds,
        correlation_id: str,
    ) -> list[RuleEvaluation]:
        account_equity = self._account_equity(balances, positions)
        position_values = {
            position.symbol: max(position.quantity * position.current_price, 0)
            for position in positions
        }
        total_position_value = sum(position_values.values())
        total_position_percent = self._percent(total_position_value, account_equity)
        largest_symbol_percent = max(
            (self._percent(value, account_equity) for value in position_values.values()),
            default=0,
        )
        worst_position_loss_percent = max(
            (
                self._loss_percent(position.unrealized_pnl, max(position.quantity * position.average_price, 0))
                for position in positions
            ),
            default=0,
        )
        daily_loss_percent = self._loss_percent(
            sum(position.unrealized_pnl for position in positions),
            account_equity,
        )
        consecutive_losses = self._consecutive_rejected_or_loss_orders(historical_orders)

        return [
            self._rule(
                name="Kill Switch",
                current=str(kill_switch_armed).lower(),
                threshold="false",
                ok=not kill_switch_armed,
                fail_action="pause",
                reason="Kill Switch 已触发，禁止新开仓并要求撤销挂单。",
                correlation_id=correlation_id,
            ),
            self._rule(
                name="全局暂停",
                current=str(paused).lower(),
                threshold="false",
                ok=not paused,
                fail_action="no_new_positions",
                reason="系统已暂停策略开仓，仅允许管理已有现货仓位。",
                correlation_id=correlation_id,
            ),
            self._rule(
                name="账户余额来源",
                current=f"{len(balances)} balances",
                threshold=">= 1",
                ok=bool(balances),
                fail_action="pause",
                reason="未配置账户余额来源，默认暂停新开仓。",
                correlation_id=correlation_id,
            ),
            self._rule(
                name="数据延迟",
                current=f"{data_latency_seconds}s / {data_integrity}",
                threshold=f"<= {thresholds.max_data_latency_seconds}s and complete",
                ok=(
                    data_latency_seconds <= thresholds.max_data_latency_seconds
                    and not data_integrity.startswith("exchange_error")
                    and data_integrity not in {"empty", "local_cache_empty", "exchange_error_cooling_down"}
                ),
                fail_action="no_new_positions",
                reason="行情数据延迟或不可用，禁止新开仓。",
                correlation_id=correlation_id,
            ),
            self._rule(
                name="单笔最大亏损",
                current=f"{worst_position_loss_percent:.2f}%",
                threshold=f"{thresholds.max_single_trade_loss_percent:.2f}%",
                ok=worst_position_loss_percent <= thresholds.max_single_trade_loss_percent,
                fail_action="reduce_only",
                reason="单笔浮动亏损超过阈值，要求减仓或人工检查。",
                correlation_id=correlation_id,
            ),
            self._rule(
                name="单日最大亏损",
                current=f"{daily_loss_percent:.2f}%",
                threshold=f"{thresholds.max_daily_loss_percent:.2f}%",
                ok=daily_loss_percent <= thresholds.max_daily_loss_percent,
                fail_action="no_new_positions",
                reason="账户当日亏损代理指标超过阈值，禁止新开仓。",
                correlation_id=correlation_id,
            ),
            self._rule(
                name="最大回撤",
                current="N/A",
                threshold=f"{thresholds.max_drawdown_percent:.2f}%",
                ok=True,
                fail_action="reduce_only",
                reason="缺少权益曲线来源，暂不触发自动拦截。",
                correlation_id=correlation_id,
                warn_when_ok=True,
            ),
            self._rule(
                name="单币最大仓位",
                current=f"{largest_symbol_percent:.2f}%",
                threshold=f"{thresholds.max_symbol_position_percent:.2f}%",
                ok=largest_symbol_percent <= thresholds.max_symbol_position_percent,
                fail_action="reduce_only",
                reason="单币现货仓位超过阈值，要求降低该币种风险暴露。",
                correlation_id=correlation_id,
            ),
            self._rule(
                name="总仓位上限",
                current=f"{total_position_percent:.2f}%",
                threshold=f"{thresholds.max_total_position_percent:.2f}%",
                ok=total_position_percent <= thresholds.max_total_position_percent,
                fail_action="no_new_positions",
                reason="总现货仓位超过阈值，禁止新开仓。",
                correlation_id=correlation_id,
            ),
            self._rule(
                name="连续亏损暂停",
                current=str(consecutive_losses),
                threshold=str(thresholds.max_consecutive_losses),
                ok=consecutive_losses < thresholds.max_consecutive_losses,
                fail_action="pause",
                reason="连续亏损或连续拒单达到阈值，暂停策略开仓。",
                correlation_id=correlation_id,
            ),
            self._rule(
                name="AI 高风险暂停",
                current=ai.risk_level.value,
                threshold="below high",
                ok=ai.risk_level.value not in {"high", "extreme"} and ai.allowed_direction.value != "none",
                fail_action="no_new_positions",
                reason="AI 风险等级或允许方向禁止新开仓。",
                correlation_id=correlation_id,
            ),
        ]

    @staticmethod
    def _rule(
        name: str,
        current: str,
        threshold: str,
        ok: bool,
        fail_action: str,
        reason: str,
        correlation_id: str,
        warn_when_ok: bool = False,
    ) -> RuleEvaluation:
        severity = Severity.SUCCESS if ok and not warn_when_ok else Severity.WARNING
        action = "allow" if ok else fail_action
        rule = RiskRule(
            name=name,
            current_value=current,
            threshold=threshold,
            status=severity,
            action=action,
        )
        if ok:
            return RuleEvaluation(rule=rule)
        return RuleEvaluation(
            rule=rule,
            event=RiskEvent(
                rule=name,
                symbol="ACCOUNT",
                trigger_value=current,
                action=fail_action,
                reason=reason,
                correlation_id=correlation_id,
            ),
        )

    @staticmethod
    def _account_equity(balances: list[Balance], positions: list[Position]) -> float:
        cash = sum(balance.total for balance in balances if balance.asset.upper() in {"USDT", "USD"})
        position_value = sum(max(position.quantity * position.current_price, 0) for position in positions)
        return max(cash + position_value, 0)

    @staticmethod
    def _percent(value: float, denominator: float) -> float:
        if denominator <= 0:
            return 0
        return round((value / denominator) * 100, 4)

    @staticmethod
    def _loss_percent(pnl: float, base: float) -> float:
        if pnl >= 0 or base <= 0:
            return 0
        return round((abs(pnl) / base) * 100, 4)

    @staticmethod
    def _consecutive_rejected_or_loss_orders(orders: list[Order]) -> int:
        count = 0
        for order in sorted(orders, key=lambda item: item.created_at, reverse=True):
            if order.status.startswith("rejected") or "loss" in order.status:
                count += 1
                continue
            break
        return count

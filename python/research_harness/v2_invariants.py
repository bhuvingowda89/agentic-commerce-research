from __future__ import annotations

from dataclasses import dataclass

from .models import TransactionRecord, TransactionRequest, TransactionState
from .services import CommerceServices
from .v2_events import EventRecord, EventType


@dataclass(frozen=True)
class V2InvariantReport:
    order_count: int
    successful_payment_count: int
    active_order_count: int
    cart_count: int
    violation: bool
    violation_types: tuple[str, ...]

    def to_event(self, run_id: str, logical_transaction_id: str, scenario: str | None = None) -> EventRecord:
        return EventRecord(
            run_id=run_id,
            component="invariant_evaluator",
            event_type=EventType.INVARIANT_EVALUATED,
            logical_transaction_id=logical_transaction_id,
            scenario=scenario,
            metadata={
                "orderCount": self.order_count,
                "successfulPaymentCount": self.successful_payment_count,
                "activeOrderCount": self.active_order_count,
                "cartCount": self.cart_count,
                "violation": self.violation,
                "violationTypes": list(self.violation_types),
            },
        )


def evaluate_v2_logical_invariants(
    record: TransactionRecord | None,
    services: CommerceServices,
    request: TransactionRequest,
) -> V2InvariantReport:
    return evaluate_v2_invariants(record, services, request.idempotency_key)


def evaluate_v2_invariants(record: TransactionRecord | None, services: CommerceServices, idempotency_key: str) -> V2InvariantReport:
    orders = [order for order in services.orders.values() if order.idempotency_key == idempotency_key]
    payments = [payment for payment in services.payments.values() if payment.idempotency_key == idempotency_key and payment.status.value == "SUCCEEDED"]
    carts = [cart for cart in services.carts.values() if cart.idempotency_key == idempotency_key]
    active_orders = [order for order in orders if order.status == "ACTIVE"]
    violations: list[str] = []

    if len(payments) > 1:
        violations.append("I1_AT_MOST_ONE_SUCCESSFUL_PAYMENT")
    if record and record.state == TransactionState.COMPLETED:
        if not record.order_id or not any(order.order_id == record.order_id for order in orders):
            violations.append("I2_COMPLETED_MISSING_VALID_ORDER")
        if not record.payment_id or not any(payment.payment_id == record.payment_id for payment in payments):
            violations.append("I2_COMPLETED_MISSING_SUCCESSFUL_PAYMENT")
    if len(orders) > 1:
        violations.append("I3_AT_MOST_ONE_ORDER")
    if record and record.state == TransactionState.COMPENSATED and active_orders:
        violations.append("I4_COMPENSATED_HAS_ACTIVE_ORDER")
    if record and record.recovered:
        for side_effect in [*carts, *orders, *payments]:
            if side_effect.transaction_id != record.transaction_id:
                violations.append("I5_RECOVERY_TRANSACTION_IDENTITY_MISMATCH")
                break
    if record and record.state in {TransactionState.COMPLETED, TransactionState.COMPENSATED, TransactionState.FAILED}:
        if record.state == TransactionState.COMPLETED and active_orders and not payments:
            violations.append("I6_TERMINAL_STATE_INCONSISTENT")
        if record.state == TransactionState.COMPENSATED and payments:
            violations.append("I6_TERMINAL_STATE_INCONSISTENT")
        if record.state == TransactionState.FAILED and (active_orders or payments):
            violations.append("I6_TERMINAL_STATE_INCONSISTENT")
    if record is None and (orders or payments):
        violations.append("I6_DOWNSTREAM_EFFECT_WITHOUT_COORDINATOR_RECORD")

    unique_violations = tuple(dict.fromkeys(violations))
    return V2InvariantReport(
        order_count=len(orders),
        successful_payment_count=len(payments),
        active_order_count=len(active_orders),
        cart_count=len(carts),
        violation=bool(unique_violations),
        violation_types=unique_violations,
    )

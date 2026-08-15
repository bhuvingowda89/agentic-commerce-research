from __future__ import annotations

from dataclasses import dataclass

from .models import TransactionRecord, TransactionState
from .services import CommerceServices


@dataclass(frozen=True)
class InvariantReport:
    order_count: int
    successful_payment_count: int
    active_order_count: int
    duplicate_order: bool
    duplicate_payment: bool
    orphaned_order: bool
    violation: bool
    violation_type: str | None


def evaluate_invariants(record: TransactionRecord, services: CommerceServices) -> InvariantReport:
    order_count = services.order_count_for_idempotency_key(record.idempotency_key)
    successful_payment_count = services.successful_payment_count_for_idempotency_key(record.idempotency_key)
    active_order_count = services.active_order_count_for_idempotency_key(record.idempotency_key)
    duplicate_order = order_count > 1
    duplicate_payment = successful_payment_count > 1
    orphaned_order = record.state == TransactionState.COMPENSATED and active_order_count > 0

    violation_type = None
    if duplicate_payment:
        violation_type = "AT_MOST_ONCE_PAYMENT"
    elif record.state == TransactionState.COMPLETED and not record.order_id:
        violation_type = "COMPLETED_TRANSACTION_MISSING_ORDER"
    elif record.state == TransactionState.COMPLETED and not record.payment_id:
        violation_type = "COMPLETED_TRANSACTION_MISSING_PAYMENT"
    elif duplicate_order:
        violation_type = "NO_DUPLICATE_ORDER"
    elif orphaned_order:
        violation_type = "NO_ORPHANED_ACTIVE_ORDER_AFTER_COMPENSATION"
    elif record.recovered and record.order_id:
        order = services.orders.get(record.order_id)
        if order is not None and order.transaction_id != record.transaction_id:
            violation_type = "RECOVERY_PRESERVES_TRANSACTION_IDENTITY"
    elif record.state == TransactionState.COMPLETED:
        cart = services.carts.get(record.cart_id or "")
        order = services.orders.get(record.order_id)
        payment = services.payments.get(record.payment_id or "")
        if not cart or not order or not payment:
            violation_type = "CROSS_SERVICE_STATE_CONSISTENCY"
        elif order.cart_id != cart.cart_id or payment.order_id != order.order_id:
            violation_type = "CROSS_SERVICE_STATE_CONSISTENCY"

    return InvariantReport(
        order_count=order_count,
        successful_payment_count=successful_payment_count,
        active_order_count=active_order_count,
        duplicate_order=duplicate_order,
        duplicate_payment=duplicate_payment,
        orphaned_order=orphaned_order,
        violation=violation_type is not None,
        violation_type=violation_type,
    )

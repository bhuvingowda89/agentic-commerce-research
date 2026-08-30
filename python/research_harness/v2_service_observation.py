from __future__ import annotations

from dataclasses import dataclass

from .models import TransactionRecord, TransactionState


@dataclass(frozen=True)
class ServiceSideEffect:
    resource_id: str
    transaction_id: str
    idempotency_key: str
    status: str


@dataclass(frozen=True)
class V2ServiceObservation:
    coordinator: TransactionRecord | None
    carts: tuple[ServiceSideEffect, ...]
    orders: tuple[ServiceSideEffect, ...]
    payments: tuple[ServiceSideEffect, ...]

    def identity_preserved(self) -> bool:
        if self.coordinator is None:
            return not (self.carts or self.orders or self.payments)
        for effect in (*self.carts, *self.orders, *self.payments):
            if effect.transaction_id != self.coordinator.transaction_id:
                return False
        return True

    def terminal_state_consistent(self) -> bool:
        if self.coordinator is None:
            return not (self.carts or self.orders or self.payments)
        state = self.coordinator.state
        successful_payments = [payment for payment in self.payments if payment.status == "SUCCEEDED"]
        active_orders = [order for order in self.orders if order.status == "ACTIVE"]
        if state == TransactionState.COMPLETED:
            return bool(self.orders) and bool(successful_payments)
        if state == TransactionState.COMPENSATED:
            return not active_orders
        if state == TransactionState.FAILED:
            return not active_orders and not successful_payments
        return True

    def duplicate_order_count(self) -> int:
        return max(0, len(self.orders) - 1)

    def duplicate_payment_count(self) -> int:
        return max(0, len([payment for payment in self.payments if payment.status == "SUCCEEDED"]) - 1)

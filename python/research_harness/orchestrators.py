from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from threading import Lock
from uuid import uuid4

from .failures import InjectedFailure
from .models import TransactionRecord, TransactionRequest, TransactionState
from .retry import RetryPolicy
from .services import CommerceServices


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.records: dict[str, TransactionRecord] = {}
        self.idempotency_index: dict[str, str] = {}
        self.lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def get_by_idempotency_key(self, key: str) -> TransactionRecord | None:
        with self.lock:
            transaction_id = self.idempotency_index.get(key)
            return self.records.get(transaction_id) if transaction_id else None

    def save(self, record: TransactionRecord) -> None:
        with self.lock:
            self.records[record.transaction_id] = record
            self.idempotency_index[record.idempotency_key] = record.transaction_id
            with self.path.open("a", encoding="utf-8") as handle:
                payload = asdict(record)
                payload["state"] = record.state.value
                handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def intermediate_records(self) -> list[TransactionRecord]:
        terminal = {TransactionState.COMPLETED, TransactionState.COMPENSATED, TransactionState.FAILED}
        with self.lock:
            return [record for record in self.records.values() if record.state not in terminal]


class BaselineOrchestrator:
    def __init__(self, services: CommerceServices, transaction_id_factory=None):
        self.services = services
        self.transaction_id_factory = transaction_id_factory or (lambda: str(uuid4()))

    def execute(self, request: TransactionRequest, crash_at: str | None = None) -> TransactionRecord:
        transaction_id = self.transaction_id_factory()
        record = TransactionRecord(transaction_id, request.idempotency_key, TransactionState.STARTED)
        cart = self.services.create_cart(request, transaction_id)
        record.cart_id = cart.cart_id
        record.state = TransactionState.CART_CREATED
        if crash_at == "after_cart":
            raise RuntimeError("SIMULATED_ORCHESTRATOR_INTERRUPTION_AFTER_CART")
        self.services.add_item(cart.cart_id, request)
        order = self.services.create_order(cart.cart_id, request, transaction_id)
        record.order_id = order.order_id
        record.state = TransactionState.ORDER_CREATED
        if crash_at == "after_order":
            raise RuntimeError("SIMULATED_ORCHESTRATOR_INTERRUPTION_AFTER_ORDER")
        if crash_at == "during_payment":
            self.services.execute_payment(order.order_id, request, transaction_id)
            raise RuntimeError("SIMULATED_ORCHESTRATOR_INTERRUPTION_DURING_PAYMENT")
        payment = self.services.execute_payment(order.order_id, request, transaction_id)
        record.payment_id = payment.payment_id
        record.state = TransactionState.COMPLETED
        return record


class ResilientOrchestrator:
    def __init__(self, services: CommerceServices, state_store: StateStore, retry_policy: RetryPolicy, transaction_id_factory=None):
        self.services = services
        self.state_store = state_store
        self.retry_policy = retry_policy
        self.transaction_id_factory = transaction_id_factory or (lambda: str(uuid4()))
        self.execution_lock = Lock()

    def execute(
        self,
        request: TransactionRequest,
        crash_after_order: bool = False,
        crash_at: str | None = None,
    ) -> TransactionRecord:
        with self.execution_lock:
            return self._execute_locked(request, crash_after_order=crash_after_order, crash_at=crash_at)

    def _execute_locked(
        self,
        request: TransactionRequest,
        crash_after_order: bool = False,
        crash_at: str | None = None,
    ) -> TransactionRecord:
        existing = self.state_store.get_by_idempotency_key(request.idempotency_key)
        if existing and existing.state in {TransactionState.COMPLETED, TransactionState.COMPENSATED, TransactionState.FAILED}:
            existing.duplicate_detected = True
            self.state_store.save(existing)
            return existing

        record = existing or TransactionRecord(self.transaction_id_factory(), request.idempotency_key, TransactionState.STARTED)
        self.state_store.save(record)

        try:
            if record.state == TransactionState.STARTED:
                cart, retries = self.retry_policy.run(
                    "create_cart",
                    lambda: self._create_cart_idempotently(record, request),
                )
                record.retry_count += retries
                record.cart_id = cart.cart_id
                record.state = TransactionState.CART_CREATED
                self.state_store.save(record)
                if crash_at == "after_cart":
                    raise RuntimeError("SIMULATED_ORCHESTRATOR_INTERRUPTION_AFTER_CART")
                self.services.add_item(cart.cart_id, request)

            if record.state == TransactionState.CART_CREATED:
                order, retries = self.retry_policy.run(
                    "create_order",
                    lambda: self._create_order_idempotently(record, request),
                )
                record.retry_count += retries
                record.order_id = order.order_id
                record.state = TransactionState.ORDER_CREATED
                self.state_store.save(record)
                if crash_after_order or crash_at == "after_order":
                    raise RuntimeError("SIMULATED_ORCHESTRATOR_INTERRUPTION_AFTER_ORDER")

            if record.state == TransactionState.ORDER_CREATED:
                record.state = TransactionState.PAYMENT_PENDING
                self.state_store.save(record)

            if record.state == TransactionState.PAYMENT_PENDING:
                if crash_at == "during_payment":
                    self.services.execute_payment(record.order_id or "", request, record.transaction_id)
                    raise RuntimeError("SIMULATED_ORCHESTRATOR_INTERRUPTION_DURING_PAYMENT")
                payment = self._execute_payment_idempotently(record, request)
                record.payment_id = payment.payment_id
                record.state = TransactionState.PAYMENT_COMPLETED
                self.state_store.save(record)

            if record.state == TransactionState.PAYMENT_COMPLETED:
                record.state = TransactionState.COMPLETED
                self.state_store.save(record)
            return record
        except InjectedFailure as failure:
            record.failure_reason = failure.failure_type
            if record.order_id:
                record.state = TransactionState.COMPENSATING
                self.state_store.save(record)
                _, retries = self.retry_policy.run("cancel_order", lambda: self._cancel_order(record.order_id or ""))
                record.retry_count += retries
                record.state = TransactionState.COMPENSATED
                record.compensated = True
            else:
                record.state = TransactionState.FAILED
            self.state_store.save(record)
            return record

    def recover(self) -> list[TransactionRecord]:
        recovered = []
        for record in self.state_store.intermediate_records():
            record.recovered = True
            request = TransactionRequest(
                logical_transaction_id=record.transaction_id,
                customer_id="recovered-customer",
                sku="recovered-sku",
                quantity=1,
                amount=1.0,
                currency="USD",
                idempotency_key=record.idempotency_key,
            )
            if record.state == TransactionState.CART_CREATED:
                order = self._create_order_idempotently(record, request)
                record.order_id = order.order_id
                record.state = TransactionState.ORDER_CREATED
                self.state_store.save(record)

            if record.state in {TransactionState.ORDER_CREATED, TransactionState.PAYMENT_PENDING}:
                record.state = TransactionState.PAYMENT_PENDING
                self.state_store.save(record)
                try:
                    payment = self._execute_payment_idempotently(record, request)
                    record.payment_id = payment.payment_id
                    record.state = TransactionState.COMPLETED
                except InjectedFailure as failure:
                    record.failure_reason = failure.failure_type
                    record.state = TransactionState.COMPENSATING
                    self.state_store.save(record)
                    if record.order_id:
                        _, retries = self.retry_policy.run("cancel_order", lambda: self._cancel_order(record.order_id or ""))
                        record.retry_count += retries
                    record.compensated = True
                    record.state = TransactionState.COMPENSATED
                self.state_store.save(record)
                recovered.append(record)
        return recovered

    def _create_cart_idempotently(self, record: TransactionRecord, request: TransactionRequest):
        existing_cart_id = f"cart-{record.transaction_id}"
        if existing_cart_id in self.services.carts:
            return self.services.carts[existing_cart_id]
        return self.services.create_cart(request, record.transaction_id)

    def _create_order_idempotently(self, record: TransactionRecord, request: TransactionRequest):
        existing_order_id = f"order-{record.transaction_id}"
        if existing_order_id in self.services.orders:
            return self.services.orders[existing_order_id]
        return self.services.create_order(record.cart_id or "", request, record.transaction_id)

    def _execute_payment_idempotently(self, record: TransactionRecord, request: TransactionRequest):
        def attempt():
            existing_payment_id = f"payment-{record.transaction_id}"
            if existing_payment_id in self.services.payments:
                return self.services.payments[existing_payment_id]
            return self.services.execute_payment(record.order_id or "", request, record.transaction_id)

        payment, retries = self.retry_policy.run(
            "execute_payment",
            attempt,
        )
        record.retry_count += retries
        return payment

    def _cancel_order(self, order_id: str) -> None:
        self.services.cancel_order(order_id)
        return None

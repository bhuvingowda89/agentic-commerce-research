from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import perf_counter


class ExecutionMode(str, Enum):
    BASELINE = "baseline"
    RESILIENT = "resilient"


class Backend(str, Enum):
    SIMULATION = "simulation"
    SERVICES = "services"


class TransactionState(str, Enum):
    STARTED = "STARTED"
    CART_CREATED = "CART_CREATED"
    ORDER_CREATED = "ORDER_CREATED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_COMPLETED = "PAYMENT_COMPLETED"
    COMPLETED = "COMPLETED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    FAILED = "FAILED"


class PaymentStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class FailureScenario(str, Enum):
    F0_NO_FAILURE = "f0-no-failure"
    F1_CART_HTTP_500 = "f1-cart-http-500"
    F2_ORDER_HTTP_500 = "f2-order-http-500"
    F3_PAYMENT_HTTP_500 = "f3-payment-http-500"
    F4_PAYMENT_TIMEOUT_BEFORE_SIDE_EFFECT = "f4-payment-timeout-before-side-effect"
    F5_PAYMENT_SUCCEEDS_RESPONSE_LOST = "f5-payment-succeeds-response-lost"
    F6_ORDER_SUCCEEDS_RESPONSE_LOST = "f6-order-succeeds-response-lost"
    F7_DUPLICATE_TRANSACTION_REQUEST = "f7-duplicate-transaction-request"
    F8_CONCURRENT_DUPLICATE_TRANSACTION_REQUESTS = "f8-concurrent-duplicate-transaction-requests"
    F9_ORCHESTRATOR_INTERRUPTION_AFTER_ORDER = "f9-orchestrator-interruption-after-order"
    F10_PAYMENT_PERMANENTLY_FAILS = "f10-payment-permanently-fails"
    F11_TRANSIENT_PAYMENT_FAILURE_RECOVERY = "f11-transient-payment-failure-recovery"
    F12_COMPENSATION_FAILURE_RETRY = "f12-compensation-failure-retry"
    CART_PERSISTED_RESPONSE_LOST = "cart-persisted-response-lost"
    ORDER_FAILURE_BEFORE_PERSISTENCE = "order-failure-before-persistence"
    PAYMENT_PERSISTED_RESPONSE_LOST = "payment-persisted-response-lost"
    ORCHESTRATOR_INTERRUPTION_AFTER_CART = "orchestrator-interruption-after-cart"
    ORCHESTRATOR_INTERRUPTION_DURING_PAYMENT = "orchestrator-interruption-during-payment"


@dataclass(frozen=True)
class TransactionRequest:
    logical_transaction_id: str
    customer_id: str
    sku: str
    quantity: int
    amount: float
    currency: str
    idempotency_key: str


@dataclass
class Cart:
    cart_id: str
    transaction_id: str
    idempotency_key: str
    customer_id: str
    items: list[dict[str, int | str]] = field(default_factory=list)


@dataclass
class Order:
    order_id: str
    transaction_id: str
    idempotency_key: str
    cart_id: str
    customer_id: str
    status: str = "ACTIVE"


@dataclass
class Payment:
    payment_id: str
    transaction_id: str
    idempotency_key: str
    order_id: str
    amount: float
    currency: str
    status: PaymentStatus


@dataclass
class TransactionRecord:
    transaction_id: str
    idempotency_key: str
    state: TransactionState
    cart_id: str | None = None
    order_id: str | None = None
    payment_id: str | None = None
    retry_count: int = 0
    operation_retry_count: int = 0
    compensation_retry_count: int = 0
    failure_reason: str | None = None
    recovered: bool = False
    compensated: bool = False
    duplicate_detected: bool = False


@dataclass
class ExperimentResult:
    experiment_id: str
    execution_mode: ExecutionMode
    failure_scenario: FailureScenario
    backend: Backend
    transaction_id: str
    idempotency_key: str
    failure_rate: float
    transaction_count: int
    concurrency: int
    repetition_number: int
    random_seed: int
    environment_metadata: dict[str, str]
    start_timestamp: float
    end_timestamp: float
    latency_ms: float
    recovery_time_ms: float
    status: str
    cart_id: str | None
    order_id: str | None
    payment_id: str | None
    order_count: int
    successful_payment_count: int
    active_order_count: int
    duplicate_order: bool
    duplicate_payment: bool
    orphaned_order: bool
    retry_count: int
    operation_retry_count: int
    compensation_retry_count: int
    total_retry_count: int
    recovered: bool
    compensated: bool
    duplicate_detected: bool
    invariant_violation: bool
    invariant_violation_type: str | None
    failure_reason: str | None = None
    actual_injected_failure: bool = False
    run_started_at: str | None = None
    run_ended_at: str | None = None
    recovery_attempted: bool = False
    recovery_completed: bool = False
    recovery_failed: bool = False
    post_recovery_state: str | None = None
    reconciliation_window_ms: int = 0
    logical_final_state: str | None = None


def now() -> float:
    return perf_counter()

from __future__ import annotations

from dataclasses import dataclass
import json
import urllib.error
import urllib.request

from .invariants import InvariantReport
from .models import ExecutionMode, FailureScenario, TransactionRecord, TransactionRequest, TransactionState


@dataclass(frozen=True)
class ServiceBackendConfig:
    orchestrator_url: str = "http://localhost:8080"
    cart_url: str = "http://localhost:8081"
    order_url: str = "http://localhost:8082"
    payment_url: str = "http://localhost:8083"
    timeout_seconds: float = 3.0


class ServiceBackendClient:
    def __init__(self, config: ServiceBackendConfig):
        self.config = config

    def execute(
        self,
        request: TransactionRequest,
        mode: ExecutionMode,
        scenario: FailureScenario,
        failure_rate: float,
        random_seed: int,
    ) -> tuple[TransactionRecord | None, str | None]:
        payload = {
            "logicalTransactionId": request.logical_transaction_id,
            "customerId": request.customer_id,
            "sku": request.sku,
            "quantity": request.quantity,
            "amount": request.amount,
            "currency": request.currency,
        }
        headers = self._headers(request.idempotency_key, mode, scenario, failure_rate, random_seed)
        try:
            body = self._post_json(f"{self.config.orchestrator_url}/transactions", payload, headers)
            return self._record_from_response(body), None
        except urllib.error.HTTPError as ex:
            if scenario == FailureScenario.F9_ORCHESTRATOR_INTERRUPTION_AFTER_ORDER and mode == ExecutionMode.RESILIENT:
                return self.recover_one(request.idempotency_key, mode, random_seed)
            return None, f"HTTP_{ex.code}"
        except Exception as ex:
            return None, str(ex)

    def inspect(self, idempotency_key: str, record: TransactionRecord | None) -> InvariantReport:
        orders = self._get_json(f"{self.config.order_url}/inspect/idempotency/{idempotency_key}")
        payments = self._get_json(f"{self.config.payment_url}/inspect/idempotency/{idempotency_key}")
        order_count = int(orders.get("orderCount", 0))
        active_order_count = int(orders.get("activeOrderCount", 0))
        successful_payment_count = int(payments.get("successfulPaymentCount", 0))
        duplicate_order = order_count > 1
        duplicate_payment = successful_payment_count > 1
        orphaned_order = bool(record and record.state == TransactionState.COMPENSATED and active_order_count > 0)

        violation_type = None
        if duplicate_payment:
            violation_type = "AT_MOST_ONCE_PAYMENT"
        elif record and record.state == TransactionState.COMPLETED and order_count == 0:
            violation_type = "COMPLETED_TRANSACTION_MISSING_ORDER"
        elif record and record.state == TransactionState.COMPLETED and successful_payment_count == 0:
            violation_type = "COMPLETED_TRANSACTION_MISSING_PAYMENT"
        elif duplicate_order:
            violation_type = "NO_DUPLICATE_ORDER"
        elif orphaned_order:
            violation_type = "NO_ORPHANED_ACTIVE_ORDER_AFTER_COMPENSATION"
        elif record is None and (active_order_count > 0 or successful_payment_count > 0):
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

    def find_transaction(self, idempotency_key: str) -> TransactionRecord | None:
        try:
            body = self._get_json(f"{self.config.orchestrator_url}/transactions/idempotency/{idempotency_key}")
            return self._record_from_response(body)
        except Exception:
            return None

    def recover_one(self, idempotency_key: str, mode: ExecutionMode, random_seed: int) -> tuple[TransactionRecord | None, str | None]:
        try:
            body = self._post_json(
                f"{self.config.orchestrator_url}/recovery/idempotency/{idempotency_key}",
                {},
                self._headers(idempotency_key, mode, FailureScenario.F0_NO_FAILURE, 0.0, random_seed),
            )
            record = self._record_from_response(body)
            record.recovered = True
            return record, None
        except Exception as ex:
            return None, str(ex)

    def _headers(
        self,
        idempotency_key: str,
        mode: ExecutionMode,
        scenario: FailureScenario,
        failure_rate: float,
        random_seed: int,
    ) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
            "X-Execution-Mode": mode.value.upper(),
            "X-Failure-Scenario": scenario.value,
            "X-Failure-Rate": str(failure_rate),
            "X-Random-Seed": str(random_seed),
        }

    def _post_json(self, url: str, payload: dict, headers: dict[str, str]) -> dict:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get_json(self, url: str) -> dict:
        with urllib.request.urlopen(url, timeout=self.config.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _record_from_response(self, payload: dict) -> TransactionRecord:
        return TransactionRecord(
            transaction_id=payload["transactionId"],
            idempotency_key=payload["idempotencyKey"],
            state=TransactionState(payload["state"]),
            cart_id=payload.get("cartId"),
            order_id=payload.get("orderId"),
            payment_id=payload.get("paymentId"),
            retry_count=int(payload.get("retryCount", 0)),
            operation_retry_count=int(payload.get("operationRetryCount", 0)),
            compensation_retry_count=int(payload.get("compensationRetryCount", 0)),
            failure_reason=payload.get("failureReason"),
            recovered=bool(payload.get("recovered", False)),
            compensated=bool(payload.get("compensated", False)),
            duplicate_detected=bool(payload.get("duplicateDetected", False)),
        )

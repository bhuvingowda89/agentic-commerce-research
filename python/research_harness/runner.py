from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from time import perf_counter
from uuid import uuid4
import zlib
import platform

from .failures import FailureConfig, FailureInjector, InjectedFailure
from .invariants import InvariantReport, evaluate_invariants
from .metrics import write_results, write_summary
from .models import Backend, ExecutionMode, ExperimentResult, FailureScenario, TransactionRecord, TransactionRequest, now
from .orchestrators import BaselineOrchestrator, ResilientOrchestrator, StateStore, V2BaselineOrchestrator
from .retry import RetryPolicy
from .service_backend import ServiceBackendClient, ServiceBackendConfig
from .services import CommerceServices
from .v2_config import V2MechanismConfiguration
from .v2_events import EventWriter


@dataclass(frozen=True)
class ExperimentRun:
    raw_path: Path
    summary_path: Path


def build_request(index: int, idempotency_key: str | None = None) -> TransactionRequest:
    return TransactionRequest(
        logical_transaction_id=f"logical-{index:06d}",
        customer_id=f"customer-{index:06d}",
        sku="sku-001",
        quantity=1,
        amount=19.99,
        currency="USD",
        idempotency_key=idempotency_key or f"idempotency-{index:06d}",
    )


def run_experiment(
    mode: ExecutionMode,
    scenario: FailureScenario,
    transactions: int,
    concurrency: int,
    failure_rate: float,
    repetitions: int,
    output_root: Path,
    random_seed: int = 7,
    backend: Backend = Backend.SIMULATION,
    service_config: ServiceBackendConfig = ServiceBackendConfig(),
    repetition_start: int = 1,
    v2_configuration: V2MechanismConfiguration | None = None,
    v2_event_writer: EventWriter | None = None,
    v2_run_id: str | None = None,
) -> list[ExperimentRun]:
    experiment_id = str(uuid4())
    runs = []
    for repetition_number in range(repetition_start, repetition_start + repetitions):
        repetition_seed = random_seed + repetition_number - 1
        output_dir = output_root / mode.value / scenario.value / experiment_id / f"rep-{repetition_number:04d}"
        state_store = StateStore(output_dir / "transaction-state.jsonl")
        services = CommerceServices(FailureInjector(FailureConfig(scenario=scenario, failure_rate=failure_rate, seed=repetition_seed)))
        service_client = ServiceBackendClient(service_config)
        id_factory = _deterministic_id_factory(mode, scenario, repetition_number)
        orchestrator = None
        if backend == Backend.SIMULATION:
            if v2_configuration and v2_configuration.name in {"C0", "C1"}:
                orchestrator = V2BaselineOrchestrator(
                    services,
                    v2_configuration,
                    transaction_id_factory=_v2_random_id_factory(v2_configuration.name, scenario, repetition_number),
                    event_writer=v2_event_writer,
                    run_id=v2_run_id,
                    scenario=scenario.value,
                )
            else:
                orchestrator = (
                    BaselineOrchestrator(services, transaction_id_factory=id_factory)
                    if mode == ExecutionMode.BASELINE
                    else ResilientOrchestrator(services, state_store, RetryPolicy(), transaction_id_factory=id_factory)
                )
        key_prefix = f"{backend.value}-{mode.value}-{scenario.value}-{experiment_id}-rep-{repetition_number:04d}"
        requests = _build_workload(scenario, transactions, repetition_number, key_prefix)
        metadata = _environment_metadata()
        run_started_at = datetime.now(timezone.utc).isoformat()

        def execute_one(request: TransactionRequest) -> ExperimentResult:
            start = now()
            recovery_time_ms = 0.0
            record = None
            failure_reason = None
            invariant_report = None
            if backend == Backend.SERVICES:
                recovery_start = perf_counter()
                record, failure_reason = service_client.execute(request, mode, scenario, failure_rate, repetition_seed, v2_configuration)
                recovery_time_ms = (perf_counter() - recovery_start) * 1000 if record and record.recovered else 0.0
                try:
                    invariant_report = service_client.inspect(request.idempotency_key, record)
                except Exception as inspect_failure:
                    failure_reason = failure_reason or f"INSPECTION_FAILED:{inspect_failure}"
            else:
                try:
                    crash_at = _crash_boundary(scenario)
                    if mode == ExecutionMode.RESILIENT and crash_at:
                        try:
                            record = orchestrator.execute(request, crash_at=crash_at)  # type: ignore[union-attr,arg-type]
                        except RuntimeError as failure:
                            recovery_start = perf_counter()
                            recovered_records = orchestrator.recover()  # type: ignore[union-attr]
                            recovery_time_ms = (perf_counter() - recovery_start) * 1000
                            record = recovered_records[-1] if recovered_records else None
                            failure_reason = None if record else str(failure)
                    else:
                        record = orchestrator.execute(request, crash_at=crash_at)  # type: ignore[union-attr,arg-type]
                except InjectedFailure as failure:
                    failure_reason = failure.failure_type
                except RuntimeError as failure:
                    failure_reason = str(failure)

            end = now()
            return _result_from_record(
                experiment_id=experiment_id,
                mode=mode,
                scenario=scenario,
                failure_rate=failure_rate,
                transaction_count=transactions,
                concurrency=concurrency,
                repetition_number=repetition_number,
                random_seed=repetition_seed,
                metadata=metadata,
                backend=backend,
                request=request,
                record=record,
                services=services,
                invariant_report=invariant_report,
                start=start,
                end=end,
                recovery_time_ms=recovery_time_ms,
                failure_reason=failure_reason,
                run_started_at=run_started_at,
            )

        if concurrency > 1:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                results = list(executor.map(execute_one, requests))
        else:
            results = [execute_one(request) for request in requests]

        if backend == Backend.SERVICES and _runner_reconciliation_enabled(v2_configuration):
            _reconcile_service_results(results, service_client, mode, repetition_seed, reconciliation_window_ms=2_000)

        run_ended_at = datetime.now(timezone.utc).isoformat()
        for result in results:
            result.run_ended_at = run_ended_at
        raw_path = write_results(results, output_dir)
        summary_path = write_summary(results, output_dir)
        runs.append(ExperimentRun(raw_path=raw_path, summary_path=summary_path))
    return runs


def _runner_reconciliation_enabled(v2_configuration: V2MechanismConfiguration | None) -> bool:
    if v2_configuration is None:
        return True
    return v2_configuration.runner_reconciliation_enabled


def _build_workload(
    scenario: FailureScenario,
    transactions: int,
    repetition_number: int,
    key_prefix: str = "idempotency",
) -> list[TransactionRequest]:
    requests = []
    for index in range(transactions):
        global_index = ((repetition_number - 1) * transactions) + index
        key = f"{key_prefix}-{global_index:06d}"
        requests.append(build_request(global_index, key))
        if scenario == FailureScenario.F7_DUPLICATE_TRANSACTION_REQUEST:
            requests.append(build_request(global_index, key))
        if scenario == FailureScenario.F8_CONCURRENT_DUPLICATE_TRANSACTION_REQUESTS:
            requests.append(build_request(global_index, key))
    return requests


def _result_from_record(
    experiment_id: str,
    mode: ExecutionMode,
    scenario: FailureScenario,
    failure_rate: float,
    transaction_count: int,
    concurrency: int,
    repetition_number: int,
    random_seed: int,
    metadata: dict[str, str],
    backend: Backend,
    request: TransactionRequest,
    record: TransactionRecord | None,
    services: CommerceServices,
    invariant_report: InvariantReport | None,
    start: float,
    end: float,
    recovery_time_ms: float,
    failure_reason: str | None,
    run_started_at: str,
) -> ExperimentResult:
    if record is None:
        order_count = invariant_report.order_count if invariant_report else services.order_count_for_idempotency_key(request.idempotency_key)
        successful_payment_count = invariant_report.successful_payment_count if invariant_report else services.successful_payment_count_for_idempotency_key(request.idempotency_key)
        active_order_count = invariant_report.active_order_count if invariant_report else services.active_order_count_for_idempotency_key(request.idempotency_key)
        violation_type = None
        if successful_payment_count > 1:
            violation_type = "AT_MOST_ONCE_PAYMENT"
        elif order_count > 1:
            violation_type = "NO_DUPLICATE_ORDER"
        elif successful_payment_count > 0 or active_order_count > 0:
            violation_type = "CROSS_SERVICE_STATE_CONSISTENCY"
        report = invariant_report or InvariantReport(
            order_count=order_count,
            successful_payment_count=successful_payment_count,
            active_order_count=active_order_count,
            duplicate_order=order_count > 1,
            duplicate_payment=successful_payment_count > 1,
            orphaned_order=False,
            violation=violation_type is not None,
            violation_type=violation_type,
        )
        transaction_id = request.logical_transaction_id
        status = "FAILED"
        cart_id = order_id = payment_id = None
        retry_count = 0
        operation_retry_count = 0
        compensation_retry_count = 0
        recovered = compensated = duplicate_detected = False
    else:
        report = invariant_report or evaluate_invariants(record, services)
        transaction_id = record.transaction_id
        status = record.state.value
        cart_id = record.cart_id
        order_id = record.order_id
        payment_id = record.payment_id
        retry_count = record.retry_count
        operation_retry_count = record.operation_retry_count
        compensation_retry_count = record.compensation_retry_count
        recovered = record.recovered or recovery_time_ms > 0
        compensated = record.compensated
        duplicate_detected = record.duplicate_detected
        failure_reason = record.failure_reason or failure_reason

    return ExperimentResult(
        experiment_id=experiment_id,
        execution_mode=mode,
        failure_scenario=scenario,
        backend=backend,
        transaction_id=transaction_id,
        idempotency_key=request.idempotency_key,
        failure_rate=failure_rate,
        transaction_count=transaction_count,
        concurrency=concurrency,
        repetition_number=repetition_number,
        random_seed=random_seed,
        environment_metadata=metadata,
        start_timestamp=start,
        end_timestamp=end,
        latency_ms=(end - start) * 1000,
        recovery_time_ms=recovery_time_ms,
        status=status,
        cart_id=cart_id,
        order_id=order_id,
        payment_id=payment_id,
        order_count=report.order_count,
        successful_payment_count=report.successful_payment_count,
        active_order_count=report.active_order_count,
        duplicate_order=report.duplicate_order,
        duplicate_payment=report.duplicate_payment,
        orphaned_order=report.orphaned_order,
        retry_count=retry_count,
        operation_retry_count=operation_retry_count,
        compensation_retry_count=compensation_retry_count,
        total_retry_count=operation_retry_count + compensation_retry_count,
        recovered=recovered,
        compensated=compensated,
        duplicate_detected=duplicate_detected,
        invariant_violation=report.violation,
        invariant_violation_type=report.violation_type,
        failure_reason=failure_reason,
        actual_injected_failure=_actual_injected_failure(scenario, failure_rate, random_seed, request, record, failure_reason, recovery_time_ms),
        run_started_at=run_started_at,
    )


def _reconcile_service_results(
    results: list[ExperimentResult],
    service_client: ServiceBackendClient,
    mode: ExecutionMode,
    random_seed: int,
    reconciliation_window_ms: int,
) -> None:
    by_key: dict[str, list[ExperimentResult]] = {}
    for result in results:
        by_key.setdefault(result.idempotency_key, []).append(result)

    deadline = perf_counter() + (reconciliation_window_ms / 1000.0)
    for idempotency_key, attempts in by_key.items():
        final_state = _best_observed_state(attempts)
        recovery_attempted = any(attempt.recovered for attempt in attempts)
        recovery_failed = False

        if mode == ExecutionMode.RESILIENT:
            record = service_client.find_transaction(idempotency_key)
            if record:
                final_state = record.state.value
                for attempt in attempts:
                    attempt.transaction_id = record.transaction_id
                    attempt.cart_id = record.cart_id
                    attempt.order_id = record.order_id
                    attempt.payment_id = record.payment_id
                    attempt.operation_retry_count = record.operation_retry_count
                    attempt.compensation_retry_count = record.compensation_retry_count
                    attempt.total_retry_count = record.operation_retry_count + record.compensation_retry_count
                    attempt.retry_count = attempt.total_retry_count
                while not _is_terminal_state(final_state) and perf_counter() < deadline:
                    recovery_attempted = True
                    record, error = service_client.recover_one(idempotency_key, mode, random_seed)
                    if record is None:
                        recovery_failed = True
                        break
                    final_state = record.state.value
                    for attempt in attempts:
                        attempt.transaction_id = record.transaction_id
                        attempt.cart_id = record.cart_id
                        attempt.order_id = record.order_id
                        attempt.payment_id = record.payment_id
                        attempt.operation_retry_count = record.operation_retry_count
                        attempt.compensation_retry_count = record.compensation_retry_count
                        attempt.total_retry_count = record.operation_retry_count + record.compensation_retry_count
                        attempt.retry_count = attempt.total_retry_count
                        attempt.failure_reason = attempt.failure_reason or error
                if not _is_terminal_state(final_state) and recovery_attempted:
                    recovery_failed = True

        recovery_completed = recovery_attempted and _is_terminal_state(final_state)
        for attempt in attempts:
            attempt.reconciliation_window_ms = reconciliation_window_ms
            attempt.logical_final_state = final_state
            attempt.post_recovery_state = final_state if recovery_attempted else None
            attempt.recovery_attempted = recovery_attempted
            attempt.recovery_completed = recovery_completed
            attempt.recovery_failed = recovery_failed


def _best_observed_state(attempts: list[ExperimentResult]) -> str:
    states = [attempt.status for attempt in attempts]
    if "COMPLETED" in states:
        return "COMPLETED"
    for state in ("COMPENSATED", "FAILED", "PAYMENT_COMPLETED", "PAYMENT_PENDING", "ORDER_CREATED", "CART_CREATED", "STARTED"):
        if state in states:
            return state
    return states[0] if states else "FAILED"


def _is_terminal_state(state: str | None) -> bool:
    return state in {"COMPLETED", "COMPENSATED", "FAILED"}


def _crash_boundary(scenario: FailureScenario) -> str | None:
    if scenario == FailureScenario.ORCHESTRATOR_INTERRUPTION_AFTER_CART:
        return "after_cart"
    if scenario == FailureScenario.F9_ORCHESTRATOR_INTERRUPTION_AFTER_ORDER:
        return "after_order"
    if scenario == FailureScenario.ORCHESTRATOR_INTERRUPTION_DURING_PAYMENT:
        return "during_payment"
    return None


def _deterministic_id_factory(mode: ExecutionMode, scenario: FailureScenario, repetition_number: int):
    lock = Lock()
    counter = {"value": 0}

    def next_id() -> str:
        with lock:
            counter["value"] += 1
            return f"tx-{mode.value}-{scenario.value}-r{repetition_number:04d}-{counter['value']:08d}"

    return next_id


def _v2_random_id_factory(configuration_name: str, scenario: FailureScenario, repetition_number: int):
    lock = Lock()
    counter = {"value": 0}

    def next_id(request: TransactionRequest) -> str:
        with lock:
            counter["value"] += 1
            return f"tx-v2-{configuration_name.lower()}-{scenario.value}-r{repetition_number:04d}-{counter['value']:08d}"

    return next_id


def _actual_injected_failure(
    scenario: FailureScenario,
    failure_rate: float,
    random_seed: int,
    request: TransactionRequest,
    record: TransactionRecord | None,
    failure_reason: str | None,
    recovery_time_ms: float,
) -> bool:
    if scenario == FailureScenario.F0_NO_FAILURE or failure_rate <= 0.0:
        return False
    if scenario in (FailureScenario.F7_DUPLICATE_TRANSACTION_REQUEST, FailureScenario.F8_CONCURRENT_DUPLICATE_TRANSACTION_REQUESTS):
        return bool(record and record.duplicate_detected)
    if scenario == FailureScenario.F9_ORCHESTRATOR_INTERRUPTION_AFTER_ORDER:
        return bool(record and record.recovered) or recovery_time_ms > 0

    operation_by_scenario = {
        FailureScenario.F1_CART_HTTP_500: "create_cart",
        FailureScenario.F2_ORDER_HTTP_500: "create_order",
        FailureScenario.F3_PAYMENT_HTTP_500: "execute_payment",
        FailureScenario.F4_PAYMENT_TIMEOUT_BEFORE_SIDE_EFFECT: "execute_payment",
        FailureScenario.F5_PAYMENT_SUCCEEDS_RESPONSE_LOST: "execute_payment",
        FailureScenario.F6_ORDER_SUCCEEDS_RESPONSE_LOST: "create_order",
        FailureScenario.F10_PAYMENT_PERMANENTLY_FAILS: "execute_payment",
        FailureScenario.F11_TRANSIENT_PAYMENT_FAILURE_RECOVERY: "execute_payment",
        FailureScenario.F12_COMPENSATION_FAILURE_RETRY: "execute_payment",
    }
    operation = operation_by_scenario.get(scenario)
    if operation is None:
        return failure_reason is not None
    transaction_id = record.transaction_id if record else f"tx-{request.logical_transaction_id}"
    return _deterministic_failure_sample(random_seed, transaction_id, operation) < failure_rate


def _deterministic_failure_sample(random_seed: int, transaction_id: str, operation: str) -> float:
    payload = f"{random_seed}:{transaction_id}:{operation}".encode("utf-8")
    return (zlib.crc32(payload) % 10_000) / 10_000.0


def _environment_metadata() -> dict[str, str]:
    return {
        "pythonVersion": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }

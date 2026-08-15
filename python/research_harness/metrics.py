from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import median

from .models import ExperimentResult


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]


def write_results(results: list[ExperimentResult], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "transactions.jsonl"
    with raw_path.open("w", encoding="utf-8") as handle:
        for result in results:
            raw_payload = result.__dict__.copy()
            raw_payload["execution_mode"] = result.execution_mode.value
            raw_payload["failure_scenario"] = result.failure_scenario.value
            raw_payload["backend"] = result.backend.value
            payload = {_to_camel_case(key): value for key, value in raw_payload.items()}
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return raw_path


def write_summary(results: list[ExperimentResult], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.csv"
    total = len(results)
    successful = sum(1 for result in results if result.status == "COMPLETED")
    failed = sum(1 for result in results if result.status == "FAILED")
    recovered = sum(1 for result in results if result.recovered)
    recovery_attempted = sum(1 for result in results if result.recovery_attempted)
    recovery_completed = sum(1 for result in results if result.recovery_completed)
    recovery_failed = sum(1 for result in results if result.recovery_failed)
    compensated = sum(1 for result in results if result.compensated)
    duplicate_orders = sum(1 for result in results if result.duplicate_order)
    duplicate_payments = sum(1 for result in results if result.duplicate_payment)
    orphaned_orders = sum(1 for result in results if result.orphaned_order)
    violations = sum(1 for result in results if result.invariant_violation)
    operation_retries = sum(result.operation_retry_count for result in results)
    compensation_retries = sum(result.compensation_retry_count for result in results)
    retries = sum(result.total_retry_count for result in results)
    if results and results[0].failure_scenario.value in {"f7-duplicate-transaction-request", "f8-concurrent-duplicate-transaction-requests"}:
        injected_failures = max(0, total - results[0].transaction_count)
    else:
        injected_failures = sum(1 for result in results if result.actual_injected_failure)
    recovery_times = [result.recovery_time_ms for result in results if result.recovery_time_ms > 0]
    latencies = [result.latency_ms for result in results]
    reconciliation_window_ms = max((result.reconciliation_window_ms for result in results), default=0)
    elapsed_seconds = (
        max(result.end_timestamp for result in results) - min(result.start_timestamp for result in results)
        if results
        else 0.0
    )
    throughput = total / elapsed_seconds if elapsed_seconds > 0 else 0.0
    logical = _logical_metrics(results)

    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "mode",
                "scenario",
                "backend",
                "configuredFailureRate",
                "transactionCount",
                "concurrency",
                "repetitionNumber",
                "randomSeed",
                "runStartedAt",
                "runEndedAt",
                "actualInjectedFailureCount",
                "actualInjectedFailureRate",
                "attemptCount",
                "requestAttemptCount",
                "successRate",
                "attemptSuccessRate",
                "logicalTransactionSuccessRate",
                "logicalTransactionCount",
                "completedLogicalTransactions",
                "terminalFailedLogicalTransactions",
                "nonTerminalLogicalTransactions",
                "failureRate",
                "recoveryRate",
                "recoveryAttempted",
                "recoveryAttemptedRate",
                "recoveryCompleted",
                "recoveryCompletedRate",
                "recoveryFailed",
                "recoveryFailedRate",
                "recoverySuccessRate",
                "nonTerminalAfterRecoveryRate",
                "compensatedTransactions",
                "compensationRate",
                "duplicateOrderCount",
                "duplicateOrderRate",
                "duplicatePaymentCount",
                "duplicatePaymentRate",
                "orphanedOrderCount",
                "orphanedOrderRate",
                "invariantViolationCount",
                "invariantViolationRate",
                "retryCount",
                "averageRetryCount",
                "operationRetryCount",
                "averageOperationRetryCount",
                "compensationRetryCount",
                "averageCompensationRetryCount",
                "totalRetryCount",
                "averageTotalRetryCount",
                "p50Latency",
                "p50LatencyMs",
                "p95Latency",
                "p95LatencyMs",
                "p99Latency",
                "p99LatencyMs",
                "throughput",
                "throughputTransactionsPerSecond",
                "recoveryTime",
                "averageRecoveryTimeMs",
                "p95RecoveryTimeMs",
                "reconciliationWindowMs",
            ],
        )
        writer.writeheader()
        mode = results[0].execution_mode.value if results else ""
        scenario = results[0].failure_scenario.value if results else ""
        backend = results[0].backend.value if results else ""
        configured_failure_rate = results[0].failure_rate if results else 0.0
        configured_transaction_count = results[0].transaction_count if results else 0
        concurrency = results[0].concurrency if results else 0
        repetition_number = results[0].repetition_number if results else 0
        random_seed = results[0].random_seed if results else 0
        run_started_at = results[0].run_started_at if results else ""
        run_ended_at = results[0].run_ended_at if results else ""
        writer.writerow(
            {
                "mode": mode,
                "scenario": scenario,
                "backend": backend,
                "configuredFailureRate": configured_failure_rate,
                "transactionCount": configured_transaction_count,
                "concurrency": concurrency,
                "repetitionNumber": repetition_number,
                "randomSeed": random_seed,
                "runStartedAt": run_started_at,
                "runEndedAt": run_ended_at,
                "actualInjectedFailureCount": injected_failures,
                "actualInjectedFailureRate": injected_failures / total if total else 0.0,
                "attemptCount": total,
                "requestAttemptCount": total,
                "successRate": successful / total if total else 0.0,
                "attemptSuccessRate": successful / total if total else 0.0,
                "logicalTransactionSuccessRate": logical["completed"] / logical["count"] if logical["count"] else 0.0,
                "logicalTransactionCount": logical["count"],
                "completedLogicalTransactions": logical["completed"],
                "terminalFailedLogicalTransactions": logical["terminal_failed"],
                "nonTerminalLogicalTransactions": logical["non_terminal"],
                "failureRate": failed / total if total else 0.0,
                "recoveryRate": recovered / total if total else 0.0,
                "recoveryAttempted": recovery_attempted,
                "recoveryAttemptedRate": recovery_attempted / total if total else 0.0,
                "recoveryCompleted": recovery_completed,
                "recoveryCompletedRate": recovery_completed / total if total else 0.0,
                "recoveryFailed": recovery_failed,
                "recoveryFailedRate": recovery_failed / total if total else 0.0,
                "recoverySuccessRate": recovery_completed / recovery_attempted if recovery_attempted else "NA",
                "nonTerminalAfterRecoveryRate": logical["non_terminal_after_recovery"] / logical["recovery_attempted_keys"] if logical["recovery_attempted_keys"] else "NA",
                "compensatedTransactions": compensated,
                "compensationRate": compensated / total if total else 0.0,
                "duplicateOrderCount": duplicate_orders,
                "duplicateOrderRate": duplicate_orders / total if total else 0.0,
                "duplicatePaymentCount": duplicate_payments,
                "duplicatePaymentRate": duplicate_payments / total if total else 0.0,
                "orphanedOrderCount": orphaned_orders,
                "orphanedOrderRate": orphaned_orders / total if total else 0.0,
                "invariantViolationCount": violations,
                "invariantViolationRate": violations / total if total else 0.0,
                "retryCount": retries,
                "averageRetryCount": retries / total if total else 0.0,
                "operationRetryCount": operation_retries,
                "averageOperationRetryCount": operation_retries / total if total else 0.0,
                "compensationRetryCount": compensation_retries,
                "averageCompensationRetryCount": compensation_retries / total if total else 0.0,
                "totalRetryCount": retries,
                "averageTotalRetryCount": retries / total if total else 0.0,
                "p50Latency": median(latencies) if latencies else 0.0,
                "p50LatencyMs": median(latencies) if latencies else 0.0,
                "p95Latency": percentile(latencies, 95),
                "p95LatencyMs": percentile(latencies, 95),
                "p99Latency": percentile(latencies, 99),
                "p99LatencyMs": percentile(latencies, 99),
                "throughput": throughput,
                "throughputTransactionsPerSecond": throughput,
                "recoveryTime": sum(recovery_times) / len(recovery_times) if recovery_times else "NA",
                "averageRecoveryTimeMs": sum(recovery_times) / len(recovery_times) if recovery_times else "NA",
                "p95RecoveryTimeMs": percentile(recovery_times, 95) if recovery_times else "NA",
                "reconciliationWindowMs": reconciliation_window_ms,
            }
        )
    return summary_path


def _to_camel_case(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def _logical_metrics(results: list[ExperimentResult]) -> dict[str, int]:
    by_key: dict[str, list[ExperimentResult]] = {}
    for result in results:
        by_key.setdefault(result.idempotency_key, []).append(result)

    completed = 0
    terminal_failed = 0
    non_terminal = 0
    recovery_attempted_keys = 0
    non_terminal_after_recovery = 0
    for attempts in by_key.values():
        state = attempts[0].logical_final_state or _best_observed_state(attempts)
        recovery_attempted = any(attempt.recovery_attempted for attempt in attempts)
        if state == "COMPLETED":
            completed += 1
        elif state in {"FAILED", "COMPENSATED"}:
            terminal_failed += 1
        else:
            non_terminal += 1
        if recovery_attempted:
            recovery_attempted_keys += 1
            if state not in {"COMPLETED", "FAILED", "COMPENSATED"}:
                non_terminal_after_recovery += 1

    return {
        "count": len(by_key),
        "completed": completed,
        "terminal_failed": terminal_failed,
        "non_terminal": non_terminal,
        "recovery_attempted_keys": recovery_attempted_keys,
        "non_terminal_after_recovery": non_terminal_after_recovery,
    }


def _best_observed_state(attempts: list[ExperimentResult]) -> str:
    states = [attempt.status for attempt in attempts]
    if "COMPLETED" in states:
        return "COMPLETED"
    for state in ("COMPENSATED", "FAILED", "PAYMENT_COMPLETED", "PAYMENT_PENDING", "ORDER_CREATED", "CART_CREATED", "STARTED"):
        if state in states:
            return state
    return states[0] if states else "FAILED"

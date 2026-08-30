from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .metrics import write_results, write_summary
from .models import Backend, ExecutionMode, ExperimentResult, FailureScenario, TransactionState, now
from .runner import _actual_injected_failure, _result_from_record, build_request, run_experiment
from .service_backend import ServiceBackendClient, ServiceBackendConfig
from .v2_artifacts import V2RunConfiguration, V2RunStore
from .v2_config import CONFIGURATIONS, configuration
from .v2_crash import DockerComposeCrashController
from .v2_events import EventRecord, EventType


PILOT_ID = "v2_6_pilot_20260829"
BASE_SEED = 2026082900


@dataclass(frozen=True)
class PilotCell:
    cell_id: str
    config: str
    scenario: FailureScenario
    failure_rate: float
    concurrency: int
    transactions: int
    repetitions: int
    paired_group: str
    primary_metric: str
    purpose: str
    crash: bool = False


ORDINARY_CELLS: tuple[PilotCell, ...] = (
    PilotCell("PV2-F8-C0", "C0", FailureScenario.F8_CONCURRENT_DUPLICATE_TRANSACTION_REQUESTS, 1.0, 50, 1000, 3, "F8-identity", "duplicatePaymentRate", "Unprotected fresh execution identity under duplicate invocation."),
    PilotCell("PV2-F8-C1", "C1", FailureScenario.F8_CONCURRENT_DUPLICATE_TRANSACTION_REQUESTS, 1.0, 50, 1000, 3, "F8-identity", "duplicatePaymentRate", "Deterministic identity under duplicate invocation."),
    PilotCell("PV2-F8-C4", "C4", FailureScenario.F8_CONCURRENT_DUPLICATE_TRANSACTION_REQUESTS, 1.0, 50, 1000, 3, "F8-identity", "duplicatePaymentRate", "Idempotent lookup under duplicate invocation."),
    PilotCell("PV2-F11-C1", "C1", FailureScenario.F11_TRANSIENT_PAYMENT_FAILURE_RECOVERY, 0.10, 50, 1000, 3, "F11-retry", "logicalTransactionSuccessRate", "No-retry comparator for pre-side-effect transient payment failure."),
    PilotCell("PV2-F11-C3", "C3", FailureScenario.F11_TRANSIENT_PAYMENT_FAILURE_RECOVERY, 0.10, 50, 1000, 3, "F11-retry", "logicalTransactionSuccessRate", "Bounded retry for pre-side-effect transient payment failure."),
    PilotCell("PV2-F5-C1", "C1", FailureScenario.F5_PAYMENT_SUCCEEDS_RESPONSE_LOST, 0.10, 50, 1000, 3, "F5-ambiguity", "invariantViolationRate", "No-reconciliation comparator for ambiguous payment success."),
    PilotCell("PV2-F5-C3", "C3", FailureScenario.F5_PAYMENT_SUCCEEDS_RESPONSE_LOST, 0.10, 50, 1000, 3, "F5-ambiguity", "duplicatePaymentRate", "Retry without lost-response reconciliation under ambiguous payment success."),
    PilotCell("PV2-F5-C4", "C4", FailureScenario.F5_PAYMENT_SUCCEEDS_RESPONSE_LOST, 0.10, 50, 1000, 3, "F5-ambiguity", "duplicatePaymentRate", "Idempotent lookup without catch-path reconciliation under ambiguous payment success."),
    PilotCell("PV2-F5-C5", "C5", FailureScenario.F5_PAYMENT_SUCCEEDS_RESPONSE_LOST, 0.10, 50, 1000, 3, "F5-ambiguity", "recoveryAttemptedRate", "Lost-response reconciliation and runner attribution audit."),
    PilotCell("PV2-F12-C1", "C1", FailureScenario.F12_COMPENSATION_FAILURE_RETRY, 0.10, 50, 1000, 3, "F12-compensation", "orphanedOrderRate", "No-compensation comparator for permanent payment failure."),
    PilotCell("PV2-F12-C6", "C6", FailureScenario.F12_COMPENSATION_FAILURE_RETRY, 0.10, 50, 1000, 3, "F12-compensation", "compensationRate", "Compensation and compensation retry behavior."),
    PilotCell("PV2-F0-C0", "C0", FailureScenario.F0_NO_FAILURE, 0.0, 50, 1000, 3, "F0-cost", "throughputTransactionsPerSecond", "No-failure random-identity cost sanity."),
    PilotCell("PV2-F0-C2", "C2", FailureScenario.F0_NO_FAILURE, 0.0, 50, 1000, 3, "F0-cost", "throughputTransactionsPerSecond", "No-failure durable coordinator-state cost sanity."),
    PilotCell("PV2-F0-C8", "C8", FailureScenario.F0_NO_FAILURE, 0.0, 50, 1000, 3, "F0-cost", "throughputTransactionsPerSecond", "No-failure full-bundle cost sanity."),
)

CRASH_CELLS: tuple[PilotCell, ...] = (
    PilotCell("PV2-CRASH-C2", "C2", FailureScenario.F0_NO_FAILURE, 0.0, 1, 1, 3, "crash-recovery", "recoveryCompletedRate", "Durable coordinator state without restart recovery; negative crash control.", crash=True),
    PilotCell("PV2-CRASH-C7", "C7", FailureScenario.F0_NO_FAILURE, 0.0, 1, 1, 3, "crash-recovery", "recoveryCompletedRate", "Restart recovery after externally killed orchestrator.", crash=True),
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase V2.6 pilot experiments only.")
    parser.add_argument("--output-root", type=Path, default=Path("results/v2/pilot"))
    parser.add_argument("--ordinary", action="store_true")
    parser.add_argument("--crash", action="store_true")
    parser.add_argument("--analyze", action="store_true")
    args = parser.parse_args()
    if not args.ordinary and not args.crash and not args.analyze:
        args.ordinary = args.crash = args.analyze = True

    controller = DockerComposeCrashController()
    service_config = ServiceBackendConfig(
        orchestrator_url="http://localhost:18080",
        cart_url="http://localhost:18081",
        order_url="http://localhost:18082",
        payment_url="http://localhost:18083",
        timeout_seconds=3.0,
    )
    store = V2RunStore(args.output_root)

    if args.ordinary or args.crash:
        controller.start()
    if args.ordinary:
        run_ordinary_cells(store, controller, service_config)
    if args.crash:
        run_crash_cells(store, controller, service_config)
    if args.analyze:
        analyze(args.output_root)


def run_ordinary_cells(store: V2RunStore, controller: DockerComposeCrashController, service_config: ServiceBackendConfig) -> None:
    for cell in ORDINARY_CELLS:
        for repetition in range(1, cell.repetitions + 1):
            run_id = f"{PILOT_ID}-{cell.cell_id}-rep{repetition:02d}"
            seed = BASE_SEED + repetition - 1
            config = _run_config(cell, repetition, seed)
            context = store.create_run(config, run_id)
            try:
                controller.reset_database()
                runs = run_experiment(
                    ExecutionMode.RESILIENT,
                    cell.scenario,
                    cell.transactions,
                    cell.concurrency,
                    cell.failure_rate,
                    1,
                    context.run_dir / "runner",
                    random_seed=seed,
                    backend=Backend.SERVICES,
                    service_config=service_config,
                    repetition_start=repetition,
                    v2_configuration=CONFIGURATIONS[cell.config],
                    v2_event_writer=context.event_writer,
                    v2_run_id=run_id,
                )
                _copy_runner_outputs(context.run_dir, runs[0].raw_path, runs[0].summary_path)
                _write_run_audit(context.run_dir, cell, seed)
            except Exception as exc:
                context.record_failure("PILOT_RUN_FAILED", exc)


def run_crash_cells(store: V2RunStore, controller: DockerComposeCrashController, service_config: ServiceBackendConfig) -> None:
    client = ServiceBackendClient(service_config)
    for cell in CRASH_CELLS:
        for repetition in range(1, cell.repetitions + 1):
            run_id = f"{PILOT_ID}-{cell.cell_id}-rep{repetition:02d}"
            seed = BASE_SEED + repetition - 1
            context = store.create_run(_run_config(cell, repetition, seed), run_id)
            controller_for_run = DockerComposeCrashController(event_writer=context.event_writer, run_id=run_id)
            started = now()
            result: ExperimentResult | None = None
            try:
                controller.reset_database()
                before_instance = client.orchestrator_instance()["orchestratorInstanceId"]
                request = build_request(repetition, f"{run_id}-key")
                token = f"{run_id}-token"
                context.event_writer.append(EventRecord(run_id=run_id, component="crash_controller", event_type=EventType.CRASH_ARMED, logical_transaction_id=request.logical_transaction_id, scenario="true-crash-after-order", mechanism="restart_recovery", operation="after-order-persisted"))
                holder: dict[str, object] = {}

                def execute_until_killed() -> None:
                    holder["result"] = client.execute(
                        request,
                        ExecutionMode.RESILIENT,
                        FailureScenario.F0_NO_FAILURE,
                        0.0,
                        seed,
                        configuration(cell.config),
                        v2_crash_point="after-order-persisted",
                        v2_crash_token=token,
                    )

                worker = threading.Thread(target=execute_until_killed, daemon=True)
                worker.start()
                status = _wait_for_crash_point(client, token)
                context.event_writer.append(EventRecord(run_id=run_id, component="orchestrator", event_type=EventType.CRASH_POINT_REACHED, logical_transaction_id=request.logical_transaction_id, execution_transaction_id=status["transactionId"], scenario="true-crash-after-order", state_after=status["state"], operation=status["point"]))
                pre = client.inspect(request.idempotency_key, client.find_transaction(request.idempotency_key))
                controller_for_run.preserve_logs(context.run_dir / "logs", "pre-crash")
                kill_started = time.perf_counter()
                controller_for_run.kill_orchestrator()
                killed_at = time.perf_counter()
                worker.join(timeout=5)
                restart_started = time.perf_counter()
                controller_for_run.restart_orchestrator()
                healthy_at = time.perf_counter()
                after_instance = client.orchestrator_instance()["orchestratorInstanceId"]
                recovery_started = time.perf_counter()
                recovered, recovery_error = client.recover_one(request.idempotency_key, ExecutionMode.RESILIENT, seed, configuration(cell.config))
                recovery_ended = time.perf_counter()
                final = client.inspect(request.idempotency_key, recovered)
                controller_for_run.preserve_logs(context.run_dir / "logs", "post-restart")
                if recovered and recovered.state == TransactionState.COMPLETED:
                    context.event_writer.append(EventRecord(run_id=run_id, component="orchestrator", event_type=EventType.RECOVERY_SUCCEEDED, logical_transaction_id=request.logical_transaction_id, execution_transaction_id=recovered.transaction_id, mechanism="restart_recovery", state_after=recovered.state.value))
                else:
                    context.event_writer.append(EventRecord(run_id=run_id, component="orchestrator", event_type=EventType.RECOVERY_FAILED, logical_transaction_id=request.logical_transaction_id, mechanism="restart_recovery", failure_type=recovery_error))
                ended = now()
                result = _result_from_record(
                    experiment_id=PILOT_ID,
                    mode=ExecutionMode.RESILIENT,
                    scenario=FailureScenario.F9_ORCHESTRATOR_INTERRUPTION_AFTER_ORDER,
                    failure_rate=0.0,
                    transaction_count=1,
                    concurrency=1,
                    repetition_number=repetition,
                    random_seed=seed,
                    metadata={"pilotCrash": "true", "beforeInstance": before_instance, "afterInstance": after_instance},
                    backend=Backend.SERVICES,
                    request=request,
                    record=recovered,
                    services=None,  # type: ignore[arg-type]
                    invariant_report=final,
                    start=started,
                    end=ended,
                    recovery_time_ms=(recovery_ended - recovery_started) * 1000,
                    failure_reason=recovery_error,
                    run_started_at=None,
                )
                result.recovery_attempted = True
                result.recovery_completed = bool(recovered and recovered.state == TransactionState.COMPLETED)
                result.recovery_failed = not result.recovery_completed
                result.logical_final_state = recovered.state.value if recovered else "ORDER_CREATED"
                write_results([result], context.run_dir)
                write_summary([result], context.run_dir)
                context.write_json("crash-metrics.json", {
                    "beforeInstance": before_instance,
                    "afterInstance": after_instance,
                    "postgresRunningAfterKill": controller_for_run.postgres_is_running(),
                    "preCrashOrderCount": pre.order_count,
                    "preCrashSuccessfulPaymentCount": pre.successful_payment_count,
                    "downtimeMs": (healthy_at - killed_at) * 1000,
                    "restartLatencyMs": (healthy_at - restart_started) * 1000,
                    "recoveryLatencyMs": (recovery_ended - recovery_started) * 1000,
                    "crashToTerminalLatencyMs": (recovery_ended - kill_started) * 1000,
                    "workerAliveAfterKill": worker.is_alive(),
                    "recoveryError": recovery_error,
                })
            except Exception as exc:
                context.record_failure("PILOT_CRASH_RUN_FAILED", exc)


def analyze(output_root: Path) -> None:
    run_root = output_root / "runs"
    summaries = []
    failures = []
    for run_dir in sorted(run_root.glob("*")):
        summary_path = run_dir / "summary.csv"
        if summary_path.exists():
            row = next(csv.DictReader(summary_path.open(encoding="utf-8")))
            row["runId"] = run_dir.name
            row["config"] = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))["mechanismConfiguration"]["name"]
            summaries.append(row)
        if (run_dir / "failed-run.json").exists():
            failures.append(json.loads((run_dir / "failed-run.json").read_text(encoding="utf-8")))
    (output_root / "analysis").mkdir(parents=True, exist_ok=True)
    (output_root / "analysis" / "run-summaries.json").write_text(json.dumps(summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_root / "analysis" / "failed-runs.json").write_text(json.dumps(failures, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_group_stats(output_root / "analysis" / "run-level-statistics.csv", summaries)
    _write_pairing_audit(output_root / "analysis" / "paired-seed-audit.json", summaries)
    _write_reconciliation_audit(output_root / "analysis" / "reconciliation-attribution-audit.json", run_root, summaries)


def _write_group_stats(path: Path, rows: list[dict[str, str]]) -> None:
    metrics = ["logicalTransactionSuccessRate", "attemptSuccessRate", "invariantViolationRate", "duplicateOrderRate", "duplicatePaymentRate", "recoveryAttemptedRate", "recoveryCompletedRate", "compensationRate", "throughputTransactionsPerSecond", "p50LatencyMs", "p95LatencyMs", "p99LatencyMs", "actualInjectedFailureCount"]
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault((row["scenario"], row["config"]), []).append(row)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scenario", "config", "metric", "n", "mean", "sd", "cv", "ci95HalfWidth"])
        writer.writeheader()
        for (scenario, config), group in sorted(groups.items()):
            for metric in metrics:
                values = [_float(row.get(metric)) for row in group if _float(row.get(metric)) is not None]
                if not values:
                    continue
                mean = statistics.mean(values)
                sd = statistics.stdev(values) if len(values) > 1 else 0.0
                writer.writerow({"scenario": scenario, "config": config, "metric": metric, "n": len(values), "mean": mean, "sd": sd, "cv": abs(sd / mean) if mean else "NA", "ci95HalfWidth": _t95(len(values)) * sd / math.sqrt(len(values)) if len(values) > 1 else "NA"})


def _write_pairing_audit(path: Path, rows: list[dict[str, str]]) -> None:
    audit = []
    by_scenario_seed: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        by_scenario_seed.setdefault((row["scenario"], row["randomSeed"]), []).append(row)
    for (scenario, seed), group in sorted(by_scenario_seed.items()):
        configs = sorted(row["config"] for row in group)
        audit.append({"scenario": scenario, "seed": int(seed), "configs": configs, "sameRunLevelSeed": len(configs) > 1, "failureScheduleBasis": "service failure sampling uses seed plus execution transaction id plus operation; C1-C8 deterministic ids pair exact logical indices, C0 random execution ids do not pair exact failure assignment."})
    path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_reconciliation_audit(path: Path, run_root: Path, rows: list[dict[str, str]]) -> None:
    payload = []
    for row in rows:
        if row["config"] != "C5" or row["scenario"] != FailureScenario.F5_PAYMENT_SUCCEEDS_RESPONSE_LOST.value:
            continue
        run_dir = run_root / row["runId"]
        tx = [json.loads(line) for line in (run_dir / "transactions.jsonl").read_text(encoding="utf-8").splitlines()]
        payload.append({
            "runId": row["runId"],
            "systemReconciliationInferred": sum(1 for item in tx if item.get("status") == "COMPLETED" and item.get("actualInjectedFailure")),
            "runnerReconciliationAttempted": int(row["recoveryAttempted"]),
            "runnerReconciliationCompleted": int(row["recoveryCompleted"]),
            "sideEffectLookupObserved": sum(1 for item in tx if item.get("duplicateDetected")),
            "materialRunnerRepair": int(row["recoveryAttempted"]) > 0,
            "interpretation": "No runner repair if runnerReconciliationAttempted is zero; C5 terminal completion after injected F5 is attributed to orchestrator catch-path reconciliation/side-effect lookup.",
        })
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _copy_runner_outputs(run_dir: Path, raw_path: Path, summary_path: Path) -> None:
    (run_dir / "transactions.jsonl").write_text(raw_path.read_text(encoding="utf-8"), encoding="utf-8")
    (run_dir / "summary.csv").write_text(summary_path.read_text(encoding="utf-8"), encoding="utf-8")


def _write_run_audit(run_dir: Path, cell: PilotCell, seed: int) -> None:
    data = [json.loads(line) for line in (run_dir / "transactions.jsonl").read_text(encoding="utf-8").splitlines()]
    failed_indices = sorted(item["idempotencyKey"] for item in data if item.get("actualInjectedFailure"))
    audit = {"cellId": cell.cell_id, "pairedGroup": cell.paired_group, "seed": seed, "actualInjectedFailureKeys": failed_indices[:2000], "actualInjectedFailureCount": len(failed_indices), "note": "For F8, duplicate attempts are the injected condition. For C0, service execution transaction ids are intentionally random, so probabilistic failure pairing by logical index is not guaranteed."}
    (run_dir / "paired-seed-audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_config(cell: PilotCell, repetition: int, seed: int) -> V2RunConfiguration:
    return V2RunConfiguration(
        cell_id=cell.cell_id,
        mechanism_configuration=CONFIGURATIONS[cell.config],
        scenario=cell.scenario,
        failure_rate=cell.failure_rate,
        concurrency=cell.concurrency,
        transactions=cell.transactions,
        repetition=repetition,
        seed=seed,
        backend=Backend.SERVICES,
    )


def _wait_for_crash_point(client: ServiceBackendClient, token: str) -> dict:
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        try:
            status = client.crash_point_status(token)
            if status.get("reached"):
                return status
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError("crash point was not reached")


def _float(value: str | None) -> float | None:
    if value in (None, "", "NA"):
        return None
    return float(value)


def _t95(n: int) -> float:
    return {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365, 9: 2.306, 10: 2.262}.get(n, 1.96)


if __name__ == "__main__":
    main()

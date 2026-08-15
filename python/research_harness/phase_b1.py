from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, stdev

from .models import Backend, ExecutionMode, FailureScenario
from .phase_a import read_summary_rows, reset_database, write_combined_summary
from .runner import run_experiment
from .service_backend import ServiceBackendConfig


B1_CELLS = [
    (FailureScenario.F0_NO_FAILURE, [0.0]),
    (FailureScenario.F5_PAYMENT_SUCCEEDS_RESPONSE_LOST, [0.01, 0.05, 0.10, 0.20]),
    (FailureScenario.F8_CONCURRENT_DUPLICATE_TRANSACTION_REQUESTS, [1.0]),
    (FailureScenario.F9_ORCHESTRATOR_INTERRUPTION_AFTER_ORDER, [1.0]),
    (FailureScenario.F11_TRANSIENT_PAYMENT_FAILURE_RECOVERY, [0.01, 0.05, 0.10, 0.20]),
    (FailureScenario.F12_COMPENSATION_FAILURE_RETRY, [0.01, 0.05, 0.10, 0.20]),
]

AGGREGATE_METRICS = [
    "attemptSuccessRate",
    "logicalTransactionSuccessRate",
    "terminalFailedLogicalTransactions",
    "nonTerminalLogicalTransactions",
    "invariantViolationRate",
    "duplicateOrderRate",
    "duplicatePaymentRate",
    "orphanedOrderRate",
    "recoveryAttemptedRate",
    "recoveryCompletedRate",
    "recoveryFailedRate",
    "recoverySuccessRate",
    "nonTerminalAfterRecoveryRate",
    "operationRetryCount",
    "averageOperationRetryCount",
    "compensationRetryCount",
    "averageCompensationRetryCount",
    "totalRetryCount",
    "averageTotalRetryCount",
    "compensationRate",
    "p50LatencyMs",
    "p95LatencyMs",
    "p99LatencyMs",
    "throughputTransactionsPerSecond",
    "averageRecoveryTimeMs",
    "p95RecoveryTimeMs",
    "actualInjectedFailureRate",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Stage B1 service-backed experiments.")
    parser.add_argument("--output-root", default="results/phase_b1_services")
    parser.add_argument("--transactions", type=int, default=10_000)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--base-seed", type=int, default=2026081400)
    parser.add_argument("--orchestrator-url", default="http://localhost:8080")
    parser.add_argument("--cart-url", default="http://localhost:8081")
    parser.add_argument("--order-url", default="http://localhost:8082")
    parser.add_argument("--payment-url", default="http://localhost:8083")
    args = parser.parse_args()

    output_root = Path(args.output_root)
    raw_root = output_root / "raw"
    final_root = output_root / "final"
    raw_root.mkdir(parents=True, exist_ok=True)
    final_root.mkdir(parents=True, exist_ok=True)
    failed_log = output_root / "phase_b1_failed_runs.jsonl"
    failed_log.touch(exist_ok=True)
    service_config = ServiceBackendConfig(
        orchestrator_url=args.orchestrator_url,
        cart_url=args.cart_url,
        order_url=args.order_url,
        payment_url=args.payment_url,
    )
    phase_started_at = datetime.now(timezone.utc)
    summary_paths: list[Path] = []
    cells = _expanded_cells()

    for cell_index, (scenario, failure_rate) in enumerate(cells):
        scenario_seed = args.base_seed + (cell_index * 10_000)
        cell_dir = raw_root / scenario.value / _rate_label(failure_rate)
        for mode in (ExecutionMode.BASELINE, ExecutionMode.RESILIENT):
            for repetition in range(1, args.repetitions + 1):
                reset_database()
                try:
                    runs = run_experiment(
                        mode=mode,
                        scenario=scenario,
                        transactions=args.transactions,
                        concurrency=args.concurrency,
                        failure_rate=failure_rate,
                        repetitions=1,
                        output_root=cell_dir,
                        random_seed=scenario_seed,
                        backend=Backend.SERVICES,
                        service_config=service_config,
                        repetition_start=repetition,
                    )
                    summary_paths.extend(run.summary_path for run in runs)
                    print(
                        f"completed stage=B1 mode={mode.value} scenario={scenario.value} "
                        f"failureRate={failure_rate} repetition={repetition} seed={scenario_seed + repetition - 1}",
                        flush=True,
                    )
                except Exception as exc:
                    event = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "backend": Backend.SERVICES.value,
                        "mode": mode.value,
                        "scenario": scenario.value,
                        "transactionCount": args.transactions,
                        "concurrency": args.concurrency,
                        "configuredFailureRate": failure_rate,
                        "repetitionNumber": repetition,
                        "randomSeed": scenario_seed + repetition - 1,
                        "errorType": exc.__class__.__name__,
                        "error": str(exc),
                    }
                    with failed_log.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(event, sort_keys=True) + "\n")
                    print(
                        f"failed stage=B1 mode={mode.value} scenario={scenario.value} "
                        f"failureRate={failure_rate} repetition={repetition}: {exc}",
                        flush=True,
                    )

    rows = _normalize_rows(read_summary_rows(summary_paths))
    rows = sorted(
        rows,
        key=lambda row: (
            row["scenario"],
            float(row["configuredFailureRate"]),
            int(row["concurrency"]),
            row["mode"],
            int(row["repetitionNumber"]),
            int(row["randomSeed"]),
        ),
    )
    summary_path = final_root / "phase_b1_summary.csv"
    aggregate_path = final_root / "phase_b1_aggregate_by_scenario_mode.csv"
    comparison_path = final_root / "phase_b1_comparison.csv"
    metadata_path = final_root / "phase_b1_metadata.json"
    final_failed_log = final_root / "phase_b1_failed_runs.jsonl"

    write_combined_summary(rows, summary_path)
    _write_aggregate(rows, aggregate_path)
    _write_comparison(rows, comparison_path)
    shutil.copyfile(failed_log, final_failed_log)

    phase_ended_at = datetime.now(timezone.utc)
    metadata = {
        "backend": Backend.SERVICES.value,
        "phase": "B1",
        "startedAt": phase_started_at.isoformat(),
        "endedAt": phase_ended_at.isoformat(),
        "runtimeSeconds": (phase_ended_at - phase_started_at).total_seconds(),
        "scenarioRateCells": len(cells),
        "modes": [mode.value for mode in ExecutionMode],
        "transactionsPerRun": args.transactions,
        "concurrency": args.concurrency,
        "repetitions": args.repetitions,
        "expectedRuns": len(cells) * len(ExecutionMode) * args.repetitions,
        "completedRuns": len(rows),
        "summaryPath": str(summary_path),
        "aggregatePath": str(aggregate_path),
        "comparisonPath": str(comparison_path),
        "failedRunLog": str(final_failed_log),
        "rawRoot": str(raw_root),
        "outputRootSizeBytes": _directory_size(output_root),
        "databaseIsolation": "PostgreSQL tables orchestrator_transactions, carts, orders, payments are truncated with restart identity before each independent repetition/configuration.",
        "reconciliationWindowMs": _first_value(rows, "reconciliationWindowMs"),
        "seedMapping": "For each scenario/rate cell, scenario_seed = base_seed + cell_index * 10000; repetition seed = scenario_seed + repetition - 1; BASELINE and RESILIENT share the same seed for matching cell/repetition.",
        "environment": _environment_metadata(),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(metadata, indent=2, sort_keys=True))


def _expanded_cells() -> list[tuple[FailureScenario, float]]:
    return [(scenario, rate) for scenario, rates in B1_CELLS for rate in rates]


def _rate_label(rate: float) -> str:
    return f"rate-{rate:.2f}".replace(".", "p")


def normalize_rows(rows: list[dict[str, str]], phase: str = "B1") -> list[dict[str, str]]:
    for row in rows:
        row["phase"] = phase
        row["p50LatencyMs"] = row.get("p50LatencyMs") or row.get("p50Latency", "")
        row["p95LatencyMs"] = row.get("p95LatencyMs") or row.get("p95Latency", "")
        row["p99LatencyMs"] = row.get("p99LatencyMs") or row.get("p99Latency", "")
        row["throughputTransactionsPerSecond"] = row.get("throughputTransactionsPerSecond") or row.get("throughput", "")
        row["averageRecoveryTimeMs"] = row.get("averageRecoveryTimeMs") or row.get("recoveryTime", "")
        row["attemptCount"] = row.get("attemptCount") or row.get("requestAttemptCount", "")
        row["requestAttemptCount"] = row.get("requestAttemptCount") or row.get("attemptCount", "")
    return rows


def _normalize_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return normalize_rows(rows, "B1")


def write_aggregate(rows: list[dict[str, str]], path: Path) -> None:
    groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault((row["scenario"], row["configuredFailureRate"], row["concurrency"], row["mode"]), []).append(row)

    fieldnames = ["scenario", "configuredFailureRate", "concurrency", "mode", "backend", "n"]
    for metric in AGGREGATE_METRICS:
        fieldnames.extend([
            f"{metric}Mean",
            f"{metric}Median",
            f"{metric}Std",
            f"{metric}Min",
            f"{metric}Max",
            f"{metric}Ci95Low",
            f"{metric}Ci95High",
            f"{metric}N",
        ])

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for (scenario, failure_rate, concurrency, mode), group_rows in sorted(groups.items()):
            output = {
                "scenario": scenario,
                "configuredFailureRate": failure_rate,
                "concurrency": concurrency,
                "mode": mode,
                "backend": group_rows[0].get("backend", ""),
                "n": len(group_rows),
            }
            for metric in AGGREGATE_METRICS:
                output.update(_stats_fields(metric, _numeric_values(group_rows, metric)))
            writer.writerow(output)


def _write_aggregate(rows: list[dict[str, str]], path: Path) -> None:
    write_aggregate(rows, path)


def write_comparison(rows: list[dict[str, str]], path: Path) -> None:
    groups: dict[tuple[str, str, str], dict[str, list[dict[str, str]]]] = {}
    for row in rows:
        key = (row["scenario"], row["configuredFailureRate"], row["concurrency"])
        groups.setdefault(key, {}).setdefault(row["mode"], []).append(row)

    fieldnames = ["scenario", "configuredFailureRate", "concurrency", "metric", "baselineMean", "resilientMean", "deltaResilientMinusBaseline", "pairedBy"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for (scenario, failure_rate, concurrency), by_mode in sorted(groups.items()):
            baseline = by_mode.get(ExecutionMode.BASELINE.value, [])
            resilient = by_mode.get(ExecutionMode.RESILIENT.value, [])
            for metric in AGGREGATE_METRICS:
                baseline_values = _numeric_values(baseline, metric)
                resilient_values = _numeric_values(resilient, metric)
                baseline_mean = mean(baseline_values) if baseline_values else "NA"
                resilient_mean = mean(resilient_values) if resilient_values else "NA"
                delta = (
                    resilient_mean - baseline_mean
                    if isinstance(baseline_mean, float) and isinstance(resilient_mean, float)
                    else "NA"
                )
                writer.writerow({
                    "scenario": scenario,
                    "configuredFailureRate": failure_rate,
                    "concurrency": concurrency,
                    "metric": metric,
                    "baselineMean": baseline_mean,
                    "resilientMean": resilient_mean,
                    "deltaResilientMinusBaseline": delta,
                    "pairedBy": "scenario,configuredFailureRate,concurrency,randomSeed,repetitionNumber",
                })


def _write_comparison(rows: list[dict[str, str]], path: Path) -> None:
    write_comparison(rows, path)


def _stats_fields(metric: str, values: list[float]) -> dict[str, float | str | int]:
    if not values:
        return {
            f"{metric}Mean": "NA",
            f"{metric}Median": "NA",
            f"{metric}Std": "NA",
            f"{metric}Min": "NA",
            f"{metric}Max": "NA",
            f"{metric}Ci95Low": "NA",
            f"{metric}Ci95High": "NA",
            f"{metric}N": 0,
        }
    metric_mean = mean(values)
    metric_std = stdev(values) if len(values) > 1 else 0.0
    half_width = 1.96 * metric_std / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {
        f"{metric}Mean": metric_mean,
        f"{metric}Median": median(values),
        f"{metric}Std": metric_std,
        f"{metric}Min": min(values),
        f"{metric}Max": max(values),
        f"{metric}Ci95Low": metric_mean - half_width,
        f"{metric}Ci95High": metric_mean + half_width,
        f"{metric}N": len(values),
    }


def _numeric_values(rows: list[dict[str, str]], metric: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        raw = row.get(metric, "")
        if raw in ("", "NA", None):
            continue
        try:
            values.append(float(raw))
        except ValueError:
            continue
    return values


def _environment_metadata() -> dict[str, str | int | None]:
    return {
        "os": platform.platform(),
        "cpu": platform.processor(),
        "cpuCoreCount": _cpu_count(),
        "ramBytes": _ram_bytes(),
        "javaVersion": _command_output(["java", "-version"]),
        "pythonVersion": platform.python_version(),
        "springBootVersion": "3.3.6",
        "postgresqlVersion": _command_output(["docker-compose", "exec", "-T", "postgres", "psql", "-U", "commerce", "-d", "commerce_research", "-tAc", "select version();"]),
        "dockerVersion": _command_output(["docker", "--version"]),
        "dockerComposeVersion": _command_output(["docker-compose", "--version"]),
        "servicePorts": "orchestrator=8080, cart=8081, order=8082, payment=8083",
        "serviceTopology": "workload runner -> orchestrator -> cart-service/order-service/payment-simulator -> PostgreSQL",
    }


def _cpu_count() -> int | None:
    try:
        return int(platform.os.cpu_count() or 0)
    except Exception:
        return None


def _ram_bytes() -> int | None:
    try:
        return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
    except Exception:
        return None


def _command_output(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        return (completed.stdout + completed.stderr).strip().replace("\n", " | ")
    except Exception as exc:
        return f"UNAVAILABLE:{exc}"


def _directory_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _first_value(rows: list[dict[str, str]], key: str) -> str:
    for row in rows:
        if row.get(key):
            return row[key]
    return ""


if __name__ == "__main__":
    main()

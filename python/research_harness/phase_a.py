from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, stdev

from .models import Backend, ExecutionMode, FailureScenario
from .runner import run_experiment
from .service_backend import ServiceBackendConfig


PHASE_A_SCENARIOS = [
    FailureScenario.F0_NO_FAILURE,
    FailureScenario.F1_CART_HTTP_500,
    FailureScenario.F2_ORDER_HTTP_500,
    FailureScenario.F3_PAYMENT_HTTP_500,
    FailureScenario.F4_PAYMENT_TIMEOUT_BEFORE_SIDE_EFFECT,
    FailureScenario.F5_PAYMENT_SUCCEEDS_RESPONSE_LOST,
    FailureScenario.F6_ORDER_SUCCEEDS_RESPONSE_LOST,
    FailureScenario.F7_DUPLICATE_TRANSACTION_REQUEST,
    FailureScenario.F8_CONCURRENT_DUPLICATE_TRANSACTION_REQUESTS,
    FailureScenario.F9_ORCHESTRATOR_INTERRUPTION_AFTER_ORDER,
    FailureScenario.F10_PAYMENT_PERMANENTLY_FAILS,
    FailureScenario.F11_TRANSIENT_PAYMENT_FAILURE_RECOVERY,
    FailureScenario.F12_COMPENSATION_FAILURE_RETRY,
]

SUMMARY_METRICS = [
    "successRate",
    "invariantViolationRate",
    "duplicatePaymentRate",
    "duplicateOrderRate",
    "orphanedOrderRate",
    "recoveryRate",
    "compensationRate",
    "p50Latency",
    "p95Latency",
    "p99Latency",
    "throughput",
    "averageRetryCount",
    "recoveryTime",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase A service-backed experiments.")
    parser.add_argument("--output-root", default="results/phase_a_services")
    parser.add_argument("--transactions", type=int, default=10_000)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--failure-rate", type=float, default=0.05)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--base-seed", type=int, default=2026081400)
    parser.add_argument("--orchestrator-url", default="http://localhost:8080")
    parser.add_argument("--cart-url", default="http://localhost:8081")
    parser.add_argument("--order-url", default="http://localhost:8082")
    parser.add_argument("--payment-url", default="http://localhost:8083")
    parser.add_argument("--skip-reset", action="store_true")
    parser.add_argument("--only-scenario", choices=[scenario.value for scenario in PHASE_A_SCENARIOS])
    parser.add_argument("--only-mode", choices=[mode.value for mode in ExecutionMode])
    parser.add_argument("--only-repetition", type=int)
    args = parser.parse_args()

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    failure_log = output_root / "phase_a_failed_runs.jsonl"
    phase_started_at = datetime.now(timezone.utc)
    service_config = ServiceBackendConfig(
        orchestrator_url=args.orchestrator_url,
        cart_url=args.cart_url,
        order_url=args.order_url,
        payment_url=args.payment_url,
    )

    summary_paths: list[Path] = []
    for scenario_index, scenario in enumerate(PHASE_A_SCENARIOS):
        if args.only_scenario and scenario.value != args.only_scenario:
            continue
        configured_failure_rate = 0.0 if scenario == FailureScenario.F0_NO_FAILURE else args.failure_rate
        scenario_seed = args.base_seed + (scenario_index * 10_000)
        for mode in (ExecutionMode.BASELINE, ExecutionMode.RESILIENT):
            if args.only_mode and mode.value != args.only_mode:
                continue
            for repetition in range(1, args.repetitions + 1):
                if args.only_repetition and repetition != args.only_repetition:
                    continue
                if not args.skip_reset:
                    reset_database()
                try:
                    runs = run_experiment(
                        mode=mode,
                        scenario=scenario,
                        transactions=args.transactions,
                        concurrency=args.concurrency,
                        failure_rate=configured_failure_rate,
                        repetitions=1,
                        output_root=output_root,
                        random_seed=scenario_seed,
                        backend=Backend.SERVICES,
                        service_config=service_config,
                        repetition_start=repetition,
                    )
                    summary_paths.extend(run.summary_path for run in runs)
                    print(f"completed mode={mode.value} scenario={scenario.value} repetition={repetition} seed={scenario_seed + repetition - 1}")
                except Exception as exc:  # preserve failed run metadata and keep moving
                    event = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "backend": Backend.SERVICES.value,
                        "mode": mode.value,
                        "scenario": scenario.value,
                        "transactionCount": args.transactions,
                        "concurrency": args.concurrency,
                        "configuredFailureRate": configured_failure_rate,
                        "repetitionNumber": repetition,
                        "randomSeed": scenario_seed + repetition - 1,
                        "errorType": exc.__class__.__name__,
                        "error": str(exc),
                    }
                    with failure_log.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(event, sort_keys=True) + "\n")
                    print(f"failed mode={mode.value} scenario={scenario.value} repetition={repetition}: {exc}")

    combined_path = output_root / "phase_a_summary.csv"
    aggregate_path = output_root / "phase_a_aggregate_by_scenario_mode.csv"
    rows = read_summary_rows(summary_paths)
    write_combined_summary(rows, combined_path)
    write_aggregate(rows, aggregate_path)
    phase_ended_at = datetime.now(timezone.utc)
    metadata = {
        "backend": Backend.SERVICES.value,
        "phase": "A",
        "startedAt": phase_started_at.isoformat(),
        "endedAt": phase_ended_at.isoformat(),
        "runtimeSeconds": (phase_ended_at - phase_started_at).total_seconds(),
        "summaryPath": str(combined_path),
        "aggregatePath": str(aggregate_path),
        "failedRunLog": str(failure_log),
        "summaryCount": len(rows),
    }
    (output_root / "phase_a_metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(metadata, indent=2, sort_keys=True))


def reset_database() -> None:
    sql = """
    truncate table
      orchestrator_transactions,
      carts,
      orders,
      payments
    restart identity;
    """
    subprocess.run(
        [
            "docker-compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "commerce",
            "-d",
            "commerce_research",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def read_summary_rows(paths: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row["summaryPath"] = str(path)
                rows.append(row)
    return rows


def write_combined_summary(rows: list[dict[str, str]], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_aggregate(rows: list[dict[str, str]], path: Path) -> None:
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault((row["scenario"], row["mode"]), []).append(row)

    fieldnames = ["scenario", "mode", "backend", "repetitionCount"]
    for metric in SUMMARY_METRICS:
        fieldnames.extend([f"{metric}Mean", f"{metric}Median", f"{metric}Std"])

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for (scenario, mode), group_rows in sorted(groups.items()):
            output = {
                "scenario": scenario,
                "mode": mode,
                "backend": group_rows[0].get("backend", ""),
                "repetitionCount": len(group_rows),
            }
            for metric in SUMMARY_METRICS:
                values = [float(row[metric]) for row in group_rows if row.get(metric) not in (None, "")]
                output[f"{metric}Mean"] = mean(values) if values else ""
                output[f"{metric}Median"] = median(values) if values else ""
                output[f"{metric}Std"] = stdev(values) if len(values) > 1 else 0.0
            writer.writerow(output)


if __name__ == "__main__":
    main()

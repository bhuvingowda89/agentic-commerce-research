from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .models import Backend, ExecutionMode, FailureScenario
from .phase_a import read_summary_rows, reset_database, write_combined_summary
from .phase_b1 import _directory_size, _environment_metadata, _first_value, normalize_rows, write_aggregate, write_comparison
from .runner import run_experiment
from .service_backend import ServiceBackendConfig


B2_CELLS = [
    (FailureScenario.F0_NO_FAILURE, 0.0),
    (FailureScenario.F5_PAYMENT_SUCCEEDS_RESPONSE_LOST, 0.05),
    (FailureScenario.F8_CONCURRENT_DUPLICATE_TRANSACTION_REQUESTS, 1.0),
]

B2_CONCURRENCY_LEVELS = [1, 10, 100]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Stage B2 service-backed concurrency-sensitivity experiments.")
    parser.add_argument("--output-root", default="results/phase_b2_services")
    parser.add_argument("--transactions", type=int, default=10_000)
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
    failed_log = output_root / "phase_b2_failed_runs.jsonl"
    failed_log.touch(exist_ok=True)
    service_config = ServiceBackendConfig(
        orchestrator_url=args.orchestrator_url,
        cart_url=args.cart_url,
        order_url=args.order_url,
        payment_url=args.payment_url,
    )
    phase_started_at = datetime.now(timezone.utc)
    summary_paths: list[Path] = []
    cells = [(scenario, failure_rate, concurrency) for scenario, failure_rate in B2_CELLS for concurrency in B2_CONCURRENCY_LEVELS]

    for cell_index, (scenario, failure_rate, concurrency) in enumerate(cells):
        scenario_seed = args.base_seed + (cell_index * 10_000)
        cell_dir = raw_root / scenario.value / _rate_label(failure_rate) / f"concurrency-{concurrency:03d}"
        for mode in (ExecutionMode.BASELINE, ExecutionMode.RESILIENT):
            for repetition in range(1, args.repetitions + 1):
                reset_database()
                try:
                    runs = run_experiment(
                        mode=mode,
                        scenario=scenario,
                        transactions=args.transactions,
                        concurrency=concurrency,
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
                        f"completed stage=B2 mode={mode.value} scenario={scenario.value} "
                        f"failureRate={failure_rate} concurrency={concurrency} "
                        f"repetition={repetition} seed={scenario_seed + repetition - 1}",
                        flush=True,
                    )
                except Exception as exc:
                    event = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "backend": Backend.SERVICES.value,
                        "mode": mode.value,
                        "scenario": scenario.value,
                        "transactionCount": args.transactions,
                        "concurrency": concurrency,
                        "configuredFailureRate": failure_rate,
                        "repetitionNumber": repetition,
                        "randomSeed": scenario_seed + repetition - 1,
                        "errorType": exc.__class__.__name__,
                        "error": str(exc),
                    }
                    with failed_log.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(event, sort_keys=True) + "\n")
                    print(
                        f"failed stage=B2 mode={mode.value} scenario={scenario.value} "
                        f"failureRate={failure_rate} concurrency={concurrency} "
                        f"repetition={repetition}: {exc}",
                        flush=True,
                    )

    rows = normalize_rows(read_summary_rows(summary_paths), "B2")
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
    summary_path = final_root / "phase_b2_summary.csv"
    aggregate_path = final_root / "phase_b2_aggregate_by_scenario_mode.csv"
    comparison_path = final_root / "phase_b2_comparison.csv"
    metadata_path = final_root / "phase_b2_metadata.json"
    final_failed_log = final_root / "phase_b2_failed_runs.jsonl"

    write_combined_summary(rows, summary_path)
    write_aggregate(rows, aggregate_path)
    write_comparison(rows, comparison_path)
    shutil.copyfile(failed_log, final_failed_log)

    phase_ended_at = datetime.now(timezone.utc)
    metadata = {
        "backend": Backend.SERVICES.value,
        "phase": "B2",
        "startedAt": phase_started_at.isoformat(),
        "endedAt": phase_ended_at.isoformat(),
        "runtimeSeconds": (phase_ended_at - phase_started_at).total_seconds(),
        "scenarioRateCells": len(B2_CELLS),
        "concurrencyLevels": B2_CONCURRENCY_LEVELS,
        "modes": [mode.value for mode in ExecutionMode],
        "transactionsPerRun": args.transactions,
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
        "seedMapping": "For each scenario/rate/concurrency cell, scenario_seed = base_seed + cell_index * 10000; repetition seed = scenario_seed + repetition - 1; BASELINE and RESILIENT share the same seed for matching cell/repetition.",
        "environment": _environment_metadata(),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(metadata, indent=2, sort_keys=True))


def _rate_label(rate: float) -> str:
    return f"rate-{rate:.2f}".replace(".", "p")


if __name__ == "__main__":
    main()

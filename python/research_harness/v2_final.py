from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import statistics
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .metrics import write_results, write_summary
from .models import Backend, ExecutionMode, FailureScenario, ExperimentResult, TransactionState, now
from .runner import _result_from_record, build_request, run_experiment
from .service_backend import ServiceBackendClient, ServiceBackendConfig
from .v2_artifacts import V2RunConfiguration, V2RunStore, capture_run_metadata
from .v2_config import CONFIGURATIONS, configuration
from .v2_crash import DockerComposeCrashController
from .v2_events import EventRecord, EventType


CAMPAIGN_ID = "v2_7_final_primary_20260829"
BASE_SEED = 2026082900
RESULT_ROOT = Path("results/v2/final")
EVENT_TYPES = [
    "IDEMPOTENT_LOOKUP_ATTEMPT", "IDEMPOTENT_LOOKUP_FOUND", "IDEMPOTENT_LOOKUP_NOT_FOUND",
    "RETRY_ATTEMPT", "RETRY_SUCCEEDED", "RETRY_EXHAUSTED",
    "RECONCILIATION_STARTED", "RECONCILIATION_FOUND_EFFECT", "RECONCILIATION_NOT_FOUND",
    "RECONCILIATION_SUCCEEDED", "RECONCILIATION_FAILED",
    "COMPENSATION_STARTED", "COMPENSATION_RETRY", "COMPENSATION_SUCCEEDED", "COMPENSATION_FAILED",
    "RECOVERY_STARTED", "RECOVERY_SUCCEEDED", "RECOVERY_FAILED",
]


@dataclass(frozen=True)
class Cell:
    cell_id: str
    analysis_class: str
    config: str
    scenario: str
    failure_rate: float
    concurrency: int
    transactions: int
    repetitions: int
    comparator: str
    rq: str
    hypothesis: str
    primary_metric: str
    causal_interpretation: str
    crash: bool = False


PRIMARY_CELLS = [
    Cell("P01", "primary", "C0", "f8-concurrent-duplicate-transaction-requests", 1.0, 50, 2000, 8, "C1", "RQ1", "H1", "duplicatePaymentRate", "Fresh execution identity is insufficient for duplicate invocation."),
    Cell("P02", "primary", "C1", "f8-concurrent-duplicate-transaction-requests", 1.0, 50, 2000, 8, "C0/C4", "RQ1", "H1", "duplicatePaymentRate", "Stable identity plus downstream uniqueness suppresses duplicate effects; not coordinator lookup."),
    Cell("P03", "primary", "C4", "f8-concurrent-duplicate-transaction-requests", 1.0, 50, 2000, 8, "C1/C8", "RQ1", "H1", "duplicateDetectionRate", "Adds explicit coordinator lookup on stable identity."),
    Cell("P04", "primary", "C8", "f8-concurrent-duplicate-transaction-requests", 1.0, 50, 2000, 8, "C4", "RQ1/RQ4", "H1/H6", "logicalTransactionSuccessRate", "Full bundle behavior and cost under duplicate load."),
    Cell("P05", "primary", "C1", "f11-transient-payment-failure-recovery", 0.10, 50, 2000, 8, "C3", "RQ2", "H2", "logicalTransactionSuccessRate", "Stable identity without retry under pre-effect transient payment failure."),
    Cell("P06", "primary", "C3", "f11-transient-payment-failure-recovery", 0.10, 50, 2000, 8, "C1/C8", "RQ2/RQ4", "H2/H6", "logicalTransactionSuccessRate", "Bounded retry resolves pre-effect transient failure."),
    Cell("P07", "primary", "C8", "f11-transient-payment-failure-recovery", 0.10, 50, 2000, 8, "C3", "RQ4", "H6", "throughputTransactionsPerSecond", "Full-bundle overhead when retry is active."),
    Cell("P08", "primary", "C1", "f5-payment-succeeds-response-lost", 0.10, 50, 2000, 8, "C4/C5", "RQ2", "H3", "logicalTransactionSuccessRate", "Stable identity alone does not resolve ambiguous post-payment response loss."),
    Cell("P10", "primary", "C4", "f5-payment-succeeds-response-lost", 0.10, 50, 2000, 8, "C1/C5", "RQ2", "H3", "logicalTransactionSuccessRate", "Explicit lookup before operations without catch-path reconciliation."),
    Cell("P11", "primary", "C5", "f5-payment-succeeds-response-lost", 0.10, 50, 2000, 8, "C1/C4/C8", "RQ2/RQ4", "H3/H6", "reconciliationSuccessRate", "Lost-response reconciliation resolves ambiguous payment outcomes; runner repair disabled."),
    Cell("P12", "primary", "C8", "f5-payment-succeeds-response-lost", 0.10, 50, 2000, 8, "C5", "RQ4", "H6", "throughputTransactionsPerSecond", "Full-bundle ambiguity behavior and cost; runner repair disabled."),
    Cell("P13", "primary", "C1", "f12-compensation-failure-retry", 0.10, 50, 2000, 8, "C6", "RQ1", "H4", "invariantViolationRate", "No-compensation comparator for permanent payment failure after order."),
    Cell("P14", "primary", "C6", "f12-compensation-failure-retry", 0.10, 50, 2000, 8, "C1/C8", "RQ1/RQ4", "H4/H6", "compensationRate", "Compensation preserves invariants after permanent downstream failure."),
    Cell("P15", "primary", "C8", "f12-compensation-failure-retry", 0.10, 50, 2000, 8, "C6", "RQ4", "H6", "throughputTransactionsPerSecond", "Full-bundle compensation behavior and cost."),
    Cell("P16", "primary", "C2", "true-crash-after-order", 0.0, 1, 1, 10, "C7", "RQ3", "H5", "recoveryCompletedRate", "Durable coordinator state without restart recovery under uniqueness constraint.", crash=True),
    Cell("P17", "primary", "C7", "true-crash-after-order", 0.0, 1, 1, 10, "C2/C8", "RQ3", "H5", "recoveryCompletedRate", "Restart recovery on durable state after SIGKILL/restart.", crash=True),
    Cell("P18", "primary", "C8", "true-crash-after-order", 0.0, 1, 1, 10, "C7", "RQ3/RQ4", "H5/H6", "recoveryCompletedRate", "Full-bundle crash recovery and cost.", crash=True),
    Cell("P19", "primary", "C0", "f0-no-failure", 0.0, 50, 2000, 8, "C1", "RQ4", "H6", "throughputTransactionsPerSecond", "Random-identity no-failure cost baseline."),
    Cell("P20", "primary", "C1", "f0-no-failure", 0.0, 50, 2000, 8, "C0/C2", "RQ4", "H6", "throughputTransactionsPerSecond", "Deterministic identity cost."),
    Cell("P21", "primary", "C2", "f0-no-failure", 0.0, 50, 2000, 8, "C1/C8", "RQ4", "H6", "throughputTransactionsPerSecond", "Durable coordinator-state cost."),
    Cell("P22", "primary", "C5", "f0-no-failure", 0.0, 50, 2000, 8, "C2/C8", "RQ4", "H6", "throughputTransactionsPerSecond", "Reconciliation-capable path cost with runner repair disabled."),
    Cell("P23", "primary", "C8", "f0-no-failure", 0.0, 50, 2000, 8, "C1/C2/C5", "RQ4", "H6", "throughputTransactionsPerSecond", "Full-bundle no-failure overhead."),
]

SUPPLEMENTAL_CELLS = [
    Cell("P09", "supplemental", "C3", "f5-payment-succeeds-response-lost", 0.10, 50, 2000, 8, "C1/C5", "RQ2/RQ4", "H2/H3/H6", "retryCountLatency", "Retry overhead under ambiguity where downstream idempotency masks duplicate-payment effects."),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["manifest", "amend-manifest", "run-primary", "audit", "aggregate"])
    args = parser.parse_args()
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    if args.command == "manifest":
        create_manifest()
    elif args.command == "amend-manifest":
        amend_manifest()
    elif args.command == "run-primary":
        run_primary()
    elif args.command == "aggregate":
        aggregate()
    elif args.command == "audit":
        audit()


def create_manifest() -> None:
    if (RESULT_ROOT / "campaign-manifest.json").exists():
        raise RuntimeError("manifest already exists")
    order = execution_order(PRIMARY_CELLS)
    run_counts = counts()
    validate_counts(run_counts)
    payload = {
        "campaignId": CAMPAIGN_ID,
        "status": "FROZEN_FINAL_PRIMARY_CAMPAIGN_NOT_YET_EXECUTED",
        "createdAt": utc_now(),
        "codeCommit": sh(["git", "rev-parse", "HEAD"]),
        "branch": sh(["git", "branch", "--show-current"]),
        "dirtyState": bool(sh(["git", "status", "--porcelain"])),
        "dirtyStatus": sh(["git", "status", "--porcelain"]),
        "baseSeed": BASE_SEED,
        "seedPolicy": "seed = baseSeed + repetitionIndex - 1; same repetition index pairs comparator configs",
        "seeds": [{"repetition": i, "seed": BASE_SEED + i - 1} for i in range(1, 11)],
        "primaryCells": [cell.__dict__ for cell in PRIMARY_CELLS],
        "supplementalCells": [cell.__dict__ for cell in SUPPLEMENTAL_CELLS],
        "executionOrder": order,
        "runCounts": run_counts,
        "mechanismConfigurations": {name: cfg.to_dict() for name, cfg in CONFIGURATIONS.items()},
        "mechanismEvents": EVENT_TYPES,
        "invariants": ["I1 at most one successful payment per logical transaction", "I2 COMPLETED implies valid order and successful payment", "I3 at most one order per logical transaction", "I4 COMPENSATED implies no active payable order", "I5 recovery preserves transaction identity", "I6 terminal coordinator/downstream consistency"],
        "analysisPolicy": "run-level units only; paired deltas by seed; descriptive aggregates now; V2.8 inference later",
        "failedRunPolicy": "preserve all runs; classify before replacement; replacements use new IDs and same seed when appropriate",
        "environment": capture_run_metadata("manifest", V2RunConfiguration("manifest", CONFIGURATIONS["C1"], FailureScenario.F0_NO_FAILURE, 0.0, 1, 1, 1, BASE_SEED, Backend.SERVICES)),
    }
    write_json(RESULT_ROOT / "campaign-manifest.json", payload)
    digest = sha256(RESULT_ROOT / "campaign-manifest.json")
    write_json(RESULT_ROOT / "campaign-manifest.sha256.json", {"path": "results/v2/final/campaign-manifest.json", "sha256": digest})
    write_json(RESULT_ROOT / "campaign-ledger.json", [{"runId": item["runId"], "cellId": item["cellId"], "repetition": item["repetition"], "seed": item["seed"], "state": "PLANNED", "replacementFor": None, "replacementRunId": None} for item in order])
    write_reproducibility_files(payload, digest, "campaign-manifest.json", "campaign-manifest.sha256.json")
    write_manifest_md(payload, digest)


def amend_manifest() -> None:
    original = RESULT_ROOT / "campaign-manifest.json"
    if not original.exists():
        raise RuntimeError("original manifest is required before amendment")
    path = RESULT_ROOT / "campaign-manifest-amendment-001.json"
    if path.exists():
        raise RuntimeError("amendment already exists")
    order = execution_order(PRIMARY_CELLS)
    run_counts = counts()
    validate_counts(run_counts)
    payload = {
        "amendmentId": "campaign-manifest-amendment-001",
        "amends": "results/v2/final/campaign-manifest.json",
        "justification": "Corrects pre-execution manifest classification error: P16-P18 are true-crash cells, not ordinary cells. No final campaign run had started.",
        "createdAt": utc_now(),
        "codeCommit": sh(["git", "rev-parse", "HEAD"]),
        "branch": sh(["git", "branch", "--show-current"]),
        "dirtyState": bool(sh(["git", "status", "--porcelain"])),
        "dirtyStatus": sh(["git", "status", "--porcelain"]),
        "baseSeed": BASE_SEED,
        "seedPolicy": "seed = baseSeed + repetitionIndex - 1; same repetition index pairs comparator configs",
        "seeds": [{"repetition": i, "seed": BASE_SEED + i - 1} for i in range(1, 11)],
        "primaryCells": [cell.__dict__ for cell in PRIMARY_CELLS],
        "supplementalCells": [cell.__dict__ for cell in SUPPLEMENTAL_CELLS],
        "executionOrder": order,
        "runCounts": run_counts,
        "mechanismConfigurations": {name: cfg.to_dict() for name, cfg in CONFIGURATIONS.items()},
        "mechanismEvents": EVENT_TYPES,
        "invariants": ["I1 at most one successful payment per logical transaction", "I2 COMPLETED implies valid order and successful payment", "I3 at most one order per logical transaction", "I4 COMPENSATED implies no active payable order", "I5 recovery preserves transaction identity", "I6 terminal coordinator/downstream consistency"],
        "analysisPolicy": "run-level units only; paired deltas by seed; descriptive aggregates now; V2.8 inference later",
        "failedRunPolicy": "preserve all runs; classify before replacement; replacements use new IDs and same seed when appropriate",
        "environment": capture_run_metadata("manifest-amendment-001", V2RunConfiguration("manifest", CONFIGURATIONS["C1"], FailureScenario.F0_NO_FAILURE, 0.0, 1, 1, 1, BASE_SEED, Backend.SERVICES)),
        "originalManifestSha256": sha256(original),
    }
    write_json(path, payload)
    digest = sha256(path)
    write_json(RESULT_ROOT / "campaign-manifest-amendment-001.sha256.json", {"path": str(path), "sha256": digest})
    write_json(RESULT_ROOT / "campaign-ledger.json", [{"runId": item["runId"], "cellId": item["cellId"], "repetition": item["repetition"], "seed": item["seed"], "state": "PLANNED", "replacementFor": None, "replacementRunId": None} for item in order])
    write_reproducibility_files(payload, digest, "campaign-manifest-amendment-001.json", "campaign-manifest-amendment-001.sha256.json")
    repro = RESULT_ROOT / "reproducibility"
    for name in ("campaign-manifest.json", "campaign-manifest.sha256.json"):
        if (RESULT_ROOT / name).exists():
            shutil.copy2(RESULT_ROOT / name, repro / name)
    write_manifest_md(payload, digest)


def write_reproducibility_files(payload, digest, manifest_name, hash_name):
    repro = RESULT_ROOT / "reproducibility"
    repro.mkdir(parents=True, exist_ok=True)
    write_json(RESULT_ROOT / "execution-order.json", payload["executionOrder"])
    write_json(RESULT_ROOT / "seed-map.json", payload["seeds"])
    write_json(RESULT_ROOT / "environment-metadata.json", payload["environment"])
    write_json(RESULT_ROOT / "failed-run-policy.json", {"policy": payload["failedRunPolicy"]})
    write_json(RESULT_ROOT / "code-commit.json", {"commit": payload["codeCommit"], "branch": payload["branch"]})
    for name in (
        manifest_name,
        hash_name,
        "campaign-ledger.json",
        "execution-order.json",
        "seed-map.json",
        "environment-metadata.json",
        "failed-run-policy.json",
        "code-commit.json",
    ):
        shutil.copy2(RESULT_ROOT / name, repro / name)
    (repro / "README.md").write_text(
        "Reproduce with: PYTHONPATH=python python3 -m research_harness.v2_final run-primary; then aggregate and audit. Use the commit recorded in the effective campaign manifest.\n",
        encoding="utf-8",
    )


def run_primary() -> None:
    manifest_path = effective_manifest_path()
    manifest = read_json(manifest_path)
    if manifest["dirtyState"] or manifest["codeCommit"] != sh(["git", "rev-parse", "HEAD"]) or sh(["git", "status", "--porcelain"]):
        raise RuntimeError("campaign requires clean working tree at frozen commit")
    if sha256(manifest_path) != read_json(manifest_hash_path(manifest_path))["sha256"]:
        raise RuntimeError("manifest hash mismatch")
    controller = DockerComposeCrashController()
    controller.start()
    service_config = ServiceBackendConfig("http://localhost:18080", "http://localhost:18081", "http://localhost:18082", "http://localhost:18083", 3.0)
    store = V2RunStore(RESULT_ROOT)
    ledger = {row["runId"]: row for row in read_json(RESULT_ROOT / "campaign-ledger.json")}
    for item in manifest["executionOrder"]:
        row = ledger[item["runId"]]
        if row["state"] == "COMPLETED":
            continue
        row["state"] = "RUNNING"; save_ledger(ledger)
        cell = cell_by_id(item["cellId"])
        try:
            if cell.config in {"C5", "C8"} and CONFIGURATIONS[cell.config].runner_reconciliation_enabled:
                raise RuntimeError("runner reconciliation unexpectedly enabled")
            if cell.crash:
                run_crash_cell(store, controller, service_config, cell, item["repetition"], item["seed"], item["runId"])
            else:
                run_ordinary_cell(store, controller, service_config, cell, item["repetition"], item["seed"], item["runId"])
            row["state"] = "COMPLETED"
        except Exception as exc:
            row["state"] = "FAILED_INFRASTRUCTURE"
            row["failure"] = str(exc)
        save_ledger(ledger)
    aggregate()
    audit()


def run_ordinary_cell(store, controller, service_config, cell, repetition, seed, run_id) -> None:
    context = store.create_run(run_config(cell, repetition, seed), run_id)
    controller.reset_database()
    runs = run_experiment(ExecutionMode.RESILIENT, FailureScenario(cell.scenario), cell.transactions, cell.concurrency, cell.failure_rate, 1, context.run_dir / "runner", random_seed=seed, backend=Backend.SERVICES, service_config=service_config, repetition_start=repetition, v2_configuration=CONFIGURATIONS[cell.config], v2_event_writer=context.event_writer, v2_run_id=run_id)
    copy(runs[0].raw_path, context.run_dir / "transactions.jsonl")
    copy(runs[0].summary_path, context.run_dir / "summary.csv")
    preserve_logs(controller, context.run_dir / "logs", "run-end")
    write_json(context.run_dir / "run-classification.json", {"classification": "COMPLETED", "analysisClass": cell.analysis_class})


def run_crash_cell(store, controller, service_config, cell, repetition, seed, run_id) -> None:
    context = store.create_run(run_config(cell, repetition, seed), run_id)
    cc = DockerComposeCrashController(event_writer=context.event_writer, run_id=run_id)
    client = ServiceBackendClient(service_config)
    controller.reset_database()
    before = client.orchestrator_instance()["orchestratorInstanceId"]
    request = build_request(repetition, f"{run_id}-key")
    token = f"{run_id}-token"
    started = now()
    context.event_writer.append(EventRecord(run_id, "crash_controller", EventType.CRASH_ARMED, logical_transaction_id=request.logical_transaction_id, scenario="true-crash-after-order", mechanism="restart_recovery", operation="after-order-persisted"))
    holder = {}
    worker = threading.Thread(target=lambda: holder.setdefault("result", client.execute(request, ExecutionMode.RESILIENT, FailureScenario.F0_NO_FAILURE, 0.0, seed, configuration(cell.config), "after-order-persisted", token)), daemon=True)
    worker.start()
    status = wait_crash_point(client, token)
    context.event_writer.append(EventRecord(run_id, "orchestrator", EventType.CRASH_POINT_REACHED, logical_transaction_id=request.logical_transaction_id, execution_transaction_id=status["transactionId"], scenario="true-crash-after-order", state_after=status["state"], operation=status["point"]))
    pre = client.inspect(request.idempotency_key, client.find_transaction(request.idempotency_key))
    preserve_logs(cc, context.run_dir / "logs", "pre-crash")
    kill_at = time.perf_counter(); cc.kill_orchestrator(); killed = time.perf_counter()
    worker.join(timeout=5)
    restart_at = time.perf_counter(); cc.restart_orchestrator(); healthy = time.perf_counter()
    after = client.orchestrator_instance()["orchestratorInstanceId"]
    rec_at = time.perf_counter(); recovered, error = client.recover_one(request.idempotency_key, ExecutionMode.RESILIENT, seed, configuration(cell.config)); rec_end = time.perf_counter()
    final = client.inspect(request.idempotency_key, recovered)
    preserve_logs(cc, context.run_dir / "logs", "post-restart")
    state = recovered.state.value if recovered else "ORDER_CREATED"
    context.event_writer.append(EventRecord(run_id, "orchestrator", EventType.RECOVERY_SUCCEEDED if state == "COMPLETED" else EventType.RECOVERY_FAILED, logical_transaction_id=request.logical_transaction_id, execution_transaction_id=status["transactionId"], mechanism="restart_recovery", state_after=state, failure_type=error))
    result = _result_from_record(CAMPAIGN_ID, ExecutionMode.RESILIENT, FailureScenario.F9_ORCHESTRATOR_INTERRUPTION_AFTER_ORDER, 0.0, 1, 1, repetition, seed, {"beforeInstance": before, "afterInstance": after}, Backend.SERVICES, request, recovered, None, final, started, now(), (rec_end - rec_at) * 1000, error, None)  # type: ignore[arg-type]
    result.recovery_attempted = True
    result.recovery_completed = state == "COMPLETED"
    result.recovery_failed = state != "COMPLETED"
    result.logical_final_state = state
    write_results([result], context.run_dir)
    write_summary([result], context.run_dir)
    write_json(context.run_dir / "crash-metrics.json", {"beforeInstance": before, "afterInstance": after, "preCrashOrderCount": pre.order_count, "preCrashSuccessfulPaymentCount": pre.successful_payment_count, "postgresRunningAfterKill": cc.postgres_is_running(), "downtimeMs": (healthy - killed) * 1000, "restartLatencyMs": (healthy - restart_at) * 1000, "recoveryLatencyMs": (rec_end - rec_at) * 1000, "crashToTerminalLatencyMs": (rec_end - kill_at) * 1000, "recoveryError": error})
    write_json(context.run_dir / "run-classification.json", {"classification": "COMPLETED", "analysisClass": cell.analysis_class})


def aggregate() -> None:
    out = RESULT_ROOT / "analysis"; out.mkdir(parents=True, exist_ok=True)
    rows = []
    for run_dir in sorted((RESULT_ROOT / "runs").glob("*")):
        s = run_dir / "summary.csv"
        if s.exists():
            row = next(csv.DictReader(s.open(encoding="utf-8")))
            cfg = read_json(run_dir / "config.json")
            row.update({"runId": run_dir.name, "cellId": cfg["cellId"], "config": cfg["mechanismConfiguration"]["name"], "analysisClass": "primary"})
            rows.append(row)
    write_csv(out / "run-level-primary.csv", rows)
    grouped = {}
    for row in rows:
        grouped.setdefault(row["cellId"], []).append(row)
    summary = []
    for cell_id, group in sorted(grouped.items()):
        for metric in ["logicalTransactionSuccessRate", "attemptSuccessRate", "invariantViolationRate", "duplicateOrderRate", "duplicatePaymentRate", "compensationRate", "recoveryCompletedRate", "throughputTransactionsPerSecond", "p50LatencyMs", "p95LatencyMs", "p99LatencyMs"]:
            vals = [float(r[metric]) for r in group if r.get(metric) not in ("", "NA", None)]
            if vals:
                summary.append({"cellId": cell_id, "metric": metric, "n": len(vals), "mean": statistics.mean(vals), "median": statistics.median(vals), "sd": statistics.stdev(vals) if len(vals) > 1 else 0.0, "min": min(vals), "max": max(vals)})
    write_csv(out / "cell-descriptive-summary.csv", summary)
    pairs = [{"cellId": r["cellId"], "config": r["config"], "scenario": r["scenario"], "repetition": r["repetitionNumber"], "seed": r["randomSeed"], "runId": r["runId"]} for r in rows]
    write_csv(out / "paired-run-map.csv", pairs)


def audit() -> None:
    manifest_path = effective_manifest_path()
    manifest = read_json(manifest_path)
    ledger = read_json(RESULT_ROOT / "campaign-ledger.json")
    issues = []
    planned = {row["runId"] for row in manifest["executionOrder"]}
    complete = {row["runId"] for row in ledger if row["state"] == "COMPLETED"}
    if planned != complete:
        issues.append({"type": "ledger", "missing": sorted(planned - complete), "extra": sorted(complete - planned)})
    if sha256(manifest_path) != read_json(manifest_hash_path(manifest_path))["sha256"]:
        issues.append({"type": "manifest_hash"})
    for run_id in sorted(planned):
        run_dir = RESULT_ROOT / "runs" / run_id
        for name in ("config.json", "metadata.json", "summary.csv", "transactions.jsonl"):
            if not (run_dir / name).exists():
                issues.append({"type": "missing_artifact", "runId": run_id, "artifact": name})
        events = (run_dir / "events.jsonl").read_text(encoding="utf-8") if (run_dir / "events.jsonl").exists() else ""
        if "reconciliationWindowMs\": 2000" in (run_dir / "transactions.jsonl").read_text(encoding="utf-8", errors="ignore") if (run_dir / "transactions.jsonl").exists() else False:
            issues.append({"type": "runner_reconciliation", "runId": run_id})
        if "MECHANISM_EVENT_COLLECTION_FAILED" in events:
            issues.append({"type": "mechanism_event_collection_failed", "runId": run_id})
        if "-CRASH-" in run_id or run_id.startswith(f"{CAMPAIGN_ID}-P16") or run_id.startswith(f"{CAMPAIGN_ID}-P17") or run_id.startswith(f"{CAMPAIGN_ID}-P18"):
            cm = run_dir / "crash-metrics.json"
            if not cm.exists():
                issues.append({"type": "missing_crash_metrics", "runId": run_id})
            else:
                data = read_json(cm)
                if data.get("beforeInstance") == data.get("afterInstance"):
                    issues.append({"type": "crash_instance_not_distinct", "runId": run_id})
    write_json(RESULT_ROOT / "campaign-completeness-audit.json", {"status": "PASS" if not issues else "FAIL", "issues": issues, "checkedAt": utc_now(), "manifestPath": str(manifest_path), "manifestHash": sha256(manifest_path), "commit": sh(["git", "rev-parse", "HEAD"])})
    repro = RESULT_ROOT / "reproducibility"
    for name in ("campaign-ledger.json", "campaign-completeness-audit.json"):
        if (RESULT_ROOT / name).exists():
            shutil.copy2(RESULT_ROOT / name, repro / name)


def execution_order(cells):
    order = []
    groups = ["f8-concurrent-duplicate-transaction-requests", "f11-transient-payment-failure-recovery", "f5-payment-succeeds-response-lost", "f12-compensation-failure-retry", "f0-no-failure", "true-crash-after-order"]
    for scenario in groups:
        max_rep = max((c.repetitions for c in cells if c.scenario == scenario), default=0)
        for rep in range(1, max_rep + 1):
            for cell in cells:
                if cell.scenario == scenario and rep <= cell.repetitions:
                    seed = BASE_SEED + rep - 1
                    order.append({"runId": f"{CAMPAIGN_ID}-{cell.cell_id}-rep{rep:02d}", "cellId": cell.cell_id, "repetition": rep, "seed": seed})
    return order


def counts():
    ordinary = sum(c.repetitions for c in PRIMARY_CELLS if not c.crash)
    crash = sum(c.repetitions for c in PRIMARY_CELLS if c.crash)
    return {"primaryCells": len(PRIMARY_CELLS), "ordinaryPrimaryRuns": ordinary, "crashPrimaryRuns": crash, "totalPrimaryRuns": ordinary + crash}


def validate_counts(run_counts):
    if run_counts != {"primaryCells": 22, "ordinaryPrimaryRuns": 152, "crashPrimaryRuns": 30, "totalPrimaryRuns": 182}:
        raise RuntimeError(f"unexpected final primary run counts: {run_counts}")


def effective_manifest_path():
    amendment = RESULT_ROOT / "campaign-manifest-amendment-001.json"
    return amendment if amendment.exists() else RESULT_ROOT / "campaign-manifest.json"


def manifest_hash_path(manifest_path):
    if manifest_path.name == "campaign-manifest-amendment-001.json":
        return RESULT_ROOT / "campaign-manifest-amendment-001.sha256.json"
    return RESULT_ROOT / "campaign-manifest.sha256.json"


def run_config(cell, repetition, seed):
    scenario = FailureScenario.F0_NO_FAILURE if cell.crash else FailureScenario(cell.scenario)
    return V2RunConfiguration(cell.cell_id, CONFIGURATIONS[cell.config], scenario, cell.failure_rate, cell.concurrency, cell.transactions, repetition, seed, Backend.SERVICES, ExecutionMode.RESILIENT)


def cell_by_id(cell_id):
    return next(c for c in PRIMARY_CELLS if c.cell_id == cell_id)


def preserve_logs(controller, output_dir, suffix):
    paths = controller.preserve_logs(output_dir, suffix)
    return paths


def wait_crash_point(client, token):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            status = client.crash_point_status(token)
            if status.get("reached"):
                return status
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError("crash point was not reached")


def write_manifest_md(payload, digest):
    Path("docs/V2_FINAL_CAMPAIGN_MANIFEST.md").write_text(
        f"# V2.7 Final Campaign Manifest\n\nFrozen manifest: `results/v2/final/campaign-manifest.json`\n\nSHA-256: `{digest}`\n\nCode commit: `{payload['codeCommit']}`\n\nPrimary cells: {payload['runCounts']['primaryCells']}\n\nOrdinary primary runs: {payload['runCounts']['ordinaryPrimaryRuns']}\n\nCrash primary runs: {payload['runCounts']['crashPrimaryRuns']}\n\nTotal primary runs: {payload['runCounts']['totalPrimaryRuns']}\n\nSupplemental cells are declared but not executed in the primary campaign.\n",
        encoding="utf-8",
    )


def copy(src, dst):
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def save_ledger(rows_by_id):
    write_json(RESULT_ROOT / "campaign-ledger.json", list(rows_by_id.values()))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sh(command):
    import subprocess
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=10)
    return (completed.stdout + completed.stderr).strip()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()

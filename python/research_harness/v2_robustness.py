from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .runner import run_experiment
from .models import Backend, ExecutionMode, FailureScenario
from .service_backend import ServiceBackendConfig
from .v2_artifacts import V2RunConfiguration, V2RunStore, capture_run_metadata
from .v2_config import CONFIGURATIONS
from .v2_crash import DockerComposeCrashController


CAMPAIGN_ID = "v2_8r_failure_rate_robustness_20260830"
BASE_SEED = 2026083000
RESULT_ROOT = Path("results/v2/robustness")
PRIMARY_RUN_LEVEL = Path("results/v2/final/analysis-v2/run-level-primary-effective.csv")
PRIMARY_SUMMARY = Path("results/v2/analysis/primary-cell-summary.csv")
PRIMARY_PAIRED = Path("results/v2/analysis/paired-primary-effects.csv")
RESET_PROBE_TX = "reset-probe-tx"
RESET_PROBE_KEY = "reset-probe-key"

T_CRIT_95 = {
    1: 12.706204736,
    2: 4.302652730,
    3: 3.182446305,
    4: 2.776445105,
    5: 2.570581836,
    6: 2.446911851,
    7: 2.364624251,
}


@dataclass(frozen=True)
class Cell:
    cell_id: str
    family: str
    rate: float
    config: str
    scenario: str
    transactions: int
    concurrency: int
    repetitions: int
    comparator: str
    primary_metric: str


CELLS = (
    Cell("R01", "F11", 0.05, "C1", "f11-transient-payment-failure-recovery", 2000, 50, 8, "C3", "logicalTransactionSuccessRate"),
    Cell("R02", "F11", 0.05, "C3", "f11-transient-payment-failure-recovery", 2000, 50, 8, "C1", "logicalTransactionSuccessRate"),
    Cell("R03", "F11", 0.20, "C1", "f11-transient-payment-failure-recovery", 2000, 50, 8, "C3", "logicalTransactionSuccessRate"),
    Cell("R04", "F11", 0.20, "C3", "f11-transient-payment-failure-recovery", 2000, 50, 8, "C1", "logicalTransactionSuccessRate"),
    Cell("R05", "F5", 0.05, "C1", "f5-payment-succeeds-response-lost", 2000, 50, 8, "C5", "logicalTransactionSuccessRate"),
    Cell("R06", "F5", 0.05, "C5", "f5-payment-succeeds-response-lost", 2000, 50, 8, "C1", "logicalTransactionSuccessRate"),
    Cell("R07", "F5", 0.20, "C1", "f5-payment-succeeds-response-lost", 2000, 50, 8, "C5", "logicalTransactionSuccessRate"),
    Cell("R08", "F5", 0.20, "C5", "f5-payment-succeeds-response-lost", 2000, 50, 8, "C1", "logicalTransactionSuccessRate"),
    Cell("R09", "F12", 0.05, "C1", "f12-compensation-failure-retry", 2000, 50, 8, "C6", "invariantViolationRate"),
    Cell("R10", "F12", 0.05, "C6", "f12-compensation-failure-retry", 2000, 50, 8, "C1", "compensationRate"),
    Cell("R11", "F12", 0.20, "C1", "f12-compensation-failure-retry", 2000, 50, 8, "C6", "invariantViolationRate"),
    Cell("R12", "F12", 0.20, "C6", "f12-compensation-failure-retry", 2000, 50, 8, "C1", "compensationRate"),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["manifest", "run", "audit", "analyze"])
    args = parser.parse_args()
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    if args.command == "manifest":
        create_manifest()
    elif args.command == "run":
        run_campaign()
    elif args.command == "audit":
        audit()
    elif args.command == "analyze":
        analyze()


def create_manifest() -> None:
    path = RESULT_ROOT / "campaign-manifest.json"
    if path.exists():
        raise RuntimeError("robustness manifest already exists")
    run_counts = counts()
    if run_counts != {"cells": 12, "runsPerCell": 8, "effectiveRuns": 96}:
        raise RuntimeError(f"unexpected robustness run counts: {run_counts}")
    order = execution_order()
    payload = {
        "campaignId": CAMPAIGN_ID,
        "status": "FROZEN_ROBUSTNESS_CAMPAIGN_NOT_YET_EXECUTED",
        "createdAt": utc_now(),
        "codeCommit": sh(["git", "rev-parse", "HEAD"]),
        "branch": sh(["git", "branch", "--show-current"]),
        "dirtyState": bool(sh(["git", "status", "--porcelain"])),
        "dirtyStatus": sh(["git", "status", "--porcelain"]),
        "baseSeed": BASE_SEED,
        "seedPolicy": "seed = baseSeed + repetitionIndex - 1; same repetition index pairs comparator configs within each family/rate",
        "seeds": [{"repetition": i, "seed": BASE_SEED + i - 1} for i in range(1, 9)],
        "cells": [cell.__dict__ for cell in CELLS],
        "executionOrder": order,
        "runCounts": run_counts,
        "primaryReferenceCommit": "0ce3d8ad223a123ffeac7c8b457e60324d1db3f3",
        "primaryReferenceFiles": {
            "runLevel": str(PRIMARY_RUN_LEVEL),
            "summary": str(PRIMARY_SUMMARY),
            "paired": str(PRIMARY_PAIRED),
        },
        "environment": capture_run_metadata(
            "robustness-manifest",
            V2RunConfiguration("manifest", CONFIGURATIONS["C1"], FailureScenario.F0_NO_FAILURE, 0.0, 1, 1, 1, BASE_SEED, Backend.SERVICES),
        ),
        "failedRunPolicy": "preserve all runs; scientific outcomes are not rerun; infrastructure/config/environment failures may be replaced with new run IDs using the same frozen slot and seed",
    }
    write_json(path, payload)
    digest = sha256(path)
    write_json(RESULT_ROOT / "campaign-manifest.sha256.json", {"path": str(path), "sha256": digest})
    write_json(
        RESULT_ROOT / "campaign-ledger.json",
        [
            {
                "slotId": item["slotId"],
                "runId": item["runId"],
                "cellId": item["cellId"],
                "family": item["family"],
                "rate": item["rate"],
                "config": item["config"],
                "repetition": item["repetition"],
                "seed": item["seed"],
                "state": "PLANNED",
                "analysisStatus": "PLANNED",
                "replacementFor": None,
                "replacementRunId": None,
            }
            for item in order
        ],
    )


def run_campaign() -> None:
    manifest_path = RESULT_ROOT / "campaign-manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("robustness manifest missing")
    manifest = read_json(manifest_path)
    if manifest["dirtyState"] or manifest["codeCommit"] != sh(["git", "rev-parse", "HEAD"]) or sh(["git", "status", "--porcelain"]):
        raise RuntimeError("robustness campaign requires clean working tree at frozen commit")
    if sha256(manifest_path) != read_json(RESULT_ROOT / "campaign-manifest.sha256.json")["sha256"]:
        raise RuntimeError("robustness manifest hash mismatch")
    controller = DockerComposeCrashController()
    controller.start()
    service_config = ServiceBackendConfig(
        orchestrator_url="http://localhost:18080",
        cart_url="http://localhost:18081",
        order_url="http://localhost:18082",
        payment_url="http://localhost:18083",
        timeout_seconds=3.0,
    )
    store = V2RunStore(RESULT_ROOT)
    ledger = {row["slotId"]: row for row in read_json(RESULT_ROOT / "campaign-ledger.json")}
    for item in manifest["executionOrder"]:
        slot = ledger[item["slotId"]]
        if slot["state"] == "COMPLETED":
            continue
        slot["state"] = "RUNNING"
        save_ledger(ledger)
        cell = cell_by_id(item["cellId"])
        run_id = item["runId"]
        try:
            if cell.config == "C5" and CONFIGURATIONS["C5"].runner_reconciliation_enabled:
                raise RuntimeError("runner reconciliation unexpectedly enabled for C5")
            run_one(store, controller, service_config, cell, item["repetition"], item["seed"], run_id)
            slot["state"] = "COMPLETED"
            slot["analysisStatus"] = "EFFECTIVE"
        except Exception as exc:
            slot["state"] = "FAILED_INFRASTRUCTURE"
            slot["analysisStatus"] = "FAILED_INFRASTRUCTURE"
            slot["failure"] = str(exc)
            save_ledger(ledger)
            raise
        save_ledger(ledger)


def run_one(store, controller, service_config, cell, repetition, seed, run_id) -> None:
    context = store.create_run(run_config(cell, repetition, seed), run_id)
    controller.reset_database()
    reset_probe = assert_reset_integrity(service_config)
    context.write_json("reset-integrity.json", reset_probe, overwrite=False)
    runs = run_experiment(
        ExecutionMode.RESILIENT,
        FailureScenario(cell.scenario),
        cell.transactions,
        cell.concurrency,
        cell.rate,
        1,
        context.run_dir / "runner",
        random_seed=BASE_SEED,
        backend=Backend.SERVICES,
        service_config=service_config,
        repetition_start=repetition,
        v2_configuration=CONFIGURATIONS[cell.config],
        v2_event_writer=context.event_writer,
        v2_run_id=run_id,
    )
    copy(runs[0].raw_path, context.run_dir / "transactions.jsonl")
    copy(runs[0].summary_path, context.run_dir / "summary.csv")
    controller.preserve_logs(context.run_dir / "logs", "run-end")
    write_json(
        context.run_dir / "run-classification.json",
        {
            "classification": "COMPLETED",
            "analysisClass": "robustness",
            "family": cell.family,
            "failureRate": cell.rate,
        },
    )


def assert_reset_integrity(service_config: ServiceBackendConfig) -> dict[str, object]:
    payment_url = f"{service_config.payment_url}/payments"
    payload = json.dumps(
        {
            "transactionId": RESET_PROBE_TX,
            "idempotencyKey": RESET_PROBE_KEY,
            "orderId": f"order-{RESET_PROBE_TX}",
            "amount": 19.99,
            "currency": "USD",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        payment_url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Failure-Scenario": "f11-transient-payment-failure-recovery",
            "X-Failure-Rate": "1.0",
            "X-Random-Seed": "1",
        },
    )
    first_status = None
    first_reason = None
    try:
        urllib.request.urlopen(request, timeout=service_config.timeout_seconds)
        first_status = 201
    except urllib.error.HTTPError as exc:
        first_status = exc.code
        first_reason = exc.reason
    if first_status != 503:
        raise RuntimeError(f"reset-integrity failure: expected initial F11 probe 503, got {first_status}")
    inspect_url = f"{service_config.payment_url}/inspect/idempotency/{RESET_PROBE_KEY}"
    with urllib.request.urlopen(inspect_url, timeout=service_config.timeout_seconds) as response:
        inspect = json.loads(response.read().decode("utf-8"))
    if int(inspect.get("successfulPaymentCount", -1)) != 0:
        raise RuntimeError(f"reset-integrity failure: expected zero probe payments, got {inspect}")
    return {
        "probeTransactionId": RESET_PROBE_TX,
        "probeIdempotencyKey": RESET_PROBE_KEY,
        "expectedHttpStatus": 503,
        "actualHttpStatus": first_status,
        "actualReason": first_reason,
        "successfulPaymentCount": int(inspect.get("successfulPaymentCount", -1)),
        "status": "PASS",
    }


def audit() -> None:
    manifest = read_json(RESULT_ROOT / "campaign-manifest.json")
    ledger = read_json(RESULT_ROOT / "campaign-ledger.json")
    issues = []
    if sha256(RESULT_ROOT / "campaign-manifest.json") != read_json(RESULT_ROOT / "campaign-manifest.sha256.json")["sha256"]:
        issues.append({"type": "manifest_hash"})
    if len(manifest["cells"]) != 12:
        issues.append({"type": "cell_count", "actual": len(manifest["cells"])})
    expected_slots = {(row["cellId"], row["repetition"]) for row in manifest["executionOrder"]}
    completed = [row for row in ledger if row["state"] == "COMPLETED"]
    completed_slots = {(row["cellId"], row["repetition"]) for row in completed}
    if expected_slots != completed_slots:
        issues.append({"type": "ledger_slots", "missing": sorted(expected_slots - completed_slots), "extra": sorted(completed_slots - expected_slots)})
    if len(completed) != 96:
        issues.append({"type": "completed_run_count", "actual": len(completed)})
    run_rows = []
    for row in completed:
        run_dir = RESULT_ROOT / "runs" / row["runId"]
        required = ["config.json", "metadata.json", "events.jsonl", "transactions.jsonl", "summary.csv", "run-classification.json", "reset-integrity.json"]
        for name in required:
            if not (run_dir / name).exists():
                issues.append({"type": "missing_artifact", "runId": row["runId"], "artifact": name})
        if (run_dir / "summary.csv").exists():
            summary = next(csv.DictReader((run_dir / "summary.csv").open(encoding="utf-8")))
            run_rows.append({**row, **summary})
            if int(summary["randomSeed"]) != row["seed"]:
                issues.append({"type": "seed_mismatch", "runId": row["runId"], "expected": row["seed"], "actual": int(summary["randomSeed"])})
        if (run_dir / "reset-integrity.json").exists():
            reset_payload = read_json(run_dir / "reset-integrity.json")
            if reset_payload.get("status") != "PASS":
                issues.append({"type": "reset_integrity", "runId": row["runId"], "payload": reset_payload})
        raw = (run_dir / "transactions.jsonl").read_text(encoding="utf-8", errors="ignore") if (run_dir / "transactions.jsonl").exists() else ""
        if "reconciliationWindowMs\": 2000" in raw:
            issues.append({"type": "runner_reconciliation", "runId": row["runId"]})
        events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()] if (run_dir / "events.jsonl").exists() else []
        event_types = {event.get("event_type") for event in events}
        if "MECHANISM_EVENT_COLLECTION_FAILED" in event_types:
            issues.append({"type": "mechanism_event_collection_failed", "runId": row["runId"]})
        if row["family"] == "F11" and "RETRY_ATTEMPT" not in event_types and float(row["actualInjectedFailureRate"]) > 0.0:
            issues.append({"type": "missing_retry_activation", "runId": row["runId"]})
        if row["family"] == "F5" and row["config"] == "C5" and "RECONCILIATION_STARTED" not in event_types and float(row["actualInjectedFailureRate"]) > 0.0:
            issues.append({"type": "missing_reconciliation_activation", "runId": row["runId"]})
        if row["family"] == "F12" and row["config"] == "C6" and "COMPENSATION_STARTED" not in event_types and float(row["actualInjectedFailureRate"]) > 0.0:
            issues.append({"type": "missing_compensation_activation", "runId": row["runId"]})
    write_json(
        RESULT_ROOT / "robustness-completeness-audit.json",
        {
            "status": "PASS" if not issues else "FAIL",
            "issues": issues,
            "checkedAt": utc_now(),
            "effectiveRuns": len(completed),
            "cells": len(manifest["cells"]),
        },
    )


def analyze() -> None:
    audit_payload = read_json(RESULT_ROOT / "robustness-completeness-audit.json")
    if audit_payload["status"] != "PASS":
        raise RuntimeError("robustness completeness audit must PASS before analysis")
    rows = []
    ledger = [row for row in read_json(RESULT_ROOT / "campaign-ledger.json") if row["state"] == "COMPLETED"]
    for row in ledger:
        run_dir = RESULT_ROOT / "runs" / row["runId"]
        summary = next(csv.DictReader((run_dir / "summary.csv").open(encoding="utf-8")))
        rows.append({
            "runId": row["runId"],
            "cellId": row["cellId"],
            "family": row["family"],
            "failureRate": row["rate"],
            "config": row["config"],
            "repetition": row["repetition"],
            "seed": row["seed"],
            **summary,
        })
    write_csv(RESULT_ROOT / "robustness-run-level.csv", rows)
    cell_summary = build_cell_summary(rows)
    write_csv(RESULT_ROOT / "robustness-cell-summary.csv", cell_summary)
    paired_effects = build_paired_effects(rows)
    write_csv(RESULT_ROOT / "robustness-paired-effects.csv", paired_effects)
    rate_response = build_rate_response(rows, paired_effects)
    write_csv(RESULT_ROOT / "robustness-rate-response.csv", rate_response)
    mech_summary = build_mechanism_summary(ledger)
    write_csv(RESULT_ROOT / "mechanism-rate-summary.csv", mech_summary)
    consistency = build_consistency_audit(rows, paired_effects)
    write_json(RESULT_ROOT / "robustness-consistency-audit.json", consistency)
    write_markdown(rows, paired_effects, rate_response, mech_summary, consistency)


def build_cell_summary(rows):
    metric_names = [
        "logicalTransactionSuccessRate",
        "invariantViolationRate",
        "compensationRate",
        "duplicateOrderRate",
        "duplicatePaymentRate",
        "retryCount",
        "operationRetryCount",
        "compensationRetryCount",
        "actualInjectedFailureCount",
        "actualInjectedFailureRate",
        "p95LatencyMs",
        "throughputTransactionsPerSecond",
    ]
    grouped = {}
    for row in rows:
        grouped.setdefault((row["cellId"], row["family"], row["failureRate"], row["config"]), []).append(row)
    out = []
    for (cell_id, family, rate, config), group in sorted(grouped.items()):
        record = {
            "cellId": cell_id,
            "family": family,
            "failureRate": rate,
            "config": config,
            "nRuns": len(group),
            "transactionsPerRun": int(group[0]["transactionCount"]),
            "concurrency": int(group[0]["concurrency"]),
        }
        for metric in metric_names:
            values = [float(item[metric]) for item in group]
            record[f"{metric}Mean"] = round(statistics.mean(values), 6)
            record[f"{metric}Sd"] = round(statistics.stdev(values), 6) if len(values) > 1 else 0.0
        out.append(record)
    return out


def build_paired_effects(rows):
    comparisons = [
        ("F11", 0.05, "C1", "C3", "logicalTransactionSuccessRate", "retry robustness"),
        ("F11", 0.20, "C1", "C3", "logicalTransactionSuccessRate", "retry robustness"),
        ("F5", 0.05, "C1", "C5", "logicalTransactionSuccessRate", "reconciliation robustness"),
        ("F5", 0.20, "C1", "C5", "logicalTransactionSuccessRate", "reconciliation robustness"),
        ("F12", 0.05, "C1", "C6", "invariantViolationRate", "compensation robustness"),
        ("F12", 0.20, "C1", "C6", "invariantViolationRate", "compensation robustness"),
        ("F12", 0.05, "C1", "C6", "compensationRate", "compensation robustness"),
        ("F12", 0.20, "C1", "C6", "compensationRate", "compensation robustness"),
    ]
    index = {(row["family"], float(row["failureRate"]), row["config"], int(row["repetition"])): row for row in rows}
    out = []
    for family, rate, base, protected, metric, label in comparisons:
        pairs = []
        for rep in range(1, 9):
            a = index[(family, rate, base, rep)]
            b = index[(family, rate, protected, rep)]
            pairs.append((float(a[metric]), float(b[metric]), int(a["seed"])))
        a_values = [a for a, _, _ in pairs]
        b_values = [b for _, b, _ in pairs]
        diffs = [b - a for a, b, _ in pairs]
        ci_low, ci_high = paired_ci(diffs)
        out.append({
            "family": family,
            "failureRate": rate,
            "baselineConfig": base,
            "protectedConfig": protected,
            "metric": metric,
            "nPairs": len(pairs),
            "meanBaseline": round(statistics.mean(a_values), 6),
            "sdBaseline": round(statistics.stdev(a_values), 6),
            "meanProtected": round(statistics.mean(b_values), 6),
            "sdProtected": round(statistics.stdev(b_values), 6),
            "meanPairedDifference": round(statistics.mean(diffs), 6),
            "sdPairedDifference": round(statistics.stdev(diffs), 6) if len(diffs) > 1 else 0.0,
            "ci95Low": round(ci_low, 6),
            "ci95High": round(ci_high, 6),
            "effectSizeDz": round(effect_size_dz(diffs), 6) if effect_size_dz(diffs) is not None else "",
            "pairedSeeds": ",".join(str(seed) for _, _, seed in pairs),
            "interpretationLabel": label,
        })
    return out


def build_rate_response(rows, paired_effects):
    primary_rows = list(csv.DictReader(PRIMARY_RUN_LEVEL.open(encoding="utf-8")))
    primary_index = {(row["cellId"], row["config"]): row for row in primary_rows}
    paired_index = {(row["family"], float(row["failureRate"]), row["metric"]): row for row in paired_effects}
    mapping = {
        "F11": ("P05", "P06", "logicalTransactionSuccessRate"),
        "F5": ("P08", "P11", "logicalTransactionSuccessRate"),
        "F12-invariant": ("P13", "P14", "invariantViolationRate"),
        "F12-compensation": ("P13", "P14", "compensationRate"),
    }
    out = []
    for family, rate, base, protected, metric, activity_metric in [
        ("F11", 0.05, "C1", "C3", "logicalTransactionSuccessRate", "retryCount"),
        ("F11", 0.10, "C1", "C3", "logicalTransactionSuccessRate", "retryCount"),
        ("F11", 0.20, "C1", "C3", "logicalTransactionSuccessRate", "retryCount"),
        ("F5", 0.05, "C1", "C5", "logicalTransactionSuccessRate", "reconciliationStarted"),
        ("F5", 0.10, "C1", "C5", "logicalTransactionSuccessRate", "reconciliationStarted"),
        ("F5", 0.20, "C1", "C5", "logicalTransactionSuccessRate", "reconciliationStarted"),
        ("F12", 0.05, "C1", "C6", "invariantViolationRate", "compensationStarted"),
        ("F12", 0.10, "C1", "C6", "invariantViolationRate", "compensationStarted"),
        ("F12", 0.20, "C1", "C6", "invariantViolationRate", "compensationStarted"),
        ("F12", 0.05, "C1", "C6", "compensationRate", "compensationStarted"),
        ("F12", 0.10, "C1", "C6", "compensationRate", "compensationStarted"),
        ("F12", 0.20, "C1", "C6", "compensationRate", "compensationStarted"),
    ]:
        if rate == 0.10:
            if family == "F11":
                base_row = primary_index[("P05", "C1")]
                protected_row = primary_index[("P06", "C3")]
                paired = find_primary_paired("P06_vs_P05")
            elif family == "F5":
                base_row = primary_index[("P08", "C1")]
                protected_row = primary_index[("P11", "C5")]
                paired = find_primary_paired("P11_vs_P08")
            elif metric == "invariantViolationRate":
                base_row = primary_index[("P13", "C1")]
                protected_row = primary_index[("P14", "C6")]
                paired = find_primary_paired("P13_vs_P14")
            else:
                base_row = primary_index[("P13", "C1")]
                protected_row = primary_index[("P14", "C6")]
                paired = find_primary_paired("P14_vs_P13")
            mechanism = mechanism_rate_row_from_primary(family, activity_metric)
            out.append({
                "mechanismFamily": family,
                "failureRate": rate,
                "source": "primary-10pct-reference",
                "baselineConfig": base,
                "protectedConfig": protected,
                "metric": metric,
                "baselineMean": round(float(base_row[metric]), 6),
                "protectedMean": round(float(protected_row[metric]), 6),
                "absoluteEffect": round(float(paired["meanPairedDiff"]), 6),
                "ci95": paired["CI95"],
                "mechanismActivityMean": mechanism,
                "baselineP95LatencyMs": round(float(base_row["p95LatencyMs"]), 6),
                "protectedP95LatencyMs": round(float(protected_row["p95LatencyMs"]), 6),
                "baselineThroughput": round(float(base_row["throughputTransactionsPerSecond"]), 6),
                "protectedThroughput": round(float(protected_row["throughputTransactionsPerSecond"]), 6),
            })
            continue
        paired = paired_index[(family, rate, metric)]
        base_row = mean_row(rows, family, rate, base)
        protected_row = mean_row(rows, family, rate, protected)
        mechanism = mechanism_rate_row_from_robustness(family, rate, activity_metric)
        out.append({
            "mechanismFamily": family,
            "failureRate": rate,
            "source": "robustness",
            "baselineConfig": base,
            "protectedConfig": protected,
            "metric": metric,
            "baselineMean": round(base_row[metric], 6),
            "protectedMean": round(protected_row[metric], 6),
            "absoluteEffect": paired["meanPairedDifference"],
            "ci95": f"[{paired['ci95Low']:.6f}, {paired['ci95High']:.6f}]",
            "mechanismActivityMean": mechanism,
            "baselineP95LatencyMs": round(base_row["p95LatencyMs"], 6),
            "protectedP95LatencyMs": round(protected_row["p95LatencyMs"], 6),
            "baselineThroughput": round(base_row["throughputTransactionsPerSecond"], 6),
            "protectedThroughput": round(protected_row["throughputTransactionsPerSecond"], 6),
        })
    return out


def build_mechanism_summary(ledger):
    out = []
    for row in ledger:
        events = [json.loads(line) for line in (RESULT_ROOT / "runs" / row["runId"] / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        counts = {}
        for event in events:
            counts[event["event_type"]] = counts.get(event["event_type"], 0) + 1
        out.append({
            "runId": row["runId"],
            "cellId": row["cellId"],
            "family": row["family"],
            "failureRate": row["rate"],
            "config": row["config"],
            "repetition": row["repetition"],
            "lookupAttempts": counts.get("IDEMPOTENT_LOOKUP_ATTEMPT", 0),
            "lookupFound": counts.get("IDEMPOTENT_LOOKUP_FOUND", 0),
            "lookupNotFound": counts.get("IDEMPOTENT_LOOKUP_NOT_FOUND", 0),
            "retryAttempts": counts.get("RETRY_ATTEMPT", 0),
            "retrySucceeded": counts.get("RETRY_SUCCEEDED", 0),
            "retryExhausted": counts.get("RETRY_EXHAUSTED", 0),
            "reconciliationStarted": counts.get("RECONCILIATION_STARTED", 0),
            "reconciliationSucceeded": counts.get("RECONCILIATION_SUCCEEDED", 0),
            "reconciliationNotFound": counts.get("RECONCILIATION_NOT_FOUND", 0),
            "compensationStarted": counts.get("COMPENSATION_STARTED", 0),
            "compensationRetry": counts.get("COMPENSATION_RETRY", 0),
            "compensationSucceeded": counts.get("COMPENSATION_SUCCEEDED", 0),
            "compensationFailed": counts.get("COMPENSATION_FAILED", 0),
            "runnerReconciliation": 1 if any("reconciliationWindowMs" in line for line in (RESULT_ROOT / "runs" / row["runId"] / "transactions.jsonl").read_text(encoding="utf-8").splitlines()) else 0,
        })
    return out


def build_consistency_audit(rows, paired_effects):
    issues = []
    if len(rows) != 96:
        issues.append({"type": "run_count", "actual": len(rows)})
    if len({row["cellId"] for row in rows}) != 12:
        issues.append({"type": "cell_count", "actual": len({row['cellId'] for row in rows})})
    if any(int(row["randomSeed"]) != int(row["seed"]) for row in rows):
        issues.append({"type": "seed_mismatch"})
    by_slot = {}
    for row in rows:
        key = (row["cellId"], int(row["repetition"]))
        by_slot[key] = by_slot.get(key, 0) + 1
    duplicates = [key for key, count in by_slot.items() if count != 1]
    if duplicates:
        issues.append({"type": "slot_multiplicity", "slots": duplicates})
    mech = list(csv.DictReader((RESULT_ROOT / "mechanism-rate-summary.csv").open(encoding="utf-8")))
    if any(int(row["runnerReconciliation"]) != 0 for row in mech if row["config"] == "C5"):
        issues.append({"type": "runner_reconciliation"})
    return {
        "status": "PASS" if not issues else "FAIL",
        "checkedAt": utc_now(),
        "effectiveRuns": len(rows),
        "cells": len({row["cellId"] for row in rows}),
        "issues": issues,
    }


def write_markdown(rows, paired_effects, rate_response, mech_summary, consistency):
    family_status = robustness_classification(rate_response)
    path = RESULT_ROOT / "robustness-analysis.md"
    lines = [
        "# V2.8R Failure-Rate Robustness",
        "",
        f"Code commit: `{sh(['git', 'rev-parse', 'HEAD'])}`",
        f"Manifest hash: `{read_json(RESULT_ROOT / 'campaign-manifest.sha256.json')['sha256']}`",
        f"Consistency audit: `{consistency['status']}`",
        "",
        "## Classification",
        "",
    ]
    for family, status in family_status.items():
        lines.append(f"- {family}: {status}")
    lines.extend([
        "",
        "## Rate Response",
        "",
        "| family | rate | metric | baseline | protected | effect | CI95 | baseline P95 | protected P95 | baseline tps | protected tps |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in rate_response:
        lines.append(
            f"| {row['mechanismFamily']} | {row['failureRate']:.2f} | {row['metric']} | {row['baselineMean']:.6f} | {row['protectedMean']:.6f} | {row['absoluteEffect']} | {row['ci95']} | {row['baselineP95LatencyMs']:.3f} | {row['protectedP95LatencyMs']:.3f} | {row['baselineThroughput']:.3f} | {row['protectedThroughput']:.3f} |"
        )
    lines.extend([
        "",
        "## Paired Effects",
        "",
        "| family | rate | metric | mean delta | CI95 | dz |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for row in paired_effects:
        lines.append(
            f"| {row['family']} | {float(row['failureRate']):.2f} | {row['metric']} | {row['meanPairedDifference']:.6f} | [{row['ci95Low']:.6f}, {row['ci95High']:.6f}] | {row['effectSizeDz']} |"
        )
    lines.extend([
        "",
        "## Mechanism Activity",
        "",
        "| family | rate | config | retry attempts | reconciliation started | compensation started | runner reconciliation |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in summarize_mechanism_activity(mech_summary):
        lines.append(
            f"| {row['family']} | {row['failureRate']:.2f} | {row['config']} | {row['retryAttemptsMean']:.2f} | {row['reconciliationStartedMean']:.2f} | {row['compensationStartedMean']:.2f} | {row['runnerReconciliationSum']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize_mechanism_activity(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault((row["family"], float(row["failureRate"]), row["config"]), []).append(row)
    out = []
    for (family, rate, config), group in sorted(grouped.items()):
        out.append({
            "family": family,
            "failureRate": rate,
            "config": config,
            "retryAttemptsMean": statistics.mean(int(item["retryAttempts"]) for item in group),
            "reconciliationStartedMean": statistics.mean(int(item["reconciliationStarted"]) for item in group),
            "compensationStartedMean": statistics.mean(int(item["compensationStarted"]) for item in group),
            "runnerReconciliationSum": sum(int(item["runnerReconciliation"]) for item in group),
        })
    return out


def robustness_classification(rate_response):
    families = {}
    for family in {"F11", "F5", "F12"}:
        rows = [row for row in rate_response if row["mechanismFamily"] == family and row["failureRate"] in {0.05, 0.10, 0.20} and row["metric"] in {"logicalTransactionSuccessRate", "invariantViolationRate"}]
        effects = [float(row["absoluteEffect"]) for row in rows]
        if not effects:
            families[family] = "INCONCLUSIVE"
            continue
        if family in {"F11", "F5"}:
            positive = all(effect > 0 for effect in effects)
        else:
            positive = all(effect < 0 for effect in effects)
        if positive and max(abs(effect) for effect in effects) - min(abs(effect) for effect in effects) < 0.2:
            families[family] = "CONSISTENT ACROSS TESTED RATES"
        elif positive:
            families[family] = "QUALITATIVELY CONSISTENT WITH MAGNITUDE CHANGE"
        else:
            families[family] = "RATE-SENSITIVE"
    return families


def mean_row(rows, family, rate, config):
    selected = [row for row in rows if row["family"] == family and float(row["failureRate"]) == rate and row["config"] == config]
    return {
        "logicalTransactionSuccessRate": statistics.mean(float(row["logicalTransactionSuccessRate"]) for row in selected),
        "invariantViolationRate": statistics.mean(float(row["invariantViolationRate"]) for row in selected),
        "compensationRate": statistics.mean(float(row["compensationRate"]) for row in selected),
        "p95LatencyMs": statistics.mean(float(row["p95LatencyMs"]) for row in selected),
        "throughputTransactionsPerSecond": statistics.mean(float(row["throughputTransactionsPerSecond"]) for row in selected),
    }


def find_primary_paired(comparison_id):
    for row in csv.DictReader(PRIMARY_PAIRED.open(encoding="utf-8")):
        if row["comparisonId"] == comparison_id:
            return row
    raise KeyError(comparison_id)


def mechanism_rate_row_from_primary(family, metric):
    mapping = {
        ("F11", "retryCount"): ("P06", "retryCountMean"),
        ("F5", "reconciliationStarted"): ("P11", None),
        ("F12", "compensationStarted"): ("P14", None),
    }
    if family == "F11":
        row = next(row for row in csv.DictReader(PRIMARY_RUN_LEVEL.open(encoding="utf-8")) if row["cellId"] == "P06")
        return round(float(row["retryCount"]), 6)
    cell_id = "P11" if family == "F5" else "P14"
    mech = list(csv.DictReader(Path("results/v2/analysis/mechanism-activation-summary.csv").open(encoding="utf-8")))
    field = "reconciliationStarted" if family == "F5" else "compensationStarted"
    values = [int(row[field]) for row in mech if row["cellId"] == cell_id]
    return round(statistics.mean(values), 6)


def mechanism_rate_row_from_robustness(family, rate, metric):
    rows = list(csv.DictReader((RESULT_ROOT / "mechanism-rate-summary.csv").open(encoding="utf-8")))
    if family == "F11":
        values = [int(row["retryAttempts"]) for row in rows if row["family"] == family and float(row["failureRate"]) == rate and row["config"] == "C3"]
    elif family == "F5":
        values = [int(row["reconciliationStarted"]) for row in rows if row["family"] == family and float(row["failureRate"]) == rate and row["config"] == "C5"]
    else:
        values = [int(row["compensationStarted"]) for row in rows if row["family"] == family and float(row["failureRate"]) == rate and row["config"] == "C6"]
    return round(statistics.mean(values), 6)


def paired_ci(diffs):
    if len(diffs) < 2:
        mean = diffs[0] if diffs else 0.0
        return mean, mean
    mean = statistics.mean(diffs)
    sd = statistics.stdev(diffs)
    half = T_CRIT_95[len(diffs) - 1] * (sd / (len(diffs) ** 0.5))
    return mean - half, mean + half


def effect_size_dz(diffs):
    if len(diffs) < 2:
        return None
    sd = statistics.stdev(diffs)
    if sd == 0:
        return None
    return statistics.mean(diffs) / sd


def counts():
    return {"cells": len(CELLS), "runsPerCell": 8, "effectiveRuns": len(CELLS) * 8}


def execution_order():
    order = []
    for family in ("F11", "F5", "F12"):
        for rate in (0.05, 0.20):
            cells = [cell for cell in CELLS if cell.family == family and cell.rate == rate]
            for repetition in range(1, 9):
                for cell in cells:
                    seed = BASE_SEED + repetition - 1
                    order.append(
                        {
                            "slotId": f"{cell.cell_id}-rep{repetition:02d}",
                            "runId": f"{CAMPAIGN_ID}-{cell.cell_id}-rep{repetition:02d}",
                            "cellId": cell.cell_id,
                            "family": family,
                            "rate": rate,
                            "config": cell.config,
                            "repetition": repetition,
                            "seed": seed,
                        }
                    )
    return order


def cell_by_id(cell_id):
    return next(cell for cell in CELLS if cell.cell_id == cell_id)


def run_config(cell, repetition, seed):
    return V2RunConfiguration(cell.cell_id, CONFIGURATIONS[cell.config], FailureScenario(cell.scenario), cell.rate, cell.concurrency, cell.transactions, repetition, seed, Backend.SERVICES, ExecutionMode.RESILIENT)


def save_ledger(rows_by_slot):
    write_json(RESULT_ROOT / "campaign-ledger.json", list(rows_by_slot.values()))


def copy(src, dst):
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_csv(path, rows):
    path = Path(path)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
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

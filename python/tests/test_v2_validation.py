from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from research_harness.failures import FailureConfig, FailureInjector, InjectedFailure
from research_harness.metrics import write_summary
from research_harness.models import Backend, ExecutionMode, ExperimentResult, FailureScenario, PaymentStatus, TransactionRecord, TransactionState
from research_harness.runner import build_request, run_experiment
from research_harness.services import CommerceServices
from research_harness.v2_artifacts import ArtifactError, V2RunConfiguration, V2RunStore
from research_harness.v2_config import CONFIGURATIONS
from research_harness.v2_events import EventRecord, EventType, EventWriter
from research_harness.v2_invariants import evaluate_v2_invariants


class V2ValidationTests(unittest.TestCase):
    def test_known_value_summary_metrics_distinguish_attempt_and_logical_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = [
                self._result("logical-key-1", "COMPLETED", latency_ms=10, operation_retries=1),
                self._result("logical-key-1", "FAILED", latency_ms=20, duplicate_payment=True),
                self._result("logical-key-2", "COMPENSATED", latency_ms=30, compensated=True, compensation_retries=1),
            ]

            summary_path = write_summary(results, Path(tmp))
            with summary_path.open(encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))

            self.assertEqual("3", row["attemptCount"])
            self.assertEqual("2", row["logicalTransactionCount"])
            self.assertEqual("0.3333333333333333", row["attemptSuccessRate"])
            self.assertEqual("0.5", row["logicalTransactionSuccessRate"])
            self.assertEqual("1", row["duplicatePaymentCount"])
            self.assertEqual("1", row["compensatedTransactions"])
            self.assertEqual("2", row["totalRetryCount"])
            self.assertEqual("20", row["p50Latency"])
            self.assertEqual("30", row["p95Latency"])
            self.assertEqual("30", row["p99Latency"])

    def test_v2_invariants_group_c0_duplicate_effects_by_logical_key(self):
        services = CommerceServices(FailureInjector(FailureConfig()))
        request = build_request(1, "logical-key-1")
        services.create_cart(request, "tx-c0-1")
        services.create_order("cart-tx-c0-1", request, "tx-c0-1")
        services.execute_payment("order-tx-c0-1", request, "tx-c0-1")
        services.create_cart(request, "tx-c0-2")
        services.create_order("cart-tx-c0-2", request, "tx-c0-2")
        services.execute_payment("order-tx-c0-2", request, "tx-c0-2")

        report = evaluate_v2_invariants(
            TransactionRecord("tx-c0-1", "logical-key-1", TransactionState.COMPLETED, order_id="order-tx-c0-1", payment_id="payment-tx-c0-1"),
            services,
            "logical-key-1",
        )

        self.assertIn("I1_AT_MOST_ONE_SUCCESSFUL_PAYMENT", report.violation_types)
        self.assertIn("I3_AT_MOST_ONE_ORDER", report.violation_types)

    def test_failure_semantics_events_are_representable_from_actual_conditions(self):
        events = [
            EventRecord(
                run_id="validation",
                component="payment-simulator",
                event_type=EventType.FAILURE_INJECTED,
                scenario=FailureScenario.F11_TRANSIENT_PAYMENT_FAILURE_RECOVERY.value,
                operation="execute_payment",
                side_effect_status="not_created",
                failure_type="TRANSIENT_PAYMENT_FAILURE_BEFORE_SIDE_EFFECT",
            ),
            EventRecord(
                run_id="validation",
                component="payment-simulator",
                event_type=EventType.FAILURE_INJECTED,
                scenario=FailureScenario.F5_PAYMENT_SUCCEEDS_RESPONSE_LOST.value,
                operation="execute_payment",
                side_effect_status="created_response_lost",
                failure_type="PAYMENT_RESPONSE_LOST_AFTER_SIDE_EFFECT",
            ),
            EventRecord(
                run_id="validation",
                component="crash_controller",
                event_type=EventType.ORCHESTRATOR_PROCESS_EXITED,
                scenario="true-crash-after-order",
                state_before=TransactionState.ORDER_CREATED.value,
                side_effect_status="order_created_payment_not_started",
            ),
        ]

        self.assertEqual("not_created", events[0].side_effect_status)
        self.assertEqual("created_response_lost", events[1].side_effect_status)
        self.assertEqual(TransactionState.ORDER_CREATED.value, events[2].state_before)

    def test_paired_seed_schedule_is_independent_of_v2_identity_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            c0_runs = run_experiment(
                ExecutionMode.BASELINE,
                FailureScenario.F8_CONCURRENT_DUPLICATE_TRANSACTION_REQUESTS,
                transactions=2,
                concurrency=1,
                failure_rate=1.0,
                repetitions=2,
                output_root=Path(tmp) / "c0",
                random_seed=900,
                backend=Backend.SIMULATION,
                v2_configuration=CONFIGURATIONS["C0"],
            )
            c1_runs = run_experiment(
                ExecutionMode.BASELINE,
                FailureScenario.F8_CONCURRENT_DUPLICATE_TRANSACTION_REQUESTS,
                transactions=2,
                concurrency=1,
                failure_rate=1.0,
                repetitions=2,
                output_root=Path(tmp) / "c1",
                random_seed=900,
                backend=Backend.SIMULATION,
                v2_configuration=CONFIGURATIONS["C1"],
            )

            self.assertEqual(self._summary_seeds(c0_runs), self._summary_seeds(c1_runs))
            self.assertEqual(["900", "901"], self._summary_seeds(c0_runs))

    def test_artifact_validation_run_preserves_raw_events_summary_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = V2RunStore(Path(tmp) / "results" / "v2" / "validation").create_run(
                self._run_config("C5"),
                run_id="validation-artifacts",
            )
            context.event_writer.append(EventRecord("validation-artifacts", "harness", EventType.RECONCILIATION_ATTEMPT))
            context.write_json("summary.json", {"status": "validation-only"}, overwrite=False)
            context.write_json("transactions.json", {"count": 1}, overwrite=False)
            context.record_failure("validation synthetic failure", InjectedFailure("EXPECTED_VALIDATION_FAILURE"))

            self.assertTrue((context.run_dir / "config.json").exists())
            self.assertTrue((context.run_dir / "metadata.json").exists())
            self.assertTrue((context.run_dir / "events.jsonl").exists())
            self.assertTrue((context.run_dir / "summary.json").exists())
            self.assertTrue((context.run_dir / "transactions.json").exists())
            self.assertTrue((context.run_dir / "failed-run.json").exists())
            self.assertIn("RUN_FAILED", (context.run_dir / "events.jsonl").read_text(encoding="utf-8"))

    def test_v2_result_store_rejects_historical_paths_for_reset_safety(self):
        for path in (
            Path("results/phase_a_services_final"),
            Path("results/phase_b1_services"),
            Path("results/phase_b2_services"),
        ):
            with self.assertRaises(ArtifactError):
                V2RunStore(path)

    def test_event_schema_preserves_logical_and_execution_identity(self):
        event = EventRecord(
            run_id="validation",
            component="orchestrator",
            event_type="EXECUTION_IDENTITY_ASSIGNED",
            logical_transaction_id="logical-000001",
            execution_transaction_id="tx-v2-c0-0001",
            attempt_id="attempt-1",
            mechanism="deterministic_identity",
            metadata={"configuration": "C0", "duplicateAttempt": True},
        )

        payload = json.loads(event.to_json())
        self.assertEqual("logical-000001", payload["logical_transaction_id"])
        self.assertEqual("tx-v2-c0-0001", payload["execution_transaction_id"])
        self.assertTrue(payload["metadata"]["duplicateAttempt"])

    def _summary_seeds(self, runs):
        seeds = []
        for run in runs:
            with run.summary_path.open(encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            seeds.append(row["randomSeed"])
        return seeds

    def _run_config(self, name: str) -> V2RunConfiguration:
        return V2RunConfiguration(
            cell_id="validation-cell",
            mechanism_configuration=CONFIGURATIONS[name],
            scenario=FailureScenario.F5_PAYMENT_SUCCEEDS_RESPONSE_LOST,
            failure_rate=1.0,
            concurrency=1,
            transactions=1,
            repetition=1,
            seed=7,
            backend=Backend.SIMULATION,
            execution_mode=ExecutionMode.RESILIENT,
        )

    def _result(
        self,
        idempotency_key: str,
        status: str,
        latency_ms: float,
        operation_retries: int = 0,
        compensation_retries: int = 0,
        compensated: bool = False,
        duplicate_payment: bool = False,
    ) -> ExperimentResult:
        return ExperimentResult(
            experiment_id="validation",
            execution_mode=ExecutionMode.RESILIENT,
            failure_scenario=FailureScenario.F0_NO_FAILURE,
            backend=Backend.SIMULATION,
            transaction_id=f"tx-{idempotency_key}",
            idempotency_key=idempotency_key,
            failure_rate=0.0,
            transaction_count=2,
            concurrency=1,
            repetition_number=1,
            random_seed=7,
            environment_metadata={},
            start_timestamp=0.0,
            end_timestamp=1.0,
            latency_ms=latency_ms,
            recovery_time_ms=0.0,
            status=status,
            cart_id=f"cart-{idempotency_key}",
            order_id=f"order-{idempotency_key}",
            payment_id=f"payment-{idempotency_key}",
            order_count=1,
            successful_payment_count=2 if duplicate_payment else 1,
            active_order_count=1,
            duplicate_order=False,
            duplicate_payment=duplicate_payment,
            orphaned_order=False,
            retry_count=operation_retries + compensation_retries,
            operation_retry_count=operation_retries,
            compensation_retry_count=compensation_retries,
            total_retry_count=operation_retries + compensation_retries,
            recovered=False,
            compensated=compensated,
            duplicate_detected=False,
            invariant_violation=duplicate_payment,
            invariant_violation_type="I1_AT_MOST_ONE_SUCCESSFUL_PAYMENT" if duplicate_payment else None,
            run_started_at="2026-08-28T00:00:00+00:00",
            run_ended_at="2026-08-28T00:00:01+00:00",
        )


if __name__ == "__main__":
    unittest.main()

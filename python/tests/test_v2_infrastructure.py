from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from research_harness.failures import FailureConfig, FailureInjector
from research_harness.models import Backend, ExecutionMode, FailureScenario, TransactionRecord, TransactionState
from research_harness.orchestrators import ResilientOrchestrator, StateStore
from research_harness.orchestrators import V2BaselineOrchestrator
from research_harness.retry import RetryPolicy
from research_harness.runner import _runner_reconciliation_enabled, build_request, run_experiment
from research_harness.service_backend import ServiceBackendClient, ServiceBackendConfig
from research_harness.services import CommerceServices
from research_harness.v2_artifacts import ArtifactError, V2RunConfiguration, V2RunStore
from research_harness.v2_config import (
    CONFIGURATIONS,
    ConfigurationError,
    IdentityMode,
    Mechanism,
    V2MechanismConfiguration,
)
from research_harness.v2_crash import DockerComposeCrashConfig, DockerComposeCrashController, FakeCommandRunner
from research_harness.v2_events import EventRecord, EventType, EventWriter
from research_harness.v2_invariants import evaluate_v2_invariants, evaluate_v2_logical_invariants
from research_harness.v2_manifest import ExperimentManifest, ManifestError
from research_harness.v2_service_observation import ServiceSideEffect, V2ServiceObservation
from research_harness import v2_final


class V2InfrastructureTests(unittest.TestCase):
    def test_run_directories_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = V2RunStore(Path(tmp) / "results" / "v2")
            config = self._run_config("C1")
            store.create_run(config, run_id="run-001")

            with self.assertRaises(ArtifactError):
                store.create_run(config, run_id="run-001")

    def test_result_store_rejects_historical_result_path(self):
        with self.assertRaises(ArtifactError):
            V2RunStore(Path("results/phase_b1_services"))

    def test_manifest_parsing_and_validation(self):
        manifest = ExperimentManifest.from_dict({
            "manifestId": "example-v2",
            "campaign": "synthetic",
            "resultRoot": "results/v2/example",
            "cells": [{
                "cellId": "cell-001",
                "configuration": "C1",
                "scenario": "f0-no-failure",
                "failureRate": 0.0,
                "concurrency": 1,
                "transactions": 10,
                "repetitions": 2,
                "paired": True,
                "pairedTarget": "C0",
                "primaryMetric": "logicalTransactionSuccessRate",
                "primaryInvariant": "I2",
            }],
        })

        manifest.validate()
        self.assertEqual("cell-001", manifest.cells[0].cell_id)

    def test_manifest_rejects_historical_result_path(self):
        with self.assertRaises(ManifestError):
            ExperimentManifest.from_dict({
                "manifestId": "bad",
                "campaign": "bad",
                "resultRoot": "results/phase_a_services_final",
                "cells": [{
                    "cellId": "cell-001",
                    "configuration": "C1",
                    "scenario": "f0-no-failure",
                    "failureRate": 0.0,
                    "concurrency": 1,
                    "transactions": 1,
                    "repetitions": 1,
                }],
            })

    def test_run_metadata_captures_git_config_and_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = V2RunStore(Path(tmp) / "results" / "v2").create_run(self._run_config("C1", seed=123), "run-002")
            config = json.loads((context.run_dir / "config.json").read_text(encoding="utf-8"))
            metadata = json.loads((context.run_dir / "metadata.json").read_text(encoding="utf-8"))

            self.assertEqual(123, config["seed"])
            self.assertEqual("run-002", metadata["runId"])
            self.assertIn("commit", metadata["git"])
            self.assertIn("pythonVersion", metadata["environment"])

    def test_event_records_serialize_correctly(self):
        event = EventRecord(
            run_id="run-003",
            component="retry_policy",
            event_type=EventType.RETRY_ATTEMPT,
            logical_transaction_id="logical-1",
            mechanism="bounded_retry",
            operation="execute_payment",
            retry_number=1,
        )

        payload = json.loads(event.to_json())
        self.assertEqual("RETRY_ATTEMPT", payload["event_type"])
        self.assertEqual("run-003", payload["run_id"])
        self.assertNotIn("failure_type", payload)

    def test_failed_runs_preserve_partial_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = V2RunStore(Path(tmp) / "results" / "v2").create_run(self._run_config("C1"), "run-004")
            context.event_writer.append(EventRecord("run-004", "harness", "PARTIAL_EVENT"))
            context.record_failure("synthetic failure", RuntimeError("boom"))

            self.assertTrue((context.run_dir / "failed-run.json").exists())
            events = (context.run_dir / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn("PARTIAL_EVENT", events)
            self.assertIn("RUN_FAILED", events)

    def test_valid_mechanism_configurations_are_accepted(self):
        self.assertEqual(set(CONFIGURATIONS), {"C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"})
        for config in CONFIGURATIONS.values():
            config.validate()

    def test_invalid_dependency_combinations_are_rejected(self):
        with self.assertRaises(ConfigurationError):
            V2MechanismConfiguration(
                "bad-restart",
                IdentityMode.DETERMINISTIC,
                frozenset({Mechanism.DETERMINISTIC_IDENTITY, Mechanism.RESTART_RECOVERY}),
            )
        with self.assertRaises(ConfigurationError):
            V2MechanismConfiguration(
                "bad-reconciliation",
                IdentityMode.DETERMINISTIC,
                frozenset({Mechanism.DETERMINISTIC_IDENTITY, Mechanism.LOST_RESPONSE_RECONCILIATION}),
            )
        with self.assertRaises(ConfigurationError):
            V2MechanismConfiguration(
                "bad-runner-reconciliation",
                IdentityMode.DETERMINISTIC,
                frozenset({Mechanism.DETERMINISTIC_IDENTITY}),
                runner_reconciliation_enabled=True,
            )

    def test_historical_modes_remain_available(self):
        self.assertEqual("baseline", ExecutionMode.BASELINE.value)
        self.assertEqual("resilient", ExecutionMode.RESILIENT.value)

    def test_reconciliation_disabled_v2_configuration_does_not_use_runner_reconciliation(self):
        self.assertTrue(_runner_reconciliation_enabled(None))
        self.assertFalse(_runner_reconciliation_enabled(CONFIGURATIONS["C0"]))
        self.assertFalse(_runner_reconciliation_enabled(CONFIGURATIONS["C1"]))
        self.assertFalse(_runner_reconciliation_enabled(CONFIGURATIONS["C3"]))
        self.assertFalse(_runner_reconciliation_enabled(CONFIGURATIONS["C5"]))
        self.assertFalse(_runner_reconciliation_enabled(CONFIGURATIONS["C8"]))

    def test_mechanism_activations_emit_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            event_path = Path(tmp) / "events.jsonl"
            services = CommerceServices(
                FailureInjector(FailureConfig(scenario=FailureScenario.F11_TRANSIENT_PAYMENT_FAILURE_RECOVERY))
            )
            orchestrator = ResilientOrchestrator(
                services,
                StateStore(Path(tmp) / "state.jsonl"),
                RetryPolicy(),
                event_writer=EventWriter(event_path),
                run_id="run-005",
                scenario=FailureScenario.F11_TRANSIENT_PAYMENT_FAILURE_RECOVERY.value,
            )

            record = orchestrator.execute(build_request(1))
            events = event_path.read_text(encoding="utf-8")

            self.assertEqual(TransactionState.COMPLETED, record.state)
            self.assertIn("RETRY_ATTEMPT", events)
            self.assertIn("RETRY_SUCCEEDED", events)
            self.assertIn("TRANSACTION_COMPLETED", events)

    def test_v2_invariant_evaluator_detects_i1_to_i6_violations(self):
        services = CommerceServices(FailureInjector(FailureConfig()))
        request = build_request(1, "same-key")
        services.create_cart(request, "tx-a")
        services.create_order("cart-tx-a", request, "tx-a")
        services.execute_payment("order-tx-a", request, "tx-a")
        services.payments["manual-duplicate"] = services.payments["payment-tx-a"]
        services.payments["manual-duplicate"].payment_id = "manual-duplicate"
        services.create_order("cart-tx-a", request, "tx-b")
        record = TransactionRecord("tx-a", "same-key", TransactionState.FAILED)

        report = evaluate_v2_invariants(record, services, "same-key")

        self.assertTrue(report.violation)
        self.assertIn("I1_AT_MOST_ONE_SUCCESSFUL_PAYMENT", report.violation_types)
        self.assertIn("I3_AT_MOST_ONE_ORDER", report.violation_types)
        self.assertIn("I6_TERMINAL_STATE_INCONSISTENT", report.violation_types)

    def test_v2_invariant_evaluator_detects_completed_missing_effects(self):
        services = CommerceServices(FailureInjector(FailureConfig()))
        record = TransactionRecord(
            "tx-missing",
            "missing-key",
            TransactionState.COMPLETED,
            order_id="order-missing",
            payment_id="payment-missing",
        )

        report = evaluate_v2_invariants(record, services, "missing-key")

        self.assertTrue(report.violation)
        self.assertIn("I2_COMPLETED_MISSING_VALID_ORDER", report.violation_types)
        self.assertIn("I2_COMPLETED_MISSING_SUCCESSFUL_PAYMENT", report.violation_types)

    def test_v2_invariant_evaluator_detects_identity_and_compensation_violations(self):
        services = CommerceServices(FailureInjector(FailureConfig()))
        request = build_request(1, "same-key")
        services.create_cart(request, "tx-other")
        services.create_order("cart-tx-other", request, "tx-other")
        record = TransactionRecord("tx-original", "same-key", TransactionState.COMPENSATED, order_id="order-tx-other", recovered=True)

        report = evaluate_v2_invariants(record, services, "same-key")

        self.assertTrue(report.violation)
        self.assertIn("I4_COMPENSATED_HAS_ACTIVE_ORDER", report.violation_types)
        self.assertIn("I5_RECOVERY_TRANSACTION_IDENTITY_MISMATCH", report.violation_types)

    def test_c0_generates_fresh_execution_identity_for_duplicate_attempts(self):
        services = CommerceServices(FailureInjector(FailureConfig()))
        orchestrator = V2BaselineOrchestrator(
            services,
            CONFIGURATIONS["C0"],
            transaction_id_factory=self._counting_v2_id_factory("c0"),
        )
        request = build_request(1, "same-key")

        first = orchestrator.execute(request)
        second = orchestrator.execute(request)

        self.assertEqual(first.idempotency_key, second.idempotency_key)
        self.assertEqual("logical-000001", request.logical_transaction_id)
        self.assertNotEqual(first.transaction_id, second.transaction_id)
        self.assertNotEqual(first.cart_id, second.cart_id)
        self.assertNotEqual(first.order_id, second.order_id)
        self.assertNotEqual(first.payment_id, second.payment_id)

    def test_c1_preserves_deterministic_execution_identity_for_duplicate_attempts(self):
        services = CommerceServices(FailureInjector(FailureConfig()))
        orchestrator = V2BaselineOrchestrator(services, CONFIGURATIONS["C1"])
        request = build_request(1, "same-key")

        first = orchestrator.execute(request)
        second = orchestrator.execute(request)

        self.assertEqual("logical-000001", request.logical_transaction_id)
        self.assertEqual("tx-logical-000001", first.transaction_id)
        self.assertEqual(first.transaction_id, second.transaction_id)
        self.assertEqual(first.cart_id, second.cart_id)
        self.assertEqual(first.order_id, second.order_id)
        self.assertEqual(first.payment_id, second.payment_id)

    def test_c0_duplicate_effects_are_grouped_by_logical_idempotency_key(self):
        services = CommerceServices(FailureInjector(FailureConfig()))
        orchestrator = V2BaselineOrchestrator(
            services,
            CONFIGURATIONS["C0"],
            transaction_id_factory=self._counting_v2_id_factory("c0"),
        )
        request = build_request(1, "same-key")

        record = orchestrator.execute(request)
        orchestrator.execute(request)
        report = evaluate_v2_logical_invariants(record, services, request)

        self.assertEqual(2, report.order_count)
        self.assertEqual(2, report.successful_payment_count)
        self.assertIn("I1_AT_MOST_ONE_SUCCESSFUL_PAYMENT", report.violation_types)
        self.assertIn("I3_AT_MOST_ONE_ORDER", report.violation_types)

    def test_runner_passes_v2_identity_events_to_artifact_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            event_path = Path(tmp) / "events.jsonl"
            run_experiment(
                mode=ExecutionMode.BASELINE,
                scenario=FailureScenario.F0_NO_FAILURE,
                transactions=1,
                concurrency=1,
                failure_rate=0.0,
                repetitions=1,
                output_root=Path(tmp) / "results",
                random_seed=7,
                backend=Backend.SIMULATION,
                v2_configuration=CONFIGURATIONS["C0"],
                v2_event_writer=EventWriter(event_path),
                v2_run_id="run-c0",
            )

            events = event_path.read_text(encoding="utf-8")
            self.assertIn("EXECUTION_IDENTITY_ASSIGNED", events)
            self.assertIn("execution_transaction_id", events)

    def test_crash_controller_uses_compose_sigkill_for_orchestrator(self):
        with tempfile.TemporaryDirectory() as tmp:
            event_path = Path(tmp) / "events.jsonl"
            runner = FakeCommandRunner()
            controller = DockerComposeCrashController(
                DockerComposeCrashConfig(readiness_timeout_seconds=0.01, poll_interval_seconds=0.01),
                event_writer=EventWriter(event_path),
                run_id="run-crash",
                command_runner=runner,
            )
            controller.wait_until_unavailable = lambda url: None

            controller.kill_orchestrator()

            command = runner.commands[0]
            self.assertIn("kill", command)
            self.assertIn("SIGKILL", command)
            self.assertIn("orchestrator", command)
            events = event_path.read_text(encoding="utf-8")
            self.assertIn("ORCHESTRATOR_KILL_REQUESTED", events)
            self.assertIn("ORCHESTRATOR_PROCESS_EXITED", events)

    def test_crash_controller_restart_emits_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            event_path = Path(tmp) / "events.jsonl"
            runner = FakeCommandRunner()
            controller = DockerComposeCrashController(
                DockerComposeCrashConfig(readiness_timeout_seconds=0.01, poll_interval_seconds=0.01),
                event_writer=EventWriter(event_path),
                run_id="run-crash",
                command_runner=runner,
            )
            controller.wait_for_http_health = lambda url, deadline: None

            controller.restart_orchestrator()

            self.assertIn("--no-deps", runner.commands[0])
            events = event_path.read_text(encoding="utf-8")
            self.assertIn("ORCHESTRATOR_RESTART_REQUESTED", events)
            self.assertIn("ORCHESTRATOR_RESTARTED", events)
            self.assertIn("ORCHESTRATOR_HEALTHY", events)

    def test_crash_controller_reset_targets_only_service_tables(self):
        runner = FakeCommandRunner()
        controller = DockerComposeCrashController(command_runner=runner)
        controller.wait_for_http_health = lambda url, deadline: None

        controller.reset_database()

        command = runner.commands[0]
        self.assertIn("truncate table orchestrator_transactions, orchestrator_mechanism_events, carts, orders, payments restart identity;", command)
        self.assertNotIn("results", " ".join(command))
        self.assertIn("restart", runner.commands[1])
        self.assertIn("payment-simulator", runner.commands[1])

    def test_v2_final_ordinary_runs_pass_base_seed_once_to_runner(self):
        calls = []

        class Store:
            def create_run(self, config, run_id):
                class Context:
                    run_dir = Path(tempfile.mkdtemp())
                    event_writer = None
                return Context()

        class Controller:
            def reset_database(self):
                pass

        class Run:
            raw_path = Path(tempfile.mkdtemp()) / "raw.jsonl"
            summary_path = Path(tempfile.mkdtemp()) / "summary.csv"

        Run.raw_path.write_text("", encoding="utf-8")
        Run.summary_path.write_text("a\n1\n", encoding="utf-8")

        def fake_run_experiment(*args, **kwargs):
            calls.append(kwargs)
            return [Run()]

        with patch.object(v2_final, "run_experiment", fake_run_experiment), patch.object(v2_final, "preserve_logs", lambda *args: {}):
            v2_final.run_ordinary_cell(Store(), Controller(), None, v2_final.cell_by_id("P05"), 1, 2026082900, "seed-test-rep1")
            v2_final.run_ordinary_cell(Store(), Controller(), None, v2_final.cell_by_id("P05"), 2, 2026082901, "seed-test-rep2")
            v2_final.run_ordinary_cell(Store(), Controller(), None, v2_final.cell_by_id("P05"), 8, 2026082907, "seed-test-rep8")

        self.assertEqual([v2_final.BASE_SEED, v2_final.BASE_SEED, v2_final.BASE_SEED], [call["random_seed"] for call in calls])
        self.assertEqual([1, 2, 8], [call["repetition_start"] for call in calls])

    def test_crash_controller_preserves_separate_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeCommandRunner()
            controller = DockerComposeCrashController(command_runner=runner)

            paths = controller.preserve_logs(Path(tmp), "pre-crash")

            self.assertIn("orchestrator", paths)
            self.assertTrue(Path(paths["orchestrator"]).name.endswith("pre-crash.log"))

    def test_v2_service_observation_detects_i5_i6_state(self):
        record = TransactionRecord("tx-1", "key-1", TransactionState.COMPLETED, order_id="order-tx-1", payment_id="payment-tx-1")
        valid = V2ServiceObservation(
            coordinator=record,
            carts=(ServiceSideEffect("cart-tx-1", "tx-1", "key-1", "OPEN"),),
            orders=(ServiceSideEffect("order-tx-1", "tx-1", "key-1", "ACTIVE"),),
            payments=(ServiceSideEffect("payment-tx-1", "tx-1", "key-1", "SUCCEEDED"),),
        )
        invalid = V2ServiceObservation(
            coordinator=record,
            carts=(ServiceSideEffect("cart-tx-2", "tx-2", "key-1", "OPEN"),),
            orders=(),
            payments=(),
        )

        self.assertTrue(valid.identity_preserved())
        self.assertTrue(valid.terminal_state_consistent())
        self.assertFalse(invalid.identity_preserved())
        self.assertFalse(invalid.terminal_state_consistent())

    def test_c0_and_c1_do_not_activate_other_mechanisms(self):
        self.assertEqual([], CONFIGURATIONS["C0"].enabled_mechanisms)
        self.assertEqual(["deterministic_identity"], CONFIGURATIONS["C1"].enabled_mechanisms)
        for name in ("C0", "C1"):
            self.assertFalse(CONFIGURATIONS[name].runner_reconciliation_enabled)
            self.assertFalse(CONFIGURATIONS[name].has(Mechanism.DURABLE_STATE))
            self.assertFalse(CONFIGURATIONS[name].has(Mechanism.BOUNDED_RETRY))
            self.assertFalse(CONFIGURATIONS[name].has(Mechanism.LOST_RESPONSE_RECONCILIATION))
            self.assertFalse(CONFIGURATIONS[name].has(Mechanism.COMPENSATION))
            self.assertFalse(CONFIGURATIONS[name].has(Mechanism.RESTART_RECOVERY))

    def test_v2_artifact_event_records_logical_and_execution_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            event_path = Path(tmp) / "events.jsonl"
            services = CommerceServices(FailureInjector(FailureConfig()))
            orchestrator = V2BaselineOrchestrator(
                services,
                CONFIGURATIONS["C0"],
                transaction_id_factory=self._counting_v2_id_factory("c0"),
                event_writer=EventWriter(event_path),
                run_id="run-identity",
                scenario=FailureScenario.F8_CONCURRENT_DUPLICATE_TRANSACTION_REQUESTS.value,
            )

            record = orchestrator.execute(build_request(1, "same-key"))
            events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
            event = events[0]
            completion = events[-1]

            self.assertEqual("logical-000001", event["logical_transaction_id"])
            self.assertEqual(record.transaction_id, event["execution_transaction_id"])
            self.assertEqual("C0", event["metadata"]["configuration"])
            self.assertEqual(record.payment_id, completion["metadata"]["paymentId"])
            self.assertEqual(record.order_id, completion["metadata"]["orderId"])

    def test_service_backend_sends_v2_configuration_without_changing_historical_headers(self):
        client = ServiceBackendClient(ServiceBackendConfig())

        historical = client._headers("key", ExecutionMode.BASELINE, FailureScenario.F0_NO_FAILURE, 0.0, 7)
        c0 = client._headers("key", ExecutionMode.BASELINE, FailureScenario.F0_NO_FAILURE, 0.0, 7, CONFIGURATIONS["C0"])

        self.assertNotIn("X-V2-Configuration", historical)
        self.assertEqual("C0", c0["X-V2-Configuration"])

    def test_runner_observation_does_not_repair_c0_or_c1_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("C0", "C1"):
                runs = run_experiment(
                    mode=ExecutionMode.BASELINE,
                    scenario=FailureScenario.F8_CONCURRENT_DUPLICATE_TRANSACTION_REQUESTS,
                    transactions=2,
                    concurrency=1,
                    failure_rate=1.0,
                    repetitions=1,
                    output_root=Path(tmp) / name,
                    random_seed=7,
                    backend=Backend.SIMULATION,
                    v2_configuration=CONFIGURATIONS[name],
                )
                raw = runs[0].raw_path.read_text(encoding="utf-8")
                self.assertNotIn('"recoveryAttempted": true', raw)
                self.assertNotIn('"reconciliationWindowMs": 2000', raw)

    def _run_config(self, name: str, seed: int = 7) -> V2RunConfiguration:
        return V2RunConfiguration(
            cell_id="cell-001",
            mechanism_configuration=CONFIGURATIONS[name],
            scenario=FailureScenario.F0_NO_FAILURE,
            failure_rate=0.0,
            concurrency=1,
            transactions=10,
            repetition=1,
            seed=seed,
            backend=Backend.SIMULATION,
            execution_mode=ExecutionMode.RESILIENT,
            retry_configuration={"maxAttempts": 3},
            reconciliation_configuration={"windowMs": 0},
        )

    def _counting_v2_id_factory(self, label: str):
        counter = {"value": 0}

        def next_id(request):
            counter["value"] += 1
            return f"tx-v2-{label}-{counter['value']:04d}"

        return next_id


if __name__ == "__main__":
    unittest.main()

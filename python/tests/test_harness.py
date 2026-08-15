from pathlib import Path
import tempfile
import unittest

from research_harness.failures import FailureConfig, FailureInjector, InjectedFailure
from research_harness.models import ExecutionMode, FailureScenario, TransactionState
from research_harness.orchestrators import BaselineOrchestrator, ResilientOrchestrator, StateStore
from research_harness.retry import RetryPolicy
from research_harness.runner import build_request, run_experiment
from research_harness.services import CommerceServices


class HarnessTests(unittest.TestCase):
    def test_resilient_normal_transaction_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = CommerceServices(FailureInjector(FailureConfig()))
            orchestrator = ResilientOrchestrator(services, StateStore(Path(tmp) / "state.jsonl"), RetryPolicy())
            record = orchestrator.execute(build_request(1))

            self.assertEqual(TransactionState.COMPLETED, record.state)
            self.assertEqual(1, services.successful_payment_count_for_order(record.order_id))

    def test_baseline_duplicate_request_creates_duplicate_side_effects(self):
        services = CommerceServices(FailureInjector(FailureConfig()))
        orchestrator = BaselineOrchestrator(services)
        request = build_request(1, "same-key")

        first = orchestrator.execute(request)
        second = orchestrator.execute(request)

        self.assertEqual(TransactionState.COMPLETED, first.state)
        self.assertEqual(TransactionState.COMPLETED, second.state)
        self.assertEqual(2, len(services.payments))

    def test_resilient_duplicate_request_returns_existing_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = CommerceServices(FailureInjector(FailureConfig()))
            orchestrator = ResilientOrchestrator(services, StateStore(Path(tmp) / "state.jsonl"), RetryPolicy())
            request = build_request(1, "same-key")

            first = orchestrator.execute(request)
            second = orchestrator.execute(request)

            self.assertEqual(first.transaction_id, second.transaction_id)
            self.assertTrue(second.duplicate_detected)
            self.assertEqual(1, len(services.payments))

    def test_payment_response_loss_does_not_double_charge_resilient_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = CommerceServices(
                FailureInjector(FailureConfig(scenario=FailureScenario.F5_PAYMENT_SUCCEEDS_RESPONSE_LOST))
            )
            orchestrator = ResilientOrchestrator(services, StateStore(Path(tmp) / "state.jsonl"), RetryPolicy())
            request = build_request(1)

            first = orchestrator.execute(request)
            second = orchestrator.execute(request)

            self.assertEqual(TransactionState.COMPLETED, first.state)
            self.assertEqual(first.transaction_id, second.transaction_id)
            self.assertEqual(1, len(services.payments))

    def test_partial_payment_failure_compensates_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = CommerceServices(
                FailureInjector(FailureConfig(scenario=FailureScenario.F10_PAYMENT_PERMANENTLY_FAILS))
            )
            orchestrator = ResilientOrchestrator(services, StateStore(Path(tmp) / "state.jsonl"), RetryPolicy())

            record = orchestrator.execute(build_request(1))

            self.assertEqual(TransactionState.COMPENSATED, record.state)
            self.assertEqual("CANCELLED", services.orders[record.order_id].status)

    def test_transient_failure_retries_then_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = CommerceServices(
                FailureInjector(FailureConfig(scenario=FailureScenario.F11_TRANSIENT_PAYMENT_FAILURE_RECOVERY))
            )
            orchestrator = ResilientOrchestrator(services, StateStore(Path(tmp) / "state.jsonl"), RetryPolicy())

            record = orchestrator.execute(build_request(1))

            self.assertEqual(TransactionState.COMPLETED, record.state)
            self.assertEqual(2, record.retry_count)

    def test_recovery_after_interruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = CommerceServices(FailureInjector(FailureConfig()))
            orchestrator = ResilientOrchestrator(services, StateStore(Path(tmp) / "state.jsonl"), RetryPolicy())

            with self.assertRaises(RuntimeError):
                orchestrator.execute(build_request(1), crash_after_order=True)
            recovered = orchestrator.recover()

            self.assertEqual(1, len(recovered))
            self.assertEqual(TransactionState.COMPLETED, recovered[0].state)
            self.assertTrue(recovered[0].recovered)

    def test_failure_injector_http_500(self):
        injector = FailureInjector(FailureConfig(scenario=FailureScenario.F1_CART_HTTP_500))
        with self.assertRaises(InjectedFailure):
            injector.before_operation("create_cart")

    def test_experiment_writes_real_output_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = run_experiment(
                mode=ExecutionMode.RESILIENT,
                scenario=FailureScenario.F0_NO_FAILURE,
                transactions=2,
                concurrency=1,
                failure_rate=0.0,
                repetitions=2,
                output_root=Path(tmp),
                random_seed=42,
            )
            raw_path = runs[0].raw_path
            summary_path = runs[0].summary_path

            self.assertEqual(2, len(runs))
            self.assertTrue(raw_path.exists())
            self.assertTrue(summary_path.exists())
            self.assertIn("transactions.jsonl", str(raw_path))
            self.assertIn("rep-0001", str(raw_path))
            self.assertIn("rep-0002", str(runs[1].raw_path))

    def test_baseline_payment_response_loss_records_observed_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = run_experiment(
                mode=ExecutionMode.BASELINE,
                scenario=FailureScenario.F5_PAYMENT_SUCCEEDS_RESPONSE_LOST,
                transactions=1,
                concurrency=1,
                failure_rate=1.0,
                repetitions=1,
                output_root=Path(tmp),
                random_seed=99,
            )

            payload = runs[0].raw_path.read_text(encoding="utf-8")
            self.assertIn('"successfulPaymentCount": 1', payload)
            self.assertIn('"invariantViolationType": "CROSS_SERVICE_STATE_CONSISTENCY"', payload)

    def test_compensation_failure_is_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = CommerceServices(
                FailureInjector(FailureConfig(scenario=FailureScenario.F12_COMPENSATION_FAILURE_RETRY))
            )
            orchestrator = ResilientOrchestrator(services, StateStore(Path(tmp) / "state.jsonl"), RetryPolicy())

            record = orchestrator.execute(build_request(1))

            self.assertEqual(TransactionState.COMPENSATED, record.state)
            self.assertEqual(1, record.retry_count)
            self.assertEqual("CANCELLED", services.orders[record.order_id].status)


if __name__ == "__main__":
    unittest.main()

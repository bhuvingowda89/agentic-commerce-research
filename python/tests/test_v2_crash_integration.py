import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError, URLError

from research_harness.models import ExecutionMode, FailureScenario, TransactionState
from research_harness.runner import build_request
from research_harness.service_backend import ServiceBackendClient, ServiceBackendConfig
from research_harness.v2_config import configuration
from research_harness.v2_crash import DockerComposeCrashController
from research_harness.v2_events import EventRecord, EventType, EventWriter


RUN_DOCKER_INTEGRATION = os.environ.get("RUN_V2_DOCKER_INTEGRATION") == "1"


@unittest.skipUnless(RUN_DOCKER_INTEGRATION, "set RUN_V2_DOCKER_INTEGRATION=1 to run Docker crash validation")
class V2CrashIntegrationTests(unittest.TestCase):
    def test_true_orchestrator_kill_restart_and_c7_recovery(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as tmp:
            run_id = "v2-crash-validation"
            event_path = Path(tmp) / "events.jsonl"
            logs_dir = Path(tmp) / "logs"
            writer = EventWriter(event_path)
            controller = DockerComposeCrashController(event_writer=writer, run_id=run_id)
            client = ServiceBackendClient(
                ServiceBackendConfig(
                    orchestrator_url="http://localhost:18080",
                    cart_url="http://localhost:18081",
                    order_url="http://localhost:18082",
                    payment_url="http://localhost:18083",
                    timeout_seconds=2.0,
                )
            )

            controller.start()
            controller.reset_database()

            before_instance = client.orchestrator_instance()["orchestratorInstanceId"]
            request = build_request(1, "v2-crash-validation-key")
            token = "v2-crash-validation-token"
            writer.append(
                EventRecord(
                    run_id=run_id,
                    component="crash_controller",
                    event_type=EventType.CRASH_ARMED,
                    logical_transaction_id=request.logical_transaction_id,
                    scenario=FailureScenario.F0_NO_FAILURE.value,
                    mechanism="restart_recovery",
                    operation="after-order-persisted",
                )
            )

            result_holder = {}

            def execute_until_killed():
                result_holder["result"] = client.execute(
                    request,
                    ExecutionMode.RESILIENT,
                    FailureScenario.F0_NO_FAILURE,
                    0.0,
                    4242,
                    configuration("C7"),
                    v2_crash_point="after-order-persisted",
                    v2_crash_token=token,
                )

            worker = threading.Thread(target=execute_until_killed, daemon=True)
            worker.start()

            status = self._wait_for_crash_point(client, token)
            writer.append(
                EventRecord(
                    run_id=run_id,
                    component="orchestrator",
                    event_type=EventType.CRASH_POINT_REACHED,
                    logical_transaction_id=request.logical_transaction_id,
                    execution_transaction_id=status["transactionId"],
                    scenario=FailureScenario.F0_NO_FAILURE.value,
                    state_after=status["state"],
                    operation=status["point"],
                )
            )
            self.assertEqual("ORDER_CREATED", status["state"])
            pre_recovery = client.inspect(request.idempotency_key, client.find_transaction(request.idempotency_key))
            self.assertEqual(1, pre_recovery.order_count)
            self.assertEqual(0, pre_recovery.successful_payment_count)

            controller.preserve_logs(logs_dir, "pre-crash")
            controller.kill_orchestrator()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertTrue(controller.postgres_is_running())

            controller.restart_orchestrator()
            after_instance = client.orchestrator_instance()["orchestratorInstanceId"]
            self.assertNotEqual(before_instance, after_instance)

            c2_record, c2_error = client.recover_one(
                request.idempotency_key,
                ExecutionMode.RESILIENT,
                4242,
                configuration("C2"),
            )
            self.assertIsNone(c2_record)
            self.assertIsNotNone(c2_error)

            writer.append(
                EventRecord(
                    run_id=run_id,
                    component="orchestrator",
                    event_type=EventType.RECOVERY_STARTED,
                    logical_transaction_id=request.logical_transaction_id,
                    mechanism="restart_recovery",
                )
            )
            recovered, recovery_error = client.recover_one(
                request.idempotency_key,
                ExecutionMode.RESILIENT,
                4242,
                configuration("C7"),
            )
            self.assertIsNone(recovery_error)
            self.assertIsNotNone(recovered)
            self.assertEqual(TransactionState.COMPLETED, recovered.state)
            self.assertEqual(status["transactionId"], recovered.transaction_id)
            writer.append(
                EventRecord(
                    run_id=run_id,
                    component="orchestrator",
                    event_type=EventType.RECOVERY_SUCCEEDED,
                    logical_transaction_id=request.logical_transaction_id,
                    execution_transaction_id=recovered.transaction_id,
                    mechanism="restart_recovery",
                    state_after=recovered.state.value,
                )
            )

            final_report = client.inspect(request.idempotency_key, recovered)
            self.assertEqual(1, final_report.order_count)
            self.assertEqual(1, final_report.successful_payment_count)
            self.assertFalse(final_report.duplicate_order)
            self.assertFalse(final_report.duplicate_payment)
            controller.preserve_logs(logs_dir, "post-restart")

            events = event_path.read_text(encoding="utf-8")
            self.assertIn(EventType.CRASH_ARMED, events)
            self.assertIn(EventType.CRASH_POINT_REACHED, events)
            self.assertIn(EventType.ORCHESTRATOR_KILL_REQUESTED, events)
            self.assertIn(EventType.ORCHESTRATOR_RESTARTED, events)
            self.assertIn(EventType.RECOVERY_SUCCEEDED, events)
            self.assertTrue((logs_dir / "orchestrator-pre-crash.log").exists())
            self.assertTrue((logs_dir / "orchestrator-post-restart.log").exists())

    def _wait_for_crash_point(self, client: ServiceBackendClient, token: str) -> dict:
        deadline = time.monotonic() + 20.0
        last_error = None
        while time.monotonic() < deadline:
            try:
                status = client.crash_point_status(token)
                if status.get("reached"):
                    return status
            except (HTTPError, URLError, TimeoutError) as exc:
                last_error = exc
            time.sleep(0.25)
        raise AssertionError(f"crash point was not reached: {last_error}")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from dataclasses import dataclass

from .failures import InjectedFailure
from .v2_events import EventRecord, EventType, EventWriter


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_backoff_ms: int = 100
    multiplier: int = 2

    def run(
        self,
        operation_name: str,
        operation,
        event_writer: EventWriter | None = None,
        run_id: str | None = None,
        mechanism: str = "bounded_retry",
    ):
        attempts = 0
        last_failure = None
        while attempts < self.max_attempts:
            try:
                result = operation()
                if attempts > 0 and event_writer and run_id:
                    event_writer.append(EventRecord(
                        run_id=run_id,
                        component="retry_policy",
                        event_type=EventType.RETRY_SUCCEEDED,
                        mechanism=mechanism,
                        operation=operation_name,
                        retry_number=attempts,
                    ))
                return result, attempts
            except InjectedFailure as failure:
                last_failure = failure
                attempts += 1
                if not failure.transient or attempts >= self.max_attempts:
                    if event_writer and run_id:
                        event_writer.append(EventRecord(
                            run_id=run_id,
                            component="retry_policy",
                            event_type=EventType.RETRY_EXHAUSTED,
                            mechanism=mechanism,
                            operation=operation_name,
                            failure_type=failure.failure_type,
                            retry_number=attempts,
                        ))
                    raise
                if event_writer and run_id:
                    event_writer.append(EventRecord(
                        run_id=run_id,
                        component="retry_policy",
                        event_type=EventType.RETRY_ATTEMPT,
                        mechanism=mechanism,
                        operation=operation_name,
                        failure_type=failure.failure_type,
                        retry_number=attempts,
                    ))
        raise last_failure or RuntimeError(f"{operation_name} failed")

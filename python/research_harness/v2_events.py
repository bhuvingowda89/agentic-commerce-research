from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class EventRecord:
    run_id: str
    component: str
    event_type: str
    timestamp: str = field(default_factory=utc_now)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    logical_transaction_id: str | None = None
    execution_transaction_id: str | None = None
    attempt_id: str | None = None
    mechanism: str | None = None
    scenario: str | None = None
    operation: str | None = None
    state_before: str | None = None
    state_after: str | None = None
    side_effect_status: str | None = None
    failure_type: str | None = None
    retry_number: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


class EventWriter:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: EventRecord) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.to_json() + "\n")


class EventType:
    TRANSACTION_STARTED = "TRANSACTION_STARTED"
    TRANSACTION_STATE_CHANGED = "TRANSACTION_STATE_CHANGED"
    TRANSACTION_COMPLETED = "TRANSACTION_COMPLETED"
    FAILURE_INJECTED = "FAILURE_INJECTED"
    RETRY_ATTEMPT = "RETRY_ATTEMPT"
    RETRY_SUCCEEDED = "RETRY_SUCCEEDED"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    RECONCILIATION_ATTEMPT = "RECONCILIATION_ATTEMPT"
    RECONCILIATION_FOUND_EFFECT = "RECONCILIATION_FOUND_EFFECT"
    RECONCILIATION_NOT_FOUND = "RECONCILIATION_NOT_FOUND"
    COMPENSATION_ATTEMPT = "COMPENSATION_ATTEMPT"
    COMPENSATION_SUCCEEDED = "COMPENSATION_SUCCEEDED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    RECOVERY_STARTED = "RECOVERY_STARTED"
    RECOVERY_SUCCEEDED = "RECOVERY_SUCCEEDED"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    DUPLICATE_DETECTED = "DUPLICATE_DETECTED"
    EXISTING_EFFECT_REUSED = "EXISTING_EFFECT_REUSED"
    INVARIANT_EVALUATED = "INVARIANT_EVALUATED"
    RUN_FAILED = "RUN_FAILED"

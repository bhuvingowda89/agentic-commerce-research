from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
import platform
from pathlib import Path
import subprocess
from uuid import uuid4

from .models import Backend, ExecutionMode, FailureScenario
from .v2_config import V2MechanismConfiguration
from .v2_events import EventRecord, EventType, EventWriter, utc_now


class ArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class V2RunConfiguration:
    cell_id: str
    mechanism_configuration: V2MechanismConfiguration
    scenario: FailureScenario
    failure_rate: float
    concurrency: int
    transactions: int
    repetition: int
    seed: int
    backend: Backend = Backend.SIMULATION
    execution_mode: ExecutionMode = ExecutionMode.RESILIENT
    service_timeout_seconds: float = 3.0
    retry_configuration: dict[str, object] = field(default_factory=dict)
    reconciliation_configuration: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["mechanism_configuration"] = self.mechanism_configuration.to_dict()
        payload["scenario"] = self.scenario.value
        payload["backend"] = self.backend.value
        payload["execution_mode"] = self.execution_mode.value
        return _camelize_keys(payload)


class V2RunStore:
    def __init__(self, result_root: Path = Path("results/v2")):
        self.result_root = result_root
        if not _is_v2_result_root(result_root):
            raise ArtifactError("v2 run store must target results/v2 or a child directory")

    def create_run(self, config: V2RunConfiguration, run_id: str | None = None) -> V2RunContext:
        actual_run_id = run_id or str(uuid4())
        run_dir = self.result_root / "runs" / actual_run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise ArtifactError(f"run directory already exists: {run_dir}") from exc
        context = V2RunContext(run_id=actual_run_id, run_dir=run_dir, config=config)
        context.write_json("config.json", config.to_dict(), overwrite=False)
        context.write_json("metadata.json", capture_run_metadata(actual_run_id, config), overwrite=False)
        return context


@dataclass(frozen=True)
class V2RunContext:
    run_id: str
    run_dir: Path
    config: V2RunConfiguration

    @property
    def event_writer(self) -> EventWriter:
        return EventWriter(self.run_dir / "events.jsonl")

    def path(self, name: str) -> Path:
        return self.run_dir / name

    def write_json(self, name: str, payload: dict[str, object], overwrite: bool = False) -> Path:
        path = self.path(name)
        if path.exists() and not overwrite:
            raise ArtifactError(f"artifact already exists: {path}")
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def record_failure(self, reason: str, exception: BaseException | None = None) -> Path:
        payload = {
            "runId": self.run_id,
            "timestamp": utc_now(),
            "configuration": self.config.to_dict(),
            "failureReason": reason,
            "exceptionType": exception.__class__.__name__ if exception else None,
            "exception": str(exception) if exception else None,
        }
        self.event_writer.append(EventRecord(
            run_id=self.run_id,
            component="harness",
            event_type=EventType.RUN_FAILED,
            failure_type=reason,
            metadata={"exceptionType": payload["exceptionType"], "exception": payload["exception"]},
        ))
        return self.write_json("failed-run.json", {k: v for k, v in payload.items() if v is not None}, overwrite=False)


def capture_run_metadata(run_id: str, config: V2RunConfiguration) -> dict[str, object]:
    return {
        "runId": run_id,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "git": {
            "commit": _command_output(["git", "rev-parse", "HEAD"]),
            "branch": _command_output(["git", "branch", "--show-current"]),
            "dirtyStatus": _command_output(["git", "status", "--short"]),
            "dirty": bool(_command_output(["git", "status", "--short"]).strip()),
        },
        "environment": {
            "os": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpuCount": os.cpu_count(),
            "memoryBytes": _memory_bytes(),
            "javaVersion": _command_output(["java", "-version"]),
            "pythonVersion": platform.python_version(),
            "dockerVersion": _command_output(["docker", "--version"]),
            "dockerComposeVersion": _command_output(["docker-compose", "--version"]),
            "postgresqlVersion": _command_output([
                "docker-compose",
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "commerce",
                "-d",
                "commerce_research",
                "-tAc",
                "select version();",
            ]),
        },
        "timeoutConfiguration": {
            "serviceTimeoutSeconds": config.service_timeout_seconds,
        },
        "retryConfiguration": config.retry_configuration,
        "reconciliationConfiguration": config.reconciliation_configuration,
    }


def _command_output(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=5)
        return (completed.stdout + completed.stderr).strip().replace("\n", " | ")
    except Exception as exc:
        return f"UNAVAILABLE:{exc}"


def _memory_bytes() -> int | None:
    if hasattr(os, "sysconf"):
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return int(pages * page_size)
        except Exception:
            pass
    try:
        return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
    except Exception:
        return None


def _is_v2_result_root(path: Path) -> bool:
    parts = path.parts
    return any(parts[index] == "results" and parts[index + 1] == "v2" for index in range(len(parts) - 1))


def _camelize_keys(payload: dict[str, object]) -> dict[str, object]:
    return {_to_camel_case(key): value for key, value in payload.items()}


def _to_camel_case(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])

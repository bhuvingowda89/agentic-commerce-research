from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import time
import urllib.request

from .v2_events import EventRecord, EventType, EventWriter


class CrashControllerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ComposeService:
    name: str
    health_url: str | None = None


@dataclass(frozen=True)
class DockerComposeCrashConfig:
    compose_file: Path = Path("docker-compose.v2.yml")
    project_name: str = "agentic-commerce-v2"
    orchestrator_service: str = "orchestrator"
    postgres_service: str = "postgres"
    services: tuple[ComposeService, ...] = (
        ComposeService("postgres"),
        ComposeService("cart-service", "http://localhost:18081/health"),
        ComposeService("order-service", "http://localhost:18082/health"),
        ComposeService("payment-simulator", "http://localhost:18083/health"),
        ComposeService("orchestrator", "http://localhost:18080/health"),
    )
    orchestrator_health_url: str = "http://localhost:18080/health"
    command_timeout_seconds: int = 120
    poll_interval_seconds: float = 0.25
    readiness_timeout_seconds: float = 90.0


class DockerComposeCrashController:
    def __init__(
        self,
        config: DockerComposeCrashConfig = DockerComposeCrashConfig(),
        event_writer: EventWriter | None = None,
        run_id: str | None = None,
        command_runner=None,
    ):
        self.config = config
        self.event_writer = event_writer
        self.run_id = run_id
        self.command_runner = command_runner or self._run_command

    def build(self) -> None:
        build_services = [service.name for service in self.config.services if service.name != self.config.postgres_service]
        self._compose("build", *build_services)

    def start(self) -> None:
        self._compose("up", "-d", *(service.name for service in self.config.services))
        self.wait_until_ready()

    def wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.config.readiness_timeout_seconds
        for service in self.config.services:
            if service.health_url is None:
                self.wait_for_compose_running(service.name, deadline)
            else:
                self.wait_for_http_health(service.health_url, deadline)

    def wait_for_http_health(self, url: str, deadline: float) -> None:
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if 200 <= response.status < 300:
                        return
            except Exception:
                time.sleep(self.config.poll_interval_seconds)
        raise CrashControllerError(f"service did not become healthy: {url}")

    def wait_for_compose_running(self, service: str, deadline: float) -> None:
        while time.monotonic() < deadline:
            status = self.compose_output("ps", "--status", "running", "--services")
            if service in status.splitlines():
                return
            time.sleep(self.config.poll_interval_seconds)
        raise CrashControllerError(f"compose service did not become running: {service}")

    def kill_orchestrator(self) -> None:
        self._emit(EventType.ORCHESTRATOR_KILL_REQUESTED)
        self._compose("kill", "-s", "SIGKILL", self.config.orchestrator_service)
        self._emit(EventType.ORCHESTRATOR_PROCESS_EXITED)
        self.wait_until_unavailable(self.config.orchestrator_health_url)

    def wait_until_unavailable(self, url: str, timeout_seconds: float = 20.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(url, timeout=1)
            except Exception:
                self._emit(EventType.ORCHESTRATOR_UNAVAILABLE)
                return
            time.sleep(self.config.poll_interval_seconds)
        raise CrashControllerError(f"orchestrator still reachable after kill: {url}")

    def restart_orchestrator(self) -> None:
        self._emit(EventType.ORCHESTRATOR_RESTART_REQUESTED)
        self._compose("up", "-d", "--no-deps", self.config.orchestrator_service)
        self._emit(EventType.ORCHESTRATOR_RESTARTED)
        self.wait_for_http_health(
            self.config.orchestrator_health_url,
            time.monotonic() + self.config.readiness_timeout_seconds,
        )
        self._emit(EventType.ORCHESTRATOR_HEALTHY)

    def postgres_is_running(self) -> bool:
        status = self.compose_output("ps", "--status", "running", "--services")
        return self.config.postgres_service in status.splitlines()

    def reset_database(self) -> None:
        sql = "truncate table orchestrator_transactions, orchestrator_mechanism_events, carts, orders, payments restart identity;"
        self._compose(
            "exec",
            "-T",
            self.config.postgres_service,
            "psql",
            "-U",
            "commerce",
            "-d",
            "commerce_research",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        )

    def preserve_logs(self, output_dir: Path, suffix: str) -> dict[str, str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = {}
        for service in self.config.services:
            path = output_dir / f"{service.name}-{suffix}.log"
            path.write_text(self.compose_output("logs", "--no-color", service.name), encoding="utf-8")
            paths[service.name] = str(path)
        return paths

    def compose_output(self, *args: str) -> str:
        return self._compose(*args, capture=True).stdout

    def _compose(self, *args: str, capture: bool = False):
        command = [
            "docker-compose",
            "-f",
            str(self.config.compose_file),
            "-p",
            self.config.project_name,
            *args,
        ]
        return self.command_runner(command, capture)

    def _run_command(self, command: list[str], capture: bool):
        return subprocess.run(
            command,
            check=True,
            capture_output=capture,
            text=True,
            timeout=self.config.command_timeout_seconds,
        )

    def _emit(self, event_type: str) -> None:
        if not self.event_writer or not self.run_id:
            return
        self.event_writer.append(EventRecord(run_id=self.run_id, component="crash_controller", event_type=event_type))


@dataclass
class FakeCommandRunner:
    outputs: dict[tuple[str, ...], str] = field(default_factory=dict)
    commands: list[list[str]] = field(default_factory=list)

    def __call__(self, command: list[str], capture: bool):
        self.commands.append(command)
        stdout = self.outputs.get(tuple(command), "")
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

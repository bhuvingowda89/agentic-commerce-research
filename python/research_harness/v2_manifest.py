from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .models import FailureScenario
from .v2_config import ConfigurationError, configuration


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class ManifestCell:
    cell_id: str
    configuration: str
    scenario: FailureScenario
    failure_rate: float
    concurrency: int
    transactions: int
    repetitions: int
    paired: bool = False
    paired_target: str | None = None
    primary_metric: str | None = None
    primary_invariant: str | None = None


@dataclass(frozen=True)
class ExperimentManifest:
    manifest_id: str
    campaign: str
    result_root: Path
    cells: tuple[ManifestCell, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ExperimentManifest:
        result_root = Path(str(payload.get("resultRoot", "results/v2")))
        if not _is_v2_result_root(result_root):
            raise ManifestError("v2 manifests must target results/v2 or a child directory")
        raw_cells = payload.get("cells")
        if not isinstance(raw_cells, list) or not raw_cells:
            raise ManifestError("manifest requires at least one cell")
        cells = tuple(_cell_from_dict(cell) for cell in raw_cells)
        return cls(
            manifest_id=str(payload["manifestId"]),
            campaign=str(payload["campaign"]),
            result_root=result_root,
            cells=cells,
        )

    @classmethod
    def load(cls, path: Path) -> ExperimentManifest:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def validate(self) -> None:
        seen = set()
        for cell in self.cells:
            if cell.cell_id in seen:
                raise ManifestError(f"duplicate cell id: {cell.cell_id}")
            seen.add(cell.cell_id)
            try:
                configuration(cell.configuration)
            except ConfigurationError as exc:
                raise ManifestError(str(exc)) from exc
            if cell.failure_rate < 0.0 or cell.failure_rate > 1.0:
                raise ManifestError(f"invalid failure rate for {cell.cell_id}")
            if cell.concurrency < 1 or cell.transactions < 1 or cell.repetitions < 1:
                raise ManifestError(f"invalid workload dimensions for {cell.cell_id}")


def _cell_from_dict(payload: object) -> ManifestCell:
    if not isinstance(payload, dict):
        raise ManifestError("cell must be an object")
    return ManifestCell(
        cell_id=str(payload["cellId"]),
        configuration=str(payload["configuration"]),
        scenario=FailureScenario(str(payload["scenario"])),
        failure_rate=float(payload["failureRate"]),
        concurrency=int(payload["concurrency"]),
        transactions=int(payload["transactions"]),
        repetitions=int(payload["repetitions"]),
        paired=bool(payload.get("paired", False)),
        paired_target=str(payload["pairedTarget"]) if payload.get("pairedTarget") else None,
        primary_metric=str(payload["primaryMetric"]) if payload.get("primaryMetric") else None,
        primary_invariant=str(payload["primaryInvariant"]) if payload.get("primaryInvariant") else None,
    )


def _is_v2_result_root(path: Path) -> bool:
    parts = path.parts
    return any(parts[index] == "results" and parts[index + 1] == "v2" for index in range(len(parts) - 1))

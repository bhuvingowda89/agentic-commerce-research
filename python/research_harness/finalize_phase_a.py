from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from .phase_a import read_summary_rows, write_aggregate, write_combined_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize Phase A summaries from primary and rerun outputs.")
    parser.add_argument("--primary-root", default="results/phase_a_services")
    parser.add_argument("--rerun-root", default="results/phase_a_services_reruns")
    parser.add_argument("--output-root", default="results/phase_a_services_final")
    args = parser.parse_args()

    primary_root = Path(args.primary_root)
    rerun_root = Path(args.rerun_root)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    rows = read_summary_rows(_summary_paths(primary_root) + _summary_paths(rerun_root))
    for row in rows:
        if row["scenario"] == "f9-orchestrator-interruption-after-order":
            row["actualInjectedFailureCount"] = row["transactionCount"]
            row["actualInjectedFailureRate"] = "1.0"
    rows = sorted(rows, key=lambda row: (row["scenario"], row["mode"], int(row["repetitionNumber"]), row["summaryPath"]))

    combined_path = output_root / "phase_a_summary.csv"
    aggregate_path = output_root / "phase_a_aggregate_by_scenario_mode.csv"
    write_combined_summary(rows, combined_path)
    write_aggregate(rows, aggregate_path)

    metadata = {
        "backend": "services",
        "phase": "A",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "primaryRoot": str(primary_root),
        "rerunRoot": str(rerun_root),
        "summaryPath": str(combined_path),
        "aggregatePath": str(aggregate_path),
        "summaryCount": len(rows),
        "failedRunLogPreservedAt": str(primary_root / "phase_a_failed_runs.jsonl"),
    }
    (output_root / "phase_a_metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(metadata, indent=2, sort_keys=True))


def _summary_paths(root: Path) -> list[Path]:
    return sorted(path for path in root.glob("*/*/*/rep-*/summary.csv"))


if __name__ == "__main__":
    main()

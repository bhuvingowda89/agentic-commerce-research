# V2 Technical Infrastructure

This document describes the Phase V2.1/V2.2 infrastructure. It does not define or execute a final experiment campaign.

## Result namespace

All future v2 artifacts must live under `results/v2/`. Historical result directories such as `results/phase_a_services_final`, `results/phase_b1_services`, and `results/phase_b2_services` are outside the v2 namespace and must not be targeted by v2 run stores or manifests.

The implemented run-store layout is:

```text
results/v2/
  runs/
    <run_id>/
      config.json
      metadata.json
      events.jsonl
      failed-run.json
```

Future runners can add per-transaction observations, summaries, service logs, and mechanism-specific event streams inside the same immutable run directory. `V2RunStore.create_run()` uses `mkdir(..., exist_ok=False)`, so an existing `run_id` fails safely instead of being overwritten.

## Manifest schema

The manifest is machine-readable JSON. The parser is intentionally small and strict enough for preflight validation.

```json
{
  "manifestId": "example-v2",
  "campaign": "pilot",
  "resultRoot": "results/v2/example",
  "cells": [
    {
      "cellId": "cell-001",
      "configuration": "C1",
      "scenario": "f0-no-failure",
      "failureRate": 0.0,
      "concurrency": 1,
      "transactions": 10,
      "repetitions": 2,
      "paired": true,
      "pairedTarget": "C0",
      "primaryMetric": "logicalTransactionSuccessRate",
      "primaryInvariant": "I2"
    }
  ]
}
```

Validation rejects historical result roots, duplicate cell IDs, unknown configurations, invalid failure rates, and non-positive workload dimensions.

## Event schema

Events are JSONL records using `EventRecord` from `python/research_harness/v2_events.py`.

Core fields:

- `event_id`
- `run_id`
- `logical_transaction_id`
- `attempt_id`
- `timestamp`
- `component`
- `event_type`
- `mechanism`
- `scenario`
- `operation`
- `state_before`
- `state_after`
- `side_effect_status`
- `failure_type`
- `retry_number`
- `metadata`

Fields that are not reliably known for an event are omitted from serialized JSON. This keeps the schema explicit without forcing fake values.

Defined event types include transaction lifecycle, injected failure, retry, reconciliation, compensation, recovery, duplicate detection, idempotent side-effect reuse, invariant evaluation, and run failure events.

## Mechanism configuration model

Configurations are explicit named presets, not seven unconstrained booleans.

Implemented presets:

- `C0`: random identity, no mechanisms.
- `C1`: deterministic identity.
- `C2`: deterministic identity + durable state.
- `C3`: deterministic identity + durable state + bounded retry.
- `C4`: deterministic identity + durable state + idempotent side-effect lookup.
- `C5`: deterministic identity + durable state + idempotent side-effect lookup + lost-response reconciliation.
- `C6`: deterministic identity + durable state + compensation.
- `C7`: deterministic identity + durable state + idempotent side-effect lookup + restart recovery.
- `C8`: full resilient bundle.

Phase V2.2 establishes the validated configuration model. It does not yet implement corrected A0/A1 runtime behavior for services experiments; that belongs to Phase V2.3.

## Dependency validation

The validator rejects semantically invalid combinations:

- `restart_recovery` requires `durable_state`.
- `lost_response_reconciliation` requires `idempotent_side_effect_lookup`.
- `lost_response_reconciliation` requires deterministic identity.
- `idempotent_side_effect_lookup` requires deterministic identity.
- `compensation` requires durable state or deterministic identity.
- runner reconciliation cannot be enabled unless `lost_response_reconciliation` is enabled.
- random identity cannot enable `deterministic_identity`.

## Provenance capture

`V2RunStore.create_run()` writes:

- run ID;
- run configuration;
- mechanism configuration;
- scenario, failure rate, concurrency, transaction count, repetition, seed;
- backend and execution mode;
- service timeout configuration;
- retry and reconciliation configuration;
- git commit, branch, dirty status;
- OS/platform, CPU count, memory where obtainable;
- Java, Python, Docker, Docker Compose, and PostgreSQL versions where available.

Unavailable external version probes are recorded as `UNAVAILABLE:<reason>`.

## Failed-run handling

`V2RunContext.record_failure()` writes `failed-run.json` and appends a `RUN_FAILED` event to `events.jsonl`. Partial events already written to the run directory are preserved. Future analysis must include failed-run records rather than silently dropping them.

## Runner-side reconciliation boundary

Historical `run_experiment()` behavior is preserved when no v2 configuration is supplied. Services-backend reconciliation still runs by default for historical Phase A/B1/B2 semantics.

For future v2 runs, `run_experiment(..., v2_configuration=config)` uses `config.runner_reconciliation_enabled`. Configurations without `lost_response_reconciliation` cannot enable runner reconciliation, preventing the harness from silently repairing outcomes in retry-only or non-reconciliation variants.

## V2 invariant instrumentation

`evaluate_v2_invariants()` provides versioned v2 checks for:

- I1 at most one successful payment;
- I2 completed implies valid order and successful payment;
- I3 at most one order;
- I4 compensated transaction leaves no active order;
- I5 recovery preserves transaction identity;
- I6 terminal coordinator/downstream consistency.

These checks are future v2 instrumentation only. They do not reinterpret historical invariant values.

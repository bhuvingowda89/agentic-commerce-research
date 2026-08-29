# V2.7 Final Campaign Proposal

This is a proposal only. It is not a frozen manifest and it does not authorize running the final campaign.

## Proposed Design

- Primary cells: retain the 23-cell matrix from `docs/V2_PRIMARY_MATRIX_REVIEW.md`.
- Ordinary repetitions: 8 independent repetitions per primary ordinary cell.
- Ordinary transactions/run: 2,000 logical transactions.
- Ordinary concurrency: 50.
- Probabilistic failure rate for primary F5/F11/F12 cells: 0.10.
- F8 duplicate workload: 2,000 logical transactions/run, concurrent duplicate attempt per logical key.
- Crash repetitions: 8-10 independent crash/restart trials per crash cell.
- Crash transactions/run: 1 controlled target transaction per independent crash trial.
- Crash concurrency: 1.
- Pairing: use identical run-level seeds and deterministic logical transaction IDs within each comparison family. Treat C0/F8 as paired by duplicate workload and seed, not by deterministic execution transaction ID.

## Analysis Rules

- Analyze independent runs, not transactions, as replicates.
- Report per-run metrics and paired run differences.
- Compute descriptive mean differences, standard deviations, t-based 95% confidence intervals, and coefficients of variation where useful.
- Do not use pilot results as final evidence.
- Preserve all failed and anomalous final runs as first-class artifacts.
- Categorize failed/anomalous runs as scientific outcome, infrastructure failure, implementation defect, configuration error, environment saturation, or unknown before any replacement run.

## Required Pre-Freeze Changes

- Add explicit service-side event instrumentation for retry, retry exhaustion, side-effect lookup/reuse, system reconciliation, runner reconciliation, compensation, and restart recovery.
- Review F5/C3 because payment-service idempotency masks duplicate payment effects. Either revise the primary metric for C3/F5 to timeout/terminal outcome and cost, or redesign F5 duplicate-side-effect semantics before freeze.
- Update crash cells P16-P18 to one independent controlled crash event per run.

## Planned Robustness Experiments

- Failure-rate robustness for F5/F11/F12 at 1%, 5%, 10%, and 20%, after the primary campaign is frozen.
- Supplemental historical-continuity comparisons only after primary analyses are locked.

## Stopping and Run Handling

- No overwrite of existing V2 run IDs.
- Do not modify historical Phase A/B1/B2 result directories.
- Stop the campaign if Compose saturation, connection-pool exhaustion, PostgreSQL bottleneck, or unplanned harness repair appears in more than one run family.
- Replace infrastructure-defect runs only with a new run ID, preserving the failed run and documenting cause, code/config change, and replacement ID.

## Proposed Cell Classification

KEEP: P01, P02, P03, P04, P05, P06, P07, P08, P10, P11, P12, P13, P14, P15, P19, P20, P21, P22, P23.

MODIFY: P09, P16, P17, P18.

REMOVE: none.

SUPPLEMENTAL: none added from pilot results.


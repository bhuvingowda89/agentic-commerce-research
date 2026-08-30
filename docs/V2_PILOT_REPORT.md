# V2.6 Pilot Report

**NOT FINAL SCIENTIFIC EVIDENCE.** This document reports Phase V2.6 pilot behavior only. It must not be used as final paper evidence.

## 1. Commit and Matrix

- V2.5 checkpoint commit used for pilot: `f6202e232933783e86a94dc2596fe89b7d1c2938`.
- Branch: `mechanism-isolation-v2`.
- Pilot artifact root: `results/v2/pilot/`.
- Exact matrix: see `docs/V2_PILOT_MATRIX.md`.
- Planned runs: 48.
- Completed runs: 48.
- Failed/anomalous run artifacts: 0 `failed-run.json` files. One valid scientific/design anomaly was observed: C3 under F5 does not isolate retry-induced duplicate side effects because downstream payment idempotency absorbs repeated payment calls.

## 2. Mechanism Activation Audit

| Family | Pilot cells | Activation result |
|---|---|---|
| Identity / duplicates | C0, C1, C4 under F8 | Activated. C0 produced high duplicate-payment and invariant-violation rates; C1/C4 did not. |
| Pre-side-effect retry | C1, C3 under F11 | Activated. C3 operation retries matched injected failures and restored logical success to 1.0. |
| Post-side-effect ambiguity | C1, C3, C4, C5 under F5 | Activated, but C3 is confounded by downstream payment idempotency. C5 reconciled all injected ambiguous payments without runner repair. |
| Compensation | C1, C6 under F12 | Activated. C6 compensated exactly the injected permanent payment failures with zero invariant violations. |
| True crash/recovery | C2, C7 | Activated. C2 rejected restart recovery; C7 recovered all trials after external orchestrator kill/restart. |
| F0 cost | C0, C2, C8 | Executable. Throughput decreased as durable/full-bundle mechanisms were added. |

## 3. Pilot Findings

Run-level means across three repetitions:

| Scenario | Config | Logical success | Violations | Duplicate payments | Compensation | Throughput txn/s | P95 latency ms |
|---|---|---:|---:|---:|---:|---:|---:|
| F8 | C0 | 1.000 | 0.976 | 0.942 | 0.000 | 417.6 | 190.2 |
| F8 | C1 | 1.000 | 0.000 | 0.000 | 0.000 | 732.2 | 101.6 |
| F8 | C4 | 1.000 | 0.000 | 0.000 | 0.000 | 425.5 | 165.7 |
| F11 | C1 | 0.898 | 0.102 | 0.000 | 0.000 | 680.9 | 111.8 |
| F11 | C3 | 1.000 | 0.000 | 0.000 | 0.000 | 595.5 | 125.2 |
| F5 | C1 | 0.898 | 0.102 | 0.000 | 0.000 | 553.5 | 517.0 |
| F5 | C3 | 0.898 | 0.000 | 0.000 | 0.000 | 222.2 | 1522.9 |
| F5 | C4 | 0.898 | 0.000 | 0.000 | 0.000 | 350.6 | 558.2 |
| F5 | C5 | 1.000 | 0.000 | 0.000 | 0.000 | 355.0 | 567.9 |
| F12 | C1 | 0.898 | 0.102 | 0.000 | 0.000 | 823.3 | 85.4 |
| F12 | C6 | 0.898 | 0.000 | 0.000 | 0.102 | 534.6 | 136.8 |
| F0 | C0 | 1.000 | 0.000 | 0.000 | 0.000 | 831.7 | 104.6 |
| F0 | C2 | 1.000 | 0.000 | 0.000 | 0.000 | 621.1 | 119.5 |
| F0 | C8 | 1.000 | 0.000 | 0.000 | 0.000 | 464.6 | 149.4 |

Injected failure counts for F5/F11/F12 were 106, 109, and 91 for seeds `2026082900`, `2026082901`, and `2026082902`, respectively. This is close to the intended 10% rate and gives enough per-run signal for pilot assessment.

## 4. Crash/Recovery Pilot

The true-crash pilot used one controlled transaction/crash event per independent run. This is the recommended final crash experimental unit because one externally killed orchestrator instance is the independent intervention.

| Config | Trials | Recovery completed | Mean downtime ms | Mean recovery latency ms | Mean crash-to-terminal ms |
|---|---:|---:|---:|---:|---:|
| C2 | 3 | 0/3 | 1690.3 | 31.7 | 2079.0 |
| C7 | 3 | 3/3 | 1649.4 | 123.9 | 2077.1 |

C2 must be described as: durable coordinator state without retry, lost-response reconciliation, compensation, or restart recovery, under the existing coordinator uniqueness constraint.

## 5. Paired Seeds and Variability

Paired seed audit artifact: `results/v2/pilot/analysis/paired-seed-audit.json`.

- C1-C8 ordinary probabilistic cells used the same run-level seeds and exact deterministic transaction IDs, so F5/F11/F12 failure keys paired exactly.
- C0 under F8 used the same run-level seed, but random execution IDs mean exact probabilistic failure assignment would not be guaranteed if a stochastic failure scenario were used. F8 itself is duplicate-schedule based, so the duplicate workload remained comparable.
- Run-level paired differences had stable correctness estimates with 95% pilot CI half-width about 0.024 for 10% F5/F11/F12 effects.
- Performance variability was materially larger. Example: F0 C8-C0 throughput difference mean -367 txn/s, pilot CI half-width 260 txn/s.

## 6. Reconciliation Attribution

Reconciliation attribution artifact: `results/v2/pilot/analysis/reconciliation-attribution-audit.json`.

For all C5/F5 runs:

- system/orchestrator reconciliation inferred: 106, 109, 91 transactions;
- runner reconciliation attempted: 0;
- runner reconciliation completed: 0;
- material runner repair: false.

Conclusion: C5/F5 pilot outcomes are attributable to the system/orchestrator reconciliation path, not hidden harness repair. The current artifact infers system reconciliation from final completion of injected F5 cases; final V2.7 should add first-class service event logging for reconciliation attempts and side-effect lookup/reuse.

## 7. Performance Sanity

Compose status after pilot: all five services healthy. Current `docker stats --no-stream` showed low CPU and memory below 364 MiB/service. No Hikari pool exhaustion, PostgreSQL bottleneck, or connection-pool exhaustion warning was observed in the inspected logs. Expected exception stack traces were present for injected failures and C2 recovery rejection.

Concurrency 50 is executable. Latency under F5/C3 is high because retry waits on repeated payment response-loss timeouts; this is mechanism behavior plus downstream idempotency, not obvious container saturation.

## 8. Recommendations

- Final ordinary transaction count: 2,000 logical transactions/run. The 1,000-run pilot is already informative, but 2,000 gives more stable within-run rare-event estimates without changing the experimental unit.
- Final ordinary repetitions: 8 remains reasonable. Correctness variability is low, while performance variability is high enough that fewer than 8 would be weak for RQ4.
- Final crash repetitions: use 8-10 independent crash/restart trials per crash cell, each with one controlled target transaction.
- Final primary concurrency: keep 50 for ordinary cells; keep 1 for crash cells.
- C5/C8 reconciliation: add explicit event instrumentation before freeze so reconciliation attribution is measured rather than inferred.

## 9. Primary Matrix Impact

| Cell | Recommendation | Reason |
|---|---|---|
| P01 C0/F8 | KEEP | Strong identity negative control. |
| P02 C1/F8 | KEEP | Isolates deterministic identity/downstream uniqueness from C0. |
| P03 C4/F8 | KEEP | Adds lookup cost/behavior under duplicate load. |
| P04 C8/F8 | KEEP | Full-bundle duplicate-load cost remains useful. |
| P05 C1/F11 | KEEP | No-retry comparator. |
| P06 C3/F11 | KEEP | Retry activates and changes correctness. |
| P07 C8/F11 | KEEP | Full-bundle retry cost. |
| P08 C1/F5 | KEEP | Ambiguity comparator. |
| P09 C3/F5 | MODIFY | Current service backend does not isolate duplicate side-effect risk; downstream payment idempotency masks retries. Use a metric focused on terminal failure/timeout cost or redesign payment duplicate semantics before final freeze. |
| P10 C4/F5 | KEEP | Lookup without catch-path reconciliation remains distinct from C5. |
| P11 C5/F5 | KEEP | Reconciliation works without runner repair. |
| P12 C8/F5 | KEEP | Full-bundle ambiguity cost, after explicit event logging. |
| P13 C1/F12 | KEEP | No-compensation comparator. |
| P14 C6/F12 | KEEP | Compensation activates cleanly. |
| P15 C8/F12 | KEEP | Full-bundle compensation cost. |
| P16 C2/crash | MODIFY | Use one controlled crash transaction per independent trial, not 100 transactions/run. |
| P17 C7/crash | MODIFY | Same crash experimental-unit change. |
| P18 C8/crash | MODIFY | Same crash experimental-unit change. |
| P19 C0/F0 | KEEP | Cost baseline. |
| P20 C1/F0 | KEEP | Deterministic identity cost comparator. |
| P21 C2/F0 | KEEP | Durable-state cost comparator. |
| P22 C5/F0 | KEEP | Reconciliation-capable path cost. |
| P23 C8/F0 | KEEP | Full-bundle cost. |

Recommended final primary matrix cell count remains 23, with three crash cells modified to one crash event/run and one F5/C3 metric/design caveat requiring review.

## 10. Readiness

RQ1-RQ4 remain supportable and H1-H6 remain falsifiable, subject to resolving the F5/C3 isolation issue and adding explicit reconciliation event instrumentation. V2.7 should not be frozen until those two items are reviewed.


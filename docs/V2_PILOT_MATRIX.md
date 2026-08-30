# V2.6 Pilot Matrix

This is a Phase V2.6 pilot plan only. Pilot outputs are **NOT FINAL SCIENTIFIC EVIDENCE** and must not be used as final paper evidence.

Pilot output root: `results/v2/pilot/`.

## Planned Cells

| Pilot cell ID | Configuration | Scenario | Failure rate | Concurrency | Transactions/run | Repetitions | Paired comparator | Primary metric | Purpose |
|---|---|---|---:|---:|---:|---:|---|---|---|
| PV2-F8-C0 | C0 | F8 concurrent duplicate transaction requests | 1.0 | 50 | 1,000 | 3 | C1, C4 | duplicate payment rate | Identity/duplicate negative control with fresh execution IDs. |
| PV2-F8-C1 | C1 | F8 concurrent duplicate transaction requests | 1.0 | 50 | 1,000 | 3 | C0, C4 | duplicate payment rate | Deterministic identity comparator. |
| PV2-F8-C4 | C4 | F8 concurrent duplicate transaction requests | 1.0 | 50 | 1,000 | 3 | C0, C1 | duplicate payment rate | Idempotent lookup under duplicate load. |
| PV2-F11-C1 | C1 | F11 transient payment failure recovery | 0.10 | 50 | 1,000 | 3 | C3 | logical transaction success rate | No-retry comparator. |
| PV2-F11-C3 | C3 | F11 transient payment failure recovery | 0.10 | 50 | 1,000 | 3 | C1 | logical transaction success rate | Bounded retry activation. |
| PV2-F5-C1 | C1 | F5 payment succeeds, response lost | 0.10 | 50 | 1,000 | 3 | C3, C4, C5 | invariant violation rate | Ambiguous side-effect comparator without retry/reconciliation. |
| PV2-F5-C3 | C3 | F5 payment succeeds, response lost | 0.10 | 50 | 1,000 | 3 | C1, C4, C5 | duplicate payment rate | Retry without lost-response reconciliation. |
| PV2-F5-C4 | C4 | F5 payment succeeds, response lost | 0.10 | 50 | 1,000 | 3 | C1, C3, C5 | duplicate payment rate | Idempotent lookup without catch-path reconciliation. |
| PV2-F5-C5 | C5 | F5 payment succeeds, response lost | 0.10 | 50 | 1,000 | 3 | C1, C3, C4 | recovery attempted rate | Lost-response reconciliation attribution audit. |
| PV2-F12-C1 | C1 | F12 compensation failure retry | 0.10 | 50 | 1,000 | 3 | C6 | orphaned order rate | No-compensation comparator. |
| PV2-F12-C6 | C6 | F12 compensation failure retry | 0.10 | 50 | 1,000 | 3 | C1 | compensation rate | Compensation and compensation retry behavior. |
| PV2-CRASH-C2 | C2 | true crash after order persisted | deterministic | 1 | 1 | 3 | C7 | recovery completed rate | Durable coordinator state without restart recovery under existing uniqueness constraint. |
| PV2-CRASH-C7 | C7 | true crash after order persisted | deterministic | 1 | 1 | 3 | C2 | recovery completed rate | Restart recovery after external orchestrator kill/restart. |
| PV2-F0-C0 | C0 | F0 no failure | 0.0 | 50 | 1,000 | 3 | C2, C8 | throughput | No-failure random-identity cost sanity. |
| PV2-F0-C2 | C2 | F0 no failure | 0.0 | 50 | 1,000 | 3 | C0, C8 | throughput | No-failure durable coordinator-state cost sanity. |
| PV2-F0-C8 | C8 | F0 no failure | 0.0 | 50 | 1,000 | 3 | C0, C2 | throughput | No-failure full-bundle cost sanity. |

Total planned pilot runs: 48.

## Adjustments

- The true-crash pilot uses one controlled logical transaction per crash trial. The experimental unit is the independent crash/restart trial, not multiple transactions sharing one orchestrator lifetime.
- C8 is not included in ordinary F8/F11/F5/F12 pilots to keep V2.6 compact; C8 is retained in F0 and may remain in the proposed final matrix as the full-bundle cost/continuity cell.
- C2 is described as durable coordinator state without retry, lost-response reconciliation, compensation, or restart recovery, under the existing coordinator uniqueness constraint.

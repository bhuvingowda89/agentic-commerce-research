# V2.7R P07 Root Cause

Status: remediation diagnosis only; not V2.8 interpretation.

## Issue

P06 (`C3/F11`) recorded 1,607 `RETRY_ATTEMPT` and 1,607 `RETRY_SUCCEEDED` events, while P07 (`C8/F11`) recorded zero `RETRY_*` events even though C8 includes bounded retry.

## Evidence

- C8 is configured with bounded retry in `python/research_harness/v2_config.py` and `V2MechanismPolicy.fromConfiguration("C8")`.
- The orchestrator payment path wraps `executePaymentWithPolicy(...)` in `attemptWithPolicy(...)`; when `boundedRetry()` is true, `attemptWithPolicy` enters `retry(...)`.
- F11 is injected by `payment-simulator` before payment persistence in `FailureInjection.before(...)`.
- P07 summaries recorded F11-selected logical transactions, but `retryCount` and `operationRetryCount` remained zero for all P07 runs.
- P07 event streams contain `IDEMPOTENT_LOOKUP_ATTEMPT` / `IDEMPOTENT_LOOKUP_NOT_FOUND` for `execute_payment`, proving the payment path was reached.
- P06, which executed earlier with the same logical transaction ids, consumed the payment simulator's in-memory F11 transient-attempt counter.

## Root Cause

The payment simulator tracks F11 transient attempts in an in-memory map keyed only by:

`operation + ":" + transactionId`

It does not include seed, idempotency key, run id, or campaign cell. The V2 reset truncated PostgreSQL tables but did not restart or otherwise clear this in-memory map.

Because P06/C3/F11 ran before P07/C8/F11 with the same deterministic transaction ids (`tx-logical-000000` ...), the F11 attempts for those transaction ids had already exceeded the transient-failure threshold. P07 therefore reached the payment path but the payment simulator no longer threw the transient pre-side-effect exception. Retry was enabled but had no exception to retry.

## Decision Category

Category D: `FAILURE_INJECTION_DEFECT`.

F11 was selected by the deterministic schedule, but it was not delivered to C8 as intended because failure-injection attempt state leaked across runs.

## P07 Validity

Original P07 runs are scientifically invalid for the frozen P07 mechanism-activation requirement. They must be superseded and rerun after fixing reset isolation.

## P12 C8/F5 Audit

P12/C8/F5 is an expected full-bundle mechanism interaction:

- F5 post-side-effect payment response loss was injected.
- A successful payment effect existed after the timed-out first payment call.
- Bounded retry re-entered the payment operation.
- The idempotent side-effect lookup ran before the retried payment call and found the existing committed effect.
- Catch-path `RECONCILIATION_*` was unnecessary in C8 for those cases.
- Runner reconciliation remained zero.

Therefore P12 should be preserved, but it should not be described as independently demonstrating explicit catch-path reconciliation. P11/C5/F5 remains the clean reconciliation condition.

## Remediation

- Reset isolation must clear payment-simulator F11 in-memory attempt state between runs.
- The selected correction restarts `payment-simulator` after every approved V2 database reset.
- The seed driver must pass `BASE_SEED` to the runner with `repetition_start = repetition`, so the runner applies the frozen `seed = baseSeed + repetitionIndex - 1` exactly once.

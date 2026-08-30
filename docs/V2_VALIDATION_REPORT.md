# V2.5 Validation Report

This report covers Phase V2.5 experimental validation only. It does not report pilot data, final campaign data, statistical tests, or manuscript results.

## 1. Configuration Semantic Audit

| Config | deterministic_identity | durable_state | idempotent_side_effect_lookup | bounded_retry | lost_response_reconciliation | compensation | restart_recovery | runner_reconciliation | Hidden/prerequisite behavior | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| C0 | no | no | no | no | no | no | no | no | Fresh execution identity per attempt; logical key retained for analysis | PASS |
| C1 | yes | no | no | no | no | no | no | no | Downstream deterministic IDs and DB uniqueness may suppress duplicates | PASS |
| C2 | yes | yes | no | no | no | no | no | no | `orchestrator_transactions.idempotency_key` uniqueness couples durable state with coordinator idempotency | LIMITATION |
| C3 | yes | yes | no | yes | no | no | no | no | Retry is bounded by orchestrator `retry.maxAttempts` | PASS |
| C4 | yes | yes | yes | no | no | no | no | no | Lookup depends on service inspect endpoints by idempotency key | PASS |
| C5 | yes | yes | yes | no | yes | no | no | yes | System reconciliation and runner reconciliation are both allowed only for C5/C8; future analysis must distinguish them | PASS |
| C6 | yes | yes | no | no | no | yes | no | no | Compensation retry is part of compensation behavior | PASS |
| C7 | yes | yes | yes | no | no | no | yes | no | Restart recovery requires deterministic identity, durable state, and side-effect lookup | PASS |
| C8 | yes | yes | yes | yes | yes | yes | yes | yes | Full bundle; useful for continuity but not causal isolation by itself | PASS |

Runtime validation came from Java service-path unit tests in `TransactionServiceV2MechanismPolicyTest` plus Python harness validation tests. Historical `baseline` and `resilient` behavior remains routed without `X-V2-Configuration`.

## 2. Mechanism-Isolation Results

PASS:

- C0 and C1 preserve the scientific distinction between logical transaction identity and execution/service identity.
- C2 persists coordinator records and rejects explicit restart recovery.
- C3 retries deterministic pre-side-effect transient payment failures and records retry attempts.
- C4 reuses existing deterministic side effects before issuing a downstream call and does not reconcile a lost response in the catch path.
- C5 reconciles post-side-effect response loss by inspecting service state after a response-loss exception.
- C6 compensates after permanent payment failure and retries compensation.
- C7 recovers a nonterminal durable record after true external orchestrator restart.
- C8 exercises retry, reconciliation, and compensation as the full bundle.

LIMITATION:

- C2 is not pure "state persistence only" in a mathematical sense because the database schema has a unique idempotency key. The final design should describe C2 as durable coordinator state with stable coordinator identity, not as a fully independent state-machine persistence mechanism detached from identity.

## 3. Failure-Semantics Validation

PASS:

- F11 validation uses a pre-side-effect transient payment failure. Retry can activate without reconciliation or compensation in C3.
- F5 validation uses payment response loss after a successful payment side effect. C5 catch-path reconciliation can inspect and reuse the existing effect.
- F12 validation uses permanent payment failure after order creation, then compensation with an injectable first compensation failure.
- True crash validation uses external Docker `SIGKILL`, not a Java exception, after durable `ORDER_CREATED` state is observable.

LIMITATION:

- F4 and F6 were inspected as distinct candidate supplemental semantics but not executed in V2.5. F4 remains useful as a pre-side-effect timeout contrast; F6 remains useful for checking whether response-loss conclusions generalize beyond payment.

## 4. Invariant Validation

PASS:

- I1: multiple successful payments per logical/idempotency key are detected.
- I2: COMPLETED without matching order/payment is detected.
- I3: multiple orders per logical/idempotency key are detected.
- I4: COMPENSATED with active order is detected.
- I5: recovered coordinator record whose service effects use a different transaction identity is detected.
- I6: terminal coordinator/downstream inconsistency is detected.

C0 duplicate validation confirms that fresh execution IDs do not hide duplicate order/payment effects because v2 invariant grouping uses the logical idempotency key.

## 5. Metric Validation

PASS:

- Synthetic known-value tests validate attempt count, logical transaction count, attempt success, logical success, duplicate payment count, compensation count, retry totals, P50, P95, and P99 fields.
- Safe compensation remains separate from purchase success because `COMPENSATED` is not counted as `COMPLETED`.

LIMITATION:

- P99 is mechanically computed for any sample size by the existing summary writer. The final analysis plan should decide when P99 is reported as meaningful rather than relying only on the writer output.

## 6. Paired-Seed Validation

PASS:

- Paired C0/C1 validation runs with the same base seed produce matched repetition seeds.
- Different repetitions receive incremented seeds.
- C0 random execution IDs do not alter the paired repetition seed recorded by the runner.

LIMITATION:

- For service-backend stochastic failure schedules, final validation should additionally compare injected-failure transaction indices across paired C2-C8 runs after the full V2.6 pilot harness exists.

## 7. Artifact and Provenance Validation

PASS:

- V2 run directories use `mkdir(..., exist_ok=False)` and fail on overwrite.
- `config.json`, `metadata.json`, `events.jsonl`, per-transaction observations, summary artifacts, and `failed-run.json` are preserved.
- Failed runs append a `RUN_FAILED` event and remain visible as first-class artifacts.
- Result stores reject historical Phase A/B1/B2 result roots.

Validation artifact:

- `results/v2/validation/runs/v2-validation-20260829T043101Z`
- Compose service logs: `results/v2/validation/runs/v2-validation-20260829T043101Z/logs`

This artifact is synthetic schema validation only. It is not experiment evidence.

## 8. Reset Validation

PASS:

- The V2 crash controller reset command targets only `orchestrator_transactions`, `carts`, `orders`, and `payments`.
- The reset path does not reference any `results/` directory.
- The Docker crash integration confirmed PostgreSQL stayed alive across orchestrator kill/restart.

## 9. Compose and Environment Sanity

PASS:

- `docker-compose -f docker-compose.v2.yml config` succeeded.
- V2 Java service images built.
- V2 Compose stack started with PostgreSQL, Redis, cart-service, order-service, payment-simulator, and orchestrator.
- Opt-in true crash integration passed.

WARNING:

- Docker Compose emitted `Docker Compose requires buildx plugin to be installed` and then successfully used the classic builder. This should be documented as an environment warning before frozen runs.
- Redis remains provisioned but unused in the measured path.

## 10. Unresolved Issues

- C2 includes unavoidable durable coordinator idempotency through the existing unique idempotency-key schema.
- C4/C5 separation is valid in code, but the paper must explain that both depend on deterministic identity and inspectable downstream services.
- C5/C8 allow runner-side reconciliation by configuration; final runs must record whether a terminal outcome came from system-side handling or runner recovery/reconciliation.
- F4/F6 remain supplemental candidates, not validated campaign cells.
- Java mechanism activations are currently visible through state, retry counters, inspect/cancel calls, and harness events, not a separate Java event stream.

## 11. Primary Matrix Impact

The 23-cell primary matrix in `docs/V2_PRIMARY_MATRIX_REVIEW.md` remains supportable with the current implementation.

Recommended final adjustments before freezing a manifest:

- Retain P01-P23 as proposed.
- Do not re-add C2/F11 or C2/F12 to primary; V2.5 confirms they do not add unique mechanism evidence beyond negative-control interpretation.
- Do not re-add C1/true-crash to primary; C2 is the cleaner negative control because durable state exists but restart recovery is disabled.
- Keep C4/F5 because V2.5 shows it distinguishes pre-operation existing-effect lookup from C5 catch-path reconciliation.
- Keep C5/F0 rather than both C4/F0 and C5/F0 unless V2.6 pilots show lookup overhead differs materially from reconciliation-capable path overhead.
- Consider a supplemental F4 or F6 validation later, but do not add either to the primary matrix yet.

## 12. Readiness Decision for V2.6

PASS with limitations.

The apparatus is ready for V2.6 pilot design review, provided the limitations above are explicitly carried forward. V2.6 should remain small and should primarily verify that service-backend event capture and paired failure schedules behave as expected under the final harness before any frozen campaign is declared.

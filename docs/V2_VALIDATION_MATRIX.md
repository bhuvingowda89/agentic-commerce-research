# V2 Validation Matrix

This matrix records Phase V2.5 apparatus validation only. These cases are not pilot experiments and are not scientific evidence for the paper.

Evidence paths:

- Unit and integration tests: `python/tests/test_v2_infrastructure.py`, `python/tests/test_v2_validation.py`, `python/tests/test_v2_crash_integration.py`, `orchestrator/src/test/java/research/commerce/orchestrator/TransactionServiceV2BaselineTest.java`, `orchestrator/src/test/java/research/commerce/orchestrator/TransactionServiceV2MechanismPolicyTest.java`, `orchestrator/src/test/java/research/commerce/orchestrator/V2CrashInfrastructureTest.java`.
- Synthetic artifact smoke record: `results/v2/validation/runs/v2-validation-20260829T043101Z`.
- V2 service path implementation: `orchestrator/src/main/java/research/commerce/orchestrator/TransactionService.java`, `orchestrator/src/main/java/research/commerce/orchestrator/V2MechanismPolicy.java`.

| ID | Configuration | Scenario | Transactions | Concurrency | Expected activation | Forbidden activation | Expected invariant behavior | Method | Status | Evidence |
|---|---|---|---:|---:|---|---|---|---|---|---|
| V25-01 | C0 | F8 duplicate | 2 logical / 4 attempts | 1 | Fresh execution identity | Durable state, retry, reconciliation, compensation, recovery | I1/I3 violations visible by logical key when duplicates occur | Python simulation unit | PASS | `test_c0_generates_fresh_execution_identity_for_duplicate_attempts`, `test_c0_duplicate_effects_are_grouped_by_logical_idempotency_key` |
| V25-02 | C1 | F8 duplicate | 2 logical / 4 attempts | 1 | Stable execution identity | Retry, reconciliation, compensation, recovery | Duplicate effects are not hidden by changing logical key | Python simulation unit | PASS | `test_c1_preserves_deterministic_execution_identity_for_duplicate_attempts` |
| V25-03 | C0/C1 | F8 duplicate | 2 logical | 1 | Runner observation only | Runner reconciliation | No recovery or reconciliation window fields are set | Python runner unit | PASS | `test_runner_observation_does_not_repair_c0_or_c1_outcomes` |
| V25-04 | C0/C1 | F0 | 1 | 1 | Historical modes remain addressable | Historical mode rewrite | Historical `baseline` and `resilient` semantics unchanged without V2 header | Java unit | PASS | `TransactionServiceV2BaselineTest` |
| V25-05 | C2 | F11 pre-effect transient | 1 | 1 | Durable coordinator record | Retry, reconciliation, compensation, restart recovery | Terminal FAILED with persisted state | Java unit | PASS | `c2PersistsStateButDoesNotRetryReconcileCompensateOrRecover` |
| V25-06 | C2 | true crash after order | 1 | 1 | Durable state remains observable | Automatic recovery | Nonterminal state remains until recovery-enabled config is invoked | Docker crash integration | PASS | `test_true_orchestrator_kill_restart_and_c7_recovery` C2 negative control |
| V25-07 | C3 | F11 pre-effect transient | 1 | 1 | RETRY behavior, retry success | Reconciliation, compensation | COMPLETED after retry budget permits | Java unit | PASS | `c3RetriesPreSideEffectTransientPaymentFailureWithoutReconciliationOrCompensation` |
| V25-08 | C3 | F11 retry exhaustion | 1 | 1 | Retry exhaustion count | Reconciliation, compensation | FAILED after max attempts | Java unit | PASS | `c3RecordsRetryExhaustionWithoutReconciliationOrCompensation` |
| V25-09 | C4 | Existing side effects | 1 | 1 | Existing-effect reuse | Lost-response catch-path reconciliation | COMPLETED using existing deterministic IDs | Java unit | PASS | `c4ReusesExistingSideEffectsButDoesNotReconcileLostResponses` |
| V25-10 | C4 | F5 response lost | 1 | 1 | Side effect may exist | Lost-response reconciliation | FAILED if post-call response is lost and reconciliation is disabled | Java unit | PASS | `c4ReusesExistingSideEffectsButDoesNotReconcileLostResponses` |
| V25-11 | C5 | F5 response lost | 1 | 1 | Reconciliation attempt/found effect | Retry, compensation | COMPLETED after post-side-effect inspection | Java unit + artifact smoke | PASS | `c5ReconcilesPostSideEffectPaymentResponseLoss`, validation artifact |
| V25-12 | C5 | Reconciliation not found | 1 | 1 | Reconciliation attempt/not found | Retry, compensation | FAILED if no side effect exists | Java unit | PASS | `c5FailsWhenReconciliationFindsNoExistingEffect` |
| V25-13 | C6 | F12 compensation failure retry | 1 | 1 | Compensation attempt/retry/success | Retry, reconciliation, recovery | COMPENSATED and safe terminal state | Java unit | PASS | `c6CompensatesAfterPermanentPaymentFailureAndRetriesCompensation` |
| V25-14 | C7 | true crash after order | 1 | 1 | Restart recovery | Retry, lost-response reconciliation, compensation | COMPLETED, identity preserved, no duplicate order/payment | Docker crash integration | PASS | `test_true_orchestrator_kill_restart_and_c7_recovery` |
| V25-15 | C7 | Recover one | 1 | 1 | Recovery from durable record | C3/C2 recovery | C7 accepted; non-recovery configs rejected | Java unit | PASS | `c7AllowsRestartRecoveryButDoesNotEnableRetryReconciliationOrCompensation` |
| V25-16 | C8 | F11/F5/F12 | 1 each | 1 | Retry, reconciliation, compensation | None of approved bundle mechanisms forbidden | Intended union of enabled behaviors | Java unit | PASS | `c8CombinesRetryReconciliationCompensationAndRestartRecovery` |
| V25-17 | any | F5/F11/true-crash | synthetic | n/a | Failure semantic event fields | Missing side-effect classification | Events distinguish pre-effect, post-effect, and crash conditions | Python unit | PASS | `test_failure_semantics_events_are_representable_from_actual_conditions` |
| V25-18 | any | F12 | source inspection + C6 unit | 1 | Permanent downstream failure plus compensation | Counting compensation as purchase success | COMPENSATED separate from COMPLETED | Java unit + metric unit | PASS | `c6...`, `test_known_value_summary_metrics_distinguish_attempt_and_logical_success` |
| V25-19 | any | I1-I6 | synthetic states | n/a | Invariant evaluator | Grouping by execution ID only | I1-I6 violations detected where feasible | Python unit | PASS | `test_v2_invariant_evaluator_*`, `test_v2_invariants_group_c0_duplicate_effects_by_logical_key` |
| V25-20 | any | metrics | synthetic known values | n/a | Summary formulas | Transaction-level pseudo-replication claim | Attempt vs logical success, duplicates, retry, compensation, percentiles | Python unit | PASS | `test_known_value_summary_metrics_distinguish_attempt_and_logical_success` |
| V25-21 | paired configs | F8 | 2 x 2 reps | 1 | Matched repetition seeds | C0 identity changing failure schedule | C0/C1 repetitions use same seeds | Python runner unit | PASS | `test_paired_seed_schedule_is_independent_of_v2_identity_mode` |
| V25-22 | any | artifact smoke | synthetic | n/a | Config, metadata, events, summary, failed-run | Overwrite, hidden failed run | Failed run remains first-class artifact | Python unit + real artifact | PASS | `test_artifact_validation_run_preserves_raw_events_summary_and_failure`, `results/v2/validation/...` |
| V25-23 | Compose | F0 readiness | 1 | 1 | Build/start/health | Fixed-sleep-only readiness | Services build and crash test can use health checks | Docker validation | PASS | `docker-compose -f docker-compose.v2.yml config`, build, opt-in crash integration |
| V25-24 | Compose | reset | n/a | n/a | Explicit table truncate | Result deletion, historical targeting | PostgreSQL remains alive; reset targets only service tables | Python unit + crash integration | PASS | `test_crash_controller_reset_targets_only_service_tables`, crash integration |
| V25-25 | F4/F6 | source inspection | 0 | 0 | Pre-payment timeout, order response loss | Added to primary matrix | Semantics appear distinct but not executed in V2.5 | Source inspection | LIMITATION | `payment-simulator` and `order-service` failure injection code inspected before V2.5; no V2.5 execution |

## Status Counts

- PASS: 24
- FAIL: 0
- LIMITATION: 1
- NOT YET TESTED: 0

## Notes

- C2 has durable coordinator state, but the service path still has the database uniqueness constraint on `orchestrator_transactions.idempotency_key`. This is a hidden prerequisite of the current persistence model and must be described as coordinator durable identity protection, not a fully independent state-machine-only mechanism.
- C4 and C5 are separable in the Java path as pre-operation existing-effect lookup versus catch-path lost-response reconciliation. Both depend on deterministic identity and downstream/service inspectability.
- Docker crash validation uses one deterministic validation transaction. It is not a pilot experiment and must not be reported as final scientific evidence.

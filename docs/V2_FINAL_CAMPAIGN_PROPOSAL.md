# V2.7 Final Campaign Proposal

**READY FOR FREEZE REVIEW - NOT YET EXECUTED.** This is a proposed freeze package only. Do not treat it as a manifest and do not run final scientific cells until reviewed.

## Design Constants

- Ordinary independent unit: one run.
- Ordinary repetitions: 8 independent runs/cell.
- Ordinary transactions/run: 2,000 logical transactions.
- Ordinary concurrency: 50.
- Primary F5/F11/F12 failure probability: 0.10.
- F8 duplicate workload: 2,000 logical transactions/run plus one concurrent duplicate attempt for each logical transaction; duplicate logical schedule and repetition seed are paired across configs. C0 intentionally uses random execution IDs, so execution IDs are not paired.
- Crash independent unit: one externally induced orchestrator crash/restart trial with one target logical transaction, concurrency 1.
- Crash repetitions: 10 independent trials/cell. Ten gives a simple recovery-success proportion denominator and slightly tighter reliability bounds than 8 while keeping crash cost small.
- Result root: future final campaign must use a new `results/v2/...` final-campaign directory, not `results/v2/pilot/`.

## Final Primary Cells

Final primary cell count: 22. P09 C3/F5 is moved to supplemental because downstream payment idempotency masks duplicate-payment effects, so it cannot support a unique causal claim about retry-only protection after ambiguous post-side-effect failure.

| Cell | Decision | Config | Scenario | Failure rate | Concurrency | Tx/run | Reps | Comparator | RQ | H | Primary metric | Exact causal interpretation |
|---|---|---|---|---:|---:|---:|---:|---|---|---|---|---|
| P01 | KEEP | C0 | F8 | 1.0 | 50 | 2,000 | 8 | C1 | RQ1 | H1 | duplicate payment/order rate | Fresh execution identity is insufficient for duplicate invocation. |
| P02 | KEEP | C1 | F8 | 1.0 | 50 | 2,000 | 8 | C0/C4 | RQ1 | H1 | duplicate effect rate | Stable identity plus downstream uniqueness suppresses duplicate effects; do not attribute this to coordinator lookup. |
| P03 | KEEP | C4 | F8 | 1.0 | 50 | 2,000 | 8 | C1/C8 | RQ1 | H1 | duplicate detection/effect rate | Adds explicit coordinator lookup on top of stable identity. |
| P04 | KEEP | C8 | F8 | 1.0 | 50 | 2,000 | 8 | C4 | RQ1/RQ4 | H1/H6 | logical success, latency | Full bundle behavior/cost under duplicate load. |
| P05 | KEEP | C1 | F11 | 0.10 | 50 | 2,000 | 8 | C3 | RQ2 | H2 | logical success | Stable identity without retry under pre-effect transient payment failure. |
| P06 | KEEP | C3 | F11 | 0.10 | 50 | 2,000 | 8 | C1/C8 | RQ2/RQ4 | H2/H6 | retry success, logical success | Bounded retry resolves pre-effect transient failure. |
| P07 | KEEP | C8 | F11 | 0.10 | 50 | 2,000 | 8 | C3 | RQ4 | H6 | latency/throughput | Full-bundle overhead when retry is active. |
| P08 | KEEP | C1 | F5 | 0.10 | 50 | 2,000 | 8 | C4/C5 | RQ2 | H3 | logical completion, ambiguous failed state | Stable identity alone does not resolve ambiguous post-payment response loss, although downstream payment idempotency prevents duplicate payments. |
| P09 | SUPPLEMENTAL | C3 | F5 | 0.10 | 50 | 2,000 | 8 | C1/C5 | RQ2/RQ4 | H2/H3/H6 | retry count, terminal failure, latency | Retry-only overhead/negative control under ambiguity; not primary causal evidence for duplicate-effect prevention. |
| P10 | KEEP | C4 | F5 | 0.10 | 50 | 2,000 | 8 | C1/C5 | RQ2 | H3 | ambiguous terminal state, lookup events | Explicit lookup before operations, without catch-path lost-response reconciliation. |
| P11 | KEEP | C5 | F5 | 0.10 | 50 | 2,000 | 8 | C1/C4/C8 | RQ2/RQ4 | H3/H6 | reconciliation success, logical success | Lost-response reconciliation resolves ambiguous payment outcomes; runner repair disabled. |
| P12 | KEEP | C8 | F5 | 0.10 | 50 | 2,000 | 8 | C5 | RQ4 | H6 | latency/throughput, reconciliation success | Full-bundle ambiguity behavior/cost; runner repair disabled. |
| P13 | KEEP | C1 | F12 | 0.10 | 50 | 2,000 | 8 | C6 | RQ1 | H4 | active orphan/invariant rate | No-compensation comparator for permanent payment failure after order. |
| P14 | KEEP | C6 | F12 | 0.10 | 50 | 2,000 | 8 | C1/C8 | RQ1/RQ4 | H4/H6 | compensation success | Compensation preserves invariants after permanent downstream failure. |
| P15 | KEEP | C8 | F12 | 0.10 | 50 | 2,000 | 8 | C6 | RQ4 | H6 | compensation success, latency | Full-bundle compensation behavior/cost. |
| P16 | MODIFY | C2 | true crash after order | deterministic | 1 | 1 | 10 | C7 | RQ3 | H5 | recovery completed, invariant state | Durable coordinator state without retry, lost-response reconciliation, compensation, or restart recovery, under coordinator uniqueness constraint. |
| P17 | MODIFY | C7 | true crash after order | deterministic | 1 | 1 | 10 | C2/C8 | RQ3 | H5 | recovery success, identity preservation | Restart recovery on durable state after SIGKILL/restart. |
| P18 | MODIFY | C8 | true crash after order | deterministic | 1 | 1 | 10 | C7 | RQ3/RQ4 | H5/H6 | recovery success, recovery latency | Full-bundle crash recovery and cost. |
| P19 | KEEP | C0 | F0 | 0.0 | 50 | 2,000 | 8 | C1 | RQ4 | H6 | latency/throughput | Random-identity no-failure cost baseline. |
| P20 | KEEP | C1 | F0 | 0.0 | 50 | 2,000 | 8 | C0/C2 | RQ4 | H6 | latency/throughput | Deterministic identity cost. |
| P21 | KEEP | C2 | F0 | 0.0 | 50 | 2,000 | 8 | C1/C8 | RQ4 | H6 | latency/throughput | Durable coordinator-state cost. |
| P22 | KEEP | C5 | F0 | 0.0 | 50 | 2,000 | 8 | C2/C8 | RQ4 | H6 | latency/throughput | Reconciliation-capable path cost with runner repair disabled. |
| P23 | KEEP | C8 | F0 | 0.0 | 50 | 2,000 | 8 | C1/C2/C5 | RQ4 | H6 | latency/throughput | Full-bundle no-failure overhead. |

## F5 Scientific Interpretation

- C1: stable identity, no retry, no explicit lookup, no reconciliation. It legitimately tests unresolved ambiguous-state/logical-completion failure. It does not test duplicate-payment risk in isolation because downstream deterministic payment identity/idempotency already suppresses duplicate successful payments.
- C3: stable identity plus retry. Under F5 it tests retry overhead and retry insufficiency for terminal logical completion, not duplicate-effect prevention. It is supplemental, not primary.
- C4: stable identity plus idempotent side-effect lookup. It tests pre-operation lookup behavior and whether lookup alone resolves already-visible effects; it does not include catch-path lost-response reconciliation.
- C5: stable identity plus lookup plus lost-response reconciliation. It tests explicit system/orchestrator reconciliation of ambiguous post-side-effect payment loss. Runner reconciliation is disabled.

## Mechanism Attribution Events

Final runs must preserve explicit orchestrator events through `orchestrator_mechanism_events` and runner-collected `events.jsonl` entries:

- `IDEMPOTENT_LOOKUP_ATTEMPT`, `IDEMPOTENT_LOOKUP_FOUND`, `IDEMPOTENT_LOOKUP_NOT_FOUND`
- `RETRY_ATTEMPT`, `RETRY_SUCCEEDED`, `RETRY_EXHAUSTED`
- `RECONCILIATION_STARTED`, `RECONCILIATION_FOUND_EFFECT`, `RECONCILIATION_NOT_FOUND`, `RECONCILIATION_SUCCEEDED`, `RECONCILIATION_FAILED`
- `COMPENSATION_STARTED`, `COMPENSATION_RETRY`, `COMPENSATION_SUCCEEDED`, `COMPENSATION_FAILED`
- `RECOVERY_STARTED`, `RECOVERY_SUCCEEDED`, `RECOVERY_FAILED`

Runner/harness reconciliation is disabled for C5 and C8 final primary configurations. The harness may observe and collect events, but must not repair primary workflows.

## RQ and Hypothesis Mapping

- RQ1 mechanism necessity: P01-P04 for identity/duplicates; P13-P15 for compensation.
- RQ2 failure semantics: P05-P07 for pre-effect retry; P08, P10-P12 for post-effect ambiguity/reconciliation. P09 is supplemental only.
- RQ3 crash/recovery: P16-P18.
- RQ4 performance cost: P04, P07, P11, P12, P15, P18-P23.
- H1: P01-P04.
- H2: P05-P07; P09 supplemental only for retry overhead under ambiguity.
- H3: P08, P10-P12. Wording: explicit lost-response reconciliation, not retry alone, is required to resolve ambiguous post-side-effect outcomes when downstream idempotency already prevents duplicate effects.
- H4: P13-P15.
- H5: P16-P18.
- H6: P04, P07, P11, P12, P15, P18-P23.

## Seed Policy

- Base seed is fixed before execution in the final manifest.
- Ordinary repetition seed rule: `seed = baseSeed + repetitionIndex - 1`.
- Same repetition index uses the same seed across comparator configs in each scenario family.
- Different repetitions use different seeds.
- F5/F11/F12 deterministic configs C1-C8 pair exact logical failure schedules because transaction IDs are deterministic.
- F8 duplicate logical schedule is paired across configs; C0 execution IDs intentionally differ.
- Crash seeds are recorded for provenance and any deterministic request/failure headers, but the primary crash intervention is deterministic: crash after `ORDER_CREATED`.

## Metrics and Invariants

Preserve per-run correctness, mechanism activity, performance, crash, and provenance metrics: logical success, attempt success, invariant violations, duplicate orders/payments, safe compensation, recovery outcome, retry/retry exhaustion, lookup/reuse, reconciliation, runner reconciliation, compensation, P50/P95/P99 latency, throughput, run duration, downtime, restart latency, recovery latency, crash-to-terminal latency, commit, dirty state, seed, config, service versions, and environment metadata.

Invariant families: at most one successful payment per logical transaction, completed state has required order/payment effects, at most one active order, compensated state has no active order, recovery preserves transaction identity, and terminal coordinator state is consistent with observed side effects.

## Statistical Plan

- Use independent runs as the unit for ordinary cells; no transaction-level pseudo-replication.
- Use matched seeds where comparisons are paired.
- Report raw per-run values, paired deltas, mean paired difference, standard deviation, t-based 95% CI, and effect sizes.
- Do not emphasize p-values.
- Crash analysis uses independent crash trials: recovery success proportion, identity/invariant outcomes, downtime, restart latency, recovery latency, and crash-to-terminal latency.

## Failed-Run Policy

- Preserve every run and failed-run artifact.
- Classify anomalies before replacement: valid scientific outcome, infrastructure failure, implementation defect, configuration error, environment saturation, or unknown.
- Rerun only infrastructure/configuration failures that prevented the intended cell from executing.
- Never silently exclude a run.
- Replacement runs must use new run IDs and retain the original failed evidence.

## Robustness Plan

After primary analysis rules are locked, run supplemental robustness for F5/F11/F12 at 1%, 5%, 10%, and 20%, plus historical-continuity comparisons if needed. Do not add robustness cells based on interesting primary outcomes.

## Stopping Rules and Environment Requirements

Stop before continuing if Compose saturation, Hikari pool exhaustion, HTTP connection exhaustion, PostgreSQL bottleneck, timeout cascades, or hidden runner repair appears in more than one run family. Required environment: clean `mechanism-isolation-v2` commit, Docker Compose V2 stack healthy, PostgreSQL/Redis/service versions captured, no dirty code except explicitly documented instrumentation under review.

## Commit Provenance

Every final run must record commit SHA, branch, dirty status, configuration, seed, backend, service URLs/versions, Docker/Compose versions, Java/Python versions, and environment metadata. Final campaign execution must start only from the reviewed frozen commit.

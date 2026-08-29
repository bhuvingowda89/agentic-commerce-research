# V2 Primary Matrix Review

This review starts from the 29-cell primary matrix in `docs/V2_EXPERIMENT_DESIGN.md`. It is not a frozen campaign manifest and does not execute any experiments.

## Implementation status informing the review

Phase V2.3 added corrected C0/C1 baseline semantics:

- C0 preserves the logical transaction identifier for analysis but assigns a fresh execution/service transaction identity per attempt.
- C1 preserves the same logical transaction identifier and assigns a stable deterministic execution/service transaction identity.
- Historical `baseline` and `resilient` modes remain separate and unchanged.

The remaining configurations C2-C8 are validated configuration names, but their services-backend runtime semantics are not fully implemented yet. Matrix reduction recommendations below assume future implementation will honor the configuration model.

## Recommendation

Use a reduced 23-cell primary matrix.

The reduction keeps all RQs and hypotheses represented while removing weak or redundant cells:

- demote C2/F11 because durable state alone should not affect pre-effect transient retry without recovery;
- demote C2/F12 because durable state alone should not affect safe compensation without the compensation mechanism;
- demote C1/true-crash because it is a negative control that cannot recover without durable state and may be covered by C2 vs C7;
- reduce no-failure cost cells to representative configurations instead of every dormant mechanism configuration.

## Reduced primary matrix

| Cell | Configuration | Scenario | Failure probability | Concurrency | Transactions/run | Repetitions | Primary comparison | RQ | Hypothesis | Primary metric | Unique causal information |
|---|---|---|---:|---:|---:|---:|---|---|---|---|---|
| P01 | C0 | F8 | 1.0 | 50 | 2,000 | 8 | C0 vs C1 | RQ1 | H1 | duplicate order/payment rate | Unprotected fresh execution identity under duplicate invocation. |
| P02 | C1 | F8 | 1.0 | 50 | 2,000 | 8 | C1 vs C0/C4 | RQ1 | H1 | duplicate order/payment rate | Deterministic identity and service uniqueness without coordinator state. |
| P03 | C4 | F8 | 1.0 | 50 | 2,000 | 8 | C4 vs C1/C8 | RQ1 | H1 | duplicate detection, duplicate effects | Adds idempotent lookup to deterministic identity. |
| P04 | C8 | F8 | 1.0 | 50 | 2,000 | 8 | C8 vs C4 | RQ1/RQ4 | H1/H6 | logical success, cost | Full bundle under duplicate load; detects added cost/side effects beyond C4. |
| P05 | C1 | F11 | 0.10 | 50 | 2,000 | 8 | C1 vs C3 | RQ2 | H2 | logical success | No-retry deterministic baseline for pre-effect transient failure. |
| P06 | C3 | F11 | 0.10 | 50 | 2,000 | 8 | C3 vs C1/C8 | RQ2/RQ4 | H2/H6 | retry success, logical success | Isolates bounded retry benefit and cost. |
| P07 | C8 | F11 | 0.10 | 50 | 2,000 | 8 | C8 vs C3 | RQ4 | H6 | logical success, latency | Tests whether full bundle adds overhead or behavior beyond retry. |
| P08 | C1 | F5 | 0.10 | 50 | 2,000 | 8 | C1 vs C3/C4/C5 | RQ2 | H2/H3 | invariant violation | Deterministic identity without retry or reconciliation under ambiguous payment outcome. |
| P09 | C3 | F5 | 0.10 | 50 | 2,000 | 8 | C3 vs C1/C5 | RQ2 | H2/H3 | invariant violation | Retry-enabled but no lost-response reconciliation. |
| P10 | C4 | F5 | 0.10 | 50 | 2,000 | 8 | C4 vs C1/C5 | RQ2 | H3 | duplicate payment, logical final state | Idempotent lookup without explicit reconciliation. |
| P11 | C5 | F5 | 0.10 | 50 | 2,000 | 8 | C5 vs C3/C4/C8 | RQ2/RQ4 | H3/H6 | reconciliation success, invariant violation | Isolates lost-response reconciliation. |
| P12 | C8 | F5 | 0.10 | 50 | 2,000 | 8 | C8 vs C5 | RQ4 | H6 | latency/throughput, invariant rate | Full bundle cost under ambiguous payment outcome. |
| P13 | C1 | F12 | 0.10 | 50 | 2,000 | 8 | C1 vs C6 | RQ1 | H4 | active orphan order rate | No-compensation baseline for permanent downstream failure. |
| P14 | C6 | F12 | 0.10 | 50 | 2,000 | 8 | C6 vs C1/C8 | RQ1/RQ4 | H4/H6 | safe compensation rate | Isolates compensation and compensation retry behavior. |
| P15 | C8 | F12 | 0.10 | 50 | 2,000 | 8 | C8 vs C6 | RQ4 | H6 | compensation success, latency | Full bundle overhead relative to compensation-focused config. |
| P16 | C2 | true crash after order | deterministic | 1 | 100 | 8 | C2 vs C7 | RQ3 | H5 | terminal state, duplicate effects | Durable state without restart recovery, negative/partial control. |
| P17 | C7 | true crash after order | deterministic | 1 | 100 | 8 | C7 vs C2/C8 | RQ3 | H5 | recovery success, identity preservation | Isolates restart recovery on durable state. |
| P18 | C8 | true crash after order | deterministic | 1 | 100 | 8 | C8 vs C7 | RQ3/RQ4 | H5/H6 | recovery success, recovery latency | Full bundle crash recovery behavior and cost. |
| P19 | C0 | F0 | 0.0 | 50 | 2,000 | 8 | C0 vs C1 | RQ4 | H6 | latency/throughput | Cost of unprotected random baseline. |
| P20 | C1 | F0 | 0.0 | 50 | 2,000 | 8 | C1 vs C0/C2 | RQ4 | H6 | latency/throughput | Cost of deterministic identity alone. |
| P21 | C2 | F0 | 0.0 | 50 | 2,000 | 8 | C2 vs C1/C8 | RQ4 | H6 | latency/throughput | Cost of durable coordinator state. |
| P22 | C5 | F0 | 0.0 | 50 | 2,000 | 8 | C5 vs C2/C8 | RQ4 | H6 | latency/throughput | Cost of idempotent lookup plus reconciliation-capable path. |
| P23 | C8 | F0 | 0.0 | 50 | 2,000 | 8 | C8 vs C1/C2/C5 | RQ4 | H6 | latency/throughput | Full bundle no-failure overhead. |

## Demoted cells

| Original cell | Recommendation | Rationale |
|---|---|---|
| C2/F11 | Demote to supplemental or remove | Durable state alone should not address pre-effect transient payment failure without retry or recovery activation. It is unlikely to provide unique causal evidence for RQ2. |
| C2/F12 | Demote to supplemental or remove | Durable state alone should not provide safe compensation. C1 vs C6 isolates compensation more directly. |
| C1/true-crash | Demote to supplemental negative control | Without durable state, C1 cannot support restart recovery. C2 is the cleaner negative/partial control because it has durable state but lacks restart recovery. |
| C3/F0 | Demote | Retry code may be dormant under F0; include only if implementation introduces measurable retry-decision overhead. |
| C4/F0 | Demote | C5/F0 better represents idempotent lookup plus reconciliation-capable overhead. |
| C6/F0 | Demote | Compensation should be dormant under F0; C8/F0 covers full bundle overhead. |

## RQ and hypothesis coverage after reduction

- RQ1 remains covered by F8 and F12 mechanism contrasts.
- RQ2 remains covered by F11 versus F5, especially C1/C3/C5.
- RQ3 remains covered by C2/C7/C8 true-crash cells.
- RQ4 remains covered by F0 representative cost cells and full-bundle comparisons in F8/F11/F5/F12/crash.
- H1 remains covered by C0/C1/C4/C8 under F8.
- H2 remains covered by C1/C3/C8 under F11 and C1/C3 under F5.
- H3 remains covered by C3/C4/C5/C8 under F5.
- H4 remains covered by C1/C6/C8 under F12.
- H5 remains covered by C2/C7/C8 under true crash.
- H6 remains covered by representative F0 cells and full-bundle comparisons.

## Remaining confounds

- C1 may still benefit from downstream database uniqueness. That is intentional for deterministic-identity isolation, but the paper must distinguish it from coordinator-level idempotency.
- C4 and C5 require careful implementation separation; if idempotent lookup and reconciliation share the same code path, their contrast may be weak.
- C8 may be hard to interpret causally, but it is useful for continuity with historical resilient behavior.
- True crash cells remain design placeholders until V2.4 implements externally controlled process/container termination.

## Transaction count and repetition review

The default 2,000 transactions/run is reasonable for 10% probabilistic F5/F11/F12 cells because each run should observe enough triggered failures for stable run-level rates. It may be higher than necessary for deterministic F8, but F8 uses concurrency and duplicate grouping, so 2,000 remains acceptable.

True crash cells should remain at 100 transactions/run or lower because the unit of evidence is externally controlled crash/recovery behavior, not rare event estimation.

Eight independent repetitions are reasonable for primary paired effects. If pilot variance is very low for deterministic cells, final repetitions could be reduced for those cells only if the reduction is declared before the frozen campaign.

## Estimated size

Reduced primary matrix:

- unique cells: 23;
- repetitions: 8;
- total runs: 184;
- approximate logical transactions: 20 non-crash cells x 8 x 2,000 + 3 crash cells x 8 x 100 = 322,400.

This remains within the target 100-250 high-information final runs.

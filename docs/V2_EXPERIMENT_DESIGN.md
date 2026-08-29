# V2 Experiment Design: Mechanism Isolation for Fault-Tolerant Transaction Orchestration

## 1. Motivation for v2

The original study compared a historical `BASELINE` implementation with a bundled `RESILIENT` implementation for a Cart -> Order -> Payment workflow under injected failures. That comparison provided useful evidence that the bundled resilient implementation preserved transaction invariants more often than the historical baseline in selected scenarios, but it did not isolate which reliability mechanism was necessary for which failure semantics.

The v2 study shifts the contribution from "a resilient commerce architecture is better than a baseline" to the more general software systems question: which fault-tolerance mechanisms are necessary for preserving distributed workflow consistency under specific failure semantics, and what cost does each mechanism introduce?

The commerce workflow is the experimental testbed. The measured system remains a deterministic multi-service transaction workflow, not a measured LLM reasoning system.

## 2. Historical study summary

Historical final results are preserved under `results/phase_b1_services/final` and `results/phase_b2_services/final`.

Phase B1 used:

- services backend;
- baseline and resilient modes;
- 10,000 logical transactions per run;
- concurrency 50;
- 5 independent repetitions;
- scenarios F0, F5, F8, F9, F11, and F12;
- F5/F11/F12 failure probabilities 1%, 5%, 10%, and 20%;
- F8 and F9 deterministic configurations;
- 150 completed runs.

Phase B2 used:

- services backend;
- baseline and resilient modes;
- 10,000 logical transactions per run;
- concurrency 1, 10, and 100;
- scenarios F0, F5 at 5%, and F8;
- 5 independent repetitions;
- 90 completed runs.

The checked-in historical artifacts contain final summaries, aggregate CSVs, comparison CSVs, metadata, and empty failed-run logs for B1/B2. The historical per-transaction raw JSONL data is not present in the repository. It must not be regenerated and represented as original evidence.

## 3. Limitations motivating the redesign

The repository audit identified the following limitations.

- The historical services baseline was not a completely stateless baseline. It used deterministic transaction IDs derived from logical transaction IDs, and downstream services used deterministic primary keys such as `cart-{transactionId}`, `order-{transactionId}`, and `payment-{transactionId}` with database conflict handling. This creates partial protection against duplicate side effects, especially in F7/F8.
- The resilient implementation bundles durable coordinator state, idempotency, retry, lost-response inspection, reconciliation, compensation, recovery, and database uniqueness constraints.
- Historical F9 is an application-level simulated interruption, not a true process or container crash.
- Most failure injection is application-level simulation, not infrastructure failure, network partition, or independent machine failure.
- All stateful services use one PostgreSQL instance/database.
- Redis is provisioned but not used in the measured path.
- The measured path does not execute an LLM or MCP tool stack.
- The historical final campaign lacks raw per-transaction artifacts in the current repository checkout.

These limitations should be treated as design constraints, not hidden weaknesses.

## 4. Target journal and contribution positioning

The primary target is the Journal of Systems and Software. The contribution should be framed as generalizable software/system reliability knowledge for multi-step service workflows and tool-using agent infrastructure.

The paper should not claim measured general LLM-agent reliability. A defensible framing is:

> A mechanism-isolation study of transaction consistency in distributed service workflows that are representative of infrastructure used by tool-using commerce agents.

The term "agentic commerce" can remain as motivation and application context, but the empirical claims must be about transaction orchestration mechanisms, failure semantics, invariants, and cost. A future title should consider reducing the emphasis on "Agentic Commerce" unless LLM/MCP execution is explicitly included and measured.

## 5. Core scientific question

Proposed question:

> Which fault-tolerance mechanisms are necessary for preserving transaction consistency under distinct distributed failure semantics, and what correctness/performance cost does each mechanism introduce?

This is supportable if v2 implements scientifically separable mechanism configurations and strengthens invariant instrumentation. A narrower and more precise version is:

> For a deterministic multi-service transaction workflow, which combinations of transaction identity, durable state, idempotent side-effect lookup, retry, reconciliation, compensation, and restart recovery preserve business invariants under pre-effect failures, post-effect ambiguous outcomes, duplicate invocation, permanent downstream failure, and coordinator crash?

The narrower wording better matches the actual system.

## 6. RQ1-RQ4

RQ1: Mechanism necessity.

Which mechanisms or minimal mechanism combinations are necessary to preserve transaction invariants under distinct failure semantics?

RQ2: Ambiguous outcomes.

How do bounded retry, stable transaction identity, idempotent side-effect lookup, and side-effect reconciliation behave differently when a failure occurs before a successful side effect versus after the side effect may have committed?

RQ3: Coordinator failure.

Can durable orchestration state plus restart recovery preserve transaction identity and exactly-once business effects across externally induced coordinator process/container failure and restart?

RQ4: Cost.

What run-level latency, throughput, retry, reconciliation, compensation, and recovery overhead is introduced by each mechanism or mechanism combination?

RQ3 requires new true crash/restart infrastructure. Without that, RQ3 must be limited to simulated interruption, which is not scientifically sufficient for the proposed claim.

## 7. Hypotheses

H1: Stable transaction identity reduces duplicate side effects under repeated or concurrent invocation relative to fresh random identity.

H2: Bounded retry improves completion under pre-side-effect transient failures, but retry alone does not establish the outcome of post-side-effect ambiguous failures.

H3: Side-effect reconciliation reduces invariant violations under post-side-effect response loss relative to retry without reconciliation.

H4: Compensation converts some partial workflow failures into safe terminal outcomes while introducing additional work and latency.

H5: Durable coordinator state plus restart recovery preserves workflow identity and prevents duplicate business effects across actual coordinator process/container failure better than non-durable execution.

H6: Reliability mechanisms introduce measurable and mechanism-specific performance costs.

These are falsifiable. They must be reported neutrally if unsupported or contradicted.

## 8. Failure-semantics taxonomy

Primary failure semantics:

- No failure: F0.
- Duplicate/concurrent invocation: F8.
- Pre-side-effect transient failure: F11.
- Pre-side-effect timeout/failure: F4, optional but useful to distinguish from F5.
- Post-side-effect ambiguous response loss: F5; F6 as optional generalization to order creation.
- Simulated coordinator interruption: historical F9, retained only for continuity and not described as a crash.
- True coordinator crash/restart: new V2 crash protocol.
- Permanent downstream failure requiring safe termination: F12, with compensation retry.

F5 and F11 are the most important contrast:

- F11 tests retry where the operation has not committed successfully before eventual success.
- F5 tests ambiguity after a payment has committed but the response is lost.

The design must allow retry-only behavior to fail or succeed empirically; it must not encode the desired conclusion into metric definitions.

## 9. Mechanism taxonomy

A0: Stateless/random-identity baseline.

- Fresh transaction identity for independent attempts.
- No durable coordinator state.
- No coordinator idempotency.
- No retry.
- No reconciliation.
- No compensation.
- No recovery.

A1: Deterministic transaction identity.

- Stable logical transaction ID.
- Deterministic downstream IDs.
- Service-level uniqueness through primary keys.

A2: Durable coordinator state.

- Persistent workflow record and state transitions.
- No automatic assumption that durable state alone retries, reconciles, compensates, or recovers.

A3: Idempotent side-effect detection/lookup.

- Detect/reuse previously created cart/order/payment effects.
- Requires stable identity or another durable idempotency key.

A4: Bounded retry.

- Retry transient failures with explicit retry counts.
- Must distinguish pre-effect retry from ambiguous post-effect retry.

A5: Lost-response reconciliation.

- Inspect downstream state after ambiguous response loss and reconcile coordinator state.

A6: Compensation.

- Cancel or compensate active order when payment cannot be completed.
- Record safe terminal state separately from purchase success.

A7: Restart recovery.

- Resume non-terminal durable state after externally induced coordinator process/container crash and restart.

## 10. Mechanism prerequisites/dependencies

The mechanisms should not be treated as a simple independent ladder.

- A3 requires stable transaction identity, idempotency key, or deterministic lookup key.
- A5 requires stable identity and inspectable downstream side effects.
- A6 requires durable or otherwise known order identity.
- A7 requires A2 durable state and restart-visible service state.
- A4 is meaningful without A5 for pre-side-effect transient failures, but can be unsafe or insufficient for post-side-effect ambiguity unless paired with A1/A3/A5.
- A2 without A3/A5 may record progress but still be unable to resolve ambiguous external outcomes.
- A1 may provide substantial protection even without a durable coordinator, and therefore must be isolated from A0.

## 11. Proposed variant/configuration design

Use a hybrid design: selective mechanism configurations targeted to failure semantics, plus a small cumulative sanity sequence.

Pure cumulative variants A0 -> A7 would create misleading comparisons because later mechanisms depend on earlier mechanisms and some scenarios do not exercise all mechanisms. A selective design gives cleaner causal evidence with fewer runs.

Recommended core configurations:

- C0: A0 only, random/fresh identity.
- C1: A1 only, deterministic identity and service uniqueness.
- C2: A1 + A2, deterministic identity plus durable coordinator state.
- C3: A1 + A2 + A4, retry-enabled without lost-response reconciliation.
- C4: A1 + A2 + A3, idempotent lookup without retry/reconciliation where meaningful.
- C5: A1 + A2 + A3 + A5, lost-response reconciliation.
- C6: A1 + A2 + A6, compensation for permanent downstream failure.
- C7: A1 + A2 + A3 + A7, restart recovery for true crash.
- C8: Full resilient bundle, for continuity with historical resilient behavior.

Not every configuration should be run against every scenario.

## 12. Corrected baseline design

The historical baseline must remain unchanged and historically labeled. V2 needs two explicit baselines:

- A0 random/fresh identity baseline: new independent transaction ID for each attempt, no coordinator state or reliability mechanisms.
- A1 deterministic identity baseline: stable transaction identity and deterministic downstream IDs, but no durable coordinator state, retry, reconciliation, compensation, or recovery.

Historical B1/B2 services baseline should be described as closest to A1, not A0.

## 13. True crash/restart experimental protocol

Protocol:

1. Start PostgreSQL and required services.
2. Start orchestrator as a separately controllable process or container.
3. Start a transaction with a known idempotency key/logical transaction ID.
4. Allow cart creation.
5. Allow order creation.
6. Ensure durable coordinator state has reached an intermediate state such as `ORDER_CREATED` or `PAYMENT_PENDING`.
7. Kill the orchestrator externally with `docker kill`, `docker stop`, or `SIGKILL`.
8. Verify the original orchestrator is unavailable.
9. Start a fresh orchestrator process/container using the same persistent PostgreSQL state.
10. Invoke or trigger recovery.
11. Complete or safely terminate the transaction.
12. Inspect durable coordinator and downstream service state directly.
13. Record crash timestamp, restart timestamp, recovery start/completion, recovery latency, final state, duplicate side effects, recovery attempts, and invariant checks.

Recommendation: Docker Compose-managed Java services are preferable to Python-managed subprocesses for final evidence. Compose provides reproducible process identity, external kill/restart semantics, logs, network names, health checks, and reset automation. Python subprocesses may be acceptable for an early pilot, but final crash/restart evidence should use container-managed orchestrator control.

## 14. Business invariants

Future v2 invariant checks should start from the existing repository invariants and strengthen services-backend enforcement without changing historical results.

I1: At most one successful payment per logical/idempotency transaction.

I2: `COMPLETED` implies a valid order and successful payment.

I3: At most one order per logical/idempotency transaction.

I4: A compensated transaction leaves no active payable order.

I5: Recovery preserves original transaction identity across coordinator and downstream state.

I6: Terminal states are mutually consistent across coordinator, order, and payment state.

Services-backend checks should query the coordinator transaction record plus cart/order/payment tables or inspect endpoints. I5 and I6 need stronger service-path implementation for v2.

## 15. Metrics

Correctness:

- logical transaction success rate;
- attempt-level success rate;
- invariant violation rate;
- duplicate order rate;
- duplicate payment rate;
- active/orphan order rate;
- safe compensation rate;
- recovery success rate;
- transaction identity preservation rate.

Mechanism behavior:

- retry attempts and retry successes;
- reconciliation attempts and reconciliation successes;
- compensation attempts and compensation successes;
- recovery attempts and recovery successes;
- duplicate requests detected;
- failure-injection events actually triggered.

Performance:

- end-to-end latency;
- P50/P95/P99 latency where sample size supports it;
- throughput;
- crash-to-recovery completion time;
- restart-to-recovery completion time;
- mechanism-specific overhead.

Safe compensation must not be counted as successful purchase completion. It is a safe terminal outcome.

## 16. Statistical methodology

The independent experimental unit is the run, not the transaction.

Recommended approach:

- Use independent run-level repetitions, default n=8 for primary comparisons.
- Use matched seeds for paired configurations within the same scenario, failure rate, concurrency, and repetition.
- Analyze paired run-level differences where pairing is meaningful.
- Report t-based 95% confidence intervals for small-n paired effects.
- Report effect sizes for primary contrasts.
- Preserve all failed and anomalous runs in manifests and analysis outputs.
- Do not silently exclude failed runs. Classify them as infrastructure failure, system under test failure, or measurement failure before analysis.
- Do not inflate statistical power with transaction-level pseudo-replication.
- Prefer confidence intervals and effect sizes over p-value-centered claims.

Statistical tests are optional and should be used only when tied to a pre-declared comparison. Multiple metrics should be interpreted as a family of evidence, not as a search for significance.

## 17. Raw artifact/provenance requirements

Use a new result hierarchy:

```text
results/v2/
  manifests/
    v2_final_manifest.yaml
    v2_pilot_manifest.yaml
  pilot/
  final/
    <campaign-id>/
      metadata.json
      git.txt
      environment.json
      failed-runs.jsonl
      cells/
        <cell-id>/
          rep-0001/
            config.json
            transactions.jsonl
            events.jsonl
            retry-events.jsonl
            reconciliation-events.jsonl
            compensation-events.jsonl
            recovery-events.jsonl
            invariant-results.jsonl
            service-logs/
            summary.csv
```

Each final run must record experiment ID, exact configuration, mechanism variant, scenario, failure rate, concurrency, transaction count, repetition, seed, commit, branch/tag, timestamps, environment metadata, service configuration, timeout configuration, retry configuration, reconciliation window, raw per-transaction observations, failure events, mechanism events, invariant results, service logs, and per-run summary.

Final campaign artifacts should be append-only after the campaign is frozen.

## 18. Primary experiment matrix

Recommended primary experiments:

| Family | Configurations | Scenario | Failure probability | Concurrency | Transactions/run | Repetitions | Paired | Primary metric | Primary invariant | Purpose |
|---|---|---:|---:|---:|---:|---:|---|---|---|---|
| Identity under duplicates | C0, C1, C4, C8 | F8 | 1.0 | 50 | 2,000 | 8 | yes | duplicate order/payment rate | I1, I3 | Isolate random vs deterministic identity vs idempotent lookup |
| Pre-effect transient retry | C1, C2, C3, C8 | F11 | 0.10 | 50 | 2,000 | 8 | yes | logical success, retry success | I2 | Isolate retry under pre-effect transient failure |
| Post-effect ambiguous payment | C1, C3, C4, C5, C8 | F5 | 0.10 | 50 | 2,000 | 8 | yes | invariant violation, reconciliation success | I1, I2, I6 | Compare retry/idempotency/reconciliation for response loss |
| Permanent failure and compensation | C1, C2, C6, C8 | F12 | 0.10 | 50 | 2,000 | 8 | yes | safe compensation rate | I4, I6 | Isolate compensation and compensation retry |
| True crash/restart | C1, C2, C7, C8 | new true crash after order | deterministic | 1 | 100 | 8 | yes | recovery success, identity preservation | I1, I3, I5, I6 | Test externally induced coordinator crash/restart |
| No-failure cost baseline | C0, C1, C2, C3, C4, C5, C6, C8 | F0 | 0.0 | 50 | 2,000 | 8 | yes | latency/throughput overhead | I2, I6 | Estimate mechanism cost without injected failure |

Primary unique cells: 29.

Primary runs: 29 cells x 8 repetitions = 232 runs.

Approximate primary logical transactions: 224 non-crash runs x 2,000 + 32 crash runs x 100 = 451,200 logical transactions.

## 19. Robustness experiment matrix

Robustness experiments should test whether the main conclusions are artifacts of one concurrency or failure-rate setting.

| Family | Configurations | Scenario | Failure probability | Concurrency | Transactions/run | Repetitions | Purpose |
|---|---|---:|---:|---:|---:|---:|---|
| F5 rate sensitivity | C1, C5, C8 | F5 | 0.01, 0.20 | 50 | 2,000 | 5 | Check low/high ambiguous failure rates |
| F11 rate sensitivity | C1, C3, C8 | F11 | 0.01, 0.20 | 50 | 2,000 | 5 | Check retry conclusions across rates |
| F8 concurrency sensitivity | C0, C1, C4, C8 | F8 | 1.0 | 10, 100 | 2,000 | 5 | Check duplicate handling under lower/higher concurrency |
| No-failure saturation | C1, C8 | F0 | 0.0 | 10, 100 | 2,000 | 5 | Separate overhead from saturation |

Robustness unique cells: 30.

Robustness runs: 30 cells x 5 repetitions = 150 runs.

Approximate robustness logical transactions: 300,000.

If the campaign must stay under 250 final runs, run the primary matrix first and keep robustness as a separate supplemental campaign.

## 20. Optional experiment matrix

| Family | Configurations | Scenario | Failure probability | Concurrency | Transactions/run | Repetitions | Purpose |
|---|---|---:|---:|---:|---:|---:|---|
| Pre-timeout contrast | C1, C3, C8 | F4 | 0.10 | 50 | 2,000 | 5 | Contrast timeout before side effect with F5 |
| Order response loss | C1, C4, C5, C8 | F6 | 0.10 | 50 | 2,000 | 5 | Test reconciliation on a non-payment operation |
| Historical continuity | historical baseline, C8 | historical F9 simulated interruption | 1.0 | 50 | 2,000 | 5 | Compare old simulated interruption with true crash semantics |
| Large headline validation | C1, C5, C8 | F5 | 0.10 | 50 | 10,000 | 3 | Validate one high-impact conclusion at historical scale |

Optional unique cells: 22.

Optional runs: 110, plus 9 large validation runs if included.

## 21. Total estimated campaign size

Recommended frozen final campaign:

- Primary only: 29 cells, 232 runs, about 451,200 logical transactions.
- Independent repetitions: n=8 primary.
- Default transactions/run: 2,000.
- Crash/restart transactions/run: 100 because the unit of interest is crash recovery, not rare probabilistic failures.

Recommended supplemental robustness campaign:

- 30 cells, 150 runs, about 300,000 logical transactions.
- Independent repetitions: n=5.

The primary campaign fits the requested 100-250 high-information run target. Robustness should be executed only after reviewing primary pilots and freezing a supplemental plan.

## 22. Expected interpretation framework

Interpretation should be scenario-specific.

- F8: distinguish duplicate suppression from successful purchase completion.
- F11: distinguish retry benefit from idempotency benefit.
- F5: distinguish completion, invariant preservation, and ambiguity resolution.
- F12: distinguish failed purchase from safe compensated terminal outcome.
- True crash: distinguish simulated exception recovery from recovery after process memory loss.
- F0: interpret overhead per mechanism, not as a correctness advantage.

Negative results are scientifically useful. For example, if deterministic identity alone prevents duplicate payments under F8, the paper should report that the baseline confound is a real mechanism effect.

## 23. Threats to validity

Internal validity:

- Mechanism coupling may remain if flags are not implemented cleanly.
- Deterministic service IDs can confound idempotency results.
- Shared PostgreSQL creates common failure domain and common serialization behavior.
- Runner-side reconciliation could mask system behavior if not separated from coordinator behavior.
- Timeout and retry constants may shape outcomes.
- High concurrency may cause saturation rather than reliability failure.

Construct validity:

- Application-level injected failures approximate, but do not fully reproduce, distributed infrastructure failures.
- Response-loss simulations model ambiguous outcomes only if side effects are actually durable before the response is lost.
- Exactly-once business effect is not exactly-once execution.
- Historical F9 is not a true crash.

External validity:

- One linear commerce workflow.
- Central coordinator architecture.
- One database technology.
- Single-machine/container environment unless v2 changes deployment.
- No measured LLM inference.

Conclusion validity:

- Small run-level n.
- Multiple metrics and comparisons.
- Transaction-level pseudo-replication risk.
- Failed-run classification can affect interpretation.
- Pairing assumptions must be enforced by the manifest and seeds.

## 24. Generalizability boundaries

Potentially generalizable:

- Stable transaction identity as a prerequisite for duplicate and ambiguous-outcome handling.
- Retry usefulness under pre-effect transient failures.
- Reconciliation usefulness under post-effect ambiguity.
- Compensation as a safe terminal strategy for partial workflows.
- Durable coordinator state and restart recovery as requirements for coordinator crash resilience.
- Correctness/performance tradeoffs of reliability mechanisms.

Prototype-specific:

- Exact throughput/latency numbers.
- PostgreSQL-specific uniqueness behavior.
- Linear Cart -> Order -> Payment topology.
- Behavior under local single-host deployment.
- Payment/order simulator semantics.

The study should avoid claims about general LLM-agent reliability unless an actual LLM path is added and measured.

## 25. Implementation roadmap

Phase V2.1: Provenance and reproducibility infrastructure.

- Objective: create immutable v2 artifact layout, manifests, run IDs, metadata capture, failed-run preservation.
- Likely files: `python/research_harness/metrics.py`, new manifest/reporting modules, documentation.
- Tests: artifact creation, no overwrite behavior, failed-run preservation.
- Completion criteria: every pilot run writes complete raw artifacts and provenance.
- Integrity checks: no historical result paths touched.

Phase V2.2: Mechanism configuration/refactoring.

- Objective: make mechanisms independently controllable where semantics permit.
- Likely files: `orchestrator/.../TransactionService.java`, `TransactionRepository.java`, `python/research_harness/orchestrators.py`, `runner.py`, `service_backend.py`.
- Tests: each mechanism flag changes only intended behavior.
- Completion criteria: configurations C0-C8 are executable and auditable.
- Integrity checks: historical baseline behavior remains available and labeled.

Phase V2.3: Corrected baselines.

- Objective: implement and validate A0 random identity and A1 deterministic identity baselines.
- Likely files: transaction ID factory paths in Java/Python, mode/config parsing.
- Tests: duplicate requests produce expected side effects for A0 and expected deterministic uniqueness for A1.
- Completion criteria: A0/A1 are distinguishable in raw artifacts.
- Integrity checks: do not relabel historical B1/B2 baseline.

Phase V2.4: True crash/restart infrastructure.

- Objective: externally kill/restart orchestrator and recover from durable state.
- Likely files: Dockerfiles/Compose or subprocess supervisor, crash test runner, health checks.
- Tests: orchestrator unavailability after kill, fresh process after restart, no in-memory recovery dependency.
- Completion criteria: crash events and recovery events are recorded with timestamps.
- Integrity checks: crash protocol cannot use voluntary application exceptions as crash evidence.

Phase V2.5: Validation tests.

- Objective: validate mechanism flags, state transitions, idempotency, retries, reconciliation, compensation, recovery, invariant detection, crash semantics, and artifact preservation.
- Likely files: Java integration tests and Python harness tests.
- Tests: unit, integration, services backend, crash protocol smoke tests.
- Completion criteria: all validation tests pass before pilot experiments.
- Integrity checks: test data isolated from historical results.

Phase V2.6: Pilot experiments.

- Objective: validate instrumentation and experimental semantics using small runs.
- Likely files: v2 pilot manifest and result paths.
- Tests: manual audit of raw event traces against expected mechanisms.
- Completion criteria: pilot artifacts support independent verification.
- Integrity checks: pilot results not used as final evidence unless frozen before execution.

Phase V2.7: Frozen final campaign.

- Objective: freeze commit, configs, manifest, statistical plan, and execute final campaign.
- Likely files: manifest only before execution, result hierarchy during execution.
- Tests: preflight environment and no-overwrite checks.
- Completion criteria: all planned runs accounted for as completed or failed/anomalous.
- Integrity checks: no methodology changes mid-campaign.

Phase V2.8: Statistical analysis.

- Objective: generate run-level metrics, paired effects, confidence intervals, robustness analyses, and figures/tables.
- Likely files: new analysis scripts, tables, figures.
- Tests: recomputation from raw artifacts matches summaries.
- Completion criteria: analysis is reproducible from raw v2 final artifacts.
- Integrity checks: failed/anomalous runs visible in outputs.

Phase V2.9: Manuscript revision.

- Objective: rewrite paper around mechanism-level findings.
- Likely files: manuscript outside or inside docs, depending repository policy.
- Tests: claims trace to frozen artifacts and source commits.
- Completion criteria: every result claim has provenance and uncertainty.
- Integrity checks: distinguish historical evidence from v2 evidence.

## 26. Research-integrity safeguards

- Do not modify historical Phase A/B1/B2 results.
- Do not overwrite v2 final artifacts.
- Tag and record source commit before final campaigns.
- Preserve raw per-transaction and event-level evidence.
- Preserve failed and anomalous runs.
- Use pre-declared manifests and statistical plans.
- Separate pilot and final evidence.
- Report negative results.
- Keep historical baseline semantics distinct from corrected v2 baselines.
- Distinguish source-code behavior, intended design, measured evidence, hypotheses, and future evidence.

## 27. Open design questions

- How should mechanism flags be represented so invalid combinations are rejected rather than silently producing meaningless variants?
- Should reconciliation be implemented inside the orchestrator only, or should runner-side reconciliation remain a measurement aid?
- What minimum service-backend invariant queries are needed to enforce I5/I6 without relying only on inspect endpoints?
- Should the final crash/restart evidence require Compose-managed services, or is a supervised subprocess acceptable for the first frozen campaign?
- Should databases be separated before v2 final, or documented as a threat to validity?
- Should the eventual title reduce "Agentic Commerce" emphasis to avoid overclaiming beyond the measured path?
- What failure-run taxonomy should distinguish infrastructure failure from valid system-under-test failure?

## Key design choices

The final study should use a hybrid design. Selective mechanism configurations should target specific failure semantics for causal evidence, while a small no-failure/cost sequence should estimate overhead across configurations.

Adding an actual LLM is not necessary for the core distributed transaction question and may add noise/cost without changing the transaction semantics. It may help justify "agentic" framing, but only if measured as a separate layer. The recommended v2 paper should avoid requiring LLM integration and should frame the measured system as workflow infrastructure for tool-using agents.

For database topology, the minimum justified v2 choice is the existing shared PostgreSQL instance for mechanism-isolation experiments, with the limitation made explicit. Separate schemas/databases or separate PostgreSQL containers would improve failure-domain realism, but they are not essential unless independent database failure becomes an RQ. If added later, separate PostgreSQL containers per service provide the cleanest failure-domain evidence at the highest implementation cost.

For containerization, Compose-managed Java services are recommended before final true crash/restart experiments. They are not required for all mechanism-isolation runs, but they provide the cleanest final evidence for externally controlled coordinator kill/restart, logs, health checks, and reproducibility.

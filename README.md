# Agentic Commerce Research

Research prototype for comparing two generic commerce agent architectures:

- Baseline: a stateless LLM/MCP-driven flow where each request reconstructs context from current service responses and tool calls.
- Proposed: a fault-tolerant flow with durable workflow state, explicit transaction state transitions, end-to-end idempotency, retry classification, and result recovery.

This repository intentionally uses generic service names, simulated external systems, and synthetic data only. It contains no company-specific code, credentials, or proprietary datasets.

## Research Question

How much end-to-end transactional consistency and recovery does a durable, transaction-aware orchestration approach add across multiple independently stateful commerce services when autonomous agents execute multi-step commerce workflows under distributed-system failures?

Retries, idempotency, and generic transactional tool execution are treated as supporting mechanisms, not the primary novelty. The research focus is cross-service commerce consistency and recovery across Cart, Order, Payment, and orchestrator state.

The Java services provide the API scaffold. The Python research harness provides the deterministic benchmark path used to compare the two execution modes without requiring an actual LLM.

## Architecture

### Baseline Architecture

The baseline architecture will model an LLM agent calling tools through an MCP server. Tool calls reach commerce services such as cart, order, payment, and merchant simulation APIs. The baseline keeps no durable workflow state in the agent path beyond service-local records.

Planned baseline components:

- `python/llm-agent`: agent entry point and prompts.
- `python/mcp-server`: MCP tool facade for commerce APIs.
- `cart-service`: cart API.
- `order-service`: order API.
- `payment-simulator`: deterministic payment simulator.
- `merchant-simulator`: deterministic merchant simulator.

### Proposed Architecture

The proposed architecture will add an orchestration layer responsible for durable workflow state, explicit transaction transitions, idempotent operation boundaries, retry classification, and result recovery.

Planned proposed components:

- `orchestrator`: workflow entry point and transaction coordination.
- PostgreSQL: durable transaction and workflow state.
- Redis: coordination, leases, or cache experiments.
- Shared JSON schemas for portable test inputs and observed results.

## Repository Layout

```text
.
├── cart-service/
├── merchant-simulator/
├── orchestrator/
├── order-service/
├── payment-simulator/
├── python/
│   ├── failure-injector/
│   ├── llm-agent/
│   ├── mcp-server/
│   └── workload-generator/
├── schemas/
└── docker-compose.yml
```

## Run Infrastructure

```bash
docker compose up -d postgres redis
docker compose ps
```

If your environment uses the standalone Compose binary:

```bash
docker-compose up -d postgres redis
docker-compose ps
```

Stop infrastructure:

```bash
docker compose down
```

## Run Services Locally

Start the cart service:

```bash
mvn -pl cart-service spring-boot:run
```

Start the order service in another terminal:

```bash
mvn -pl order-service spring-boot:run
```

Start the payment simulator in another terminal:

```bash
mvn -pl payment-simulator spring-boot:run
```

Start the orchestrator in another terminal:

```bash
mvn -pl orchestrator spring-boot:run
```

Create a cart through the deterministic non-LLM flow:

```bash
curl -X POST http://localhost:8080/flows/create-cart \
  -H "Content-Type: application/json" \
  -d '{"customerId":"customer-001"}'
```

Expected response:

```json
{
  "cartId": "cart-customer-001",
  "customerId": "customer-001",
  "status": "OPEN",
  "items": []
}
```

## Test

```bash
mvn test
PYTHONPATH=python python3 -m unittest discover -s python/tests
```

## Execution Modes

`BASELINE` is modeled as a reasonable simple distributed workflow:

```text
Create Cart -> Add Item -> Create Order -> Execute Payment -> Complete
```

It uses sequential calls, basic exception behavior, and no durable transaction orchestration, recovery, or coordinated idempotency.

`RESILIENT` runs the same logical workflow but adds:

- durable transaction records in PostgreSQL when `--backend services` is used;
- in-process durable-enough state objects for fast `--backend simulation` validation;
- explicit state transitions;
- idempotency-key lookup;
- bounded retries for transient failures;
- deterministic order cancellation compensation;
- deterministic recovery of intermediate transaction states.

The services backend persists orchestrator state in `orchestrator_transactions` and service side effects in `carts`, `orders`, and `payments`.

## Run Experiments

Run a baseline experiment:

```bash
./run-experiment.sh \
  --backend simulation \
  --mode baseline \
  --scenario f0-no-failure \
  --transactions 100 \
  --concurrency 1 \
  --failure-rate 0.0 \
  --repetitions 1 \
  --seed 7
```

Run the same workload in resilient mode:

```bash
./run-experiment.sh \
  --backend simulation \
  --mode resilient \
  --scenario f0-no-failure \
  --transactions 100 \
  --concurrency 1 \
  --failure-rate 0.0 \
  --repetitions 1 \
  --seed 7
```

Run against the actual Spring Boot services after PostgreSQL and the services are running:

```bash
./run-experiment.sh \
  --backend services \
  --mode resilient \
  --scenario f0-no-failure \
  --transactions 10 \
  --concurrency 1 \
  --failure-rate 0.0 \
  --repetitions 1 \
  --seed 900
```

Supported scenarios:

- `f0-no-failure`
- `f1-cart-http-500`
- `f2-order-http-500`
- `f3-payment-http-500`
- `f4-payment-timeout-before-side-effect`
- `f5-payment-succeeds-response-lost`
- `f6-order-succeeds-response-lost`
- `f7-duplicate-transaction-request`
- `f8-concurrent-duplicate-transaction-requests`
- `f9-orchestrator-interruption-after-order`
- `f10-payment-permanently-fails`
- `f11-transient-payment-failure-recovery`
- `f12-compensation-failure-retry`

Additional boundary scenarios are available for focused tests:

- `cart-persisted-response-lost`
- `order-failure-before-persistence`
- `payment-persisted-response-lost`
- `orchestrator-interruption-after-cart`
- `orchestrator-interruption-during-payment`

Additional options:

```text
--transactions <count>
--concurrency <count>
--failure-rate <0.0-1.0>
--repetitions <count>
--seed <integer>
--backend <simulation|services>
--orchestrator-url <url>
--cart-url <url>
--order-url <url>
--payment-url <url>
--output-root <directory>
```

Outputs are written under:

```text
results/<mode>/<scenario>/<experimentId>/rep-0001/
results/<mode>/<scenario>/<experimentId>/rep-0002/
```

Each run writes:

- `transactions.jsonl`: raw per-transaction observed results.
- `summary.csv`: aggregated observed metrics.

For `--backend services`, durable transaction and side-effect state is stored in PostgreSQL. The JSONL and CSV files remain the raw experiment output and are not overwritten between repetitions.

Raw results are not overwritten between repetitions. A deterministic seed controls the failure injector and deterministic transaction IDs for reproducible runs.

## Experiment Methodology

Supported dimensions:

```text
transaction counts: 1000, 10000, 50000
concurrency levels: 1, 10, 50, 100
failure rates: 0.0, 0.01, 0.05, 0.10, 0.20
execution modes: baseline, resilient
repetitions: configurable
random seed: configurable
```

Phase A command shape:

```bash
./run-experiment.sh \
  --backend simulation \
  --mode baseline \
  --scenario f5-payment-succeeds-response-lost \
  --transactions 10000 \
  --concurrency 50 \
  --failure-rate 0.05 \
  --repetitions 5 \
  --seed 2026
```

Run the same command with `--mode resilient` for the paired comparison. Repeat for all F0-F12 scenarios.

Phase B varies selected high-value scenarios across failure rates `0.01`, `0.05`, `0.10`, `0.20` and concurrency `1`, `10`, `50`, `100`, with 5-10 repetitions.

Do not treat generated outputs as paper results until the intended experiment suite is explicitly run in the target environment.

## Invariants

Every transaction record includes cross-service invariant checks:

- At most one successful payment per logical idempotency identity.
- Completed transactions must have a valid order and successful payment.
- Repeated execution with the same identity must not create multiple successful orders.
- Compensated transactions must not leave an active order requiring payment.
- Recovery must preserve transaction identity.
- Cart, Order, Payment, and orchestrator state must agree with the final transaction outcome.

## Metrics

Raw transaction fields include:

```text
experimentId
executionMode
failureScenario / scenario
failureRate
transactionCount
concurrency
repetitionNumber
randomSeed
environmentMetadata
transactionId
idempotencyKey
cartId
orderId
paymentId
orderCount
successfulPaymentCount
activeOrderCount
transactionFinalState/status
duplicateOrder
duplicatePayment
orphanedOrder
startTimestamp
endTimestamp
latencyMs
recoveryTimeMs
retryCount
recovered
compensated
duplicateDetected
invariantViolation
invariantViolationType
failureReason
```

Summary fields include:

```text
successRate = successful_transactions / total_transactions
failureRate = failed_transactions / total_transactions
recoveryRate = recovered_transactions / total_transactions
compensationRate = compensated_transactions / total_transactions
duplicateOrderRate = duplicate_order_observations / total_transactions
duplicatePaymentRate = duplicate_payment_observations / total_transactions
orphanedOrderRate = orphaned_order_observations / total_transactions
invariantViolationRate = invariant_violations / total_transactions
p50Latency
p95Latency
p99Latency
throughput
averageRetryCount
recoveryTime
```

The harness reports only values observed during the run. It does not fabricate benchmark data or encode conclusions favoring either mode.

## Research Assumptions And Limitations

- `--backend simulation` remains useful for fast deterministic methodology validation.
- `--backend services` executes the workflow through the real HTTP service path: workload runner -> orchestrator -> Cart Service -> Order Service -> Payment Simulator.
- The services backend persists resilient orchestrator state in PostgreSQL. Redis is available in Compose but is not yet used by the current milestone.
- The current services backend records service-observed side effects by querying service inspection endpoints keyed by idempotency key.
- Retry counters in the services backend are currently coarse-grained and do not yet record every individual HTTP attempt across every operation.
- Payment, cart, order, and merchant behavior is simulated. No real payment provider, customer data, or production commerce integration is included.

## Health Endpoints

Each Java service exposes:

```text
GET /health
```

The cart service also exposes:

```text
POST /carts
GET /inspect/idempotency/{idempotencyKey}
```

The orchestrator exposes:

```text
POST /flows/create-cart
POST /transactions
POST /recovery/run
GET /transactions/idempotency/{idempotencyKey}
```

Order and payment services expose inspection endpoints under:

```text
GET /inspect/idempotency/{idempotencyKey}
```

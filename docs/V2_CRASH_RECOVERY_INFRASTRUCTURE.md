# V2 Crash/Restart Infrastructure

This document describes Phase V2.4 infrastructure. It is validation infrastructure, not a scientific campaign result.

## Compose topology

`docker-compose.v2.yml` defines the v2 container topology:

```text
experiment harness on host
  -> orchestrator container
      -> cart-service container
      -> order-service container
      -> payment-simulator container
      -> PostgreSQL container
```

Redis remains available in the Compose file for continuity with the original infrastructure, but it is not used by the measured transaction path.

The Java services use container service names internally:

- orchestrator -> `http://cart-service:8081`
- orchestrator -> `http://order-service:8082`
- orchestrator -> `http://payment-simulator:8083`
- all stateful services -> `jdbc:postgresql://postgres:5432/commerce_research`

The original `docker-compose.yml` remains available for historical/local infrastructure. The v2 topology is isolated in `docker-compose.v2.yml`.

Host-facing ports use a v2-specific default range to avoid colliding with local-development services:

- PostgreSQL: `${V2_POSTGRES_PORT:-15432}`;
- Redis: `${V2_REDIS_PORT:-16379}`;
- orchestrator: `${V2_ORCHESTRATOR_PORT:-18080}`;
- cart-service: `${V2_CART_PORT:-18081}`;
- order-service: `${V2_ORDER_PORT:-18082}`;
- payment-simulator: `${V2_PAYMENT_PORT:-18083}`.

Container-to-container traffic still uses the normal internal ports listed above.

## Docker images

The root `Dockerfile` is a multi-stage Java build:

- build image: `maven:3.9.9-eclipse-temurin-17`;
- runtime image: `eclipse-temurin:17-jre-jammy`;
- module selected by `MODULE` build argument;
- no credentials are baked into images;
- each image copies the module's Spring Boot jar explicitly.

Containerized Java services:

- `orchestrator`;
- `cart-service`;
- `order-service`;
- `payment-simulator`.

`merchant-simulator` is not part of the v2 measured path and is not included.

## Readiness checks

PostgreSQL uses `pg_isready`.

Java services use `/health` endpoints through Compose health checks.

The Python crash controller also polls health endpoints and does not rely on fixed startup sleeps.

## Orchestrator instance identity

The orchestrator creates an `orchestrator_instance_id` at Java process startup through `OrchestratorInstance`.

`GET /v2/instance` returns:

- `orchestratorInstanceId`;
- `startedAt`.

A true restart validation must show that the pre-crash and post-restart instance IDs differ.

## Deterministic crash point

The v2 crash point is enabled only by explicit headers:

- `X-V2-Crash-Point: after-order-persisted`
- `X-V2-Crash-Token: <token>`

The resilient transaction path first persists `ORDER_CREATED`, then records the crash point in `V2CrashPointRegistry`, then blocks. The Java application does not throw an exception and does not call `System.exit()`. The orchestrator must be killed externally by the crash controller.

`GET /v2/crash-points/{token}` reports whether the crash point has been reached, the transaction ID, state, point, and timestamp.

## Crash controller

`python/research_harness/v2_crash.py` provides `DockerComposeCrashController`.

Crash primitive:

```bash
docker-compose -f docker-compose.v2.yml -p agentic-commerce-v2 kill -s SIGKILL orchestrator
```

The controller records events for:

- `ORCHESTRATOR_KILL_REQUESTED`;
- `ORCHESTRATOR_PROCESS_EXITED`;
- `ORCHESTRATOR_UNAVAILABLE`;
- `ORCHESTRATOR_RESTART_REQUESTED`;
- `ORCHESTRATOR_RESTARTED`;
- `ORCHESTRATOR_HEALTHY`.

The event timestamps are sufficient to compute kill detection latency, downtime, restart latency, and crash-to-healthy time. Recovery timing is recorded by the future validation runner when it invokes recovery.

## Restart procedure

The controller restarts only the orchestrator:

```bash
docker-compose -f docker-compose.v2.yml -p agentic-commerce-v2 up -d --no-deps orchestrator
```

PostgreSQL, cart, order, and payment containers remain running. PostgreSQL state is therefore expected to survive orchestrator termination.

## Recovery procedure

For recovery-enabled configurations such as C7/C8, the future validation runner calls:

```text
POST /recovery/idempotency/{idempotencyKey}
X-V2-Configuration: C7
```

For C2, the Java orchestrator rejects explicit v2 recovery with `V2_RESTART_RECOVERY_DISABLED_FOR_C2`. This preserves the negative control: durable state can remain observable without being automatically repaired by restart.

## C2 semantics

C2 means deterministic identity plus durable coordinator state, but restart recovery disabled.

After orchestrator restart:

- persisted non-terminal state should remain queryable;
- the harness may observe state;
- the harness must not call recovery as a repair step;
- if recovery is called with `X-V2-Configuration: C2`, the orchestrator rejects it.

## C7 semantics

C7 means deterministic identity, durable coordinator state, idempotent side-effect lookup, and restart recovery.

For the current crash-after-order path with no injected downstream failure, C7 recovery should resume from durable state and continue to payment completion. Retry, compensation, and lost-response reconciliation are not intended to activate in the basic crash validation path. If later C7 tests require those dormant mechanisms to activate, the design must be revisited before final experiments.

## Service-log preservation

`DockerComposeCrashController.preserve_logs(output_dir, suffix)` writes one log file per service:

```text
<service>-pre-crash.log
<service>-post-restart.log
```

Pre-crash and post-restart orchestrator logs use distinct file names and are not overwritten by restart.

## Reset procedure

`DockerComposeCrashController.reset_database()` truncates only:

- `orchestrator_transactions`;
- `carts`;
- `orders`;
- `payments`.

It does not touch any result directory. It must be invoked explicitly and must not run during crash recovery.

## I5/I6 service observation

`python/research_harness/v2_service_observation.py` defines V2-only observation objects for:

- I5 recovery identity preservation;
- I6 terminal coordinator/downstream consistency;
- duplicate order count;
- duplicate successful payment count.

These checks are future v2 instrumentation only. They do not reinterpret historical Phase A/B1/B2 invariant values.

## Validation status

Unit tests validate:

- instance IDs;
- crash point status;
- C2 recovery rejection;
- crash point reachability before external kill;
- controller SIGKILL command construction;
- restart command construction;
- log preservation file naming;
- safe DB reset command construction;
- historical mode regression.

Docker/Compose build/start validation should be run as infrastructure validation only. It is not a scientific experiment and must not be reported as paper evidence.

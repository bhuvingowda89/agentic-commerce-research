from __future__ import annotations

import argparse
from pathlib import Path

from .models import Backend, ExecutionMode, FailureScenario
from .runner import run_experiment
from .service_backend import ServiceBackendConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic agentic commerce experiments.")
    parser.add_argument("--mode", choices=[mode.value for mode in ExecutionMode], required=True)
    parser.add_argument("--scenario", choices=[scenario.value for scenario in FailureScenario], default="none")
    parser.add_argument("--transactions", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--failure-rate", type=float, default=1.0)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--backend", choices=[backend.value for backend in Backend], default=Backend.SIMULATION.value)
    parser.add_argument("--orchestrator-url", default="http://localhost:8080")
    parser.add_argument("--cart-url", default="http://localhost:8081")
    parser.add_argument("--order-url", default="http://localhost:8082")
    parser.add_argument("--payment-url", default="http://localhost:8083")
    parser.add_argument("--output-root", type=Path, default=Path("results"))
    args = parser.parse_args()

    runs = run_experiment(
        mode=ExecutionMode(args.mode),
        scenario=FailureScenario(args.scenario),
        transactions=args.transactions,
        concurrency=args.concurrency,
        failure_rate=args.failure_rate,
        repetitions=args.repetitions,
        output_root=args.output_root,
        random_seed=args.seed,
        backend=Backend(args.backend),
        service_config=ServiceBackendConfig(
            orchestrator_url=args.orchestrator_url,
            cart_url=args.cart_url,
            order_url=args.order_url,
            payment_url=args.payment_url,
        ),
    )
    for index, run in enumerate(runs, start=1):
        print(f"repetition={index}")
        print(f"rawResults={run.raw_path}")
        print(f"summary={run.summary_path}")


if __name__ == "__main__":
    main()

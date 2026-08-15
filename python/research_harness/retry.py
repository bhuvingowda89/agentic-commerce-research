from __future__ import annotations

from dataclasses import dataclass

from .failures import InjectedFailure


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_backoff_ms: int = 100
    multiplier: int = 2

    def run(self, operation_name: str, operation):
        attempts = 0
        last_failure = None
        while attempts < self.max_attempts:
            try:
                return operation(), attempts
            except InjectedFailure as failure:
                last_failure = failure
                attempts += 1
                if not failure.transient or attempts >= self.max_attempts:
                    raise
        raise last_failure or RuntimeError(f"{operation_name} failed")


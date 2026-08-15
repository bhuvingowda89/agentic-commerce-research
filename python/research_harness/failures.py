from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import random

from .models import FailureScenario


class InjectedFailure(RuntimeError):
    def __init__(self, failure_type: str, transient: bool = False, response_lost: bool = False):
        super().__init__(failure_type)
        self.failure_type = failure_type
        self.transient = transient
        self.response_lost = response_lost


@dataclass(frozen=True)
class FailureConfig:
    scenario: FailureScenario = FailureScenario.F0_NO_FAILURE
    failure_rate: float = 1.0
    seed: int = 7


class FailureInjector:
    def __init__(self, config: FailureConfig):
        self.config = config
        self.random = random.Random(config.seed)
        self.operation_counts: dict[str, int] = defaultdict(int)

    def before_operation(self, operation: str) -> None:
        self.operation_counts[operation] += 1
        base_operation = operation.split(":", 1)[0]
        scenario = self.config.scenario

        if scenario == FailureScenario.F0_NO_FAILURE:
            return
        if scenario == FailureScenario.F1_CART_HTTP_500 and base_operation == "create_cart":
            self._maybe_raise("CART_HTTP_500", transient=False)
        if scenario == FailureScenario.F2_ORDER_HTTP_500 and base_operation == "create_order":
            self._maybe_raise("ORDER_HTTP_500", transient=False)
        if scenario == FailureScenario.F3_PAYMENT_HTTP_500 and base_operation == "execute_payment":
            self._maybe_raise("PAYMENT_HTTP_500", transient=False)
        if scenario == FailureScenario.ORDER_FAILURE_BEFORE_PERSISTENCE and base_operation == "create_order":
            self._maybe_raise("ORDER_FAILURE_BEFORE_PERSISTENCE", transient=False)
        if (
            scenario in {
                FailureScenario.F4_PAYMENT_TIMEOUT_BEFORE_SIDE_EFFECT,
                FailureScenario.F10_PAYMENT_PERMANENTLY_FAILS,
            }
            and base_operation == "execute_payment"
        ):
            transient = scenario == FailureScenario.F4_PAYMENT_TIMEOUT_BEFORE_SIDE_EFFECT
            self._maybe_raise(scenario.value.upper().replace("-", "_"), transient=transient)
        if scenario == FailureScenario.F11_TRANSIENT_PAYMENT_FAILURE_RECOVERY and base_operation == "execute_payment":
            if self.operation_counts[operation] <= 2:
                raise InjectedFailure("TRANSIENT_PAYMENT_FAILURE", transient=True)
        if scenario == FailureScenario.F12_COMPENSATION_FAILURE_RETRY and base_operation == "execute_payment":
            self._maybe_raise("PAYMENT_PERMANENTLY_FAILS", transient=False)
        if scenario == FailureScenario.F12_COMPENSATION_FAILURE_RETRY and base_operation == "cancel_order":
            if self.operation_counts[operation] == 1:
                raise InjectedFailure("COMPENSATION_TRANSIENT_FAILURE", transient=True)

    def after_operation(self, operation: str) -> None:
        scenario = self.config.scenario
        base_operation = operation.split(":", 1)[0]
        if scenario == FailureScenario.CART_PERSISTED_RESPONSE_LOST and base_operation == "create_cart":
            self._maybe_raise_response_lost("CART_PERSISTED_RESPONSE_LOST", operation)
        if scenario == FailureScenario.F6_ORDER_SUCCEEDS_RESPONSE_LOST and base_operation == "create_order":
            self._maybe_raise_response_lost("ORDER_PERSISTED_RESPONSE_LOST", operation)
        if scenario in {
            FailureScenario.F5_PAYMENT_SUCCEEDS_RESPONSE_LOST,
            FailureScenario.PAYMENT_PERSISTED_RESPONSE_LOST,
        }:
            if base_operation == "execute_payment":
                self._maybe_raise_response_lost("PAYMENT_PERSISTED_RESPONSE_LOST", operation)

    def _maybe_raise(self, failure_type: str, transient: bool) -> None:
        if self.random.random() <= self.config.failure_rate:
            raise InjectedFailure(failure_type, transient=transient)

    def _maybe_raise_response_lost(self, failure_type: str, operation: str) -> None:
        if self.random.random() <= self.config.failure_rate:
            raise InjectedFailure(failure_type, transient=True, response_lost=True)

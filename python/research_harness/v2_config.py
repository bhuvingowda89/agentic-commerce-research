from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Mechanism(str, Enum):
    DETERMINISTIC_IDENTITY = "deterministic_identity"
    DURABLE_STATE = "durable_state"
    IDEMPOTENT_SIDE_EFFECT_LOOKUP = "idempotent_side_effect_lookup"
    BOUNDED_RETRY = "bounded_retry"
    LOST_RESPONSE_RECONCILIATION = "lost_response_reconciliation"
    COMPENSATION = "compensation"
    RESTART_RECOVERY = "restart_recovery"


class IdentityMode(str, Enum):
    RANDOM = "random"
    DETERMINISTIC = "deterministic"


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class V2MechanismConfiguration:
    name: str
    identity_mode: IdentityMode
    mechanisms: frozenset[Mechanism] = field(default_factory=frozenset)
    runner_reconciliation_enabled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "mechanisms", frozenset(self.mechanisms))
        self.validate()

    @property
    def enabled_mechanisms(self) -> list[str]:
        return sorted(mechanism.value for mechanism in self.mechanisms)

    def has(self, mechanism: Mechanism) -> bool:
        return mechanism in self.mechanisms

    def validate(self) -> None:
        if not self.name:
            raise ConfigurationError("configuration name is required")
        if self.identity_mode == IdentityMode.RANDOM and self.has(Mechanism.DETERMINISTIC_IDENTITY):
            raise ConfigurationError("random identity cannot enable deterministic_identity")
        if self.identity_mode == IdentityMode.DETERMINISTIC and not self.has(Mechanism.DETERMINISTIC_IDENTITY):
            raise ConfigurationError("deterministic identity mode must enable deterministic_identity")
        if self.has(Mechanism.RESTART_RECOVERY) and not self.has(Mechanism.DURABLE_STATE):
            raise ConfigurationError("restart_recovery requires durable_state")
        if self.has(Mechanism.LOST_RESPONSE_RECONCILIATION) and not self.has(Mechanism.IDEMPOTENT_SIDE_EFFECT_LOOKUP):
            raise ConfigurationError("lost_response_reconciliation requires idempotent_side_effect_lookup")
        if self.has(Mechanism.LOST_RESPONSE_RECONCILIATION) and self.identity_mode != IdentityMode.DETERMINISTIC:
            raise ConfigurationError("lost_response_reconciliation requires deterministic identity")
        if self.has(Mechanism.IDEMPOTENT_SIDE_EFFECT_LOOKUP) and self.identity_mode != IdentityMode.DETERMINISTIC:
            raise ConfigurationError("idempotent_side_effect_lookup requires deterministic identity")
        if self.has(Mechanism.COMPENSATION) and not (
            self.has(Mechanism.DURABLE_STATE) or self.identity_mode == IdentityMode.DETERMINISTIC
        ):
            raise ConfigurationError("compensation requires durable_state or deterministic identity")
        if self.runner_reconciliation_enabled and not self.has(Mechanism.LOST_RESPONSE_RECONCILIATION):
            raise ConfigurationError("runner reconciliation cannot be enabled unless lost_response_reconciliation is enabled")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "identityMode": self.identity_mode.value,
            "enabledMechanisms": self.enabled_mechanisms,
            "runnerReconciliationEnabled": self.runner_reconciliation_enabled,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> V2MechanismConfiguration:
        mechanisms = frozenset(Mechanism(value) for value in payload.get("enabledMechanisms", []))
        return cls(
            name=str(payload["name"]),
            identity_mode=IdentityMode(str(payload["identityMode"])),
            mechanisms=mechanisms,
            runner_reconciliation_enabled=bool(payload.get("runnerReconciliationEnabled", False)),
        )


def configuration(name: str) -> V2MechanismConfiguration:
    try:
        return CONFIGURATIONS[name]
    except KeyError as exc:
        raise ConfigurationError(f"unknown v2 configuration: {name}") from exc


CONFIGURATIONS: dict[str, V2MechanismConfiguration] = {
    "C0": V2MechanismConfiguration("C0", IdentityMode.RANDOM, frozenset()),
    "C1": V2MechanismConfiguration(
        "C1",
        IdentityMode.DETERMINISTIC,
        frozenset({Mechanism.DETERMINISTIC_IDENTITY}),
    ),
    "C2": V2MechanismConfiguration(
        "C2",
        IdentityMode.DETERMINISTIC,
        frozenset({Mechanism.DETERMINISTIC_IDENTITY, Mechanism.DURABLE_STATE}),
    ),
    "C3": V2MechanismConfiguration(
        "C3",
        IdentityMode.DETERMINISTIC,
        frozenset({Mechanism.DETERMINISTIC_IDENTITY, Mechanism.DURABLE_STATE, Mechanism.BOUNDED_RETRY}),
    ),
    "C4": V2MechanismConfiguration(
        "C4",
        IdentityMode.DETERMINISTIC,
        frozenset({
            Mechanism.DETERMINISTIC_IDENTITY,
            Mechanism.DURABLE_STATE,
            Mechanism.IDEMPOTENT_SIDE_EFFECT_LOOKUP,
        }),
    ),
    "C5": V2MechanismConfiguration(
        "C5",
        IdentityMode.DETERMINISTIC,
        frozenset({
            Mechanism.DETERMINISTIC_IDENTITY,
            Mechanism.DURABLE_STATE,
            Mechanism.IDEMPOTENT_SIDE_EFFECT_LOOKUP,
            Mechanism.LOST_RESPONSE_RECONCILIATION,
        }),
        runner_reconciliation_enabled=False,
    ),
    "C6": V2MechanismConfiguration(
        "C6",
        IdentityMode.DETERMINISTIC,
        frozenset({Mechanism.DETERMINISTIC_IDENTITY, Mechanism.DURABLE_STATE, Mechanism.COMPENSATION}),
    ),
    "C7": V2MechanismConfiguration(
        "C7",
        IdentityMode.DETERMINISTIC,
        frozenset({
            Mechanism.DETERMINISTIC_IDENTITY,
            Mechanism.DURABLE_STATE,
            Mechanism.IDEMPOTENT_SIDE_EFFECT_LOOKUP,
            Mechanism.RESTART_RECOVERY,
        }),
    ),
    "C8": V2MechanismConfiguration(
        "C8",
        IdentityMode.DETERMINISTIC,
        frozenset({
            Mechanism.DETERMINISTIC_IDENTITY,
            Mechanism.DURABLE_STATE,
            Mechanism.IDEMPOTENT_SIDE_EFFECT_LOOKUP,
            Mechanism.BOUNDED_RETRY,
            Mechanism.LOST_RESPONSE_RECONCILIATION,
            Mechanism.COMPENSATION,
            Mechanism.RESTART_RECOVERY,
        }),
        runner_reconciliation_enabled=False,
    ),
}

"""Static restatement of the Frozen Test configuration contract.

The reconciliation and sealing pipeline checks gold labels for internal
consistency: an EXECUTE gold object must be a complete, valid configuration,
and a REJECT gold object must name a value that really violates the contract.
Those rules are restated here from the sealed benchmark specification so that
this package never imports ``agentic_anex``. Nothing in ``frozen_test_v2``
calls Phi4, ANEX, scope policy v2, or the schedule validator.

Contract profiles
-----------------
``frozen-test-v2`` is the contract under which the sealed Frozen Test v2 was
generated and adjudicated: ``interference_ratio`` may be any finite number
greater than or equal to 1.0.

``frozen-test-v3`` (the default) fixes ``interference_ratio`` at 1.0: the
interference range equals the communication range, which is the only model
the legacy ANEX implementation enforces. Any other explicit value is invalid.
With the ratio fixed at 1.0 the two collision models are equivalent, and both
literals remain valid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

ACTIONS: tuple[str, ...] = ("EXECUTE", "CLARIFY", "REJECT", "UNSUPPORTED")
DIFFICULTIES: tuple[str, ...] = ("easy", "medium", "hard")
AMBIGUITY_RISKS: tuple[str, ...] = ("none", "low", "medium", "high")
ITEM_QUALITIES: tuple[str, ...] = ("accept", "revise", "exclude")
COLLISION_MODELS: tuple[str, ...] = ("legacy_neighbor", "interference_range")
PARAPHRASES_PER_GROUP = 2

CONTRACT_FIELDS: tuple[str, ...] = (
    "topology_id",
    "workload",
    "objective",
    "channels",
    "interference_ratio",
    "collision_model",
    "latency_target_slots",
    "seed",
    "working_period",
    "communication_range",
)

DEFAULT_FIELDS: dict[str, Any] = {
    "workload": "one_shot",
    "objective": "minimize_latency",
    "channels": 2,
    "interference_ratio": 1.0,
    "collision_model": "legacy_neighbor",
    "latency_target_slots": None,
    "seed": 0,
    "working_period": 10,
    "communication_range": 18.0,
}

DEFAULT_TOPOLOGY_CATALOGUE: dict[str, dict[str, Any]] = {
    "legacy30_seed7": {"working_period": 10, "communication_range": 18.0},
}

# Keys that generators and reviewers attach next to contract fields as
# annotations rather than configuration values.
ANNOTATION_KEYS: frozenset[str] = frozenset({
    "invalid_fields",
    "unresolved",
    "also_missing",
    "also_invalid",
    "unsupported_capability",
    "configuration_bundle",
    "notes",
})

# Closed protocol categories of docs/frozen_test_v2_protocol.md and the gold
# action each one implies. Generators may attach ``protocol_category`` to a
# group; when present it must agree with ``proposed_gold_action``.
PROTOCOL_CATEGORY_ACTIONS: dict[str, str] = {
    "supported_default": "EXECUTE",
    "supported_configured": "EXECUTE",
    "supported_latency_target": "EXECUTE",
    "missing_information": "CLARIFY",
    "invalid_parameter": "REJECT",
    "unsupported_energy": "UNSUPPORTED",
    "unsupported_digital_twin_or_sync": "UNSUPPORTED",
    "unsupported_periodic": "UNSUPPORTED",
    "unsupported_topology_adaptation": "UNSUPPORTED",
    "unsupported_other_objective": "UNSUPPORTED",
}


@dataclass(frozen=True)
class ContractProfile:
    """A versioned set of contract rules.

    ``interference_ratio_fixed`` is ``None`` when any finite ratio >= 1.0 is
    valid, or the single value every explicit ratio must equal.
    """

    version: str
    interference_ratio_fixed: float | None
    description: str


CONTRACT_V2 = ContractProfile(
    version="frozen-test-v2",
    interference_ratio_fixed=None,
    description="interference_ratio may be any finite number >= 1.0 (sealed Frozen Test v2 rules)",
)
CONTRACT_V3 = ContractProfile(
    version="frozen-test-v3",
    interference_ratio_fixed=1.0,
    description=("interference_ratio must equal 1.0 (interference range equals communication "
                 "range); legacy_neighbor and interference_range are equivalent"),
)
CONTRACT_PROFILES: dict[str, ContractProfile] = {
    profile.version: profile for profile in (CONTRACT_V2, CONTRACT_V3)
}
DEFAULT_CONTRACT = CONTRACT_V3


def get_profile(profile: ContractProfile | str | None) -> ContractProfile:
    """Resolve a profile object, a version name, or ``None`` (the default)."""
    if profile is None:
        return DEFAULT_CONTRACT
    if isinstance(profile, ContractProfile):
        return profile
    try:
        return CONTRACT_PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"unknown contract profile {profile!r}; known profiles: "
                         f"{sorted(CONTRACT_PROFILES)}") from exc


def is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_finite_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def values_equal(left: Any, right: Any) -> bool:
    """Structural equality that keeps booleans distinct from numbers."""
    if is_bool(left) or is_bool(right):
        return is_bool(left) and is_bool(right) and left == right
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return (set(left) == set(right)
                and all(values_equal(left[key], right[key]) for key in left))
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return (len(left) == len(right)
                and all(values_equal(a, b) for a, b in zip(left, right)))
    if is_finite_number(left) and is_finite_number(right):
        return left == right
    return left == right


def contract_fields_only(fields: Any) -> dict[str, Any]:
    """Project a fields object onto the ten contract keys that are present."""
    if not isinstance(fields, Mapping):
        return {}
    return {key: fields[key] for key in CONTRACT_FIELDS if key in fields}


def missing_contract_fields(fields: Any) -> list[str]:
    if not isinstance(fields, Mapping):
        return list(CONTRACT_FIELDS)
    return [key for key in CONTRACT_FIELDS if key not in fields]


def field_violations(fields: Any,
                     catalogue: Mapping[str, Mapping[str, Any]] | None = None,
                     profile: ContractProfile | str | None = None) -> dict[str, str]:
    """Return ``{field: reason}`` for every present field that violates the contract.

    Absent fields are not reported; use :func:`missing_contract_fields` for
    completeness checks. ``profile`` selects the contract version.
    """
    catalogue = DEFAULT_TOPOLOGY_CATALOGUE if catalogue is None else catalogue
    profile = get_profile(profile)
    if not isinstance(fields, Mapping):
        return {"$": "configuration must be a JSON object"}
    problems: dict[str, str] = {}
    topology_spec: Mapping[str, Any] | None = None
    if "topology_id" in fields:
        topology = fields["topology_id"]
        if isinstance(topology, str) and topology in catalogue:
            topology_spec = catalogue[topology]
        else:
            problems["topology_id"] = (
                f"{topology!r} is not an available topology; available: {sorted(catalogue)}")
    if "workload" in fields and fields["workload"] != "one_shot":
        problems["workload"] = f"{fields['workload']!r} is not the supported literal 'one_shot'"
    if "objective" in fields and fields["objective"] != "minimize_latency":
        problems["objective"] = (
            f"{fields['objective']!r} is not the supported literal 'minimize_latency'")
    if "channels" in fields:
        value = fields["channels"]
        if not is_integer(value) or value < 1:
            problems["channels"] = f"{value!r} is not an integer >= 1"
    if "interference_ratio" in fields:
        value = fields["interference_ratio"]
        fixed = profile.interference_ratio_fixed
        if not is_finite_number(value) or value < 1.0:
            problems["interference_ratio"] = f"{value!r} is not a finite number >= 1.0"
        elif fixed is not None and value != fixed:
            problems["interference_ratio"] = (
                f"{value!r} is not the fixed value {fixed!r} required by contract "
                f"{profile.version} (interference range equals communication range)")
    if "collision_model" in fields and fields["collision_model"] not in COLLISION_MODELS:
        problems["collision_model"] = (
            f"{fields['collision_model']!r} is not one of {list(COLLISION_MODELS)}")
    if "latency_target_slots" in fields:
        value = fields["latency_target_slots"]
        if value is not None and (not is_integer(value) or value < 1):
            problems["latency_target_slots"] = f"{value!r} is not null or an integer >= 1"
    if "seed" in fields:
        value = fields["seed"]
        if not is_integer(value) or value < 0:
            problems["seed"] = f"{value!r} is not an integer >= 0"
    if "working_period" in fields:
        value = fields["working_period"]
        if not is_integer(value) or value < 1:
            problems["working_period"] = f"{value!r} is not an integer > 0"
        elif topology_spec is not None and value != topology_spec["working_period"]:
            problems["working_period"] = (
                f"{value!r} does not match the topology value {topology_spec['working_period']!r}")
    if "communication_range" in fields:
        value = fields["communication_range"]
        if not is_finite_number(value) or value <= 0:
            problems["communication_range"] = f"{value!r} is not a finite number > 0"
        elif topology_spec is not None and value != topology_spec["communication_range"]:
            problems["communication_range"] = (
                f"{value!r} does not match the topology value "
                f"{topology_spec['communication_range']!r}")
    return problems


def execute_configuration_problems(fields: Any,
                                   catalogue: Mapping[str, Mapping[str, Any]] | None = None,
                                   profile: ContractProfile | str | None = None
                                   ) -> list[str]:
    """Problems that make ``fields`` unusable as an EXECUTE gold configuration."""
    if not isinstance(fields, Mapping):
        return ["EXECUTE gold fields must be a complete configuration object"]
    problems = [f"missing field {name}" for name in missing_contract_fields(fields)]
    problems.extend(f"{name}: {reason}"
                    for name, reason in field_violations(fields, catalogue, profile).items())
    unknown = sorted(set(fields) - set(CONTRACT_FIELDS) - ANNOTATION_KEYS)
    if unknown:
        problems.append(f"unknown fields {unknown}")
    return problems


def unconfirmed_invalid_fields(fields: Any, invalid_fields: Mapping[str, Any],
                               catalogue: Mapping[str, Mapping[str, Any]] | None = None,
                               profile: ContractProfile | str | None = None
                               ) -> list[str]:
    """Names in ``invalid_fields`` that the contract does not confirm as invalid.

    An entry whose ``observed`` value is not a scalar (for example a
    contradiction recorded as an object) cannot be value-checked and is
    accepted as-is; it is never reported here.
    """
    base = contract_fields_only(fields)
    unconfirmed: list[str] = []
    for name, entry in invalid_fields.items():
        if name not in CONTRACT_FIELDS:
            unconfirmed.append(name)
            continue
        observed = entry.get("observed") if isinstance(entry, Mapping) else None
        if not is_scalar(observed):
            continue
        probe = dict(base)
        probe[name] = observed
        if name not in field_violations(probe, catalogue, profile):
            unconfirmed.append(name)
    return unconfirmed

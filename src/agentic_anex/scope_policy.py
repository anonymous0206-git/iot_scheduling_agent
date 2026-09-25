"""Independent closed-scope policy over raw Paper 1 user requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .schemas import JsonSchema


SCOPE_POLICY_VERSION = "paper1-scope-policy.v2"
CHECKED_TAXONOMY = (
    "digital_twin_or_emulation",
    "dynamic_state_synchronization",
    "energy_aware_scheduling",
    "residual_battery_evolution",
    "periodic_or_continuous_aggregation",
    "topology_adaptation",
    "unsupported_optimization_objective",
)


@dataclass(frozen=True)
class ScopeViolation(JsonSchema):
    category: str
    pattern_id: str
    message: str
    witness: str
    start: int
    end: int

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScopeViolation":
        return cls(**dict(data))


@dataclass(frozen=True)
class ScopePolicyReport(JsonSchema):
    supported: bool
    checked_taxonomy: tuple[str, ...]
    violations: tuple[ScopeViolation, ...]
    policy_version: str = SCOPE_POLICY_VERSION

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScopePolicyReport":
        payload = dict(data)
        payload["checked_taxonomy"] = tuple(payload["checked_taxonomy"])
        payload["violations"] = tuple(ScopeViolation.from_dict(item)
                                      for item in payload["violations"])
        return cls(**payload)


@dataclass(frozen=True)
class _Rule:
    category: str
    pattern_id: str
    pattern: re.Pattern[str]
    message: str


def _rule(category: str, pattern_id: str, pattern: str, message: str) -> _Rule:
    return _Rule(category, pattern_id, re.compile(pattern, re.IGNORECASE), message)


# The vocabulary is a closed Paper 1 capability taxonomy designed from the
# development split and domain specification. It intentionally uses
# compositional bounded patterns rather than Frozen Test v1 sentences.
_RULES = (
    _rule("digital_twin_or_emulation", "DT_NAMED_CAPABILITY",
          r"\b(?:digital\s+twin|network\s+emulat(?:or|ion)|cyber[ -]?physical\s+twin)\b",
          "Digital Twin and emulation capabilities are outside Paper 1."),
    _rule("digital_twin_or_emulation", "DT_VIRTUAL_REPRESENTATION",
          r"\bvirtual\b(?:\W+\w+){0,4}\W+\b(?:replica|representation|counterpart)\b",
          "A virtual network representation is outside Paper 1."),
    _rule("dynamic_state_synchronization", "DYNAMIC_STATE_FLOW",
          r"\b(?:stream|synchroni[sz]e|mirror|continuously\s+update)\w*\b"
          r"(?:\W+\w+){0,8}\W+\b(?:telemetry|sensor\s+state|network\s+state|physical\s+nodes?)\b",
          "Dynamic state synchronization is outside the static Paper 1 workflow."),
    _rule("dynamic_state_synchronization", "BIDIRECTIONAL_CONTROL",
          r"\b(?:bidirectional|closed[ -]?loop|real[ -]?time)\w*\b"
          r"(?:\W+\w+){0,8}\W+\b(?:control|synchroni[sz]e|actuat)\w*\b",
          "Bidirectional real-time control is outside Paper 1."),
    _rule("energy_aware_scheduling", "ENERGY_OBJECTIVE",
          r"\b(?:optimi[sz]|minimi[sz]|maximi[sz]|reduce|budget)\w*\b"
          r"(?:\W+\w+){0,6}\W+\b(?:energy|battery|power|network\s+lifetime)\b"
          r"|\b(?:energy|battery|power)\b(?:\W+\w+){0,6}\W+"
          r"\b(?:optimi[sz]|minimi[sz]|maximi[sz]|reduce|budget|efficien)\w*\b",
          "Energy-aware scheduling is outside the latency-only Paper 1 objective."),
    _rule("residual_battery_evolution", "BATTERY_EVOLUTION",
          r"\b(?:residual|remaining|evolving|deplet)\w*\b"
          r"(?:\W+\w+){0,5}\W+\b(?:battery|energy|charge)\b"
          r"|\b(?:battery|energy|charge)\b(?:\W+\w+){0,5}\W+"
          r"\b(?:evolution|depletion|trajectory|state)\b",
          "Battery-state evolution is outside the static Paper 1 model."),
    _rule("periodic_or_continuous_aggregation", "REPEATED_AGGREGATION",
          r"\b(?:periodic|continuous|recurring|repeated|ongoing)\w*\b"
          r"(?:\W+\w+){0,6}\W+\b(?:aggregation|collection|convergecast|scheduling|schedule)\b"
          r"|\b(?:aggregation|collection|convergecast)\b(?:\W+\w+){0,6}\W+"
          r"\b(?:periodic|continuous|recurring|repeated|ongoing)\w*\b",
          "Periodic or continuous aggregation is outside one-shot Paper 1."),
    _rule("topology_adaptation", "DYNAMIC_TOPOLOGY",
          r"\b(?:adapt|reconfigur|evolv|dynamic|repair)\w*\b"
          r"(?:\W+\w+){0,6}\W+\b(?:topology|routing\s+graph|network\s+structure|routes?)\b"
          r"|\b(?:topology|routing\s+graph|network\s+structure|routes?)\b"
          r"(?:\W+\w+){0,6}\W+\b(?:adapt|reconfigur|evolv|dynamic|repair)\w*\b",
          "Adaptive topology or routing is outside the static Paper 1 network."),
    _rule("unsupported_optimization_objective", "NON_LATENCY_OBJECTIVE",
          r"\b(?:optimi[sz]|minimi[sz]|maximi[sz])\w*\b"
          r"(?:\W+\w+){0,5}\W+\b(?:throughput|fairness|reliability|coverage|lifetime|hop\s+count|cost)\b",
          "The requested optimization objective is outside latency-only Paper 1."),
)


def evaluate_scope_policy(user_text: str) -> ScopePolicyReport:
    """Classify unsupported raw capabilities before any LLM interpretation."""
    violations = []
    seen = set()
    for rule in _RULES:
        match = rule.pattern.search(user_text)
        if match and rule.pattern_id not in seen:
            seen.add(rule.pattern_id)
            violations.append(ScopeViolation(
                rule.category, rule.pattern_id, rule.message,
                match.group(0), match.start(), match.end(),
            ))
    return ScopePolicyReport(not violations, CHECKED_TAXONOMY, tuple(violations))


def scope_error_code(report: ScopePolicyReport) -> str:
    categories = {item.category for item in report.violations}
    if categories & {"digital_twin_or_emulation", "dynamic_state_synchronization"}:
        return "UNSUPPORTED_DIGITAL_TWIN"
    if categories & {"energy_aware_scheduling", "residual_battery_evolution",
                     "unsupported_optimization_objective"}:
        return "UNSUPPORTED_OBJECTIVE"
    if "periodic_or_continuous_aggregation" in categories:
        return "UNSUPPORTED_WORKLOAD"
    return "UNSUPPORTED_CAPABILITY"


__all__ = ["SCOPE_POLICY_VERSION", "CHECKED_TAXONOMY", "ScopeViolation",
           "ScopePolicyReport", "evaluate_scope_policy", "scope_error_code"]

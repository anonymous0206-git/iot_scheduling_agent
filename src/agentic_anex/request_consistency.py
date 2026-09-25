"""Deterministic consistency checks for LLM-produced Paper 1 requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .schemas import JsonSchema, NetworkInstance, SchedulingRequest, SchemaError


@dataclass(frozen=True)
class RequestFieldCheck(JsonSchema):
    field: str
    expected: Any
    actual: Any
    source: str
    status: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RequestFieldCheck":
        return cls(**dict(data))


@dataclass(frozen=True)
class RequestConsistencyReport(JsonSchema):
    valid: bool
    checks: tuple[RequestFieldCheck, ...]
    checker_version: str = "paper1-request-consistency.v1"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RequestConsistencyReport":
        payload = dict(data)
        payload["checks"] = tuple(RequestFieldCheck.from_dict(item) for item in payload["checks"])
        return cls(**payload)


class RequestConsistencyError(SchemaError):
    def __init__(self, report: RequestConsistencyReport):
        failed = [check for check in report.checks if check.status == "mismatch"]
        fields = ", ".join(check.field for check in failed)
        super().__init__(
            f"LLM structured request conflicts with deterministic evidence: {fields}",
            path=failed[0].field if failed else None, code="REQUEST_FIELD_MISMATCH",
        )
        self.report = report

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(), "consistency": self.report.to_dict()}


_NUMBER = r"[-+]?\d+(?:\.\d+)?"
_INTEGER = r"[-+]?\d+"
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
          "six": 6, "seven": 7, "eight": 8, "nine": 9}


def _number(text: str, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group("value"))
    return None


def _integer_or_word(text: str, patterns: tuple[str, ...]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group("value").lower()
            return _WORDS.get(value, int(value) if value.lstrip("+-").isdigit() else None)
    return None


def explicit_request_fields(user_text: str) -> dict[str, Any]:
    """Extract only unambiguous controlled Paper 1 parameter statements."""
    # Preserve identifier separators while extracting numeric fields so a name
    # such as ``legacy30_seed7`` cannot masquerade as an explicit seed clause.
    text = user_text
    number_word = rf"(?:{_INTEGER}|{'|'.join(_WORDS)})"
    fields: dict[str, Any] = {}
    channels = _integer_or_word(text, (
        rf"\b(?P<value>{number_word})\s+(?:radio\s+)?(?:channels?|frequencies)\b",
        rf"\bchannels?\s*(?:=|:|of)?\s*(?P<value>{number_word})\b",
    ))
    if channels is not None:
        fields["channels"] = channels
    ratio = _number(text, (
        rf"\b(?:alpha|interference\s*(?:ratio|factor))\s*(?:=|:|of)?\s*(?P<value>{_NUMBER})\b",
        rf"\b(?P<value>{_NUMBER})\s+times?\s+the\s+communication\s+range\b",
    ))
    if ratio is None and re.search(r"\b(?:alpha|interference ratio)\s+(?:of\s+)?one half\b", text, re.I):
        ratio = 0.5
    if ratio is not None:
        fields["interference_ratio"] = ratio
    seed = _integer_or_word(text, (rf"\bseed\s*(?:=|:)?\s*(?P<value>{number_word})\b",))
    if seed is not None:
        fields["seed"] = seed
    target = _integer_or_word(text, (
        rf"\blatency\s+target\s+(?:of\s+)?(?P<value>{number_word})\s+slots?\b",
        rf"\bwithin\s+(?P<value>{number_word})\s+slots?\b",
        rf"\btarget\s+(?:of\s+)?(?P<value>{number_word})\s+slots?\b",
    ))
    if target is not None:
        fields["latency_target_slots"] = target
    period = _integer_or_word(text, (
        rf"\bworking[ -]?period\s*(?:=|:|of)?\s*(?P<value>{number_word})\b",
        rf"\bperiod\s+(?:of\s+)?(?P<value>{number_word})\s+slots?\b",
    ))
    if period is not None:
        fields["working_period"] = period
    communication_range = _number(text, (
        rf"\bcommunication\s+range\s*(?:=|:|of)?\s*(?P<value>{_NUMBER})\b",
    ))
    if communication_range is not None:
        fields["communication_range"] = communication_range
    normalized = text.lower().replace("-", " ").replace("_", " ")
    if "legacy neighbor" in normalized:
        fields["collision_model"] = "legacy_neighbor"
    elif any(phrase in normalized for phrase in
             ("interference range", "geometric collision", "geometric model",
              "validate interference out to")):
        fields["collision_model"] = "interference_range"
    if any(phrase in normalized for phrase in
           ("one shot", "single aggregation round", "single collection", "single round")):
        fields["workload"] = "one_shot"
    if any(phrase in normalized for phrase in
           ("minimize latency", "minimum latency", "minimize collection latency",
            "latency minimization")):
        fields["objective"] = "minimize_latency"
    return fields


def check_request_consistency(user_text: str, topology: NetworkInstance,
                              request: SchedulingRequest) -> RequestConsistencyReport:
    explicit = explicit_request_fields(user_text)
    defaults = {
        "channels": 2, "interference_ratio": 1.0, "collision_model": "legacy_neighbor",
        "seed": 0, "latency_target_slots": None,
        "workload": "one_shot", "objective": "minimize_latency",
    }
    actual = {
        "channels": request.channels, "interference_ratio": request.interference_ratio,
        "collision_model": request.collision_model, "seed": request.seed,
        "latency_target_slots": request.latency_target_slots, "workload": request.workload,
        "objective": request.objective, "working_period": request.network.working_period,
        "communication_range": request.network.communication_range,
    }
    checks: list[RequestFieldCheck] = []
    for field in ("workload", "objective", "channels", "interference_ratio",
                  "collision_model", "seed", "latency_target_slots"):
        expected = explicit.get(field, defaults[field])
        source = "explicit_user_text" if field in explicit else "documented_default"
        checks.append(RequestFieldCheck(field, expected, actual[field], source,
                                        "match" if actual[field] == expected else "mismatch"))
    for field, expected in (("working_period", topology.working_period),
                            ("communication_range", topology.communication_range)):
        source = "validated_topology"
        if field in explicit:
            expected, source = explicit[field], "explicit_user_text"
        checks.append(RequestFieldCheck(field, expected, actual[field], source,
                                        "match" if actual[field] == expected else "mismatch"))
    report = RequestConsistencyReport(not any(c.status == "mismatch" for c in checks), tuple(checks))
    if not report.valid:
        raise RequestConsistencyError(report)
    return report


__all__ = ["RequestFieldCheck", "RequestConsistencyReport", "RequestConsistencyError",
           "explicit_request_fields", "check_request_consistency"]

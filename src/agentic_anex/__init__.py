from .models import AnexConfig, AnexResult, ScheduleEntry, ValidationReport
from .runner import run_anex
from .topology import generate_connected_topology
from .validator import export_validation_certificate, validate_schedule, validation_certificate
from .schemas import (
    DomainError,
    InfeasibleNetworkError,
    NetworkInstance,
    NodeSpec,
    RequirementDecision,
    SchedulingRequest,
    SchedulingResult,
    SchemaError,
    UnsupportedRequestError,
)
from .topology_io import (
    generate_network_instance,
    legacy_nodes_to_network_instance,
    legacy_nodes_to_schedule_entries,
    load_json_topology,
    load_legacy_topology,
    network_instance_to_legacy_nodes,
    save_json_topology,
    topology_statistics,
)
from .llm_clients import ProviderConfig, create_llm_client
from .request_consistency import (
    RequestConsistencyError,
    RequestConsistencyReport,
    RequestFieldCheck,
    check_request_consistency,
    explicit_request_fields,
)
from .scope_policy import (
    SCOPE_POLICY_VERSION,
    ScopePolicyReport,
    ScopeViolation,
    evaluate_scope_policy,
)

_LAZY_VISUAL_EXPORTS = {
    "VisualizationArtifact",
    "render_topology",
    "render_schedule",
    "render_schedule_report",
    "render_interactive_schedule",
    "save_visualization",
}


def __getattr__(name):
    """Load visualization helpers only when explicitly requested.

    This keeps ``python -m agentic_anex.tools`` from pre-importing its target
    module through the package initializer, which otherwise triggers runpy's
    duplicate-module warning.
    """
    if name in _LAZY_VISUAL_EXPORTS:
        from . import visualization

        value = getattr(visualization, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AnexConfig",
    "AnexResult",
    "ScheduleEntry",
    "ValidationReport",
    "generate_connected_topology",
    "run_anex",
    "validate_schedule",
    "validation_certificate",
    "export_validation_certificate",
    "DomainError",
    "SchemaError",
    "UnsupportedRequestError",
    "InfeasibleNetworkError",
    "NodeSpec",
    "NetworkInstance",
    "SchedulingRequest",
    "SchedulingResult",
    "RequirementDecision",
    "load_legacy_topology",
    "load_json_topology",
    "save_json_topology",
    "generate_network_instance",
    "network_instance_to_legacy_nodes",
    "legacy_nodes_to_network_instance",
    "legacy_nodes_to_schedule_entries",
    "topology_statistics",
    "ProviderConfig",
    "create_llm_client",
    "RequestFieldCheck",
    "RequestConsistencyReport",
    "RequestConsistencyError",
    "explicit_request_fields",
    "check_request_consistency",
    "SCOPE_POLICY_VERSION",
    "ScopeViolation",
    "ScopePolicyReport",
    "evaluate_scope_policy",
    "VisualizationArtifact",
    "render_topology",
    "render_schedule",
    "render_schedule_report",
    "render_interactive_schedule",
    "save_visualization",
]

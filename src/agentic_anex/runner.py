from __future__ import annotations

import copy

from .legacy import anex_module
from .models import AnexConfig, AnexResult, ScheduleEntry, ValidationReport, Violation
from .schemas import ScheduleEntry as SchemaScheduleEntry
from .topology_io import legacy_nodes_to_network_instance
from .validator import validate_schedule


def run_anex(nodes, config: AnexConfig, *, copy_input: bool = True) -> AnexResult:
    """Execute the legacy ANEX algorithm through a stable typed boundary."""
    # Constructing the immutable schema performs ID, active-slot, edge, and
    # sink-connectivity checks before the potentially non-terminating legacy
    # tree builder is allowed to run.
    legacy_nodes_to_network_instance(
        nodes,
        working_period=config.working_period,
        communication_range=config.communication_range,
    )
    working_nodes = copy.deepcopy(nodes) if copy_input else nodes
    working_nodes, max_layer = anex_module.tree_construction_based_minimum_link_delay(
        working_nodes, config.working_period
    )
    anex_module.ANEX(
        working_nodes,
        config.working_period,
        config.channels,
        config.communication_range,
        config.interference_ratio,
    )
    schema_schedule = tuple(
        SchemaScheduleEntry(
            sender=u,
            receiver=working_nodes[u].parentID,
            timeslot=working_nodes[u].timeslot,
            channel=working_nodes[u].channel,
            receiver_active_slot=working_nodes[u].timeslot % config.working_period,
        )
        for u in range(1, len(working_nodes))
    )
    network = legacy_nodes_to_network_instance(
        working_nodes,
        working_period=config.working_period,
        communication_range=config.communication_range,
    )
    schema_report = validate_schedule(
        network,
        schema_schedule,
        channels=config.channels,
        interference_ratio=config.interference_ratio,
        collision_model="legacy_neighbor",
    )
    report = ValidationReport(
        valid=schema_report.valid,
        violations=tuple(Violation(
            item.code, item.message, item.nodes,
            {**item.details, "links": item.links, "timeslots": item.timeslots},
        ) for item in schema_report.violations),
        checked_nodes=schema_report.checked_nodes,
        secondary_collision_model="legacy_neighbor",
    )
    schedule = tuple(
        ScheduleEntry(
            sender=u,
            receiver=working_nodes[u].parentID,
            timeslot=working_nodes[u].timeslot,
            channel=working_nodes[u].channel,
            receiver_active_slot=working_nodes[u].timeslot % config.working_period,
        )
        for u in range(1, len(working_nodes))
    )
    legacy_max = max(entry.timeslot for entry in schedule)
    return AnexResult(
        config=config,
        schedule=schedule,
        validation=report,
        legacy_max_timeslot=legacy_max,
        elapsed_slots=legacy_max + 1,
        max_layer=max_layer,
        node_count=len(working_nodes),
        metadata={
            "legacy_active_slot_sampling_excludes_final_slot": True,
            "secondary_collision_model": "legacy_neighbor",
        },
    )

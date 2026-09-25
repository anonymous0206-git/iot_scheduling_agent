"""Dependency-free deterministic SVG/HTML visualization tools."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence, TypeVar

from .schemas import JsonSchema, NetworkInstance, ScheduleEntry, SchemaError, ValidationReport
from .tools import ScheduleMetrics, TraceRecord, measure_schedule
from .topology_io import load_json_topology, topology_statistics


@dataclass(frozen=True)
class VisualizationArtifact(JsonSchema):
    kind: Literal["topology_svg", "schedule_svg", "schedule_report_html",
                  "interactive_schedule_html"]
    media_type: Literal["image/svg+xml", "text/html"]
    content: str
    width: int
    height: int
    metadata: dict[str, Any]
    trace: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VisualizationArtifact":
        return cls(**dict(data))


R = TypeVar("R", bound=VisualizationArtifact)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _visual_call(name: str, payload: Any, operation: Callable[[], R]) -> R:
    encoded = json.dumps(
        payload.to_dict() if isinstance(payload, JsonSchema) else payload,
        sort_keys=True, separators=(",", ":"), default=str,
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    started = _now()
    try:
        result = operation()
    except Exception as exc:
        trace = TraceRecord(name, digest, started, _now(),
                            "domain_failure" if isinstance(exc, SchemaError) else "internal_exception",
                            type(exc).__name__)
        try:
            setattr(exc, "trace", trace.to_dict())
        except (AttributeError, TypeError):
            pass
        raise
    trace = TraceRecord(name, digest, started, _now(), "success")
    return replace(result, trace=trace.to_dict())


def _project(instance: NetworkInstance, width: int, height: int,
             margin: int = 55) -> dict[int, tuple[float, float]]:
    xs = [node.x for node in instance.nodes]
    ys = [node.y for node in instance.nodes]
    x_min, x_max, y_min, y_max = min(xs), max(xs), min(ys), max(ys)
    x_span, y_span = x_max - x_min, y_max - y_min
    scale = min(
        (width - 2 * margin) / x_span if x_span else float("inf"),
        (height - 2 * margin) / y_span if y_span else float("inf"),
    )
    if not (scale > 0 and scale != float("inf")):
        scale = 1.0
    used_width, used_height = x_span * scale, y_span * scale
    x_offset = (width - used_width) / 2
    y_offset = (height - used_height) / 2
    return {
        node.id: (x_offset + (node.x - x_min) * scale,
                  height - (y_offset + (node.y - y_min) * scale))
        for node in instance.nodes
    }


_CHANNEL_PALETTE = (
    "#0072B2", "#D55E00", "#009E73", "#CC79A7",
    "#E69F00", "#56B4E9", "#7A5195", "#5F5F5F",
)


def _channel_color(channel: int) -> str:
    """Return a stable, color-vision-friendly color for any channel count."""
    return _CHANNEL_PALETTE[(channel - 1) % len(_CHANNEL_PALETTE)]


def render_topology(
    instance: NetworkInstance,
    *, width: int = 900,
    height: int = 650,
    show_active_slots: bool = True,
    interference_ratio: float | None = None,
) -> VisualizationArtifact:
    """Render positions, communication links, sink, and duty-cycle slots."""
    def operation() -> VisualizationArtifact:
        if not isinstance(instance, NetworkInstance):
            raise SchemaError("must be a NetworkInstance", path="instance", code="INVALID_NETWORK")
        if width < 300 or height < 240:
            raise SchemaError("canvas must be at least 300x240", code="INVALID_CANVAS_SIZE")
        if interference_ratio is not None and interference_ratio < 1:
            raise SchemaError("must be at least 1", path="interference_ratio",
                              code="INVALID_INTERFERENCE_RATIO")
        points = _project(instance, width, height)
        lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="Network topology">',
            '<rect width="100%" height="100%" fill="#fbfcfe"/>',
            '<style>.edge{stroke:#aab4c3;stroke-width:1.4}.node{stroke:#172033;stroke-width:1.5}'
            '.label{font:12px sans-serif;fill:#172033}.slot{font:10px monospace;fill:#526071}</style>',
        ]
        by_id = {node.id: node for node in instance.nodes}
        for node in instance.nodes:
            for neighbor in node.neighbor_ids:
                if node.id < neighbor:
                    x1, y1 = points[node.id]; x2, y2 = points[neighbor]
                    lines.append(f'<line class="edge" x1="{x1:.2f}" y1="{y1:.2f}" '
                                 f'x2="{x2:.2f}" y2="{y2:.2f}"/>')
        for node_id in sorted(points):
            node = by_id[node_id]; x, y = points[node_id]
            if interference_ratio is not None:
                # Radius is shown symbolically because screen scale is derived
                # from the coordinate bounding box.
                xs = [point[0] for point in points.values()]
                coordinate_span = max(n.x for n in instance.nodes) - min(n.x for n in instance.nodes)
                screen_scale = ((max(xs) - min(xs)) / coordinate_span) if coordinate_span else 1
                radius = instance.communication_range * interference_ratio * screen_scale
                lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" '
                             'fill="none" stroke="#e59b45" stroke-opacity="0.10"/>')
            sink = node_id == instance.sink_id
            lines.append(f'<circle class="node" cx="{x:.2f}" cy="{y:.2f}" r="{10 if sink else 7}" '
                         f'fill="{"#ef476f" if sink else "#4ea8de"}"><title>Node {node_id}; '
                         f'active slots {html.escape(str(node.active_slots))}</title></circle>')
            lines.append(f'<text class="label" x="{x + 11:.2f}" y="{y + 4:.2f}">{node_id}'
                         f'{" (sink)" if sink else ""}</text>')
            if show_active_slots:
                slots = ",".join(str(slot) for slot in node.active_slots)
                lines.append(f'<text class="slot" x="{x + 11:.2f}" y="{y + 17:.2f}">[{slots}]</text>')
        stats = topology_statistics(instance)
        lines.append(f'<text class="label" x="16" y="24">nodes={stats["node_count"]} '
                     f'edges={stats["edge_count"]} max-hop={stats["max_bfs_layer"]}</text>')
        lines.append('<g aria-label="Legend" transform="translate(16 42)">'
                     '<circle class="node" cx="7" cy="0" r="7" fill="#ef476f"/>'
                     '<text class="label" x="19" y="4">sink</text>'
                     '<circle class="node" cx="75" cy="0" r="7" fill="#4ea8de"/>'
                     '<text class="label" x="87" y="4">sensor</text>'
                     '<line class="edge" x1="145" y1="0" x2="169" y2="0"/>'
                     '<text class="label" x="175" y="4">communication link</text></g>')
        lines.append('</svg>')
        return VisualizationArtifact(
            "topology_svg", "image/svg+xml", "".join(lines), width, height,
            {"statistics": stats, "interference_ratio": interference_ratio,
             "show_active_slots": show_active_slots},
        )
    return _visual_call("render_topology", {
        "instance": instance.to_dict() if isinstance(instance, NetworkInstance) else instance,
        "width": width, "height": height, "show_active_slots": show_active_slots,
        "interference_ratio": interference_ratio,
    }, operation)


def render_schedule(
    instance: NetworkInstance,
    schedule: Sequence[ScheduleEntry],
    *, validation: ValidationReport | None = None,
    width: int = 1100,
) -> VisualizationArtifact:
    """Render a sender-by-timeslot timeline colored by channel."""
    def operation() -> VisualizationArtifact:
        if not isinstance(instance, NetworkInstance):
            raise SchemaError("must be a NetworkInstance", code="INVALID_NETWORK")
        if not isinstance(schedule, (list, tuple)) or any(not isinstance(e, ScheduleEntry) for e in schedule):
            raise SchemaError("must contain ScheduleEntry values", code="INVALID_SCHEDULE")
        entries = tuple(sorted(schedule, key=lambda item: item.sender))
        max_slot = max((entry.timeslot for entry in entries), default=-1)
        rows = max(1, len(entries)); height = 76 + rows * 28
        left, right, top = 125, 25, 42
        plot_width = width - left - right
        cell_width = plot_width / max(1, max_slot + 1)
        violated = set()
        if validation:
            for violation in validation.violations:
                for sender in violation.nodes:
                    for timeslot in violation.timeslots:
                        violated.add((sender, timeslot))
        svg = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="ANEX schedule timeline">',
            '<rect width="100%" height="100%" fill="#fbfcfe"/>',
            '<defs><marker id="schedule-arrow" viewBox="0 0 10 10" refX="10" refY="5" '
            'markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" '
            'fill="#607086"/></marker></defs>',
            '<style>.axis{stroke:#cbd3df;stroke-width:1}.txt{font:11px sans-serif;fill:#172033}'
            '.small{font:9px sans-serif;fill:#fff;font-weight:bold}</style>',
        ]
        for slot in range(max_slot + 1):
            x = left + slot * cell_width
            svg.append(f'<line class="axis" x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height-20}"/>')
            svg.append(f'<text class="txt" x="{x + cell_width/2:.2f}" y="28" text-anchor="middle">{slot}</text>')
        for row, entry in enumerate(entries):
            y = top + row * 28
            svg.append(f'<text class="txt" x="8" y="{y + 18}">node {entry.sender}</text>')
            svg.append(f'<line x1="{55}" y1="{y + 14}" x2="{78}" y2="{y + 14}" '
                       'stroke="#607086" marker-end="url(#schedule-arrow)"/>')
            svg.append(f'<text class="txt" x="86" y="{y + 18}">{entry.receiver}</text>')
            svg.append(f'<line class="axis" x1="{left}" y1="{y + 24}" x2="{width-right}" y2="{y + 24}"/>')
            x = left + entry.timeslot * cell_width + 1
            bad = (entry.sender, entry.timeslot) in violated
            svg.append(f'<rect x="{x:.2f}" y="{y + 3}" width="{max(2, cell_width-2):.2f}" height="18" '
                       f'rx="3" fill="{_channel_color(entry.channel)}" '
                       f'stroke="{"#d90429" if bad else "none"}" stroke-width="3">'
                       f'<title>sender {entry.sender}, receiver {entry.receiver}, slot {entry.timeslot}, '
                       f'channel {entry.channel}</title></rect>')
            if cell_width >= 28:
                svg.append(f'<text class="small" x="{x + (cell_width-2)/2:.2f}" y="{y + 16}" '
                           f'text-anchor="middle">ch{entry.channel}</text>')
        svg.append('<g aria-label="Legend"><line x1="8" y1="16" x2="38" y2="16" '
                   'stroke="#607086" marker-end="url(#schedule-arrow)"/>'
                   '<text class="txt" x="46" y="20">sender to receiver; cell color = channel; red outline = violation</text></g>')
        svg.append('</svg>')
        return VisualizationArtifact(
            "schedule_svg", "image/svg+xml", "".join(svg), width, height,
            {"max_timeslot_index": max_slot, "latency_slots": max_slot + 1,
             "transmissions": len(entries), "violations_highlighted": len(violated)},
        )
    return _visual_call("render_schedule", {
        "instance": instance.to_dict() if isinstance(instance, NetworkInstance) else instance,
        "schedule": [entry.to_dict() for entry in schedule] if isinstance(schedule, (list, tuple)) else schedule,
        "validation": validation.to_dict() if validation else None, "width": width,
    }, operation)


def render_interactive_schedule(
    instance: NetworkInstance,
    schedule: Sequence[ScheduleEntry],
    *,
    validation: ValidationReport | None = None,
    slot_duration_ms: int = 1000,
    loop: bool = False,
    width: int = 1100,
    height: int = 720,
) -> VisualizationArtifact:
    """Render a deterministic, self-contained, timeslot-by-timeslot replay."""
    def operation() -> VisualizationArtifact:
        if not isinstance(instance, NetworkInstance):
            raise SchemaError("must be a NetworkInstance", path="instance", code="INVALID_NETWORK")
        if not isinstance(schedule, (list, tuple)) or any(
            not isinstance(entry, ScheduleEntry) for entry in schedule
        ):
            raise SchemaError("must contain ScheduleEntry values", path="schedule",
                              code="INVALID_SCHEDULE")
        if validation is not None and not isinstance(validation, ValidationReport):
            raise SchemaError("must be a ValidationReport", path="validation",
                              code="INVALID_VALIDATION_REPORT")
        if isinstance(slot_duration_ms, bool) or not isinstance(slot_duration_ms, int) \
                or slot_duration_ms <= 0:
            raise SchemaError("must be a positive integer", path="slot_duration_ms",
                              code="INVALID_SLOT_DURATION")
        if not isinstance(loop, bool):
            raise SchemaError("must be boolean", path="loop", code="INVALID_LOOP")
        if width < 640 or height < 480:
            raise SchemaError("canvas must be at least 640x480", code="INVALID_CANVAS_SIZE")

        entries = tuple(sorted(schedule, key=lambda item: (
            item.timeslot, item.sender, item.receiver, item.channel,
        )))
        max_slot = max((entry.timeslot for entry in entries), default=0)
        network_height = max(350, height - 260)
        points = _project(instance, width, network_height, margin=68)
        by_id = {node.id: node for node in instance.nodes}
        violations = tuple(validation.violations) if validation else ()

        def implicated(entry: ScheduleEntry) -> list[dict[str, Any]]:
            matches = []
            for violation in violations:
                slot_matches = not violation.timeslots or entry.timeslot in violation.timeslots
                if violation.links:
                    witness_matches = (entry.sender, entry.receiver) in violation.links
                else:
                    witness_matches = not violation.nodes or entry.sender in violation.nodes \
                        or entry.receiver in violation.nodes
                if slot_matches and witness_matches:
                    matches.append({
                        "code": violation.code, "message": violation.message,
                        "nodes": list(violation.nodes),
                        "links": [list(link) for link in violation.links],
                        "timeslots": list(violation.timeslots),
                    })
            return matches

        frames = []
        for slot in range(max_slot + 1):
            transmissions = []
            for entry in entries:
                if entry.timeslot != slot:
                    continue
                receiver = by_id.get(entry.receiver)
                transmissions.append({
                    **entry.to_dict(),
                    "receiver_is_active": bool(
                        receiver and entry.timeslot % instance.working_period in receiver.active_slots
                    ),
                    "violations": implicated(entry),
                })
            frames.append({"timeslot": slot, "transmissions": transmissions})

        channels = sorted({entry.channel for entry in entries})
        payload = {
            "schema_version": "1.0",
            "working_period": instance.working_period,
            "sink_id": instance.sink_id,
            "slot_duration_ms": slot_duration_ms,
            "loop": loop,
            "min_timeslot": 0,
            "max_timeslot": max_slot,
            "latency_slots": max_slot + 1,
            "nodes": [{
                **node.to_dict(), "screen_x": round(points[node.id][0], 2),
                "screen_y": round(points[node.id][1], 2),
            } for node in sorted(instance.nodes, key=lambda item: item.id)],
            "frames": frames,
            "channel_palette": {str(channel): _channel_color(channel) for channel in channels},
            "validation": validation.to_dict() if validation else None,
        }
        replay_json = json.dumps(payload, sort_keys=True, separators=(",", ":")).replace("</", "<\\/")

        edge_markup = []
        for node in sorted(instance.nodes, key=lambda item: item.id):
            for neighbor in sorted(node.neighbor_ids):
                if node.id < neighbor:
                    x1, y1 = points[node.id]; x2, y2 = points[neighbor]
                    edge_markup.append(
                        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}"/>'
                    )
        node_markup = []
        permanent_labels = len(instance.nodes) <= 35
        for node in sorted(instance.nodes, key=lambda item: item.id):
            x, y = points[node.id]
            node_markup.append(
                f'<g class="node idle{" sink" if node.id == instance.sink_id else ""}" '
                f'data-node="{node.id}" transform="translate({x:.2f} {y:.2f})">'
                f'<circle r="{11 if node.id == instance.sink_id else 8}"><title>Node {node.id}; '
                f'active slots {html.escape(str(node.active_slots))}</title></circle>'
                f'<text class="node-id" x="12" y="4">{node.id}</text></g>'
            )
            slots = ",".join(str(value) for value in node.active_slots)
            node_markup.append(
                f'<text class="active-slot-label" x="{x + 12:.2f}" y="{y + 17:.2f}">[{slots}]</text>'
            )
        tx_markup = []
        for index, entry in enumerate(entries):
            x1, y1 = points[entry.sender]; x2, y2 = points[entry.receiver]
            distance = math.hypot(x2 - x1, y2 - y1)
            if distance:
                unit_x, unit_y = (x2 - x1) / distance, (y2 - y1) / distance
                line_x1, line_y1 = x1 + unit_x * 10, y1 + unit_y * 10
                receiver_radius = 13 if entry.receiver == instance.sink_id else 10
                line_x2, line_y2 = x2 - unit_x * receiver_radius, y2 - unit_y * receiver_radius
            else:
                line_x1, line_y1, line_x2, line_y2 = x1, y1, x2, y2
            warnings = implicated(entry)
            warning_codes = ", ".join(item["code"] for item in warnings)
            title = (f"TX {entry.sender} to RX {entry.receiver}; slot {entry.timeslot}; "
                     f"CH {entry.channel}" + (f"; WARNING {warning_codes}" if warnings else ""))
            tx_markup.append(
                f'<g class="tx-event{" violated" if warnings else ""}" data-slot="{entry.timeslot}" '
                f'data-index="{index}" hidden><line class="tx-line" x1="{line_x1:.2f}" y1="{line_y1:.2f}" '
                f'x2="{line_x2:.2f}" y2="{line_y2:.2f}" stroke="{_channel_color(entry.channel)}" '
                f'marker-end="url(#arrow-{(entry.channel - 1) % len(_CHANNEL_PALETTE)})">'
                f'<title>{html.escape(title)}</title></line>'
                f'<text class="tx-label" x="{(x1+x2)/2:.2f}" y="{(y1+y2)/2-7:.2f}">'
                f'TX {entry.sender} → RX {entry.receiver} · CH {entry.channel}'
                f'{" ⚠ " + html.escape(warning_codes) if warnings else ""}</text></g>'
            )
        marker_markup = "".join(
            f'<marker id="arrow-{index}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" '
            f'orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>'
            for index, color in enumerate(_CHANNEL_PALETTE)
        )
        channel_legend = "".join(
            f'<span><i style="background:{_channel_color(channel)}"></i>CH {channel}</span>'
            for channel in channels
        ) or "<span>No transmissions</span>"
        timeline = "".join(
            f'<button class="timeline-slot future" data-slot="{slot}" type="button">{slot}</button>'
            for slot in range(max_slot + 1)
        )
        violation_rows = "".join(
            f'<li><strong>{html.escape(item.code)}</strong>: {html.escape(item.message)}; '
            f'nodes={html.escape(str(item.nodes))}; links={html.escape(str(item.links))}; '
            f'timeslots={html.escape(str(item.timeslots))}</li>'
            for item in violations
        ) or "<li>No supplied violations.</li>"
        loop_checked = " checked" if loop else ""
        labels_class = "" if permanent_labels else " dense"

        document = f'''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ANEX interactive schedule replay</title><style>
:root{{--ink:#172033;--muted:#607086;--panel:#fff;--bg:#f3f6fa;--danger:#c1121f}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px system-ui,sans-serif}}
main{{max-width:{width}px;margin:auto;padding:14px}}h1{{font-size:20px;margin:0 0 4px}}.scientific-note{{color:var(--muted)}}
.card{{background:var(--panel);border:1px solid #d7deea;border-radius:9px;padding:10px;margin:10px 0}}
#network{{width:100%;height:auto;display:block;background:#fbfcfe}}#communication-links line{{stroke:#c6cfdb;stroke-width:1.2}}
.overlay-hidden{{display:none!important}}
.node circle{{stroke:#172033;stroke-width:1.7;fill:#b7c4d4;transition:fill .15s}}.node.idle circle{{fill:#b7c4d4}}
.node.completed circle{{fill:#6cbd75}}.node.sender circle{{fill:#f0a202;stroke-width:3}}
.node.receiver circle{{fill:#8b5cf6;stroke-width:3}}.node.sink circle{{fill:#ef476f}}
.node.sender.receiver circle{{stroke:#6d28d9;stroke-width:4}}.node-id{{font-size:11px;fill:#172033}}
.dense .node-id{{display:none}}.dense .node:hover .node-id{{display:block;font-weight:bold}}
.active-slot-label{{font:9px ui-monospace,monospace;fill:#607086}}.tx-event{{display:none}}.tx-event.is-current{{display:inline}}
.tx-line{{stroke-width:4;stroke-dasharray:10 7;animation:flow .65s linear infinite}}
.tx-label{{font:11px system-ui,sans-serif;font-weight:700;paint-order:stroke;stroke:#fff;stroke-width:4;stroke-linejoin:round;fill:#172033}}
.tx-event.violated .tx-line{{stroke:var(--danger)!important;stroke-width:7;filter:drop-shadow(0 0 2px #fff)}}
.tx-event.violated .tx-label{{fill:var(--danger)}}@keyframes flow{{to{{stroke-dashoffset:-17}}}}
.controls{{display:flex;flex-wrap:wrap;gap:7px;align-items:center}}button,select,input{{font:inherit}}button{{padding:6px 10px}}
#timeline{{display:flex;overflow-x:auto;gap:3px;padding:5px 0}}.timeline-slot{{min-width:34px;border:1px solid #bac5d3;background:#fff}}
.timeline-slot.completed{{background:#d8f0dc}}.timeline-slot.current{{background:#172033;color:#fff}}.timeline-slot.future{{background:#fff}}
.legend,.channel-legend{{display:flex;gap:12px;flex-wrap:wrap;align-items:center}}.legend i,.channel-legend i{{display:inline-block;width:13px;height:13px;border:1px solid #172033;margin-right:4px;vertical-align:-2px}}
.legend .idle{{background:#b7c4d4}}.legend .sender{{background:#f0a202}}.legend .receiver{{background:#8b5cf6}}.legend .done{{background:#6cbd75}}.legend .sink{{background:#ef476f}}
table{{border-collapse:collapse;width:100%}}th,td{{border-bottom:1px solid #d7deea;text-align:left;padding:5px}}.warning{{color:var(--danger);font-weight:700}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}@media(max-width:750px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main><h1>ANEX interactive schedule replay</h1>
<p class="scientific-note">Deterministic replay of a computed schedule. This is not a network emulator, real-time execution environment, simulator, or Digital Twin.</p>
<section class="card"><div class="controls">
<button id="play-button" type="button">Play</button><button id="pause-button" type="button">Pause</button>
<button id="previous-slot-button" type="button">Previous slot</button><button id="next-slot-button" type="button">Next slot</button>
<button id="restart-button" type="button">Restart</button>
<label>Timeline <input id="timeline-slider" type="range" min="0" max="{max_slot}" value="0" step="1"></label>
<label>Speed <select id="playback-speed"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option><option value="4">4×</option></select></label>
<label><input id="loop-toggle" type="checkbox"{loop_checked}> Loop</label>
<label><input id="links-toggle" type="checkbox" checked> Background communication links</label>
<label><input id="active-slots-toggle" type="checkbox" checked> Active-slot labels</label></div>
<div id="timeline" aria-label="Schedule timeslots">{timeline}</div></section>
<section class="card"><svg id="network" class="network{labels_class}" viewBox="0 0 {width} {network_height}" role="img" aria-label="Interactive ANEX network schedule">
<defs>{marker_markup}</defs><g id="communication-links">{"".join(edge_markup)}</g>
<g id="nodes">{"".join(node_markup)}</g><g id="transmissions">{"".join(tx_markup)}</g></svg></section>
<div class="legend card"><strong>Node states:</strong><span><i class="sink"></i>Sink</span><span><i class="idle"></i>Idle</span><span><i class="sender"></i>Sender (TX)</span><span><i class="receiver"></i>Receiver (RX)</span><span><i class="done"></i>Completed</span></div>
<div class="channel-legend card"><strong>Channels:</strong>{channel_legend}<span class="warning">Red outline = supplied violation witness</span></div>
<div class="grid"><section class="card"><h2>Current slot: <span id="current-timeslot">0</span></h2>
<p>Simultaneous transmissions: <strong id="simultaneous-count">0</strong></p><table><thead><tr><th>Sender (TX)</th><th>Receiver (RX)</th><th>Channel (CH)</th><th>Receiver active</th><th>Warnings</th></tr></thead><tbody id="transmissions-body"></tbody></table></section>
<section class="card"><h2>Supplied validation evidence</h2><ul id="validation-evidence">{violation_rows}</ul></section></div>
<script type="application/json" id="anex-replay-data">{replay_json}</script>
<script>(()=>{{'use strict';const data=JSON.parse(document.getElementById('anex-replay-data').textContent);
let current=0,timer=null,loopEnabled=data.loop;const slider=document.getElementById('timeline-slider'),body=document.getElementById('transmissions-body');
const esc=v=>String(v).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
function pause(){{if(timer!==null){{clearInterval(timer);timer=null}}}}
function render(slot){{current=Math.max(0,Math.min(data.max_timeslot,Number(slot)));const frame=data.frames[current];slider.value=String(current);
document.getElementById('current-timeslot').textContent=String(current);document.getElementById('simultaneous-count').textContent=String(frame.transmissions.length);
const sentBefore=new Set();data.frames.slice(0,current).forEach(f=>f.transmissions.forEach(t=>sentBefore.add(t.sender)));
document.querySelectorAll('.node').forEach(n=>{{const id=Number(n.dataset.node);n.classList.remove('idle','completed','sender','receiver');n.classList.add(sentBefore.has(id)?'completed':'idle');}});
frame.transmissions.forEach(t=>{{const s=document.querySelector(`.node[data-node="${{t.sender}}"]`),r=document.querySelector(`.node[data-node="${{t.receiver}}"]`);if(s){{s.classList.remove('idle','completed');s.classList.add('sender')}}if(r){{r.classList.remove('idle','completed');r.classList.add('receiver')}}}});
document.querySelectorAll('.tx-event').forEach(e=>{{const active=Number(e.dataset.slot)===current;e.hidden=!active;e.classList.toggle('is-current',active)}});
document.querySelectorAll('.timeline-slot').forEach(b=>{{const s=Number(b.dataset.slot);b.className='timeline-slot '+(s<current?'completed':s===current?'current':'future')}});
body.innerHTML=frame.transmissions.map(t=>`<tr class="${{t.violations.length?'warning':''}}"><td>TX ${{esc(t.sender)}}</td><td>RX ${{esc(t.receiver)}}</td><td>CH ${{esc(t.channel)}}</td><td>${{t.receiver_is_active?'yes':'no'}} (slot ${{esc(t.receiver_active_slot)}})</td><td>${{t.violations.map(v=>esc(v.code)+' — nodes='+esc(JSON.stringify(v.nodes))+', links='+esc(JSON.stringify(v.links))+', timeslots='+esc(JSON.stringify(v.timeslots))).join('<br>')||'—'}}</td></tr>`).join('')||'<tr><td colspan="5">No transmission in this slot.</td></tr>';}}
function play(){{pause();timer=setInterval(()=>{{if(current>=data.max_timeslot){{if(loopEnabled)render(0);else pause()}}else render(current+1)}},data.slot_duration_ms/Number(document.getElementById('playback-speed').value))}}
document.getElementById('play-button').onclick=play;document.getElementById('pause-button').onclick=pause;
document.getElementById('previous-slot-button').onclick=()=>{{pause();render(current-1)}};document.getElementById('next-slot-button').onclick=()=>{{pause();render(current+1)}};
document.getElementById('restart-button').onclick=()=>{{pause();render(0)}};slider.oninput=()=>{{pause();render(slider.value)}};
document.getElementById('playback-speed').onchange=()=>{{if(timer!==null)play()}};document.querySelectorAll('.timeline-slot').forEach(b=>b.onclick=()=>{{pause();render(b.dataset.slot)}});
document.getElementById('loop-toggle').onchange=e=>{{loopEnabled=e.target.checked}};
document.getElementById('links-toggle').onchange=e=>document.getElementById('communication-links').classList.toggle('overlay-hidden',!e.target.checked);
document.getElementById('active-slots-toggle').onchange=e=>document.querySelectorAll('.active-slot-label').forEach(n=>n.classList.toggle('overlay-hidden',!e.target.checked));
document.addEventListener('keydown',e=>{{if(['INPUT','SELECT','BUTTON'].includes(document.activeElement.tagName))return;if(e.key==='ArrowLeft'){{pause();render(current-1)}}if(e.key==='ArrowRight'){{pause();render(current+1)}}}});render(0);
}})();</script></main></body></html>'''
        return VisualizationArtifact(
            "interactive_schedule_html", "text/html", document, width, height,
            {"max_timeslot_index": max_slot, "latency_slots": max_slot + 1,
             "frame_count": max_slot + 1, "transmissions": len(entries),
             "channels": channels, "slot_duration_ms": slot_duration_ms, "loop": loop,
             "validation_supplied": validation is not None,
             "violation_count": len(violations), "self_contained": True},
        )
    return _visual_call("render_interactive_schedule", {
        "instance": instance.to_dict() if isinstance(instance, NetworkInstance) else instance,
        "schedule": [entry.to_dict() for entry in schedule]
        if isinstance(schedule, (list, tuple)) else schedule,
        "validation": validation.to_dict() if isinstance(validation, ValidationReport) else validation,
        "slot_duration_ms": slot_duration_ms, "loop": loop, "width": width, "height": height,
    }, operation)


def render_schedule_report(
    instance: NetworkInstance,
    schedule: Sequence[ScheduleEntry],
    validation: ValidationReport,
) -> VisualizationArtifact:
    """Create a self-contained HTML report with topology, timeline, and evidence."""
    def operation() -> VisualizationArtifact:
        topology = render_topology(instance)
        timeline = render_schedule(instance, schedule, validation=validation)
        metrics: ScheduleMetrics = measure_schedule(instance, schedule)
        violation_rows = "".join(
            "<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in (
                item.code, item.message, item.nodes, item.links, item.timeslots
            )) + "</tr>"
            for item in validation.violations
        ) or '<tr><td colspan="5">No violations</td></tr>'
        document = f'''<!doctype html><html><head><meta charset="utf-8">
<title>ANEX schedule report</title><style>
body{{font-family:system-ui,sans-serif;color:#172033;margin:24px;background:#f5f7fa}}
section{{background:white;padding:18px;margin:16px 0;border-radius:10px;box-shadow:0 1px 5px #ccd3dd}}
svg{{max-width:100%;height:auto}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #d8dee8;padding:6px;text-align:left}}.ok{{color:#16803c}}.bad{{color:#c1121f}}
</style></head><body><h1>ANEX schedule report</h1>
<p class="{'ok' if validation.valid else 'bad'}">Validation: {'PASS' if validation.valid else 'FAIL'} ·
latency {metrics.latency_slots} slots · max index {metrics.max_timeslot_index}</p>
<section><h2>Topology</h2>{topology.content}</section>
<section><h2>Schedule timeline</h2>{timeline.content}</section>
<section><h2>Validation evidence</h2><table><thead><tr><th>Code</th><th>Message</th>
<th>Nodes</th><th>Links</th><th>Timeslots</th></tr></thead><tbody>{violation_rows}</tbody></table></section>
</body></html>'''
        return VisualizationArtifact(
            "schedule_report_html", "text/html", document, 1100,
            topology.height + timeline.height,
            {"validation_valid": validation.valid,
             "metrics": json.loads(json.dumps(metrics.to_dict(), sort_keys=True))},
        )
    return _visual_call("render_schedule_report", {
        "instance": instance.to_dict(), "schedule": [entry.to_dict() for entry in schedule],
        "validation": validation.to_dict(),
    }, operation)


def save_visualization(artifact: VisualizationArtifact, path: str | Path,
                       *, overwrite: bool = False) -> None:
    if not isinstance(artifact, VisualizationArtifact):
        raise SchemaError("must be a VisualizationArtifact", code="INVALID_VISUALIZATION")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with destination.open(mode, encoding="utf-8") as handle:
        handle.write(artifact.content)


def _load_schedule(path: str | Path) -> tuple[ScheduleEntry, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = payload.get("schedule", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise SchemaError("schedule must be an array or SchedulingResult object",
                          code="INVALID_SCHEDULE_JSON")
    return tuple(ScheduleEntry.from_dict(item) for item in raw)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Render deterministic ANEX visualizations")
    commands = parser.add_subparsers(dest="command", required=True)
    topology_parser = commands.add_parser("topology")
    topology_parser.add_argument("--network", required=True); topology_parser.add_argument("--output", required=True)
    topology_parser.add_argument("--interference-ratio", type=float)
    for name in ("schedule", "report", "animate"):
        command = commands.add_parser(name)
        command.add_argument("--network", required=True); command.add_argument("--schedule", required=True)
        command.add_argument("--validation"); command.add_argument("--output", required=True)
        if name == "animate":
            command.add_argument("--slot-duration-ms", type=int, default=1000)
            command.add_argument("--loop", action="store_true")
    args = parser.parse_args(argv)
    network = load_json_topology(args.network)
    if args.command == "topology":
        artifact = render_topology(network, interference_ratio=args.interference_ratio)
    else:
        schedule = _load_schedule(args.schedule)
        if args.validation:
            validation = ValidationReport.from_json(Path(args.validation).read_text(encoding="utf-8"))
        elif args.command == "animate":
            validation = None
        else:
            from .tools import ValidationMode, validate_schedule
            validation = validate_schedule(
                network, schedule,
                ValidationMode("legacy_neighbor", max((entry.channel for entry in schedule), default=1), 1.0),
            )
        if args.command == "schedule":
            artifact = render_schedule(network, schedule, validation=validation)
        elif args.command == "report":
            assert validation is not None
            artifact = render_schedule_report(network, schedule, validation)
        else:
            artifact = render_interactive_schedule(
                network, schedule, validation=validation,
                slot_duration_ms=args.slot_duration_ms, loop=args.loop,
            )
    save_visualization(artifact, args.output)
    print(json.dumps({"output": str(args.output), "kind": artifact.kind,
                      "trace": artifact.trace}, indent=2))


if __name__ == "__main__":
    main()


__all__ = [
    "VisualizationArtifact", "render_topology", "render_schedule",
    "render_schedule_report", "render_interactive_schedule", "save_visualization", "main",
]

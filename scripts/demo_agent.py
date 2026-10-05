#!/usr/bin/env python3
"""Interactive demo: type a request in plain English, watch the pipeline decide.

This is the paper's pipeline, not a simplified re-implementation. It calls the
same `Orchestrator` the experiments call, with the same scope policy, the same
topology-binding rule and the same independent validator, so what you see here
is what Section 5 measures.

What the demo adds is a view of *where* a request was decided. Each stage that
can terminate a run prints a line, so a refusal that came from the regular
expressions in `scope_policy.py` before the model was ever called looks
different from one the model chose. That difference is the paper's subject, and
it is invisible in the answer alone.

    # no model needed, deterministic, good for a dry run
    python scripts/demo_agent.py --provider mock

    # a local model through Ollama
    python scripts/demo_agent.py --provider ollama --model phi4:14b

    # the frontier arm
    OPENAI_API_KEY=... python scripts/demo_agent.py \
        --provider openai --model gpt-5.5-2026-04-23

`:mode off` and `:mode advisory` move the gate's authority during a session,
which is the ablation of Sections 5.2 and 5.3 run by hand: the same request,
the same detector, a different decision about who may act on it.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from agentic_anex.llm_clients import MockLLMClient, ProviderConfig, create_llm_client
from agentic_anex.orchestration import Orchestrator, RequirementAgent
from agentic_anex.schemas import DomainError, SchemaError
from agentic_anex.topology_io import load_json_topology
from agentic_anex.visualization import render_interactive_schedule, save_visualization
from frozen_test_v2.harness import bind_topologies

DEFAULT_CATALOGUE = ROOT / "benchmarks/topologies/frozen_test_v3_llm_catalogue.json"

EXAMPLES = (
    ("executes", "Plan one collection on topo100_seed0 with three channels and give me the slot count."),
    ("executes, the contract's defaults fill the rest",
     "Schedule a single round of aggregation on legacy30_seed7."),
    ("the gate catches it: the capability is named",
     "Build a digital twin of topo50_seed0 and keep it synchronised."),
    ("the gate misses it: same capability, no keyword",
     "Keep topo50_seed0 mirrored in software with each node's state refreshed continuously."),
    ("the gate misses it: periodic collection, described not named",
     "On topo50_seed0, have the nodes report again every ten minutes from now on."),
    ("the gate over-blocks: a supported request that mentions battery",
     "The earlier study optimised battery life; this one minimises latency alone. Use topo250_seed0 with four channels."),
    ("stage 2 rejects: a parameter outside its domain",
     "Run one collection on topo100_seed0 with 0 channels."),
    ("stage 3 asks: no catalogue topology is named",
     "Plan one collection on the fifty-node network with two channels."),
    ("nothing binds: the topology is not in the catalogue",
     "Plan one collection on topo999_seed3."),
)

BANNER = """\
Agentic ANEX demo --- the pipeline of Sections 3 and 5.
Type a request in plain English. Commands start with a colon.

  :help        this text                :examples    sample requests, numbered
  :topologies  what the catalogue holds  :e <n>       run example <n>
  :mode <m>    gate authority: enforcing | advisory | off
  :last        the full JSON report for the last request
  :quit
"""

#: Error codes stage 2 raises when a value stated in the raw text is outside
#: its domain. Reading the code is how we tell stage 2 apart from a later
#: rejection that happens to carry the same action.
STAGE_2_CODES = frozenset({
    "INVALID_CHANNEL_COUNT", "INVALID_INTERFERENCE_RATIO", "INVALID_LATENCY_TARGET",
})


def deciding_stage(report, mode: str) -> str:
    """Which part of the pipeline ended the run.

    The action alone does not say: an \textsc{unsupported} answer can come from
    the gate or from the model, and the paper's first finding is precisely the
    difference. The reliable evidence is whether the model was called at all,
    which the ledger records as the interaction log, plus the error code.
    """
    code = report.error.get("code") if isinstance(report.error, Mapping) else None
    if not report.llm_logs:
        policy = report.scope_policy
        if mode == "enforcing" and policy is not None and not policy.supported:
            return "the scope gate, stage 1, before the model ran"
        if code in STAGE_2_CODES:
            return "parameter legality, stage 2, before the model ran"
        if code == "MISSING_TOPOLOGY":
            return "the topology gate, stage 3, before the model ran"
        return "a deterministic stage, before the model ran"
    if code and (code.startswith("PROVIDER_") or code in {"LLM_CLIENT_ERROR",
                                                           "INVALID_LLM_RESPONSE"}):
        return f"nothing: the provider call failed ({code})"
    if report.status == "EXECUTE":
        return "the model, and the deterministic stages sustained it"
    return "the model, or a check on what it returned"


def load_catalogue(path: Path) -> dict[str, Any]:
    """Read a topology catalogue in either shape the repository ships.

    `frozen_test_v3_llm_catalogue.json` is a bare mapping of id to entry. The
    generated catalogues under `benchmarks/topologies/*/catalogue.json` wrap the
    same mapping in a document that also records how they were produced, and put
    it under `topologies`. Reading only the first shape silently yields the six
    keys of the wrapper and makes all 180 topologies look absent.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"cannot read the topology catalogue {path}: {exc}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"the topology catalogue {path} is not JSON: {exc}")
    if not isinstance(data, Mapping):
        raise SystemExit(f"the topology catalogue {path} must be a JSON object")
    nested = data.get("topologies")
    if isinstance(nested, Mapping):
        return dict(nested)
    return dict(data)


def resolve_topology(topology_id: str, catalogue: Mapping[str, Any], base: Path,
                     catalogue_path: Path):
    """Load a catalogue topology, exactly as the experiment runner does.

    The two catalogue shapes also differ in what their relative paths are
    relative to: the frozen-test catalogue names files from the repository root,
    the generated ones from their own directory. Trying the catalogue's own
    directory first and the given base second reads either without the caller
    having to know which it has.
    """
    entry = catalogue.get(topology_id)
    if not isinstance(entry, Mapping) or "path" not in entry:
        raise DomainError(f"topology {topology_id!r} is not in the catalogue",
                          code="UNKNOWN_TOPOLOGY")
    raw = Path(entry["path"])
    if raw.is_absolute():
        candidates = [raw]
    else:
        candidates = [catalogue_path.parent / raw, base / raw]
    for candidate in candidates:
        if candidate.exists():
            return load_json_topology(str(candidate))
    tried = ", ".join(str(c) for c in candidates)
    raise DomainError(f"topology file for {topology_id!r} not found (tried {tried})",
                      code="MISSING_TOPOLOGY_FILE")


#: A token shaped like a catalogue identifier. Stage 3 binds only on an exact
#: whole-token match, so `topo50_seed10` binds nothing at all --- correct, and
#: indistinguishable from naming no topology unless we say which token missed.
TOPOLOGY_TOKEN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_seed\d+\b")


def unlisted_topologies(text: str, catalogue) -> list[tuple[str, str | None]]:
    """Identifier-shaped tokens that name nothing, each with its nearest match."""
    found = []
    for token in TOPOLOGY_TOKEN.findall(text):
        if token in catalogue:
            continue
        close = difflib.get_close_matches(token, sorted(catalogue), n=1, cutoff=0.6)
        found.append((token, close[0] if close else None))
    return found


#: Slots per line before the timeline wraps. A 300-node schedule can run to
#: hundreds of slots, and a line that wraps in the terminal instead of here
#: loses the column alignment that makes the grid readable.
TIMELINE_WIDTH = 60


def render_timeline(schedule: Sequence[Any]) -> list[str]:
    """A slot-by-channel grid of the schedule, for a terminal.

    One row per channel, one column per slot, each cell the number of
    transmissions that channel carries in that slot. Collision-freedom is the
    property the validator certifies, and it is what the grid shows: on one
    channel and one slot the senders must not interfere, so a busy column is
    the scheduler packing a slot, not a conflict.
    """
    if not schedule:
        return []
    span = max(entry.timeslot for entry in schedule) + 1
    channels = sorted({entry.channel for entry in schedule})
    counts: dict[tuple[int, int], int] = {}
    for entry in schedule:
        key = (entry.channel, entry.timeslot)
        counts[key] = counts.get(key, 0) + 1

    label_width = max(len(f"ch {channel}") for channel in channels) + 2
    lines = []
    for start in range(0, span, TIMELINE_WIDTH):
        stop = min(start + TIMELINE_WIDTH, span)
        if span > TIMELINE_WIDTH:
            lines.append(" " * (label_width + 2) + f"slots {start}-{stop - 1}")
        # a ruler every ten slots, so a column can be counted back to a number
        tens = "".join("|" if slot % 10 == 0 else " " for slot in range(start, stop))
        ruler = "".join(str((slot // 10) % 10) if slot % 10 == 0 else " "
                        for slot in range(start, stop))
        lines.append(" " * (label_width + 2) + ruler)
        lines.append(" " * (label_width + 2) + tens)
        for channel in channels:
            cells = []
            for slot in range(start, stop):
                count = counts.get((channel, slot), 0)
                cells.append("." if count == 0 else
                             str(count) if count < 10 else "+")
            lines.append(f"{f'ch {channel}':>{label_width}}  " + "".join(cells))
    return lines


def open_in_browser(path: Path) -> str:
    """Open a file with whatever this machine uses, WSL included.

    Under WSL the browser lives on the Windows side. `xdg-open` is present but
    usually resolves to nothing without a desktop session, so it reports success
    while opening no window; `explorer.exe` is the bridge that works, and it
    needs a Windows path, which `wslpath -w` produces.
    """
    import shutil
    import subprocess
    import webbrowser

    def launch(argv: list[str]) -> bool:
        try:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False

    under_wsl = "microsoft" in Path("/proc/version").read_text().lower() \
        if Path("/proc/version").exists() else False

    if under_wsl and shutil.which("explorer.exe"):
        try:
            windows_path = subprocess.run(
                ["wslpath", "-w", str(path)], capture_output=True, text=True,
                check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            windows_path = None
        if windows_path and launch(["explorer.exe", windows_path]):
            return "explorer.exe"

    for launcher in ("wslview", "xdg-open", "open"):
        if shutil.which(launcher) and launch([launcher, str(path)]):
            return launcher
    return "webbrowser" if webbrowser.open(path.as_uri()) else "nothing"


def describe_gate(report) -> list[str]:
    """What the scope policy saw, whether or not it was allowed to act on it.

    Printed in every mode: under `off` and `advisory` the detector still runs,
    and seeing it match while the request proceeds is the ablation's whole
    point.
    """
    policy = report.scope_policy
    if policy is None:
        return []
    violations = getattr(policy, "violations", ()) or ()
    if not violations:
        return ["  scope gate  : matched nothing"]
    lines = []
    for violation in violations:
        if isinstance(violation, Mapping):
            category = violation.get("category", "?")
            witness = violation.get("witness", "")
        else:
            category = getattr(violation, "category", "?")
            witness = getattr(violation, "witness", "")
        detail = f" on {witness!r}" if witness else ""
        lines.append(f"  scope gate  : matched {category}{detail}")
    return lines


def print_report(report, topology_id: str | None, elapsed_ms: float,
                 mode: str, catalogue=None) -> None:
    status = report.status
    print(f"\n  action      : {status}")
    print(f"  decided by  : {deciding_stage(report, mode)}")
    for line in describe_gate(report):
        print(line)
    if topology_id:
        print(f"  topology    : {topology_id}")
    if report.decision_summary:
        print(f"  summary     : {report.decision_summary}")

    if status == "CLARIFY" and report.clarification_questions:
        for question in report.clarification_questions:
            text = getattr(question, "question", None) or getattr(question, "field", "")
            print(f"  asks        : {text}")
        if catalogue is not None:
            names = sorted(catalogue)
            shown = ", ".join(names[:8])
            more = f" ... and {len(names) - 8} more (:topologies)" if len(names) > 8 else ""
            print(f"  catalogue   : {shown}{more}")
    if report.error:
        code = report.error.get("code") if isinstance(report.error, Mapping) else None
        if code:
            print(f"  error code  : {code}")

    if status == "EXECUTE" and report.request is not None:
        fields = report.request.to_dict()
        shown = {k: v for k, v in fields.items() if k != "network" and v is not None}
        print(f"  parsed      : {json.dumps(shown, sort_keys=True)}")

    if report.result is not None:
        metrics = report.metrics
        print(f"  schedule    : {len(report.result.schedule)} transmissions, "
              f"{report.result.latency_slots} slots"
              + (f", {len(metrics.used_channels)} channel(s)" if metrics else ""))
        valid = report.final_validation.valid if report.final_validation else None
        certified = "accepted" if valid else "REJECTED"
        print(f"  validator   : independent validator {certified}")
        if report.target_satisfied is not None:
            print(f"  latency tgt : {'met' if report.target_satisfied else 'not met'}")
        print()
        print("  timeline    : columns are slots, rows are channels, "
              "digits are transmissions")
        for line in render_timeline(report.result.schedule):
            print(f"    {line}")
        print()

    calls = len(report.llm_logs)
    print(f"  cost        : {calls} model call(s), {report.retry_count} retry(ies), "
          f"{elapsed_ms:.0f} ms")


def build_client(args: argparse.Namespace):
    # ProviderConfig validates each field it is given, so an unset option has to
    # be absent rather than None.
    values = {"provider": args.provider, "max_retries": args.max_retries,
              "seed": args.seed}
    for key, value in (("model", args.model), ("temperature", args.temperature),
                       ("base_url", args.base_url), ("api_key_env", args.api_key_env),
                       ("timeout_seconds", args.timeout_seconds)):
        if value is not None:
            values[key] = value
    if args.provider == "mock" and not args.model:
        values["model"] = "deterministic-mock"
    if args.provider != "mock" and not args.model:
        raise SystemExit("--model is required for every provider except mock")
    return create_llm_client(ProviderConfig.from_dict(values))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", default="mock",
                        choices=("mock", "ollama", "openai_compatible", "openai"))
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--api-key-env")
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=180.0,
                        help="per model call; the default is generous because a "
                             "local model's first call includes loading it")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--scope-mode", default="enforcing",
                        choices=("enforcing", "advisory", "off"),
                        help="the gate's authority; the ablation of Sections 5.2 and 5.3")
    parser.add_argument("--catalogue", default=str(DEFAULT_CATALOGUE))
    parser.add_argument("--catalogue-dir", default=str(ROOT),
                        help="base directory for relative catalogue paths")
    parser.add_argument("--visualize", metavar="DIR",
                        help="write an interactive HTML schedule per EXECUTE into DIR")
    parser.add_argument("--open", action="store_true",
                        help="open each HTML schedule as it is written; implies "
                             "--visualize into a temporary directory when that is unset")
    parser.add_argument("--request", action="append", default=[],
                        help="run this request and exit (repeatable); skips the prompt")
    return parser


def run_once(text: str, *, client, args, catalogue, base, catalogue_path: Path,
             mode: str, counter: list[int]) -> Any:
    named = bind_topologies(text, catalogue)
    topology = None
    topology_id = None
    if len(named) == 1:
        topology_id = named[0]
        try:
            topology = resolve_topology(topology_id, catalogue, base,
                                        catalogue_path)
        except (DomainError, SchemaError) as exc:
            print(f"  could not load topology {topology_id}: {exc}")
            return None
    elif len(named) > 1:
        # The binding rule: naming two catalogue topologies selects neither.
        print(f"  note        : {len(named)} topologies named ({', '.join(named)}), "
              "so none is bound")

    if not named:
        # Stage 3 will ask for a topology. Without this the question is the same
        # whether the request named nothing or named something one character off,
        # and the reader cannot tell which.
        for token, suggestion in unlisted_topologies(text, catalogue):
            hint = f"; did you mean {suggestion}?" if suggestion else ""
            print(f"  note        : {token} is not in the catalogue{hint}")

    started = time.monotonic()
    report = Orchestrator(
        RequirementAgent(client, max_retries=args.max_retries), scope_mode=mode,
    ).run(text, topology)
    elapsed_ms = (time.monotonic() - started) * 1000
    print_report(report, topology_id, elapsed_ms, mode, catalogue)

    if (args.visualize or args.open) and report.status == "EXECUTE" \
            and report.result is not None and report.final_validation is not None \
            and report.final_validation.valid:
        directory = Path(args.visualize) if args.visualize else Path(tempfile.gettempdir()) / "anex_demo"
        directory.mkdir(parents=True, exist_ok=True)
        counter[0] += 1
        destination = directory / f"schedule_{counter[0]:02d}.html"
        artifact = render_interactive_schedule(
            topology, report.result.schedule, validation=report.final_validation)
        save_visualization(artifact, destination, overwrite=True)
        note = f"  visual      : {destination}"
        if args.open:
            note += f" (opened with {open_in_browser(destination)})"
        print(note)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    catalogue_path = Path(args.catalogue)
    catalogue = load_catalogue(catalogue_path)
    base = Path(args.catalogue_dir)
    client = build_client(args)
    if isinstance(client, MockLLMClient):
        print("note: the mock provider answers from a fixed script, so only the "
              "deterministic stages are meaningful here.\n")
    elif args.provider == "ollama":
        print(f"note: the first request that reaches {args.model} also loads it, "
              f"which can take minutes. Timeout is {args.timeout_seconds:.0f}s per "
              "call; raise it with --timeout-seconds.\n")

    mode = args.scope_mode
    counter = [0]
    last = None

    for text in args.request:
        print(f"> {text}")
        last = run_once(text, client=client, args=args, catalogue=catalogue,
                        base=base, catalogue_path=catalogue_path,
                        mode=mode, counter=counter)
        print()
    if args.request:
        return 0

    print(BANNER)
    print(f"provider {args.provider}"
          + (f" / {args.model}" if args.model else "")
          + f", gate {mode}")
    names = sorted(catalogue)
    if len(names) <= 12:
        print(f"topologies: {', '.join(names)}")
    else:
        print(f"topologies: {len(names)}, e.g. {', '.join(names[:4])} ... "
              f"(:topologies for all)")
    print("a request binds one only by naming it exactly, as a whole word.\n")

    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue

        if text.startswith(":"):
            command, _, rest = text[1:].partition(" ")
            command, rest = command.lower(), rest.strip()
            if command in ("q", "quit", "exit"):
                return 0
            if command in ("h", "help", "?"):
                print(BANNER)
            elif command in ("t", "topologies"):
                for name in sorted(catalogue):
                    print(f"  {name}")
            elif command == "examples":
                for index, (label, sample) in enumerate(EXAMPLES, start=1):
                    print(f"  {index}. [{label}]\n     {sample}")
            elif command == "e":
                try:
                    _, sample = EXAMPLES[int(rest) - 1]
                except (ValueError, IndexError):
                    print(f"  no example {rest!r}; try :examples")
                    continue
                print(f"> {sample}")
                last = run_once(sample, client=client, args=args, catalogue=catalogue,
                                base=base, catalogue_path=catalogue_path,
                                mode=mode, counter=counter)
                print()
            elif command == "mode":
                if rest in ("enforcing", "advisory", "off"):
                    mode = rest
                    print(f"  gate authority is now {mode}")
                else:
                    print("  :mode enforcing | advisory | off")
            elif command == "last":
                print(json.dumps(last.to_dict(), indent=2, sort_keys=True)
                      if last is not None else "  nothing run yet")
            else:
                print(f"  unknown command {command!r}; :help")
            continue

        try:
            last = run_once(text, client=client, args=args, catalogue=catalogue,
                            base=base, catalogue_path=catalogue_path,
                            mode=mode, counter=counter)
        except (DomainError, SchemaError) as exc:
            print(f"  the pipeline refused the request: {exc}")
        except Exception as exc:  # noqa: BLE001 - a demo should not die on one bad call
            print(f"  the provider call failed: {type(exc).__name__}: {exc}")
        print()


if __name__ == "__main__":
    raise SystemExit(main())

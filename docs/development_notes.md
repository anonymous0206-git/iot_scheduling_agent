# Agentic ANEX - implementation baseline

This project wraps the published ANEX implementation without changing its
scheduling logic. The first milestone provides:

- deterministic topology generation;
- typed run configuration and result objects;
- a stable `run_anex` API;
- an independent schedule validator;
- explicit legacy and elapsed-slot latency metrics;
- regression tests for valid and deliberately corrupted schedules.

The extracted original files remain under `source/` for provenance. The LLM
agent layer will be added only after this deterministic foundation is frozen.

## Run the baseline

```bash
uv run python -m agentic_anex.cli --nodes 30 --seed 7
```

## Run tests

```bash
uv run python -m unittest discover -s tests -v
```

## Frozen Test v2 reconciliation and sealing

The `frozen_test_v2` package joins the two generated benchmark batches with
their blind cross-reviews, classifies every semantic group, exports a
human-adjudication worksheet, applies recorded human decisions, and seals the
target-facing requests, the gold labels, and a lock manifest. It never imports
`agentic_anex` and never calls Phi4, ANEX, scope policy v2, or the schedule
validator.

```bash
uv run python -m frozen_test_v2 reconcile --batch-a benchmark_model_A.json \
  --review-of-a "Model-B blind review of Batch A.json" \
  --batch-b benchmark_model_B.json \
  --review-of-b "Model-A blind review of Batch B.json" \
  --tolerate-leading-prose --out benchmarks/frozen_test_v2/reconciliation
```

See [the pipeline guide](docs/frozen_test_v2_pipeline.md) for the
classification rules, the decisions file format, sealing, and verification.
The configuration contract is versioned: the default profile
`frozen-test-v3` fixes `interference_ratio` at 1.0 (interference range
equals communication range); pass `--contract frozen-test-v2` to reproduce
the rules the sealed Frozen Test v2 was adjudicated under. See
[docs/frozen_test_v3_contract.md](docs/frozen_test_v3_contract.md).

## Interactive schedule replay

Create a self-contained HTML player from a network, schedule, and optional
validation certificate:

```bash
uv run python -m agentic_anex.visualization animate \
  --network network_30_seed7.json \
  --schedule schedule_30_seed7.json \
  --validation validation_30_seed7.json \
  --slot-duration-ms 1000 \
  --output schedule_replay.html
```

The resulting file contains the topology, schedule frames, validation
evidence, CSS, and JavaScript. It has no external web dependencies and opens
directly from the local filesystem. Playback is a deterministic replay of the
computed schedule: it is not a network emulator, real-time execution
environment, simulator, or Digital Twin. Controls support play/pause,
timeslot navigation, speed, looping, and optional communication-link and
active-slot overlays.

## Multi-provider LLM runtime

Provider selection is explicit; Agentic ANEX never falls back from a local
runtime to a cloud API or silently changes models. There is no implicit
provider: select `--provider`, supply `provider` in `--config`, or select
`--rule-based`. The `mock` provider is available only when explicitly named.

Rule-based execution without an LLM:

```bash
uv run python -m agentic_anex.agent_cli \
  --rule-based \
  --network network.json \
  --request "Schedule one-shot aggregation with minimum latency"
```

Ollama example:

```bash
ollama serve
ollama pull MODEL_NAME
uv run python -m agentic_anex.agent_cli \
  --provider ollama --model MODEL_NAME \
  --network network.json \
  --request "Schedule one-shot aggregation with minimum latency" \
  --output orchestration_report.json \
  --visualization-output interactive_schedule.html
```

An OpenAI-compatible llama.cpp or vLLM server can be selected with
`--provider openai_compatible --base-url http://localhost:8000/v1`. For the
OpenAI cloud provider, export the credential instead of placing it in a file:

```bash
export OPENAI_API_KEY="..."
uv run python -m agentic_anex.agent_cli \
  --provider openai --model MODEL_NAME \
  --network network.json \
  --request "Schedule one-shot aggregation with minimum latency"
```

Configuration precedence is CLI arguments, then `--config` JSON, then
documented defaults. See [the operator guide](docs/operator_guide.md) for
configuration, privacy, cost, and troubleshooting details.

Before any scientific tool runs, a deterministic consistency boundary checks
every `SchedulingRequest` field against explicit controlled phrases,
documented defaults, and the validated topology. A conflicting LLM value is
rejected or retried with typed field-level evidence; it is never silently
substituted. This checker is conservative and is not a general natural-language
parser.

An earlier independent boundary, `paper1-scope-policy.v2`, reads the raw user
request against a closed Paper 1 capability taxonomy. Unsupported energy,
battery evolution, Digital Twin/emulation, dynamic synchronization, periodic
aggregation, topology adaptation, and non-latency objectives cannot reach the
LLM or ANEX. A valid schedule never overrides this semantic decision.

Topology availability is owned by the deterministic orchestrator. A missing
network returns `CLARIFY` without an LLM call; a validated supplied network is
bound before interpretation and cannot be questioned or replaced by the LLM.

PowerShell uses the same CLI. Set the cloud credential and run with:

```powershell
$env:OPENAI_API_KEY = "..."
uv run python -m agentic_anex.agent_cli `
  --provider openai `
  --model MODEL_NAME `
  --network network.json `
  --request "Schedule one-shot aggregation with minimum latency"
```

## Scope lock for Paper 1

Paper 1 uses one-shot aggregation, a latency-only objective, static network
state, ANEX as the sole scheduling solver, and deterministic validation. It
does not optimize residual energy, maintain dynamic virtual state, adapt a
topology, schedule periodic workloads, emulate a network, or claim a Digital
Twin.

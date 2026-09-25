# Agentic ANEX operator guide

## Runtime choices

All LLM providers implement the same structured-output protocol and use the
same bounded `RequirementAgent`, `Orchestrator`, deterministic ANEX tools, and
independent validator. Provider selection is explicit. A failed local request
never initiates a cloud request, and no provider or model fallback is used.

There is no implicit `mock` default. Operators must provide `--provider`, put
`provider` in the JSON config, or explicitly select `--rule-based`. The `mock`
provider is an offline test runtime and is used only when explicitly named; it
is not a production language parser.

For a completely deterministic baseline without an LLM:

```bash
uv run python -m agentic_anex.agent_cli \
  --rule-based \
  --network network.json \
  --request "Schedule one-shot aggregation with minimum latency" \
  --output rule_report.json
```

The rule-based CLI extracts only explicitly stated critical intent. If
`one-shot` or latency minimization is absent, it returns structured
clarification instead of inventing those values.

## Ollama

Install Ollama using its platform instructions, then start the service and
download the model selected for the experiment:

```bash
ollama serve
ollama pull MODEL_NAME
uv run python -m agentic_anex.agent_cli \
  --provider ollama --model MODEL_NAME \
  --network network.json \
  --request "Schedule one-shot aggregation with minimum latency" \
  --output report.json
```

The default endpoint is `http://localhost:11434`. Override it using
`--base-url`. Local LLM inference is not a Digital Twin, simulator, emulator,
or real-time network execution environment.

## OpenAI-compatible local servers

Start llama.cpp, vLLM, or another compatible server separately, then provide
its `/v1` base URL:

```bash
uv run python -m agentic_anex.agent_cli \
  --provider openai_compatible \
  --base-url http://localhost:8000/v1 \
  --model MODEL_NAME \
  --network network.json \
  --request "Schedule one-shot aggregation with minimum latency"
```

The client first requests native JSON Schema output. If the server explicitly
rejects that feature, it requests JSON-only output and the existing typed
schema boundary validates the result. This is not a provider fallback.

## OpenAI cloud

Keep credentials in the environment. The default variable is
`OPENAI_API_KEY`; `--api-key-env` selects another variable name.

```bash
export OPENAI_API_KEY="..."
uv run python -m agentic_anex.agent_cli \
  --provider openai --model MODEL_NAME \
  --network network.json \
  --request "Schedule one-shot aggregation with minimum latency" \
  --output report.json
```

Credential values are not placed in prompts, logs, reports, visualizations,
or experiment records. Error messages do not include response bodies or
authorization headers.

### PowerShell

Use PowerShell's environment-variable syntax and backtick continuation:

```powershell
$env:OPENAI_API_KEY = "..."
uv run python -m agentic_anex.agent_cli `
  --provider openai `
  --model MODEL_NAME `
  --network network.json `
  --request "Schedule one-shot aggregation with minimum latency" `
  --output report.json
```

Ollama and OpenAI-compatible commands follow the same pattern:

```powershell
ollama serve
uv run python -m agentic_anex.agent_cli `
  --provider ollama `
  --model MODEL_NAME `
  --network network.json `
  --request "Schedule one-shot aggregation with minimum latency"

uv run python -m agentic_anex.agent_cli `
  --provider openai_compatible `
  --base-url http://localhost:8000/v1 `
  --model MODEL_NAME `
  --network network.json `
  --request "Schedule one-shot aggregation with minimum latency"

uv run python -m agentic_anex.agent_cli `
  --rule-based `
  --network network.json `
  --request "Schedule one-shot aggregation with minimum latency"
```

## JSON configuration and precedence

Example `provider_config.json`:

```json
{
  "provider": "ollama",
  "model": "MODEL_NAME",
  "base_url": "http://localhost:11434",
  "temperature": 0,
  "timeout_seconds": 60,
  "max_retries": 2,
  "seed": 7
}
```

Use `--config provider_config.json`. Explicit CLI values override the file;
the file overrides documented defaults. Temperature defaults to zero, timeout
to 60 seconds, maximum retries to two, and the API-key variable name to
`OPENAI_API_KEY`. Provider selection has no default. Real providers require an
explicit model name; explicitly selected `mock` uses `deterministic-mock` when
its model is omitted.

## Privacy and cost

- Ollama and loopback-compatible servers keep inference requests local, but
  operators remain responsible for the selected model and runtime logs.
- Remote compatible services and OpenAI receive the request prompt and the
  serialized topology. Review provider retention policy before use.
- Cloud calls may incur token charges. The report records available token and
  model-call metadata but never credentials.
- The LLM only interprets requirements and approves tools. It cannot construct
  or edit schedules, change topology, bypass validation, or report scientific
  success without a passing certificate.

## Troubleshooting

- `PROVIDER_UNAVAILABLE`: verify the process is running and `base_url` is
  reachable. No alternate provider will be tried.
- `PROVIDER_TIMEOUT`: increase `timeout_seconds` or select a smaller local
  model explicitly.
- `MODEL_UNAVAILABLE`: download the exact model or correct `model`; no model is
  substituted automatically.
- `MISSING_API_KEY`: export the environment variable named by `api_key_env`.
- `MALFORMED_STRUCTURED_OUTPUT`: the bounded agent retries at most the configured
  count, then rejects without running ANEX.

## Reproducible LLM benchmark runs

`paper1-scope-policy.v2` runs before the provider and evaluates the raw request,
not the model's structured interpretation. It returns a machine-readable
taxonomy report with matched pattern IDs and text witnesses. Once this gate
finds an unsupported capability, neither an LLM response nor a passing schedule
certificate can change the final action to `EXECUTE`.

The provider output passes through `paper1-request-consistency.v1` before ANEX.
It checks workload, objective, channels, interference ratio/alpha, collision
model, seed, latency target, working period, and communication range. Explicit
user values have priority; omitted LLM-controlled fields must equal documented
defaults; topology-owned fields must equal the validated `NetworkInstance`.
Mismatches use `REQUEST_FIELD_MISMATCH` and include `expected`, `actual`,
`source`, and `status` for each field in the LLM interaction log. Use a nonzero
`--max-retries` when evaluating whether a provider can correct such mismatches.
Topology presence is checked before the provider is called. Missing topology
returns a deterministic `CLARIFY`; supplied topology is validated and bound,
and a provider response that asks for it again is rejected without retry.
Explicit energy/lifetime optimization and Digital Twin/virtual-replica intents
are also classified deterministically as `UNSUPPORTED`, so provider wording
cannot turn an out-of-scope request into `REJECT` or `EXECUTE`.

After validating one request with the selected local model, run the development
split into a model-specific append-only ledger:

```bash
uv run python scripts/run_experiments.py \
  --benchmark benchmarks/requests_dev.jsonl \
  --raw-output results/phi4_dev.jsonl \
  --systems llm_agent \
  --provider ollama \
  --model phi4:14b \
  --timeout-seconds 600 \
  --max-retries 0 \
  --seeds 0
```

Replace the model and raw-output name for another arm. The runner constructs an
explicit client for each experiment seed, safely resumes completed keys, and
never overwrites raw records. A provider failure is recorded as a completed
failure, so confirm the local endpoint and model before starting a long run.
Do not tune prompts on `requests_test.jsonl`; run that frozen split only after
the prompt and provider configuration are locked.

The Paper 1 evaluation configuration is recorded in
`benchmarks/evaluation_lock_v1.json`. Verify it before and after a frozen test
campaign with:

```bash
uv run python scripts/verify_evaluation_lock.py
```

Any hash mismatch invalidates comparability with the locked campaign. Test
results may be analyzed and reported, but must not be used to modify the locked
prompt, scope policy, consistency checker, or frozen requests.

After Frozen Test v1 was opened, its reasoning-model false acceptance was
locked as exploratory evidence and motivated policy v2. The original v1 source
archive and hashes remain immutable. The current policy-v2 working tree will
therefore intentionally differ from `evaluation_lock_v1.json`; it must not be
used to replace or relabel the v1 results. See
`docs/phi4_reasoning_failure_case.md` and
`docs/frozen_test_v2_protocol.md`.

## Retrospective policy replay

Locked outputs can be replayed through scope policies without calling an LLM,
ANEX, or the validator again:

```bash
uv run python scripts/replay_locked_policy.py \
  --benchmark benchmarks/requests_test.jsonl \
  --raw results/phi4_reasoning_test_locked_v1_wsl.jsonl \
  --output results/retrospective_policy_ablation_v1.json
```

The replay joins by `request_id`, verifies and records source hashes, reproduces
the exact v1 flat phrase gate, and evaluates v2 over the same raw requests. Its
output is explicitly labelled retrospective/regression and must not be reported
as new Frozen Test v1 generalization performance. The output path is
write-once by default.

## Scope-gate modes

The scope gate is one detector whose authority is a parameter. `Orchestrator`
takes `scope_mode`, and every mode runs the same pipeline otherwise:

| mode | what stage 1 does | arm name in the ledger |
|---|---|---|
| `enforcing` | a match short-circuits the run to `UNSUPPORTED` before the model is called | `llm_agent` |
| `advisory` | the same match is passed to the model as a non-binding notice; the model decides | `llm_agent_advisory_scope_gate` |
| `off` | the gate is not consulted | `llm_agent_no_scope_gate` |

`enforcing` is the production configuration and the only one
`scripts/run_frozen_test_v3_experiments.py` will run. The other two come from
`scripts/run_scope_gate_ablation.py`, which requires `--confirm-ablation` and
a fresh ledger path, and refuses to produce the primary arm at all:

```bash
uv run python scripts/run_scope_gate_ablation.py \
  --benchmark benchmarks/frozen_test_v3/harness/frozen_test_v3_harness.jsonl \
  --topology-catalogue benchmarks/topologies/frozen_test_v3_llm_catalogue.json \
  --catalogue-dir . --raw-output results/frozen_test_v3/phi4_advisory.jsonl \
  --provider ollama --model phi4:14b --temperature 0 --seeds 1 \
  --scope-mode advisory --confirm-ablation
```

What differs between the arms, and nothing else does. In `off` every record
carries `policy_version` = `paper1-scope-policy.v2-ABLATED`. In `advisory` the
gate runs and records what it matched, and on the requests it matched --- and
only those --- the prompt carries an extra `ADVISORY SCOPE NOTICE` block and
is versioned `paper1-requirements-v4-advisory`. On every other request all
three modes send a byte-identical prompt, which is what makes a difference
between arms attributable to the gate. `tests/test_scope_modes.py` pins both
properties.

Neither non-primary arm may be reported as the production system.

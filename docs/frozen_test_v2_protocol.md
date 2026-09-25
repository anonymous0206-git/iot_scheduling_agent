# Frozen Test v2 Authoring and Evaluation Protocol

Frozen Test v2 is required for unbiased evaluation of scope-policy v2. It must
not reuse or lightly edit any user text from Frozen Test v1. The policy author
must not inspect its final natural-language requests before the policy-v2 code,
taxonomy, models, seeds, retry limit, and ablations are locked.

## Target design

The target size is 72 semantic requests, each with at least two independently
authored paraphrases, for 144 or more items. If inference cost requires a
smaller release, the minimum is 60 total items with the same stratification.
Request IDs, topology IDs, semantic gold objects, and category quotas are fixed
before paraphrase authoring.

The semantic-request allocation is:

| Category | Semantic requests |
|---|---:|
| Supported default one-shot latency | 8 |
| Supported configured channels/range/alpha | 8 |
| Supported latency targets | 6 |
| Missing critical information | 6 |
| Malformed or invalid parameters | 8 |
| Energy and battery objectives | 8 |
| Digital Twin, emulation, and state synchronization | 8 |
| Periodic or continuous aggregation | 6 |
| Topology or routing adaptation | 6 |
| Other unsupported objectives | 8 |

At least one third of unsupported items must express capabilities
compositionally without using their canonical category name. Negated requests
and mixed supported/unsupported requests must be represented and manually
adjudicated. No phrase may be copied from `requests_test.jsonl`.

## Separation of roles

An independent author or held-out generation process receives only the closed
taxonomy and benchmark schema, not the v1 requests or policy regexes. A second
reviewer assigns gold actions and structured requests. Disagreements are
resolved before freezing. The development team receives only the final file
hash after policy v2 is locked.

## Freeze procedure

1. Validate every JSONL item against `benchmarks/schema.json`.
2. Verify unique request IDs and consistent gold semantics within paraphrase
   groups.
3. Record category counts and a SHA-256 hash in a new evaluation-lock manifest.
4. Lock Phi4 as the primary local model, seed 0, temperature 0, and at most two
   retries. Record the exact Ollama model digest.
5. Do not alter the request file, prompt, policy, or consistency checker after
   opening model outputs.

## Systems and ablations

Run identical request/topology/seed tuples for:

- deterministic rule-based baseline;
- Phi4 with policy v2 (primary system);
- Phi4 without the independent scope gate, as a safety ablation;
- optionally Qwen2.5 as the already-declared comparison model.

The no-scope-gate ablation must be isolated as an experiment configuration and
must never become the production default. All schedules still pass through the
independent validator.

Report action accuracy, field exact match, task completion, produced-schedule
validity, false acceptance, paraphrase consistency, retries, model calls,
tokens, and paired bootstrap confidence intervals. Separate semantic failures,
schedule failures, and provider/infrastructure failures.

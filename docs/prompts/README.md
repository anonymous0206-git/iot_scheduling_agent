# Frozen Test v2 prompts

These files are hashed into the Frozen Test v2 lock manifest by
`python -m frozen_test_v2 seal --prompt NAME=PATH`. They are stored as the
plain prompt text so that the recorded hash is the hash of what the model
actually received.

| File | Provenance |
|---|---|
| `frozen_test_v2_generator_prompt.txt` | Generation prompt exactly as delivered to Model B (Claude Fable 5.1) on 2026-09-08. It names the role "Frontier Benchmark Generator B"; Model A received the corresponding Generator A variant. |
| `frozen_test_v2_reviewer_prompt.txt` | Blind-adjudication prompt exactly as delivered to Model B on 2026-09-08, with `batch_a_blind.json` attached separately. Model A received the corresponding variant for blind Batch B. |
| `frozen_test_v3_generator_prompt.txt` | Template for the Frozen Test v3 generation prompt: contract `frozen-test-v3` (interference_ratio fixed at 1.0), the seven-topology catalogue of `benchmarks/topologies/frozen_test_v3_llm_catalogue.json`, protocol-table stratification with a closed `protocol_category`, and construction rules from the v2 adjudication. Placeholders `{ROLE}` / `{ROLE_LOWER}` (A/a or B/b); save and hash each delivered copy, not this template. |
| `frozen_test_v3_reviewer_prompt.txt` | Template for the v3 blind-adjudication prompt with `{BATCH}` / `{BATCH_LOWER}` placeholders. The reviewer receives it together with sections 1 to 4 of the generator prompt and the blind batch produced by `python -m frozen_test_v2 blind`. |

If the text delivered to Model A differs from these files, save that text
too and pass it as an additional `--prompt` argument so both variants are
hashed.

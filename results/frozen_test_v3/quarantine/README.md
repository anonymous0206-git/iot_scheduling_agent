# Rate-limited runs — NOT results

Six ledgers from the frontier campaign of 2026-09-21 (seeds 12 and 13 of
`gpt55_policy_v2`, `gpt55_no_scope_gate`, `gpt55_advisory_scope_gate`). The
provider returned HTTP 429 on every model call after the seed-11 runs
exhausted a rate limit, so each ledger records 113 items whose only content is
a provider error.

They are kept because they are evidence of the failure, not because they
measure anything. Nothing in `results/` outside this directory reads them, and
no analysis should.

How to tell them apart from a real run, in case they are ever mixed back in:

    error_code == "HTTP_PROVIDER_ERROR"   on 113 of 144 items
    model_calls                            339, against 126 for a healthy run
    wall clock                             ~2 min, against ~10 min

Seed 11 of all three arms is unaffected and ran before the limit was hit.

## Second batch, 2026-09-22

`gpt55_no_scope_gate_seed13.jsonl` — 28 of 144 items are provider errors
(19.4%), which tripped the campaign's new abort threshold. The campaign
stopped there and reported `partial` rather than `completed`.

`gpt55_advisory_scope_gate_seed11.jsonl` — only 3 provider errors (2.1%), on
the last three items, so it slipped under the abort threshold. It is
quarantined anyway: those three items are not agent decisions, and leaving
them in understated the arm by three and made an advisory-versus-ungated
comparison look like a five-item gap when the honest figure on the clean items
was two.

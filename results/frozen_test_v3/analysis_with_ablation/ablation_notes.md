# Scope-gate ablation: item-level account

Arms compared, both Phi4 `phi4:14b`, temperature 0, seed 0, identical harness:

* `llm_agent` — the sealed pipeline, `paper1-scope-policy.v2` active
  (`results/frozen_test_v3/phi4_policy_v2.jsonl`)
* `llm_agent_no_scope_gate` — the same pipeline with the scope gate replaced by a
  stub that reports every request as supported, recorded under
  `paper1-scope-policy.v2-ABLATED`
  (`results/frozen_test_v3/phi4_no_scope_gate.jsonl`)

Everything else — the consistency checker, the topology gate, ANEX, and the
independent schedule validator — ran unchanged in both arms.

## What the gate actually did

The gate short-circuited 18 of 144 items. It refused all 18 before the model was
called, so those 18 items are exactly where the two arms can differ by design.

| Gold action of the blocked item | Count | Gate verdict |
|---|---:|---|
| UNSUPPORTED | 11 | correct refusal |
| EXECUTE | 7 | over-block (a supported request refused) |

Removing the gate:

* **fixes 7 items**, all gold EXECUTE — `ft3-r0017, r0032, r0040, r0060, r0083,
  r0105, r0118`. Every one of them is a hard negative that mentions an
  out-of-scope word while asking for something the system genuinely supports;
  the model answers EXECUTE correctly once it is allowed to see the request.
* **breaks 6 items**, all gold UNSUPPORTED — 4 of them were blocked items the
  model then mishandled (`r0008 → EXECUTE`, `r0049 → REJECT`, `r0122 → EXECUTE`,
  `r0124 → EXECUTE`), and 2 are run-to-run flips on items the gate never touched
  (`r0036`, `r0127`, both UNSUPPORTED → REJECT).
* leaves 7 of the 11 correct refusals intact: the model reaches UNSUPPORTED on
  `r0002, r0064, r0080, r0091, r0093, r0095, r0100` without any help from the gate.

Net: **+1 item**, action accuracy 64/144 → 65/144. The paired bootstrap difference
is `+0.0069, 95% CI [-0.0417, +0.0556]` — indistinguishable from zero.

So on this benchmark the gate is close to a wash: it buys 4 refusals the model
would have got wrong, and pays for them with 7 supported requests it refuses.
Its measurable benefit is not in action accuracy but in **false acceptance**,
which rises 30 → 33 (0.208 → 0.229) without it, and it costs **field exact match
on EXECUTE**, which rises 0.549 → 0.685 without it, because the 7 recovered
EXECUTE items are well-specified requests the model fills in correctly.

## Free variance estimate

The two runs share an identical prompt for the 126 unblocked items
(temperature 0, seed 0, same model digest). They still disagree on 2 of them:

    agreement on the 126 unblocked items: 124/126 = 0.984

That is a lower bound on provider nondeterminism: roughly ±1.6 percentage points
of action accuracy is run-to-run noise, not signal. Any claimed difference
smaller than that is not interpretable from a single run per arm.

## Bearing on the paper

The ablation answers the question "does the independent scope gate earn its
place?" with a measured *no, not as an accuracy device* on this benchmark, and
with a *yes, as a false-acceptance device* — a smaller and more honest claim
than "the gate improves the agent". Combined with the canonical-vs-compositional
split (10/10 UNSUPPORTED caught on canonical wording, 14/62 on compositional),
the picture is consistent: `paper1-scope-policy.v2` is a phrase matcher whose
recall is a property of the phrasing, not of the request's semantics.

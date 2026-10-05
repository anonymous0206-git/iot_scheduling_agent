#!/usr/bin/env python3
"""Render a revision request for the groups a blind adjudication flagged.

When an adjudicator flags a group for paraphrase inequivalence and not for its
label, the defect is in the wording and the author is the right party to fix
it: the operator repairing it would be the operator writing benchmark content,
and the assistant repairing it would be the contaminated party writing it. So
the flagged texts go back to the session that wrote them, with the defect
described and nothing else.

What the rendered request does not contain, deliberately: the adjudicator's
proposed label, which is masked out of the quoted reason, its identity, any
count or quota, and anything at all about the system under test. The author learns that two of its groups have paraphrases
that do not carry the same intent, and which detail differs. It does not learn
whether its own label was upheld.

The texts are quoted from the reconciliation worksheet rather than retyped, so
what the author sees is what the pipeline read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HEADER = """You generated a benchmark batch for an agentic IoT data-aggregation
scheduling system. An independent adjudicator has reviewed it and flagged the
groups below: in each one, your two paraphrases do not carry the same intent.

The gold action of these groups is not in question and you should not change
it. Nothing else about the batch is in question either.

For each group, revise the request texts so that both paraphrases:

- express exactly the same intent and the same configuration, including every
  quantity;
- keep the same gold action as before;
- still differ in sentence structure rather than in a few synonyms;
- still read like a request from a system operator or researcher.

Change the wording only. Do not introduce a capability, a parameter or a
topology that the group did not already mention, and do not copy sentences
from the adjudicator's description into a request.

Return JSON only, with this structure and these two groups alone:

{
  "revisions": [
    {
      "semantic_group_id": "...",
      "paraphrases": [
        {"request_id": "...", "request_text": "..."},
        {"request_id": "...", "request_text": "..."}
      ]
    }
  ]
}
"""


# The adjudicator's wording names the action it settled on, and the author must
# not learn whether its own label was upheld. The reason is quoted rather than
# paraphrased --- a paraphrase would be us writing it --- so the action tokens
# are masked in place instead.
ACTIONS = ("EXECUTE", "CLARIFY", "REJECT", "UNSUPPORTED")


def mask_actions(reason: str) -> str:
    for action in ACTIONS:
        reason = reason.replace(action, "[action]")
    return reason


def flagged_groups(worksheet: dict, batch_id: str) -> list[dict]:
    groups = worksheet.get("groups") or worksheet.get("worksheet") or []
    return [g for g in groups
            if g.get("classification") == "PARAPHRASE_MISMATCH"
            and (g.get("batch_id") == batch_id or batch_id is None)]


def render(worksheet: dict, reviews: dict, batch_id: str) -> str:
    by_id = {r["semantic_group_id"]: r for r in reviews.get("reviews", [])}
    parts = [HEADER]
    for group in flagged_groups(worksheet, batch_id):
        gid = group["semantic_group_id"]
        reason = mask_actions((by_id.get(gid) or {}).get("reason", ""))
        parts.append("=" * 50)
        parts.append(f"Group {gid}")
        parts.append("")
        parts.append("What the adjudicator found:")
        parts.append(f"  {reason}")
        parts.append("")
        parts.append("Your current texts:")
        for paraphrase in group.get("paraphrases", []):
            parts.append(f"  {paraphrase['request_id']}:")
            parts.append(f"    {paraphrase['request_text']}")
        parts.append("")
    parts.append("Return JSON only.")
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worksheet", required=True)
    parser.add_argument("--reviews", required=True,
                        help="the adjudication of that batch, for the defect wording")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--out", required=True, help="write-once")
    args = parser.parse_args()

    worksheet = json.loads((ROOT / args.worksheet).read_text(encoding="utf-8"))
    reviews = json.loads((ROOT / args.reviews).read_text(encoding="utf-8"))
    out = ROOT / args.out
    if out.exists():
        print(json.dumps({"status": "refused",
                          "problems": [f"refusing to overwrite {out}"]}, indent=2))
        return 1
    text = render(worksheet, reviews, args.batch_id)
    groups = len(flagged_groups(worksheet, args.batch_id))
    if not groups:
        print(json.dumps({"status": "refused",
                          "problems": ["no flagged group in that batch"]}, indent=2))
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print(json.dumps({"status": "rendered", "out": str(out), "groups": groups,
                      "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

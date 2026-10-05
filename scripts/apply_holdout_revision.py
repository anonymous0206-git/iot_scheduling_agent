#!/usr/bin/env python3
"""Apply an author's paraphrase revision to a batch, and refuse anything else.

A flagged group goes back to the session that wrote it, and what comes back is
new wording for the same request ids. This applies that wording and nothing
else: the labels, the fields, the categories and the identifiers of the batch
are carried across untouched, and a revision that tries to move any of them is
refused rather than partly applied.

The original batch is never modified. The revised batch is written beside it,
and the two are what the seal step hashes, so a reader can diff them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def apply_revision(batch: dict, revision: dict) -> tuple[dict, list[str], list[str]]:
    by_id = {group["semantic_group_id"]: group for group in batch["groups"]}
    problems: list[str] = []
    changed: list[str] = []
    out = json.loads(json.dumps(batch))
    index = {group["semantic_group_id"]: group for group in out["groups"]}

    for entry in revision.get("revisions", []):
        gid = entry.get("semantic_group_id")
        extra = set(entry) - {"semantic_group_id", "paraphrases"}
        if extra:
            problems.append(f"{gid}: revision carries fields it may not set: {sorted(extra)}")
            continue
        if gid not in by_id:
            problems.append(f"{gid}: not a group of this batch")
            continue
        original = by_id[gid]
        new = entry.get("paraphrases") or []
        if [p.get("request_id") for p in new] != [p["request_id"] for p in original["paraphrases"]]:
            problems.append(f"{gid}: request ids differ from the batch")
            continue
        if any(set(p) - {"request_id", "request_text"} for p in new):
            problems.append(f"{gid}: a paraphrase carries fields it may not set")
            continue
        if any(not (p.get("request_text") or "").strip() for p in new):
            problems.append(f"{gid}: an empty request text")
            continue
        for slot, paraphrase in zip(index[gid]["paraphrases"], new):
            slot["request_text"] = paraphrase["request_text"]
        changed.append(gid)
    return out, changed, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--out", required=True, help="write-once")
    args = parser.parse_args()

    batch = json.loads((ROOT / args.batch).read_text(encoding="utf-8"))
    revision = json.loads((ROOT / args.revision).read_text(encoding="utf-8"))
    out = ROOT / args.out
    if out.exists():
        print(json.dumps({"status": "refused",
                          "problems": [f"refusing to overwrite {out}"]}, indent=2))
        return 1

    revised, changed, problems = apply_revision(batch, revision)
    if problems:
        print(json.dumps({"status": "refused", "problems": problems}, indent=2))
        return 1

    text = json.dumps(revised, indent=2, ensure_ascii=False) + "\n"
    with open(out, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print(json.dumps({
        "status": "applied",
        "out": str(out),
        "groups_revised": changed,
        "groups_total": len(revised["groups"]),
        "sha256": {"before": hashlib.sha256((ROOT / args.batch).read_bytes()).hexdigest(),
                   "after": hashlib.sha256(text.encode("utf-8")).hexdigest()},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

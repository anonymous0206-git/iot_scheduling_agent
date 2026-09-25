#!/usr/bin/env python3
"""Export the sealed Frozen Test v2 into the experiment-runner benchmark format.

This is an evaluator-side step: it joins the target-facing requests with the
gold records, so its output carries labels and must not be given to the system
under test. The sealed directory is verified first, the output is write-once,
and a sidecar manifest records the source hashes. No model, ANEX, policy, or
validator is invoked.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from frozen_test_v2.documents import (
    canonical_json,
    jsonl_text,
    read_jsonl,
    sha256_file,
    sha256_text,
    utc_now_iso,
    write_text_exclusive,
)
from frozen_test_v2.harness import HARNESS_FORMAT, HarnessExportError, build_harness_items
from frozen_test_v2.seal import MANIFEST_FILENAME, SEALED_FILENAMES, verify_sealed_directory


def _refuse(problems: list[str]) -> int:
    print(json.dumps({"status": "refused", "problems": problems}, indent=2))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sealed-dir", required=True, help="directory written by frozen_test_v2 seal")
    parser.add_argument("--output", required=True, help="harness JSONL to create (write-once)")
    args = parser.parse_args()
    sealed = Path(args.sealed_dir)
    output = Path(args.output)
    sidecar = output.with_name(output.name + ".manifest.json")
    existing = [str(path) for path in (output, sidecar) if path.exists()]
    if existing:
        return _refuse([f"refusing to overwrite {path}" for path in existing])
    report = verify_sealed_directory(sealed)
    if not report["valid"]:
        return _refuse([f"sealed directory failed verification: {failure}"
                        for failure in report["failures"]])
    requests = read_jsonl(sealed / SEALED_FILENAMES["requests_jsonl"])
    gold = read_jsonl(sealed / SEALED_FILENAMES["gold_jsonl"])
    sealed_manifest = json.loads((sealed / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    try:
        export = build_harness_items(
            requests, gold,
            catalogue=sealed_manifest.get("topology_catalogue"),
            benchmark_version=sealed_manifest.get("benchmark_version", "frozen-test-v2"))
    except HarnessExportError as exc:
        return _refuse([str(exc)])
    text = jsonl_text(export.items)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_text_exclusive(output, text)
    manifest = {
        "harness_format": HARNESS_FORMAT,
        "exported_at_utc": utc_now_iso(),
        "sealed_dir": str(sealed),
        "sources": {
            key: {"path": name, "sha256": sha256_file(sealed / name)}
            for key, name in (
                ("requests_jsonl", SEALED_FILENAMES["requests_jsonl"]),
                ("gold_jsonl", SEALED_FILENAMES["gold_jsonl"]),
                ("lock_manifest", MANIFEST_FILENAME),
            )
        },
        "output": {"path": str(output), "sha256": sha256_text(text), "records": len(export.items)},
        "evaluator_side_only": True,
        "summary": export.summary,
    }
    write_text_exclusive(sidecar, canonical_json(manifest))
    print(json.dumps({"status": "exported", "output": str(output), "manifest": str(sidecar),
                      "summary": export.summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

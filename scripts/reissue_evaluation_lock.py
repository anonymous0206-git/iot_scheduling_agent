#!/usr/bin/env python3
"""Re-issue an evaluation lock after a deliberate change to the locked pipeline.

A lock exists so that a result can be tied to the exact bytes that produced it.
That means a lock is never edited: when the pipeline has to change, the old lock
stays as the record of the old results and a new lock is issued beside it.

This script does that, and refuses to do it quietly. It recomputes the SHA-256 of
every file the base lock covers, reports which ones changed, and writes the new
lock only if a written rationale is supplied. The rationale, the base lock's own
hash, and the before/after hash of every changed file are recorded in the output,
so a reader can see precisely what moved between two sets of results.

What it does not do: re-seal a benchmark. The sealed requests and gold labels are
unchanged by a pipeline repair, and their provenance chain is the authoring lock,
which this script never touches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]


class LockError(ValueError):
    """The lock cannot be re-issued as asked."""


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recompute(base_hashes: Mapping[str, str], root: Path) -> dict[str, Any]:
    """Hash every file the base lock covers and classify it."""
    current: dict[str, str] = {}
    missing: list[str] = []
    for relative in sorted(base_hashes):
        path = root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        current[relative] = sha256_of(path)
    changed = {name: {"was": base_hashes[name], "now": digest}
               for name, digest in current.items() if digest != base_hashes[name]}
    return {"current": current, "missing": missing, "changed": changed}


def add_coverage(current: dict[str, str], additions: Sequence[str], root: Path) -> list[str]:
    """Bring files the base lock never covered under the new lock.

    A lock that omits a file cannot detect a change to it. When a repair touches
    code outside the base lock's reach, extending coverage is part of the repair.
    """
    added: list[str] = []
    for relative in sorted(set(additions)):
        if relative in current:
            raise LockError(f"{relative} is already covered by the base lock")
        path = root / relative
        if not path.is_file():
            raise LockError(f"cannot add a file that does not exist: {relative}")
        current[relative] = sha256_of(path)
        added.append(relative)
    return added


def build(base: Mapping[str, Any], base_path: Path, rationale: str, status: str,
          runtime_overrides: Mapping[str, Any] | None, root: Path,
          additions: Sequence[str] = ()) -> dict[str, Any]:
    base_hashes = base.get("sha256")
    if not isinstance(base_hashes, Mapping) or not base_hashes:
        raise LockError(f"{base_path} carries no sha256 map")
    result = recompute(base_hashes, root)
    if result["missing"]:
        raise LockError("files covered by the base lock are missing: "
                        + ", ".join(result["missing"]))
    added = add_coverage(result["current"], additions, root)
    if not result["changed"] and not added:
        raise LockError("no covered file changed and no file was added; re-issuing a "
                        "lock that would be identical to its base only adds confusion")

    runtime = dict(base.get("runtime") or {})
    runtime.update(dict(runtime_overrides or {}))
    lock = dict(base)
    lock.update({
        "lock_format": base.get("lock_format", "agentic_anex.evaluation_lock"),
        "status": status,
        "locked_at": date.today().isoformat(),
        "supersedes": str(base_path.relative_to(root)) if base_path.is_relative_to(root)
                      else str(base_path),
        "revision_of": {
            "lock": str(base_path.relative_to(root)) if base_path.is_relative_to(root)
                    else str(base_path),
            "sha256": sha256_of(base_path),
            "locked_at": base.get("locked_at"),
        },
        "pipeline_revision": {
            "rationale": rationale,
            "changed_files": result["changed"],
            "newly_covered_files": added,
            "unchanged_file_count": (len(result["current"]) - len(result["changed"])
                                     - len(added)),
            "results_produced_under_the_base_lock_remain_valid_for_that_lock": True,
        },
        "runtime": runtime,
        "sha256": result["current"],
    })
    return lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True, help="the lock being superseded")
    parser.add_argument("--out", required=True, help="new lock path; must not exist")
    parser.add_argument("--status", required=True)
    parser.add_argument("--rationale", help="why the pipeline changed")
    parser.add_argument("--rationale-file", help="read the rationale from this file")
    parser.add_argument("--runtime-json", help="JSON file of runtime fields to update")
    parser.add_argument("--add", action="append", default=[], metavar="PATH",
                        help="bring a file the base lock never covered under the new "
                             "lock (repeatable)")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    if out.exists():
        print(json.dumps({"status": "refused", "problems": [
            f"refusing to overwrite an existing lock: {out}"]}, indent=2))
        return 1

    rationale = args.rationale
    if args.rationale_file:
        rationale = Path(args.rationale_file).read_text(encoding="utf-8").strip()
    if not rationale or not rationale.strip():
        print(json.dumps({"status": "refused", "problems": [
            "a lock may not be re-issued without a written rationale"]}, indent=2))
        return 1

    base_path = Path(args.base)
    if not base_path.is_absolute():
        base_path = root / base_path
    base = json.loads(base_path.read_text(encoding="utf-8"))
    overrides = (json.loads(Path(args.runtime_json).read_text(encoding="utf-8"))
                 if args.runtime_json else None)
    try:
        lock = build(base, base_path, rationale.strip(), args.status, overrides, root,
                     args.add)
    except LockError as exc:
        print(json.dumps({"status": "refused", "problems": [str(exc)]}, indent=2))
        return 1

    out.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "issued",
        "lock": str(out.relative_to(root)) if out.is_relative_to(root) else str(out),
        "supersedes": lock["supersedes"],
        "changed_files": sorted(lock["pipeline_revision"]["changed_files"]),
        "newly_covered_files": lock["pipeline_revision"]["newly_covered_files"],
        "unchanged_file_count": lock["pipeline_revision"]["unchanged_file_count"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

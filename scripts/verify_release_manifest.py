#!/usr/bin/env python3
"""Verify the release manifest, the lock chain, and the record between them.

`verify_evaluation_lock.py` answers one question about one lock: do the files it
covers still hash to what it recorded? For a historical lock the answer is no,
and should be --- the pipeline moved on after it was issued. This script is the
check that can therefore pass:

  1. every file the release manifest pins hashes to what the manifest records;
  2. every lock in the chain still hashes to what the manifest recorded for it,
     so no lock has been quietly rewritten to make a hash agree;
  3. every divergence between a lock and the tree is one the manifest declares,
     and every declared divergence is still real;
  4. where a declaration names the lock that pins the current bytes, that lock
     does record them.

A failure in (3) is the one worth reading closely: it means a file moved and
nothing says why.

It passes on the repository and on an unpacked anonymous archive alike. In the
archive some members are rewritten to remove an identifying path and a few are
omitted; the manifest records which and to what, and the report names them
rather than failing on them.

    scripts/verify_release_manifest.py
    scripts/verify_release_manifest.py --manifest benchmarks/release_manifest_v5.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_released_files(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    """Hash every released file, allowing for the anonymous archive.

    The manifest records the repository's bytes. In the anonymous archive some
    members are rewritten and a few are omitted, and the manifest says which
    and to what, so the same check passes on both: a rewritten member has to
    match its recorded archive hash, and an omitted one has to be one of the
    files named as omitted.
    """
    anonymity = manifest.get("anonymity") or {}
    withheld = set(manifest.get("withheld_from_the_anonymous_archive") or ())
    failures, rewritten, absent = [], [], []
    for relative, expected in sorted(manifest["sha256"].items()):
        path = root / relative
        if not path.is_file():
            if relative in withheld:
                absent.append(relative)
            else:
                failures.append({"path": relative, "expected": expected,
                                 "actual": "MISSING"})
            continue
        actual = sha256_of(path)
        if actual == expected:
            continue
        if actual == (anonymity.get(relative) or {}).get("anonymous_archive_sha256"):
            rewritten.append(relative)
            continue
        failures.append({"path": relative, "expected": expected, "actual": actual})
    return {"released_files_that_do_not_match": failures,
            "members_rewritten_for_anonymity": rewritten,
            "members_withheld_for_anonymity": absent}


def check_lock_chain(manifest: dict[str, Any], root: Path) -> list[dict[str, str]]:
    failures = []
    for relative, recorded in sorted(manifest["lock_chain"].items()):
        path = root / relative
        actual = sha256_of(path) if path.is_file() else "MISSING"
        if actual != recorded["sha256"]:
            failures.append({"lock": relative, "expected": recorded["sha256"],
                             "actual": actual,
                             "note": "a lock is a historical record and is never "
                                     "edited; this one has been"})
    return failures


def check_divergences(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    """Recompute the divergences and compare them with the declared ones."""
    declared = manifest["divergences_from_the_lock_chain"]
    actual: dict[str, dict[str, str]] = {}
    for lock_name in manifest["lock_chain"]:
        lock = json.loads((root / lock_name).read_text(encoding="utf-8"))
        for relative, locked in (lock.get("sha256") or {}).items():
            path = root / relative
            current = sha256_of(path) if path.is_file() else None
            if current != locked:
                actual.setdefault(relative, {})[lock_name] = locked

    # A file a lock covers that this release does not ship is absent by design,
    # not changed. The manifest lists those with the hash the repository holds,
    # so an unpacked archive does not read as a tree full of missing files.
    not_shipped = manifest.get("lock_covered_files_not_shipped") or {}
    # The same for the one kind of released file the anonymous archive leaves
    # out: a file carrying an identifying path whose hash a lock publishes, so
    # it is omitted rather than rewritten. check_released_files reports those.
    withheld = set(manifest.get("withheld_from_the_anonymous_archive") or ())
    undeclared = []
    for relative, locks in sorted(actual.items()):
        path = root / relative
        if relative in not_shipped:
            if not path.is_file():
                continue
            if sha256_of(path) == not_shipped[relative]:
                continue
            undeclared.append({"path": relative, "diverges_from": sorted(locks),
                               "note": "not shipped by this release, and the "
                                       "copy here does not hold the hash the "
                                       "manifest recorded for it either"})
            continue
        if relative in withheld and not path.is_file():
            continue
        if relative not in declared:
            undeclared.append({"path": relative, "diverges_from": sorted(locks),
                               "note": "differs from a lock and no reason is on "
                                       "record"})
            continue
        entry = declared[relative]
        missing = sorted(set(locks) - set(entry["diverges_from"]))
        if missing:
            undeclared.append({"path": relative, "diverges_from": missing,
                               "note": "declared, but not against these locks"})

    resolved = [path for path in sorted(declared)
                if path not in actual and (root / path).is_file()]
    mispinned = []
    for relative, entry in sorted(declared.items()):
        pinning = entry.get("superseded_by")
        if not pinning:
            continue
        lock = json.loads((root / pinning).read_text(encoding="utf-8"))
        recorded = (lock.get("sha256") or {}).get(relative)
        if recorded != entry["current_sha256"]:
            mispinned.append({"path": relative, "lock": pinning,
                              "declared_current": entry["current_sha256"],
                              "lock_records": recorded or "nothing"})
    return {"undeclared_divergences": undeclared,
            "declarations_no_longer_real": resolved,
            "superseding_lock_does_not_pin_the_current_bytes": mispinned}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", default="benchmarks/release_manifest_v5.json")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    if not manifest_path.is_file():
        print(json.dumps({"valid": False, "problems": [
            f"no manifest at {args.manifest}; build it with "
            "scripts/build_release_manifest.py"]}, indent=2))
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    released = check_released_files(manifest, root)
    chain = check_lock_chain(manifest, root)
    divergence = check_divergences(manifest, root)

    valid = not (released["released_files_that_do_not_match"] or chain
                 or any(divergence.values()))
    report = {
        "valid": valid,
        "manifest": manifest_path.relative_to(root).as_posix()
                    if manifest_path.is_relative_to(root) else str(manifest_path),
        "release": manifest.get("release"),
        "built_at": manifest.get("built_at"),
        "files_pinned": len(manifest["sha256"]),
        "locks_in_chain": len(manifest["lock_chain"]),
        "declared_divergences": len(manifest["divergences_from_the_lock_chain"]),
        "locks_that_have_been_edited": chain,
        **released,
        **divergence,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

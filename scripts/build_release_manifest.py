#!/usr/bin/env python3
"""Write the manifest of the current artefact release.

A lock is never edited. That rule is what makes a lock worth anything --- a
manifest that is brought into line with the tree whenever the tree moves
records nothing --- but it has a consequence a reader meets immediately: run
`verify_evaluation_lock.py` against any lock in the chain and files come back
changed, because the pipeline moved on after that lock was issued. A reader who
is not told which divergences are expected cannot tell them from tampering.

This script writes the other half of that record. It covers every file the
release ships, including the holdout batch and the ledgers that no lock covers,
and it states every divergence from every historical lock: the two hashes, the
reason, and the lock that pins the current bytes where one does. The locks
themselves are pinned by their own SHA-256, so the chain cannot be rewritten
behind the manifest either.

Divergences are declared below, by path, and the script refuses to write a
manifest whose declarations do not match what the tree actually shows: an
undeclared divergence is an error, and so is a declaration for a file that no
longer diverges. That is the point of generating this file rather than writing
it by hand --- the explanation cannot drift away from the bytes it explains.

    scripts/build_release_manifest.py --out benchmarks/release_manifest_v5.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The release is exactly what the archive ships, so the two read one list of
# patterns rather than two that can drift apart.
from build_supplementary import ROOT, anonymise, collect, hashed_paths  # noqa: E402

RELEASE = "aamas2027-submission"
MANIFEST_FORMAT = "agentic_anex.release_manifest.v1"

# The lock chain, oldest first. Each is pinned by its own hash below, and none
# is edited by this script or by any other.
LOCK_CHAIN = (
    "benchmarks/evaluation_lock_v1.json",               # 2026-08-31
    "benchmarks/policy_v2_development_lock.json",       # 2026-09-01
    "benchmarks/evaluation_lock_v2.json",               # 2026-09-09
    "benchmarks/frozen_test_v3_authoring_lock.json",    # 2026-09-14
    "benchmarks/evaluation_lock_v3.json",               # 2026-09-14
    "benchmarks/evaluation_lock_v3_1.json",             # 2026-09-16
    "benchmarks/evaluation_lock_v4_holdout.json",       # 2026-09-27
)

# Why each released file differs from the hash some earlier lock published.
# One entry per path, because a path that moved once diverges from every lock
# issued before the move and the reason is the same each time.
#
# `revision` names the dated change. `superseded_by` names the lock that
# publishes the current bytes, or is None for the three files no lock reaches:
# this manifest is what pins those.
DIVERGENCES: Mapping[str, Mapping[str, Any]] = {
    "src/agentic_anex/orchestration.py": {
        "revision": "2026-09-21, the pipeline repair of Section 5.5 and the "
                    "scope-mode parameter of Sections 5.2 and 5.3",
        "reason":
            "Two changes, both reported in the paper. The repair: a strict "
            "structured-output mode cannot omit a property, so a field the user "
            "did not state arrives as null, and the orchestrator now reads null "
            "as 'not stated' for the four fields that carry a contract default "
            "and tolerates a null clarification list. That is what made the "
            "CLARIFY capability measurable --- before it, four requests failed "
            "for every model we tested because our own contract discarded the "
            "answer. The ablation: stage 1's authority became a parameter "
            "(enforcing, advisory, off) so that the arms of Sections 5.2 and "
            "5.3 run one pipeline with one component moved rather than three "
            "pipelines. The detector itself is unchanged; only what the "
            "orchestrator does with its finding moves.",
        "superseded_by": "benchmarks/evaluation_lock_v4_holdout.json",
    },
    "src/agentic_anex/experiments.py": {
        "revision": "2026-09-21, alongside the orchestration change above",
        "reason":
            "Carries the scope mode through to the arms and names each mode's "
            "ledger, so a ledger says which configuration produced it without "
            "a separate note. It also puts the rule baseline behind the same "
            "stage-1 gate the agent runs, which is why Section 4.5 calls that "
            "arm the pipeline without its model rather than a different "
            "pipeline. No scheduling, validation or scoring code is touched.",
        "superseded_by": "benchmarks/evaluation_lock_v4_holdout.json",
    },
    "scripts/run_scope_gate_ablation.py": {
        "revision": "2026-09-21, alongside the orchestration change above",
        "reason":
            "The runner for the ablation arms, updated to pass the scope mode "
            "it now selects. It writes ledgers and reads none, so it cannot "
            "alter a recorded run.",
        "superseded_by": "benchmarks/evaluation_lock_v4_holdout.json",
    },
    "scripts/run_frozen_test_v3_seed_campaign.py": {
        "revision": "2026-09-22, while the campaign was being run",
        "reason":
            "Changed between runs of the campaign it drives. The ledgers are "
            "append-only and each records the arm, the seed and the model "
            "digest it ran under, so a change to the runner cannot reach a run "
            "already written.",
        "superseded_by": "benchmarks/evaluation_lock_v4_holdout.json",
    },
    "scripts/analyze_frozen_test_results.py": {
        "revision": "2026-09-26 and 2026-09-29, after the campaigns closed",
        "reason":
            "The analysis, which reads ledgers and writes summaries; it cannot "
            "change a result, only what is computed from one. It gained joint "
            "intent success and a fix for the three runner-bound fields on "
            "2026-09-26, and on 2026-09-29, after the holdout had closed, a "
            "check that a ledger and a harness agree on the fields naming the "
            "request. That check is the one the holdout's identifier collision "
            "called for: `holdout_v4` inherited `frozen_test_v3`'s `ft3-rNNNN` "
            "numbering from `sealed_id_prefix`, so pairing those ledgers with "
            "the frozen harness used to report a plausible accuracy instead of "
            "an error. Every number in the paper was produced before the check "
            "existed, by the version `evaluation_lock_v4_holdout.json` records, "
            "and re-running the analysis with the check in place reproduces "
            "them --- the check refuses a pairing nothing in the paper used. "
            "The identifiers themselves are left alone: the prefix comes from "
            "`sealed_id_prefix` in `src/frozen_test_v2/seal.py`, which this lock "
            "pins, and section 2 of the holdout protocol restarts the experiment "
            "on a change to a covered file. The lock covers no `holdout_v4` path "
            "of its own, having been issued before the batch existed, so what is "
            "locked is the sealing code rather than the sealed files.",
        "superseded_by": None,
    },
    "src/frozen_test_v2/seal.py": {
        "revision": "2026-09-14, the frozen-test-v3 sealing pipeline",
        "reason":
            "The v3 contract profile, sealed directory layout and identifier "
            "prefix. Issued as part of frozen-test-v3 and pinned by that "
            "benchmark's authoring lock, which is why the sealed v3 files "
            "verify against it.",
        "superseded_by": "benchmarks/frozen_test_v3_authoring_lock.json",
    },
    "src/frozen_test_v2/contract.py": {
        "revision": "2026-09-14, the frozen-test-v3 sealing pipeline",
        "reason": "The v3 request contract: the seven parsed fields, their "
                  "defaults and their validation. Pinned by the v3 authoring "
                  "lock.",
        "superseded_by": "benchmarks/frozen_test_v3_authoring_lock.json",
    },
    "src/frozen_test_v2/cli.py": {
        "revision": "2026-09-14, the frozen-test-v3 sealing pipeline",
        "reason": "The sealing and blinding commands the v3 batches were "
                  "produced with. Pinned by the v3 authoring lock.",
        "superseded_by": "benchmarks/frozen_test_v3_authoring_lock.json",
    },
    "src/frozen_test_v2/decisions.py": {
        "revision": "2026-09-14, the frozen-test-v3 sealing pipeline",
        "reason": "The human-decision record the v3 reconciliation writes. "
                  "Pinned by the v3 authoring lock.",
        "superseded_by": "benchmarks/frozen_test_v3_authoring_lock.json",
    },
    "src/frozen_test_v2/reconcile.py": {
        "revision": "2026-09-14, the frozen-test-v3 sealing pipeline",
        "reason": "The adjudication reconciliation for v3's two blind reviews. "
                  "Pinned by the v3 authoring lock.",
        "superseded_by": "benchmarks/frozen_test_v3_authoring_lock.json",
    },
    "src/frozen_test_v2/schemas.py": {
        "revision": "2026-09-14, the frozen-test-v3 sealing pipeline",
        "reason": "The schemas the v3 batches and harness are validated "
                  "against. Pinned by the v3 authoring lock.",
        "superseded_by": "benchmarks/frozen_test_v3_authoring_lock.json",
    },
    "docs/frozen_test_v2_pipeline.md": {
        "revision": "2026-09-14, the frozen-test-v3 sealing pipeline",
        "reason": "Documentation of the pipeline above, revised with it. "
                  "Pinned by the v3 authoring lock.",
        "superseded_by": "benchmarks/frozen_test_v3_authoring_lock.json",
    },
    "README.md": {
        "revision": "rewritten for the release, most recently 2026-10-05",
        "reason":
            "The artefact index: what each number in the paper is derived from "
            "and the commands that check it. It is documentation, it is read by "
            "no code, and it is the one file in the release that must describe "
            "the release rather than the state of some earlier lock. No lock "
            "after 2026-09-14 covers it; this manifest pins it.",
        "superseded_by": None,
    },
    "docs/operator_guide.md": {
        "revision": "2026-09-21, with the scope-mode runners",
        "reason":
            "Documentation of how to run the arms, revised when stage 1's "
            "authority became a runner argument. Read by no code. The two locks "
            "that cover it were issued on 2026-09-01 and 2026-09-14, before "
            "that revision, and no later lock reaches it; this manifest pins "
            "it.",
        "superseded_by": None,
    },
}

# Where each released path belongs in the manifest's own grouping. First match
# wins, so the more specific prefixes come first.
GROUPS = (
    ("sealed_benchmark_frozen_test_v3", ("benchmarks/frozen_test_v3/",)),
    ("holdout_batch_v4", ("benchmarks/holdout_v4/",)),
    ("holdout_results_v4", ("results/holdout_v4/",
                            "results/frozen_test_v3/holdout_sizing/")),
    ("sealed_benchmark_results_v3", ("results/frozen_test_v3/",)),
    ("supporting_experiments", ("results/topology_scaling/",
                                "results/validator_mutation/",
                                "results/")),
    ("lock_chain", ("benchmarks/evaluation_lock_",
                    "benchmarks/policy_v2_development_lock",
                    "benchmarks/frozen_test_v3_authoring_lock",
                    "benchmarks/release_manifest_")),
    ("topologies_and_fixtures", ("benchmarks/topologies/", "benchmarks/",
                                 "network_30_seed7.json")),
    ("agent_and_pipeline_sources", ("src/", "source/")),
    ("scripts", ("scripts/",)),
    ("tests", ("tests/",)),
    ("documentation", ("docs/", "README.md")),
    ("figure_data", ("paper/",)),
    ("build", ("pyproject.toml", "uv.lock")),
)


class ManifestError(ValueError):
    """The manifest cannot be written as asked."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def group_of(relative: str) -> str:
    for name, prefixes in GROUPS:
        if any(relative.startswith(prefix) for prefix in prefixes):
            return name
    return "other"


def lock_chain(root: Path) -> dict[str, Any]:
    """Pin each lock by its own hash, so the chain cannot be rewritten."""
    chain: dict[str, Any] = {}
    for name in LOCK_CHAIN:
        path = root / name
        if not path.is_file():
            raise ManifestError(f"the lock chain names a file that is not here: {name}")
        lock = json.loads(path.read_text(encoding="utf-8"))
        chain[name] = {
            "sha256": sha256_of(path),
            "locked_at": lock.get("locked_at"),
            "status": lock.get("status"),
            "covers_files": len(lock.get("sha256") or {}),
        }
    return chain


def not_shipped(root: Path, released: Mapping[str, str]) -> dict[str, Any]:
    """Files a lock covers that this release does not ship.

    The locks reach back to work the release leaves out --- frozen-test-v2, the
    development ledgers, the author-identifying source zips --- and those files
    are absent from the archive by design. Recording them here, with the hash
    the repository holds, is what lets the verifier tell an absent member from
    a changed one when it is run inside an unpacked archive rather than here.
    """
    covered: set[str] = set()
    for name in LOCK_CHAIN:
        lock = json.loads((root / name).read_text(encoding="utf-8"))
        covered.update((lock.get("sha256") or {}).keys())
    absent: dict[str, Any] = {}
    for relative in sorted(covered - set(released)):
        path = root / relative
        absent[relative] = sha256_of(path) if path.is_file() else None
    return absent


def divergences(root: Path, released: Mapping[str, str]) -> dict[str, Any]:
    """Every file an earlier lock published a different hash for.

    Raises when the declarations above do not match what the tree shows, in
    either direction.
    """
    found: dict[str, dict[str, Any]] = {}
    undeclared: list[str] = []
    for name in LOCK_CHAIN:
        lock = json.loads((root / name).read_text(encoding="utf-8"))
        for relative, locked in sorted((lock.get("sha256") or {}).items()):
            path = root / relative
            current = sha256_of(path) if path.is_file() else None
            if current == locked:
                continue
            declaration = DIVERGENCES.get(relative)
            if declaration is None:
                undeclared.append(f"{name}: {relative}")
                continue
            entry = found.setdefault(relative, {
                "state": "absent" if current is None else "changed",
                "current_sha256": current,
                "released": relative in released,
                "diverges_from": {},
                **{key: declaration[key]
                   for key in ("revision", "reason", "superseded_by")},
            })
            entry["diverges_from"][name] = {
                "locked_sha256": locked,
                "lock_issued": lock.get("locked_at"),
            }
    if undeclared:
        raise ManifestError(
            "these files differ from a lock and no divergence is declared for "
            "them; declare them in DIVERGENCES rather than letting the manifest "
            "pass over them: " + ", ".join(sorted(undeclared)))
    stale = sorted(set(DIVERGENCES) - set(found))
    if stale:
        raise ManifestError(
            "a divergence is declared for these files but they now match every "
            "lock that covers them; remove the stale declaration: "
            + ", ".join(stale))
    for relative, entry in found.items():
        if entry["superseded_by"] is None:
            continue
        pinning = json.loads((root / entry["superseded_by"]).read_text(encoding="utf-8"))
        recorded = (pinning.get("sha256") or {}).get(relative)
        if recorded != entry["current_sha256"]:
            raise ManifestError(
                f"{relative} declares {entry['superseded_by']} as the lock that "
                f"pins its current bytes, but that lock records "
                f"{recorded or 'nothing'} for it")
    return found


def build(root: Path, out: Path) -> dict[str, Any]:
    files, withheld_for_anonymity = collect(root)
    # The manifest ships inside the release it describes, so the collection
    # picks it up. It cannot pin itself --- writing the hash changes the bytes
    # --- so it is excluded here and named in `self` below instead.
    itself = out.relative_to(root).as_posix() if out.is_relative_to(root) else None
    released = {path.relative_to(root).as_posix(): sha256_of(path) for path in files
                if path.relative_to(root).as_posix() != itself}
    if not released:
        raise ManifestError("no released files matched")

    diverged = divergences(root, released)
    grouped: dict[str, list[str]] = {}
    for relative in sorted(released):
        grouped.setdefault(group_of(relative), []).append(relative)

    pinned_only_here = sorted(name for name, entry in diverged.items()
                              if entry["superseded_by"] is None)

    # What the anonymous archive will do to these same files, computed from the
    # packaging rules rather than described separately, so the two cannot drift.
    # A reviewer who has only the zip can then verify it: a redacted member
    # matches its archive hash, and a withheld one is absent on purpose.
    members, redacted, withheld_by_hash = anonymise(root, files, hashed_paths(root))
    archive_hashes = {name: hashlib.sha256(data).hexdigest()
                      for name, data in members}
    anonymity = {name: {"repository_sha256": released[name],
                        "anonymous_archive_sha256": archive_hashes[name]}
                 for name in sorted(redacted) if name in released}
    return {
        "manifest_format": MANIFEST_FORMAT,
        "release": RELEASE,
        "built_at": date.today().isoformat(),
        "self": itself,
        "self_note":
            "This manifest ships inside the release and is the one released "
            "file it does not pin, because recording its own hash would change "
            "it. Everything it covers is listed under sha256.",
        "what_this_is":
            "The manifest of the released artefact. It pins every file the "
            "release ships, including the holdout batch and the ledgers that "
            "no lock covers, and it states every divergence from every lock in "
            "the chain. The locks are historical records and are not edited: "
            "where a locked file has moved on, the divergence is declared here "
            "with its reason and the lock that pins the current bytes. Verify "
            "it with scripts/verify_release_manifest.py, which fails on an "
            "undeclared divergence as well as on a bad hash.",
        "lock_chain": lock_chain(root),
        "lock_chain_note":
            "Issued oldest first; each lock supersedes the one before it and "
            "none is rewritten. Running verify_evaluation_lock.py against any "
            "of them reports the divergences below, which is expected: a lock "
            "records the bytes that produced one set of results, not the "
            "current tree.",
        "divergences_from_the_lock_chain": diverged,
        "files_pinned_by_this_manifest_alone": pinned_only_here,
        "sha256": released,
        "sha256_groups": grouped,
        "lock_covered_files_not_shipped": not_shipped(root, released),
        "lock_covered_files_not_shipped_note":
            "The chain reaches back to work this release leaves out --- "
            "frozen-test-v2, the development ledgers, the author-identifying "
            "source zips. Their absence from the archive is not a divergence, "
            "and the hash recorded here is the one the repository holds.",
        "anonymity": anonymity,
        "withheld_from_the_anonymous_archive": sorted(withheld_by_hash),
        "withheld_for_anonymity": withheld_for_anonymity,
        "anonymity_note":
            "The hashes under sha256 are the repository's own bytes. The "
            "anonymous archive rewrites an absolute path that carries a "
            "username, and in the legacy scheduler sources a docstring naming "
            "its programmer; `anonymity` gives both hashes for each such file, "
            "so the archive verifies as the archive and the repository as the "
            "repository. Files that carry that path and whose hash a lock "
            "publishes are omitted from the archive instead of rewritten, and "
            "are listed under withheld_from_the_anonymous_archive.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="benchmarks/release_manifest_v5.json")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--force", action="store_true",
                        help="rewrite an existing manifest of this release. A "
                             "manifest is regenerated whenever the release "
                             "changes, unlike a lock, which never is.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    if out.exists() and not args.force:
        print(json.dumps({"status": "refused", "problems": [
            f"{out} exists; pass --force to regenerate it"]}, indent=2))
        return 1

    try:
        manifest = build(root, out)
    except ManifestError as exc:
        print(json.dumps({"status": "refused", "problems": [str(exc)]}, indent=2))
        return 1

    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "status": "written",
        "manifest": out.relative_to(root).as_posix(),
        "files_pinned": len(manifest["sha256"]),
        "groups": {name: len(paths)
                   for name, paths in sorted(manifest["sha256_groups"].items())},
        "declared_divergences": len(manifest["divergences_from_the_lock_chain"]),
        "files_pinned_by_this_manifest_alone":
            manifest["files_pinned_by_this_manifest_alone"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

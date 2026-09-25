"""Seal the reconciled benchmark: target-facing requests, gold labels, lock manifest.

Sealing refuses to proceed when unresolved disagreements remain, when a
sealed benchmark already exists in the output directory, when a leakage check
fails, or when any provenance input (topology, prompts, model metadata,
source commit) is missing or inconsistent.
"""

from __future__ import annotations

import json
import platform
import random
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import PIPELINE_VERSION
from .contract import ACTIONS
from .decisions import FinalSet, SealRefusal, apply_decisions
from .documents import (
    LoadedDocument,
    canonical_json,
    jsonl_text,
    read_jsonl,
    sha256_bytes,
    sha256_file,
    sha256_text,
    utc_now_iso,
    write_text_exclusive,
)
from .reconcile import Reconciliation
from .schemas import validate_model_metadata

MANIFEST_FORMAT = "agentic_anex.frozen_test_v2_lock.v1"
DEFAULT_SHUFFLE_SEED = 20260908
DEFAULT_MAX_SAME_ACTION_RUN = 10
SEALED_FILENAMES: dict[str, str] = {
    "requests_jsonl": "frozen_test_v2_requests.jsonl",
    "gold_jsonl": "frozen_test_v2_gold.jsonl",
    "worksheet_json": "frozen_test_v2_reconciliation_worksheet.json",
    "human_decisions_copy": "frozen_test_v2_human_decisions.json",
}
MANIFEST_FILENAME = "frozen_test_v2_lock_manifest.json"
MANIFEST_DIGEST_FILENAME = "frozen_test_v2_lock_manifest.sha256"
ALLOWED_REQUEST_KEYS = frozenset({"request_id", "request_text"})
SEALED_ID_PATTERN = re.compile(r"^ft\d+-r\d{4,}$")
LABEL_TOKEN_PATTERN = re.compile(r"\b(EXECUTE|CLARIFY|REJECT|UNSUPPORTED)\b")
SCHEMA_TOKEN_PATTERN = re.compile(
    r"(proposed_gold|gold_action|gold_fields|adjudicated_|annotation_reason|"
    r"capability_category|ambiguity_risk|item_quality|semantic_group_id|invalid_fields|"
    r"reconciliation_class)", re.IGNORECASE)


@dataclass
class SealedRecords:
    requests: list[dict[str, Any]]
    gold: list[dict[str, Any]]
    source_order: list[str]


@dataclass
class SealResult:
    output_dir: Path
    manifest: dict[str, Any]
    paths: dict[str, Path]


def sealed_id_prefix(version: str) -> str:
    """Opaque request-id prefix for a benchmark version, e.g. frozen-test-v3 -> ft3."""
    match = re.search(r"v(\d+)$", version)
    return f"ft{match.group(1)}" if match else "ft0"


def build_sealed_records(final_set: FinalSet, *, shuffle_seed: int,
                         id_prefix: str = "ft2") -> SealedRecords:
    """Assign opaque request ids in a seeded shuffled order and split requests from gold."""
    items: list[tuple[Any, int, dict[str, str]]] = []
    for group in final_set.groups:
        for index, paraphrase in enumerate(group.paraphrases, start=1):
            items.append((group, index, paraphrase))
    order = list(range(len(items)))
    random.Random(shuffle_seed).shuffle(order)
    requests: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    for position, item_index in enumerate(order, start=1):
        group, paraphrase_index, paraphrase = items[item_index]
        sealed_id = f"{id_prefix}-r{position:04d}"
        text = paraphrase["request_text"]
        requests.append({"request_id": sealed_id, "request_text": text})
        gold.append({
            "request_id": sealed_id,
            "source_request_id": paraphrase["request_id"],
            "semantic_group_id": group.semantic_group_id,
            "batch_id": group.batch_id,
            "paraphrase_index": paraphrase_index,
            "gold_action": group.gold_action,
            "gold_fields": group.gold_fields,
            "invalid_fields": group.invalid_fields,
            "topology_id": group.topology_id,
            "difficulty": group.difficulty,
            "capability_category": group.capability_category,
            "reconciliation_class": group.reconciliation_class,
            "decision_source": group.decision_source,
            "paraphrase_equivalence_source": group.paraphrase_equivalence_source,
            "request_text_sha256": sha256_text(text),
        })
    return SealedRecords(requests=requests, gold=gold,
                         source_order=[item[2]["request_id"] for item in items])


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "passed": passed, "detail": detail}


def _longest_run(values: Sequence[str]) -> int:
    longest = current = 0
    previous: str | None = None
    for value in values:
        current = current + 1 if value == previous else 1
        previous = value
        longest = max(longest, current)
    return longest


def check_request_leakage(requests: Sequence[Mapping[str, Any]],
                          gold: Sequence[Mapping[str, Any]], *,
                          source_identifiers: Iterable[str] = (),
                          source_order: Sequence[str] | None = None,
                          max_same_action_run: int = DEFAULT_MAX_SAME_ACTION_RUN
                          ) -> list[dict[str, Any]]:
    """Return a list of leakage checks (each with ``passed``) for target-facing records."""
    checks: list[dict[str, Any]] = []
    gold_by_id = {record.get("request_id"): record for record in gold}
    bad = [record.get("request_id") for record in requests
           if set(record) != ALLOWED_REQUEST_KEYS]
    checks.append(_check("request_keys_allowlist", not bad,
                         f"records with keys outside {sorted(ALLOWED_REQUEST_KEYS)}: {bad[:5]}"
                         if bad else "only request_id and request_text are present"))
    bad = [record.get("request_id") for record in requests
           if not isinstance(record.get("request_id"), str)
           or not SEALED_ID_PATTERN.match(record["request_id"])]
    checks.append(_check("opaque_request_ids", not bad,
                         f"ids not matching {SEALED_ID_PATTERN.pattern}: {bad[:5]}"
                         if bad else "all ids are opaque sealed ids"))
    identifiers = sorted({value for value in source_identifiers if value})
    bad = [record.get("request_id") for record in requests
           if any(identifier in str(record.get("request_text", ""))
                  or identifier in str(record.get("request_id", ""))
                  for identifier in identifiers)]
    checks.append(_check("no_source_identifiers", not bad,
                         f"records exposing source ids: {bad[:5]}" if bad
                         else "no source request or group identifiers are exposed"))
    bad = [record.get("request_id") for record in requests
           if LABEL_TOKEN_PATTERN.search(str(record.get("request_text", "")))]
    checks.append(_check("no_label_tokens", not bad,
                         f"records containing action label tokens: {bad[:5]}" if bad
                         else "no gold action tokens appear in request text"))
    bad = [record.get("request_id") for record in requests
           if SCHEMA_TOKEN_PATTERN.search(str(record.get("request_text", "")))]
    checks.append(_check("no_schema_field_names", not bad,
                         f"records containing gold schema field names: {bad[:5]}" if bad
                         else "no gold schema field names appear in request text"))
    texts = [str(record.get("request_text", "")) for record in requests]
    checks.append(_check("unique_texts", len(set(texts)) == len(texts),
                         "all request texts are unique" if len(set(texts)) == len(texts)
                         else "duplicate request texts are present"))
    sealed_sequence = [gold_by_id[record["request_id"]].get("source_request_id")
                       for record in requests if record.get("request_id") in gold_by_id]
    if source_order is not None and len(source_order) > 1:
        passed = list(source_order) != sealed_sequence
        checks.append(_check("order_differs_from_source", passed,
                             "sealed order differs from the generator order" if passed
                             else "sealed order equals the generator order"))
    actions = [str(gold_by_id[record["request_id"]].get("gold_action"))
               for record in requests if record.get("request_id") in gold_by_id]
    longest = _longest_run(actions)
    checks.append(_check("bounded_same_action_runs", longest <= max_same_action_run,
                         f"longest run of one gold action is {longest} "
                         f"(limit {max_same_action_run})"))
    bad = [record.get("request_id") for record in requests
           if record.get("request_id") not in gold_by_id
           or gold_by_id[record["request_id"]].get("request_text_sha256")
           != sha256_text(str(record.get("request_text", "")))]
    checks.append(_check("gold_text_binding", not bad,
                         f"records whose gold binding hash does not match: {bad[:5]}" if bad
                         else "every request is bound to exactly one gold record by text hash"))
    same_ids = set(gold_by_id) == {record.get("request_id") for record in requests}
    checks.append(_check("gold_covers_requests", same_ids and len(gold_by_id) == len(gold),
                         "gold ids and request ids coincide" if same_ids
                         else "gold ids and request ids differ"))
    return checks


def resolve_topology_path(topology_id: str, spec: Mapping[str, Any] | Any,
                          explicit: Mapping[str, Path], catalogue_dir: Path) -> Path | None:
    """Locate the file of one catalogue topology, or ``None`` when unknown."""
    if topology_id in explicit:
        return explicit[topology_id]
    declared = spec.get("path") if isinstance(spec, Mapping) else None
    if not isinstance(declared, str) or not declared.strip():
        return None
    path = Path(declared)
    return path if path.is_absolute() else catalogue_dir / path


def load_topology_references(catalogue: Mapping[str, Mapping[str, Any]], *,
                             topology_files: Mapping[str, str | Path] | None = None,
                             catalogue_dir: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Hash every catalogue topology and check each file against its entry.

    A topology's file comes from ``topology_files`` or from the ``path`` of its
    catalogue entry, resolved relative to ``catalogue_dir`` (the working
    directory by default). Every catalogue entry must resolve: sealing a
    benchmark whose topologies cannot all be hashed is refused.
    """
    if not catalogue:
        raise SealRefusal(["the topology catalogue is empty"])
    explicit = {str(key): Path(value) for key, value in (topology_files or {}).items()}
    unknown = sorted(set(explicit) - set(catalogue))
    if unknown:
        raise SealRefusal([f"topology file supplied for {name!r}, which is not in the catalogue"
                           for name in unknown])
    base = Path(catalogue_dir) if catalogue_dir is not None else Path.cwd()
    references: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for topology_id in sorted(catalogue):
        spec = catalogue[topology_id]
        path = resolve_topology_path(topology_id, spec, explicit, base)
        if path is None:
            problems.append(
                f"no file for topology {topology_id!r}: pass --topology-file "
                f"{topology_id}=PATH or give its catalogue entry a 'path'")
            continue
        if not path.is_file():
            problems.append(f"topology file for {topology_id!r} not found: {path}")
            continue
        raw = path.read_bytes()
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            problems.append(f"topology {path} is not valid JSON: {exc}")
            continue
        if not isinstance(data, Mapping):
            problems.append(f"topology {path}: file must contain a JSON object")
            continue
        digest = sha256_bytes(raw)
        for field, observed, expected in (
            ("name", data.get("name"), topology_id),
            ("working_period", data.get("working_period"),
             spec.get("working_period") if isinstance(spec, Mapping) else None),
            ("communication_range", data.get("communication_range"),
             spec.get("communication_range") if isinstance(spec, Mapping) else None),
        ):
            if observed != expected:
                problems.append(f"topology {path}: {field} {observed!r} != {expected!r}")
        declared_sha = spec.get("sha256") if isinstance(spec, Mapping) else None
        if isinstance(declared_sha, str) and declared_sha != digest:
            problems.append(f"topology {path}: sha256 {digest} does not match the catalogue "
                            f"entry {declared_sha}")
        nodes = data.get("nodes")
        references[topology_id] = {
            "topology_id": topology_id,
            "path": str(path),
            "sha256": digest,
            "size_bytes": len(raw),
            "working_period": data.get("working_period"),
            "communication_range": data.get("communication_range"),
            "node_count": len(nodes) if isinstance(nodes, list) else None,
        }
    if problems:
        raise SealRefusal(problems)
    return references


def hash_prompt_files(prompt_files: Mapping[str, str | Path]) -> dict[str, dict[str, Any]]:
    if not prompt_files:
        raise SealRefusal(["at least one prompt file is required for the lock manifest"])
    hashes: dict[str, dict[str, Any]] = {}
    for name, path in sorted(prompt_files.items()):
        path = Path(path)
        if not path.is_file():
            raise SealRefusal([f"prompt file {name!r} not found: {path}"])
        hashes[name] = {"path": str(path), "sha256": sha256_file(path),
                        "size_bytes": path.stat().st_size}
    return hashes


def hash_source_archives(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    archives = []
    for path in paths:
        path = Path(path)
        if not path.is_file():
            raise SealRefusal([f"source archive not found: {path}"])
        archives.append({"path": str(path), "sha256": sha256_file(path),
                         "size_bytes": path.stat().st_size})
    return archives


def resolve_source_commit(project_root: str | Path | None,
                          explicit: str | None = None) -> dict[str, Any]:
    """Resolve the source commit from an explicit value or a git checkout."""
    if explicit is not None:
        if not explicit.strip():
            raise SealRefusal(["source commit must be a non-empty string"])
        return {"value": explicit.strip(), "source": "explicit", "dirty": None}
    if project_root is None:
        raise SealRefusal(["source commit unavailable: pass an explicit source commit or a "
                           "project root that is a git checkout"])
    try:
        head = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=30).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(project_root), "status", "--porcelain"],
            capture_output=True, text=True, check=True, timeout=30).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SealRefusal([f"source commit unavailable from git at {project_root} ({exc}); "
                           "pass an explicit source commit"]) from exc
    if not head:
        raise SealRefusal([f"git at {project_root} returned no HEAD commit"])
    return {"value": head, "source": "git", "dirty": bool(status.strip())}


def sealed_artifacts_present(output_dir: Path) -> list[str]:
    if not output_dir.exists():
        return []
    if not output_dir.is_dir():
        return [str(output_dir)]
    protected = set(SEALED_FILENAMES.values()) | {MANIFEST_FILENAME, MANIFEST_DIGEST_FILENAME}
    return sorted(entry.name for entry in output_dir.iterdir()
                  if entry.name in protected or "lock_manifest" in entry.name)


def _refuse_if_sealed(output_dir: Path) -> None:
    existing = sealed_artifacts_present(output_dir)
    if existing:
        raise SealRefusal([f"refusing to overwrite an existing sealed benchmark in "
                           f"{output_dir}: {existing}"])


def seal(*, reconciliation: Reconciliation, decisions: LoadedDocument,
         model_metadata: LoadedDocument, prompt_files: Mapping[str, str | Path],
         policy_version: str, output_dir: str | Path,
         source_commit: Mapping[str, Any],
         topology_files: Mapping[str, str | Path] | None = None,
         catalogue_dir: str | Path | None = None,
         source_archives: Sequence[str | Path] = (),
         shuffle_seed: int = DEFAULT_SHUFFLE_SEED,
         max_same_action_run: int = DEFAULT_MAX_SAME_ACTION_RUN) -> SealResult:
    output_dir = Path(output_dir)
    _refuse_if_sealed(output_dir)
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise SealRefusal(["policy_version must be a non-empty string"])
    metadata_errors = validate_model_metadata(model_metadata.data)
    if metadata_errors:
        raise SealRefusal([f"model metadata: {error}" for error in metadata_errors])
    for key in ("value", "source"):
        if not isinstance(source_commit.get(key), str) or not source_commit[key].strip():
            raise SealRefusal([f"source_commit.{key} must be a non-empty string"])
    final_set = apply_decisions(reconciliation, decisions.data, catalogue=reconciliation.catalogue)
    topologies = load_topology_references(reconciliation.catalogue,
                                          topology_files=topology_files,
                                          catalogue_dir=catalogue_dir)
    prompts = hash_prompt_files(prompt_files)
    archives = hash_source_archives(source_archives)
    records = build_sealed_records(final_set, shuffle_seed=shuffle_seed,
                                   id_prefix=sealed_id_prefix(reconciliation.contract_version))
    identifiers = [group.semantic_group_id for group in final_set.groups]
    identifiers.extend(item["request_id"] for group in final_set.groups
                       for item in group.paraphrases)
    checks = check_request_leakage(records.requests, records.gold,
                                   source_identifiers=identifiers,
                                   source_order=records.source_order,
                                   max_same_action_run=max_same_action_run)
    failed = [check for check in checks if not check["passed"]]
    if failed:
        raise SealRefusal([f"leakage check {check['check']} failed: {check['detail']}"
                           for check in failed])
    output_dir.mkdir(parents=True, exist_ok=True)
    _refuse_if_sealed(output_dir)
    paths = {key: output_dir / name for key, name in SEALED_FILENAMES.items()}
    contents = {
        "requests_jsonl": jsonl_text(records.requests),
        "gold_jsonl": jsonl_text(records.gold),
        "worksheet_json": canonical_json(reconciliation.worksheet()),
        "human_decisions_copy": canonical_json(decisions.data),
    }
    record_counts = {"requests_jsonl": len(records.requests), "gold_jsonl": len(records.gold)}
    for key, text in contents.items():
        write_text_exclusive(paths[key], text)
    outputs = {
        key: {
            "path": SEALED_FILENAMES[key],
            "sha256": sha256_text(contents[key]),
            "size_bytes": len(contents[key].encode("utf-8")),
            "records": record_counts.get(key),
        }
        for key in SEALED_FILENAMES
    }
    batches = reconciliation.batches
    per_batch = {batch.batch_id: sum(1 for group in final_set.groups
                                     if group.batch_id == batch.batch_id)
                 for batch in batches}
    source_defects = []
    for label, document in (("benchmark_a", batches[0].benchmark),
                            ("review_of_a", batches[0].review),
                            ("benchmark_b", batches[1].benchmark),
                            ("review_of_b", batches[1].review),
                            ("human_decisions", decisions),
                            ("model_metadata", model_metadata)):
        source_defects.extend({"document": label, **defect.to_dict()}
                              for defect in document.defects)
    manifest = {
        "manifest_format": MANIFEST_FORMAT,
        "benchmark_version": reconciliation.contract_version,
        "contract_version": reconciliation.contract_version,
        "sealed_at_utc": utc_now_iso(),
        "pipeline": {"package": "frozen_test_v2", "version": PIPELINE_VERSION,
                     "python": platform.python_version()},
        "policy_version": policy_version,
        "source_commit": dict(source_commit),
        "source_archives": archives,
        "model_metadata": {
            "declared": model_metadata.data,
            "roles": {
                "model_a": [f"generator of {batches[0].batch_id}",
                            f"blind reviewer of {batches[1].batch_id}"],
                "model_b": [f"generator of {batches[1].batch_id}",
                            f"blind reviewer of {batches[0].batch_id}"],
            },
        },
        "prompt_hashes": prompts,
        "topologies": topologies,
        "topology_count": len(topologies),
        "topology_catalogue": reconciliation.catalogue,
        "shuffle_seed": shuffle_seed,
        "leakage_policy": {"max_same_action_run": max_same_action_run},
        "inputs": {
            "benchmark_a": batches[0].benchmark.to_manifest_entry(),
            "review_of_a": batches[0].review.to_manifest_entry(),
            "benchmark_b": batches[1].benchmark.to_manifest_entry(),
            "review_of_b": batches[1].review.to_manifest_entry(),
            "human_decisions": decisions.to_manifest_entry(),
            "model_metadata": model_metadata.to_manifest_entry(),
        },
        "source_defects": source_defects,
        "reconciliation_summary": reconciliation.summary(),
        "human_decisions": {
            "decided_by": final_set.decided_by,
            "decided_at": final_set.decided_at,
            "decisions_applied": final_set.decisions_applied,
            "excluded_groups": final_set.excluded,
        },
        "quotas": {"expected": final_set.quotas_expected,
                   "observed": final_set.quotas_observed,
                   "source": final_set.quota_source},
        "counts": {
            "groups": len(final_set.groups),
            "requests": len(records.requests),
            "per_action": {action: final_set.quotas_observed[action] for action in ACTIONS},
            "per_batch": per_batch,
        },
        "leakage_checks": checks,
        "outputs": outputs,
    }
    manifest_text = canonical_json(manifest)
    manifest_path = output_dir / MANIFEST_FILENAME
    digest_path = output_dir / MANIFEST_DIGEST_FILENAME
    write_text_exclusive(manifest_path, manifest_text)
    write_text_exclusive(digest_path, f"{sha256_text(manifest_text)}  {MANIFEST_FILENAME}\n")
    paths["manifest"] = manifest_path
    paths["manifest_digest"] = digest_path
    return SealResult(output_dir=output_dir, manifest=manifest, paths=paths)


def verify_sealed_directory(output_dir: str | Path) -> dict[str, Any]:
    """Recompute hashes and leakage checks for a sealed directory."""
    output_dir = Path(output_dir)
    failures: list[str] = []
    manifest_path = output_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return {"valid": False, "failures": [f"missing manifest {manifest_path}"]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest_path = output_dir / MANIFEST_DIGEST_FILENAME
    if digest_path.is_file():
        recorded = digest_path.read_text(encoding="utf-8").split()[0]
        if recorded != sha256_file(manifest_path):
            failures.append("manifest digest sidecar does not match the manifest")
    else:
        failures.append(f"missing manifest digest {digest_path}")
    for key, entry in manifest.get("outputs", {}).items():
        path = output_dir / entry["path"]
        actual = sha256_file(path) if path.is_file() else "MISSING"
        if actual != entry["sha256"]:
            failures.append(f"{key}: expected {entry['sha256']} got {actual}")
    requests_path = output_dir / SEALED_FILENAMES["requests_jsonl"]
    gold_path = output_dir / SEALED_FILENAMES["gold_jsonl"]
    if requests_path.is_file() and gold_path.is_file():
        requests = read_jsonl(requests_path)
        gold = read_jsonl(gold_path)
        identifiers = [record.get("source_request_id") for record in gold]
        identifiers.extend(record.get("semantic_group_id") for record in gold)
        limit = manifest.get("leakage_policy", {}).get("max_same_action_run",
                                                        DEFAULT_MAX_SAME_ACTION_RUN)
        for check in check_request_leakage(requests, gold, source_identifiers=identifiers,
                                           max_same_action_run=limit):
            if not check["passed"]:
                failures.append(f"leakage check {check['check']}: {check['detail']}")
    return {"valid": not failures, "failures": failures,
            "manifest_format": manifest.get("manifest_format")}

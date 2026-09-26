#!/usr/bin/env python3
"""Package the supplementary archive for submission.

AAMAS accepts one zip of at most 25 MB, and reviewers are not obliged to open
it, so the archive is for reproduction rather than for argument: everything
needed to re-derive a number in the paper, and nothing that only repeats it.

What goes in, and why:

  * the sealed benchmark and its gold labels, so the evaluation can be re-run;
  * both evaluation locks, so the pipeline that produced each set of results can
    be identified by hash rather than by trust;
  * every ledger, including the ones from before the pipeline repair, because a
    before/after claim that ships only the "after" is not checkable;
  * the analysis and figure-data code, so every table and figure in the paper
    can be regenerated from the ledgers;
  * the pipeline sources and their tests.

What stays out: build outputs, caches, virtual environments, the paper's own
PDF, and anything that would identify the authors. The script prints what it
excluded on those grounds so the decision is visible rather than implicit.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INCLUDE = (
    "benchmarks/frozen_test_v3/**/*",
    "benchmarks/topologies/frozen_test_v3_llm_catalogue.json",
    "benchmarks/evaluation_lock_v3.json",
    "benchmarks/evaluation_lock_v3_1.json",
    "benchmarks/frozen_test_v3_authoring_lock.json",
    "results/frozen_test_v3/*.jsonl",
    "results/frozen_test_v3/**/summary.json",
    "results/frozen_test_v3/**/summary.md",
    "results/frozen_test_v3/**/seed_variance.*",
    "results/frozen_test_v3/*.json",
    "results/topology_scaling/**/*",
    "results/validator_mutation/*",
    "results/frozen_test_v3/*.device.json",
    # The audit and analysis directories are versioned by campaign, so the
    # glob has to allow the suffix; "audit/*" alone silently shipped none of
    # them.
    "results/frozen_test_v3/audit*/*",
    "results/frozen_test_v3/analysis*/*",
    # Ledgers a provider outage ruined, kept because two sections of the paper
    # describe those outages. The README in that directory says plainly that
    # they measure nothing, so shipping them cannot be mistaken for a result.
    "results/frozen_test_v3/quarantine/*",
    "benchmarks/frozen_test_v3/model_metadata.json",
    "benchmarks/frozen_test_v3/generation_provenance.json",
    "src/**/*.py",
    # The published ANEX sources the agent wraps. Without them the released
    # agent imports a module that is not there, which a clean clone shows at
    # once: seventeen test modules fail to collect on `No module named ANEX`.
    # Only the four files the import bridge actually loads go in --- the rest
    # of that tree is other papers' experiments, and shipping it would mean
    # shipping their bylines too.
    "source/ANEX/ANEX.py",
    # The mutation test validates against this second legacy implementation,
    # so it is part of what "the tests pass" means here.
    "source/ANEX/EDAS_validation.py",
    "source/libs/__init__.py",
    "source/libs/gentopo.py",
    "source/libs/node.py",
    # Fixtures the tests read by path: a 30-node topology and the two
    # development request sets that predate the sealed benchmark.
    "network_30_seed7.json",
    "benchmarks/requests_dev.jsonl",
    "benchmarks/requests_test.jsonl",
    # The pre-v3 ledger the policy-replay test replays. It is evidence for the
    # retrospective ablation, not for any number in the paper, but a test that
    # cannot find its input is indistinguishable from a broken artefact.
    "results/phi4_reasoning_test_locked_v1_wsl.jsonl",
    "benchmarks/schema.json",
    "scripts/*.py",
    "tests/*.py",
    "docs/**/*.md",
    "docs/prompts/**/*.txt",
    "pyproject.toml",
    # The index a reviewer opens first: what each number in the paper is
    # derived from, and the one command that checks the artefact runs.
    "README.md",
    # The figure data, so a reader who wants the per-item lists behind a figure
    # --- which requests the vocabulary test put in each group, which fields
    # the model determined from the sentence --- has the file the paper names
    # rather than a re-derivation.
    "paper/aamas2027/figure_data/*.json",
    # No PDF of the paper goes in, in either build. AAMAS allows a supplement
    # to carry experimental detail and proofs and does not allow it to carry an
    # extended or revised version of the submission, and `main-full.pdf` is
    # exactly that: the same manuscript with its \iffull passages restored.
    # What the submission cited it for --- the worked example's schedule and
    # the paired-difference table --- is in the figure data and the analysis
    # summaries, which are here.
)

EXCLUDE = (
    "**/__pycache__/**", "**/*.pyc", "**/.venv/**", "**/.git/**",
    "**/node_modules/**", "**/*.zip", "**/.pytest_cache/**",
)

# Paths that would identify the authors or that belong to a different project.
WITHHELD = (
    "**/*.docx", "**/Research_Plan*", "**/*_source.zip",
)

# The absolute path of the working copy carries a username. It appears in files
# that recorded where something was read from.
IDENTIFYING = re.compile(r"/home/[A-Za-z0-9_.-]+/projects/[A-Za-z0-9_.-]+")
REDACTED = "<repository>"
# The legacy sources carry their programmer's name and institution in a
# docstring. The institution is the one a reviewer would match against the
# submission, so the line is replaced rather than the file withheld: the code
# below it is what the agent runs, unaltered.
BYLINE = re.compile(r"Programmed by the ANEX authors (byline withheld for double-blind review)
BYLINE_REDACTED = ("Programmed by the ANEX authors (byline withheld for double-blind review)
                   "(byline withheld for double-blind review)")
REDACTABLE_SUFFIXES = {".json", ".jsonl", ".md", ".txt", ".py", ".tex", ".bib",
                       ".toml", ".cfg", ".yml", ".yaml"}
LOCKS = ("benchmarks/evaluation_lock_v3.json",
         "benchmarks/evaluation_lock_v3_1.json",
         "benchmarks/frozen_test_v3_authoring_lock.json")


def hashed_paths(root: Path) -> set[str]:
    """Every file whose SHA-256 a lock publishes. These may not be altered."""
    covered: set[str] = set()
    for name in LOCKS:
        lock = root / name
        if lock.is_file():
            data = json.loads(lock.read_text(encoding="utf-8"))
            covered.update((data.get("sha256") or {}).keys())
    return covered


def matches(path: str, patterns) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def collect(root: Path) -> tuple[list[Path], list[str]]:
    seen: dict[str, Path] = {}
    withheld: list[str] = []
    for pattern in INCLUDE:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if matches(relative, EXCLUDE):
                continue
            if matches(relative, WITHHELD):
                withheld.append(relative)
                continue
            seen[relative] = path
    return [seen[key] for key in sorted(seen)], withheld


def anonymise(root: Path, files: list[Path], covered: set[str]):
    """Split the members into those safe to ship, to redact, and to withhold."""
    plain: list[tuple[str, bytes]] = []
    redacted: list[str] = []
    withheld: list[str] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        if path.suffix.lower() not in REDACTABLE_SUFFIXES:
            plain.append((relative, data))
            continue
        body = data.decode("utf-8", "replace")
        if not (IDENTIFYING.search(body) or BYLINE.search(body)):
            plain.append((relative, data))
            continue
        if relative in covered:
            # Its hash is published; altering it would look like tampering.
            withheld.append(relative)
            continue
        redacted.append(relative)
        cleaned = BYLINE.sub(BYLINE_REDACTED, IDENTIFYING.sub(REDACTED, body))
        plain.append((relative, cleaned.encode("utf-8")))
    return plain, redacted, withheld


def readme(redacted: list[str], withheld: list[str]) -> str:
    lines = [
        "Supplementary archive, prepared for double-blind review.",
        "",
        "Handling of author-identifying content:",
        "",
        "REDACTED -- the absolute path of the working copy contained a username and",
        "has been replaced by <repository>; in the legacy scheduler sources a docstring",
        "naming its programmer and institution has been replaced by a neutral line. No",
        "lock publishes a hash of these files, so rewriting them changes nothing a",
        "reader can verify, and no line of executed code was touched.",
    ]
    lines += [f"  {name}" for name in redacted] or ["  (none)"]
    lines += [
        "",
        "WITHHELD -- these files also carried that path, but a lock publishes their",
        "SHA-256. Editing them would produce a member that does not match its",
        "recorded hash, which is a worse thing to hand a reviewer than an absent",
        "file, so they are omitted here and will be included unaltered in the",
        "archival release on acceptance. Their hashes remain in the locks and the",
        "rest of the manifest verifies without them.",
    ]
    lines += [f"  {name}" for name in withheld] or ["  (none)"]
    lines += ["", "Nothing else was altered."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="supplementary.zip")
    parser.add_argument("--limit-mb", type=float, default=25.0)
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    if out.exists():
        print(json.dumps({"status": "refused", "problems": [
            f"refusing to overwrite an existing archive: {out}"]}, indent=2))
        return 1

    files, withheld = collect(root)
    if not files:
        print(json.dumps({"status": "refused",
                          "problems": ["no files matched"]}, indent=2))
        return 1

    covered = hashed_paths(root)
    members, redacted, blinded = anonymise(root, files, covered)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in members:
            archive.writestr(name, data)
        archive.writestr("README-anonymity.txt", readme(redacted, blinded))

    size_mb = out.stat().st_size / 1_000_000
    biggest = sorted((root / name for name, _ in members),
                     key=lambda p: p.stat().st_size, reverse=True)[:5]
    report = {
        "status": "packaged" if size_mb <= args.limit_mb else "OVER_LIMIT",
        "archive": str(out.relative_to(root)),
        "files": len(members) + 1,
        "redacted_for_anonymity": redacted,
        "withheld_because_their_hash_is_published": blinded,
        "size_mb": round(size_mb, 2),
        "limit_mb": args.limit_mb,
        "withheld_for_anonymity": withheld,
        "largest_members": [
            {"path": p.relative_to(root).as_posix(),
             "mb": round(p.stat().st_size / 1_000_000, 2)} for p in biggest],
    }
    print(json.dumps(report, indent=2))
    return 0 if size_mb <= args.limit_mb else 1


if __name__ == "__main__":
    raise SystemExit(main())

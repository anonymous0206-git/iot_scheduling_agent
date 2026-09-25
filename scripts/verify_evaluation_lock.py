"""Verify files frozen by an Agentic ANEX evaluation lock."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def verify(lock_path: Path, project_root: Path) -> list[dict[str, str]]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    failures = []
    for relative, expected in lock["sha256"].items():
        path = project_root / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "MISSING"
        if actual != expected:
            failures.append({"path": relative, "expected": expected, "actual": actual})
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", default="benchmarks/evaluation_lock_v1.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    lock_path = Path(args.lock)
    if not lock_path.is_absolute():
        lock_path = root / lock_path
    failures = verify(lock_path, root)
    print(json.dumps({"valid": not failures, "failures": failures}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

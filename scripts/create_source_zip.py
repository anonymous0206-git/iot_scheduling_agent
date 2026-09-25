"""Create a deterministic source-only Agentic ANEX ZIP archive."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

SOURCE_ROOTS = (
    "README.md", "pyproject.toml", "uv.lock", "generate_topo.py",
    "src", "source", "tests", "docs", "scripts", "benchmarks",
    "rule-based_workflow",
)
EXCLUDED_PARTS = frozenset({".venv", ".pytest_cache", "__pycache__", ".git", ".codex", ".agents"})
EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo"})


def source_files(project_root: Path) -> tuple[Path, ...]:
    selected: list[Path] = []
    for name in SOURCE_ROOTS:
        candidate = project_root / name
        paths = candidate.rglob("*") if candidate.is_dir() else (candidate,)
        for path in paths:
            relative = path.relative_to(project_root)
            if path.is_file() and not EXCLUDED_PARTS.intersection(relative.parts) \
                    and not any(part.endswith(".egg-info") for part in relative.parts) \
                    and path.suffix not in EXCLUDED_SUFFIXES:
                selected.append(path)
    return tuple(sorted(set(selected), key=lambda path: path.as_posix()))


def create_source_zip(project_root: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for path in source_files(project_root):
            relative = path.relative_to(project_root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    create_source_zip(root, Path(args.output).resolve())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Render the delivered Frozen Test v3 prompts from the locked templates.

The templates in ``docs/prompts`` carry role placeholders. Delivery needs one
concrete file per model, and the seal step hashes exactly what each model
received, so the rendering must be mechanical and reproducible rather than
hand-edited.

Rendered files:

  frozen_test_v3_specification.txt   sections 1 to 4 of the generation prompt
  frozen_test_v3_generator_A.txt     generation prompt for generator A
  frozen_test_v3_generator_B.txt     generation prompt for generator B
  frozen_test_v3_reviewer_batch_A.txt  adjudication prompt for blind Batch A
  frozen_test_v3_reviewer_batch_B.txt  adjudication prompt for blind Batch B

Each reviewer file embeds the specification, so one file plus the blind batch
is everything the adjudicator receives. The reviewer of Batch A is the model
that did **not** generate Batch A.

Outputs are write-once and every rendered file is checked for leftover
placeholders.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

GENERATOR_TEMPLATE = "docs/prompts/frozen_test_v3_generator_prompt.txt"
REVIEWER_TEMPLATE = "docs/prompts/frozen_test_v3_reviewer_prompt.txt"
SECTION_RULE = "=" * 50
SPECIFICATION_START = "1. PAPER-1 SCIENTIFIC SCOPE"
SPECIFICATION_END = "5. GENERATION TASK"
PLACEHOLDER = re.compile(r"\{[A-Z_]+\}")
SPECIFICATION_HEADER = (
    f"{SECTION_RULE}\nSPECIFICATION\n{SECTION_RULE}\n\n"
    "The sections below are the scientific scope, action labels, topology\n"
    "catalogue, and configuration contract given to the generators. Judge the\n"
    "attached batch against them and nothing else.\n\n")


class RenderError(ValueError):
    """A template cannot be rendered into a deliverable prompt."""


def extract_specification(generator_template: str) -> str:
    """Return sections 1 to 4 of the generation prompt, which carry no roles."""
    lines = generator_template.splitlines()
    try:
        start = lines.index(SPECIFICATION_START)
        end = lines.index(SPECIFICATION_END)
    except ValueError as exc:
        raise RenderError(f"generator template lacks a section marker: {exc}") from exc
    if start == 0 or lines[start - 1] != SECTION_RULE or lines[end - 1] != SECTION_RULE:
        raise RenderError("section markers are not preceded by a section rule")
    specification = "\n".join(lines[start - 1:end - 1]).rstrip() + "\n"
    leftover = PLACEHOLDER.findall(specification)
    if leftover:
        raise RenderError(f"the specification sections carry role placeholders: {leftover}")
    return specification


def render(text: str, substitutions: dict[str, str]) -> str:
    """Substitute placeholders literally; braces elsewhere are left untouched."""
    for placeholder, value in substitutions.items():
        text = text.replace(placeholder, value)
    leftover = PLACEHOLDER.findall(text)
    if leftover:
        raise RenderError(f"unsubstituted placeholders remain: {sorted(set(leftover))}")
    return text


def render_all(project_root: str | Path) -> dict[str, str]:
    """Return ``{filename: content}`` for every deliverable prompt."""
    root = Path(project_root)
    generator_template = (root / GENERATOR_TEMPLATE).read_text(encoding="utf-8")
    reviewer_template = (root / REVIEWER_TEMPLATE).read_text(encoding="utf-8")
    specification = extract_specification(generator_template)
    rendered = {"frozen_test_v3_specification.txt": specification}
    for role in ("A", "B"):
        rendered[f"frozen_test_v3_generator_{role}.txt"] = render(
            generator_template, {"{ROLE_LOWER}": role.lower(), "{ROLE}": role})
        reviewer = render(reviewer_template,
                          {"{BATCH_LOWER}": role.lower(), "{BATCH}": role})
        rendered[f"frozen_test_v3_reviewer_batch_{role}.txt"] = (
            reviewer.rstrip() + "\n\n" + SPECIFICATION_HEADER + specification)
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", default="docs/prompts/delivered")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    try:
        rendered = render_all(args.project_root)
    except (OSError, RenderError) as exc:
        print(json.dumps({"status": "refused", "problems": [str(exc)]}, indent=2))
        return 1
    existing = [name for name in rendered if (output_dir / name).exists()]
    if existing:
        print(json.dumps({"status": "refused", "problems": [
            f"refusing to overwrite {output_dir / name}" for name in existing]}, indent=2))
        return 1
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, content in rendered.items():
        path = output_dir / name
        with open(path, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        files[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "bytes": path.stat().st_size}
    print(json.dumps({
        "status": "rendered",
        "output_dir": str(output_dir),
        "files": files,
        "delivery": {
            "frozen_test_v3_generator_A.txt": "generator A",
            "frozen_test_v3_generator_B.txt": "generator B",
            "frozen_test_v3_reviewer_batch_A.txt": "the model that did not generate Batch A",
            "frozen_test_v3_reviewer_batch_B.txt": "the model that did not generate Batch B",
            "frozen_test_v3_specification.txt": "reference copy; already embedded in both "
                                                "reviewer prompts",
        },
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

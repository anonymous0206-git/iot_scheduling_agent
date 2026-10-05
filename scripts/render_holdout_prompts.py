#!/usr/bin/env python3
"""Render the authoring and adjudication prompts for the post-repair holdout.

The holdout exists because the sealed benchmark was reused: the pipeline was
repaired after failures on it were seen, so nothing in it is held out. The
remedy is a batch authored after the pipeline stopped moving, which
`benchmarks/evaluation_lock_v4_holdout.json` records the moment of.

The prompt is the released Frozen Test v3 generator prompt with the batch size
changed and nothing else. That is the point: a holdout whose specification
differs from the one it is compared against measures a different thing, so the
scope, the action definitions, the contract, the catalogue, the precedence
rules and the output schema are carried across byte for byte, and the
substitutions below are the complete list of what is not.

  size            18 groups per author rather than 36, so two authors produce
                  36 groups and 72 requests. The size comes from
                  `results/frozen_test_v3/holdout_sizing/`: at this size the
                  headline ablation has power 0.44, which is why the holdout is
                  addressed at the mechanism --- a count, not an estimate ---
                  rather than at the interval.

  quotas          halved to integers, keeping the action mix and the 50 per
                  cent unsupported share: 6 EXECUTE, 1 CLARIFY, 2 REJECT and 9
                  UNSUPPORTED groups per author.

  composition     the compositional-phrasing floor rises from a third to five
                  of the nine unsupported groups, because the mechanism the
                  holdout tests is measured on requests that do not name the
                  capability, and a floor set by proportion alone would leave
                  that cell too small to read.

  identifiers     `h4-` rather than `v3-`, and the candidate version string
                  changes with it, so a holdout file can never be mistaken for
                  a frozen-test-v3 file by a tool that reads either.

Two kinds of leakage the rendering must not introduce, and does not: the prompt
names no file, path, policy or failure of the system under test, and it says
nothing about an earlier benchmark. An author who has read this prompt knows
the scientific scope and nothing about the implementation.

Delivery is two files to two sessions that have not seen this repository, and
the adjudicator of each batch is the model that did not write it.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

GENERATOR_TEMPLATE = "docs/prompts/frozen_test_v3_generator_prompt.txt"
REVIEWER_TEMPLATE = "docs/prompts/frozen_test_v3_reviewer_prompt.txt"
SECTION_RULE = "=" * 50
SPECIFICATION_START = "1. PAPER-1 SCIENTIFIC SCOPE"
SPECIFICATION_END = "5. GENERATION TASK"
SPECIFICATION_HEADER = (
    f"{SECTION_RULE}\nSPECIFICATION\n{SECTION_RULE}\n\n"
    "The definitions below are the same ones the generator received.\n\n")

# (what it says now, what the holdout says instead). Every entry is a size or
# an identifier; none changes a definition, a rule of precedence, or the
# contract. A substitution that does not fire is an error, not a no-op.
SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    ("Create exactly 36 independent semantic groups.",
     "Create exactly 18 independent semantic groups."),
    ("""| protocol_category                | groups | gold action |
|----------------------------------|-------:|-------------|
| supported_default                |      4 | EXECUTE     |
| supported_configured             |      4 | EXECUTE     |
| supported_latency_target         |      3 | EXECUTE     |
| missing_information              |      3 | CLARIFY     |
| invalid_parameter                |      4 | REJECT      |
| unsupported_energy               |      4 | UNSUPPORTED |
| unsupported_digital_twin_or_sync |      4 | UNSUPPORTED |
| unsupported_periodic             |      3 | UNSUPPORTED |
| unsupported_topology_adaptation  |      3 | UNSUPPORTED |
| unsupported_other_objective      |      4 | UNSUPPORTED |

That is 11 EXECUTE, 3 CLARIFY, 4 REJECT, and 18 UNSUPPORTED groups.""",
     """| protocol_category                | groups | gold action |
|----------------------------------|-------:|-------------|
| supported_default                |      2 | EXECUTE     |
| supported_configured             |      2 | EXECUTE     |
| supported_latency_target         |      2 | EXECUTE     |
| missing_information              |      1 | CLARIFY     |
| invalid_parameter                |      2 | REJECT      |
| unsupported_energy               |      2 | UNSUPPORTED |
| unsupported_digital_twin_or_sync |      2 | UNSUPPORTED |
| unsupported_periodic             |      2 | UNSUPPORTED |
| unsupported_topology_adaptation  |      1 | UNSUPPORTED |
| unsupported_other_objective      |      2 | UNSUPPORTED |

That is 6 EXECUTE, 1 CLARIFY, 2 REJECT, and 9 UNSUPPORTED groups."""),
    ("Therefore, the batch must contain exactly 72 individual requests.",
     "Therefore, the batch must contain exactly 36 individual requests."),
    ("""Topology use: the EXECUTE groups must name at least four different
catalogue topologies; the UNSUPPORTED groups at least three; the REJECT
groups at least two.""",
     """Topology use: the EXECUTE groups must name at least four different
catalogue topologies; the UNSUPPORTED groups at least three; the two
REJECT groups must name different topologies."""),
    ("""missing_information (CLARIFY) must include:
- a missing topology_id;
- an ambiguous topology selection (two ids for one run, or a description
  without an id);
- an ambiguity between two materially different configurations.""",
     """missing_information (CLARIFY), the single group, must be an ambiguous
topology selection: two ids for one run, or a description without an id."""),
    ("""invalid_parameter (REJECT) must include at least:
- a topology_id that is not in the catalogue;
- an interference_ratio other than 1.0;
- a working_period or communication_range inconsistent with the selected
  topology (for example 18.0 with topo100_seed0);
and one more kind chosen from: zero or negative channel count, non-integer
channel count, invalid collision model, invalid latency target,
contradictory explicit supported fields.""",
     """invalid_parameter (REJECT), two groups, must be one of each:
- a topology_id that is not in the catalogue;
- a working_period or communication_range inconsistent with the selected
  topology (for example 18.0 with topo100_seed0)."""),
    ("""Across the 18 UNSUPPORTED groups:
- at least 6 groups must express the capability compositionally, without
  using the canonical category name (no "Digital Twin", "energy-aware",
  "periodic", "adaptation" wording);
- at least 3 groups must be mixed requests that also contain a fully
  supported schedule;
- at least one group must contain a supported schedule whose configuration
  would otherwise be REJECT, to exercise precedence rule 1.""",
     """Across the 9 UNSUPPORTED groups:
- at least 5 groups must express the capability compositionally, without
  using the canonical category name (no "Digital Twin", "energy-aware",
  "periodic", "adaptation" wording);
- at least 2 groups must be mixed requests that also contain a fully
  supported schedule;
- at least one group must contain a supported schedule whose configuration
  would otherwise be REJECT, to exercise precedence rule 1."""),
    ('"benchmark_version": "frozen-test-v3-candidate",',
     '"benchmark_version": "holdout-v4-candidate",'),
    ('"semantic_group_id": "v3-{ROLE_LOWER}-001",',
     '"semantic_group_id": "h4-{ROLE_LOWER}-001",'),
    ('"request_id": "v3-{ROLE_LOWER}-001-p1"',
     '"request_id": "h4-{ROLE_LOWER}-001-p1"'),
    ('"request_id": "v3-{ROLE_LOWER}-001-p2"',
     '"request_id": "h4-{ROLE_LOWER}-001-p2"'),
    ("""  "self_check": {
    "group_count": 36,
    "item_count": 72,
    "execute_groups": 11,
    "clarify_groups": 3,
    "reject_groups": 4,
    "unsupported_groups": 18,
    "protocol_category_counts": {
      "supported_default": 4,
      "supported_configured": 4,
      "supported_latency_target": 3,
      "missing_information": 3,
      "invalid_parameter": 4,
      "unsupported_energy": 4,
      "unsupported_digital_twin_or_sync": 4,
      "unsupported_periodic": 3,
      "unsupported_topology_adaptation": 3,
      "unsupported_other_objective": 4
    }
  }""",
     """  "self_check": {
    "group_count": 18,
    "item_count": 36,
    "execute_groups": 6,
    "clarify_groups": 1,
    "reject_groups": 2,
    "unsupported_groups": 9,
    "protocol_category_counts": {
      "supported_default": 2,
      "supported_configured": 2,
      "supported_latency_target": 2,
      "missing_information": 1,
      "invalid_parameter": 2,
      "unsupported_energy": 2,
      "unsupported_digital_twin_or_sync": 2,
      "unsupported_periodic": 2,
      "unsupported_topology_adaptation": 1,
      "unsupported_other_objective": 2
    }
  }"""),
    ("""- exactly 36 groups;
- exactly 72 requests;
- the protocol_category counts above, and 11 / 3 / 4 / 18 groups per
  action;""",
     """- exactly 18 groups;
- exactly 36 requests;
- the protocol_category counts above, and 6 / 1 / 2 / 9 groups per
  action;"""),
)

REVIEWER_SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    ('"semantic_group_id": "v3-{BATCH_LOWER}-001",',
     '"semantic_group_id": "h4-{BATCH_LOWER}-001",'),
    ('"reviewed_batch": "frontier-model-{BATCH_LOWER}",',
     '"reviewed_batch": "holdout-model-{BATCH_LOWER}",'),
)


def substitute(text: str, pairs: tuple[tuple[str, str], ...], where: str) -> str:
    for old, new in pairs:
        if old not in text:
            raise SystemExit(f"{where}: the template no longer contains:\n{old[:120]}")
        text = text.replace(old, new, 1)
    return text


def specification_of(prompt: str) -> str:
    """Sections 1 to 4, which the adjudicator needs and the generator had."""
    lines = prompt.splitlines()
    start = lines.index(SPECIFICATION_START)
    end = lines.index(SPECIFICATION_END)
    while lines[start - 1].startswith("="):
        start -= 1
    while lines[end - 1].startswith("=") or not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[start:end]).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", default="docs/prompts/holdout_v4")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()

    root = Path(args.project_root)
    template = (root / GENERATOR_TEMPLATE).read_text(encoding="utf-8")
    reviewer_template = (root / REVIEWER_TEMPLATE).read_text(encoding="utf-8")
    holdout = substitute(template, SUBSTITUTIONS, GENERATOR_TEMPLATE)
    reviewer = substitute(reviewer_template, REVIEWER_SUBSTITUTIONS, REVIEWER_TEMPLATE)
    specification = specification_of(holdout)

    out = root / args.output_dir
    written: dict[str, str] = {}
    files = {"holdout_v4_specification.txt": specification}
    for role in ("A", "B"):
        files[f"holdout_v4_generator_{role}.txt"] = holdout.replace(
            "{ROLE_LOWER}", role.lower()).replace("{ROLE}", role)
        files[f"holdout_v4_reviewer_batch_{role}.txt"] = (
            reviewer.replace("{BATCH_LOWER}", role.lower()).replace("{BATCH}", role).rstrip()
            + "\n\n" + SPECIFICATION_HEADER + specification)

    existing = [name for name in files if (out / name).exists()]
    if existing:
        print(f"refusing to overwrite: {existing}")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        if "{" in text and "}" in text and ("{ROLE" in text or "{BATCH" in text):
            raise SystemExit(f"{name}: a placeholder survived rendering")
        with open(out / name, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        written[name] = hashlib.sha256(text.encode("utf-8")).hexdigest()

    print(f"rendered into {out}")
    for name, digest in written.items():
        print(f"  {digest[:16]}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

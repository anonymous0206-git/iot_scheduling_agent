"""Replay scope policies over locked outputs without invoking models or tools."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentic_anex.policy_replay import replay_files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite replay artifact: {output}")
    artifact = replay_files(Path(args.benchmark), Path(args.raw))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

"""Export one immutable experiment record as a standalone trace artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite trace artifact: {output}")
    matches = []
    for line in Path(args.raw).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("request_id") == args.request_id and record.get("model") == args.model:
            matches.append(record)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one matching record, found {len(matches)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(matches[0], indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

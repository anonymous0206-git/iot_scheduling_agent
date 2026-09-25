"""Export a validation certificate from one immutable experiment record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentic_anex.schemas import ValidationReport
from agentic_anex.validator import validation_certificate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite certificate: {output}")
    matches = []
    for line in Path(args.raw).read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if record.get("request_id") == args.request_id and record.get("model") == args.model:
                matches.append(record)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one matching record, found {len(matches)}")
    validation = matches[0].get("validation")
    if validation is None:
        raise ValueError("matching record has no validation report")
    certificate = validation_certificate(ValidationReport.from_dict(validation))
    artifact = {
        "artifact_format": "agentic_anex.locked_record_certificate.v1",
        "source": {"raw": args.raw, "request_id": args.request_id, "model": args.model},
        "certificate": certificate,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

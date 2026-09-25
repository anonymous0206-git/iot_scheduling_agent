#!/usr/bin/env python3
"""Generate paper-table CSV summaries from the immutable raw JSONL ledger."""

from __future__ import annotations

import argparse

from agentic_anex.experiments import generate_summary_csv, load_experiment_records


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize raw Paper 1 experiments")
    parser.add_argument("--raw", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--overwrite-summary", action="store_true",
                        help="May overwrite derived CSV only; never modifies raw JSONL")
    args = parser.parse_args()
    generate_summary_csv(
        load_experiment_records(args.raw), args.output,
        overwrite=args.overwrite_summary,
    )


if __name__ == "__main__":
    main()

"""Frozen Test v2 reconciliation and sealing pipeline.

The package joins two independently generated benchmark batches with their
blind cross-reviews, classifies every semantic group, exports a
human-adjudication worksheet, applies recorded human decisions, and seals the
result into a target-facing requests file, a gold-only labels file, and a lock
manifest.

Boundary: this package never imports ``agentic_anex`` and never invokes Phi4,
ANEX, scope policy v2, or the schedule validator. Every check it performs is a
static, offline restatement of the sealed benchmark contract.
"""

PIPELINE_VERSION = "frozen-test-v2-pipeline/1.0.0"
BENCHMARK_VERSION = "frozen-test-v2"

__all__ = ["PIPELINE_VERSION", "BENCHMARK_VERSION"]

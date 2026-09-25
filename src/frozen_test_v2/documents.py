"""Loading, hashing, and deterministic serialization of pipeline documents.

A document that is not strict JSON is never repaired silently. With
``tolerate_leading_prose`` the loader extracts the JSON object that follows
any leading prose and records a :class:`SourceDefect` that travels into the
worksheet and the lock manifest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class DocumentFormatError(ValueError):
    """A document could not be parsed as the expected JSON payload."""


@dataclass(frozen=True)
class SourceDefect:
    kind: str
    detail: str
    byte_offset: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "detail": self.detail, "byte_offset": self.byte_offset}


@dataclass(frozen=True)
class LoadedDocument:
    path: str
    data: Any
    sha256: str
    size_bytes: int
    payload_sha256: str
    defects: tuple[SourceDefect, ...] = ()

    def to_manifest_entry(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "payload_sha256": self.payload_sha256,
            "source_defects": [defect.to_dict() for defect in self.defects],
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def canonical_json(data: Any, *, indent: int | None = 2) -> str:
    return json.dumps(data, indent=indent, sort_keys=True, ensure_ascii=False) + "\n"


def jsonl_line(record: Any) -> str:
    return json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def parse_json_payload(text: str, *, tolerate_leading_prose: bool = False
                       ) -> tuple[Any, str, tuple[SourceDefect, ...]]:
    """Parse ``text``; return ``(value, payload_text, defects)``."""
    try:
        return json.loads(text), text, ()
    except json.JSONDecodeError as exc:
        first_error = exc
    if not tolerate_leading_prose:
        raise DocumentFormatError(
            f"not valid JSON ({first_error.msg} at line {first_error.lineno}); if prose "
            "precedes the JSON payload, rerun with tolerate_leading_prose so the defect "
            "is recorded instead of ignored")
    decoder = json.JSONDecoder()
    search_from = 0
    while True:
        start = text.find("{", search_from)
        if start < 0:
            raise DocumentFormatError("no JSON object payload found in the document")
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            search_from = start + 1
            continue
        if isinstance(value, dict):
            break
        search_from = start + 1
    if text[end:].strip():
        raise DocumentFormatError(
            "content follows the JSON payload; refusing to guess which part is the document")
    prose = text[:start]
    preview = " ".join(prose.split())[:160]
    defect = SourceDefect(
        kind="leading_prose",
        detail=(f"{len(prose)} characters of non-JSON text precede the payload: "
                f"{preview!r}"),
        byte_offset=len(prose.encode("utf-8")),
    )
    return value, text[start:end], (defect,)


def load_json_document(path: str | Path, *, tolerate_leading_prose: bool = False
                       ) -> LoadedDocument:
    path = Path(path)
    if not path.is_file():
        raise DocumentFormatError(f"{path}: file not found")
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    try:
        data, payload, defects = parse_json_payload(
            text, tolerate_leading_prose=tolerate_leading_prose)
    except DocumentFormatError as exc:
        raise DocumentFormatError(f"{path}: {exc}") from exc
    return LoadedDocument(
        path=str(path),
        data=data,
        sha256=sha256_bytes(raw),
        size_bytes=len(raw),
        payload_sha256=sha256_text(payload),
        defects=defects,
    )


def document_from_data(data: Any, path: str = "<memory>") -> LoadedDocument:
    """Wrap an in-memory object as a document (hashes its canonical serialization)."""
    payload = canonical_json(data)
    digest = sha256_text(payload)
    return LoadedDocument(path=path, data=data, sha256=digest,
                          size_bytes=len(payload.encode("utf-8")), payload_sha256=digest)


def write_text_exclusive(path: str | Path, text: str) -> None:
    """Create ``path`` and write ``text``; fail if the file already exists."""
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write_text(path: str | Path, text: str, *, overwrite: bool = False) -> None:
    if overwrite:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    else:
        write_text_exclusive(path, text)


def write_json(path: str | Path, data: Any, *, overwrite: bool = False) -> None:
    write_text(path, canonical_json(data), overwrite=overwrite)


def jsonl_text(records: Iterable[Any]) -> str:
    lines = [jsonl_line(record) for record in records]
    return "\n".join(lines) + ("\n" if lines else "")


def write_jsonl(path: str | Path, records: Iterable[Any], *, overwrite: bool = False) -> None:
    write_text(path, jsonl_text(records), overwrite=overwrite)


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DocumentFormatError(f"{path}:{number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise DocumentFormatError(f"{path}:{number}: record must be an object")
        records.append(value)
    return records


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

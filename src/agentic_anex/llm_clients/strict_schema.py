"""Rewrite a JSON Schema into the subset OpenAI strict structured output accepts.

The agent's decision schema is written for validation: it carries bounds,
defaults, and ``const`` values that make it precise and that Ollama enforces
directly as a generation grammar. OpenAI's strict structured-output mode accepts
a narrower subset, and rejects the whole request rather than ignoring what it
does not support. Without this adapter every request silently degrades to
free-form ``json_object`` mode, which is how an agent ends up inventing field
names for a schema it was never shown.

The rewrite is deliberately lossy in one direction only: it removes constraints
the strict subset cannot express, and never adds or relaxes semantics that the
Python-side validators do not re-check. Every constraint dropped here is still
enforced when the response is parsed, so the adapter cannot let an invalid
decision through --- it can only cost the model the guidance the constraint gave.

Rules applied:

* keywords the strict subset rejects are dropped (bounds, lengths, defaults,
  ``uniqueItems``, ``pattern``, ``format``, ``$schema``);
* ``const: X`` becomes ``enum: [X]`` with an explicit ``type``, because the
  strict subset requires a ``type`` on every subschema;
* every object lists all of its properties in ``required`` and sets
  ``additionalProperties: false``, because the strict subset forbids optional
  properties;
* a property that was optional before the rewrite is made nullable, so that
  "absent" remains expressible as ``null``.
"""

from __future__ import annotations

from typing import Any, Mapping

UNSUPPORTED_KEYWORDS = frozenset({
    "$schema", "default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "pattern", "format", "minItems", "maxItems",
    "uniqueItems", "multipleOf", "contentEncoding", "contentMediaType",
})

_JSON_TYPE_NAMES: tuple[tuple[type, str], ...] = (
    (bool, "boolean"), (int, "integer"), (float, "number"),
    (str, "string"), (type(None), "null"),
)


def _type_name(value: Any) -> str | None:
    for python_type, name in _JSON_TYPE_NAMES:
        if isinstance(value, python_type):
            return name
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return None


def _make_nullable(node: dict[str, Any]) -> dict[str, Any]:
    """Allow null, so a property that used to be omissible stays expressible."""
    declared = node.get("type")
    if isinstance(declared, str):
        node["type"] = [declared, "null"]
    elif isinstance(declared, list):
        if "null" not in declared:
            node["type"] = [*declared, "null"]
    if isinstance(node.get("enum"), list) and None not in node["enum"]:
        node["enum"] = [*node["enum"], None]
    return node


def _rewrite(node: Any) -> Any:
    if isinstance(node, list):
        return [_rewrite(item) for item in node]
    if not isinstance(node, Mapping):
        return node

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in UNSUPPORTED_KEYWORDS:
            continue
        if key in ("properties", "$defs", "definitions"):
            out[key] = {name: _rewrite(sub) for name, sub in value.items()}
        elif key in ("items", "additionalProperties", "not"):
            out[key] = _rewrite(value)
        elif key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            out[key] = [_rewrite(sub) for sub in value]
        else:
            out[key] = value

    if "const" in out:
        constant = out.pop("const")
        out["enum"] = [constant]
        if "type" not in out:
            name = _type_name(constant)
            if name is not None:
                out["type"] = name
    if "enum" in out and "type" not in out:
        names = {_type_name(item) for item in out["enum"]} - {None}
        if len(names) == 1:
            out["type"] = names.pop()

    properties = out.get("properties")
    if isinstance(properties, dict):
        previously_required = set(node.get("required") or ())
        for name, sub in properties.items():
            if name not in previously_required and isinstance(sub, dict):
                properties[name] = _make_nullable(sub)
        out["required"] = list(properties)
        out["additionalProperties"] = False
    return out


def to_openai_strict(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of ``schema`` acceptable to OpenAI strict structured output."""
    rewritten = _rewrite(schema)
    if not isinstance(rewritten, dict):
        raise TypeError("a JSON Schema document must be an object")
    return rewritten


__all__ = ["to_openai_strict", "UNSUPPORTED_KEYWORDS"]

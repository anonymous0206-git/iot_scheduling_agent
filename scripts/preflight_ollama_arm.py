#!/usr/bin/env python3
"""Check which device Ollama will serve an arm on, before timing anything.

The companion to `preflight_openai_arm.py`, for the local arms. It exists
because of a failure this project has already had twice: the Ollama server
decides at startup whether it can see the GPU, and when discovery fails it
does not error --- it reports `total_vram=0 B` and serves the model entirely
on CPU, at roughly a sixteenth of the token rate. Every answer is still
correct, so the run looks fine and only the wall-clock numbers are ruined.
Nothing in the ledger records the device, so the damage is invisible
afterwards.

What it reports, all of it from `/api/ps` after ensuring the model is loaded:

  * the fraction of the model resident in VRAM, which is the actual question;
  * the model digest, because an Ollama tag is mutable and a digest is not;
  * the quantization level and parameter size, which the paper has to state;
  * the server version and the context length actually in force.

Exit status is the point: non-zero unless the model is fully on the GPU, so a
campaign driver can refuse to start a timed run on a CPU-served model rather
than discovering it afterwards. `--allow-cpu` overrides, and says so in the
output, for the case where a CPU run is deliberate.

    preflight_ollama_arm.py --model phi4:14b --json-out run_device.json
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_HOST = "http://localhost:11434"
# A load can take minutes from cold, and on CPU it takes longer than on GPU,
# so the timeout has to tolerate the slow case it exists to detect.
LOAD_TIMEOUT_SECONDS = 600.0


class PreflightError(RuntimeError):
    """The server could not be asked what it is doing."""


def _get(host: str, path: str, timeout: float) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(f"{host}{path}", timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PreflightError(f"cannot reach {host}{path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PreflightError(f"{host}{path} did not return JSON: {exc}") from exc


def _post(host: str, path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(f"{host}{path}", data=body,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PreflightError(f"cannot reach {host}{path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PreflightError(f"{host}{path} did not return JSON: {exc}") from exc


def loaded_model(host: str, model: str, timeout: float) -> dict[str, Any] | None:
    for entry in _get(host, "/api/ps", timeout).get("models", []):
        if entry.get("model") == model or entry.get("name") == model:
            return entry
    return None


def ensure_loaded(host: str, model: str, timeout: float) -> dict[str, Any]:
    """Load the model if it is not resident, then report how it was loaded.

    The device is chosen when the model is loaded, so asking about a model
    that is not loaded answers nothing. A one-token generation is the cheapest
    way to make the server commit.
    """
    entry = loaded_model(host, model, timeout=10.0)
    if entry is not None:
        return entry
    _post(host, "/api/generate",
          {"model": model, "prompt": "ok", "stream": False,
           "options": {"num_predict": 1}}, LOAD_TIMEOUT_SECONDS)
    entry = loaded_model(host, model, timeout=10.0)
    if entry is None:
        raise PreflightError(f"{model} is not resident even after a load request")
    return entry


def describe(host: str, model: str, timeout: float) -> dict[str, Any]:
    version = _get(host, "/api/version", timeout).get("version")
    entry = ensure_loaded(host, model, timeout)
    size = int(entry.get("size") or 0)
    in_vram = int(entry.get("size_vram") or 0)
    fraction = (in_vram / size) if size else 0.0
    details = entry.get("details") or {}
    if fraction >= 0.999:
        device = "gpu"
    elif fraction <= 0.001:
        device = "cpu"
    else:
        device = "split"
    return {
        "preflight_format": "agentic_anex.ollama_preflight.v1",
        "host": host,
        "server_version": version,
        "model": entry.get("model") or entry.get("name"),
        # A tag is mutable; the digest is what was actually served.
        "digest": entry.get("digest"),
        "parameter_size": details.get("parameter_size"),
        "quantization_level": details.get("quantization_level"),
        "context_length": entry.get("context_length"),
        "size_bytes": size,
        "size_vram_bytes": in_vram,
        "vram_fraction": round(fraction, 4),
        "serving_device": device,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument("--allow-cpu", action="store_true",
                        help="succeed even if the model is not on the GPU; the report "
                             "still records the device, so a deliberate CPU run stays "
                             "distinguishable from an accidental one")
    parser.add_argument("--json-out", help="write the report here, to be kept with the "
                                           "ledger it certifies")
    args = parser.parse_args()

    try:
        report = describe(args.host, args.model, args.timeout_seconds)
    except PreflightError as exc:
        print(json.dumps({"status": "refused", "problems": [str(exc)]}, indent=2))
        return 1

    acceptable = report["serving_device"] == "gpu" or args.allow_cpu
    report["status"] = "ready" if acceptable else "refused"
    if not acceptable:
        report["problems"] = [
            f"{report['model']} is served on {report['serving_device']} "
            f"({report['vram_fraction']:.1%} of {report['size_bytes']} bytes in VRAM). "
            "Timings from this server are not comparable with GPU-served runs. "
            "Restart the Ollama server so it retries GPU discovery, or pass "
            "--allow-cpu if a CPU run is intended."
        ]
    if args.allow_cpu and report["serving_device"] != "gpu":
        report["warning"] = ("proceeding on a non-GPU device because --allow-cpu was "
                             "given; do not compare these timings with GPU runs")
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if acceptable else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Exercise an installed or frozen product using temporary data only."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from importlib.resources import files
from pathlib import Path

REQUIRED_CHECKS = (
    "events",
    "imported",
    "edited",
    "tags_written",
    "nfo_written",
    "cover_written",
    "albums_viewed",
    "artists_viewed",
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-test", action="store_true", required=True)
    parser.add_argument("--report", type=Path, required=True, help="Write the JSON result here.")
    parser.add_argument("--platform", default="offscreen", help="Qt backend to verify.")
    args = parser.parse_args(argv)
    report: dict[str, object] = {"frozen": bool(getattr(sys, "frozen", False))}
    status = 1
    try:
        resources = files("trackfolio.resources")
        assets = json.loads(resources.joinpath("manifest.json").read_text(encoding="utf-8"))
        for name, digest in assets["sha256"].items():
            if hashlib.sha256(resources.joinpath(name).read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"Resource hash mismatch: {name}")
        report["resources_verified"] = True
        from trackfolio.interfaces.gui.probe import run_probe

        report.update(run_probe(["-platform", args.platform]))
        missing = [key for key in REQUIRED_CHECKS if report.get(key) is not True]
        if missing:
            raise RuntimeError(f"Unverified product checks: {', '.join(missing)}")
        if report.get("style") != "fusion" or report.get("platform") != args.platform:
            raise RuntimeError("The requested Qt backend and Fusion style were not verified.")
        status = 0
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return status

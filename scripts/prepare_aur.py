"""Render an AUR recipe pinned to a verified release archive."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(version: str, archive: Path, destination: Path) -> None:
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("Expected a release version such as 0.1.0, without v.")
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    template = ROOT / "packaging" / "aur"
    recipe = (template / "PKGBUILD").read_text(encoding="utf-8")
    recipe = re.sub(r"^pkgver=.*$", f"pkgver={version}", recipe, flags=re.MULTILINE)
    recipe = recipe.replace("0" * 64, digest)
    destination.mkdir(parents=True, exist_ok=True)
    for name, token in (
        ("trackfolio.desktop", "@DESKTOP_SHA256@"),
        ("trackfolio.svg", "@ICON_SHA256@"),
    ):
        source = template / name
        recipe = recipe.replace(token, hashlib.sha256(source.read_bytes()).hexdigest())
        shutil.copyfile(source, destination / name)
    (destination / "PKGBUILD").write_text(recipe, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.version, args.archive, args.output)


if __name__ == "__main__":
    main()

"""Local preferences; never store user data beside installed package code."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from platformdirs import user_config_path


class CatalogPreferences:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or user_config_path("Trackfolio", appauthor=False) / "settings.json"

    def last_catalog(self) -> Path | None:
        try:
            content = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return None
        value = content.get("last_catalog") if isinstance(content, dict) else None
        if isinstance(value, str) and value:
            candidate = Path(value).expanduser()
            if candidate.is_file():
                return candidate
        return None

    def remember(self, path: Path) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".settings-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(
                    {"last_catalog": str(path.resolve())}, stream, ensure_ascii=False, indent=2
                )
                stream.write("\n")
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

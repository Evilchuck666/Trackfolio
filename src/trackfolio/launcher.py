"""Qt-free entry point, including a useful message when the optional GUI is absent."""

from __future__ import annotations

import sys
from importlib.util import find_spec


def main() -> int:
    if find_spec("PySide6") is None:
        if sys.stderr is not None:
            print(
                "Falta la interfaz Qt. Ejecuta: uv sync --locked --extra gui --group dev",
                file=sys.stderr,
            )
        return 2
    from trackfolio.interfaces.gui.app import main as run_gui

    return run_gui()

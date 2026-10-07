"""Launch the catalog viewer with a configurable database and local preferences."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from trackfolio.infrastructure.preferences import CatalogPreferences
from trackfolio.interfaces.gui.lifecycle import dispose_window
from trackfolio.interfaces.gui.theme import apply_theme
from trackfolio.startup import create_window


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trackfolio · catálogo de música")
    parser.add_argument("--database", type=Path, help="Catálogo SQLite existente.")
    parser.add_argument("--no-restore", action="store_true", help="Iniciar sin restaurar catálogo.")
    args, qt_args = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    app = QApplication(["Trackfolio", *qt_args])
    app.setApplicationName("Trackfolio")
    app.setOrganizationName("Trackfolio")
    app.setApplicationVersion("0.1.0")
    apply_theme(app)
    preferences = CatalogPreferences()
    window, controller = create_window(preferences)
    app.aboutToQuit.connect(controller.shutdown)
    window.show()
    database = args.database or (None if args.no_restore else preferences.last_catalog())
    if database is not None:
        QTimer.singleShot(0, lambda: controller.open_database(database))
    try:
        return app.exec()
    finally:
        controller.shutdown()
        dispose_window(window)

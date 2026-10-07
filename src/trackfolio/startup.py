"""Composition root: bind read-only infrastructure to interface-independent use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trackfolio.infrastructure.preferences import CatalogPreferences
    from trackfolio.interfaces.gui.controller import CatalogController
    from trackfolio.interfaces.gui.window import MainWindow


def create_window(
    preferences: CatalogPreferences | None = None,
) -> tuple[MainWindow, CatalogController]:
    from trackfolio.infrastructure.session import open_catalog
    from trackfolio.interfaces.gui.controller import CatalogController
    from trackfolio.interfaces.gui.window import MainWindow

    window = MainWindow()
    controller = CatalogController(
        window, open_catalog, preferences.remember if preferences is not None else None
    )
    return window, controller

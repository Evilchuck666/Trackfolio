"""Compose catalog queries, import and editing operations for the GUI."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trackfolio.infrastructure.preferences import CatalogPreferences
    from trackfolio.interfaces.gui.controller import CatalogController
    from trackfolio.interfaces.gui.window import MainWindow


def create_window(
    preferences: CatalogPreferences | None = None,
) -> tuple[MainWindow, CatalogController]:
    from platformdirs import user_data_path

    from trackfolio.application.import_catalog import ImportCatalog
    from trackfolio.infrastructure.audio_scan import FileSystemAudioScanner
    from trackfolio.infrastructure.catalog_edit import SqliteCatalogEditSessionFactory
    from trackfolio.infrastructure.import_target import SqliteImportTargetFactory
    from trackfolio.infrastructure.metadata import read_metadata
    from trackfolio.infrastructure.session import open_catalog
    from trackfolio.interfaces.gui.controller import CatalogController
    from trackfolio.interfaces.gui.window import MainWindow

    window = MainWindow()
    previous = preferences.last_catalog() if preferences is not None else None
    directory = (
        previous.parent if previous is not None else user_data_path("Trackfolio", appauthor=False)
    )
    controller = CatalogController(
        window,
        open_catalog,
        preferences.remember if preferences is not None else None,
        importer=ImportCatalog(
            FileSystemAudioScanner(), read_metadata, SqliteImportTargetFactory()
        ),
        import_directory=directory,
        edit_factory=SqliteCatalogEditSessionFactory(),
    )
    return window, controller

"""Exercise the real product window with temporary data, independent of a checkout."""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer, qVersion
from PySide6.QtWidgets import QApplication

from trackfolio.domain.metadata import Artwork, TrackMetadata
from trackfolio.infrastructure.catalog import SqliteCatalogRepository
from trackfolio.infrastructure.database import create_engine, migrate_database
from trackfolio.interfaces.gui.lifecycle import dispose_window
from trackfolio.interfaces.gui.theme import apply_theme
from trackfolio.startup import create_window


def _image() -> bytes:
    # A tiny BMP created locally, without a GUI image dependency or music fixture.
    header = b"BM" + struct.pack("<IHHI", 58, 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 24, 0, 4, 2835, 2835, 0, 0)
    return header + dib + b"\xff\x80\x30\x00"


def run_probe(argv: list[str]) -> dict[str, object]:
    app = QApplication(["trackfolio-doctor", *argv])
    apply_theme(app)
    with tempfile.TemporaryDirectory(prefix="trackfolio-gui-") as directory:
        database = Path(directory) / "catálogo portable.tfo"
        migrate_database(database)
        engine = create_engine(database)
        try:
            repository = SqliteCatalogRepository(engine)
            entry = repository.save(
                TrackMetadata(
                    title="Canción de prueba",
                    album="Álbum de prueba",
                    album_year=2020,
                    artists=("Artista de prueba",),
                    genres=("Rock", "Jazz"),
                    track_number=3,
                    track_total=10,
                    disc_number=1,
                    disc_total=2,
                    lyrics="Texto inventado\nSegunda línea",
                    artwork=Artwork(_image(), "image/bmp", 1, 1),
                    audio_format="flac",
                ),
                Path(directory),
                "missing-source.flac",
            )
        finally:
            engine.dispose()
        window, controller = create_window()
        state: dict[str, object] = {"events": False, "failure": "La ventana no cargó el detalle."}

        def inspect_detail(file_id: int) -> None:
            expected = {
                "title": "Canción de prueba",
                "artists": "Artista de prueba",
                "album": "Álbum de prueba",
                "album_year": "2020",
                "track_number": "3",
                "track_total": "10",
                "disc_number": "1",
                "disc_total": "2",
                "genres": "Rock; Jazz",
            }
            try:
                assert file_id == entry.file_id
                assert window.isVisible()
                for key, value in expected.items():
                    assert window.fields[key].text() == value, key
                assert window.lyrics.toPlainText() == "Texto inventado\nSegunda línea"
                assert window.cover.pixmap() is not None and not window.cover.pixmap().isNull()
                state["events"] = True
                state["failure"] = ""
            except Exception as exc:
                state["failure"] = str(exc) or type(exc).__name__
            QTimer.singleShot(100, app.quit)

        controller.detail_loaded.connect(inspect_detail)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(app.quit)
        timeout.start(10000)
        window.show()
        QTimer.singleShot(0, lambda: controller.open_database(database))
        exit_code = app.exec()
        timeout.stop()
        controller.shutdown()
        dispose_window(window)
        if exit_code != 0 or not state["events"]:
            raise RuntimeError(str(state["failure"]))
        return {
            "platform": app.platformName(),
            "style": app.style().objectName(),
            "qt_version": qVersion(),
            "events": True,
        }

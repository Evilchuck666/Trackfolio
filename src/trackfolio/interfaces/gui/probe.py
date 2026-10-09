"""Exercise the real product window with temporary data, independent of a checkout."""

from __future__ import annotations

import binascii
import struct
import tempfile
import zlib
from pathlib import Path

from PySide6.QtCore import QTimer, qVersion

from trackfolio.application.import_catalog import ImportReport, ImportRequest
from trackfolio.interfaces.gui.app import CatalogApplication
from trackfolio.interfaces.gui.lifecycle import dispose_window
from trackfolio.interfaces.gui.theme import apply_theme
from trackfolio.startup import create_window


def _image() -> bytes:
    # A tiny BMP created locally, without a GUI image dependency or music fixture.
    header = b"BM" + struct.pack("<IHHI", 58, 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 24, 0, 4, 2835, 2835, 0, 0)
    return header + dib + b"\xff\x80\x30\x00"


def _audio_source(root: Path) -> Path:
    """A metadata-only FLAC exercises Mutagen and imports without external music."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", binascii.crc32(kind + payload))
        )

    image = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x80\x30"))
        + chunk(b"IEND", b"")
    )
    properties = (44100 << 44) | (1 << 41) | (15 << 36) | 88200
    stream_info = b"\x10\x00\x10\x00" + b"\x00" * 6 + properties.to_bytes(8, "big") + b"\x00" * 16
    tags = (
        ("TITLE", "Canción de prueba"),
        ("ALBUM", "Álbum de prueba"),
        ("DATE", "2020"),
        ("ARTIST", "Artista de prueba"),
        ("GENRE", "Rock"),
        ("GENRE", "Jazz"),
        ("TRACKNUMBER", "3/10"),
        ("DISCNUMBER", "1/2"),
        ("LYRICS", "Texto inventado\nSegunda línea"),
    )
    vendor = b"Trackfolio diagnostic"
    comments = struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", len(tags))
    for key, value in tags:
        encoded = f"{key}={value}".encode()
        comments += struct.pack("<I", len(encoded)) + encoded
    mime = b"image/png"
    picture = (
        struct.pack(">II", 3, len(mime))
        + mime
        + struct.pack(">I", 0)
        + struct.pack(">IIIII", 1, 1, 24, 0, len(image))
        + image
    )
    blocks = ((0, stream_info), (4, comments), (6, picture))
    content = b"fLaC"
    for index, (kind, payload) in enumerate(blocks):
        content += bytes([kind | (0x80 if index == len(blocks) - 1 else 0)])
        content += len(payload).to_bytes(3, "big") + payload
    source = root / "diagnostic.flac"
    source.write_bytes(content)
    return source


def run_probe(argv: list[str]) -> dict[str, object]:
    app = CatalogApplication(["trackfolio-doctor", *argv])
    apply_theme(app)
    with tempfile.TemporaryDirectory(prefix="trackfolio-gui-") as directory:
        database = Path(directory) / "catálogo portable.tfo"
        source = _audio_source(Path(directory))
        window, controller = create_window()
        app.close_guard = controller.request_close
        app.aboutToQuit.connect(controller.shutdown)
        state: dict[str, object] = {"events": False, "failure": "La ventana no cargó el detalle."}

        def inspect_import(report: ImportReport) -> None:
            if report.state != "completed" or report.created != 1 or report.failed:
                state["failure"] = report.fatal_error or "La importación de prueba falló."
                app.quit()
            else:
                source.unlink()
                state["imported"] = True

        controller.import_finished.connect(inspect_import)

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
                assert file_id > 0
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
        QTimer.singleShot(
            0, lambda: controller.start_import(ImportRequest(Path(directory), database, "create"))
        )
        exit_code = app.exec()
        timeout.stop()
        controller.shutdown()
        app.close_guard = None
        dispose_window(window)
        if exit_code != 0 or not state["events"]:
            raise RuntimeError(str(state["failure"]))
        return {
            "platform": app.platformName(),
            "style": app.style().objectName(),
            "qt_version": qVersion(),
            "events": True,
            "imported": bool(state.get("imported")),
        }

"""Exercise the real product window with temporary data, independent of a checkout."""

from __future__ import annotations

import binascii
import struct
import tempfile
import zlib
from pathlib import Path
from typing import Any, cast
from xml.etree import ElementTree

from mutagen.flac import FLAC
from PySide6.QtCore import Qt, QTimer, qVersion
from PySide6.QtTest import QTest

from trackfolio.application.edit_catalog import CatalogEditOutcome
from trackfolio.application.import_catalog import ImportReport, ImportRequest
from trackfolio.domain.tag_write import TagWriteReport
from trackfolio.infrastructure.metadata import read_metadata
from trackfolio.infrastructure.session import open_catalog
from trackfolio.interfaces.gui.app import CatalogApplication
from trackfolio.interfaces.gui.lifecycle import dispose_window
from trackfolio.interfaces.gui.theme import apply_theme
from trackfolio.startup import create_window


def _image() -> bytes:
    # A tiny BMP created locally, without a GUI image dependency or music fixture.
    header = b"BM" + struct.pack("<IHHI", 58, 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 24, 0, 4, 2835, 2835, 0, 0)
    return header + dib + b"\xff\x80\x30\x00"


def _png(color: bytes = b"\xff\x80\x30") -> bytes:
    """A complete one-pixel PNG for embedded and external cover checks."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", binascii.crc32(kind + payload))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" + color))
        + chunk(b"IEND", b"")
    )


def _audio_source(root: Path) -> Path:
    """A metadata-only FLAC exercises Mutagen without external music."""
    image = _png()
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
        window, controller = create_window(tag_journal_root=Path(directory) / "tag-writes")
        assert window.views.currentWidget() is window.album_view
        window.views.setCurrentWidget(window.splitter)
        app.close_guard = controller.request_close
        app.aboutToQuit.connect(controller.shutdown)
        state: dict[str, object] = {"events": False, "failure": "La ventana no cargó el detalle."}

        def fail(message: str) -> None:
            state["failure"] = message
            # A diagnostic failure must not display a pending-draft dialog unattended.
            app.close_guard = None
            app.quit()

        def inspect_import(report: ImportReport) -> None:
            if report.state != "completed" or report.created != 1 or report.failed:
                fail(report.fatal_error or "La importación de prueba falló.")
            else:
                source.unlink()
                state["imported"] = True

        controller.import_finished.connect(inspect_import)

        def request_edit() -> None:
            try:
                assert window.edit_button.isEnabled(), "El botón Editar no se habilitó."
                QTest.mouseClick(window.edit_button, Qt.MouseButton.LeftButton)
            except Exception as exc:
                fail(str(exc) or type(exc).__name__)

        def inspect_detail(file_id: int) -> None:
            if state.get("edited"):
                return
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
                state["failure"] = "La ventana no preparó la edición del catálogo."
                # detail_loaded fires before the controller restores idle actions.
                QTimer.singleShot(0, request_edit)
            except Exception as exc:
                fail(str(exc) or type(exc).__name__)

        controller.detail_loaded.connect(inspect_detail)

        def inspect_edit(file_id: int) -> None:
            try:
                assert file_id == window.current_file_id()
                assert not source.exists(), "La edición debe funcionar sin el archivo musical."
                assert not window.fields["title"].isReadOnly()
                assert not window.save_button.isEnabled()
                window.fields["title"].selectAll()
                QTest.keyClicks(window.fields["title"], "Catalog correction")
                artists = window.ordered_labels["artists"]
                artists.list.setCurrentRow(0)
                QTest.mouseClick(artists.remove_button, Qt.MouseButton.LeftButton)
                QTest.keyClicks(artists.name_edit, "Accept")
                QTest.mouseClick(artists.add_button, Qt.MouseButton.LeftButton)
                assert window.edit_dirty()
                assert window.save_button.isEnabled()
                state["failure"] = "La ventana no confirmó el guardado del catálogo."
                QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
            except Exception as exc:
                fail(str(exc) or type(exc).__name__)

        controller.edit_started.connect(inspect_edit)

        def inspect_saved(result: object) -> None:
            try:
                assert isinstance(result, CatalogEditOutcome), window.error_label.text()
                assert window.fields["title"].text() == "Catalog correction"
                assert window.fields["artists"].text() == "Accept"
                assert all(field.isReadOnly() for field in window.fields.values())
                assert window.lyrics.isReadOnly()
                assert not window.edit_dirty()
                assert window.model.data(window.model.index(0, 0)) == "Catalog correction"
                assert window.model.data(window.model.index(0, 1)) == "Accept"
                session = open_catalog(database)
                try:
                    stored = session.get(result.entry.file_id)
                    assert stored is not None
                    assert stored.metadata.title == "Catalog correction"
                    assert stored.metadata.artists == ("Accept",)
                    assert session.list_summaries() == window.model.summaries()
                    assert any(
                        tag.key.lower() == "title" and tag.value == "Canción de prueba"
                        for tag in stored.metadata.raw_tags
                    )
                    assert stored.metadata.artwork is not None
                finally:
                    session.close()
                state["edited"] = True
                state["failure"] = "La ventana no confirmó la escritura de etiquetas."
                _audio_source(Path(directory))
                (source.parent / "folder.png").write_bytes(_png(b"\x10\xee\x20"))
                (source.parent / "album.nfo").write_text(
                    '<?xml version="1.0" encoding="utf-8"?>\n'
                    "<album><title>Outdated</title><artist>Artista de prueba</artist>"
                    "<review>Keep this review</review>"
                    "<track><position>3</position><title>Canción de prueba</title>"
                    "<duration>0:02</duration></track></album>",
                    encoding="utf-8",
                )
                QTimer.singleShot(0, request_tags)
            except Exception as exc:
                fail(str(exc) or type(exc).__name__)

        controller.edit_finished.connect(inspect_saved)

        def request_tags() -> None:
            try:
                assert window.write_tags_button.isEnabled()
                QTest.mouseClick(window.write_tags_button, Qt.MouseButton.LeftButton)
                dialog = controller._tag_dialog
                assert dialog is not None
                assert dialog.table.rowCount() == 1
                QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
            except Exception as exc:
                fail(str(exc) or type(exc).__name__)

        def inspect_tags(report: TagWriteReport) -> None:
            try:
                assert len(report.results) == 1
                assert report.results[0].state == "confirmed", report.results[0].message
                assert report.results[0].backup_path is None
                assert not (source.parent / ".trackfolio-backups").exists()
                actual = read_metadata(source)
                assert actual.title == "Catalog correction" and actual.artists == ("Accept",)
                assert actual.artwork is not None
                selected_cover = _png(b"\x10\xee\x20")
                assert [(p.type, p.mime, p.data) for p in cast(Any, FLAC)(source).pictures] == [
                    (3, "image/png", selected_cover)
                ]
                assert actual.artwork.data == selected_cover
                assert report.results[0].cover_action == "replaced"
                session = open_catalog(database)
                try:
                    entry = session.get(report.results[0].file_id)
                    assert entry is not None and entry.metadata.artwork is not None
                    assert entry.metadata.artwork.data == selected_cover
                    assert entry.metadata.artwork.source == "embedded"
                finally:
                    session.close()
                assert len(report.nfo_results) == 1 and report.nfo_results[0].state == "updated", (
                    report
                )
                assert report.nfo_results[0].backup_path is None
                nfo = ElementTree.parse(source.parent / "album.nfo").getroot()
                assert nfo.findtext("title") == "Álbum de prueba", ElementTree.tostring(nfo)
                assert nfo.findtext("review") == "Keep this review"
                assert nfo.findtext("track/title") == "Catalog correction"
                assert nfo.findtext("track/duration") == "0:02"
                assert nfo.findtext("artist") == "Accept", ElementTree.tostring(nfo)
                assert nfo.find("albumArtistCredits") is None
                assert (
                    (source.parent / "album.nfo")
                    .read_text(encoding="utf-8")
                    .startswith('<?xml version="1.0" encoding="utf-8"?>\n<album>')
                )
                state["tags_written"] = True
                state["nfo_written"] = True
                state["cover_written"] = True
                state["failure"] = ""
                if controller._tag_dialog is not None:
                    controller._tag_dialog.reject()
                state["failure"] = "La vista de álbum no confirmó sus datos."
                QTimer.singleShot(0, request_albums)
            except Exception as exc:
                fail(str(exc) or type(exc).__name__)

        def request_albums() -> None:
            window.views.setCurrentWidget(window.album_view)
            QTimer.singleShot(20, inspect_albums)

        def inspect_albums() -> None:
            if controller._jobs:
                QTimer.singleShot(20, inspect_albums)
                return
            try:
                view = window.album_view
                assert view.list.count() == 1 and view.current_album is not None
                assert view.title.text() == "Álbum de prueba"
                assert view.table.rowCount() == 1
                title_cell, artist_cell = view.table.item(0, 2), view.table.item(0, 3)
                assert title_cell is not None and title_cell.text() == "Catalog correction"
                assert artist_cell is not None and artist_cell.text() == "Accept"
                assert view.cover.pixmap() is not None and not view.cover.pixmap().isNull()
                assert view.edit_button.isEnabled() and view.write_button.isEnabled()
                state["albums_viewed"] = True
                state["failure"] = ""
                app.quit()
            except Exception as exc:
                fail(str(exc) or type(exc).__name__)

        controller.tag_write_finished.connect(inspect_tags)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(lambda: fail(str(state["failure"])))
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
        if exit_code != 0 or not state["events"] or not state.get("albums_viewed"):
            raise RuntimeError(str(state["failure"]))
        return {
            "platform": app.platformName(),
            "style": app.style().objectName(),
            "qt_version": qVersion(),
            "events": True,
            "imported": bool(state.get("imported")),
            "edited": bool(state.get("edited")),
            "tags_written": bool(state.get("tags_written")),
            "nfo_written": bool(state.get("nfo_written")),
            "cover_written": bool(state.get("cover_written")),
            "albums_viewed": bool(state.get("albums_viewed")),
        }

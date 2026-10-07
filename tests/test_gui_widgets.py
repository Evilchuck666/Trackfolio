"""Exercise the real widgets with synthetic values and Qt's event tools."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import (  # noqa: E402
    QBuffer,
    QByteArray,
    QCoreApplication,
    QEvent,
    QIODevice,
    QModelIndex,
    QPointF,
    Qt,
)
from PySide6.QtGui import QGuiApplication, QImage, QMouseEvent  # noqa: E402
from PySide6.QtTest import QSignalSpy, QTest  # noqa: E402

from trackfolio.domain.catalog import CatalogEntry, CatalogSummary  # noqa: E402
from trackfolio.domain.metadata import Artwork, TrackMetadata  # noqa: E402
from trackfolio.interfaces.gui.catalog_model import CatalogTableModel  # noqa: E402
from trackfolio.interfaces.gui.window import MainWindow  # noqa: E402


@pytest.fixture
def window(qt_app):
    result = MainWindow()
    result.show()
    qt_app.processEvents()
    yield result
    result.close()
    result.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_app.processEvents()


def summary(file_id, *, title=None, artists=(), album=None, year=None):
    return CatalogSummary(file_id, file_id + 10, title, artists, album, year, f"{file_id}.flac")


def entry(metadata, file_id=1):
    # A display operation must not depend on this source path existing.
    return CatalogEntry(
        file_id, file_id + 10, Path("unavailable-library"), "missing.flac", metadata
    )


def png_bytes(width=120, height=60):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.darkCyan)
    data = QByteArray()
    buffer = QBuffer(data)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def wait_until(predicate):
    # Native compositors acknowledge window-state changes asynchronously.
    for _ in range(40):
        if predicate():
            return
        QTest.qWait(25)
    assert predicate()


def test_table_exposes_only_summary_values(qt_app):
    model = CatalogTableModel()
    model.set_summaries(
        (
            summary(8),
            summary(9, title="Árbol", artists=("Björk", "坂本"), album="Música", year=1981),
        )
    )
    assert model.rowCount() == 2
    assert model.columnCount() == 5
    assert [model.data(model.index(0, column)) for column in range(5)] == [
        "",
        "",
        "",
        "",
        "8.flac",
    ]
    assert [model.data(model.index(1, column)) for column in range(5)] == [
        "Árbol",
        "Björk; 坂本",
        "Música",
        "1981",
        "9.flac",
    ]
    assert model.data(model.index(1, 0), Qt.ItemDataRole.UserRole) == 9
    assert model.data(model.index(1, 4), Qt.ItemDataRole.ToolTipRole) == "9.flac"
    assert model.data(QModelIndex()) is None
    assert model.rowCount(model.index(1, 0)) == 0
    assert model.row_for_file(9) == 1
    assert model.row_for_file(99) is None
    assert model.file_id_at(-1) is None


def test_detail_renders_all_fields_as_read_only_plain_text(window):
    lyrics = "<b>Sin HTML</b>\nOtra línea: 坂本"
    window.set_detail(
        entry(
            TrackMetadata(
                title="Canción Ω",
                artists=("Accept", "Otro artista"),
                album="Breaker",
                album_year=1981,
                track_number=3,
                track_total=10,
                disc_number=1,
                disc_total=2,
                genres=("Heavy Metal", "Rock"),
                lyrics=lyrics,
                artwork=Artwork(png_bytes(), "image/png"),
            )
        )
    )
    assert {key: field.text() for key, field in window.fields.items()} == {
        "title": "Canción Ω",
        "artists": "Accept; Otro artista",
        "album": "Breaker",
        "album_year": "1981",
        "track_number": "3",
        "track_total": "10",
        "disc_number": "1",
        "disc_total": "2",
        "genres": "Heavy Metal; Rock",
    }
    assert all(field.isReadOnly() for field in window.fields.values())
    assert window.lyrics.isReadOnly()
    assert window.lyrics.toPlainText() == lyrics
    pixmap = window.cover.pixmap()
    assert not pixmap.isNull()
    assert pixmap.width() == 2 * pixmap.height()
    assert pixmap.deviceIndependentSize().width() <= window.cover.width()


def test_partial_detail_clears_previous_cover_lyrics_and_totals(window):
    window.set_detail(
        entry(
            TrackMetadata(
                title="Anterior",
                artists=("Artista",),
                album="Álbum",
                album_year=2000,
                track_number=4,
                track_total=8,
                disc_number=2,
                disc_total=2,
                genres=("Rock",),
                lyrics="Texto anterior",
                artwork=Artwork(png_bytes(), "image/png"),
            )
        )
    )
    window.set_detail(entry(TrackMetadata(track_number=3), file_id=2))
    assert window.fields["track_number"].text() == "3"
    assert all(field.text() == "" for key, field in window.fields.items() if key != "track_number")
    assert window.lyrics.toPlainText() == ""
    assert window.cover.pixmap().isNull()
    window.set_detail(None)
    assert all(field.text() == "" for field in window.fields.values())


def test_invalid_cover_leaves_other_metadata_available(window):
    window.set_detail(
        entry(TrackMetadata(title="Válida", artwork=Artwork(b"broken image", "image/jpeg")))
    )
    assert window.fields["title"].text() == "Válida"
    assert window.cover.pixmap().isNull()


def test_catalog_selects_first_and_preserves_id_after_refresh(window, qt_app):
    signals = QSignalSpy(window.track_selected)
    rows = (summary(3, title="Primera"), summary(7, title="Segunda"))
    window.set_catalog(Path("library.sqlite3"), rows)
    assert window.current_file_id() == 3
    assert signals.count() == 1 and signals.at(0) == [3]
    window.set_detail(entry(TrackMetadata(title="Primera"), file_id=3))
    window.table.setFocus()
    QTest.keyClick(window.table, Qt.Key.Key_Down)
    qt_app.processEvents()
    assert window.current_file_id() == 7
    assert signals.at(1) == [7]
    assert window.fields["title"].text() == ""
    window.set_catalog(Path("library.sqlite3"), tuple(reversed(rows)))
    assert window.current_file_id() == 7
    assert window.table.currentIndex().row() == 0
    assert signals.count() == 3 and signals.at(2) == [7]
    window.set_catalog(Path("other-library.sqlite3"), rows)
    assert window.current_file_id() == 3
    window.set_catalog(Path("library.sqlite3"), (rows[0],))
    assert window.current_file_id() == 3
    window.set_catalog(Path("empty.sqlite3"), ())
    assert window.current_file_id() is None
    assert window.count_label.text() == "0"
    assert all(field.text() == "" for field in window.fields.values())
    assert window.empty_label.isVisible()


def test_actions_errors_and_loading_remain_recoverable(window, qt_app):
    opened = QSignalSpy(window.open_requested)
    refreshed = QSignalSpy(window.refresh_requested)
    window.set_catalog(Path("library.sqlite3"), (summary(1),))
    window.set_busy(True)
    assert not window.refresh_button.isEnabled()
    assert window.open_button.isEnabled() and window.table.isEnabled()
    QTest.mouseClick(window.open_button, Qt.MouseButton.LeftButton)
    assert opened.count() == 1
    window.set_busy(False)
    QTest.mouseClick(window.refresh_button, Qt.MouseButton.LeftButton)
    assert refreshed.count() == 1
    window.set_error("No se pudo abrir <catálogo>.")
    assert window.error_label.isVisible()
    assert window.error_label.textFormat() == Qt.TextFormat.PlainText
    window.set_error("")
    assert window.error_label.isHidden()
    window.set_status("1 canción cargada.")
    assert window.status_label.text() == "1 canción cargada."
    window.set_catalog(None, ())
    assert not window.refresh_button.isEnabled()
    assert window.catalog_label.text() == "Sin catálogo"


def test_qt_title_controls_toggle_maximize_and_close(window, qt_app):
    closed = QSignalSpy(window.closing)
    QTest.mouseClick(window.title_bar.maximize_button, Qt.MouseButton.LeftButton)
    wait_until(window.isMaximized)
    assert window.title_bar.maximize_button.accessibleName() == "Restaurar"
    QTest.mouseClick(window.title_bar.maximize_button, Qt.MouseButton.LeftButton)
    wait_until(lambda: not window.isMaximized())
    assert window.title_bar.maximize_button.accessibleName() == "Maximizar"
    QTest.mouseClick(window.title_bar.close_button, Qt.MouseButton.LeftButton)
    assert closed.count() == 1


def test_failed_wayland_move_enables_system_frame(window, monkeypatch):
    class UnsupportedHandle:
        def startSystemMove(self):
            return False

    monkeypatch.setattr(window, "windowHandle", lambda: UnsupportedHandle())
    monkeypatch.setattr(QGuiApplication, "platformName", lambda: "wayland")
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(80, 20),
        QPointF(120, 80),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.title_bar.mousePressEvent(event)
    assert not window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.title_bar.isHidden()
    assert "marco" in window.status_label.text().lower()


def test_manual_resize_respects_minimum_size_when_system_operation_unavailable(window, monkeypatch):
    monkeypatch.setattr(window, "windowHandle", lambda: None)
    monkeypatch.setattr(QGuiApplication, "platformName", lambda: "offscreen")
    handle = window._handles[3]
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(2, 20),
        QPointF(1000, 100),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    handle.mousePressEvent(press)
    move = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(2, 20),
        QPointF(100, 100),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    handle.mouseMoveEvent(move)
    assert window.width() == window.minimumWidth()
